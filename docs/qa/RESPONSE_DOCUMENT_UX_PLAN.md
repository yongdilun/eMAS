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
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
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
- Broken flow renders blank chat, raw JSON, endless spinner, or vague generic failure copy.
- Failure response hides already-applied changes or implies no work happened when partial progress exists.
- Failure card offers retry/action that is unsafe for the current operation state.
- Technical diagnostics leak raw stack traces, secrets, tokens, or environment values by default.
- Browser E2E passes only because it ignores visible UX and checks backend state only.

## Out Of Scope For This Plan

- Promptfoo or broad LLM semantic evaluation.
- LLM-written final responses.
- Replacing the entire chat UI shell.
- Removing backend `presentation` from the API payload before frontend migration is complete.
