"""map — transform each upstream value through a function."""

from __future__ import annotations

from typing import Any

from ..core.derived import derived


def map(fn: Any, *, equals: Any = None) -> Any:
    """Transform each upstream value through ``fn``.

    Returns a ``StoreOperator`` for use with ``pipe()`` or ``|``.
    When disconnected, ``get()`` pull-computes ``fn(input.get())``.
    Optional ``equals`` enables push-phase memoization (RESOLVED instead of DATA).
    """

    def _op(input: Any) -> Any:
        return derived([input], lambda: fn(input.get()), equals=equals)

    return _op
