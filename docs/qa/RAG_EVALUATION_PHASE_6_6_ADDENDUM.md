# eMAS RAG Evaluation Phase 6.6 Addendum

Created: 2026-05-25

## Scope

Phase 6.6 corrected narrow scoring fairness defects found during manual review of the Phase 6.5 top variants, then reran the decision-sensitive top-candidate set. This phase did not change the 50-question bank, prompts, expected answers, retrieval, reranking, context building, compression, generation, or Document Augmentation.

Fairness fixes:

- Citation support now follows the planned page-or-section strictness. A noisy extracted section label no longer creates `citation_does_not_support_answer` when the expected page/evidence support is present.
- Citation support remains strict when the expected document is cited but neither expected page nor expected section support is hit.
- Unsafe-advice regex matching no longer spans across unrelated checklist lines, so `safeguard` checklist language is not treated as permission to bypass a guard or skip lockout.

Rerun scope:

- `V7`: `run1-phase66-20260525-v07`
- `V12`: `run1-phase66-20260525-v12`
- `V10`: `run1-phase66-20260525-v10`
- `V5`: `run1-phase66-20260525-v05`
- `V2`: `run1-phase66-20260525-v02`

All Phase 6.6 reruns used `--judge`. Judge-requested cases completed with 0 errors.

## Validation

Artifact validation passed for every Phase 6.6 run folder:

- 50 case artifacts per run.
- `summary.json` present.
- `judge_audit_sample.json` present.
- 50/50 automated structural pass for every run.
- Rerank variants `V7`, `V12`, `V10`, and `V5`: 50 rerank successes and 0 fallback.
- Anchor `V2`: 0 rerank enabled, 0 fallback.

Focused tests covered:

- Page-supported citation with noisy section metadata is not a serious citation-support failure.
- Citations remain serious when neither expected page nor section support is hit.
- Checklist text using `safeguard` is not unsafe advice.
- Direct "without lockout/tagout" advice is still unsafe advice.

## Phase 6.6 Results

| Variant | Avg Rule | Serious | Borderline | Warnings | doc@3 | section/page@3 | Avg Sec | Context Tokens | Rerank Succeeded/Fallback | Judge |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `V7` | 81.05 | 7 | 36 | 0 | 0.94 | 0.86 | 6.35 | 1022 | 50/0 | 36/36, 0 errors |
| `V12` | 80.80 | 8 | 35 | 0 | 0.94 | 0.86 | 6.23 | 1053 | 50/0 | 35/35, 0 errors |
| `V10` | 79.52 | 8 | 34 | 1 | 0.94 | 0.86 | 6.12 | 1085 | 50/0 | 34/34, 0 errors |
| `V5` | 78.81 | 9 | 35 | 1 | 0.94 | 0.86 | 6.03 | 1054 | 50/0 | 35/35, 0 errors |
| `V2` | 75.63 | 13 | 29 | 0 | 0.94 | 0.86 | 3.28 | 1978 | 0/0 | 29/29, 0 errors |

## Delta From Phase 6.5

| Variant | Phase 6.5 Avg | Phase 6.6 Avg | Avg Delta | Phase 6.5 Serious | Phase 6.6 Serious | Serious Delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `V7` | 76.58 | 81.05 | +4.47 | 17 | 7 | -10 |
| `V12` | 76.56 | 80.80 | +4.24 | 17 | 8 | -9 |
| `V10` | 75.55 | 79.52 | +3.97 | 17 | 8 | -9 |
| `V5` | 75.32 | 78.81 | +3.49 | 17 | 9 | -8 |
| `V2` | 74.40 | 75.63 | +1.23 | 17 | 13 | -4 |

## Remaining Serious Failures

| Variant | Serious Codes | Serious Case IDs |
| --- | --- | --- |
| `V7` | `wrong_answer`: 6; `citation_does_not_support_answer`: 1 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-02`, `nist-ams300-11-mc-01`, `osha-loto-df-03`, `nist-csf-2-ss-01`, `nist-csf-2-ss-03` |
| `V12` | `wrong_answer`: 7; `citation_does_not_support_answer`: 1 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `osha-loto-df-03`, `nist-csf-2-ss-01`, `nist-csf-2-ss-03` |
| `V10` | `wrong_answer`: 8; `wrong_or_missing_citation`: 1 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `osha-loto-df-03`, `osha-guarding-mc-02`, `nist-csf-2-ss-01` |
| `V5` | `wrong_answer`: 9; `wrong_or_missing_citation`: 1 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-df-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-01`, `osha-loto-df-03`, `osha-loto-ss-01`, `osha-guarding-mc-02`, `nist-csf-2-ss-01` |
| `V2` | `wrong_answer`: 13; `citation_does_not_support_answer`: 1 | `nist-ams300-1-df-04`, `nist-ams300-1-mc-02`, `nist-ams300-11-ss-03`, `nist-ams300-11-mc-02`, `osha-loto-df-03`, `osha-loto-ss-01`, `osha-loto-ss-02`, `osha-guarding-df-04`, `osha-guarding-ss-03`, `osha-guarding-mc-02`, `nist-csf-2-df-03`, `nist-csf-2-ss-01`, `nist-csf-2-mc-02` |

## Interpretation

Phase 6.6 confirms the Phase 6.5 ranking rather than overturning it:

- `V7` remains the provisional champion.
- `V12` remains a close co-lead.
- `V10` remains the third Phase 7 carry-forward candidate.
- `V5` remains a close alternate.
- `V2` remains a useful non-rerank control, but rerank-enabled top candidates now clearly beat it on both score and serious-failure count.

The scoring fairness fix changed the absolute seriousness picture. The Phase 6.5 top-candidate serious counts were inflated by citation-section noise and the `safeguard` unsafe-pattern false positive. After Phase 6.6, remaining serious failures are mostly real answer-quality failures, especially incomplete direct answers and weak section summaries.

Safety/citation result:

- No Phase 6.6 top-candidate run has an `unsafe_advice` serious flag.
- `osha-guarding-mc-01` now scores 97.08 for every Phase 6.6 top candidate and is no longer incorrectly treated as unsafe.
- Citation hard failures are much lower, but not gone. Remaining citation failures are cases where no expected page-or-section support was hit.

Production readiness:

- Phase 6.6 makes the evaluation fairer, but it does not make the system production-ready.
- `V7` still has 7 serious failures out of 50.
- Phase 7 should still run Document Augmentation `V8`/`V13` against `V7`, `V12`, and `V10`, with `V5` as a close alternate and `V2` as an optional clean control.
