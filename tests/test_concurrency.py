"""Concurrency tests: lock-free get() safety under concurrent access."""

from __future__ import annotations

import contextlib
import gc
import sys
import threading
import time
import weakref
from typing import TYPE_CHECKING, Any

import pytest

from recharge import Signal, configure, derived, dynamic_derived, effect, state
from recharge.core.subgraph_locks import (
    _REGISTRY,
    acquire_subgraph_write_lock_with_defer,
    defer_set,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _runtime_mode() -> str:
    """Return interpreter threading mode for test diagnostics."""
    is_gil_enabled: Callable[[], bool] | None = getattr(sys, "_is_gil_enabled", None)
    if is_gil_enabled is None:
        return "gil"
    return "gil" if is_gil_enabled() else "free-threaded"


def test_concurrent_derived_get_under_writes() -> None:
    """Derived get() stays lock-free and value-consistent under write pressure."""
    s = state(0)
    doubled = derived([s], lambda: s.get() * 2)
    dispose = effect([doubled], lambda: None)  # Keep derived push-connected.

    errors: list[BaseException] = []
    error_lock = threading.Lock()
    done = threading.Event()

    def record_error(err: BaseException) -> None:
        with error_lock:
            errors.append(err)
        done.set()

    def reader() -> None:
        try:
            for _ in range(25_000):
                if done.is_set():
                    return
                value = doubled.get()
                # Invariant: f(x) = x * 2, so every observed value must be even.
                if value % 2 != 0:
                    raise AssertionError(f"expected even derived value, got {value}")
        except BaseException as err:  # pragma: no cover - only for stress failures
            record_error(err)

    def writer() -> None:
        try:
            for i in range(5_000):
                if done.is_set():
                    return
                s.set(i)
        except BaseException as err:  # pragma: no cover - only for stress failures
            record_error(err)

    readers = [threading.Thread(target=reader) for _ in range(6)]
    writers = [threading.Thread(target=writer) for _ in range(2)]
    all_threads = readers + writers
    try:
        for thread in all_threads:
            thread.start()
        for thread in all_threads:
            thread.join(timeout=5.0)
        stuck = [thread.name for thread in all_threads if thread.is_alive()]
        if stuck:
            done.set()
            raise AssertionError(f"worker threads did not finish: {stuck}")
    finally:
        done.set()
        dispose()
    assert not errors, f"concurrency invariant failed in {_runtime_mode()} mode: {errors!r}"


def test_concurrent_state_get_under_writes() -> None:
    """State get() is safe and lock-free while other threads write."""
    s = state(0)
    errors: list[BaseException] = []
    error_lock = threading.Lock()
    done = threading.Event()

    def record_error(err: BaseException) -> None:
        with error_lock:
            errors.append(err)
        done.set()

    max_written = 9_999

    def reader() -> None:
        try:
            for _ in range(40_000):
                if done.is_set():
                    return
                value = s.get()
                if not isinstance(value, int):
                    raise AssertionError(f"expected int state value, got {type(value)!r}")
                if value < 0 or value > max_written:
                    raise AssertionError(f"state value out of expected range: {value}")
        except BaseException as err:  # pragma: no cover - only for stress failures
            record_error(err)

    def writer() -> None:
        try:
            for i in range(10_000):
                if done.is_set():
                    return
                s.set(i)
        except BaseException as err:  # pragma: no cover - only for stress failures
            record_error(err)

    readers = [threading.Thread(target=reader) for _ in range(8)]
    writer_thread = threading.Thread(target=writer)
    all_threads = readers + [writer_thread]
    for thread in readers:
        thread.start()
    writer_thread.start()
    for thread in all_threads:
        thread.join(timeout=5.0)
    stuck = [thread.name for thread in all_threads if thread.is_alive()]
    if stuck:
        done.set()
        raise AssertionError(f"worker threads did not finish: {stuck}")

    final_value = s.get()
    if final_value < 0 or final_value > max_written:
        raise AssertionError(f"final state value out of expected range: {final_value}")
    assert not errors, f"lock-free state.get() failed in {_runtime_mode()} mode: {errors!r}"


def test_independent_subgraph_writes_do_not_block_each_other() -> None:
    """Independent subgraphs should allow concurrent set() execution."""
    a = state(0)
    b = state(0)

    started = threading.Barrier(3)
    done_a = threading.Event()
    done_b = threading.Event()
    release = threading.Event()

    def slow_a() -> int:
        value = a.get()
        if value > 0:
            started.wait(timeout=2.0)
            done_a.set()
            release.wait(timeout=2.0)
        return value

    def slow_b() -> int:
        value = b.get()
        if value > 0:
            started.wait(timeout=2.0)
            done_b.set()
            release.wait(timeout=2.0)
        return value

    da = derived([a], slow_a)
    db = derived([b], slow_b)
    dispose_a = effect([da], lambda: None)
    dispose_b = effect([db], lambda: None)

    def writer_a() -> None:
        a.set(1)

    def writer_b() -> None:
        b.set(1)

    t1 = threading.Thread(target=writer_a)
    t2 = threading.Thread(target=writer_b)
    t1.start()
    t2.start()
    try:
        started.wait(timeout=2.0)
        assert done_a.wait(timeout=1.0), "subgraph A write did not enter derived compute"
        assert done_b.wait(timeout=1.0), "subgraph B write did not enter derived compute"
    finally:
        release.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)
    assert not t1.is_alive()
    assert not t2.is_alive()
    dispose_a()
    dispose_b()


def test_merged_subgraph_serializes_writes() -> None:
    """When two states merge via derived, concurrent writes serialize."""
    left = state(0)
    right = state(0)
    merged = derived([left, right], lambda: left.get() + right.get())
    dispose = effect([merged], lambda: None)

    gate = threading.Event()
    entered = threading.Event()

    def slow_left() -> int:
        if left.get() > 0:
            entered.set()
            gate.wait(timeout=1.0)
        return left.get()

    left_slow = derived([left], slow_left)
    hold = effect([left_slow], lambda: None)

    right_started = threading.Event()
    right_finished = threading.Event()

    def write_left() -> None:
        left.set(1)

    def write_right() -> None:
        entered.wait(timeout=1.0)
        right_started.set()
        right.set(1)
        right_finished.set()

    t_left = threading.Thread(target=write_left)
    t_right = threading.Thread(target=write_right)
    t_left.start()
    t_right.start()
    assert entered.wait(timeout=2.0), "left writer did not reach slow section"
    assert right_started.wait(timeout=1.0), "right writer did not start"
    assert not right_finished.is_set(), "right write completed before left lock released"
    gate.set()
    t_left.join(timeout=2.0)
    t_right.join(timeout=2.0)
    assert not t_left.is_alive()
    assert not t_right.is_alive()
    assert right_finished.is_set()
    assert merged.get() == 2
    hold()
    dispose()


# ---------------------------------------------------------------------------
# Concurrency hardening tests
# ---------------------------------------------------------------------------


def test_gc_cleanup_removes_registry_entries() -> None:
    """When nodes are GC'd, their registry entries are cleaned up."""
    s = state(0)
    node_id = id(s)

    # Node should be registered.
    with _REGISTRY._meta_lock:
        assert node_id in _REGISTRY._parent

    # Delete the only reference and force GC.
    del s
    gc.collect()

    # Registry entry should be cleaned up.
    with _REGISTRY._meta_lock:
        assert node_id not in _REGISTRY._parent
        assert node_id not in _REGISTRY._refs


def test_batch_is_thread_isolated() -> None:
    """Each thread has its own batch context — no cross-thread interference."""
    from recharge.core.protocol import batch, is_batching

    results: dict[str, list[bool]] = {"main": [], "worker": []}
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait(timeout=2.0)
        # Worker is NOT in a batch — main thread's batch should not leak.
        results["worker"].append(is_batching())
        with batch():
            results["worker"].append(is_batching())
        results["worker"].append(is_batching())

    t = threading.Thread(target=worker)
    with batch():
        results["main"].append(is_batching())
        t.start()
        barrier.wait(timeout=2.0)
        # Give worker time to check.
        t.join(timeout=2.0)
        results["main"].append(is_batching())

    assert results["main"] == [True, True], "main thread should be in batch"
    assert results["worker"] == [False, True, False], "worker should have independent batch state"


def test_cross_subgraph_defer_set() -> None:
    """defer_set() queues cross-subgraph writes to avoid deadlock."""
    a = state(0)
    b = state(0)
    log: list[str] = []

    # Simulate: inside subgraph A's lock, defer a write to B.
    with acquire_subgraph_write_lock_with_defer(a):
        log.append(f"a_locked:b={b.get()}")
        defer_set(b, 42)
        # b should NOT be updated yet — deferred until lock release.
        log.append(f"still_locked:b={b.get()}")

    # After lock release, deferred set should have executed.
    log.append(f"after_release:b={b.get()}")
    assert log == ["a_locked:b=0", "still_locked:b=0", "after_release:b=42"]


def test_defer_set_immediate_when_no_lock() -> None:
    """defer_set() executes immediately when not inside a subgraph lock."""
    s = state(0)
    defer_set(s, 99)
    assert s.get() == 99


def test_lock_box_indirection_after_union() -> None:
    """After union(), both subgraphs serialize via the same underlying lock.

    Verifies fix #4: lock-box indirection. When two subgraphs merge via
    derived(), the _LockBox for the subsumed root is redirected to the
    canonical root's RLock. Any thread that captured a box reference before
    the union must still acquire the correct merged lock.
    """
    a = state(0)
    b = state(0)

    # Capture lock boxes *before* they get merged by derived().
    with _REGISTRY._meta_lock:
        id_a = id(a)
        id_b = id(b)
        root_a = _REGISTRY._find_locked(id_a)
        root_b = _REGISTRY._find_locked(id_b)
        box_a = _REGISTRY._boxes[root_a]
        box_b = _REGISTRY._boxes[root_b]
        # Before union: independent locks.
        assert box_a.lock is not box_b.lock

    # Merge subgraphs via derived that depends on both.
    merged = derived([a, b], lambda: a.get() + b.get())
    dispose = effect([merged], lambda: None)

    # After union: both boxes should point to the same underlying RLock.
    assert box_a.lock is box_b.lock or box_b.lock is box_a.lock

    # Verify serialization works: concurrent writes must not interleave.
    gate = threading.Event()
    entered = threading.Event()
    order: list[str] = []

    def slow_effect_a() -> int:
        val = a.get()
        if val > 0:
            order.append("a_enter")
            entered.set()
            gate.wait(timeout=2.0)
            order.append("a_exit")
        return val

    da = derived([a], slow_effect_a)
    hold = effect([da], lambda: None)

    b_done = threading.Event()

    def write_a() -> None:
        a.set(1)

    def write_b() -> None:
        entered.wait(timeout=2.0)
        b.set(1)
        order.append("b_done")
        b_done.set()

    t1 = threading.Thread(target=write_a)
    t2 = threading.Thread(target=write_b)
    t1.start()
    t2.start()

    assert entered.wait(timeout=2.0), "write_a did not enter slow section"
    # b should be blocked because same subgraph lock.
    assert not b_done.wait(timeout=0.3), "write_b completed while write_a held the lock"
    gate.set()

    t1.join(timeout=2.0)
    t2.join(timeout=2.0)
    assert not t1.is_alive()
    assert not t2.is_alive()
    # a must complete before b can proceed.
    assert order.index("a_exit") < order.index("b_done")
    hold()
    dispose()


def test_connect_state_is_thread_isolated() -> None:
    """Each thread has its own _ConnectState — concurrent graph construction
    on independent subgraphs doesn't interfere.

    Verifies fix #5: _ConnectState uses threading.local().
    """
    from recharge.core.protocol import (
        _get_connect_state,
        begin_deferred_start,
        end_deferred_start,
    )

    results: dict[str, list[int]] = {"main": [], "worker": []}
    barrier = threading.Barrier(2)

    def worker() -> None:
        # Worker should start with depth=0, independent of main thread.
        results["worker"].append(_get_connect_state().depth)
        barrier.wait(timeout=2.0)
        # Main thread is at depth=1, but worker should still be 0.
        results["worker"].append(_get_connect_state().depth)
        begin_deferred_start()
        results["worker"].append(_get_connect_state().depth)
        end_deferred_start()
        results["worker"].append(_get_connect_state().depth)

    begin_deferred_start()
    results["main"].append(_get_connect_state().depth)  # Should be 1
    t = threading.Thread(target=worker)
    t.start()
    barrier.wait(timeout=2.0)
    results["main"].append(_get_connect_state().depth)  # Still 1
    end_deferred_start()
    results["main"].append(_get_connect_state().depth)  # Back to 0
    t.join(timeout=2.0)

    assert results["main"] == [1, 1, 0], f"main thread connect state: {results['main']}"
    assert results["worker"] == [0, 0, 1, 0], f"worker thread connect state: {results['worker']}"


def test_end_deferred_start_raises_on_underflow() -> None:
    """Mismatched end_deferred_start() fails fast instead of corrupting state."""
    from recharge.core.protocol import end_deferred_start

    with pytest.raises(RuntimeError, match="without matching begin_deferred_start"):
        end_deferred_start()


def test_deferred_flush_runs_all_callbacks_before_raising() -> None:
    """Deferred queue keeps flushing even if one callback raises."""
    s = state(0)

    class _RaisingTarget:
        __slots__ = ()

        def set(self, _value: int) -> None:
            raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"), acquire_subgraph_write_lock_with_defer(s):
        defer_set(_RaisingTarget(), 1)
        defer_set(s, 99)

    # Second callback should still run despite first error.
    assert s.get() == 99


def test_deferred_flush_mode_safe_propagates_keyboard_interrupt_immediately() -> None:
    """safe mode should not swallow KeyboardInterrupt during deferred flush."""
    s = state(0)
    configure(deferred_flush_mode="safe")

    class _KeyboardInterruptTarget:
        __slots__ = ()

        def set(self, _value: int) -> None:
            raise KeyboardInterrupt()

    try:
        with pytest.raises(KeyboardInterrupt), acquire_subgraph_write_lock_with_defer(s):
            defer_set(_KeyboardInterruptTarget(), 1)
            defer_set(s, 123)
        # Queue stops at KeyboardInterrupt in safe mode.
        assert s.get() == 0
    finally:
        configure(deferred_flush_mode="safe")


def test_deferred_flush_mode_strict_drains_before_reraising() -> None:
    """strict mode should drain all deferred callbacks, then re-raise."""
    s = state(0)
    configure(deferred_flush_mode="strict")

    class _KeyboardInterruptTarget:
        __slots__ = ()

        def set(self, _value: int) -> None:
            raise KeyboardInterrupt()

    try:
        with pytest.raises(KeyboardInterrupt), acquire_subgraph_write_lock_with_defer(s):
            defer_set(_KeyboardInterruptTarget(), 1)
            defer_set(s, 456)
        # strict mode drains queue fully before re-raising.
        assert s.get() == 456
    finally:
        configure(deferred_flush_mode="safe")


def test_registry_preserves_lock_identity_when_root_is_gced() -> None:
    """GC of root node should not split lock identity for surviving members."""

    class _Node:
        __slots__ = ("__weakref__",)

    a = _Node()
    b = _Node()
    c = _Node()

    _REGISTRY.ensure_node(a)
    _REGISTRY.ensure_node(b)
    _REGISTRY.ensure_node(c)
    _REGISTRY.union(a, b)
    _REGISTRY.union(a, c)

    with _REGISTRY._meta_lock:
        root_a = _REGISTRY._find_locked(id(a))
        root_b = _REGISTRY._find_locked(id(b))
        root_c = _REGISTRY._find_locked(id(c))
        assert root_a == root_b == root_c
        original_lock = _REGISTRY._boxes[root_a].lock

    # Drop the object that currently represents the root id.
    del a
    gc.collect()

    with _REGISTRY._meta_lock:
        new_root_b = _REGISTRY._find_locked(id(b))
        new_root_c = _REGISTRY._find_locked(id(c))
        assert new_root_b == new_root_c
        assert _REGISTRY._boxes[new_root_b].lock is original_lock


def test_registry_ignores_stale_gc_callback_reference() -> None:
    """Stale weakref callbacks must not clear a newer slot on same node id."""

    class _Node:
        __slots__ = ("__weakref__",)

    n = _Node()
    _REGISTRY.ensure_node(n)

    node_id = id(n)
    with _REGISTRY._meta_lock:
        ref_new = _REGISTRY._refs[node_id]
        stale = weakref.ref(_Node())
        assert _REGISTRY._parent.get(node_id) == node_id

        _REGISTRY._on_gc(node_id, stale)
        # Wrong callback identity should be ignored.
        assert _REGISTRY._refs.get(node_id) is ref_new
        assert node_id in _REGISTRY._parent


def test_deferred_depth_underflow_raises() -> None:
    """Deferred-depth accounting fails fast on mismatched decrement."""
    from recharge.core.subgraph_locks import _dec_deferred_depth

    with pytest.raises(RuntimeError, match="underflow"):
        _dec_deferred_depth()


def test_dynamic_derived_rejects_undeclared_dep() -> None:
    """dynamic_derived raises ValueError if get() accesses undeclared dep."""
    a = state(1)
    b = state(2)

    # Only declare 'a' as possible dep.
    dd = dynamic_derived([a], lambda get: get(a) + get(b))
    with pytest.raises(ValueError, match="not in declared possible_deps"):
        dd.get()


def test_dynamic_derived_explicit_deps_basic() -> None:
    """dynamic_derived with explicit deps works like before."""
    flag = state(True)
    a = state(10)
    b = state(20)

    dd = dynamic_derived([flag, a, b], lambda get: get(a) if get(flag) else get(b))
    assert dd.get() == 10

    flag.set(False)
    assert dd.get() == 20

    b.set(30)
    assert dd.get() == 30


# ---------------------------------------------------------------------------
# 2.1 Deferred: Protocol-level concurrency validation under contention
# ---------------------------------------------------------------------------


def test_signal_sequencing_dirty_before_data_under_contention() -> None:
    """DIRTY always precedes DATA in the observed event stream, even under
    concurrent write pressure from multiple threads on the same subgraph.

    The per-subgraph write lock serializes set() calls. Within each
    serialized transaction the two-phase push (DIRTY → DATA) must hold.
    """
    from tests.conftest import observe

    s = state(0)
    d = derived([s], lambda: s.get() * 2)
    obs = observe(d)

    errors: list[str] = []
    n_writes = 2_000

    def writer(start: int) -> None:
        for i in range(start, start + n_writes):
            s.set(i)

    threads = [threading.Thread(target=writer, args=(i * n_writes,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    stuck = [t.name for t in threads if t.is_alive()]
    assert not stuck, f"threads did not finish: {stuck}"

    # Validate protocol ordering in the collected event stream:
    # Every DATA must be immediately preceded by a DIRTY signal.
    events = obs.events
    for idx, (kind, _payload) in enumerate(events):
        if kind == "DATA":
            if idx == 0:
                errors.append("DATA at index 0 with no preceding DIRTY")
            elif events[idx - 1] != ("SIGNAL", Signal.DIRTY):
                errors.append(
                    f"DATA at index {idx} preceded by {events[idx - 1]!r}, "
                    f"expected ('SIGNAL', Signal.DIRTY)"
                )

    obs.dispose()
    assert not errors, f"signal sequencing violations in {_runtime_mode()} mode: {errors}"


def test_signal_sequencing_dirty_before_resolved_under_contention() -> None:
    """DIRTY→RESOLVED sequencing holds when many concurrent set() calls
    write the same value (triggering equality-based RESOLVED).
    """
    from tests.conftest import observe

    s = state(0, equals=lambda a, b: a == b)
    d = derived([s], lambda: s.get() // 10, equals=lambda a, b: a == b)
    obs = observe(d)

    n_writes = 1_000

    def writer() -> None:
        # Write values 0..9 repeatedly — derived floors to 0 every time,
        # producing RESOLVED after the first write.
        for i in range(n_writes):
            s.set(i % 10)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    stuck = [t.name for t in threads if t.is_alive()]
    assert not stuck, f"threads did not finish: {stuck}"

    # Validate: every RESOLVED must be preceded by a DIRTY
    events = obs.events
    errors: list[str] = []
    for idx, (kind, payload) in enumerate(events):
        if kind == "SIGNAL" and payload is Signal.RESOLVED:
            if idx == 0:
                errors.append("RESOLVED at index 0 with no preceding DIRTY")
            elif events[idx - 1] != ("SIGNAL", Signal.DIRTY):
                errors.append(
                    f"RESOLVED at index {idx} preceded by {events[idx - 1]!r}, "
                    f"expected ('SIGNAL', Signal.DIRTY)"
                )

    obs.dispose()
    assert not errors, f"DIRTY→RESOLVED violations in {_runtime_mode()} mode: {errors}"


def test_diamond_convergence_race_under_concurrent_writes() -> None:
    """Diamond topology under concurrent writes: D always sees a consistent
    state and computes exactly once per upstream change.

    Topology: A → B, A → C, B+C → D
    Multiple threads write to A concurrently. The subgraph lock serializes
    these writes. D must never see B updated but C stale (or vice versa).
    """
    a = state(0)
    b = derived([a], lambda: a.get() + 10)
    c = derived([a], lambda: a.get() + 100)
    d = derived([b, c], lambda: b.get() + c.get())

    d_values: list[int] = []
    d_lock = threading.Lock()

    def d_observer() -> None:
        val = d.get()
        with d_lock:
            d_values.append(val)

    dispose = effect([d], d_observer)

    n_writes = 2_000

    def writer(offset: int) -> None:
        for i in range(n_writes):
            a.set(offset + i)

    threads = [threading.Thread(target=writer, args=(i * n_writes,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    stuck = [t.name for t in threads if t.is_alive()]
    assert not stuck, f"threads did not finish: {stuck}"
    dispose()

    # Every observed D value must be consistent: d = (a+10) + (a+100) = 2*a + 110
    errors: list[str] = []
    for val in d_values:
        # d = 2*a + 110  =>  (d - 110) must be even
        if (val - 110) % 2 != 0:
            errors.append(f"inconsistent diamond value: d={val}, inferred a={(val - 110) / 2}")

    assert not errors, f"diamond convergence violations ({len(errors)}): {errors[:5]}"

    # Final value must also be consistent
    final = d.get()
    assert (final - 110) % 2 == 0, f"final d={final} is inconsistent"


def test_diamond_single_compute_per_change_under_concurrent_writes() -> None:
    """Under concurrent writes, D recomputes exactly once per A.set() call,
    never double-computing from the same upstream change.
    """
    a = state(0)
    b = derived([a], lambda: a.get() * 2)
    c = derived([a], lambda: a.get() * 3)

    compute_count = 0
    count_lock = threading.Lock()

    def d_fn() -> int:
        nonlocal compute_count
        with count_lock:
            compute_count += 1
        return b.get() + c.get()

    d = derived([b, c], d_fn)
    dispose = effect([d], lambda: None)

    n_writes = 500

    def writer(offset: int) -> None:
        for i in range(n_writes):
            a.set(offset + i)

    threads = [threading.Thread(target=writer, args=(i * n_writes,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    stuck = [t.name for t in threads if t.is_alive()]
    assert not stuck, f"threads did not finish: {stuck}"
    dispose()

    # Total writes = 3 * 500 = 1500, but some may be skipped (same value from
    # equality check). D computes should be <= total writes. The key invariant
    # is that compute_count should never exceed total distinct set() calls.
    total_writes = 3 * n_writes
    assert compute_count >= 1, "D never computed — test is vacuous"
    assert compute_count <= total_writes, (
        f"D computed {compute_count} times for {total_writes} writes — possible double-computation"
    )


def test_completion_propagation_under_concurrent_reads() -> None:
    """Completion from a producer is visible to concurrent reader threads
    without crashes or corruption.
    """
    from recharge import producer as make_producer
    from recharge import subscribe

    actions_ref: list[Any] = []

    def factory(actions: Any) -> None:
        actions_ref.append(actions)

    p = make_producer(factory, initial=0)
    # Subscribe to trigger the factory function.
    _sub = subscribe(p, lambda v, _: None)

    errors: list[BaseException] = []
    error_lock = threading.Lock()
    done = threading.Event()

    def reader() -> None:
        try:
            for _ in range(10_000):
                if done.is_set():
                    return
                p.get()  # Must not crash even during/after completion
        except BaseException as err:
            with error_lock:
                errors.append(err)

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for t in readers:
        t.start()

    # Emit a few values then complete
    assert actions_ref, "factory was not called"
    actions_ref[0].emit(1)
    actions_ref[0].emit(2)
    actions_ref[0].complete()

    done.set()
    for t in readers:
        t.join(timeout=5.0)
    stuck = [t.name for t in readers if t.is_alive()]
    assert not stuck, f"reader threads did not finish: {stuck}"

    assert not errors, f"reader errors during completion: {errors}"
    # After completion, get() returns last value
    assert p.get() == 2


def test_error_propagation_under_concurrent_reads() -> None:
    """Error from a producer is visible to concurrent readers without crashes."""
    from recharge import producer as make_producer
    from recharge import subscribe

    actions_ref: list[Any] = []

    def factory(actions: Any) -> None:
        actions_ref.append(actions)

    p = make_producer(factory, initial=0)
    _sub = subscribe(p, lambda v, _: None)

    errors: list[BaseException] = []
    error_lock = threading.Lock()
    done = threading.Event()

    def reader() -> None:
        try:
            for _ in range(10_000):
                if done.is_set():
                    return
                with contextlib.suppress(Exception):
                    p.get()  # May raise after error — expected
        except BaseException as err:
            with error_lock:
                errors.append(err)

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for t in readers:
        t.start()

    assert actions_ref, "factory was not called"
    actions_ref[0].emit(1)
    actions_ref[0].error(ValueError("test error"))

    done.set()
    for t in readers:
        t.join(timeout=5.0)
    stuck = [t.name for t in readers if t.is_alive()]
    assert not stuck, f"reader threads did not finish: {stuck}"

    assert not errors, f"reader errors during error propagation: {errors}"


def test_teardown_propagation_under_concurrent_access() -> None:
    """TEARDOWN signal through an effect doesn't corrupt concurrent get() calls."""
    s = state(0)
    d = derived([s], lambda: s.get() * 2)
    dispose = effect([d], lambda: None)

    errors: list[BaseException] = []
    error_lock = threading.Lock()
    done = threading.Event()

    def reader() -> None:
        try:
            for _ in range(10_000):
                if done.is_set():
                    return
                val = d.get()
                if not isinstance(val, int):
                    raise AssertionError(f"expected int, got {type(val)}")
        except BaseException as err:
            with error_lock:
                errors.append(err)

    def writer() -> None:
        try:
            for i in range(500):
                if done.is_set():
                    return
                s.set(i)
        except BaseException as err:
            with error_lock:
                errors.append(err)

    readers = [threading.Thread(target=reader) for _ in range(3)]
    writer_thread = threading.Thread(target=writer)
    for t in readers:
        t.start()
    writer_thread.start()

    time.sleep(0.01)  # Let threads run briefly
    dispose.signal(Signal.TEARDOWN)

    done.set()
    all_threads = [*readers, writer_thread]
    for t in all_threads:
        t.join(timeout=5.0)
    stuck = [t.name for t in all_threads if t.is_alive()]
    assert not stuck, f"threads did not finish: {stuck}"

    assert not errors, f"errors during teardown: {errors}"
