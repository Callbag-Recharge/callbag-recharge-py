"""from_any -- universal normalizer (sync/coro/async gen/source/plain value)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._talkback import StoppableTalkback

if TYPE_CHECKING:
    from ._scheduling import ScheduleFn
    from .protocol import Sink, Source, Talkback


class _ValueSource:
    """Source that emits a single plain value, then completes."""

    __slots__ = ("_value",)

    def __init__(self, value: Any) -> None:
        self._value = value

    def subscribe(self, sink: Sink[Any], /) -> Talkback:
        tb = StoppableTalkback()
        sink.next(self._value)
        if not tb._stopped:
            tb._stopped = True
            sink.complete()
        return tb


def from_any(
    value: Any,
    *,
    schedule: ScheduleFn | None = None,
) -> Source[Any]:
    """Normalize any value into a Source.

    Dispatch order:
    1. Source (has .subscribe method) -- returned as-is
    2. Coroutine (has __await__) -- delegates to from_awaitable
    3. AsyncIterable (has __aiter__) -- delegates to from_async_iter
    4. Iterable (has __iter__, excluding str/bytes) -- delegates to from_iter
    5. Plain value -- emits once, then completes

    Args:
        value: Anything.  Dispatched by duck-type checks.
        schedule: Passed through to from_awaitable/from_async_iter if needed.

    Returns:
        A Source that emits the appropriate values and completes.
    """
    # Fast path: plain scalars (most common case for from_any)
    vtype = type(value)
    if vtype in _PLAIN_TYPES:
        return _ValueSource(value)

    # 1. Already a Source
    subscribe = getattr(value, "subscribe", None)
    if subscribe is not None and callable(subscribe):
        return value  # type: ignore[no-any-return]

    # 2. Coroutine (awaitable with send/throw -- distinguishes from Future)
    if hasattr(value, "send") and hasattr(value, "__await__"):
        from .from_awaitable import from_awaitable

        return from_awaitable(value, schedule=schedule)

    # 3. AsyncIterable
    if hasattr(value, "__aiter__"):
        from .from_async_iter import from_async_iter

        return from_async_iter(value, schedule=schedule)

    # 4. Iterable (excluding str/bytes -- those are treated as plain values)
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
        from .from_iter import from_iter

        return from_iter(value)

    # 5. Plain value (custom types, etc.)
    return _ValueSource(value)


_PLAIN_TYPES: frozenset[type] = frozenset({int, float, str, bytes, bool, type(None)})
