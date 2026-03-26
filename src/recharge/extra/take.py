"""take — emit at most n values then complete."""

from __future__ import annotations

from typing import Any

from ..core.operator import operator
from ..core.protocol import DATA, END, STATE


def take(n: int) -> Any:
    """Emit at most ``n`` DATA values from upstream, then complete.

    If ``n <= 0``, completes immediately with no DATA.
    """

    def _op(input: Any) -> Any:
        def init(actions: Any) -> Any:
            count = [0]

            if n <= 0:
                actions.disconnect()
                actions.complete()

            def handler(dep: int, type: int, data: Any) -> None:
                if type == STATE:
                    if count[0] < n:
                        actions.signal(data)
                elif type == DATA:
                    if count[0] < n:
                        count[0] += 1
                        actions.emit(data)
                        if count[0] >= n:
                            actions.disconnect()
                            actions.complete()
                elif type == END:
                    if data is not None:
                        actions.error(data)
                    else:
                        actions.complete()

            return handler

        return operator([input], init)

    return _op
