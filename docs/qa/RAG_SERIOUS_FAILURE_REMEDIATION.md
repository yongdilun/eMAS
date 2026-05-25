# RAG Serious-Failure Remediation

Created: 2026-05-25

Scope: Phase 9 remediation for the reviewed serious-failure classes in the V12 engineering candidate. This phase changed generic RAG behavior only. It did not change the 50-question bank, expected answers, scoring rules, judge behavior, Document Augmentation defaults, compression defaults, or variant definitions.

## Executive Summary

Phase 9 materially improved the reviewed V12 serious-failure set, including the four production blockers from the Phase 8 readiness recommendation.

Final Phase 9 V12 full run:

- Run: `phase9-20260525-v12`
- Candidate: `V12` = Query Rewrite + Hybrid Search + RSE + Rerank
- Automated structural result: 50/50 pass, 0 warnings
- Average rule score: 80.301
- Serious failures: 6
- Borderline cases: 39
- Judge requested/completed: 39/39, 0 judge errors
- Judge serious failures: 4
- Reranker fallback: 0
- Retrieval: `doc_hit@3 = 0.98`, `doc_hit@5 = 1.00`, `section_or_page_hit@3 = 0.86`, `section_or_page_hit@5 = 0.94`

Final Phase 9 V7 full run:

- Run: `phase9-20260525-v07`
- Fallback/co-lead: `V7` = Query Rewrite + Hybrid Search + Small-to-Big + Rerank
- Automated structural result: 50/50 pass, 0 warnings
- Average rule score: 81.961
- Serious failures: 7
- Borderline cases: 32
- Judge requested/completed: 32/32, 0 judge errors
- Judge serious failures: 2
- Reranker fallback: 0
- Retrieval: `doc_hit@3 = 0.98`, `doc_hit@5 = 1.00`, `section_or_page_hit@3 = 0.86`, `section_or_page_hit@5 = 0.94`

Recommendation after Phase 9: keep production as **NO-GO**. V12 cleared the eight reviewed serious cases in the final full run, but the full bank still has 6 serious failures, including safety-adjacent OSHA guarding cases. The production gate from Phase 8 required at most 2 serious failures and no safety-relevant unresolved serious failures.

## Generic Fixes Implemented

Generation evidence repair:

- Added a repair pass when the first answer is invalid or returns insufficient-context despite matching retrieved evidence.
- Kept a boundary guard so live status, machine-action, safety/current-state, vendor, and compliance-proof questions do not get repaired into unsafe operational advice.
- Added `generation_validation` metadata to record initial validation, repair attempt, repair reason, and repair outcome.

Citation repair:

- Added deterministic single-source citation repair for repair-pass answers that are otherwise supported but fail the citation contract due missing citation markers or uncited factual tails.
- Kept this scoped to one-source answers to avoid masking multi-source attribution errors.

Answer completeness:

- Strengthened the generation prompt for dispersed evidence, section summaries, multi-part questions, comparisons, and safety procedures.
- Procedure answers now explicitly ask the model to include all supported procedural categories while leaving safety cautions in structured safety metadata.

RSE context expansion:

- RSE now includes sibling or nearby related sections for list, group, summary, scope, standard, resource, and procedure-style questions.
- This addresses cases where the seed chunk is one section in a sibling group, such as A2321-A2324, or where a section summary spans adjacent pages.

Source page enrichment:

- For related-section questions, the context builder can append bounded text from the same source PDF page when the indexed chunk lost useful headings or page-local evidence.
- This avoids reingestion and keeps the fix generic across PDF sources.

Query rewrite generalization:

- Replaced exact phrase topic expansions with intent-based retrieval cues.
- The rewrite now triggers on term families such as supplemental/web/reference/resource/material/guide/example and standards/formats/interoperability/scope.
- The original query terms remain in the retrieval focus, so adjacent wording keeps its own retrieval signal.
- Added a small stem fix so words such as `resources`, `references`, and `devices` do not degrade into malformed stems.

Citation localization:

- Representative source selection now considers section title and section path in addition to chunk text and snippets.

## Reviewed Serious Cases

The eight reviewed V12 cases from Phase 8 all cleared serious-failure status in the final V12 full run.

| Case | Phase 8 status | Final V12 score | Final V12 serious? | Notes |
| --- | --- | ---: | --- | --- |
| `nist-ams300-1-df-04` | Fix before production | 75.69 | No | RSE plus page evidence preserved the A232 sibling list. |
| `nist-ams300-1-mc-02` | Production blocker | 100.00 | No | Resource availability/status/usage now answers from retrieved evidence. |
| `nist-ams300-11-df-02` | Production blocker | 89.58 | No | Scope and out-of-scope answer no longer falls back. |
| `nist-ams300-11-mc-01` | Fix before production | 85.42 | No | Proprietary-connection/interoperability answer now uses context. |
| `nist-ams300-11-ss-03` | Fix before production | 85.42 | No | Standards summary now retrieves and synthesizes the standards list. |
| `nist-csf-2-ss-01` | Production blocker | 72.78 | No | CSF Core summary improved, though section@3 still misses the expected section. |
| `nist-csf-2-ss-03` | Fix before production | 80.56 | No | Online-resource citation/localization improved with generalized resource cues. |
| `osha-loto-df-03` | Production blocker | 86.25 | No | OSHA energy-control procedure answer now includes required procedural categories. |

V7 remains a close fallback/co-lead, but it still has a serious failure on `nist-ams300-1-df-04` in the final full run. V12 is therefore still the cleaner engineering candidate for the reviewed-remediation target, despite V7's higher average rule score.

## Remaining Full-Bank Failures

V12 still has 6 serious failures in the final full run:

- `nist-ams300-1-mc-01`
- `nist-ams300-11-df-04`
- `osha-guarding-df-04`
- `osha-guarding-ss-03`
- `osha-guarding-mc-01`
- `nist-csf-2-mc-02`

These are outside the original eight reviewed cases. They keep production readiness closed because the Phase 8 gate required at most 2 serious failures out of 50 and no unresolved safety-relevant serious cases. The OSHA guarding failures should receive manual review before any readiness upgrade.

## Regression Coverage Added

Focused tests were added for:

- No-evidence fallback repair when matching evidence is present.
- Invalid or uncited answers repaired into cited answers when evidence is present.
- Live safety boundary fallback not repaired into operational advice.
- OSHA energy-control procedure completeness with structured safety caution.
- Single-source citation repair for missing citations and uncited factual tails.
- RSE sibling-section expansion for list/group questions.
- Query rewrite preserving original terms while adding generalized intent cues.
- Adjacent query wording for supplemental web/material/resource questions.
- Standards/scope intent cues without exact eval phrase triggers.

Focused pytest result:

- `python -m pytest factory-agent/tests/test_rag_context_building.py factory-agent/tests/test_rag_generation.py -q`
- Result: 33 passed

## Verification Runs

CLI help:

- `python -m tests.rag_eval.run_eval --help`
- Passed and showed the expected variant and judge options.

Focused V12 spot checks after generalizing query rewrite:

- `phase9-v12-nist-csf-2-ss-03`: score 80.56, judge OK, 0 warnings
- `phase9-v12-nist-ams300-11-ss-03`: score 87.85, judge OK, 0 warnings
- `phase9-v12-nist-ams300-11-df-02`: score 84.72, judge OK, 0 warnings

Full final reruns:

- `python -m tests.rag_eval.run_eval --variant V12 --run-id phase9-20260525-v12 --judge`
- `python -m tests.rag_eval.run_eval --variant V7 --run-id phase9-20260525-v07 --judge`

Both final full reruns completed with 50/50 automated structural pass, 0 warnings, 0 judge errors, and 0 reranker fallback.

## Production Decision

Phase 9 improves the candidate but does not make it production ready.

Keep:

- V12 as engineering candidate.
- V7 as close fallback/co-lead.
- Document Augmentation experimental only.
- Compression off by default.
- Qwen2.5 7B judge as triage-grade only.

Do not ship yet. Next readiness work should manually review the 6 remaining V12 serious failures, especially OSHA guarding cases, then remediate or adjudicate them before another production recommendation.
