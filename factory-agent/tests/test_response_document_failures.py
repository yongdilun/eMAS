from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pytest

from factory_agent.config import Settings
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.models import Approval, Message, Plan, PlanStep, Session
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.services.session_snapshot_service import SessionSnapshotService


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
        checkpoint_enabled=False,
        memory_enabled=False,
        jwt_required=False,
        enforce_tool_registry_health=False,
        auto_repair_tool_registry=False,
        min_healthy_tool_count=0,
    )


async def _snapshot(db_session, session_id: str) -> dict[str, Any]:
    service = SessionSnapshotService(
        session_mgr=SessionManager(_settings()),
        memory_manager=MemoryManager(_settings()),
        tool_registry=ToolRegistry(),
    )
    snapshot = await service.load_session_snapshot(db=db_session, session_id=session_id)
    assert snapshot is not None
    return snapshot.model_dump(mode="json")


def _session(
    *,
    session_id: str,
    created_at: datetime,
    status: str,
    plan_id: str | None = None,
    event_seq: int = 1,
    step_count: int = 1,
    error: str | None = None,
) -> Session:
    return Session(
        session_id=session_id,
        user_id="u1",
        status=status,
        current_intent=f"failure recovery contract for {session_id}",
        plan_id=plan_id,
        plan_version=1 if plan_id else 0,
        plan_hash=f"{plan_id}-hash" if plan_id else None,
        current_step_index=0,
        step_count=step_count,
        llm_call_count=0,
        event_seq=event_seq,
        session_started_at=created_at,
        created_at=created_at,
        updated_at=created_at + timedelta(seconds=5),
        completed_at=created_at + timedelta(seconds=5) if status == "COMPLETED" else None,
        error=error,
    )


def _plan(*, session_id: str, plan_id: str, created_at: datetime) -> Plan:
    return Plan(
        plan_id=plan_id,
        session_id=session_id,
        version=1,
        kind="execution",
        status="PENDING_APPROVAL",
        dependency_graph={"0": []},
        parallel_groups=[],
        plan_hash=f"{plan_id}-hash",
        plan_explanation="Execute the requested operation safely.",
        risk_summary="Writes require approval.",
        created_at=created_at,
        created_by="test",
    )


def _user_message(*, session_id: str, created_at: datetime, content: str = "Run the operation") -> Message:
    return Message(
        message_id=f"{session_id}-user",
        session_id=session_id,
        role="user",
        content=content,
        created_at=created_at,
    )


def _assistant_message(
    *,
    session_id: str,
    content: str,
    created_at: datetime,
    tool_name: str | None = "__conversation__",
    step_id: str | None = None,
) -> Message:
    return Message(
        message_id=f"{session_id}-assistant-{abs(hash((content, created_at))) % 100000}",
        session_id=session_id,
        role="assistant",
        content=content,
        tool_name=tool_name,
        step_id=step_id,
        created_at=created_at,
    )


def _approval(
    *,
    session_id: str,
    plan_id: str,
    approval_id: str,
    created_at: datetime,
    status: str,
    decided_at: datetime | None = None,
    rejection_reason: str | None = None,
    rows: list[dict[str, Any]] | None = None,
    created_offset_s: int = 2,
) -> Approval:
    return Approval(
        approval_id=approval_id,
        session_id=session_id,
        subject_type="graph",
        plan_id=plan_id,
        tool_name="__langgraph_commit__",
        args={
            "bundle_ui": {
                "rows": rows or [{"job_id": f"JOB-{approval_id}", "new_priority": "high"}],
                "write_set": f"write-set-{approval_id}",
            }
        },
        risk_summary=f"Review {approval_id}.",
        side_effect_level="HIGH",
        status=status,
        expires_at=created_at + timedelta(hours=1),
        decided_by="operator" if decided_at else None,
        decided_at=decided_at,
        rejection_reason=rejection_reason,
        created_at=created_at + timedelta(seconds=created_offset_s),
    )


def _write_step(
    *,
    session_id: str,
    plan_id: str,
    step_id: str,
    step_index: int,
    created_at: datetime,
    approval_id: str | None,
    status: str,
    result: dict[str, Any] | None,
    last_error: str | None = None,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        plan_id=plan_id,
        session_id=session_id,
        step_index=step_index,
        tool_name="put__jobs_{id}",
        args={"id": f"JOB-{step_id}", "priority": "high"},
        bindings=[],
        status=status,
        idempotency_key=f"{step_id}-key",
        requires_approval=approval_id is not None,
        approval_id=approval_id,
        retry_count=0,
        max_retries=0,
        completed_at=created_at,
        result=result,
        result_summary=None,
        last_error=last_error,
    )


def _diagnostic(document: dict[str, Any]) -> dict[str, Any]:
    return next(block for block in document["blocks"] if block["type"] == "diagnostic")


def _assert_failure_fields(diagnostic: dict[str, Any]) -> None:
    assert diagnostic["cause"]
    assert diagnostic["impact"]
    assert diagnostic["current_state"]
    assert diagnostic["next_action"]
    assert diagnostic["retry_safety"]
    assert diagnostic["technical_details"]["sanitized"] is True
    assert diagnostic["details_collapsed"] is True


@pytest.mark.asyncio
async def test_timeout_response_document_uses_failure_card_not_stale_progress(db_session):
    created_at = datetime(2026, 5, 18, 8, 0, 0)
    session_id = "rd-failure-timeout"
    plan_id = "rd-failure-timeout-plan"
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                status="FAILED",
                event_seq=8,
                error="Planner timeout after 20s\nTraceback (most recent call last):\n  password=super-secret",
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    diagnostic = _diagnostic(document)

    assert document["state"] == "failed"
    assert document["message"] == "I could not finish this request because the planner timed out while preparing the next step."
    assert diagnostic["reason"] == "planner_timeout"
    assert diagnostic["retry_safety"]["safe_to_retry"] is True
    assert "retry_from_checkpoint" in {action["id"] for action in diagnostic["next_actions"]}
    assert "Run complete" not in document["message"]
    assert "Waiting for approval" not in document["message"]
    _assert_failure_fields(diagnostic)
    serialized = json.dumps(document).lower()
    assert "traceback" not in serialized
    assert "super-secret" not in serialized


@pytest.mark.asyncio
async def test_decision_guard_loop_has_bounded_diagnostic_and_no_blind_retry(db_session):
    created_at = datetime(2026, 5, 18, 8, 30, 0)
    session_id = "rd-failure-decision-guard"
    plan_id = "rd-failure-decision-guard-plan"
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                status="BLOCKED",
                event_seq=9,
                error=(
                    "Decision guard rejected repeated planner repairs: "
                    "decision_guard_constraint_repair_limit; constraint_violation_loop"
                ),
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    diagnostic = _diagnostic(document)

    assert document["state"] == "blocked"
    assert diagnostic["reason"] == "planner_validation_loop"
    assert diagnostic["retry_safety"]["safe_to_retry"] is False
    assert "retry_from_checkpoint" not in {action["id"] for action in diagnostic["next_actions"]}
    assert diagnostic["impact"]["incomplete_steps"] == ["diagnostic:planner_validation_loop"]
    _assert_failure_fields(diagnostic)


@pytest.mark.asyncio
async def test_tool_http_error_sanitizes_stack_traces_and_secrets(db_session):
    created_at = datetime(2026, 5, 18, 9, 0, 0)
    session_id = "rd-failure-tool-http"
    plan_id = "rd-failure-tool-http-plan"
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                status="FAILED",
                event_seq=10,
                error="HTTP 500: database unavailable",
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-http-step",
                step_index=0,
                created_at=created_at + timedelta(seconds=3),
                approval_id=None,
                status="FAILED",
                result={},
                last_error="HTTP 500: database unavailable\nTraceback (most recent call last):\n api_key=sk-test-secret",
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    diagnostic = _diagnostic(document)

    assert diagnostic["reason"] == "tool_http_error"
    assert diagnostic["retry_safety"]["safe_to_retry"] is False
    assert "check_status" in {action["id"] for action in diagnostic["next_actions"]}
    _assert_failure_fields(diagnostic)
    serialized = json.dumps(document).lower()
    assert "traceback" not in serialized
    assert "sk-test-secret" not in serialized
    assert "api_key=sk-test-secret" not in serialized


@pytest.mark.asyncio
async def test_partial_failure_lists_succeeded_and_failed_rows_separately(db_session):
    created_at = datetime(2026, 5, 18, 9, 30, 0)
    session_id = "rd-failure-partial"
    plan_id = "rd-failure-partial-plan"
    approval_id = "approval-rd-partial-failure"
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                status="FAILED",
                event_seq=11,
                error="Partial commit failure.",
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                approval_id=approval_id,
                created_at=created_at,
                status="APPROVED",
                decided_at=created_at + timedelta(seconds=2),
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-partial-step",
                step_index=0,
                created_at=created_at + timedelta(seconds=3),
                approval_id=approval_id,
                status="FAILED",
                result={
                    "approval_id": approval_id,
                    "outcomes": [
                        {"job_id": "JOB-RD-PARTIAL-OK", "status": "succeeded"},
                        {"job_id": "JOB-RD-PARTIAL-FAIL", "status": "failed", "error": "version_conflict"},
                    ],
                },
                last_error="version_conflict",
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    diagnostic = _diagnostic(document)

    assert diagnostic["reason"] == "partial_commit_failure"
    assert diagnostic["impact"]["succeeded_rows"] == ["JOB-RD-PARTIAL-OK"]
    assert diagnostic["impact"]["failed_rows"] == ["JOB-RD-PARTIAL-FAIL"]
    assert diagnostic["retry_safety"]["policy"] == "retry_failed_rows_only"
    assert "retry_failed_rows_only" in {action["id"] for action in diagnostic["next_actions"]}
    assert any(block["type"] == "completed_step" for block in document["blocks"])
    mutation = next(block for block in document["blocks"] if block["type"] == "mutation_result")
    assert mutation["status"] == "partial_failure"


@pytest.mark.asyncio
async def test_rejected_approval_preserves_completed_step_and_does_not_claim_success(db_session):
    created_at = datetime(2026, 5, 18, 10, 0, 0)
    session_id = "rd-failure-rejected"
    plan_id = "rd-failure-rejected-plan"
    approval_1 = "approval-rd-rejected-1"
    approval_2 = "approval-rd-rejected-2"
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, status="COMPLETED", event_seq=12),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                approval_id=approval_1,
                created_at=created_at,
                status="APPROVED",
                decided_at=created_at + timedelta(seconds=2),
                created_offset_s=1,
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-rejected-success-step",
                step_index=0,
                created_at=created_at + timedelta(seconds=3),
                approval_id=approval_1,
                status="DONE",
                result={"approval_id": approval_1, "data": {"job_id": "JOB-RD-REJECTED-OK", "priority": "high"}},
            ),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                approval_id=approval_2,
                created_at=created_at,
                status="REJECTED",
                decided_at=created_at + timedelta(seconds=4),
                rejection_reason="Operator rejected the second change.",
                rows=[{"job_id": "JOB-RD-REJECTED-NOT-CHANGED", "new_priority": "low"}],
                created_offset_s=4,
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    diagnostic = _diagnostic(document)

    assert document["state"] == "rejected"
    assert diagnostic["reason"] == "approval_rejected"
    assert diagnostic["retry_safety"]["safe_to_retry"] is False
    assert "success" not in document["message"].lower()
    assert any(block["id"] == f"completed-step:{approval_1}" for block in document["blocks"])
    assert not any(block["type"] == "approval_required" for block in document["blocks"])
    assert approval_2 in diagnostic["impact"]["incomplete_steps"][0]


@pytest.mark.asyncio
async def test_expired_and_stale_approvals_do_not_render_active_actions(db_session):
    created_at = datetime(2026, 5, 18, 10, 30, 0)
    expired_session = "rd-failure-expired"
    expired_plan = "rd-failure-expired-plan"
    stale_session = "rd-failure-stale"
    stale_plan = "rd-failure-stale-plan"
    stale_approval_id = "approval-rd-stale"
    db_session.add_all(
        [
            _session(
                session_id=expired_session,
                plan_id=expired_plan,
                created_at=created_at,
                status="WAITING_APPROVAL",
                event_seq=13,
            ),
            _user_message(session_id=expired_session, created_at=created_at),
            _plan(session_id=expired_session, plan_id=expired_plan, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=expired_session,
                plan_id=expired_plan,
                approval_id="approval-rd-expired-failure",
                created_at=created_at,
                status="EXPIRED",
                decided_at=created_at + timedelta(seconds=3),
                rejection_reason="Approval expired before it was approved",
            ),
            _session(
                session_id=stale_session,
                plan_id=stale_plan,
                created_at=created_at,
                status="WAITING_APPROVAL",
                event_seq=14,
            ),
            _user_message(session_id=stale_session, created_at=created_at),
            _plan(session_id=stale_session, plan_id=stale_plan, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=stale_session,
                plan_id=stale_plan,
                approval_id=stale_approval_id,
                created_at=created_at,
                status="EXPIRED",
                decided_at=created_at + timedelta(seconds=3),
                rejection_reason="Approval is stale because the session changed state",
            ),
        ]
    )
    await db_session.commit()

    expired = (await _snapshot(db_session, expired_session))["response_document"]
    stale = (await _snapshot(db_session, stale_session))["response_document"]
    stale_row = await db_session.get(Approval, stale_approval_id)

    assert _diagnostic(expired)["reason"] == "approval_expired"
    assert _diagnostic(stale)["reason"] == "approval_stale"
    assert stale_row is not None
    assert stale_row.status == "EXPIRED"
    assert not any(block["type"] == "approval_required" for block in expired["blocks"])
    assert not any(block["type"] == "approval_required" for block in stale["blocks"])
    assert _diagnostic(stale)["retry_safety"]["safe_to_retry"] is False


@pytest.mark.asyncio
async def test_cancelled_run_uses_cancelled_state_and_operator_text(db_session):
    created_at = datetime(2026, 5, 18, 11, 0, 0)
    session_id = "rd-failure-cancelled"
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                created_at=created_at,
                status="IDLE",
                event_seq=15,
                step_count=0,
                error="Cancelled by user message",
            ),
            _user_message(session_id=session_id, created_at=created_at),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    diagnostic = _diagnostic(document)

    assert document["state"] == "cancelled"
    assert diagnostic["reason"] == "cancelled_by_user"
    assert document["message"] == "The run was cancelled. I stopped work and did not continue pending actions."
    assert any(step["kind"] == "cancelled" and step["state"] == "cancelled" for step in document["run_steps"])
    _assert_failure_fields(diagnostic)


@pytest.mark.asyncio
async def test_malformed_response_payload_becomes_sanitized_diagnostic(db_session):
    created_at = datetime(2026, 5, 18, 11, 30, 0)
    session_id = "rd-failure-malformed"
    plan_id = "rd-failure-malformed-plan"
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                status="FAILED",
                event_seq=16,
                error="Malformed response payload from backend.",
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-malformed-step",
                step_index=0,
                created_at=created_at + timedelta(seconds=2),
                approval_id=None,
                status="FAILED",
                result={"error": "invalid response payload", "token": "raw-secret-token"},
                last_error="Malformed response payload: expected object; token=raw-secret-token",
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    diagnostic = _diagnostic(document)

    assert diagnostic["reason"] == "malformed_response_payload"
    assert diagnostic["retry_safety"]["safe_to_retry"] is False
    _assert_failure_fields(diagnostic)
    serialized = json.dumps(document).lower()
    assert "raw-secret-token" not in serialized


@pytest.mark.asyncio
async def test_empty_final_response_becomes_no_results_diagnostic_not_fake_success(db_session):
    created_at = datetime(2026, 5, 18, 12, 0, 0)
    session_id = "rd-failure-empty-final"
    plan_id = "rd-failure-empty-final-plan"
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, status="COMPLETED", event_seq=17),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(session_id=session_id, content="", created_at=created_at + timedelta(seconds=2)),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    diagnostic = _diagnostic(document)

    assert document["state"] == "failed"
    assert diagnostic["reason"] == "no_results"
    assert diagnostic["title"] == "No results"
    assert "success" not in document["message"].lower()
    assert not any(block["type"] in {"result_summary", "mutation_result"} for block in document["blocks"])
    _assert_failure_fields(diagnostic)
