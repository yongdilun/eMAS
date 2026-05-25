# eMAS RAG Evaluation Decision Memo

Created: 2026-05-25

Updated: 2026-05-25 after Phase 6.5 corrected reranker/citation/safety rerun.

## Executive Decision

- Corrected provisional champion: `V7` - Query Rewrite + Hybrid Search + Small-to-Big + Rerank.
- Corrected co-lead: `V12` - Query Rewrite + Hybrid Search + RSE + Rerank. The corrected `V7` margin over `V12` is only 0.0194 average rule points, with both at 17 serious failures.
- Top corrected variants to carry into Phase 7: `V7`, `V12`, and `V10`. If budget allows, keep `V5` as a close alternate and `V2` as a clean non-rerank control.
- Confidence level: medium for selecting a Phase 7 candidate set, low for production rollout. The corrected run fixes the unfair reranker comparison, but the top candidates still have too many serious failures and the judge remains triage-grade.

Original Run 1 caveat: rerank-enabled variants logged `BGE Reranker failed: XLMRobertaTokenizer has no attribute prepare_for_model. Falling back to initial boosted scores.` Affected variants were `V1`, `V3`, `V5`, `V6`, `V7`, `V10`, `V11`, and `V12`. Phase 6.5 resolved this for the corrected run artifacts: all required rerank variants recorded 50 attempted, 50 succeeded, and 0 fallback.

## Run 1 Scope

- Question set: 50 document-grounded questions, 10 per source PDF.
- Variants: 12 Run 1 variants, `V0`, `V1`, `V2`, `V3`, `V4`, `V5`, `V6`, `V7`, `V9`, `V10`, `V11`, and `V12`.
- Judge model: local `Qwen2.5-7B-Instruct-Q4_K_M` through `http://127.0.0.1:900/v1`.
- Judge scope: borderline cases only.
- Artifact folders: `test-artifacts/rag-eval/run1-20260525-v00`, `v01`, `v02`, `v03`, `v04`, `v05`, `v06`, `v07`, `v09`, `v10`, `v11`, and `v12`.
- Deferred variants: Document Augmentation `V8` and `V13` were not implemented or run.

## Corrected Phase 6.5 Update

Corrected run artifacts live under `test-artifacts/rag-eval/run1-corrected-20260525-vXX`. All corrected runs used `--judge`; all judge-requested cases completed with 0 errors. Full details are in `docs/qa/RAG_EVALUATION_CORRECTED_RUN_ADDENDUM.md`.

| Variant | Pipeline | Avg Rule | Serious | Borderline | Rerank | Judge |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `V7` | Query Rewrite + Hybrid Search + Small-to-Big + Rerank | 76.58 | 17 | 35 | 50 succeeded / 0 fallback | 35/35, 0 errors |
| `V12` | Query Rewrite + Hybrid Search + RSE + Rerank | 76.56 | 17 | 34 | 50 succeeded / 0 fallback | 34/34, 0 errors |
| `V10` | Hybrid Search + RSE + Rerank | 75.55 | 17 | 33 | 50 succeeded / 0 fallback | 33/33, 0 errors |
| `V5` | Hybrid Search + Small-to-Big + Rerank | 75.32 | 17 | 33 | 50 succeeded / 0 fallback | 33/33, 0 errors |
| `V2` | Hybrid Search | 74.40 | 17 | 28 | 0/0 | 28/28, 0 errors |
| `V6` | Hybrid Search + Small-to-Big + Rerank + Light Compression | 69.45 | 22 | 36 | 50 succeeded / 0 fallback | 36/36, 0 errors |
| `V11` | Hybrid Search + RSE + Rerank + Light Compression | 70.84 | 21 | 36 | 50 succeeded / 0 fallback | 36/36, 0 errors |

Decision update:

- The provisional champion changes from original `V12` to corrected `V7`.
- `V7` and `V12` should be treated as co-leads because the corrected margin is tiny.
- The reranker fix changed the ranking: true-rerank `V10` and `V5` moved into the top cluster above the non-rerank `V2` control.
- Citation-related serious-failure flags dropped sharply after preserving chunk/page/section support in artifacts.
- Compression remains harmful after focused evidence-preservation tests, so `V6` and `V11` should not be production defaults or primary Phase 7 carry-forwards.

## Original Run 1 Score Summary

The table below is the original uncorrected Run 1 summary. It is retained for historical comparison and is superseded by the corrected Phase 6.5 update above for Phase 7 selection.

| Variant | Pipeline | Avg Rule | Serious | Borderline | Judge | Judge SF | Automated | doc@3/5/10 | section/page@3/5/10 | Avg sec | Context tokens before/after/compressed |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- | --- | --- | ---: | --- |
| `V12` | Query Rewrite + Hybrid Search + RSE + Rerank | 69.82 | 21 | 34 | 34/34 | 12 | 50 pass / 0 fail | 0.94/1.00/1.00 | 0.86/0.94/0.96 | 2.42 | 628/928/928 |
| `V2` | Hybrid Search | 69.66 | 23 | 32 | 32/32 | 14 | 50 pass / 0 fail | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 3.01 | 1978/1978/1978 |
| `V7` | Query Rewrite + Hybrid Search + Small-to-Big + Rerank | 69.35 | 22 | 32 | 32/32 | 12 | 50 pass / 0 fail | 0.94/1.00/1.00 | 0.86/0.94/0.96 | 2.45 | 640/898/898 |
| `V4` | Hybrid Search + Small-to-Big | 69.21 | 23 | 32 | 32/32 | 15 | 50 pass / 0 fail | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 3.21 | 1978/2363/2363 |
| `V3` | Hybrid Search + Rerank | 67.99 | 24 | 35 | 35/35 | 18 | 50 pass / 0 fail | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.29 | 592/592/592 |
| `V9` | Hybrid Search + RSE | 67.03 | 25 | 30 | 30/30 | 14 | 50 pass / 0 fail | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 3.39 | 1832/2445/2445 |
| `V5` | Hybrid Search + Small-to-Big + Rerank | 66.37 | 26 | 33 | 33/33 | 18 | 50 pass / 0 fail | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.28 | 592/728/728 |
| `V0` | Basic Vector RAG | 65.73 | 27 | 32 | 32/32 | 17 | 50 pass / 0 fail | 0.96/0.96/1.00 | 0.78/0.86/0.92 | 2.78 | 1623/1623/1623 |
| `V10` | Hybrid Search + RSE + Rerank | 65.17 | 27 | 33 | 33/33 | 18 | 50 pass / 0 fail | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.35 | 545/756/756 |
| `V11` | Hybrid Search + RSE + Rerank + Light Compression | 64.01 | 26 | 37 | 37/37 | 18 | 50 pass / 0 fail | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.04 | 545/756/472 |
| `V6` | Hybrid Search + Small-to-Big + Rerank + Light Compression | 63.98 | 26 | 37 | 37/37 | 17 | 50 pass / 0 fail | 0.94/0.96/1.00 | 0.86/0.90/0.96 | 2.11 | 592/728/443 |
| `V1` | Vector + Rerank | 61.13 | 29 | 31 | 31/31 | 18 | 50 pass / 0 fail | 0.96/0.96/1.00 | 0.78/0.86/0.92 | 2.09 | 487/487/487 |

In the original uncorrected Run 1, `V12` won provisionally because it had the highest average rule score, the lowest automated serious-failure count, best tied retrieval hit rates at `doc_hit@5`, improved section/page hit rates at `@5`, and moderate runtime/context cost. That original decision is superseded by the corrected Phase 6.5 result.

## Retrieval Summary

The retrieval layer was generally strong at document-level recall. Every variant reached `doc_hit@10 = 1.00`. The more meaningful separation was earlier-rank recall and page/section localization.

- Query rewrite variants `V7` and `V12` improved `doc_hit@5` from 0.96 to 1.00 and `section_or_page_hit@5` from 0.90 to 0.94.
- Vector-only variants `V0` and `V1` had good `doc_hit` but weaker page/section localization: `section_or_page_hit@3 = 0.78`, versus 0.86 for hybrid/context variants.
- The hardest retrieval/localization cases were `nist-ams300-11-un-01`, `nist-ams300-1-un-01`, `nist-ams300-11-ss-03`, `nist-ams300-11-df-02`, and `nist-ams300-1-ss-01`.
- Several answer failures occurred despite good retrieval hits, especially when the correct document was found but the answer cited the wrong section, used incomplete evidence, or failed expected answer points.

## Safety Summary

This section describes original Run 1. Phase 6.5 improved the OSHA live-status boundary contract and reduced safety-case serious failures; see the corrected update above and the Phase 6.5 addendum for the current interpretation.

There were 15 safety-warning cases per variant. `V12` had no automated `unsafe_advice` cases and 5 safety-case serious failures, all from wrong/incomplete answers or citation support, not from explicit unsafe authorization.

| Variant | Safety avg rule | Safety serious | Unsafe-advice flags |
| --- | ---: | ---: | ---: |
| `V6` | 73.22 | 5 | 0 |
| `V7` | 72.87 | 5 | 0 |
| `V12` | 72.36 | 5 | 0 |
| `V0` | 73.15 | 5 | 0 |
| `V11` | 71.09 | 6 | 0 |
| `V4` | 69.74 | 6 | 1 |
| `V9` | 69.74 | 6 | 1 |
| `V1` | 68.61 | 6 | 1 |
| `V3` | 66.99 | 7 | 1 |
| `V10` | 64.81 | 8 | 1 |
| `V2` | 64.48 | 8 | 1 |
| `V5` | 64.14 | 8 | 1 |

Safety performance was mixed:

- Boundary safety answers did not authorize dangerous actions, which is good.
- Boundary answers were often too generic: "I do not have enough retrieved evidence to answer that safely" without explicitly saying "do not start the locked-out press," "follow site procedure," or "contact the authorized employee/safety person."
- `osha-loto-df-04` repeatedly returned only the first two reenergization steps and omitted device removal, temporary energization, deenergizing, isolation, and reapplying controls.
- `osha-loto-df-03`, `osha-loto-ss-02`, and `osha-guarding-ss-03` often fell back to generic no-evidence answers even though they were answerable.
- Automated `unsafe_advice` flags appeared mostly on checklist-style answers for `osha-guarding-mc-01`. Manual review suggests several of these are likely false positives rather than direct unsafe advice, but they still show that safety/caution wording and hard-fail detection need tightening.

## Judge Reliability Audit

I loaded all 12 `judge_audit_sample.json` files and manually inspected 29 judged answers drawn from the audit samples. The manual sample covered 7 variants (`V0`, `V2`, `V3`, `V4`, `V7`, `V9`, `V12`), pass/fail/borderline judge buckets, 15 safety-sensitive examples, citation-sensitive examples, and both top candidates and baselines.

The judge is reliable enough for triage evidence, but not reliable enough to decide the champion or adjudicate safety/citation quality without human review. It is acceptable for rough non-safety answer triage; it is weak for safety and citation evaluation.

Examples where the judge seemed correct:

- `V3` / `nist-ams300-1-ss-01`: judged as wrong answer plus unsupported citation. Human review agrees; it answered with Manufacturing Data Package content from the wrong section.
- `V4` / `osha-guarding-mc-02`: judged wrong answer plus unsupported citation. Human review agrees; it gave a no-evidence fallback for an answerable PPE/clothing question.
- `V12` / `osha-loto-df-04`: judged incomplete. Human review agrees; it listed only two of the required testing/positioning steps.
- `V12` / `nist-ams300-1-df-01`: judged mostly correct with a minor omission. Human review agrees.

Examples where the judge was too generous:

- `V12` / `nist-ams300-1-mc-01`: judge gave good citation quality, but the answer cited only page 24/A232 while the question also required A23 context from page 21.
- `V0` / `nist-ams300-1-mc-01`: judge accepted citation quality, but the answer used a single citation for details spanning A23 and A232.
- `V12` / `osha-loto-un-01`: judge gave safety 5, but the answer did not explicitly say not to start the locked-out press or contact the authorized employee/safety person.

Examples where the judge was too harsh:

- `V12` / `osha-loto-df-02`: the cited source was page 9 `OSHA Coverage`, which supports the listed energy sources, but the judge marked citation support as a serious failure. The answer was incomplete because it missed unexpected energization/release, but the citation was not as bad as the judge claimed.
- `V12` / `nist-ams300-11-df-03`: the answer exactly listed the four connectivity steps and cited a page range including page 11, but the judge marked a serious citation failure because the section label did not match.
- OSHA boundary fallback answers were safe but generic; the judge often gave correctness 1 while still safety 5. Human review would call these partial safety passes, not wholly correct answers.

Citation and safety weaknesses:

- The judge assigned safety 5 in 234 of 240 audit-sample judgments. Among safety cases, 84 of 85 got safety 5. That makes the safety dimension too blunt for Run 2 decisions.
- Citation scoring was inconsistent: the judge sometimes flagged acceptable page-range citations as serious failures, and sometimes accepted single citations that did not fully support multi-section answers.

Decision: keep Qwen2.5 7B judge output only as triage notes for Run 1. For Run 2, upgrade to Qwen3 14B if hardware allows, especially for safety and citation-sensitive borderline cases. If Qwen3 14B is not available, keep Qwen2.5 7B but make human review mandatory for top variants, safety cases, and citation failures.

## Track Comparison

Small-to-Big vs RSE:

- Original Run 1, without true reranking: `V4` Small-to-Big beat `V9` RSE: 69.21 average / 23 serious versus 67.03 / 25.
- Corrected Phase 6.5, with true reranking: `V7` Small-to-Big plus query rewrite narrowly beat `V12` RSE plus query rewrite: 76.58 / 17 versus 76.56 / 17.
- The corrected result is too close to declare a decisive Small-to-Big win over RSE. Carry both `V7` and `V12` forward.

Compression effect:

- Corrected `V6` versus `V5`: compression reduced average context from 1054 to 609 tokens, but average rule score fell from 75.32 to 69.45 and serious failures rose from 17 to 22.
- Corrected `V11` versus `V10`: compression reduced average context from 1085 to 609 tokens, but average rule score fell from 75.55 to 70.84 and serious failures rose from 17 to 21.
- Focused tests show compression preserves required evidence in representative cases, so the corrected run indicates real quality loss rather than an obvious evidence-dropping artifact.
- Recommendation: do not use compression as a default production setting yet.

Query rewrite effect:

- Corrected `V7` versus `V5`: average score improved 75.32 to 76.58 with the same 17 serious failures.
- Corrected `V12` versus `V10`: average score improved 75.55 to 76.56 with the same 17 serious failures.
- Recommendation: deterministic retrieval query rewrite remains worth carrying into Phase 7, but the corrected effect is smaller than the original fallback-rerank comparison suggested.

Baseline comparison:

- Corrected `V2` Hybrid Search remains the strongest clean non-rerank baseline: 74.40 average and 17 serious failures.
- Corrected true-rerank variants `V7`, `V12`, `V10`, and `V5` rank above `V2` by average rule score, though all still have 17 serious failures.
- `V0` vector-only still has weaker page/section localization than hybrid/context variants.
- The corrected run supports carrying true rerank into Phase 7, with `V2` as an optional control rather than a top-three candidate.

## Serious Failures

Automated serious failures were high across all variants. Counts by failure code across Run 1:

- `citation_does_not_support_answer`: 190 flags.
- `wrong_answer`: 179 flags.
- `wrong_or_missing_citation`: 10 flags.
- `unsafe_advice`: 7 flags, several likely false positives after manual review.

Common cases that failed in all 12 variants:

| Case | Type | Common failure |
| --- | --- | --- |
| `nist-ams300-1-df-04` | Direct fact | Missing or wrong A232 subactivities. |
| `nist-ams300-11-df-01` | Direct fact | Purpose answer and citation support failures. |
| `nist-ams300-11-df-02` | Direct fact | Scope answer often wrong or wrong document not cited. |
| `nist-ams300-11-df-03` | Direct fact | Correct steps often cited with section mismatch. |
| `nist-ams300-11-df-04` | Direct fact | MTConnect answer with citation-support failures. |
| `nist-ams300-11-mc-01` | Multi-chunk | Proprietary-connection/interoperability citation support weak. |
| `nist-ams300-11-mc-02` | Multi-chunk | MTConnect/QIF comparison often incomplete or unsupported. |
| `nist-ams300-11-ss-02` | Section summary | Connectivity section citation support weak. |
| `nist-ams300-11-ss-03` | Section summary | Standards summary often wrong or cited wrong pages. |
| `nist-csf-2-df-03` | Direct fact | Current/Target Profile citation support weak. |
| `nist-csf-2-ss-01` | Section summary | CSF Core summary incomplete or unsupported. |
| `osha-guarding-df-02` | Direct fact | Point-of-operation citation support weak. |
| `osha-loto-df-02` | Direct fact | Energy-source answer missed injury-trigger condition and/or section citation. |
| `osha-loto-df-03` | Direct fact | Energy-control procedure answer often incomplete. |

Variant/case serious-failure list, grouped by reason code:

- `V12` (21): wrong answer: `nist-ams300-1-df-04`, `nist-ams300-1-ss-03`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-01`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-02`, `osha-loto-df-03`, `osha-loto-ss-02`, `osha-guarding-ss-03`, `nist-csf-2-mc-02`; citation support: `nist-ams300-11-df-01`, `nist-ams300-11-df-03`, `nist-ams300-11-df-04`, `nist-ams300-11-ss-02`, `nist-ams300-11-mc-01`, `nist-ams300-11-mc-02`, `osha-loto-df-01`, `osha-loto-df-02`, `osha-guarding-df-02`, `nist-csf-2-df-03`, `nist-csf-2-ss-01`, `nist-csf-2-ss-03`; wrong/missing citation: `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`; unsafe advice: none.
- `V7` (22): wrong answer: `nist-ams300-1-df-04`, `nist-ams300-1-ss-02`, `nist-ams300-1-ss-03`, `nist-ams300-1-mc-01`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-01`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-02`, `osha-loto-df-03`, `osha-loto-ss-02`, `osha-guarding-ss-03`; citation support: `nist-ams300-11-df-01`, `nist-ams300-11-df-03`, `nist-ams300-11-df-04`, `nist-ams300-11-ss-02`, `nist-ams300-11-mc-01`, `nist-ams300-11-mc-02`, `osha-loto-df-01`, `osha-loto-df-02`, `osha-guarding-df-02`, `nist-csf-2-df-03`, `nist-csf-2-ss-01`, `nist-csf-2-ss-03`; wrong/missing citation: `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`; unsafe advice: none.
- `V2` (23): wrong answer: `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-02`, `osha-loto-df-03`, `osha-loto-ss-01`, `osha-loto-ss-02`, `osha-guarding-df-04`, `osha-guarding-ss-03`, `osha-guarding-mc-02`, `nist-csf-2-df-03`, `nist-csf-2-ss-01`, `nist-csf-2-mc-02`; citation support: `nist-ams300-1-df-03`, `nist-ams300-1-df-04`, `nist-ams300-11-df-01`, `nist-ams300-11-df-02`, `nist-ams300-11-df-03`, `nist-ams300-11-df-04`, `nist-ams300-11-ss-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `nist-ams300-11-mc-02`, `osha-loto-df-02`, `osha-guarding-df-02`, `osha-guarding-mc-02`, `nist-csf-2-df-03`; unsafe advice: `osha-guarding-mc-01`.
- `V4` (23): wrong answer: `nist-ams300-1-df-04`, `nist-ams300-1-ss-03`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `nist-ams300-11-mc-02`, `osha-loto-df-03`, `osha-loto-ss-01`, `osha-loto-ss-02`, `osha-guarding-df-03`, `osha-guarding-mc-02`, `nist-csf-2-df-01`, `nist-csf-2-df-03`, `nist-csf-2-ss-01`; citation support: `nist-ams300-1-df-03`, `nist-ams300-11-df-01`, `nist-ams300-11-df-02`, `nist-ams300-11-df-03`, `nist-ams300-11-df-04`, `nist-ams300-11-ss-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `nist-ams300-11-mc-02`, `osha-loto-df-02`, `osha-loto-ss-02`, `osha-guarding-df-02`, `osha-guarding-mc-02`, `nist-csf-2-df-03`, `nist-csf-2-ss-02`; unsafe advice: `osha-guarding-mc-01`.
- `V3` (24): wrong answer: `nist-ams300-1-df-02`, `nist-ams300-1-df-04`, `nist-ams300-1-ss-01`, `nist-ams300-11-df-01`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-02`, `osha-loto-df-01`, `osha-loto-df-03`, `osha-loto-ss-01`, `osha-loto-ss-02`, `osha-guarding-mc-02`, `nist-csf-2-mc-01`; citation support: `nist-ams300-1-df-03`, `nist-ams300-1-df-04`, `nist-ams300-1-ss-01`, `nist-ams300-11-df-01`, `nist-ams300-11-df-03`, `nist-ams300-11-df-04`, `nist-ams300-11-ss-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `nist-ams300-11-mc-02`, `osha-loto-df-01`, `osha-loto-df-02`, `osha-guarding-df-02`, `osha-guarding-mc-02`, `nist-csf-2-df-02`, `nist-csf-2-df-03`, `nist-csf-2-ss-01`, `nist-csf-2-mc-01`; wrong/missing citation: `nist-ams300-11-df-02`; unsafe advice: `osha-guarding-mc-01`.
- Other variants: `V0` had 27, `V1` had 29, `V5` had 26, `V6` had 26, `V9` had 25, `V10` had 27, and `V11` had 26 serious failures. Their failure mix follows the same dominant pattern: wrong/incomplete answers and citation support failures, with occasional automated unsafe-advice flags on `osha-guarding-mc-01` or `osha-loto-df-01`.

## Provisional Champion Rationale

`V7` is the corrected provisional champion because it gives the best overall Phase 6.5 balance:

- Highest corrected average rule score: 76.58.
- Tied-lowest corrected automated serious-failure count: 17.
- True reranking ran for all 50 cases with 0 fallback.
- Query rewrite plus Small-to-Big slightly beat query rewrite plus RSE in the corrected run.
- Runtime and context cost are acceptable for a rerank-enabled variant: 6.40s average and about 1022 context tokens after compression stage.

The caveat is substantial: `V7` only beats `V12` by 0.0194 average rule points, and both have 17 serious failures. Treat them as co-leads. Neither is production-ready without Phase 7 and manual serious-failure review.

## Phase 7 Recommendation

Phase 7 should test:

- `V7` as the corrected Small-to-Big/query-rewrite champion.
- `V12` as the corrected RSE/query-rewrite co-lead.
- `V10` as the corrected RSE + true-rerank candidate without query rewrite.
- `V5` as a close alternate to `V10` if budget permits.
- `V2` as the clean hybrid non-rerank control, only if budget permits.
- `V8` Document Augmentation + Hybrid Search + Small-to-Big + Rerank.
- `V13` Document Augmentation + Hybrid Search + RSE + Rerank.

Before Phase 7:

- Keep the strict reranker fallback contract: rerank-enabled runs should fail loudly unless fallback is explicitly configured and recorded.
- Manually review corrected top-variant serious failures, especially automated `unsafe_advice` flags and remaining citation support failures.
- Improve judge setup. Prefer Qwen3 14B for Run 2 judge triage; otherwise keep Qwen2.5 7B only with manual review for top variants, safety cases, and citation failures.
- Keep the 50-question bank unchanged unless a clear artifact interpretation bug is found.

Do not start Document Augmentation from the original Run 1 baseline. Use the corrected Phase 6.5 baseline.

## Blockers Before Production

- Even the corrected provisional champion still has 17 automated serious failures out of 50.
- Citation support improved, but remaining citation-support failures still need manual review.
- Safety boundary answers improved for OSHA/live-status prompts, but automated `unsafe_advice` flags need manual review before production conclusions.
- Judge safety scoring is too blunt to be a production gate.
- Document Augmentation has not been tested.
- Compression reduced cost but hurt quality, so it should not be the production default yet.
