from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest

from factory_agent.config import get_settings
from factory_agent.graph.checkpointing import clear_graph_checkpointer_cache
from factory_agent.graph.errors import LangGraphPlannerApprovalRequired
from factory_agent.graph.nodes.validate import make_final_validator_node
from factory_agent.graph.planner_graph import LangGraphPlanner
from factory_agent.graph.state import replaceable_list_reducer
from factory_agent.schemas import ToolInfo
from tests.support.operation_assertions import assert_audit_rows_match
from tests.support.operation_assertions import assert_final_state_matches_oracle
from tests.support.operation_assertions import assert_no_timeline_event
from tests.support.operation_assertions import assert_timeline_contains_chain
from tests.support.operation_assertions import assert_unchanged_rows
from tests.support.stateful_oracle_harness import StatefulOracleHarness


def _settings(*, checkpoint_backend: str = "memory"):
    return replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        graph_checkpoint_backend=checkpoint_backend,
        max_foreach_items=50,
        max_plan_steps=8,
    )


def _jobs_list_tool() -> ToolInfo:
    return ToolInfo(
        name="get__jobs",
        description="List jobs",
        endpoint="/jobs",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                "fields": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "job_id": {"type": "string"},
                            "priority": {"type": "string"},
                        },
                    },
                }
            },
        },
        query_params=["priority", "fields", "limit"],
        param_sources={"priority": "query", "fields": "query", "limit": "query"},
        is_read_only=True,
    )


def _job_update_tool() -> ToolInfo:
    return ToolInfo(
        name="put__jobs_{id}",
        description="Update a job",
        endpoint="/jobs/{id}",
        method="PUT",
        input_schema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            },
        },
        path_params=["id"],
        body_fields=["priority"],
        param_sources={"id": "path", "priority": "body"},
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
    )


def _priority_tools() -> list[ToolInfo]:
    return [_jobs_list_tool(), _job_update_tool()]


def _install_harnessed_langgraph(monkeypatch: pytest.MonkeyPatch, harness: StatefulOracleHarness) -> None:
    clear_graph_checkpointer_cache()

    def fail_model(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Phase 3 state-machine oracles must use deterministic graph mechanics")

    monkeypatch.setattr("factory_agent.graph.nodes.planner_loop.build_planner_chat_model", fail_model)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.execute_tool_http", harness.execute_tool_http)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.bundle_dry_run_node", harness.bundle_dry_run_node)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.commit_node_impl", harness.commit_node)


def _staged_priority_write(intent_id: str = "intent-1") -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "decision_id": f"{intent_id}-decision",
        "tool_call_id": f"{intent_id}-write-1",
        "tool_name": "put__jobs_{id}",
        "args": {"id": "JOB-1", "priority": "high"},
        "output_ref": "$ref:JOB-1",
        "idempotency_key": f"{intent_id}-idem",
        "status": "staged",
    }


def _approval_ids(harness: StatefulOracleHarness) -> list[str]:
    return list(harness.approvals)


def _job_priorities(harness: StatefulOracleHarness) -> dict[str, str]:
    return {str(row["id"]): str(row.get("priority")) for row in harness.job_snapshot()}


def _assert_job_priorities(harness: StatefulOracleHarness, expected: dict[str, str]) -> None:
    assert _job_priorities(harness) == expected


def _assert_staged_write_args(dry_run: dict[str, Any], expected: list[dict[str, Any]]) -> None:
    assert [item["args"] for item in dry_run["staged_writes"]] == expected


def _assert_expected_approval_ids(harness: StatefulOracleHarness) -> None:
    expected = [
        str(item["approval_id"])
        for item in harness.oracle.get("expected_approvals") or []
        if item.get("decision") in {"accepted", "rejected", "expired"}
    ]
    assert _approval_ids(harness) == expected


def _operation_start_payload(oracle: dict[str, Any]) -> dict[str, Any]:
    first = next((row for row in oracle.get("expected_timeline") or [] if row.get("event") == "operation_started"), {})
    return {key: value for key, value in first.items() if key != "event"}


def _expected_write_args_for_approval(oracle: dict[str, Any], index: int) -> list[dict[str, Any]]:
    approval = oracle["expected_approvals"][index]
    intent = next(
        item
        for item in oracle["expected_intents"]
        if item.get("intent_id") == approval.get("intent_id")
    )
    target_priority = approval.get("new_priority") or (intent.get("new_values") or {}).get("priority")
    return [{"id": str(row_id), "priority": target_priority} for row_id in approval.get("row_ids") or []]


def _assert_no_completed_state_with_active_work(state: dict[str, Any]) -> None:
    if state.get("status") != "completed":
        return
    active_intents = [
        item
        for item in state.get("working_intents") or []
        if isinstance(item, dict) and item.get("status") in {"pending", "in_progress"}
    ]
    staged = [item for item in state.get("staged_writes") or [] if isinstance(item, dict)]
    pending_approvals = [
        item
        for item in state.get("approval_requests") or []
        if isinstance(item, dict) and item.get("status") in {"pending", "requested"}
    ]
    assert not active_intents, f"COMPLETED with active intents: {active_intents!r}"
    assert not staged, f"COMPLETED with staged writes: {staged!r}"
    assert not pending_approvals, f"COMPLETED with pending approvals: {pending_approvals!r}"


def test_successful_commit_with_active_intent_does_not_complete_and_clears_staged_writes():
    node = make_final_validator_node(_settings(checkpoint_backend="off"))
    staged = [_staged_priority_write()]

    out = node(
        {
            "last_commit_result": {"ok": True, "http_status": 200, "body": {"committed": True}},
            "working_intents": [
                {
                    "intent_id": "intent-1",
                    "description": "change medium jobs to high",
                    "depends_on": [],
                    "status": "in_progress",
                },
                {
                    "intent_id": "intent-2",
                    "description": "change original high jobs to medium",
                    "depends_on": [],
                    "status": "pending",
                },
            ],
            "intent_cursor": 0,
            "staged_writes": staged,
            "bundle_dry_run_result": {"ok": True, "http_status": 200},
            "approval_requests": [{"status": "approved"}],
            "pending_decision": {"stale": True},
            "pending_relevance_batch": [{"stale": True}],
            "repair_attempts": 2,
        }
    )

    assert out["status"] == "planning"
    assert out["next_route"] == "continue_planner"
    assert out["intent_cursor"] == 1
    assert out["current_intent"]["intent_id"] == "intent-2"
    assert out["working_intents"][0]["status"] == "completed"
    assert out["working_intents"][1]["status"] == "in_progress"
    assert out["approval_requests"] == []
    assert replaceable_list_reducer(staged, out["staged_writes"]) == []
    _assert_no_completed_state_with_active_work(out)


@pytest.mark.parametrize(
    "bad_state",
    [
        {
            "status": "completed",
            "working_intents": [{"intent_id": "intent-2", "status": "pending"}],
        },
        {
            "status": "completed",
            "staged_writes": [_staged_priority_write()],
        },
        {
            "status": "completed",
            "approval_requests": [{"approval_id": "approval-1", "status": "pending"}],
        },
    ],
)
def test_oracle_validity_completed_state_invariant_fails_with_active_work(bad_state):
    with pytest.raises(AssertionError):
        _assert_no_completed_state_with_active_work(bad_state)


def test_oracle_validity_detects_premature_completion_and_missing_second_approval():
    harness = StatefulOracleHarness.from_oracle_id("SO-011")
    harness.start_operation(intent_count=2)
    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-011-1", auto_complete=False).ok is True

    harness.complete_operation()

    with pytest.raises(AssertionError):
        assert_no_timeline_event(harness, "final_response_created")
    with pytest.raises(AssertionError):
        assert_no_timeline_event(harness, "operation_completed")
    with pytest.raises(AssertionError):
        assert_timeline_contains_chain(harness, harness.oracle["expected_timeline"])


def test_oracle_validity_detects_mutation_before_approval():
    harness = StatefulOracleHarness.from_oracle_id("SO-001")
    baseline = _job_priorities(harness)

    harness.dry_run_oracle_intent(0)
    _assert_job_priorities(harness, baseline)

    harness.jobs["JOB-SO001-MED-01"]["priority"] = "high"
    with pytest.raises(AssertionError):
        _assert_job_priorities(harness, baseline)


def test_oracle_validity_detects_current_state_cascade_source_set():
    harness = StatefulOracleHarness.from_oracle_id("SO-001")
    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-001-1", auto_complete=False).ok is True

    bad_second = harness.dry_run(
        harness.build_priority_update_writes(
            source_priority="high",
            target_priority="medium",
            intent_id="SO-001-I2",
            state_basis="current",
        )
    )

    with pytest.raises(AssertionError):
        _assert_staged_write_args(
            bad_second,
            [
                {"id": "JOB-SO001-HIGH-01", "priority": "medium"},
                {"id": "JOB-SO001-HIGH-02", "priority": "medium"},
            ],
        )


def test_oracle_validity_detects_reused_approval_id():
    harness = StatefulOracleHarness.from_oracle_id("SO-001")
    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-001-1", auto_complete=False).ok is True
    bad_second = harness.build_priority_update_writes(
        source_priority="high",
        target_priority="medium",
        intent_id="SO-001-I2",
        state_basis="original",
    )

    harness.request_approval(
        approval_id="approval-so-001-1",
        intent_id="SO-001-I2",
        staged_writes=bad_second,
    )

    with pytest.raises(AssertionError):
        _assert_expected_approval_ids(harness)


def test_oracle_validity_detects_success_claim_when_rejection_has_no_commit_evidence():
    harness = StatefulOracleHarness.from_oracle_id("SO-005")
    harness.start_operation(intent_count=2)
    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-005-1", auto_complete=False).ok is True
    harness.dry_run_oracle_intent(1)

    harness.record_event("final_response_created")
    harness.record_event("operation_completed")

    with pytest.raises(AssertionError):
        assert_no_timeline_event(harness, "final_response_created")
    with pytest.raises(AssertionError):
        assert_timeline_contains_chain(harness, harness.oracle["expected_timeline"])


@pytest.mark.asyncio
async def test_so011_no_completion_with_pending_approval_or_before_second_approval(monkeypatch):
    session_id = f"so011-state-machine-{uuid.uuid4()}"
    harness = StatefulOracleHarness.from_oracle_id("SO-011", session_id=session_id)
    harness.start_operation(intent_count=2)
    _install_harnessed_langgraph(monkeypatch, harness)

    planner = LangGraphPlanner(_settings())
    with pytest.raises(LangGraphPlannerApprovalRequired) as first:
        await planner.generate(
            intent=harness.oracle["prompt"],
            scoped_tools=_priority_tools(),
            context={"session_id": session_id},
        )

    first_id = harness.pending_approval_id
    assert first_id == "approval-so-011-1"
    assert first.value.payload["kind"] == "approval_required"
    assert harness.session_phase == "WAITING_APPROVAL"
    assert_no_timeline_event(harness, "final_response_created")
    assert_no_timeline_event(harness, "operation_completed")

    with pytest.raises(LangGraphPlannerApprovalRequired) as second:
        await planner.resume_after_approval(session_id=session_id, approved=True)

    second_id = harness.pending_approval_id
    assert second_id == "approval-so-011-2"
    assert first_id != second_id
    _assert_expected_approval_ids(harness)
    assert harness.commit_count_by_approval == {"approval-so-011-1": 1}
    assert second.value.payload["kind"] == "approval_required"
    assert harness.session_phase == "WAITING_APPROVAL"
    assert_no_timeline_event(harness, "final_response_created")
    assert_no_timeline_event(harness, "operation_completed")

    await planner.resume_after_approval(session_id=session_id, approved=True)

    assert harness.commit_count_by_approval == {
        "approval-so-011-1": 1,
        "approval-so-011-2": 1,
    }
    assert_final_state_matches_oracle(harness, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])
    assert_unchanged_rows(harness, harness.oracle["expected_unchanged_rows"])


@pytest.mark.asyncio
async def test_so001_cascade_uses_original_state_for_second_approval(monkeypatch):
    session_id = f"so001-original-state-{uuid.uuid4()}"
    harness = StatefulOracleHarness.from_oracle_id("SO-001", session_id=session_id)
    harness.start_operation(intent_count=2)
    _install_harnessed_langgraph(monkeypatch, harness)

    planner = LangGraphPlanner(_settings())
    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.generate(
            intent=harness.oracle["prompt"],
            scoped_tools=_priority_tools(),
            context={"session_id": session_id},
        )
    _assert_job_priorities(
        harness,
        {
            "JOB-SO001-HIGH-01": "high",
            "JOB-SO001-HIGH-02": "high",
            "JOB-SO001-MED-01": "medium",
            "JOB-SO001-MED-02": "medium",
            "JOB-SO001-LOW-01": "low",
        },
    )

    assert [call["args"] for call in harness.read_requests if call["tool_name"] == "get__jobs"] == [
        {"priority": "medium", "fields": "job_id,priority", "limit": 500},
        {"priority": "high", "fields": "job_id,priority", "limit": 500},
    ]
    _assert_staged_write_args(
        harness.dry_runs[0],
        [
            {"id": "JOB-SO001-MED-01", "priority": "high"},
            {"id": "JOB-SO001-MED-02", "priority": "high"},
        ],
    )

    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.resume_after_approval(session_id=session_id, approved=True)

    assert harness.select_job_ids({"priority": "high"}, state_basis="current") == [
        "JOB-SO001-HIGH-01",
        "JOB-SO001-HIGH-02",
        "JOB-SO001-MED-01",
        "JOB-SO001-MED-02",
    ]
    _assert_staged_write_args(
        harness.dry_runs[1],
        [
            {"id": "JOB-SO001-HIGH-01", "priority": "medium"},
            {"id": "JOB-SO001-HIGH-02", "priority": "medium"},
        ],
    )

    await planner.resume_after_approval(session_id=session_id, approved=True)

    assert_final_state_matches_oracle(harness, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])
    assert_timeline_contains_chain(harness, harness.oracle["expected_timeline"])


@pytest.mark.asyncio
async def test_so041_medium_to_high_then_original_high_to_low(monkeypatch):
    session_id = f"so041-original-state-{uuid.uuid4()}"
    harness = StatefulOracleHarness.from_oracle_id("SO-041", session_id=session_id)
    harness.start_operation(intent_count=2)
    _install_harnessed_langgraph(monkeypatch, harness)

    planner = LangGraphPlanner(_settings())
    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.generate(
            intent="change all medium priority job to high then change all high priority job to low",
            scoped_tools=_priority_tools(),
            context={"session_id": session_id},
        )

    assert [call["args"] for call in harness.read_requests if call["tool_name"] == "get__jobs"] == [
        {"priority": "medium", "fields": "job_id,priority", "limit": 500},
        {"priority": "high", "fields": "job_id,priority", "limit": 500},
    ]
    _assert_staged_write_args(
        harness.dry_runs[0],
        [
            {"id": "JOB-SO041-MED-01", "priority": "high"},
            {"id": "JOB-SO041-MED-02", "priority": "high"},
        ],
    )

    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.resume_after_approval(session_id=session_id, approved=True)

    assert harness.select_job_ids({"priority": "high"}, state_basis="current") == [
        "JOB-SO041-HIGH-01",
        "JOB-SO041-HIGH-02",
        "JOB-SO041-MED-01",
        "JOB-SO041-MED-02",
    ]
    _assert_staged_write_args(
        harness.dry_runs[1],
        [
            {"id": "JOB-SO041-HIGH-01", "priority": "low"},
            {"id": "JOB-SO041-HIGH-02", "priority": "low"},
        ],
    )

    _draft, _contract, outputs = await planner.resume_after_approval(session_id=session_id, approved=True)

    assert harness.commit_count_by_approval == {
        "approval-so-041-1": 1,
        "approval-so-041-2": 1,
    }
    assert_final_state_matches_oracle(harness, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])
    assert_unchanged_rows(harness, harness.oracle["expected_unchanged_rows"])
    assert_timeline_contains_chain(harness, harness.oracle["expected_timeline"])
    assert {row.get("args", {}).get("id") for row in outputs if row.get("tool_name") == "put__jobs_{id}"} == {
        "JOB-SO041-MED-01",
        "JOB-SO041-MED-02",
        "JOB-SO041-HIGH-01",
        "JOB-SO041-HIGH-02",
    }
    previous_by_id = {
        row["args"]["id"]: row["result"]["data"].get("previous_priority")
        for row in outputs
        if row.get("tool_name") == "put__jobs_{id}"
    }
    assert previous_by_id == {
        "JOB-SO041-MED-01": "medium",
        "JOB-SO041-MED-02": "medium",
        "JOB-SO041-HIGH-01": "high",
        "JOB-SO041-HIGH-02": "high",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("oracle_id", ["SO-002", "SO-003", "SO-004", "SO-035"])
async def test_priority_cascade_oracles_use_original_state_for_second_write_set(monkeypatch, oracle_id):
    session_id = f"{oracle_id.lower()}-original-state-{uuid.uuid4()}"
    harness = StatefulOracleHarness.from_oracle_id(oracle_id, session_id=session_id)
    harness.start_operation(
        intent_count=len(harness.oracle["expected_intents"]),
        event_payload=_operation_start_payload(harness.oracle),
    )
    _install_harnessed_langgraph(monkeypatch, harness)

    planner = LangGraphPlanner(_settings())
    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.generate(
            intent=harness.oracle["prompt"],
            scoped_tools=_priority_tools(),
            context={"session_id": session_id},
        )

    _assert_staged_write_args(harness.dry_runs[0], _expected_write_args_for_approval(harness.oracle, 0))

    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.resume_after_approval(session_id=session_id, approved=True)

    _assert_staged_write_args(harness.dry_runs[1], _expected_write_args_for_approval(harness.oracle, 1))
    forbidden_rows = set(
        (harness.oracle.get("expected_intermediate_states") or [{}])[0].get("forbidden_second_approval_rows")
        or []
    )
    second_rows = {row["args"]["id"] for row in harness.dry_runs[1]["staged_writes"]}
    assert not (second_rows & forbidden_rows), (
        f"{oracle_id} second approval used rows from approval 1: {second_rows & forbidden_rows}"
    )

    await planner.resume_after_approval(session_id=session_id, approved=True)

    assert harness.commit_count_by_approval == {
        str(row["approval_id"]): 1 for row in harness.oracle["expected_approvals"]
    }
    assert_final_state_matches_oracle(harness, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])
    assert_unchanged_rows(harness, harness.oracle["expected_unchanged_rows"])
    if oracle_id != "SO-035":
        assert_timeline_contains_chain(harness, harness.oracle["expected_timeline"])


@pytest.mark.asyncio
async def test_so005_second_approval_rejection_stops_without_hidden_commit(monkeypatch):
    session_id = f"so005-reject-{uuid.uuid4()}"
    harness = StatefulOracleHarness.from_oracle_id("SO-005", session_id=session_id)
    harness.start_operation(intent_count=2)
    _install_harnessed_langgraph(monkeypatch, harness)

    planner = LangGraphPlanner(_settings())
    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.generate(
            intent=harness.oracle["prompt"],
            scoped_tools=_priority_tools(),
            context={"session_id": session_id},
        )
    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.resume_after_approval(session_id=session_id, approved=True)

    second_id = "approval-so-005-2"
    await planner.resume_after_approval(session_id=session_id, approved=False)

    assert harness.commit_count_by_approval == {"approval-so-005-1": 1}
    assert harness.audit_rows_for(second_id) == []
    assert_no_timeline_event(harness, "commit_started", approval_id=second_id)
    assert_no_timeline_event(harness, "commit_completed", approval_id=second_id)
    assert_no_timeline_event(harness, "operation_completed")


@pytest.mark.asyncio
async def test_so006_second_approval_timeout_does_not_mutate_or_complete(monkeypatch):
    session_id = f"so006-timeout-{uuid.uuid4()}"
    harness = StatefulOracleHarness.from_oracle_id("SO-006", session_id=session_id)
    harness.start_operation(intent_count=2)
    _install_harnessed_langgraph(monkeypatch, harness)

    planner = LangGraphPlanner(_settings())
    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.generate(
            intent=harness.oracle["prompt"],
            scoped_tools=_priority_tools(),
            context={"session_id": session_id},
        )
    with pytest.raises(LangGraphPlannerApprovalRequired):
        await planner.resume_after_approval(session_id=session_id, approved=True)

    expired = harness.expire_approval("approval-so-006-2")
    late = harness.approve("approval-so-006-2", source="late_approve_attempt")

    assert expired.http_status == 409
    assert expired.error == "expired_approval"
    assert late.http_status == 409
    assert late.error == "expired_approval"
    assert harness.commit_count_by_approval == {"approval-so-006-1": 1}
    assert_no_timeline_event(harness, "commit_started", approval_id="approval-so-006-2")
    assert_no_timeline_event(harness, "operation_completed")
    assert_final_state_matches_oracle(harness, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])


def test_so008_user_revision_invalidates_stale_approval_without_mutation():
    harness = StatefulOracleHarness.from_oracle_id("SO-008")
    harness.start_operation(turn_id="SO-008-T1")

    harness.dry_run_oracle_intent(0)
    assert harness.pending_approval_id == "approval-so-008-old"
    invalidated = harness.supersede_pending_approvals(
        reason="superseded_by_user_revision",
        turn_id="SO-008-T2",
    )

    harness.dry_run_oracle_intent(1)
    stale = harness.approve("approval-so-008-old", source="revision_replay")
    accepted = harness.approve("approval-so-008-new")

    assert invalidated == ["approval-so-008-old"]
    assert stale.http_status == 409
    assert stale.error == "stale_approval"
    assert accepted.ok is True
    assert harness.commit_count_by_approval == {"approval-so-008-new": 1}
    assert harness.audit_rows_for("approval-so-008-old") == []
    assert_no_timeline_event(harness, "commit_started", approval_id="approval-so-008-old")
    assert_final_state_matches_oracle(harness, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])
    assert_unchanged_rows(harness, harness.oracle["expected_unchanged_rows"])
