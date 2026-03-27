"""Runtime configuration for core concurrency behavior."""

from __future__ import annotations

import threading
from typing import Literal

DeferredFlushMode = Literal["safe", "strict"]

_config_lock = threading.Lock()
_deferred_flush_mode: DeferredFlushMode = "safe"


def configure(*, deferred_flush_mode: DeferredFlushMode | None = None) -> None:
    """Configure core runtime behavior.

    Args:
        deferred_flush_mode:
            - ``"safe"`` (default): deferred flush catches ``Exception`` only.
              ``KeyboardInterrupt``/``SystemExit`` propagate immediately.
            - ``"strict"``: deferred flush catches ``BaseException``, drains all
              deferred callbacks, then re-raises the first captured throwable.
    """
    global _deferred_flush_mode
    with _config_lock:
        if deferred_flush_mode is not None:
            _deferred_flush_mode = deferred_flush_mode


def get_deferred_flush_mode() -> DeferredFlushMode:
    """Return active deferred flush mode."""
    with _config_lock:
        return _deferred_flush_mode
