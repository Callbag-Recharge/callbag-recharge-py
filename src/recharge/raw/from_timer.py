"""from_timer -- delay source using threading.Timer (no asyncio)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocol import Signal, Sink, Talkback


class _TimerTalkback:
    """Talkback that cancels the timer on stop."""

    __slots__ = ("_timer", "_stopped")

    def __init__(self) -> None:
        self._stopped = False
        self._timer: threading.Timer | None = None

    def pull(self) -> None:
        pass  # timer is push-only

    def stop(self) -> None:
        if not self._stopped:
            self._stopped = True
            if self._timer is not None:
                self._timer.cancel()

    def signal(self, sig: Signal) -> None:
        pass


class _TimerSource:
    """Source that emits None once after *seconds*, then completes.

    Uses threading.Timer -- no asyncio dependency.
    Cancellable via talkback.stop().
    """

    __slots__ = ("_seconds",)

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def subscribe(self, sink: Sink[None], /) -> Talkback:
        tb = _TimerTalkback()

        def _fire() -> None:
            try:
                if not tb._stopped:
                    sink.next(None)
                if not tb._stopped:
                    tb._stopped = True
                    sink.complete()
            except Exception as e:
                if not tb._stopped:
                    tb._stopped = True
                    sink.error(e)

        timer = threading.Timer(self._seconds, _fire)
        tb._timer = timer
        timer.daemon = True
        timer.start()
        return tb


def from_timer(seconds: float) -> _TimerSource:
    """Create a source that emits None after *seconds*, then completes.

    Uses threading.Timer (no asyncio dependency).
    The timer is cancelled if the subscriber calls talkback.stop().
    """
    if seconds < 0:
        raise ValueError(f"seconds must be non-negative, got {seconds}")
    return _TimerSource(seconds)
