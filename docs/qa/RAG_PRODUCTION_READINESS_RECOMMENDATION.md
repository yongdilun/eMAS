# eMAS RAG Production Readiness Recommendation

Created: 2026-05-25

Scope: production-readiness recommendation for the eMAS RAG evaluation track, updated through Phase 11. This document summarizes the current candidate, production gate decision, remediation roadmap, regression gate, and limited-mode monitoring plan. It does not rerun the benchmark, change scoring, change the question bank, or implement new RAG behavior.

Primary references:

- `docs/qa/RAG_EVALUATION_DECISION_MEMO.md`
- `docs/qa/RAG_EVALUATION_RUN2_ADDENDUM.md`
- `docs/qa/RAG_EVALUATION_SERIOUS_FAILURE_REVIEW.md`
- `docs/qa/RAG_EVALUATION_PHASE_6_6_ADDENDUM.md`
- `docs/qa/RAG_SERIOUS_FAILURE_REMEDIATION.md`
- `docs/qa/RAG_REMAINING_FAILURE_REVIEW.md`
- `docs/qa/RAG_PHASE_11_REMEDIATION.md`

## Phase 9 Status Update

Phase 9 remediated the reviewed serious-failure classes and supersedes the Phase 8 case-level remediation target for the original 8 serious cases.

Final Phase 9 `V12` result:

- 50/50 automated structural pass, 0 warnings.
- Average rule score: 80.301.
- Serious failures: 6.
- Reranker fallback: 0.
- All 8 reviewed Phase 8 serious cases are no longer serious failures.
- The four Phase 8 production blockers are no longer serious failures in final `V12`.

At the end of Phase 9, production readiness remained **NO-GO** because final `V12` still exceeded the regression gate of at most 2 serious failures out of 50 and still had unresolved OSHA guarding serious failures requiring manual review. Phase 11 supersedes this benchmark blocker status, but the production gate and monitoring requirements remain in force.

## Phase 10 Status Update

Phase 10 manually reviewed the 6 remaining final Phase 9 `V12` serious failures. Full details are in `docs/qa/RAG_REMAINING_FAILURE_REVIEW.md`.

Manual review found:

- All 6 remaining `V12` serious failures are real answer failures.
- None are scoring false positives or ambiguous eval cases.
- All 6 are production blockers under the current gate because answerable evidence was retrieved and/or available in context but the final answer returned the no-evidence fallback.
- The 3 OSHA guarding failures are safety-relevant omissions, but none gives direct unsafe advice.
- `V7` handled 3 of the 6 better: `nist-ams300-1-mc-01`, `nist-ams300-11-df-04`, and `osha-guarding-ss-03`.
- `V7` tied on `osha-guarding-df-04`, `osha-guarding-mc-01`, and `nist-csf-2-mc-02`.

Production readiness remains **NO-GO** after Phase 10. Keep `V12` as the engineering candidate, keep `V7` as the fallback/co-lead, and do not remediate by changing scoring or the question bank.

## Phase 11 Status Update

Phase 11 remediated the 6 confirmed remaining `V12` production blockers. Full details are in `docs/qa/RAG_PHASE_11_REMEDIATION.md`.

Final Phase 11 `V12` result:

- 50/50 automated structural pass, 0 warnings.
- Average rule score: 85.1308.
- Serious failures: 0.
- Borderline cases: 40.
- Judge requested/completed: 40/40, 0 judge errors.
- Judge serious failures: 0.
- Reranker fallback: 0.

Final Phase 11 `V7` result:

- 50/50 automated structural pass, 0 warnings.
- Average rule score: 87.7648.
- Serious failures: 2.
- Judge requested/completed: 36/36, 0 judge errors.
- Judge serious failures: 2.
- Reranker fallback: 0.

The Phase 11 benchmark result clears the serious-failure blocker for `V12`: all 6 Phase 10 blockers are no longer serious, no new final `V12` serious failures appear, and no unsafe-advice serious failures appear. `V12` now beats `V7` on readiness because `V12` has 0 serious failures while `V7` has 2, even though `V7` keeps a higher average rule score.

Production remains **NO-GO** as a formal rollout decision until Phase 12 completes manual safety/citation review and a limited-mode rollout checklist. The benchmark gate is now met by `V12`, but the existing readiness policy treats the 50-question benchmark as necessary rather than sufficient.

## Executive Decision

Production shipment is a **NO-GO**.

`V12` remains the engineering candidate after Phase 11 because Query Rewrite + Hybrid Search + RSE + Rerank cleared all 8 reviewed Phase 8 serious cases, remediated all 6 confirmed Phase 10 blockers, and finished the final Phase 11 full run with 0 serious failures. Phase 11 makes `V12` the clear production-readiness review target, not an automatic production rollout.

`V7` remains the close fallback/co-lead: Query Rewrite + Hybrid Search + Small-to-Big + Rerank scored higher on final Phase 11 average rule score at 87.7648, but it had 2 serious failures overall while `V12` had 0. It is not a safer ship candidate yet.

Document Augmentation remains experimental. `V8` and `V13` improved some retrieval/citation signals and fixed `nist-csf-2-ss-03`, but they did not improve overall answer accuracy or serious-failure count enough to become production defaults.

Compression is not a default. Light compression reduced context tokens but hurt quality in corrected runs, so it should stay off unless a future remediation phase proves it can preserve answer quality.

The current Qwen2.5 7B judge is triage-grade only. Production readiness still requires manual review or a stronger judge for safety, citation, and serious-failure adjudication.

## Final Selected Candidate Config

The intended engineering candidate is `V12`.

| Setting | Intended value |
| --- | --- |
| Query rewrite | Enabled for retrieval. Current implementation is deterministic retrieval-only query rewrite; generation receives the original user query. |
| Retrieval | Hybrid Search with vector retrieval plus BM25/keyword retrieval and rank fusion. |
| Context builder | RSE. Expand only same-document chunks, prefer same `section_path` where available, use a plus/minus 2 chunk window, and keep each segment within the planned about 2,000-token RSE cap. |
| Rerank | Enabled. Reranker fallback must remain 0 unless an explicit fallback mode is configured and recorded. |
| Segment scoring | Keep the existing cheap segment scoring after expansion. |
| Light compression | Disabled by default. |
| Document Augmentation | Disabled by default. Keep augmented indexes as experimental eval plumbing only. |
| Safety behavior | Keep boundary/no-action behavior for live status, machine action, OSHA procedure, compliance, and unsupported current-state questions. |
| Judge | Qwen2.5 7B is triage-grade only; do not use it as the production-quality gate. |

This config should be treated as the current remediation target, not as a production rollout plan.

## Why Not Ship Yet

Phase 11 fixed the benchmark serious-failure blocker: final `V12` has 0 serious failures, 0 judge-serious cases, and 0 unsafe-advice serious failures on the unchanged 50-question bank.

Production still should not ship automatically because the readiness policy requires more than the benchmark result. Phase 12 must manually review safety, boundary, citation, and low-scoring borderline cases, then decide whether a limited advisory-mode rollout is acceptable.

The 6 Phase 10 blockers were:

- `nist-ams300-1-mc-01`
- `nist-ams300-11-df-04`
- `osha-guarding-df-04`
- `osha-guarding-ss-03`
- `osha-guarding-mc-01`
- `nist-csf-2-mc-02`

All 6 are no longer serious failures in final Phase 11 `V12`.

The original reviewed serious cases were:

| Case | Manual classification | Decision | Why it matters |
| --- | --- | --- | --- |
| `nist-ams300-1-df-04` | `context_builder_missed_evidence` | Fix before production | The A232 page was found, but the sibling list A2321-A2324 did not survive into usable context. |
| `nist-ams300-1-mc-02` | `generation_failed_to_use_evidence` | Production blocker | Resource availability/status/usage evidence was retrieved, but generation returned the no-evidence fallback. |
| `nist-ams300-11-df-02` | `generation_failed_to_use_evidence` | Production blocker | Scope and out-of-scope evidence reached context, but the answer still fell back. |
| `nist-ams300-11-mc-01` | `generation_failed_to_use_evidence` | Fix before production | Proprietary-connection and interoperability evidence was present, but generation did not use it. |
| `nist-ams300-11-ss-03` | `retrieval_miss` | Fix before production | The standards overview evidence was weakly retrieved and the answer missed the specific standards list. |
| `nist-csf-2-ss-01` | `incomplete_answer` | Production blocker | The CSF Core summary omitted central section points despite retrieved evidence. |
| `nist-csf-2-ss-03` | `citation_support_problem` | Fix before production | The answer cited a broad overview page instead of the online-resources section. |
| `osha-loto-df-03` | `generation_failed_to_use_evidence` | Production blocker | The exact OSHA energy-control procedure section was retrieved at rank 1, but the answer returned the no-evidence fallback. |

The original four production blockers were:

- `nist-ams300-1-mc-02`
- `nist-ams300-11-df-02`
- `nist-csf-2-ss-01`
- `osha-loto-df-03`

Those original blockers are no longer serious failures in final Phase 9 V12, but the full-bank production gate remains unmet.

## Failure Pattern Analysis

Generation failed to use evidence:

- `nist-ams300-1-mc-02`
- `nist-ams300-11-df-02`
- `nist-ams300-11-mc-01`
- `osha-loto-df-03`

Incomplete answer despite retrieved evidence:

- `nist-csf-2-ss-01`
- `nist-csf-2-ss-03` also had partial content but missed required online-resource details.

Retrieval or context miss:

- `nist-ams300-1-df-04`
- `nist-ams300-11-ss-03`
- `nist-csf-2-ss-03` also failed to retrieve the expected page/section for `V12`.

Citation localization problem:

- `nist-csf-2-ss-03`
- More generally, section-specific questions need citation selection to prefer the evidence-bearing page/section over broad overview pages.

Safety-relevant failure:

- `osha-loto-df-03`

The largest systemic issue is the no-evidence fallback firing when answer evidence is already present. That pattern appears in manufacturing architecture, manufacturing data recommendations, and OSHA LOTO, so it should be treated as a cross-source generation/context contract problem.

## Required Remediation Roadmap

Phase 9 completed the original reviewed-case remediation tasks below. Keep them as regression requirements for future changes:

1. Fix no-evidence fallback when evidence is present.
   - Add a generation/context contract that distinguishes true boundary questions from answerable questions with retrieved evidence.
   - Prevent the generic no-evidence fallback when the expected document/page/section or strong evidence spans are already in context.
   - Add instrumentation that records why fallback was chosen.

2. Improve answer completeness for section-summary and multi-chunk questions.
   - Ensure the generator covers section-level expectations, not only the first obvious definition or function list.
   - Add evidence coverage checks for multi-part answers before final response generation where feasible.

3. Improve sibling-section expansion for related section lists such as A2321-A2324.
   - When a retrieved heading is part of a numbered sibling group, include adjacent sibling headings and short bodies in context.
   - Preserve list headings, section labels, and ordering through RSE/Small-to-Big context assembly.

4. Improve AMS 300-11 standards/scope retrieval or context selection.
   - Target the scope question `nist-ams300-11-df-02` and standards summary `nist-ams300-11-ss-03`.
   - Make named-section and standards-list queries bring the relevant overview and enumerated standards into top context.

5. Improve CSF section-summary generation.
   - Target `nist-csf-2-ss-01` so CSF Core answers cover hierarchy, non-checklist nature, concurrent Functions, and broad ICT applicability.
   - Preserve central section constraints in the final answer, not just the six Function names.

6. Improve OSHA LOTO procedural completeness.
   - Target `osha-loto-df-03` and related LOTO procedural questions.
   - Require procedural answers to include scope/purpose/authorization/rules, shutdown/isolation/security steps, device placement/removal/transfer responsibility, and testing/verification when evidence supports them.

7. Add a manual or stronger-judge safety gate.
   - Use Qwen3 14B or stronger if available for safety/citation triage.
   - Keep manual review mandatory for OSHA/safety cases and any answer with operational safety implications.

8. Create regression tests from the 8 reviewed serious cases.
   - Preserve the current 50-question bank.
   - Add focused regression fixtures/assertions for the 8 case IDs, including fallback behavior, evidence use, citation support, and safety review status.

## Regression Gate Before Production

Before production readiness can be reconsidered, the next candidate must meet all of these gates:

- 0 production-blocker failures on the 8 reviewed serious cases.
- 0 production-blocker failures on the 6 Phase 10 remaining-failure cases.
- 0 unsafe-advice failures.
- 0 no-evidence fallback answers when expected evidence is present in retrieval/context for an answerable case.
- At most 2 serious failures out of the 50-question bank, and none may be safety-relevant, boundary-breaking, or production-blocker failures.
- Manual review required for all OSHA/safety cases before a ship decision.
- Reranker fallback must remain 0 for rerank-enabled production candidates.
- Citation support must cite the expected document and expected page/section, or an acceptable supporting page range that contains the evidence.
- The 50-question benchmark result is necessary but not sufficient; it is not by itself a production pass.

## Monitoring Plan For Internal/Limited Mode

If eMAS RAG is exposed internally before production, it should run in limited advisory mode with no unreviewed operational action authority.

Required logs and review signals:

- No-evidence fallback rate, split by answerable vs boundary-style prompts where possible.
- Retrieved-document vs cited-document mismatch rate.
- Expected-page/section support miss rate for eval and sampled internal queries.
- Serious safety, boundary, and citation categories.
- Latency, retrieved chunk count, context token estimates, answer token estimates, and reranker fallback status.
- Context builder metadata, including whether RSE found same-section/sibling-section evidence.
- Sampled answers for manual review, with oversampling of OSHA/safety and procedure questions.

Required limited-mode behavior:

- Keep safety disclaimers and no-action boundaries for OSHA/live-status or operational-risk questions.
- Do not authorize live machine actions, lockout removal, compliance certification, or current-state claims from static documents.
- Route safety-critical or compliance-critical answers to a qualified human reviewer before operational use.

## What Not To Do

- Do not ship `V8` or `V13` as production defaults.
- Do not enable compression by default.
- Do not rely on the Qwen2.5 7B judge as a production-quality evaluator.
- Do not relax scoring to hide failures.
- Do not treat the benchmark as a production pass.
- Do not change the question bank, scoring, or expected answers just to improve the readiness story.
- Do not start an unrelated experiment before Phase 12 reviews the final Phase 11 safety, citation, and boundary evidence.

## Next Implementation Phase Proposal

Recommended follow-up phase: **Phase 12: Production-Readiness Review**.

Proposed substeps:

1. Manually review final Phase 11 `V12` OSHA/safety, boundary, citation, and low-scoring borderline cases.
2. Confirm the 6 Phase 10 blockers stay fixed under adjacent wording smoke checks.
3. Decide whether Qwen2.5 7B judge output is enough as triage or whether a stronger judge/manual checklist is required.
4. Draft a limited advisory-mode rollout plan with monitoring for fallback rate, citation support, safety/boundary behavior, and reranker fallback.
5. Only then reconsider production readiness.

Phase 12 should keep `V12` as the main engineering candidate. Keep `V7` as the comparison fallback because it has a higher average score, but it is weaker for readiness after Phase 11 because it still has 2 serious failures.
