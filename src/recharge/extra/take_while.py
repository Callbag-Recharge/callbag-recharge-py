"""take_while — emit while predicate holds, then complete."""

from __future__ import annotations

from typing import Any

from ..core.operator import operator
from ..core.protocol import DATA, END, STATE


def take_while(predicate: Any) -> Any:
    """Emit values while ``predicate`` returns True.

    On the first False, disconnects upstream and completes. The failing
    value is **not** emitted. Predicate exceptions cause an error end.
    """

    def _op(input: Any) -> Any:
        def init(actions: Any) -> Any:
            completed = [False]

            def handler(dep: int, type: int, data: Any) -> None:
                if completed[0]:
                    return
                if type == STATE:
                    actions.signal(data)
                elif type == DATA:
                    try:
                        if predicate(data):
                            actions.emit(data)
                        else:
                            completed[0] = True
                            actions.disconnect()
                            actions.complete()
                    except Exception as e:
                        completed[0] = True
                        actions.disconnect()
                        actions.error(e)
                elif type == END:
                    if data is not None:
                        actions.error(data)
                    else:
                        actions.complete()

            return handler

        return operator([input], init)

    return _op
