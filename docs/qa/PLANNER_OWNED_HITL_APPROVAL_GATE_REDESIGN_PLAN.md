# Planner-Owned Human-in-the-Loop Approval Gate Redesign Plan

## Scope

This plan records the approval-gate redesign for planner-owned LangGraph write flows. It is planning-only. Implementation should be done on a dedicated branch after the current worktree is intentionally prepared for this change.

Recommended implementation branch name:

```text
codex/hitl-approval-gate-redesign
```

Do not mix the implementation with unrelated RAG, response document, or frontend cleanup work.

## Problem

The current graph does not blindly commit writes before approval, which is good. However, the approval lifecycle is still shaped too much like an end-of-graph concern:

```text
planner chooses write
tool_execution_node stages pending approval
satisfaction_node pauses
approval_node exposes pending approval near the end path
finalize_node defers while approval is pending
approval resume commits the write
```

This makes the graph harder to reason about for human-in-the-loop writes because approval is not modeled as the immediate lifecycle gate of the write requirement.

The failure mode becomes serious when the user changes their mind at approval time:

```text
System: approve changing 5 jobs?
User: no, only change JOB-005 instead
```

That response must not mutate the old staged calls. It must invalidate the old approval, revise the requirement ledger, and replan from the new requirement.

## Correct Design

Approval should sit directly inside the write requirement lifecycle:

```text
planner_decision_node
tool_retrieval_node
planner_choose_tool_node
write_staging_node
approval_gate_node
commit_write_node
evidence_observation_node
satisfaction_node
```

The key rule:

```text
Stage first.
Approve second.
Commit immediately after approval.
Record evidence.
Then continue to dependent requirements.
```

Do not wait until final response to commit. Dependent reads need committed evidence.

## New Write Flow

### 1. Plan Write Requirement

The planner selects the open write requirement.

Example:

```yaml
req-001:
  requirement_type: mutation_request
  entity: job
  constraints:
    status: planned
    priority: low
    new_priority: medium
```

### 2. Choose Write Tool

The planner chooses the write tool and exact staged calls.

At this point, no production data changes.

### 3. Stage Write Preview

`write_staging_node` builds a no-mutation preview:

```yaml
staged_write:
  requirement_id: req-001
  affected_rows:
    - id: JOB-SEED-005
      before:
        priority: low
      after:
        priority: medium
  staged_calls:
    - tool: PATCH /jobs/{id}
      args:
        id: JOB-SEED-005
        priority: medium
```

This is the approval payload.

### 4. Approval Gate

`approval_gate_node` pauses the graph and exposes the approval card.

Allowed user decisions:

```text
approve
reject
revise
timeout/expire
```

### 5A. Approved

If approved:

```text
approval evidence recorded
commit_write_node executes staged API calls
write evidence recorded
req-001 can be satisfied
dependent requirements may unblock
```

### 5B. Rejected

If rejected:

```text
approval evidence recorded as rejected
staged write is cancelled
req-001 becomes rejected/cancelled/blocked
dependent requirements stay blocked or become unavailable
final response explains no mutation happened
```

### 5C. Revised

If the user says:

```text
No, change only JOB-005 instead.
```

the graph must treat that as a requirement-ledger interrupt:

```text
old approval = stale/cancelled
old staged calls = stale
old req-001 = superseded or revised
ledger revision increments
new req-001 = change only JOB-005
planner loops back
new staged preview is created
approval requested again
```

No old staged call may commit after the ledger revision changes.

### 5D. Timeout / Expired

If the approval expires:

```text
approval evidence recorded as expired
staged calls remain uncommitted
write requirement remains unsatisfied or terminal-safe
dependent requirements do not run
```

## Dependency Rule

For a request like:

```text
Change planned low-priority jobs to medium priority, then show the updated jobs.
```

the read requirement must wait until the write has committed:

```yaml
req-001:
  mutation_request: update jobs

req-002:
  read_request: show updated jobs
  depends_on:
    - req-001
```

Flow:

```text
stage req-001
approve req-001
commit req-001
record write evidence
satisfy req-001
unblock req-002
read updated jobs
final response
```

If approval is rejected or stale, `req-002` must not run as if the write happened.

## Current vs Proposed Design

### Current Design Strengths

- Writes are not committed before approval.
- Native checkpoint resume can continue after approval.
- Stale approval protection already exists in several paths.
- Approval evidence and write evidence are recorded separately.

### Current Design Weaknesses

- Approval is exposed through a late graph node instead of being the explicit write gate.
- The same `tool_execution_node` handles read execution, write staging, and approval-related pauses.
- User revision during approval is easy to model incorrectly as modified approval args instead of a ledger revision.
- Bulk staged writes can be corrupted if global approved args overwrite row-specific IDs.
- Dependent read-after-write is not naturally represented.

### Proposed Design Strengths

- Write lifecycle is explicit and auditable.
- Approval pause happens immediately after staging.
- Commit happens immediately after approval, before dependent reads.
- Rejection/revision/timeout paths are terminal-safe.
- Ledger revision invalidates old approvals and staged calls.
- SSE/frontend state can render accurate progress events.

### Proposed Design Risk

- This is a graph contract change, not a small refactor.
- It affects backend approval semantics, checkpoint resume, response documents, frontend approval UX, SSE ordering, and release E2E.
- It needs a broad regression run.

## SSE / Frontend Progress Events

Push updates at each meaningful transition:

```text
requirement_ledger.created
planner.started
tool.selected
write.staged
approval.required
approval.approved
write.committing
write.committed
dependency.unblocked
read.started
read.completed
final_response.rendered
```

Rejected/revised paths:

```text
approval.rejected
approval.revision_requested
ledger.revised
staged_write.cancelled
```

The frontend may render from the latest event snapshot, but graph checkpoint state remains the source of truth.

## Affected Backend Unit / Integration Tests

### Must Change Or Add Assertions

These tests directly cover approval staging, approval resume, write commit timing, stale approvals, or revision during approval.

- `factory-agent/tests/test_planner_owned_graph_approval_resume.py`
  - `test_phase8_write_query_stages_preview_and_pauses_at_approval_node`
  - `test_phase8_incomplete_create_job_stages_approval_form_without_direct_fill`
  - `test_manual_regression_create_job_query_renders_manual_input_approval_contract`
  - `test_phase8_create_job_resume_executes_with_approval_form_args`
  - `test_phase8_no_records_for_first_write_continues_to_second_approval`
  - `test_phase8_commit_happens_only_after_matching_approval_and_native_checkpoint_resume`
  - `test_phase8_rejection_creates_rejection_evidence_and_finalizes_safely`
  - `test_phase8_stale_approval_is_rejected_without_commit`
  - `test_phase8_multi_step_approval_labels_approval_one_and_two`
  - `test_phase8_low_to_medium_then_medium_to_high_stages_second_approval_without_llm`
  - `test_phase8_no_record_first_operation_does_not_show_stale_or_future_approval_details`
  - add: bulk approval preserves each staged row ID after approval
  - add: read-after-write dependent read runs only after committed write evidence
  - add: approval revision supersedes old staged calls and replans

- `factory-agent/tests/test_planner_owned_graph_execution_observation.py`
  - `test_approval_staging_waits_for_prior_read_evidence_observation`
  - add: write staging node emits preview without API mutation
  - add: commit node records API write evidence after approval
  - add: rejected/expired approval produces no API write evidence

- `factory-agent/tests/test_planner_owned_graph_interruptions.py`
  - `test_phase9_append_interruption_creates_new_ledger_revision`
  - `test_phase9_modify_interruption_revises_requirement_and_preserves_locked_constraints`
  - `test_phase9_replace_interruption_supersedes_old_active_requirements_and_evidence`
  - `test_phase9_cancel_interruption_closes_active_graph_safely`
  - `test_phase9_stale_approval_cannot_commit_after_interruption`
  - `test_phase9_stale_background_result_is_ignored_by_revision_and_checkpoint`
  - add: approval-time user revision invalidates approval and staged write calls

- `factory-agent/tests/test_planner_owned_interrupt_replan.py`
  - update for approval-time revise flow if interrupt helpers are reused

- `factory-agent/tests/test_planner_owned_dependency_scheduler.py`
  - `test_dependency_scheduler_labels_mutation_as_approval_required`
  - `test_dependency_scheduler_serializes_mutation_until_prerequisite_read_is_satisfied_variant`
  - add: dependent read blocked until write commit evidence exists
  - add: dependent read stays blocked after approval rejection

- `factory-agent/tests/test_planner_owned_satisfaction.py`
  - update write satisfaction checks to require approval evidence plus committed API evidence
  - add: staged-only write cannot satisfy mutation requirement
  - add: rejected approval cannot satisfy mutation requirement

- `factory-agent/tests/test_planner_owned_intake_compiler.py`
  - `test_compiler_rejects_singular_dependent_read_without_referent`
  - add: `show the updated jobs` binds to previous mutation result
  - add: same prompt without previous mutation still asks clarification

- `factory-agent/tests/test_planner_owned_semantic_intake.py`
  - `test_semantic_intake_preserves_sequence_and_dependency`
  - add: LLM dependency hint for `updated jobs` is preserved but compiler remains authority

- `factory-agent/tests/test_planner_owned_graph_state_contract.py`
  - update serialized graph state if `staged_write`, `approval_gate`, or binding fields are added

- `factory-agent/tests/test_planner_owned_graph_shell_contract.py`
  - `test_phase3_simple_read_query_flows_through_graph_nodes_in_order`
  - add/write-flow node order test including `write_staging_node`, `approval_gate_node`, `commit_write_node`

- `factory-agent/tests/test_planner_owned_graph_api_contract.py`
  - `test_live_activity_records_repeated_graph_nodes_as_ordered_occurrences`
  - update snapshot/intent contract for new approval/write lifecycle diagnostics

- `factory-agent/tests/test_planner_owned_graph_runtime_adapter.py`
  - `test_graph_approval_row_is_not_committed_before_waiting_session_state`
  - `test_phase10_graph_pending_approval_empty_plan_is_not_planner_no_action`
  - `test_phase10_static_approval_resume_uses_native_graph_checkpoint_before_historical_direct_resume`
  - `test_phase10_graph_runtime_projects_approval_business_change_metadata_into_tool_outputs`
  - `test_graph_runtime_preserves_live_activity_history_before_clearing_transient_rows`
  - add: live activity emits write staged, approval required, commit started, commit completed

- `factory-agent/tests/test_api_endpoints.py`
  - approval approve/reject endpoints
  - stale approval recovery tests
  - historical approval payload resume tests
  - background resume failure tests
  - update approval payload contract if staged write metadata changes

- `factory-agent/tests/test_approval_atomicity.py`
  - `test_approve_is_atomic_and_bumps_event_seq`
  - `test_reject_is_atomic_and_bumps_event_seq`
  - `test_snapshot_self_heal_decided_approval_is_null`
  - `test_snapshot_self_heal_pending_approval_shown_when_truly_pending`
  - `test_resume_hint_set_when_executing_and_no_post_approval_tool`
  - `test_resume_hint_null_when_post_approval_tool_started`
  - `test_resume_hint_null_when_not_executing`
  - `test_resume_hint_null_when_no_approval_resume_context`

- `factory-agent/tests/test_approval_bundle_ui.py`
  - `test_build_job_priority_bundle_uiview_bulk_medium_to_high`
  - `test_build_approval_required_payload_includes_bundle_ui`
  - `test_non_job_writes_skip_bundle_ui`

### Must Rerun For Snapshot / SSE / Response Regressions

- `factory-agent/tests/test_event_stream_runtime.py`
- `factory-agent/tests/test_phase7_api_ui_alignment.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `factory-agent/tests/test_response_document_contract.py`
- `factory-agent/tests/test_response_document_failures.py`
- `factory-agent/tests/test_typed_snapshot_presentation_contract.py`
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`
- `factory-agent/tests/test_phase3_contract_coverage.py`
- `factory-agent/tests/test_stateful_oracle_harness.py`
- `factory-agent/tests/test_stateful_oracle_schema.py`
- `factory-agent/tests/test_seeded_scenario_engine.py`
- `factory-agent/tests/test_historical_direct_v2_hard_query_compatibility.py`
- `factory-agent/tests/test_historical_direct_v2_trace_compatibility.py`

## Affected Stateful Oracle Scenario Files

Primary approval/write/revision scenarios:

- `tests/e2e/scenarios/stateful_oracles/so-001_priority_medium_to_high_original_high_to_medium.json`
- `tests/e2e/scenarios/stateful_oracles/so-002_priority_high_to_low_original_low_to_medium.json`
- `tests/e2e/scenarios/stateful_oracles/so-003_priority_low_to_high_original_high_to_low.json`
- `tests/e2e/scenarios/stateful_oracles/so-004_priority_high_to_medium_original_medium_to_low.json`
- `tests/e2e/scenarios/stateful_oracles/so-005_second_approval_rejected.json`
- `tests/e2e/scenarios/stateful_oracles/so-006_second_approval_timeout.json`
- `tests/e2e/scenarios/stateful_oracles/so-007_approval_double_click_refresh_replay.json`
- `tests/e2e/scenarios/stateful_oracles/so-008_stale_approval_after_user_revision.json`
- `tests/e2e/scenarios/stateful_oracles/so-009_partial_bulk_commit_failure.json`
- `tests/e2e/scenarios/stateful_oracles/so-010_commit_succeeds_audit_missing.json`
- `tests/e2e/scenarios/stateful_oracles/so-011_no_final_before_second_approval.json`
- `tests/e2e/scenarios/stateful_oracles/so-012_timeline_omits_approval_2.json`
- `tests/e2e/scenarios/stateful_oracles/so-018_browser_refresh_during_active_approval.json`
- `tests/e2e/scenarios/stateful_oracles/so-027_revision_while_waiting_approval.json`
- `tests/e2e/scenarios/stateful_oracles/so-029_go_api_500_mid_run.json`
- `tests/e2e/scenarios/stateful_oracles/so-035_real_langgraph_no_seeded_adapter.json`
- `tests/e2e/scenarios/stateful_oracles/so-041_priority_medium_to_high_original_high_to_low.json`
- `tests/e2e/scenarios/stateful_oracles/so-044_unsupported_dangerous_action_blocked.json`

Streaming/snapshot scenarios to rerun because approval state is delivered through SSE/snapshots:

- `tests/e2e/scenarios/stateful_oracles/so-013_sse_completion_before_snapshot_terminal.json`
- `tests/e2e/scenarios/stateful_oracles/so-014_sse_reconnect_duplicates_activity_rows.json`
- `tests/e2e/scenarios/stateful_oracles/so-015_sse_malformed_payload_then_valid_payload.json`
- `tests/e2e/scenarios/stateful_oracles/so-016_eventsource_disconnect_on_modal_close.json`
- `tests/e2e/scenarios/stateful_oracles/so-017_static_bearer_polling_fallback.json`
- `tests/e2e/scenarios/stateful_oracles/so-030_factory_agent_restart_or_stream_drop_mid_run.json`

Response/safety scenarios to rerun for final document regressions:

- `tests/e2e/scenarios/stateful_oracles/so-020_empty_final_response.json`
- `tests/e2e/scenarios/stateful_oracles/so-031_large_structured_result_layout_final_state.json`
- `tests/e2e/scenarios/stateful_oracles/so-032_cross_session_leakage_security_privacy.json`
- `tests/e2e/scenarios/stateful_oracles/so-033_authorization_failure_stale_response.json`
- `tests/e2e/scenarios/stateful_oracles/so-042_unsafe_rendered_content_inert.json`
- `tests/e2e/scenarios/stateful_oracles/so-043_large_pasted_input_controlled.json`

## Affected Frontend Unit Tests

Approval rendering, reducer ordering, timeline, and turn assembly are affected:

- `eMas Front/src/components/features/chat/factory-agent/ApprovalCard.component.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/ActivityTimeline.component.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/approvalInterruptDisplay.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/approvalFieldUtils.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/responseDocumentReducer.test.mjs`
- `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs`
- `eMas Front/e2e/support/factoryAgentTransitionOracle.test.mjs`
- `eMas Front/e2e/support/responseDocumentProbe.test.mjs`

## Affected Frontend Browser E2E Specs

Primary approval/write specs:

- `eMas Front/e2e/specs/final-response-quality.spec.js`
- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/specs/full-stack-orchestration.spec.js`
- `eMas Front/e2e/specs/full-stack-seeded.spec.js`
- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`
- `eMas Front/e2e/specs/release-resilience.spec.js`
- `eMas Front/e2e/specs/security-privacy.spec.js`

SSE/snapshot ordering specs:

- `eMas Front/e2e/specs/chat-sse-activity.spec.js`
- `eMas Front/e2e/specs/chat-sse-notification.spec.js`
- `eMas Front/e2e/specs/chat-stream-errors.spec.js`
- `eMas Front/e2e/specs/chat-cancel-navigation.spec.js`
- `eMas Front/e2e/specs/full-stack-sse-hard.spec.js`
- `eMas Front/e2e/specs/full-stack-resilience.spec.js`
- `eMas Front/e2e/specs/reliability-soak.spec.js`
- `eMas Front/e2e/specs/response-document-traffic.spec.js`

Response document and release specs:

- `eMas Front/e2e/specs/chat-fixtures.spec.js`
- `eMas Front/e2e/specs/response-document-hard-query-oracle.spec.js`
- `eMas Front/e2e/specs/release-validation.spec.js`
- `eMas Front/e2e/specs/release-security-privacy.spec.js`
- `eMas Front/e2e/specs/production-synthetic.spec.js`

## Required Test Pipeline After Implementation

### Backend Targeted Gate

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\factory-agent"
python -m pytest `
  tests/test_planner_owned_graph_approval_resume.py `
  tests/test_planner_owned_graph_execution_observation.py `
  tests/test_planner_owned_graph_interruptions.py `
  tests/test_planner_owned_dependency_scheduler.py `
  tests/test_planner_owned_satisfaction.py `
  tests/test_planner_owned_intake_compiler.py `
  tests/test_planner_owned_semantic_intake.py `
  tests/test_planner_owned_graph_runtime_adapter.py `
  tests/test_api_endpoints.py `
  tests/test_approval_atomicity.py `
  tests/test_approval_bundle_ui.py `
  tests/test_event_stream_runtime.py `
  tests/test_response_document_contract.py `
  tests/test_response_document_failures.py `
  tests/test_snapshot_timeline_final_response_contract.py `
  -q
```

### Backend Oracle Gate

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front"
npm run test:backend-oracles
```

### Full Backend Pytest

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\factory-agent"
python -m pytest
```

### Seed / Oracle E2E

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi"
.\tests\e2e\run_seed_pipeline.ps1
.\tests\e2e\run_seed_pipeline.ps1 -AgentApi
```

### Frontend Unit Tests

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front"
npm test
```

### Mocked Chromium E2E

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front"
npm run test:e2e:mocked
```

### Seeded Oracle Chromium E2E

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front"
npm run test:e2e:seeded-oracles
```

### Real LangGraph E2E

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front"
npm run test:e2e:real-langgraph
```

### Release E2E

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front"
npm run test:e2e:release
```

### Optional Reliability / Synthetic

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front"
npm run test:e2e:reliability
npm run test:e2e:reliability:seeded
npm run test:e2e:synthetic
```

## Acceptance Criteria

- Write staging creates a preview and does not mutate data.
- Approval is exposed immediately after write staging.
- Approved writes commit before dependent reads run.
- Rejected writes never commit.
- Approval-time revision increments the ledger and invalidates old staged calls.
- Stale approvals cannot commit after any ledger revision or checkpoint change.
- Bulk approval preserves row-specific IDs.
- Response document shows staged, approved, committed, rejected, revised, and failed states distinctly.
- SSE and polling snapshots converge on the same approval/write lifecycle.
- The full backend, oracle, Chromium, real LangGraph, and release E2E gates pass.
