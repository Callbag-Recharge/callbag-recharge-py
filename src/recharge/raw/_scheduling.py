"""Shared scheduling utilities for raw/ async primitives."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

type ScheduleFn = Callable[
    [Coroutine[Any, Any, Any], Callable[[Any], None], Callable[[Exception], None]],
    None,
]


def thread_schedule(
    coro: Coroutine[Any, Any, Any],
    on_result: Callable[[Any], None],
    on_error: Callable[[Exception], None],
) -> None:
    """Default scheduler: runs the coroutine in a daemon thread via asyncio.run()."""
    import asyncio

    def _run() -> None:
        try:
            result = asyncio.run(coro)
        except Exception as e:
            on_error(e)
        else:
            on_result(result)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
