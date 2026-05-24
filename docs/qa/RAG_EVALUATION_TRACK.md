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

Phase 0 baseline harness inspection is complete. No question bank, scoring logic, RAG pipeline variants, RSE, Small-to-Big, compression, or judge scoring have been implemented for this track yet.

Important current decisions:

- Run 1 is a 50-question benchmark across 12 variants.
- Run 1 uses the existing local judge model on port `900`: `Qwen2.5-7B-Instruct-Q4_K_M`.
- The local judge is a practical triage judge, not the final gold-standard judge.
- A random judge reliability audit is required before judge scores are trusted in the decision memo.
- Document Augmentation variants V8 and V13 are deferred to Run 2.
- Work continues directly on `main`; do not create a feature branch unless the user changes this instruction.
- Phase 0 findings reflect the current worktree and persisted indexes. Several RAG ingestion/index files were already dirty before Phase 0 started, so future agents should not assume those ingestion changes are part of the committed baseline until they are reviewed and committed separately.

## Phase Status

| Phase | Name | Status | Owner | Notes |
| --- | --- | --- | --- | --- |
| 0 | Confirm baseline harness shape | Done | Codex | Findings recorded below. Confirmed current artifact schema, citation metadata, retrieval metadata, PDF metadata, neighbor expansion toggle, and smallest safe Phase 1/2 plan. |
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

- [x] Read `docs/qa/RAG_EVALUATION_PLAN.md`.
- [x] Read `tests/rag_eval/README.md`.
- [x] Read `tests/rag_eval/run_eval.py`.
- [x] Read `tests/rag_eval/artifact_schema.py`.
- [x] Read `tests/rag_eval/cases.json`.
- [x] Read `factory-agent/factory_agent/rag/pipeline.py`.
- [x] Read `factory-agent/factory_agent/rag/retrieval.py`.
- [x] Read `factory-agent/factory_agent/rag/reranking.py`.
- [x] Read `factory-agent/factory_agent/rag/generation.py`.
- [x] Read `factory-agent/factory_agent/rag/ingestion.py`.
- [x] Confirm whether answer citations include `doc_id`, `page`, `section_title`, and/or `section_path`.
- [x] Confirm whether retrieval debug includes enough data for `doc_hit@k` and `section_or_page_hit@k`.
- [x] Confirm whether current ingestion stores PDF section/page metadata correctly for all five registered PDFs.
- [x] Confirm how to disable current neighbor expansion for clean V2/V3 comparisons.
- [x] Identify the smallest safe harness change list before implementation starts.

## Phase 0 Findings

Date: 2026-05-25

Working tree note: `git status --short` showed unrelated or pre-existing dirty files before this phase started, including frontend files, RAG ingestion/index files, `factory-agent/tests/test_rag_ingestion.py`, an untracked chunk quality audit, and an untracked vector DB directory. Phase 0 only updates this tracker.

### 1. Answer Citation Metadata

Current answer citations expose:

- `doc_id`: yes, via `SourceCitation.doc_id`.
- `page`: yes, via `SourceCitation.page` when chunk metadata contains a page.
- `page_label`, `pdf_url`, `char_range`, `text_search`: yes, optional locator fields are passed through.
- `section_title`: no, not on `SourceCitation` today.
- `section_path`: no, not on `SourceCitation` today.

Important caveat: `AnswerGenerator` groups chunks by document and emits one citation per unique document using a representative chunk. That means a citation page is the representative support page for the document, not necessarily a per-claim or per-chunk page locator. Phase 2 should expose section fields and consider chunk-level citation artifacts if strict citation scoring is required.

### 2. Retrieval Debug Metadata

Current `retrieval_debug.top_chunks` exposes `chunk_id`, `doc_id`, title, broad metadata, scores, and snippet. List order can be treated as rank, so `doc_hit@3` and `doc_hit@5` are partly possible when at least 5 chunks are serialized.

It is not enough for the planned retrieval metrics:

- `doc_hit@10` is not reliable because the runner defaults to `retrieval_top_n = 5` and the retriever defaults to `fusion_top_k = 8`.
- `section_or_page_hit@3/@5/@10` is not possible from the artifact alone because retrieval debug does not serialize `page`, `page_start`, `page_end`, `section_title`, or `section_path`.
- Current debug retrieval uses `HybridRetriever.retrieve(...)` with `expand_neighbors=True` by default, so expanded neighbor chunks can pollute retrieval rank metrics.

Minimum Phase 2 fix: serialize rank plus page/section metadata in `retrieval_debug`, request at least 10 clean ranked candidates for metrics, and run debug retrieval with neighbor expansion disabled unless the selected variant explicitly tests expansion.

### 3. PDF Ingestion Metadata

The current worktree `ingestion.py` has a PDF structure-aware path that stores page and section metadata: `page`, `page_start`, `page_end`, `page_label`, `page_labels`, `section_title`, `section_path`, `section_level`, paragraph/sentence ranges, `chunk_strategy_version`, and `source_format = pdf`.

Persisted Chroma and BM25 indexes under the current default paths include all five registered PDFs with page and section metadata on every chunk:

| Doc ID | Chunks | Page Metadata | Section Metadata | Strategy |
| --- | ---: | ---: | ---: | --- |
| `nist_ams_300_1` | 117 | 117/117 | 117/117 | `pdf_struct_sentence_v1` |
| `nist_ams_300_11` | 31 | 31/31 | 31/31 | `pdf_struct_sentence_v1` |
| `osha_3120_lockout_tagout` | 82 | 82/82 | 82/82 | `pdf_struct_sentence_v1` |
| `osha_machine_guarding_checklist` | 10 | 10/10 | 10/10 | `pdf_struct_sentence_v1` |
| `nist_csf_2_0` | 62 | 62/62 | 62/62 | `pdf_struct_sentence_v1` |

Quality caveat: the metadata exists, but section-title quality still needs manual review when building the question bank. Some early/front-matter chunks resolve to generic or cover-page style sections such as `General` or `Engineering Laboratory`.

### 4. Neighbor Expansion Control

`HybridRetriever.retrieve` already has an `expand_neighbors` parameter and defaults it to `True`.

For clean V2/V3 hybrid baselines, call:

```python
retriever.retrieve(query=query, route=route, expand_neighbors=False)
```

Current blocker: `RAGPipeline._run_sync` does not expose retrieval options and always calls `self._retriever.retrieve(query=query, route=route)`, so the answer path currently gets hidden neighbor expansion. Phase 2 should add a variant/config object and pass `expand_neighbors=False` for V0-V3 and any non-expansion baseline. The separate retrieval debug call in `tests/rag_eval/run_eval.py` must use the same setting.

### 5. Smallest Safe Phase 1 And Phase 2 Plan

Phase 1 should stay documentation/data-only:

- Read the five registered PDFs directly.
- Replace `tests/rag_eval/cases.json` with the fresh 50-question bank.
- Add `docs/qa/rag_eval_question_bank.md` for human review.
- Include the planned fields: `id`, `doc_id`, `query`, `question_type`, `difficulty`, `wording_style`, `expected_answer_points`, `gold_answer`, `expected_source`, `expects_sources`, `expects_safety_warning`, `unanswerable_reason`, and `serious_failure_modes`.
- Preserve backward-compatible fields that the current harness still reads, especially `expected_doc_ids`, `expects_sources`, and any routing expectation fields needed by existing checks.
- Prefer page-grounded expected sources. Add section expectations only when manually verified from the PDF text/TOC because citations do not yet expose sections.

Phase 2 should make the harness configurable before adding new context-building behavior:

- Add a small `RAGVariantConfig` registry for V0-V7 and V9-V12 with explicit flags for retrieval mode, rerank, query rewrite, neighbor expansion, context builder, and compression.
- Implement clean executable paths for V0-V3 first: vector-only, vector + rerank, hybrid, and hybrid + rerank.
- Disable `expand_neighbors` for V0-V3 and for retrieval debug metrics.
- Add a no-op or bypass path for reranking so V0/V2 truly skip rerank.
- Add vector-only retrieval without BM25 for V0/V1.
- Store `variant_id` and full variant config in every per-case artifact and summary row.
- Expand `retrieval_debug` to top 10 clean ranked chunks and include rank, page, page range, section title/path, and scores.
- Add runtime metric placeholders now, even if scoring waits for Phase 4.
- Do not silently run V4+ as plain hybrid before Phase 3. Either mark unsupported context-builder variants as pending or make the runner fail clearly if Small-to-Big/RSE/compression is requested before implementation.

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

Start Phase 1 only after the user confirms question-bank work should begin. Do not implement variants, RSE, Small-to-Big, compression, or scoring before the Phase 1 question bank is grounded in the five PDFs.
