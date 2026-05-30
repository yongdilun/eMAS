# RAG V15A/B/C Execution Plan: Hardcode Reduction And Maintainable Evidence Selection

## Purpose

Split the V15 work into three controlled candidates so we can keep the high-value techniques, drop the harmful ones, and remove the remaining named-standard query rewrite hardcode without hiding regressions.

Primary goals:

1. Preserve V12/V14 safety while testing V15 improvements.
2. Replace legacy named-standard query rewrite behavior with corpus-aware rewrite for new candidates.
3. Keep the proven V15 retrieval gains.
4. Stop aggressive evidence-card compression from hurting summary and relationship answers.
5. Increase maintainability by centralizing heuristics, adding debug traces, and requiring generic fixes.

## Current Lessons

Positive techniques to keep:

| Technique | Decision | Reason |
| --- | --- | --- |
| Corpus-aware multi-query rewrite | Keep | Improved recall and kept retrieval hit rates high. |
| Original + expanded retrieval fusion | Keep | Preserves original-query intent while adding corpus vocabulary. |
| Exact/top candidate preservation | Keep | Protects strong direct hits that reranker may miss. |
| Short alphanumeric anchors such as `A4`, `B2`, `A232` | Keep | Important for standards/activity references. |
| Query-term/heading coverage checks | Keep | Reduces premature stopping and context loss. |
| Comparison concept-definition preservation | Keep | Improved CSF profile comparison behavior. |
| Resource-listing penalty | Keep as soft penalty | Helps avoid broad resource/tool distractions unless user asks for resources. |

Negative techniques to remove or disable:

| Technique | Decision | Reason |
| --- | --- | --- |
| Aggressive evidence-card compression | Disable by default | Biggest cause of NIST summary and relationship failures. |
| Evidence cards as full context replacement | Disable for V15A/B | Too thin for broad summaries and relationships. |
| Broad metadata expansion | Restrict | Common terms such as `machine`, `NIST`, `manufacturing`, `security` can pull noisy adjacent sources. |
| Front-matter/citation cards as purpose evidence | Strongly demote | Can satisfy the wrong facet and displace actual content evidence. |
| Too-strict no-evidence fallback with thin cards | Soften | Expand context before refusing when retrieved evidence is strong but selected cards are thin. |

## Hardcode Reduction Requirement

The legacy rewrite table contains named terms such as:

```text
loto
csf
mtconnect
qif
```

That table can remain only as legacy compatibility for V12/V14 until a replacement is proven. It must not be used by V15A/B/C.

V15A/B/C must use corpus-aware rewrite built from:

- source registry metadata,
- document titles,
- section titles and section paths,
- domain/subdomain,
- `use_for`,
- organization/authority metadata,
- aliases/acronyms when available in metadata or corpus-derived lexicon,
- indexed chunk metadata.

Do not encode answer facts into rewrite.

Bad:

```text
LOTO -> six steps prepare shutdown isolate lockout release verify
```

Good:

```text
LOTO -> lockout tagout hazardous energy control energy-control procedure
```

## Candidate Definitions

### V15A: Corpus Rewrite Isolation Candidate

Purpose: prove corpus-aware rewrite and multi-query fusion without evidence-card risk.

Config:

```text
V15A = V14
     + corpus-aware multi-query rewrite
     + original/expanded retrieval fusion
     + exact/top candidate preservation
     + short alphanumeric anchor preservation
     + query-term/heading coverage checks
     + soft resource-listing penalty
     - legacy named-standard rewrite table
     - evidence cards as context replacement
     - aggressive evidence-card compression
```

Evidence cards may be produced for logs/debugging only, but generation context remains budgeted RSE.

Success signal:

- If V15A passes, corpus-aware rewrite is useful and can become the replacement path for legacy hardcoded rewrite.
- If V15A fails, fix rewrite/fusion generally before touching evidence cards.

### V15B: Evidence Cards As Metadata Candidate

Purpose: use evidence cards for citation/facet metadata without shrinking the generation context.

Config:

```text
V15B = V15A
     + evidence cards for citation metadata
     + evidence cards for facet/intent traces
     + citation-aware child evidence selection
     - evidence cards as full context replacement
     - aggressive evidence-card compression
```

Cards help choose citations and explain evidence coverage, but do not replace the RSE context sent to the LLM.

Success signal:

- Citation precision improves.
- No loss in summary/relationship accuracy.
- Debug traces explain why cards were selected.

### V15C: Mode-Aware Evidence Card Context Candidate

Purpose: reintroduce compact card context only where it is safe.

Config:

```text
V15C = V15B
     + mode-aware evidence-card context
```

Mode behavior:

| Query mode | Context behavior |
| --- | --- |
| Direct fact | Compact evidence cards allowed. |
| Explicit procedure/list | Exact procedure/list spans allowed, preserving item boundaries. |
| Summary | Evidence cards select anchors, but broader section/RSE context is required. |
| Relationship/comparison | Require concept A, concept B, and connector/relationship evidence. Broader context allowed. |
| Checklist/review | Prefer checklist/list/table evidence, but allow procedure evidence for missing facets. |

Do not use one hard intent label. Use multi-label soft intent scores.

Success signal:

- V15C keeps V15A/B safety.
- Tokens improve without reintroducing NIST summary/relationship failures.
- No false no-evidence fallback caused by thin cards.

## Maintainability Rules

1. Keep V12 and V14 available unchanged.
2. Keep V15A/B/C behind explicit config.
3. Do not change `tests/rag_eval/cases.json`.
4. Do not weaken scoring or expected answers.
5. Do not hardcode benchmark case IDs, query strings, document IDs, chunk IDs, page numbers, or section titles.
6. Do not add named-standard facet templates such as `CSF must cover X` or `guarding must cover Y`.
7. Do not add one-off source rules for OSHA, LOTO, NIST, CSF, AMS, MTConnect, QIF, or any benchmark-specific document.
8. Do not encode answer facts into query rewrite.
9. Use generic metadata-derived and structure-derived logic.
10. Put rewrite thresholds, card weights, facet thresholds, and mode policies in centralized settings objects.
11. Every selected evidence card must expose a score breakdown.
12. Every rewrite expansion must expose source, reason, and confidence.
13. Every bug fix must target the general failure mode, not only the exact failing case.
14. Every bug fix needs one reported-shape regression test and one adjacent/generalized test.

## Centralized Settings To Add Or Confirm

Avoid scattered heuristics. Use centralized dataclasses/config objects such as:

```text
CorpusRewriteSettings
MultiQueryFusionSettings
EvidenceCardSettings
EvidenceSelectionSettings
QueryIntentSettings
NoEvidenceFallbackSettings
```

Each should include defaults and metadata logging. Avoid hidden constants inside scoring functions.

## Evaluation Plan

### Phase 0: Baseline And Hardcode Audit

Run:

```powershell
git status --short
git log -5 --oneline
python -m tests.rag_eval.run_eval --help
```

Audit:

- Identify legacy `QUERY_REWRITE_EXPANSIONS` usage.
- Confirm V15A/B/C do not call the legacy named-standard rewrite table.
- Confirm V12/V14 behavior remains unchanged unless explicitly requested later.
- Confirm no new benchmark-specific hardcode is added.

### Phase 1: V15A

Implement and test:

- corpus-aware rewrite,
- original + expanded retrieval fusion,
- exact/top candidate preservation,
- alphanumeric anchor preservation,
- query-term/heading coverage checks,
- soft resource-listing penalty,
- broad metadata expansion controls.

Focused eval:

```powershell
python -m tests.rag_eval.run_eval --variant V15A --filter loto --run-id v15a-smoke-loto --no-judge
python -m tests.rag_eval.run_eval --variant V15A --filter guarding --run-id v15a-smoke-guarding --no-judge
python -m tests.rag_eval.run_eval --variant V15A --filter nist-ams300-1 --run-id v15a-smoke-ams1 --no-judge
python -m tests.rag_eval.run_eval --variant V15A --filter nist-csf-2 --run-id v15a-smoke-csf2 --no-judge
```

Proceed only if focused smoke is no worse than V14 on serious failures.

### Phase 2: V15B

Implement and test:

- evidence cards as metadata/facet/citation traces only,
- exact child evidence selection,
- front-matter/resource card demotion,
- no evidence-card context replacement.

Focused eval:

```powershell
python -m tests.rag_eval.run_eval --variant V15B --filter loto --run-id v15b-smoke-loto --no-judge
python -m tests.rag_eval.run_eval --variant V15B --filter guarding --run-id v15b-smoke-guarding --no-judge
python -m tests.rag_eval.run_eval --variant V15B --filter nist-ams300-1 --run-id v15b-smoke-ams1 --no-judge
python -m tests.rag_eval.run_eval --variant V15B --filter nist-csf-2 --run-id v15b-smoke-csf2 --no-judge
```

Proceed only if citation quality improves without serious-failure regression.

### Phase 3: V15C

Implement and test:

- mode-aware card context,
- direct/procedure compact mode,
- summary broad-context mode,
- relationship/comparison connector evidence,
- expand-before-refuse fallback.

Focused eval:

```powershell
python -m tests.rag_eval.run_eval --variant V15C --filter loto --run-id v15c-smoke-loto --no-judge
python -m tests.rag_eval.run_eval --variant V15C --filter guarding --run-id v15c-smoke-guarding --no-judge
python -m tests.rag_eval.run_eval --variant V15C --filter nist-ams300-1 --run-id v15c-smoke-ams1 --no-judge
python -m tests.rag_eval.run_eval --variant V15C --filter nist-csf-2 --run-id v15c-smoke-csf2 --no-judge
```

Full judged eval only after focused smoke passes:

```powershell
python -m tests.rag_eval.run_eval --variant V15A --run-id v15a-full --judge
python -m tests.rag_eval.run_eval --variant V15B --run-id v15b-full --judge
python -m tests.rag_eval.run_eval --variant V15C --run-id v15c-full --judge
```

Run full eval only for candidates that pass smoke; do not run all three if earlier smoke clearly fails.

## Acceptance Gates

| Metric | Required |
| --- | ---: |
| Automated pass | 50/50 |
| Serious failures | 0 |
| Reranker fallback | 0 |
| Final score | >= V14 and preferably >= V12 final |
| Avg context tokens | not worse than corresponding baseline |
| Avg time | not materially worse than corresponding baseline |
| doc_hit@3 | >= 0.98 |
| doc_hit@5 | 1.00 |
| section/page_hit@3 | >= 0.86 |
| section/page_hit@5 | >= 0.94 |
| Legacy named rewrite use in V15A/B/C | 0 |
| New benchmark-specific hardcode | 0 |
| Citation precision | no broad parent evidence overriding exact child/card evidence |
| Safety boundary | no compliance certification, sign-off, live action approval, or current-state proof |

V15A/B/C remain experimental if any candidate improves performance but loses safety, citation support, or maintainability.

## Prompt To Execute

```text
You are continuing eMAS RAG work in:

C:\Users\dilun\OneDrive\Documents\eMas APi

Work directly on main. Do not create a branch.

Goal:
Implement and evaluate V15A/B/C while reducing query rewrite hardcode and improving maintainability.

Candidate definitions:
- V15A = V14 + corpus-aware multi-query rewrite + original/expanded retrieval fusion + exact/top candidate preservation + anchor preservation + query-term/heading coverage checks + soft resource-listing penalty. No evidence-card context replacement.
- V15B = V15A + evidence cards for citation/facet/debug metadata only. No evidence-card context replacement.
- V15C = V15B + mode-aware evidence-card context only where safe: compact for direct/procedure answers, broader RSE/section context for summaries, relationships, comparisons, and checklist reviews.

Read first:
docs/qa/RAG_V15_ABC_HARDCODE_REDUCTION_EXECUTION_PLAN.md
docs/qa/RAG_V15_CORPUS_AWARE_REWRITE_AND_EVIDENCE_PLAN.md
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
- Do not weaken scoring, expected answers, or serious-failure rules.
- Do not hardcode benchmark case IDs, query strings, document IDs, chunk IDs, page numbers, or section titles.
- Do not add one-off rules for OSHA, LOTO, NIST, CSF, AMS, guarding, MTConnect, QIF, or any benchmark-specific document.
- Do not encode answer facts into query rewrite.
- Do not add named-standard facet templates such as "CSF must cover X" or "guarding must cover Y".
- V15A/B/C must not use the legacy named-standard QUERY_REWRITE_EXPANSIONS table.
- Keep V12 and V14 available unchanged.
- Keep generation on the original user query.
- Keep compression off by default.
- Keep Document Augmentation off by default.
- Keep reranker fallback disabled.
- Do not grant autonomous safety/compliance authority.
- When a bug is found, fix the general failure mode and add both reported-shape and adjacent/generalized regression tests.

Maintainability requirements:
- Centralize rewrite thresholds, card weights, facet thresholds, and mode policies in settings/dataclasses.
- Every rewrite expansion must log source, reason, and confidence.
- Every evidence card must log score breakdown.
- Every selected/dropped context item must be explainable.
- Avoid scattered constants and hidden scoring rules.

Phase 0:
Audit hardcode and baseline.
- Confirm legacy named rewrite table usage.
- Confirm V15A/B/C do not call legacy named rewrite.
- Confirm no new benchmark-specific hardcode is added.

Phase 1:
Implement V15A and run focused smoke.

Phase 2:
Implement V15B only if V15A smoke is acceptable.

Phase 3:
Implement V15C only if V15B smoke is acceptable.

Validation:
python -m pytest -q factory-agent/tests/test_rag_query_rewriting.py factory-agent/tests/test_rag_context_building.py factory-agent/tests/test_rag_pipeline_config.py factory-agent/tests/test_rag_generation.py factory-agent/tests/test_response_document_contract.py

Focused smoke:
python -m tests.rag_eval.run_eval --variant V15A --filter loto --run-id v15a-smoke-loto --no-judge
python -m tests.rag_eval.run_eval --variant V15A --filter guarding --run-id v15a-smoke-guarding --no-judge
python -m tests.rag_eval.run_eval --variant V15A --filter nist-ams300-1 --run-id v15a-smoke-ams1 --no-judge
python -m tests.rag_eval.run_eval --variant V15A --filter nist-csf-2 --run-id v15a-smoke-csf2 --no-judge

Repeat the same focused smoke for V15B and V15C only after the previous candidate is acceptable.

Full candidate gate only after focused smoke passes:
python -m tests.rag_eval.run_eval --variant <V15A-or-V15B-or-V15C> --run-id <candidate>-full --judge
git diff --check

Report:
- V15A vs V14 and V12
- V15B vs V15A
- V15C vs V15B
- score, serious failures, warnings, avg duration, avg context tokens, retrieval hit rates, reranker fallback, citation/evidence regressions
- hardcoded rewrite rules removed/reduced
- proof that V15A/B/C do not use legacy named-standard QUERY_REWRITE_EXPANSIONS
- each bug found, the general failure mode, the generic fix, and adjacent/generalized tests
- which candidate should remain experimental and which, if any, is ready for further readiness review
```
