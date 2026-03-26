"""replay — re-seed with current value on reconnect."""

from __future__ import annotations

from typing import Any

from ..core.operator import operator
from ..core.protocol import DATA, END, STATE


def replay() -> Any:
    """Replay the last value to new subscribers.

    On each (re)connect, seeds the stored value with the current
    upstream value so ``get()`` returns a meaningful result immediately.
    Cache clears on last disconnect (``reset_on_teardown=True``).
    """

    def _op(input: Any) -> Any:
        def init(actions: Any) -> Any:
            actions.seed(input.get())

            def handler(dep: int, type: int, data: Any) -> None:
                if type == STATE:
                    actions.signal(data)
                elif type == DATA:
                    actions.emit(data)
                elif type == END:
                    if data is not None:
                        actions.error(data)
                    else:
                        actions.complete()

            return handler

        return operator([input], init, reset_on_teardown=True)

    return _op
