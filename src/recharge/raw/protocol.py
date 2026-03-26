"""Foundational protocol types for the reactive graph (Tier -1).

This module defines the core protocol vocabulary: Signal enum and the
Sink/Talkback/Source Protocol classes.  Every other tier imports from here.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Protocol, TypeVar

T_co = TypeVar("T_co", covariant=True)
T_contra = TypeVar("T_contra", contravariant=True)


class Signal(Enum):
    """Control signals for the reactive graph."""

    DIRTY = auto()
    RESOLVED = auto()
    RESET = auto()
    PAUSE = auto()
    RESUME = auto()
    TEARDOWN = auto()


class Sink(Protocol[T_contra]):
    """Receives signals from upstream (source -> sink direction)."""

    def next(self, value: T_contra, /) -> None: ...
    def signal(self, sig: Signal, /) -> None: ...
    def complete(self) -> None: ...
    def error(self, err: Exception, /) -> None: ...


class Talkback(Protocol):
    """Sends signals upstream (sink -> source direction)."""

    def pull(self) -> None: ...
    def stop(self) -> None: ...
    def signal(self, sig: Signal, /) -> None: ...


class Source(Protocol[T_co]):
    """Subscribable -- the subscribe handshake."""

    def subscribe(self, sink: Sink[T_co], /) -> Talkback: ...
