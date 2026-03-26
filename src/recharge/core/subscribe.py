"""Core subscribe — store-aware subscription with previous-value tracking."""

from __future__ import annotations

import contextlib
from typing import Any

from .protocol import Signal, begin_deferred_start, end_deferred_start
from .types import Subscription, _CallbackSink


def subscribe(
    store: Any,
    cb: Any,
    *,
    on_end: Any = None,
) -> Subscription:
    """Subscribe to a store's DATA emissions with previous-value tracking.

    Returns a Subscription with ``unsubscribe()`` and ``signal()`` for
    upstream lifecycle control. Also works as a context manager.

    The callback receives ``(value, prev)`` on each DATA emission after
    subscription. The initial value is NOT emitted — only subsequent changes.
    """
    prev: list[Any] = [None]
    talkback_ref: list[Any] = [None]

    def on_next(value: Any) -> None:
        p = prev[0]
        prev[0] = value
        cb(value, p)

    def on_signal(sig: Signal) -> None:
        pass  # subscribe is transparent to STATE signals

    def on_complete() -> None:
        talkback_ref[0] = None
        if on_end is not None:
            on_end(None)

    def on_error(err: Exception) -> None:
        talkback_ref[0] = None
        if on_end is not None:
            on_end(err)

    begin_deferred_start()

    sink = _CallbackSink(on_next, on_signal, on_complete, on_error)
    tb = store.subscribe(sink)
    talkback_ref[0] = tb

    # Baseline: capture current value before producers start
    with contextlib.suppress(Exception):
        prev[0] = store.get()

    end_deferred_start()

    return Subscription(tb)
