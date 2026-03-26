"""share — no-op; stores are inherently multicast."""

from __future__ import annotations

from typing import Any


def share() -> Any:
    """No-op operator. All stores are already multicast.

    Included for API parity with RxJS-style libraries.
    """

    def _op(input: Any) -> Any:
        return input

    return _op
