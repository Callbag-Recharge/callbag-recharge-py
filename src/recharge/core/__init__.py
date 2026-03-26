"""Core primitives — foundation layer (Tier 0)."""

from .bitmask import Bitmask
from .derived import DerivedImpl, derived, derived_from
from .dynamic_derived import DynamicDerivedImpl, dynamic_derived
from .effect import effect
from .operator import OperatorImpl, operator
from .pipe import pipe
from .producer import ProducerImpl, producer
from .protocol import (
    DATA,
    END,
    STATE,
    NodeStatus,
    Signal,
    batch,
    is_lifecycle_signal,
)
from .state import StateImpl, state
from .subscribe import subscribe
from .types import (
    NOOP_TALKBACK,
    Sink,
    Source,
    Store,
    StoreOperator,
    Subscription,
    Talkback,
)

__all__ = [
    # Enums
    "Signal",
    "NodeStatus",
    # Type tags (for operator handler)
    "DATA",
    "END",
    "STATE",
    # Protocol classes
    "Sink",
    "Talkback",
    "Source",
    "Store",
    "StoreOperator",
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
    "Bitmask",
    "NOOP_TALKBACK",
    # Implementation classes (for subclassing/testing)
    "StateImpl",
    "DerivedImpl",
    "DynamicDerivedImpl",
    "ProducerImpl",
    "OperatorImpl",
]
