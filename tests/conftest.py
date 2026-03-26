"""Shared test fixtures and helpers."""

from __future__ import annotations

from typing import Any

from recharge import Signal
from recharge.core.types import _CallbackSink


class Observation:
    """Collects DATA values, STATE signals, and END events from a store.

    Returned by ``observe()``. See docs/test-guidance.md for the full API.
    """

    __slots__ = (
        "_store",
        "_sub",
        "values",
        "signals",
        "events",
        "dirty_count",
        "resolved_count",
        "ended",
        "end_error",
    )

    def __init__(self, store: Any) -> None:
        self._store = store
        self.values: list[Any] = []
        self.signals: list[Signal] = []
        self.events: list[tuple[str, Any]] = []
        self.dirty_count: int = 0
        self.resolved_count: int = 0
        self.ended: bool = False
        self.end_error: Exception | None = None
        self._sub: Any = None
        self._connect()

    def _connect(self) -> None:
        def on_next(value: Any) -> None:
            if self.ended:
                return
            self.values.append(value)
            self.events.append(("DATA", value))

        def on_signal(sig: Signal) -> None:
            if self.ended:
                return
            self.signals.append(sig)
            self.events.append(("SIGNAL", sig))
            if sig is Signal.DIRTY:
                self.dirty_count += 1
            elif sig is Signal.RESOLVED:
                self.resolved_count += 1

        def on_complete() -> None:
            self.ended = True
            self.events.append(("END", None))

        def on_error(err: Exception) -> None:
            self.ended = True
            self.end_error = err
            self.events.append(("END", err))

        sink = _CallbackSink(on_next, on_signal, on_complete, on_error)
        self._sub = self._store.subscribe(sink)

    @property
    def completed_cleanly(self) -> bool:
        """True if ended without error."""
        return self.ended and self.end_error is None

    @property
    def errored(self) -> bool:
        """True if ended with error."""
        return self.ended and self.end_error is not None

    def dispose(self) -> None:
        """Unsubscribe from the store."""
        if self._sub is not None:
            self._sub.stop()
            self._sub = None

    def __enter__(self) -> Observation:
        return self

    def __exit__(self, *args: Any) -> None:
        self.dispose()

    def reconnect(self) -> None:
        """Dispose and re-observe the same store with fresh state."""
        self.dispose()
        self.values.clear()
        self.signals.clear()
        self.events.clear()
        self.dirty_count = 0
        self.resolved_count = 0
        self.ended = False
        self.end_error = None
        self._connect()


def observe(store: Any) -> Observation:
    """Observe a store's protocol output for test assertions.

    Returns an ``Observation`` that records DATA values, STATE signals,
    and END events in protocol order. This is the standard test tool —
    prefer it over manual sinks.
    """
    return Observation(store)
