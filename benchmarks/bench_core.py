"""Basic benchmarks: recharge reactive graph vs manual state management.

Run with: uv run python benchmarks/bench_core.py
"""

from __future__ import annotations

import time
from typing import Any

from recharge import batch, derived, effect, state, subscribe


def bench(name: str, fn: Any, n: int = 10_000) -> float:
    """Run fn() n times, return total ms."""
    start = time.perf_counter()
    for _ in range(n):
        fn()
    elapsed_ms = (time.perf_counter() - start) * 1000
    per_op = elapsed_ms / n * 1000  # µs per op
    print(f"  {name}: {elapsed_ms:.1f}ms total, {per_op:.1f}µs/op  (n={n})")
    return elapsed_ms


def main() -> None:
    n = 50_000

    print("=" * 60)
    print("Benchmark: recharge vs manual state management")
    print("=" * 60)

    # --- 1. Simple set/get ---
    print("\n1. state.set() + state.get()")
    s = state(0)

    def reactive_set_get() -> None:
        s.set(s.get() + 1)

    manual_val = [0]

    def manual_set_get() -> None:
        manual_val[0] += 1

    bench("recharge state", reactive_set_get, n)
    bench("manual variable", manual_set_get, n)

    # --- 2. Derived chain (A → B → C) ---
    print("\n2. Derived chain: A → B → C, read C")
    a = state(0)
    b = derived([a], lambda: a.get() * 2)
    c = derived([b], lambda: b.get() + 1)
    # Activate
    sub_c = subscribe(c, lambda v, _: None)

    def reactive_chain() -> None:
        a.set(a.get() + 1)
        c.get()

    m_a = [0]
    m_b = [0]
    m_c = [0]

    def manual_chain() -> None:
        m_a[0] += 1
        m_b[0] = m_a[0] * 2
        m_c[0] = m_b[0] + 1

    bench("recharge chain", reactive_chain, n)
    bench("manual chain", manual_chain, n)
    sub_c.unsubscribe()

    # --- 3. Diamond (A → B, A → C, B+C → D) ---
    print("\n3. Diamond: A → B, A → C, B+C → D")
    a2 = state(0)
    b2 = derived([a2], lambda: a2.get() + 10)
    c2 = derived([a2], lambda: a2.get() + 100)
    d2 = derived([b2, c2], lambda: b2.get() + c2.get())
    sub_d = subscribe(d2, lambda v, _: None)

    def reactive_diamond() -> None:
        a2.set(a2.get() + 1)

    m2_a = [0]

    def manual_diamond() -> None:
        m2_a[0] += 1
        _b = m2_a[0] + 10
        _c = m2_a[0] + 100
        _d = _b + _c

    bench("recharge diamond", reactive_diamond, n)
    bench("manual diamond", manual_diamond, n)
    sub_d.unsubscribe()

    # --- 4. Batched updates ---
    print("\n4. Batched set (3 states, 1 derived)")
    s1 = state(0)
    s2 = state(0)
    s3 = state(0)
    combined = derived([s1, s2, s3], lambda: s1.get() + s2.get() + s3.get())
    sub_combined = subscribe(combined, lambda v, _: None)

    i = [0]

    def reactive_batched() -> None:
        i[0] += 1
        with batch():
            s1.set(i[0])
            s2.set(i[0])
            s3.set(i[0])

    j = [0]
    m_s = [0, 0, 0]

    def manual_batched() -> None:
        j[0] += 1
        m_s[0] = j[0]
        m_s[1] = j[0]
        m_s[2] = j[0]
        _combined = sum(m_s)

    bench("recharge batched", reactive_batched, n)
    bench("manual batched", manual_batched, n)
    sub_combined.unsubscribe()

    # --- 5. Effect with cleanup ---
    print("\n5. Effect with cleanup callback")
    es = state(0)

    def eff_fn() -> Any:
        es.get()
        return lambda: None  # cleanup

    dispose = effect([es], eff_fn)

    def reactive_effect() -> None:
        es.set(es.get() + 1)

    m_val = [0]
    m_cleanup = [None]

    def manual_effect() -> None:
        if m_cleanup[0] is not None:
            m_cleanup[0]()
        m_val[0] += 1
        m_cleanup[0] = lambda: None

    bench("recharge effect", reactive_effect, n)
    bench("manual effect", manual_effect, n)
    dispose()

    print("\n" + "=" * 60)
    print("Done. Reactive overhead is expected — it buys you automatic")
    print("dependency tracking, diamond resolution, and glitch-freedom.")
    print("=" * 60)


if __name__ == "__main__":
    main()
