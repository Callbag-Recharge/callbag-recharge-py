"""combine — tuple store from multiple sources."""

from __future__ import annotations

from typing import Any

from ..core.derived import derived


def combine(*sources: Any) -> Any:
    """Build a tuple store from multiple sources.

    Updates when any dependency changes. Each recompute produces a fresh
    tuple. Participates in diamond resolution via ``derived``.
    """
    source_list = list(sources)
    return derived(source_list, lambda: tuple(s.get() for s in source_list))
