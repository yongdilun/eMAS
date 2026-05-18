# Response Document UX And Final Response Quality Tracker

Branch: `codex/playwright-e2e-plan`
Created: 2026-05-18

## Phase Status

| Phase | Name | Status | Owner | Notes |
| --- | --- | --- | --- | --- |
| 0 | Response gap audit and contract inventory | Completed | Codex | Current backend/frontend response paths, existing coverage, missing gates, blockers, and Phase 1 starting point documented below. |
| 1 | Backend response document schema | Done | Codex | Added additive backend `response_document.version=1`, `run_steps`, typed blocks, snapshot revision, and backend contract tests. |
| 2 | Deterministic composer and run steps | Done | Codex | Added backend-owned deterministic composer, run-step evidence, completed-step preservation, read/RAG/no-result blocks, and Phase 2 contract tests. |
| 3 | Failure recovery response documents | Done | Codex | Added typed failure taxonomy, operator-friendly diagnostic cards, sanitized technical details, impact/retry policies, and failure-focused backend tests. |
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
- Frontend rendering still needs Phase 4/5 work before typed response-document diagnostics become the primary visible UI contract.
- Phase 0 audit found no additive `response_document`, no `snapshot_revision`, and no frontend response-document reducer. Existing `cursor` protects notification invalidation only, while `presentation` and activity rows can still be assembled independently.
- Phase 0 audit found frontend table/detail selection still depends on legacy bundle/table heuristics and phrase checks. This is a blocker for retiring `presentation` as the primary UI contract, but it should be fixed in later implementation phases, not Phase 0.

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

- [x] Inventory backend response creation paths.
- [x] Inventory frontend rendering paths.
- [x] Map current `presentation` usage and legacy phrase/table inference.
- [x] Map approval card rendering and bundle UI paths.
- [x] Map timeline/SSE to activity UI behavior.
- [x] Document current tests that already cover response quality.
- [x] Document missing tests.
- [x] Update this tracker with audit findings.

## Phase 0 Audit Findings

Date: 2026-05-18

Phase 0 was documentation-only. No backend schema, UI renderer, reducer, or product behavior was implemented.

### Files Inspected

- `docs/qa/RESPONSE_DOCUMENT_UX_PLAN.md`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `factory-agent/factory_agent/schemas.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/services/planner_service.py`
- `factory-agent/factory_agent/services/execution_service.py`
- `factory-agent/factory_agent/api/routers/messages.py`
- `factory-agent/factory_agent/api/routers/events.py`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js`
- `eMas Front/src/components/features/chat/factory-agent/presentationContract.js`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- Current related tests under `factory-agent/tests` and `eMas Front/e2e`

### Backend Response Creation Paths

- API contract lives in `factory-agent/factory_agent/schemas.py`.
  - `PresentationResponse` is the current typed display contract with `kind`, `state`, `operation_id`, `approval_id`, `summary`, `rows`, `sources`, `diagnostics`, and `invariants`.
  - `TimelineEventResponse.presentation` attaches typed presentation to selected timeline events.
  - `SessionSnapshotResponse.presentation` is described as authoritative typed presentation for the current snapshot/final response.
  - `SessionSnapshotResponse.cursor` is the current monotonic event cursor for notification SSE staleness. There is no `snapshot_revision` or per-turn document revision yet.
  - There is no `ResponseDocument`, `RunStep`, typed block schema, or `response_document` payload yet.

- Final text is assembled mostly in `factory-agent/factory_agent/services/session_snapshot_service.py`.
  - Conversation/RAG assistant messages become `session_completed` timeline events.
  - Completed sessions without a latest completion event synthesize `completed:{session_id}`.
  - Completion synthesis chooses a useful assistant message, generic completion message, or a useful latest tool result via `_operator_result_content_for_completion`.
  - Several filters prevent raw JSON, plan-like text, approval-wait text, and generic tool completion from winning.
  - Tool-result text is produced from stored tool messages, `PlanStep.result_summary`, `summarize_tool_result`, or fallback strings such as `<tool> completed`.

- Typed `presentation` is derived in `session_snapshot_service.py`.
  - `_derive_snapshot_presentation` chooses pending approval, expired approval, rejected approval, blocked, partial failure, failed, empty final response, completed mutation, knowledge answer, completed answer, or non-terminal diagnostic.
  - `_presentation_for_event` derives per-event typed presentations for `approval_required`, `approval_decided`, and `tool_result`.
  - `_attach_typed_presentations_to_events` attaches the snapshot presentation to the latest terminal event and per-event presentations elsewhere.
  - Row evidence comes from `_rows_from_steps`, `_rows_from_tool_events`, `_approval_rows_from_args`, and `_operation_rows_from_result`.

- Failed/blocked/timeout/cancelled/expired states are converted through several paths.
  - `ExecutionService.run_langgraph_session` maps planner clarification to `BLOCKED`, planner rejected to `BLOCKED` plus HTTP 400, and planner backend/transient failures to `FAILED` plus HTTP 503.
  - `messages.py` handles user cancel commands by marking pending work skipped/rejected, setting session status to `IDLE`, and storing the cancellation error.
  - `session_snapshot_service.py` converts `BLOCKED` to `session_blocked`, `FAILED` to `session_failed`, user-cancelled state to a cancellation-flavored `session_failed`, and expired/rejected approvals to typed presentation states.
  - Timeout and transient failures are recognized in `planner_service.py` via `_is_transient_exception`, but Phase 0 found no typed failure taxonomy or operator failure-card template yet.

- Approval bundle UI data is created before snapshot rendering.
  - Current dedicated tests point to `factory_agent.graph.approval_summary.build_job_priority_bundle_uiview` and `build_approval_required_payload`.
  - Snapshot approval rows read `approval.args.bundle_ui.rows`, `preview`, or `staged_writes` through `_approval_rows_from_args`.
  - Timeline approval events expose `details.args`, `details.tool`, `details.input_schema`, `missing_required`, `side_effect_level`, and `expires_at`.

- SSE/polling snapshot payloads are assembled from snapshots.
  - `events.py` has three streams:
    - `/events/semantic` polls snapshots every 1s and emits timeline-derived semantic events plus resume markers and heartbeats.
    - `/events/activity` polls snapshots every 1s and emits server activity steps with signature dedupe and optional fault injection.
    - `/events` notification stream polls snapshots every 0.5s and emits `snapshot_invalidated` and `phase_changed` frames when `cursor` or `phase` changes.
  - Frontend still re-fetches full snapshots after notification invalidation. Activity SSE updates only the activity strip.
  - No backend stream currently emits a typed response-document revision.

### Frontend Rendering Paths

- `presentation` is normalized in `presentationContract.js`.
  - `normalizeTypedPresentation` sanitizes shape, rows, sources, diagnostics, and invariants.
  - `summaryFromTypedPresentation`, `typedPresentationIsAuthoritative`, `tablePresentationFromTypedPresentation`, and `activityStepFromTypedPresentation` convert typed presentation into text, tables, and activity rows.

- Snapshot state enters the UI in `useFactoryAgentChat.js`.
  - `applySnapshot` sets `session`, `plan`, `steps`, `timeline`, `presentation`, `pendingApproval`, `resumeHint`, and `activitySteps`.
  - Activity steps prefer `snapshot.activity_steps`; fallback builds steps from snapshot timeline and presentation.
  - Active-stream snapshots union server activity rows by id with existing rows; terminal snapshots finalize historical rows.
  - There is no centralized document reducer, revision comparison, or invalid-document diagnostic path.

- Turn summary is chosen in `turnAssembler.js`.
  - `assembleFactoryAgentTurns` groups timeline events by turn, merges event presentations, then applies the snapshot presentation to the latest turn.
  - `presentationMergeRank` ranks snapshot presentation above terminal events, pending approval, failures, tool results, and plan events.
  - `computeFactoryAgentTurnSummary` prefers authoritative typed presentation but can fall back through approval, terminal, plan, tool, and phrase-based heuristics.
  - The function still strips approval-wait phrases and checks for plan-like, raw JSON, interrupt-bundle, generic completion, and stale approval text.

- Timeline/activity rows are built in `activityTimelineUtils.js`.
  - `buildActivityStepsFromSnapshot` prefers operation-scoped timeline events, suppresses premature `session_completed` while active/pending, injects status-based rows, and adds typed-presentation rows for non-completed terminal states.
  - `buildStepsFromEventsOperational` creates operator activity rows from timeline event type, approval position, and tool result ordering.
  - `finalizeHistoricalActivityStates`, `stripPrematureTerminalActivitySteps`, and `injectExecutionSummaryFromPlanSteps` try to prevent stale `Current` rows and missing execution evidence.

- Approval cards and affected records render in `FactoryAgentChatPanel.jsx`.
  - `AssistantTurnBubble` renders `ActivityTimeline`, optional resume banner, streamed summary, `TablePresentation`, `TurnDetails`, confirmation options, and `ApprovalCard`.
  - `pendingApprovalVisibleSummary` chooses `bundle_ui.headline`, compacted risk summary, or "Waiting for approval."
  - `showApprovalCard` is tied to `pendingApproval`, latest turn ownership, `WAITING_APPROVAL`, and resume state.
  - Full approval card implementation lives in `ApprovalCard`; Phase 0 did not change it.

- Tables/lists/details are inferred in `FactoryAgentChatPanel.jsx` and `turnAssembler.js`.
  - `bundleUiPresentationFromTurn` chooses pending approval bundle, decided/stashed bundle, or latest approval-required event bundle.
  - `getLatestToolPresentation` prefers typed mutation/partial-failure table presentation, otherwise scans latest tool presentation tables and can skip tables that contradict summary text.
  - `buildUserDetailLines` collects diagnostics, plan explanation, tool content, approval content, and terminal reason, then dedupes and truncates.
  - `summarizeToolResult` in `turnAssembler.js` infers list/table summaries from result rows, `details.presentation.table.rows`, ids, `_summary`, `summary`, `message`, `detail`, and `status`.

- Stale text or old presentation can still override newer state in these spots.
  - `presentationMergeRank` is rank-based, not revision-based. A high-rank stale snapshot presentation can still win if the backend sends it.
  - `applySnapshot` accepts every fetched snapshot for the requested session without comparing cursor/revision against current state.
  - Activity stream rows merge by id/signature and timestamp, but there is no session/document revision guard for out-of-order full snapshots.
  - `bundleTableByApprovalIdRef` intentionally preserves approval bundle tables after decision, which helps avoid evidence loss but can also preserve old evidence until later logic hides it.
  - `useStagedAssistantSummary` delays summary changes for progress staging, so very fast backend state changes can temporarily display older text.
  - Table contradiction checks and summary heuristics can hide stale tables, but they are phrase/data-shape heuristics rather than a contract.

### Existing Test Coverage

- Backend contract coverage already exists for current `presentation` behavior.
  - `factory-agent/tests/test_typed_snapshot_presentation_contract.py` covers pending approval over stale success text, rejected, expired, partial failure, successful multi-approval rows, cancelled, knowledge-source presentation, empty final response diagnostic, and failed-over-stale-success presentation.
  - `factory-agent/tests/test_snapshot_timeline_final_response_contract.py` covers completion projection helpers and stateful oracle invariants for final response timing, approval ids, timeline/SSE ordering, committed jobs, and final response phrases.
  - `factory-agent/tests/test_approval_bundle_ui.py` covers job-priority approval bundle UI payload shape and headline/row evidence.
  - Related backend tests also include `test_event_stream_runtime.py`, `test_phase7_api_ui_alignment.py`, `test_summary_bundle.py`, `test_langgraph_state_machine_oracles.py`, and `test_hardcode_guardrails.py`.

- Frontend/Playwright coverage already protects many legacy visible behaviors.
  - `eMas Front/e2e/specs/chat-fixtures.spec.js` covers backend unavailable without fake success, empty completed assistant content not reusing old answer, typed rejected presentation suppressing stale success, typed pending approval over stale completion text, and typed knowledge sources.
  - `chat-sse-activity.spec.js` covers ordered activity stream rows and final-answer gating until completed snapshot state.
  - `chat-sse-notification.spec.js` covers notification SSE invalidation and final completion.
  - `chat-stream-errors.spec.js` covers malformed SSE recovery, execute 409 retry, non-terminal active busy state with no fake final answer, and notification stream-drop fallback without final success.
  - `full-stack-sse-hard.spec.js` covers out-of-order/duplicate SSE not regressing phase or duplicating visible activity.
  - `full-stack-data-integrity.spec.js` covers seeded approval chains, original-state semantics, approval rejection, refresh during active approval, stale/expired approval safety, cross-surface agreement, partial/failure cases, and stream-drop polling recovery.
  - `real-langgraph-critical.spec.js` covers real LangGraph two-approval workflows, no premature `Run complete`, final aggregation for the SO-041 scenario, and visible stale-copy exclusions.

### Missing Coverage For New Response-Document Plan

- No backend tests assert a `response_document` exists, validates, or agrees with `presentation`.
- No tests cover `response_document.revision`, `snapshot_revision`, document identity, turn identity, or operation identity.
- No frontend unit tests exist for a centralized response-document reducer because the reducer does not exist yet.
- No tests cover invalid existing `response_document` rendering a safe diagnostic instead of falling back to `presentation`.
- No tests cover same-revision conflicting document content.
- No tests cover higher document revision winning across polling/SSE disagreement.
- No tests cover cross-turn/cross-document stale response documents being ignored.
- No tests assert collapse state keyed by stable block id across accepted document revisions.
- No response-document renderer tests cover block types such as `run_activity`, `short_message`, `approval_card`, `completed_step`, `result_summary`, `result_table`, `source_list`, `warning`, and `diagnostic`.
- Existing browser tests cover final text and some visible exclusions, but they do not yet assert compact default approval-card height, top 3-5 affected records, expandable full details, or completed-step evidence preserved beside approval 2 as typed blocks.
- Failure tests do not yet assert typed failure-card fields for cause, impact, changes applied, incomplete steps, safe retry policy, next actions, and collapsed sanitized technical details.
- Busy traffic coverage exists for activity/SSE, but not for full response-document event storms or final-then-stale-pending document downgrades.

### Known Bug Classes Mapped To Current Paths

- Missing multi-step conclusion:
  - Backend final text synthesis in `session_snapshot_service.py` and frontend `computeFactoryAgentTurnSummary` can still choose one terminal/tool summary. Existing seeded/real tests cover some cascades, but typed block aggregation is missing.

- Approval 2 overwriting approval 1 evidence:
  - Snapshot presentation has one primary `approval_id`; frontend displays latest pending approval as primary and stashes decided bundle tables by approval id. There is no typed completed-step block guaranteeing approval 1 evidence remains visible during approval 2.

- Stale read summary overriding mutation result:
  - Backend filters plan-like/generic/approval-wait text and frontend has table contradiction checks, but both are heuristic. A response document should make mutation result blocks authoritative.

- Approval card taking too much chat space:
  - `ApprovalCard` plus `TablePresentation` and bundle rows can still dominate the bubble. Existing plan calls for compact preview, but Phase 0 found no response-document-driven compact card contract yet.

- Collapse reopens after polling/SSE:
  - Current table collapse is derived from `presentation`, `pendingApproval`, and `hasServerDecidedApproval`. There is no reducer-owned collapse state keyed by stable block id.

- Stale `Current` activity row:
  - `finalizeHistoricalActivityStates`, `stripPrematureTerminalActivitySteps`, and `injectExecutionSummaryFromPlanSteps` mitigate this. However, activity rows are still built separately from final response state and do not share a response-document revision.

- Timeout/failure shows vague or ugly response:
  - `planner_service.py` classifies transient failures and `ExecutionService` maps them to `FAILED`, but snapshot presentation only exposes generic diagnostic fields. There is no operator-friendly typed failure taxonomy or action policy.

- Busy traffic/out-of-order SSE or polling rendering stale UI:
  - Notification SSE uses `cursor`, activity SSE dedupes by row signature, and tests cover some out-of-order activity behavior. Full snapshots and typed response surface updates do not yet have per-document revision ordering.

### Phase 0 Decisions

- Do not modify product code in Phase 0.
- Do not add schema fields until Phase 1.
- Keep `PresentationResponse` as the audited legacy contract that Phase 1 must agree with.
- Phase 1 should add response-document schemas in `schemas.py` and assemble an additive placeholder/minimal document in the snapshot path without changing frontend rendering.
- Phase 2 should own deterministic composition in a new `response_document_service.py` unless implementation proves it is small enough to keep `session_snapshot_service.py` readable.
- Keep `cursor` as existing notification invalidation evidence, but add explicit `snapshot_revision`/document revision rather than overloading activity ids or timeline ordering.
- Treat existing phrase/table heuristics as migration risks to isolate in Phase 8, not as contracts to copy into the response-document renderer.

### Recommended Phase 1 Starting Point

Start with `factory-agent/factory_agent/schemas.py` and `factory-agent/factory_agent/services/session_snapshot_service.py`:

- Add additive Pydantic schemas for `ResponseDocument`, `RunStep`, and response blocks.
- Add `response_document` to `SessionSnapshotResponse` while keeping `presentation` unchanged.
- Use a minimal deterministic mapper from existing `SessionSnapshotResponse.presentation`, `activity_steps`, `pending_approval`, and `timeline` so tests can assert presence and agreement without changing UI.
- Add `factory-agent/tests/test_response_document_contract.py` covering schema presence, version, identity, state alignment with `presentation`, pending approval, completed mutation, rejected/expired/cancelled/failed diagnostics, and knowledge sources.
- Defer frontend use, revision conflict behavior, compact renderer, and reducer behavior to later phases.

## Phase 1 Checklist

- [x] Define backend `ResponseDocument` schema.
- [x] Define backend `RunStep` schema.
- [x] Define response block schema.
- [x] Add additive `response_document` to snapshot/final response payload.
- [x] Add agreement tests between `presentation` and `response_document`.
- [x] Keep frontend behavior unchanged.

## Phase 1 Implementation Notes

Date: 2026-05-18

Phase 1 is complete. No product bug was found while implementing or verifying this phase.

### Files Changed

- `factory-agent/factory_agent/schemas.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/tests/test_response_document_contract.py`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`

### Decisions Made

- Keep `PresentationResponse` unchanged and continue deriving it exactly as before.
- Add `response_document` as an optional additive field on `SessionSnapshotResponse`; the snapshot service now populates it for loaded snapshots.
- Add `snapshot_revision` as an additive field and mirror the generated response-document revision during migration.
- Use `session.event_seq` as the preferred response-document revision source; fall back to session/timeline timestamps only when `event_seq` is unavailable.
- Generate stable document ids from session and turn identity, and stable block ids from document, operation, approval, and source identity.
- Keep the Phase 1 mapper intentionally minimal: it maps the current `presentation` and server activity rows into the new contract, but does not implement the final deterministic composer.
- Include all later-phase block families in the schema now: run activity, short message, approval required, mutation result, affected-record table, knowledge answer, source list, and diagnostic.
- Do not introduce LLM final response generation.
- Do not change frontend rendering behavior.

### Commands Run

```powershell
git status --short --branch
python -m pytest tests/test_response_document_contract.py -q
python -m pytest tests/test_typed_snapshot_presentation_contract.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py tests/test_response_document_contract.py -q
```

### Test Results

- `python -m pytest tests/test_response_document_contract.py -q`: 4 passed.
- `python -m pytest tests/test_typed_snapshot_presentation_contract.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py tests/test_response_document_contract.py -q`: 72 passed.

### Remaining Phase 2 Work

- Build the deterministic backend response-document composer in a dedicated service or clearly isolated module.
- Derive richer `run_steps` from execution state, approvals, audit evidence, timeline, and current operation state instead of only mapping current activity rows.
- Implement deterministic block ordering and lifecycle rules for completed-step preservation during later pending approvals.
- Add compact preview versus table rules and multi-step aggregation.
- Cover flagship RD-001 and RD-002 backend states, including approval 1 complete/approval 2 pending and final aggregate completion.
- Add deeper diagnostic/rejection/expiry/cancel/RAG/source/long-table contract coverage.

## Phase 2 Checklist

- [x] Implement deterministic response composer.
- [x] Build `run_steps` from execution/timeline/approval/audit evidence.
- [x] Implement block-order rules.
- [x] Implement compact preview/list/table rules.
- [x] Implement multi-step aggregation rules.
- [x] Implement pending-approval rules preserving completed steps.
- [x] Implement final completion rules aggregating all completed steps.
- [x] Add backend tests for RD-001 and RD-002.
- [x] Add backend tests for partial failure, rejected, expired, cancelled, RAG/source, read-only, long table, and diagnostic states.

## Phase 2 Implementation Notes

Date: 2026-05-18

Phase 2 is complete. One product bug was found and fixed: empty read results shaped as `{"data": []}` were being treated as successful row evidence in the new response document path. The composer now classifies those as informational `no_results` diagnostics instead of fake success/result rows.

### Files Changed

- `factory-agent/factory_agent/schemas.py`
- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/tests/test_response_document_contract.py`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`

### Decisions Made

- Move response-document composition into `factory_agent.services.response_document_service` so snapshot assembly can delegate typed document decisions to a dedicated deterministic composer.
- Keep `PresentationResponse` generation and frontend rendering behavior unchanged.
- Compose `run_steps` from approvals, mutation steps/tool evidence, read evidence, sources, diagnostics, and activity fallback rather than prose phrases.
- Preserve completed mutation groups as `completed_step` blocks while a later approval is pending.
- Treat the latest pending approval as primary and keep earlier completed approval/mutation steps visible in `run_steps`.
- Add additive block schemas for completed steps, result summaries, and record previews while preserving existing Phase 1 block types.
- Use deterministic block ids derived from document, operation, approval, read-result, and source identity.
- Keep final response generation deterministic and backend-owned; no LLM final-response generation was introduced.

### Commands Run

```powershell
git status --short --branch
python -m pytest tests/test_response_document_contract.py -q
python -m pytest tests/test_typed_snapshot_presentation_contract.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py tests/test_response_document_contract.py -q
```

### Test Results

- `python -m pytest tests/test_response_document_contract.py -q`: 13 passed.
- `python -m pytest tests/test_typed_snapshot_presentation_contract.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py tests/test_response_document_contract.py -q`: 81 passed.

### Remaining Phase 3 Work

- Add the full typed failure taxonomy and deterministic failure templates.
- Add operator-safe failure card actions and retry policy.
- Add partial-progress failure response documents that combine completed work and incomplete impact.

## Phase 3 Checklist

- [x] Define typed failure taxonomy.
- [x] Define deterministic failure templates.
- [x] Add failure card block fields for reason, severity, title, user message, impact, next actions, technical details, and collapsed state.
- [x] Map planner timeout and planner validation loop.
- [x] Map LLM timeout and answer timeout.
- [x] Map tool timeout, tool HTTP error, and tool schema error.
- [x] Map approval expired, rejected, and stale.
- [x] Map network disconnect and SSE interruption.
- [x] Map auth denied and cancelled by user.
- [x] Map partial commit failure and unknown failure.
- [x] Add safety/retry policy for context-aware actions.
- [x] Add tests proving technical details are collapsed and sanitized.
- [x] Add tests proving partial-progress failure shows completed and incomplete work together.
- [x] Add tests proving no blank/raw/generic failure response for broken flows.

## Phase 3 Implementation Notes

Date: 2026-05-18

Phase 3 is complete. One product bug was found and fixed: response-document diagnostic blocks were passing through raw legacy `presentation.diagnostics`, which could expose raw session errors, stack traces, or secret-like values in the new response-document path. The response-document composer now emits sanitized structured technical details while leaving legacy `PresentationResponse` behavior compatible.

### Files Changed

- `factory-agent/factory_agent/schemas.py`
- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/tests/test_response_document_contract.py`
- `factory-agent/tests/test_response_document_failures.py`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`

### Decisions Made

- Keep frontend rendering unchanged; Phase 3 only enriches backend `response_document`.
- Keep legacy `PresentationResponse` generation compatible and sanitize diagnostics only in the response-document layer.
- Add optional diagnostic fields for `cause`, `current_state`, `next_action`, and `retry_safety`.
- Centralize the failure taxonomy, templates, action policy, retry-safety policy, impact calculation, and sanitizer in `factory_agent.services.response_document_service`.
- Use typed reason templates for planner timeout, planner validation loop, LLM timeout, tool timeout, tool HTTP error, tool schema error, approval expired, approval rejected, approval stale, network disconnect, SSE stream interruption, snapshot contract invalid, response document invalid, auth denied, cancelled by user, partial commit failure, malformed response payload, no results, and unknown failure.
- Map empty final responses to a `no_results` diagnostic response document rather than fake success.
- Preserve completed mutation evidence beside later failure diagnostics.
- Do not show blind retry actions when retry safety is ambiguous or duplicate mutation risk is present.
- Continue to avoid LLM final-response generation.

### Commands Run

```powershell
python -m pytest tests/test_response_document_failures.py tests/test_response_document_contract.py -q
python -m pytest tests/test_response_document_contract.py -q
python -m pytest tests/test_response_document_failures.py -q
python -m pytest tests/test_typed_snapshot_presentation_contract.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py tests/test_response_document_contract.py -q
python -m pytest tests/test_stateful_oracle_harness.py -q
python -m pytest tests/test_tool_pipeline.py -q
python -m pytest tests/test_approval_atomicity.py -q
```

### Test Results

- `python -m pytest tests/test_response_document_failures.py tests/test_response_document_contract.py -q`: 22 passed.
- `python -m pytest tests/test_response_document_contract.py -q`: 13 passed.
- `python -m pytest tests/test_response_document_failures.py -q`: 9 passed.
- `python -m pytest tests/test_typed_snapshot_presentation_contract.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py tests/test_response_document_contract.py -q`: 81 passed.
- `python -m pytest tests/test_stateful_oracle_harness.py -q`: 5 passed.
- `python -m pytest tests/test_tool_pipeline.py -q`: 11 passed.
- `python -m pytest tests/test_approval_atomicity.py -q`: 8 passed.

### Remaining Phase 4 Work

- Render the typed diagnostic fields in the frontend response-document renderer.
- Keep legacy `presentation` fallback only when `response_document` is absent.
- Add UI coverage for collapsed diagnostics and context-aware failure actions.

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
git add -- "docs/qa/RESPONSE_DOCUMENT_UX_PLAN.md" "docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md"; git commit -m "docs: add response document UX plan"
rg -n "final_response|final response|presentation|approval|snapshot|timeline|SSE|ServerSent|EventSource|poll|expired|cancelled|timeout|blocked|failed" factory-agent/factory_agent/schemas.py factory-agent/factory_agent/services/session_snapshot_service.py factory-agent/factory_agent/services/planner_service.py factory-agent/factory_agent/services/execution_service.py factory-agent/factory_agent/api/routers/messages.py factory-agent/factory_agent/api/routers/events.py
rg -n "presentation|summary|timeline|activity|approval|affected|record|table|list|details|stale|current|collapse|poll|EventSource|SSE" "eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx" "eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js" "eMas Front/src/components/features/chat/factory-agent/presentationContract.js" "eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js" "eMas Front/src/components/features/chat/turns/turnAssembler.js"
rg --files factory-agent/tests "eMas Front/e2e" | rg "(response|presentation|snapshot|timeline|approval|final|sse|poll|collapse|busy|traffic|factory|langgraph|oracle|failure|timeout|turn)"
rg -n "presentation|final response|session_completed|approval|required|pending|expired|cancelled|failed|timeline|activity|SSE|poll|collapse|stale|response_document|empty final|busy|out-of-order|out of order" factory-agent/tests "eMas Front/e2e"
```

## Test Results

- Phase 0 was documentation-only.
- No backend, frontend unit, or Playwright product tests were run because Phase 0 did not implement product behavior.
- Required verification passed: `git diff --check`.

## Files Changed

- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`

## Next Action

Start Phase 1 by adding additive backend response-document schemas and a minimal snapshot response-document mapper beside existing `presentation`; keep frontend behavior unchanged.
