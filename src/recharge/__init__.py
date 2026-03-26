"""recharge — Reactive state management with push/pull duality."""

__version__ = "0.1.0"

from .core import (
    DATA,
    END,
    STATE,
    NodeStatus,
    Signal,
    Sink,
    Source,
    Store,
    Subscription,
    Talkback,
    batch,
    derived,
    derived_from,
    dynamic_derived,
    effect,
    is_lifecycle_signal,
    operator,
    pipe,
    producer,
    state,
    subscribe,
)
from .raw import (
    first_value_from,
    from_any,
    from_async_iter,
    from_awaitable,
    from_iter,
    from_timer,
    raw_subscribe,
)

__all__ = [
    # Enums
    "Signal",
    "NodeStatus",
    # Type tags
    "DATA",
    "END",
    "STATE",
    # Protocol classes
    "Sink",
    "Talkback",
    "Source",
    "Store",
    "Subscription",
    # Primitives
    "state",
    "derived",
    "derived_from",
    "dynamic_derived",
    "effect",
    "producer",
    "operator",
    # Composition
    "pipe",
    "batch",
    "subscribe",
    # Utilities
    "is_lifecycle_signal",
    # Raw primitives
    "raw_subscribe",
    "from_iter",
    "from_timer",
    "first_value_from",
    "from_awaitable",
    "from_async_iter",
    "from_any",
]
