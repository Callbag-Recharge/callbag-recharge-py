# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**uv workspace** managed by mise. `mise trust && mise install` to set up uv. `uv sync` to install deps.

- **Test:** `uv run pytest`
- **Single test:** `uv run pytest tests/test_core.py::test_state_basic`
- **Lint:** `uv run ruff check src/`
- **Lint fix:** `uv run ruff check --fix src/`
- **Format:** `uv run ruff format src/`
- **Type check:** `uv run mypy src/`

## Architecture

Package name is `recharge` (import as `from recharge import ...`). Python >=3.12, targeting 3.14 (free-threaded). Zero external dependencies for core.

Ported from [callbag-recharge](https://github.com/nicepkg/callbag-recharge) (TypeScript). Every store is a source with push/pull duality via typed Protocol classes (`Sink`, `Talkback`, `Source`).

**6 core primitives:** `producer`, `state`, `derived`, `dynamic_derived`, `operator`, `effect`. Same tiered architecture as the TypeScript version.

See [docs/architecture.md](docs/architecture.md) for the full design.

## Key docs

| Doc | What it covers | When to read |
|-----|----------------|-------------|
| [docs/architecture.md](docs/architecture.md) | Protocol, primitives, signal flow, concurrency model, folder structure | Modifying core, adding operators, import rule questions |
| [docs/roadmap.md](docs/roadmap.md) | Phased implementation plan | Planning next work |

## Design invariants

- **Control flows through the graph, not around it** (architecture.md §1.15). Lifecycle events (reset, cancel, pause) must propagate as STATE signals — never as imperative method calls that bypass the graph topology. `threading.Event` or `asyncio.Event` bridges STATE to imperative async but is not the primary mechanism. Litmus test: if a new node needs registering in a flat list for lifecycle management, the design is wrong.
- **Signal-first for orchestrate**: When implementing any orchestrate node (`task`, `for_each`, `sensor`, etc.), the `signal: AbortSignal`-equivalent (cancellation token or callback) is always the first parameter to user callbacks. Values follow as tuple (for deps) or positional args (for fixed-arity callbacks).
- **The core graph is 100% synchronous** (architecture.md §1.13). No asyncio, no trio, no event loop in core/, raw/, extra/, utils/, data/. `state.set()` triggers DIRTY→DATA synchronously on the call stack. Async exists only in orchestrate/ and adapters/ via the pluggable Runner protocol.
- **No raw coroutines in library internals** (architecture.md §1.16). Use library primitives (`from_timer`, `producer`) and `first_value_from` (the ONE bridge in `raw/`) instead of hand-rolling coroutines. `src/recharge/raw/` is the foundation layer — pure protocol with zero core dependencies. Dependency hierarchy: `raw/` → `core/` → `extra/` → `utils/` → higher layers. `raw/` is importable from any folder.
- **Push/pull via protocol, never poll** (architecture.md §1.17). Wait for conditions via reactive stores + `subscribe`, not `time.sleep` loops or `asyncio.sleep` polling.
- **Source-native output — no internal coroutine APIs** (architecture.md §1.20). Every internal API returns sources, not coroutines/awaitables. Wrap system boundary calls with `raw/from_awaitable` or `raw/from_async_iter`. Wrap user callbacks with `raw/from_any` (accepts sync, coroutine, async generator, or source). `first_value_from` exists only for end-users exiting reactive-land — never used internally.
- **No `asyncio.ensure_future`/`threading.Timer` for reactive coordination** (architecture.md §1.18). Use `effect` or `derived` to chain reactive updates — never `asyncio.ensure_future`, `threading.Timer`, or `loop.call_soon()`. Async scheduling breaks glitch-free guarantees. Timer usage only at true system boundaries (e.g. `from_timer` for demo latency).
- **Prefer `subscribe` over `effect` for single-dep data sinks** (architecture.md §1.19). Use `subscribe` when: single store dep, no diamond risk, no cleanup return, just react to value changes. Use `effect` for multi-dep diamond resolution or when DIRTY/RESOLVED guarantee is needed. `subscribe` has no DIRTY/RESOLVED overhead.
- **Two-phase push:** `sink.signal(Signal.DIRTY)` → then either `sink.next(value)` (changed) or `sink.signal(Signal.RESOLVED)` (no change). DIRTY before DATA, always.
- **Typed Protocol, not integer tags.** Python uses `Sink.next()`, `Sink.signal()`, `Talkback.pull()` — same callbag push/pull semantics, idiomatic Python encoding.

## Coroutine → source replacement patterns

| Coroutine pattern | Source replacement |
|---|---|
| `await asyncio.sleep(n)` | `from_timer(n)` |
| `await some_coro()` | `subscribe(from_awaitable(some_coro()), cb)` |
| `asyncio.gather(a, b)` | Subscribe both `from_awaitable` sources, collect, emit when all done |
| `async for x in agen` | `from_async_iter(agen)` → `subscribe` |
| `await user_callback(args)` | `from_any(user_callback(args))` → `subscribe` |
| `time.sleep(n)` in a loop | `subscribe(from_timer(n), fn)` |
| `await aiohttp.get(url)` | `from_awaitable(session.get(url))` → subscribe |
| `async for chunk in resp.content` | `from_async_iter(resp.content)` |

## Import hierarchy

```
Tier -1 (raw protocol) raw/          ← zero deps, importable everywhere
Tier 0 (foundation)    core/
Tier 1 (operators)     extra/
Tier 2 (utilities)     utils/
Tier 3 (domains)       orchestrate/  messaging/  memory/
Tier 4 (surface)       patterns/     adapters/   compat/
Tier 5 (ai)            ai/
```

`data/` is cross-cutting — importable from any tier (core excluded).
Strict downward-only imports. See architecture.md §3 for full rules.

## Code style

- Ruff: 4-space indent, 100 char line width, double quotes
- `__slots__` on hot-path classes
- Type hints on all public APIs
- `Signal` enum for DIRTY/RESOLVED/RESET/PAUSE/RESUME/TEARDOWN
- Always use `Inspector.observe()` equivalent for test assertions

## Concurrency model

- **Reads (`get()`):** Lock-free, any thread, any time
- **Writes (`set()`):** Per-subgraph lock. Independent subgraphs run in parallel.
- **Parallel derived:** Opt-in via `parallel=True`. Thread pool for expensive computations.
- **Graph construction:** Not thread-safe. Build at startup.
- Works under both GIL and free-threaded (3.13t/3.14t) Python.

## Commit conventions

Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`. Scope optional (e.g., `feat(core): add state primitive`).
