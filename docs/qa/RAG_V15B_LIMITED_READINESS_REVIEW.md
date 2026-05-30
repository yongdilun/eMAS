# RAG V15B Limited Readiness Review

Created: 2026-05-31
Activation update: 2026-05-31

Scope: stabilization and readiness review for the `V15B` RAG candidate. This review did not tune `V15B`, did not tune `V15C`, did not change `tests/rag_eval/cases.json`, and did not modify RAG source logic during this readiness pass.

Candidate:

- `V15B` = `V15A` plus evidence cards for citation, facet, and debug metadata only.
- Evidence-card context replacement remains off for `V15B`.
- Generation remains on the original user query.
- Compression remains off by default.
- Document augmentation remains off by default.
- Reranker fallback remains disabled.
- `V15B` is active for this school/demo advisory RAG environment.
- `V15B` is not approved for production authority, autonomous safety/compliance decisions, compliance certification, sign-off, live machine-action approval, or current-state proof.

Primary reviewed artifacts:

- `test-artifacts/rag-eval/v15b-readiness-smoke-loto`
- `test-artifacts/rag-eval/v15b-readiness-smoke-guarding`
- `test-artifacts/rag-eval/v15b-readiness-smoke-ams1`
- `test-artifacts/rag-eval/v15b-readiness-smoke-csf2`
- `test-artifacts/rag-eval/v15b-readiness-full`
- `test-artifacts/rag-eval/phase14-20260526-v12`
- `test-artifacts/rag-eval/v12-readiness-current-judged`
- `test-artifacts/rag-eval/v12-pre-v14-baseline-live`
- `test-artifacts/rag-eval/v12-current-drift-audit`

## Executive Decision

Decision: **ACTIVE FOR SCHOOL/DEMO ADVISORY RAG; READY FOR LIMITED READINESS REVIEW**.

`V15B` is now the active advisory RAG variant for this school/demo environment. It is not approved as a production RAG variant or as autonomous safety/compliance authority. It should stay controlled by `RAG_ADVISORY_VARIANT`/runtime config while V12 baseline drift is resolved and while V15B fallback/repair behavior is monitored.

Do not claim `V15B` beats `V12` until the V12 comparison is apples-to-apples. The approved Phase 14 V12 artifact and current V12 reruns differ materially because the V12 baseline has drifted.

## Final V15B Metrics

Final full judged gate:

- Run: `test-artifacts/rag-eval/v15b-readiness-full`
- Cases: 50.
- Automated pass: 50/50.
- Average rule score: 86.6886.
- Serious failures: 0.
- Warnings: 0.
- Judge requested/completed: 39/39.
- Judge errors: 0.
- Judge serious failures: 0.
- Average duration: 10.0248 seconds.
- Average context tokens after compression: 1587.8.
- Reranker fallback: 0.
- Retrieval: `doc_hit@3 = 1.00`, `doc_hit@5 = 1.00`, `doc_hit@10 = 1.00`.
- Retrieval: `section_or_page_hit@3 = 0.94`, `section_or_page_hit@5 = 0.94`, `section_or_page_hit@10 = 0.98`.

## Focused Smoke Results

All focused smoke runs were repeated after the stabilization fixes and remained 0 serious.

| Run | Cases | Avg score | Serious | Warnings | Avg duration | Avg context tokens | Reranker fallback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `v15b-readiness-smoke-loto` | 10 | 85.895 | 0 | 0 | 11.8908s | 1752.5 | 0 |
| `v15b-readiness-smoke-guarding` | 10 | 85.816 | 0 | 0 | 9.8338s | 977.9 | 0 |
| `v15b-readiness-smoke-ams1` | 20 | 84.35 | 0 | 0 | 10.8425s | 1769.05 | 0 |
| `v15b-readiness-smoke-csf2` | 10 | 87.936 | 0 | 0 | 10.1309s | 1670.5 | 0 |

Note: the `nist-ams300-1` filter also matched `nist-ams300-11` cases, producing 20 cases. This is consistent with the earlier focused smoke behavior.

## Full Judged Gate Results

| Run | Variant | Cases | Avg score | Serious | Warnings | Judge | Avg duration | Avg context tokens | Reranker fallback |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| `v15b-readiness-full` | V15B | 50 | 86.6886 | 0 | 0 | 39/39, 0 errors | 10.0248s | 1587.8 | 0 |

Retrieval rates:

- `doc_hit@3 = 1.00`
- `doc_hit@5 = 1.00`
- `doc_hit@10 = 1.00`
- `section_or_page_hit@3 = 0.94`
- `section_or_page_hit@5 = 0.94`
- `section_or_page_hit@10 = 0.98`

## Baseline Comparison

| Run | Variant | Judge mode | Avg score | Serious | Warnings | Avg context tokens | Retrieval doc@3/5/10 | Retrieval section/page@3/5/10 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `phase14-20260526-v12` | V12 | judged | 85.5598 | 0 | 0 | 4656.64 | 0.98 / 1.00 / 1.00 | 0.86 / 0.94 / 0.98 |
| `v12-pre-v14-baseline-live` | V12 | no judge | 81.4852 | 4 | 0 | 4656.64 | 0.98 / 1.00 / 1.00 | 0.86 / 0.94 / 0.98 |
| `v12-current-drift-audit` | V12 | no judge | 80.5298 | 5 | 0 | 4465.34 | 0.98 / 1.00 / 1.00 | 0.86 / 0.94 / 0.98 |
| `v12-readiness-current-judged` | V12 | judged | 83.7014 | 2 | 0 | 4656.66 | 0.98 / 1.00 / 1.00 | 0.86 / 0.94 / 0.98 |
| `v15b-readiness-full` | V15B | judged | 86.6886 | 0 | 0 | 1587.8 | 1.00 / 1.00 / 1.00 | 0.94 / 0.94 / 0.98 |

### V12 Baseline Caveat

The V12 comparison is **not apples-to-apples**.

The approved Phase 14 V12 number is:

- `phase14-20260526-v12`: 85.5598 average score, 0 serious, judged 41/41.

The later table value that showed 81.4852 / 4 serious came from:

- `v12-pre-v14-baseline-live`: 81.4852 average score, 4 serious, judge 0/0.

Those two artifacts are not equivalent because judge mode differed and the V12 generated answers drifted despite similar retrieval metrics and matching V12 configuration. A current judged V12 audit also drifted from the approved Phase 14 artifact:

- `v12-readiness-current-judged`: 83.7014 average score, 2 serious, judged 40/40.

The current judged serious cases are:

- `nist-ams300-1-ss-03`
- `nist-ams300-11-df-04`

For these cases, retrieval seeds and token budgets were effectively the same as the approved Phase 14 artifact, but generation/repair behavior changed. This points to shared generation, repair, or validation drift rather than a retrieval miss.

Until V12 drift is resolved or a new V12 baseline is explicitly approved, V15B should not be described as beating the approved V12 baseline. It can only be described as passing its own current limited-readiness gate.

## Changed Logic Summary

`V15B` includes the following changes relative to V14/V12 behavior:

- Corpus-aware retrieval rewrite based on corpus/index metadata instead of legacy named-standard rewrite.
- Original plus expanded retrieval query fusion.
- Exact/top candidate preservation for context candidates that cover query anchors.
- Budgeted RSE context building with centralized scoring settings.
- Query-term, heading, and metadata coverage checks.
- Soft penalties for resource-listing and front-matter material.
- Evidence cards for metadata, citation, facet, and debug visibility only.
- Summary completeness repair for supported but omitted facets.
- Checklist/list recall separated from procedure repair.
- Guarded extractive fallback for evidence-present refusals in relationship/comparison-style answers.

`V15B` does **not** use evidence-card context replacement. That remains the unstable `V15C` direction and is frozen.

## Bug Fixes And Generalization

### Checklist/procedure drift

Observed shape: a checklist/list-recall question could be converted into a procedure answer when nearby ordered procedure evidence was available.

Generic fix: detect static checklist/item recall and prevent deterministic procedure repair unless the query actually asks for steps, procedure, order, or sequence.

Why it generalizes: the fix is based on question intent shape, not OSHA, LOTO, guarding, or a specific document.

### Summary breadth omission

Observed shape: retrieved evidence supported summary facets such as limitations, scope/applicability, or cadence, but the generated summary omitted them.

Generic fix: summary completeness settings detect supported missing facets and allow repair/augmentation with cited evidence.

Why it generalizes: the fix operates on generic summary facets and evidence/answer pattern coverage, not on named standards or expected benchmark answers.

### Evidence-present refusal

Observed shape: the model sometimes returned an insufficient-evidence answer even when selected context supported a relationship/comparison answer.

Generic fix: guarded extractive fallback can assemble a short cited answer from retrieved evidence only when the query shape and evidence support it.

Why it generalizes: the fallback is driven by relationship/comparison intent and query/evidence term overlap, not by benchmark case IDs or document-specific rules.

### Boundary/purchase over-answering

Observed shape: relationship fallback risked activating on boundary/purchase style requests.

Generic fix: boundary-style requests are excluded from the extractive fallback path.

Why it generalizes: the guard is about request authority and answer type, not about any single source.

## Maintainability Audit

Passes:

- No production diff added benchmark-specific hardcode for OSHA, NIST, CSF, LOTO, MTConnect, QIF, guarding, or any benchmark case.
- `tests/rag_eval/cases.json` was not changed.
- `V15A`, `V15B`, and `V15C` set `query_rewrite=False` and `corpus_aware_query_rewrite=True`.
- Legacy `QUERY_REWRITE_EXPANSIONS` remains available for legacy V12/V14 behavior, but V15A/B/C do not use it.
- Corpus rewrite logs each expansion source, reason, and confidence.
- Evidence cards log selected/dropped metadata and score breakdowns.
- Major rewrite, context, card, and mode settings are centralized in dataclasses/settings.
- Reranker fallback remains disabled.
- Document augmentation remains off.
- Compression remains off by default.

Risks:

- Some helper/fallback thresholds remain outside settings/dataclasses, especially in generation repair and extractive fallback logic. Examples include procedure candidate score thresholds, answer coverage thresholds, and relationship sentence selection thresholds. These should be centralized before broader rollout.
- Shared generation and repair code still affects V12. Current V12 drift shows V12/V14 behavior is not fully isolated from shared generation changes.
- Corpus-aware rewrite can still add noisy low-confidence metadata terms from broad corpus overlap. Rerank/context filtering prevented serious failures in the readiness run, but this should be monitored.
- Evidence cards are metadata-only for V15B. If future config enables context replacement, that becomes V15C-like behavior and must be separately gated.

## Remaining Risks

- V12 approved baseline drift remains unresolved.
- V15B full judged pass is strong, but many cases remain borderline by rule score.
- Relationship/comparison extractive fallback can still over-select adjacent sentences if query intent is ambiguous.
- Summary facet repair can under-trigger or over-trigger on unusual wording.
- Corpus rewrite depends on corpus metadata quality; poor `use_for`, aliases, or section titles can pollute retrieval focus.
- Current evaluation corpus is still narrow relative to production user diversity.
- Safety/compliance answers remain advisory only and must not certify current state, live readiness, or compliance.

## V12 Stabilization Follow-Up

Required before using V12 as an apples-to-apples approval baseline:

- Re-run approved Phase 14 V12 artifact conditions and current V12 under the same judge mode.
- Compare per-case answers, generation validation metadata, and repair paths for the current V12 serious cases.
- Isolate V12 from shared generation repair/fallback changes where those changes alter approved V12 behavior.
- Decide whether to restore the approved V12 behavior or explicitly approve a new V12 baseline.
- Add a regression guard that checks V12 does not activate newer V15-only repair/fallback paths unless explicitly intended.

Current V12 drift cases for follow-up:

- `nist-ams300-1-ss-03`: current judged V12 fell to 38.89 and became serious despite similar retrieved context; generation returned insufficient evidence after repair validation.
- `nist-ams300-11-df-04`: current judged V12 fell to 38.89 and became serious despite similar retrieved context; generation/citation repair failed on the four-item answer.

## Rollback Instructions

If V15B shows serious failures, citation regressions, latency spikes, or unsafe fallback behavior:

1. Set `RAG_ADVISORY_VARIANT=V12` to return to the Phase 14 V12 limited advisory baseline, or set `RAG_ADVISORY_VARIANT=default` to return to previous legacy advisory RAG behavior.
2. Disable `corpus_aware_query_rewrite` and `multi_query_retrieval` by selecting a non-V15 variant.
3. Disable evidence-card metadata by selecting a variant without `use_evidence_cards`.
4. Keep `document_augmentation=false`, `compression=none`, and `allow_rerank_fallback=false`.
5. Preserve the failing run artifacts under `test-artifacts/rag-eval`.
6. Record the failed case IDs, run ID, query, answer, selected citations, `query_rewrite` metadata, rerank trace, and `context_building` metadata.
7. Do not patch with document-specific rules; classify whether the issue is retrieval, context selection, generation, citation, fallback, or safety boundary behavior.

## Monitoring Checklist

During limited readiness review, monitor:

- Serious failure count remains 0 on focused and full gates.
- Judge errors remain 0.
- Reranker fallback remains 0.
- Citation source IDs point to the cited evidence document and section/page.
- Boundary questions refuse certification, sign-off, live machine action, current compliance proof, and unsupported vendor purchase advice.
- Checklist/list recall answers do not turn into procedure steps unless the user asks for procedure/sequence.
- Procedure answers include all supported steps and per-step citations.
- Summary answers include supported limitations, scope/applicability, and cadence when present.
- Relationship/comparison answers do not over-answer purchase, compliance, or live-operation requests.
- Corpus rewrite expansion terms have source, reason, confidence, and do not include answer facts.
- Context token budget remains near the V15B gate level and does not silently approach V12-sized context.
- Evidence-card mode remains `metadata_only` for V15B.
- V15C remains frozen and is not used as a fallback.

## Recommendation

`V15B` should remain active for **school/demo advisory RAG** and move through **limited readiness review behind runtime config**.

It should not become the production RAG variant. The main blockers to broader approval are V12 baseline drift, remaining hidden thresholds outside settings/dataclasses, and fallback/repair behavior that needs monitoring under broader query diversity.
