"""Concurrency tests: lock-free get() safety under concurrent access."""

from __future__ import annotations

import gc
import sys
import threading
from typing import TYPE_CHECKING

import pytest

from recharge import derived, dynamic_derived, effect, state
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
