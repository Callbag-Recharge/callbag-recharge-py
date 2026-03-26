"""flat_map — map to inner stores, subscribe all concurrently (mergeMap)."""

from __future__ import annotations

from typing import Any

from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe

_UNSET: Any = object()


def flat_map(fn: Any, *, initial: Any = _UNSET) -> Any:
    """Map each outer value to an inner store; run all inners concurrently.

    Unlike ``switch_map`` (which cancels the previous inner) or
    ``concat_map`` (which queues), ``flat_map`` subscribes to every
    inner simultaneously. Completes when outer is done and all
    inners have completed. Tier 2 cycle boundary.
    """

    _has_initial = initial is not _UNSET

    def _op(outer: Any) -> Any:
        def factory(api: Any) -> Any:
            inner_subs: set[Any] = set()
            outer_done = [False]
            outer_sub: list[Any] = [None]

            def subscribe_inner(inner_store: Any) -> None:
                inner_emitted = [False]
                inner_ended = [False]
                sub_ref: list[Any] = [None]

                def on_inner(v: Any, _prev: Any) -> None:
                    inner_emitted[0] = True
                    api.emit(v)

                def on_inner_end(err: Any) -> None:
                    inner_ended[0] = True
                    inner_subs.discard(sub_ref[0])
                    if err is not None:
                        api.error(err)
                    elif outer_done[0] and len(inner_subs) == 0:
                        api.complete()

                sub_ref[0] = subscribe(inner_store, on_inner, on_end=on_inner_end)
                if not inner_ended[0]:
                    inner_subs.add(sub_ref[0])
                if not inner_emitted[0] and not inner_ended[0]:
                    api.emit(inner_store.get())

            def handle_lifecycle(sig: Signal) -> None:
                if outer_sub[0] is not None:
                    outer_sub[0].signal(sig)
                if sig is Signal.RESET:
                    for s in list(inner_subs):
                        s.unsubscribe()
                    inner_subs.clear()
                    outer_done[0] = False

            api.on_signal(handle_lifecycle)

            def on_outer(v: Any, _prev: Any) -> None:
                subscribe_inner(fn(v))

            def on_outer_end(err: Any) -> None:
                if err is not None:
                    api.error(err)
                else:
                    outer_done[0] = True
                    if len(inner_subs) == 0:
                        api.complete()

            outer_sub[0] = subscribe(outer, on_outer, on_end=on_outer_end)

            def cleanup() -> None:
                for s in list(inner_subs):
                    s.unsubscribe()
                inner_subs.clear()
                if outer_sub[0] is not None:
                    outer_sub[0].unsubscribe()

            return cleanup

        kwargs: dict[str, Any] = {}
        if _has_initial:
            kwargs["initial"] = initial
        return producer(factory, **kwargs)

    return _op
