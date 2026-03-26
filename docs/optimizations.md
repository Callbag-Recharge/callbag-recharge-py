# Optimizations — Findings from TypeScript Port

This document captures design decisions and bug fixes from the TypeScript port (callbag-recharge) that affect the Python port. Review each item and determine if changes are needed.

---

## 1. RESET is purely lifecycle — no auto re-emission or re-run

**Status in TS:** Implemented. **Status in Python:** ✅ Fixed.

### Design decision

RESET means "clear transient state, prepare for re-trigger" — neither push (source emit) nor pull (effect run) auto-fires. The user decides when to restart by explicitly pushing new data into the graph.

**Rationale:**
- **Symmetry:** Neither side auto-fires, making push and pull symmetric on RESET
- **User control:** A reset button shouldn't cause side effects the user didn't ask for — they might want to reset, configure, then trigger
- **No `_force` hack:** Sources don't emit on RESET, so no need to bypass equality guards
- **No multi-dep fan-out:** A 2-dep effect doesn't run twice per RESET (once per dep re-emission)
- **Simpler orchestration:** Pipeline doesn't need to reorder meta clears around RESET signals

### What changed in TypeScript

**Producer/State RESET handler — no emission:**
```python
# Before (Python current):
if sig is Signal.RESET:
    self._value = self._initial
    self._pending = False
if self._on_lifecycle_handler is not None:
    self._on_lifecycle_handler(sig)
if sig is Signal.RESET:
    self.emit(self._initial, _force=True)  # ← REMOVE THIS

# After (purely lifecycle):
if sig is Signal.RESET:
    self._value = self._initial
    self._pending = False
if self._on_lifecycle_handler is not None:
    self._on_lifecycle_handler(sig)
# No emit — RESET is purely lifecycle
```

**Effect RESET handler — cleanup yes, run() no:**
```python
# Before (Python current — no cleanup, no run):
if sig is Signal.RESET:
    self.generation += 1
    self.dirty_deps.reset()
    self.any_data = False
    for i in range(len(self.sink_gens)):
        self.sink_gens[i] = self.generation

# After (add cleanup):
if sig is Signal.RESET:
    self.generation += 1
    self.dirty_deps.reset()
    self.any_data = False
    for i in range(len(self.sink_gens)):
        self.sink_gens[i] = self.generation
    # Tear down side effects from the last run
    if self.cleanup is not None:
        self.cleanup()
        self.cleanup = None
```

### Action items for Python port

1. **Remove `self.emit(self._initial, _force=True)` from `producer.py` `_handle_lifecycle_signal`** — RESET should not trigger re-emission
2. **Remove `_force` parameter from `emit()`** — no longer needed (can keep if other callers use it, but RESET shouldn't)
3. **Add cleanup call in `effect.py` `handle_lifecycle_signal` for RESET** — "clear transient state" includes tearing down the effect's side effects
4. **Do NOT add `run()` to effect RESET** — the user triggers re-run by pushing new data

### Verification

All examples in the TS repo already follow the correct pattern:
- `pipeline.reset()` followed by explicit `trigger.fire("go")`
- `field.reset()` as a standalone clear operation
- No code depends on RESET causing automatic re-emission or effect re-run

---

## 2. Effect `sink_gens` shared array — already implemented correctly

**Status in Python:** ✅ Already correct. The `_EffectState.sink_gens` list with generation updates in `handle_lifecycle_signal` matches the TS fix.

This was the original bug: per-dep closure-local `sinkGen` variables caused permanent deafness after RESET. The shared `sink_gens` array with bulk update on RESET ensures all dep closures accept post-RESET signals.

No changes needed — Python already has this right.

---

## 3. Batch drain resilience

**Status in Python:** ✅ Fixed — per-emission try/catch added to `batch()` drain loop in `protocol.py`.

The TS port wraps each individual deferred emission in try/catch so one throwing callback doesn't orphan remaining emissions. The first error is captured and re-thrown after all emissions drain. The outer try/finally ensures `draining` is reset and the queue is cleared regardless.

```python
# Pattern — per-emission try/catch:
first_error = None
try:
    for emission in deferred_emissions:
        try:
            emission()
        except Exception as e:
            if first_error is None:
                first_error = e
finally:
    deferred_emissions.clear()
    draining = False
if first_error is not None:
    raise first_error
```

### Action item
- Review Python `batch()` drain loop — if it only has outer try/finally but not per-emission try/catch, add it.

---

## 4. Deferred emission P_PENDING guard

**Status in Python:** ✅ Fixed — `_flush_pending` now checks `_pending` before dispatching.

When RESET fires during a batch, it clears `P_PENDING` on the producer/state. But a deferred emission closure (queued before RESET) may still be in the drain queue. Without a guard, that stale closure fires and emits the reset initial value — violating "RESET doesn't emit."

The TS fix: deferred emission callbacks check `P_PENDING` at the start and bail if cleared.

```python
# In the deferred emission callback:
def deferred():
    if not self._pending:  # Cleared by RESET
        return
    self._pending = False
    self._dispatch(DATA, self._value)
```

### Action item
- Add `_pending` guard to deferred emission callbacks in producer and state.

---

## 5. Derived get() cache invalidation on RESET

**Status in Python:** ✅ Fixed — `get()` checks `_has_cached` when connected; pull-computes on demand if cache invalidated.

When derived is connected (has subscribers) and receives RESET, the cache is cleared (`D_HAS_CACHED` unset). But `get()` previously assumed that being connected meant the cache was always valid. After RESET, `get()` returned the stale pre-RESET cached value.

The TS fix: `get()` checks both "connected" AND "has cached value." If connected but cache invalidated, it pull-computes on demand.

```python
# Derived.get():
if self._connected:
    if not self._has_cached:
        result = self._fn()
        self._cached_value = result
        self._has_cached = True
        return result
    return self._cached_value
# ... disconnected path unchanged
```

### Action item
- Check Python derived `get()` — if it assumes connected = cached, add the `_has_cached` check.

---

## Summary

| Item | Python status | Action needed |
|------|--------------|---------------|
| Producer RESET: remove `emit(_force=True)` | ✅ Fixed | Removed force-emit and `_force` param |
| Effect RESET: add cleanup | ✅ Fixed | `_run_cleanup()` in RESET handler |
| Effect RESET: no `run()` | ✅ Correct | Already does not call `run()` |
| Effect `sink_gens` shared array | ✅ Correct | Already implemented |
| Batch drain per-emission try/catch | ✅ Fixed | Per-emission try/catch in `protocol.py` |
| Deferred emission P_PENDING guard | ✅ Fixed | `_flush_pending` checks `_pending` |
| Derived get() cache after RESET | ✅ Fixed | `get()` checks `_has_cached` when connected |
