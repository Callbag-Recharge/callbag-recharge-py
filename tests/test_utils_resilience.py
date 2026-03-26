from __future__ import annotations

import time

import pytest

from recharge import Signal, pipe, producer, state, subscribe
from recharge.utils import (
    CircuitBreaker,
    CircuitOpenError,
    TimeoutError,
    constant,
    exponential,
    fibonacci,
    linear,
    resolve_backoff_preset,
    retry,
    timeout,
    with_breaker,
    with_status,
)

from .conftest import observe


def test_backoff_presets_resolve() -> None:
    assert resolve_backoff_preset("constant")(0, None, None) == 1.0
    assert resolve_backoff_preset("linear")(2, None, None) == 3.0
    assert resolve_backoff_preset("exponential")(3, None, None) == pytest.approx(0.8)
    assert resolve_backoff_preset("fibonacci")(4, None, None) == pytest.approx(0.5)


def test_backoff_helpers() -> None:
    assert constant(0.2)(0, None, None) == pytest.approx(0.2)
    assert linear(0.1)(3, None, None) == pytest.approx(0.4)
    assert exponential(base=0.1, factor=2.0, max_delay=1.0)(4, None, None) == pytest.approx(1.0)
    assert fibonacci(0.1, max_delay=1.0)(5, None, None) == pytest.approx(0.8)


def test_retry_retries_then_completes() -> None:
    attempts = {"count": 0}

    def make_source():
        def factory(api):
            attempts["count"] += 1
            if attempts["count"] < 3:
                api.error(ValueError("boom"))
            else:
                api.emit(42)
                api.complete()

        return producer(factory, resubscribable=True)

    source = make_source()
    retried = pipe(source, retry(3))
    obs = observe(retried)
    time.sleep(0.02)
    assert obs.values == [42]
    assert obs.completed_cleanly
    assert attempts["count"] == 3


def test_retry_stops_at_max_retries() -> None:
    def factory(api):
        api.error(ValueError("nope"))

    source = producer(factory, resubscribable=True)
    retried = pipe(source, retry(1))
    obs = observe(retried)
    time.sleep(0.02)
    assert obs.errored
    assert isinstance(obs.end_error, ValueError)


def test_with_status_tracks_lifecycle() -> None:
    src = producer()
    tracked = with_status(src)
    assert tracked.status.get() == "pending"
    assert tracked.error_store.get() is None

    obs = observe(tracked)
    src.emit(1)
    assert tracked.status.get() == "active"
    assert obs.values == [1]

    src.complete()
    assert tracked.status.get() == "completed"
    assert obs.completed_cleanly


def test_with_status_tracks_error() -> None:
    src = producer()
    tracked = with_status(src)
    obs = observe(tracked)
    src.error(ValueError("broken"))
    assert tracked.status.get() == "errored"
    assert isinstance(tracked.error_store.get(), ValueError)
    assert obs.errored


def test_with_breaker_skip_mode() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown=10.0)
    source = producer()
    guarded = pipe(source, with_breaker(breaker, on_open="skip"))
    obs = observe(guarded)

    source.error(ValueError("first failure"))
    assert obs.errored


def test_with_breaker_error_mode_when_open() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown=999.0)
    source = state(0)
    guarded = pipe(source, with_breaker(breaker, on_open="error"))
    obs = observe(guarded)

    breaker.record_failure(ValueError("trip"))
    source.set(1)
    assert obs.errored
    assert isinstance(obs.end_error, CircuitOpenError)


def test_timeout_errors_on_silence() -> None:
    src = producer()
    wrapped = pipe(src, timeout(0.03))
    obs = observe(wrapped)
    time.sleep(0.06)
    assert obs.errored
    assert isinstance(obs.end_error, TimeoutError)


def test_timeout_resets_after_data() -> None:
    src = state(0)
    wrapped = pipe(src, timeout(0.05))
    obs = observe(wrapped)
    src.set(1)
    time.sleep(0.03)
    src.set(2)
    time.sleep(0.03)
    assert not obs.ended


def test_retry_forwards_lifecycle_signals() -> None:
    seen: list[Signal] = []

    def factory(api):
        api.on_signal(lambda sig: seen.append(sig))

    source = producer(factory, resubscribable=True)
    retried = pipe(source, retry(1))
    sub = subscribe(retried, lambda _v, _p: None)
    sub.signal(Signal.RESET)
    sub.signal(Signal.PAUSE)
    sub.signal(Signal.RESUME)
    sub.unsubscribe()
    assert Signal.RESET in seen
    assert Signal.PAUSE in seen
    assert Signal.RESUME in seen


def test_with_status_reset_resets_companion_stores() -> None:
    src = state(0)
    tracked = with_status(src, initial_status="pending")
    sub = subscribe(tracked, lambda _v, _p: None)
    src.set(1)
    assert tracked.status.get() == "active"
    sub.signal(Signal.RESET)
    assert tracked.status.get() == "pending"
    assert tracked.error_store.get() is None
    sub.unsubscribe()


def test_with_breaker_skip_emits_resolved() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown=999.0)
    source = state(0)
    guarded = pipe(source, with_breaker(breaker, on_open="skip"))
    obs = observe(guarded)
    breaker.record_failure(ValueError("trip"))
    source.set(1)
    assert obs.resolved_count >= 1


def test_with_breaker_forwards_lifecycle_signal() -> None:
    seen: list[Signal] = []

    def factory(api):
        api.on_signal(lambda sig: seen.append(sig))

    source = producer(factory)
    guarded = pipe(source, with_breaker(CircuitBreaker()))
    sub = subscribe(guarded, lambda _v, _p: None)
    sub.signal(Signal.PAUSE)
    sub.unsubscribe()
    assert Signal.PAUSE in seen


def test_timeout_reset_rearms_timer() -> None:
    src = state(0)
    wrapped = pipe(src, timeout(0.02))
    obs = observe(wrapped)
    time.sleep(0.01)
    sub = subscribe(wrapped, lambda _v, _p: None)
    sub.signal(Signal.RESET)
    time.sleep(0.03)
    assert obs.errored
