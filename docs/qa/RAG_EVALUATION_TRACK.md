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

Phase 6.5 Fairness Fix and Corrected Rerun is complete. The fresh 50-question bank now has the original Run 1 artifacts plus a corrected comparison set for the 8 rerank-enabled variants and 4 anchor variants. `docs/qa/RAG_EVALUATION_CORRECTED_RUN_ADDENDUM.md` records the corrected baseline. The corrected provisional champion is `V7`, with `V12` effectively tied as co-lead and `V10` as the third carry-forward candidate for Phase 7. Document Augmentation V8/V13 has not been implemented or run.

Important current decisions:

- Run 1 is a 50-question benchmark across 12 variants.
- Run 1 uses the existing local judge model on port `900`: `Qwen2.5-7B-Instruct-Q4_K_M`.
- The local judge is a practical triage judge, not the final gold-standard judge.
- Phase 6 manually audited judge samples and found Qwen2.5 7B reliable enough for rough triage only, weak for safety and citation adjudication.
- Phase 6.5 fixed the unfair reranker fallback, improved citation/evidence audit artifacts and safety-boundary checks, then reran the affected variants plus anchors.
- Corrected Phase 6.5 provisional champion: `V7`. Co-lead: `V12`. Recommended top 3 for Phase 7: `V7`, `V12`, and `V10`; `V5` is a close alternate and `V2` remains an optional clean control.
- Run 2 should prefer a stronger judge such as Qwen3 14B if hardware allows.
- Document Augmentation variants V8 and V13 are deferred to Run 2.
- Work continues directly on `main`; do not create a feature branch unless the user changes this instruction.
- Phase 5 ran the benchmark only. It did not change the question bank, scoring, RSE, Small-to-Big, compression, or Document Augmentation.
- Run 1 judge calls completed without runtime errors, but judge output remains triage evidence only after the Phase 6 manual audit.
- V7 and V12 use a deterministic retrieval-only query rewrite path that appends retrieval focus terms and acronym expansions; generation still receives the original user query.
- Light compression is extractive and keyword-overlap based for Phase 3. It preserves source sentence order and section context, but does not yet use embedding-based semantic sentence selection.
- Original Run 1 caveat: rerank-enabled variants logged `BGE Reranker failed: XLMRobertaTokenizer has no attribute prepare_for_model. Falling back to initial boosted scores.` Phase 6.5 resolved this for corrected artifacts by replacing the reranker integration and requiring visible, explicit fallback.
- Phase 0 findings reflect the current worktree and persisted indexes. Several RAG ingestion/index files were already dirty before Phase 0 started, so future agents should not assume those ingestion changes are part of the committed baseline until they are reviewed and committed separately.

## Phase Status

| Phase | Name | Status | Owner | Notes |
| --- | --- | --- | --- | --- |
| 0 | Confirm baseline harness shape | Done | Codex | Findings recorded below. Confirmed current artifact schema, citation metadata, retrieval metadata, PDF metadata, neighbor expansion toggle, and smallest safe Phase 1/2 plan. |
| 1 | Read PDFs and build question bank | Done | Codex | Fresh 50-question bank created in `tests/rag_eval/cases.json` and human-readable copy added at `docs/qa/rag_eval_question_bank.md`. JSON validation confirmed the 10-per-PDF and 4/3/2/1 type mix. |
| 2 | Add variant configuration | Done | Codex | Added V0-V7 and V9-V12 registry/config. V0-V3 are executable; V4/V5/V6/V7/V9/V10/V11/V12 are registered but blocked as not implemented for Phase 2. |
| 3 | Implement context-building strategies | Done | Codex | Implemented Small-to-Big, RSE, cheap segment scoring, deterministic retrieval query rewrite for V7/V12, and extractive compression for V6/V11. |
| 4 | Add scoring | Done | Codex | Added rule scoring, retrieval metrics, borderline detection, optional Qwen2.5 7B judge support, random reliability audit sample export, summary aggregates, and serious-failure flags. |
| 5 | Run Benchmark 1 | Done | Codex | Run 1 completed across 12 variants in fixed randomized order. Artifacts validated: 600 case artifacts, 12 summaries, and 12 judge audit samples. |
| 6 | Review and decision memo | Done | Codex | Decision memo added. Provisional champion: V12. Runner-up: V7. Run 2 carry-forward set: V12, V7, and V2 if budget permits. |
| 6.5 | Fairness fix and corrected rerun | Done | Codex | Fixed/replaced reranker integration, added visible fallback tracing, improved citation/evidence artifacts and safety-boundary scoring, reran V1/V3/V5/V6/V7/V10/V11/V12 plus V0/V2/V4/V9 anchors. |
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

## Phase 1 Findings

Date: 2026-05-25

Phase 1 stayed data/documentation-only:

- Replaced the old 10-case `tests/rag_eval/cases.json` with 50 fresh document-only questions.
- Added `docs/qa/rag_eval_question_bank.md` as the human-readable review copy.
- Read the five registered PDFs directly and grounded each case to page-level source expectations.
- Preserved current-harness compatibility fields in each case: `expected_doc_ids`, `tags`, and `routing_expectation`.
- Added planned scoring fields in each case: `doc_id`, `question_type`, `difficulty`, `wording_style`, `expected_answer_points`, `gold_answer`, `expected_source`, `expects_sources`, `expects_safety_warning`, `unanswerable_reason`, and `serious_failure_modes`.
- `expected_source` records `doc_id`, a section label, a representative `page`, and a `pages` array for multi-page evidence. Current answer citations still expose only `doc_id` and `page`, so section labels are future-facing for Phase 4 scoring.

Question-bank mix:

| Doc ID | Direct Fact | Section Summary | Multi-Chunk | Boundary | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| `nist_ams_300_1` | 4 | 3 | 2 | 1 | 10 |
| `nist_ams_300_11` | 4 | 3 | 2 | 1 | 10 |
| `osha_3120_lockout_tagout` | 4 | 3 | 2 | 1 | 10 |
| `osha_machine_guarding_checklist` | 4 | 3 | 2 | 1 | 10 |
| `nist_csf_2_0` | 4 | 3 | 2 | 1 | 10 |

Boundary cases intentionally cover:

- Live factory status/scheduling request unsupported by the NIST reference architecture.
- Vendor purchase recommendation unsupported by NIST manufacturing data guidance.
- Live lockout permission unsupported by the OSHA lockout/tagout booklet.
- OSHA compliance certification unsupported by the machine guarding checklist.
- Live cloud security/compliance proof unsupported by NIST CSF 2.0.

Safety-warning expectations are set only where the query has high-risk safety intent. OSHA lockout/tagout procedural cases expect safety warnings; descriptive machine-guarding checklist recall does not always expect one.

Validation:

- JSON parsed successfully.
- All 50 cases include the required Phase 1 fields.
- No duplicate case IDs were found.
- Each registered PDF has exactly 10 cases with the required 4/3/2/1 question-type mix.

## Phase 2 Findings

Date: 2026-05-25

Phase 2 stayed limited to variant configuration and clean retrieval/debug plumbing:

- Added `tests/rag_eval/variants.py` with the Run 1 registry for V0, V1, V2, V3, V4, V5, V6, V7, V9, V10, V11, and V12.
- V0-V3 are executable in Phase 2:
  - V0: vector retrieval only, no BM25, no rerank, no neighbor expansion.
  - V1: vector retrieval plus rerank, no BM25, no neighbor expansion.
  - V2: hybrid retrieval, no rerank, no neighbor expansion.
  - V3: hybrid retrieval plus rerank, no neighbor expansion.
- V4/V5/V6/V7/V9/V10/V11/V12 are registered as Run 1 variants but marked `registered_not_implemented`; selecting them through the runner fails clearly instead of silently running plain hybrid retrieval.
- Added `RAGPipelineConfig` so the eval harness can pass retrieval mode, top-k settings, rerank enablement, and `expand_neighbors` while normal RAG callers keep the old default behavior: hybrid retrieval, rerank enabled, neighbor expansion enabled.
- Added vector-only retrieval mode to `HybridRetriever.retrieve(...)`; it skips BM25 and reciprocal-rank fusion and preserves vector score as the base fusion score for downstream ordering/debug output.
- Added a no-rerank path in `RAGPipeline` so V0 and V2 pass retrieved chunks directly to generation.
- Updated retrieval debug to use the selected variant's retrieval settings and to log rank, doc ID, page, page_start/page_end, section_title, section_path, chunk_id, score fields, and snippet.
- Added `variant_id` and `variant_config` to every per-case artifact and to `summary.json`.
- Default eval variant is V3. The CLI and PowerShell wrapper now accept `--variant` / `-Variant`.
- No RSE, Small-to-Big, compression, scoring, judge scoring, or full benchmark execution was added.

## Phase 3 Findings

Date: 2026-05-25

Phase 3 stayed limited to context building and compression:

- Added `factory-agent/factory_agent/rag/context_building.py` with a post-retrieval context builder used by the RAG pipeline.
- Small-to-Big now expands selected small chunks to all chunks in the same `doc_id` and `section_path` parent section. If the parent section is over the token cap, it keeps section context plus extractive matching spans using original wording.
- RSE now starts from top selected/reranked chunks, joins only same-`doc_id` chunks, keeps same `section_path` when available, preserves chunk order inside each segment, respects a plus/minus 2 window, and caps segment size before generation.
- The second stage after expansion uses cheap segment scoring based on max child score, query coverage, and metadata/source bonuses. It does not call the LLM reranker again.
- V6 and V11 now run light extractive compression after expansion. Compression preserves section heading/context, source sentence order, selected evidence sentences, and nearby evidence sentences where budget allows. It targets roughly 40-50% reduction with a 1,500-token hard cap.
- Small-to-Big and RSE are mutually exclusive at `RAGPipelineConfig` validation time.
- V7 and V12 are executable with deterministic retrieval-only query rewrite. The rewrite appends retrieval focus terms and known acronym expansions; it is not an LLM rewrite.
- Per-case artifacts now receive context-building metadata through `rag.metadata.context_building`, including builder type, segment IDs, child chunk IDs, doc/section/page metadata, token estimates before expansion, after expansion, after compression, segment scores, and compression status.
- Source citations now carry section title/path and page start/end when available.
- V8 and V13 remain deferred and were not added to the Run 1 registry.
- No scoring, LLM judge, Document Augmentation, or full benchmark execution was added.

## Phase 4 Findings

Date: 2026-05-25

Phase 4 stayed limited to scoring and judge triage:

- Added deterministic rule scoring in `tests/rag_eval/scoring.py`.
- Rule dimensions cover answer presence, expected document citation for answerable cases, expected citation page/range, expected citation section when exposed, expected answer-point coverage, expected safety warning, helpful boundary behavior, and no obvious serious failure.
- Added retrieval metrics from clean ranked `retrieval_debug.top_chunks`: `doc_hit@3/@5/@10` and `section_or_page_hit@3/@5/@10`.
- Added explicit serious-failure classifications: `wrong_answer`, `wrong_or_missing_citation`, `citation_does_not_support_answer`, `unsafe_advice`, `hallucinated_unsupported_claim`, and `failed_boundary_answer`.
- Unsafe advice is a hard fail signal and caps the deterministic rule score at 40.
- Borderline detection now flags cases in the 60-80 rule-score band, expected-doc-cited-but-partial-answer cases, unclear page/section locator cases, possible valid paraphrases, weak safety warnings, and partially helpful boundary answers.
- Added optional judge support in `tests/rag_eval/judge.py`. The judge is off by default and can be enabled with `--judge` or `FACTORY_AGENT_RAG_EVAL_JUDGE=1`.
- Judge calls are limited to borderline cases only. The default judge endpoint/model are `http://127.0.0.1:900/v1` and `Qwen2.5-7B-Instruct-Q4_K_M`.
- Judge prompts require strict JSON with correctness, completeness, faithfulness, citation quality, safety, conciseness, serious-failure fields, and a short rationale.
- Judge output is stored as triage evidence only in `judge_result`; parse/call errors go to `judge_error`.
- Added judge audit sample export in `tests/rag_eval/audit.py`. When judge mode is enabled, the runner writes `judge_audit_sample.json` in the run artifact folder.
- Audit sampling includes all judged answers for small smoke runs under 20 judged answers. Larger samples target at least 20 or 10% of judged answers, try to include pass/fail/borderline buckets, at least 5 safety-related answers when available, at least 5 citation-sensitive answers when available, and at least 3 variants when available.
- `summary.json` now includes run-level scoring aggregates and per-variant aggregates: average rule score, borderline count, serious-failure count, retrieval hit rates, average duration, average context token estimates when present, and judge counts.
- The PowerShell wrapper accepts `-Judge`; the CLI accepts `--judge`, `--no-judge`, `--judge-base-url`, `--judge-model`, and `--judge-audit-seed`.
- No live judge call, live LLM run, full benchmark, Document Augmentation V8/V13, question-bank change, RSE behavior change, or Small-to-Big behavior change was made.

## Phase 5 Findings

Date: 2026-05-25

Phase 5 stayed limited to live benchmark execution and tracker documentation:

- Confirmed current branch `main` at `aa90b87c feat: add rag eval scoring`.
- Confirmed local llama-server on `http://127.0.0.1:900/v1/models`; reported model ID `Qwen2.5-7B-Instruct-Q4_K_M.gguf`.
- Re-ran ingestion before the benchmark. All five PDFs were already ingested at the expected versions; BM25 was rebuilt.
- Ran the requested smoke tests:
  - `smoke-v3-score`: V3, case `nist-csf-2-df-01`, score 100.0, no warnings.
  - `smoke-v11-context`: V11, case `nist-csf-2-df-01`, score 100.0, no warnings. Judge was enabled but skipped because the case was not borderline.
- Ran the 12 Run 1 variants one at a time in the fixed randomized order: V9, V3, V6, V0, V12, V5, V2, V11, V7, V1, V10, V4.
- All full runs used `--judge`; all judge calls completed without errors.
- Artifact validation passed for every full run: each folder has 50 case JSON artifacts plus `summary.json` and `judge_audit_sample.json`.
- Total full benchmark artifacts: 600 case artifacts, 12 summaries, and 12 judge audit sample files.
- Each judge audit sample contains 20 sampled judged cases.
- No question-bank, scoring, RSE, Small-to-Big, compression, or Document Augmentation changes were made.

Important runtime caveats:

- Rerank-enabled variants repeatedly logged `BGE Reranker failed: XLMRobertaTokenizer has no attribute prepare_for_model. Falling back to initial boosted scores.` Affected variants: V1, V3, V5, V6, V7, V10, V11, and V12. This did not crash the runs, but Phase 6 should treat their reranking behavior as degraded/fallback behavior.
- Judge output is still triage evidence only. Phase 6 must manually audit the judge samples before relying on judge conclusions.
- Serious-failure counts below are automated classifications, not final manual adjudications.

### Run 1 Summary

| Variant | Run ID | Cases | Automated Failures | Serious Failures | Borderline | Judge | Avg Rule | doc@3/5/10 | section/page@3/5/10 | Avg Sec | Context Tokens Before/After/Compressed |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | --- | ---: | --- |
| V9 | `run1-20260525-v09` | 50 | 0 | 25 | 30 | 30/30, 0 errors | 67.03 | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 3.39 | 1832/2445/2445 |
| V3 | `run1-20260525-v03` | 50 | 0 | 24 | 35 | 35/35, 0 errors | 67.99 | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.29 | 592/592/592 |
| V6 | `run1-20260525-v06` | 50 | 0 | 26 | 37 | 37/37, 0 errors | 63.98 | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.11 | 592/728/443 |
| V0 | `run1-20260525-v00` | 50 | 0 | 27 | 32 | 32/32, 0 errors | 65.73 | 0.96/0.96/1.00 | 0.78/0.86/0.92 | 2.78 | 1623/1623/1623 |
| V12 | `run1-20260525-v12` | 50 | 0 | 21 | 34 | 34/34, 0 errors | 69.82 | 0.94/1.00/1.00 | 0.86/0.94/0.96 | 2.42 | 628/928/928 |
| V5 | `run1-20260525-v05` | 50 | 0 | 26 | 33 | 33/33, 0 errors | 66.37 | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.28 | 592/728/728 |
| V2 | `run1-20260525-v02` | 50 | 0 | 23 | 32 | 32/32, 0 errors | 69.66 | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 3.01 | 1978/1978/1978 |
| V11 | `run1-20260525-v11` | 50 | 0 | 26 | 37 | 37/37, 0 errors | 64.01 | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.04 | 545/756/472 |
| V7 | `run1-20260525-v07` | 50 | 0 | 22 | 32 | 32/32, 0 errors | 69.35 | 0.94/1.00/1.00 | 0.86/0.94/0.96 | 2.45 | 640/898/898 |
| V1 | `run1-20260525-v01` | 50 | 0 | 29 | 31 | 31/31, 0 errors | 61.13 | 0.96/0.96/1.00 | 0.78/0.86/0.92 | 2.09 | 487/487/487 |
| V10 | `run1-20260525-v10` | 50 | 0 | 27 | 33 | 33/33, 0 errors | 65.17 | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.35 | 545/756/756 |
| V4 | `run1-20260525-v04` | 50 | 0 | 23 | 32 | 32/32, 0 errors | 69.21 | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 3.21 | 1978/2363/2363 |

## Phase 6 Findings

Date: 2026-05-25

Phase 6 stayed limited to artifact review and documentation:

- Loaded all 12 Run 1 `summary.json` files and compared average rule score, serious failures, borderline counts, judge counts, automated pass/fail counts, retrieval hit rates, average duration, and context-token estimates.
- Loaded all 12 `judge_audit_sample.json` files.
- Manually inspected 29 judged answers from the audit samples, covering 7 variants, pass/fail/borderline judge buckets, safety-sensitive answers, citation-sensitive answers, and top-candidate/baseline variants.
- Added `docs/qa/RAG_EVALUATION_DECISION_MEMO.md`.
- Updated this tracker.
- Did not rerun the full benchmark.
- Did not run live judge calls.
- Did not change the question bank.
- Did not change RAG pipeline behavior.
- Did not implement or start Document Augmentation V8/V13.

Phase 6 decision:

- Provisional champion: `V12` - Query Rewrite + Hybrid Search + RSE + Rerank flag.
- Runner-up: `V7` - Query Rewrite + Hybrid Search + Small-to-Big + Rerank flag.
- Top Run 1 variants for Run 2: `V12`, `V7`, and `V2` if budget permits a clean non-rerank control.
- Confidence: medium for choosing the Run 2 candidate set, low for production rollout.

Important interpretation:

- `V12` is not a validated true-reranker champion. Because rerank-enabled variants fell back, `V12` should be read as the best query-rewrite + hybrid + RSE + fallback-ranking Run 1 candidate.
- `V2` remains important because it is the strongest clean non-rerank baseline: 69.66 average rule score, 23 serious failures, no reranker fallback caveat.
- Query rewrite helped materially: `V7` and `V12` improved `doc_hit@5` to 1.00 and `section_or_page_hit@5` to 0.94.
- Compression lowered token cost but hurt quality, so `V6` and `V11` should not be production defaults yet.
- Safety answers generally avoided direct unsafe authorization, but high-risk boundary answers were often too generic.
- Qwen2.5 7B judge output is useful only as triage evidence. It is weak for safety scoring and inconsistent for citation support. Run 2 should use Qwen3 14B if available.

Required bug fix before Run 2:

- Fix or replace the BGE reranker integration and add a smoke assertion that rerank-enabled variants fail loudly if reranking falls back.

## Phase 6.5 Findings

Date: 2026-05-25

Phase 6.5 corrected fairness defects and reran the affected comparison set:

- Replaced the broken FlagEmbedding reranker integration with a direct Transformers cross-encoder wrapper for `BAAI/bge-reranker-v2-m3`.
- Added strict reranker behavior: rerank-enabled variants fail loudly by default if reranking cannot run, and fallback is allowed only when explicitly configured and recorded.
- Added rerank trace artifacts and summary counts for enabled, attempted, succeeded, and fallback-used cases.
- Added citation support artifacts with supporting chunk IDs, pages, sections, and evidence snippets.
- Improved OSHA/live-status boundary behavior so high-risk unsupported requests require a concrete caution and a safe next step.
- Audited compression with focused tests showing required evidence is preserved in representative compressed contexts.
- Kept the 50-question bank unchanged.
- Did not implement Document Augmentation `V8` or `V13`.

Corrected rerun scope:

- Required rerank variants: `V1`, `V3`, `V5`, `V6`, `V7`, `V10`, `V11`, and `V12`.
- Anchor variants: `V0`, `V2`, `V4`, and `V9`.
- All corrected runs used `--judge`; judge calls completed without errors.
- Artifact validation passed for every corrected folder: 50 case artifacts, `summary.json`, and `judge_audit_sample.json`.
- Rerank variants recorded 50/50 attempted, 50/50 succeeded, and 0 fallback.

Corrected result:

| Variant | Avg Rule | Serious | Borderline | Rerank Succeeded/Fallback |
| --- | ---: | ---: | ---: | --- |
| `V7` | 76.58 | 17 | 35 | 50/0 |
| `V12` | 76.56 | 17 | 34 | 50/0 |
| `V10` | 75.55 | 17 | 33 | 50/0 |
| `V5` | 75.32 | 17 | 33 | 50/0 |
| `V2` | 74.40 | 17 | 28 | 0/0 |
| `V3` | 72.58 | 19 | 30 | 50/0 |
| `V1` | 72.37 | 18 | 35 | 50/0 |
| `V4` | 71.94 | 19 | 28 | 0/0 |
| `V0` | 70.93 | 20 | 31 | 0/0 |
| `V9` | 70.91 | 20 | 26 | 0/0 |
| `V11` | 70.84 | 21 | 36 | 50/0 |
| `V6` | 69.45 | 22 | 36 | 50/0 |

Decision update:

- Corrected provisional champion: `V7`.
- Co-lead: `V12`; the margin is only 0.0194 average rule points, with both at 17 serious failures.
- Top Phase 7 carry-forward set: `V7`, `V12`, and `V10`.
- `V5` is a close alternate to `V10`.
- `V2` remains useful as a clean non-rerank hybrid control, but it is no longer a top-three corrected candidate.

Important interpretation:

- The reranker fix changed the ranking enough that the Phase 6 `V12` champion should be superseded by the corrected `V7`/`V12` co-lead result.
- Citation-related serious-failure flags dropped from 200 citation flags in original Run 1 to 105 in the corrected comparison.
- Safety-case serious failures dropped from 91 safety cases with at least one serious failure to 75, while the OSHA live-status boundary case gained concrete caution and safe-next-step metadata.
- Automated `unsafe_advice` flags increased from 7 to 9 and need manual review; strict hard-failure scoring remains in place.
- Compression remains quality-negative: `V6` and `V11` save tokens but trail their uncompressed counterparts by 5.87 and 4.72 average rule points respectively.

Full details are in `docs/qa/RAG_EVALUATION_CORRECTED_RUN_ADDENDUM.md`.

## Run 1 Variant Set

| ID | Pipeline | Status |
| --- | --- | --- |
| V0 | Basic Vector RAG | Phase 2 Executable |
| V1 | Vector + Rerank | Phase 2 Executable |
| V2 | Hybrid Search | Phase 2 Executable |
| V3 | Hybrid Search + Rerank | Phase 2 Executable |
| V4 | Hybrid Search + Small-to-Big | Phase 3 Executable |
| V5 | Hybrid Search + Small-to-Big + Rerank | Phase 3 Executable |
| V6 | Hybrid Search + Small-to-Big + Rerank + Light Compression | Phase 3 Executable |
| V7 | Query Rewrite + Hybrid Search + Small-to-Big + Rerank | Phase 3 Executable with deterministic retrieval rewrite |
| V9 | Hybrid Search + RSE | Phase 3 Executable |
| V10 | Hybrid Search + RSE + Rerank | Phase 3 Executable |
| V11 | Hybrid Search + RSE + Rerank + Light Compression | Phase 3 Executable |
| V12 | Query Rewrite + Hybrid Search + RSE + Rerank | Phase 3 Executable with deterministic retrieval rewrite |

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
git status --short
Get-Content -Raw -LiteralPath 'docs/qa/RAG_EVALUATION_PLAN.md'
Get-Content -Raw -LiteralPath 'docs/qa/RAG_EVALUATION_TRACK.md'
Get-Content -Raw -LiteralPath 'tests/rag_eval/cases.json'
Get-Content -Raw -LiteralPath 'rag_sources/00_metadata_templates/source_register.json'
rg --files -g '*.pdf'
python -c "import fitz; print('pymupdf ok')"
python -c "import pypdf; print('pypdf ok')"
python -c "import PyPDF2; print('PyPDF2 ok')"
@'<pdf extraction scripts for TOC, headings, page text, and source snippets>'@ | python -
@'<JSON validation and mix-count script>'@ | python -
git diff --check -- tests/rag_eval/cases.json docs/qa/rag_eval_question_bank.md docs/qa/RAG_EVALUATION_TRACK.md
git status --short
Get-Content -Raw -Path 'docs/qa/RAG_EVALUATION_PLAN.md'
Get-Content -Raw -Path 'docs/qa/RAG_EVALUATION_TRACK.md'
Get-Content -Raw -Path 'tests/rag_eval/run_eval.py'
Get-Content -Raw -Path 'tests/rag_eval/artifact_schema.py'
Get-Content -Raw -Path 'tests/rag_eval/cases.json'
Get-Content -Raw -Path 'factory-agent/factory_agent/rag/pipeline.py'
Get-Content -Raw -Path 'factory-agent/factory_agent/rag/retrieval.py'
Get-Content -Raw -Path 'factory-agent/factory_agent/rag/reranking.py'
Get-Content -Raw -Path 'factory-agent/factory_agent/rag/generation.py'
rg "RAGPipeline|HybridRetriever|serialize_retrieval_debug|RunnerOptions|run_eval" -n
rg --files -g '*rag*test*.py' -g 'test_*rag*.py' -g '*rag_eval*'
python -m pytest -q factory-agent/tests/test_rag_retrieval.py factory-agent/tests/test_rag_pipeline_config.py tests/rag_eval/test_variants.py tests/rag_eval/test_artifact_schema.py
python -m pytest -q factory-agent/tests/test_rag_retrieval.py factory-agent/tests/test_rag_pipeline_config.py tests/rag_eval/test_variants.py tests/rag_eval/test_artifact_schema.py tests/rag_eval/test_run_eval_variants.py
python -m json.tool tests/rag_eval/cases.json
python -m tests.rag_eval.run_eval --help
git diff --check
git status --short
Get-Content -Raw -LiteralPath 'docs/qa/RAG_EVALUATION_PLAN.md'
Get-Content -Raw -LiteralPath 'docs/qa/RAG_EVALUATION_TRACK.md'
Get-Content -Raw -LiteralPath 'tests/rag_eval/variants.py'
Get-Content -Raw -LiteralPath 'tests/rag_eval/run_eval.py'
Get-Content -Raw -LiteralPath 'tests/rag_eval/artifact_schema.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/rag/pipeline.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/rag/retrieval.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/rag/reranking.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/rag/generation.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/rag/schemas.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/rag/ingestion.py'
rg "context_builder|RAGPipelineConfig|context|chunks" -n factory-agent tests/rag_eval
Get-Content -Raw -LiteralPath 'factory-agent/tests/test_rag_pipeline_config.py'
Get-Content -Raw -LiteralPath 'tests/rag_eval/test_variants.py'
Get-Content -Raw -LiteralPath 'tests/rag_eval/test_run_eval_variants.py'
Get-Content -Raw -LiteralPath 'tests/rag_eval/test_artifact_schema.py'
python -m pytest -q factory-agent/tests/test_rag_context_building.py factory-agent/tests/test_rag_pipeline_config.py tests/rag_eval/test_variants.py tests/rag_eval/test_artifact_schema.py tests/rag_eval/test_run_eval_variants.py
python -m pytest -q factory-agent/tests/test_rag_generation.py
python -m pytest -q factory-agent/tests/test_rag_retrieval.py
python -m tests.rag_eval.run_eval --help
python -m json.tool tests/rag_eval/cases.json
git diff --check
git branch --show-current
git log -1 --oneline
Get-Content -Raw -LiteralPath 'tests/rag_eval/run_rag_eval.ps1'
Get-Content -Raw -LiteralPath 'factory-agent/tests/test_rag_live_llm.py'
rg "manual_evaluation|build_summary|run_eval\(" -n tests/rag_eval factory-agent/tests
rg "openai|base_url|build_.*chat_model" -n factory-agent/factory_agent tests/rag_eval
python -m pytest -q tests/rag_eval/test_scoring.py tests/rag_eval/test_judge.py tests/rag_eval/test_audit.py tests/rag_eval/test_run_eval_judge.py tests/rag_eval/test_artifact_schema.py tests/rag_eval/test_run_eval_variants.py tests/rag_eval/test_variants.py
python -m json.tool tests/rag_eval/cases.json
python -m tests.rag_eval.run_eval --help
git diff --check
git status --short
git diff --stat
python -m py_compile tests/rag_eval/scoring.py tests/rag_eval/judge.py tests/rag_eval/audit.py tests/rag_eval/run_eval.py tests/rag_eval/artifact_schema.py
git status --short
Get-Content -Raw -LiteralPath 'docs/qa/RAG_EVALUATION_PLAN.md'
Get-Content -Raw -LiteralPath 'docs/qa/RAG_EVALUATION_TRACK.md'
Get-Content -Raw -LiteralPath 'tests/rag_eval/README.md'
Get-Content -Raw -LiteralPath 'tests/rag_eval/cases.json'
Get-Content -Raw -LiteralPath 'docs/qa/rag_eval_question_bank.md'
@'<summary aggregation scripts for all 12 Run 1 summary.json files>'@ | python -
@'<serious failure and safety aggregation scripts>'@ | python -
@'<judge audit sampling and manual-review prep scripts>'@ | python -
```

## Test Results

- JSON validation passed for `tests/rag_eval/cases.json`: 50 cases, no missing required fields, no duplicate IDs, and exact 4/3/2/1 question-type mix for each registered PDF.
- `git diff --check -- tests/rag_eval/cases.json docs/qa/rag_eval_question_bank.md docs/qa/RAG_EVALUATION_TRACK.md` passed with exit code 0. Git reported LF-to-CRLF normalization warnings for touched text files, but no whitespace errors.
- No RAG harness, LLM, or application tests were run because Phase 1 is question-bank only.
- Phase 2 focused tests passed: `python -m pytest -q factory-agent/tests/test_rag_retrieval.py factory-agent/tests/test_rag_pipeline_config.py tests/rag_eval/test_variants.py tests/rag_eval/test_artifact_schema.py tests/rag_eval/test_run_eval_variants.py` returned 18 passed. Warnings were existing deprecation warnings from Swig/PyMuPDF-style imports, `pytest_asyncio`, and `datetime.utcnow()` in telemetry.
- `python -m json.tool tests/rag_eval/cases.json` parsed the question bank successfully.
- `python -m tests.rag_eval.run_eval --help` showed the new `--variant {V0,V1,V2,V3,V4,V5,V6,V7,V9,V10,V11,V12}` option without starting a benchmark.
- `git diff --check` passed with exit code 0. Git reported LF-to-CRLF normalization warnings for touched text files, but no whitespace errors.
- No live LLM run and no full 50-question benchmark were run for Phase 2.
- Phase 3 focused tests passed: `python -m pytest -q factory-agent/tests/test_rag_context_building.py factory-agent/tests/test_rag_pipeline_config.py tests/rag_eval/test_variants.py tests/rag_eval/test_artifact_schema.py tests/rag_eval/test_run_eval_variants.py` returned 16 passed. Warnings were existing Swig/PyMuPDF-style import warnings, `pytest_asyncio`, and `datetime.utcnow()` telemetry warnings.
- Additional touched-generation test passed: `python -m pytest -q factory-agent/tests/test_rag_generation.py` returned 15 passed.
- Additional touched-retrieval test passed: `python -m pytest -q factory-agent/tests/test_rag_retrieval.py` returned 10 passed.
- `python -m tests.rag_eval.run_eval --help` showed all Run 1 variant choices without starting a benchmark.
- `python -m json.tool tests/rag_eval/cases.json` parsed successfully. The cases file was not changed in Phase 3.
- `git diff --check` passed with exit code 0. Git reported LF-to-CRLF normalization warnings for touched text files, but no whitespace errors.
- No live LLM run, no scoring run, no judge run, and no full 50-question x 12-variant benchmark were run for Phase 3.
- Phase 4 focused tests passed: `python -m pytest -q tests/rag_eval/test_scoring.py tests/rag_eval/test_judge.py tests/rag_eval/test_audit.py tests/rag_eval/test_run_eval_judge.py tests/rag_eval/test_artifact_schema.py tests/rag_eval/test_run_eval_variants.py tests/rag_eval/test_variants.py` returned 20 passed. Warnings were existing Swig/PyMuPDF-style import warnings and `pytest_asyncio` configuration deprecation warnings.
- `python -m json.tool tests/rag_eval/cases.json` parsed successfully. The cases file was not changed in Phase 4.
- `python -m tests.rag_eval.run_eval --help` showed the new judge options without starting a benchmark: `--judge`, `--no-judge`, `--judge-base-url`, `--judge-model`, and `--judge-audit-seed`.
- `git diff --check` passed with exit code 0. Git reported LF-to-CRLF normalization warnings for touched text files, but no whitespace errors.
- `python -m py_compile tests/rag_eval/scoring.py tests/rag_eval/judge.py tests/rag_eval/audit.py tests/rag_eval/run_eval.py tests/rag_eval/artifact_schema.py` passed.
- No live LLM run, no live judge run, no scoring benchmark run, no Document Augmentation run, and no full 50-question x 12-variant benchmark were run for Phase 4.
- Phase 5 live benchmark completed for all 12 Run 1 variants with judge enabled: 600 case artifacts, 12 summaries, and 12 judge audit samples were written under `test-artifacts/rag-eval/`.
- Phase 5 artifact validation passed: every full run folder has exactly 50 case JSON artifacts plus `summary.json`; every judged run has `judge_audit_sample.json` with 20 sampled judged cases.
- Phase 5 judge calls completed without errors: 398 requested, 398 completed, 0 errors.
- Phase 5 smoke tests passed for `smoke-v3-score` and `smoke-v11-context`.
- Phase 6 loaded all 12 `summary.json` files and all 12 `judge_audit_sample.json` files for local analysis.
- Phase 6 manually inspected 29 judged answers from the audit samples.
- Phase 6 did not run the full benchmark, did not run live judge calls, and did not change RAG behavior.
- Phase 6.5 focused tests passed: `python -m pytest -q factory-agent/tests/test_rag_reranking.py factory-agent/tests/test_rag_pipeline_config.py factory-agent/tests/test_rag_generation.py factory-agent/tests/test_rag_context_building.py tests/rag_eval/test_scoring.py tests/rag_eval/test_artifact_schema.py tests/rag_eval/test_variants.py tests/rag_eval/test_run_eval_variants.py` returned 53 passed. Warnings were existing Swig/PyMuPDF-style import warnings, `pytest_asyncio` warnings, and telemetry `datetime.utcnow()` deprecation warnings.
- `python -m tests.rag_eval.run_eval --help` passed and showed the expected variant and judge options.
- Phase 6.5 corrected live reruns completed with `--judge` for `V1`, `V3`, `V5`, `V6`, `V7`, `V10`, `V11`, `V12`, and anchor variants `V0`, `V2`, `V4`, and `V9`.
- Phase 6.5 artifact validation passed for all corrected run folders: every folder has 50 case artifacts plus `summary.json` and `judge_audit_sample.json`; all judge-requested cases completed with 0 judge errors.
- Phase 6.5 rerank validation passed: all required rerank variants recorded 50 enabled, 50 attempted, 50 succeeded, and 0 fallback.

## Files Created

- `docs/qa/RAG_EVALUATION_PLAN.md`
- `docs/qa/RAG_EVALUATION_TRACK.md`
- `docs/qa/rag_eval_question_bank.md`
- `tests/rag_eval/variants.py`
- `tests/rag_eval/test_artifact_schema.py`
- `tests/rag_eval/test_run_eval_variants.py`
- `tests/rag_eval/test_variants.py`
- `factory-agent/factory_agent/rag/context_building.py`
- `factory-agent/tests/test_rag_context_building.py`
- `factory-agent/tests/test_rag_pipeline_config.py`
- `tests/rag_eval/scoring.py`
- `tests/rag_eval/judge.py`
- `tests/rag_eval/audit.py`
- `tests/rag_eval/test_scoring.py`
- `tests/rag_eval/test_judge.py`
- `tests/rag_eval/test_audit.py`
- `tests/rag_eval/test_run_eval_judge.py`
- `docs/qa/RAG_EVALUATION_DECISION_MEMO.md`
- `docs/qa/RAG_EVALUATION_CORRECTED_RUN_ADDENDUM.md`

## Files Updated

- `tests/rag_eval/cases.json`
- `factory-agent/factory_agent/rag/pipeline.py`
- `factory-agent/factory_agent/rag/retrieval.py`
- `factory-agent/factory_agent/rag/generation.py`
- `factory-agent/factory_agent/rag/schemas.py`
- `factory-agent/factory_agent/rag/reranking.py`
- `factory-agent/factory_agent/rag/source_metadata.py`
- `factory-agent/factory_agent/llm/models.py`
- `factory-agent/tests/test_rag_live_llm.py`
- `factory-agent/tests/test_rag_context_building.py`
- `factory-agent/tests/test_rag_generation.py`
- `factory-agent/tests/test_rag_pipeline_config.py`
- `factory-agent/tests/test_rag_retrieval.py`
- `factory-agent/tests/test_rag_reranking.py`
- `tests/rag_eval/README.md`
- `tests/rag_eval/artifact_schema.py`
- `tests/rag_eval/run_eval.py`
- `tests/rag_eval/run_rag_eval.ps1`
- `tests/rag_eval/test_artifact_schema.py`
- `tests/rag_eval/test_scoring.py`
- `tests/rag_eval/test_variants.py`
- `tests/rag_eval/variants.py`
- `docs/qa/RAG_EVALUATION_TRACK.md`
- `docs/qa/RAG_EVALUATION_DECISION_MEMO.md`

## Current Blockers

- Corrected reranker integration is fixed for Phase 6.5 artifacts, but the corrected champion `V7` still has 17 automated serious failures out of 50 and is not production-ready.
- Judge safety and citation scoring are weak enough that top Run 2 candidates require manual review.
- Automated `unsafe_advice` flags increased slightly in the corrected comparison and need manual review before production conclusions.
- Compression remains quality-negative despite focused evidence-preservation fixes.

## Next Action

Start Phase 7 only after accepting the corrected Phase 6.5 baseline: compare Document Augmentation `V8` and `V13` against the corrected top candidates, preferably `V7`, `V12`, and `V10`, with `V2` only as an optional clean control.
