# RAG V15 Plan: Corpus-Aware Rewrite And Evidence Selection

## Purpose

V14 focuses on budgeted evidence-aware RSE. V15 should target the next highest-impact maintainability and accuracy problems:

1. reduce hardcoded query rewrite rules,
2. improve source intent matching,
3. select the smallest complete evidence set,
4. keep exact citation lineage.

This is not a benchmark patch phase. The goal is to make retrieval and evidence selection more general across new documents and query wording.

Target candidate:

```text
V15 = V14 + Corpus-Aware Multi-Query Rewrite + Evidence Cards + Soft Intent/Facet Selection
```

## Baseline

Use V12 and V14 as baselines:

| Baseline | Role |
| --- | --- |
| V12 | Approved advisory rollout baseline. Must remain available unchanged. |
| V14 | Optimized RSE candidate. V15 should build on V14 only after V14 focused tests are green. |
| V7 | Efficiency reference, but not rollout default because it had serious failures. |

V15 must not be promoted unless it preserves safety and improves maintainability. Performance gains are valuable only when they do not hide evidence or weaken refusals.

## High-Impact Scope

| Priority | Item | Why It Matters | V15 Scope |
| ---: | --- | --- | --- |
| 1 | Corpus-aware query rewrite | Current rewrite is useful but too hardcoded. Build expansions from corpus metadata instead of one-off constants. | In scope |
| 2 | Multi-query retrieval + fusion | Keeps original query safe while testing expanded queries. Reduces bad rewrite pollution. | In scope |
| 3 | Evidence cards | Replaces broad chunk soup with auditable support units. Helps citations, budget, and debugging. | In scope |
| 4 | Soft intent scoring | Prevents checklist questions from drifting into procedure-only evidence without hard filtering. | In scope |
| 5 | Facet-aware minimal evidence set | Covers required parts with fewer tokens. Helps summaries, comparisons, checklist answers, and procedures. | In scope |
| 6 | Citation-aware child evidence | Exact child chunk/page/span should win over broad parent RSE metadata. | In scope |
| 7 | Citation-first answer outline | Compose from cited facts before final prose. | Small slice only |
| 8 | Verifier/repair | Useful but can add latency and instability. | Defer unless needed by eval |
| 9 | Reranker cost reduction | Valuable, but should come after evidence quality is stable. | Defer |
| 10 | RRF tuning | Useful experiment, but lower impact than rewrite/evidence selection. | Defer |
| 11 | Monitoring dashboard | Important for rollout ops, not core retrieval architecture. | Defer to rollout/ops |

## Maintainability Guardrails

- Do not change `tests/rag_eval/cases.json`.
- Do not weaken scoring, expected answers, or serious-failure rules.
- Do not hardcode benchmark case IDs, query strings, document IDs, chunk IDs, page numbers, or section titles.
- Do not encode answer facts into query rewrite. Rewrite may add search vocabulary, not answers.
- Do not add named-standard facet templates such as "CSF must cover X" or "guarding must cover Y".
- Do not use hard source filters for intent. Use soft boosts and penalties unless safety policy requires refusal.
- Do not derive section type from document title. Derive it from structure and metadata.
- When a bug is found, fix the general failure mode and add an adjacent/generalized regression case.
- Keep V12 and V14 behavior available and unchanged.
- Keep generation on the original user query.
- Log why rewrite terms, evidence cards, facets, and citations were selected.

Bad rewrite:

```text
LOTO -> six steps prepare shutdown isolate lockout release verify
```

Good rewrite:

```text
LOTO -> lockout tagout hazardous energy control energy-control procedure
```

The first leaks answer content. The second improves retrieval vocabulary.

## Phase 1: Corpus-Aware Multi-Query Rewrite

Goal: reduce hardcoded rewrite logic while improving retrieval recall for unseen wording.

Implement a generic corpus lexicon built from:

- source register metadata,
- document titles,
- section titles and section paths,
- domain and subdomain,
- organization and authority metadata,
- `use_for` fields,
- aliases/acronyms where present,
- normalized terms from indexed chunk metadata.

Rewrite output should include:

- original query,
- normalized query,
- corpus-expanded query,
- expansion terms,
- expansion source metadata,
- confidence/reason for each expansion.

Retrieval should run original and expanded queries separately when possible:

```text
original query retrieval
expanded query retrieval
fusion of both result sets
rerank
```

This protects the original user intent when an expansion is imperfect.

Tests:

- acronym variants: `LOTO`, `lock-out tag-out`, `lockout/tagout`;
- unseen wording: `zero energy maintenance steps` should move toward hazardous energy/lockout concepts without hardcoding that exact query;
- metadata-derived expansion from titles/headings/use_for;
- negative case where unrelated corpus metadata is not added;
- generation still receives the original user query;
- logs include expansion sources and confidence.

Success criteria:

- hardcoded rewrite rules are not increased;
- current acronym behavior is preserved or replaced by corpus-derived equivalents;
- doc/section retrieval does not regress against V12/V14 smoke cases;
- no answer facts are inserted into the retrieval query.

## Phase 2: Evidence Cards And Soft Intent/Facet Selection

Goal: select compact, complete, intent-aligned evidence before answer generation.

Create evidence cards from retrieved/RSE chunks:

| Field | Purpose |
| --- | --- |
| `doc_id`, `chunk_id`, `source_id` | Traceability |
| `page`, `page_label`, `section_path` | Location |
| `text_span` | Compact support text |
| `text_search`, `char_range`, `bbox` | Exact evidence locator when available |
| `section_type_scores` | Structural type signals, not title hardcoding |
| `intent_match_scores` | Soft query-intent match |
| `facets_covered` | Generic facets covered by the card |
| `authority_risk_flags` | Safety and source quality |
| `token_cost` | Budgeting |
| `redundancy_key` | Duplicate/noise reduction |

Use generic intent scores, not a single hard enum:

```text
procedure: 0.7
checklist: 0.5
summary: 0.2
comparison: 0.0
```

Use generic facet slots:

- definition,
- purpose,
- scope,
- included items,
- excluded items,
- requirements,
- steps,
- checklist areas,
- limitations,
- relationships,
- examples,
- evidence basis.

Select a minimal evidence set using:

```text
maximize facet coverage
+ source intent match
+ citation precision
+ authority/risk suitability
- redundancy
- token cost
```

Tests:

- checklist-like query prefers checklist/list/table evidence but can still include procedure evidence for missing facets;
- procedure query preserves ordered step evidence;
- summary query covers purpose/scope/components/limitations when evidence exists;
- comparison query includes evidence for both compared concepts;
- mixed-intent query keeps multiple intent scores instead of forcing one label;
- exact child evidence remains attached even when parent RSE context is present.

Success criteria:

- fewer broad chunks are sent to generation;
- missing-facet failures decrease in focused smoke;
- no hardcoded CSF/OSHA/NIST facet templates are introduced;
- citation projection prefers exact card evidence over parent context.

## Phase 3: Cited Outline, Evaluation, And Decision

Goal: prove V15 improves maintainability and quality before any rollout consideration.

Add a small citation-first outline step only if evidence cards are stable:

```text
evidence cards -> cited fact outline -> final answer from original user query
```

Do not add a broad LLM verifier by default. If a verifier is needed, constrain it to evidence cards and generic facets only.

Focused eval first:

```powershell
python -m tests.rag_eval.run_eval --variant V15 --filter loto --run-id v15-smoke-loto --no-judge
python -m tests.rag_eval.run_eval --variant V15 --filter guarding --run-id v15-smoke-guarding --no-judge
python -m tests.rag_eval.run_eval --variant V15 --filter nist-ams300-1 --run-id v15-smoke-ams1 --no-judge
python -m tests.rag_eval.run_eval --variant V15 --filter nist-csf-2 --run-id v15-smoke-csf2 --no-judge
```

Full eval only after focused smoke passes:

```powershell
python -m tests.rag_eval.run_eval --variant V15 --run-id v15-full --judge
```

Compare against:

- Phase 14 V12 final,
- fresh V12 baseline,
- V14 full run,
- fresh V7 reference.

Acceptance gates:

| Metric | Gate |
| --- | ---: |
| Automated pass | 50/50 |
| Serious failures | 0 |
| Reranker fallback | 0 |
| Final score | >= V14 and preferably >= V12 final |
| Avg context tokens | <= V14 and preferably lower |
| Avg time | not materially worse than V14 |
| doc_hit@3 | >= 0.98 |
| doc_hit@5 | 1.00 |
| section/page_hit@3 | >= 0.86 |
| section/page_hit@5 | >= 0.94 |
| Hardcoded rewrite rules | reduced or isolated behind corpus-derived lexicon |
| Citation quality | no broad parent evidence overriding exact child/card evidence |
| Safety boundary | no compliance certification, sign-off, live action approval, or current-state proof |

V15 remains experimental if it improves performance but loses safety, citation support, or maintainability.

## Prompt To Start Implementation

```text
You are continuing eMAS RAG work in:

C:\Users\dilun\OneDrive\Documents\eMas APi

Work directly on main. Do not create a branch.

Goal:
Implement and evaluate V15 = V14 + Corpus-Aware Multi-Query Rewrite + Evidence Cards + Soft Intent/Facet Selection.

Read first:
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
- Do not add one-off rules for OSHA, LOTO, NIST, CSF, guarding, MTConnect, QIF, or any benchmark-specific document.
- Do not encode answer facts into query rewrite. Rewrite may add search vocabulary only.
- Do not add named-standard facet templates such as "CSF must cover X" or "guarding must cover Y".
- When a bug is found, fix the general failure mode and add both reported-shape and adjacent/generalized regression tests.
- Use soft intent scores and evidence-card metadata instead of hard source filters.
- Keep V12 and V14 behavior available and unchanged.
- Keep generation on the original user query.
- Keep compression off by default.
- Keep Document Augmentation off by default.
- Keep reranker fallback disabled.
- Do not grant autonomous safety/compliance authority.

Phase 1:
Implement corpus-aware multi-query rewrite.
- Build expansions from source register metadata, document titles, section headings, aliases/acronyms, domain/subdomain, use_for fields, and indexed metadata.
- Run original and expanded retrieval separately where possible, then fuse.
- Log original query, normalized query, expanded query, expansion terms, expansion sources, and confidence.
- Add tests for acronym variants, unseen wording, metadata-derived expansion, unrelated metadata rejection, and original-query generation.

Phase 2:
Implement evidence cards and soft intent/facet selection.
- Create compact cards with doc/chunk/page/span/citation metadata.
- Derive section type from structure and metadata, not document title.
- Use multi-label intent scores, not one hard enum.
- Use generic facets: definition, purpose, scope, included items, excluded items, requirements, steps, checklist areas, limitations, relationships, examples, evidence basis.
- Select a minimal evidence set that maximizes coverage and intent match while minimizing redundancy and token cost.
- Add tests for checklist, procedure, summary, comparison, mixed-intent, and exact child evidence preservation.

Phase 3:
Evaluate and decide.
- Add a small citation-first outline only if evidence cards are stable.
- Do not add a broad LLM verifier unless focused eval proves it is necessary.
- Run focused V15 smoke first.
- Run full V15 judged eval only after focused smoke passes.

Validation:
python -m pytest -q factory-agent/tests/test_rag_context_building.py factory-agent/tests/test_rag_pipeline_config.py factory-agent/tests/test_rag_generation.py factory-agent/tests/test_response_document_contract.py
python -m tests.rag_eval.run_eval --variant V15 --filter loto --run-id v15-smoke-loto --no-judge
python -m tests.rag_eval.run_eval --variant V15 --filter guarding --run-id v15-smoke-guarding --no-judge
python -m tests.rag_eval.run_eval --variant V15 --filter nist-ams300-1 --run-id v15-smoke-ams1 --no-judge
python -m tests.rag_eval.run_eval --variant V15 --filter nist-csf-2 --run-id v15-smoke-csf2 --no-judge

Full candidate gate only after focused smoke passes:
python -m tests.rag_eval.run_eval --variant V15 --run-id v15-full --judge
git diff --check

Report:
- V15 vs Phase 14 V12 final
- V15 vs V14
- V15 vs fresh V12 baseline
- V15 vs fresh V7 reference
- score, serious failures, warnings, avg duration, avg context tokens, retrieval hit rates, reranker fallback, citation/evidence regressions
- hardcoded rewrite rules removed/reduced
- each bug found, the general failure mode, the generic fix, and adjacent/generalized tests
- whether V15 is ready to replace V14/V12 or should remain experimental
```
