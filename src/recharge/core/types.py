"""Protocol classes and internal helpers for the reactive graph."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from ..raw.protocol import Signal as Signal  # noqa: TC001
from ..raw.protocol import Sink as Sink  # noqa: TC001
from ..raw.protocol import Source as Source  # noqa: TC001
from ..raw.protocol import Talkback as Talkback  # noqa: TC001

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


# ---------------------------------------------------------------------------
# Public protocol classes (Sink, Talkback, Source imported from raw/)
# ---------------------------------------------------------------------------


class Store(Protocol[T_co]):
    """Read-only store — get() + subscribe()."""

    def get(self) -> T_co: ...
    def subscribe(self, sink: Sink[T_co], /) -> Talkback: ...


StoreOperator = Any  # Callable[[Store[A]], Store[B]] — proper typing in pipe overloads


# ---------------------------------------------------------------------------
# Subscription — user-facing handle from subscribe()
# ---------------------------------------------------------------------------


class Subscription:
    """Handle returned by subscribe(). Supports context manager."""

    __slots__ = ("_talkback",)

    def __init__(self, talkback: Talkback) -> None:
        self._talkback = talkback

    def unsubscribe(self) -> None:
        """Disconnect from the store."""
        self._talkback.stop()

    def signal(self, sig: Signal) -> None:
        """Send a lifecycle signal upstream via talkback."""
        self._talkback.signal(sig)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *args: Any) -> None:
        self.unsubscribe()


# ---------------------------------------------------------------------------
# Internal helpers — shared across core modules
# ---------------------------------------------------------------------------


class _NoopTalkback:
    """Talkback that does nothing (for completed nodes)."""

    __slots__ = ()

    def pull(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def signal(self, sig: Signal) -> None:
        pass


NOOP_TALKBACK = _NoopTalkback()


class _NodeTalkback:
    """Talkback returned to downstream subscribers."""

    __slots__ = ("_node", "_sink", "_stopped")

    def __init__(self, node: Any, sink: Any) -> None:
        self._node = node
        self._sink = sink
        self._stopped = False

    def pull(self) -> None:
        if not self._stopped:
            self._sink.next(self._node.get())

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._node._remove_sink(self._sink)

    def signal(self, sig: Signal) -> None:
        if not self._stopped:
            self._node._handle_lifecycle_signal(sig)


class _CallbackSink:
    """Lightweight sink that delegates to callbacks."""

    __slots__ = ("_on_next", "_on_signal", "_on_complete", "_on_error")

    def __init__(
        self,
        on_next: Any,
        on_signal: Any,
        on_complete: Any,
        on_error: Any,
    ) -> None:
        self._on_next = on_next
        self._on_signal = on_signal
        self._on_complete = on_complete
        self._on_error = on_error

    def next(self, value: Any) -> None:
        self._on_next(value)

    def signal(self, sig: Signal) -> None:
        self._on_signal(sig)

    def complete(self) -> None:
        self._on_complete()

    def error(self, err: Exception) -> None:
        self._on_error(err)
