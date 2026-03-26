"""Tests for the observe() test utility itself."""

from __future__ import annotations

from recharge import Signal, derived, producer, state

from .conftest import observe

# ---------------------------------------------------------------------------
# Basic value collection
# ---------------------------------------------------------------------------


def test_observe_collects_values():
    s = state(0)
    obs = observe(s)
    s.set(1)
    s.set(2)
    s.set(3)
    assert obs.values == [1, 2, 3]
    obs.dispose()


def test_observe_collects_signals():
    """DIRTY and RESOLVED signals are recorded."""
    s = state(1)
    d = derived([s], lambda: s.get() * 2)
    obs = observe(d)
    s.set(2)  # DIRTY → DATA
    s.set(2)  # same value, state skips entirely — no signals
    assert obs.dirty_count == 1
    assert obs.values == [4]
    obs.dispose()


def test_observe_events_order():
    """Events list preserves protocol order: SIGNAL(DIRTY) → DATA."""
    s = state(0)
    obs = observe(s)
    s.set(1)
    # Find DIRTY and the subsequent DATA(1)
    dirty_indices = [i for i, e in enumerate(obs.events) if e == ("SIGNAL", Signal.DIRTY)]
    data_indices = [i for i, e in enumerate(obs.events) if e == ("DATA", 1)]
    assert len(dirty_indices) >= 1
    assert len(data_indices) >= 1
    # DIRTY must come before DATA
    assert dirty_indices[0] < data_indices[0]
    obs.dispose()


# ---------------------------------------------------------------------------
# END tracking
# ---------------------------------------------------------------------------


def test_observe_complete():
    p = producer()
    obs = observe(p)
    p.emit(1)
    p.complete()
    assert obs.values == [1]
    assert obs.completed_cleanly is True
    assert obs.errored is False


def test_observe_error():
    p = producer()
    obs = observe(p)
    p.error(ValueError("boom"))
    assert obs.ended is True
    assert obs.errored is True
    assert isinstance(obs.end_error, ValueError)
    assert obs.completed_cleanly is False


# ---------------------------------------------------------------------------
# Dispose and reconnect
# ---------------------------------------------------------------------------


def test_observe_dispose_stops_collection():
    s = state(0)
    obs = observe(s)
    s.set(1)
    obs.dispose()
    s.set(2)
    assert obs.values == [1]  # no 2


def test_observe_reconnect_resets_state():
    s = state(0)
    obs = observe(s)
    s.set(1)
    assert obs.values == [1]

    obs.reconnect()
    assert obs.values == []
    assert obs.dirty_count == 0
    s.set(2)
    assert obs.values == [2]
    obs.dispose()


# ---------------------------------------------------------------------------
# RESOLVED tracking
# ---------------------------------------------------------------------------


def test_observe_resolved_count():
    """Derived that produces same value sends RESOLVED, tracked by observe."""
    a = state(1)
    d = derived([a], lambda: a.get() % 2, equals=lambda x, y: x == y)
    obs = observe(d)
    a.set(3)  # 3 % 2 == 1, same → RESOLVED
    assert obs.dirty_count >= 1  # two-phase: DIRTY must precede RESOLVED
    assert obs.resolved_count >= 1
    assert obs.values == []  # no DATA emitted
    obs.dispose()
