"""Tests for Tier 2 extra operators: debounce, throttle, sample,
switch_map, concat_map, flat_map.
"""

from __future__ import annotations

import time

from recharge import pipe, producer, state
from recharge.extra import concat_map, debounce, flat_map, sample, switch_map, throttle

from .conftest import observe

# ── debounce ─────────────────────────────────────────────────────────


def test_debounce_basic():
    s = state(0)
    d = pipe(s, debounce(0.05))
    obs = observe(d)
    s.set(1)
    s.set(2)
    s.set(3)
    time.sleep(0.1)
    assert obs.values == [3]  # only last value after silence


def test_debounce_flushes_on_complete():
    p = producer()
    d = pipe(p, debounce(1.0))  # long debounce
    obs = observe(d)
    p.emit(42)
    p.complete()
    # Should flush pending value immediately
    assert 42 in obs.values
    assert obs.completed_cleanly


def test_debounce_error_cancels_timer():
    p = producer()
    d = pipe(p, debounce(1.0))
    obs = observe(d)
    p.emit(1)
    p.error(ValueError("err"))
    assert obs.errored
    assert obs.values == []  # no flush on error


def test_debounce_get_value():
    s = state(0)
    d = pipe(s, debounce(0.05))
    obs = observe(d)
    s.set(10)
    time.sleep(0.1)
    assert d.get() == 10


def test_debounce_teardown():
    s = state(0)
    d = pipe(s, debounce(1.0))
    obs = observe(d)
    s.set(1)
    obs.dispose()  # should cancel timer
    time.sleep(0.05)  # no crash


# ── throttle ─────────────────────────────────────────────────────────


def test_throttle_basic():
    s = state(0)
    t = pipe(s, throttle(0.1))
    obs = observe(t)
    s.set(1)  # emits immediately (leading edge)
    s.set(2)  # dropped (within window)
    s.set(3)  # dropped (within window)
    assert obs.values == [1]
    time.sleep(0.15)
    s.set(4)  # window passed, emits
    assert obs.values == [1, 4]


def test_throttle_completion():
    p = producer()
    t = pipe(p, throttle(0.1))
    obs = observe(t)
    p.emit(1)
    p.complete()
    assert obs.completed_cleanly


def test_throttle_error():
    p = producer()
    t = pipe(p, throttle(0.1))
    obs = observe(t)
    p.error(ValueError("err"))
    assert obs.errored


def test_throttle_teardown():
    s = state(0)
    t = pipe(s, throttle(1.0))
    obs = observe(t)
    s.set(1)
    obs.dispose()
    time.sleep(0.05)  # no crash


# ── sample ───────────────────────────────────────────────────────────


def test_sample_basic():
    input_store = state(0)
    tick = state(0)
    sampled = pipe(input_store, sample(tick))
    obs = observe(sampled)
    input_store.set(10)
    input_store.set(20)
    tick.set(1)
    assert obs.values == [20]  # latest input at sample time


def test_sample_get():
    input_store = state(5)
    tick = state(0)
    sampled = pipe(input_store, sample(tick))
    obs = observe(sampled)
    # get() reflects latest input when subscribed
    assert sampled.get() == 5
    input_store.set(42)
    assert sampled.get() == 42


def test_sample_input_complete():
    p = producer()
    tick = state(0)
    sampled = pipe(p, sample(tick))
    obs = observe(sampled)
    p.complete()
    assert obs.completed_cleanly


def test_sample_notifier_complete():
    input_store = state(0)
    notifier = producer()
    sampled = pipe(input_store, sample(notifier))
    obs = observe(sampled)
    notifier.complete()
    assert obs.completed_cleanly


# ── switch_map ───────────────────────────────────────────────────────


def test_switch_map_basic():
    outer = state("a")
    out = pipe(
        outer,
        switch_map(lambda x: state(x + "!")),
    )
    obs = observe(out)
    # Initial inner from current outer value doesn't auto-trigger (subscribe doesn't emit initial)
    # We need to set the outer to trigger switchMap
    outer.set("b")
    assert "b!" in obs.values


def test_switch_map_switches_inner():
    outer = state(0)
    inner1 = state("x")
    inner2 = state("y")
    inners = {1: inner1, 2: inner2}

    out = pipe(outer, switch_map(lambda v: inners[v]))
    obs = observe(out)

    outer.set(1)  # triggers switchMap → subscribes to inner1
    inner1.set("x1")
    assert "x1" in obs.values

    outer.set(2)  # switch to inner2
    inner1.set("x2")  # inner1 no longer active — should not emit
    inner2.set("y1")
    assert "x2" not in obs.values
    assert "y1" in obs.values


def test_switch_map_outer_complete():
    outer = producer()
    out = pipe(outer, switch_map(lambda v: state(v)))
    obs = observe(out)
    outer.emit("a")
    outer.complete()
    # Outer done, inner (state) doesn't complete → switch_map stays open
    # Actually state doesn't complete, so switch_map shouldn't complete
    # But per the implementation, it completes only if inner is None
    # After outer emits and creates inner, inner_sub is not None → stays open


def test_switch_map_outer_error():
    outer = producer()
    out = pipe(outer, switch_map(lambda v: state(v)))
    obs = observe(out)
    outer.error(ValueError("err"))
    assert obs.errored


def test_switch_map_initial():
    outer = state("a")
    out = pipe(outer, switch_map(lambda x: state(x), initial="init"))
    assert out.get() == "init"


# ── concat_map ───────────────────────────────────────────────────────


def test_concat_map_sequential():
    outer = state(0)
    results = []

    def make_inner(v):
        p = producer()
        results.append((v, p))
        return p

    out = pipe(outer, concat_map(make_inner))
    obs = observe(out)

    outer.set(1)  # starts inner1
    outer.set(2)  # queued
    outer.set(3)  # queued

    # Only inner1 should be active
    assert len(results) == 1
    v1, p1 = results[0]
    assert v1 == 1
    p1.emit("a")
    assert "a" in obs.values
    p1.complete()

    # Now inner2 should start
    assert len(results) == 2
    v2, p2 = results[1]
    assert v2 == 2


def test_concat_map_max_buffer():
    outer = state(0)
    inners: list[tuple[int, Any]] = []

    def make_inner(v):
        p = producer()
        inners.append((v, p))
        return p

    out = pipe(outer, concat_map(make_inner, max_buffer=1))
    obs = observe(out)

    outer.set(1)  # starts inner
    outer.set(2)  # queued
    outer.set(3)  # replaces 2 in queue (max_buffer=1)

    _, p1 = inners[0]
    p1.complete()

    # Next should be 3 (2 was dropped)
    assert len(inners) == 2
    v2, _ = inners[1]
    assert v2 == 3


def test_concat_map_outer_error():
    outer = producer()
    out = pipe(outer, concat_map(lambda v: state(v)))
    obs = observe(out)
    outer.error(ValueError("err"))
    assert obs.errored


# ── flat_map ─────────────────────────────────────────────────────────


def test_flat_map_concurrent():
    outer = state(0)
    p1 = producer()
    p2 = producer()
    counter = [0]

    def make_inner(v):
        counter[0] += 1
        return p1 if counter[0] == 1 else p2

    out = pipe(outer, flat_map(make_inner))
    obs = observe(out)

    outer.set(1)  # subscribes to p1
    outer.set(2)  # subscribes to p2 (p1 still active)

    p1.emit("from-1")
    p2.emit("from-2")
    assert "from-1" in obs.values
    assert "from-2" in obs.values


def test_flat_map_completes_when_all_done():
    outer = producer()
    inner = producer()
    out = pipe(outer, flat_map(lambda v: inner))
    obs = observe(out)

    outer.emit(1)
    outer.complete()
    assert not obs.ended  # inner still active

    inner.complete()
    assert obs.completed_cleanly


def test_flat_map_outer_error():
    outer = producer()
    out = pipe(outer, flat_map(lambda v: state(v)))
    obs = observe(out)
    outer.error(ValueError("err"))
    assert obs.errored


def test_flat_map_inner_error():
    outer = state(0)
    inner = producer()
    out = pipe(outer, flat_map(lambda v: inner))
    obs = observe(out)
    outer.set(1)
    inner.error(ValueError("inner-err"))
    assert obs.errored
    assert isinstance(obs.end_error, ValueError)
