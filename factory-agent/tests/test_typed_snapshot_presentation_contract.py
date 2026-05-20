from __future__ import annotations

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


async def _snapshot(db_session, session_id: str):
    settings = _settings()
    service = SessionSnapshotService(
        session_mgr=SessionManager(settings),
        memory_manager=MemoryManager(settings),
        tool_registry=ToolRegistry(),
    )
    snapshot = await service.load_session_snapshot(db=db_session, session_id=session_id)
    assert snapshot is not None
    return snapshot.model_dump(mode="json")


def _session(
    *,
    session_id: str,
    status: str,
    plan_id: str | None,
    created_at: datetime,
    error: str | None = None,
) -> Session:
    return Session(
        session_id=session_id,
        user_id="u1",
        status=status,
        current_intent=f"typed presentation contract for {session_id}",
        plan_id=plan_id,
        plan_version=1 if plan_id else 0,
        plan_hash=f"{session_id}-hash" if plan_id else None,
        current_step_index=0,
        step_count=1 if plan_id else 0,
        llm_call_count=0,
        session_started_at=created_at,
        created_at=created_at,
        updated_at=created_at + timedelta(seconds=3),
        completed_at=created_at + timedelta(seconds=3) if status == "COMPLETED" else None,
        error=error,
    )


def _plan(
    *,
    session_id: str,
    plan_id: str,
    created_at: datetime,
    status: str = "COMPLETED",
    sources: list[dict[str, Any]] | None = None,
) -> Plan:
    return Plan(
        plan_id=plan_id,
        session_id=session_id,
        version=1,
        kind="execution",
        status=status,
        dependency_graph={"0": []},
        parallel_groups=[],
        plan_hash=f"{plan_id}-hash",
        plan_explanation="Structured plan evidence.",
        risk_summary="Structured risk evidence.",
        created_at=created_at,
        created_by="test",
        sources=sources or [],
    )


def _user_message(*, session_id: str, created_at: datetime) -> Message:
    return Message(
        message_id=f"{session_id}-user",
        session_id=session_id,
        role="user",
        content=f"Run typed presentation case {session_id}",
        created_at=created_at,
    )


def _assistant_message(
    *,
    session_id: str,
    content: str,
    created_at: datetime,
    tool_name: str | None = "__plan__",
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
    args: dict[str, Any],
    decided_at: datetime | None = None,
    rejection_reason: str | None = None,
    expires_at: datetime | None = None,
) -> Approval:
    return Approval(
        approval_id=approval_id,
        session_id=session_id,
        subject_type="graph",
        plan_id=plan_id,
        tool_name="__langgraph_commit__",
        args=args,
        risk_summary=args.get("risk_summary") or "Structured approval evidence.",
        side_effect_level="HIGH",
        status=status,
        expires_at=expires_at or datetime(2099, 1, 1, 0, 0, 0),
        decided_at=decided_at,
        decided_by="operator" if decided_at else None,
        rejection_reason=rejection_reason,
        created_at=created_at,
    )


def _write_step(
    *,
    session_id: str,
    plan_id: str,
    step_id: str,
    created_at: datetime,
    status: str,
    approval_id: str,
    result: dict[str, Any],
    last_error: str | None = None,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        plan_id=plan_id,
        session_id=session_id,
        step_index=0,
        tool_name="put__jobs_{id}",
        args={"id": "JOB-TYPED-001", "priority": "high", "approval_id": approval_id},
        bindings=[],
        status=status,
        idempotency_key=f"{step_id}-idempotency",
        requires_approval=True,
        approval_id=approval_id,
        retry_count=0,
        max_retries=3,
        completed_at=created_at,
        last_error=last_error,
        result=result,
        result_summary=str(result.get("summary") or ""),
    )


@pytest.mark.asyncio
async def test_pending_approval_presentation_is_typed_before_approval_wait_text(db_session):
    created_at = datetime(2026, 5, 17, 9, 0, 0)
    session_id = "typed-pending-approval"
    plan_id = "typed-pending-plan"
    db_session.add_all(
        [
            _session(session_id=session_id, status="COMPLETED", plan_id=plan_id, created_at=created_at),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content="All requested changes completed. This stale text must not win.",
                created_at=created_at + timedelta(seconds=2),
                step_id=plan_id,
            ),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                approval_id="approval-typed-pending",
                created_at=created_at + timedelta(seconds=3),
                status="PENDING",
                args={
                    "risk_summary": "One row requires operator decision.",
                    "bundle_ui": {
                        "rows": [{"job_id": "JOB-TYPED-001", "new_priority": "high"}],
                        "write_set": "pending_write_set",
                    },
                },
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["session"]["status"] == "WAITING_APPROVAL"
    assert body["presentation"]["kind"] == "approval_required"
    assert body["presentation"]["state"] == "pending"
    assert body["presentation"]["approval_id"] == "approval-typed-pending"
    assert body["presentation"]["rows"][0]["status"] == "pending"
    assert body["presentation"]["invariants"]["full_success_forbidden"] is True
    assert "please approve" not in body["presentation"]["summary"].lower()


@pytest.mark.asyncio
async def test_rejected_approval_presentation_cannot_be_overridden_by_stale_success_text(db_session):
    created_at = datetime(2026, 5, 17, 10, 0, 0)
    session_id = "typed-rejected"
    plan_id = "typed-rejected-plan"
    db_session.add_all(
        [
            _session(session_id=session_id, status="COMPLETED", plan_id=plan_id, created_at=created_at),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content="**Success**\n\nAll requested changes completed.",
                created_at=created_at + timedelta(seconds=2),
                step_id=plan_id,
            ),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                approval_id="approval-typed-rejected",
                created_at=created_at + timedelta(seconds=1),
                status="REJECTED",
                args={"bundle_ui": {"rows": [{"job_id": "JOB-TYPED-002", "new_priority": "medium"}]}},
                decided_at=created_at + timedelta(seconds=3),
                rejection_reason="Operator rejected the requested mutation.",
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["presentation"]["kind"] == "rejected"
    assert body["presentation"]["state"] == "rejected"
    assert body["presentation"]["approval_id"] == "approval-typed-rejected"
    assert body["presentation"]["invariants"]["full_success_forbidden"] is True
    terminal = [event for event in body["timeline"] if event["event_type"] == "session_completed"][-1]
    assert terminal["presentation"]["state"] == "rejected"


@pytest.mark.asyncio
async def test_expired_pending_approval_is_typed_as_expired_safe_failure(db_session):
    created_at = datetime(2026, 5, 17, 11, 0, 0)
    session_id = "typed-expired"
    plan_id = "typed-expired-plan"
    db_session.add_all(
        [
            _session(session_id=session_id, status="WAITING_APPROVAL", plan_id=plan_id, created_at=created_at),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                approval_id="approval-typed-expired",
                created_at=created_at + timedelta(seconds=2),
                status="PENDING",
                args={"bundle_ui": {"rows": [{"job_id": "JOB-TYPED-003", "new_priority": "urgent"}]}},
                expires_at=created_at - timedelta(seconds=1),
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["presentation"]["kind"] == "expired"
    assert body["presentation"]["state"] == "expired"
    assert body["presentation"]["approval_id"] == "approval-typed-expired"
    assert body["presentation"]["rows"][0]["status"] == "expired"
    assert body["presentation"]["diagnostics"]["reason"] == "approval_expired"


@pytest.mark.asyncio
async def test_partial_failure_presentation_includes_per_row_evidence(db_session):
    created_at = datetime(2026, 5, 17, 12, 0, 0)
    session_id = "typed-partial"
    plan_id = "typed-partial-plan"
    approval_id = "approval-typed-partial"
    db_session.add_all(
        [
            _session(session_id=session_id, status="FAILED", plan_id=plan_id, created_at=created_at, error="Partial commit failure."),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                approval_id=approval_id,
                created_at=created_at + timedelta(seconds=1),
                status="APPROVED",
                args={},
                decided_at=created_at + timedelta(seconds=2),
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="typed-partial-step",
                created_at=created_at + timedelta(seconds=3),
                status="FAILED",
                approval_id=approval_id,
                result={
                    "approval_id": approval_id,
                    "outcomes": [
                        {"job_id": "JOB-TYPED-004", "status": "succeeded"},
                        {"job_id": "JOB-TYPED-005", "status": "failed", "error": "version_conflict"},
                    ],
                    "summary": "One row succeeded and one row failed.",
                },
                last_error="version_conflict",
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["presentation"]["kind"] == "partial_failure"
    assert body["presentation"]["state"] == "failed"
    assert body["presentation"]["approval_id"] == approval_id
    assert {row["row_id"]: row["status"] for row in body["presentation"]["rows"]} == {
        "JOB-TYPED-004": "succeeded",
        "JOB-TYPED-005": "failed",
    }
    assert body["presentation"]["invariants"]["has_partial_failure_rows"] is True


@pytest.mark.asyncio
async def test_successful_multi_approval_mutation_presentation_has_operation_approval_and_rows(db_session):
    created_at = datetime(2026, 5, 17, 13, 0, 0)
    session_id = "typed-success-mutation"
    plan_id = "typed-success-plan"
    db_session.add_all(
        [
            _session(session_id=session_id, status="COMPLETED", plan_id=plan_id, created_at=created_at),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                approval_id="approval-typed-success-1",
                created_at=created_at + timedelta(seconds=1),
                status="APPROVED",
                args={},
                decided_at=created_at + timedelta(seconds=2),
            ),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                approval_id="approval-typed-success-2",
                created_at=created_at + timedelta(seconds=3),
                status="APPROVED",
                args={},
                decided_at=created_at + timedelta(seconds=4),
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="typed-success-step-1",
                created_at=created_at + timedelta(seconds=2),
                status="DONE",
                approval_id="approval-typed-success-1",
                result={"approval_id": "approval-typed-success-1", "data": {"job_id": "JOB-TYPED-006", "priority": "high"}},
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="typed-success-step-2",
                created_at=created_at + timedelta(seconds=4),
                status="DONE",
                approval_id="approval-typed-success-2",
                result={"approval_id": "approval-typed-success-2", "data": {"job_id": "JOB-TYPED-007", "priority": "low"}},
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["presentation"]["kind"] == "mutation_result"
    assert body["presentation"]["state"] == "completed"
    assert body["presentation"]["operation_id"] == plan_id
    assert body["presentation"]["approval_id"] == "approval-typed-success-1"
    assert {row["approval_id"] for row in body["presentation"]["rows"]} == {
        "approval-typed-success-1",
        "approval-typed-success-2",
    }
    assert {row["row_id"] for row in body["presentation"]["rows"]} == {"JOB-TYPED-006", "JOB-TYPED-007"}


@pytest.mark.asyncio
async def test_cancelled_session_presentation_is_cancelled(db_session):
    created_at = datetime(2026, 5, 17, 14, 0, 0)
    session_id = "typed-cancelled"
    db_session.add_all(
        [
            _session(session_id=session_id, status="IDLE", plan_id=None, created_at=created_at, error="Cancelled"),
            _user_message(session_id=session_id, created_at=created_at),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["presentation"]["kind"] == "cancelled"
    assert body["presentation"]["state"] == "cancelled"
    assert body["presentation"]["diagnostics"]["reason"] == "cancelled_by_user"


@pytest.mark.asyncio
async def test_knowledge_answer_presentation_contains_typed_sources(db_session):
    created_at = datetime(2026, 5, 17, 15, 0, 0)
    session_id = "typed-knowledge"
    plan_id = "typed-knowledge-plan"
    source = {"machine_id": "M-CNC-01", "procedure_id": "LOTO-M-CNC-01", "title": "LOTO procedure"}
    db_session.add_all(
        [
            _session(session_id=session_id, status="COMPLETED", plan_id=plan_id, created_at=created_at),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at + timedelta(seconds=1),
                sources=[source],
            ),
            _assistant_message(
                session_id=session_id,
                content="Controlled source-backed LOTO answer.",
                created_at=created_at + timedelta(seconds=2),
                tool_name="__conversation__",
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["presentation"]["kind"] == "knowledge_answer"
    assert body["presentation"]["state"] == "completed"
    assert body["presentation"]["sources"][0]["procedure_id"] == "LOTO-M-CNC-01"
    assert body["presentation"]["invariants"]["has_sources"] is True


@pytest.mark.asyncio
async def test_empty_final_response_presentation_is_diagnostic_not_fake_success(db_session):
    created_at = datetime(2026, 5, 17, 16, 0, 0)
    session_id = "typed-empty-final"
    plan_id = "typed-empty-plan"
    db_session.add_all(
        [
            _session(session_id=session_id, status="COMPLETED", plan_id=plan_id, created_at=created_at),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1), sources=[]),
            _assistant_message(
                session_id=session_id,
                content="",
                created_at=created_at + timedelta(seconds=2),
                tool_name="__conversation__",
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["presentation"]["kind"] == "diagnostic"
    assert body["presentation"]["state"] == "failed"
    assert body["presentation"]["diagnostics"]["reason"] == "empty_final_response"
    assert body["presentation"]["invariants"]["has_empty_final_response"] is True


@pytest.mark.asyncio
async def test_failed_session_presentation_uses_structured_failure_over_stale_success_text(db_session):
    created_at = datetime(2026, 5, 17, 17, 0, 0)
    session_id = "typed-failed-stale-success"
    plan_id = "typed-failed-plan"
    db_session.add_all(
        [
            _session(session_id=session_id, status="FAILED", plan_id=plan_id, created_at=created_at, error="HTTP 500: database unavailable"),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content="**Success**\n\nUpdated **1** job(s).",
                created_at=created_at + timedelta(seconds=2),
                step_id=plan_id,
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="typed-failed-step",
                created_at=created_at + timedelta(seconds=3),
                status="FAILED",
                approval_id="approval-typed-failed",
                result={"approval_id": "approval-typed-failed", "error": "database unavailable"},
                last_error="HTTP 500: database unavailable",
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["presentation"]["kind"] == "diagnostic"
    assert body["presentation"]["state"] == "failed"
    assert body["presentation"]["summary"] == "HTTP 500: database unavailable"
    assert body["presentation"]["invariants"]["full_success_forbidden"] is True
