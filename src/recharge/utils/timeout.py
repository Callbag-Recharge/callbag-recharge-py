"""timeout operator."""

from __future__ import annotations

import threading
from typing import Any

from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe


class TimeoutError(RuntimeError):
    def __init__(self, seconds: float) -> None:
        super().__init__(f"Timeout: source did not emit within {seconds}s")


def timeout(seconds: float) -> Any:
    """Error if upstream emits no value within ``seconds``."""
    if seconds < 0:
        raise ValueError("seconds must be non-negative")

    def _op(input_store: Any) -> Any:
        def factory(api: Any) -> Any:
            timer: list[threading.Timer | None] = [None]
            outer_sub: list[Any] = [None]
            stopped = [False]
            generation = [0]
            lock = threading.Lock()

            def clear_timer_locked() -> None:
                if timer[0] is not None:
                    timer[0].cancel()
                    timer[0] = None

            def arm_timer() -> None:
                with lock:
                    if stopped[0]:
                        return
                    generation[0] += 1
                    current_gen = generation[0]
                    clear_timer_locked()

                    def fire() -> None:
                        with lock:
                            if stopped[0] or current_gen != generation[0]:
                                return
                            stopped[0] = True
                            if outer_sub[0] is not None:
                                outer_sub[0].unsubscribe()
                                outer_sub[0] = None
                            clear_timer_locked()
                        api.error(TimeoutError(seconds))

                    t = threading.Timer(seconds, fire)
                    t.daemon = True
                    t.start()
                    timer[0] = t

            def handle_lifecycle(sig: Signal) -> None:
                with lock:
                    if outer_sub[0] is not None:
                        outer_sub[0].signal(sig)
                    if sig is Signal.RESET:
                        generation[0] += 1
                        clear_timer_locked()
                if sig is Signal.RESET:
                    arm_timer()

            api.on_signal(handle_lifecycle)

            def on_value(v: Any, _prev: Any) -> None:
                arm_timer()
                api.emit(v)

            def on_end(err: Exception | None) -> None:
                with lock:
                    if stopped[0]:
                        return
                    stopped[0] = True
                    generation[0] += 1
                    clear_timer_locked()
                if err is None:
                    api.complete()
                else:
                    api.error(err)

            outer_sub[0] = subscribe(input_store, on_value, on_end=on_end)
            arm_timer()

            def cleanup() -> None:
                with lock:
                    stopped[0] = True
                    generation[0] += 1
                    clear_timer_locked()
                    if outer_sub[0] is not None:
                        outer_sub[0].unsubscribe()
                        outer_sub[0] = None

            return cleanup

        return producer(factory, initial=input_store.get())

    return _op
