"""raw/ -- pure protocol primitives (Tier -1).  Zero core dependencies."""

from .first_value_from import first_value_from
from .from_any import from_any
from .from_async_iter import from_async_iter
from .from_awaitable import from_awaitable
from .from_iter import from_iter
from .from_timer import from_timer
from .protocol import Signal, Sink, Source, Talkback
from .subscribe import raw_subscribe

__all__ = [
    # Protocol
    "Signal",
    "Sink",
    "Source",
    "Talkback",
    # Primitives
    "first_value_from",
    "from_any",
    "from_async_iter",
    "from_awaitable",
    "from_iter",
    "from_timer",
    "raw_subscribe",
]
