# Architecture

> **Status:** Design document. Adapted from callbag-recharge (TypeScript) for Python.
> See the [TypeScript architecture](https://github.com/nicepkg/callbag-recharge/blob/main/docs/architecture.md) for the original.

---

## 1. Core Principles

1. **Every node has a store.** Sources, transforms, and sinks all maintain `_value` and `_status`. Any node in the graph can be read at any time via `.get()`.

2. **Three roles, not three primitives.** Source, transform, sink. `state` and `derived` are user-facing sugar; `producer`, `operator`, and `effect` are the implementation primitives.

3. **Typed protocol, not integer tags.** The TypeScript version uses callbag's `(type: 0|1|2|3, payload)` encoding. Python uses typed Protocol classes (`Sink.next()`, `Sink.signal()`, `Talkback.pull()`, `Talkback.stop()`) — same push/pull semantics, idiomatic Python encoding.

4. **A tap keeps every node's store current.** Handler callbacks fire on every DATA and STATE signal. `_value` and `_status` are always up to date.

5. **Type 1 DATA carries only real values.** Never sentinels. DIRTY, RESOLVED, and other control signals live exclusively on STATE.

6. **STATE is forwarded, not swallowed.** Unknown signals pass through downstream unchanged. Forward-compatible (PAUSE, RESUME, etc.).

7. **DIRTY before DATA, always.** Phase 1: DIRTY propagates downstream. Phase 2: DATA follows.

8. **RESOLVED means "I was dirty, value didn't change."** Only sent if a DIRTY was sent in the same cycle.

9. **Bitmask at convergence points only.** Diamond resolution bitmask only at nodes with multiple deps. Linear chains carry DIRTY straight through.

10. **Batch defers DATA, not DIRTY.** DIRTY propagates immediately during `batch()`. DATA is deferred to the outermost batch exit.

11. **Completion is terminal.** After a node completes or errors, it emits nothing further.

12. **Effects run inline.** When all dirty deps resolve, the effect fn runs synchronously. No scheduler.

13. **The core graph is 100% synchronous.** No asyncio, no trio, no event loop. `state.set()` triggers DIRTY→DATA synchronously. Async exists only at system boundaries (orchestrate/, adapters/).

14. **High-level layers speak domain language.** `core/`, `extra/`, `utils/` expose reactive plumbing. `orchestrate/`, `patterns/`, `ai/` present user-friendly APIs with domain semantics. Internals go under an `inner` property.

15. **Control flows through the graph, not around it.** Lifecycle events (reset, cancel, pause, resume) propagate as STATE signals through the graph — never as imperative method calls that bypass the topology. **Litmus test:** if adding a new orchestrate node requires registering it in a flat list for lifecycle management, the design is wrong.

16. **No raw coroutines in business logic — use library primitives.** System boundary calls (HTTP, file I/O) are wrapped into sources via `from_awaitable` / `from_async_iter`. User callbacks are wrapped with `from_any` (accepts sync, coroutine, async generator, or source).

17. **Push/pull via protocol, never poll.** Wait for conditions via reactive stores + `first_value_from`, not polling loops.

18. **No `asyncio.ensure_future` / `threading.Timer` for reactive coordination.** Use `effect` or `derived` to chain reactive updates. Timer usage only at true system boundaries.

19. **Prefer `subscribe` over `effect` for single-dep data sinks.** `subscribe` has no DIRTY/RESOLVED overhead — use it when: single store dep, no diamond risk, no cleanup.

20. **Pluggable async runner.** The library never calls `asyncio.get_event_loop()`. A `Runner` protocol abstracts async execution. Users choose asyncio, trio, or sync. Only `orchestrate/` and `adapters/` touch the runner.

---

## 2. Protocol: Python Encoding

The TypeScript version uses callbag's single-function signature with integer type tags. Python uses typed Protocol classes that preserve the same semantics:

```python
from typing import Protocol, TypeVar, Generic

T = TypeVar("T")

class Sink(Protocol[T]):
    """Receives signals from upstream (source → sink direction)."""
    def next(self, value: T) -> None: ...       # DATA — pushed value
    def complete(self) -> None: ...              # END — no error
    def error(self, err: Exception) -> None: ... # END — with error
    def signal(self, sig: Signal) -> None: ...   # STATE — DIRTY, RESOLVED, lifecycle

class Talkback(Protocol):
    """Sends signals upstream (sink → source direction)."""
    def pull(self) -> None: ...                  # Request next value (pull mode)
    def stop(self) -> None: ...                  # Unsubscribe (END upstream)
    def signal(self, sig: Signal) -> None: ...   # Lifecycle: RESET, PAUSE, RESUME, TEARDOWN

class Source(Protocol[T]):
    """Subscribable — the START handshake."""
    def subscribe(self, sink: Sink[T]) -> Talkback: ...
```

### Signal vocabulary

```python
from enum import Enum, auto

class Signal(Enum):
    DIRTY = auto()       # "My value is about to change."
    RESOLVED = auto()    # "I was dirty, value didn't change."
    RESET = auto()       # Reset to initial state
    PAUSE = auto()       # Pause activity
    RESUME = auto()      # Resume after pause
    TEARDOWN = auto()    # Terminal — complete + cleanup
```

### Two-phase push

```python
sink.signal(Signal.DIRTY)     # phase 1: "prepare"
sink.next(value)               # phase 2: "new value"
sink.signal(Signal.RESOLVED)   # alternative phase 2: "no change"
```

### Push/pull duality

A **listenable** source pushes via `sink.next()` proactively.
A **pullable** source waits for `talkback.pull()` before sending.
A **hybrid** source does both — exactly like callbag.

### Pipe operator

```python
# | operator for composing sources and operators
result = source | map(fn) | filter(pred) | take(5)

# Equivalent to pipe() from TypeScript version
result = pipe(source, map(fn), filter(pred), take(5))
```

---

## 3. Folder & Dependency Hierarchy

> **This is the single source of truth for import rules.**

```
src/recharge/
├── core/            ← foundation: 6 primitives + protocol + inspector + pipe + types
├── raw/             ← pure protocol primitives (subscribe, from_timer, first_value_from, from_any) — no core deps
├── extra/           ← operators, sources, sinks (tier 1 + tier 2)
├── utils/           ← resilience, async, tracking (with_status, with_breaker, retry, backoff, …)
├── data/            ← reactive data structures (ReactiveDict, ReactiveList, reactive_sorted, pubsub)
├── orchestrate/     ← workflow nodes (pipeline, task, branch, approval, gate)
├── messaging/       ← topic/subscription system
├── memory/          ← agent memory primitives (collection, decay, vector_index)
├── patterns/        ← composed recipes (create_store, form_field, pagination, …)
├── adapters/        ← external connectors (from_http, from_websocket, from_mcp, …)
├── compat/          ← framework bindings (fastapi, django, pydantic)
├── ai/              ← AI/LLM surface (chat_stream, rag_pipeline, doc_index, from_llm, …)
└── __init__.py      ← public API (core primitives only; other layers via subpackage imports)
```

### Dependency tiers

```
Tier -1 (raw protocol) raw/
                         ↓
Tier 0 (foundation)    core/
                         ↓
Tier 1 (operators)     extra/
                         ↓
Tier 2 (utilities)     utils/
                         ↓
Tier 3 (domains)       orchestrate/    messaging/    memory/
                         ↓                ↓              ↓
Tier 4 (surface)       patterns/    adapters/    compat/
                         ↓                ↓
Tier 5 (ai)            ai/
```

`data/` is a **cross-cutting layer** — importable from any tier (core excluded).

### Strict import rules

- `raw/` never imports from any other folder — pure protocol, zero dependencies
- `core/` imports from `raw/` only
- `extra/` imports from `core/` and `raw/` only
- `utils/` imports from `core/`, `raw/`, and `extra/` only
- `data/` imports from `core/`, `raw/`, and `utils/` only
- `orchestrate/` imports from `core/`, `raw/`, `extra/`, `utils/`, and `data/`
- `messaging/` imports from `core/`, `raw/`, `extra/`, `utils/`, `data/`, and `orchestrate/`
- `memory/` imports from `core/`, `raw/`, `utils/`, and `data/`
- `patterns/` imports from everything except `ai/`
- `adapters/` imports from everything except `ai/`
- `compat/` imports from `core/`, `raw/`, `extra/`, `orchestrate/`, and `memory/` only
- `ai/` imports from everything. Nothing imports from `ai/`.
- **Intra-folder imports are always allowed**

---

## 4. Concurrency Model

### Principle: Correct by default, concurrent when you ask for it

The core reactive graph is **synchronous and single-writer**. Concurrency is layered on top.

### Level 1: Lock-free reads

`get()` reads a stable, already-computed value. No lock, no contention. Scales to N threads.

```python
counter = state(0)
doubled = derived(lambda: counter.get() * 2)
# Any thread can call doubled.get() at any time — zero contention
```

### Level 2: Per-subgraph write locks

Independent subgraphs (disconnected components in the dependency DAG) get separate locks. Sets on different subgraphs run truly in parallel.

```python
# Subgraph A: counter → doubled → effect_a
# Subgraph B: username → greeting → effect_b
# These two set() calls run in parallel — different locks
counter.set(5)      # thread A, locks subgraph A
username.set("Jo")  # thread B, locks subgraph B
```

Union-Find tracks subgraph membership. When a new `derived` connects nodes from two subgraphs, they merge.

### Level 3: Parallel DATA phase (opt-in)

During a single transaction's DATA phase, independent derived nodes at the same depth compute in parallel.

```python
# text.set("...") triggers:
#   depth 0: text (source)
#   depth 1: embedding, sentiment, keywords — all independent, compute in parallel
#   depth 2: summary — waits for all three, then computes
embedding = derived(lambda: compute_embedding(text.get()), parallel=True)
sentiment = derived(lambda: analyze_sentiment(text.get()), parallel=True)
keywords  = derived(lambda: extract_keywords(text.get()), parallel=True)
summary   = derived(lambda: f"{embedding.get()} {sentiment.get()} {keywords.get()}")
```

### Thread safety guarantees

| Operation | GIL mode (default) | Free-threaded (3.13t/3.14t) |
|-----------|--------------------|-----------------------------|
| `get()` from any thread | Safe (GIL) | Safe (lock-free reads) |
| `set()` from any thread | Safe (subgraph lock) | Safe (subgraph lock) |
| Parallel derived computation | Sequential (GIL) | True parallelism |
| Graph construction | Not thread-safe (do at startup) | Not thread-safe (do at startup) |

### Write safety scope

Only `state.set()` is protected by the per-subgraph write lock. `producer.emit()` and lifecycle signal pushes are **not** covered — callers must synchronize externally if using these from multiple threads.

### Cross-subgraph writes

An effect in subgraph A that calls `state.set()` on a state in subgraph B risks deadlock if another thread does the reverse (classic lock-ordering deadlock). Use `defer_set(target, value)` to queue cross-subgraph writes for execution after the current subgraph lock is released:

```python
from recharge.core import defer_set

# Inside an effect that holds subgraph A's lock:
defer_set(b_state, new_value)  # Executes after A's lock releases
```

Same-subgraph nested `set()` calls are safe — `RLock` handles re-entrancy.

### Batch thread isolation

Each thread has its own batch context (`batch()` state is thread-local). Batches do not span threads. Deferred emissions re-acquire the subgraph write lock during drain to maintain atomicity.

### Registry GC safety

The subgraph registry uses weak references to nodes. When a node is garbage collected, its registry entry is automatically cleaned up, preventing `id()` reuse collisions and unbounded registry growth.

### Async runner (system boundaries only)

```python
class Runner(Protocol):
    def schedule(self, coro: Coroutine) -> None: ...
    def sleep(self, seconds: float) -> Awaitable: ...
    def cancel(self, handle: Any) -> None: ...
```

Only `orchestrate/` and `adapters/` use the runner. Core graph never touches it.

---

## 5. Node Roles

### Source (`producer`) — originates values

- Has no deps. Maintains `_value`, exposes `get()` / `source()`.
- `state(initial)` = producer with `set()` / `update()` and `equals=operator.is_`
- Emits DIRTY then DATA on change; emits RESOLVED if `equals` fires

### Transform (`operator` / `derived`) — receives deps, produces output

- Has one or more deps. Maintains `_value` and `_status`.
- `derived([deps], fn)` = operator with lazy connect/disconnect lifecycle
- Exposes `get()` and `source()` — full store, subscribable downstream

### Sink (`effect`) — terminal, no downstream

- Has deps, tracks DIRTY/RESOLVED, runs `fn()` when deps settle
- No `get()` or `source()`. Returns `dispose()`.

---

## 6. Extra Operators (`extra/`)

18 operators split across two tiers by implementation strategy.

### Tier 1 — operator/derived-based (synchronous, no timers)

| Operator | Strategy | Notes |
|----------|----------|-------|
| `map(fn)` | `derived` | Simple computed transform |
| `filter(predicate)` | `operator` | Sends RESOLVED when predicate fails; tracks `dirty_forwarded` |
| `scan(reducer, seed)` | `operator` | Accumulator; sends RESOLVED on equal accumulation |
| `take(n)` | `operator` | Disconnects + completes after *n* values |
| `skip(n)` | `operator` | Suppresses DIRTY/RESOLVED during skip window |
| `take_while(predicate)` | `operator` | Disconnects + completes when predicate fails |
| `distinct_until_changed()` | `derived` | Uses `operator.is_` equality by default |
| `merge(*sources)` | `operator` | Multi-dep; bitmask dirty tracking; `any_data` flag prevents spurious RESOLVED |
| `combine(*sources)` | `derived` | Multi-dep tuple; recomputes when any dep changes |
| `zip(*sources)` | `operator` | Per-source deque buffers; `max_buffer` caps buffer size |

### Tier 2 — producer-based (cycle boundaries, may use timers)

| Operator | Notes |
|----------|-------|
| `debounce(ms)` | `threading.Timer`; clears pending reference after flush |
| `throttle(ms)` | `threading.Timer`; leading-edge emit |
| `sample(notifier)` | Dual subscribe; latest input emitted on notifier tick |
| `switch_map(fn)` | Cancels previous inner on new outer; `_UNSET` sentinel for initial |
| `concat_map(fn)` | Queues inner sources; `deque` buffer; `_UNSET` sentinel |
| `flat_map(fn)` | Concurrent inner sources; `set` tracking; `_UNSET` sentinel |

### Utility

| Operator | Notes |
|----------|-------|
| `share` | No-op — stores are already multicast |
| `replay` | Seeds with last value on reconnect via `actions.seed()` |

All operators support `pipe()` and `|` syntax: `source | map(fn) | filter(pred) | take(5)`.

---

## 7. Diamond Resolution

Multi-dep nodes use a bitmask to track which deps are dirty. Recompute fires only when all bits clear.

- **DIRTY from dep N:** set bit N, forward DIRTY on first dirty dep only
- **RESOLVED from dep N:** clear bit N, forward RESOLVED if all clear
- **DATA from dep N:** clear bit N, recompute if all clear

Python implementation: `int` (unlimited precision) — no need for `Uint32Array` fallback.

---

## 8. `.get()` Semantics

| Status | `.get()` behavior |
|--------|-------------------|
| `SETTLED` / `RESOLVED` | Return `_value` (current) |
| `DIRTY` | Return `_value` (may be stale) |
| `DISCONNECTED` | Pull-recompute: call `_fn()`, write to `_value`, return |
| `COMPLETED` | Return last value before terminal |
| `ERRORED` | **Raise** stored error |

---

## 9. Output Slot

Lazy multicast dispatch point per node:

```
DISCONNECTED (None) ──→ SINGLE (sink) ──→ MULTI (set)
      ↑                      |                |
      └──[last unsub]────────┘                |
      └──[last unsub]─────────────────────────┘
```

On last unsubscribe: `_output = None`, disconnect from deps, status = DISCONNECTED.

---

## 10. Lifecycle Signals

Flow **upstream** via `talkback.signal(sig)`:

| Signal | Behavior |
|--------|----------|
| RESET | Reset `_value` to initial, clear derived cache, re-run effect |
| PAUSE | Forward upstream; tier 2 extras handle locally |
| RESUME | Forward upstream; resume paused activity |
| TEARDOWN | Handle cleanup, then `complete()` — cascades END downstream |

---

## 11. Python-Specific Adaptations

### Context managers for resource lifecycle

```python
with subscribe(store) as sub:
    ...  # auto-unsubscribes on exit

with batch():
    counter.set(1)
    name.set("Jo")
# DATA propagates here
```

### `|` pipe operator

```python
result = source | map(fn) | filter(pred) | take(5) | for_each(print)
```

### Iterator/AsyncIterator integration

```python
# Pull-based source from iterator
nums = from_iter(range(100))

# Async source from async generator
prices = from_async_iter(stock_prices("AAPL"))

# Consume a source as an iterator
for value in iter(store):
    print(value)
```

### No raw coroutines in library internals

| Pattern | Replacement |
|---------|-------------|
| `await some_coro()` | `subscribe(from_awaitable(some_coro()), cb)` |
| `asyncio.sleep(n)` | `from_timer(n)` |
| `async for x in agen` | `from_async_iter(agen)` |
| `await user_callback()` | `from_any(user_callback())` (handles sync, coro, async gen, source) |

---

## 12. Comparison with TypeScript Version

| Aspect | TypeScript | Python |
|--------|-----------|--------|
| Protocol encoding | `(type: 0\|1\|2\|3, payload)` single function | Typed Protocol classes (`Sink`, `Talkback`, `Source`) |
| Push/pull duality | Same | Same |
| Two-phase push | Same | Same |
| Diamond resolution | Bitmask (number / Uint32Array) | Bitmask (Python `int`, unlimited) |
| Pipe syntax | `pipe(a, b, c)` | `a \| b \| c` or `pipe(a, b, c)` |
| Resource cleanup | Manual unsubscribe | Context managers + unsubscribe |
| Async at boundaries | `fromPromise`, `fromAsyncIter` | `from_awaitable`, `from_async_iter` |
| Concurrency | Single-threaded (JS) | Multi-threaded: lock-free reads, per-subgraph writes, parallel derived |
| Event loop | Not needed (sync core) | Not needed (sync core). Runner for orchestrate/ only |
| V8 optimizations | Hidden classes, flag packing | N/A — use `__slots__`, avoid dict overhead |
| Compatibility targets | TC39 Signals, RxJS, raw callbag | Pydantic, FastAPI, Django, asyncio, trio |
