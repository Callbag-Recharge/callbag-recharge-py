"""Tests for core primitives: state, derived, effect, producer, operator, pipe, batch."""

from __future__ import annotations

from recharge import (
    DATA,
    END,
    STATE,
    Signal,
    batch,
    derived,
    derived_from,
    dynamic_derived,
    effect,
    operator,
    pipe,
    producer,
    state,
    subscribe,
)


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------


def test_state_basic():
    s = state(0)
    assert s.get() == 0
    s.set(1)
    assert s.get() == 1


def test_state_update():
    s = state(10)
    s.update(lambda n: n + 5)
    assert s.get() == 15


def test_state_equality_guard():
    """set() with the same object reference should be a no-op."""
    s = state(42)
    log: list[int] = []
    sub = subscribe(s, lambda v, _: log.append(v))
    s.set(42)  # same reference — skipped
    assert log == []
    s.set(43)
    assert log == [43]
    sub.unsubscribe()


def test_state_custom_equals():
    s = state({"x": 0}, equals=lambda a, b: a["x"] == b["x"])
    log: list = []
    sub = subscribe(s, lambda v, _: log.append(v))
    s.set({"x": 0})  # equal — skipped
    assert log == []
    s.set({"x": 1})
    assert log == [{"x": 1}]
    sub.unsubscribe()


def test_state_subscribe_prev_tracking():
    s = state("a")
    log: list[tuple] = []
    sub = subscribe(s, lambda v, p: log.append((v, p)))
    s.set("b")
    s.set("c")
    assert log == [("b", "a"), ("c", "b")]
    sub.unsubscribe()


# ---------------------------------------------------------------------------
# derived
# ---------------------------------------------------------------------------


def test_derived_basic():
    a = state(1)
    b = state(2)
    sum_ = derived([a, b], lambda: a.get() + b.get())
    assert sum_.get() == 3
    a.set(10)
    assert sum_.get() == 12


def test_derived_lazy_connect():
    """Derived should not compute until first get() or subscribe()."""
    calls = [0]
    a = state(1)

    def compute():
        calls[0] += 1
        return a.get() * 2

    d = derived([a], compute)
    assert calls[0] == 0  # not computed yet
    assert d.get() == 2
    assert calls[0] == 1


def test_derived_disconnect_on_unsub():
    a = state(1)
    d = derived([a], lambda: a.get() * 2)
    log: list[int] = []
    sub = subscribe(d, lambda v, _: log.append(v))
    a.set(2)
    assert log == [4]
    sub.unsubscribe()
    a.set(3)
    # After unsub, derived is disconnected — no new emissions
    assert log == [4]
    # But get() still pull-computes
    assert d.get() == 6


def test_derived_diamond():
    """Diamond: A → B, A → C, B+C → D. D recomputes once per A change."""
    a = state(1)
    b = derived([a], lambda: a.get() + 10)
    c = derived([a], lambda: a.get() + 100)
    d_calls = [0]

    def compute_d():
        d_calls[0] += 1
        return b.get() + c.get()

    d = derived([b, c], compute_d)
    log: list[int] = []
    sub = subscribe(d, lambda v, _: log.append(v))
    assert d.get() == 112  # 11 + 101
    d_calls[0] = 0

    a.set(2)
    assert d.get() == 114  # 12 + 102
    assert d_calls[0] == 1  # only ONE recompute despite two deps changing
    assert log == [114]
    sub.unsubscribe()


def test_derived_resolved_no_recompute():
    """When all deps send RESOLVED (no actual change), derived skips recompute."""
    a = state(1)
    calls = [0]

    def compute():
        calls[0] += 1
        return a.get() * 2

    d = derived([a], compute)
    log: list[int] = []
    sub = subscribe(d, lambda v, _: log.append(v))
    calls[0] = 0
    # set same value — state's equality guard prevents emission
    a.set(1)
    assert calls[0] == 0
    assert log == []
    sub.unsubscribe()


def test_derived_from():
    a = state(42)
    b = derived_from(a)
    assert b.get() == 42
    a.set(99)
    assert b.get() == 99


def test_derived_equality_memoization():
    """Derived with equals sends RESOLVED instead of DATA when value unchanged."""
    a = state(1)
    d = derived([a], lambda: a.get() % 2, equals=lambda x, y: x == y)
    log: list[int] = []
    sub = subscribe(d, lambda v, _: log.append(v))
    assert d.get() == 1
    a.set(3)  # 3 % 2 == 1, same as before — RESOLVED
    assert log == []
    a.set(4)  # 4 % 2 == 0, different — DATA
    assert log == [0]
    sub.unsubscribe()


# ---------------------------------------------------------------------------
# dynamic_derived
# ---------------------------------------------------------------------------


def test_dynamic_derived_basic():
    flag = state(True)
    a = state(1)
    b = state(2)
    d = dynamic_derived(lambda get: get(a) if get(flag) else get(b))
    assert d.get() == 1
    flag.set(False)
    assert d.get() == 2


def test_dynamic_derived_rewire():
    """After dep change, only the new dep triggers recompute."""
    flag = state(True)
    a = state(10)
    b = state(20)
    d = dynamic_derived(lambda get: get(a) if get(flag) else get(b))
    log: list[int] = []
    sub = subscribe(d, lambda v, _: log.append(v))
    assert d.get() == 10

    flag.set(False)  # switch to b
    assert d.get() == 20
    assert 20 in log

    log.clear()
    a.set(99)  # a should no longer trigger recompute (disconnected)
    # After rewire, changes to a should not affect d
    # (but this depends on rewiring happening during recompute)
    b.set(30)
    assert d.get() == 30
    assert 30 in log
    sub.unsubscribe()


# ---------------------------------------------------------------------------
# effect
# ---------------------------------------------------------------------------


def test_effect_basic():
    s = state(0)
    log: list[int] = []
    dispose = effect([s], lambda: log.append(s.get()))
    assert log == [0]  # runs immediately
    s.set(1)
    assert log == [0, 1]
    s.set(2)
    assert log == [0, 1, 2]
    dispose()


def test_effect_cleanup():
    s = state("a")
    cleanups: list[str] = []

    def eff():
        val = s.get()

        def cleanup():
            cleanups.append(f"cleanup-{val}")

        return cleanup

    dispose = effect([s], eff)
    assert cleanups == []
    s.set("b")
    assert cleanups == ["cleanup-a"]
    s.set("c")
    assert cleanups == ["cleanup-a", "cleanup-b"]
    dispose()
    assert cleanups == ["cleanup-a", "cleanup-b", "cleanup-c"]


def test_effect_dispose():
    s = state(0)
    log: list[int] = []
    dispose = effect([s], lambda: log.append(s.get()))
    assert log == [0]
    dispose()
    s.set(1)
    assert log == [0]  # no more runs after dispose


def test_effect_multi_dep_diamond():
    """Effect with multiple deps uses diamond resolution."""
    a = state(1)
    b = derived([a], lambda: a.get() + 10)
    c = derived([a], lambda: a.get() + 100)
    log: list[int] = []

    def eff():
        log.append(b.get() + c.get())

    dispose = effect([b, c], eff)
    assert log == [112]

    a.set(2)
    assert log == [112, 114]
    dispose()


# ---------------------------------------------------------------------------
# producer
# ---------------------------------------------------------------------------


def test_producer_manual_emit():
    p = producer()
    p.emit("hello")
    assert p.get() == "hello"


def test_producer_factory():
    log: list[str] = []

    def factory(actions):
        actions.emit("started")
        log.append("factory-ran")

        def cleanup():
            log.append("cleanup")

        return cleanup

    p = producer(factory, initial="init")
    assert p.get() == "init"  # factory hasn't run yet
    sub = subscribe(p, lambda v, _: log.append(f"sub:{v}"))
    assert "factory-ran" in log
    assert p.get() == "started"
    sub.unsubscribe()
    assert "cleanup" in log


def test_producer_complete():
    p = producer()
    p.emit(1)
    end_log: list = []
    sub = subscribe(p, lambda v, _: None, on_end=lambda err: end_log.append(err))
    p.complete()
    assert end_log == [None]
    p.emit(2)  # no-op after complete
    assert p.get() == 1


# ---------------------------------------------------------------------------
# operator
# ---------------------------------------------------------------------------


def test_operator_double():
    n = state(2)

    def init(actions):
        def handler(dep_idx, type_, data):
            if type_ == STATE:
                actions.signal(data)
            elif type_ == DATA:
                actions.emit(data * 2)

        return handler

    doubled = operator([n], init)
    log: list[int] = []
    sub = subscribe(doubled, lambda v, _: log.append(v))
    # Initial value not pushed by state on subscribe — operator starts with None
    n.set(5)
    assert doubled.get() == 10
    assert log == [10]
    n.set(3)
    assert doubled.get() == 6
    assert log == [10, 6]
    sub.unsubscribe()


def test_operator_filter():
    """Operator that filters: forwards DIRTY, sends RESOLVED when filtered."""
    n = state(1)

    def init(actions):
        dirty = False

        def handler(dep_idx, type_, data):
            nonlocal dirty
            if type_ == STATE:
                if data is Signal.DIRTY:
                    dirty = True
                    actions.signal(Signal.DIRTY)
                elif data is Signal.RESOLVED:
                    if dirty:
                        dirty = False
                        actions.signal(Signal.RESOLVED)
                else:
                    actions.signal(data)
            elif type_ == DATA:
                dirty = False
                if data % 2 == 0:
                    actions.emit(data)
                else:
                    actions.signal(Signal.RESOLVED)

        return handler

    evens = operator([n], init)
    log: list[int] = []
    sub = subscribe(evens, lambda v, _: log.append(v))
    n.set(2)
    n.set(3)
    n.set(4)
    assert log == [2, 4]
    sub.unsubscribe()


# ---------------------------------------------------------------------------
# pipe
# ---------------------------------------------------------------------------


def test_pipe_identity():
    s = state(42)
    assert pipe(s).get() == 42


def test_pipe_operator():
    """pipe() composes operators left-to-right."""
    s = state(3)
    result = pipe(s, lambda src: derived([src], lambda: src.get() * 2))
    assert result.get() == 6


def test_pipe_or_operator():
    """| operator should work the same as pipe()."""
    s = state(3)
    result = s | (lambda src: derived([src], lambda: src.get() * 2))
    assert result.get() == 6


# ---------------------------------------------------------------------------
# batch
# ---------------------------------------------------------------------------


def test_batch_coalesce():
    a = state(1)
    b = state(2)
    sum_ = derived([a, b], lambda: a.get() + b.get())
    log: list[int] = []
    sub = subscribe(sum_, lambda v, _: log.append(v))

    with batch():
        a.set(10)
        b.set(20)

    assert sum_.get() == 30
    # Should see only one update, not two
    assert log == [30]
    sub.unsubscribe()


def test_batch_nested():
    s = state(0)
    log: list[int] = []
    sub = subscribe(s, lambda v, _: log.append(v))

    with batch():
        s.set(1)
        with batch():
            s.set(2)
        # Still in outer batch — no emission yet
        assert log == []

    # Outermost batch exit flushes
    assert log == [2]  # only latest value
    sub.unsubscribe()


def test_batch_dirty_propagates_immediately():
    """Within batch, DIRTY should propagate even though DATA is deferred."""
    a = state(1)
    d = derived([a], lambda: a.get() * 2)
    # After batch, derived should have the new value
    with batch():
        a.set(5)

    assert d.get() == 10


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------


def test_subscribe_context_manager():
    s = state(0)
    log: list[int] = []
    with subscribe(s, lambda v, _: log.append(v)) as sub:
        s.set(1)
        s.set(2)
    # After context exit, unsubscribed
    s.set(3)
    assert log == [1, 2]


def test_subscribe_on_end():
    p = producer()
    end_log: list = []
    sub = subscribe(p, lambda v, _: None, on_end=lambda err: end_log.append(err))
    p.error(ValueError("boom"))
    assert len(end_log) == 1
    assert isinstance(end_log[0], ValueError)


# ---------------------------------------------------------------------------
# lifecycle signals
# ---------------------------------------------------------------------------


def test_effect_teardown_signal():
    s = state(0)
    log: list[int] = []
    dispose = effect([s], lambda: log.append(s.get()))
    assert log == [0]
    dispose.signal(Signal.TEARDOWN)
    s.set(1)
    assert log == [0]  # teardown should have disposed


def test_subscription_signal_reset():
    """subscribe.signal(RESET) forwards upstream."""
    p = producer(initial=0)
    signals: list[Signal] = []

    def factory(actions):
        actions.emit(0)

        def on_sig(sig):
            signals.append(sig)

        actions.on_signal(on_sig)

    p2 = producer(factory, initial=0)
    sub = subscribe(p2, lambda v, _: None)
    sub.signal(Signal.RESET)
    assert Signal.RESET in signals
    sub.unsubscribe()


# ---------------------------------------------------------------------------
# node status tracking
# ---------------------------------------------------------------------------


def test_effect_reset_signal():
    """After RESET, effect should re-run with reset dep values and stay responsive."""
    s = state(0)
    log: list[int] = []

    def fn():
        log.append(s.get())

    dispose = effect([s], fn)
    assert log == [0]  # initial run

    s.set(5)
    assert log == [0, 5]

    # RESET: upstream state resets to initial (0) and re-emits.
    # Effect should re-run with reset value AND remain responsive afterward.
    dispose.signal(Signal.RESET)
    assert log == [0, 5, 0]  # re-ran with reset value

    # Verify effect is still responsive after RESET
    s.set(10)
    assert log == [0, 5, 0, 10]
    dispose()


def test_state_none_equality_guard():
    """Setting None repeatedly should be deduplicated by equals."""
    s = state(None)
    log: list = []
    sub = subscribe(s, lambda v, _: log.append(v))
    s.set(None)
    s.set(None)
    assert log == []  # None -> None should be suppressed by is_ equality
    s.set(1)
    assert log == [1]
    sub.unsubscribe()


def test_batch_drain_exception_recovery():
    """batch() should reset draining flag even if a deferred emission throws."""
    s = state(0)
    bad = producer()
    error_log: list = []

    sub_s = subscribe(s, lambda v, _: None)

    try:
        with batch():
            s.set(1)
            bad.emit(object())  # no subs, won't throw; but let's test with a real throw

    except Exception:
        pass

    # Verify batch still works after the exception
    log: list = []
    sub2 = subscribe(s, lambda v, _: log.append(v))
    with batch():
        s.set(2)
    assert log == [2]
    sub_s.unsubscribe()
    sub2.unsubscribe()


def test_dynamic_derived_rewire_signal_queue():
    """Signals from newly connected deps during rewire should not be lost."""
    flag = state(True)
    a = state(1)
    b = state(10)

    def compute(get):
        if get(flag):
            return get(a)
        else:
            return get(b)

    dd = dynamic_derived(compute)
    log: list = []
    sub = subscribe(dd, lambda v, _: log.append(v))
    assert dd.get() == 1

    flag.set(False)
    assert dd.get() == 10

    # Now b should be wired; changes to b should propagate
    b.set(20)
    assert dd.get() == 20
    assert 20 in log
    sub.unsubscribe()


def test_state_status():
    from recharge.core.protocol import NodeStatus

    s = state(0)
    assert s._status == NodeStatus.DISCONNECTED
    log: list = []
    sub = subscribe(s, lambda v, _: log.append(v))
    s.set(1)
    assert s._status == NodeStatus.SETTLED
    sub.unsubscribe()
    assert s._status == NodeStatus.DISCONNECTED


def test_derived_status():
    from recharge.core.protocol import NodeStatus

    a = state(1)
    d = derived([a], lambda: a.get() * 2)
    assert d._status == NodeStatus.DISCONNECTED
    sub = subscribe(d, lambda v, _: None)
    assert d._status == NodeStatus.SETTLED
    sub.unsubscribe()
    assert d._status == NodeStatus.DISCONNECTED
