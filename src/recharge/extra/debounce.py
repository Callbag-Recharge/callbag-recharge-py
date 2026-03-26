"""debounce — delay emission until silence of ``seconds``."""

from __future__ import annotations

import threading
from typing import Any

from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe


def debounce(seconds: float) -> Any:
    """Delay each upstream change by ``seconds``; reset timer on new value.

    Tier 2 cycle boundary. Flushes pending value on upstream completion.
    Cancels timer and forwards on upstream error.
    """

    def _op(input: Any) -> Any:
        def factory(api: Any) -> Any:
            timer: list[threading.Timer | None] = [None]
            pending_value: list[Any] = [None]
            has_pending = [False]
            outer_sub: list[Any] = [None]

            def handle_lifecycle(sig: Signal) -> None:
                if outer_sub[0] is not None:
                    outer_sub[0].signal(sig)
                if sig is Signal.RESET:
                    if timer[0] is not None:
                        timer[0].cancel()
                        timer[0] = None
                    has_pending[0] = False
                    pending_value[0] = None

            api.on_signal(handle_lifecycle)

            def on_value(v: Any, _prev: Any) -> None:
                if timer[0] is not None:
                    timer[0].cancel()
                pending_value[0] = v
                has_pending[0] = True

                def flush() -> None:
                    timer[0] = None
                    has_pending[0] = False
                    v = pending_value[0]
                    pending_value[0] = None
                    api.emit(v)

                t = threading.Timer(seconds, flush)
                t.daemon = True
                t.start()
                timer[0] = t

            def on_end(err: Any) -> None:
                if err is not None:
                    if timer[0] is not None:
                        timer[0].cancel()
                        timer[0] = None
                    api.error(err)
                else:
                    if timer[0] is not None:
                        timer[0].cancel()
                        timer[0] = None
                    if has_pending[0]:
                        has_pending[0] = False
                        api.emit(pending_value[0])
                    api.complete()

            outer_sub[0] = subscribe(input, on_value, on_end=on_end)

            def cleanup() -> None:
                if timer[0] is not None:
                    timer[0].cancel()
                    timer[0] = None
                if outer_sub[0] is not None:
                    outer_sub[0].unsubscribe()

            return cleanup

        return producer(factory)

    return _op
