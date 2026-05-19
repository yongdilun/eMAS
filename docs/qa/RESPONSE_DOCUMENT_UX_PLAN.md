# Response Document UX And Final Response Quality Plan

Branch: `codex/playwright-e2e-plan`
Created: 2026-05-18

## Purpose

Replace fragile final-response rendering with a backend-owned typed response document that gives operators a reliable step-by-step view, compact approvals, and deterministic final summaries. This plan is intentionally separate from the existing hardcode-reduction work because the problem is not only routing correctness; it is response composition, progress UX, approval ergonomics, and final-response testability.

## Current Problem

The chatbot can now pass strong backend, seeded browser, and real LangGraph tests, but the answer surface still has product risk:

- Final responses can miss important details from multi-step work.
- Multi-approval flows can show only the newest approval/result instead of preserving completed step evidence.
- The UI can show stale timeline/current-state text while the backend state has moved on.
- Table/list choice is inferred from result shape or legacy presentation instead of a stable response contract.
- Approval cards can occupy too much chat space and make multi-step flows hard to read.
- Frontend logic still contains compatibility paths that rank, merge, or suppress old `presentation` and table evidence.
- Existing tests cover many state/truth bugs, but they do not yet enforce a complete response-document UX standard.

## Decisions Made

| Decision | Chosen direction |
| --- | --- |
| Final response truth | Deterministic backend truth. No LLM final-response layer for now. |
| Response format | Typed response blocks only. Markdown is not the UI contract. |
| Progress UX | Compact in-chat run activity plus short conversational status message. |
| Multi-step evidence | Preserve completed step evidence; latest pending approval is primary. |
| Layout ownership | Backend sends typed response document; frontend renders block types. |
| LLM usage | Not in scope for this plan. Future LLM polish can be planned later only after deterministic quality is stable. |
| Detail strategy | Progressive disclosure: short default, expandable details. |
| Progress source of truth | Backend-owned typed `run_steps`, derived from execution state/timeline. |
| Approval UI | Compact by default, expandable for records/details, actions always visible. |
| Testing strategy | Both typed backend contract tests and visible browser E2E tests. |
| Migration | Add `response_document` beside existing `presentation`, migrate frontend, then complete a mandatory cleanup phase. |
| Flagship scenario | Multi-step two-approval mutation, starting with medium -> high then original high -> low; also cover the reverse cascade. |
| Phase completion rule | Any product bug found blocks phase completion until fixed. |
| Busy traffic rendering | Latest valid response-document revision is truth; frontend coalesces fast updates and preserves `run_steps` history. |
| Stale ordering | Backend prevents stale snapshots; frontend refuses stale documents; no frontend merging of older revisions. |
| Revision scope | Use both session-level `snapshot_revision` and per-turn `response_document.revision`. |
| Transport conflicts | Highest valid revision wins regardless of SSE or polling transport. |
| Invalid document | Existing but invalid `response_document` renders a safe diagnostic and logs a contract violation; old `presentation` fallback is allowed only when the document is absent. |
| Reducer ownership | A centralized frontend response-document reducer/store update function owns ordering, validation, coalescing, and collapse preservation. |
| Revision ownership | Backend owns monotonic response-document revisions. |
| Block identity | Backend generates deterministic block ids from operation, approval, step, and source identity. |
| Block lifecycle | Backend decides which blocks remain, change, or disappear; frontend does not invent removed-block history. |
| Flicker testing | Use event-storm convergence tests plus Playwright failure artifacts, not brittle millisecond flicker assertions. |
| Broken-flow UX | Broken flows render typed operator-friendly failure cards with cause, impact, current state, and next actions. |
| Failure taxonomy | Use typed failure reasons and deterministic templates, not generic messages or raw backend errors. |
| Failure detail | Show operator-friendly summary by default; technical diagnostics stay collapsed. |
| Failure actions | Actions are context-aware and gated by safety/retry policy. |
| Partial-progress failure | Show both completed progress and failure impact together. |
| Final mutation result shape | Short summary plus grouped business changes plus compact affected-record preview. |
| Final mutation detail | Expandable clean audit grouped by business change. |
| Final mutation display source | Backend `response_document` typed facts, not raw assistant final markdown. |
| Internal identifiers | `operation_id`, `step_id`, `row_id`, and raw audit ids stay out of normal rendered chat. |
| Final response row preview | Show at most 5 affected records by default, with expandable full clean audit. |
| Final response aggregation | Aggregate by business write set, not backend operation, tool call, audit row, or execution step count. |

## Target Architecture

### Response Document

The backend snapshot/final-response payload should include an additive `response_document` field:

```json
{
  "response_document": {
    "version": 1,
    "document_id": "rd-session-1-turn-3",
    "turn_id": "turn-3",
    "state": "waiting_approval",
    "intent_id": "intent-...",
    "operation_id": "op-...",
    "revision": 7,
    "revision_source": "timeline_sequence",
    "current_step_id": "approval-2",
    "run_steps": [],
    "blocks": [],
    "invariants": {},
    "diagnostics": {}
  }
}
```

`response_document` is the new UI source of truth when present. Existing `presentation` remains temporarily for compatibility only and must be retired from frontend decision-making in the cleanup phase.

### Revision And Busy-Traffic Contract

Response-document rendering must be robust when backend, SSE, and polling updates arrive very quickly, duplicated, or out of order.

The backend payload should carry both session and document ordering:

```json
{
  "session_id": "session-1",
  "snapshot_revision": 42,
  "active_turn_id": "turn-3",
  "response_document": {
    "document_id": "rd-session-1-turn-3",
    "turn_id": "turn-3",
    "operation_id": "op-123",
    "revision": 7,
    "revision_source": "timeline_sequence",
    "state": "waiting_approval",
    "run_steps": [],
    "blocks": []
  }
}
```

Ordering rules:

- Backend owns monotonic `response_document.revision`.
- `snapshot_revision` protects whole-session ordering.
- `response_document.revision` protects one assistant turn or operation.
- `turn_id` prevents an old operation from overwriting a newer user turn.
- `operation_id` links approvals, audit rows, DB mutations, and final result.
- Backend must prevent stale snapshots where possible.
- Frontend must refuse stale documents that arrive anyway.
- For the same `session_id`, `document_id`, and `turn_id`, the highest valid `response_document.revision` wins regardless of whether it arrived by SSE or polling.
- Lower revisions are ignored for primary rendering.
- Duplicate same-content revisions are ignored.
- Same revision with conflicting content is a contract violation; render a safe diagnostic or keep the existing stable document and log telemetry.
- If `response_document` is absent during migration, legacy fallback is allowed.
- If `response_document` exists but is structurally invalid, do not fall back to old `presentation`; show a safe diagnostic and report the violation.

Fast-event rendering rules:

- Frontend should render the latest valid response-document revision, not every raw event.
- Frontend may coalesce rapid updates on the next animation frame or a short window such as 50-100ms.
- Do not force fake minimum display time for normal progress.
- Preserve completed `run_steps` history in the latest document.
- Sticky states such as pending approval remain visible until the backend sends a valid newer decision state.
- User expand/collapse state is keyed by stable block id and must survive polling/SSE updates.

### Frontend Response-Document Reducer

All incoming response-document updates should pass through one centralized reducer/store update function, for example:

```js
applyResponseDocumentUpdate(currentState, incoming, transportMeta)
```

The reducer owns:

- document validation
- `snapshot_revision` and `response_document.revision` comparison
- SSE versus polling conflict resolution
- duplicate/stale revision handling
- same-revision conflict handling
- turn/document identity checks
- coalescing fast updates
- preserving expand/collapse state by stable block id
- emitting safe diagnostics for invalid documents

Renderer components must not implement their own revision ordering logic.

### Stable Block Identity And Lifecycle

Block ids must be deterministic:

```json
[
  { "id": "activity:rd-session-1-turn-3", "type": "run_activity" },
  { "id": "message:approval-1:pending", "type": "short_message" },
  { "id": "approval:approval-1", "type": "approval_card" },
  { "id": "completed-step:op-1", "type": "completed_step" },
  { "id": "result-table:op-1:affected-records", "type": "result_table" }
]
```

Rules:

- Same logical block keeps the same id across revisions.
- Do not use array index or random UUID as block identity.
- Approval card id should be derived from `approval_id`.
- Completed step id should be derived from `operation_id` or `intent_id`.
- Activity id should be derived from `document_id`.
- Result table id should be derived from operation plus table purpose.
- Backend decides block lifecycle. If a pending approval disappears, important completed evidence must reappear as a completed-step/history block.
- Frontend renders accepted blocks and preserves local UI state only for block ids that still exist.

### Run Steps

`run_steps` should represent operator-level progress, not raw timeline rows:

```json
{
  "step_id": "approval-2",
  "kind": "approval",
  "state": "waiting",
  "title": "Waiting for approval 2",
  "summary": "11 original high-priority jobs are ready for review.",
  "approval_id": "approval-2",
  "operation_id": "op-2",
  "record_count": 11,
  "current": true
}
```

Expected step kinds:

- `analysis`
- `read`
- `approval`
- `mutation`
- `knowledge`
- `diagnostic`
- `cancelled`
- `completed`

Expected step states:

- `pending`
- `current`
- `waiting`
- `completed`
- `failed`
- `rejected`
- `expired`
- `cancelled`

### Blocks

The frontend should render block types rather than infer layout from text:

- `run_activity`
- `short_message`
- `approval_card`
- `completed_step`
- `result_summary`
- `result_table`
- `record_preview`
- `source_list`
- `warning`
- `diagnostic`

Required block rules:

- `run_activity` appears near the top of the assistant bubble for active or completed agent work.
- `short_message` gives a concise conversational status.
- `approval_card` is compact by default, with top 3-5 records and expandable details.
- `completed_step` stays visible after later approvals become pending.
- `result_summary` aggregates all completed steps at final completion.
- `result_table` is used when row-level comparison is necessary.
- `source_list` is used for RAG/knowledge answers with source metadata.
- `diagnostic` is used for empty final response, backend errors, validation/guard failure, timeout, rejected, expired, or cancelled states.

### Failure Recovery Contract

Broken flows must never end as a blank response, raw JSON, endless spinner, or vague "needs attention" message. They should render a typed operator-friendly failure card:

```json
{
  "id": "diagnostic:op-123:planner-timeout",
  "type": "diagnostic",
  "severity": "error",
  "reason": "planner_timeout",
  "title": "Run interrupted",
  "user_message": "I could not finish this request because the planner timed out while preparing the next step.",
  "impact": {
    "changes_applied": true,
    "completed_steps": ["op-1"],
    "incomplete_steps": ["approval-2"],
    "changed_count": 10,
    "unchanged_count": 11,
    "safe_to_retry": true,
    "safe_resume_step": "step-2"
  },
  "next_actions": [
    { "id": "retry_from_checkpoint", "label": "Retry from last safe point" },
    { "id": "start_new_request", "label": "Start new request" },
    { "id": "view_diagnostics", "label": "View diagnostics" }
  ],
  "technical_details": {
    "error_code": "planner_timeout",
    "trace_id": "trace-..."
  },
  "details_collapsed": true
}
```

Failure taxonomy should include:

- `planner_timeout`
- `planner_validation_loop`
- `llm_timeout`
- `tool_timeout`
- `tool_http_error`
- `tool_schema_error`
- `approval_expired`
- `approval_rejected`
- `approval_stale`
- `network_disconnect`
- `sse_stream_interrupted`
- `snapshot_contract_invalid`
- `response_document_invalid`
- `auth_denied`
- `cancelled_by_user`
- `partial_commit_failure`
- `unknown_failure`

Failure templates must define:

- operator title
- operator-safe message
- severity
- impact policy
- retry policy
- default next actions
- collapsed technical diagnostics policy

Failure rendering rules:

- Do not show stack traces or raw technical details by default.
- Do not expose secrets, environment values, or raw tokens.
- Show whether changes were applied, not applied, partially applied, or unknown.
- Show last completed safe step when available.
- Show incomplete steps when a multi-step flow breaks.
- Do not offer retry if it could duplicate mutation unless idempotency/operation state proves safety.
- If commit state is uncertain, show "Check status" before retry.
- If part of the flow completed before failure, show completed progress and failure impact together.
- Approval expired/stale/rejected states must not show active approval actions.

### Deterministic Composer

The backend should own a deterministic response composer that converts execution state, approvals, audit rows, timeline, and typed presentation evidence into `response_document`.

The composer must decide:

- Which blocks appear.
- Block order.
- Which approval is primary.
- Which completed steps remain visible.
- Whether data appears as a compact preview, list, or table.
- Whether details are collapsed by default.
- Whether final result is successful, partial, rejected, expired, cancelled, or diagnostic.

The frontend must not decide these from prose.

## Flagship UX Standard

Prompt A:

```text
change all medium priority job to high then change all high priority job to low
```

After first pending approval:

```text
Run activity
[done] Understood request
[done] Found 10 original medium-priority jobs
[current] Waiting for approval 1

I found 10 jobs that are currently medium priority. Please review before I update them to high priority.

Approval required
Update 10 jobs from medium -> high

Affected records
JOB-SEED-002
JOB-SEED-004
JOB-SEED-007
+7 more

[Approve] [Reject] [View details]
```

After approval 1 and pending approval 2:

```text
Run activity
[done] Understood request
[done] Found 10 original medium-priority jobs
[done] Approval 1 received
[done] Updated 10 jobs: medium -> high
[done] Found 11 original high-priority jobs
[current] Waiting for approval 2

Done. I updated the first 10 jobs from medium to high. I also found 11 jobs that were originally high priority. Please review before I update them to low.

Completed step
Updated 10 jobs from medium -> high
[View details]

Approval required
Update 11 jobs from high -> low

Affected records
JOB-SEED-001
JOB-SEED-003
JOB-SEED-006
+8 more

[Approve] [Reject] [View details]
```

After final approval:

```text
Run complete

Updated 21 jobs across 2 approved steps.

Step 1
10 original medium-priority jobs changed to high.

Step 2
11 original high-priority jobs changed to low.

No jobs were created or deleted.
[View affected records]
```

Prompt B should also be covered:

```text
change all high priority job to low then change all low priority job to medium
```

## Phased Implementation Plan

### Phase 0: Response Gap Audit And Contract Inventory

Goal: Map current final-response, presentation, timeline, approval, and frontend rendering behavior before implementing the new document.

Files likely touched:

- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/schemas.py`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- existing tests under `factory-agent/tests` and `eMas Front/e2e`

Implementation steps:

- Inventory where final text, typed `presentation`, timeline events, approval bundle UI, table presentation, and frontend summaries are produced.
- Identify every place where frontend still infers state/layout from text or legacy table presentation.
- Document the exact response bugs already observed: missing multi-step conclusion, stale read summary overriding mutation summary, approval card size, stale current timeline, collapse reopening.
- Confirm which current tests already cover these behaviors and where they are missing.

Acceptance criteria:

- Tracker lists current response paths and known gaps.
- No product behavior changes are made in this phase.
- Phase 1 implementation scope is explicit.

Verification command:

```powershell
git diff --check
```

Risks:

- Audit may reveal existing hidden dependencies on `presentation` that must be migrated carefully.

### Phase 1: Backend Response Document Schema

Goal: Add additive typed `response_document` schema without changing frontend behavior yet.

Files likely touched:

- `factory-agent/factory_agent/schemas.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/tests/test_response_document_contract.py`
- `factory-agent/tests/test_typed_snapshot_presentation_contract.py`

Implementation steps:

- Define `ResponseDocument`, `RunStep`, and block schemas.
- Add `response_document.version = 1`.
- Include `state`, `current_step_id`, `run_steps`, `blocks`, `invariants`, and `diagnostics`.
- Keep existing `presentation` unchanged.
- Add backend tests proving `response_document` exists and agrees with existing typed state for common states.

Acceptance criteria:

- Snapshot/final payload includes `response_document`.
- Existing tests remain green.
- No frontend uses `response_document` yet.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_typed_snapshot_presentation_contract.py -q
```

Rollback notes:

- Additive schema can be disabled from snapshot response if needed while keeping tests pending.

### Phase 2: Deterministic Composer And Run Steps

Goal: Build backend deterministic composer for high-quality response documents.

Files likely touched:

- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/tests/test_response_document_contract.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`

Implementation steps:

- Create a response document composer module if it keeps `session_snapshot_service.py` smaller.
- Build `run_steps` from execution state, approvals, audit evidence, timeline, and current session state.
- Build blocks using deterministic rules.
- Implement compact preview versus table rules.
- Implement multi-step aggregation rules.
- Preserve completed step cards when later approval is pending.
- Ensure final completion aggregates all steps and does not get overwritten by stale read/tool summaries.
- Add contract tests for pending approval, approval 1 complete/approval 2 pending, final complete, rejection, expiry, cancel, partial failure, RAG answer, and diagnostic.

Acceptance criteria:

- Flagship Prompt A backend contract passes through each state.
- Prompt B backend contract is covered at least at final result state.
- No final success while any approval is pending.
- Any product bug found is fixed before continuing.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_snapshot_timeline_final_response_contract.py tests/test_langgraph_state_machine_oracles.py -q
```

### Phase 3: Failure Recovery Response Documents

Goal: Give broken flows clear, safe, deterministic chat responses with cause, impact, current state, and next actions.

Files likely touched:

- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/schemas.py`
- `factory-agent/factory_agent/graph/nodes/planner_loop.py`
- `factory-agent/factory_agent/services/planner_service.py`
- `factory-agent/factory_agent/services/execution_service.py`
- `factory-agent/tests/test_response_document_failures.py`
- `factory-agent/tests/test_response_document_contract.py`

Implementation steps:

- Add typed failure taxonomy and deterministic templates.
- Map planner timeout, planner validation loop, LLM timeout, tool timeout, tool HTTP error, tool schema error, approval expired/stale/rejected, network disconnect, SSE interruption, auth denied, cancellation, partial commit failure, invalid response document, and unknown failure.
- Add failure card block fields for `reason`, `severity`, `title`, `user_message`, `impact`, `next_actions`, `technical_details`, and `details_collapsed`.
- Add impact policies for no changes, partial changes, unknown commit state, completed approval, incomplete approval, and safe resume.
- Add retry/action policies such as `retry_from_checkpoint`, `retry_failed_rows_only`, `check_status`, `request_new_approval`, `start_new_request`, `sign_in_again`, `view_affected_records`, `view_diagnostics`, and `export_audit_details`.
- Ensure partial-progress failures show completed work and incomplete work together.
- Ensure raw technical errors stay collapsed and sanitized.
- Ensure broken flows never render blank final response, raw JSON, spinner forever, or generic failure copy without next action.

Acceptance criteria:

- Timeout and validation-loop failures render operator-friendly failure cards.
- Partial-progress failure card shows completed step evidence plus incomplete-step impact.
- Context-aware next actions respect safety and retry policy.
- Technical details are collapsed by default and sanitized.
- Any product bug found is fixed before continuing.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_failures.py tests/test_response_document_contract.py tests/test_typed_snapshot_presentation_contract.py -q
```

### Phase 4: Frontend Response Document Renderer

Goal: Render `response_document` block types in the chat UI.

Files likely touched:

- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer.jsx`
- `eMas Front/src/components/features/chat/factory-agent/responseDocumentContract.js`
- `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- frontend component tests

Implementation steps:

- Add response document normalization on the frontend.
- Render `run_activity`, `short_message`, `approval_card`, `completed_step`, `result_summary`, `result_table`, `source_list`, `warning`, and `diagnostic`.
- Make approval card compact by default with expandable details.
- Keep latest pending approval primary.
- Preserve completed step evidence above or near the pending approval.
- Ensure expand/collapse state does not auto-reset from later polling/SSE updates.
- Keep old `presentation` fallback only when `response_document` is missing.

Acceptance criteria:

- Frontend uses `response_document` when present.
- Approval cards no longer take over the whole chat by default.
- Completed step evidence remains visible during approval 2.
- Existing presentation-based sessions still render through fallback.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
```

### Phase 5: Response Document Reducer And Busy-Traffic Ordering

Goal: Make fast backend, SSE, and polling updates render deterministically without flicker, stale downgrades, or collapse-state resets.

Files likely touched:

- `eMas Front/src/components/features/chat/factory-agent/responseDocumentReducer.js`
- `eMas Front/src/components/features/chat/factory-agent/responseDocumentContract.js`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/responseDocumentReducer.test.mjs`
- `eMas Front/e2e/specs/response-document-traffic.spec.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`

Implementation steps:

- Add a centralized `responseDocumentReducer` or equivalent store update function.
- Validate incoming documents before rendering.
- Apply `snapshot_revision`, `document_id`, `turn_id`, and `response_document.revision` ordering.
- Accept only higher valid revisions for the same document.
- Ignore stale lower revisions from either SSE or polling.
- Detect same-revision conflicting content and render/log a contract violation diagnostic.
- Coalesce fast update bursts on the next animation frame or a short delay such as 50-100ms.
- Preserve expand/collapse state by stable block id across accepted revisions.
- Prevent old turns/documents from updating the active turn UI.
- Add reducer/unit tests for stale, duplicate, conflicting, invalid, and cross-turn documents.
- Add mocked Playwright event-storm tests for fast progress, out-of-order SSE/polling, final-then-stale-pending, approval 1 completion then approval 2 pending, and collapse stability.

Acceptance criteria:

- Highest valid revision wins regardless of transport.
- Invalid existing `response_document` shows a safe diagnostic instead of falling back to old `presentation`.
- Completed `run_steps` history remains visible after fast event bursts.
- Final complete cannot be downgraded by stale pending approval.
- Pending approval cannot be cleared by stale lower revision.
- Collapse state survives newer accepted revisions.
- Event-storm tests converge to the correct visible UI without stale text after settle.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium --grep "response document|event storm|revision|traffic"
```

Risks:

- Over-broad coalescing can hide important pending approval updates. Approval state must remain sticky until a valid newer decision state arrives.
- If backend revisions are not truly monotonic, frontend tests will expose it but the fix belongs in backend revision generation.

### Phase 6: Final Response Quality E2E Gate

Goal: Add Playwright tests dedicated to final response UX and progress behavior.

Files likely touched:

- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/support/responseDocumentScenarios.js`
- seeded scenario data where needed
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`

Implementation steps:

- Add flagship seeded/browser test for Prompt A.
- Add Prompt B coverage.
- Assert visible run activity steps in order.
- Assert approval 1 compact card, approval 2 compact card, and final aggregate result.
- Assert completed step remains visible when approval 2 is pending.
- Assert no stale `Current`, stale read summary, stale approval wait, or fake success.
- Assert card default height/compact preview behavior where feasible.
- Assert collapse does not reopen after polling/SSE update.
- Add partial failure, rejected, expired, cancel, RAG/source, and long-table coverage in focused cases.

Acceptance criteria:

- E2E catches the final-response bugs that previously required manual screenshot inspection.
- Browser proof includes typed document assertions and visible DOM assertions.
- Any product bug found blocks phase completion.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph -- --grep "SO-041|final response|response document|@critical"
```

### Phase 7: Compact Approval And Progressive Disclosure Hardening

Goal: Polish approval ergonomics and details behavior after core rendering works.

Files likely touched:

- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- frontend CSS/component tests
- Playwright visual/DOM assertions

Implementation steps:

- Cap default approval-card height.
- Show top 3-5 records plus `+N more`.
- Keep approve/reject actions visible without scrolling inside huge tables.
- Move full affected-record table into expandable details.
- Make completed/rejected/expired approvals compact history cards.
- Test mobile and desktop widths for text overflow and layout stability.

Acceptance criteria:

- Approval card does not dominate the chat.
- Multi-step approval flow remains readable.
- UI text does not overlap or overflow.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e:seeded-oracles -- --grep "approval|response document|SO-041"
```

### Phase 8: Mandatory Compatibility Cleanup

Goal: Remove old frontend decision-making from legacy `presentation` once `response_document` rendering is stable.

Files likely touched:

- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- `eMas Front/src/components/features/chat/factory-agent/presentationContract.js`
- `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `factory-agent/tests/test_hardcode_guardrails.py`
- frontend tests

Implementation steps:

- Make `response_document` the only primary UI contract.
- Keep legacy `presentation` only for sessions without `response_document`.
- Add guardrails so new response-document-capable code cannot add phrase-based state inference.
- Remove or isolate table contradiction/ranking logic that was only needed for old presentation merging.
- Update docs with the retirement policy.

Acceptance criteria:

- New sessions render from `response_document`.
- Old `presentation` fallback is clearly isolated.
- Tests fail if frontend ignores `response_document` and chooses old presentation/phrase logic.

Implementation clarification after Phase 8:

- Legacy `presentation` remains only as a compatibility fallback for snapshots where `response_document` is absent.
- When `response_document` is present, the assistant bubble must not compute primary tables, summaries, or approval state from old `presentation`, tool table heuristics, or approval-wait phrases.
- If `response_document` is present but invalid, the frontend renders the safe response-document diagnostic and does not fall back to legacy presentation.
- Backend `PresentationResponse` remains in the API for compatibility until a separate API retirement plan proves old snapshots and clients no longer need it.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_hardcode_guardrails.py tests/test_response_document_contract.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:seeded-oracles
```

### Phase 9: Release Gate And Future LLM Handoff

Goal: Stabilize the new response-document pipeline and document future LLM polish as separate work.

Implementation steps:

- Run the full release gate.
- Document final response quality coverage and remaining accepted gaps.
- Record that LLM polish is out of scope until deterministic response quality is stable.
- If future LLM polish is added, require schema validation and fallback to deterministic text.
- Future LLM polish may only rewrite safe explanatory copy. It must not change facts, rows, approval ids, approval state, sources, diagnostics, run state, current/next action, retry safety, or any mutation outcome.
- Promptfoo or broad semantic LLM evaluation remains out of scope for this deterministic response-document release gate.

Acceptance criteria:

- Backend, frontend, seeded browser, and real LangGraph critical gates pass.
- Response-document docs explain owner, contract, and migration status.
- No old/new source-of-truth ambiguity remains.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:backend-oracles
npm test
npm run test:e2e:mocked
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
npm run test:e2e:release
```

### Phase 10: Orphan Turn And Session State Invariant Gate

Goal: Prevent user-visible orphan turns such as `IDLE` + `non_terminal_snapshot` + "Needs attention" after a normal prompt.

Problem this phase targets:

- A user can send a real request and end up with a chat bubble that says the request needs attention, with technical detail `Reason: non_terminal_snapshot` and `Session status: IDLE`.
- This page exists because the backend has a user turn but no terminal result, no pending approval, no blocked/failed reason, and no completed response document.
- That state is a contract violation for normal chatbot flow. It should either continue running, show a real pending approval, complete, or fail/block with an operator-friendly reason.

Files likely touched:

- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/services/execution_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/tests/test_response_document_contract.py`
- `factory-agent/tests/test_api_endpoints.py`
- `eMas Front/e2e/specs/final-response-quality.spec.js`

Implementation steps:

- Define an orphan-turn invariant: after the latest user message, the session must not settle as `IDLE` with no terminal event, no pending approval, no confirmation, no explicit cancellation, and no blocked/failed reason.
- Add backend tests that seed/send a user request and assert the snapshot is never `IDLE/non_terminal_snapshot` for an actionable prompt.
- If the planner produces no executable steps for an actionable prompt, transition to `BLOCKED` with a typed `planner_no_action` or `unable_to_start_request` diagnostic instead of `IDLE/non_terminal_snapshot`.
- If the request should create an approval, ensure the snapshot has `WAITING_APPROVAL`, `pending_approval`, an approval block, and matching session-list status.
- Add a frontend/browser test that sends RD-001 and fails if visible text includes `non_terminal_snapshot`, generic `Needs attention`, or `Session status: IDLE` before a terminal result.

Acceptance criteria:

- Normal user prompts cannot produce an orphan `IDLE/non_terminal_snapshot` response document.
- The user never sees internal `non_terminal_snapshot` as the main response for RD-001/RD-002.
- If the backend cannot start the request, it returns a typed blocked/failure reason with next action.
- Session header, session list, snapshot status, and response document state agree for the active chat.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_api_endpoints.py tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm run test:e2e:response-document -- --grep "orphan|non_terminal|RD-001|session state"
```

### Phase 11: Real Flow Browser State-Transition Oracle

Goal: Add browser tests that prove the real UI follows every critical state transition, not only final backend state.

Problem this phase targets:

- Existing E2E coverage was strong on backend assertions and mocked response documents, but weak on visible transition checkpoints.
- A bug can pass if data changes correctly while the UI remains stuck on an old approval or diagnostic card.

Files likely touched:

- `eMas Front/e2e/support/responseDocumentScenarios.js`
- `eMas Front/e2e/support/factoryAgentAssertions.js` or equivalent support file
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`
- `factory-agent/tests/test_api_endpoints.py`

Implementation steps:

- Build a reusable Playwright state-transition oracle for each turn:
  - visible header status;
  - session-sidebar status;
  - latest snapshot status;
  - `pending_approval.approval_id`;
  - `response_document.state`;
  - `response_document.revision`;
  - visible approval/result/diagnostic blocks.
- For RD-001 and RD-002, assert each transition:
  - after send: planning/executing or waiting approval, not orphan idle;
  - approval 1 visible;
  - after approve 1: approval 1 disappears or becomes completed evidence;
  - approval 2 visible when expected;
  - after approve 2: no approval card remains;
  - final aggregate result visible.
- Include forbidden visible text at every checkpoint:
  - `non_terminal_snapshot`;
  - `Session status: IDLE`;
  - stale `Waiting for approval 1` after approval 1 is decided;
  - stale `Approval required` after final completion;
  - raw JSON/stack trace/secret-like diagnostics.
- Store a compact JSON artifact per failed transition with only high-signal fields.

Acceptance criteria:

- A real browser flow fails if backend data changes but the visible UI remains pending.
- Tests identify the exact transition that failed instead of only timing out at the final assertion.
- Header, sidebar, snapshot, response document, and visible DOM are compared in the same assertion helper.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e:response-document -- --grep "state transition|RD-001|RD-002"
npm run test:e2e:real-langgraph -- --grep "state transition|RD-001|SO-041|@critical"
```

### Phase 12: Semantic Snapshot Probe And Artifact Quality

Goal: Replace huge low-signal Playwright/a11y snapshots as the primary debugging artifact with compact semantic probes.

Problem this phase targets:

- Full browser snapshots are long because they contain the whole accessibility tree and repeated chat/session content.
- They are also low-signal for this bug class because they do not directly compare visible UI state with backend snapshot state.

Files likely touched:

- `eMas Front/e2e/support/responseDocumentProbe.js`
- `eMas Front/e2e/support/factoryAgentAssertions.js`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/playwright.config.*`
- docs for QA artifacts

Implementation steps:

- Add a semantic probe helper that collects:
  - active session id/name/status from UI;
  - sidebar status for the active session;
  - latest visible user prompt;
  - latest assistant card title/message/block types;
  - visible approval ids/buttons;
  - visible run-step titles/states;
  - backend snapshot status, pending approval id, response-document state/revision/block types.
- Save this compact probe as JSON on failure.
- Keep screenshots/traces for visual debugging, but make the semantic probe the first artifact future agents read.
- Add assertions that fail with the semantic probe summary, not with a vague timeout.
- Add a size/readability budget for artifacts: one compact current-turn probe should be enough to identify state disagreement.

Acceptance criteria:

- A failing chatbot E2E test produces a readable current-turn probe under 200 lines.
- The probe clearly shows whether the fault is backend state, response-document composition, reducer ordering, or renderer/display.
- Full Playwright snapshots are supporting evidence only, not the main oracle.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e:response-document -- --grep "probe|artifact|state transition"
```

### Phase 13: Manual Screenshot Regression Intake

Goal: Turn every manual screenshot failure into an executable regression before adding more scenario volume.

Problem this phase targets:

- Manual testing still finds UI states that automated tests did not encode.
- Adding more scenario prompts is low value unless every discovered failure becomes a precise invariant.

Files likely touched:

- `docs/qa/manual_prompt_regression_bank.md`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `factory-agent/tests/test_response_document_contract.py`

Implementation steps:

- Add a regression intake template with:
  - screenshot symptom;
  - user prompt;
  - observed bad state;
  - expected backend state;
  - expected response document state, revision behavior, block types, and current step;
  - expected visible DOM;
  - forbidden visible text;
  - minimal backend fixture or real-flow reproducer;
  - exact test layer to add first;
  - owner, status, and verification command.
- Add this `Chat 514 / non_terminal_snapshot / IDLE` failure as the first response-document UX manual regression.
- Require a failing test before a product fix whenever the failure can be reproduced or seeded.
- Track whether the test is backend contract, frontend reducer/component, mocked Playwright, seeded Playwright, or real LangGraph.
- Link existing semantic-probe and transition-oracle coverage from each screenshot regression entry when visible DOM can diverge from backend state.

Acceptance criteria:

- Manual screenshot issues cannot remain as chat-only knowledge.
- Each accepted screenshot bug has a regression id and an executable test.
- Scenario volume increases only after root-cause invariants are covered.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_phase18_manual_prompt_bank.py -q
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "manual regression|non_terminal|RD-001|Chat 514|state transition"
```

### Phase 14: Final Response Business Contract

Goal: Make completed mutation response documents clean, compact, business-level, and deterministic before the frontend renders them.

Problem this phase targets:

- A completed multi-step mutation can render a raw assistant marker such as `done_all`.
- The final card can mix raw assistant markdown, run activity, individual completed steps, duplicated affected rows, and internal ids.
- Aggregates can be based on backend execution artifacts, for example `Updated 63 jobs across 22 approved steps`, instead of the user's business request.
- The visible result can include low-level fields such as `Operation ID`, `Step ID`, `Row ID`, or duplicate rows that are not meaningful to the operator.

Files likely touched:

- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/schemas.py`
- `factory-agent/tests/test_response_document_contract.py`
- `factory-agent/tests/test_response_document_failures.py`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Add or strengthen backend response-document contract tests for RD-001 final completion.
- Reproduce the bad final response shape as a failing backend contract before the fix when possible.
- Compose completed mutation results from typed DB/audit/tool facts, not raw assistant final markdown.
- Add a business-level mutation result shape with:
  - one short final summary;
  - grouped business changes;
  - compact affected-record preview with at most 5 records;
  - expandable clean audit grouped by business change;
  - no internal ids in normal display blocks.
- Deduplicate affected records by business identity and change group.
- Aggregate by approved business write set, not individual operation, execution step, or audit row.
- For RD-001, enforce:
  - total affected jobs = 21;
  - approved business changes = 2;
  - `Medium -> High` group has 10 jobs;
  - `Original High -> Low` group has 11 jobs;
  - no `done_all`;
  - no `Updated 63 jobs across 22 approved steps`;
  - no `Operation ID`, `Step ID`, or `Row ID` in visible response-document blocks.
- Preserve technical identifiers only in backend logs, test probe artifacts, or non-rendered diagnostics if already present for support.

Acceptance criteria:

- Backend response-document contract tests fail before the fix for the noisy RD-001 final result and pass after the fix.
- Completed mutation response documents expose a clean business result without raw assistant mutation prose.
- The response document has one final mutation result, not one visible block per backend operation.
- Full audit detail is clean and grouped by business change.
- Existing partial failure, rejected, expired, cancelled, read-only, RAG, and diagnostic response documents still pass.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
python -m pytest tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation -q
```

### Phase 15: Final Response Visual Quality Oracle

Goal: Prove in the browser that the final response is readable, compact, grouped by business change, and free of raw/internal noise.

Problem this phase targets:

- Backend truth can be correct while the rendered chat is still too long, duplicated, or visually misleading.
- Existing E2E tests can pass by checking backend state or final status while ignoring response readability.
- Full screenshots are useful for humans but are not strict enough to block duplicated tables, raw markers, or internal ids.

Files likely touched:

- `eMas Front/e2e/support/responseDocumentProbe.js`
- `eMas Front/e2e/support/factoryAgentTransitionOracle.js`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer.jsx`
- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer` tests if present
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Extend the semantic probe to capture final response visual quality:
  - final result card count;
  - business change group count and labels;
  - affected-record preview count;
  - expandable audit presence;
  - forbidden text hits;
  - duplicate affected-record rows within the same rendered section.
- Add a browser semantic oracle for RD-001 final completion.
- Assert the default visible final response is readable without expanding details.
- Assert the expanded audit is grouped by business change, not backend operation id or step id.
- Forbid:
  - `done_all`;
  - `Updated 63 jobs across 22 approved steps`;
  - `Operation ID`;
  - `Step ID`;
  - `Row ID`;
  - duplicate noisy completed-step blocks;
  - raw assistant mutation markdown as the primary result.
- Keep screenshots/traces as supporting artifacts; the semantic probe should explain failures first.

Acceptance criteria:

- RD-001 browser flow passes only when the visible final response is compact and grouped correctly.
- The browser oracle fails if internal ids or raw assistant markers appear in the rendered final response.
- The oracle fails if the default view shows a huge audit dump instead of a compact preview.
- The oracle fails if the final response aggregates backend operation rows instead of business write sets.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e:response-document -- --grep "final response quality|RD-001|business result|visual quality"
npm run test:e2e:real-langgraph -- --grep "RD-001|SO-041|final response quality|@critical"
```

### Phase 16: Approval Copy And Pending Guidance Cleanup

Goal: Remove always-visible pending-approval helper copy from the normal approval card while preserving useful guidance only when the user actually needs it.

Problem this phase targets:

- The approval view can show system-behavior copy that distracts from the approval decision:
  `Follow-up messages can revise the plan, but the current approval remains pending until you approve, reject, or cancel it.`
- Normal approval UI should focus on the proposed change, affected records, and approve/reject actions.
- Guidance about follow-up messages is useful only when a user sends or attempts a conflicting follow-up while an approval is pending.

Files likely touched:

- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/e2e/support/responseDocumentProbe.js`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Remove the always-visible pending-approval helper copy from normal approval rendering.
- Keep normal approval cards focused on:
  - what will change;
  - affected-record preview/details;
  - approve/reject actions.
- Add or update frontend component tests proving the helper copy is absent in the normal approval state.
- Add or update browser/semantic-probe assertions forbidding the helper copy during RD-001 approval 1 and approval 2.
- Preserve conditional guidance for cases where the user actually sends a follow-up or tries to start a conflicting new edit while approval is still pending.
- If conditional guidance is already implemented, assert it remains available in that specific path; otherwise document it as the next targeted behavior before building broader follow-up conflict UX.

Acceptance criteria:

- Normal approval cards do not show the follow-up helper sentence.
- Approval buttons and affected-record context remain visible and usable.
- Browser tests fail if the helper sentence returns to normal approval display.
- Any follow-up conflict guidance is conditional, not always visible.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e:response-document -- --grep "approval copy|RD-001|Waiting for approval|pending guidance"
```

### Phase 17: Entity-Agnostic No-Op Mutation Result Contract

Goal: Make no-data edit steps explicit, safe, and visible instead of silently skipping them.

Problem this phase targets:

- A mutation step that finds no matching records can be silently skipped.
- Users need to know that no edit was attempted for a requested step when no data matches.
- Approval should never be requested for a no-op group, but independent valid mutation groups may still proceed.
- This must not become another job-priority-only fix. The contract should work for any entity-specific mutation group where the selector matches zero records.

Files likely touched:

- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/schemas.py`
- `factory-agent/tests/test_response_document_contract.py`
- `factory-agent/tests/test_api_endpoints.py`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/e2e/support/responseDocumentProbe.js`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Represent no-op mutation groups with typed business fields such as `entity_type`, `selector_summary`, `change_summary`, `matched_count`, `changed_count`, `status=not_changed`, and `reason=no_matching_records`.
- Add backend contract tests for partial no-op plus valid edit:
  - no-op step appears before approval in run activity/message;
  - approval card includes only actual proposed mutations;
  - final response includes both `Changed` and `Not changed` groups;
  - no mutation/audit rows are created for the no-op group.
- Add backend contract tests for all-no-op mutation:
  - terminal completed no-op response;
  - no approval card;
  - no mutation audit rows;
  - response says `No changes were made`, not fake success.
- Use `Not changed` wording for no-op mutation groups.
- Treat `no matching records` as a valid business outcome, not a system failure, unless the specific requested record should exist and a domain rule says otherwise.
- Continue independent valid mutation groups when safe; stop only dependent steps that require the no-op output.
- Add browser/semantic-probe assertions for at least one no-op mutation flow.
- Include at least one non-job-priority no-op contract if existing fixtures support it. If the current fixture set does not support a safe non-job mutation, document that as a Phase 20 audit finding instead of hardcoding the contract to jobs.

Acceptance criteria:

- No matching records never disappears silently.
- No approval is requested for a no-op group.
- Partial no-op plus valid edit shows the no-op before approval and in the final response.
- All-no-op edit completes with `No changes were made`.
- Tests prove no data mutation was attempted for no-op groups.
- The backend response-document contract is entity-agnostic and does not depend on job priority wording.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q
python -m pytest tests/test_api_endpoints.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "no-op|Not changed|No changes were made|no matching"
```

### Phase 18: Read-Only Status Response Contract

Goal: Make read-only status answers clean, typed, and operator-friendly instead of rendering raw assistant markdown or dump-style API fields.

Problem this phase targets:

- A machine-status prompt such as `Show status for machine with machine id M-CNC-01` can render raw assistant output:
  - `done_all`;
  - raw `**Success**` markdown;
  - duplicated answer text;
  - dump-style field names such as `Machineid`, `Machinename`, `Capacityperhour`, `Defaultsetuptime`;
  - irrelevant zero/default metrics;
  - a weak generic `Results` block that only says `running`.
- Phase 14/15 fixed final mutation output, but read-only/status answers need the same deterministic response-document standard.

Files likely touched:

- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/schemas.py`
- `factory-agent/tests/test_response_document_contract.py`
- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
- `eMas Front/e2e/support/responseDocumentProbe.js`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Add backend contract tests for machine-status read-only response documents.
- Compose read-only status answers from typed tool facts, not raw assistant markdown.
- Add or reuse a typed status/result block shape for machine status:
  - one short status summary;
  - key facts with human labels;
  - optional compact detail section for secondary machine metadata;
  - no mutation/approval language;
  - no raw assistant markers.
- Define operator-friendly field labels:
  - `Machine ID`;
  - `Machine name`;
  - `Machine type`;
  - `Location`;
  - `Status`;
  - `Capacity per hour`;
  - `Last maintenance`;
  - `Maintenance interval`.
- Suppress or move low-value default/zero fields out of the default visible answer unless the user asks for full technical details.
- Remove duplicate answer rendering between the short answer, result table, and activity.
- Add frontend/browser semantic assertions for:
  - no `done_all`;
  - no raw `**Success**`;
  - no dump-style labels such as `Machineid` or `Capacityperhour`;
  - exactly one readable machine-status answer;
  - no approval card or mutation result block;
  - status value `running` is visible in a meaningful sentence or status field.

Acceptance criteria:

- `Show status for machine with machine id M-CNC-01` renders one clean read-only answer.
- The user sees a readable summary before expanding details.
- Raw assistant markdown and backend field dump labels do not appear.
- Read-only status response does not render as mutation, approval, or generic result noise.
- Existing RAG/source, no-result, mutation, diagnostic, and no-op response documents still pass.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "machine status|read-only status|M-CNC-01|status response"
```

### Phase 19: RAG Question-Type Routing Contract

Goal: Separate document-content RAG questions from entity-specific procedure-selection questions so procedure/policy questions do not wrongly require a machine ID.

Problem this phase targets:

- The prompt `According to the LOTO procedure, what notification is required before starting lockout` is a document-content question, but current routing can treat it as a machine-specific LOTO procedure selection and ask for `machine_id`.
- Existing tests cover specific machine LOTO prompts and OSHA policy prompts, but miss the middle category: asking about what a procedure says without asking which machine procedure applies.
- The fix should not be a LOTO-only phrase patch. It should introduce a reusable question-type distinction that also applies to SOP, safety policy, quality procedure, job instruction, maintenance instruction, and other document-backed topics.

Files likely touched:

- `factory-agent/factory_agent/planning/intent.py`
- `factory-agent/factory_agent/planning/tool_selector.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/rag/knowledge_policy.py`
- `factory-agent/tests/test_intent_splitter.py`
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`
- `factory-agent/tests/test_route_to_execution_contract.py`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Add a semantic question-type signal, for example `rag_question_type`, before missing-entity clarification is applied.
- Distinguish at least these categories:
  - `document_content_question`: asks what a procedure/policy/document says.
  - `machine_specific_procedure_selection`: asks which procedure applies to a specific or implied machine.
  - `safety_policy_question`: asks policy/regulatory guidance.
  - `live_operational_status`: asks live status/condition/health of an entity.
- Require `machine_id` only for question types that need a specific machine procedure or live machine status.
- Do not require `machine_id` for document-content questions that can be answered from RAG without knowing the exact asset.
- Add a routing matrix for these prompts:
  - `According to the LOTO procedure, what notification is required before starting lockout`
  - `What does the LOTO procedure say about notifying affected employees?`
  - `Before lockout, who needs to be notified according to LOTO?`
  - `What are the notification requirements before lockout/tagout?`
  - `According to OSHA LOTO guidance, what notification is required before lockout?`
- Expected behavior for that matrix:
  - route to RAG/procedure or safety-policy answer;
  - `missing_required_entities` is empty;
  - no machine-ID clarification is generated;
  - response document does not render `No results` or `completed_answer` technical diagnostic.
- Preserve adjacent behavior:
  - `What LOTO procedure applies before working on M-CNC-01?` still routes to machine-specific LOTO/RAG.
  - `What LOTO procedure applies before working on the CNC machine?` still asks for the exact machine ID when it truly needs procedure selection.
  - `What is the status of M-CNC-01?` still routes to live machine-status tooling, not RAG.

Acceptance criteria:

- The notification LOTO prompt routes to RAG/procedure content and does not ask for machine ID.
- Document-content questions and entity-specific procedure-selection questions have separate route contracts.
- The route contract is reusable beyond LOTO and is not implemented as a single prompt string special case.
- Existing machine-specific LOTO, machine-status, job read, job mutation, approval, and cancel routing tests still pass.
- Browser or semantic-probe evidence confirms the user-facing answer is a clean response document, not a generic clarification/no-result diagnostic.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py tests/test_route_to_execution_contract.py -q
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "LOTO|document content|machine ID|notification"
```

### Phase 20: Entity-Specific Overfitting Audit

Goal: Find job-specific, machine-specific, or other entity-specific implementation and test patterns that should be generalized before Phase 21.

Problem this phase targets:

- Several recent fixes started from specific examples: LOTO/machine routing, job-priority no-op mutations, machine-status formatting, and exact cascade wording.
- Those fixes are valuable only if they become general contracts instead of a growing list of defensive special cases.
- Before Phase 21, the team needs an audit of where product code, tests, and planning docs still overfit to one entity type or exact prompt family.

Files likely inspected:

- `factory-agent/factory_agent`
- `factory-agent/tests`
- `eMas Front/src`
- `eMas Front/e2e`
- `tests/e2e/scenarios`
- `docs/qa`

Implementation steps:

- Search for entity-specific logic and wording around jobs, machines, products, materials, inventory, work orders, approvals, LOTO, priority, status, and seeded IDs.
- Classify every finding as one of:
  - `acceptable_fixture`
  - `test_fixture`
  - `product-risk`
  - `planning-risk`
  - `missing-general-contract`
  - `defer`
- For each `product-risk` or `missing-general-contract`, document:
  - file/path;
  - specific overfitted pattern;
  - why it can break future prompts;
  - recommended abstraction or contract;
  - suggested Phase 21 scope.
- Do not change broad product behavior in Phase 20. It is an audit and planning phase unless a tiny safety issue is exposed and explicitly accepted as part of the audit.
- Update the tracker with a prioritized Phase 21 recommendation after the audit.

Acceptance criteria:

- Tracker includes an overfitting inventory table with file/path, entity-specific pattern, risk level, recommended abstraction, and disposition.
- The audit covers backend routing/planning, backend response-document composition, frontend rendering, Playwright probes, seeded fixtures, scenario oracles, and QA docs.
- Phase 21 is not started until the audit returns a prioritized recommendation.
- No product behavior changes are made in Phase 20 unless called out as an explicit exception.

Verification command:

```powershell
git status --short --branch
git diff --check
```

### Phase 21: Backend Capability Metadata Readiness

Goal: Enhance backend/OpenAPI/tool metadata so the generic entity response work has reliable backend semantics before implementation starts.

Problem this phase targets:

- Phase 20 found that the response-document layer is ready to become more generic, but backend route/tool metadata is still not rich enough to support that cleanly.
- Starting generic response-document composition before backend readiness would force more inference from endpoint names, job/machine labels, summary prose, or frontend fixtures.
- OpenAPI, generated `tools.md`, generated tool vocabulary, and RAG API reference mirrors must move together or the planner, tool selector, RAG docs, and tests will drift.

Files likely touched:

- `emas/docs/swagger.json`
- `emas/docs/swagger.yaml`
- `rag_sources/01_emas_internal_docs/api_reference/openapi.json`
- `factory-agent/factory_agent/tools.md`
- `rag_sources/01_emas_internal_docs/api_reference/tools.md`
- `factory-agent/factory_agent/generated/tool_intent_vocabulary.json`
- `factory-agent/factory_agent/registry/toolgen.py`
- `factory-agent/factory_agent/planning/tool_intent_profile.py`
- `factory-agent/factory_agent/planning/tool_selector.py`
- `factory-agent/tests/test_toolgen.py`
- `factory-agent/tests/test_tool_intent_profile.py`
- `factory-agent/tests/test_tool_selector.py`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Inspect the current OpenAPI and generated tool metadata for entity/action/capability gaps.
- Update the backend/OpenAPI source of truth where needed so supported routes expose enough metadata for:
  - entity type;
  - stable entity id fields;
  - display id fields;
  - read/status capability;
  - mutation capability;
  - approval requirement;
  - no-op/no-match outcomes;
  - business-change field metadata.
- Regenerate and keep in sync:
  - `emas/docs/swagger.json`;
  - `emas/docs/swagger.yaml`;
  - `rag_sources/01_emas_internal_docs/api_reference/openapi.json`;
  - `factory-agent/factory_agent/tools.md`;
  - `rag_sources/01_emas_internal_docs/api_reference/tools.md`;
  - `factory-agent/factory_agent/generated/tool_intent_vocabulary.json`.
- Add or update tests proving generated tools and generated vocabulary include generic entity/capability metadata beyond machine/job when the backend surface supports it.
- Add metadata-readiness tests for the future contracts:
  - `entity_status_v1`;
  - `business_change_v1`;
  - `entity_agnostic_no_matching_records_v1`.
- Do not hand-edit generated `tools.md` or generated vocabulary output. Update the generator or source metadata, then regenerate.

Acceptance criteria:

- Backend metadata can identify supported entity status reads generically, not only machine status.
- Backend metadata can represent business-change/no-op semantics needed by generic mutation result composition.
- OpenAPI, RAG OpenAPI mirror, Factory Agent tools reference, RAG tools reference, and generated vocabulary are synchronized.
- Tool generation and vocabulary tests pass.
- Phase 22 is unblocked only when the tracker records the ready evidence.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_toolgen.py tests/test_tool_intent_profile.py tests/test_tool_selector.py -q
python scripts/generate_tools.py --local --no-db
python scripts/generate_tool_intent_vocabulary.py

Set-Location ".."
git diff --check
git status --short --branch
```

### Phase 22: Generic Entity Status And Mutation Business Contract

Goal: Create the generic response-document contracts the audit asked for before migrating existing flows.

Problem this phase targets:

- Phase 20 found that the system needs real generic contracts, not another machine/job-specific implementation.
- Phase 21 prepares backend metadata, but it does not itself define the response-document block contracts and contract tests.
- Existing machine status must become one example of entity status, not the model itself.

Prerequisite:

- Phase 21 must be marked Done with OpenAPI, generated tools, generated vocabulary, and `tools.md` synchronized.

Files likely touched:

- `factory-agent/factory_agent/schemas.py`
- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/tests/test_response_document_contract.py`
- `factory-agent/tests/test_response_document_failures.py`
- `eMas Front/src/components/features/chat/factory-agent/responseDocumentContract.js`
- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer.jsx`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Add `entity_status_v1` for read-only single-entity status answers.
- Add `business_change_v1` for mutation result groups.
- Add one safe non-job no-op contract proof, even if synthetic at the backend contract layer.
- Add a guard proving machine status is one example of `entity_status_v1`, not the schema/model itself.
- Touch backend contracts first; add focused frontend rendering only if the current renderer cannot display the new typed contract correctly.
- Keep broad migration of existing RD-001/RD-008 outputs out of this phase; that is Phase 23.

Acceptance criteria:

- `entity_status_v1` exists and is tested independently from machine-only behavior.
- `business_change_v1` exists and can represent mutation groups without job/priority prose.
- At least one safe non-job no-op contract proof exists.
- A test fails if machine status becomes the only accepted entity-status shape.
- Frontend changes are focused and contract-driven only where needed.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
```

### Phase 23: Migrate Existing Machine/Job Outputs Onto Generic Contracts

Goal: Move existing machine status and job priority mutation output onto the generic contracts created in Phase 22.

Problem this phase targets:

- Phase 18 made machine status clean, but it still needs to render through a generic `entity_status_v1` contract instead of a machine-first display path.
- Phase 14/15 made RD-001 job priority mutation output clean, but the composer must stop using job/priority prose as the source of business grouping when typed change fields exist.
- Phase 17 made no-op mutation output entity-agnostic at the wording/contract level, but existing job no-op behavior must remain stable while the generic contract becomes the production path.

Prerequisite:

- Phase 22 must be marked Done with `entity_status_v1`, `business_change_v1`, and safe non-job no-op contract proof in place.

Files likely touched:

- `factory-agent/factory_agent/services/response_document_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/schemas.py`
- `factory-agent/tests/test_response_document_contract.py`
- `eMas Front/src/components/features/chat/factory-agent/ResponseDocumentRenderer.jsx`
- `eMas Front/src/components/features/chat/factory-agent/responseDocumentContract.js`
- `eMas Front/e2e/support/responseDocumentProbe.js`
- `eMas Front/e2e/support/responseDocumentScenarios.js`
- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `docs/qa/RESPONSE_DOCUMENT_UX_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Add or finalize `entity_status_v1` response-document support and migrate the current machine-status answer onto it.
- Add or finalize typed `business_change_v1` support and migrate the current job priority cascade onto it.
- Keep existing no-op mutation behavior working through the generic no-match/no-op contract.
- Make completed mutation composition prefer typed business-change fields over assistant summary text, job id shape, priority prose, or RD-001 phrase matching.
- Make frontend rendering and probes assert contract type/evidence, not `M-CNC-01`, `JOB-SEED`, `Medium -> High`, or exact entity labels as the reason the UI passes.
- Preserve RD-001, RD-002, RD-006, RD-007, RD-008, and RD-009 behavior.

Acceptance criteria:

- Machine status still works.
- Job priority cascade still works.
- Job no-op mutation still works.
- Final response does not parse job/priority prose to infer business groups when typed fields exist.
- Frontend renders by contract type, not entity name.
- Existing flagship flows still pass.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py tests/test_toolgen.py tests/test_tool_intent_profile.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "entity_status_v1|business_change_v1|machine status|RD-001|no-op"
```

### Phase 24: Add Entity Diversity Coverage

Goal: Prove the generic contracts work beyond jobs and machines.

Problem this phase targets:

- A contract is not truly generic if the only visible proofs are `JOB-SEED-*` and `M-CNC-01`.
- Phase 23 intentionally migrates existing outputs first; Phase 24 adds deterministic non-job/non-machine coverage so future entities do not need one-off rendering branches.

Prerequisite:

- Phase 23 must be marked Done.

Implementation steps:

- Add safe deterministic coverage for at least two of:
  - product status/read result;
  - material/inventory read result;
  - work order status;
  - non-job no-op mutation;
  - non-job partial/no-op plus valid group.
- Prefer real backend-supported read/status paths when available.
- If a non-job write path is not safely supported, use contract-level backend fixtures without enabling broad new write behavior.
- Ensure the response document carries entity type, entity id/display id, primary status or change metadata, row outcome, and no-op counts through typed fields.
- Add frontend/probe coverage only where visible DOM can diverge from backend contract evidence.

Acceptance criteria:

- At least two non-job/non-machine deterministic examples pass.
- The new examples render through `entity_status_v1`, `business_change_v1`, or no-op/no-match typed contracts.
- The tests fail if the implementation only understands job priority or machine status.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "product status|material|inventory|work order|non-job|entity diversity"
```

### Phase 25: Hardcode Regression Guardrails

Goal: Prevent the generic contract work from sliding back into fixture-specific or entity-specific implementations.

Problem this phase targets:

- Previous phases repeatedly found fixes that worked for one prompt, one fixture id, or one entity label.
- Guardrails should catch product-code branches on `M-CNC-01`, `JOB-SEED`, exact prompt text, or specific entity labels outside fixtures.
- Composer and frontend tests must prove contract evidence, not only machine/job visible text.

Prerequisite:

- Phase 24 must be marked Done.

Implementation steps:

- Add product-code guardrails that fail when non-fixture code branches on seeded ids, exact prompt text, or specific entity labels without a registry/metadata contract.
- Add response-document composer guardrails that fail when business facts are derived from summary prose while typed fields are available.
- Add frontend/probe guardrails that fail when generic checks only inspect machine/job text instead of contract type, block type, entity type, and typed field evidence.
- Allow exact ids and labels inside deterministic fixtures, manual regression banks, seeded scenario definitions, and explicitly named compatibility tests.
- Document any accepted exception with owner, reason, and expiry/revisit condition.

Acceptance criteria:

- Guardrails fail on newly introduced hardcoded product branches.
- Guardrails distinguish product-code risk from fixture constants.
- Business-change composition cannot regress to summary-prose parsing when typed fields exist.
- Frontend generic proofs require contract evidence.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py tests/test_toolgen.py tests/test_tool_intent_profile.py -q
python -m pytest tests/test_hardcode_guardrails.py -q

Set-Location "..\eMas Front"
npm test
node --test --test-concurrency=1 e2e/support/responseDocumentProbe.test.mjs
```

### Phase 26: Real Flow Release Proof

Goal: Run the real pipeline after the generic contract refactor and prove the release-critical flows still work end to end.

Problem this phase targets:

- Mocked and contract tests can prove shape, but the release gate must prove planner, routing, tool selection, approval sequencing, snapshots, response documents, and visible UI agree in real or seeded flows.
- Phase 26 is the release-confidence pass after the backend metadata, contract, migration, diversity, and guardrail phases.

Prerequisite:

- Phase 25 must be marked Done.

Implementation steps:

- Run RD-001 cascade real/seeded proof.
- Run machine status real/seeded proof.
- Run LOTO document-content RAG proof.
- Run no-op mutation proof.
- Run at least one non-job generic proof if the backend surface supports it.
- Run the final response visual-quality oracle.
- Capture compact semantic probes for browser failures; screenshots/traces remain supporting evidence.

Acceptance criteria:

- Real/seeded RD-001 completes with 21 jobs across 2 approved business changes and no raw/internal noise.
- Machine status completes as one typed status answer.
- LOTO document-content question reaches RAG/procedure content without machine-ID clarification.
- No-op mutation completes without approval or fake success.
- At least one non-job generic proof passes, or the tracker records why no safe real backend surface exists yet and points to Phase 24 contract coverage.
- Final response visual-quality oracle passes.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py tests/test_route_to_execution_contract.py tests/test_intent_splitter.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "RD-001|machine status|LOTO|no-op|entity status|business change|visual quality"
npm run test:e2e:seeded-oracles -- --grep "RD-001|machine status|LOTO|no-op|entity status|business change"
npm run test:e2e:real-langgraph -- --grep "RD-001|SO-041|machine status|LOTO|no-op|@critical"
```

### Phase 27: RAG Metadata Readiness And Legacy Renderer Cleanup

Goal: Prepare RAG answers for typed source UX by fixing the data contract and removing legacy markdown/display paths that currently leak raw safety directives or duplicate the answer.

Problem this phase targets:

- Current RAG source metadata is document-level only. It can support basic source labels, but not claim-level source chips, source drawers, PDF page jumps, or highlights.
- PDF ingestion currently concatenates page text, so page boundaries and highlight coordinates are not reliable.
- RAG generation can inject raw `:::safety` admonition markdown into the answer text.
- Response-document rendering can show the same RAG body as both the document message and a `knowledge_answer` block.
- Legacy chat rendering still parses `[^1]` citations and renders separate source/safety chrome outside the response-document renderer.

Prerequisite:

- Phase 26 must be marked Done.

Implementation steps:

- Extend backend RAG source metadata to a minimum reliable locator shape:
  - required: `source_id`, `source_number`, `doc_id`, `chunk_id`, `title`, `organization`, `snippet`;
  - optional/pass-through: `page`, `pdf_url`, `bbox`, `char_range`.
- Do not expose raw local filesystem `file_path` in normal UI payloads. Map documents to safe `pdf_url` or keep them as source drawer metadata until a document-serving route exists.
- Stop injecting `SAFETY_WARNING_BLOCK` / `:::safety` into generated answer text. Preserve safety information as structured `safety_content` or future `safety_notice_v1` data.
- Add sanitizer/normalizer coverage that strips or rejects raw `:::safety` if it comes from legacy RAG output.
- Update response-document composition so a source-backed answer body is visible exactly once. Use a short message only as chrome/summary; the substantive answer belongs to the knowledge block.
- Isolate legacy `[^1]` parsing/source-list/safety rendering to compatibility paths where `response_document` is absent.
- Keep the existing `source_list` bibliography behavior working while adding richer locator fields.
- Document the accepted limitation that exact PDF highlight is not complete until Phase 29.

Acceptance criteria:

- LOTO notification RAG output has no visible `:::safety`.
- The RAG answer body is not duplicated between `message`, `knowledge_answer`, and legacy chat chrome.
- Every cited RAG source has at least `source_id`, `doc_id`, `chunk_id`, `title`, `organization`, and `snippet`.
- Existing fallback/policy sources either supply the minimum locator fields or are marked as policy-only sources with deterministic snippets.
- Legacy `ChatMessage` citation/source/safety chrome does not render on top of a valid `response_document`.
- Existing Phase 21-26 tests still pass.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_rag_generation.py tests/test_rag_knowledge_policy.py tests/test_response_document_contract.py tests/test_response_document_failures.py -q

Set-Location "..\eMas Front"
npm test
node --test --test-concurrency=1 src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs
npm run test:e2e:response-document -- --grep "LOTO|RAG|source|safety|duplicate"
```

### Phase 28: Typed RAG Answer And Source Citation UX

Goal: Render RAG/procedure answers as typed response-document UI with clean safety notices, inline source chips, compact source hover, source drawer click behavior, and separate sections when operation data and RAG guidance appear together.

Problem this phase targets:

- A source list at the bottom is not enough evidence for sentence-level RAG answers.
- Users need to see which source supports which claim without reading raw markdown citations.
- RAG guidance and live operation facts must be visually distinct when a response contains both.

Prerequisite:

- Phase 27 must be marked Done.

Implementation steps:

- Add or finalize typed RAG response-document blocks/contracts:
  - `safety_notice_v1`;
  - `knowledge_answer_v1`;
  - inline `source_citation_v1` or equivalent citation refs inside `knowledge_answer_v1`;
  - `source_locator_v1` / enriched `source_list_v1`.
- Render safety content as a dedicated non-dismissible safety notice block, not markdown.
- Render the knowledge answer once, with inline source chips after supported claims/sentences.
- Render compact hover content for source chips: title, organization, page/chunk when available, and snippet.
- On source chip click, open an in-app source drawer with the exact cited snippet and metadata.
- If `pdf_url` and `page` exist, provide/open the PDF at that page; otherwise keep the drawer as the source-of-truth view.
- Keep `Knowledge sources` as bibliography/details, but do not make it the only citation mechanism.
- For mixed operation + RAG answers, render operation result and procedure/knowledge guidance as separate sections.
- Add frontend semantic probe coverage that asserts typed RAG blocks and source evidence, not exact answer prose only.

Acceptance criteria:

- LOTO document-content answer renders with a safety panel, one answer body, inline source chips, hover metadata, a source drawer, and bibliography/details.
- Raw `:::safety`, raw footnote definitions, and unconverted `[^1]` markers do not appear in visible response-document UI.
- Source chip click works even without PDF page/highlight metadata by opening the source drawer.
- Mixed operation + RAG response uses separate sections and does not blend live status facts with policy/procedure claims.
- Browser tests prove visible source chips and semantic source metadata.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_response_document_contract.py tests/test_response_document_failures.py tests/test_rag_generation.py tests/test_rag_knowledge_policy.py -q

Set-Location "..\eMas Front"
npm test
node --test --test-concurrency=1 e2e/support/responseDocumentProbe.test.mjs
npm run test:e2e:response-document -- --grep "LOTO|typed RAG|source chip|safety notice|source drawer|mixed operation"
```

### Phase 29: PDF Source Locator And Highlight Upgrade

Goal: Upgrade document ingestion and source opening so cited chunks can open the original PDF at the right page and highlight or locate the cited chunk when metadata is available.

Problem this phase targets:

- Phase 28 can show source drawers and page links only when metadata exists.
- Current PDF ingestion does not preserve page boundaries or highlight coordinates.
- Exact PDF highlighting should be implemented after the typed source contract is stable, not as a blocker for RAG display cleanup.

Prerequisite:

- Phase 28 must be marked Done.

Implementation steps:

- Make PDF ingestion page-aware so chunks preserve `page` and safe document locator metadata.
- Add or map a safe `pdf_url` / document open route for source documents instead of exposing raw local paths.
- Preserve enough chunk text to support search/snippet highlight fallback.
- Add optional exact highlight metadata when feasible:
  - `bbox` for rendered PDF coordinates;
  - or `char_range` / text range for text-layer highlighting.
- Add migration/reingestion notes for existing vector/BM25 indexes.
- Update source chip click behavior:
  - exact highlight when `bbox` or `char_range` exists;
  - page jump plus text/snippet search when exact geometry is missing;
  - source drawer fallback when PDF locator is unavailable.
- Add tests that prove page metadata survives ingestion and source-opening fallback order is deterministic.

Acceptance criteria:

- At least one PDF-backed source can open at the cited page.
- Source drawer still works when PDF locator metadata is missing.
- Highlight fallback order is deterministic: exact geometry, text range/search, page-only, drawer-only.
- No normal UI payload leaks raw local file paths.
- Existing Phase 27-28 RAG display tests still pass.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_rag_ingestion.py tests/test_rag_generation.py tests/test_response_document_contract.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "source PDF|source drawer|highlight|LOTO"
```

### Phase 30: RAG Reingestion And Live Release Proof

Goal: Rebuild the local RAG stores after the PDF source-locator upgrade and prove live source payloads carry page-aware safe locator metadata.

Problem this phase targets:

- Phase 29 can add the correct ingestion behavior while old local Chroma/BM25 stores still contain stale chunks.
- Source UX proof is incomplete if browser fixtures have PDF metadata but live retrieved chunks still lack `page`, `pdf_url`, `text_search`, or `char_range`.
- Local ingestion must not leak raw filesystem `file_path` through normal source payloads.

Prerequisite:

- Phase 29 must be marked Done.

Implementation steps:

- Reingest the registered RAG sources from `rag_sources/00_metadata_templates/source_register.json`.
- Confirm local vector and BM25 indexes agree on page-aware locator metadata.
- Prove OSHA LOTO chunks carry `source_id`, `doc_id`, `chunk_id`, `title`, `organization`, `snippet`, `page`, `pdf_url`, `text_search`, and `char_range`.
- Prove normal source payloads do not expose raw local `file_path`.
- Keep source drawer fallback coverage for sources that genuinely lack PDF locators.

Acceptance criteria:

- Local RAG indexes are rebuilt or verified as current.
- Live LOTO source payloads include safe page/highlight locator metadata.
- Existing typed RAG/source browser gates remain green.
- Reingestion steps and accepted limitations are recorded in the tracker.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_rag_ingestion.py tests/test_rag_generation.py tests/test_response_document_contract.py tests/test_rag_knowledge_policy.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "LOTO|source PDF|source drawer|highlight|typed RAG"
npm run test:e2e:seeded-oracles -- --grep "LOTO|source|RAG"
```

### Phase 31: Backend RAG Evidence Truth Cleanup

Goal: Remove unsafe hardcoded runtime RAG fallback behavior and make backend citation/source truth deterministic before any new source UI work.

Status: Completed 2026-05-19. Backend cleanup and focused regression coverage are in place; Phases 32, 33, 34, and 35 remain planned.

Problem this phase targets:

- `LOTO Notification Requirements` is currently a hardcoded runtime policy fallback, not a retrieved PDF-backed source.
- Policy fallback sources can reuse `source_number: 1`, which can overwrite or confuse real PDF-backed source citations.
- Backend-added answer supplements can appear without their own typed citation evidence.
- Helpful-looking fallback answers can make unsupported safety/procedure claims appear source-backed.
- Existing Phase 27-30 tests are not sufficient by themselves because they previously allowed the synthetic policy source, duplicate source numbering, and uncited backend-added fallback text.

Prerequisite:

- Phase 30 must be marked Done.

Implementation steps:

- Remove hardcoded runtime RAG policy fallback answers and synthetic sources such as `loto_notification_requirement` from real chat paths.
- If retrieved sources do not support the requested safety/procedure claim, return an insufficient-context answer instead of adding policy text from code.
- Keep retrieved sources visible for insufficient-context answers as "related sources checked" or equivalent wording, not proof of the unsupported claim.
- Ensure final RAG source numbers are unique after all source normalization and merging.
- Ensure citation mapping uses stable source identity and does not allow duplicate source numbers to redirect a chip to the wrong source.
- Ensure every important backend-owned answer claim/sentence has typed citation evidence or is clearly marked as insufficient context.
- Add RAG hardcode guardrails that fail if product/runtime code branches on exact LOTO prompt text, emits synthetic `loto_notification_requirement`, or appends answer text from policy fallback without retrieved source evidence.
- Add new focused backend regression tests; do not count Phase 31 complete only because older tests still pass.
- Add a negative unsupported-prompt test for:

```text
According to the OSHA lockout/tagout guide, what notification is required before starting lockout?
```

- Add a contract or unit test proving no synthetic `loto_notification_requirement` / `LOTO Notification Requirements` source appears in runtime RAG output.
- Add a unit test proving source normalization/merging cannot leave duplicate final `source_number` values.
- Add a response-document contract test proving uncited backend-added factual supplement text is blocked or converted to insufficient context.

Acceptance criteria:

- No real/runtime response includes synthetic `loto_notification_requirement` or a hardcoded `LOTO Notification Requirements` source.
- No backend-added RAG answer supplement can appear as an uncited fact.
- Unsupported safety/procedure prompts produce insufficient-context output instead of fallback facts.
- Final source numbers are unique and source identity is stable.
- New Phase 31 tests fail on the pre-cleanup behavior and pass after the cleanup.
- Guardrails distinguish runtime/product code from allowed tests, seeded fixtures, and docs references.
- Existing Phase 27-30 backend RAG, safety, source, and response-document contract tests remain green.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_rag_generation.py tests/test_rag_knowledge_policy.py tests/test_rag_ingestion.py tests/test_response_document_contract.py tests/test_response_document_failures.py tests/test_hardcode_guardrails.py -q

Set-Location ".."
git diff --check
git status --short --branch
```

### Phase 32: Live RAG Positive And Negative Release Proof

Goal: Prove the cleaned backend RAG behavior through real or seeded pipeline paths before frontend source UI expansion.

Status: Completed 2026-05-19. Backend contract, mocked browser, and seeded browser proof now cover the positive OSHA reenergizing answer and the negative before-starting-lockout insufficient-context answer; Phases 33, 34, and 35 remain planned.

Problem this phase targets:

- Backend contract tests can pass while live retrieval, route selection, source locators, or browser payloads still drift.
- Removing hardcoded fallback behavior must not be mistaken for a broken RAG system.
- The release proof needs one supported PDF-backed answer and one honest unsupported/insufficient-context answer.

Prerequisite:

- Phase 31 must be marked Done.

Implementation steps:

- Use a real PDF-backed positive proof prompt:

```text
According to the OSHA lockout/tagout guide, what notification is required before reenergizing a machine after removing lockout or tagout devices?
```

- Require the positive answer to cite `osha_3120_lockout_tagout` with `doc_id`, `chunk_id`, `page`, `pdf_url`, and `char_range` or `text_search`.
- Use the old unsupported prompt as the negative proof:

```text
According to the OSHA lockout/tagout guide, what notification is required before starting lockout?
```

- Require the negative answer to say insufficient context when indexed PDFs do not support the requested claim.
- Show retrieved sources for the negative answer as related sources checked, not proof of the unsupported claim.
- Prove LOTO document-content routing still does not ask for machine ID.
- Prove API/browser payloads do not leak `loto_notification_requirement` or hardcoded fallback content.

Acceptance criteria:

- Positive real/seeded proof returns source-backed OSHA PDF evidence.
- Negative real/seeded proof returns insufficient-context wording and related sources checked.
- Both proofs preserve typed `safety_notice_v1`, `knowledge_answer_v1`, and source locator contracts where applicable.
- No source chip, drawer payload, or bibliography payload disagrees on source number, source id, document id, or title.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_rag_generation.py tests/test_rag_knowledge_policy.py tests/test_response_document_contract.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:response-document -- --grep "OSHA lockout|reenergizing|insufficient context|LOTO|source|RAG"
npm run test:e2e:seeded-oracles -- --grep "LOTO|source|RAG|insufficient context"

Set-Location ".."
git diff --check
git status --short --branch
```

### Phase 33: Side Evidence Drawer And PDF Panel UX

Goal: Replace source-chip metadata-only interaction with a usable evidence workspace that can show source details and PDF evidence in one resizable side panel.

Status: Completed 2026-05-19. Source chips now open a resizable side evidence drawer with cited/related source grouping, in-panel PDF view, back navigation, page/search fallback evidence, and no-PDF drawer fallback; Phases 34 and 35 remain planned.

Problem this phase targets:

- A source chip can open a plain metadata drawer even when a cited or related source has PDF/page/highlight locator metadata.
- Users need to inspect cited evidence without losing the chat context.
- One inline source tag represents one cited claim/evidence group, so related supporting sources must be discoverable without making fake inline citations.

Prerequisite:

- Phase 32 must be marked Done.

Implementation steps:

- Replace or upgrade the source drawer into a resizable, closable side evidence drawer for source-chip clicks.
- Show the cited source first and related supporting sources second.
- When a cited or related source has `pdf_url` and page/locator metadata, open the PDF inside the same side panel.
- Add back navigation from in-panel PDF view to the evidence list.
- If exact highlight is unavailable, jump to the cited page and show snippet/search evidence instead of silently falling back to metadata-only display.
- Preserve drawer-only fallback for true no-PDF sources.
- Add component/probe/browser coverage for PDF-backed source, related supporting source, and no-PDF fallback.

Acceptance criteria:

- Clicking the positive OSHA source chip opens the side evidence drawer.
- The drawer can open the PDF in-panel at the cited page/highlight fallback.
- Back navigation returns from PDF view to evidence list.
- True no-PDF sources still show useful drawer evidence without pretending to have PDF support.
- Source chip, drawer entry, and bibliography source identity agree.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
node --test --test-concurrency=1 e2e/support/responseDocumentProbe.test.mjs
npm run test:e2e:response-document -- --grep "source drawer|side evidence|PDF|back navigation|source chip|related source"

Set-Location ".."
git diff --check
git status --short --branch
```

### Phase 34: Source Tooltip And Responsive Chat Width

Status: Completed 2026-05-19. Source hover cards are collision-aware, right-edge hover stays inside the visible chat surface, and assistant response cards expand with resized chatbot/modal width while prose keeps a readable line length. Phase 35 remains planned.

Goal: Fix the layout problems independently from RAG truth and source drawer behavior.

Problem this phase targets:

- Source hover cards can overflow outside the chat surface near the right edge.
- Assistant response cards remain too narrow when the chatbot/modal is resized wider.
- Structured response-document content needs more width than plain prose, but long text still needs readable line lengths.

Prerequisite:

- Phase 33 must be marked Done.

Implementation steps:

- Make source-chip hover cards collision-aware: prefer bottom-right, flip to bottom-left or another safe placement when needed, and keep the card inside the chat/evidence container.
- Add right-edge and small-screen hover tests.
- Make assistant response cards grow with the chatbot/modal width while preserving readable prose widths.
- Allow structured content such as source evidence, tables, approvals, and PDF panels to use wider space.
- Add resize tests proving the chat content area grows when the chatbot/modal grows.

Acceptance criteria:

- Tooltip placement stays within the visible chat/evidence surface at right-edge and small-screen positions.
- Resizing the chatbot/modal wider also widens the assistant response/card area enough to use available space.
- Long prose remains readable and does not become edge-to-edge on very wide screens.
- Structured response-document blocks can use wider layouts where useful.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e:response-document -- --grep "tooltip|responsive|resize|source chip|chat width"

Set-Location ".."
git diff --check
git status --short --branch
```

### Phase 35: Final RAG Source UX Release Gate

Status: Completed 2026-05-19. The integrated gate passed after fixing the shell-level side evidence panel ownership and backend-routed PDF URL resolution blockers.

Goal: Run the integrated release proof after backend RAG truth cleanup, live RAG proof, source evidence drawer, and responsive layout hardening.

Problem this phase targets:

- Individually green backend and frontend phases can still disagree when the real pipeline, response document, visible UI, source interactions, and layout are exercised together.
- The plan should not claim the RAG/source UX refactor is complete until the positive, negative, PDF, drawer, tooltip, and resize paths all pass together.

Prerequisite:

- Phases 31, 32, 33, and 34 must be marked Done.

Implementation steps:

- Run the positive OSHA reenergizing PDF-backed answer through the real/seeded response-document browser path.
- Run the negative before-starting-lockout insufficient-context answer through the real/seeded response-document browser path.
- Verify no hardcoded fallback source or answer text appears in runtime/API/browser payloads.
- Verify source chip to side evidence drawer to in-panel PDF to back navigation.
- Verify no-PDF fallback remains available for true no-PDF sources.
- Verify tooltip edge positioning and resized chatbot/card width in browser.
- Update tracker and manual regression bank with final release evidence.

Acceptance criteria:

- Positive PDF-backed OSHA answer passes with locator evidence and in-panel PDF/source UX.
- Negative unsupported prompt passes with insufficient context and related sources checked.
- RAG hardcode guardrails pass.
- Tooltip and responsive width gates pass.
- Existing Phase 27-34 suites remain green.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_rag_generation.py tests/test_rag_knowledge_policy.py tests/test_rag_ingestion.py tests/test_response_document_contract.py tests/test_response_document_failures.py tests/test_hardcode_guardrails.py -q

Set-Location "..\eMas Front"
npm test
node --test --test-concurrency=1 e2e/support/responseDocumentProbe.test.mjs
npm run test:e2e:response-document -- --grep "OSHA lockout|reenergizing|insufficient context|side evidence|PDF|tooltip|responsive"
npm run test:e2e:seeded-oracles -- --grep "LOTO|source|RAG|insufficient context"

Set-Location ".."
git diff --check
git status --short --branch
```

## Stop Conditions

Stop and fix before continuing when:

- A product bug is found.
- A pending approval appears as final success.
- A completed step disappears during a later pending approval.
- Final response omits any completed mutation step.
- UI renders from legacy `presentation` while `response_document` is available.
- Approval cards auto-expand again after user collapse.
- Stale read-tool summaries overwrite terminal mutation summaries.
- Lower response-document revisions downgrade a newer visible state.
- SSE and polling disagree and the frontend chooses by transport instead of revision.
- Invalid `response_document` silently falls back to old `presentation`.
- Old turn/document updates change the active turn's primary UI.
- A normal sent prompt lands in `IDLE` with no terminal result, no pending approval, and `non_terminal_snapshot`.
- Active session header/status, sidebar status, backend snapshot status, and response-document state disagree after a refresh window.
- Browser E2E has no compact semantic probe explaining a failed chatbot transition.
- Broken flow renders blank chat, raw JSON, endless spinner, or vague generic failure copy.
- Failure response hides already-applied changes or implies no work happened when partial progress exists.
- Failure card offers retry/action that is unsafe for the current operation state.
- Technical diagnostics leak raw stack traces, secrets, tokens, or environment values by default.
- Browser E2E passes only because it ignores visible UX and checks backend state only.
- Final mutation response shows raw assistant markers such as `done_all`.
- Final mutation response shows internal ids such as `Operation ID`, `Step ID`, or `Row ID`.
- Final mutation response duplicates affected rows or counts backend operations as business changes.
- RD-001 final result does not summarize 21 jobs across 2 approved business changes.
- Normal approval card shows always-visible pending guidance about follow-up messages.
- A mutation step with no matching records is silently skipped.
- Approval is requested for a no-op mutation group.
- Final response omits a `Not changed` group for a requested no-op mutation.
- Read-only status response shows raw assistant markers such as `done_all` or raw `**Success**`.
- Read-only status response exposes dump-style API labels such as `Machineid`, `Machinename`, or `Capacityperhour`.
- Read-only status response duplicates the same answer in multiple visible blocks.
- Read-only status response renders as approval or mutation UI.
- A document-content RAG question asks for a machine ID before trying retrieval.
- Routing requires an entity ID before classifying whether the question actually needs that entity.
- New no-op mutation logic is hardcoded only to jobs or priority changes.
- New status response formatting is hardcoded only to `M-CNC-01` or one machine route.
- Phase 20 finds product-risk overfitting without a tracker entry and Phase 21 recommendation.
- Phase 22 starts before Phase 21 proves backend/OpenAPI/tool/vocabulary readiness.
- Phase 23 starts before Phase 22 proves `entity_status_v1`, `business_change_v1`, and a safe non-job no-op contract proof.
- OpenAPI, RAG OpenAPI mirror, generated `tools.md`, RAG `tools.md`, or generated vocabulary are updated inconsistently.
- Generated tool metadata cannot express the entity/action/capability semantics required by the generic response-document contract.
- Phase 24 claims generic coverage with only job and machine examples.
- Phase 25 starts after new product-code branches on seeded ids, exact prompt text, or entity labels are accepted without a guardrail or explicit exception.
- Phase 26 starts before hardcode guardrails pass.
- Completed mutation composition derives business facts from assistant summary prose when typed `business_change_v1` fields are available.
- Frontend generic response-document tests pass by checking only machine/job text instead of contract type, block type, entity type, and typed field evidence.
- RAG answers show raw markdown directives such as `:::safety`.
- RAG answers duplicate the same substantive answer body in multiple visible blocks.
- A valid `response_document` renders legacy `ChatMessage` source/safety chrome on top of typed response-document blocks.
- Source chips are claimed complete without minimum locator metadata: `source_id`, `doc_id`, `chunk_id`, `title`, `organization`, and `snippet`.
- PDF highlight is treated as complete while ingestion still loses page boundaries or exposes only raw local `file_path`.
- Runtime RAG answers use hardcoded policy fallback text or synthetic sources such as `loto_notification_requirement` instead of retrieved evidence.
- Backend-added RAG answer text appears without typed citation evidence or an explicit insufficient-context state.
- Multiple final RAG sources share the same `source_number` or a source chip opens a different source than its displayed number/title implies.
- Unsupported safety/procedure prompts are answered as facts from uncited fallback content instead of returning insufficient context with related sources checked.
- Source-chip PDF UX falls back to metadata-only display when a cited or related source has a safe `pdf_url` and page/locator metadata.
- Source hover cards overflow outside the chat/evidence container.
- Assistant response cards remain artificially narrow after the chatbot/modal is resized wider.

## Out Of Scope For This Plan

- Promptfoo or broad LLM semantic evaluation.
- LLM-written final responses.
- Replacing the entire chat UI shell.
- Removing backend `presentation` from the API payload before frontend migration is complete.
- Exact PDF highlight before Phase 29 source-locator ingestion support is in place.
