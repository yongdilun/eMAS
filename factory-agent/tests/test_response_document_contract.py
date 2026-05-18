from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from factory_agent.config import Settings
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.models import Approval, Message, Plan, PlanStep, Session
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import ResponseDocument
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
    plan_id: str,
    created_at: datetime,
    event_seq: int,
    status: str = "WAITING_APPROVAL",
    step_count: int = 1,
    current_intent: str | None = None,
    completed_at: datetime | None = None,
    error: str | None = None,
) -> Session:
    return Session(
        session_id=session_id,
        user_id="u1",
        status=status,
        current_intent=current_intent or f"response document contract for {session_id}",
        plan_id=plan_id,
        plan_version=1,
        plan_hash=f"{plan_id}-hash",
        current_step_index=0,
        step_count=step_count,
        llm_call_count=0,
        event_seq=event_seq,
        session_started_at=created_at,
        created_at=created_at,
        updated_at=created_at + timedelta(seconds=3),
        completed_at=completed_at if completed_at is not None else (created_at + timedelta(seconds=3) if status == "COMPLETED" else None),
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
        plan_explanation="Stage the requested change.",
        risk_summary="High-risk write requires approval.",
        created_at=created_at,
        created_by="test",
    )


def _user_message(*, session_id: str, created_at: datetime) -> Message:
    return Message(
        message_id=f"{session_id}-user",
        session_id=session_id,
        role="user",
        content="Change one job priority",
        created_at=created_at,
    )


def _assistant_message(
    *,
    session_id: str,
    content: str,
    created_at: datetime,
    step_id: str | None = None,
    tool_name: str | None = "__plan__",
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
    created_at: datetime,
    approval_id: str = "approval-rd-1",
    status: str = "PENDING",
    args: dict[str, Any] | None = None,
    risk_summary: str | None = None,
    decided_at: datetime | None = None,
    created_offset_s: int = 2,
) -> Approval:
    payload = args or {
        "risk_summary": "One job will be changed from medium to high priority.",
        "bundle_ui": {
            "rows": [{"job_id": "JOB-RD-001", "from_priority": "medium", "new_priority": "high"}],
            "write_set": "rd-write-set",
        },
    }
    return Approval(
        approval_id=approval_id,
        session_id=session_id,
        subject_type="graph",
        plan_id=plan_id,
        tool_name="__langgraph_commit__",
        args=payload,
        risk_summary=risk_summary or str(payload.get("risk_summary") or payload.get("summary") or "One job will be changed from medium to high priority."),
        side_effect_level="HIGH",
        status=status,
        expires_at=created_at + timedelta(hours=1),
        decided_at=decided_at,
        decided_by="operator" if decided_at else None,
        created_at=created_at + timedelta(seconds=created_offset_s),
    )


def _write_step(
    *,
    session_id: str,
    plan_id: str,
    step_id: str,
    step_index: int,
    completed_at: datetime,
    approval_id: str,
    outcomes: list[dict[str, Any]],
    status: str = "DONE",
) -> PlanStep:
    target_priority = str((outcomes[0] if outcomes else {}).get("priority") or (outcomes[0] if outcomes else {}).get("new_priority") or "high")
    return PlanStep(
        step_id=step_id,
        plan_id=plan_id,
        session_id=session_id,
        step_index=step_index,
        tool_name="put__jobs_{id}",
        args={"write_set": f"write-set-{approval_id}", "priority": target_priority},
        bindings=[],
        status=status,
        idempotency_key=f"{step_id}-key",
        requires_approval=True,
        approval_id=approval_id,
        retry_count=0,
        max_retries=0,
        completed_at=completed_at,
        result={"success": True, "approval_id": approval_id, "outcomes": outcomes},
        result_summary=f"{len(outcomes)} rows updated.",
    )


def _read_step(
    *,
    session_id: str,
    plan_id: str,
    step_id: str,
    completed_at: datetime,
    rows: list[dict[str, Any]],
    summary: str,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        plan_id=plan_id,
        session_id=session_id,
        step_index=0,
        tool_name="get__jobs",
        args={"fields": "job_id,priority,status"},
        bindings=[],
        status="DONE",
        idempotency_key=f"{step_id}-key",
        requires_approval=False,
        retry_count=0,
        max_retries=0,
        completed_at=completed_at,
        result={"success": True, "data": rows},
        result_summary=summary,
    )


def _cascade_args(
    *,
    approval_number: int,
    source: str,
    target: str,
    job_ids: list[str],
    previous_approval_id: str | None = None,
) -> dict[str, Any]:
    bundle_ui: dict[str, Any] = {
        "kind": "phase14_cascade_priority",
        "write_set": f"original_{source}_to_{target}",
        "headline": f"Approval {approval_number} required: original {source.upper()}-priority jobs will become {target.upper()}.",
        "rows": [{"job_id": job_id, "original_priority": source, "new_priority": target} for job_id in job_ids],
        "original_state_semantics": "Original priority groups are evaluated before any approved writes are applied.",
    }
    if previous_approval_id:
        bundle_ui["previous_approval_id"] = previous_approval_id
    return {
        "summary": f"Change {len(job_ids)} original {source}-priority jobs to {target}.",
        "count": len(job_ids),
        "bundle_ui": bundle_ui,
    }


def test_response_document_schema_validates_phase_1_block_types():
    document = ResponseDocument.model_validate(
        {
            "id": "rd:session-1:turn-1",
            "document_id": "rd:session-1:turn-1",
            "turn_id": "turn-1",
            "operation_id": "op-1",
            "revision": 7,
            "revision_source": "event_seq",
            "state": "waiting_approval",
            "status": "waiting_approval",
            "summary": "Waiting for approval.",
            "message": "Waiting for approval.",
            "current_step_id": "approval-step",
            "run_steps": [
                {
                    "step_id": "approval-step",
                    "kind": "approval",
                    "state": "waiting",
                    "title": "Waiting for approval",
                    "summary": "Review the write set.",
                    "approval_id": "approval-1",
                    "operation_id": "op-1",
                    "record_count": 1,
                    "current": True,
                }
            ],
            "blocks": [
                {"id": "activity:rd:session-1:turn-1", "type": "run_activity", "step_ids": ["approval-step"]},
                {
                    "id": "message:approval-1:waiting_approval",
                    "type": "short_message",
                    "message": "Waiting for approval.",
                    "status": "waiting_approval",
                },
                {
                    "id": "approval:approval-1",
                    "type": "approval_required",
                    "approval_id": "approval-1",
                    "operation_id": "op-1",
                    "summary": "Review one staged write.",
                    "rows": [{"row_id": "JOB-RD-001"}],
                },
                {
                    "id": "mutation:op-1",
                    "type": "mutation_result",
                    "operation_id": "op-1",
                    "approval_id": "approval-1",
                    "summary": "Updated one job.",
                    "rows": [{"row_id": "JOB-RD-001", "status": "succeeded"}],
                },
                {
                    "id": "table:op-1:affected-records",
                    "type": "result_table",
                    "operation_id": "op-1",
                    "approval_id": "approval-1",
                    "rows": [{"row_id": "JOB-RD-001", "status": "succeeded"}],
                },
                {
                    "id": "knowledge:op-1",
                    "type": "knowledge_answer",
                    "operation_id": "op-1",
                    "answer": "Use the controlled LOTO procedure.",
                },
                {
                    "id": "sources:op-1",
                    "type": "source_list",
                    "operation_id": "op-1",
                    "sources": [{"procedure_id": "LOTO-M-CNC-01"}],
                },
                {
                    "id": "diagnostic:op-1:planner_timeout",
                    "type": "diagnostic",
                    "severity": "error",
                    "reason": "planner_timeout",
                    "user_message": "The run was interrupted before it could continue.",
                    "technical_details": {"trace_id": "trace-1"},
                },
            ],
            "invariants": {"full_success_forbidden": True},
            "diagnostics": {"reason": "approval_pending"},
        }
    )

    assert document.version == 1
    assert document.id == "rd:session-1:turn-1"
    assert {block.type for block in document.blocks} == {
        "run_activity",
        "short_message",
        "approval_required",
        "mutation_result",
        "result_table",
        "knowledge_answer",
        "source_list",
        "diagnostic",
    }


def test_response_document_schema_rejects_missing_required_fields():
    with pytest.raises(ValidationError):
        ResponseDocument.model_validate(
            {
                "document_id": "rd:missing-id",
                "revision": 1,
                "revision_source": "event_seq",
                "state": "completed",
                "status": "completed",
            }
        )

    with pytest.raises(ValidationError):
        ResponseDocument.model_validate(
            {
                "id": "rd:bad-block",
                "document_id": "rd:bad-block",
                "revision": 1,
                "revision_source": "event_seq",
                "state": "waiting_approval",
                "status": "waiting_approval",
                "blocks": [{"id": "approval:missing-fields", "type": "approval_required"}],
            }
        )


@pytest.mark.asyncio
async def test_snapshot_includes_additive_response_document_without_changing_presentation(db_session):
    created_at = datetime(2026, 5, 18, 9, 0, 0)
    session_id = "rd-pending-snapshot"
    plan_id = "rd-pending-plan"
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=4),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(session_id=session_id, plan_id=plan_id, created_at=created_at),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)

    assert body["presentation"]["kind"] == "approval_required"
    assert body["presentation"]["state"] == "pending"
    document = body["response_document"]
    assert document["version"] == 1
    assert document["id"].startswith(f"rd:{session_id}:")
    assert document["revision"] == 4
    assert document["revision_source"] == "event_seq"
    assert document["state"] == "waiting_approval"
    assert document["status"] == "waiting_approval"
    assert document["summary"] == body["presentation"]["summary"]
    assert document["diagnostics"]["reason"] == "approval_pending"
    assert {block["type"] for block in document["blocks"]} >= {
        "run_activity",
        "short_message",
        "approval_required",
        "result_table",
    }
    waiting_steps = [
        step
        for step in document["run_steps"]
        if step["kind"] == "approval" and step["state"] == "waiting"
    ]
    assert len(waiting_steps) == 1
    assert waiting_steps[0]["approval_id"] == "approval-rd-1"
    assert waiting_steps[0]["current"] is True
    assert document["current_step_id"] == waiting_steps[0]["step_id"]
    assert any(step["kind"] == "read" and step["record_count"] == 1 for step in document["run_steps"])


@pytest.mark.asyncio
async def test_response_document_reports_approval_received_before_mutation_result(db_session):
    created_at = datetime(2026, 5, 18, 11, 0, 0)
    session_id = "rd-approval-received"
    plan_id = "rd-approval-received-plan"
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=9,
                status="EXECUTING",
                current_intent="change one medium priority job to high",
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id="approval-rd-received",
                status="APPROVED",
                decided_at=created_at + timedelta(seconds=3),
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert document["state"] == "running"
    assert document["message"] == "Approval received. I'm applying the approved change now."
    assert any(
        step["step_id"] == "approval:approval-rd-received"
        and step["state"] == "completed"
        for step in document["run_steps"]
    )
    applying_steps = [
        step
        for step in document["run_steps"]
        if step["step_id"] == "mutation:approval-rd-received"
    ]
    assert applying_steps[0]["state"] == "current"
    assert applying_steps[0]["current"] is True
    assert "approval_required" not in {block["type"] for block in document["blocks"]}


@pytest.mark.asyncio
async def test_two_step_approval_document_preserves_completed_mutation_during_second_pending(db_session):
    created_at = datetime(2026, 5, 18, 12, 0, 0)
    session_id = "rd-two-step-pending"
    plan_id = "rd-two-step-plan"
    approval_1 = "approval-rd-two-step-1"
    approval_2 = "approval-rd-two-step-2"
    first_rows = [
        {"job_id": "JOB-RD-MED-001", "original_priority": "medium", "priority": "high"},
        {"job_id": "JOB-RD-MED-002", "original_priority": "medium", "priority": "high"},
    ]
    second_ids = ["JOB-RD-HIGH-001", "JOB-RD-HIGH-002", "JOB-RD-HIGH-003"]
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=18,
                step_count=2,
                current_intent="change all medium priority job to high then change all high priority job to low",
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id=approval_1,
                status="APPROVED",
                args=_cascade_args(approval_number=1, source="medium", target="high", job_ids=[row["job_id"] for row in first_rows]),
                decided_at=created_at + timedelta(seconds=3),
                created_offset_s=2,
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-two-step-write-1",
                step_index=0,
                completed_at=created_at + timedelta(seconds=4),
                approval_id=approval_1,
                outcomes=first_rows,
            ),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id=approval_2,
                status="PENDING",
                args=_cascade_args(
                    approval_number=2,
                    source="high",
                    target="low",
                    job_ids=second_ids,
                    previous_approval_id=approval_1,
                ),
                created_offset_s=5,
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert document["state"] == "waiting_approval"
    assert document["invariants"]["latest_pending_approval_id"] == approval_2
    assert document["invariants"]["completed_approval_ids"] == [approval_1]
    assert any(
        step["step_id"] == f"approval:{approval_1}" and step["state"] == "completed"
        for step in document["run_steps"]
    )
    assert any(
        step["step_id"] == f"mutation:{approval_1}" and step["state"] == "completed"
        for step in document["run_steps"]
    )
    assert any(
        step["step_id"] == f"approval:{approval_2}" and step["state"] == "waiting" and step["current"]
        for step in document["run_steps"]
    )
    block_ids = [block["id"] for block in document["blocks"]]
    assert block_ids.index(f"completed-step:{approval_1}") < block_ids.index(f"approval:{approval_2}")
    completed = next(block for block in document["blocks"] if block["id"] == f"completed-step:{approval_1}")
    assert {row["row_id"] for row in completed["rows"]} == {"JOB-RD-MED-001", "JOB-RD-MED-002"}
    assert "Run complete" not in document["message"]
    assert "Updated 5 jobs across 2 approved steps" not in document["message"]


@pytest.mark.asyncio
async def test_final_completed_mutation_document_aggregates_all_approved_changes(db_session):
    created_at = datetime(2026, 5, 18, 13, 0, 0)
    session_id = "rd-two-step-completed"
    plan_id = "rd-two-step-completed-plan"
    approval_1 = "approval-rd-completed-1"
    approval_2 = "approval-rd-completed-2"
    first_rows = [
        {"job_id": "JOB-RD-MED-001", "original_priority": "medium", "priority": "high"},
        {"job_id": "JOB-RD-MED-002", "original_priority": "medium", "priority": "high"},
    ]
    second_rows = [
        {"job_id": "JOB-RD-HIGH-001", "original_priority": "high", "priority": "low"},
        {"job_id": "JOB-RD-HIGH-002", "original_priority": "high", "priority": "low"},
        {"job_id": "JOB-RD-HIGH-003", "original_priority": "high", "priority": "low"},
    ]
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=24,
                status="COMPLETED",
                step_count=2,
                current_intent="change all medium priority job to high then change all high priority job to low",
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id=approval_1,
                status="APPROVED",
                args=_cascade_args(approval_number=1, source="medium", target="high", job_ids=[row["job_id"] for row in first_rows]),
                decided_at=created_at + timedelta(seconds=3),
                created_offset_s=2,
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-completed-write-1",
                step_index=0,
                completed_at=created_at + timedelta(seconds=4),
                approval_id=approval_1,
                outcomes=first_rows,
            ),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id=approval_2,
                status="APPROVED",
                args=_cascade_args(
                    approval_number=2,
                    source="high",
                    target="low",
                    job_ids=[row["job_id"] for row in second_rows],
                    previous_approval_id=approval_1,
                ),
                decided_at=created_at + timedelta(seconds=6),
                created_offset_s=5,
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-completed-write-2",
                step_index=1,
                completed_at=created_at + timedelta(seconds=7),
                approval_id=approval_2,
                outcomes=second_rows,
            ),
            _assistant_message(
                session_id=session_id,
                content="Execution completed successfully.",
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=8),
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert document["state"] == "completed"
    assert document["message"] == "Updated 5 jobs across 2 approved steps."
    result_summary = next(block for block in document["blocks"] if block["type"] == "result_summary")
    assert result_summary["total_count"] == 5
    assert [step["approval_id"] for step in result_summary["steps"]] == [approval_1, approval_2]
    mutation = next(block for block in document["blocks"] if block["type"] == "mutation_result")
    assert {row["row_id"] for row in mutation["rows"]} == {
        "JOB-RD-MED-001",
        "JOB-RD-MED-002",
        "JOB-RD-HIGH-001",
        "JOB-RD-HIGH-002",
        "JOB-RD-HIGH-003",
    }
    assert document["invariants"]["completed_approval_ids"] == [approval_1, approval_2]
    assert not any(step["state"] == "waiting" for step in document["run_steps"])


@pytest.mark.asyncio
async def test_read_only_result_shape_is_deterministic_for_table_and_list(db_session):
    created_at = datetime(2026, 5, 18, 14, 0, 0)
    table_session = "rd-read-table"
    table_plan = "rd-read-table-plan"
    list_session = "rd-read-list"
    list_plan = "rd-read-list-plan"
    db_session.add_all(
        [
            _session(session_id=table_session, plan_id=table_plan, created_at=created_at, event_seq=6, status="COMPLETED"),
            _user_message(session_id=table_session, created_at=created_at),
            _plan(session_id=table_session, plan_id=table_plan, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=table_session,
                plan_id=table_plan,
                step_id="rd-read-table-step",
                completed_at=created_at + timedelta(seconds=2),
                rows=[
                    {"job_id": "JOB-RD-READ-001", "priority": "low", "status": "planned"},
                    {"job_id": "JOB-RD-READ-002", "priority": "low", "status": "queued"},
                    {"job_id": "JOB-RD-READ-003", "priority": "low", "status": "queued"},
                    {"job_id": "JOB-RD-READ-004", "priority": "low", "status": "queued"},
                    {"job_id": "JOB-RD-READ-005", "priority": "low", "status": "queued"},
                    {"job_id": "JOB-RD-READ-006", "priority": "low", "status": "queued"},
                ],
                summary="Found 6 low-priority jobs.",
            ),
            _assistant_message(session_id=table_session, content="Found 6 low-priority jobs.", step_id=table_plan, created_at=created_at + timedelta(seconds=3)),
            _session(session_id=list_session, plan_id=list_plan, created_at=created_at, event_seq=6, status="COMPLETED"),
            _user_message(session_id=list_session, created_at=created_at),
            _plan(session_id=list_session, plan_id=list_plan, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=list_session,
                plan_id=list_plan,
                step_id="rd-read-list-step",
                completed_at=created_at + timedelta(seconds=2),
                rows=[{"job_id": "JOB-RD-READ-003", "priority": "medium", "status": "planned"}],
                summary="Found 1 matching job.",
            ),
            _assistant_message(session_id=list_session, content="Found 1 matching job.", step_id=list_plan, created_at=created_at + timedelta(seconds=3)),
        ]
    )
    await db_session.commit()

    table_body = await _snapshot(db_session, table_session)
    list_body = await _snapshot(db_session, list_session)

    assert table_body["response_document"]["invariants"]["read_result_shape"] == "table"
    assert any(block["type"] == "result_table" and block["title"] == "Results" for block in table_body["response_document"]["blocks"])
    assert list_body["response_document"]["invariants"]["read_result_shape"] == "list"
    assert any(block["type"] == "record_preview" and block["title"] == "Results" for block in list_body["response_document"]["blocks"])
    assert not any(block["type"] == "approval_required" for block in table_body["response_document"]["blocks"])


@pytest.mark.asyncio
async def test_rag_response_document_includes_knowledge_answer_and_source_blocks(db_session):
    created_at = datetime(2026, 5, 18, 15, 0, 0)
    session_id = "rd-rag-sources"
    plan_id = "rd-rag-plan"
    source = {"machine_id": "M-CNC-01", "procedure_id": "LOTO-M-CNC-01", "title": "LOTO procedure"}
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=7, status="COMPLETED"),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content="Use the controlled LOTO procedure before working on M-CNC-01.",
                step_id=plan_id,
                tool_name="__conversation__",
                created_at=created_at + timedelta(seconds=2),
            ),
        ]
    )
    plan = await db_session.get(Plan, plan_id)
    assert plan is not None
    plan.sources = [source]
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert body["presentation"]["kind"] == "knowledge_answer"
    assert any(block["type"] == "knowledge_answer" for block in document["blocks"])
    source_block = next(block for block in document["blocks"] if block["type"] == "source_list")
    assert source_block["sources"][0]["procedure_id"] == "LOTO-M-CNC-01"
    assert any(step["kind"] == "knowledge" for step in document["run_steps"])


@pytest.mark.asyncio
async def test_no_result_response_document_uses_info_diagnostic_not_fake_success(db_session):
    created_at = datetime(2026, 5, 18, 16, 0, 0)
    session_id = "rd-no-results"
    plan_id = "rd-no-results-plan"
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=8, status="COMPLETED"),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-no-results-step",
                completed_at=created_at + timedelta(seconds=2),
                rows=[],
                summary="No matching jobs found.",
            ),
            _assistant_message(session_id=session_id, content="No matching jobs found.", step_id=plan_id, created_at=created_at + timedelta(seconds=3)),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert document["state"] == "completed"
    assert document["diagnostics"]["reason"] == "no_results"
    diagnostic = next(block for block in document["blocks"] if block["type"] == "diagnostic")
    assert diagnostic["reason"] == "no_results"
    assert diagnostic["severity"] == "info"
    assert not any(block["type"] in {"result_summary", "mutation_result"} for block in document["blocks"])
    assert "updated" not in document["message"].lower()


@pytest.mark.asyncio
async def test_partial_failure_response_document_keeps_row_outcomes_and_diagnostic(db_session):
    created_at = datetime(2026, 5, 18, 17, 0, 0)
    session_id = "rd-partial-failure"
    plan_id = "rd-partial-failure-plan"
    approval_id = "approval-rd-partial"
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=10, status="FAILED", error="Partial commit failure."),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id=approval_id,
                status="APPROVED",
                decided_at=created_at + timedelta(seconds=2),
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-partial-write",
                step_index=0,
                completed_at=created_at + timedelta(seconds=3),
                approval_id=approval_id,
                status="FAILED",
                outcomes=[
                    {"job_id": "JOB-RD-PARTIAL-001", "status": "succeeded", "original_priority": "low", "priority": "high"},
                    {"job_id": "JOB-RD-PARTIAL-002", "status": "failed", "error": "version_conflict", "original_priority": "low", "priority": "high"},
                ],
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert body["presentation"]["kind"] == "partial_failure"
    assert document["state"] == "failed"
    result_summary = next(block for block in document["blocks"] if block["type"] == "result_summary")
    assert result_summary["status"] == "partial_failure"
    diagnostic = next(block for block in document["blocks"] if block["type"] == "diagnostic")
    assert diagnostic["reason"] == "partial_commit_failure"
    assert diagnostic["impact"]["succeeded_rows"] == ["JOB-RD-PARTIAL-001"]
    assert diagnostic["impact"]["failed_rows"] == ["JOB-RD-PARTIAL-002"]
    mutation = next(block for block in document["blocks"] if block["type"] == "mutation_result")
    assert {row["row_id"]: row["status"] for row in mutation["rows"]} == {
        "JOB-RD-PARTIAL-001": "succeeded",
        "JOB-RD-PARTIAL-002": "failed",
    }


@pytest.mark.asyncio
async def test_rejected_and_expired_approvals_render_diagnostics_without_mutation_success(db_session):
    created_at = datetime(2026, 5, 18, 18, 0, 0)
    rejected_session = "rd-rejected"
    rejected_plan = "rd-rejected-plan"
    expired_session = "rd-expired"
    expired_plan = "rd-expired-plan"
    db_session.add_all(
        [
            _session(session_id=rejected_session, plan_id=rejected_plan, created_at=created_at, event_seq=5, status="COMPLETED"),
            _user_message(session_id=rejected_session, created_at=created_at),
            _plan(session_id=rejected_session, plan_id=rejected_plan, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=rejected_session,
                plan_id=rejected_plan,
                created_at=created_at,
                approval_id="approval-rd-rejected",
                status="REJECTED",
                decided_at=created_at + timedelta(seconds=3),
            ),
            _session(session_id=expired_session, plan_id=expired_plan, created_at=created_at, event_seq=5, status="WAITING_APPROVAL"),
            _user_message(session_id=expired_session, created_at=created_at),
            _plan(session_id=expired_session, plan_id=expired_plan, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=expired_session,
                plan_id=expired_plan,
                created_at=created_at,
                approval_id="approval-rd-expired",
                status="EXPIRED",
            ),
        ]
    )
    await db_session.commit()

    rejected = (await _snapshot(db_session, rejected_session))["response_document"]
    expired = (await _snapshot(db_session, expired_session))["response_document"]

    assert rejected["state"] == "rejected"
    assert any(step["state"] == "rejected" for step in rejected["run_steps"])
    assert any(block["type"] == "diagnostic" and block["reason"] == "approval_rejected" for block in rejected["blocks"])
    assert not any(block["type"] == "mutation_result" for block in rejected["blocks"])
    assert expired["state"] == "expired"
    assert any(step["state"] == "expired" for step in expired["run_steps"])
    assert any(block["type"] == "diagnostic" and block["reason"] == "approval_expired" for block in expired["blocks"])
    assert not any(block["type"] == "mutation_result" for block in expired["blocks"])


@pytest.mark.asyncio
async def test_cancelled_response_document_uses_cancelled_state_and_diagnostic(db_session):
    created_at = datetime(2026, 5, 18, 19, 0, 0)
    session_id = "rd-cancelled"
    db_session.add_all(
        [
            Session(
                session_id=session_id,
                user_id="u1",
                status="IDLE",
                current_intent="cancel active run",
                plan_version=0,
                current_step_index=0,
                step_count=0,
                llm_call_count=0,
                event_seq=3,
                session_started_at=created_at,
                created_at=created_at,
                updated_at=created_at + timedelta(seconds=2),
                error="Cancelled by user message",
            ),
            _user_message(session_id=session_id, created_at=created_at),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert body["presentation"]["kind"] == "cancelled"
    assert document["state"] == "cancelled"
    assert any(step["kind"] == "cancelled" and step["state"] == "cancelled" for step in document["run_steps"])
    assert any(block["type"] == "diagnostic" and block["reason"] == "cancelled_by_user" for block in document["blocks"])


@pytest.mark.asyncio
async def test_response_document_revision_is_monotonic_and_block_ids_are_stable(db_session):
    created_at = datetime(2026, 5, 18, 10, 0, 0)
    session_id = "rd-revision-stable"
    plan_id = "rd-revision-plan"
    session = _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=11)
    db_session.add_all(
        [
            session,
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id="approval-rd-stable",
            ),
        ]
    )
    await db_session.commit()

    first = await _snapshot(db_session, session_id)
    first_document = first["response_document"]
    first_block_ids = [block["id"] for block in first_document["blocks"]]
    first_step_ids = [step["step_id"] for step in first_document["run_steps"]]

    session.event_seq = 12
    session.updated_at = created_at + timedelta(seconds=4)
    await db_session.commit()

    second = await _snapshot(db_session, session_id)
    second_document = second["response_document"]

    assert second_document["revision"] > first_document["revision"]
    assert second_document["id"] == first_document["id"]
    assert [block["id"] for block in second_document["blocks"]] == first_block_ids
    assert [step["step_id"] for step in second_document["run_steps"]] == first_step_ids
    assert "approval:approval-rd-stable" in first_block_ids
