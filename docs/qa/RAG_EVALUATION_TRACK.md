# eMAS RAG Evaluation Tracker

Created: 2026-05-25

Branch: `main`

Purpose: living execution tracker for the RAG evaluation plan. Future agents should update this file before and after each phase. The project is intentionally working directly on `main` for this evaluation track.

Plan: `docs/qa/RAG_EVALUATION_PLAN.md`

## Status Legend

- `Not Started`
- `In Progress`
- `Blocked`
- `Done`

## Current Status

The evaluation plan is drafted and committed as documentation. No harness code, question bank, scoring logic, or RAG pipeline variants have been implemented yet.

Important current decisions:

- Run 1 is a 50-question benchmark across 12 variants.
- Run 1 uses the existing local judge model on port `900`: `Qwen2.5-7B-Instruct-Q4_K_M`.
- The local judge is a practical triage judge, not the final gold-standard judge.
- A random judge reliability audit is required before judge scores are trusted in the decision memo.
- Document Augmentation variants V8 and V13 are deferred to Run 2.
- Work continues directly on `main`; do not create a feature branch unless the user changes this instruction.

## Phase Status

| Phase | Name | Status | Owner | Notes |
| --- | --- | --- | --- | --- |
| 0 | Confirm baseline harness shape | Not Started | TBD | Next action. Confirm current artifact schema, citation metadata, retrieval metadata, and minimal harness changes. |
| 1 | Read PDFs and build question bank | Not Started | TBD | Create fresh 50-question bank and replace existing `tests/rag_eval/cases.json`. |
| 2 | Add variant configuration | Not Started | TBD | Add V0-V7 and V9-V12 registry/config. Keep V8/V13 deferred. |
| 3 | Implement context-building strategies | Not Started | TBD | Implement Small-to-Big, RSE, two-stage segment scoring, and extractive compression. |
| 4 | Add scoring | Not Started | TBD | Add rule scoring, borderline detection, Qwen2.5 7B judge scoring, random reliability audit sample export, and serious-failure flags. |
| 5 | Run Benchmark 1 | Not Started | TBD | Run 50 questions across 12 variants once each. Randomize variant execution order. |
| 6 | Review and decision memo | Not Started | TBD | Review failures, borderline cases, top candidates, safety cases, and judge reliability sample. Select provisional champion. |
| 7 | Benchmark Run 2 with Document Augmentation | Not Started | TBD | Compare top 2-3 Run 1 variants against V8 and V13. |
| 8 | Production rollout recommendation | Not Started | TBD | Freeze winning pipeline config and define production monitoring/regression tasks. |

## Phase 0 Checklist

Before changing code, the next agent should inspect the current harness and metadata reality:

- [ ] Read `docs/qa/RAG_EVALUATION_PLAN.md`.
- [ ] Read `tests/rag_eval/README.md`.
- [ ] Read `tests/rag_eval/run_eval.py`.
- [ ] Read `tests/rag_eval/artifact_schema.py`.
- [ ] Read `tests/rag_eval/cases.json`.
- [ ] Read `factory-agent/factory_agent/rag/pipeline.py`.
- [ ] Read `factory-agent/factory_agent/rag/retrieval.py`.
- [ ] Read `factory-agent/factory_agent/rag/reranking.py`.
- [ ] Read `factory-agent/factory_agent/rag/generation.py`.
- [ ] Read `factory-agent/factory_agent/rag/ingestion.py`.
- [ ] Confirm whether answer citations include `doc_id`, `page`, `section_title`, and/or `section_path`.
- [ ] Confirm whether retrieval debug includes enough data for `doc_hit@k` and `section_or_page_hit@k`.
- [ ] Confirm whether current ingestion stores PDF section/page metadata correctly for all five registered PDFs.
- [ ] Confirm how to disable current neighbor expansion for clean V2/V3 comparisons.
- [ ] Identify the smallest safe harness change list before implementation starts.

## Run 1 Variant Set

| ID | Pipeline | Status |
| --- | --- | --- |
| V0 | Basic Vector RAG | Not Started |
| V1 | Vector + Rerank | Not Started |
| V2 | Hybrid Search | Not Started |
| V3 | Hybrid Search + Rerank | Not Started |
| V4 | Hybrid Search + Small-to-Big | Not Started |
| V5 | Hybrid Search + Small-to-Big + Rerank | Not Started |
| V6 | Hybrid Search + Small-to-Big + Rerank + Light Compression | Not Started |
| V7 | Query Rewrite + Hybrid Search + Small-to-Big + Rerank | Not Started |
| V9 | Hybrid Search + RSE | Not Started |
| V10 | Hybrid Search + RSE + Rerank | Not Started |
| V11 | Hybrid Search + RSE + Rerank + Light Compression | Not Started |
| V12 | Query Rewrite + Hybrid Search + RSE + Rerank | Not Started |

## Deferred Run 2 Variant Set

| ID | Pipeline | Status |
| --- | --- | --- |
| V8 | Document Augmentation + Hybrid Search + Small-to-Big + Rerank | Deferred |
| V13 | Document Augmentation + Hybrid Search + RSE + Rerank | Deferred |

## Judge Reliability Audit Requirements

Run 1 judge:

```text
http://127.0.0.1:900/v1
Qwen2.5-7B-Instruct-Q4_K_M
```

Expected server command used by the user:

```powershell
.\llama-server.exe -m "C:\models\Qwen2.5-7B-Instruct-Q4_K_M.gguf" -ngl 999 -c 32768 -b 512 --parallel 1 -fa on --port 900
```

Audit sample rule:

- Manually check at least 20 judged answers, or 10% of judged answers, whichever is larger.
- Include pass, fail, and borderline judge outputs.
- Include at least 5 safety-related answers if available.
- Include at least 5 citation-sensitive answers if available.
- Include answers from at least 3 different variants.

If judge-human agreement is weak, use judge output only as notes and rely on manual review for top variants. Consider upgrading the Run 2 judge to Qwen3 14B if hardware allows.

## Git Instructions For This Track

- Work directly on `main`.
- Do not create a new branch unless the user explicitly changes the instruction.
- Before committing, run `git status --short` and stage only files related to this RAG evaluation work.
- Do not stage or revert unrelated dirty files.
- Use focused commits with messages like:

```text
docs: add rag evaluation tracker
test: add rag eval question bank
feat: add rag eval variant registry
```

## Commands Run

```powershell
Get-Content -Raw -LiteralPath 'C:\Users\dilun\OneDrive\Documents\eMas APi\.agents\skills\grill-me\SKILL.md'
rg --files -g "*.pdf"
rg --files
Get-ChildItem -Force
Get-Content -Raw tests\rag_eval\README.md
Get-Content -Raw tests\rag_eval\cases.json
Get-Content -Raw tests\rag_eval\run_eval.py
Get-Content -Raw tests\rag_eval\artifact_schema.py
Get-Content -Raw rag_sources\00_metadata_templates\source_register.json
Get-Content -Raw factory-agent\factory_agent\rag\ingestion.py
Get-Content -Raw factory-agent\factory_agent\rag\pipeline.py
Get-Content -Raw factory-agent\factory_agent\rag\retrieval.py
```

## Test Results

No tests have been run for this track yet. The current changes are documentation-only.

## Files Created

- `docs/qa/RAG_EVALUATION_PLAN.md`
- `docs/qa/RAG_EVALUATION_TRACK.md`

## Current Blockers

- None.

## Next Action

Start Phase 0. Do not generate the 50-question bank yet. First confirm that the current citation and ingestion metadata can support page/section-level scoring.

