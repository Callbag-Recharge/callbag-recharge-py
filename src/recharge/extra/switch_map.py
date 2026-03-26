"""switch_map — map to inner store, switch on new outer value."""

from __future__ import annotations

from typing import Any

from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe

_UNSET: Any = object()


def switch_map(fn: Any, *, initial: Any = _UNSET) -> Any:
    """Map each outer value to an inner store; subscribe to the latest, unsub previous.

    Tier 2 cycle boundary. Each switch starts a new reactive cycle.
    Pass ``initial`` to seed ``get()`` before the first inner emission.
    """

    _has_initial = initial is not _UNSET

    def _op(outer: Any) -> Any:
        def factory(api: Any) -> Any:
            inner_sub: list[Any] = [None]
            outer_done = [False]
            outer_sub: list[Any] = [None]

            def subscribe_inner(inner_store: Any) -> None:
                if inner_sub[0] is not None:
                    inner_sub[0].unsubscribe()
                    inner_sub[0] = None

                inner_emitted = [False]
                inner_ended = [False]

                def on_inner(v: Any, _prev: Any) -> None:
                    inner_emitted[0] = True
                    api.emit(v)

                def on_inner_end(err: Any) -> None:
                    inner_sub[0] = None
                    inner_ended[0] = True
                    if err is not None:
                        api.error(err)
                    elif outer_done[0]:
                        api.complete()

                inner_sub[0] = subscribe(inner_store, on_inner, on_end=on_inner_end)
                if not inner_emitted[0] and not inner_ended[0]:
                    api.emit(inner_store.get())
                if inner_ended[0]:
                    inner_sub[0] = None

            def handle_lifecycle(sig: Signal) -> None:
                if outer_sub[0] is not None:
                    outer_sub[0].signal(sig)
                if sig is Signal.RESET:
                    if inner_sub[0] is not None:
                        inner_sub[0].unsubscribe()
                        inner_sub[0] = None
                    outer_done[0] = False

            api.on_signal(handle_lifecycle)

            def on_outer(v: Any, _prev: Any) -> None:
                subscribe_inner(fn(v))

            def on_outer_end(err: Any) -> None:
                if err is not None:
                    api.error(err)
                else:
                    outer_done[0] = True
                    if inner_sub[0] is None:
                        api.complete()

            outer_sub[0] = subscribe(outer, on_outer, on_end=on_outer_end)

            def cleanup() -> None:
                if inner_sub[0] is not None:
                    inner_sub[0].unsubscribe()
                if outer_sub[0] is not None:
                    outer_sub[0].unsubscribe()

            return cleanup

        kwargs: dict[str, Any] = {}
        if _has_initial:
            kwargs["initial"] = initial
        return producer(factory, **kwargs)

    return _op
