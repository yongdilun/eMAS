# RAG V14 Optimization Plan: Budgeted Evidence-Aware RSE

## Purpose

Optimize the approved V12 RAG candidate without weakening safety, citation, or compliance boundaries.

The next experiment should test whether RSE can keep the safety/recall benefit that made V12 the limited-rollout candidate while reducing context size, latency, and citation noise.

Target experiment:

```text
V14 = Query Rewrite + Hybrid Search + Rerank + Budgeted Evidence-Aware RSE
```

## Current Baseline

Final approved limited-rollout baseline:

| Variant | Technique | Cases | Pass | Serious failures | Score | Avg time | Avg context tokens | Rerank fallback |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| V12 final | Query Rewrite + Hybrid Search + RSE + Rerank | 50 | 50/50 | 0 | 85.5598 | 10.7929s | 4656.64 | 0 |
| V7 Phase 11 | Query Rewrite + Hybrid Search + Small-to-Big + Rerank | 50 | 50/50 | 2 | 87.7648 | 8.6768s | 2267.10 | 0 |

Interpretation:

- V12 is safer and is the current rollout baseline because it reached 0 serious failures.
- V7 is faster, cheaper, and higher scoring, but still had serious failures.
- Current RSE likely gets safety value by recall-heavy expansion, not by strong evidence-budget optimization.

## Target Goals

V14 is not successful merely because it is different from V12. It must preserve V12 safety while proving measurable efficiency and citation-quality gains.

Primary goal:

```text
Keep V12's 0 serious failures while cutting context tokens and latency toward V7 levels.
```

| Target | V12 baseline | Minimum V14 gate | Preferred V14 goal | Stretch goal |
| --- | ---: | ---: | ---: | ---: |
| Serious failures | 0 | 0 | 0 | 0 |
| Automated pass | 50/50 | 50/50 | 50/50 | 50/50 |
| Final score | 85.5598 | >= 85.0 with no serious regression | >= 85.5598 | >= 87.0 |
| Avg context tokens | 4656.64 | <= 3500, about 25% reduction | <= 3000, about 35% reduction | <= 2800, about 40% reduction |
| Avg time | 10.7929s | <= 9.25s, about 14% faster | <= 8.75s, about 19% faster | <= 8.25s, about 24% faster |
| Reranker fallback | 0 | 0 | 0 | 0 |
| doc_hit@3 | 0.98 | >= 0.98 | >= 0.98 | 1.00 |
| doc_hit@5 | 1.00 | 1.00 | 1.00 | 1.00 |
| section/page_hit@3 | 0.86 | >= 0.86 | >= 0.88 | >= 0.90 |
| section/page_hit@5 | 0.94 | >= 0.94 | >= 0.94 | >= 0.96 |
| Citation precision | broad RSE evidence can be noisy | no regression | exact child evidence preferred | exact child evidence for all clear support cases |

Efficiency target rationale:

- A 25% token reduction means average context drops from about 4657 tokens to at most about 3500 tokens.
- A 35% token reduction means average context drops to about 3000 tokens, close enough to V7's efficiency to justify the RSE optimization.
- A 14% latency reduction means average runtime drops below 9.25s without needing to remove the reranker.
- A 19% latency reduction means average runtime lands near 8.75s, roughly V7-class speed while keeping V12-class safety.

If V14 reaches the efficiency goals but loses the 0-serious-failure safety property, it remains experimental and V12 stays the rollout default.

## Hypothesis

Current RSE expands too broadly:

```text
seed chunk -> nearby same-document/same-section chunks -> cap tokens -> cheap segment score
```

Optimized RSE should behave more like:

```text
seed chunk -> slide left/right only while neighbors add relevant evidence -> preserve exact child evidence -> stop when support is sufficient or budget is reached
```

This should reduce token load and latency while keeping or improving serious-failure behavior.

## Non-Goals

- Do not change `tests/rag_eval/cases.json`.
- Do not weaken scoring, expected answers, or serious-failure rules.
- Do not grant autonomous safety/compliance authority.
- Do not enable compression or Document Augmentation by default.
- Do not hardcode OSHA, LOTO, NIST, or benchmark-specific fixes into the context builder.
- Do not add new hardcoded query, document, chunk, page, section, or case IDs to make specific benchmark cases pass.
- Do not add one-off string rules for individual documents. If a rule is needed, express it as generic metadata-driven logic.
- Do not replace V12 rollout defaults until V14 beats the gates below.

## Maintainability Rules

1. Keep V14 behind explicit config. V12 must remain available unchanged.
2. Implement generic context-building logic, not case-specific patches.
3. Prefer small pure functions for scoring, expansion, budget checks, and span selection.
4. Keep retrieval, reranking, context building, generation, and response projection separated.
5. Preserve metadata lineage from parent RSE segment to exact child chunk/page/span.
6. Make scoring parameters configurable with safe defaults, not hidden constants scattered through code.
7. Add tests before implementation for each behavior change.
8. Log enough metadata to audit why a chunk was included or excluded.
9. Keep final answer generation on the original user query. Query rewrite remains retrieval-only.
10. Keep Qwen2.5-7B judge as triage only, not a production approval gate.
11. Do not introduce benchmark-specific hardcode. New logic must generalize across document families.
12. Prefer corpus metadata, section structure, chunk adjacency, query facets, and measured relevance over literal document names.
13. Put tunable thresholds in config or a single context-builder settings object.
14. Every new heuristic needs a test that proves the general rule, not only one OSHA/NIST example.
15. When a bug is found, fix the underlying general failure mode. Do not patch only the observed query, case ID, document, page, or chunk.
16. Every bug fix needs at least one regression test for the reported case shape and one adjacent/generalized case that would fail under the same class of bug.

## Evaluation Before Proceeding

Before changing code, capture the current baseline and confirm the harness:

```powershell
git status --short
git log -5 --oneline
python -m tests.rag_eval.run_eval --help
python -m pytest -q factory-agent/tests/test_rag_context_building.py factory-agent/tests/test_rag_pipeline_config.py
```

Confirm:

- Existing user/unrelated changes are not reverted.
- `tests/rag_eval/cases.json` is unchanged.
- V12 config still means Query Rewrite + Hybrid Search + RSE + Rerank.
- Reranker fallback remains disabled for V12.
- Baseline artifact values are recorded before comparing V14.

Recommended fresh baseline commands before full V14 comparison:

```powershell
python -m tests.rag_eval.run_eval --variant V12 --run-id v12-pre-v14-baseline --no-judge
python -m tests.rag_eval.run_eval --variant V7 --run-id v7-pre-v14-reference --no-judge
```

Use the existing Phase 14 judged V12 run as the readiness baseline, but use fresh no-judge V12/V7 runs to detect local runtime drift before implementing V14.

## Proposed V14 Design

### 1. Seed Selection

Start from the reranked selected chunks, as V12 does today. Each seed starts an RSE candidate segment.

Keep:

- same document restriction
- section path awareness
- authority and risk metadata
- source chunk evidence metadata

Change:

- do not automatically include every chunk in a fixed plus/minus window.
- expand only when a neighbor passes relevance, continuity, novelty, and budget checks.

### 2. Adaptive Sliding Expansion

For each seed, evaluate the immediate left and right neighbor separately.

Include the neighbor with the highest marginal gain, then repeat:

```text
segment = [seed]

while budget remains:
    left_gain = score_neighbor(left, segment, query)
    right_gain = score_neighbor(right, segment, query)
    best = max(left_gain, right_gain)

    if best < threshold:
        stop

    add best neighbor
```

Stop when:

- relevance is below threshold
- section/topic continuity breaks
- neighbor adds no missing query facet
- segment token budget is reached
- global context token budget is reached
- max expansion radius is reached

### 3. Neighbor Scoring

Score the neighbor as a separate chunk first. Do not only score the whole expanded blob.

Suggested scoring signals:

| Signal | Purpose |
| --- | --- |
| Query relevance | Does this chunk help answer the question? |
| Missing-facet gain | Does it cover query terms/facets not already covered? |
| Continuity | Is it same section, sibling section, adjacent page, or clear continuation? |
| Heading match | Does the heading/section path match the user intent? |
| Authority/risk | Prefer official and high-risk safety evidence when relevant. |
| Redundancy penalty | Avoid repeated broad background text. |
| Token cost penalty | Prefer compact evidence when support is equivalent. |

### 4. Span Extraction

Use whole chunks to decide whether a neighbor belongs, but extract support spans for generation and citation.

Rules:

- If a chunk has an exact paragraph/list item that supports the claim, preserve that span.
- If the query asks for an explicit procedure/list, preserve the item boundaries.
- If span extraction is low confidence, keep the chunk as context but mark citation evidence as page/chunk-level, not exact highlight.
- Never claim exact PDF highlight unless `text_search`, `char_range`, or `bbox` is truly exact.

### 5. Global Budget

Add a total context budget in addition to per-segment budget.

Initial target:

| Budget | Starting target |
| --- | ---: |
| Per RSE segment | 1200 to 1600 tokens |
| Total context | 2500 to 3500 tokens |
| Max adaptive radius | 2 chunks each side |

The target is to move V14 closer to V7 token/time cost while preserving V12 safety.

### 6. Citation and Evidence Lineage

Every RSE segment must keep:

- parent segment ID
- seed chunk ID
- included child chunk IDs
- included/excluded neighbor decisions
- source page(s)
- exact support span when available
- reason for inclusion
- token contribution

Response document projection should prefer exact child evidence for citations, not broad parent RSE metadata.

## TDD Slices

### Slice 1: Adaptive Expansion Unit Tests

Add tests in `factory-agent/tests/test_rag_context_building.py`.

Prove:

- a highly relevant left/right neighbor is included.
- an adjacent but off-topic neighbor is excluded.
- expansion stops when relevance drops.
- same-document restriction remains.
- same-section/sibling-section continuity is respected.

### Slice 2: Budget Tests

Prove:

- per-segment budget is enforced.
- global context budget is enforced.
- lower-value chunks are dropped before higher-value evidence.
- metadata records included and excluded neighbor decisions.

### Slice 3: Procedure/List Evidence Tests

Prove:

- explicit source procedures preserve item boundaries.
- long procedure item plus following item do not merge.
- exact child chunk/page remains available for response projection.
- broad RSE parent page does not override exact child page.

### Slice 4: V14 Config Tests

Add V14 to config only after unit behavior is proven.

Prove:

- V12 config is unchanged.
- V14 uses query rewrite, hybrid retrieval, rerank, and optimized RSE.
- compression remains off.
- Document Augmentation remains off.
- reranker fallback remains disabled.

### Slice 5: Focused Eval Smoke

Run focused evals before full benchmark:

```powershell
python -m tests.rag_eval.run_eval --variant V14 --filter loto --run-id v14-smoke-loto --no-judge
python -m tests.rag_eval.run_eval --variant V14 --filter guarding --run-id v14-smoke-guarding --no-judge
python -m tests.rag_eval.run_eval --variant V14 --filter nist-ams300-1 --run-id v14-smoke-ams1 --no-judge
python -m tests.rag_eval.run_eval --variant V14 --filter nist-csf-2 --run-id v14-smoke-csf2 --no-judge
```

If focused smoke regresses serious failures, fix the generic context logic before running the full set.

### Slice 6: Full Eval

Run:

```powershell
python -m tests.rag_eval.run_eval --variant V14 --run-id v14-full --judge
```

Compare against:

- Phase 14 V12 final
- fresh V12 pre-V14 baseline
- fresh V7 reference

## Acceptance Gates

V14 is only a candidate if all gates pass:

| Gate | Required result |
| --- | --- |
| Automated pass | 50/50 |
| Serious failures | 0 |
| Warnings | 0 or explicitly explained |
| Reranker fallback | 0 |
| Final score | >= 85.0 minimum and >= 85.5598 preferred, with no material safety/citation regression |
| Avg context tokens | <= 3500 minimum, <= 3000 preferred, <= 2800 stretch |
| Avg token reduction | >= 25% minimum, >= 35% preferred, >= 40% stretch |
| Avg time | <= 9.25s minimum, <= 8.75s preferred, <= 8.25s stretch |
| Avg time reduction | >= 14% minimum, >= 19% preferred, >= 24% stretch |
| doc_hit@3 | >= 0.98 |
| doc_hit@5 | 1.00 |
| section/page_hit@3 | >= 0.86 |
| section/page_hit@5 | >= 0.94 |
| Citation precision | no broad parent RSE page overriding exact child evidence |
| Safety boundary | no compliance certification, sign-off, live action approval, or current-state proof |

If V14 improves tokens/time but introduces any serious failure, keep V12 as rollout default.

## Manual Review Set

Always manually inspect:

- OSHA/LOTO sequence completeness
- moving-parts checklist synthesis
- weak generic refusals
- citation claim support
- `osha-loto-df-04`
- `nist-csf-2-un-01`
- broad citation-support cases
- any case where V14 drops evidence included by V12

## Rollback Rule

V12 remains the approved advisory rollout default unless V14 passes the full acceptance gates and is explicitly approved in a new readiness memo.

Rollback to V12 if V14 shows:

- unsafe advice
- compliance certification/sign-off behavior
- unsupported citations
- frequent no-evidence fallback spikes
- reranker fallback
- latency above V12 baseline
- lower recall on OSHA/NIST safety-critical cases

## Prompt To Start Implementation

Use this prompt to start the implementation pass:

```text
You are continuing eMAS RAG work in:

C:\Users\dilun\OneDrive\Documents\eMas APi

Work directly on main. Do not create a branch.

Goal:
Implement and evaluate V14 = Query Rewrite + Hybrid Search + Rerank + Budgeted Evidence-Aware RSE.

Target goals:
- Preserve V12 safety: 0 serious failures, 50/50 automated pass, 0 reranker fallback.
- Reduce average context tokens from the V12 baseline 4656.64 to <= 3500 minimum, <= 3000 preferred, <= 2800 stretch.
- Reduce average runtime from the V12 baseline 10.7929s to <= 9.25s minimum, <= 8.75s preferred, <= 8.25s stretch.
- Keep final score >= 85.0 minimum and preferably >= 85.5598.
- Preserve doc_hit@3 >= 0.98, doc_hit@5 = 1.00, section/page_hit@3 >= 0.86, section/page_hit@5 >= 0.94.
- Improve citation precision by preferring exact child chunk/page/span evidence over broad parent RSE metadata.

Read first:
docs/qa/RAG_V14_OPTIMIZED_RSE_PLAN.md
docs/qa/RAG_PHASE_14_LIMITED_ROLLOUT_READINESS.md
docs/qa/RAG_PRODUCTION_READINESS_RECOMMENDATION.md
docs/qa/RAG_EVALUATION_TRACK.md

First run:
git status --short
git log -5 --oneline
python -m tests.rag_eval.run_eval --help

Rules:
- Use TDD.
- Do not change tests/rag_eval/cases.json.
- Do not weaken scoring or expected answers.
- Do not hardcode OSHA, LOTO, NIST, or benchmark-specific fixes.
- Do not add hardcoded query, document, chunk, page, section, or case IDs to pass specific benchmark cases.
- Do not add one-off string rules for individual documents. Use generic metadata-driven and structure-driven logic.
- When a bug is found, fix the general failure mode, not only the exact failing case.
- For each bug fix, add a regression test for the reported case shape and at least one adjacent/generalized case that proves similar cases are covered.
- In the final report, explain why each fix generalizes and identify the invariant or contract it enforces.
- Keep V12 behavior unchanged and available.
- Add V14 behind explicit config only after optimized RSE behavior is proven by tests.
- Keep compression off by default.
- Keep Document Augmentation off by default.
- Keep reranker fallback disabled.
- Do not grant autonomous safety/compliance authority.

Implementation target:
- Add budgeted evidence-aware RSE as generic context-building logic.
- Expand left/right neighbors only when they add relevant, non-redundant evidence.
- Score neighbor chunks separately before adding them to a segment.
- Use marginal gain, missing-facet coverage, continuity, authority/risk metadata, redundancy penalty, and token-cost penalty.
- Stop expansion when support is sufficient, relevance drops, section/topic continuity breaks, or budget is reached.
- Preserve exact child chunk/page/span evidence for citation projection.
- Add metadata explaining included and excluded neighbor decisions.
- Add global and per-segment context budgets.
- Keep thresholds centralized in config/settings, not scattered constants.
- Add tests that prove the generic rules across at least OSHA-style procedure/list content and NIST-style section/facet content.

Validation:
python -m pytest -q factory-agent/tests/test_rag_context_building.py factory-agent/tests/test_rag_pipeline_config.py factory-agent/tests/test_rag_generation.py factory-agent/tests/test_response_document_contract.py
python -m tests.rag_eval.run_eval --variant V12 --run-id v12-pre-v14-baseline --no-judge
python -m tests.rag_eval.run_eval --variant V7 --run-id v7-pre-v14-reference --no-judge
python -m tests.rag_eval.run_eval --variant V14 --filter loto --run-id v14-smoke-loto --no-judge
python -m tests.rag_eval.run_eval --variant V14 --filter guarding --run-id v14-smoke-guarding --no-judge
python -m tests.rag_eval.run_eval --variant V14 --filter nist-ams300-1 --run-id v14-smoke-ams1 --no-judge
python -m tests.rag_eval.run_eval --variant V14 --filter nist-csf-2 --run-id v14-smoke-csf2 --no-judge

Full candidate gate only after focused smoke passes:
python -m tests.rag_eval.run_eval --variant V14 --run-id v14-full --judge
git diff --check

Report:
- V14 vs Phase 14 V12 final
- V14 vs fresh V12 baseline
- V14 vs fresh V7 reference
- score, serious failures, warnings, avg duration, avg context tokens, retrieval hit rates, reranker fallback, citation/evidence regressions
- whether V14 is ready to replace V12 or should remain experimental
```
