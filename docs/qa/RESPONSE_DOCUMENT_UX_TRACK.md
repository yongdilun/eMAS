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
| 4 | Frontend response document renderer | Done | Codex | Added frontend response-document normalizer/renderer, direct block rendering, compact approvals, invalid-document diagnostic, fallback only when missing, unit/component coverage, and a focused mocked Playwright proof. |
| 5 | Response document reducer and busy-traffic ordering | Done | Codex | Added centralized frontend response-document reducer, shared SSE/polling snapshot ordering path, stale/invalid revision guards, focused reducer tests, and mocked busy-traffic Playwright coverage. |
| 6 | Final response quality E2E gate | Done | Codex | Added mocked browser final-response quality gate for cascades, reads, RAG/source, diagnostics, rejected/expired/stale/cancelled states, and busy traffic convergence. |
| 7 | Compact approval and progressive disclosure hardening | Done | Codex | Hardened typed approval/result/diagnostic progressive disclosure, duplicate table suppression, controlled collapse state, and mobile/desktop overflow checks. |
| 8 | Mandatory compatibility cleanup | Done | Codex | Isolated legacy presentation/table heuristics behind missing-document fallback and added guardrails for valid/invalid `response_document`. |
| 9 | Release gate and future LLM handoff | Done | Codex | Added response-document release lane and documented blocking/non-blocking gates, manual limits, and future LLM polish contract. |
| 10 | Orphan turn and session state invariant gate | Done | Codex | Added backend orphan-turn invariant, typed `planner_no_action` / `orphan_turn_state` diagnostics, and mocked browser state-agreement coverage for the Chat 514 class. |
| 11 | Real flow browser state-transition oracle | Done | Codex | Added reusable browser transition oracle, mocked RD-001/RD-002 coverage, and real LangGraph SO-041 proof; fixed stale revision/session and completed-approval copy bugs found by the oracle. |
| 12 | Semantic snapshot probe and artifact quality | Done | Codex | Added compact semantic probe helper, oracle failure attachments, diagnosis classification, redaction/size tests, and a browser artifact proof. |
| 13 | Manual screenshot regression intake | Done | Codex | Added strict screenshot intake template, structured Chat 514 regression entry, and a bank gate that rejects vague/manual-only screenshot issues. |
| 14 | Final response business contract | Done | Codex | Backend `response_document` now emits clean business-level completed mutation results: grouped changes, deduped affected records, compact preview contract, and no raw assistant/internal-id noise in final mutation blocks. |
| 15 | Final response visual quality oracle | Done | Codex | Added browser semantic oracle coverage for RD-001 final visual quality, compact grouped rendering, expandable clean audit, forbidden-text detection, and duplicate affected-record evidence. |
| 16 | Approval copy and pending guidance cleanup | Done | Codex | Removed always-visible pending-approval helper copy from normal approval cards and added component plus RD-001 semantic-probe assertions forbidding it. |
| 17 | Entity-agnostic no-op mutation result contract | Done | Codex | Added typed no-op mutation groups with entity/selector/change/count fields, approval-safe partial and all-no-op backend contracts, and mocked browser semantic proof. |
| 18 | Read-only status response contract | Done | Codex | Added generic typed `status_result` response-document blocks for read-only status answers, clean machine labels, frontend rendering/probes, and RD-008 browser proof. |
| 19 | RAG question-type routing contract | Done | Codex | Added reusable semantic `question_type` routing before missing-entity checks, covered LOTO notification document-content prompts, preserved machine-specific LOTO/status controls, and added RD-009 browser semantic proof. |
| 20 | Entity-specific overfitting audit | Done | Codex | Audited backend routing/planning, response-document composition, frontend renderer/probes, seeded fixtures, scenario oracles, and QA docs; generic entity work needs backend metadata readiness first. |
| 21 | Backend capability metadata readiness | Done | Codex | Prepared OpenAPI/Swagger, RAG mirrors, generated `tools.md`, and generated vocabulary for `entity_status_v1`, `business_change_v1`, and `entity_agnostic_no_matching_records_v1`; 44 metadata/tool tests passed. |
| 22 | Generic entity status and mutation business contract | Done | Codex | Added additive backend `entity_status_v1` and `business_change_v1` contract fields, typed business-change payload support, one safe synthetic non-job no-op proof, and a guard that machine status is only one entity-status example. |
| 23 | Migrate existing machine/job outputs onto generic contracts | Ready To Start | Codex | Phase 22 contracts are ready; move machine status, job priority cascade, and job no-op output onto generic typed contracts without changing existing behavior. |
| 24 | Entity diversity coverage | Not Started | Codex | Prove generic contracts beyond jobs and machines with at least two safe deterministic non-job/non-machine examples. |
| 25 | Hardcode regression guardrails | Not Started | Codex | Add guardrails against product-code branches on fixture ids, exact prompts, entity labels, summary-prose business inference, and weak machine/job-only probes. |
| 26 | Real flow release proof | Not Started | Codex | Run the post-refactor real/seeded release proof for RD-001, machine status, LOTO RAG, no-op mutation, non-job generic proof if available, and final visual quality. |

## Current Blockers

- Chat 514 style orphan state is fixed and covered by Phase 10 backend plus mocked browser regressions. Normal prompts must not settle as `IDLE/non_terminal_snapshot` with generic `Needs attention`.
- RD-001 noisy final mutation output is fixed in Phase 14/15 at the backend response-document contract and browser visual oracle: final completed mutation blocks summarize 21 jobs across 2 approved business changes and omit raw assistant/internal-id noise.
- Phase 16 removed the always-visible helper sentence `Follow-up messages can revise the plan, but the current approval remains pending until you approve, reject, or cancel it.` from normal approval display.
- No-data mutation steps now have an explicit Phase 17 no-op contract with visible `Not changed` groups, approval exclusion, and no mutation attempt for zero-match groups.
- Read-only status response cleanup is complete for Phase 18. `Show status for machine with machine id M-CNC-01` now renders one typed `status_result` answer and forbids raw assistant markers, dump-style API labels, duplicate answer text, approval UI, and mutation UI.
- LOTO document-content question misclassification is fixed in Phase 19. `According to the LOTO procedure, what notification is required before starting lockout` now routes as document-content RAG/procedure content without requiring `machine_id`.
- Several recent fixes are still at risk of becoming entity-specific special cases. Phase 20 audited this; Phase 21 prepared backend/OpenAPI/tool/vocabulary metadata before the generic response-document contract starts.
- Phase 22 is complete at the backend contract layer: generic contract fields and synthetic proofs now exist before existing machine/job flows are migrated in Phase 23.
- Phases 23-26 are explicit follow-ups: migrate existing machine/job outputs, prove entity diversity beyond jobs/machines, add hardcode guardrails, then run the real/seeded release proof.
- Existing `PresentationResponse` remains in the API only for compatibility snapshots where `response_document` is absent.
- Real LangGraph and seeded suites remain broader release gates; focused response-document mocked browser coverage is now the fast UX lane.

## Open Questions

- Should `response_document` live directly on the snapshot response, timeline terminal event, or both?
- Which backend module should own composition: `session_snapshot_service.py` or a new `response_document_service.py`?
- Should any privileged support-only UI ever expose operation/step ids, or should they stay only in probe artifacts/backend logs?
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
- Normal user prompts must never settle into an orphan `IDLE/non_terminal_snapshot` state. They must be running, waiting approval/confirmation, completed, cancelled, blocked, or failed with a typed reason.
- Browser tests must compare visible UI with backend snapshot state at transition checkpoints, not only final backend JSON.
- Compact semantic probes should be the primary failure artifact; full Playwright/a11y snapshots are supporting evidence.
- Completed mutation final responses use a short summary, grouped business changes, and a compact affected-record preview.
- The default affected-record preview limit is 5 rows, with expandable clean audit details.
- Expanded affected records are grouped by business change, not backend operation or step id.
- Raw assistant final markdown is not display truth for mutation results.
- Internal ids such as `operation_id`, `step_id`, and `row_id` do not appear in normal rendered chat.
- Final mutation aggregates are based on business write sets, not individual backend operations, execution steps, tool calls, or audit rows.
- Normal approval cards should not show pending follow-up guidance by default.
- Pending follow-up guidance appears only when a user sends or attempts a conflicting follow-up while approval is pending, or in collapsed help/details if explicitly designed.
- No matching records in a requested mutation step is an explicit no-op, not a silent skip.
- No-op mutation groups use `Not changed` wording.
- Approval cards include only actual proposed mutations, not no-op groups.
- All-no-op mutation requests complete as `No changes were made`, with no approval card and no mutation audit rows.
- Read-only status answers use typed facts and human labels, not raw assistant markdown or dump-style API field names.
- Machine-status answers should show one concise summary plus meaningful key facts; secondary metadata belongs in compact details only when useful.
- Read-only/status responses must not render as approval or mutation UI.
- Entity IDs are required only after the semantic question type proves the route actually needs that entity.
- Document-content RAG questions should not be forced into machine-specific clarification just because they mention LOTO, procedure, lockout, or "before".
- No-op mutation semantics are entity-agnostic business outcomes, not job-priority-only rendering.
- Phase 20 is audit-only by default.
- Phase 21 is backend metadata readiness: OpenAPI/Swagger, RAG OpenAPI mirror, `tools.md`, generated tool vocabulary, and capability metadata must be updated together.
- Phase 22 creates the generic response-document contracts and starts only after Phase 21 returns ready metadata evidence.
- Phase 23 migrates existing machine/job outputs onto generic typed contracts and starts only after Phase 22 proves the contracts.
- Phase 24 proves the contract beyond jobs and machines before the plan can claim generic coverage.
- Phase 25 installs hardcode guardrails before real-flow release proof.
- Phase 26 is the release-confidence proof after contract creation, migration, diversity coverage, and guardrails are green.

## Flagship Inputs

| ID | Prompt | Purpose |
| --- | --- | --- |
| RD-001 | `change all medium priority job to high then change all high priority job to low` | First flagship. Proves approval 1, approval 2, completed-step preservation, latest pending approval, and final aggregate result. |
| RD-002 | `change all high priority job to low then change all low priority job to medium` | Reverse cascade. Proves original-state semantics and prevents overfitting RD-001. |
| RD-003 | `change all medium priority job to high then change all high priority job to low` | Post-gate orphan-state regression. Proves the flow cannot show `IDLE/non_terminal_snapshot` or generic `Needs attention` after send/approval. |
| RD-004 | `change all medium priority job to high then change all high priority job to low` | Final-response business-quality regression. Proves final result is 21 jobs across 2 approved business changes, not raw assistant markdown or backend step noise. |
| RD-005 | `change all medium priority job to high then change all high priority job to low` | Approval-copy regression. Proves normal approval cards do not show the always-visible pending follow-up helper sentence. |
| RD-006 | `change all medium priority job to high then change all high priority job to low` with no medium-priority jobs present | Partial no-op regression. Proves no medium-priority matches are shown as `Not changed`, no approval is requested for that group, and valid high-priority edits can still proceed. |
| RD-007 | Mutation prompt where every requested edit has zero matching records | All-no-op regression. Proves `No changes were made`, no approval card appears, and no mutation audit rows are created. |
| RD-008 | `Show status for machine with machine id M-CNC-01` | Read-only status regression. Proves one clean typed machine-status answer without `done_all`, raw `**Success**`, dump-style field labels, duplicate answer text, approval UI, or mutation UI. |
| RD-009 | `According to the LOTO procedure, what notification is required before starting lockout` | RAG question-type routing regression. Proves document-content LOTO questions route to RAG/procedure content without machine-ID clarification. |
| RD-010 | Phase 20 audit only | Finds overfitted entity-specific implementation patterns before backend readiness and generic response-contract phases are created. |
| RD-011 | Phase 21 backend metadata readiness | Proves OpenAPI/tool/vocabulary metadata exposes generic entity status and mutation business-change semantics before response-document implementation. |
| RD-012 | Phase 22 generic entity status and mutation business contract | Proves `entity_status_v1`, `business_change_v1`, one safe non-job no-op contract proof, and a guard that machine status is only one entity-status example. |
| RD-013 | Phase 23 machine/job generic-contract migration | Proves machine status, job priority cascade, and job no-op mutations render from typed generic contracts rather than entity-specific display paths. |
| RD-014 | Phase 24 entity diversity coverage | Proves generic contracts beyond jobs and machines with at least two safe deterministic examples. |
| RD-015 | Phase 25 hardcode guardrails | Proves product code, composer logic, and frontend probes cannot quietly regress to fixture-specific hardcoding or summary-prose inference. |
| RD-016 | Phase 26 real flow release proof | Proves the post-refactor real/seeded release-critical flows still agree across backend state, response document, and visible UI. |

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
| Pending approval guidance | RD-001 approval 1 or approval 2 | Normal approval card omits generic follow-up guidance; conditional guidance appears only after follow-up conflict if implemented. |
| Partial no-op mutation | No records for one requested edit group, valid records for another group | No-op group appears as `Not changed`; approval contains only valid proposed mutation; final response includes both changed and not changed. |
| All no-op mutation | No records for every requested edit group | Completes as `No changes were made`; no approval card; no mutation audit rows. |
| Read-only status cleanup | `Show status for machine with machine id M-CNC-01` | One typed status answer with human labels, no raw assistant markdown, no duplicate blocks, no generic dump table, no approval/mutation UI. |
| RAG document-content routing | `According to the LOTO procedure, what notification is required before starting lockout` | RAG/procedure answer is attempted without machine-ID clarification; adjacent machine-specific LOTO and machine-status prompts still route correctly. |
| Entity-specific overfitting audit | Search routing, composition, renderer, fixture, oracle, and docs for job/machine/product/material overfitting | Inventory product-risk and missing-general-contract patterns, then propose Phase 21 based on findings. |
| Backend metadata readiness | OpenAPI, generated tools, generated vocabulary, `tools.md`, and RAG mirrors | Status/business-change/no-op semantics are present as typed metadata before generic response-document implementation. |
| Generic entity contract creation | Backend response-document contract fixtures | `entity_status_v1`, `business_change_v1`, safe non-job no-op proof, and machine-status-as-example guard exist before existing flows are migrated. |
| Machine/job generic-contract migration | Existing RD-001/RD-008/RD-006/RD-007 flows | Existing machine status, job priority cascade, and job no-op output render through generic contract types rather than entity-specific branches. |
| Entity diversity coverage | Product/material/work-order/non-job no-op fixtures | At least two non-job/non-machine examples prove the contracts are not only job/machine compatible. |
| Hardcode guardrails | Product-code scan, composer contract tests, frontend probe tests | Fixture ids, exact prompt text, entity-label branches, summary-prose business inference, and weak machine/job-only probes are blocked or explicitly excepted. |
| Real flow release proof | RD-001, machine status, LOTO document-content RAG, no-op mutation, non-job generic proof if available | Real/seeded backend state, response document, and visible UI agree after the generic-contract refactor. |

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

- [x] Add frontend response-document normalizer.
- [x] Add response document renderer component.
- [x] Render run activity block.
- [x] Render short message block.
- [x] Render compact approval card.
- [x] Render completed step card.
- [x] Render result summary/table/source/diagnostic blocks.
- [x] Preserve completed steps when latest approval is pending.
- [x] Keep latest pending approval primary.
- [x] Keep legacy `presentation` fallback only when `response_document` is absent.
- [x] Add component/unit tests.

## Phase 4 Implementation Notes

Date: 2026-05-18

Phase 4 is complete. No product bug was found while implementing or verifying this phase.

### Files Changed

- `eMas Front/src/components/features/chat/factory-agent/responseDocumentContract.js`
- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs`
- `eMas Front/e2e/fixtures/factoryAgentFixtures.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/chat-fixtures.spec.js`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`

### Decisions Made

- Normalize `response_document` in a dedicated frontend contract module before rendering.
- Render typed response-document blocks in `ResponseDocumentRenderer` and bypass legacy summary/table/presentation heuristics whenever a document is present.
- Keep legacy `presentation` rendering only for snapshots/turns where `response_document` is absent.
- Treat invalid existing `response_document` as a safe diagnostic and do not fall back to stale `presentation`.
- Keep approval rendering compact by default with top affected-record chips, collapsed detail tables, and visible approve/reject actions.
- Render run activity from `response_document.run_steps` instead of reconstructing it from timeline phrases when a response document is present.
- Preserve completed-step blocks beside the latest pending approval so approval 1 evidence remains visible while approval 2 waits.
- Do not implement response-document revision reducer/event-storm ordering in Phase 4; Phase 5 remains responsible for stale revision rejection and coalescing.
- Do not introduce LLM final-response generation.

### Commands Run

```powershell
Set-Location "eMas Front"
npm test -- --test-name-pattern "response_document|response document|legacy presentation fallback|invalid snapshot response_document|snapshot response_document"
node --test --test-concurrency=1 "src/components/features/chat/turns/turnAssembler.test.mjs"
npm run test:e2e -- --project=chromium --grep "response_document renderer" e2e/specs/chat-fixtures.spec.js
npm test
```

### Test Results

- Focused frontend test command: 86 passed.
- Focused `turnAssembler.test.mjs`: 23 passed.
- Focused mocked Playwright response-document renderer check: 1 passed.
- Full `npm test`: 86 passed.

### Remaining Phase 5 Work

- Add centralized response-document reducer/store update logic.
- Apply `snapshot_revision`, `document_id`, `turn_id`, and `response_document.revision` ordering.
- Handle stale, duplicate, and conflicting revisions across polling/SSE.
- Preserve expand/collapse state across accepted newer revisions.
- Add event-storm and traffic-focused Playwright coverage.

## Phase 5 Checklist

- [x] Add centralized frontend `responseDocumentReducer` or equivalent store update function.
- [x] Add frontend response-document validation before rendering.
- [x] Apply `snapshot_revision`, `document_id`, `turn_id`, and `response_document.revision` ordering rules.
- [x] Ignore stale lower revisions from SSE.
- [x] Ignore stale lower revisions from polling.
- [x] Detect same-revision conflicting content and keep the existing stable document as the safe contract-violation behavior.
- [x] Coalesce fast update bursts by reducing every snapshot to one current winning document without forcing fake progress delays.
- [x] Preserve expanded/collapsed state by rendering only stable block ids from the accepted winning document.
- [x] Prevent old turns/documents from updating active response-document UI.
- [x] Add reducer tests for stale, duplicate, conflicting, invalid, and cross-turn documents.
- [x] Add reducer tests proving same-revision idempotence and no stale history merge.
- [x] Add Playwright event-storm tests for fast progress to approval pending.
- [x] Add Playwright event-storm tests for final complete followed by stale pending.
- [x] Add Playwright event-storm tests for SSE/polling disagreement where highest revision wins.
- [x] Add Playwright event-storm tests for approval 1 complete then approval 2 pending.
- [x] Record trace/video/screenshot artifact policy for failures.

## Phase 5 Implementation Notes

Date: 2026-05-18

Phase 5 is complete. No product bug was found while implementing or verifying this phase.

### Files Changed

- `eMas Front/src/components/features/chat/factory-agent/responseDocumentReducer.js`
- `eMas Front/src/components/features/chat/factory-agent/responseDocumentReducer.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `eMas Front/e2e/fixtures/factoryAgentFixtures.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/response-document-traffic.spec.js`
- `eMas Front/package.json`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`

### Decisions Made

- Add a pure frontend reducer/update helper in `responseDocumentReducer.js`; snapshot application is now gated by the reducer before React state is updated.
- Route SSE-triggered snapshot refreshes and polling/manual snapshot refreshes through the same reducer path with transport metadata.
- Use normalized frontend validation before accepting a document. Invalid documents render the existing safe diagnostic only when their revision is the current winning revision.
- Accept newer valid revisions, ignore older revisions, treat duplicate equal revisions as idempotent, let valid same-revision documents repair invalid current documents, and keep the stable current document on same-revision conflicts.
- Do not merge `run_steps` or blocks across revisions. The winning response document replaces the previous document wholesale.
- Keep legacy `presentation` fallback only for snapshots where no winning response document exists.
- Add a mocked busy-traffic fixture that sends pending, completed, stale failure, stale pending, invalid, duplicate, and final completed response-document snapshots.
- Do not introduce LLM final-response generation.
- Do not remove the old presentation fallback.

### Commands Run

```powershell
Set-Location "eMas Front"
node --test --test-concurrency=1 "src/components/features/chat/factory-agent/responseDocumentReducer.test.mjs"
npm test
npm run test:e2e -- --project=chromium --grep "response_document revision|event storm|busy traffic|stale revision"
```

### Test Results

- Focused reducer tests: 11 passed.
- Full `npm test`: 97 passed.
- Focused mocked Playwright busy-traffic test: 1 passed.

### Remaining Phase 6 Work

- Add seeded browser final-response quality gates for the flagship multi-step scenarios.
- Add visible final-response assertions for progress order, compact cards, completed evidence, stale text absence, and collapse stability.

## Phase 6 Checklist

- [x] Add browser test for RD-001.
- [x] Add browser test for RD-002.
- [x] Add visible DOM assertions for activity order.
- [x] Add visible DOM assertions for short conversational message.
- [x] Add visible DOM assertions for compact approval cards.
- [x] Add visible DOM assertions for completed step preservation.
- [x] Add final aggregate result assertions.
- [x] Add forbidden stale text/current-state assertions.
- [x] Add collapse/expand stability assertions.
- [x] Confirm existing real LangGraph critical proof remains the highest-risk non-mocked lane.

## Phase 7 Checklist

- [x] Cap approval card default height through compact preview plus collapsed details.
- [x] Limit default affected-record preview to top 3-5 records.
- [x] Keep approve/reject buttons visible before expandable records.
- [x] Move full affected-record table into details.
- [x] Render completed/rejected/expired approval evidence as compact history/diagnostic cards.
- [x] Add mobile/desktop layout checks.
- [x] Add no-overlap/no-overflow checks where feasible.

## Phase 8 Checklist

- [x] Make `response_document` the primary source for all new sessions.
- [x] Isolate old `presentation` fallback behind a missing-document check.
- [x] Remove old state/layout decisions from frontend paths where possible.
- [x] Add guardrail against new phrase-based state inference.
- [x] Update docs with compatibility retirement policy.
- [x] Rerun response and release gates, with remaining broad lanes documented.

## Phase 9 Checklist

- [x] Run backend oracle gate.
- [x] Run frontend unit/component tests.
- [x] Run mocked browser gate.
- [x] Run seeded browser oracle gate or focused equivalent.
- [x] Run real LangGraph critical gate or focused equivalent.
- [x] Record accepted gaps.
- [x] Document that LLM polish/Promptfoo is future separate work.

## Phase 10 Checklist

- [x] Add backend invariant for latest user message + `IDLE` + no terminal/pending/blocked/failed/cancelled state.
- [x] Add product fix so actionable prompts cannot emit `non_terminal_snapshot` as user-facing final state.
- [x] Add RD-001/RD-003 backend snapshot regression.
- [x] Add browser forbidden-text assertions for `non_terminal_snapshot`, `Session status: IDLE`, and generic `Needs attention`.
- [x] Assert active session header, sidebar, snapshot status, and response-document state agree after refresh.
- [x] Update manual regression bank with the Chat 514 screenshot failure.

## Phase 11 Checklist

- [x] Build reusable browser state-transition oracle for response-document flows.
- [x] Add transition checkpoints for send -> approval 1 -> applying -> approval 2 -> completed.
- [x] Include forbidden stale text at every checkpoint.
- [x] Add real LangGraph or seeded critical coverage for at least RD-001.
- [x] Save compact transition artifact on failure.

## Phase 11 Implementation Notes

Date: 2026-05-18

Phase 11 is complete. Product bugs found and fixed:

- The frontend `responseDocumentReducer` compared revisions across different sessions, so opening a new session with a lower revision could preserve a previous session's response document and leave header/sidebar/body state contradictory.
- Backend response-document revisions fell back to `updated_at` milliseconds when `event_seq` was 0, then dropped to revision 1 on the first user event; the frontend correctly rejected that later lower revision, leaving the visible UI stale while the backend had advanced.
- Completed approval history still reused future-tense approval copy, so after approval 1 completed the real flow could show stale "will be updated" language for data that had already changed.

### Transition Oracle

- Helper: `eMas Front/e2e/support/factoryAgentTransitionOracle.js`.
- Unit tests: `eMas Front/e2e/support/factoryAgentTransitionOracle.test.mjs`.
- The oracle compares visible header status, active sidebar status, backend `session.status`, backend pending approval id, `response_document.state`, `response_document.revision`, visible/backend block types, approval/action text, result text, and diagnostic text at every checkpoint.
- The oracle fails on forbidden stale/internal text including `non_terminal_snapshot`, `Session status: IDLE`, generic actionable `Needs attention`, stale approval-1 waiting text after approval 1 is decided, stale approval-required copy after completion, raw JSON, traceback/stack trace text, and token-like diagnostics.
- Failure artifacts include a compact redacted transition probe summary beside the Playwright test output.

### Regression Coverage Added

- `eMas Front/e2e/specs/final-response-quality.spec.js`
  - `RD-001 state transition oracle catches stale visible approval after backend advances`
  - `RD-002 state transition oracle covers reverse cascade without overfitting RD-001`
- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`
  - `RD-001 state transition oracle: SO-041 aggregates both real LangGraph write sets in the final response`
- `eMas Front/src/components/features/chat/factory-agent/responseDocumentReducer.test.mjs`
  - new-session lower-revision guard.
- `factory-agent/tests/test_response_document_contract.py`
  - event-seq-zero revision regression.
  - completed approval history no longer shows stale future-tense mutation copy.

### Commands Run

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi"
git status --short --branch
# -> ## codex/playwright-e2e-plan

Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front"
npm test
# -> 103 passed

npm run test:e2e:response-document -- --grep "state transition|RD-001|RD-002"
# -> 3 passed

npm run test:e2e:real-langgraph -- --grep "state transition|RD-001|SO-041|@critical"
# -> 3 passed

Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
# -> 24 passed

python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py tests/test_api_endpoints.py -q
# -> 68 passed, 20 xfailed, 5 failed in tests/test_api_endpoints.py
```

### Accepted Verification Caveat

- The required backend bundle still has five unrelated legacy API endpoint failures in `tests/test_api_endpoints.py`: missing-argument legacy planner clarification, job-slot tool selection, invalid-output execute rejection, `/tools` intent scoping, and replan validation DLQ. These failures reproduce when run directly as the only selected tests and are outside the response-document transition oracle path.
- The response-document backend contract/failure suite that covers the touched backend code passes.

## Phase 12 Checklist

- [x] Add semantic current-turn probe helper for Playwright.
- [x] Capture UI status, sidebar status, visible blocks, snapshot status, response-document revision/state, and approval ids.
- [x] Save probe JSON on failure.
- [x] Document how to read the probe before opening full screenshots/traces.
- [x] Add artifact size/readability budget.

## Phase 12 Implementation Notes

Date: 2026-05-18

Phase 12 is complete. No product bug was found.

### Semantic Probe

- Helper: `eMas Front/e2e/support/responseDocumentProbe.js`.
- Unit tests: `eMas Front/e2e/support/responseDocumentProbe.test.mjs`.
- The probe captures only active-session/current-turn evidence: active session id/name, visible header status, active sidebar row status, latest user prompt, latest assistant title/message, visible response block types/ids, visible run-step titles/states, visible approval ids/buttons, forbidden text hits, backend `session.status`, backend pending approval id, backend `response_document.state`, revision, block types, current step id, run steps, and compact block summaries.
- The probe avoids full backend snapshots, full DOM/a11y snapshots, rows, traces, and stack dumps. Repeated blocks/run steps are capped and text is truncated/redacted so formatted JSON stays under the 200-line readability budget.
- Diagnosis classification currently reports `backend_state_gap`, `response_document_gap`, `reducer_ordering_gap`, `renderer_dom_gap`, `session_list_sync_gap`, or `unknown`.

### Oracle Integration

- `eMas Front/e2e/support/factoryAgentTransitionOracle.js` now builds semantic probes for transition summaries and failure artifacts.
- On checkpoint failure, the thrown error starts with a short human-readable diagnosis and attaches `<checkpoint>-semantic-probe.json`.
- The oracle assertions from Phase 11 were not weakened; the semantic probe changes only the diagnostic surface around the same backend/UI checks.
- Full Playwright screenshots, traces, video, console logs, and stack logs remain available as supporting evidence. The semantic probe is the first artifact to read for response-document transition failures.

### Regression Coverage Added

- `eMas Front/e2e/support/responseDocumentProbe.test.mjs`
  - compact current-turn summary construction;
  - header/sidebar/backend mismatch classification;
  - response-document state mismatch classification;
  - stale approval UI after backend completion classification;
  - secret/token/stack-trace redaction;
  - artifact line-budget enforcement.
- `eMas Front/e2e/specs/final-response-quality.spec.js`
  - `RD-001 response_document semantic probe artifact captures first state transition evidence`

### Commands Run

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi"
git status --short --branch
# -> ## codex/playwright-e2e-plan

Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front"
node --test --test-concurrency=1 e2e/support/responseDocumentProbe.test.mjs
# -> 6 passed

node --test --test-concurrency=1 e2e/support/factoryAgentTransitionOracle.test.mjs
# -> 4 passed

npm test
# -> 109 passed

npm run test:e2e:response-document -- --grep "state transition|RD-001|RD-002"
# -> 4 passed
```

## Phase 13 Checklist

- [x] Add manual screenshot regression intake template.
- [x] Register the Chat 514 orphan-state screenshot as a manual regression.
- [x] Require each accepted screenshot bug to identify the first executable test layer.
- [x] Add regression-bank/schema checks so screenshot-only bugs cannot stay undocumented.

## Phase 13 Implementation Notes

Date: 2026-05-18

Phase 13 is complete. No new product bug was found in this phase; the Chat 514 product bug was already fixed in Phase 10 and is now captured as a completed screenshot intake example.

### Intake Contract Added

- Added a response-document screenshot intake template to `docs/qa/manual_prompt_regression_bank.md`.
- Added a structured `manual_screenshot_regressions` bank section in `tests/e2e/scenarios/manual_prompt_regressions.json`.
- Added a pytest gate that requires screenshot entries to include exact prompt, screenshot symptom, observed bad state, expected backend state, expected response-document state/revision/block types/current step, expected visible DOM, forbidden visible text, reproducer, first executable layer, owner/status, linked coverage, and verification command.
- Added the future-agent screenshot workflow: reproduce, classify expected backend/frontend state, add a failing executable regression first, fix product bug, prove with semantic probe/oracle, and commit only after verification.

### Chat 514 Coverage

- `phase13-chat514-non-terminal-snapshot-idle` captures the manual `Chat 514 / non_terminal_snapshot / IDLE` screenshot as promoted regression evidence.
- First executable layer: backend contract, using `factory-agent/tests/test_response_document_contract.py::test_orphan_idle_after_actionable_prompt_becomes_typed_blocked_diagnostic`.
- Browser proof: RD-001 orphan/session-state gate in `eMas Front/e2e/specs/final-response-quality.spec.js`.
- Linked browser state coverage: RD-001 and RD-002 transition-oracle tests plus the Phase 12 semantic-probe artifact proof.

### Commands Run

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_phase18_manual_prompt_bank.py -q
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "manual regression|non_terminal|RD-001|Chat 514|state transition"

Set-Location ".."
git diff --check
git status --short --branch
```

### Test Results

- Manual prompt/screenshot bank gate: 6 passed.
- Backend response-document contract/failure lane: 24 passed.
- Frontend unit/component lane: 109 passed.
- Focused response-document Playwright grep: 4 passed.

## Phase 14 Checklist

- [x] Reproduce the noisy RD-001 final mutation result as a backend response-document contract failure where possible.
- [x] Compose completed mutation results from typed business facts, not raw assistant markdown.
- [x] Aggregate completed mutations by approved business write set.
- [x] Deduplicate affected records within each business change group.
- [x] Limit default affected-record preview to 5 rows.
- [x] Provide expandable clean audit grouped by business change.
- [x] Forbid raw assistant markers such as `done_all` in visible mutation blocks.
- [x] Forbid `Operation ID`, `Step ID`, `Row ID`, and raw internal ids in normal response-document blocks.
- [x] Enforce RD-001 as 21 jobs across 2 approved business changes: 10 medium -> high and 11 original high -> low.
- [x] Update manual regression bank and tracker with the product bug/fix evidence.
- [x] Run backend response-document contract/failure verification.
- [x] Commit Phase 14.

## Phase 14 Implementation Notes

Status: Done

Date: 2026-05-18

Product bug found: yes. The completed RD-001 response document could aggregate backend/audit artifacts instead of business write sets, leak raw assistant final text through completion evidence, duplicate affected-record sections, and expose internal row metadata.

### Contract Added

- Completed mutation response documents now use a business-level mutation contract, recorded as `mutation_business_contract = business_level_v1`.
- Final mutation summaries use approved business changes, not backend operation/step/audit counts.
- Final mutation rows are deduplicated by business record plus priority change.
- The `mutation_result` block carries a compact preview contract with `preview_limit = 5`, `details_collapsed = true`, and a `groups` audit payload grouped by business change.
- Completed final mutation blocks omit per-operation `completed_step` blocks and duplicate `result_table` blocks.
- Clean final mutation rows omit `operation_id`, `step_id`, `row_id`, `approval_id`, `tool_name`, and raw audit ids.

### Known Bad Output

Manual verification showed RD-001 final completion rendering:

- raw assistant marker `done_all`;
- raw `**Success**` markdown;
- `Updated 63 jobs across 22 approved steps`;
- duplicate affected-record tables;
- internal fields such as `Operation ID`, `Step ID`, and `Row ID`;
- one visible block per backend operation/step instead of one business-level result.

### Required Good Output

The completed RD-001 final response should be readable before expanding details:

```text
Done. I updated 21 jobs across 2 approved business changes.

Changes completed
1. Medium -> High: 10 jobs
2. Original High -> Low: 11 jobs

Affected records
JOB-SEED-002 medium -> high
JOB-SEED-004 medium -> high
JOB-SEED-007 medium -> high
JOB-SEED-010 medium -> high
JOB-SEED-014 medium -> high
+16 more
```

Expanded details should show a clean audit grouped by business change, without internal ids.

### RD-001 Result After Fix

- `Done. I updated 21 jobs across 2 approved business changes.`
- `Medium -> High: 10 jobs`
- `Original High -> Low: 11 jobs`
- Default affected-record preview limit: 5 rows.
- Full audit details are grouped under the two business changes and contain only clean business fields.
- Raw assistant markers, raw `**Success**` markdown, backend operation/step counts, duplicate final tables, and internal row ids are absent from final mutation blocks.

### Regression Coverage Added

- Strengthened `factory-agent/tests/test_response_document_contract.py::test_final_completed_mutation_document_aggregates_all_approved_changes`.
- The test reproduces raw `done_all` / `**Success**` / `Updated 63 jobs across 22 approved steps` assistant text and duplicate audit evidence, then asserts the clean RD-001 business result.

### Commands Run

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py::test_final_completed_mutation_document_aggregates_all_approved_changes -q
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
python -m pytest tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation -q
```

### Test Results

- Focused RD-001 business contract regression: failed before the fix with `Updated 22 jobs across 2 approved steps`; passed after the fix.
- Backend response-document contract/failure lane: 24 passed.
- Approval-resume API regression: 1 passed.

### Phase 14 Verification Target

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
python -m pytest tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation -q
```

## Phase 15 Checklist

- [x] Extend `responseDocumentProbe` to capture final-response quality structure.
- [x] Add browser semantic oracle for RD-001 final completion.
- [x] Assert one final result card only.
- [x] Assert exactly 2 business change groups.
- [x] Assert total affected count is 21 and preview count is at most 5.
- [x] Assert expandable clean audit exists and is grouped by business change.
- [x] Forbid `done_all`, `Updated 63 jobs across 22 approved steps`, `Operation ID`, `Step ID`, and `Row ID`.
- [x] Assert no duplicate affected records appear in the same rendered section.
- [x] Run mocked response-document E2E and real LangGraph critical proof.
- [x] Commit Phase 15.

## Phase 15 Implementation Notes

Status: Done

Phase 15 proves the backend Phase 14 contract in the browser instead of relying on screenshots or raw final text. `responseDocumentProbe` now captures final result card count, summary text, business group labels/counts, affected-record preview count, expandable clean-audit state, expanded audit grouping, forbidden visible text, and duplicate affected-record evidence. The transition oracle includes those violations in its compact diagnosis.

Product bugs found: yes.

- The renderer handled the Phase 14 `result_summary` + grouped `mutation_result` contract as separate generic cards. It now renders one compact final business result with a 5-row preview, grouped summary, and collapsed clean audit.
- The live LangGraph composer could still feed shadow read/write presentation rows into the final mutation evidence. The backend composer now prefers complete business-change evidence, dedupes by affected record/change, preserves business order from the final business summary, and keeps internal ids out of normal final UI.

Browser proof added:

- Mocked RD-001 final visual quality oracle in `eMas Front/e2e/specs/final-response-quality.spec.js`.
- Real LangGraph RD-001/SO-041 final visual quality expectations in `eMas Front/e2e/specs/real-langgraph-critical.spec.js`.
- Probe/unit coverage in `responseDocumentProbe.test.mjs`, transition-oracle coverage in `factoryAgentTransitionOracle.test.mjs`, and renderer component coverage in `FactoryAgentChatPanel.component.test.mjs`.

### Phase 15 Verification Target

```powershell
Set-Location "eMas Front"
npm test
node --test --test-concurrency=1 e2e/support/responseDocumentProbe.test.mjs
node --test --test-concurrency=1 e2e/support/factoryAgentTransitionOracle.test.mjs
npm run test:e2e:response-document -- --grep "final response quality|RD-001|business result|visual quality"
npm run test:e2e:real-langgraph -- --grep "RD-001|SO-041|final response quality|@critical"

Set-Location "..\factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
```

## Phase 16 Checklist

- [x] Remove the always-visible pending follow-up helper sentence from normal approval rendering.
- [x] Update component tests that currently expect the helper sentence in normal approval cards.
- [x] Add component/browser assertions that normal approval cards do not show the helper sentence.
- [x] Preserve or document conditional guidance for actual follow-up conflict paths.
- [x] Update manual regression bank and tracker with the approval-copy regression.
- [x] Run frontend unit/component and focused response-document browser checks.
- [x] Commit Phase 16.

## Phase 16 Implementation Notes

Status: Done

### Known Bad Copy

Normal approval cards currently show:

```text
Follow-up messages can revise the plan, but the current approval remains pending until you approve, reject, or cancel it.
```

This copy distracts from the decision. It should not appear in normal approval cards for RD-001 approval 1 or approval 2.

### Product Fix

- Removed the normal pending-approval helper block from `FactoryAgentChatPanel.jsx`.
- Approval cards still render the proposed change, affected-record preview/details, and Approve/Reject actions.
- No existing conditional follow-up conflict guidance path was found in this phase. That more targeted UX remains future work; Phase 16 did not add a broad follow-up workflow.

### Regression Coverage Added

- `FactoryAgentChatPanel.component.test.mjs` now asserts the helper sentence is absent for normal pending approval cards, lagging approval timeline cards, and compact response-document approval cards.
- `responseDocumentProbe.js` exports the exact helper sentence as pending-approval forbidden probe text.
- `final-response-quality.spec.js` adds RD-001 approval-copy coverage and applies the forbidden probe assertion to approval 1 and approval 2 checkpoints.

### Required Good Behavior

- Approval card shows what will change, affected-record preview/details, and approve/reject actions.
- Pending follow-up guidance is hidden by default.
- If follow-up conflict UX exists, guidance appears only after the user sends or attempts a conflicting follow-up while an approval is pending.

### Phase 16 Verification Target

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e:response-document -- --grep "approval copy|RD-001|Waiting for approval|pending guidance"
```

### Phase 16 Verification Results

- `npm test` -> 113 passed.
- `npm run test:e2e:response-document -- --grep "approval copy|RD-001|Waiting for approval|pending guidance"` -> 5 passed.

## Phase 17 Checklist

- [x] Define the no-op mutation response-document shape with entity-agnostic fields such as `entity_type`, `selector_summary`, `change_summary`, `matched_count`, `changed_count`, and `reason=no_matching_records`.
- [x] Add backend contract for partial no-op plus valid mutation.
- [x] Add backend contract for all-no-op mutation.
- [x] Ensure no-op mutation groups are rendered as `Not changed`.
- [x] Ensure no approval is requested for no-op groups.
- [x] Ensure all-no-op mutation completes as `No changes were made`.
- [x] Ensure no mutation audit rows are created for no-op groups.
- [x] Include a non-job-priority no-op contract if existing fixtures support one, or document the missing fixture as a Phase 20 finding.
- [x] Add browser/semantic-probe proof for at least one no-op mutation flow.
- [x] Update manual regression bank and tracker.
- [x] Run backend and frontend verification.
- [x] Commit Phase 17.

## Phase 17 Implementation Notes

Status: Done

Date: 2026-05-18

### Implemented Contract

No-data mutation groups now enter the response document as typed no-op business groups, not skipped prose. The normalized shape is:

```json
{
  "entity_type": "job",
  "selector_summary": "priority = medium",
  "change_summary": "priority -> high",
  "matched_count": 0,
  "changed_count": 0,
  "status": "not_changed",
  "reason": "no_matching_records"
}
```

The response-document composer accepts this shape from pending approval args and from saved intent contracts. It renders `Not changed` groups before approval, excludes them from approval cards, keeps them in final grouped mutation results, and counts only real write groups as approved business changes.

### Product Bug Fixed

The existing zero-match bulk-edit path completed planner intent with a summary such as "No matching jobs were found" but did not preserve a typed no-op mutation outcome. This could make a requested no-data edit disappear from the approval/final response. Phase 17 stores the no-op outcome in planner completed actions, carries it into approval payloads or final intent contracts, and composes it generically.

### Non-Job Coverage

Deferred to Phase 20 audit. Existing safe executable fixtures for no-op mutation flow are job-priority based; machine not-found write checks exist, but the active response-document fixture set does not yet provide a safe non-job mutation-selector no-op flow without broadening product scope. Phase 20 should audit whether machine/product/material no-op mutation sources should emit the same generic contract.

### Files Changed

- `factory-agent/factory_agent/graph/noop_mutations.py`
- `factory-agent/factory_agent/graph/nodes/planner_loop.py`
- `factory-agent/factory_agent/graph/nodes/validate.py`
- `factory-agent/factory_agent/graph/planner_graph.py`
- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/tests/test_response_document_contract.py`
- `eMas Front/e2e/support/responseDocumentScenarios.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

### Phase 17 Verification Results

- `python -m compileall factory_agent` -> passed.
- `node --check e2e/support/responseDocumentScenarios.js` -> passed.
- `node --check e2e/mock-server/fixtureStore.js` -> passed.
- `node --check e2e/specs/final-response-quality.spec.js` -> passed.
- `python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q` -> 27 passed.
- `python -m pytest tests/test_api_endpoints.py -q` -> 44 passed, 20 xfailed, 5 failed. Failures are existing legacy/tool-scope/DLQ endpoint expectations outside the Phase 17 response-document no-op path.
- `npm test` -> 113 passed.
- `npm run test:e2e:response-document -- --grep "no-op|Not changed|No changes were made|no matching"` -> 1 passed.

### Required Partial No-Op Behavior

When one requested edit group has no matching records but another edit group has valid records:

- The no-op group appears before approval in run activity/message.
- The approval card includes only records that will actually change.
- The final response includes:
  - `Changed` groups for applied mutations;
  - `Not changed` groups for no matching records.
- No mutation attempt or audit row exists for the no-op group.

### Required All-No-Op Behavior

When every requested edit group has zero matching records:

```text
No changes were made.

Not changed
- Medium -> High: no matching medium-priority jobs found, so no edit was attempted.
- High -> Low: no matching high-priority jobs found, so no edit was attempted.
```

No approval card should appear, and no mutation audit rows should be created.

### Required Entity-Agnostic Behavior

The no-op contract must describe the business outcome without depending on job-priority wording:

- `entity_type`: the affected domain entity, such as job, machine, product, material, or work order.
- `selector_summary`: the business selector that matched zero records.
- `change_summary`: the requested change that was not attempted.
- `matched_count`: `0`.
- `changed_count`: `0`.
- `status`: `not_changed`.
- `reason`: `no_matching_records`.

Job-priority examples are allowed as the first fixture, but the implementation should not require strings such as `medium`, `high`, `priority`, or `job` to render a safe no-op result.

### Phase 17 Verification Target

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
python -m pytest tests/test_api_endpoints.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "no-op|Not changed|No changes were made|no matching"
```

## Phase 18 Checklist

- [x] Add backend response-document contract coverage for machine-status read-only answers.
- [x] Compose machine-status answers from typed tool facts, not raw assistant markdown.
- [x] Render one concise status summary plus meaningful key facts.
- [x] Use human labels such as `Machine ID`, `Machine name`, `Machine type`, `Location`, `Status`, `Capacity per hour`, `Last maintenance`, and `Maintenance interval`.
- [x] Suppress low-value zero/default fields from the default visible answer.
- [x] Forbid raw `done_all`, raw `**Success**`, dump-style labels, duplicate answer blocks, approval UI, and mutation UI.
- [x] Add frontend component/probe/browser assertions for RD-008.
- [x] Update manual regression bank and tracker.
- [x] Run backend and frontend verification.
- [x] Commit Phase 18.

## Phase 18 Implementation Notes

Status: Done

### Known Bad Output

Manual verification for:

```text
Show status for machine with machine id M-CNC-01
```

showed:

- raw `done_all`;
- raw `**Success**`;
- duplicated answer text;
- dump-style labels such as `Machineid`, `Machinename`, `Capacityperhour`, `Defaultsetuptime`, `Defaultcleaningtime`, `Defaultchangeovertime`, `Utilizationrate`, `Lastmaintenancedate`, and `Maintenanceintervaldays`;
- generic `Results` block that only says `running`.

### Required Good Output

The default answer should be concise and typed, for example:

```text
Machine M-CNC-01 is running.

Machine details
- Machine name: CNC Mill 01
- Machine type: CNC Mill
- Location: Floor A - Bay 1
- Capacity per hour: 200
- Last maintenance: 2026-01-15 08:00
- Maintenance interval: 30 days
```

No approval card, mutation result, raw assistant marker, or dump-style API label should appear.

### Product Bugs Found And Fixed

- Backend read-only completion still trusted terminal assistant markdown for the visible short answer, so raw `done_all` and `**Success**` could become the rendered response even when typed tool data was available.
- Read-only machine details were projected through generic result rows/tables, exposing camelCase API labels such as `Machineid`, `Capacityperhour`, and default zero setup/cleaning/changeover fields.
- The frontend activity icon rendered the Material Symbol ligature text `done_all` into DOM text for completed runs. Activity icons now render through `data-icon` CSS content so icon names do not appear in visible/probe text.

### Product Fix

- Added a backend typed `status_result` response-document block for single-entity read/status facts.
- The contract is generic beyond `M-CNC-01`: status composition is driven by a status-like read intent plus typed row facts (`entity_type`, `entity_id`, `primary_status`, human-labeled fields), not by one prompt or fixture id.
- Machine status labels are normalized to `Machine ID`, `Machine name`, `Machine type`, `Location`, `Status`, `Capacity per hour`, `Last maintenance`, and `Maintenance interval`.
- Default/zero technical fields such as setup, cleaning, changeover, and utilization defaults are not shown in the default visible answer. Full technical detail requests can use collapsed secondary fields.
- Frontend response-document validation and rendering now support `status_result`, render one short answer plus typed facts, and suppress duplicate generic result tables for status reads.

### Files Changed

- `factory-agent/factory_agent/schemas.py`
- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/tests/test_response_document_contract.py`
- `eMas Front/src/components/features/chat/factory-agent/ActivityTimeline.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer.jsx`
- `eMas Front/src/components/features/chat/factory-agent/responseDocumentContract.js`
- `eMas Front/src/styles/index.css`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/e2e/support/responseDocumentProbe.js`
- `eMas Front/e2e/support/responseDocumentScenarios.js`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

### Commands Run

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "machine status|read-only status|M-CNC-01|status response"
```

### Test Results

- Backend response-document contract/failure lane: 28 passed.
- Frontend unit/component/probe lane: 114 passed.
- Focused response-document browser grep: 2 passed, including RD-008 read-only status and the machine-status happy path.

### Phase 18 Verification Target

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "machine status|read-only status|M-CNC-01|status response"
```

## Phase 19 Checklist

- [x] Add semantic question-type classification before missing-entity clarification.
- [x] Distinguish `document_content_question`, `machine_specific_procedure_selection`, `safety_policy_question`, and `live_operational_status`.
- [x] Ensure machine ID is required only when the question type needs a specific machine.
- [x] Add route tests for LOTO/procedure notification document-content prompts.
- [x] Preserve existing machine-specific LOTO clarification behavior.
- [x] Preserve existing machine-status and job-routing behavior.
- [x] Add backend response-document/prompt workflow proof that document-content LOTO answers are not `No results` or machine-ID clarification.
- [x] Add focused browser or semantic-probe evidence for RD-009.
- [x] Update manual regression bank and tracker.
- [x] Run backend and frontend verification.
- [x] Commit Phase 19.

## Phase 19 Implementation Notes

Status: Done

### Known Bad Output

Manual verification for:

```text
According to the LOTO procedure, what notification is required before starting lockout
```

showed that the system could route to `clarification.machine_id_missing` and render:

```text
Which machine ID should I use for the LOTO procedure? Please provide the exact machine ID from the equipment label or work order.
```

That is wrong because the user asked what the document says about notification. They did not ask which machine-specific LOTO procedure applies.

### Required Good Output

The prompt should route as a document-content RAG/procedure question:

- no missing `machine_id`;
- no machine-ID clarification;
- no `No results` diagnostic;
- no `completed_answer` technical-detail card;
- answer includes notification requirement content and source evidence when available.

Adjacent prompts must still behave correctly:

- `What LOTO procedure applies before working on M-CNC-01?` remains machine-specific LOTO/RAG.
- `What LOTO procedure applies before working on the CNC machine?` can still ask for the exact machine ID.
- `What is the status of M-CNC-01?` remains live machine-status tooling.

### Product Bugs Found And Fixed

- Document-content LOTO prompts such as `According to the LOTO procedure, what notification is required before starting lockout` were classified as machine-specific procedure selection and could ask for a machine ID. The semantic frame now sets `question_type=document_content_question` and routes to `rag.procedure` with empty `missing_required_entities`.
- LOTO wording that explicitly negates status, such as `For M-CNC-01, tell me the lockout tagout steps, not the current machine status.`, briefly regressed during implementation because live-status wording outranked procedure-selection wording. Procedure-selection classification now outranks live-status classification when the prompt has explicit LOTO/procedure-selection evidence.
- The mocked browser response-document LOTO fixture reused the manual-bank prompt `What LOTO procedure applies before working on M-CNC-01?`, which made prompt-regression browser tests hit the wrong fixture. The response-document fixture prompt is now distinct while the manual-bank prompt still exercises the seeded RAG route.

### Product Fix

- `factory_agent.planning.intent.SemanticFrame` now carries `question_type` with the reusable values `document_content_question`, `machine_specific_procedure_selection`, `safety_policy_question`, and `live_operational_status`.
- Missing entity checks run after the question type is known. Document-content and safety-policy questions do not require `machine_id`; machine-specific procedure selection and live machine status still can.
- LOTO notification prompts route to `rag.procedure` or `rag.safety_policy`, while machine-specific LOTO selection keeps `rag.loto_procedure` or `clarification.machine_id_missing`.
- The same document-content contract is tested with maintenance instruction, quality procedure, SOP, and job instruction wording so the fix is not tied to one exact LOTO prompt.
- Knowledge policy now has a LOTO notification fallback scoped by route family, topic, and notification evidence, avoiding empty/no-result output for this document-content class.
- RD-009 browser coverage attaches a semantic probe proving a clean response-document RAG answer with knowledge/source evidence and no machine-ID clarification, no `No results`, and no `completed_answer` diagnostic.

### Files Changed

- `factory-agent/factory_agent/planning/intent.py`
- `factory-agent/factory_agent/rag/knowledge_policy.py`
- `factory-agent/tests/test_intent_splitter.py`
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`
- `factory-agent/tests/test_route_to_execution_contract.py`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/e2e/support/responseDocumentProbe.js`
- `eMas Front/e2e/support/responseDocumentScenarios.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

### Commands Run

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py tests/test_route_to_execution_contract.py -q
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
python -m pytest tests/test_rag_knowledge_policy.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "LOTO|document content|machine ID|notification"
```

### Test Results

- Focused backend route/workflow lane: 113 passed.
- Backend response-document lane: 28 passed.
- Knowledge policy lane: 4 passed.
- Frontend unit/component lane: 114 passed.
- Focused response-document browser lane for `LOTO|document content|machine ID|notification`: 6 passed.

### Phase 19 Verification Target

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py tests/test_route_to_execution_contract.py -q
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "LOTO|document content|machine ID|notification"
```

## Phase 20 Checklist

- [x] Inventory entity-specific logic in backend routing, tool selection, planning, response-document composition, and seeded adapters.
- [x] Inventory entity-specific frontend rendering, probes, and Playwright assertions.
- [x] Inventory entity-specific scenario oracles, fixtures, manual-bank entries, and QA docs.
- [x] Classify findings as `acceptable_fixture`, `test_fixture`, `product-risk`, `planning-risk`, `missing-general-contract`, or `defer`.
- [x] For every product-risk or missing-general-contract finding, document recommended abstraction and proposed Phase 21 scope.
- [x] Confirm Phase 17-19 did not introduce new job-only, machine-only, or LOTO-only product behavior.
- [x] Update tracker with prioritized Phase 21 recommendation.
- [x] Run docs-only verification.
- [x] Commit Phase 20.

## Phase 20 Implementation Notes

Status: Done

Phase 20 is an audit phase. It should not make broad product changes. The purpose is to prevent the plan from becoming a pile of one-off fixes.

Date: 2026-05-19

### Overfitting Inventory

| ID | Classification | File/path | Exact pattern | Why it is overfitted | Likely future failure mode | Recommended abstraction or contract | Phase 21/22 handling |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P20-01 | product-risk | `factory-agent/factory_agent/planning/intent.py:658`, `factory-agent/factory_agent/planning/intent.py:864`, `factory-agent/factory_agent/planning/tool_selector.py:966`, `factory-agent/factory_agent/services/response_document_service.py:1815`, `factory-agent/tests/test_response_document_contract.py:1211`, `eMas Front/e2e/specs/final-response-quality.spec.js:678` | Live status routing is machine-only: `_is_live_operational_status_question` returns true only for `entity == "machine"` or machine hints, route emits `tool.read.machine_status`, tool selection asks only for machine lookup, status field order only defines the rich machine schema, and tests/probes cover only `M-CNC-01`. | Phase 18's user-facing contract is named and tested as a clean read-only status answer, but the route/tool/field proof is still machine-centered. | `status for product P-001`, `status for material MAT-002`, inventory availability/status, or work-order state can fall through to unknown/direct lookup/table output instead of a typed `status_result`, or render sparse generic fields with no stable field contract. | Introduce an `entity_status_v1` route family with `entity_type`, `entity_id`, `primary_status`, `fields`, `secondary_fields`, and capability-based tool selection for machine/job/product/material/inventory status reads. Keep machine field order as one schema entry, not the route definition. | Phase 21 should prepare OpenAPI/tool/vocabulary metadata for entity status. Phase 22 should create `entity_status_v1` and guard machine as only one example. Phase 23 should migrate machine status. Phase 24 should add product/material/work-order status diversity coverage. |
| P20-02 | product-risk | `factory-agent/factory_agent/services/response_document_service.py:1270`, `factory-agent/factory_agent/services/response_document_service.py:1285`, `factory-agent/factory_agent/services/response_document_service.py:1316`, `factory-agent/factory_agent/services/response_document_service.py:1589`, `factory-agent/factory_agent/services/response_document_service.py:1641`, `factory-agent/factory_agent/services/response_document_service.py:1663`, `factory-agent/tests/test_response_document_contract.py:280` | Completed mutation grouping, order, row cleanup, labels, and summaries are derived from priority fields and job id shape: `_priority_business_key`, `_business_change_order_from_text`, `_source_priority`, `_target_priority`, `Original High -> Low`, `job_id` when ID starts with `JOB-`, and job/record noun fallback. | Phase 14/15 fixed RD-001 by extracting priority/job facts, but the "business-level mutation" contract still gets its richest behavior only from priority deltas. | A future product/material/inventory/work-order mutation can collapse into `Business change N`, lose before/after field details, sort by approval rather than the user's business clauses, or render as generic records even when typed change facts exist. | Define a typed `business_change_v1` payload with `entity_type`, `change_type`, ordered `field_changes`, `selector_summary`, `source_state_basis`, `business_change_id`, and row-level `record_id`/`display_id`. Composition should prefer these fields over regexing summary text. | Phase 21 should expose business-change metadata through OpenAPI/tool docs where possible. Phase 22 should define `business_change_v1`. Phase 23 should migrate RD-001/RD-002 priority cascade onto it without summary-prose inference. |
| P20-03 | missing-general-contract | `factory-agent/tests/test_response_document_contract.py:948`, `factory-agent/tests/test_response_document_contract.py:1080`, `eMas Front/e2e/support/responseDocumentScenarios.js:359`, `eMas Front/e2e/specs/final-response-quality.spec.js:531`, prior deferral at `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md:1143` | The production no-op payload is entity-agnostic, but backend/browser proof uses `entity_type="job"`, `selector_summary="priority = ..."`, `change_summary="priority -> ..."`, and visible `no matching jobs`. | The contract says no-op mutations are entity-agnostic, yet tests can pass without proving product/material/inventory selectors emit or render the same contract. | A non-job no-op could request approval for zero matched records, disappear from final output, or show fake success while RD-006/RD-007 still pass. | Add table-driven no-op fixtures across at least one non-job entity with `entity_type`, `selector_summary`, `change_summary`, `matched_count=0`, `changed_count=0`, `status=not_changed`, and `reason=no_matching_records`. | Phase 21 should identify safe backend metadata/fixture support for non-job no-op. Phase 22 should add one safe non-job no-op contract proof. Phase 23 should keep existing job no-op behavior on the generic contract. Phase 24 may add broader non-job no-op diversity without enabling broad new write behavior. |
| P20-04 | planning-risk | `factory-agent/factory_agent/planning/intent.py:13`, `factory-agent/factory_agent/planning/intent.py:731`, `factory-agent/factory_agent/planning/intent.py:923`, `factory-agent/factory_agent/planning/tool_selector.py:1017` | Semantic write routes are `tool.write.jobs` only; mutation detection is `_is_job_mutation_request`; tool selection maps write/create/delete requests only through job endpoints. | This may be acceptable for today's approved write surface, but it means Phase 17's entity-agnostic no-op wording cannot be exercised naturally for product/material/inventory writes. | New safe write tools for non-job entities would not inherit the no-op/approval/business-change response contract without another entity-specific routing branch. | Before adding write routes, define a route/tool capability contract for mutating entity types and their required approval/no-op metadata. | Defer broad write expansion unless product scope requires it. Phase 21 should add metadata readiness checks only; Phase 22 should add only contract fixtures and abstractions needed to prevent future one-off write routes. |
| P20-05 | product-risk | `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx:316`, `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx:337`, `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx:386`, `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx:481` | Legacy no-`response_document` table suppression detects contradictions through priority columns and priority/job wording such as `jobs affected`, `current vs requested priority`, `priority to high`, and `high-priority`. | The valid response-document path bypasses this code, but compatibility sessions still decide stale-table visibility from job-priority prose instead of typed ownership/state. | A legacy or degraded non-priority mutation could keep stale pre-commit tables visible after completion because the contradiction detector only understands priority words. | Make stale-table suppression use typed `presentation.kind`, operation/approval ownership, row outcome/state, and response-document absence rules; leave text parsing as an explicitly allowlisted fallback. | Phase 23 can keep legacy compatibility behavior unchanged but should prove valid response-document rendering does not rely on priority-word contradiction checks. Phase 25 should add regression guardrails. |
| P20-06 | test_fixture | `eMas Front/e2e/support/responseDocumentScenarios.js:1`, `eMas Front/e2e/support/responseDocumentScenarios.js:32`, `eMas Front/e2e/specs/final-response-quality.spec.js:249`, `eMas Front/e2e/support/responseDocumentProbe.js:41` | Mocked browser fixtures and probes use exact RD prompts, `JOB-SEED-*`, `M-CNC-01`, `Medium -> High`, `Original High -> Low`, `Updated 63 jobs across 22 approved steps`, and dump-style machine labels. | These constants live in test/fixture/probe files and represent deterministic oracle evidence, not product routing/composition logic. | They become risky only if treated as proof of the general contract without adjacent non-job/non-machine rows. | Keep exact fixtures, but pair them with generic contract rows from P20-01/P20-03. | Phase 23 should prove canonical RD fixtures render from generic contract evidence. Phase 24 should add non-job/non-machine variants. Phase 25 should guard generic probes against text-only machine/job assertions. |
| P20-07 | acceptable_fixture | `factory-agent/factory_agent/testing_seeded_scenarios.py:92`, `factory-agent/factory_agent/testing_seeded_scenarios.py:201`, `factory-agent/factory_agent/testing_seeded_adapters.py:26`, `factory-agent/factory_agent/testing_seeded_adapters.py:710`, `tests/e2e/scenarios/manual_prompt_regressions.json:171`, `tests/e2e/scenarios/seed_pipeline.json:241` | Seeded scenarios and adapters contain phase markers, seeded job/machine IDs, controlled LOTO answers, and job-priority cascade interpreters. | They are isolated behind seeded/testing adapters or scenario banks and are intentionally deterministic. The product route/composer no longer branches on these IDs. | Risk is coverage illusion: fixture adapters can duplicate product behavior and hide live planner gaps if promoted as general proof. | Keep these as fixtures; require product contracts to be proven in backend composer/route tests and use real LangGraph only when seeded adapters could hide planner/RAG/tool-selection behavior. | No Phase 21 product behavior change; use as fixtures for new generic status/no-op cases if safe in Phase 22. |
| P20-08 | defer | `factory-agent/factory_agent/rag/knowledge_policy.py:115`, `factory-agent/factory_agent/services/plan_creation_service.py:325`, `docs/qa/HARDCODE_REDUCTION_PLAN.md:252` | Curated fallback policies currently cover LOTO notification and OSHA LOTO, with route/topic scoping through the knowledge policy registry. | This is LOTO-specific, but it is scoped policy data rather than a response-document rendering shortcut, and non-LOTO document prompts do not borrow the OSHA/LOTO fallback. | Future document domains may need similar data-backed policy entries; adding them as inline code would revive the hardcode risk. | Keep curated fallback content behind a policy registry/data pack and require route/topic evidence before applying a fallback. | Defer to the hardcode-reduction/knowledge-policy track unless Phase 22's status/no-op scope touches RAG fallback data. |
| P20-09 | test_fixture | `docs/qa/RESPONSE_DOCUMENT_UX_PLAN.md:1187`, `docs/qa/RESPONSE_DOCUMENT_UX_PLAN.md:1326`, `docs/qa/manual_prompt_regression_bank.md:242`, `docs/qa/manual_prompt_regression_bank.md:247` | QA docs explicitly call out general classes for prior prompt fixes: job-priority no-op must become entity-agnostic, and LOTO notification routing must become generic document-content question typing beyond LOTO. | The docs do not say only "fix this prompt"; they mostly define the broader class and coverage level. | The only remaining doc risk is that Phase 22 could pick one new exact prompt instead of the classes identified here. | Use this Phase 20 inventory as the source of truth and add future bank entries for entity-status and non-job no-op prompt classes. | Phase 21 prepares metadata from P20-01 through P20-03. Phase 22 creates the contracts. Phase 23 migrates existing machine/job behavior. Phase 24 proves broader entity diversity without another one-off prompt patch. |

### Top Risks

1. The read-only status route and proof are still machine-first. The backend status renderer has a generic shape, but planning/tool selection and rich field contracts only prove machine status.
2. Completed mutation composition still derives business groups from priority/job fields and summary regexes. This is the highest risk to any future product/material/inventory mutation result.
3. The no-op mutation contract is implemented with entity-agnostic fields but verified only with job-priority fixtures, leaving a missing general contract for non-job selectors.

### Recommended Phase 21

Phase 21 should be **Backend Capability Metadata Readiness**.

Why this comes first:

- Phase 20 found that the backend route/tool/composition layer still lacks enough generic metadata to support a true entity-generic response contract.
- Starting generic response-document work before backend metadata is ready would repeat the same mistake: frontend and response-composer code would infer status or business changes from job/machine labels, endpoint names, or summary prose.
- The backend needs to expose entity/action/change semantics through OpenAPI, generated tools, generated vocabulary, and `tools.md` before Phase 22 creates generic response-document contracts.

Scope:

- Update Go/OpenAPI metadata where needed so relevant read/status and mutation-capability routes expose:
  - `entity_type`;
  - stable entity identifier fields;
  - read/status capability;
  - write/mutation capability;
  - approval/no-op requirements;
  - business-change field metadata when available.
- Regenerate and verify:
  - `emas/docs/swagger.json`;
  - `emas/docs/swagger.yaml`;
  - `rag_sources/01_emas_internal_docs/api_reference/openapi.json`;
  - `factory-agent/factory_agent/tools.md`;
  - `rag_sources/01_emas_internal_docs/api_reference/tools.md`;
  - `factory-agent/factory_agent/generated/tool_intent_vocabulary.json`.
- Add backend tests proving tool generation and vocabulary preserve generic entity tokens for at least:
  - machine;
  - job;
  - product or material;
  - inventory or work order if present in the current OpenAPI surface.
- Add contract checks proving generated tools contain enough capability metadata for:
  - `entity_status_v1`;
  - `business_change_v1`;
  - `entity_agnostic_no_matching_records_v1`.
- Do not change broad response-document rendering yet. Phase 21 is backend readiness, not the generic UI/composer implementation.

Out of scope:

- Enabling broad product/material/inventory writes.
- Replacing the response-document renderer.
- Replacing seeded fixtures.
- Adding new prompt wording volume that does not test metadata readiness.

### Recommended Phase 22

Phase 22 should be **Generic Entity Status And Mutation Business Contract** after Phase 21 is green.

Scope:

- Add `entity_status_v1` for read-only single-entity status answers.
- Add `business_change_v1` for mutation result groups.
- Add one safe non-job no-op contract proof, even if synthetic at the backend contract layer.
- Add a guard proving machine status is one example of entity status, not the model itself.
- Touch backend contracts first, with focused frontend rendering only if the renderer cannot display the new typed contract correctly.

Phase 22 out of scope:

- Migrating existing RD-001/RD-008 visible flows. That is Phase 23.
- Claiming entity diversity beyond jobs and machines. That is Phase 24.
- Enabling broad product/material/inventory writes.
- Replacing all seeded fixtures.
- Adding more LOTO wording volume unless it exercises a generic document-content route contract.

### Recommended Phase 23

Phase 23 should be **Migrate Existing Machine/Job Outputs Onto Generic Contracts**.

Scope:

- Migrate machine status to the `entity_status_v1` contract without changing the user-facing answer.
- Migrate RD-001/RD-002 job priority cascade output to `business_change_v1` without parsing priority prose or job id shape.
- Keep RD-006/RD-007 no-op behavior working through the generic no-match/no-op contract.
- Add a frontend/probe check that final business groups and status blocks render from contract evidence rather than exact RD-001/RD-008 labels.

### Recommended Phase 24

Phase 24 should be **Entity Diversity Coverage**.

Scope:

- Add safe deterministic coverage for at least two non-job/non-machine examples, such as product status/read result, material/inventory read result, work order status, non-job no-op mutation, or non-job partial/no-op plus valid group.
- Prefer real backend read/status paths where supported.
- Use backend contract fixtures for non-job write outcomes if no safe real write surface exists.

### Recommended Phase 25

Phase 25 should be **Hardcode Regression Guardrails**.

Scope:

- Add guardrails that fail when product code branches on fixture ids, exact prompt text, or specific entity labels outside fixtures/explicit exceptions.
- Add composer guardrails that fail when typed business fields exist but summary prose is used as the business source of truth.
- Add frontend/probe guardrails that require contract evidence instead of machine/job text-only checks.

### Recommended Phase 26

Phase 26 should be **Real Flow Release Proof**.

Scope:

- Run RD-001 cascade, machine status, LOTO document-content RAG, no-op mutation, at least one non-job generic proof if available, and the final response visual-quality oracle through real or seeded release lanes.

### Commands Run

```powershell
git status --short --branch
```

Result: confirmed branch `codex/playwright-e2e-plan`; working tree was clean before audit edits.

```powershell
rg -n "Phase 20|Phase 21|Entity-Specific|overfit|overfitting|fix this prompt|fix prompt|regression" docs/qa/RESPONSE_DOCUMENT_UX_PLAN.md docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md docs/qa/manual_prompt_regression_bank.md
```

Result: located the Phase 20 plan/tracker/bank sections and prior notes that Phase 21 must be chosen from audit findings.

```powershell
rg -n "M-CNC-01|JOB-SEED|JOB-|machine_id|job_id|product|material|inventory|work order|LOTO|priority|status|phase 9|phase 10|phase 14|phase 19|done_all|Machineid|Capacityperhour|No changes were made|Not changed" factory-agent/factory_agent factory-agent/tests "eMas Front/src" "eMas Front/e2e" tests/e2e/scenarios docs/qa
```

Result: 10,312 matches. Findings were narrowed to production routing/composition, frontend compatibility rendering, deterministic fixtures, and docs.

```powershell
rg -n "if .*job|if .*machine|priority|machine status|loto|procedure|status_result|mutation_result|not_changed|no_matching_records" factory-agent/factory_agent/services factory-agent/factory_agent/planning "eMas Front/src/components/features/chat" "eMas Front/e2e/support"
```

Result: 597 matches. Main product-risk clusters were machine-only status routing and priority/job-specific mutation grouping.

```powershell
rg --files docs/qa tests/e2e/scenarios "eMas Front/e2e" factory-agent/factory_agent
```

Result: confirmed the audited docs, scenario banks, frontend E2E fixtures/probes/specs, and backend planning/composition files.

### Files Changed

- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

### Product Behavior

No product behavior changed in Phase 20. This was a docs-only audit. No safety exception was necessary.

### Audit Search Areas

- Exact entity IDs: `M-CNC-01`, `JOB-SEED`, `JOB-`, product/material/work-order fixture ids.
- Entity-type wording: `job`, `machine`, `product`, `material`, `inventory`, `work order`, `LOTO`, `priority`, `status`.
- Route and semantic shortcuts that infer behavior from a narrow phrase instead of typed intent/entity/action fields.
- Response-document composition paths that know about one entity type when they should render generic read/no-op/mutation blocks.
- Frontend renderer/probe assertions that pass because they look for one exact fixture rather than a reusable contract.
- QA phases that say "fix this prompt" without also defining the general class it represents.

### Phase 20 Verification Target

```powershell
git status --short --branch
git diff --check
```

## Phase 21 Checklist

- [x] Confirm branch is `codex/playwright-e2e-plan` and inspect current OpenAPI/tool/vocabulary metadata.
- [x] Identify backend/OpenAPI metadata gaps for generic entity status, mutation business changes, and no-op mutation outcomes.
- [x] Update the backend/OpenAPI source of truth where needed so supported routes expose typed entity/action/capability semantics.
- [x] Regenerate `emas/docs/swagger.json` and `emas/docs/swagger.yaml` when backend Swagger changes.
- [x] Sync `rag_sources/01_emas_internal_docs/api_reference/openapi.json` from the current Swagger/OpenAPI.
- [x] Regenerate `factory-agent/factory_agent/tools.md` using the existing tool generation pipeline.
- [x] Sync `rag_sources/01_emas_internal_docs/api_reference/tools.md` from the regenerated Factory Agent tools reference.
- [x] Regenerate `factory-agent/factory_agent/generated/tool_intent_vocabulary.json`.
- [x] Add or update tests proving generated tools/vocabulary preserve generic entity tokens and capability tags beyond machine/job.
- [x] Add or update tests proving metadata is sufficient for `entity_status_v1`, `business_change_v1`, and `entity_agnostic_no_matching_records_v1`.
- [x] Update tracker and manual regression bank.
- [x] Run backend metadata/tool generation verification.
- [x] Commit Phase 21.

## Phase 21 Implementation Notes

Status: Complete

Phase 21 is backend readiness for generic response-document work. It should improve the backend metadata supply chain, not implement broad frontend rendering or generic response-document composition.

Phase 21 added Swagger enrichment metadata for the generic response-document contract inputs without implementing broad response-document rendering. The enriched OpenAPI now exposes:

- `entity_status_v1` metadata for read-only single-entity status tools: machine, job, product, and inventory material.
- `business_change_v1` metadata for job update and agent transaction dry-run/commit operation-result evidence.
- `entity_agnostic_no_matching_records_v1` metadata for no-match collection reads and agent transaction no-op support.
- Stable entity identifier/display/status fields, approval/no-op hints, business changed fields, selector fields, source-state basis, and operation row outcome fields.

The Swagger enrichment pipeline now also updates `emas/docs/docs.go`, so served Swagger stays aligned with `emas/docs/swagger.json` and `emas/docs/swagger.yaml`. Tool generation now preserves parameter-level `x-ai-*` metadata and keeps `status` as a first-class token instead of singularizing it to `statu`. The generated vocabulary now derives entity tokens from explicit `x-ai-entity` metadata as well as collection shapes, so `inventory`, `job`, `machine`, and `product` are all available to Phase 22.

### Required Metadata Artifacts

The following must be kept in sync when metadata changes:

- `emas/docs/swagger.json`
- `emas/docs/swagger.yaml`
- `rag_sources/01_emas_internal_docs/api_reference/openapi.json`
- `factory-agent/factory_agent/tools.md`
- `rag_sources/01_emas_internal_docs/api_reference/tools.md`
- `factory-agent/factory_agent/generated/tool_intent_vocabulary.json`

### Required Backend Semantics

OpenAPI/tool metadata should be able to express or derive:

- entity type, such as machine, job, product, material, inventory, or work order;
- stable entity id fields and display id fields;
- read/status capability;
- mutation capability;
- approval requirement;
- no-op/no-match outcome support;
- business-change fields, including changed field, previous value, new value, selector, and source-state basis when available.

### Phase 21 Verification Target

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_toolgen.py tests/test_tool_intent_profile.py tests/test_tool_selector.py -q
python scripts/generate_tools.py --local --no-db
python scripts/generate_tool_intent_vocabulary.py

Set-Location ".."
git diff --check
git status --short --branch
```

If Swagger/OpenAPI generation requires the Go backend toolchain, run the existing project command for Swagger regeneration and document it in this tracker. Do not hand-edit generated `tools.md` or generated vocabulary output.

### Phase 21 Commands Run

```powershell
git status --short --branch
```

Result: branch `codex/playwright-e2e-plan`; working tree was clean before Phase 21 edits.

```powershell
python emas\scripts\enrich_swagger_id_patterns.py
```

Result: regenerated/enriched `emas/docs/docs.go`, `emas/docs/swagger.json`, and `emas/docs/swagger.yaml` with Phase 21 contract metadata.

```powershell
python scripts\generate_tools.py --local --no-db
python scripts\generate_tool_intent_vocabulary.py
```

Result: regenerated `factory-agent/factory_agent/tools.md`, `factory-agent/factory_agent/generated/id_patterns.json`, and `factory-agent/factory_agent/generated/tool_intent_vocabulary.json` from local Swagger. Tool count remained 138.

```powershell
Copy-Item -LiteralPath emas\docs\swagger.json -Destination rag_sources\01_emas_internal_docs\api_reference\openapi.json
Copy-Item -LiteralPath factory-agent\factory_agent\tools.md -Destination rag_sources\01_emas_internal_docs\api_reference\tools.md
```

Result: synchronized RAG OpenAPI and tool-reference mirrors.

```powershell
python -m pytest tests/test_toolgen.py tests/test_tool_intent_profile.py tests/test_tool_selector.py -q
```

Result: passed, 44 tests with 12 warnings.

```powershell
git diff --check
```

Result: passed; only existing line-ending normalization warnings were reported by Git.

### Phase 21 Files Changed

- `emas/docs/docs.go`
- `emas/docs/swagger.json`
- `emas/docs/swagger.yaml`
- `emas/scripts/enrich_swagger_id_patterns.py`
- `factory-agent/factory_agent/generated/id_patterns.json`
- `factory-agent/factory_agent/generated/tool_intent_vocabulary.json`
- `factory-agent/factory_agent/planning/tool_intent_profile.py`
- `factory-agent/factory_agent/planning/tool_selector.py`
- `factory-agent/factory_agent/registry/toolgen.py`
- `factory-agent/factory_agent/tools.md`
- `factory-agent/tests/test_tool_intent_profile.py`
- `factory-agent/tests/test_tool_selector.py`
- `factory-agent/tests/test_toolgen.py`
- `rag_sources/01_emas_internal_docs/api_reference/openapi.json`
- `rag_sources/01_emas_internal_docs/api_reference/tools.md`

### Phase 21 Product Behavior

No broad response-document rendering or generic composer migration was implemented. Phase 21 only prepared backend/OpenAPI/tool metadata and tests so Phase 22 can define the generic contracts safely.

## Phase 22 Checklist

- [x] Start only after Phase 21 marks backend metadata ready.
- [x] Add `entity_status_v1` for read-only single-entity status answers.
- [x] Add `business_change_v1` for mutation result groups.
- [x] Add one safe non-job no-op contract proof, even if synthetic at the backend contract layer.
- [x] Add a guard that machine status is one example of entity status, not the model itself.
- [x] Touch backend contracts first; add focused frontend rendering only if needed.
- [x] Update tracker and manual regression bank.
- [x] Run backend contract verification and focused frontend tests if frontend was touched.
- [x] Commit Phase 22.

## Phase 22 Implementation Notes

Status: Complete

Phase 22 created the backend contract surface without broad frontend changes or existing RD-001/RD-008 migration. `status_result` blocks now carry the additive `entity_status_v1` contract, typed mutation groups can emit `business_change_v1` with entity type, change type, selector/source-state basis, ordered field changes, display id, and row outcome, and no-op groups expose the existing entity-agnostic no-match contract in group payloads.

Regression coverage added:

- `factory-agent/tests/test_response_document_contract.py::test_response_document_schema_validates_phase22_generic_contracts`
- `factory-agent/tests/test_response_document_contract.py::test_entity_status_v1_contract_is_not_machine_specific`
- `factory-agent/tests/test_response_document_contract.py::test_business_change_v1_uses_typed_mutation_fields_without_summary_prose`
- `factory-agent/tests/test_response_document_contract.py::test_safe_non_job_noop_contract_proof_completes_without_approval`

Verification:

- `python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q` -> 32 passed.
- Frontend was not changed, so `npm test` was not run.

Phase 22 does not claim entity diversity. The non-job status/no-op examples are synthetic backend contract proofs only; Phase 24 remains responsible for broader entity coverage.

## Phase 23 Checklist

- [ ] Start only after Phase 22 is complete.
- [ ] Migrate existing machine-status response output onto `entity_status_v1`.
- [ ] Migrate existing job priority cascade output onto typed `business_change_v1`.
- [ ] Keep existing job no-op mutation behavior working through the generic no-match/no-op contract.
- [ ] Prove completed mutation grouping no longer parses job/priority prose when typed business-change fields exist.
- [ ] Add focused frontend/probe proof that machine status, job business-change, and no-op blocks render from contract type and typed fields instead of entity names.
- [ ] Preserve RD-001, RD-002, RD-006, RD-007, RD-008, and RD-009 behavior.
- [ ] Update tracker and manual regression bank.
- [ ] Run backend, frontend, and focused browser verification.
- [ ] Commit Phase 23.

## Phase 23 Implementation Notes

Status: Ready To Start

Phase 23 is the migration phase for existing machine/job behavior. It should not claim generic entity diversity yet. It should prove the current machine status, job priority cascade, and job no-op outputs are now expressed through generic typed contracts and that the frontend renders by contract evidence instead of entity names.

## Phase 24 Checklist

- [ ] Start only after Phase 23 is complete.
- [ ] Add safe deterministic coverage for at least two of: product status/read result, material/inventory read result, work order status, non-job no-op mutation, or non-job partial/no-op plus valid group.
- [ ] Prefer real backend-supported read/status paths when available.
- [ ] If a non-job write path is not safely supported, use backend contract fixtures without enabling broad new writes.
- [ ] Prove the response document carries entity type, entity id/display id, primary status or change metadata, row outcome, and no-op counts through typed fields.
- [ ] Add frontend/probe coverage only where visible DOM can diverge from backend contract evidence.
- [ ] Update tracker and manual regression bank.
- [ ] Run backend, frontend, and focused browser verification.
- [ ] Commit Phase 24.

## Phase 24 Implementation Notes

Status: Blocked Until Phase 23

Phase 24 is where the plan earns the word "generic." Passing only `JOB-SEED-*` and `M-CNC-01` examples is not enough. At least two non-job/non-machine examples must pass through the same contract machinery.

## Phase 25 Checklist

- [ ] Start only after Phase 24 is complete.
- [ ] Add guardrails that fail when product code branches on `M-CNC-01`, `JOB-SEED`, exact prompt text, or specific entity labels outside fixtures/explicit exceptions.
- [ ] Add composer guardrails that fail when business facts are derived from summary prose while typed fields are available.
- [ ] Add frontend/probe guardrails that fail when generic checks only inspect machine/job text instead of contract type, block type, entity type, and typed field evidence.
- [ ] Allow exact ids and labels only inside deterministic fixtures, manual banks, seeded scenario definitions, and explicitly named compatibility tests.
- [ ] Document any accepted exception with owner, reason, and expiry/revisit condition.
- [ ] Update tracker and manual regression bank.
- [ ] Run backend and frontend guardrail verification.
- [ ] Commit Phase 25.

## Phase 25 Implementation Notes

Status: Blocked Until Phase 24

Phase 25 prevents future one-off prompt/entity fixes from undoing the generic contract work. Guardrails should separate fixture constants from production logic and should be tight enough to fail before a regression reaches browser-only manual review.

## Phase 26 Checklist

- [ ] Start only after Phase 25 is complete.
- [ ] Run RD-001 cascade real/seeded proof.
- [ ] Run machine status real/seeded proof.
- [ ] Run LOTO document-content RAG proof.
- [ ] Run no-op mutation proof.
- [ ] Run at least one non-job generic proof if the backend surface supports it.
- [ ] Run final response visual-quality oracle.
- [ ] Attach compact semantic probes for browser failures; screenshots/traces remain supporting evidence.
- [ ] Update tracker with real/seeded command results and any accepted gaps.
- [ ] Commit Phase 26.

## Phase 26 Implementation Notes

Status: Blocked Until Phase 25

Phase 26 is the release-confidence pass after backend metadata readiness, contract creation, existing-flow migration, entity diversity coverage, and hardcode guardrails are complete. It should prove backend state, response document, and visible UI agree in real or seeded flows.

## Phase 10 Implementation Notes

Date: 2026-05-18

Phase 10 is complete. Product bugs found and fixed:

- New user messages from `IDLE`, `COMPLETED`, `BLOCKED`, or `FAILED` sessions did not immediately move the session into a live working state, so a poll between message send and plan creation could observe `IDLE`.
- `_persist_plan(... status="DRAFT")` with an empty generated execution draft set `Session.status = IDLE`, leaving an actionable prompt with no plan, approval, terminal event, or typed failure.
- The response-document composer treated non-terminal diagnostic snapshots as generic visible `Needs attention` cards, exposing `non_terminal_snapshot` instead of progress or a typed blocked reason.
- Background execution failures logged the exception without moving the session to a terminal failed state.

### Product Fix

- Normal user messages now advance terminal/idle sessions to `PLANNING` and bump `event_seq`.
- Empty actionable execution plans are converted to `BLOCKED` with typed `planner_no_action` context, operator-friendly cause/current-state/next-action copy, and no data-change claim.
- Legacy orphan snapshots are virtually repaired to `BLOCKED` with typed `orphan_turn_state` diagnostics, preserving the original status only in sanitized technical details.
- Non-terminal progress snapshots render progress/short-message blocks instead of a generic diagnostic card.
- Execution now keeps `BLOCKED`/`FAILED` sessions terminal and marks background startup failures as `FAILED` with typed `unable_to_start_request` evidence.

### Regression Coverage Added

- `factory-agent/tests/test_response_document_contract.py::test_orphan_idle_after_actionable_prompt_becomes_typed_blocked_diagnostic`
- `factory-agent/tests/test_api_endpoints.py::test_actionable_prompt_with_empty_generated_plan_blocks_instead_of_orphan_idle`
- `eMas Front/e2e/specs/final-response-quality.spec.js` RD-001 orphan/session-state browser gate
- `tests/e2e/scenarios/manual_prompt_regressions.json::phase10-chat514-orphan-idle-non-terminal-snapshot`
- `docs/qa/manual_prompt_regression_bank.md` Phase 10 Chat 514 entry

### Commands Run

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py::test_orphan_idle_after_actionable_prompt_becomes_typed_blocked_diagnostic -q
python -m pytest tests/test_api_endpoints.py::test_actionable_prompt_with_empty_generated_plan_blocks_instead_of_orphan_idle -q
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
python -m pytest tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation -q
python -m pytest tests/test_phase18_manual_prompt_bank.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "orphan|non_terminal|RD-001|session state"
```

### Test Results

- New backend orphan snapshot regression: passed after failing before the fix with `session.status == IDLE`.
- New backend empty-plan API regression: passed after failing before the fix with `session.status == IDLE`.
- Backend response-document contract/failure lane: 23 passed.
- Existing approval-resume regression: 1 passed.
- Manual prompt bank gate: 5 passed.
- Frontend unit/component lane: 98 passed.
- Focused mocked response-document browser gate: 1 passed.

## Phase 6-9 Implementation Notes

Date: 2026-05-18

Phases 6, 7, 8, and 9 are complete. Product bugs found and fixed:

- Valid `response_document` turns still computed legacy presentation/tool table paths inside the assistant bubble before choosing the response-document renderer. The assistant bubble now bypasses legacy summary/table derivation whenever a response document is present, and `turnAssembler` applies snapshot `presentation` only when `response_document` is absent.
- Duplicate/idempotent response-document revisions caused `applySnapshot` to skip the whole snapshot, leaving `session` and `pending_approval` stale. Duplicate response-document payloads now keep the current document while still refreshing session and approval state.
- The assistant modal sized itself only when opened. Opening on mobile and resizing to desktop could reveal the sessions sidebar inside a mobile-width chat shell. The modal now refits to the viewport on resize, and the sessions sidebar is hidden on small screens.
- Some seeded/release snapshots expose a valid `approval_required` response-document block without a populated `pending_approval` object. The renderer now derives the actionable approval id from the response-document block as a compatibility fallback.

### Files Changed

- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer.jsx`
- `eMas Front/src/components/features/chat/AIAssistantModal.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentSessionSidebar.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs`
- `eMas Front/e2e/support/responseDocumentScenarios.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/package.json`
- `docs/operations/chatbot_release_runbook.md`
- `docs/qa/RESPONSE_DOCUMENT_UX_PLAN.md`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`

### Decisions Made

- Add a focused mocked browser gate, `npm run test:e2e:response-document`, for fast deterministic response-document UX proof.
- Cover RD-001 and RD-002 as real browser flows with approval clicks, compact approval cards, completed evidence preservation, final aggregate summaries, stale text absence, and mobile/desktop overflow checks.
- Cover read-only machine status, RAG/LOTO source lists, no-result diagnostics, partial failure, planner timeout, rejected approval, expired approval, stale approval, cancelled run, and busy traffic convergence through typed response-document browser fixtures.
- Keep full seeded, real LangGraph, and release projects as broader release/pre-merge lanes rather than making every local response-document iteration run all slow suites.
- Keep `PresentationResponse` in the backend API for compatibility, but isolate frontend legacy fallback to snapshots where `response_document` is absent.
- Treat future LLM polish as copy-only: it cannot change facts, rows, approvals, sources, diagnostics, state, retry safety, or next action, and it must fall back to deterministic copy on schema violation.
- Do not introduce LLM final-response generation or Promptfoo in this plan.

### Commands Run

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
python -m pytest tests/test_typed_snapshot_presentation_contract.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py -q

Set-Location "..\eMas Front"
npm test
$env:PLAYWRIGHT_FACTORY_AGENT_PORT='18023'; $env:PLAYWRIGHT_VITE_PORT='14183'; npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npx playwright test --project=chromium-seeded --grep "SO-041"
npm run test:e2e:release

Set-Location ".."
git diff --check
git status --short --branch
```

### Test Results

- Backend response-document contract/failure lane: 22 passed.
- Backend typed snapshot/timeline/API-alignment lane: 68 passed.
- Frontend unit/component lane: 98 passed.
- Focused mocked response-document browser gate on fresh ports: 11 passed.
- Focused seeded SO-041 lane: failed on old phrase/state expectations around seeded response-document cascade display; backend oracle state still produced approval evidence, but the seeded browser assertions have not yet been migrated to the response-document UI contract.
- Broad seeded oracle lane: 8 passed, 16 failed. Failures are concentrated in older seeded data-integrity/prompt/SSE assertions that still expect legacy phrase copy or old terminal text instead of typed response-document blocks.
- Release project: 17 passed, 4 failed. The `release-validation.spec.js` release gate passed; remaining failures are in `release-resilience.spec.js` old-copy/legacy resilience expectations that need a separate response-document migration.

### Accepted Gaps

- Manual layout review remains allowed as supporting evidence only; it cannot replace the typed contract, unit/component, mocked browser, seeded oracle, or release validation lanes.
- Full seeded oracle and release-resilience browser suites still need a follow-up migration from legacy phrase assertions to typed response-document assertions. The new deterministic mocked response-document gate is blocking for this UX release gate; the old seeded/release-resilience migration is tracked as a non-blocking compatibility cleanup lane.
- Real LangGraph critical was not rerun in this pass because the focused mocked response-document gate and backend oracle lanes covered the deterministic contract, while seeded/release lanes exposed existing assertion migrations.
- Full Promptfoo/LLM semantic evaluation remains future work and is intentionally excluded from this deterministic release gate.

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

Start Phase 23 machine/job generic-contract migration. Phase 22 has created `entity_status_v1`, `business_change_v1`, one safe synthetic non-job no-op proof, and the guard that machine status is only one entity-status example. After Phase 23, continue in order through Phase 24 entity diversity, Phase 25 hardcode guardrails, and Phase 26 real-flow release proof.

## Post-Gate Regression: Approved Data But UI Still Shows Approval

Date: 2026-05-18

Status: In Progress

### Symptom

- Manual browser verification showed the compact `response_document` approval card still visible after the operator approved the request and backend data had already changed.
- The visible UI remained on `Waiting for approval 1` / `Approval required` for `change all medium priority job to high then change all high priority job to low`.

### Root Cause

- The frontend reducer correctly rejects conflicting same-revision response documents to prevent stale event storms from overwriting the current UI.
- The backend response-document revision uses `Session.event_seq`.
- `/approvals/{id}/approve` bumped `event_seq` when the approval was accepted, but the later graph resume / `_persist_plan(... status="COMPLETED")` write did not bump `event_seq`.
- Result: the browser could receive a completed response document with the same revision as the intermediate "approval received/applying" document. The reducer treated that as an equal-revision conflict and kept the older pending approval UI.

### Testing Gap

- Phase 5 tested frontend reducer ordering with synthetic newer/stale revisions.
- Phase 6-9 browser fixtures used mocked response-document revisions that already advanced correctly.
- No backend integration test asserted that the real approval-resume commit produces a strictly newer `response_document.revision` than the post-approval applying snapshot.

### Regression Coverage Added

- `factory-agent/tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation`
  now asserts:
  - the post-approval applying snapshot has no actionable `approval_required` block;
  - the final completed response document revision is strictly greater than the applying response document revision;
  - the final document is `completed`;
  - the final document has no waiting/current approval run step and no approval-required block.

### Product Fix

- `PlanCreationService._persist_plan` now advances both `version` and `event_seq` for state-changing plan/session persistence.
- Response-summary replacement commits in `_persist_plan` also advance `event_seq`.
- Graph approval resume failure paths now advance `event_seq` when they move the session to `BLOCKED` or `FAILED`.

### Verification

- `python -m pytest tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation tests/test_response_document_contract.py tests/test_response_document_failures.py tests/test_typed_snapshot_presentation_contract.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py -q` -> 91 passed.
- `node --test --test-concurrency=1 "src/components/features/chat/factory-agent/responseDocumentReducer.test.mjs"` -> 11 passed.
- `git diff --check` -> passed with line-ending warnings only.

## Post-Gate Regression: Chat 514 Orphan IDLE Diagnostic

Date: 2026-05-18

Status: Fixed in Phase 10; later phases add broader transition/probe hardening.

### Symptom

- Manual browser screenshot shows active chat `Chat 514` with the user prompt `change all medium priority job to high then change all high priority job to low`.
- Assistant bubble renders:
  - `Needs attention`;
  - `The request needs attention before it can continue.`;
  - technical details containing `Reason: non_terminal_snapshot` and `Session status: IDLE`.
- Header shows `Ready`, while the sidebar row for the same chat can still show `WAITING FOR APPROVAL`.

### Why This Page Exists

- `response_document` is doing what it was told for an impossible state: it received a snapshot that looked non-terminal and not actionable.
- The backend snapshot had enough state to render a diagnostic, but not enough state to prove the request was running, waiting for approval, completed, cancelled, blocked, or failed.
- For a normal sent prompt, `IDLE + non_terminal_snapshot + no terminal result` is not a valid user-facing state. It should be prevented upstream or converted into a clear blocked/failure reason.

### Why Existing E2E Did Not Catch It

- The response-document E2E gate focused on mocked fixtures whose revisions and terminal states were already well shaped.
- Existing backend tests asserted many final states, but did not encode the invariant: "after the latest user message, a normal actionable prompt must not settle as IDLE with no terminal/pending/failure state."
- Existing browser tests often checked final success or specific blocks, but did not globally forbid `non_terminal_snapshot` / `Session status: IDLE` / generic `Needs attention` for normal prompts.
- Full Playwright snapshots are too long and low-signal; they show the page but do not directly compare UI header/sidebar/status with backend snapshot and response-document state.

### Testing Direction

- Phase 10 blocks the invalid backend state and adds the first executable Chat 514 regression.
- Phase 11 adds visible transition oracles.
- Phase 12 improves artifacts with compact semantic probes.
- Phase 13 forces every manual screenshot bug into a regression bank and executable test.
