# Design Discussion Archive

This directory preserves the most important design discussions from the callbag-recharge-py project.

## Quick Start

1. Read **DESIGN-ARCHIVE-INDEX.md** — overview of all sessions and reading guides
2. Pick a specific session based on what interests you

## Archive Files

### Index and Reference
- **DESIGN-ARCHIVE-INDEX.md** — Master index, reading guides, key themes
- **README.md** — This file

### Design Sessions

1. **SESSION-python-port-strategy.md**
   - Python port strategy — language choice, architecture adaptation, concurrency model
   - When: March 25, 2026
   - Best for: Understanding why Python, how the architecture adapts from TypeScript

## Key Themes

### 1. Protocol Adaptation
Typed Protocol classes instead of integer tags. Same push/pull semantics, idiomatic Python encoding.

### 2. Sync Core, Async Edges
Core graph is 100% synchronous. Async only at system boundaries via pluggable Runner.

### 3. Concurrency as Differentiator
Three-level concurrency model that works under both GIL and free-threaded Python.

### 4. AI Orchestration as Go-to-Market
The ai/ and orchestrate/ layers are the selling point — cleaner than LangChain/LangGraph.

## Traceability

Each file references its session date and topic. For the TypeScript library's design history, see the [callbag-recharge archive](https://github.com/nicepkg/callbag-recharge/tree/main/src/archive/docs).
