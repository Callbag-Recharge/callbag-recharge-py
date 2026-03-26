"""merge — combine multiple sources; last emitter wins."""

from __future__ import annotations

from typing import Any

from ..core.bitmask import Bitmask
from ..core.operator import operator
from ..core.protocol import DATA, END, STATE, Signal


def merge(*sources: Any) -> Any:
    """Merge multiple stores; output holds the latest value from whichever source emitted last.

    Completes when all sources have completed. Errors immediately on
    any source error.
    """
    source_list = list(sources)

    def init(actions: Any) -> Any:
        dirty_deps = Bitmask()
        active_count = [len(source_list)]
        any_data = [False]

        def handler(dep: int, type: int, data: Any) -> None:
            if type == STATE:
                if data is Signal.DIRTY:
                    was_clean = dirty_deps.empty()
                    dirty_deps.set(dep)
                    if was_clean:
                        any_data[0] = False
                        actions.signal(Signal.DIRTY)
                elif data is Signal.RESOLVED:
                    if dirty_deps.test(dep):
                        dirty_deps.clear(dep)
                        if dirty_deps.empty() and not any_data[0]:
                            actions.signal(Signal.RESOLVED)
                else:
                    actions.signal(data)
            elif type == DATA:
                dirty_deps.clear(dep)
                any_data[0] = True
                actions.emit(data)
            elif type == END:
                dirty_deps.clear(dep)
                if data is not None:
                    actions.error(data)
                else:
                    active_count[0] -= 1
                    if active_count[0] == 0:
                        actions.complete()

        return handler

    return operator(source_list, init)
