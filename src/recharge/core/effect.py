"""Side-effect runner.

Connects eagerly to deps on creation, runs fn() inline when all dirty deps
resolve. Returns a dispose callable with an attached signal() method.
"""

from __future__ import annotations

from typing import Any

from .bitmask import Bitmask
from .protocol import (
    Signal,
    begin_deferred_start,
    end_deferred_start,
    is_lifecycle_signal,
)
from .subgraph_locks import ensure_registered, union_nodes
from .types import _CallbackSink


class _EffectState:
    """Mutable state shared across effect closures."""

    __slots__ = (
        "cleanup",
        "talkbacks",
        "disposed",
        "dirty_deps",
        "any_data",
        "generation",
        "sink_gens",
        "fn",
        "__weakref__",
    )

    def __init__(self, fn: Any) -> None:
        self.cleanup: Any = None
        self.talkbacks: list[Any] = []
        self.disposed = False
        self.dirty_deps = Bitmask()
        self.any_data = False
        self.generation = 0
        self.sink_gens: list[int] = []
        self.fn = fn

    def run(self) -> None:
        if self.disposed:
            return
        self._run_cleanup()
        result = self.fn()
        if callable(result):
            self.cleanup = result

    def _run_cleanup(self) -> None:
        """Run and clear cleanup. Always nulls cleanup even if it raises."""
        if self.cleanup is not None:
            fn, self.cleanup = self.cleanup, None
            fn()

    def handle_lifecycle_signal(self, sig: Signal) -> None:
        if self.disposed:
            return
        if sig is Signal.TEARDOWN:
            for tb in self.talkbacks:
                tb.signal(Signal.TEARDOWN)
            self.talkbacks.clear()
            self.disposed = True
            self._run_cleanup()
            return
        if sig is Signal.RESET:
            self.generation += 1
            self.dirty_deps.reset()
            self.any_data = False
            # Update all sink_gens so dep closures accept post-RESET signals.
            # Without this, all closures reject signals (stale generation).
            for i in range(len(self.sink_gens)):
                self.sink_gens[i] = self.generation
            # Tear down side effects from the last run.
            # RESET means "clear transient state" — includes effect cleanup.
            self._run_cleanup()
        for tb in self.talkbacks:
            tb.signal(sig)

    def dispose(self) -> None:
        if self.disposed:
            return
        self.disposed = True
        self._run_cleanup()
        for tb in self.talkbacks:
            tb.stop()
        self.talkbacks.clear()


def effect(
    deps: list[Any],
    fn: Any,
) -> _Disposable:
    """Run a side effect when all dependencies have resolved after a change.

    Eagerly subscribes to deps on creation. Not a store — no get() or subscribe().

    Returns a dispose callable. Call ``dispose()`` to stop the effect.
    Call ``dispose.signal(sig)`` for lifecycle control (RESET, TEARDOWN, etc.).
    """
    es = _EffectState(fn)
    ensure_registered(es)
    for dep in deps:
        union_nodes(es, dep)

    begin_deferred_start()
    es.run()

    for i in range(len(deps)):
        if es.disposed:
            break
        _connect_dep(es, i, deps[i])

    end_deferred_start()

    return _Disposable(es.dispose, es.handle_lifecycle_signal)


def _connect_dep(es: _EffectState, dep_index: int, dep: Any) -> None:
    """Connect to a single dep. Separate function for correct closure capture."""
    es.sink_gens.append(es.generation)

    def on_next(value: Any) -> None:
        if es.disposed:
            return
        if es.sink_gens[dep_index] != es.generation:
            return
        if es.dirty_deps.test(dep_index):
            es.dirty_deps.clear(dep_index)
            es.any_data = True
            if es.dirty_deps.empty():
                es.run()
        else:
            if es.dirty_deps.empty():
                es.run()
            else:
                es.any_data = True

    def on_signal(sig: Signal) -> None:
        if es.disposed:
            return
        if is_lifecycle_signal(sig):
            es.handle_lifecycle_signal(sig)
            es.sink_gens[dep_index] = es.generation
            return
        if es.sink_gens[dep_index] != es.generation:
            return
        if sig is Signal.DIRTY:
            if es.dirty_deps.empty():
                es.any_data = False
            es.dirty_deps.set(dep_index)
        elif sig is Signal.RESOLVED:
            if es.dirty_deps.test(dep_index):
                es.dirty_deps.clear(dep_index)
                if es.dirty_deps.empty() and es.any_data:
                    es.run()

    def on_complete() -> None:
        es.dispose()

    def on_error(err: Exception) -> None:
        es.dispose()

    sink = _CallbackSink(on_next, on_signal, on_complete, on_error)
    tb = dep.subscribe(sink)
    es.talkbacks.append(tb)


class _Disposable:
    """Callable dispose with attached signal() method."""

    __slots__ = ("_dispose", "signal")

    def __init__(self, dispose_fn: Any, signal_fn: Any) -> None:
        self._dispose = dispose_fn
        self.signal = signal_fn

    def __call__(self) -> None:
        self._dispose()
