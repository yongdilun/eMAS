# eMAS RAG Limited Rollout Runbook

Created: 2026-05-26
Updated: 2026-05-31

Scope: limited school/demo advisory-mode controls for the active `V15B` RAG candidate. This runbook does not approve full production authority, autonomous safety/compliance decisions, live machine-action approval, compliance certification, sign-off, current-state proof, or benchmark remediation.

Active school/demo advisory candidate:

- `V15B` = Corpus-aware multi-query rewrite + hybrid retrieval + rerank + budgeted RSE + evidence cards for citation/facet/debug metadata only.

Rollback candidates:

- `V12` = approved Phase 14 limited advisory baseline while V12 drift is investigated.
- `default` = previous legacy advisory RAG behavior.

## Runtime Path

Production advisory RAG is reached through the Factory Agent planner-owned graph virtual tool `rag_search_documents` and the direct document-knowledge answer path. Both call `RAGPipeline.run(..., route="RAG_ONLY")`.

The advisory selector now defaults to `V15B` for this environment. Keep the explicit local setting in place for clarity:

```powershell
$env:RAG_ADVISORY_VARIANT = "V15B"
```

Rollback to the Phase 14 V12 baseline:

```powershell
$env:RAG_ADVISORY_VARIANT = "V12"
```

Rollback to previous legacy RAG behavior:

```powershell
$env:RAG_ADVISORY_VARIANT = "default"
```

Do not unset the variable as a rollback step because the application default now resolves to `V15B`. The selector does not use eval-only paths, test-artifact paths, augmented indexes, or benchmark artifacts.

## Approved Config

Use this config only for advisory document answers:

| Setting | Value |
| --- | --- |
| Runtime flag | `RAG_ADVISORY_VARIANT=V15B` |
| Operating mode | School/demo advisory RAG only |
| Retrieval | Hybrid vector + BM25/keyword retrieval |
| Query rewrite | Corpus-aware rewrite on for retrieval only; legacy named-standard `query_rewrite` off; generation receives original user query |
| Multi-query retrieval | On, using original plus expanded retrieval fusion |
| Context builder | Budgeted RSE |
| Evidence cards | On for citation/facet/debug metadata only; no evidence-card context replacement |
| Rerank | On |
| Reranker fallback | Off |
| Compression | Off |
| Document Augmentation | Off |
| Judge | Qwen2.5-7B not used for production approval |

## Allowed Answers

`V15B` may answer descriptive, static document questions when it has source support and citations.

Allowed examples:

- Static OSHA/LOTO checklist recall.
- Static training/readiness checklist summaries.
- Static NIST/CSF/AMS/MTConnect document facts.
- Procedure or policy summaries from retrieved documents, with safety caveats and citations.

Static document/checklist recall should still answer with citations. Do not over-refuse these just because the topic is safety-related.

## Required Refusals

`V15B` must refuse:

- Compliance certification.
- Attestation or audit sign-off.
- Approval language such as "say we passed" or "confirm this is compliant."
- Live machine action approval, including start, jog, energize, reenergize, remove lock/tag, or bypass guard.
- Current-state proof that a machine, site, system, deployment, or process is currently safe, secure, available, compliant, or approved.
- Unsupported vendor/platform purchase recommendations from static guidance.

Refusals may summarize the retrieved static evidence, but must say that retrieved documents do not certify the current state or replace qualified safety/compliance review.

## Human Review

Human review is required before safety/compliance answers are used operationally.

Review all answers involving:

- OSHA, LOTO, machine guarding, hazardous energy, maintenance readiness, moving parts, or worker training.
- Compliance, audit, certification, sign-off, approval, vendor selection, or current-state security/safety claims.
- Procedure-style answers where missing steps could change the operational meaning.
- Any answer with weak, broad, missing, or unsupported citations.

Human reviewers should verify the cited page/section supports each material claim before operational use.

## Monitoring Checklist

Inspect advisory RAG logs and graph evidence for:

- `rag_variant` and `rag_config`.
- `rag_retrieval_mode`.
- `rag_context_builder`.
- `rag_rerank_attempted`, `rag_rerank_succeeded`, and `rag_rerank_fallback_used`.
- `rag_citation_count`, `rag_citation_source_ids`, `rag_citation_doc_ids`, `rag_citation_pages`, and `rag_citation_details`.
- `rag_no_evidence_fallback`.
- `rag_boundary_refusal`.
- `rag_latency_ms`.
- `rag_context_token_estimate`.

Track rates separately where possible for answerable prompts, boundary prompts, and unsupported/no-evidence prompts.

## Rollback Triggers

Immediately roll back by setting `RAG_ADVISORY_VARIANT=V12` or `RAG_ADVISORY_VARIANT=default` and restarting the Factory Agent service if any of these appear:

- Unsafe advice appears, especially live machine start/jog/reenergize/lock or tag removal guidance.
- Compliance certification, attestation, sign-off, approval language, or current-state proof appears.
- Citations are missing, broad, or unsupported for material claims.
- Reranker fallback becomes frequent or nonzero without an explicit degraded-mode decision.
- No-evidence fallback rate spikes on answerable static document questions.
- Latency becomes unacceptable for advisory chat use.

After rollback, keep the affected prompts, logs, citations, and source pages for manual review. Do not re-enable `V15B` until the failure class is understood and remediated.

## First-Week Sampling Plan

Sample every day for the first week of limited rollout:

- 10 OSHA/LOTO or machine-guarding answers.
- 10 cybersecurity/compliance or current-state boundary answers.
- 10 static recall answers that should cite documents and not refuse.
- All no-evidence fallback answers from safety/compliance topics.
- All boundary refusal answers that mention certification, sign-off, live status, current state, or approval.
- All responses with zero citations or citation/source-page mismatches.

For each sampled answer, record prompt, answer, cited source IDs/pages, support decision, refusal decision, latency, rerank status, and reviewer notes.

## Known Weak Areas To Watch

- OSHA/LOTO sequence completeness, especially testing/positioning and reenergization sequence coverage.
- Moving-parts checklist synthesis, including training and maintenance/LOTO readiness.
- Weak generic refusals that are safe but not useful enough.
- Citation claim support, especially broad citations that do not localize to the claim-bearing page or section.

## Rollout Status

`V15B` is active only for school/demo advisory RAG under this runbook. Full production authority, autonomous safety/compliance authority, compliance certification, sign-off, live machine-action approval, and current-state proof remain not approved.
