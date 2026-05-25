# eMAS RAG Serious Failure Review

Created: 2026-05-25

Scope: manual review of the remaining Run 2 serious failures for `V12`, before Phase 8. This review reads the existing artifacts only. It does not rerun the benchmark, change scoring rules, change the question bank, or implement new RAG behavior.

Primary artifacts reviewed:

- `test-artifacts/rag-eval/run2-20260525-v12`
- `test-artifacts/rag-eval/run2-20260525-v07`
- `test-artifacts/rag-eval/run2-20260525-v08`
- `test-artifacts/rag-eval/run2-20260525-v13`
- `test-artifacts/rag-eval/run2-20260525-v10`

Reference files reviewed:

- `docs/qa/RAG_EVALUATION_TRACK.md`
- `docs/qa/RAG_EVALUATION_DECISION_MEMO.md`
- `docs/qa/RAG_EVALUATION_RUN2_ADDENDUM.md`
- `docs/qa/rag_eval_question_bank.md`
- `tests/rag_eval/cases.json`

## Executive Summary

`V12` remains the recommended Run 2 candidate, but it is not production-ready.

All 8 `V12` automated serious failures are real enough to keep the production gate closed. None are clear scoring false positives. The dominant pattern is not total document retrieval failure: in 5 of 8 cases, the expected document and source page or section was present in retrieval/context, but generation either returned the generic "not enough retrieved evidence" fallback or used only part of the evidence. One case is primarily a citation/localization failure, and two cases have meaningful retrieval/context-builder misses.

`V7` did not handle any of the 8 `V12` serious cases better. It tied `V12` on the same failure outcome for all 8 reviewed cases.

Document Augmentation fixed 1 of the 8 `V12` serious cases: `nist-csf-2-ss-03`. Both `V8` and `V13` retrieved and cited the expected page 14 online-resources section and scored 85.42 on that case. Document Augmentation also improved early-rank retrieval for `nist-ams300-11-df-02`, but generation still failed with the no-evidence fallback. It did not fix the remaining 7 cases.

Final recommendation before Phase 8: **do not ship yet**. `V12` can remain the provisional production candidate for engineering work, with `V7` as the close fallback/co-lead, but rollout should wait until the serious failure patterns below are fixed and regression-tested.

## V12 Serious Cases

| Case | V12 Serious Code | Manual Classification | Decision | V7 Better? | V8/V13 Helped? |
| --- | --- | --- | --- | --- | --- |
| `nist-ams300-1-df-04` | `wrong_answer` | `context_builder_missed_evidence` | `should_be_fixed_before_production` | No | No |
| `nist-ams300-1-mc-02` | `wrong_answer` | `generation_failed_to_use_evidence` | `production_blocker` | No | No |
| `nist-ams300-11-df-02` | `wrong_answer` | `generation_failed_to_use_evidence` | `production_blocker` | No | Partial retrieval help only |
| `nist-ams300-11-mc-01` | `wrong_answer` | `generation_failed_to_use_evidence` | `should_be_fixed_before_production` | No | No |
| `nist-ams300-11-ss-03` | `wrong_answer` | `retrieval_miss` | `should_be_fixed_before_production` | No | No |
| `nist-csf-2-ss-01` | `wrong_answer` | `incomplete_answer` | `production_blocker` | No | No |
| `nist-csf-2-ss-03` | `citation_does_not_support_answer` | `citation_support_problem` | `should_be_fixed_before_production` | No | Yes |
| `osha-loto-df-03` | `wrong_answer` | `generation_failed_to_use_evidence` | `production_blocker` | No | No |

## Case Notes

### `nist-ams300-1-df-04`

Query: "Name the four subactivities under A232: Specify Instrumentation and Control Systems."

Expected answer: A2321 Identify Control Requirements; A2322 Identify Instrumentation Requirements; A2323 Identify Communications Requirements; A2324 Integrate System Specifications.

`V12` retrieved page 24 and cited the A2324 section, so page-level retrieval metrics passed. The retrieved/context segments did not carry the full sibling list of A2321 through A2324. The answer was the generic no-evidence fallback and matched 0 of 4 expected points.

Manual classification: `context_builder_missed_evidence`. This is not a scoring false positive. The artifact shows a real answer failure and a page-hit metric that is too coarse for this list-style page question.

Comparison: `V7`, `V8`, `V13`, and `V10` all failed the same way. Document Augmentation did not help; for `V8`/`V13`, an unrelated CSF glossary chunk ranked first, although the expected page was still retrieved.

### `nist-ams300-1-mc-02`

Query: "What's the difference between resource availability, resource status, and resource usage in this document?"

Expected answer: availability is planned/expected resource capacity over time; status is current personnel/equipment state; usage is time and process-condition history for maintenance, utilization, or cost.

`V12` retrieval was strong: top chunks and context included resource usage, resource availability, and resource status on page 42. The evidence snippets directly contained the needed distinctions. The answer still returned the generic no-evidence fallback and matched 0 of 3 expected points.

Manual classification: `generation_failed_to_use_evidence`.

Decision: `production_blocker`, because this is a straightforward evidence-present answer that a production RAG system should handle.

Comparison: `V7`, `V8`, `V13`, and `V10` all failed the same way. Document Augmentation slightly reordered top chunks but did not change the outcome.

### `nist-ams300-11-df-02`

Query: "What manufacturing processes and data formats are in scope or out of scope for the recommendations?"

Expected answer: network-based shop-floor data collection using open consensus standards for CNC subtractive and CNC metal additive processes is in scope; proprietary formats, polymer additive processes, and mass-conserving processes such as casting and forging are out of scope.

`V12` top 3 retrieval missed the expected document and pulled `nist_ams_300_1`, but top 5/top 10 did include the `nist_ams_300_11` overview/scope material on page 8. The final context contained the core in-scope and out-of-scope language, including CNC subtractive, CNC metal additive, polymer additive, casting, and forging. The answer still returned the no-evidence fallback and matched 0 of 4 expected points.

Manual classification: `generation_failed_to_use_evidence`, with secondary early-rank retrieval weakness.

Decision: `production_blocker`, because document scope questions are common and the evidence was present by the time generation ran.

Comparison: `V7` tied `V12`. Document Augmentation improved `V8`/`V13` early-rank retrieval so the expected page landed in the top 3, but both still returned the fallback. It helped retrieval, not answer quality.

### `nist-ams300-11-mc-01`

Query: "Why does the report prefer data interoperability standards over lots of proprietary machine-data connections?"

Expected answer: proprietary connections become bespoke, costly, and vendor-locking as sources/applications grow; open interoperability standards give manufacturers more flexible strategic connectivity investments and are internationally recognized, open, consensus-based standards.

`V12` retrieved relevant `nist_ams_300_11` chunks, including the proprietary-connection challenge and the standards/interoperability discussion. The cited source snippet included the key sentence about standards providing a flexible means to limit long-term costs and integrate the right solutions. The answer still returned the no-evidence fallback and matched 0 of 4 expected points.

Manual classification: `generation_failed_to_use_evidence`.

Decision: `should_be_fixed_before_production`.

Comparison: `V7`, `V8`, `V13`, and `V10` all failed the same way. Document Augmentation did not fix the case.

### `nist-ams300-11-ss-03`

Query: "Give a short section summary of the relevant standards reviewed in the report."

Expected answer: the section reviews open consensus standards supporting manufacturing-process inputs or outputs, including STEP AP242, AMF, G-code, MTConnect, QIF, and PDF/PRC.

`V12` gave a partial generic standards answer but missed the specific standards list. It matched 1 full point and 1 partial point, missing 6 expected points. Retrieval was weak: the first three chunks were from the wrong document or irrelevant generic sections, and the expected `Overview of Relevant Standards` section appeared only at rank 5. Context included the overview and abstract, plus an irrelevant OSHA source, but not enough specific standards evidence.

Manual classification: `retrieval_miss`.

Decision: `should_be_fixed_before_production`.

Comparison: `V7`, `V8`, and `V13` did not improve the outcome. `V10` was worse, returning the fallback and also recording a wrong/missing citation.

### `nist-csf-2-ss-01`

Query: "Summarize the CSF Core section in plain English."

Expected answer: the Core is outcomes arranged by Function, Category, and Subcategory; it is not a checklist or sequence; Functions should be addressed concurrently; the Core applies broadly across ICT, including IT, IoT, OT, cloud, mobile, AI, and future environments.

`V12` answered with a useful description of the six Functions, but it did not fully summarize the section. It partially matched the hierarchy/function points and missed the non-checklist, concurrency, and broad-ICT applicability points. Retrieval/context contained the page 8-10 evidence, including the non-checklist/concurrent language, so this is mainly incomplete generation rather than missing evidence.

Manual classification: `incomplete_answer`.

Decision: `production_blocker`, because CSF Core summaries are a central expected capability for this source.

Comparison: `V7` tied `V12`. `V10` also failed similarly. `V8`/`V13` regressed to the no-evidence fallback despite relevant chunks.

### `nist-csf-2-ss-03`

Query: "What's in the online resources section that supplements the CSF?"

Expected answer: online resources can be updated more frequently than the stable PDF and may be machine-readable; they include Informative References, Implementation Examples, and Quick Start Guides.

`V12` answered partially correctly but cited page 6 instead of the expected page 14 online-resources section. The answer missed the update-frequency/machine-readable point and the non-baseline nature of Implementation Examples. Retrieval never hit the expected page or section in the top 10, so the cited evidence did not properly support the section-specific answer.

Manual classification: `citation_support_problem`.

Decision: `should_be_fixed_before_production`. This is not a scoring false positive: page 6 gives high-level mentions, but the question asks about the online resources section and the answer needs page 14 support.

Comparison: `V7` tied `V12`. `V10`, `V8`, and `V13` answered this case better. Document Augmentation fixed it for both `V8` and `V13` by retrieving page 14 at rank 1 and citing the correct online-resources section.

### `osha-loto-df-03`

Query: "What must an energy-control procedure include?"

Expected answer: the procedure must explain what employees need to know and do; outline scope, purpose, authorization, rules, techniques, and enforcement; include how to use the procedure; steps to shut down/isolate/block/secure; placement/removal/transfer/responsibility for devices; and testing/verification requirements.

`V12` retrieved the exact expected section on page 13 at rank 1. The context snippets directly contained the expected checklist items. The answer still returned the no-evidence fallback and matched 0 of 6 expected points.

Manual classification: `generation_failed_to_use_evidence`.

Decision: `production_blocker`. This is a safety-relevant answerable LOTO procedure question. The system did not give unsafe advice, but failing to answer from directly retrieved OSHA evidence is not acceptable for production.

Comparison: `V7`, `V8`, `V13`, and `V10` all failed the same way. Document Augmentation did not help.

## Review Questions

1. Are `V12`'s 8 serious failures real?

Yes. All 8 are real enough to preserve the serious-failure count. None should be dismissed as a scoring false positive. One is primarily citation support (`nist-csf-2-ss-03`); the others are wrong, incomplete, retrieval/context, or generation failures.

2. Did `V7` handle any of them better?

No. `V7` tied `V12` on all 8 reviewed cases by score, serious-failure status, and practical answer quality.

3. Did Document Augmentation fix any of them?

Yes, but only one. `V8` and `V13` fixed `nist-csf-2-ss-03` by retrieving and citing the expected page 14 online-resources section. They also improved retrieval rank for `nist-ams300-11-df-02`, but both still failed generation. They did not fix the other 7 `V12` serious failures.

4. Which failures block production?

The clearest production blockers are:

- `nist-ams300-1-mc-02`: evidence-present answer failed for core information-flow definitions.
- `nist-ams300-11-df-02`: evidence-present answer failed for source scope/in-scope/out-of-scope boundaries.
- `nist-csf-2-ss-01`: central CSF Core summary was incomplete despite supporting evidence.
- `osha-loto-df-03`: safety-relevant OSHA LOTO procedure question failed despite exact-section retrieval.

The remaining serious failures should still be fixed before production, especially because they show the same systemic issues: sibling-section evidence loss, weak standards-section retrieval, and citation localization errors.

5. Which failures are scoring/eval artifacts?

None. `nist-csf-2-ss-03` is closest to debatable because the answer content was partially correct, but the cited source was the wrong page/section and the retrieval never hit the expected support. It should remain a real citation-support problem.

6. What are the top fixes before production?

- Fix the generation no-evidence fallback behavior so it answers from retrieved evidence when exact source snippets are present, especially on non-boundary questions.
- Add regression tests/gates for the 8 reviewed case IDs and track the failure class, not just the aggregate score.
- Improve context assembly for list and sibling-section questions so section titles and nearby sibling headings survive into generation context.
- Improve retrieval/rerank behavior for section-summary questions that ask for named sections or standards lists.
- Improve citation selection so the cited source is the evidence-bearing page/section, not a broad overview page.
- Keep a manual or stronger-judge gate for safety-relevant OSHA cases before production rollout.

7. Is `V12` still the recommended candidate?

Yes, for continued engineering work. `V12` still has the best Run 2 aggregate result among the required comparison set. `V7` remains a close co-lead/fallback but did not answer any of `V12`'s serious cases better. Document Augmentation should remain experimental because it fixed one case but lost overall.

8. Is the final recommendation "ship", "limited/internal only", or "do not ship yet"?

Do not ship yet. The remaining serious failures are real, include a safety-relevant OSHA procedure failure, and expose a systemic generation issue where the model declines to answer despite having the needed retrieved evidence.
