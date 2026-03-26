"""with_breaker operator and simple circuit breaker."""

from __future__ import annotations

import threading
import time
from typing import Any, Literal, Protocol

from ..core import state
from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe

CircuitState = Literal["closed", "open", "half-open"]


class BreakerLike(Protocol):
    def can_execute(self) -> bool: ...
    def record_success(self) -> None: ...
    def record_failure(self, error: Exception | None = None) -> None: ...
    @property
    def state(self) -> str: ...


class CircuitOpenError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Circuit breaker is open")


class CircuitBreaker:
    """Small synchronous circuit breaker state machine."""

    __slots__ = (
        "_threshold",
        "_cooldown",
        "_half_open_max",
        "_state",
        "_failures",
        "_opened_at",
        "_trials",
        "_lock",
    )

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown: float = 30.0,
        half_open_max: int = 1,
    ) -> None:
        self._threshold = max(1, failure_threshold)
        self._cooldown = max(0.0, cooldown)
        self._half_open_max = max(1, half_open_max)
        self._state: CircuitState = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._trials = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def can_execute(self) -> bool:
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if (time.monotonic() - self._opened_at) >= self._cooldown:
                    self._state = "half-open"
                    self._trials = 1
                    return True
                return False
            if self._trials < self._half_open_max:
                self._trials += 1
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._trials = 0

    def record_failure(self, error: Exception | None = None) -> None:
        _ = error
        with self._lock:
            if self._state == "half-open":
                self._state = "open"
                self._opened_at = time.monotonic()
                self._trials = 0
                return
            self._failures += 1
            if self._failures >= self._threshold:
                self._state = "open"
                self._opened_at = time.monotonic()
                self._trials = 0


class _WithBreakerStore:
    __slots__ = ("_inner", "breaker_state")

    def __init__(self, inner: Any, breaker_state: Any) -> None:
        self._inner = inner
        self.breaker_state = breaker_state

    def get(self) -> Any:
        return self._inner.get()

    def subscribe(self, sink: Any, /) -> Any:
        return self._inner.subscribe(sink)

    def __or__(self, op: Any) -> Any:
        return op(self)


def with_breaker(breaker: BreakerLike, *, on_open: Literal["skip", "error"] = "skip") -> Any:
    """Guard a source with breaker state."""

    def _op(input_store: Any) -> Any:
        breaker_state = state(str(breaker.state))

        def factory(api: Any) -> Any:
            sub: list[Any] = [None]

            def on_value(v: Any, _prev: Any) -> None:
                if breaker.can_execute():
                    breaker_state.set(str(breaker.state))
                    api.emit(v)
                    return

                breaker_state.set(str(breaker.state))
                if on_open == "error":
                    api.error(CircuitOpenError())
                else:
                    api.signal(Signal.RESOLVED)

            def on_end(err: Exception | None) -> None:
                if err is not None:
                    breaker.record_failure(err)
                    breaker_state.set(str(breaker.state))
                    api.error(err)
                else:
                    breaker.record_success()
                    breaker_state.set(str(breaker.state))
                    api.complete()

            def on_signal(sig: Signal) -> None:
                if sub[0] is not None:
                    sub[0].signal(sig)

            api.on_signal(on_signal)
            sub[0] = subscribe(input_store, on_value, on_end=on_end)

            def cleanup() -> None:
                if sub[0] is not None:
                    sub[0].unsubscribe()
                    sub[0] = None

            return cleanup

        out = producer(factory, initial=input_store.get(), resubscribable=True)
        return _WithBreakerStore(out, breaker_state)

    return _op
