"""concat_map — map to inner stores, process sequentially."""

from __future__ import annotations

from collections import deque
from typing import Any

from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe

_UNSET: Any = object()


def concat_map(fn: Any, *, initial: Any = _UNSET, max_buffer: int = 0) -> Any:
    """Map each outer value to an inner store; run inners sequentially.

    Queues outer values while an inner is active. Pass ``max_buffer``
    to limit the queue size (0 = unlimited, drops oldest on overflow).
    Tier 2 cycle boundary.
    """

    _has_initial = initial is not _UNSET

    def _op(outer: Any) -> Any:
        def factory(api: Any) -> Any:
            inner_sub: list[Any] = [None]
            inner_active = [False]
            outer_done = [False]
            queue: deque[Any] = deque()
            outer_sub: list[Any] = [None]

            def process_next() -> None:
                if len(queue) == 0:
                    inner_active[0] = False
                    if outer_done[0]:
                        api.complete()
                    return
                subscribe_inner(fn(queue.popleft()))

            def subscribe_inner(inner_store: Any) -> None:
                inner_active[0] = True
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
                    else:
                        process_next()

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
                    inner_active[0] = False
                    outer_done[0] = False
                    queue.clear()

            api.on_signal(handle_lifecycle)

            def on_outer(v: Any, _prev: Any) -> None:
                if not inner_active[0]:
                    subscribe_inner(fn(v))
                else:
                    if max_buffer > 0 and len(queue) >= max_buffer:
                        queue.popleft()
                    queue.append(v)

            def on_outer_end(err: Any) -> None:
                if err is not None:
                    api.error(err)
                else:
                    outer_done[0] = True
                    if not inner_active[0]:
                        api.complete()

            outer_sub[0] = subscribe(outer, on_outer, on_end=on_outer_end)

            def cleanup() -> None:
                if inner_sub[0] is not None:
                    inner_sub[0].unsubscribe()
                if outer_sub[0] is not None:
                    outer_sub[0].unsubscribe()
                queue.clear()

            return cleanup

        kwargs: dict[str, Any] = {}
        if _has_initial:
            kwargs["initial"] = initial
        return producer(factory, **kwargs)

    return _op
