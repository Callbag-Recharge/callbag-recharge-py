"""throttle — leading-edge rate limiter."""

from __future__ import annotations

import threading
from typing import Any

from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe


def throttle(seconds: float) -> Any:
    """Emit the first value, then drop further values until ``seconds`` has passed.

    Leading-edge throttle: the first value in each window is emitted
    immediately. Tier 2 cycle boundary.
    """

    def _op(input: Any) -> Any:
        def factory(api: Any) -> Any:
            timer: list[threading.Timer | None] = [None]
            outer_sub: list[Any] = [None]

            def handle_lifecycle(sig: Signal) -> None:
                if outer_sub[0] is not None:
                    outer_sub[0].signal(sig)
                if sig is Signal.RESET and timer[0] is not None:
                    timer[0].cancel()
                    timer[0] = None

            api.on_signal(handle_lifecycle)

            def on_value(v: Any, _prev: Any) -> None:
                if timer[0] is not None:
                    return  # still within throttle window
                api.emit(v)

                def open_window() -> None:
                    timer[0] = None

                t = threading.Timer(seconds, open_window)
                t.daemon = True
                t.start()
                timer[0] = t

            def on_end(err: Any) -> None:
                if timer[0] is not None:
                    timer[0].cancel()
                    timer[0] = None
                if err is not None:
                    api.error(err)
                else:
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
