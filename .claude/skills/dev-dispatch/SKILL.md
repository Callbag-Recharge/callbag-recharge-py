---
name: dev-dispatch
description: "Implement feature/fix with planning and self-test. Use when user says 'dispatch', 'dev-dispatch', or provides a task with implementation context. Supports --light flag for bug fixes and small changes. Run /qa afterward for code review and final checks."
disable-model-invocation: true
argument-hint: "[--light] [task description or context]"
---

You are executing the **dev-dispatch** workflow for callbag-recharge-py (Python).

The user's task/context is: $ARGUMENTS

### Mode detection

If `$ARGUMENTS` contains `--light`, this is **light mode**. Otherwise, this is **full mode**. Differences are noted inline per phase.

---

## Phase 1: Context & Planning

Load context and plan the implementation in a single pass. **Parallelize all reads.**

Read in parallel:
- `docs/architecture.md` — skim for orientation; deep-read only sections relevant to the task
- `docs/test-guidance.md` — only the checklist for the relevant operator tier
- Any files the user referenced in $ARGUMENTS
- Relevant source files in the area you'll modify
- Existing tests for the area
- `docs/roadmap.md` — only if this is a new feature

While planning, explicitly validate proposed changes against these invariants:
- The core graph is 100% synchronous — no asyncio, no trio, no event loop in core/, raw/, extra/, utils/, data/
- Control flows through the graph (STATE signals), not imperative bypasses
- No raw coroutines in library internals — use `from_awaitable`, `from_async_iter`, `from_any`
- Push/pull via protocol, never polling loops (`time.sleep`, `asyncio.sleep`)
- No `asyncio.ensure_future`/`threading.Timer` for reactive coordination
- Prefer `subscribe` over `effect` for single-dependency data sinks
- Source-native output — internal APIs return sources, not coroutines/awaitables
- Typed Protocol classes, not integer tags

Do NOT start implementing yet.

---

## Phase 2: Architecture Discussion

### Full mode — HALT

**HALT and report to the user before implementing.** Present:

1. **Architecture assumptions** — any assumptions about how this fits into the existing system
2. **New patterns** — any new patterns you're introducing that don't exist in the codebase yet
3. **Options considered** — alternative approaches with pros/cons
4. **Recommendation** — your preferred approach and why

Prioritize (in order):
1. **Correctness** — does it follow the reactive protocol semantics correctly?
2. **Completeness** — does it handle all edge cases?
3. **Consistency** — does it match existing library patterns?
4. **Simplicity** — is it the minimal solution?
5. **Thread safety** — does it work under both GIL and free-threaded Python?

Do NOT consider backward compatibility at this early stage (pre-1.0).

**Wait for user approval before proceeding.**

### Light mode — Skip unless escalation needed

Proceed directly to Phase 3 **unless** your Phase 1 research reveals any of these:
- Changes to core primitives (`src/recharge/core/`) or signal semantics (DIRTY/DATA/RESOLVED/END)
- Changes to the concurrency model (subgraph locks, parallel derived)
- New patterns not present anywhere in the codebase
- Multiple viable approaches with non-obvious trade-offs

If any of these apply, escalate: HALT and present findings as in full mode.

---

## Phase 3: Implementation & Self-Test

After user approves (full mode) or after Phase 1 (light mode, no escalation):
1. Implement the changes
   - Enforce design invariants from `docs/architecture.md` as non-negotiable constraints
   - If existing code violates invariants, refactor toward invariant-compliant flow as part of the change
   - Favor clean replacement over compatibility layers (pre-1.0, no legacy retention by default)
   - Use `__slots__` on hot-path classes
   - Type hints on all public APIs
2. Create tests following `docs/test-guidance.md`:
   - Put tests in the most specific existing test file, or create a new one in `tests/`
   - Follow the checklist for the operator tier (tier 1 or tier 2)
   - Use `observe()` for protocol-level assertions (values, signals, events)
   - Use pytest with clear arrange/act/assert structure
   - Test signal protocol assertions (DIRTY→DATA, DIRTY→RESOLVED, diamond resolution)
   - Test thread safety where applicable (see concurrency testing patterns)
3. Run checks: `uv run pytest && uv run ruff check src/ && uv run mypy src/`
4. Fix any failures

When done, briefly list files changed and new exports added. Then suggest running `/qa` for adversarial review and final checks.
