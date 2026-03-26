# Roadmap

> **Status:** Living document. Single source of truth for what's planned.
> Ported from [callbag-recharge](https://github.com/nicepkg/callbag-recharge) TypeScript library.

---

## Phase 0: Foundation (current)

### 0.1 — Project scaffold ✅
- [x] Repository setup: uv, mise, ruff, pytest, mypy
- [x] Architecture doc adapted from TypeScript version
- [x] Folder structure with dependency tiers
- [x] Design session archived

### 0.2 — Protocol & core primitives ✅
- [x] `Signal` enum (DIRTY, RESOLVED, RESET, PAUSE, RESUME, TEARDOWN)
- [x] `Sink`, `Talkback`, `Source` Protocol classes
- [x] `State` — mutable source with `get()`, `set()`, `update()`
- [x] `Derived` — computed from deps with lazy connect/disconnect
- [x] `DynamicDerived` — runtime-tracked dependency graph
- [x] `Effect` — terminal sink, runs when deps settle
- [x] `Producer` — custom source (async wrapping, timers, etc.)
- [x] `Operator` — custom transform
- [x] `pipe()` function and `|` operator overload
- [x] `batch()` context manager
- [x] Node status tracking (DISCONNECTED, DIRTY, SETTLED, RESOLVED, COMPLETED, ERRORED)

### 0.3 — Diamond resolution & two-phase push ✅
- [x] Bitmask for multi-dep convergence (Python `int`)
- [x] DIRTY propagation (phase 1)
- [x] DATA propagation (phase 2)
- [x] RESOLVED signal for unchanged values
- [x] Single-dep fast path (no bitmask)

### 0.4 — Output slot & lifecycle ✅
- [x] Lazy output slot: None → single → set
- [x] `_lazy_connect()` / disconnect on last unsub
- [x] RESET, PAUSE, RESUME, TEARDOWN signal propagation
- [x] `subscribe()` — lightweight single-dep sink
- [x] Context manager support (`with subscribe(store) as sub:`)

### 0.5 — Tests & validation ✅
- [x] Port core test suite from TypeScript (35 tests)
- [x] Diamond resolution tests
- [x] Lifecycle signal tests
- [x] `observe()` test helper for protocol-level assertions (`tests/conftest.py`)
- [x] Basic benchmarks vs manual state management (`benchmarks/bench_core.py`)

---

## Phase 1: Operators & utilities

### 1.1 — raw/ layer
- [ ] `raw_subscribe` — pure protocol sink
- [ ] `from_iter` — Iterator → source
- [ ] `from_timer` — delay source (threading.Timer, no asyncio)
- [ ] `first_value_from` — source → awaitable (the ONE bridge)
- [ ] `from_awaitable` — coroutine → source
- [ ] `from_async_iter` — async generator → source
- [ ] `from_any` — universal normalizer (sync/coro/async gen/source)

### 1.2 — extra/ operators
- [ ] `map`, `filter`, `scan`, `take`, `skip`, `take_while`
- [ ] `merge`, `combine`, `zip`
- [ ] `distinct_until_changed`
- [ ] `debounce`, `throttle`, `sample`
- [ ] `switch_map`, `concat_map`, `flat_map`
- [ ] `share` (no-op — stores are multicast), `replay`

### 1.3 — utils/ resilience
- [ ] `retry(n, backoff=...)` — retry with backoff strategies
- [ ] `backoff` — exponential, linear, fibonacci presets
- [ ] `with_status` — wraps source with loading/error/success status
- [ ] `with_breaker` — circuit breaker pattern
- [ ] `timeout` — error if no value within duration

---

## Phase 2: Concurrency

### 2.1 — Thread-safe reads
- [ ] Lock-free `get()` — atomic reference reads
- [ ] Validate on GIL and free-threaded (3.13t/3.14t) builds

### 2.2 — Per-subgraph write locks
- [ ] Union-Find for subgraph detection
- [ ] Per-subgraph `threading.Lock`
- [ ] Subgraph merge on cross-graph `derived`
- [ ] Benchmark: independent set() from N threads

### 2.3 — Parallel DATA phase
- [ ] Depth-grouped computation in DATA phase
- [ ] `parallel=True` opt-in per derived node
- [ ] `configure(parallel_threshold_ms=N)` adaptive parallelism
- [ ] Thread pool management (reuse, sizing)
- [ ] Benchmark: N expensive derived nodes vs sequential

---

## Phase 3: Data structures & orchestration

### 3.1 — data/ layer
- [ ] `ReactiveDict` — dict with per-key change notifications
- [ ] `ReactiveList` — list with index-aware change notifications
- [ ] `reactive_sorted` — sorted view over a reactive collection
- [ ] `pubsub` — publish/subscribe within the graph

### 3.2 — orchestrate/ layer
- [ ] `pipeline` — DAG step composition with pause/resume/cancel
- [ ] `task` — async unit of work with status tracking
- [ ] `branch` — conditional routing
- [ ] `gate` — approval/condition gate
- [ ] `task_state` — per-task reactive state (pending/running/done/error)
- [ ] Pluggable `Runner` protocol for async execution

### 3.3 — messaging/ layer
- [ ] `topic` — named publish point
- [ ] `subscription` — filtered consumer with backpressure

---

## Phase 4: AI & ecosystem

### 4.1 — memory/ layer
- [ ] `collection` — reactive document collection with TTL/decay
- [ ] `vector_index` — embedding-based similarity search
- [ ] `knowledge_graph` — reactive node/edge graph

### 4.2 — ai/ layer (the selling point)
- [ ] `chat_stream` — streaming LLM responses as reactive source
- [ ] `rag_pipeline` — retrieve → augment → generate pipeline
- [ ] `from_llm` — wrap any LLM API as a source
- [ ] `agent_loop` — reactive agent with tool calling

### 4.3 — compat/ layer
- [ ] FastAPI integration (reactive endpoints)
- [ ] Pydantic model ↔ store bridges
- [ ] Django signals bridge
- [ ] asyncio / trio runner implementations

### 4.4 — adapters/ layer
- [ ] `from_http` — HTTP polling/SSE/WebSocket as source
- [ ] `from_websocket` — WebSocket connection as source
- [ ] `from_mcp` — Model Context Protocol integration

---

## Phase 5: Polish & release

### 5.1 — Documentation
- [ ] API reference (auto-generated from docstrings)
- [ ] Getting started guide
- [ ] Recipes: LLM chat, data pipeline, web server state
- [ ] Migration guide from LangChain/LangGraph

### 5.2 — Performance
- [ ] Comprehensive benchmarks (vs RxPY, vs manual, vs asyncio patterns)
- [ ] Free-threaded Python (3.14t) benchmark suite
- [ ] Memory profiling
- [ ] `__slots__` optimization on hot path classes

### 5.3 — Release
- [ ] PyPI publication
- [ ] CI/CD (GitHub Actions)
- [ ] Semantic versioning
- [ ] CHANGELOG

---

## Non-goals (for now)

- **GUI/browser reactivity** — Python isn't the frontend. Focus on backend, AI, data pipelines.
- **Worker/thread bridge** — Python's `multiprocessing` and `concurrent.futures` already handle this. May add later if there's demand.
- **Promise convenience layer** — Python's `await` already works. `first_value_from` is the bridge.
