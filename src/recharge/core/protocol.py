"""Signal vocabulary, node status, and batch mechanism."""

from __future__ import annotations

from contextlib import contextmanager
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


class Signal(Enum):
    """Control signals for the reactive graph."""

    DIRTY = auto()
    RESOLVED = auto()
    RESET = auto()
    PAUSE = auto()
    RESUME = auto()
    TEARDOWN = auto()


class NodeStatus(Enum):
    """Node lifecycle status."""

    DISCONNECTED = auto()
    DIRTY = auto()
    SETTLED = auto()
    RESOLVED = auto()
    COMPLETED = auto()
    ERRORED = auto()


_LIFECYCLE_SIGNALS = frozenset({Signal.RESET, Signal.PAUSE, Signal.RESUME, Signal.TEARDOWN})


def is_lifecycle_signal(sig: Signal) -> bool:
    """Returns True for lifecycle signals (RESET, PAUSE, RESUME, TEARDOWN)."""
    return sig in _LIFECYCLE_SIGNALS


# ---------------------------------------------------------------------------
# Callbag type tags — used by operator handler for TS API compatibility.
# These encode the *channel* a signal travels on, not the signal itself.
# ---------------------------------------------------------------------------

DATA = 1
END = 2
STATE = 3


# ---------------------------------------------------------------------------
# Batch — defers DATA emissions; DIRTY propagates immediately
# ---------------------------------------------------------------------------


class _BatchState:
    __slots__ = ("depth", "draining", "emissions")

    def __init__(self) -> None:
        self.depth = 0
        self.draining = False
        self.emissions: list[Callable[[], None]] = []


_bs = _BatchState()


@contextmanager
def batch() -> Generator[None]:
    """Context manager that defers DATA emissions until the outermost batch exits.

    DIRTY signals propagate immediately so the graph knows what changed.
    Multiple set() calls within a batch coalesce — downstream sees one update.
    """
    _bs.depth += 1
    try:
        yield
    finally:
        _bs.depth -= 1
        if _bs.depth == 0 and not _bs.draining:
            _bs.draining = True
            try:
                i = 0
                while i < len(_bs.emissions):
                    _bs.emissions[i]()
                    i += 1
            finally:
                _bs.emissions.clear()
                _bs.draining = False


def is_batching() -> bool:
    """Returns True if currently inside a batch context."""
    return _bs.depth > 0


def defer_emission(fn: Callable[[], None]) -> None:
    """Queue a DATA emission for deferred dispatch at batch exit."""
    _bs.emissions.append(fn)


# ---------------------------------------------------------------------------
# Connection batching — defers producer start() until all deps are wired
# ---------------------------------------------------------------------------


class _ConnectState:
    __slots__ = ("depth", "pending")

    def __init__(self) -> None:
        self.depth = 0
        self.pending: list[Callable[[], None]] = []


_cs = _ConnectState()


def begin_deferred_start() -> None:
    """Begin deferring producer start() calls."""
    _cs.depth += 1


def end_deferred_start() -> None:
    """End deferring. Flush pending starts if outermost."""
    _cs.depth -= 1
    if _cs.depth == 0:
        pending = _cs.pending[:]
        _cs.pending.clear()
        for start in pending:
            start()


def defer_start(start: Callable[[], None]) -> None:
    """Defer or immediately run a producer start."""
    if _cs.depth > 0:
        _cs.pending.append(start)
    else:
        start()
