---
SESSION: agentic-memory-research
DATE: March 26, 2026
TOPIC: SOTA Agentic Memory Research — Python Port Relevance
---

## KEY DISCUSSION

### Context

This session distills the agentic memory research from the TypeScript callbag-recharge project
(original session: March 17, 2026; updated March 23 and March 26, 2026) into the findings
relevant to the Python port's memory/ and ai/ layers (Phase 4).

---

## PART 1: SOTA AGENTIC MEMORY LANDSCAPE

### Leading Architectures

| System | Key Innovation | Memory Model |
|--------|---------------|--------------|
| **Letta (MemGPT)** | Self-editing memory via tool calls | Core (in-context) + Recall (conversational) + Archival (long-term) |
| **Mem0 / Mem0g** | Hybrid vector + incremental graph | Two-phase extraction pipeline; 91% p95 latency reduction vs full-history |
| **Zep/Graphiti** | Temporal knowledge graphs | Neo4j-backed; tracks fact evolution over time |
| **OpenViking** | Filesystem-shaped context DB | L0/L1/L2 progressive loading; typed categories; hierarchical retrieval |
| **MAGMA** | Four parallel graphs per memory item | Semantic + temporal + causal + entity; intent-adaptive retrieval |
| **A-Mem** | Zettelkasten-style atomic notes | Agent-driven linking; memory evolution triggers historical updates |

### Critical Gap: No Reactive Memory

**No existing agent memory system uses reactive/push-based state management.** All are pull-based (query → retrieve → return). Push-based dirty tracking + incremental computation via callbag-recharge is a genuinely novel contribution. This applies equally to the Python port.

### Memory Types (CoALA Taxonomy)

- **Working Memory:** Active scratchpad (context window). Conversation buffer + system prompt.
- **Episodic Memory:** Records of specific experiences. Scoring: recency × importance × relevance.
- **Semantic Memory:** Factual knowledge, entity relationships. Knowledge graphs or vector stores.
- **Procedural Memory:** Learned workflows, tool usage patterns. AGENTS.md files, skill learning.

---

## PART 2: OPENVIKING DEEP DIVE (Primary Competitor for Python Port)

### What OpenViking Is

Open-source **Context Database** for AI Agents by Volcengine (ByteDance). 19.3K+ stars, Apache 2.0,
Python + C++ core extensions + Rust CLI. Published January 2026.

**Core modules:** VikingFS (virtual filesystem), AGFS (content storage: local/S3/memory),
Vector Index (local/HTTP/VikingDB), Parser (PDF/MD/HTML/code via tree-sitter),
SemanticQueue (async L0/L1 generation), Retrieve (intent + hierarchical search + rerank),
Session (conversation management + compression), Compressor (extraction + LLM dedup).

### L0/L1/L2 Progressive Loading

OpenViking's most distinctive design for token budget management:

| Layer | File | ~Tokens | Purpose |
|---|---|---|---|
| **L0** (Abstract) | `.abstract.md` | ~100 | Vector search, quick filtering |
| **L1** (Overview) | `.overview.md` | ~2k | Rerank, usually sufficient for LLM context |
| **L2** (Detail) | Original files | Unlimited | Full content, on-demand |

L0/L1 generated bottom-up by LLM. Maps to `derived()` chains in callbag-recharge.

### Hotness/Decay Formula

```
score = sigmoid(log1p(active_count)) * exp_decay(age, half_life=7d)
```

- **Frequency:** Diminishing returns via `sigmoid(log1p(count))`
- **Recency:** Exponential decay with 7-day default half-life
- Simpler than Generative Agents' `α×recency + β×importance + γ×relevance` — purely data-driven

### Retrieval Algorithm

1. **Intent Analysis:** LLM → 0-5 `TypedQuery` objects (query, context type, intent, priority)
2. **Hierarchical Retrieval:** Priority queue over directory tree:
   - `final_score = 0.5 * embedding_score + 0.5 * parent_score`
   - Convergence detection: stops when top-K unchanged for 3 rounds

### Memory Update: MemoryReAct

Single LLM call with tool use in ReAct loop (max 5 iterations). Dedup flow:
embed candidate → vector pre-filter → LLM decides: `skip | create | merge | delete`.

### Typed Memory Categories

6 categories defined as YAML templates:
- **User:** profile, preferences, entities, events
- **Agent:** cases (problem-solution pairs), patterns (reusable patterns)

---

## PART 3: PERFORMANCE — callbag-recharge-py vs OpenViking

| Operation | OpenViking | callbag-recharge-py | Notes |
|---|---|---|---|
| Memory read (cached) | ~50-500μs (subprocess/HTTP) | ~100-500ns (`state.get()`) | In-process vs IPC |
| Reactive propagation | N/A (pull-only) | ~0.5-5μs | Reactive eliminates redundant pulls |
| Vector search (k=10, 10K) | ~1-10μs (C++ core) | ~5-50μs (pure Python HNSW) | numpy/C extension can close gap |
| Session commit (sync) | ~1ms (archive to AGFS) | ~1-10μs (batch write) | Async extraction dominates wall time |
| Memory extraction (LLM) | ~1-5s (LLM call) | ~1-5s (LLM call) | LLM is the bottleneck |
| Context assembly | O(n) per turn | O(1) cached (`derived()`) | **Key differentiator** |

### Why We Still Win

1. **O(1) context assembly** — `derived()` caching means unchanged deps don't recompute. OpenViking re-retrieves every turn.
2. **In-process, zero-serialization** — OpenViking's "embedded" mode still spawns AGFS subprocess. We're truly in-process.
3. **Diamond-safe coordination** — two-phase DIRTY→DATA guarantees consistency for concurrent memory operations.
4. **Free-threaded Python 3.14** — unlocks true parallel DATA phase. OpenViking's Python is GIL-bound (parallelism only via C++ extensions).

### Where We Need Investment

- **Vector search:** Pure Python HNSW needs numpy/BLAS for distance computation hot path
- **Parser:** Tree-sitter AST parsing for code-aware memory (tree-sitter-python binding)

---

## PART 4: PATTERNS TO ADOPT IN PYTHON PORT

### Phase 4.1 (memory/) Enhancements

1. **Progressive context loading (L0/L1/L2)** — three-tier summaries per memory node, generated via `from_llm`. `derived()` chains for bottom-up aggregation. Token-budget-aware retrieval.

2. **Improved decay formula** — `sigmoid(log1p(access_count)) * exp_decay(age, half_life)` with configurable half-life. Adopt when building `decay` module.

3. **Typed memory categories** — optional `category` field on nodes (profile/preferences/entities/events/cases/patterns). Policy-driven routing for retrieval weighting and dedup.

4. **Admission control** — vector pre-filter + LLM dedup (skip/create/merge/delete). Build as composable policy, not hardwired into `collection`.

### Phase 4.2 (ai/) Enhancements

5. **Retrieval observability** — `search()` returns trace: query plan, candidate scores, decay/similarity breakdown. "Why this memory surfaced" in domain language.

6. **Two-phase session commit** — sync archive + async extraction via job queue with reactive status stores.

7. **Explicit memory operations** — stable tool-friendly API: `search/read/browse/commit` for agent surfaces and MCP.

### Implementation Rules (Do/Don't)

**Do:**
- Keep primitives pure (`collection`, `node`, `decay`, `vector_index`) with policy hooks
- Build product behavior in `ai/agent_memory`, not low-level data primitives
- Use `from_llm` through job queues for extraction/embedding

**Don't:**
- Hard-wire LLM extraction into memory primitives
- Add external service dependency as default path
- Couple retrieval explanation to one transport

---

## KEY INSIGHTS

1. **OpenViking is the primary competitor** for the Python port's ai/memory story. Same language, same ecosystem, strong traction (19K+ stars).

2. **Architecture is our moat.** OpenViking is pull-based with subprocess IPC. We're push-based, in-process, diamond-safe. The LLM call (~1-5s) dwarfs runtime overhead — but reactive caching of context assembly is a genuine O(n)→O(1) improvement.

3. **L0/L1/L2 progressive loading** is the most valuable pattern to adopt. It's a natural `derived()` chain and directly addresses the #1 pain point (context assembly cost).

4. **The decay formula is validated and simple.** `sigmoid(log1p(count)) * exp_decay(age, 7d)` — adopt it directly.

5. **Free-threaded Python 3.14** is a strategic advantage OpenViking cannot easily match without rewriting their Python layer.

## FILES CHANGED

- This file created: `src/archive/docs/SESSION-agentic-memory-research.md`

---END SESSION---
