# eMAS RAG Evaluation Corrected Run Addendum

Created: 2026-05-25

## Scope

Phase 6.5 corrected unfair Run 1 comparison defects, then reran the affected comparison set. This phase did not implement Document Augmentation `V8`/`V13`, did not change the 50-question bank, did not tune prompts or expected answers, and kept serious-failure scoring strict.

Required rerank variants rerun:

- `V1`: `run1-corrected-20260525-v01`
- `V3`: `run1-corrected-20260525-v03`
- `V5`: `run1-corrected-20260525-v05`
- `V6`: `run1-corrected-20260525-v06`
- `V7`: `run1-corrected-20260525-v07`
- `V10`: `run1-corrected-20260525-v10`
- `V11`: `run1-corrected-20260525-v11`
- `V12`: `run1-corrected-20260525-v12`

Anchor variants rerun:

- `V0`: `run1-corrected-20260525-v00`
- `V2`: `run1-corrected-20260525-v02`
- `V4`: `run1-corrected-20260525-v04`
- `V9`: `run1-corrected-20260525-v09`

All corrected runs used `--judge` against the same local OpenAI-compatible Qwen2.5 7B judge endpoint used in Run 1. Judge calls completed without runtime errors.

## Fix Summary

- Replaced the broken FlagEmbedding integration with a direct Transformers cross-encoder wrapper for `BAAI/bge-reranker-v2-m3`.
- Rerank-enabled pipeline runs now fail loudly by default if reranking cannot run.
- Reranker fallback is allowed only through explicit configuration and is recorded in per-case artifacts and summary aggregates.
- Per-case artifacts now record rerank traces, including attempted/succeeded/fallback flags, selected chunk IDs, and rerank scores.
- Citation artifacts now preserve supporting chunk IDs, supporting pages, supporting sections, and evidence snippets so `citation_does_not_support_answer` can be audited against the full support set.
- OSHA/live-status boundary answers now require a concrete caution and a safe next step rather than generic "not enough evidence" wording.
- Compression now has focused coverage proving query and child evidence are preserved in representative cases.

## Artifact Validation

Validation passed for every corrected run folder:

- 50 case JSON artifacts per run.
- `summary.json` present per run.
- `judge_audit_sample.json` present per run.
- All runs: 50/50 automated pass.
- All judge-requested cases completed with 0 judge errors.
- Rerank variants `V1`, `V3`, `V5`, `V6`, `V7`, `V10`, `V11`, and `V12`: 50 enabled, 50 attempted, 50 succeeded, 0 fallback.
- Anchor variants `V0`, `V2`, `V4`, and `V9`: 0 rerank enabled, 0 attempted, 0 fallback.
- Artifacts with sources include citation support metadata and evidence chunks.

## Corrected Results

| Variant | Avg Rule | Serious | Borderline | Warnings | doc@3 | section/page@3 | Avg Sec | Context Tokens After Compression | Rerank Succeeded/Fallback | Judge |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `V7` | 76.58 | 17 | 35 | 0 | 0.94 | 0.86 | 6.40 | 1022 | 50/0 | 35/35, 0 errors |
| `V12` | 76.56 | 17 | 34 | 0 | 0.94 | 0.86 | 6.55 | 1053 | 50/0 | 34/34, 0 errors |
| `V10` | 75.55 | 17 | 33 | 1 | 0.94 | 0.86 | 6.29 | 1085 | 50/0 | 33/33, 0 errors |
| `V5` | 75.32 | 17 | 33 | 1 | 0.94 | 0.86 | 7.82 | 1054 | 50/0 | 33/33, 0 errors |
| `V2` | 74.40 | 17 | 28 | 0 | 0.94 | 0.86 | 3.06 | 1978 | 0/0 | 28/28, 0 errors |
| `V3` | 72.58 | 19 | 30 | 1 | 0.94 | 0.86 | 8.55 | 830 | 50/0 | 30/30, 0 errors |
| `V1` | 72.37 | 18 | 35 | 1 | 0.96 | 0.78 | 8.07 | 696 | 50/0 | 35/35, 0 errors |
| `V4` | 71.94 | 19 | 28 | 0 | 0.94 | 0.86 | 3.33 | 2363 | 0/0 | 28/28, 0 errors |
| `V0` | 70.93 | 20 | 31 | 0 | 0.96 | 0.78 | 3.02 | 1623 | 0/0 | 31/31, 0 errors |
| `V9` | 70.91 | 20 | 26 | 0 | 0.94 | 0.86 | 3.45 | 2445 | 0/0 | 26/26, 0 errors |
| `V11` | 70.84 | 21 | 36 | 1 | 0.94 | 0.86 | 5.97 | 609 | 50/0 | 36/36, 0 errors |
| `V6` | 69.45 | 22 | 36 | 1 | 0.94 | 0.86 | 7.99 | 609 | 50/0 | 36/36, 0 errors |

## Delta From Original Run 1

| Variant | Avg Rule Delta | Serious Delta |
| --- | ---: | ---: |
| `V0` | +5.19 | -7 |
| `V1` | +11.24 | -11 |
| `V2` | +4.73 | -6 |
| `V3` | +4.59 | -5 |
| `V4` | +2.73 | -4 |
| `V5` | +8.95 | -9 |
| `V6` | +5.47 | -4 |
| `V7` | +7.23 | -5 |
| `V9` | +3.89 | -5 |
| `V10` | +10.39 | -10 |
| `V11` | +6.83 | -5 |
| `V12` | +6.74 | -4 |

The corrected runs reduce total serious-failure flags across the 12-run comparison from 386 to 259. Most of that improvement comes from fairer citation support auditing and safer boundary behavior, not from loosening serious-failure criteria.

Failure-code deltas across the full corrected comparison:

- `citation_does_not_support_answer`: 190 to 99.
- `wrong_answer`: 179 to 145.
- `wrong_or_missing_citation`: 10 to 6.
- `unsafe_advice`: 7 to 9.

The small increase in automated `unsafe_advice` flags should be manually reviewed before production decisions. Strict hard-failure scoring remains in place.

## Decision Update

The provisional champion changes from `V12` to `V7`, but the margin is tiny: 76.5778 vs 76.5584 average rule score, with both at 17 serious failures. Treat `V7` and `V12` as co-leads rather than a decisive separation.

Top variants to carry into Phase 7:

1. `V7` - Query Rewrite + Hybrid Search + Small-to-Big + Rerank.
2. `V12` - Query Rewrite + Hybrid Search + RSE + Rerank.
3. `V10` - Hybrid Search + RSE + Rerank.

`V5` is a near alternate to `V10` and should be considered if Phase 7 budget allows four corrected Run 1 carry-forwards. `V2` remains useful as a clean non-rerank hybrid control, but it is no longer a top-three corrected candidate.

## Interpretation

Reranker fix:

- The reranker now really runs for rerank-enabled variants.
- The old Run 1 rerank caveat is resolved for corrected artifacts.
- The corrected ranking changed: `V7` narrowly overtook `V12`, and true rerank variants `V10` and `V5` moved into the top cluster above the non-rerank control `V2`.
- Some improvement also comes from citation/evidence and safety-boundary artifact fixes that apply to anchors, so the reranker is not the only cause of score increases.

Safety and citation:

- Citation-related serious-failure flags dropped sharply after preserving chunk/page/section support in artifacts.
- Safety-case serious flags dropped from 91 safety cases with at least one serious failure to 75, while average safety-case rule score increased from 72.71 to 76.73.
- OSHA live-status boundary artifacts now record concrete caution and safe next-step checks. The `osha-loto-un-01` rule score improved from 61.11 to 72.78 for every variant.
- Serious-failure scoring remains strict; the corrected champion still has 17 serious failures out of 50 and is not production-ready.

Compression:

- Compression remains quality-negative after the evidence-preservation fix.
- `V6` vs `V5`: 69.45 vs 75.32 average rule, 22 vs 17 serious failures, with context reduced from 1054 to 609 tokens.
- `V11` vs `V10`: 70.84 vs 75.55 average rule, 21 vs 17 serious failures, with context reduced from 1085 to 609 tokens.
- Focused compression tests show required evidence is preserved in representative cases, so the corrected benchmark suggests the remaining quality loss is real rather than an obvious evidence-dropping bug.

## Phase 7 Guidance

Do not start Phase 7 until this corrected baseline is accepted. When Phase 7 starts, compare Document Augmentation `V8` and `V13` against the corrected top candidates, preferably `V7`, `V12`, and `V10`, with `V2` only as an optional clean control.

The corrected champion is still provisional. Production rollout remains blocked by serious failures, citation-support sensitivity, safety hard-fail review, and the need to test Document Augmentation.
