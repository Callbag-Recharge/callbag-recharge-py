"""raw_subscribe -- lowest-level subscribe (pure protocol, no store awareness)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from .protocol import Signal, Source, Talkback


class _StoppedFlag:
    """Shared mutable flag between _RawSink and _RawSubscription."""

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = False


class _RawSubscription:
    """Handle returned by raw_subscribe.  Call .unsubscribe() to disconnect."""

    __slots__ = ("_talkback", "_flag")

    def __init__(self, talkback: Talkback, flag: _StoppedFlag) -> None:
        self._talkback = talkback
        self._flag = flag

    def unsubscribe(self) -> None:
        if not self._flag.value:
            self._flag.value = True
            self._talkback.stop()

    def __enter__(self) -> _RawSubscription:
        return self

    def __exit__(self, *args: Any) -> None:
        self.unsubscribe()


class _RawSink:
    """Callback-based sink for raw_subscribe."""

    __slots__ = ("_on_next", "_on_end", "_flag")

    def __init__(
        self,
        on_next: Callable[[Any], None],
        on_end: Callable[[Exception | None], None] | None,
        flag: _StoppedFlag,
    ) -> None:
        self._on_next = on_next
        self._on_end = on_end
        self._flag = flag

    def next(self, value: Any) -> None:
        if not self._flag.value:
            self._on_next(value)

    def signal(self, sig: Signal) -> None:
        pass  # raw_subscribe ignores STATE signals

    def complete(self) -> None:
        if not self._flag.value:
            self._flag.value = True
            if self._on_end is not None:
                self._on_end(None)

    def error(self, err: Exception) -> None:
        if not self._flag.value:
            self._flag.value = True
            if self._on_end is not None:
                self._on_end(err)


def raw_subscribe(
    source: Source[Any],
    on_next: Callable[[Any], None],
    on_end: Callable[[Exception | None], None] | None = None,
) -> _RawSubscription:
    """Subscribe to a source with plain callbacks.

    Args:
        source: Any Source-compatible object.
        on_next: Called with each DATA value.
        on_end: Called on completion (None) or error (Exception).

    Returns:
        A subscription handle with .unsubscribe() and context manager support.
    """
    flag = _StoppedFlag()
    sink = _RawSink(on_next, on_end, flag)
    talkback = source.subscribe(sink)
    return _RawSubscription(talkback, flag)
