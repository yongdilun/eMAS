# eMAS RAG Evaluation Run 2 Addendum

Created: 2026-05-25

## Scope

Run 2 implemented and tested indexing-time Document Augmentation for the two deferred Phase 7 variants:

- `V8`: Document Augmentation + Hybrid Search + Small-to-Big + Rerank.
- `V13`: Document Augmentation + Hybrid Search + RSE + Rerank.

The 50-question bank, expected answers, scoring rules, RSE behavior, Small-to-Big behavior, reranker behavior, and generation prompts were not changed. Augmentation was generated only from source chunk text and source metadata. It did not read `tests/rag_eval/cases.json`, `docs/qa/rag_eval_question_bank.md`, gold answers, expected answer points, or evaluation question IDs.

The augmented retrieval index uses separate generated paths:

- `factory_agent/rag/vector_db_augmented`
- `factory_agent/rag/bm25_index_augmented.pkl`

These generated paths are ignored and were not staged.

## Implementation Notes

- Added deterministic indexing-time augmentation with document title, source metadata, section title/path, `use_for`, related entities, source-derived key terms, aliases, source-grounded summary excerpts, and generated retrieval questions.
- Chroma stores augmented retrieval text for search, while retriever results are normalized back to original evidence text before rerank, context building, generation, and citations.
- BM25 indexes augmented retrieval text but returns original evidence chunks.
- Per-case artifacts now record document augmentation in `variant_config`, `retrieval_debug.retrieval_settings`, `retrieval_debug.top_chunks[*].document_augmentation`, and `rag.metadata.document_augmentation`.
- Artifact audit found augmented top chunks in 50/50 V8 cases and 50/50 V13 cases, with no synthetic augmentation text in final evidence snippets.

## Run 2 Results

All required Run 2 runs used `--judge`. Every run produced 50 case artifacts, `summary.json`, and `judge_audit_sample.json`. Judge-requested cases completed with 0 errors.

| Variant | Pipeline | Avg Rule | Serious | Borderline | Warnings | doc@3/5/10 | section/page@3/5/10 | Avg Sec | Context Tokens | Rerank Succeeded/Fallback |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | --- |
| `V12` | Query Rewrite + Hybrid + RSE + Rerank | 80.74 | 8 | 36 | 0 | 0.94 / 1.00 / 1.00 | 0.86 / 0.94 / 0.96 | 10.48 | 1053 | 50 / 0 |
| `V7` | Query Rewrite + Hybrid + Small-to-Big + Rerank | 79.87 | 9 | 35 | 0 | 0.94 / 1.00 / 1.00 | 0.86 / 0.94 / 0.96 | 6.25 | 1022 | 50 / 0 |
| `V8` | Document Augmentation + Hybrid + Small-to-Big + Rerank | 79.17 | 9 | 34 | 0 | 0.96 / 0.98 / 1.00 | 0.86 / 0.94 / 0.98 | 6.21 | 991 | 50 / 0 |
| `V10` | Hybrid + RSE + Rerank | 78.90 | 9 | 33 | 1 | 0.94 / 0.96 / 1.00 | 0.86 / 0.90 / 0.96 | 6.29 | 1085 | 50 / 0 |
| `V13` | Document Augmentation + Hybrid + RSE + Rerank | 78.13 | 10 | 34 | 0 | 0.96 / 0.98 / 1.00 | 0.86 / 0.94 / 0.98 | 6.06 | 991 | 50 / 0 |

Optional `V5` and `V2` Run 2 reruns were not run because the required comparison set was sufficient to answer the Phase 7 decision questions.

## Serious Failures

| Variant | Serious Codes | Serious Case IDs |
| --- | --- | --- |
| `V8` | `wrong_answer`: 9 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `osha-loto-df-03`, `osha-guarding-mc-02`, `nist-csf-2-ss-01`, `nist-csf-2-mc-02` |
| `V13` | `wrong_answer`: 10 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `osha-loto-df-03`, `osha-guarding-mc-02`, `nist-csf-2-df-04`, `nist-csf-2-ss-01`, `nist-csf-2-mc-02` |
| `V7` | `wrong_answer`: 8; `citation_does_not_support_answer`: 1 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `osha-loto-df-03`, `nist-csf-2-ss-01`, `nist-csf-2-ss-03`, `nist-csf-2-mc-02` |
| `V12` | `wrong_answer`: 7; `citation_does_not_support_answer`: 1 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `osha-loto-df-03`, `nist-csf-2-ss-01`, `nist-csf-2-ss-03` |
| `V10` | `wrong_answer`: 9; `wrong_or_missing_citation`: 1 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-01`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `osha-loto-df-03`, `osha-guarding-mc-02`, `nist-csf-2-ss-01` |

## Phase 7 Questions

1. Did Document Augmentation improve retrieval hit rates?

Yes, but only modestly and not uniformly. V8/V13 improved `doc_hit@3` to 0.96 versus 0.94 for V7/V12/V10, and improved `section_or_page_hit@10` to 0.98 versus 0.96 for the anchors. Against V10, V13 also improved `doc_hit@5` from 0.96 to 0.98 and `section_or_page_hit@5` from 0.90 to 0.94. Against query-rewrite anchors V7/V12, augmented variants trailed `doc_hit@5` at 0.98 versus 1.00.

2. Did it improve answer accuracy?

No. V8 trailed V7 by 0.70 average rule points with the same serious-failure count. V13 trailed V10 by 0.77 points and had one more serious failure. Neither augmented variant beat V12.

3. Did it reduce serious failures?

No. V8 matched V7 at 9 serious failures but did not reduce them. V13 had 10 serious failures versus 9 for V10 and 8 for V12.

4. Did it improve citation support?

Marginally. V8 and V13 had no citation-related serious-failure flags, while V7/V12/V10 each had one citation-related serious flag. This did not translate into better total serious-failure counts because the augmented runs still had more wrong-answer failures.

5. Did it help Small-to-Big or RSE more?

Small-to-Big benefited more. V8 scored 79.17 with 9 serious failures, while V13 scored 78.13 with 10 serious failures. Relative to their closest non-augmented comparators, V8 stayed closer to V7 than V13 stayed to V10.

6. Did it increase latency or token cost too much?

No. Augmented runtime and context size were not excessive: V8 averaged 6.21s and 991 context tokens, V13 averaged 6.06s and 991 context tokens. Both were comparable to or cheaper than the non-augmented anchors at generation time. The extra cost is ingestion complexity and a separate augmented index, not per-answer token cost.

7. Did V8 or V13 beat V7/V12/V10?

Not enough to matter. V8 beat V10 on average score by 0.27 with the same serious-failure count, but V8 did not beat V7 or V12. V13 did not beat V7, V12, or V10. The Run 2 champion is V12, not an augmented variant.

8. Should Document Augmentation be kept?

Keep the implementation as experimental eval plumbing, but do not make Document Augmentation the production default. It improved some retrieval hit rates and citation support flags, but the added indexing complexity did not improve answer accuracy or serious-failure count.

9. What remains blocking before production?

- V12 still has 8 serious failures out of 50.
- The dominant remaining failures are real wrong or incomplete answers, not retrieval absence alone.
- Hard cases need targeted manual review: A232 subactivities, resource availability/status/usage, AMS 300-11 scope/standards/interoperability cases, OSHA energy-control procedure completeness, and CSF Core/online resources summaries.
- Judge output remains triage-grade and should not be the production quality gate.
- Safety and boundary answers still require manual review before rollout.
- Phase 8 should not start until the winning config, regression cases, monitoring gates, and serious-failure remediation plan are documented.

## Decision Update

Run 2 does not support keeping Document Augmentation as a production default. It also changes the same-day top ranking back to `V12`: Query Rewrite + Hybrid Search + RSE + Rerank. `V7` remains a close co-lead, but `V12` has the best Run 2 average score and the fewest serious failures in the required comparison set.

Production rollout remains blocked.
