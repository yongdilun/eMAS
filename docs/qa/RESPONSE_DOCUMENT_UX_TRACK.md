# Response Document UX And Final Response Quality Tracker

Branch: `codex/playwright-e2e-plan`
Created: 2026-05-18

## Phase Status

| Phase | Name | Status | Owner | Notes |
| --- | --- | --- | --- | --- |
| 0 | Response gap audit and contract inventory | Not Started | Next agent | Map current final-response, typed presentation, timeline, approval, and frontend rendering paths. |
| 1 | Backend response document schema | Not Started | Next agent | Add additive `response_document.version=1`, `run_steps`, and typed blocks beside existing `presentation`. |
| 2 | Deterministic composer and run steps | Not Started | Next agent | Build backend-owned deterministic response composer with progressive disclosure rules. |
| 3 | Failure recovery response documents | Not Started | Next agent | Add typed failure taxonomy, operator-friendly diagnostic cards, impact summaries, and context-aware next actions. |
| 4 | Frontend response document renderer | Not Started | Next agent | Render block types directly; keep legacy presentation only as missing-document fallback. |
| 5 | Response document reducer and busy-traffic ordering | Not Started | Next agent | Centralize revision ordering, validation, SSE/polling conflict handling, coalescing, and collapse preservation. |
| 6 | Final response quality E2E gate | Not Started | Next agent | Add typed and visible browser checks for multi-step response quality. |
| 7 | Compact approval and progressive disclosure hardening | Not Started | Next agent | Make approval cards compact, stable, expandable, and usable across multi-step workflows. |
| 8 | Mandatory compatibility cleanup | Not Started | Next agent | Retire old frontend decision-making from `presentation` when `response_document` exists. |
| 9 | Release gate and future LLM handoff | Not Started | Next agent | Stabilize gates and document future LLM polish as separate work. |

## Current Blockers

- Current final response UX is not governed by a single response-document contract.
- Multi-step and multi-approval response quality has historically required manual screenshot inspection.
- Existing `presentation` and frontend merge/ranking logic can still create old/new source-of-truth confusion until cleanup is complete.
- Busy traffic can still cause rendering bugs unless response documents include revisions and frontend applies them through one reducer.
- Broken flows such as timeout, validation-loop exhaustion, interrupted SSE, auth denial, or backend failure do not yet have one operator-friendly failure-card standard.

## Open Questions

- Should `response_document` live directly on the snapshot response, timeline terminal event, or both?
- Which backend module should own composition: `session_snapshot_service.py` or a new `response_document_service.py`?
- What exact compact-card record preview count should be standard: 3 or 5?
- Should expanded/collapsed state be keyed by block id, approval id, or operation id?
- Which real LangGraph scenario should be the first non-seeded proof after Prompt A: Prompt B, partial failure, or RAG/source answer?
- What coalescing strategy is best after implementation: next animation frame, 50ms debounce, or 100ms debounce?
- Which failure actions are safe to expose first: retry from checkpoint, check status, start new request, or view diagnostics only?

## Decisions Made

- Final response truth is deterministic backend evidence, not LLM narrative.
- No LLM final-response layer is included in this plan.
- Response output should be typed blocks only; markdown is not the UI contract.
- Backend owns `response_document` and `run_steps`.
- Frontend renders block types and does not infer state/layout from prose when `response_document` exists.
- UX pattern is compact run activity plus short conversational message plus compact action/result cards.
- Completed step evidence stays visible when a later approval is pending.
- Latest pending approval is visually primary.
- Approval cards are compact by default and expandable for records/details.
- Progressive disclosure is the standard: short default, auditable details on demand.
- The first flagship scenario is multi-step two-approval mutation.
- Cover both cascade directions; implement Prompt A first, then Prompt B.
- Any product bug found blocks the phase until fixed.
- Additive migration is allowed only with a mandatory cleanup phase.
- Latest valid `response_document.revision` is the frontend source of truth under busy traffic.
- Backend should prevent stale snapshots, but frontend must still refuse stale documents.
- Do not merge older frontend revisions into newer documents.
- Use both session-level `snapshot_revision` and per-turn `response_document.revision`.
- Highest valid revision wins regardless of SSE or polling transport.
- If `response_document` exists but is invalid, render a safe diagnostic and report/log the contract violation; do not use old `presentation` as fallback.
- Centralized frontend `responseDocumentReducer` or equivalent store update function owns incoming document validation, ordering, coalescing, and collapse preservation.
- Backend owns monotonic response-document revision generation.
- Block ids must be deterministic and derived from operation, approval, step, or source identity.
- Backend owns block lifecycle; frontend does not preserve removed blocks as invented history.
- Busy-traffic tests should use reducer/unit tests plus Playwright event-storm convergence tests and failure artifacts.
- Broken flows render typed operator-friendly failure cards with cause, impact, current state, and next actions.
- Failure handling uses typed failure reasons and deterministic templates.
- Technical diagnostics are collapsed and sanitized by default.
- Failure-card actions are context-aware and gated by safety/retry policy.
- Partial-progress failures show both completed progress and failure impact.

## Flagship Inputs

| ID | Prompt | Purpose |
| --- | --- | --- |
| RD-001 | `change all medium priority job to high then change all high priority job to low` | First flagship. Proves approval 1, approval 2, completed-step preservation, latest pending approval, and final aggregate result. |
| RD-002 | `change all high priority job to low then change all low priority job to medium` | Reverse cascade. Proves original-state semantics and prevents overfitting RD-001. |

## Additional Required Scenario Groups

| Group | Example input | Required proof |
| --- | --- | --- |
| Partial failure | Existing SO-009 partial bulk failure flow | Response document shows per-row success/failure and never claims full success. |
| Rejected approval | Approval 1 accepted, approval 2 rejected | Completed step remains visible; rejected step is compact diagnostic/history card; no hidden mutation. |
| Expired approval | Approval 2 timeout/expiry | Expired card is compact; stale approval cannot mutate; no fake final success. |
| Cancelled run | User cancels active run | Activity and final block show cancelled state without stale active copy. |
| RAG/source answer | `What LOTO procedure applies before working on M-CNC-01?` | Knowledge answer uses `source_list` block and does not render as mutation or approval. |
| Read-only status | `What is the status of M-CNC-01?` | Simple answer uses status/result blocks without approval UI. |
| Long table/list | Large job list or structured result | Compact default preview, expandable table, no UI takeover. |
| Diagnostic | Empty final response or backend failure | Diagnostic block appears; no fake success or blank answer. |
| Planner timeout | Planner or LLM timeout before final answer | Operator-friendly failure card with safe retry/check-status action and collapsed technical detail. |
| Validation loop | Repeated planner/decision-guard repair exhaustion | Failure card explains the run stopped before unsafe execution and gives next action. |
| Tool failure | Tool timeout, schema error, or HTTP 500 | Failure card states whether data changed, whether retry is safe, and what to check next. |
| Partial-progress failure | Approval 1 completed, later step breaks | Completed work and incomplete work are both visible in one diagnostic response. |

## Phase 0 Checklist

- [ ] Inventory backend response creation paths.
- [ ] Inventory frontend rendering paths.
- [ ] Map current `presentation` usage and legacy phrase/table inference.
- [ ] Map approval card rendering and bundle UI paths.
- [ ] Map timeline/SSE to activity UI behavior.
- [ ] Document current tests that already cover response quality.
- [ ] Document missing tests.
- [ ] Update this tracker with audit findings.

## Phase 1 Checklist

- [ ] Define backend `ResponseDocument` schema.
- [ ] Define backend `RunStep` schema.
- [ ] Define response block schema.
- [ ] Add additive `response_document` to snapshot/final response payload.
- [ ] Add agreement tests between `presentation` and `response_document`.
- [ ] Keep frontend behavior unchanged.

## Phase 2 Checklist

- [ ] Implement deterministic response composer.
- [ ] Build `run_steps` from execution/timeline/approval/audit evidence.
- [ ] Implement block-order rules.
- [ ] Implement compact preview/list/table rules.
- [ ] Implement multi-step aggregation rules.
- [ ] Implement pending-approval rules preserving completed steps.
- [ ] Implement final completion rules aggregating all completed steps.
- [ ] Add backend tests for RD-001 and RD-002.
- [ ] Add backend tests for partial failure, rejected, expired, cancelled, RAG/source, read-only, long table, and diagnostic states.

## Phase 3 Checklist

- [ ] Define typed failure taxonomy.
- [ ] Define deterministic failure templates.
- [ ] Add failure card block fields for reason, severity, title, user message, impact, next actions, technical details, and collapsed state.
- [ ] Map planner timeout and planner validation loop.
- [ ] Map LLM timeout and answer timeout.
- [ ] Map tool timeout, tool HTTP error, and tool schema error.
- [ ] Map approval expired, rejected, and stale.
- [ ] Map network disconnect and SSE interruption.
- [ ] Map auth denied and cancelled by user.
- [ ] Map partial commit failure and unknown failure.
- [ ] Add safety/retry policy for context-aware actions.
- [ ] Add tests proving technical details are collapsed and sanitized.
- [ ] Add tests proving partial-progress failure shows completed and incomplete work together.
- [ ] Add tests proving no blank/raw/generic failure response for broken flows.

## Phase 4 Checklist

- [ ] Add frontend response-document normalizer.
- [ ] Add response document renderer component.
- [ ] Render run activity block.
- [ ] Render short message block.
- [ ] Render compact approval card.
- [ ] Render completed step card.
- [ ] Render result summary/table/source/diagnostic blocks.
- [ ] Preserve completed steps when latest approval is pending.
- [ ] Keep latest pending approval primary.
- [ ] Keep legacy `presentation` fallback only when `response_document` is absent.
- [ ] Add component/unit tests.

## Phase 5 Checklist

- [ ] Add centralized frontend `responseDocumentReducer` or equivalent store update function.
- [ ] Add frontend response-document validation before rendering.
- [ ] Apply `snapshot_revision`, `document_id`, `turn_id`, and `response_document.revision` ordering rules.
- [ ] Ignore stale lower revisions from SSE.
- [ ] Ignore stale lower revisions from polling.
- [ ] Detect same-revision conflicting content and show/log a contract violation diagnostic.
- [ ] Coalesce fast update bursts without forcing fake progress delays.
- [ ] Preserve expanded/collapsed state by stable block id.
- [ ] Prevent old turns/documents from updating active turn UI.
- [ ] Add reducer tests for stale, duplicate, conflicting, invalid, and cross-turn documents.
- [ ] Add reducer tests for collapse-state preservation.
- [ ] Add Playwright event-storm tests for fast progress to approval pending.
- [ ] Add Playwright event-storm tests for final complete followed by stale pending.
- [ ] Add Playwright event-storm tests for SSE/polling disagreement where highest revision wins.
- [ ] Add Playwright event-storm tests for approval 1 complete then approval 2 pending.
- [ ] Record trace/video/screenshot artifact policy for failures.

## Phase 6 Checklist

- [ ] Add seeded browser test for RD-001.
- [ ] Add seeded browser test for RD-002.
- [ ] Add visible DOM assertions for activity order.
- [ ] Add visible DOM assertions for short conversational message.
- [ ] Add visible DOM assertions for compact approval cards.
- [ ] Add visible DOM assertions for completed step preservation.
- [ ] Add final aggregate result assertions.
- [ ] Add forbidden stale text/current-state assertions.
- [ ] Add collapse/expand stability assertions.
- [ ] Add focused real LangGraph proof for the highest-risk scenario.

## Phase 7 Checklist

- [ ] Cap approval card default height.
- [ ] Limit default affected-record preview to top 3-5 records.
- [ ] Keep approve/reject buttons visible.
- [ ] Move full affected-record table into details.
- [ ] Render completed/rejected/expired approval cards as compact history.
- [ ] Add mobile/desktop layout checks.
- [ ] Add no-overlap/no-overflow checks where feasible.

## Phase 8 Checklist

- [ ] Make `response_document` the primary source for all new sessions.
- [ ] Isolate old `presentation` fallback behind a missing-document check.
- [ ] Remove old state/layout decisions from frontend paths where possible.
- [ ] Add guardrail against new phrase-based state inference.
- [ ] Update docs with compatibility retirement policy.
- [ ] Rerun full response and release gates.

## Phase 9 Checklist

- [ ] Run backend oracle gate.
- [ ] Run frontend unit/component tests.
- [ ] Run mocked browser gate.
- [ ] Run seeded browser oracle gate.
- [ ] Run real LangGraph critical gate.
- [ ] Record accepted gaps.
- [ ] Document that LLM polish/Promptfoo is future separate work.

## Commands Run

```powershell
git status --short --branch
Test-Path "docs/qa/RESPONSE_DOCUMENT_UX_PLAN.md"; Test-Path "docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md"
Get-Content "docs/qa/HARDCODE_REDUCTION_TRACK.md" | Select-Object -First 25
rg -n "PresentationResponse|presentation|run_steps|response_document|FactoryAgentChatPanel|turnAssembler|activityTimeline" factory-agent/factory_agent/schemas.py factory-agent/factory_agent/services/session_snapshot_service.py "eMas Front/src/components/features/chat" -g "!**/node_modules/**"
```

## Test Results

- Documentation creation only so far.
- No product tests have been run for this new plan.

## Files Changed

- `docs/qa/RESPONSE_DOCUMENT_UX_PLAN.md`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`

## Next Action

Start Phase 0. Do not implement UI or backend schema before the current response paths and test gaps are documented in this tracker.
