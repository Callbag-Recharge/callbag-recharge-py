"""Left-to-right operator composition."""

from __future__ import annotations

from typing import Any


def pipe(source: Any, *ops: Any) -> Any:
    """Compose StoreOperator functions left-to-right, returning a single output store.

    Each operator wraps the previous store; order matches visual reading order.

    Equivalent to the ``|`` operator: ``source | op1 | op2``.
    """
    current = source
    for op in ops:
        current = op(current)
    return current
