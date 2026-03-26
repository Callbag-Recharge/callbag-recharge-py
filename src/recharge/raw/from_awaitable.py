"""from_awaitable -- coroutine/awaitable to source (framework-agnostic)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._scheduling import ScheduleFn, thread_schedule
from ._talkback import StoppableTalkback

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from .protocol import Sink, Talkback


class _AwaitableSource:
    """Source that runs a coroutine and emits its result.

    Framework-agnostic: accepts a ``schedule`` callable that runs a coroutine
    to completion.  Defaults to ``thread_schedule`` which spins up a daemon
    thread with ``asyncio.run()``.
    """

    __slots__ = ("_coro_factory", "_schedule")

    def __init__(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
        schedule: ScheduleFn,
    ) -> None:
        self._coro_factory = coro_factory
        self._schedule = schedule

    def subscribe(self, sink: Sink[Any], /) -> Talkback:
        tb = StoppableTalkback()
        coro = self._coro_factory()

        def on_result(value: Any) -> None:
            if not tb._stopped:
                sink.next(value)
            if not tb._stopped:
                tb._stopped = True
                sink.complete()

        def on_error(err: Exception) -> None:
            if not tb._stopped:
                tb._stopped = True
                sink.error(err)

        self._schedule(coro, on_result, on_error)
        return tb


def from_awaitable[T](
    coro: Coroutine[Any, Any, T] | Callable[[], Coroutine[Any, Any, T]],
    *,
    schedule: ScheduleFn | None = None,
) -> _AwaitableSource:
    """Create a source from a coroutine.  Emits the result, then completes.

    Framework-agnostic: provide a ``schedule`` callback to use trio, anyio, etc.
    Default uses ``asyncio.run()`` in a daemon thread.

    Args:
        coro: A coroutine object, or a zero-arg factory that creates one.
            Factories allow resubscription (each subscriber gets a fresh coro).
        schedule: ``(coro, on_result, on_error) -> None``.  Runs the coroutine
            and calls on_result/on_error when done.

    Returns:
        A Source that emits one value and completes.
    """
    if callable(coro) and not hasattr(coro, "__await__"):
        factory = coro
    else:
        # Wrap a single coroutine object -- only first subscriber gets it
        _coro = coro
        _used = False

        def factory() -> Coroutine[Any, Any, T]:
            nonlocal _used
            if _used:
                raise RuntimeError(
                    "Coroutine already consumed.  Pass a factory function "
                    "for resubscribable sources."
                )
            _used = True
            return _coro  # type: ignore[return-value]

    return _AwaitableSource(factory, schedule or thread_schedule)
