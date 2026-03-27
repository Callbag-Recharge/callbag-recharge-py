# Design Decision Archive

This directory preserves detailed design discussions from key Claude Code sessions. These are not casual notes — they capture the reasoning chains, rejected alternatives, and key insights that shaped the architecture.

## Sessions

### Session python-port-strategy (March 25, 2026) — Python Port Strategy
**Topic:** Strategic analysis — should callbag-recharge exist in other languages? Which one? How to adapt?

Research covered: Rust reactive ecosystem (callbag-rs, Leptos, Dioxus, futures-signals), language fit analysis (Elixir, Lua, Python, Kotlin, Swift, Dart), Python 3.14 free-threaded mode, concurrency model design.

**Key decisions:**
- Target Python (biggest market gap + AI ecosystem)
- Separate repo (different tooling/users)
- Don't port callbag wire protocol — use typed Protocol classes (same push/pull semantics)
- Core graph is 100% synchronous — no asyncio dependency
- Three-level concurrency: lock-free reads → per-subgraph write locks → parallel DATA phase
- Pluggable async Runner for orchestrate/adapters only

**Rejected:** Literal callbag protocol port, Rust as target, monorepo, asyncio dependency, single global lock.

**Downstream impact:** Architecture doc, roadmap, folder structure, all future implementation decisions.

### Session agentic-memory-research (March 26, 2026) — Agentic Memory Research
**Topic:** SOTA agentic memory landscape, OpenViking competitive analysis, patterns to adopt in Python port's memory/ and ai/ layers.

Research covered: 8 leading memory architectures (Letta, Mem0, Zep, OpenViking, MAGMA, A-Mem, Cognee, MemOS), CoALA taxonomy, OpenViking deep dive (L0/L1/L2 progressive loading, decay formula, hierarchical retrieval, typed categories), performance comparison (callbag-recharge-py vs OpenViking).

**Key decisions:**
- OpenViking is the primary Python-ecosystem competitor (19K+ stars, ByteDance)
- Adopt L0/L1/L2 progressive context loading as `derived()` chains
- Adopt validated decay formula: `sigmoid(log1p(count)) * exp_decay(age, 7d)`
- Add typed memory categories (profile/preferences/entities/events/cases/patterns)
- Add retrieval observability ("why this memory surfaced")
- Pure Python HNSW needs numpy/BLAS acceleration to match OpenViking's C++ core
- Free-threaded Python 3.14 is a strategic advantage over OpenViking

**Rejected:** Hard-wiring LLM extraction into primitives, external service dependency as default, filesystem-shaped virtual FS (keep reactive graph paradigm instead).

**Downstream impact:** Phase 4.1 (memory/) and 4.2 (ai/) scope expanded with OpenViking-validated patterns.

---

## Reading Paths

### For Project Newcomers
1. python-port-strategy — Why Python, how the architecture adapts from TypeScript
2. agentic-memory-research — Competitive landscape, what to build in memory/ai layers

### For Understanding the TypeScript Origin
See the [callbag-recharge archive](https://github.com/nicepkg/callbag-recharge/tree/main/src/archive/docs) for the full design history of the TypeScript library.

---

## Archive Format

Each session file contains:

```
---
SESSION: [id]
DATE: [date]
TOPIC: [topic]
---

## KEY DISCUSSION
[Reasoning chains, code examples, comparisons]

## REJECTED ALTERNATIVES
[What was considered, why not]

## KEY INSIGHTS
[Main takeaways]

## FILES CREATED / CHANGED
[Implementation side effects]

---END SESSION---
```
