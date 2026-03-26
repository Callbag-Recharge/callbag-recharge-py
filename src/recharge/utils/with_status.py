"""with_status wrapper for loading/error/success style metadata."""

from __future__ import annotations

from typing import Any, Literal

from ..core import batch, state
from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe

StatusValue = Literal["pending", "active", "completed", "errored"]


class _WithStatusStore:
    __slots__ = ("_inner", "status", "error_store")

    def __init__(self, inner: Any, status: Any, error_store: Any) -> None:
        self._inner = inner
        self.status = status
        self.error_store = error_store

    def get(self) -> Any:
        return self._inner.get()

    def subscribe(self, sink: Any, /) -> Any:
        return self._inner.subscribe(sink)

    def __or__(self, op: Any) -> Any:
        return op(self)


def with_status(input_store: Any, *, initial_status: StatusValue = "pending") -> Any:
    """Wrap a store and expose ``status`` and ``error_store`` companion stores."""
    status_store = state(initial_status)
    error_store = state(None)

    def factory(api: Any) -> Any:
        status_store.set(initial_status)
        error_store.set(None)
        sub: list[Any] = [None]

        def on_value(v: Any, _prev: Any) -> None:
            if status_store.get() == "errored":
                with batch():
                    error_store.set(None)
                    status_store.set("active")
            else:
                status_store.set("active")
            api.emit(v)

        def on_end(err: Exception | None) -> None:
            if err is None:
                status_store.set("completed")
                api.complete()
                return

            with batch():
                error_store.set(err)
                status_store.set("errored")
            api.error(err)

        def on_signal(sig: Signal) -> None:
            if sub[0] is not None:
                sub[0].signal(sig)
            if sig is Signal.RESET:
                with batch():
                    status_store.set(initial_status)
                    error_store.set(None)

        api.on_signal(on_signal)
        sub[0] = subscribe(input_store, on_value, on_end=on_end)

        def cleanup() -> None:
            if sub[0] is not None:
                sub[0].unsubscribe()
                sub[0] = None

        return cleanup

    out = producer(factory, initial=input_store.get(), resubscribable=True)
    return _WithStatusStore(out, status_store, error_store)
