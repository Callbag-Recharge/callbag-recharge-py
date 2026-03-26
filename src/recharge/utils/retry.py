"""retry operator with optional backoff."""

from __future__ import annotations

import math
import threading
from typing import Any

from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe
from ..raw import from_timer, raw_subscribe
from .backoff import BackoffPreset, BackoffStrategy, resolve_backoff_preset


def retry(
    count: int | None = None, *, backoff: BackoffStrategy | BackoffPreset | None = None
) -> Any:
    """Retry upstream after errors with optional delay strategy."""
    max_retries = count if count is not None else (0 if backoff is None else 1_000_000_000)
    if max_retries < 0:
        raise ValueError("count must be >= 0")

    strategy: BackoffStrategy | None = (
        resolve_backoff_preset(backoff) if isinstance(backoff, str) else backoff
    )

    def _op(input_store: Any) -> Any:
        def factory(api: Any) -> Any:
            attempt = 0
            stopped = False
            prev_delay: float | None = None
            upstream_sub: list[Any] = [None]
            timer_sub: list[Any] = [None]
            timer_generation = 0
            lock = threading.RLock()

            def _clear_timer_locked() -> None:
                if timer_sub[0] is not None:
                    timer_sub[0].unsubscribe()
                    timer_sub[0] = None

            def _connect() -> None:
                if upstream_sub[0] is not None:
                    upstream_sub[0].unsubscribe()
                    upstream_sub[0] = None
                _clear_timer_locked()

                def on_value(v: Any, _prev: Any) -> None:
                    api.emit(v)

                def on_end(err: Exception | None) -> None:
                    _schedule_retry_or_finish(err)

                upstream_sub[0] = subscribe(input_store, on_value, on_end=on_end)

            def _retry_now() -> None:
                with lock:
                    if stopped:
                        return
                    _connect()

            def _coerce_delay(raw_delay: Any) -> float:
                try:
                    delay = float(raw_delay)
                except (TypeError, ValueError):
                    raise ValueError("backoff strategy must return a number or None") from None
                if not math.isfinite(delay):
                    raise ValueError("backoff strategy returned non-finite delay")
                if delay < 0:
                    return 0.0
                return delay

            def _schedule_retry_or_finish(err: Exception | None) -> None:
                nonlocal attempt, prev_delay, timer_generation
                with lock:
                    if stopped:
                        return
                    if err is None:
                        api.complete()
                        return

                    if attempt >= max_retries:
                        api.error(err)
                        return

                    raw_delay = 0.0 if strategy is None else strategy(attempt, err, prev_delay)
                    delay = _coerce_delay(0.0 if raw_delay is None else raw_delay)
                    prev_delay = delay
                    attempt += 1

                    # Avoid recursive call chains for repeatedly failing sync sources.
                    safe_delay = delay if delay > 0 else 1e-6
                    timer_generation += 1
                    current_generation = timer_generation
                    _clear_timer_locked()

                def on_tick(_: Any) -> None:
                    with lock:
                        if stopped or current_generation != timer_generation:
                            return
                    _retry_now()

                with lock:
                    if stopped or current_generation != timer_generation:
                        return
                    timer_sub[0] = raw_subscribe(from_timer(safe_delay), on_tick, lambda _e: None)

            def _handle_lifecycle(sig: Signal) -> None:
                nonlocal attempt, prev_delay, timer_generation
                with lock:
                    if stopped:
                        return
                    if upstream_sub[0] is not None:
                        upstream_sub[0].signal(sig)
                    if sig is Signal.RESET:
                        attempt = 0
                        prev_delay = None
                        timer_generation += 1
                        _clear_timer_locked()
                        _connect()

            api.on_signal(_handle_lifecycle)

            with lock:
                _connect()

            def cleanup() -> None:
                nonlocal stopped, timer_generation
                with lock:
                    stopped = True
                    timer_generation += 1
                    _clear_timer_locked()
                    if upstream_sub[0] is not None:
                        upstream_sub[0].unsubscribe()
                        upstream_sub[0] = None

            return cleanup

        return producer(factory, initial=input_store.get(), resubscribable=True)

    return _op
