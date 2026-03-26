"""Shared talkback base for raw/ source primitives."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocol import Signal


class StoppableTalkback:
    """Minimal talkback with a stoppable flag.  Pull and signal are no-ops."""

    __slots__ = ("_stopped",)

    def __init__(self) -> None:
        self._stopped = False

    def pull(self) -> None:
        pass

    def stop(self) -> None:
        self._stopped = True

    def signal(self, sig: Signal) -> None:
        pass
