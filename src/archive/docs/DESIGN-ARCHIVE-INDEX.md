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

---

## Reading Paths

### For Project Newcomers
1. python-port-strategy — Why Python, how the architecture adapts from TypeScript

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
