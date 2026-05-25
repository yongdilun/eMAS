# RAG Remaining Failure Review

Created: 2026-05-25

Scope: Phase 10 manual review of the six remaining serious failures from the final Phase 9 `V12` full run. This review is classification only. It does not change RAG behavior, scoring, the question bank, judge behavior, or benchmark artifacts.

Reviewed artifacts:

- `test-artifacts/rag-eval/phase9-20260525-v12`
- `test-artifacts/rag-eval/phase9-20260525-v07`

Candidate under review:

- `V12` = Query Rewrite + Hybrid Search + RSE + Rerank

Fallback/co-lead:

- `V7` = Query Rewrite + Hybrid Search + Small-to-Big + Rerank

## Executive Findings

All six remaining `V12` serious failures are real answer failures. None are scoring false positives, none are acceptable known limits, and none should be closed as ambiguous eval cases.

All six are production blockers under the current production gate because they are answerable cases where expected evidence was retrieved and/or available in context, but `V12` returned the no-evidence fallback instead of using the evidence. The three OSHA guarding cases are safety-relevant production blockers. They do not contain direct unsafe advice, but they fail to provide answerable lockout/tagout and guarding checklist guidance in a safety domain.

`V7` handled three of the six better:

- `nist-ams300-1-mc-01`
- `nist-ams300-11-df-04`
- `osha-guarding-ss-03`

`V7` tied `V12` on the other three:

- `osha-guarding-df-04`
- `osha-guarding-mc-01`
- `nist-csf-2-mc-02`

`V12` remains the engineering candidate because it still has fewer final Phase 9 serious failures than `V7` overall, 6 versus 7, and it cleared all eight reviewed Phase 8 remediation targets. However, `V7`'s better handling of three remaining cases is important evidence for the next remediation pass, especially where Small-to-Big generation succeeded and RSE generation fell back.

Production remains **NO-GO**.

## Case Summary

| Case | V12 classification | Decision | V7 comparison | Safety relevance |
| --- | --- | --- | --- | --- |
| `nist-ams300-1-mc-01` | `generation_failed_to_use_evidence` | `production_blocker` | Better | No safety issue. |
| `nist-ams300-11-df-04` | `generation_failed_to_use_evidence` | `production_blocker` | Better | No safety issue. |
| `osha-guarding-df-04` | `generation_failed_to_use_evidence` | `production_blocker` | Tied | Safety-relevant omission; no unsafe advice. |
| `osha-guarding-ss-03` | `generation_failed_to_use_evidence` | `production_blocker` | Better | Safety-relevant omission; no unsafe advice. |
| `osha-guarding-mc-01` | `generation_failed_to_use_evidence` | `production_blocker` | Tied | Safety-relevant omission; no unsafe advice. |
| `nist-csf-2-mc-02` | `context_builder_missed_evidence` | `production_blocker` | Tied | Cybersecurity incident-response relevance, but not physical safety. |

## Detailed Review

### `nist-ams300-1-mc-01`

Query: How does A23's production system design work connect to A232's instrumentation and control system work?

Expected answer: A23 defines the facility and system design, including equipment, storage/delivery, instrumentation, control, support systems, physical plant, networks, and information systems. A232 narrows that work into controller, data acquisition, communication, and integrated system specifications.

Expected source: `nist_ams_300_1`, A23 and A232, pages 21 and 24.

`V12` answer: no-evidence fallback: "I do not have enough retrieved evidence to answer that safely."

`V12` retrieval and context: retrieval found the expected evidence at ranks 1 to 3, including A2324 on page 24 and A23 on pages 16 and 21. RSE context included A23 and A2324 evidence chunks with supporting pages 16, 21, and 24. The artifact recorded `generation_validation.initial_reason = unknown_citation`, attempted repair, and still failed validation with `repair_failure_reason = unknown_citation`.

Judge: not requested because the automated score was below the borderline band.

Manual classification: `generation_failed_to_use_evidence`.

Decision: `production_blocker`.

V7 comparison: Better. `V7` used the same retrieved evidence and scored 93.52, with 2 full and 1 partial expected-answer point match. It did understate the broader A23 facility-design context, but it was materially correct and not serious.

### `nist-ams300-11-df-04`

Query: Which four information models does MTConnect define?

Expected answer: Devices, Streams, Assets, and Interfaces.

Expected source: `nist_ams_300_11`, ANSI MTConnect, page 16.

`V12` answer: no-evidence fallback.

`V12` retrieval and context: retrieval found the expected document and page. The RSE source snippet itself contained the answer: "Devices, Streams, Assets, and Interfaces." Context expanded around the MTConnect section, but the final answer still fell back. The artifact recorded `generation_validation.initial_reason = unknown_citation`, attempted repair, and `repair_failure_reason = unknown_citation`.

Judge: requested and marked serious, with `wrong_answer`.

Manual classification: `generation_failed_to_use_evidence`.

Decision: `production_blocker`.

V7 comparison: Better. `V7` answered the four models directly, scored 94.44, and the judge marked it non-serious.

### `osha-guarding-df-04`

Query: What lockout/tagout-related maintenance checks are listed in the machine guarding checklist?

Expected answer: maintenance workers lock out machines before repairs; multiple lockout devices are used when several maintenance persons work on the same machine; maintenance and servicing workers are trained in 29 CFR 1910.147; lockout/tagout procedures exist before tasks.

Expected source: `osha_machine_guarding_checklist`, Machinery Maintenance and Repair, page 2.

`V12` answer: no-evidence fallback, plus safety warning.

`V12` retrieval and context: retrieval placed the exact machine-guarding maintenance chunk at rank 1. RSE context included the page 2 maintenance checklist chunk, but the section title was localized poorly as "Protective Equipment and Proper Clothing" even though the expanded text contained items 34 to 37 from Machinery Maintenance and Repair. The artifact recorded `initial_insufficient_context = true`, attempted repair because matching evidence was present, and failed repair due to `missing_citations`.

Judge: requested and marked serious, with `wrong_answer`.

Manual classification: `generation_failed_to_use_evidence`.

Decision: `production_blocker`.

Safety decision: Safety-relevant omission, but no direct unsafe advice. The fallback does not authorize risky maintenance work and includes a safety warning, but it fails to provide answerable lockout/tagout checklist items in a high-risk maintenance context.

V7 comparison: Tied. `V7` also returned a no-evidence fallback with a safety warning and remained a serious failure. Its score was slightly higher, but it did not materially handle the case better.

### `osha-guarding-ss-03`

Query: Summarize the training and worker-readiness checks in this machine guarding checklist.

Expected answer: workers should be trained on how to use safeguards, where safeguards are, what hazards they protect against, when guards may be removed, what to do when guards are damaged/missing/inadequate, machine-specific maintenance instruction, and lockout/tagout requirements/procedures.

Expected source: `osha_machine_guarding_checklist`, Training and Machinery Maintenance and Repair, page 2.

`V12` answer: no-evidence fallback, plus safety warning.

`V12` retrieval and context: retrieval found the training chunk at rank 2 and maintenance chunk at rank 3. RSE context included the expected page 2 training and maintenance evidence, though one segment title was localized as "Nonmechanical Hazards" because the expansion began from an adjacent chunk. The artifact recorded `generation_validation.initial_reason = uncited_claim`, attempted repair, and `repair_failure_reason = uncited_claim`.

Judge: requested and marked serious, with `wrong_answer`.

Manual classification: `generation_failed_to_use_evidence`.

Decision: `production_blocker`.

Safety decision: Safety-relevant omission, but no direct unsafe advice. The answer is conservative, but it suppresses answerable safety-training guidance.

V7 comparison: Better. `V7` answered the training checklist items, scored 94.17, matched all six expected points at least partially, and the judge marked it non-serious.

### `osha-guarding-mc-01`

Query: Before maintenance repairs around moving parts, which checklist areas should be reviewed?

Expected answer: review moving-part safeguards, shutdown before safeguard removal, safeguard and guard-removal training, up-to-date machine maintenance instruction, lockout before repair, multiple lockout devices, safe/guarded maintenance equipment, and 29 CFR 1910.147 procedures.

Expected source: `osha_machine_guarding_checklist`, Requirements for All Safeguards, Other moving parts, Training, and Machinery Maintenance and Repair, pages 1 and 2.

`V12` answer: no-evidence fallback, plus safety warning.

`V12` retrieval and context: retrieval found the maintenance page at rank 1 and the safeguard requirements page at rank 2. RSE context included page 1 safeguarding evidence and page 2 maintenance evidence, but again with some imprecise section titles from page-local expansion. The artifact recorded `generation_validation.initial_reason = uncited_claim`, attempted repair, and `repair_failure_reason = uncited_claim`.

Judge: requested and marked serious, with `wrong_answer`.

Manual classification: `generation_failed_to_use_evidence`.

Decision: `production_blocker`.

Safety decision: Safety-relevant omission, but no direct unsafe advice. This is a high-risk maintenance checklist question, and a production system should answer it from the retrieved checklist while preserving the safety warning.

V7 comparison: Tied. `V7` also returned a no-evidence fallback with a safety warning and remained a serious failure.

### `nist-csf-2-mc-02`

Query: How do DETECT, RESPOND, and RECOVER fit together during cybersecurity incidents?

Expected answer: DETECT finds and analyzes possible attacks, compromises, anomalies, indicators, and adverse events; it supports response and recovery; RESPOND manages, analyzes, communicates, reports, and mitigates incidents; RECOVER restores assets and operations and communicates recovery progress; response and recovery should be ready at all times and occur when incidents happen.

Expected source: `nist_csf_2_0`, CSF Core and Appendix A, pages 9, 10, and 26 to 28.

`V12` answer: no-evidence fallback.

`V12` retrieval and context: retrieval found the DETECT overview at rank 1, an Appendix A incident/recovery chunk at rank 2, and the concurrency/readiness statement at rank 3. RSE context kept pages 8 to 10 and the glossary page 31, but did not carry the retrieved Appendix A `RS`/`RC` incident-response/recovery evidence from page 27 into the final context. The final source snippet supported DETECT and readiness, but not the full RESPOND/RECOVER expected points. The artifact recorded `generation_validation.initial_reason = unknown_citation`, attempted repair, and `repair_failure_reason = unknown_citation`.

Judge: not requested because the automated score was below the borderline band.

Manual classification: `context_builder_missed_evidence`.

Decision: `production_blocker`.

V7 comparison: Tied. `V7` retrieved the same top chunks and also returned the no-evidence fallback. Both variants omitted the rank-2 Appendix A incident-response/recovery chunk from final context.

## Direct Answers To Phase 10 Questions

1. Are all 6 remaining V12 serious failures real? Yes. All six are real answer failures.
2. Which are production blockers? All six are production blockers under the current gate.
3. Are any scoring false positives? No. The scorer correctly flagged answerable cases where the final answer missed all or nearly all expected answer points.
4. Are the OSHA guarding failures safety-relevant? Yes. They are safety-relevant omissions, but none gives direct unsafe advice. The fallback plus safety warning is conservative, yet inadequate for production because the evidence was available.
5. Did V7 handle any better? Yes. `V7` handled `nist-ams300-1-mc-01`, `nist-ams300-11-df-04`, and `osha-guarding-ss-03` better. It tied on `osha-guarding-df-04`, `osha-guarding-mc-01`, and `nist-csf-2-mc-02`.
6. What generic fix categories are needed next? Fix evidence-present fallback and repair validation; improve citation validation for repaired answers; make OSHA descriptive checklist questions answerable while preserving safety warnings; improve context selection for multi-chunk incident/function questions; improve section-title/page-local metadata handling for expanded checklist chunks.
7. Is V12 still the engineering candidate? Yes. `V12` still has fewer final serious failures than `V7` and cleared the eight reviewed Phase 8 cases, but `V7` provides useful contrast for the next fix pass.
8. Is production still NO-GO? Yes. The candidate still has six real serious failures, including three safety-relevant OSHA guarding failures.

## Next Generic Fix Categories

1. Evidence-present fallback repair: stop returning the no-evidence fallback when retrieved/context evidence contains the expected answer, unless the query is truly a live-action, current-state, compliance-certification, vendor, or unsupported boundary request.
2. Citation validation and repair: investigate `unknown_citation`, `uncited_claim`, `uncited_procedure_step`, and `missing_citations` failures where the candidate answer likely had supporting sources but was rejected into fallback.
3. Safety-aware OSHA checklist answering: distinguish descriptive checklist recall from unsafe operational authorization. The model should answer static OSHA checklist questions with citations and a safety warning, not collapse to a generic fallback.
4. RSE/Small-to-Big context selection: preserve retrieved high-value sibling or appendix chunks, especially when the rank-2 chunk carries RESPOND/RECOVER evidence and when page-local expansion changes the apparent section title.
5. Multi-chunk synthesis: improve synthesis across related pages and source segments, especially A23/A232, OSHA guarding page 1/page 2, and CSF DETECT/RESPOND/RECOVER.
