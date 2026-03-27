"""Computed store with dynamic dependency tracking.

Like derived() but deps are discovered at runtime via a tracking ``get``
function, and can change between recomputations. Deps are re-tracked on
each recomputation and upstream connections are rewired when deps change.
"""

from __future__ import annotations

from typing import Any

from .bitmask import Bitmask
from .protocol import (
    NodeStatus,
    Signal,
    begin_deferred_start,
    end_deferred_start,
)
from .subgraph_locks import ensure_registered, union_nodes
from .types import NOOP_TALKBACK, _CallbackSink, _NodeTalkback


class DynamicDerivedImpl:
    """Internal implementation of dynamic_derived."""

    __slots__ = (
        "_output",
        "_is_multi",
        "_upstream_talkbacks",
        "_cached_value",
        "_deps",
        "_possible_deps",
        "_tracking_fn",
        "_eq_fn",
        "_dirty_deps",
        "_connected",
        "_completed",
        "_has_cached",
        "_any_data",
        "_recomputing",
        "_rewiring",
        "_rewire_queue",
        "_status",
        "_tracked_deps",
        "_tracking_set",
        "__weakref__",
    )

    def __init__(self, possible_deps: list[Any], fn: Any, *, equals: Any = None) -> None:
        self._possible_deps: frozenset[Any] = frozenset(possible_deps)
        self._tracking_fn = fn
        self._eq_fn = equals
        self._output: Any = None
        self._is_multi = False
        self._upstream_talkbacks: list[Any] = []
        self._cached_value: Any = None
        self._deps: list[Any] = []
        self._dirty_deps = Bitmask()
        self._connected = False
        self._completed = False
        self._has_cached = False
        self._any_data = False
        self._recomputing = False
        self._rewiring = False
        self._rewire_queue: list[tuple[int, int, Any]] | None = None  # (dep_index, kind, data)
        self._status = NodeStatus.DISCONNECTED
        self._tracked_deps: list[Any] = []
        self._tracking_set: set[Any] | None = None
        ensure_registered(self)
        for dep in possible_deps:
            union_nodes(self, dep)

    # --- Output slot ---

    def _add_sink(self, sink: Any) -> None:
        if self._output is None:
            self._output = sink
        elif not self._is_multi:
            self._output = {self._output, sink}
            self._is_multi = True
        else:
            self._output.add(sink)

    def _remove_sink(self, sink: Any) -> None:
        if self._output is None:
            return
        if self._is_multi:
            self._output.discard(sink)
            if len(self._output) == 1:
                self._output = next(iter(self._output))
                self._is_multi = False
            elif len(self._output) == 0:
                self._output = None
                self._is_multi = False
                self._disconnect_upstream()
        elif self._output is sink:
            self._output = None
            self._disconnect_upstream()

    # --- Dispatch ---

    def _dispatch_next(self, value: Any) -> None:
        output = self._output
        if output is None:
            return
        if self._is_multi:
            for sink in tuple(output):
                sink.next(value)
        else:
            output.next(value)

    def _dispatch_signal(self, sig: Signal) -> None:
        output = self._output
        if output is None:
            return
        if self._is_multi:
            for sink in tuple(output):
                sink.signal(sig)
        else:
            output.signal(sig)

    # --- Tracking get ---

    def _track_get(self, store: Any) -> Any:
        assert self._tracking_set is not None
        if store not in self._possible_deps:
            raise ValueError(
                f"Store {store!r} not in declared possible_deps. "
                f"All stores accessed via get() must be declared upfront."
            )
        if store not in self._tracking_set:
            self._tracking_set.add(store)
            self._tracked_deps.append(store)
        return store.get()

    # --- Recompute ---

    def _recompute(self) -> None:
        if self._recomputing:
            return
        self._recomputing = True
        self._tracked_deps = []
        self._tracking_set = set()
        try:
            result = self._tracking_fn(self._track_get)
        except Exception as err:
            self._tracking_set = None
            self._recomputing = False
            self._handle_end(err)
            return
        self._tracking_set = None
        if self._connected:
            self._maybe_rewire()
        self._recomputing = False
        if self._eq_fn is not None and self._has_cached and self._eq_fn(self._cached_value, result):
            self._status = NodeStatus.RESOLVED
            self._dispatch_signal(Signal.RESOLVED)
            return
        self._cached_value = result
        self._has_cached = True
        self._status = NodeStatus.SETTLED
        self._dispatch_next(result)

    def _maybe_rewire(self) -> None:
        new_deps = self._tracked_deps
        old_deps = self._deps
        # Subgraph unions already done at construction via possible_deps.
        # Fast path: same deps in same order
        if len(new_deps) == len(old_deps):
            same = True
            for i in range(len(new_deps)):
                if new_deps[i] is not old_deps[i]:
                    same = False
                    break
            if same:
                return
        self._rewiring = True
        self._rewire_queue = []
        for tb in self._upstream_talkbacks:
            if tb is not None:
                tb.stop()
        self._deps = new_deps
        self._upstream_talkbacks = [None] * len(new_deps)
        self._dirty_deps = Bitmask()
        for i in range(len(new_deps)):
            self._connect_one_dep(i)
        self._rewiring = False
        # Replay any signals queued during rewire
        queued = self._rewire_queue
        self._rewire_queue = None
        if queued:
            for dep_idx, kind, data in queued:
                if self._completed:
                    break
                if kind == DynamicDerivedImpl._REWIRE_DATA:
                    self._handle_dep_signal_data(dep_idx, data)
                else:
                    self._handle_dep_signal_state(dep_idx, data)

    # --- Connection ---

    def _lazy_connect(self) -> None:
        if self._connected or self._completed:
            return
        self._tracked_deps = []
        self._tracking_set = set()
        try:
            self._cached_value = self._tracking_fn(self._track_get)
        except Exception as err:
            self._tracking_set = None
            self._tracked_deps = []
            self._handle_end(err)
            return
        self._tracking_set = None
        self._has_cached = True
        self._status = NodeStatus.SETTLED
        self._deps = self._tracked_deps
        # Subgraph unions already done at construction via possible_deps.
        self._dirty_deps = Bitmask()
        begin_deferred_start()
        self._connect_upstream()
        if not self._completed:
            self._connected = True
        end_deferred_start()

    def _connect_upstream(self) -> None:
        self._upstream_talkbacks.clear()
        if len(self._deps) == 1:
            self._connect_single_dep()
        else:
            for i in range(len(self._deps)):
                if self._completed:
                    break
                self._connect_one_dep(i)

    def _connect_single_dep(self) -> None:
        dirty = False

        def on_next(value: Any) -> None:
            nonlocal dirty
            if self._completed:
                return
            if dirty:
                dirty = False
                self._recompute()
            else:
                self._status = NodeStatus.DIRTY
                self._dispatch_signal(Signal.DIRTY)
                self._recompute()

        def on_signal(sig: Signal) -> None:
            nonlocal dirty
            if self._completed:
                return
            if sig is Signal.DIRTY:
                if dirty:
                    return
                dirty = True
                self._status = NodeStatus.DIRTY
                self._dispatch_signal(Signal.DIRTY)
            elif sig is Signal.RESOLVED:
                if dirty:
                    dirty = False
                    self._status = NodeStatus.RESOLVED
                    self._dispatch_signal(Signal.RESOLVED)
            else:
                self._dispatch_signal(sig)

        sink = _CallbackSink(on_next, on_signal, lambda: self._handle_end(None), self._handle_end)
        tb = self._deps[0].subscribe(sink)
        self._upstream_talkbacks.append(tb)

    _REWIRE_DATA = 0
    _REWIRE_SIGNAL = 1

    def _connect_one_dep(self, dep_index: int) -> None:
        def on_next(value: Any) -> None:
            if self._completed:
                return
            if self._rewiring:
                if self._rewire_queue is not None:
                    self._rewire_queue.append((dep_index, DynamicDerivedImpl._REWIRE_DATA, value))
                return
            self._handle_dep_signal_data(dep_index, value)

        def on_signal(sig: Signal) -> None:
            if self._completed:
                return
            if self._rewiring:
                if self._rewire_queue is not None:
                    self._rewire_queue.append((dep_index, DynamicDerivedImpl._REWIRE_SIGNAL, sig))
                return
            self._handle_dep_signal_state(dep_index, sig)

        sink = _CallbackSink(on_next, on_signal, lambda: self._handle_end(None), self._handle_end)
        tb = self._deps[dep_index].subscribe(sink)
        if dep_index < len(self._upstream_talkbacks):
            self._upstream_talkbacks[dep_index] = tb
        else:
            self._upstream_talkbacks.append(tb)

    def _handle_dep_signal_state(self, dep_index: int, sig: Signal) -> None:
        if sig is Signal.DIRTY:
            was_empty = self._dirty_deps.empty()
            self._dirty_deps.set(dep_index)
            if was_empty:
                self._any_data = False
                self._status = NodeStatus.DIRTY
                self._dispatch_signal(Signal.DIRTY)
        elif sig is Signal.RESOLVED:
            if self._dirty_deps.test(dep_index):
                self._dirty_deps.clear(dep_index)
                if self._dirty_deps.empty():
                    if self._any_data:
                        self._recompute()
                    else:
                        self._status = NodeStatus.RESOLVED
                        self._dispatch_signal(Signal.RESOLVED)
        else:
            self._dispatch_signal(sig)

    def _handle_dep_signal_data(self, dep_index: int, value: Any) -> None:
        if self._dirty_deps.test(dep_index):
            self._dirty_deps.clear(dep_index)
            self._any_data = True
            if self._dirty_deps.empty():
                self._recompute()
        else:
            if self._dirty_deps.empty():
                self._status = NodeStatus.DIRTY
                self._dispatch_signal(Signal.DIRTY)
                self._recompute()
            else:
                self._any_data = True

    # --- Disconnect & end ---

    def _disconnect_upstream(self) -> None:
        for tb in self._upstream_talkbacks:
            if tb is not None:
                tb.stop()
        self._upstream_talkbacks.clear()
        self._deps = []
        self._tracked_deps = []
        self._connected = False
        self._any_data = False
        self._status = NodeStatus.DISCONNECTED
        self._dirty_deps.reset()

    def _handle_end(self, error: Any) -> None:
        self._completed = True
        if error is not None:
            self._status = NodeStatus.ERRORED
            self._cached_value = error
        else:
            self._status = NodeStatus.COMPLETED
        for tb in self._upstream_talkbacks:
            if tb is not None:
                tb.stop()
        self._upstream_talkbacks.clear()
        self._deps = []
        self._tracked_deps = []
        self._connected = False
        self._dirty_deps.reset()
        output = self._output
        was_multi = self._is_multi
        self._output = None
        self._is_multi = False
        if output is not None:
            if was_multi:
                for sink in tuple(output):
                    try:
                        if error is not None:
                            sink.error(error)
                        else:
                            sink.complete()
                    except Exception:
                        pass
            else:
                if error is not None:
                    output.error(error)
                else:
                    output.complete()

    def _handle_lifecycle_signal(self, sig: Signal) -> None:
        if self._completed:
            return
        if sig is Signal.TEARDOWN:
            for tb in self._upstream_talkbacks:
                if tb is not None:
                    tb.signal(Signal.TEARDOWN)
            self._handle_end(None)
            return
        if sig is Signal.RESET:
            self._has_cached = False
            self._any_data = False
            self._dirty_deps.reset()
        for tb in self._upstream_talkbacks:
            if tb is not None:
                tb.signal(sig)

    # --- Public API ---

    def get(self) -> Any:
        if self._connected:
            if not self._has_cached:
                # Cache invalidated (e.g. by RESET) — pull-compute on demand.
                self._tracked_deps = []
                self._tracking_set = set()
                try:
                    result = self._tracking_fn(self._track_get)
                except Exception:
                    self._tracking_set = None
                    self._tracked_deps = []
                    raise
                self._tracking_set = None
                self._cached_value = result
                self._has_cached = True
                return result
            return self._cached_value
        if self._completed:
            if self._status is NodeStatus.ERRORED:
                raise self._cached_value
            return self._cached_value
        # Disconnected: pull-compute with tracking
        self._tracked_deps = []
        self._tracking_set = set()
        try:
            result = self._tracking_fn(self._track_get)
        except Exception:
            self._tracking_set = None
            self._tracked_deps = []
            raise
        self._tracking_set = None
        self._cached_value = result
        self._has_cached = True
        return result

    def subscribe(self, sink: Any) -> Any:
        if self._completed:
            if self._status is NodeStatus.ERRORED:
                sink.error(self._cached_value)
            else:
                sink.complete()
            return NOOP_TALKBACK
        if not self._connected:
            self._lazy_connect()
            if self._completed:
                if self._status is NodeStatus.ERRORED:
                    sink.error(self._cached_value)
                else:
                    sink.complete()
                return NOOP_TALKBACK
        self._add_sink(sink)
        return _NodeTalkback(self, sink)

    def __or__(self, op: Any) -> Any:
        return op(self)


def dynamic_derived(possible_deps: list[Any], fn: Any, *, equals: Any = None) -> DynamicDerivedImpl:
    """Create a computed store with dynamic dependency tracking.

    ``possible_deps`` declares the exhaustive superset of stores that ``fn``
    might read. Subgraph unions are performed at construction time for all
    declared deps. At runtime, ``fn`` receives a tracking ``get`` function —
    call ``get(store)`` to read a store's value and subscribe to it.
    Accessing a store not in ``possible_deps`` raises ``ValueError``.

    Dependencies are re-tracked on each recomputation and upstream
    connections are rewired when the active subset of deps changes.
    """
    return DynamicDerivedImpl(possible_deps, fn, equals=equals)
