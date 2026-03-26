"""from_async_iter -- async iterable to source (framework-agnostic)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._scheduling import ScheduleFn, thread_schedule
from ._talkback import StoppableTalkback

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Callable

    from .protocol import Sink, Talkback


class _AsyncIterSource:
    """Source that emits values from an async iterable.

    Framework-agnostic: accepts a ``schedule`` callable that runs a coroutine.
    Default uses asyncio.run() in a daemon thread.
    """

    __slots__ = ("_factory", "_schedule")

    def __init__(
        self,
        factory: Callable[[], AsyncIterable[Any]],
        schedule: ScheduleFn,
    ) -> None:
        self._factory = factory
        self._schedule = schedule

    def subscribe(self, sink: Sink[Any], /) -> Talkback:
        tb = StoppableTalkback()
        aiterable = self._factory()

        async def _consume() -> None:
            async_iter = aiterable.__aiter__()
            try:
                async for value in async_iter:
                    if tb._stopped:
                        break
                    sink.next(value)
            finally:
                # Ensure cleanup if stopped mid-iteration
                aclose = getattr(async_iter, "aclose", None)
                if aclose is not None and tb._stopped:
                    await aclose()

        def on_result(_: Any) -> None:
            if not tb._stopped:
                tb._stopped = True
                sink.complete()

        def on_error(err: Exception) -> None:
            if not tb._stopped:
                tb._stopped = True
                sink.error(err)

        self._schedule(_consume(), on_result, on_error)
        return tb


def from_async_iter[T](
    iterable: AsyncIterable[T] | Callable[[], AsyncIterable[T]],
    *,
    schedule: ScheduleFn | None = None,
) -> _AsyncIterSource:
    """Create a source from an async iterable.

    Framework-agnostic: provide a ``schedule`` callback to use trio, anyio, etc.
    Default uses ``asyncio.run()`` in a daemon thread.

    Args:
        iterable: An async iterable, or a zero-arg factory that creates one.
            Factories allow resubscription (each subscriber gets a fresh iterator).
        schedule: ``(coro, on_result, on_error) -> None``.  Runs the coroutine
            and calls on_result/on_error when done.

    Returns:
        A Source that emits each value from the async iterable, then completes.
    """
    if callable(iterable) and not hasattr(iterable, "__aiter__"):
        factory = iterable
    else:
        _iter = iterable

        def factory() -> AsyncIterable[T]:
            return _iter

    return _AsyncIterSource(factory, schedule or thread_schedule)
