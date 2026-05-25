# eMAS RAG Evaluation Plan

## Purpose

This evaluation exists to choose the best production RAG setup for eMAS. It is not only a report-writing comparison. The final outcome should identify a provisional production champion, explain why it won, describe remaining risks, and define what must be tested in the second benchmark.

The evaluation optimizes for balance:

- Answer quality first.
- Speed and token cost second.
- Serious safety, citation, hallucination, and boundary-answer failures are heavily penalized.
- If Run 1 does not produce a fully reliable answer, it can still select a provisional champion and define Run 2 improvements.

## Locked Decisions

| Area | Decision |
| --- | --- |
| Main goal | Choose the best production eMAS RAG strategy |
| Winner criterion | Best balance of quality, citations, speed, and token cost |
| Quality threshold | No fixed threshold before first benchmark; decide after seeing real scores |
| Question count | 50 questions |
| Source split | 10 questions per PDF |
| Question type mix per PDF | 4 direct fact, 3 section-summary, 2 multi-chunk, 1 unanswerable/boundary |
| Question creation | Codex reads PDFs directly and manually creates grounded questions |
| Existing cases | Replace existing `tests/rag_eval/cases.json` with a fresh 50-question bank |
| Question metadata | Question, expected answer points, short gold answer, doc ID, page/section source, type, safety expectation |
| Citation strictness | Page or section level where available |
| Question style | Mixed normal-user and expert-style questions |
| eMAS mentions | No eMAS-specific application questions in Run 1; document-only questions |
| Cross-document questions | None in Run 1; each question targets one expected PDF |
| Keyword questions | Include only a few exact-term questions |
| Wording | Mostly clean English, with some messy real-user phrasing |
| Unanswerable behavior | Helpful boundary answer, not bare refusal |
| Safety warning behavior | Required for high-risk safety intent, not every OSHA mention |
| Answer length | Depends on question type |
| Run count | Run each variant once in Run 1 |
| Run order | Same 50 questions for each variant; randomize variant execution order |
| Scoring | Rule checks plus LLM judge for borderline cases |
| Run 1 judge model | Use the existing local port `900` model first: `Qwen2.5-7B-Instruct-Q4_K_M` |
| Judge reliability check | Randomly manual-check a sample of judge outputs before trusting judge scores |
| LLM judge rubric | Correctness, completeness, faithfulness, citation quality, safety, conciseness |
| Safety hard fail | Serious unsafe advice fails regardless of other scores |
| Final output | Decision memo |
| Artifacts | Save both JSON and Markdown question bank |

## Source Corpus

Run 1 uses the five registered PDFs from `rag_sources/00_metadata_templates/source_register.json`.

| Doc ID | PDF | Question Count |
| --- | --- | ---: |
| `nist_ams_300_1` | Reference Architecture for Smart Manufacturing Part 1: Functional Models | 10 |
| `nist_ams_300_11` | Recommendations for Collecting, Curating, and Re-Using Manufacturing Data | 10 |
| `osha_3120_lockout_tagout` | Control of Hazardous Energy Lockout/Tagout | 10 |
| `osha_machine_guarding_checklist` | Machine Guarding Checklist | 10 |
| `nist_csf_2_0` | The NIST Cybersecurity Framework 2.0 | 10 |

## Variant Strategy

Run 1 tests 12 variants. Document Augmentation variants are intentionally deferred to Run 2 because augmentation is an indexing-time change and should be tested after the first retrieval/context-building benchmark.

### Run 1 Variants

| ID | Pipeline | Purpose |
| --- | --- | --- |
| V0 | Basic Vector RAG | Pure baseline |
| V1 | Vector + Rerank | Isolate rerank effect without BM25 |
| V2 | Hybrid Search | BM25 + vector retrieval baseline |
| V3 | Hybrid Search + Rerank | Strong retrieval baseline |
| V4 | Hybrid Search + Small-to-Big | Parent section context effect |
| V5 | Hybrid Search + Small-to-Big + Rerank | Strong Small-to-Big candidate |
| V6 | Hybrid Search + Small-to-Big + Rerank + Light Compression | Token-saving Small-to-Big candidate |
| V7 | Query Rewrite + Hybrid Search + Small-to-Big + Rerank | Query rewrite with Small-to-Big |
| V9 | Hybrid Search + RSE | RSE context-building effect |
| V10 | Hybrid Search + RSE + Rerank | Strong RSE candidate |
| V11 | Hybrid Search + RSE + Rerank + Light Compression | Token-saving RSE candidate |
| V12 | Query Rewrite + Hybrid Search + RSE + Rerank | Query rewrite with RSE |

### Run 2 Deferred Variants

| ID | Pipeline | Run 2 Purpose |
| --- | --- | --- |
| V8 | Document Augmentation + Hybrid Search + Small-to-Big + Rerank | Test indexing-time recall improvement for Small-to-Big |
| V13 | Document Augmentation + Hybrid Search + RSE + Rerank | Test indexing-time recall improvement for RSE |

Run 2 should compare the top 2-3 Run 1 variants against V8 and V13.

## Strategy Definitions

### V0 Basic Vector RAG

V0 must be clean:

- Vector retrieval only.
- No BM25.
- No rerank.
- No context expansion.
- No compression.

### V1 Vector + Rerank

V1 isolates the effect of reranking:

```text
Vector retrieval
-> Rerank
-> Generation
```

### Hybrid Search

Hybrid Search means vector retrieval plus BM25/keyword retrieval with reciprocal rank fusion or equivalent fusion.

Important: hybrid variants must not use neighbor expansion by default. The current retriever's default neighbor expansion should be disabled unless the variant explicitly tests Small-to-Big or RSE. Otherwise V2 and V3 would already contain a hidden context-expansion behavior.

### Small-to-Big

Small-to-Big should retrieve small chunks, then return the parent section as the larger context unit.

Rules:

- The "big" context is the parent section.
- If the parent section is too long, keep the section heading and best matching spans.
- Preserve original wording when trimming long parent sections.
- Token cap: about 3,000 tokens per parent section.
- Do not combine Small-to-Big with RSE in Run 1.

### RSE: Relevant Segment Extraction

RSE is a post-retrieval context-building technique. It dynamically joins nearby relevant chunks into coherent segments.

Run 1 order:

```text
Retrieve
-> Chunk rerank
-> RSE segment building
-> Segment score/rerank
-> Optional light compression
-> Generation
```

RSE expansion rule:

- Start from top reranked chunks.
- Expand previous/next chunks only when they belong to the same `doc_id`.
- Prefer same `section_path` when available.
- Maximum window: plus/minus 2 chunks.
- Maximum segment size: about 2,000 tokens.
- Stop expansion when token budget or section boundary would be violated.

### Two-Stage Rerank

For Small-to-Big and RSE variants:

```text
Retrieve
-> Chunk rerank
-> Context expansion
-> Segment scoring/rerank
-> Generation
```

The second stage should use cheaper scoring, not another LLM reranker.

Recommended segment score:

```text
segment_score = max child rerank score + coverage bonus + metadata bonus
```

### Light Contextual Compression

Light Compression must be extractive only in Run 1.

Rules:

- No aggressive LLM summarization.
- Keep original sentences/spans.
- Preserve source order.
- Always keep section heading/context.
- Keep high keyword-overlap sentences.
- Keep semantically similar sentences where available.
- Keep neighboring evidence sentences around selected sentences.
- Target reduction: around 40-50%.
- Hard cap: about 1,500 tokens per compressed segment.

## Evaluation Question Bank

Create two files:

- `tests/rag_eval/cases.json`
- `docs/qa/rag_eval_question_bank.md`

Each question should include:

```json
{
  "id": "string",
  "doc_id": "string",
  "query": "string",
  "question_type": "direct_fact | section_summary | multi_chunk | unanswerable",
  "difficulty": "normal | expert",
  "wording_style": "clean | messy",
  "expected_answer_points": ["string"],
  "gold_answer": "short reference answer",
  "expected_source": {
    "doc_id": "string",
    "section": "string or null",
    "page": "number or null"
  },
  "expects_sources": true,
  "expects_safety_warning": false,
  "unanswerable_reason": "string or null",
  "serious_failure_modes": ["string"]
}
```

Per PDF:

| Question Type | Count |
| --- | ---: |
| Direct fact | 4 |
| Section-summary | 3 |
| Multi-chunk | 2 |
| Unanswerable/boundary | 1 |
| Total | 10 |

## Unanswerable Questions

Each PDF gets one unanswerable or boundary question. Across the full bank, include a mix:

- Outside-document facts.
- Live/current status questions.
- Unsupported vendor, legal, compliance, or approval questions.

Expected behavior:

```text
The answer should explain that the provided sources do not support the requested claim/action,
then briefly say what the sources can support instead.
```

Example:

```text
The OSHA guide does not provide live lockout status for a specific machine. It only explains general lockout/tagout procedures. Check the live maintenance system or an authorized safety person for current machine status.
```

## Scoring Design

Run 1 uses rule scoring first, then LLM judge scoring for borderline cases.

### Run 1 Judge Model

Run 1 should use the same local OpenAI-compatible model already used by the planner server:

```text
http://127.0.0.1:900/v1
Qwen2.5-7B-Instruct-Q4_K_M
```

This is a practical pilot judge, not the final gold-standard judge. The judge should only handle borderline cases and should return strict JSON. Recommended settings:

```text
temperature = 0
top_p = 1
judge_scope = borderline cases only
```

Because this is a 7B quantized model, its scores must be treated as triage signals. Final production decisions still require manual review of serious failures, safety questions, and top candidate variants.

### Rule-Based Checks

Rule checks should cover:

- Answer is non-empty.
- Expected `doc_id` is cited for answerable questions.
- Expected page or section is cited when available.
- Required answer points are present or partially present.
- Safety warning is present when high-risk safety intent requires it.
- Unanswerable questions produce a helpful boundary answer.
- Latency is recorded.
- Token/context size is recorded.

### Borderline Cases

A case is borderline when the rule score is not clearly pass or fail.

Recommended definition:

```text
rule score between 60% and 80%
OR expected doc is cited but answer points are partial
OR answer seems correct but uses different wording
OR source doc is correct but page/section is unclear
OR safety answer is mostly correct but warning strength is unclear
```

### LLM Judge Rubric

LLM judge should score 1-5 for:

- Correctness.
- Completeness.
- Faithfulness.
- Citation quality.
- Safety.
- Conciseness.

For safety-sensitive questions, serious unsafe advice is a hard fail regardless of numeric score.

### Judge Reliability Audit

Before using LLM judge scores in the final decision memo, manually audit a random sample of judged cases.

Recommended sample:

- At least 20 judged answers, or 10% of judged answers, whichever is larger.
- Include pass, fail, and borderline outputs.
- Include at least 5 safety-related answers if available.
- Include at least 5 citation-sensitive answers if available.
- Include answers from at least 3 different variants.

Manual audit should compare:

- Whether the judge score matches human judgment.
- Whether the judge missed unsupported claims.
- Whether the judge accepted weak or wrong citations.
- Whether the judge was too harsh on valid paraphrases.
- Whether the judge handled safety warnings correctly.

Recommended acceptance rule:

```text
If judge-human agreement is good enough for triage, use judge scores as supporting evidence.
If judge-human agreement is weak, use judge output only as notes and rely on manual review for top variants.
```

The decision memo must report judge reliability, even if the result is only qualitative.

### Serious Failures

Serious failures include:

- Wrong answer.
- Wrong or missing citation for answerable factual/procedural questions.
- Citation does not support the answer.
- Unsafe safety advice.
- Hallucinated unsupported claim.
- Failure to provide a boundary answer for unanswerable questions.

Missing citation is serious for answerable factual/procedural questions, but not always serious for unanswerable boundary answers if the answer clearly states that the sources do not contain enough information.

## Retrieval Metrics

Measure retrieval quality separately from final answer quality.

Record:

- `doc_hit@3`
- `doc_hit@5`
- `doc_hit@10`
- `section_or_page_hit@3`
- `section_or_page_hit@5`
- `section_or_page_hit@10`

This makes it easier to diagnose whether a failure came from retrieval, context building, reranking, compression, or generation.

## Runtime Metrics

Record for every case and variant:

- Latency.
- Retrieved chunk count.
- Context token estimate before expansion.
- Context token estimate after expansion.
- Context token estimate after compression.
- Final prompt/context token estimate where available.
- Answer token estimate where available.

Quality remains the first decision filter, but speed and token cost decide between otherwise strong candidates.

## Phased Implementation Plan

### Phase 0: Confirm Baseline Harness Shape

Goal: understand the current RAG harness and identify the minimum changes needed for variant execution.

Tasks:

- Review current `tests/rag_eval/run_eval.py`.
- Review current `factory_agent.rag.pipeline`.
- Review current `factory_agent.rag.retrieval`.
- Confirm how citations expose `doc_id`, `page`, `section_title`, and `section_path`.
- Confirm whether existing ingestion already stores enough metadata for page/section checking.

Exit criteria:

- List of required harness changes is known.
- No question bank work starts until citation metadata is confirmed.

### Phase 1: Read PDFs And Build Question Bank

Goal: create a fresh 50-question benchmark grounded in the actual PDFs.

Tasks:

- Read each registered PDF.
- Create 10 grounded questions per PDF.
- Include expected answer points, short gold answer, expected doc ID, page/section source, safety expectation, and serious failure modes.
- Save machine-readable cases to `tests/rag_eval/cases.json`.
- Save human-readable bank to `docs/qa/rag_eval_question_bank.md`.
- Replace existing cases rather than extending them.

Exit criteria:

- 50 questions exist.
- Every question has source grounding.
- Every PDF has the required 4/3/2/1 question-type mix.

### Phase 2: Add Variant Configuration

Goal: make the harness able to run Run 1 variants cleanly.

Tasks:

- Add a variant registry for V0-V7 and V9-V12.
- Add toggles for vector-only retrieval, hybrid retrieval, rerank, query rewrite, Small-to-Big, RSE, and extractive compression.
- Disable default neighbor expansion except in explicit expansion variants.
- Make run artifacts include variant ID and pipeline configuration.
- Randomize variant execution order while using the same 50 questions for each variant.

Exit criteria:

- Harness can run a selected variant.
- Variant config is written into every artifact.
- V0 and V1 are clean and do not accidentally use hybrid retrieval or expansion.

### Phase 3: Implement Context-Building Strategies

Goal: implement Small-to-Big, RSE, and light compression in a way that keeps the comparison clean.

Tasks:

- Implement parent-section expansion for Small-to-Big.
- Implement long-section handling with heading plus best matching spans.
- Implement RSE with same-doc, same-section preference, plus/minus 2 window, and 2,000-token cap.
- Implement cheap segment scoring after expansion.
- Implement extractive compression with heading preservation, keyword/semantic selection, neighbor evidence sentences, 40-50% target reduction, and 1,500-token cap.

Exit criteria:

- Small-to-Big and RSE do not run together.
- Compression is extractive only.
- Artifacts expose pre/post expansion and compression context sizes.

### Phase 4: Add Scoring

Goal: produce useful automated diagnostics before manual review.

Tasks:

- Add rule scoring for answer points, source match, page/section match, safety warning, boundary behavior, and structural checks.
- Add borderline-case detection.
- Add optional LLM judge for borderline cases.
- Configure the Run 1 judge to use the existing local `Qwen2.5-7B-Instruct-Q4_K_M` server on port `900`.
- Add a random judge-reliability sample export for manual review.
- Add serious-failure classification.
- Aggregate scores per variant.

Exit criteria:

- Each answer gets rule-check results.
- Borderline answers are flagged.
- LLM judge outputs can be sampled and manually audited.
- Serious failures are visible in summary output.

### Phase 5: Run Benchmark 1

Goal: run the first production strategy benchmark.

Run 1 scope:

- 50 questions.
- 12 variants.
- One run per variant.
- Same question set for every variant.
- Randomized variant run order.

Tasks:

- Re-run ingestion before benchmark.
- Run all V0-V7 and V9-V12 variants.
- Write artifacts under `test-artifacts/rag-eval/<run_id>/`.
- Generate run-level summary with retrieval metrics, answer metrics, serious failures, latency, and token estimates.

Exit criteria:

- 600 answer artifacts exist.
- Summary ranks variants.
- Failures are traceable to retrieval, context building, compression, or generation.

### Phase 6: Review And Decision Memo

Goal: choose a provisional champion and explain the tradeoffs.

Tasks:

- Review all automated failures.
- Review all borderline cases.
- Review top 2-3 variants manually.
- Review all safety-sensitive failures.
- Produce a decision memo with:
  - provisional champion,
  - runner-up,
  - score table,
  - retrieval quality table,
  - latency/token table,
  - judge reliability audit summary,
  - serious failure list,
  - production risks,
  - recommended Run 2 changes.

Exit criteria:

- A provisional production candidate is selected.
- Run 2 scope is clear.
- If no candidate is safe enough, the memo says so directly and explains blockers.

### Phase 6.5: Fairness Fix And Corrected Rerun

Goal: fix benchmark defects that made Run 1 unfair or hard to interpret, then rerun the affected comparison set before Document Augmentation is tested.

This phase exists because Run 1 can identify promising candidates but should not be treated as the final fair comparison if core evaluation infrastructure was degraded. In particular, rerank-enabled variants must not be compared as true reranker variants when the reranker fell back to initial boosted scores.

Scope rules:

- Fix benchmark or pipeline defects that distort the comparison.
- Do not change the 50-question bank to make results easier.
- Do not tune prompts or expected answers to favor a variant.
- Do not implement Document Augmentation V8/V13.
- Do not change the production winner based only on Phase 6.5; use it to produce a corrected Run 1 baseline for Phase 7.

Tasks:

- Fix or replace the reranker integration so V1, V3, V5, V6, V7, V10, V11, and V12 really use the intended rerank stage.
- Add a focused proof that rerank-enabled variants call a working reranker and do not silently fall back unless explicitly configured to do so.
- Improve citation support in artifacts where needed so answer claims can be tied to supporting chunks, pages, and sections more fairly.
- Improve high-risk safety and boundary-answer contracts so OSHA/live-status questions require concrete cautions and safe next steps.
- Audit extractive compression to confirm V6/V11 quality loss is real, not caused by accidental removal of required evidence.
- Keep scoring strict; do not loosen `citation_does_not_support_answer` or serious-failure rules just to raise scores.
- Rerun a corrected benchmark subset:
  - Required: V1, V3, V5, V6, V7, V10, V11, V12.
  - Recommended anchors: V0, V2, V4, V9.
- Compare corrected results against Run 1 and explain what changed.

Exit criteria:

- Reranker behavior is fixed, replaced, or explicitly downgraded with a documented reason.
- Corrected artifacts exist for all affected rerank variants.
- Any citation/safety contract fixes are covered by focused tests.
- A short corrected-run addendum explains whether the provisional champion changes.
- Phase 7 has a fairer baseline for comparing Document Augmentation.

### Phase 6.6: Scoring Fairness Audit And Top-Candidate Rerun

Goal: correct narrow scoring defects found during manual review of the Phase 6.5 top variants, then rerun the decision-sensitive candidate set before Phase 7.

This phase exists because Phase 6.5 fixed the reranker comparison, but manual review found that the automated serious-failure count was still inflated by evaluation defects. The benchmark should remain strict, but strictness must distinguish unsupported answers from noisy PDF section labels and safety-regex false positives.

Scope rules:

- Do not change the 50-question bank.
- Do not tune prompts, expected answer points, or gold answers.
- Do not change RAG retrieval, reranking, context building, compression, or generation behavior unless a scoring artifact proves the comparison is otherwise invalid.
- Do not implement Document Augmentation `V8`/`V13`.
- Keep serious failures strict for wrong answers, wrong/missing expected-document citations, true unsupported citations, unsafe advice, hallucinated boundary claims, and failed boundary answers.

Tasks:

- Treat page-or-section support as the strict citation locator standard when both page and section metadata exist. A noisy extracted section label should not create `citation_does_not_support_answer` when the expected page/evidence support is present.
- Keep citation hard failures when the expected document is cited but neither expected page nor expected section support is hit.
- Tighten unsafe-advice pattern matching so checklist text about `safeguard` is not treated as permission to bypass or remove a guard.
- Add focused tests for the citation and unsafe-pattern edge cases.
- Rerun or rescore the decision-sensitive top set:
  - `V7`
  - `V12`
  - `V10`
  - `V5`
  - `V2`
- Compare Phase 6.6 results against Phase 6.5 and record whether the champion, Phase 7 candidate set, serious-failure count, and reranker-vs-anchor conclusion changed.

Exit criteria:

- Focused scoring tests pass.
- Top-candidate artifacts or rescored summaries exist for the Phase 6.6 candidate set.
- A Phase 6.6 addendum records the corrected result table and interpretation.
- Phase 7 starts only after the Phase 6.6 fairness baseline is accepted.

### Phase 7: Benchmark Run 2 With Document Augmentation

Goal: test whether indexing-time document augmentation improves the best corrected Run 1 result after Phase 6.5/6.6.

Run 2 scope:

- Top 2-3 variants from the corrected Run 1 / Phase 6.5 result.
- V8 Document Augmentation + Hybrid Search + Small-to-Big + Rerank.
- V13 Document Augmentation + Hybrid Search + RSE + Rerank.

Tasks:

- Design document augmentation fields: generated questions, summaries, titles, or metadata.
- Re-ingest augmented corpus.
- Run the selected Run 2 variant set.
- Compare Run 2 against Run 1 champion.

Exit criteria:

- It is clear whether document augmentation is worth the ingestion complexity.
- Final champion can be confirmed or updated.

### Phase 8: Production Rollout Recommendation

Goal: turn benchmark results into implementation guidance.

Tasks:

- Freeze the winning pipeline config.
- Document default token caps and safety behavior.
- Add regression cases from the evaluation bank.
- Define what should be monitored in production: no-source answers, safety warnings, latency, token cost, and retrieval misses.

Exit criteria:

- Production RAG strategy is documented.
- Follow-up implementation tasks are known.

## Open Implementation Questions

These should be resolved while implementing the harness:

- Whether current citation objects expose page and section strongly enough for section/page scoring.
- Whether token estimates should use the current heuristic or model tokenizer.
- Whether semantic sentence selection for compression can reuse existing embeddings cheaply.
- Whether query rewrite should be LLM-based or deterministic for Run 1.
- Whether Run 2 should upgrade the judge to a stronger model such as Qwen3 14B after the Run 1 reliability audit.
