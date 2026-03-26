---
SESSION: python-port-strategy
DATE: 2026-03-25
TOPIC: Strategic analysis — porting callbag-recharge to Python
---

## KEY DISCUSSION

### 1. Should callbag-recharge exist in Rust?

Researched the Rust reactive ecosystem (Leptos reactive_graph, Dioxus signals, futures-signals, callbag-rs). Found that `callbag-rs` (30 stars, v0.14.0) is a direct port of the original callbag spec — basic map/filter/take operators. It didn't gain traction because:

- The callbag protocol (single function with integer type tags) fights Rust's type system
- `Arc<dyn Any>` dynamic dispatch is strictly worse than Iterator/Stream traits
- Rust's ownership model makes closure-heavy composition painful

**Key insight:** The callbag *protocol* is a JavaScript solution. The *architecture* (tiered deps, diamond resolution, control-through-graph) is language-agnostic.

**Rust verdict:** The core reactive graph has mature solutions (Leptos reactive_graph, etc.). The gap is orchestration/data/memory — but porting should use idiomatic Rust (traits, enums, arenas), not the callbag wire format.

### 2. Which language should we target?

Evaluated: Elixir (most elegant fit — actor model IS callbag), Lua (underserved, perfect substrate), Python (largest impact), Kotlin (Flow already won), Swift (gap between Combine and AsyncSequence), Dart (decent fit).

**Decision: Python.** Reasons:
- LangChain/LangGraph incumbents are widely criticized for complexity
- Python has no lightweight reactive library (RxPY abandoned)
- The AI agent community is building exactly what orchestrate/ + memory/ + ai/ provide
- The callbag protocol ports trivially to Python
- Market size 10-100x larger than other options

### 3. Monorepo vs separate repo?

**Decision: Separate repo** (`callbag-recharge-py`).
- Different ecosystems, tooling, users (pyproject.toml/pytest/ruff vs package.json/vitest/biome)
- Python version will diverge (async generators, context managers, `|` pipe operator)
- Cross-reference the architecture philosophy; don't co-locate implementations

### 4. Protocol adaptation

**Decision: Don't port the callbag function signature.** Use typed Protocol classes:

| callbag (JS) | Python |
|---|---|
| `sink(0, talkback)` | `talkback = source.subscribe(sink)` |
| `talkback(1)` | `talkback.pull()` |
| `sink(1, value)` | `sink.next(value)` |
| `sink(2)` | `sink.complete()` |
| `sink(3, DIRTY)` | `sink.signal(Signal.DIRTY)` |

**Same push/pull duality, same two-phase DIRTY→DATA, same handshake semantics.** Just typed methods instead of integer tags.

### 5. Async strategy — avoiding event loop hell

**Critical design decision: The core graph is 100% synchronous.**

```python
counter = state(0)
doubled = derived(lambda: counter.get() * 2)
effect(lambda: print(doubled.get()))
counter.set(5)  # prints 10 — synchronously, no await, no event loop
```

Async only at system boundaries (orchestrate/, adapters/). Library never calls `asyncio.get_event_loop()`. Instead:
- `Runner` protocol abstracts async execution
- `pipe.run_sync(data)` — blocking call for scripts (internally does asyncio.run())
- `await pipe.run(data)` — for existing async contexts
- `pipe.start(data)` — fire-and-forget on background thread

### 6. Concurrency model (Python 3.14 free-threaded)

Three levels of concurrency:

**Level 1: Lock-free reads** — `get()` reads stable values, no lock, scales to N threads. Day-one feature.

**Level 2: Per-subgraph write locks** — Independent subgraphs get separate `threading.Lock`. Union-Find tracks membership. `counter.set(5)` and `username.set("Jo")` run truly in parallel if in different subgraphs.

**Level 3: Parallel DATA phase** — During a single transaction, independent derived nodes at the same depth compute in parallel via ThreadPoolExecutor. Opt-in via `parallel=True` per node. Only useful when computation is expensive (>1ms) — e.g., embedding computation, sentiment analysis.

**GIL compatibility:** Works in both modes. Under GIL, subgraph locks are low-contention. Under free-threaded (3.13t/3.14t), full parallelism unlocked. Library is correct by design because:
1. Graph transactions are atomic (lock per subgraph)
2. No compound check-then-act patterns
3. `get()` reads stable values from last completed transaction

**Advantage over competitors:** Most Python state management assumes GIL. In free-threaded Python they'll have subtle data races. Our library is correct from day one.

## REJECTED ALTERNATIVES

1. **Port callbag protocol literally** — `def source(type: int, payload)` works but fights Python's type system, loses IDE support, no static analysis benefit
2. **Depend on asyncio** — Forces event loop setup, breaks simple scripts, adds complexity for no benefit in core graph
3. **Single global lock** — Works but prevents parallel writes on independent subgraphs
4. **Monorepo with TypeScript version** — Different tooling, users, and evolutionary paths make this impractical
5. **Target Rust first** — Existing solutions cover core reactivity. Python has a bigger gap and bigger market.
6. **Target Elixir** — Most elegant fit technically, but tiny market compared to Python/AI ecosystem

## KEY INSIGHTS

1. **The protocol is a JS artifact; the architecture is universal.** Tier system, diamond resolution, control-through-graph, two-phase push — these are language-agnostic design insights.
2. **Python's killer advantage is concurrency.** JS is single-threaded. Python + free-threading = parallel reactive graphs. This is a genuine new capability, not just a port.
3. **The AI agent market is the go-to-market hook.** `pipeline | task(call_llm) | retry(3) | gate(approval)` is cleaner than LangGraph for orchestration.
4. **Sync core, async edges.** Never force users into event loop setup for simple state management.

## FILES CREATED

- `~/src/callbag-recharge-py/` — new repository
- `docs/architecture.md` — adapted from TypeScript version
- `docs/roadmap.md` — phased implementation plan
- `pyproject.toml` — uv + hatch build system
- `.mise.toml` — mise pins uv, uv manages python
- `src/recharge/` — package with all tier subpackages
- `src/archive/docs/` — this session and archive index

---END SESSION---
