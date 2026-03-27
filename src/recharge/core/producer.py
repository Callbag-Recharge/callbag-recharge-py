"""General-purpose source primitive.

Can emit values, send control signals, complete, and error.
Lazy start on first sink, auto-cleanup on last sink disconnect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .protocol import (
    NodeStatus,
    Signal,
    defer_emission,
    defer_start,
    is_batching,
)
from .subgraph_locks import ensure_registered
from .types import NOOP_TALKBACK, _NodeTalkback

if TYPE_CHECKING:
    from collections.abc import Callable

    from .types import Talkback


class ProducerImpl:
    """Internal implementation of the producer source."""

    __slots__ = (
        "_value",
        "_output",
        "_is_multi",
        "_status",
        "_completed",
        "_started",
        "_auto_dirty",
        "_reset_on_teardown",
        "_resubscribable",
        "_pending",
        "_fn",
        "_cleanup",
        "_eq_fn",
        "_getter_fn",
        "_initial",
        "_on_lifecycle_handler",
        "__weakref__",
    )

    def __init__(
        self,
        fn: Callable[..., Callable[[], None] | None] | None = None,
        *,
        initial: Any = None,
        auto_dirty: bool = True,
        equals: Callable[[Any, Any], bool] | None = None,
        getter: Callable[[Any], Any] | None = None,
        reset_on_teardown: bool = False,
        resubscribable: bool = False,
    ) -> None:
        self._value = initial
        self._output: Any = None  # Sink | set[Sink] | None
        self._is_multi = False
        self._status = NodeStatus.DISCONNECTED
        self._completed = False
        self._started = False
        self._auto_dirty = auto_dirty
        self._reset_on_teardown = reset_on_teardown
        self._resubscribable = resubscribable
        self._pending = False
        self._fn = fn
        self._cleanup: Callable[[], None] | None = None
        self._eq_fn = equals
        self._getter_fn = getter
        self._initial = initial
        self._on_lifecycle_handler: Callable[[Signal], None] | None = None
        ensure_registered(self)

    def get(self) -> Any:
        if self._getter_fn is not None:
            return self._getter_fn(self._value)
        return self._value

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
                if not self._completed:
                    self._status = NodeStatus.DISCONNECTED
                self._stop()
        elif self._output is sink:
            self._output = None
            if not self._completed:
                self._status = NodeStatus.DISCONNECTED
            self._stop()

    # --- Dispatch to subscribers ---

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

    # --- Core operations ---

    def emit(self, value: Any) -> None:
        """Set value and push DATA to all sinks."""
        if self._completed:
            return
        if self._eq_fn is not None and self._eq_fn(self._value, value):
            return
        self._value = value
        if self._output is None:
            return
        if is_batching():
            if not self._pending:
                self._pending = True
                if self._auto_dirty:
                    self._status = NodeStatus.DIRTY
                    self._dispatch_signal(Signal.DIRTY)
                defer_emission(self, self._flush_pending)
        else:
            if self._auto_dirty:
                self._status = NodeStatus.DIRTY
                self._dispatch_signal(Signal.DIRTY)
            self._status = NodeStatus.SETTLED
            self._dispatch_next(self._value)

    def _flush_pending(self) -> None:
        if not self._pending:
            return  # Cleared by RESET — stale deferred emission
        self._pending = False
        self._status = NodeStatus.SETTLED
        self._dispatch_next(self._value)

    def signal(self, sig: Signal) -> None:
        """Push a Signal on the STATE channel."""
        if self._completed or self._output is None:
            return
        if sig is Signal.DIRTY:
            self._status = NodeStatus.DIRTY
        elif sig is Signal.RESOLVED:
            self._status = NodeStatus.RESOLVED
        self._dispatch_signal(sig)

    def complete(self) -> None:
        """Send END to all sinks, mark completed."""
        if self._completed:
            return
        self._completed = True
        self._status = NodeStatus.COMPLETED
        output = self._output
        was_multi = self._is_multi
        self._output = None
        self._is_multi = False
        self._stop()
        if output is not None:
            if was_multi:
                for sink in tuple(output):
                    try:  # noqa: SIM105
                        sink.complete()
                    except Exception:
                        pass  # ensure all sinks receive END
            else:
                output.complete()

    def error(self, err: Exception) -> None:
        """Send END with error to all sinks, mark errored."""
        if self._completed:
            return
        self._completed = True
        self._status = NodeStatus.ERRORED
        output = self._output
        was_multi = self._is_multi
        self._output = None
        self._is_multi = False
        self._stop()
        if output is not None:
            if was_multi:
                for sink in tuple(output):
                    try:  # noqa: SIM105
                        sink.error(err)
                    except Exception:
                        pass
            else:
                output.error(err)

    # --- Lifecycle ---

    def _start(self) -> None:
        if self._started or self._fn is None:
            return
        self._started = True
        self._on_lifecycle_handler = None

        def on_signal(handler: Callable[[Signal], None]) -> None:
            self._on_lifecycle_handler = handler

        result = self._fn(
            _ProducerActions(
                emit=self.emit,
                signal=self.signal,
                complete=self.complete,
                error=self.error,
                on_signal=on_signal,
            )
        )
        self._cleanup = result if callable(result) else None

    def _stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._on_lifecycle_handler = None
        if self._cleanup is not None:
            self._cleanup()
            self._cleanup = None
        if self._reset_on_teardown:
            self._value = self._initial
        if not self._completed:
            self._status = NodeStatus.DISCONNECTED

    def _handle_lifecycle_signal(self, sig: Signal) -> None:
        if self._completed:
            return
        if sig is Signal.TEARDOWN:
            if self._on_lifecycle_handler is not None:
                self._on_lifecycle_handler(sig)
            self.complete()
            return
        if sig is Signal.RESET:
            self._value = self._initial
            self._pending = False
        if self._on_lifecycle_handler is not None:
            self._on_lifecycle_handler(sig)
        # No auto-emit on RESET — purely lifecycle. User triggers re-run
        # by explicitly pushing new data into the graph.

    # --- Subscribe ---

    def subscribe(self, sink: Any) -> Talkback:
        if self._completed:
            if self._resubscribable and self._output is None:
                self._completed = False
                self._status = NodeStatus.DISCONNECTED
            else:
                sink.complete()
                return NOOP_TALKBACK
        self._add_sink(sink)
        tb = _NodeTalkback(self, sink)
        defer_start(self._start)
        return tb

    def __or__(self, op: Any) -> Any:
        return op(self)


class _ProducerActions:
    """Actions passed to the producer factory function."""

    __slots__ = ("emit", "signal", "complete", "error", "on_signal")

    def __init__(
        self,
        emit: Callable[..., None],
        signal: Callable[..., None],
        complete: Callable[[], None],
        error: Callable[..., None],
        on_signal: Callable[..., None],
    ) -> None:
        self.emit = emit
        self.signal = signal
        self.complete = complete
        self.error = error
        self.on_signal = on_signal


def producer(
    fn: Callable[..., Callable[[], None] | None] | None = None,
    *,
    initial: Any = None,
    equals: Callable[[Any, Any], bool] | None = None,
    auto_dirty: bool = True,
    getter: Callable[[Any], Any] | None = None,
    reset_on_teardown: bool = False,
    resubscribable: bool = False,
) -> ProducerImpl:
    """Create a general-purpose reactive source.

    The optional factory ``fn`` runs on first subscriber; its return value
    (if callable) is cleanup on last disconnect.
    """
    return ProducerImpl(
        fn,
        initial=initial,
        auto_dirty=auto_dirty,
        equals=equals,
        getter=getter,
        reset_on_teardown=reset_on_teardown,
        resubscribable=resubscribable,
    )
