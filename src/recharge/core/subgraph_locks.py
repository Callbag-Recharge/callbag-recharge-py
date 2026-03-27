"""Union-find registry for per-subgraph write locking.

Concurrency contract:
- Only ``state.set()`` is protected by the subgraph write lock.
- ``producer.emit()`` and lifecycle signal pushes are NOT covered — callers
  must synchronize externally if used from multiple threads.
- ``get()`` is lock-free from any thread.
- Graph construction (creating nodes, connecting deps) is safe to interleave
  with ``set()`` calls on independent subgraphs. ``union()`` is serialized
  against ``lock_for()`` via lock-box indirection.
"""

from __future__ import annotations

import threading
import weakref
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from .config import get_deferred_flush_mode

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


class _LockBox:
    """Mutable container for a subgraph's RLock.

    On union, the subsumed root's box is redirected to the canonical root's
    lock. Any thread that already captured a box reference will dereference
    ``.lock`` at acquisition time and get the merged lock — no TOCTOU gap.
    """

    __slots__ = ("lock",)

    def __init__(self) -> None:
        self.lock = threading.RLock()


class _SubgraphRegistry:
    __slots__ = ("_meta_lock", "_parent", "_rank", "_boxes", "_refs")

    def __init__(self) -> None:
        self._meta_lock = threading.RLock()
        self._parent: dict[int, int] = {}
        self._rank: dict[int, int] = {}
        self._boxes: dict[int, _LockBox] = {}
        self._refs: dict[int, weakref.ref[object]] = {}

    # --- Internal helpers (must hold _meta_lock) ---

    def _on_gc(self, node_id: int, ref_obj: weakref.ref[object]) -> None:
        """Weak-ref callback: clean up a GC'd node from the registry."""
        with self._meta_lock:
            # Stale callback guard: node id may have been reused and rebound
            # to a new live weakref slot before this callback executes.
            if self._refs.get(node_id) is not ref_obj:
                return
            self._refs.pop(node_id, None)
            parent = self._parent.get(node_id)
            if parent is None:
                return

            # Rewire direct children before removing the node id from DSU maps.
            direct_children = [
                nid for nid, p in self._parent.items() if p == node_id and nid != node_id
            ]

            if parent == node_id:
                # Node is current root for its component. Promote one child so
                # lock identity remains stable for surviving members.
                if direct_children:
                    new_root = direct_children[0]
                    self._parent[new_root] = new_root
                    for child in direct_children[1:]:
                        self._parent[child] = new_root

                    box = self._boxes.get(node_id)
                    if box is not None:
                        self._boxes[new_root] = box
                    self._rank[new_root] = self._rank.get(new_root, self._rank.get(node_id, 0))
                # If there are no children, the component is gone and maps can
                # be fully removed below.
            else:
                # Non-root node: bypass it in any parent chains.
                for child in direct_children:
                    self._parent[child] = parent

            self._parent.pop(node_id, None)
            self._rank.pop(node_id, None)
            self._boxes.pop(node_id, None)

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
        existing_ref = self._refs.get(node_id)
        existing_obj = existing_ref() if existing_ref is not None else None

        # Fresh node id or stale slot from a GC'd node (id reuse): initialize.
        if node_id not in self._parent or existing_obj is None:
            self._parent[node_id] = node_id
            self._rank[node_id] = 0
            self._boxes[node_id] = _LockBox()
            self._refs[node_id] = weakref.ref(node, lambda _ref: self._on_gc(node_id, _ref))
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

            # Redirect the subsumed root's lock box to the canonical lock.
            # Any thread that already captured box_b will dereference .lock
            # at acquisition time and get the merged lock.
            canonical_lock = self._boxes[root_a].lock
            box_b = self._boxes.get(root_b)
            if box_b is not None:
                box_b.lock = canonical_lock

    @contextmanager
    def lock_for(self, node: object) -> Generator[None]:
        # Validate the lock after acquisition to avoid a union() TOCTOU race
        # between selecting box.lock and entering the lock.
        while True:
            with self._meta_lock:
                node_id = self._ensure_locked(node)
                root = self._find_locked(node_id)
                box = self._boxes.get(root)
                if box is None:
                    box = _LockBox()
                    self._boxes[root] = box
                lock = box.lock

            lock.acquire()
            valid = False
            try:
                with self._meta_lock:
                    current_root = self._find_locked(node_id)
                    current_box = self._boxes.get(current_root)
                    if current_box is None:
                        current_box = _LockBox()
                        self._boxes[current_root] = current_box
                    valid = current_box.lock is lock
                if valid:
                    yield
                    return
            finally:
                lock.release()


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
    current = getattr(_deferred_tls, "depth", 0)
    if current <= 0:
        raise RuntimeError("deferred depth underflow: lock/defer bookkeeping out of balance")
    depth = current - 1
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
            mode = get_deferred_flush_mode()
            first_error: BaseException | None = None
            while queue:
                pending = queue[:]
                queue.clear()
                for fn in pending:
                    if mode == "strict":
                        try:
                            fn()
                        except BaseException as e:  # noqa: BLE001 - strict mode is explicit
                            if first_error is None:
                                first_error = e
                    else:
                        try:
                            fn()
                        except Exception as e:
                            if first_error is None:
                                first_error = e
            if first_error is not None:
                raise first_error


def defer_set(target: Any, value: Any) -> None:
    """Schedule a cross-subgraph set() to run after the current lock is released.

    If not currently inside a subgraph write lock, executes immediately.
    """
    if _get_deferred_depth() > 0:
        _get_deferred_queue().append(lambda: target.set(value))
    else:
        target.set(value)
