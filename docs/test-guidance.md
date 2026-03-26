# Test Guidance

Guidelines for writing, organizing, and maintaining tests in callbag-recharge-py. Read this before adding any new tests.

---

## Guiding Principles

1. **Verify before fixing.** Every "known bug" is a hypothesis until a test exposes it. Write the test first. If it passes, the hypothesis was wrong — delete the test or adjust expectations. Do not blindly implement fixes.

2. **Existing tests may be wrong.** When a new test contradicts an existing test's expectation, read the source code to determine which is correct. The source is the authority — update whichever test has the wrong expectation.

3. **Design choices ≠ bugs.** Some behaviors are intentional:
   - `state` uses `is` for equality (like `Object.is` in the TS version).
   - Stores are inherently multicast — no `share()` needed.
   - Completion ordering is cleanup-first (same as the TS version).
   - Core graph is 100% synchronous — no asyncio involvement in core tests.

   When in doubt, write the test, see what happens, and check `docs/architecture.md` before "fixing."

4. **Test what the code *should* do, not what it *does*.** Write tests expressing the correct semantic. If the test fails, that's a real bug. If it passes, the code was already correct.

5. **One concern per test.** Each `test_*` function should verify one specific behavior. Do not bundle "happy path + error + completion + reconnect" into one test.

6. **Observer-first for assertions.** Use `observe()` (the Python equivalent of `Inspector.observe()`) for collecting emitted values and signals in tests — never wire raw protocol sinks manually. Raw sinks are only acceptable when testing the protocol itself.

7. **Authority hierarchy for expected behavior:**
   - `docs/architecture.md` → primary. Defines correct behavior for this library.
   - TypeScript callbag-recharge → for operator semantics when not explicitly covered above.
   - RxJS documentation → for operator naming and behavior conventions.

---

## Test File Organization

```
tests/
├── test_core.py                    — state, derived, effect, producer, operator, pipe, batch
├── test_protocol.py                — protocol compliance, signal types, two-phase push
├── test_signals.py                 — DIRTY/RESOLVED control flow, diamond resolution
├── test_lifecycle.py               — RESET, PAUSE, RESUME, TEARDOWN propagation
├── test_extra_tier1.py             — passthrough operators (map, filter, scan, take, skip)
├── test_extra_tier2.py             — time-based, dynamic subscription (debounce, switchMap, etc.)
├── test_sources.py                 — from_iter, from_awaitable, from_async_iter, from_timer
├── test_reconnect.py               — disconnect→reconnect for all operators
├── test_data.py                    — ReactiveDict, ReactiveList, pubsub
├── test_orchestrate.py             — pipeline, task, branch, gate, task_state
├── test_concurrency.py             — thread safety: concurrent get/set, subgraph locks, parallel derived
├── test_regressions.py             — bug regression suite (never delete entries)
└── conftest.py                     — shared fixtures (observe, helpers)
```

**Rule:** New tests go in the most specific existing file. Create a new file only when the scope is genuinely orthogonal to all existing files.

---

## What to Test for Every Operator

### For tier 1 operators (operator-based)

- [ ] **Happy path:** correct output for basic input
- [ ] **STATE forwarding:** DIRTY propagates to downstream
- [ ] **RESOLVED when suppressing:** filter/distinct_until_changed sends RESOLVED (not silence)
- [ ] **Upstream error → `error(err)` forwarded**, not swallowed or converted to complete
- [ ] **Upstream completion → `complete()` forwarded**
- [ ] **Reconnect:** local state resets on disconnect→reconnect
- [ ] **Diamond resolution:** in a diamond topology (A→B→D, A→C→D), D computes exactly once

### For tier 2 operators (producer-based)

- [ ] **Happy path:** correct output for basic input
- [ ] **Upstream error → forwarded**
- [ ] **Upstream completion → forwarded** (some operators flush pending on complete, e.g., debounce)
- [ ] **Teardown:** all resources cleaned up (timers cancelled, inner unsub called)
- [ ] **Reconnect:** fresh state after reconnect (timer restarts, queue empty, etc.)
- [ ] **get() value:** correct before first emit, correct after several emits

### For source operators (producer-based sources)

- [ ] **Emits expected values**
- [ ] **Completes correctly**
- [ ] **Error forwarded** (from_awaitable rejection, etc.)
- [ ] **Cleanup on unsubscribe** (listener removed, iterator released, etc.)
- [ ] **Multiple subscribers:** multicast behavior
- [ ] **Late subscriber after completion:** gets immediate END

### For sink functions (subscribe)

- [ ] **Callback called with correct values**
- [ ] **Unsubscribe function disconnects cleanly**
- [ ] **Does not track DIRTY** (sinks are purely reactive to DATA)

---

## Diamond Resolution Testing Pattern

Diamond tests are critical — they verify that derived nodes compute exactly once even when multiple paths connect them to the same source.

```python
def test_diamond_computes_once():
    a = state(1)
    b = derived([a], lambda: a.get() * 2)   # a → b
    c = derived([a], lambda: a.get() + 10)   # a → c
    d = derived([b, c], lambda: b.get() + c.get())  # b,c → d

    d_count = 0
    def d_effect():
        nonlocal d_count
        d_count += 1
    effect([d], d_effect)

    a.set(5)
    assert d_count == 1    # d computes once, not twice
    assert d.get() == 25   # (5*2) + (5+10) = 10 + 15 = 25
```

Always verify:
1. The count (exactly once per upstream change)
2. The value (correct final value with all deps resolved)

---

## RESOLVED Signal Testing Pattern

RESOLVED enables subtree skipping. Test that downstream nodes skip computation when a dep sends RESOLVED.

```python
def test_resolved_skips_downstream():
    a = state(1)
    b = derived([a], lambda: a.get())   # equals uses `is` by default

    c_count = 0
    def c_fn():
        nonlocal c_count
        c_count += 1
        return b.get() + 100
    c = derived([b], c_fn)
    effect([c], lambda: None)  # activate

    a.set(1)  # same value → b sends RESOLVED → c skips
    assert c_count == 0  # c did not rerun
```

---

## Observer Testing Utility

Use the `observe()` helper for collecting emitted values and signals. This is the **mandatory tool** for observing store output in tests.

### Anti-patterns (do NOT use in tests)

```python
# ❌ Manual sink — hard to read, easy to get wrong
values = []
store.subscribe(ManualSink(on_next=lambda v: values.append(v)))

# ✅ observe() — typed, complete, standard
obs = observe(store)
assert obs.values == [1, 2, 3]
```

### `observe(store)` API

```python
obs = observe(store)
obs.values          # DATA payloads only
obs.signals         # STATE payloads (Signal.DIRTY, Signal.RESOLVED, etc.)
obs.events          # full protocol order: [("DATA", 5), ("SIGNAL", Signal.DIRTY), ...]
obs.dirty_count     # DIRTY signal count
obs.resolved_count  # RESOLVED signal count
obs.ended           # True after END
obs.end_error       # error payload if END(error)
obs.completed_cleanly  # ended and no error
obs.errored         # ended and has error
obs.dispose()       # unsubscribe
obs.reconnect()     # dispose + fresh observe on same store
```

### When to use which tool

| Use case | Best tool |
|---|---|
| **"Did it recompute once?"** | Inline `nonlocal` counter in `fn()` |
| **"What values were emitted?"** | `obs.values` |
| **"Was DIRTY sent before DATA?"** | `obs.events` → `[("SIGNAL", DIRTY), ("DATA", 5), ...]` |
| **"Did RESOLVED skip downstream?"** | `obs.resolved_count` |
| **"Did it complete cleanly?"** | `obs.completed_cleanly` |
| **"Did it error?"** | `obs.errored` + `obs.end_error` |
| **"Disconnect and re-subscribe"** | `obs.reconnect()` |

---

## Error Forwarding Testing Pattern

Always verify that errors propagate as errors (not completions):

```python
def test_error_propagation():
    source = producer(lambda api: api.error(ValueError("fail")))
    obs = observe(source)
    assert obs.ended is True
    assert isinstance(obs.end_error, ValueError)
```

---

## Reconnect Testing Pattern

Reconnect tests verify that operators produce correct behavior after all subscribers disconnect and a new subscriber connects.

```python
def test_skip_resets_on_reconnect():
    a = state(0)
    skipped = pipe(a, skip(2))

    # First subscription
    values1 = []
    sub1 = subscribe(skipped, lambda v, _: values1.append(v))
    a.set(1); a.set(2); a.set(3)
    sub1.unsubscribe()
    # values1 = [3] (skipped first 2)

    # Reconnect — skip counter must reset
    values2 = []
    sub2 = subscribe(skipped, lambda v, _: values2.append(v))
    a.set(4); a.set(5); a.set(6)
    sub2.unsubscribe()
    assert values2 == [6]  # skip resets, first 2 of new session skipped
```

---

## Concurrency Testing Patterns

Thread safety tests are essential for the Python port. Test under both GIL and free-threaded modes when possible.

### Concurrent reads

```python
import threading

def test_concurrent_reads():
    """get() from multiple threads must never see a half-propagated state."""
    s = state(0)
    d = derived([s], lambda: s.get() * 2)
    effect([d], lambda: None)  # activate

    results = []
    def reader():
        for _ in range(1000):
            v = d.get()
            assert v % 2 == 0  # always even — never half-updated
            results.append(v)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads: t.start()

    # Writer in main thread
    for i in range(100):
        s.set(i)

    for t in threads: t.join()
```

### Concurrent writes on independent subgraphs

```python
def test_independent_subgraph_writes():
    """set() on independent subgraphs should not deadlock or corrupt."""
    a = state(0)
    b = state(0)
    a_log = []
    b_log = []
    effect([derived([a], lambda: a.get())], lambda: a_log.append(a.get()))
    effect([derived([b], lambda: b.get())], lambda: b_log.append(b.get()))

    def writer_a():
        for i in range(1000):
            a.set(i)

    def writer_b():
        for i in range(1000):
            b.set(i)

    t1 = threading.Thread(target=writer_a)
    t2 = threading.Thread(target=writer_b)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert a_log[-1] == 999
    assert b_log[-1] == 999
```

### Parallel derived computation

```python
import time

def test_parallel_derived_computation():
    """Independent derived nodes at the same depth compute in parallel."""
    text = state("hello")

    def slow_a():
        time.sleep(0.05)
        return f"a:{text.get()}"

    def slow_b():
        time.sleep(0.05)
        return f"b:{text.get()}"

    a = derived([text], slow_a, parallel=True)
    b = derived([text], slow_b, parallel=True)
    combined = derived([a, b], lambda: f"{a.get()}+{b.get()}")
    effect([combined], lambda: None)  # activate

    start = time.monotonic()
    text.set("world")
    elapsed = time.monotonic() - start

    assert combined.get() == "a:world+b:world"
    # If parallel: ~50ms. If sequential: ~100ms.
    # Use generous threshold to avoid flaky tests.
    assert elapsed < 0.09  # less than 2x — proves parallelism
```

---

## Orchestrate / Pipeline Testing Patterns

Pipeline tests verify workflow-level behavior: status derivation, task lifecycle, reset.

### Pipeline status derivation

```python
def test_pipeline_status_transitions():
    trigger = state(None)
    wf = pipeline({
        "trigger": source(trigger),
        "fetch": task(["trigger"], lambda signal, deps: fetch_data(deps[0])),
    })

    assert wf.status.get() == "idle"
    trigger.set("go")
    assert wf.status.get() == "active"
    # ... await completion
    assert wf.status.get() == "completed"
```

### Reset returns to idle

```python
def test_pipeline_reset():
    # ... trigger and complete ...
    wf.reset()
    assert wf.status.get() == "idle"
```

### What to test for pipeline

- [ ] **Status transitions:** idle → active → completed, idle → active → errored
- [ ] **Skipped tasks:** skip predicate → status "skipped", pipeline still completes
- [ ] **Reset:** completed → reset → idle; re-trigger works after reset
- [ ] **Task lifecycle hooks:** on_start, on_success, on_error, on_skip fire correctly
- [ ] **Destroy cleanup:** wf.destroy() tears down all subscriptions
- [ ] **Cancellation:** signal-based cancellation propagates to running tasks

---

## Regression Tests

The `test_regressions.py` file records every confirmed bug that was found and fixed. **Never delete entries from this file.** Each regression test should have a comment explaining:

```python
def test_regression_diamond_double_compute():
    """Bug: diamond with batch() triggered derived recompute twice.
    Fixed: defer DATA in batch, not DIRTY.
    Date: 2026-xx-xx
    """
    ...
```

When a bug is fixed, add the regression test immediately before closing the issue.

---

## Running Tests

```bash
# Full suite
uv run pytest

# Single file
uv run pytest tests/test_core.py

# Single test
uv run pytest tests/test_core.py::test_state_basic

# With verbose output
uv run pytest -v

# With print output shown
uv run pytest -s

# Concurrency tests only
uv run pytest tests/test_concurrency.py

# Stop on first failure
uv run pytest -x
```
