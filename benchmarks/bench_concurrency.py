"""Benchmark: independent state.set() from N threads.

Measures throughput of concurrent set() calls on independent subgraphs
(separate write locks) vs a single thread baseline.

Run with: uv run python benchmarks/bench_concurrency.py
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

from recharge import derived, effect, state


def _runtime_mode() -> str:
    is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
    if is_gil_enabled is None:
        return "GIL"
    return "GIL" if is_gil_enabled() else "free-threaded"


def bench_single_thread(n_subgraphs: int, writes_per: int) -> float:
    """Baseline: single thread writes to N independent subgraphs sequentially."""
    stores: list[Any] = []
    disposers: list[Any] = []
    for _ in range(n_subgraphs):
        s = state(0)
        d = derived([s], lambda _s=s: _s.get() * 2)
        disposers.append(effect([d], lambda: None))
        stores.append(s)

    start = time.perf_counter()
    for s in stores:
        for i in range(writes_per):
            s.set(i)
    elapsed = time.perf_counter() - start

    for d in disposers:
        d()
    return elapsed


def bench_multi_thread(n_threads: int, writes_per: int) -> float:
    """N threads each write to their own independent subgraph concurrently."""
    stores: list[Any] = []
    disposers: list[Any] = []
    for _ in range(n_threads):
        s = state(0)
        d = derived([s], lambda _s=s: _s.get() * 2)
        disposers.append(effect([d], lambda: None))
        stores.append(s)

    barrier = threading.Barrier(n_threads)

    def writer(s: Any) -> None:
        barrier.wait(timeout=5.0)
        for i in range(writes_per):
            s.set(i)

    threads = [threading.Thread(target=writer, args=(s,)) for s in stores]

    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    elapsed = time.perf_counter() - start

    for d in disposers:
        d()
    return elapsed


def bench_contended(n_threads: int, writes_per: int) -> float:
    """N threads all write to the SAME subgraph (contended lock)."""
    s = state(0)
    d = derived([s], lambda: s.get() * 2)
    dispose = effect([d], lambda: None)

    barrier = threading.Barrier(n_threads)

    def writer() -> None:
        barrier.wait(timeout=5.0)
        for i in range(writes_per):
            s.set(i)

    threads = [threading.Thread(target=writer) for _ in range(n_threads)]

    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    elapsed = time.perf_counter() - start

    dispose()
    return elapsed


def main() -> None:
    writes_per = 50_000
    thread_counts = [1, 2, 4, 8]

    print("=" * 70)
    print(f"Benchmark: concurrent state.set() throughput ({_runtime_mode()} mode)")
    print(f"Writes per subgraph: {writes_per:,}")
    print("=" * 70)

    # --- Single-thread baseline ---
    baselines: dict[int, float] = {}
    for n in thread_counts:
        elapsed = bench_single_thread(n, writes_per)
        baselines[n] = elapsed
        total = n * writes_per
        ops_per_sec = total / elapsed
        per_op = elapsed / total * 1_000_000
        print(
            f"\n  single-thread {n} subgraphs: {elapsed:.3f}s  "
            f"({ops_per_sec:,.0f} ops/s, {per_op:.1f}µs/op)"
        )

    # --- Multi-thread independent subgraphs ---
    print("\n" + "-" * 70)
    print("Independent subgraphs (each thread owns its own subgraph):")
    for n in thread_counts:
        if n < 2:
            continue
        elapsed = bench_multi_thread(n, writes_per)
        total = n * writes_per
        ops_per_sec = total / elapsed
        per_op = elapsed / total * 1_000_000
        speedup = baselines[n] / elapsed
        print(
            f"\n  {n} threads: {elapsed:.3f}s  "
            f"({ops_per_sec:,.0f} ops/s, {per_op:.1f}µs/op, "
            f"{speedup:.2f}x vs single-thread)"
        )

    # --- Contended (same subgraph) ---
    print("\n" + "-" * 70)
    print("Contended (all threads write to same subgraph):")
    for n in thread_counts:
        if n < 2:
            continue
        elapsed = bench_contended(n, writes_per)
        total = n * writes_per
        ops_per_sec = total / elapsed
        per_op = elapsed / total * 1_000_000
        print(f"\n  {n} threads: {elapsed:.3f}s  ({ops_per_sec:,.0f} ops/s, {per_op:.1f}µs/op)")

    print("\n" + "=" * 70)
    print("Key insight: independent subgraphs should scale near-linearly")
    print("with thread count (especially under free-threaded Python).")
    print("Contended writes serialize via the subgraph lock.")
    print("=" * 70)


if __name__ == "__main__":
    main()
