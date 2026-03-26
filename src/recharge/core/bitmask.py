"""Dirty-dep bitmask — safe for any number of deps.

Python int has unlimited precision, so we always use a plain int
as the bitmask. No need for the Uint32Array fallback from TypeScript.
"""

from __future__ import annotations


class Bitmask:
    """Per-dep dirty tracking with O(1) emptiness check."""

    __slots__ = ("_v",)

    def __init__(self) -> None:
        self._v = 0

    def set(self, i: int) -> None:
        """Mark dep i as dirty."""
        self._v |= 1 << i

    def clear(self, i: int) -> None:
        """Clear dirty bit for dep i."""
        self._v &= ~(1 << i)

    def test(self, i: int) -> bool:
        """Returns True if dep i is dirty."""
        return bool(self._v & (1 << i))

    def empty(self) -> bool:
        """Returns True if no deps are dirty."""
        return self._v == 0

    def reset(self) -> None:
        """Clear all dirty bits."""
        self._v = 0
