"""Signal vocabulary, node status, and batch mechanism."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from enum import Enum, auto
from typing import TYPE_CHECKING

from ..raw.protocol import Signal as Signal

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


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
#
# Each thread has its own batch state so concurrent batches are isolated.
# ---------------------------------------------------------------------------

_batch_tls = threading.local()


class _BatchState:
    __slots__ = ("depth", "draining", "emissions")

    def __init__(self) -> None:
        self.depth = 0
        self.draining = False
        self.emissions: list[tuple[object, Callable[[], None]]] = []


def _get_batch_state() -> _BatchState:
    bs: _BatchState | None = getattr(_batch_tls, "state", None)
    if bs is None:
        bs = _BatchState()
        _batch_tls.state = bs
    return bs


@contextmanager
def batch() -> Generator[None]:
    """Context manager that defers DATA emissions until the outermost batch exits.

    DIRTY signals propagate immediately so the graph knows what changed.
    Multiple set() calls within a batch coalesce — downstream sees one update.

    Each thread has its own batch context — batches do not span threads.
    """
    # Import here to avoid circular import at module level.
    from .subgraph_locks import acquire_subgraph_write_lock_with_defer

    bs = _get_batch_state()
    bs.depth += 1
    try:
        yield
    finally:
        bs.depth -= 1
        if bs.depth == 0 and not bs.draining:
            bs.draining = True
            first_error: Exception | None = None
            try:
                i = 0
                while i < len(bs.emissions):
                    node, fn = bs.emissions[i]
                    try:
                        with acquire_subgraph_write_lock_with_defer(node):
                            fn()
                    except Exception as e:
                        if first_error is None:
                            first_error = e
                    i += 1
            finally:
                bs.emissions.clear()
                bs.draining = False
            if first_error is not None:
                raise first_error


def is_batching() -> bool:
    """Returns True if currently inside a batch context on this thread."""
    return _get_batch_state().depth > 0


def defer_emission(node: object, fn: Callable[[], None]) -> None:
    """Queue a DATA emission for deferred dispatch at batch exit.

    *node* identifies which subgraph the emission belongs to so the drain
    loop can re-acquire the correct write lock.
    """
    _get_batch_state().emissions.append((node, fn))


# ---------------------------------------------------------------------------
# Connection batching — defers producer start() until all deps are wired
#
# Each thread has its own connection state so concurrent graph construction
# on independent subgraphs is isolated.
# ---------------------------------------------------------------------------

_connect_tls = threading.local()


class _ConnectState:
    __slots__ = ("depth", "pending")

    def __init__(self) -> None:
        self.depth = 0
        self.pending: list[Callable[[], None]] = []


def _get_connect_state() -> _ConnectState:
    cs: _ConnectState | None = getattr(_connect_tls, "state", None)
    if cs is None:
        cs = _ConnectState()
        _connect_tls.state = cs
    return cs


def begin_deferred_start() -> None:
    """Begin deferring producer start() calls."""
    _get_connect_state().depth += 1


def end_deferred_start() -> None:
    """End deferring. Flush pending starts if outermost."""
    cs = _get_connect_state()
    if cs.depth <= 0:
        raise RuntimeError("end_deferred_start() called without matching begin_deferred_start()")
    cs.depth -= 1
    if cs.depth == 0:
        pending = cs.pending[:]
        cs.pending.clear()
        for start in pending:
            start()


def defer_start(start: Callable[[], None]) -> None:
    """Defer or immediately run a producer start."""
    cs = _get_connect_state()
    if cs.depth > 0:
        cs.pending.append(start)
    else:
        start()
