"""filter — forward values that pass a predicate; RESOLVED when they don't."""

from __future__ import annotations

from typing import Any

from ..core.operator import operator
from ..core.protocol import DATA, END, STATE, Signal


def filter(predicate: Any, *, equals: Any = None) -> Any:
    """Forward upstream values where ``predicate`` returns True.

    When the predicate fails, sends RESOLVED (not silence) so downstream
    diamond resolution stays correct. Optional ``equals`` deduplicates
    consecutive passing values.
    """

    def _op(input: Any) -> Any:
        last_passing: list[Any] = [None]
        has_last_passing = [False]
        v0 = input.get()
        if predicate(v0):
            last_passing[0] = v0
            has_last_passing[0] = True

        def init(actions: Any) -> Any:
            dirty_forwarded = [False]

            def handler(dep: int, type: int, data: Any) -> None:
                if type == STATE:
                    if data is Signal.DIRTY:
                        dirty_forwarded[0] = True
                    actions.signal(data)
                elif type == DATA:
                    if predicate(data):
                        if (
                            equals is not None
                            and has_last_passing[0]
                            and equals(last_passing[0], data)
                        ):
                            if dirty_forwarded[0]:
                                dirty_forwarded[0] = False
                                actions.signal(Signal.RESOLVED)
                            return
                        last_passing[0] = data
                        has_last_passing[0] = True
                        dirty_forwarded[0] = False
                        actions.emit(data)
                    else:
                        if dirty_forwarded[0]:
                            dirty_forwarded[0] = False
                            actions.signal(Signal.RESOLVED)
                elif type == END:
                    if data is not None:
                        actions.error(data)
                    else:
                        actions.complete()

            return handler

        def getter(_val: Any) -> Any:
            v = input.get()
            if predicate(v):
                last_passing[0] = v
                has_last_passing[0] = True
            return last_passing[0]

        return operator([input], init, initial=last_passing[0], getter=getter)

    return _op
