"""Computed store with dirty tracking, caching, and diamond resolution.

Fully lazy: no computation or connection at construction. Connects on first
subscriber, disconnects when last subscriber leaves. get() pull-computes
from deps when disconnected (always fresh).
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
from .types import NOOP_TALKBACK, _CallbackSink, _NodeTalkback


class DerivedImpl:
    """Internal implementation of the derived computed store."""

    __slots__ = (
        "_output",
        "_is_multi",
        "_upstream_talkbacks",
        "_cached_value",
        "_deps",
        "_fn",
        "_eq_fn",
        "_dirty_deps",
        "_connected",
        "_completed",
        "_has_cached",
        "_any_data",
        "_status",
    )

    def __init__(
        self,
        deps: list[Any],
        fn: Any,
        *,
        equals: Any = None,
    ) -> None:
        self._deps = deps
        self._fn = fn
        self._eq_fn = equals
        self._output: Any = None
        self._is_multi = False
        self._upstream_talkbacks: list[Any] = []
        self._cached_value: Any = None
        self._dirty_deps = Bitmask()
        self._connected = False
        self._completed = False
        self._has_cached = False
        self._any_data = False
        self._status = NodeStatus.DISCONNECTED

    # --- Output slot management ---

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

    # --- Recompute ---

    def _recompute(self) -> None:
        try:
            result = self._fn()
        except Exception as err:
            self._handle_end(err)
            return
        if self._eq_fn is not None and self._has_cached and self._eq_fn(self._cached_value, result):
            self._status = NodeStatus.RESOLVED
            self._dispatch_signal(Signal.RESOLVED)
            return
        self._cached_value = result
        self._has_cached = True
        self._status = NodeStatus.SETTLED
        self._dispatch_next(result)

    # --- Connection ---

    def _lazy_connect(self) -> None:
        if self._connected or self._completed:
            return
        try:
            self._cached_value = self._fn()
        except Exception as err:
            self._handle_end(err)
            return
        self._has_cached = True
        self._status = NodeStatus.SETTLED
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
            self._connect_multi_dep()

    def _connect_single_dep(self) -> None:
        """Single-dep: no bitmask, direct state machine with boolean dirty flag."""
        dirty = False

        def on_next(value: Any) -> None:
            nonlocal dirty
            if self._completed:
                return
            if dirty:
                dirty = False
                self._recompute()
            else:
                # DATA without prior DIRTY — synthesize DIRTY for downstream
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
                # Forward unknown/lifecycle signals
                self._dispatch_signal(sig)

        sink = _CallbackSink(on_next, on_signal, lambda: self._handle_end(None), self._handle_end)
        tb = self._deps[0].subscribe(sink)
        self._upstream_talkbacks.append(tb)

    def _connect_multi_dep(self) -> None:
        """Multi-dep: bitmask-based diamond resolution."""
        for i in range(len(self._deps)):
            if self._completed:
                break
            self._connect_one_dep(i)

    def _connect_one_dep(self, dep_index: int) -> None:
        def on_next(value: Any) -> None:
            if self._completed:
                return
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

        def on_signal(sig: Signal) -> None:
            if self._completed:
                return
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

        sink = _CallbackSink(on_next, on_signal, lambda: self._handle_end(None), self._handle_end)
        tb = self._deps[dep_index].subscribe(sink)
        self._upstream_talkbacks.append(tb)

    # --- Disconnect & end ---

    def _disconnect_upstream(self) -> None:
        for tb in self._upstream_talkbacks:
            tb.stop()
        self._upstream_talkbacks.clear()
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
            tb.stop()
        self._upstream_talkbacks.clear()
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

    # --- Lifecycle signals (from downstream via talkback) ---

    def _handle_lifecycle_signal(self, sig: Signal) -> None:
        if self._completed:
            return
        if sig is Signal.TEARDOWN:
            for tb in self._upstream_talkbacks:
                tb.signal(Signal.TEARDOWN)
            self._handle_end(None)
            return
        if sig is Signal.RESET:
            self._has_cached = False
            self._any_data = False
            self._dirty_deps.reset()
        for tb in self._upstream_talkbacks:
            tb.signal(sig)

    # --- Public API ---

    def get(self) -> Any:
        if self._connected:
            if not self._has_cached:
                # Cache invalidated (e.g. by RESET) — pull-compute on demand.
                result = self._fn()
                self._cached_value = result
                self._has_cached = True
                return result
            return self._cached_value
        if self._completed:
            if self._status is NodeStatus.ERRORED:
                raise self._cached_value
            return self._cached_value
        # Disconnected: pull-compute from deps
        result = self._fn()
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


def derived(
    deps: list[Any],
    fn: Any,
    *,
    equals: Any = None,
) -> DerivedImpl:
    """Create a computed store from explicit dependencies with diamond-safe dirty tracking.

    Fully lazy: connects when subscribed; ``get()`` pull-computes when
    disconnected without wiring upstream.
    """
    return DerivedImpl(deps, fn, equals=equals)


def derived_from(dep: Any, *, equals: Any = None) -> DerivedImpl:
    """Create a single-dep derived that mirrors the dependency's value (identity mode)."""
    return DerivedImpl([dep], lambda: dep.get(), equals=equals)
