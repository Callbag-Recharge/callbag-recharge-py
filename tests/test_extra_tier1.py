"""Tests for Tier 1 extra operators: map, filter, scan, take, skip,
take_while, distinct_until_changed, merge, combine, zip, share, replay.
"""

from __future__ import annotations

from .conftest import observe

from recharge import Signal, derived, effect, operator, pipe, producer, state, subscribe
from recharge.core.protocol import batch
from recharge.extra import (
    combine,
    distinct_until_changed,
    filter,
    map,
    merge,
    replay,
    scan,
    share,
    skip,
    take,
    take_while,
    zip,
)


# ── map ──────────────────────────────────────────────────────────────


def test_map_basic():
    s = state(3)
    doubled = pipe(s, map(lambda x: x * 2))
    assert doubled.get() == 6
    s.set(5)
    assert doubled.get() == 10


def test_map_emits_on_change():
    s = state(1)
    m = pipe(s, map(lambda x: x + 10))
    obs = observe(m)
    s.set(2)
    s.set(3)
    assert obs.values == [12, 13]


def test_map_with_equals():
    s = state({"x": 1, "y": 2})
    x_only = pipe(s, map(lambda d: d["x"], equals=lambda a, b: a == b))
    obs = observe(x_only)
    s.set({"x": 1, "y": 99})  # x unchanged
    assert obs.resolved_count >= 1
    assert obs.values == []  # no new DATA


def test_map_state_forwarding():
    s = state(1)
    m = pipe(s, map(lambda x: x * 2))
    obs = observe(m)
    s.set(2)
    assert obs.dirty_count >= 1


def test_map_upstream_error():
    p = producer(lambda api: api.error(ValueError("boom")))
    m = pipe(p, map(lambda x: x))
    obs = observe(m)
    assert obs.errored
    assert isinstance(obs.end_error, ValueError)


def test_map_upstream_completion():
    p = producer(lambda api: api.complete())
    m = pipe(p, map(lambda x: x))
    obs = observe(m)
    assert obs.completed_cleanly


def test_map_diamond():
    a = state(1)
    b = pipe(a, map(lambda x: x * 2))
    c = pipe(a, map(lambda x: x + 10))
    d = derived([b, c], lambda: b.get() + c.get())
    d_count = [0]
    effect([d], lambda: d_count.__setitem__(0, d_count[0] + 1))
    # effect runs once on initial connect
    assert d_count[0] == 1
    a.set(5)
    assert d_count[0] == 2  # +1 from set (not +2 — diamond resolves once)
    assert d.get() == 25  # (5*2) + (5+10)


# ── filter ───────────────────────────────────────────────────────────


def test_filter_basic():
    s = state(0)
    evens = pipe(s, filter(lambda x: x % 2 == 0))
    obs = observe(evens)
    s.set(1)
    s.set(2)
    s.set(3)
    s.set(4)
    assert obs.values == [2, 4]


def test_filter_resolved_on_fail():
    s = state(0)
    evens = pipe(s, filter(lambda x: x % 2 == 0))
    obs = observe(evens)
    s.set(1)  # fails predicate
    assert obs.resolved_count >= 1


def test_filter_get_disconnected():
    s = state(5)
    pos = pipe(s, filter(lambda x: x > 0))
    assert pos.get() == 5
    s.set(-1)
    assert pos.get() == 5  # last passing


def test_filter_upstream_error():
    p = producer(lambda api: api.error(ValueError("fail")))
    f = pipe(p, filter(lambda x: True))
    obs = observe(f)
    assert obs.errored


def test_filter_upstream_completion():
    p = producer(lambda api: api.complete())
    f = pipe(p, filter(lambda x: True))
    obs = observe(f)
    assert obs.completed_cleanly


def test_filter_diamond():
    a = state(2)
    b = pipe(a, filter(lambda x: x % 2 == 0))
    c = pipe(a, map(lambda x: x + 100))
    d = derived([b, c], lambda: (b.get(), c.get()))
    d_count = [0]
    effect([d], lambda: d_count.__setitem__(0, d_count[0] + 1))
    assert d_count[0] == 1  # initial run
    a.set(4)
    assert d_count[0] == 2  # +1 (diamond resolves once)
    assert d.get() == (4, 104)


# ── scan ─────────────────────────────────────────────────────────────


def test_scan_basic():
    s = state(1)
    total = pipe(s, scan(lambda acc, x: acc + x, 0))
    obs = observe(total)
    s.set(2)
    s.set(3)
    assert obs.values == [2, 5]  # 0+2=2, 2+3=5


def test_scan_get_disconnected():
    s = state(10)
    total = pipe(s, scan(lambda acc, x: acc + x, 0))
    assert total.get() == 10  # seed(0) + 10


def test_scan_reset_on_reconnect():
    s = state(1)
    total = pipe(s, scan(lambda acc, x: acc + x, 0))
    obs = observe(total)
    s.set(2)
    s.set(3)
    assert obs.values == [2, 5]
    obs.reconnect()
    s.set(10)
    assert obs.values == [10]  # acc reset to seed


def test_scan_upstream_error():
    p = producer(lambda api: api.error(RuntimeError("oops")))
    sc = pipe(p, scan(lambda acc, x: acc + x, 0))
    obs = observe(sc)
    assert obs.errored


# ── take ─────────────────────────────────────────────────────────────


def test_take_basic():
    s = state(0)
    t = pipe(s, take(2))
    obs = observe(t)
    s.set(1)
    s.set(2)
    s.set(3)
    assert obs.values == [1, 2]
    assert obs.completed_cleanly


def test_take_zero():
    s = state(0)
    t = pipe(s, take(0))
    obs = observe(t)
    assert obs.completed_cleanly
    assert obs.values == []


def test_take_upstream_error():
    p = producer(lambda api: api.error(ValueError("err")))
    t = pipe(p, take(5))
    obs = observe(t)
    assert obs.errored


def test_take_upstream_completes_early():
    p = producer(lambda api: api.complete())
    t = pipe(p, take(5))
    obs = observe(t)
    assert obs.completed_cleanly


# ── skip ─────────────────────────────────────────────────────────────


def test_skip_basic():
    s = state(0)
    sk = pipe(s, skip(2))
    obs = observe(sk)
    s.set(1)
    s.set(2)
    s.set(3)
    s.set(4)
    assert obs.values == [3, 4]


def test_skip_state_suppressed_during_window():
    s = state(0)
    sk = pipe(s, skip(1))
    obs = observe(sk)
    s.set(1)  # skipped — should not forward DIRTY
    # After skip window, DIRTY should appear
    s.set(2)
    assert obs.dirty_count >= 1
    assert obs.values == [2]


def test_skip_upstream_error():
    p = producer(lambda api: api.error(ValueError("err")))
    sk = pipe(p, skip(1))
    obs = observe(sk)
    assert obs.errored


def test_skip_upstream_completion():
    p = producer(lambda api: api.complete())
    sk = pipe(p, skip(1))
    obs = observe(sk)
    assert obs.completed_cleanly


# ── take_while ───────────────────────────────────────────────────────


def test_take_while_basic():
    s = state(0)
    tw = pipe(s, take_while(lambda x: x < 3))
    obs = observe(tw)
    s.set(1)
    s.set(2)
    s.set(5)  # fails — completes
    s.set(1)  # after completion — ignored
    assert obs.values == [1, 2]
    assert obs.completed_cleanly


def test_take_while_error_in_predicate():
    s = state(0)

    def bad_pred(x):
        if x == 2:
            raise RuntimeError("bad")
        return True

    tw = pipe(s, take_while(bad_pred))
    obs = observe(tw)
    s.set(1)
    s.set(2)
    assert obs.errored
    assert isinstance(obs.end_error, RuntimeError)


def test_take_while_upstream_error():
    p = producer(lambda api: api.error(ValueError("err")))
    tw = pipe(p, take_while(lambda x: True))
    obs = observe(tw)
    assert obs.errored


# ── distinct_until_changed ───────────────────────────────────────────


def test_distinct_basic():
    s = state(1)
    d = pipe(s, distinct_until_changed())
    obs = observe(d)
    s.set(1)  # same → RESOLVED
    s.set(2)  # different → DATA
    s.set(2)  # same → RESOLVED
    s.set(3)  # different → DATA
    assert obs.values == [2, 3]


def test_distinct_custom_equals():
    s = state({"k": 1})
    d = pipe(s, distinct_until_changed(equals=lambda a, b: a["k"] == b["k"]))
    obs = observe(d)
    s.set({"k": 1})  # equal by custom fn
    assert obs.resolved_count >= 1
    s.set({"k": 2})
    assert obs.values == [{"k": 2}]


# ── merge ────────────────────────────────────────────────────────────


def test_merge_basic():
    a = state(0)
    b = state(0)
    m = merge(a, b)
    obs = observe(m)
    a.set(1)
    b.set(2)
    assert obs.values == [1, 2]


def test_merge_last_value():
    a = state(0)
    b = state(0)
    m = merge(a, b)
    obs = observe(m)
    a.set(10)
    assert m.get() == 10
    b.set(20)
    assert m.get() == 20


def test_merge_completes_when_all_complete():
    a = producer()
    b = producer()
    m = merge(a, b)
    obs = observe(m)
    a.complete()
    assert not obs.ended
    b.complete()
    assert obs.completed_cleanly


def test_merge_error_from_any():
    a = state(0)
    b = producer(lambda api: api.error(ValueError("err")))
    m = merge(a, b)
    obs = observe(m)
    assert obs.errored


def test_merge_dirty_resolution():
    a = state(1)
    b = state(2)
    m = merge(a, b)
    obs = observe(m)
    with batch():
        a.set(10)
        b.set(20)
    # After batch, both emit
    assert 10 in obs.values
    assert 20 in obs.values


# ── combine ──────────────────────────────────────────────────────────


def test_combine_basic():
    a = state(1)
    b = state(2)
    c = combine(a, b)
    assert c.get() == (1, 2)


def test_combine_updates():
    a = state(1)
    b = state(2)
    c = combine(a, b)
    obs = observe(c)
    a.set(10)
    assert obs.values == [(10, 2)]
    b.set(20)
    assert obs.values == [(10, 2), (10, 20)]


def test_combine_diamond():
    s = state(1)
    a = derived([s], lambda: s.get() * 2)
    b = derived([s], lambda: s.get() + 10)
    c = combine(a, b)
    count = [0]
    effect([c], lambda: count.__setitem__(0, count[0] + 1))
    assert count[0] == 1  # initial run
    s.set(5)
    assert count[0] == 2  # +1 (diamond resolves once)
    assert c.get() == (10, 15)


# ── zip ──────────────────────────────────────────────────────────────


def test_zip_basic():
    a = state(0)
    b = state(0)
    z = zip(a, b)
    obs = observe(z)
    a.set(1)
    b.set(10)
    # After both emit, zip should produce (1, 10)
    assert (1, 10) in obs.values


def test_zip_buffering():
    a = state(0)
    b = state(0)
    z = zip(a, b)
    obs = observe(z)
    a.set(1)
    a.set(2)
    b.set(10)
    # First pair: (1, 10), second pair waits for b
    assert (1, 10) in obs.values
    b.set(20)
    assert (2, 20) in obs.values


def test_zip_completes_on_source_empty():
    a = producer()
    b = producer()
    z = zip(a, b)
    obs = observe(z)
    a.complete()
    # a completed with empty buffer — no more tuples possible
    assert obs.completed_cleanly


def test_zip_error():
    a = state(0)
    b = producer(lambda api: api.error(ValueError("err")))
    z = zip(a, b)
    obs = observe(z)
    assert obs.errored


# ── share ────────────────────────────────────────────────────────────


def test_share_noop():
    s = state(42)
    shared = pipe(s, share())
    assert shared is s


# ── replay ───────────────────────────────────────────────────────────


def test_replay_seeds_on_connect():
    s = state(5)
    r = pipe(s, replay())
    obs = observe(r)
    assert r.get() == 5


def test_replay_emits():
    s = state(0)
    r = pipe(s, replay())
    obs = observe(r)
    s.set(1)
    s.set(2)
    assert obs.values == [1, 2]


def test_replay_resets_on_disconnect():
    s = state(10)
    r = pipe(s, replay())
    obs = observe(r)
    s.set(20)
    assert obs.values == [20]
    obs.reconnect()
    # After reconnect, should re-seed with current value
    assert r.get() == 20
    s.set(30)
    assert obs.values == [30]


# ── reconnect tests ──────────────────────────────────────────────────


def test_take_reconnect():
    """take resets count on reconnect."""
    s = state(0)
    t = pipe(s, take(2))
    obs = observe(t)
    s.set(1)
    s.set(2)
    assert obs.completed_cleanly

    # New subscription should work again
    s2 = state(0)
    t2 = pipe(s2, take(2))
    obs2 = observe(t2)
    s2.set(10)
    s2.set(20)
    assert obs2.values == [10, 20]
    assert obs2.completed_cleanly


def test_skip_reconnect():
    """skip resets counter on reconnect (new operator instance)."""
    s = state(0)
    sk = pipe(s, skip(1))
    obs = observe(sk)
    s.set(1)  # skipped
    s.set(2)
    assert obs.values == [2]
    obs.dispose()

    obs2 = observe(sk)
    s.set(3)  # skip resets
    s.set(4)
    assert obs2.values == [4]


def test_filter_reconnect():
    s = state(0)
    f = pipe(s, filter(lambda x: x > 0))
    obs = observe(f)
    s.set(5)
    assert obs.values == [5]
    obs.reconnect()
    s.set(10)
    assert obs.values == [10]
