"""General-purpose transform primitive.

Receives all signal types from upstream deps and decides what to forward.
Building block for tier 1 operators; participates in diamond resolution
when you forward STATE correctly.
"""

from __future__ import annotations

from typing import Any

from .protocol import DATA, END, STATE, NodeStatus, Signal
from .subgraph_locks import ensure_registered, union_nodes
from .types import NOOP_TALKBACK, _CallbackSink, _NodeTalkback


class _Actions:
    """Actions API for operator init functions. Bound to a generation."""

    __slots__ = ("emit", "seed", "signal", "complete", "error", "disconnect")

    def __init__(
        self,
        emit: Any,
        seed: Any,
        signal: Any,
        complete: Any,
        error: Any,
        disconnect: Any,
    ) -> None:
        self.emit = emit
        self.seed = seed
        self.signal = signal
        self.complete = complete
        self.error = error
        self.disconnect = disconnect


class OperatorImpl:
    """Internal implementation of the operator transform."""

    __slots__ = (
        "_value",
        "_output",
        "_is_multi",
        "_upstream_talkbacks",
        "_handler",
        "_deps",
        "_init",
        "_getter_fn",
        "_initial",
        "_error_data",
        "_generation",
        "_completed",
        "_reset_on_teardown",
        "_resubscribable",
        "_status",
        "__weakref__",
    )

    def __init__(
        self,
        deps: list[Any],
        init: Any,
        *,
        initial: Any = None,
        getter: Any = None,
        reset_on_teardown: bool = False,
        resubscribable: bool = False,
    ) -> None:
        self._value = initial
        self._initial = initial
        self._deps = deps
        self._init = init
        self._getter_fn = getter
        self._output: Any = None
        self._is_multi = False
        self._upstream_talkbacks: list[Any] = []
        self._handler: Any = None
        self._error_data: Any = None
        self._generation = 0
        self._completed = False
        self._reset_on_teardown = reset_on_teardown
        self._resubscribable = resubscribable
        self._status = NodeStatus.DISCONNECTED
        ensure_registered(self)
        for dep in deps:
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

    # --- Actions ---

    def _create_actions(self, gen: int) -> _Actions:
        talkbacks = self._upstream_talkbacks

        def seed(value: Any) -> None:
            if gen != self._generation:
                return
            self._value = value

        def emit(value: Any) -> None:
            if gen != self._generation:
                return
            self._value = value
            self._status = NodeStatus.SETTLED
            self._dispatch_next(value)

        def signal(sig: Signal) -> None:
            if gen != self._generation:
                return
            if sig is Signal.DIRTY:
                self._status = NodeStatus.DIRTY
            elif sig is Signal.RESOLVED:
                self._status = NodeStatus.RESOLVED
            self._dispatch_signal(sig)

        def complete() -> None:
            if gen != self._generation:
                return
            self._generation += 1
            self._completed = True
            self._status = NodeStatus.COMPLETED
            self._handler = None
            for tb in talkbacks:
                if tb is not None:
                    tb.stop()
            if self._reset_on_teardown:
                self._value = self._initial
            output = self._output
            was_multi = self._is_multi
            self._output = None
            self._is_multi = False
            if output is not None:
                if was_multi:
                    for sink in tuple(output):
                        try:  # noqa: SIM105
                            sink.complete()
                        except Exception:
                            pass
                else:
                    output.complete()

        def error(err: Any) -> None:
            if gen != self._generation:
                return
            self._generation += 1
            self._error_data = err
            self._completed = True
            self._status = NodeStatus.ERRORED
            self._handler = None
            for tb in talkbacks:
                if tb is not None:
                    tb.stop()
            if self._reset_on_teardown:
                self._value = self._initial
            output = self._output
            was_multi = self._is_multi
            self._output = None
            self._is_multi = False
            if output is not None:
                if was_multi:
                    for sink in tuple(output):
                        try:  # noqa: SIM105
                            sink.error(err)
                        except Exception:
                            pass
                else:
                    output.error(err)

        def disconnect(dep: int | None = None) -> None:
            if dep is not None:
                if dep < len(talkbacks) and talkbacks[dep] is not None:
                    talkbacks[dep].stop()
                    talkbacks[dep] = None
            else:
                for tb in talkbacks:
                    if tb is not None:
                        tb.stop()
                for j in range(len(talkbacks)):
                    talkbacks[j] = None

        return _Actions(emit, seed, signal, complete, error, disconnect)

    # --- Connection ---

    def _connect_upstream(self) -> None:
        self._upstream_talkbacks = [None] * len(self._deps)
        self._generation += 1
        gen = self._generation
        actions = self._create_actions(gen)
        self._handler = self._init(actions)

        for i in range(len(self._deps)):
            if gen != self._generation:
                break
            self._connect_one_dep(i, gen)

    def _connect_one_dep(self, dep_index: int, gen: int) -> None:
        def on_next(value: Any) -> None:
            if self._handler is not None:
                self._handler(dep_index, DATA, value)

        def on_signal(sig: Signal) -> None:
            if self._handler is not None:
                self._handler(dep_index, STATE, sig)

        def on_complete() -> None:
            if self._handler is not None:
                self._handler(dep_index, END, None)

        def on_error(err: Exception) -> None:
            if self._handler is not None:
                self._handler(dep_index, END, err)

        sink = _CallbackSink(on_next, on_signal, on_complete, on_error)
        tb = self._deps[dep_index].subscribe(sink)
        if gen == self._generation:
            self._upstream_talkbacks[dep_index] = tb

    def _disconnect_upstream(self) -> None:
        for tb in self._upstream_talkbacks:
            if tb is not None:
                tb.stop()
        self._upstream_talkbacks.clear()
        self._handler = None
        self._status = NodeStatus.DISCONNECTED
        if self._reset_on_teardown:
            self._value = self._initial

    # --- Lifecycle ---

    def _handle_lifecycle_signal(self, sig: Signal) -> None:
        if self._completed:
            return
        if sig is Signal.TEARDOWN:
            if self._handler is not None:
                self._handler(0, STATE, Signal.TEARDOWN)
            for tb in self._upstream_talkbacks:
                if tb is not None:
                    tb.signal(Signal.TEARDOWN)
            self._generation += 1
            self._completed = True
            self._status = NodeStatus.COMPLETED
            self._handler = None
            for tb in self._upstream_talkbacks:
                if tb is not None:
                    tb.stop()
            if self._reset_on_teardown:
                self._value = self._initial
            output = self._output
            was_multi = self._is_multi
            self._output = None
            self._is_multi = False
            if output is not None:
                if was_multi:
                    for sink in tuple(output):
                        try:  # noqa: SIM105
                            sink.complete()
                        except Exception:
                            pass
                else:
                    output.complete()
            return
        if sig is Signal.RESET:
            self._generation += 1
            gen = self._generation
            actions = self._create_actions(gen)
            self._handler = self._init(actions)
            if self._reset_on_teardown:
                self._value = self._initial
            if self._handler is not None:
                self._handler(0, STATE, sig)
        for tb in self._upstream_talkbacks:
            if tb is not None:
                tb.signal(sig)

    # --- Public API ---

    def get(self) -> Any:
        if self._getter_fn is not None and self._output is None:
            v = self._getter_fn(self._value)
            self._value = v
            return v
        return self._value

    def subscribe(self, sink: Any) -> Any:
        if self._completed:
            if self._resubscribable and self._output is None:
                self._completed = False
                self._status = NodeStatus.DISCONNECTED
            else:
                if self._status is NodeStatus.ERRORED:
                    sink.error(self._error_data)
                else:
                    sink.complete()
                return NOOP_TALKBACK
        was_empty = self._output is None
        self._add_sink(sink)
        tb = _NodeTalkback(self, sink)
        if was_empty:
            self._connect_upstream()
        return tb

    def __or__(self, op: Any) -> Any:
        return op(self)


def operator(
    deps: list[Any],
    init: Any,
    *,
    initial: Any = None,
    getter: Any = None,
    reset_on_teardown: bool = False,
    resubscribable: bool = False,
) -> OperatorImpl:
    """Create a custom transform node.

    ``init`` receives an Actions object and returns a handler
    ``(dep_index: int, type: int, data: Any) -> None``.

    Type constants: ``DATA=1``, ``STATE=3``, ``END=2`` (from protocol).
    """
    return OperatorImpl(
        deps,
        init,
        initial=initial,
        getter=getter,
        reset_on_teardown=reset_on_teardown,
        resubscribable=resubscribable,
    )
