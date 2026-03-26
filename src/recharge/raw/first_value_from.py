"""first_value_from -- source to concurrent.futures.Future (THE bridge)."""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from .protocol import Signal, Source, Talkback


class _FirstValueSink:
    """Sink that resolves a Future with the first matching value."""

    __slots__ = ("_future", "_predicate", "_talkback", "_settled")

    def __init__(
        self,
        future: concurrent.futures.Future[Any],
        predicate: Callable[[Any], bool] | None,
    ) -> None:
        self._future = future
        self._predicate = predicate
        self._talkback: Talkback | None = None
        self._settled = False

    def next(self, value: Any) -> None:
        if self._settled:
            return
        if self._predicate is not None and not self._predicate(value):
            return
        self._settled = True
        self._future.set_result(value)
        if self._talkback is not None:
            self._talkback.stop()

    def signal(self, sig: Signal) -> None:
        pass  # ignore STATE signals

    def complete(self) -> None:
        if self._settled:
            return
        self._settled = True
        self._future.set_exception(
            LookupError("Source completed without emitting a matching value")
        )

    def error(self, err: Exception) -> None:
        if self._settled:
            return
        self._settled = True
        self._future.set_exception(err)


def first_value_from[T](
    source: Source[T],
    *,
    predicate: Callable[[T], bool] | None = None,
) -> concurrent.futures.Future[T]:
    """Subscribe to *source* and resolve a Future with the first matching value.

    This is THE canonical bridge from reactive-land to imperative code.
    Returns a ``concurrent.futures.Future`` (framework-agnostic -- works with
    asyncio via ``asyncio.wrap_future``, or with any threading code).

    Args:
        source: Any Source-compatible object.
        predicate: Optional filter.  Only values for which ``predicate(v)``
            returns True are considered.

    Returns:
        A Future that resolves with the first matching value, or rejects if
        the source completes without a match or errors.
    """
    future: concurrent.futures.Future[T] = concurrent.futures.Future()
    sink = _FirstValueSink(future, predicate)
    talkback = source.subscribe(sink)
    sink._talkback = talkback

    # If the source emitted synchronously during subscribe, the future
    # is already resolved and we're done.
    if sink._settled:
        return future

    # Allow external cancellation via Future.cancel().
    # Use a list to hold mutable refs so the callback can clear them
    # after firing, preventing the closure from keeping sink/talkback alive.
    refs: list[Any] = [sink, talkback]

    def _on_cancel(f: concurrent.futures.Future[Any]) -> None:
        s, tb = refs[0], refs[1]
        refs.clear()  # release references regardless of outcome
        if s is not None and f.cancelled() and not s._settled:
            s._settled = True
            tb.stop()

    future.add_done_callback(_on_cancel)
    return future
