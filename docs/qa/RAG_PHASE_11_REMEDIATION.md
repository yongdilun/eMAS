# RAG Phase 11 Remediation

Created: 2026-05-25

Scope: Phase 11 remediated the six confirmed final Phase 9 `V12` serious failures without changing `tests/rag_eval/cases.json`, expected answers, scoring, judge behavior, variant definitions, Document Augmentation defaults, or compression defaults.

Primary run artifacts:

- `test-artifacts/rag-eval/phase11-20260525-v12`
- `test-artifacts/rag-eval/phase11-20260525-v07`

## Executive Summary

Phase 11 fixed the six remaining `V12` production blockers from Phase 10 in the final judged rerun.

Final Phase 11 `V12`:

- 50/50 automated structural pass, 0 warnings.
- Average rule score: 85.1308.
- Serious failures: 0.
- Borderline cases: 40.
- Judge requested/completed: 40/40, 0 judge errors.
- Judge serious failures: 0.
- Reranker fallback: 0.
- Retrieval: `doc_hit@3 = 0.98`, `doc_hit@5 = 1.00`, `section_or_page_hit@3 = 0.86`, `section_or_page_hit@5 = 0.94`.

Final Phase 11 `V7`:

- 50/50 automated structural pass, 0 warnings.
- Average rule score: 87.7648.
- Serious failures: 2.
- Borderline cases: 36.
- Judge requested/completed: 36/36, 0 judge errors.
- Judge serious failures: 2.
- Reranker fallback: 0.
- Retrieval matched `V12` on the reported aggregate hit rates.

`V12` wins the readiness comparison because it has 0 serious failures and no judge-serious cases. `V7` still has the higher average rule score, but it has 2 serious failures: `nist-ams300-11-ss-03` and `nist-csf-2-ss-01`.

Production should remain **NO-GO** as a formal rollout decision until Phase 12 performs the required manual safety/citation readiness review and limited-mode production checklist. Phase 11 removes the benchmark blockers, but the existing production policy still treats the 50-question benchmark as necessary, not sufficient.

## Code Paths Changed

1. `factory-agent/factory_agent/rag/generation.py`
   - Added prompt guidance for static OSHA/checklist recall versus live authorization.
   - Added citation repair that can normalize single-source page-style markers such as `[^16]` to the actual source number.
   - Added bounded multi-source citation repair for uncited repair answers by choosing the best supporting source via answer/source overlap.
   - Added count-aware completeness repair for valid but short list answers when the query asks for a specific number of items.

2. `factory-agent/factory_agent/rag/answer_contract.py`
   - Allowed grouped bullet/checklist blocks when a contiguous list has a valid citation, matching the existing grouped-procedure citation contract.

3. `factory-agent/factory_agent/rag/context_building.py`
   - Added normalized related-section cues such as `function`, `incident`, `detect`, `respond`, `recover`, `check`, and `checklist`.
   - Preserved top retrieved related candidates for RSE when rerank omits a high-value rank 1-3 candidate.

4. `factory-agent/factory_agent/rag/source_metadata.py`
   - Removed footnote definitions and bare marker-only lines during answer sanitization.

5. Regression tests
   - Added focused tests for single-source unknown-citation repair, multi-source missing-citation repair, OSHA static checklist answering, grouped checklist citations, RSE rank preservation, and count-aware list completeness repair.

## Six Blockers

| Case | Final V12 score | Final V12 serious? | Judge serious? | Phase 11 result |
| --- | ---: | --- | --- | --- |
| `nist-ams300-1-mc-01` | 93.52 | No | No | Fixed. Uses A23 and A232 evidence instead of fallback. |
| `nist-ams300-11-df-04` | 94.44 | No | No | Fixed. Lists Devices, Streams, Assets, and Interfaces. |
| `osha-guarding-df-04` | 73.12 | No | No | Fixed. Answers static checklist LOTO checks with citations and safety metadata. |
| `osha-guarding-ss-03` | 89.17 | No | No | Fixed. Summarizes training/readiness checks from checklist evidence. |
| `osha-guarding-mc-01` | 80.42 | No | No | Fixed. Answers checklist review areas without live-action permission. |
| `nist-csf-2-mc-02` | 92.22 | No | No | Fixed. RSE preserves RESPOND/RECOVER appendix evidence. |

All six confirmed Phase 10 blockers are fixed for final `V12`.

## New Serious Failures

No new serious failures appear in the final Phase 11 `V12` rerun. A preliminary rerun exposed a valid-but-short answer for the A232 four-item list case; Phase 11 addressed it with the generic count-aware completeness repair before the final rerun.

## OSHA Safety Behavior

OSHA safety behavior improved without unsafe advice:

- Static machine-guarding checklist questions now receive descriptive, cited answers.
- High-risk OSHA answers still carry structured safety metadata.
- Boundary questions still refuse live authorization or compliance certification.
- No `unsafe_advice` serious failures appeared in final `V12` or `V7`.

## V12 Versus V7

`V12` beats `V7` for readiness after remediation:

- `V12`: 0 serious failures, 0 judge-serious cases, average 85.1308.
- `V7`: 2 serious failures, 2 judge-serious cases, average 87.7648.

`V7` remains a useful fallback/co-lead for comparison because its average score is higher, but the serious-failure gate now favors `V12`.

## Production Decision

Production remains **NO-GO** as a formal rollout decision. Phase 11 clears the benchmark blocker and makes `V12` the clear engineering candidate, but production approval still needs:

- Manual review of all OSHA/safety and boundary cases.
- Manual or stronger-judge citation review for top-candidate borderline cases.
- A limited-mode deployment/monitoring checklist.
- Confirmation that the improved behavior is stable across reruns or a small adjacent query set.

## Phase 12 Recommendation

Phase 12 should be a production-readiness review rather than another broad remediation pass:

1. Manually review final Phase 11 `V12` OSHA/safety, boundary, and low-scoring borderline cases.
2. Review the remaining weak-but-non-serious cases, especially `nist-ams300-11-un-01`, `nist-csf-2-un-01`, `osha-guarding-un-01`, and low 70s section-summary cases.
3. Run an adjacent wording smoke set for the repaired patterns without changing the 50-question benchmark.
4. Decide whether to upgrade the judge or add a human-review acceptance checklist for production.
5. If approved, draft a limited advisory-mode rollout plan with monitoring for fallback rate, citation support, safety/boundary behavior, and reranker fallback.

## Validation

- `python -m pytest -q factory-agent/tests/test_rag_context_building.py factory-agent/tests/test_rag_generation.py tests/rag_eval`: 69 passed.
- Extended focused pytest including `factory-agent/tests/test_rag_answer_contract.py`: 84 passed.
- `python -m tests.rag_eval.run_eval --help`: passed.
- `git diff --check`: passed with LF-to-CRLF warnings only.
- `python -m tests.rag_eval.run_eval --variant V12 --run-id phase11-20260525-v12 --judge`: completed, 0 serious failures.
- `python -m tests.rag_eval.run_eval --variant V7 --run-id phase11-20260525-v07 --judge`: completed, 2 serious failures.
