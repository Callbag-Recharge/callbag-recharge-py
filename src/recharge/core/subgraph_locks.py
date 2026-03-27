"""Union-find registry for per-subgraph write locking.

Concurrency contract:
- Only ``state.set()`` is protected by the subgraph write lock.
- ``producer.emit()`` and lifecycle signal pushes are NOT covered — callers
  must synchronize externally if used from multiple threads.
- ``get()`` is lock-free from any thread.
- Graph construction (creating nodes, connecting deps) is NOT thread-safe.
  Build the graph at startup before concurrent writes begin.
"""

from __future__ import annotations

import threading
import weakref
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


class _SubgraphRegistry:
    __slots__ = ("_meta_lock", "_parent", "_rank", "_locks", "_refs")

    def __init__(self) -> None:
        self._meta_lock = threading.Lock()
        self._parent: dict[int, int] = {}
        self._rank: dict[int, int] = {}
        self._locks: dict[int, threading.RLock] = {}
        self._refs: dict[int, weakref.ref[object]] = {}

    # --- Internal helpers (must hold _meta_lock) ---

    def _on_gc(self, node_id: int) -> None:
        """Weak-ref callback: clean up a GC'd node from the registry."""
        with self._meta_lock:
            self._refs.pop(node_id, None)
            self._parent.pop(node_id, None)
            self._rank.pop(node_id, None)
            self._locks.pop(node_id, None)

    def _find_locked(self, node_id: int) -> int:
        """Path-compressing find. Caller must hold _meta_lock."""
        parent = self._parent.get(node_id)
        if parent is None:
            # Node was GC'd or removed — treat as its own root.
            return node_id
        if parent != node_id:
            root = self._find_locked(parent)
            self._parent[node_id] = root
            return root
        return node_id

    def _ensure_locked(self, node: object) -> int:
        """Register node if not present. Caller must hold _meta_lock. Returns node_id."""
        node_id = id(node)
        if node_id not in self._parent:
            self._parent[node_id] = node_id
            self._rank[node_id] = 0
            self._locks[node_id] = threading.RLock()
            self._refs[node_id] = weakref.ref(node, lambda _ref: self._on_gc(node_id))
        return node_id

    # --- Public registry operations ---

    def ensure_node(self, node: object) -> None:
        with self._meta_lock:
            self._ensure_locked(node)

    def union(self, node_a: object, node_b: object) -> None:
        with self._meta_lock:
            id_a = self._ensure_locked(node_a)
            id_b = self._ensure_locked(node_b)

            root_a = self._find_locked(id_a)
            root_b = self._find_locked(id_b)
            if root_a == root_b:
                return

            rank_a = self._rank.get(root_a, 0)
            rank_b = self._rank.get(root_b, 0)
            if rank_a < rank_b:
                root_a, root_b = root_b, root_a
            self._parent[root_b] = root_a
            if rank_a == rank_b:
                self._rank[root_a] = rank_a + 1

            # Keep a single canonical lock for the merged component.
            self._locks.pop(root_b, None)

    @contextmanager
    def lock_for(self, node: object) -> Generator[None]:
        with self._meta_lock:
            node_id = self._ensure_locked(node)
            root = self._find_locked(node_id)
            lock = self._locks.get(root)
            if lock is None:
                # Root was GC'd — create a fresh lock for this node.
                lock = threading.RLock()
                self._locks[root] = lock
        with lock:
            yield


_REGISTRY = _SubgraphRegistry()


def ensure_registered(node: object) -> None:
    """Register a node in the subgraph registry."""
    _REGISTRY.ensure_node(node)


def union_nodes(a: object, b: object) -> None:
    """Merge two nodes into the same subgraph (same write lock)."""
    _REGISTRY.union(a, b)


@contextmanager
def acquire_subgraph_write_lock(node: object) -> Generator[None]:
    """Acquire the write lock for the subgraph containing *node*."""
    with _REGISTRY.lock_for(node):
        yield


# ---------------------------------------------------------------------------
# defer_set — safe cross-subgraph writes from within effects
# ---------------------------------------------------------------------------

_deferred_tls = threading.local()


def _get_deferred_depth() -> int:
    return getattr(_deferred_tls, "depth", 0)


def _inc_deferred_depth() -> None:
    _deferred_tls.depth = getattr(_deferred_tls, "depth", 0) + 1


def _dec_deferred_depth() -> int:
    depth = getattr(_deferred_tls, "depth", 1) - 1
    _deferred_tls.depth = depth
    return depth


def _get_deferred_queue() -> list[Callable[[], None]]:
    q: list[Callable[[], None]] | None = getattr(_deferred_tls, "queue", None)
    if q is None:
        q = []
        _deferred_tls.queue = q
    return q


@contextmanager
def acquire_subgraph_write_lock_with_defer(node: object) -> Generator[None]:
    """Acquire subgraph lock and flush any deferred cross-subgraph sets on exit."""
    _inc_deferred_depth()
    try:
        with _REGISTRY.lock_for(node):
            yield
    finally:
        if _dec_deferred_depth() == 0:
            queue = _get_deferred_queue()
            while queue:
                pending = queue[:]
                queue.clear()
                for fn in pending:
                    fn()


def defer_set(target: Any, value: Any) -> None:
    """Schedule a cross-subgraph set() to run after the current lock is released.

    If not currently inside a subgraph write lock, executes immediately.
    """
    if _get_deferred_depth() > 0:
        _get_deferred_queue().append(lambda: target.set(value))
    else:
        target.set(value)
