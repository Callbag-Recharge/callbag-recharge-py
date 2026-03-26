"""distinct_until_changed — drop consecutive duplicates."""

from __future__ import annotations

import operator as op
from typing import Any

from ..core.derived import derived_from


def distinct_until_changed(equals: Any = None) -> Any:
    """Drop consecutive duplicate values.

    Uses ``operator.is_`` by default (identity comparison, matching
    ``state``'s default equality). Pass a custom ``equals`` for
    value-based comparison.
    """
    eq_fn = equals if equals is not None else op.is_

    def _op(input: Any) -> Any:
        return derived_from(input, equals=eq_fn)

    return _op
