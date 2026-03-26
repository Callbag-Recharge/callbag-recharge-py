"""zip — pair sources by emission index."""

from __future__ import annotations

from collections import deque
from typing import Any

from ..core.bitmask import Bitmask
from ..core.operator import operator
from ..core.protocol import DATA, END, STATE, Signal


def zip(*sources: Any, max_buffer: int = 0) -> Any:
    """Combine sources by index: emits a tuple when all have contributed a value.

    Buffers values from each source. When all buffers are non-empty, pops
    the oldest from each and emits the tuple. Completes when any source
    completes and its buffer is empty, or when all sources complete.

    Pass ``max_buffer`` to limit per-source buffer size (0 = unlimited,
    drops oldest on overflow).
    """
    source_list = list(sources)

    def init(actions: Any) -> Any:
        dirty_deps = Bitmask()
        buffers: list[deque[Any]] = [deque() for _ in source_list]
        active_count = [len(source_list)]
        any_data = [False]

        def try_emit() -> None:
            while all(len(b) > 0 for b in buffers):
                values = tuple(b.popleft() for b in buffers)
                actions.emit(values)

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
                        if dirty_deps.empty():
                            if any_data[0]:
                                try_emit()
                            else:
                                actions.signal(Signal.RESOLVED)
                else:
                    actions.signal(data)
            elif type == DATA:
                dirty_deps.clear(dep)
                buffers[dep].append(data)
                if max_buffer > 0 and len(buffers[dep]) > max_buffer:
                    buffers[dep].popleft()
                any_data[0] = True
                if dirty_deps.empty():
                    try_emit()
            elif type == END:
                if data is not None:
                    actions.error(data)
                else:
                    active_count[0] -= 1
                    if active_count[0] == 0 or len(buffers[dep]) == 0:
                        actions.complete()

        return handler

    return operator(source_list, init)
