"""skip — drop the first n upstream DATA emissions."""

from __future__ import annotations

from typing import Any

from ..core.operator import operator
from ..core.protocol import DATA, END, STATE, Signal


def skip(n: int) -> Any:
    """Ignore the first ``n`` upstream DATA emissions, then mirror the rest.

    During the skip window, DIRTY/RESOLVED are suppressed (the operator
    absorbs the entire cycle). Unknown STATE signals are always forwarded.
    """

    def _op(input: Any) -> Any:
        def init(actions: Any) -> Any:
            emission_count = [0]

            def handler(dep: int, type: int, data: Any) -> None:
                if type == STATE:
                    if data is Signal.DIRTY or data is Signal.RESOLVED:
                        if emission_count[0] >= n:
                            actions.signal(data)
                    else:
                        actions.signal(data)
                elif type == DATA:
                    emission_count[0] += 1
                    if emission_count[0] > n:
                        actions.emit(data)
                elif type == END:
                    if data is not None:
                        actions.error(data)
                    else:
                        actions.complete()

            return handler

        return operator([input], init)

    return _op
