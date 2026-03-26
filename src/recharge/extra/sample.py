"""sample — emit latest input value on notifier pulse."""

from __future__ import annotations

from typing import Any

from ..core.producer import producer
from ..core.protocol import Signal
from ..core.subscribe import subscribe


def sample(notifier: Any) -> Any:
    """On each notifier emission, emit the latest value from the primary input.

    Tier 2 cycle boundary. ``get()`` reflects the latest input, not only
    the last sample. Completes when either input or notifier ends.
    """

    def _op(input: Any) -> Any:
        latest_input: list[Any] = [input.get()]

        def factory(api: Any) -> Any:
            latest_input[0] = input.get()
            input_sub: list[Any] = [None]
            notifier_sub: list[Any] = [None]

            def handle_lifecycle(sig: Signal) -> None:
                if input_sub[0] is not None:
                    input_sub[0].signal(sig)
                if notifier_sub[0] is not None:
                    notifier_sub[0].signal(sig)
                if sig is Signal.RESET:
                    latest_input[0] = input.get()

            api.on_signal(handle_lifecycle)

            def on_input(v: Any, _prev: Any) -> None:
                latest_input[0] = v

            def on_input_end(err: Any) -> None:
                if err is not None:
                    api.error(err)
                else:
                    api.complete()

            def on_notifier(_v: Any, _prev: Any) -> None:
                api.emit(latest_input[0])

            def on_notifier_end(err: Any) -> None:
                if err is not None:
                    api.error(err)
                else:
                    api.complete()

            input_sub[0] = subscribe(input, on_input, on_end=on_input_end)
            notifier_sub[0] = subscribe(notifier, on_notifier, on_end=on_notifier_end)

            def cleanup() -> None:
                if input_sub[0] is not None:
                    input_sub[0].unsubscribe()
                if notifier_sub[0] is not None:
                    notifier_sub[0].unsubscribe()

            return cleanup

        return producer(
            factory,
            initial=latest_input[0],
            getter=lambda _val: latest_input[0],
        )

    return _op
