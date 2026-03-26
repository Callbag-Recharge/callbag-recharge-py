"""from_iter -- synchronous iterator to source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._talkback import StoppableTalkback

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .protocol import Sink, Talkback


class _IterSource[T]:
    """Source that emits values from a synchronous iterable.

    Listenable mode: on subscribe, pushes all values synchronously then completes.
    If the iterable is an iterator (single-use), subsequent subscribers get
    immediate completion.
    """

    __slots__ = ("_iterable",)

    def __init__(self, iterable: Iterable[T]) -> None:
        self._iterable = iterable

    def subscribe(self, sink: Sink[T], /) -> Talkback:
        tb = StoppableTalkback()
        # Push all values synchronously (listenable mode)
        for value in self._iterable:
            if tb._stopped:
                return tb
            sink.next(value)
        if not tb._stopped:
            sink.complete()
        return tb


def from_iter[T](iterable: Iterable[T]) -> _IterSource[T]:
    """Create a source from a synchronous iterable.

    On subscribe, emits each item synchronously, then completes.
    Strings are treated as sequences of characters (unlike from_any).
    """
    return _IterSource(iterable)
