# eMAS RAG Limited Rollout Runbook

Created: 2026-05-26

Scope: limited advisory-mode rollout controls for the approved `V12` RAG candidate. This runbook does not approve full production authority, autonomous safety/compliance decisions, live machine-action approval, or benchmark remediation.

Approved candidate:

- `V12` = Query Rewrite + Hybrid Search + RSE + Rerank.

## Runtime Path

Production advisory RAG is reached through the Factory Agent planner-owned graph virtual tool `rag_search_documents` and the direct document-knowledge answer path. Both call `RAGPipeline.run(..., route="RAG_ONLY")`.

Phase 15 added a production-facing advisory selector:

```powershell
$env:RAG_ADVISORY_VARIANT = "V12"
```

Rollback to previous RAG behavior:

```powershell
$env:RAG_ADVISORY_VARIANT = "default"
```

Unset the variable for the same rollback behavior. The selector does not use eval-only paths, test-artifact paths, augmented indexes, or benchmark artifacts.

## Approved Config

Use this config only for advisory document answers:

| Setting | Value |
| --- | --- |
| Runtime flag | `RAG_ADVISORY_VARIANT=V12` |
| Operating mode | Advisory RAG only |
| Retrieval | Hybrid vector + BM25/keyword retrieval |
| Query rewrite | On for retrieval only; generation receives original user query |
| Context builder | RSE |
| Rerank | On |
| Reranker fallback | Off unless explicitly accepted as a degraded rollout state |
| Compression | Off |
| Document Augmentation | Off |
| Judge | Qwen2.5-7B not used for production approval |

## Allowed Answers

`V12` may answer descriptive, static document questions when it has source support and citations.

Allowed examples:

- Static OSHA/LOTO checklist recall.
- Static training/readiness checklist summaries.
- Static NIST/CSF/AMS/MTConnect document facts.
- Procedure or policy summaries from retrieved documents, with safety caveats and citations.

Static document/checklist recall should still answer with citations. Do not over-refuse these just because the topic is safety-related.

## Required Refusals

`V12` must refuse:

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

Immediately roll back by setting `RAG_ADVISORY_VARIANT=default` and restarting the Factory Agent service if any of these appear:

- Unsafe advice appears, especially live machine start/jog/reenergize/lock or tag removal guidance.
- Compliance certification, attestation, sign-off, approval language, or current-state proof appears.
- Citations are missing, broad, or unsupported for material claims.
- Reranker fallback becomes frequent or nonzero without an explicit degraded-mode decision.
- No-evidence fallback rate spikes on answerable static document questions.
- Latency becomes unacceptable for advisory chat use.

After rollback, keep the affected prompts, logs, citations, and source pages for manual review. Do not re-enable `V12` until the failure class is understood and remediated.

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

Limited advisory rollout is conditionally approved only under this runbook. Full production authority remains not approved.
