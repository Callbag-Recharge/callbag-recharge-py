"""scan — accumulate upstream values with a reducer."""

from __future__ import annotations

from typing import Any

from ..core.operator import operator
from ..core.protocol import DATA, END, STATE, Signal


def scan(reducer: Any, seed: Any, *, equals: Any = None) -> Any:
    """Accumulate upstream values: ``reducer(acc, value) -> new_acc``.

    Emits the accumulator after each step. Resets to ``seed`` on reconnect.
    Optional ``equals`` sends RESOLVED when the accumulator is unchanged.
    """

    def _op(input: Any) -> Any:
        acc: list[Any] = [seed]
        last_getter_input: list[Any] = [None]
        getter_seeded: list[bool] = [False]

        def init(actions: Any) -> Any:
            acc[0] = seed
            getter_seeded[0] = False
            dirty_forwarded = [False]

            def handler(dep: int, type: int, data: Any) -> None:
                if type == STATE:
                    if data is Signal.DIRTY:
                        dirty_forwarded[0] = True
                    actions.signal(data)
                elif type == DATA:
                    next_acc = reducer(acc[0], data)
                    if equals is not None and equals(acc[0], next_acc):
                        if dirty_forwarded[0]:
                            dirty_forwarded[0] = False
                            actions.signal(Signal.RESOLVED)
                        return
                    acc[0] = next_acc
                    dirty_forwarded[0] = False
                    actions.emit(acc[0])
                elif type == END:
                    if data is not None:
                        actions.error(data)
                    else:
                        actions.complete()

            return handler

        def getter(_val: Any) -> Any:
            v = input.get()
            if not getter_seeded[0] or v is not last_getter_input[0]:
                acc[0] = reducer(acc[0], v)
                last_getter_input[0] = v
                getter_seeded[0] = True
            return acc[0]

        return operator([input], init, initial=seed, getter=getter, reset_on_teardown=True)

    return _op
