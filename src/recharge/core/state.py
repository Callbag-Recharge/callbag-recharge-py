"""Writable store — subclass of ProducerImpl with set()/update() API."""

from __future__ import annotations

import operator as op
from typing import TYPE_CHECKING, Any

from .producer import ProducerImpl
from .protocol import NodeStatus, Signal, defer_emission, is_batching

if TYPE_CHECKING:
    from collections.abc import Callable


class StateImpl(ProducerImpl):
    """Internal implementation of the writable state store."""

    __slots__ = ()

    def __init__(
        self,
        initial: Any,
        *,
        equals: Callable[[Any, Any], bool] | None = None,
    ) -> None:
        super().__init__(
            None,
            initial=initial,
            auto_dirty=True,
            equals=equals if equals is not None else op.is_,
        )

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        """Set a new value and notify subscribers.

        Fast path: inlines ProducerImpl.emit() to skip method call overhead.
        """
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
                self._status = NodeStatus.DIRTY
                self._dispatch_signal(Signal.DIRTY)
                defer_emission(self._flush_pending)
        else:
            self._status = NodeStatus.DIRTY
            self._dispatch_signal(Signal.DIRTY)
            self._status = NodeStatus.SETTLED
            self._dispatch_next(self._value)

    def update(self, fn: Callable[[Any], Any]) -> None:
        """Update the value using a function of the current value."""
        self.set(fn(self._value))


def state(
    initial: Any,
    *,
    equals: Callable[[Any, Any], bool] | None = None,
) -> StateImpl:
    """Create a writable reactive store with an initial value.

    ``equals`` defaults to ``operator.is_``. If ``set()`` is called with a
    value equal to the current value, the emission is skipped entirely.
    """
    return StateImpl(initial, equals=equals)
