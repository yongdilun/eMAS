Here is the **final migration plan** for moving from your original architecture to **Option A: Custom core + LangChain helpers**.

## Final Migration Plan

### 1. Goal

Adopt LangChain only for **planner and summary generation** while keeping the **runtime, safety, and execution model fully custom**.

### 2. Core rule

The following components remain the source of truth and are **not** migrated into LangChain:

* session manager
* state machine
* execution engine
* approval flow
* retry logic
* idempotency handling
* DLQ handling
* recovery logic
* tool registry and OpenAPI pipeline 

LangChain is used only for:

* planner prompt composition
* model invocation
* structured plan output
* planner-visible tool wrappers
* risk summary, plan explanation, and optional final summary

---

## 3. Migration steps

### Phase 1 — Freeze runtime boundary

Keep the execution path unchanged.

* Add feature flags:

  * `PLANNER_BACKEND=legacy|langchain`
  * `SUMMARY_BACKEND=legacy|langchain`
* Keep `execute_until_blocked` and current execution flow as the only execution authority.
* Capture baseline metrics before migration:

  * plan validity rate
  * validator pass rate
  * approval behavior
  * retry behavior
  * DLQ rate
  * planner latency
  * overall session success rate

### Phase 2 — Add planner adapter

Introduce one internal interface:

```python
generate_plan(intent, scoped_tools, context) -> PlanDraft
```

Rules:

* route all planner calls through this adapter
* implement legacy planner first
* add LangChain implementation second
* no behavior change yet

This creates a clean swap point without changing runtime behavior.

### Phase 3 — Move planner prompting to LangChain

Replace only prompt construction and model invocation.

* move planner prompt into LangChain prompt templates
* preserve the same planner role
* preserve the same tool scope filter
* preserve the same JSON contract
* preserve the same context assembly

LangChain must generate the same kind of plan your current system expects.

### Phase 4 — Add structured output

Bind LangChain output to your `PlanDraft` / `PlanSchema`.

Rules:

* LangChain structured output is for generation only
* your existing validator remains the final gate
* invalid plans are rejected exactly the same way as today
* no validator bypass is allowed

This ensures LangChain improves generation but does not weaken safety.

### Phase 5 — Add planner-only tool wrappers

Build LangChain tool wrappers from tool registry / OpenAPI metadata.

Rules:

* wrappers are visible to the planner only
* LangChain is not allowed to execute tools
* no autonomous agent execution
* all execution still goes through your custom engine

This keeps planning convenience while preserving execution control.

### Phase 6 — Add summary entrypoints

Use LangChain for:

* `plan_explanation`
* `risk_summary`
* optional final run summary

Do not migrate:

* approvals
* retries
* idempotency
* DLQ
* recovery
* step execution behavior 

### Phase 7 — Canary rollout

Roll out LangChain gradually.

Suggested rollout:

* 5%
* 25%
* 50%
* 100%

Rules:

* compare metrics at each stage
* immediate rollback through feature flag if safety or quality regresses
* log which backend generated each plan:

  * `backend_used=legacy`
  * `backend_used=langchain`

### Phase 8 — Fallback behavior

If LangChain planner fails or produces invalid output after normal retries:

* reject the invalid LangChain plan
* optionally fall back to legacy planner during rollout
* never bypass validator
* never allow direct execution from LangChain output without standard validation

---

## 4. Hard invariants

These must remain true after migration:

1. **LangChain never executes tools directly**
2. **Custom validator remains final gate**
3. **Approval gating for writes is unchanged**
4. **Retry and timeout behavior is unchanged**
5. **AMBIGUOUS handling is unchanged**
6. **DLQ behavior is unchanged**
7. **Recovery behavior is unchanged**
8. **Execution engine remains source of truth** 

---

## 5. Exit requirements

### R1 — Plan schema compliance stays strict

Test:

* existing schema tests
* `test_langchain_planner_invalid_output_rejected`

### R2 — Approval gating unchanged for writes

Test:

* existing approval gate execution test

### R3 — Non-strongly-idempotent timeout still becomes AMBIGUOUS + DLQ

Test:

* existing ambiguous timeout test

### R4 — Strongly-idempotent retries unchanged

Test:

* existing strong idempotent retry test

### R5 — DB failure recovery unchanged

Test:

* existing DB failure recovery test

### R6 — Backpressure and chaos gates remain green

Test:

* existing phase 4 exit scripts for load, queue, DB failure, JWT, and validation gates

### R7 — Planner quality parity

Compare legacy vs LangChain on a fixed intent corpus for:

* acceptance rate
* validator pass rate
* unknown tool rate
* schema failure rate
* clarification rate
* average steps per plan

### R8 — Performance guardrail

Pass criteria:

* planner p95 latency regression stays within agreed threshold
* no increase in 5xx rate
* no increase in DLQ rate
* no drop in session completion quality

### R9 — Reject flow unchanged

Test:

* approval rejection still returns session to the currently expected state in your implementation

---

## 6. Final implementation order

1. Add feature flags
2. Capture baseline metrics
3. Add planner adapter
4. Route legacy planner through adapter
5. Implement LangChain prompt template
6. Implement LangChain structured output
7. Connect existing validator as hard gate
8. Add planner-only tool wrappers
9. Add LangChain summary generation
10. Run fixed-corpus parity tests
11. Start canary rollout
12. Roll back immediately if safety metrics regress

---

## 7. Final recommendation

This migration is a **thin planner-layer integration**, not a rewrite.

**Keep custom:**
runtime, safety, approvals, execution, retries, DLQ, recovery

**Use LangChain for:**
planner generation, structured output, and summaries

That is the safest, fastest, and cleanest way to move from your original hardened architecture to **Option A** while preserving all core guarantees from the original plan. 
