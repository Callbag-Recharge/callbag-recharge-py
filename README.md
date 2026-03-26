# recharge

Reactive state management for Python with push/pull duality, concurrent graph computation, and AI orchestration.

Ported from [callbag-recharge](https://github.com/nicepkg/callbag-recharge) (TypeScript).

## Features

- **Sync core** — no asyncio required for basic state management
- **Push/pull duality** — same protocol handles both reactive streams and iterable pipelines
- **Two-phase push** — DIRTY→DATA propagation with diamond resolution
- **Concurrent** — lock-free reads, per-subgraph write locks, parallel derived computation
- **Free-threaded ready** — works under both GIL and Python 3.13t/3.14t
- **AI orchestration** — pipeline, task, retry, gate — cleaner than LangChain/LangGraph

## Install

```bash
pip install recharge
```

## Quick Start

```python
from recharge import state, derived, effect

counter = state(0)
doubled = derived(lambda: counter.get() * 2)
effect(lambda: print(f"doubled = {doubled.get()}"))

counter.set(5)   # prints "doubled = 10" — synchronously, no event loop
counter.set(10)  # prints "doubled = 20"
```

## Status

Early development. See [docs/roadmap.md](docs/roadmap.md) for the implementation plan.

## License

MIT
