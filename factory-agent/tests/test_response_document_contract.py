from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from factory_agent.config import Settings
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.models import Approval, Message, Plan, PlanStep, Session
from factory_agent.rag.source_metadata import insufficient_context_answer
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import PresentationResponse, ResponseDocument
from factory_agent.services import response_document_service, session_snapshot_service
from factory_agent.services.response_document_service import (
    BUSINESS_CHANGE_CONTRACT,
    ENTITY_STATUS_CONTRACT,
    MutationGroup,
    NO_OP_MUTATION_CONTRACT,
    ReadEvidence,
    _business_change_order_from_text,
    _business_change_summary,
    _business_group_sort_key,
    _failure_reason,
    _knowledge_answer_payload,
    _merge_mutation_groups_by_business_change,
    _read_evidence_collection_summary,
    _status_result_from_read_rows,
)
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
    replan_context: dict[str, Any] | None = None,
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
        replan_context=replan_context,
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


def _user_message(*, session_id: str, created_at: datetime, content: str = "Change one job priority") -> Message:
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
        expires_at=datetime(2099, 1, 1),
        decided_at=decided_at,
        decided_by="operator" if decided_at else None,
        created_at=created_at + timedelta(seconds=created_offset_s),
    )


def test_failure_reason_does_not_treat_redacted_authorization_metadata_as_auth_denied():
    presentation = PresentationResponse(
        kind="diagnostic",
        state="failed",
        summary="Execution stopped after response-document assembly saw authorization=[redacted] metadata.",
    )

    assert _failure_reason(
        presentation=presentation,
        steps=[],
        approvals=[],
        mutation_groups=[],
    ) is None

    denied = PresentationResponse(
        kind="diagnostic",
        state="failed",
        summary="The backend returned authorization denied for this protected action.",
    )

    assert _failure_reason(
        presentation=denied,
        steps=[],
        approvals=[],
        mutation_groups=[],
    ) == "auth_denied"


def test_read_evidence_collection_summary_surfaces_business_rule_rows():
    item = ReadEvidence(
        key="read:jobs",
        operation_id="op-rule",
        tool_name="get__jobs",
        args={"priority": "low"},
    )

    summary = _read_evidence_collection_summary(
        item,
        rows=[
            {"job_id": "job-alpha", "priority": "low", "rule": "expedite"},
            {"job_id": "job-beta", "priority": "low", "rule": "monitor"},
        ],
    )

    assert summary == "Rule Applied: found 2 low-priority jobs."


def test_planner_owned_completed_answer_summary_prefers_graph_response_summary():
    created_at = datetime(2026, 5, 27, 12, 0, 0)
    session = _session(
        session_id="rd-conditional-summary",
        plan_id="plan-rd-conditional-summary",
        created_at=created_at,
        event_seq=3,
        status="COMPLETED",
        replan_context={
            "intent_contract": {
                "response_document_context": {
                    "diagnostics": {
                        "summary": (
                            "Job JOB-SEED-001 was retrieved. "
                            "No machine id was present, so the conditional machine follow-up was skipped."
                        )
                    }
                }
            }
        },
    )
    plan = _plan(
        session_id=session.session_id,
        plan_id=session.plan_id,
        created_at=created_at,
    )
    terminal = type("TerminalEvent", (), {"content": "Job JOB-SEED-001 was retrieved."})()

    summary = session_snapshot_service._planner_owned_completed_answer_summary(
        session=session,
        terminal_event=terminal,
        plan=plan,
    )

    assert summary == (
        "Job JOB-SEED-001 was retrieved. "
        "No machine id was present, so the conditional machine follow-up was skipped."
    )


@pytest.mark.asyncio
async def test_planner_owned_conditional_summary_overrides_mixed_read_counter(db_session):
    created_at = datetime(2026, 5, 27, 14, 35, 0)
    session_id = "rd-conditional-product-summary"
    plan_id = "rd-conditional-product-summary-plan"
    prompt = "Read job JOB-SEED-001. If the job result includes a product id, read that product. Summarize the result."
    planner_summary = (
        "Job JOB-SEED-001 included product id P-001, so the conditional product follow-up was run. "
        "Product P-001 is active."
    )
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=6,
                status="COMPLETED",
                current_intent=prompt,
                replan_context={
                    "intent_contract": {
                        "response_document_context": {
                            "diagnostics": {
                                "summary": planner_summary,
                                "conditional_branches": [
                                    {
                                        "id": "branch-001",
                                        "status": "activated",
                                        "parent_requirement_id": "req-001",
                                        "activated_child_requirement_ids": ["req-001.a"],
                                        "diagnostics": {
                                            "trigger_field": "product_id",
                                            "trigger_value": "P-001",
                                        },
                                    }
                                ],
                                "answer_instructions": [
                                    {"id": "answer-001", "text": "Summarize the result."}
                                ],
                            }
                        }
                    }
                },
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-conditional-job",
                completed_at=created_at + timedelta(seconds=2),
                rows=[],
                summary="Job JOB-SEED-001 was retrieved.",
                tool_name="get__jobs_{id}",
                args={"id": "JOB-SEED-001"},
                result={
                    "success": True,
                    "data": {
                        "job_id": "JOB-SEED-001",
                        "product_id": "P-001",
                    },
                },
            ),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-conditional-product",
                completed_at=created_at + timedelta(seconds=3),
                rows=[],
                summary="Product P-001 is active.",
                tool_name="get__products_{id}",
                args={"id": "P-001"},
                result={
                    "success": True,
                    "data": {
                        "product_id": "P-001",
                        "status": "active",
                    },
                },
            ),
            _assistant_message(
                session_id=session_id,
                content="Found 1 job. Found 1 product.",
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=4),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]

    assert document["state"] == "completed"
    assert document["message"] == planner_summary
    assert document["summary"] == planner_summary
    assert "Found 1 job. Found 1 product." not in json.dumps(document)
    completion = next(step for step in document["run_steps"] if step["kind"] == "completed")
    assert completion["summary"] == planner_summary


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
    tool_name: str = "put__jobs_{id}",
    args: dict[str, Any] | None = None,
) -> PlanStep:
    target_args = args
    if target_args is None:
        target_priority = str(
            (outcomes[0] if outcomes else {}).get("priority")
            or (outcomes[0] if outcomes else {}).get("new_priority")
            or "high"
        )
        target_args = {"write_set": f"write-set-{approval_id}", "priority": target_priority}
    return PlanStep(
        step_id=step_id,
        plan_id=plan_id,
        session_id=session_id,
        step_index=step_index,
        tool_name=tool_name,
        args=target_args,
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
    step_index: int = 0,
    completed_at: datetime,
    rows: list[dict[str, Any]],
    summary: str,
    tool_name: str = "get__jobs",
    args: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        plan_id=plan_id,
        session_id=session_id,
        step_index=step_index,
        tool_name=tool_name,
        args=args if args is not None else {"fields": "job_id,priority,status"},
        bindings=[],
        status="DONE",
        idempotency_key=f"{step_id}-key",
        requires_approval=False,
        retry_count=0,
        max_retries=0,
        completed_at=completed_at,
        result=result if result is not None else {"success": True, "data": rows},
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


def _noop_contract(
    *,
    entity_type: str,
    selector_summary: str,
    change_summary: str,
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "selector_summary": selector_summary,
        "change_summary": change_summary,
        "matched_count": 0,
        "changed_count": 0,
        "status": "not_changed",
        "reason": "no_matching_records",
    }


def test_business_mutation_groups_drop_shadow_rows_and_follow_summary_order():
    groups = [
        MutationGroup(
            key="read-medium",
            operation_id="op-rd",
            approval_id=None,
            rows=[
                {"job_id": "JOB-MED-001", "priority": "medium", "status": "succeeded"},
                {"job_id": "JOB-MED-002", "priority": "medium", "status": "succeeded"},
            ],
            first_seen=0,
        ),
        MutationGroup(
            key="read-high",
            operation_id="op-rd",
            approval_id=None,
            rows=[
                {"job_id": "JOB-HIGH-001", "priority": "high", "status": "succeeded"},
                {"job_id": "JOB-HIGH-002", "priority": "high", "status": "succeeded"},
            ],
            first_seen=1,
        ),
        MutationGroup(
            key="write-high",
            operation_id="op-rd",
            approval_id=None,
            rows=[
                {
                    "job_id": "JOB-HIGH-001",
                    "from_priority": "high",
                    "to_priority": "low",
                    "source_state_basis": "original",
                    "status": "succeeded",
                },
                {
                    "job_id": "JOB-HIGH-002",
                    "from_priority": "high",
                    "to_priority": "low",
                    "source_state_basis": "original",
                    "status": "succeeded",
                },
            ],
            first_seen=2,
        ),
        MutationGroup(
            key="write-medium",
            operation_id="op-rd",
            approval_id=None,
            rows=[
                {
                    "job_id": "JOB-MED-001",
                    "from_priority": "medium",
                    "to_priority": "high",
                    "source_state_basis": "original",
                    "status": "succeeded",
                },
                {
                    "job_id": "JOB-MED-002",
                    "from_priority": "medium",
                    "to_priority": "high",
                    "source_state_basis": "original",
                    "status": "succeeded",
                },
            ],
            first_seen=3,
        ),
    ]
    summary_order = _business_change_order_from_text(
        "- 2 medium priority jobs changed to high\n"
        "- 2 original high priority jobs changed to low"
    )

    merged = _merge_mutation_groups_by_business_change(groups)
    ordered = sorted(merged, key=lambda group: _business_group_sort_key(group, {}, summary_order))

    assert [_business_change_summary(group, index=index) for index, group in enumerate(ordered, start=1)] == [
        "Medium -> High: 2 jobs",
        "Original High -> Low: 2 jobs",
    ]
    assert [len(group.rows) for group in ordered] == [2, 2]
    assert {row["job_id"] for group in ordered for row in group.rows} == {
        "JOB-MED-001",
        "JOB-MED-002",
        "JOB-HIGH-001",
        "JOB-HIGH-002",
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
                    "id": "status:op-1",
                    "type": "status_result",
                    "operation_id": "op-1",
                    "title": "Machine status",
                    "summary": "Machine M-CNC-01 is running.",
                    "entity_type": "machine",
                    "entity_id": "M-CNC-01",
                    "primary_status": "running",
                    "fields": [
                        {"key": "machine_id", "label": "Machine ID", "value": "M-CNC-01"},
                        {"key": "status", "label": "Status", "value": "running", "primary": True},
                    ],
                },
                {
                    "id": "knowledge:op-1",
                    "type": "knowledge_answer",
                    "contract": "knowledge_answer_v1",
                    "operation_id": "op-1",
                    "answer": "Use the controlled LOTO procedure.",
                    "segments": [
                        {
                            "text": "Use the controlled LOTO procedure.",
                            "citation_ids": ["citation:LOTO-M-CNC-01#chunk-1"],
                        }
                    ],
                    "citations": [
                        {
                            "contract": "source_citation_v1",
                            "citation_id": "citation:LOTO-M-CNC-01#chunk-1",
                            "source_id": "LOTO-M-CNC-01#chunk-1",
                            "source_number": 1,
                            "doc_id": "LOTO-M-CNC-01",
                            "chunk_id": "chunk-1",
                            "title": "LOTO procedure",
                            "organization": "Factory Safety",
                            "snippet": "Use the controlled LOTO procedure.",
                        }
                    ],
                },
                {
                    "id": "safety:op-1",
                    "type": "safety_notice",
                    "contract": "safety_notice_v1",
                    "title": "Safety notice",
                    "safety_content": "Follow the approved SOP before acting.",
                    "operation_id": "op-1",
                },
                {
                    "id": "sources:op-1",
                    "type": "source_list",
                    "contract": "source_list_v1",
                    "operation_id": "op-1",
                    "sources": [{"contract": "source_locator_v1", "procedure_id": "LOTO-M-CNC-01"}],
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
        "status_result",
        "knowledge_answer",
        "safety_notice",
        "source_list",
        "diagnostic",
    }


def test_response_document_schema_validates_phase22_generic_contracts():
    document = ResponseDocument.model_validate(
        {
            "id": "rd:phase22:turn-1",
            "document_id": "rd:phase22:turn-1",
            "turn_id": "turn-1",
            "operation_id": "op-phase22",
            "revision": 1,
            "revision_source": "event_seq",
            "state": "completed",
            "status": "completed",
            "summary": "Product P-RD-001 is active.",
            "message": "Product P-RD-001 is active.",
            "blocks": [
                {
                    "id": "status:product",
                    "type": "status_result",
                    "contract": ENTITY_STATUS_CONTRACT,
                    "summary": "Product P-RD-001 is active.",
                    "entity_type": "product",
                    "entity_id": "P-RD-001",
                    "primary_status": "active",
                    "fields": [
                        {"key": "product_id", "label": "Product ID", "value": "P-RD-001"},
                        {"key": "status", "label": "Status", "value": "active", "primary": True},
                    ],
                },
                {
                    "id": "mutation:material",
                    "type": "mutation_result",
                    "contract": BUSINESS_CHANGE_CONTRACT,
                    "summary": "Material hold status: 1 material",
                    "rows": [
                        {
                            "record_id": "MAT-RD-001",
                            "display_id": "Material MAT-RD-001",
                            "business_change": "Material hold status",
                            "business_change_id": "bc-material-hold",
                            "entity_type": "material",
                            "field_changes": [
                                {
                                    "field": "hold_status",
                                    "label": "Hold status",
                                    "from": "available",
                                    "to": "quality_hold",
                                }
                            ],
                            "outcome": "succeeded",
                            "status": "succeeded",
                        }
                    ],
                    "groups": [
                        {
                            "contract": BUSINESS_CHANGE_CONTRACT,
                            "business_change": "Material hold status",
                            "business_change_id": "bc-material-hold",
                            "entity_type": "material",
                            "change_type": "update",
                            "selector_summary": "material_id = MAT-RD-001",
                            "source_state_basis": "current_state",
                            "field_changes": [
                                {
                                    "field": "hold_status",
                                    "label": "Hold status",
                                    "from": "available",
                                    "to": "quality_hold",
                                }
                            ],
                            "summary": "Material hold status: 1 material",
                            "record_count": 1,
                            "rows": [],
                        }
                    ],
                },
            ],
        }
    )

    payload = document.model_dump(mode="json")
    status = next(block for block in payload["blocks"] if block["type"] == "status_result")
    mutation = next(block for block in payload["blocks"] if block["type"] == "mutation_result")

    assert status["contract"] == ENTITY_STATUS_CONTRACT
    assert status["entity_type"] == "product"
    assert mutation["contract"] == BUSINESS_CHANGE_CONTRACT
    assert mutation["groups"][0]["contract"] == BUSINESS_CHANGE_CONTRACT
    assert mutation["groups"][0]["field_changes"][0]["field"] == "hold_status"


def test_entity_status_v1_contract_is_not_machine_specific():
    session = type("StatusProbe", (), {"current_intent": "What is the status of product P-RD-001?"})()

    status = _status_result_from_read_rows(
        [
            {
                "productID": "P-RD-001",
                "name": "Widget",
                "status": "ACTIVE",
                "tool_name": "get__products_{id}",
            }
        ],
        operation_id="op-product-status",
        session=session,
    )

    assert status is not None
    assert status["contract"] == ENTITY_STATUS_CONTRACT
    assert status["entity_type"] == "product"
    assert status["entity_id"] == "P-RD-001"
    assert status["primary_status"] == "active"
    assert [(field["key"], field["label"], field["value"]) for field in status["fields"]] == [
        ("product_id", "Product ID", "P-RD-001"),
        ("status", "Status", "active"),
    ]


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
    assert body["presentation"]["summary"] == "One job will be changed from medium to high priority."
    assert document["summary"] == "1 job will be updated from medium to high priority."
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
async def test_orphan_idle_after_actionable_prompt_becomes_typed_blocked_diagnostic(db_session):
    created_at = datetime(2026, 5, 18, 10, 30, 0)
    session_id = "rd-orphan-idle-actionable"
    plan_id = "rd-orphan-idle-plan"
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=3,
                status="IDLE",
                current_intent="change all medium priority job to high then change all high priority job to low",
                completed_at=None,
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content="No safe discovery steps are required before preparing an execution proposal.",
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=1),
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert body["session"]["status"] == "BLOCKED"
    assert body["pending_approval"] is None
    assert document["state"] == "blocked"
    assert document["diagnostics"]["reason"] == "orphan_turn_state"
    assert document["diagnostics"]["session_status"] == "BLOCKED"
    assert document["diagnostics"]["original_session_status"] == "IDLE"
    assert document["invariants"]["orphan_turn_state"] is True
    diagnostic = next(block for block in document["blocks"] if block["type"] == "diagnostic")
    assert diagnostic["reason"] == "orphan_turn_state"
    assert diagnostic["title"] != "Needs attention"
    assert "current state" in diagnostic["user_message"].lower()
    assert "check current status" in diagnostic["next_action"].lower()


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
    run_step_text = "\n".join((step.get("summary") or "") for step in document["run_steps"])
    assert "will be updated from medium to high" not in run_step_text
    assert "2 original medium priority jobs changed to high." in run_step_text
    assert "Run complete" not in document["message"]
    assert "Updated 5 jobs across 2 approved steps" not in document["message"]


@pytest.mark.asyncio
async def test_final_completed_mutation_document_aggregates_all_approved_changes(db_session):
    created_at = datetime(2026, 5, 18, 13, 0, 0)
    session_id = "rd-two-step-completed"
    plan_id = "rd-two-step-completed-plan"
    approval_1 = "approval-rd-completed-1"
    approval_2 = "approval-rd-completed-2"
    medium_job_ids = [
        "JOB-SEED-002",
        "JOB-SEED-004",
        "JOB-SEED-007",
        "JOB-SEED-010",
        "JOB-SEED-014",
        "JOB-SEED-016",
        "JOB-SEED-018",
        "JOB-SEED-020",
        "JOB-SEED-022",
        "JOB-SEED-024",
    ]
    high_job_ids = [
        "JOB-SEED-001",
        "JOB-SEED-003",
        "JOB-SEED-006",
        "JOB-SEED-008",
        "JOB-SEED-011",
        "JOB-SEED-013",
        "JOB-SEED-015",
        "JOB-SEED-017",
        "JOB-SEED-019",
        "JOB-SEED-021",
        "JOB-SEED-023",
    ]
    first_rows = [
        {
            "job_id": job_id,
            "original_priority": "medium",
            "priority": "high",
            "audit_row_id": f"audit-medium-{index}",
        }
        for index, job_id in enumerate(medium_job_ids, start=1)
    ]
    first_rows_with_duplicate_audit = [
        *first_rows,
        {
            "job_id": "JOB-SEED-002",
            "original_priority": "medium",
            "priority": "high",
            "audit_row_id": "audit-medium-duplicate",
            "operation_id": "internal-operation-duplicate",
        },
    ]
    second_rows = [
        {
            "job_id": job_id,
            "original_priority": "high",
            "priority": "low",
            "audit_row_id": f"audit-high-{index}",
        }
        for index, job_id in enumerate(high_job_ids, start=1)
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
                outcomes=first_rows_with_duplicate_audit,
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
                content=(
                    "done_all\n\n"
                    "**Success**\n\n"
                    "Updated 63 jobs across 22 approved steps.\n\n"
                    "Operation ID: internal-op\nStep ID: internal-step\nRow ID: internal-row"
                ),
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=8),
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert document["state"] == "completed"
    assert document["message"] == "Done. I updated 21 jobs across 2 approved business changes."
    assert document["invariants"]["mutation_business_contract"] == BUSINESS_CHANGE_CONTRACT
    assert document["invariants"]["affected_record_count"] == 21
    assert document["invariants"]["approved_business_change_count"] == 2
    assert document["invariants"]["affected_record_preview_limit"] == 5

    block_types = [block["type"] for block in document["blocks"]]
    assert block_types.count("result_summary") == 1
    assert block_types.count("mutation_result") == 1
    assert "completed_step" not in block_types
    assert "result_table" not in block_types

    result_summary = next(block for block in document["blocks"] if block["type"] == "result_summary")
    assert result_summary["title"] == "Changes completed"
    assert result_summary["total_count"] == 21
    assert result_summary["steps"] == [
        {
            "step_number": 1,
            "business_change": "Medium -> High",
            "summary": "Medium -> High: 10 jobs",
            "record_count": 10,
            "status": "completed",
            "contract": BUSINESS_CHANGE_CONTRACT,
            "business_change_id": "job-priority-original-medium-to-high",
            "entity_type": "job",
            "change_type": "update",
            "selector_summary": "priority = medium",
            "source_state_basis": "original",
            "field_changes": [{"field": "priority", "label": "Priority", "from": "medium", "to": "high"}],
        },
        {
            "step_number": 2,
            "business_change": "Original High -> Low",
            "summary": "Original High -> Low: 11 jobs",
            "record_count": 11,
            "status": "completed",
            "contract": BUSINESS_CHANGE_CONTRACT,
            "business_change_id": "job-priority-original-high-to-low",
            "entity_type": "job",
            "change_type": "update",
            "selector_summary": "priority = high",
            "source_state_basis": "original",
            "field_changes": [{"field": "priority", "label": "Priority", "from": "high", "to": "low"}],
        },
    ]

    mutation = next(block for block in document["blocks"] if block["type"] == "mutation_result")
    assert mutation["contract"] == BUSINESS_CHANGE_CONTRACT
    assert mutation["title"] == "Affected records"
    assert mutation["preview_limit"] == 5
    assert mutation["details_collapsed"] is True
    assert len(mutation["rows"]) == 21
    assert len({row["record_id"] for row in mutation["rows"]}) == 21
    assert [row["display_id"] for row in mutation["rows"][:5]] == medium_job_ids[:5]
    assert len(mutation["groups"]) == 2
    first_group, second_group = mutation["groups"]
    assert {
        "contract": first_group["contract"],
        "business_change": first_group["business_change"],
        "business_change_id": first_group["business_change_id"],
        "entity_type": first_group["entity_type"],
        "change_type": first_group["change_type"],
        "selector_summary": first_group["selector_summary"],
        "source_state_basis": first_group["source_state_basis"],
        "field_changes": first_group["field_changes"],
        "summary": first_group["summary"],
        "record_count": first_group["record_count"],
    } == {
        "contract": BUSINESS_CHANGE_CONTRACT,
        "business_change": "Medium -> High",
        "business_change_id": "job-priority-original-medium-to-high",
        "entity_type": "job",
        "change_type": "update",
        "selector_summary": "priority = medium",
        "source_state_basis": "original",
        "field_changes": [{"field": "priority", "label": "Priority", "from": "medium", "to": "high"}],
        "summary": "Medium -> High: 10 jobs",
        "record_count": 10,
    }
    assert {
        "contract": second_group["contract"],
        "business_change": second_group["business_change"],
        "business_change_id": second_group["business_change_id"],
        "entity_type": second_group["entity_type"],
        "change_type": second_group["change_type"],
        "selector_summary": second_group["selector_summary"],
        "source_state_basis": second_group["source_state_basis"],
        "field_changes": second_group["field_changes"],
        "summary": second_group["summary"],
        "record_count": second_group["record_count"],
    } == {
        "contract": BUSINESS_CHANGE_CONTRACT,
        "business_change": "Original High -> Low",
        "business_change_id": "job-priority-original-high-to-low",
        "entity_type": "job",
        "change_type": "update",
        "selector_summary": "priority = high",
        "source_state_basis": "original",
        "field_changes": [{"field": "priority", "label": "Priority", "from": "high", "to": "low"}],
        "summary": "Original High -> Low: 11 jobs",
        "record_count": 11,
    }
    assert first_group["rows"] == mutation["rows"][:10]
    assert second_group["rows"] == mutation["rows"][10:]
    assert {row["business_change"] for row in mutation["rows"][:10]} == {"Medium -> High"}
    assert {row["business_change"] for row in mutation["rows"][10:]} == {"Original High -> Low"}
    assert {row["change"] for row in mutation["rows"][:10]} == {"Priority: medium -> high"}
    assert {row["change"] for row in mutation["rows"][10:]} == {"Priority: high -> low"}
    assert {row["entity_type"] for row in mutation["rows"]} == {"job"}
    assert all(row["field_changes"] for row in mutation["rows"])
    forbidden_row_keys = {
        "operation_id",
        "step_id",
        "row_id",
        "approval_id",
        "tool_name",
        "audit_row_id",
        "job_id",
        "from_priority",
        "to_priority",
        "previous_priority",
        "new_priority",
    }
    assert all(forbidden_row_keys.isdisjoint(row) for row in mutation["rows"])

    assert document["invariants"]["completed_approval_ids"] == [approval_1, approval_2]
    assert not any(step["state"] == "waiting" for step in document["run_steps"])
    serialized_document = json.dumps(document)
    for forbidden in [
        "done_all",
        "**Success**",
        "Updated 63 jobs across 22 approved steps",
        "Operation ID",
        "Step ID",
        "Row ID",
    ]:
        assert forbidden not in serialized_document


@pytest.mark.asyncio
async def test_business_change_v1_uses_typed_mutation_fields_without_summary_prose(db_session, monkeypatch):
    created_at = datetime(2026, 5, 18, 13, 10, 0)
    session_id = "rd-business-change-v1"
    plan_id = "rd-business-change-v1-plan"
    approval_id = "approval-rd-business-change-v1"
    typed_change = {
        "contract": BUSINESS_CHANGE_CONTRACT,
        "business_change_id": "bc-material-hold",
        "business_change": "Material hold status",
        "entity_type": "material",
        "change_type": "update",
        "selector_summary": "material_id = MAT-RD-001",
        "source_state_basis": "current_state",
        "record_id": "MAT-RD-001",
        "display_id": "Material MAT-RD-001",
        "field_changes": [
            {
                "field": "hold_status",
                "label": "Hold status",
                "from": "available",
                "to": "quality_hold",
            }
        ],
        "status": "succeeded",
    }

    def fail_on_summary_prose_ordering(text: str) -> dict[str, int]:
        raise AssertionError(f"typed business_change_v1 composition parsed summary prose: {text!r}")

    monkeypatch.setattr(
        response_document_service,
        "_business_change_order_from_text",
        fail_on_summary_prose_ordering,
    )

    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=12,
                status="COMPLETED",
                current_intent="Put material MAT-RD-001 on quality hold",
            ),
            _user_message(session_id=session_id, created_at=created_at, content="Put material MAT-RD-001 on quality hold"),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id=approval_id,
                status="APPROVED",
                args={
                    "summary": "Put one material on quality hold.",
                    "bundle_ui": {
                        "write_set": "material_quality_hold",
                        "rows": [typed_change],
                    },
                },
                risk_summary="Put one material on quality hold.",
                decided_at=created_at + timedelta(seconds=2),
            ),
            _write_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-business-change-v1-write",
                step_index=0,
                completed_at=created_at + timedelta(seconds=3),
                approval_id=approval_id,
                outcomes=[typed_change],
            ),
            _assistant_message(
                session_id=session_id,
                content="The backend operation completed.",
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=4),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    mutation = next(block for block in document["blocks"] if block["type"] == "mutation_result")
    group = mutation["groups"][0]
    row = group["rows"][0]

    assert document["state"] == "completed"
    assert document["message"] == "Done. I updated 1 material across 1 approved business change."
    assert document["invariants"]["mutation_business_contract"] == BUSINESS_CHANGE_CONTRACT
    assert mutation["contract"] == BUSINESS_CHANGE_CONTRACT
    assert group["contract"] == BUSINESS_CHANGE_CONTRACT
    assert group["business_change"] == "Material hold status"
    assert group["business_change_id"] == "bc-material-hold"
    assert group["entity_type"] == "material"
    assert group["change_type"] == "update"
    assert group["selector_summary"] == "material_id = MAT-RD-001"
    assert group["source_state_basis"] == "current_state"
    assert group["field_changes"] == [
        {"field": "hold_status", "label": "Hold status", "from": "available", "to": "quality_hold"}
    ]
    assert row["record_id"] == "MAT-RD-001"
    assert row["display_id"] == "Material MAT-RD-001"
    assert row["outcome"] == "succeeded"
    assert row["field_changes"] == group["field_changes"]
    assert "job_id" not in row
    assert "from_priority" not in row
    assert "to_priority" not in row
    assert "The backend operation completed" not in json.dumps(document)


@pytest.mark.asyncio
async def test_partial_noop_plus_valid_mutation_is_visible_before_approval_and_final(db_session):
    created_at = datetime(2026, 5, 18, 13, 30, 0)
    session_id = "rd-partial-noop"
    plan_id = "rd-partial-noop-plan"
    approval_id = "approval-rd-partial-noop-valid"
    no_op = _noop_contract(
        entity_type="job",
        selector_summary="priority = medium",
        change_summary="priority -> high",
    )
    valid_rows = [
        {"job_id": "JOB-RD-HIGH-001", "original_priority": "high", "new_priority": "low"},
        {"job_id": "JOB-RD-HIGH-002", "original_priority": "high", "new_priority": "low"},
    ]
    approval_args = {
        "summary": "Change 2 original high-priority jobs to low.",
        "count": 2,
        "no_op_mutations": [no_op],
        "bundle_ui": {
            "kind": "phase17_partial_noop",
            "write_set": "original_high_to_low",
            "headline": "Update 2 jobs from high to low",
            "rows": valid_rows,
            "original_state_semantics": "Original priority groups are evaluated before any approved writes are applied.",
        },
    }
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=11,
                status="WAITING_APPROVAL",
                current_intent="change all medium priority job to high then change all high priority job to low",
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id=approval_id,
                status="PENDING",
                args=approval_args,
                risk_summary="Update 2 jobs from high to low",
                created_offset_s=3,
            ),
        ]
    )
    await db_session.commit()

    waiting = (await _snapshot(db_session, session_id))["response_document"]

    assert waiting["state"] == "waiting_approval"
    assert "Not changed" in waiting["message"]
    assert "no matching jobs for priority = medium" in waiting["message"]
    block_types = [block["type"] for block in waiting["blocks"]]
    noop_index = next(index for index, block in enumerate(waiting["blocks"]) if block["type"] == "completed_step")
    approval_index = next(index for index, block in enumerate(waiting["blocks"]) if block["type"] == "approval_required")
    assert noop_index < approval_index
    approval_block = waiting["blocks"][approval_index]
    assert approval_block["approval_id"] == approval_id
    assert [row["job_id"] for row in approval_block["rows"]] == ["JOB-RD-HIGH-001", "JOB-RD-HIGH-002"]
    assert "JOB-RD-MEDIUM" not in json.dumps(approval_block)
    run_step_titles = [step["title"] for step in waiting["run_steps"]]
    assert run_step_titles.index("Not changed") < run_step_titles.index("Waiting for approval 1")

    approval = await db_session.get(Approval, approval_id)
    assert approval is not None
    approval.status = "APPROVED"
    approval.decided_at = created_at + timedelta(seconds=4)
    approval.decided_by = "operator"
    session = await db_session.get(Session, session_id)
    assert session is not None
    session.status = "COMPLETED"
    session.completed_at = created_at + timedelta(seconds=6)
    session.updated_at = created_at + timedelta(seconds=6)
    session.event_seq = 16
    db_session.add(
        _write_step(
            session_id=session_id,
            plan_id=plan_id,
            step_id="rd-partial-noop-valid-write",
            step_index=0,
            completed_at=created_at + timedelta(seconds=5),
            approval_id=approval_id,
            outcomes=valid_rows,
        )
    )
    await db_session.commit()

    final = (await _snapshot(db_session, session_id))["response_document"]

    assert final["state"] == "completed"
    assert final["message"] == (
        "Done. I updated 2 jobs across 1 approved business change. "
        "1 business change not changed because no matching records were found."
    )
    assert not any(block["type"] == "approval_required" for block in final["blocks"])
    result_summary = next(block for block in final["blocks"] if block["type"] == "result_summary")
    assert [step["business_change"] for step in result_summary["steps"]] == ["Not changed", "Original High -> Low"]
    assert {
        key: result_summary["steps"][0][key]
        for key in (
            "step_number",
            "business_change",
            "summary",
            "record_count",
            "status",
            "contract",
            "entity_type",
            "selector_summary",
            "change_summary",
            "matched_count",
            "changed_count",
            "reason",
        )
    } == {
        "step_number": 1,
        "business_change": "Not changed",
        "summary": "Not changed: no matching jobs for priority = medium; priority -> high.",
        "record_count": 0,
        "status": "not_changed",
        "contract": NO_OP_MUTATION_CONTRACT,
        "entity_type": "job",
        "selector_summary": "priority = medium",
        "change_summary": "priority -> high",
        "matched_count": 0,
        "changed_count": 0,
        "reason": "no_matching_records",
    }
    assert result_summary["steps"][1]["contract"] == BUSINESS_CHANGE_CONTRACT
    assert result_summary["steps"][1]["entity_type"] == "job"
    assert result_summary["steps"][1]["field_changes"] == [
        {"field": "priority", "label": "Priority", "from": "high", "to": "low"}
    ]
    mutation = next(block for block in final["blocks"] if block["type"] == "mutation_result")
    assert mutation["contract"] == BUSINESS_CHANGE_CONTRACT
    assert [group["business_change"] for group in mutation["groups"]] == ["Not changed", "Original High -> Low"]
    not_changed_group = mutation["groups"][0]
    assert not_changed_group["rows"] == []
    assert not_changed_group["contract"] == NO_OP_MUTATION_CONTRACT
    assert not_changed_group["entity_type"] == "job"
    assert not_changed_group["selector_summary"] == "priority = medium"
    assert not_changed_group["change_summary"] == "priority -> high"
    assert not_changed_group["matched_count"] == 0
    assert not_changed_group["changed_count"] == 0
    assert not_changed_group["status"] == "not_changed"
    assert not_changed_group["reason"] == "no_matching_records"
    assert len(mutation["rows"]) == 2
    changed_group = mutation["groups"][1]
    assert changed_group["contract"] == BUSINESS_CHANGE_CONTRACT
    assert changed_group["entity_type"] == "job"
    assert changed_group["selector_summary"] == "priority = high"
    assert changed_group["source_state_basis"] == "original"
    assert changed_group["field_changes"] == [
        {"field": "priority", "label": "Priority", "from": "high", "to": "low"}
    ]
    assert {row["record_id"] for row in mutation["rows"]} == {"JOB-RD-HIGH-001", "JOB-RD-HIGH-002"}
    assert all("job_id" not in row for row in mutation["rows"])
    assert final["invariants"]["approved_business_change_count"] == 1
    assert final["invariants"]["not_changed_group_count"] == 1
    assert final["invariants"]["no_op_mutation_contract"] == "entity_agnostic_no_matching_records_v1"
    assert final["invariants"]["mutation_business_contract"] == BUSINESS_CHANGE_CONTRACT

    write_steps = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().all()
    assert len([step for step in write_steps if step.requires_approval]) == 1
    assert "priority = medium" not in json.dumps([step.result for step in write_steps], default=str)


@pytest.mark.asyncio
async def test_phase14_zero_match_first_change_uses_active_pending_approval_write_set(db_session):
    created_at = datetime(2026, 5, 19, 10, 15, 0)
    session_id = "rd-phase14-zero-match-first"
    plan_id = "rd-phase14-zero-match-first-plan"
    approval_id = "approval-rd-phase14-medium-high"
    no_op = _noop_contract(
        entity_type="job",
        selector_summary="priority = low",
        change_summary="priority -> medium",
    )
    valid_rows = [
        {"job_id": "JOB-RD-MED-001", "priority": "medium", "previous_priority": "medium", "new_priority": "high"},
        {"job_id": "JOB-RD-MED-002", "priority": "medium", "previous_priority": "medium", "new_priority": "high"},
    ]
    approval_args = {
        "summary": "Update 2 jobs from medium to high.",
        "count": 2,
        "no_op_mutations": [no_op],
        "bundle_ui": {
            "kind": "phase14_zero_match_first",
            "write_set": "medium_to_high",
            "headline": "Update 2 jobs from medium to high",
            "rows": valid_rows,
            "source_priority": "medium",
            "new_priority": "high",
        },
    }
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=12,
                status="WAITING_APPROVAL",
                current_intent="change all low priority job to medium, then change all medium priority job to high",
                replan_context={"langgraph_pending_approval": {"approval_id": approval_id, "thread_id": session_id}},
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id=approval_id,
                status="PENDING",
                args=approval_args,
                risk_summary="Update 2 jobs from medium to high.",
                created_offset_s=3,
            ),
        ]
    )
    await db_session.commit()

    waiting = (await _snapshot(db_session, session_id))["response_document"]

    assert waiting["state"] == "waiting_approval"
    assert "no matching jobs for priority = low" in waiting["message"]
    assert "2 jobs will be updated from medium to high priority" in waiting["message"]
    assert "Approval required before applying staged changes" not in waiting["message"]
    noop_index = next(index for index, block in enumerate(waiting["blocks"]) if block["type"] == "completed_step")
    approval_index = next(index for index, block in enumerate(waiting["blocks"]) if block["type"] == "approval_required")
    assert noop_index < approval_index
    approval_block = waiting["blocks"][approval_index]
    assert approval_block["approval_id"] == approval_id
    assert approval_block["contract"] == BUSINESS_CHANGE_CONTRACT
    assert approval_block["summary"] == "2 jobs will be updated from medium to high priority."
    assert [row["job_id"] for row in approval_block["rows"]] == ["JOB-RD-MED-001", "JOB-RD-MED-002"]
    assert {row["previous_priority"] for row in approval_block["rows"]} == {"medium"}
    assert {row["new_priority"] for row in approval_block["rows"]} == {"high"}
    assert "priority = low" not in json.dumps(approval_block)
    run_step_titles = [step["title"] for step in waiting["run_steps"]]
    assert "Waiting for approval 2" not in run_step_titles
    assert run_step_titles.index("Not changed") < run_step_titles.index("Waiting for approval 1")


@pytest.mark.asyncio
async def test_all_noop_mutation_completes_without_approval_or_fake_success(db_session):
    created_at = datetime(2026, 5, 18, 13, 45, 0)
    session_id = "rd-all-noop"
    plan_id = "rd-all-noop-plan"
    no_op = _noop_contract(
        entity_type="job",
        selector_summary="priority = medium",
        change_summary="priority -> high",
    )
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=9,
                status="COMPLETED",
                current_intent="change all medium priority job to high",
                replan_context={"intent_contract": {"no_op_mutations": [no_op]}},
            ),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-all-noop-read",
                completed_at=created_at + timedelta(seconds=2),
                rows=[],
                summary="No medium-priority jobs were found.",
            ),
        ]
    )
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert document["state"] == "completed"
    assert document["message"] == "No changes were made."
    assert not any(block["type"] == "approval_required" for block in document["blocks"])
    assert not any(step["kind"] == "approval" for step in document["run_steps"])
    assert not any(step["title"].startswith("Updated") for step in document["run_steps"])
    assert "fake success" not in document["message"].lower()
    assert "I updated" not in document["message"]
    result_summary = next(block for block in document["blocks"] if block["type"] == "result_summary")
    mutation = next(block for block in document["blocks"] if block["type"] == "mutation_result")
    assert result_summary["title"] == "No changes made"
    assert result_summary["total_count"] == 0
    assert result_summary["steps"][0]["step_number"] == 1
    assert result_summary["steps"][0]["business_change"] == "Not changed"
    assert result_summary["steps"][0]["summary"] == "Not changed: no matching jobs for priority = medium; priority -> high."
    assert result_summary["steps"][0]["record_count"] == 0
    assert result_summary["steps"][0]["status"] == "not_changed"
    assert result_summary["steps"][0]["contract"] == NO_OP_MUTATION_CONTRACT
    assert result_summary["steps"][0]["reason"] == "no_matching_records"
    assert mutation["title"] == "Not changed"
    assert mutation["rows"] == []
    assert mutation["groups"][0]["status"] == "not_changed"
    assert mutation["groups"][0]["reason"] == "no_matching_records"
    assert document["invariants"]["affected_record_count"] == 0
    assert document["invariants"]["approved_business_change_count"] == 0
    assert document["invariants"]["not_changed_group_count"] == 1
    assert document["invariants"]["no_op_mutation_contract"] == "entity_agnostic_no_matching_records_v1"

    approvals = (await db_session.execute(select(Approval).where(Approval.session_id == session_id))).scalars().all()
    write_steps = (
        await db_session.execute(
            select(PlanStep).where(PlanStep.session_id == session_id).where(PlanStep.requires_approval.is_(True))
        )
    ).scalars().all()
    assert approvals == []
    assert write_steps == []


@pytest.mark.asyncio
async def test_safe_non_job_noop_contract_proof_completes_without_approval(db_session):
    created_at = datetime(2026, 5, 18, 13, 50, 0)
    session_id = "rd-material-noop"
    plan_id = "rd-material-noop-plan"
    no_op = _noop_contract(
        entity_type="material",
        selector_summary="material_id = MAT-404",
        change_summary="hold_status -> quality_hold",
    )
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=9,
                status="COMPLETED",
                current_intent="Put material MAT-404 on quality hold",
                replan_context={"intent_contract": {"no_op_mutations": [no_op]}},
            ),
            _user_message(session_id=session_id, created_at=created_at, content="Put material MAT-404 on quality hold"),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-material-noop-read",
                completed_at=created_at + timedelta(seconds=2),
                rows=[],
                summary="No matching material was found.",
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    mutation = next(block for block in document["blocks"] if block["type"] == "mutation_result")
    group = mutation["groups"][0]

    assert document["state"] == "completed"
    assert document["message"] == "No changes were made."
    assert document["invariants"]["no_op_mutation_contract"] == NO_OP_MUTATION_CONTRACT
    assert document["invariants"]["not_changed_group_count"] == 1
    assert not any(block["type"] == "approval_required" for block in document["blocks"])
    assert not any(step["kind"] == "approval" for step in document["run_steps"])
    assert mutation["title"] == "Not changed"
    assert mutation["rows"] == []
    assert group["contract"] == NO_OP_MUTATION_CONTRACT
    assert group["business_change"] == "Not changed"
    assert group["entity_type"] == "material"
    assert group["selector_summary"] == "material_id = MAT-404"
    assert group["change_summary"] == "hold_status -> quality_hold"
    assert group["matched_count"] == 0
    assert group["changed_count"] == 0
    assert group["status"] == "not_changed"
    assert group["reason"] == "no_matching_records"

    approvals = (await db_session.execute(select(Approval).where(Approval.session_id == session_id))).scalars().all()
    write_steps = (
        await db_session.execute(
            select(PlanStep).where(PlanStep.session_id == session_id).where(PlanStep.requires_approval.is_(True))
        )
    ).scalars().all()
    assert approvals == []
    assert write_steps == []


@pytest.mark.asyncio
async def test_phase24_product_status_read_result_uses_entity_status_contract(db_session):
    created_at = datetime(2026, 5, 19, 9, 0, 0)
    session_id = "rd-phase24-product-status"
    plan_id = "rd-phase24-product-status-plan"
    prompt = "Show status for product P-RD-024"
    raw_assistant_markdown = (
        "done_all\n\n"
        "**Success**\n\n"
        "Product **P-RD-024** is currently **ACTIVE**.\n\n"
        "- **ProductID:** P-RD-024\n"
        "- **ProductName:** Pump Assembly\n"
        "- **InternalRouteID:** route-99"
    )
    product_payload = {
        "productID": "P-RD-024",
        "productName": "Pump Assembly",
        "status": "ACTIVE",
        "revision": "B",
        "internalRouteID": "route-99",
    }
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=10,
                status="COMPLETED",
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-phase24-product-status-read",
                completed_at=created_at + timedelta(seconds=2),
                rows=[],
                summary=raw_assistant_markdown,
                tool_name="get__products_{id}",
                args={"id": "P-RD-024"},
                result={"success": True, "data": product_payload},
            ),
            _assistant_message(
                session_id=session_id,
                content=raw_assistant_markdown,
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=3),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    status_block = next(block for block in document["blocks"] if block["type"] == "status_result")
    serialized = json.dumps(document)

    assert document["state"] == "completed"
    assert document["message"] == "Product P-RD-024 is active."
    assert document["invariants"]["read_result_shape"] == "status"
    assert document["invariants"]["read_status_contract"] == ENTITY_STATUS_CONTRACT
    assert document["invariants"]["read_status_entity_type"] == "product"
    assert [block["type"] for block in document["blocks"]].count("status_result") == 1
    assert not any(block["type"] in {"approval_required", "mutation_result", "result_table"} for block in document["blocks"])
    assert any(step["kind"] == "read" and step["title"] == "Read product status" for step in document["run_steps"])

    assert status_block["contract"] == ENTITY_STATUS_CONTRACT
    assert status_block["title"] == "Product status"
    assert status_block["entity_type"] == "product"
    assert status_block["entity_id"] == "P-RD-024"
    assert status_block["primary_status"] == "active"
    assert status_block["fields"] == [
        {"key": "product_id", "label": "Product ID", "value": "P-RD-024"},
        {"key": "status", "label": "Status", "value": "active", "primary": True},
    ]

    for forbidden in ["done_all", "**Success**", "ProductID", "ProductName", "InternalRouteID", "route-99"]:
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_phase24_material_partial_noop_plus_valid_group_uses_generic_contracts(db_session):
    created_at = datetime(2026, 5, 19, 9, 20, 0)
    session_id = "rd-phase24-material-partial-noop"
    plan_id = "rd-phase24-material-partial-noop-plan"
    approval_id = "approval-rd-phase24-material-valid"
    no_op = _noop_contract(
        entity_type="material",
        selector_summary="material_id = MAT-RD-404",
        change_summary="hold_status -> quality_hold",
    )
    staged_change = {
        "contract": BUSINESS_CHANGE_CONTRACT,
        "business_change_id": "bc-material-quality-hold",
        "business_change": "Material hold status",
        "entity_type": "material",
        "change_type": "update",
        "selector_summary": "material_id = MAT-RD-024",
        "source_state_basis": "current_state",
        "material_id": "MAT-RD-024",
        "display_id": "Material MAT-RD-024",
        "field_changes": [
            {
                "field": "hold_status",
                "label": "Hold status",
                "from": "available",
                "to": "quality_hold",
            }
        ],
        "status": "pending",
    }
    applied_change = {**staged_change, "status": "succeeded"}
    approval_args = {
        "summary": "Put one material on quality hold.",
        "count": 1,
        "no_op_mutations": [no_op],
        "bundle_ui": {
            "kind": "phase24_material_partial_noop",
            "write_set": "material_quality_hold",
            "headline": "Put 1 material on quality hold",
            "rows": [staged_change],
        },
    }
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=13,
                status="WAITING_APPROVAL",
                current_intent="Put material MAT-RD-024 and MAT-RD-404 on quality hold",
            ),
            _user_message(
                session_id=session_id,
                created_at=created_at,
                content="Put material MAT-RD-024 and MAT-RD-404 on quality hold",
            ),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _approval(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                approval_id=approval_id,
                status="PENDING",
                args=approval_args,
                risk_summary="Put 1 material on quality hold",
                created_offset_s=3,
            ),
        ]
    )
    await db_session.commit()

    waiting = (await _snapshot(db_session, session_id))["response_document"]
    approval_block = next(block for block in waiting["blocks"] if block["type"] == "approval_required")
    noop_block = next(block for block in waiting["blocks"] if block["type"] == "completed_step")

    assert waiting["state"] == "waiting_approval"
    assert "Not changed" in waiting["message"]
    assert "no matching materials for material_id = MAT-RD-404" in waiting["message"]
    assert approval_block["approval_id"] == approval_id
    assert [row["row_id"] for row in approval_block["rows"]] == ["MAT-RD-024"]
    assert "MAT-RD-404" not in json.dumps(approval_block)
    assert "no matching materials for material_id = MAT-RD-404" in noop_block["summary"]

    approval = await db_session.get(Approval, approval_id)
    assert approval is not None
    approval.status = "APPROVED"
    approval.decided_at = created_at + timedelta(seconds=4)
    approval.decided_by = "operator"
    session = await db_session.get(Session, session_id)
    assert session is not None
    session.status = "COMPLETED"
    session.completed_at = created_at + timedelta(seconds=6)
    session.updated_at = created_at + timedelta(seconds=6)
    session.event_seq = 17
    db_session.add(
        _write_step(
            session_id=session_id,
            plan_id=plan_id,
            step_id="rd-phase24-material-valid-write",
            step_index=0,
            completed_at=created_at + timedelta(seconds=5),
            approval_id=approval_id,
            outcomes=[applied_change],
            tool_name="put__materials_{id}",
            args={"write_set": "material_quality_hold", "id": "MAT-RD-024", "hold_status": "quality_hold"},
        )
    )
    await db_session.commit()

    final = (await _snapshot(db_session, session_id))["response_document"]
    result_summary = next(block for block in final["blocks"] if block["type"] == "result_summary")
    mutation = next(block for block in final["blocks"] if block["type"] == "mutation_result")
    not_changed_group, changed_group = mutation["groups"]
    changed_row = mutation["rows"][0]

    assert final["state"] == "completed"
    assert final["message"] == (
        "Done. I updated 1 material across 1 approved business change. "
        "1 business change not changed because no matching records were found."
    )
    assert final["invariants"]["mutation_business_contract"] == BUSINESS_CHANGE_CONTRACT
    assert final["invariants"]["no_op_mutation_contract"] == NO_OP_MUTATION_CONTRACT
    assert final["invariants"]["not_changed_group_count"] == 1
    assert final["invariants"]["no_op_mutation_count"] == 1
    assert final["invariants"]["affected_record_count"] == 1
    assert final["invariants"]["approved_business_change_count"] == 1
    assert not any(block["type"] == "approval_required" for block in final["blocks"])

    assert result_summary["steps"][0]["contract"] == NO_OP_MUTATION_CONTRACT
    assert result_summary["steps"][0]["entity_type"] == "material"
    assert result_summary["steps"][0]["matched_count"] == 0
    assert result_summary["steps"][0]["changed_count"] == 0
    assert result_summary["steps"][0]["reason"] == "no_matching_records"
    assert result_summary["steps"][1]["contract"] == BUSINESS_CHANGE_CONTRACT
    assert result_summary["steps"][1]["entity_type"] == "material"
    assert result_summary["steps"][1]["field_changes"] == staged_change["field_changes"]

    assert mutation["contract"] == BUSINESS_CHANGE_CONTRACT
    assert not_changed_group["contract"] == NO_OP_MUTATION_CONTRACT
    assert not_changed_group["rows"] == []
    assert not_changed_group["entity_type"] == "material"
    assert not_changed_group["selector_summary"] == "material_id = MAT-RD-404"
    assert not_changed_group["change_summary"] == "hold_status -> quality_hold"
    assert not_changed_group["matched_count"] == 0
    assert not_changed_group["changed_count"] == 0
    assert changed_group["contract"] == BUSINESS_CHANGE_CONTRACT
    assert changed_group["business_change_id"] == "bc-material-quality-hold"
    assert changed_group["entity_type"] == "material"
    assert changed_group["selector_summary"] == "material_id = MAT-RD-024"
    assert changed_group["source_state_basis"] == "current_state"
    assert changed_group["field_changes"] == staged_change["field_changes"]
    assert changed_row["record_id"] == "MAT-RD-024"
    assert changed_row["display_id"] == "Material MAT-RD-024"
    assert changed_row["entity_type"] == "material"
    assert changed_row["outcome"] == "succeeded"
    assert changed_row["field_changes"] == staged_change["field_changes"]
    assert "job_id" not in changed_row
    assert "priority" not in json.dumps(final).lower()

    write_steps = (
        await db_session.execute(
            select(PlanStep).where(PlanStep.session_id == session_id).where(PlanStep.requires_approval.is_(True))
        )
    ).scalars().all()
    assert len(write_steps) == 1
    assert write_steps[0].tool_name == "put__materials_{id}"
    assert "MAT-RD-404" not in json.dumps([step.result for step in write_steps], default=str)


@pytest.mark.asyncio
async def test_read_only_result_shape_is_deterministic_for_table_and_list(db_session):
    created_at = datetime(2026, 5, 18, 14, 0, 0)
    table_session = "rd-read-table"
    table_plan = "rd-read-table-plan"
    list_session = "rd-read-list"
    list_plan = "rd-read-list-plan"
    db_session.add_all(
        [
            _session(
                session_id=table_session,
                plan_id=table_plan,
                created_at=created_at,
                event_seq=6,
                status="COMPLETED",
                current_intent="Show low priority jobs",
            ),
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
    assert table_body["response_document"]["invariants"]["read_scope"] == "records"
    assert table_body["response_document"]["invariants"]["display_mode"] == "collapsed_collection_table"
    assert table_body["response_document"]["invariants"]["entity_count"] == 6
    assert table_body["response_document"]["invariants"]["preview_limit"] == 5
    table = next(block for block in table_body["response_document"]["blocks"] if block["type"] == "result_table")
    block_types = [block["type"] for block in table_body["response_document"]["blocks"]]
    assert table["title"] == "Results"
    assert table["display_mode"] == "collapsed_collection_table"
    assert table["entity_count"] == 6
    assert table["preview_limit"] == 5
    assert table["details_collapsed"] is True
    assert block_types.count("result_table") == 1
    assert not any(block["type"] == "record_preview" and block["title"] == "Preview" for block in table_body["response_document"]["blocks"])
    assert list_body["response_document"]["invariants"]["read_result_shape"] == "list"
    assert any(block["type"] == "record_preview" and block["title"] == "Results" for block in list_body["response_document"]["blocks"])
    assert not any(block["type"] == "approval_required" for block in table_body["response_document"]["blocks"])


@pytest.mark.asyncio
async def test_machine_status_read_only_response_uses_typed_status_contract(db_session):
    created_at = datetime(2026, 5, 18, 14, 30, 0)
    session_id = "rd-machine-status"
    plan_id = "rd-machine-status-plan"
    raw_assistant_markdown = (
        "done_all\n\n"
        "**Success**\n\n"
        "Machine **M-CNC-01** is currently **RUNNING**.\n\n"
        "- **Machineid:** M-CNC-01\n"
        "- **Machinename:** CNC Mill 01\n"
        "- **Capacityperhour:** 40\n"
        "- **Defaultsetuptime:** 0\n"
        "- **Defaultcleaningtime:** 0\n"
        "- **Defaultchangeovertime:** 0\n"
        "- **Utilizationrate:** 0"
    )
    machine_payload = {
        "machineID": "M-CNC-01",
        "machineName": "CNC Mill 01",
        "machineType": "CNC mill",
        "location": "Line 1",
        "status": "RUNNING",
        "capacityPerHour": 40,
        "lastMaintenanceDate": "2026-05-01",
        "maintenanceIntervalDays": 30,
        "defaultSetupTime": 0,
        "defaultCleaningTime": 0,
        "defaultChangeoverTime": 0,
        "utilizationRate": 0,
    }
    prompt = "Show status for machine with machine id M-CNC-01"
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=8,
                status="COMPLETED",
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-machine-status-step",
                completed_at=created_at + timedelta(seconds=2),
                rows=[],
                summary=raw_assistant_markdown,
                tool_name="get__machines_{id}",
                args={"id": "M-CNC-01"},
                result={"success": True, "data": machine_payload},
            ),
            _assistant_message(
                session_id=session_id,
                content=raw_assistant_markdown,
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=3),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    serialized = json.dumps(document)

    assert document["state"] == "completed"
    assert document["message"] == "Machine M-CNC-01 is running."
    assert document["summary"] == "Machine M-CNC-01 is running."
    assert document["invariants"]["read_result_shape"] == "status"
    assert document["invariants"]["read_status_contract"] == "entity_status_v1"
    assert document["invariants"]["read_status_entity_type"] == "machine"
    assert [block["type"] for block in document["blocks"]].count("short_message") == 1
    assert [block["type"] for block in document["blocks"]].count("status_result") == 1
    assert not any(block["type"] in {"approval_required", "mutation_result", "result_table", "record_preview"} for block in document["blocks"])

    status_block = next(block for block in document["blocks"] if block["type"] == "status_result")
    assert status_block["contract"] == ENTITY_STATUS_CONTRACT
    assert status_block["title"] == "Machine status"
    assert status_block["summary"] == "Machine M-CNC-01 is running."
    assert status_block["entity_type"] == "machine"
    assert status_block["entity_id"] == "M-CNC-01"
    assert status_block["primary_status"] == "running"
    assert status_block["read_scope"] == "status_only"
    assert status_block["requested_fields"] == ["machine_id", "status"]
    assert status_block["display_mode"] == "compact_status_card"
    assert status_block["entity_count"] == 1
    assert status_block["preview_limit"] == 5
    assert status_block["details_collapsed"] is True
    assert [(field["label"], field["value"]) for field in status_block["fields"]] == [
        ("Machine ID", "M-CNC-01"),
        ("Status", "running"),
    ]
    assert status_block["secondary_fields"] == []
    assert any(step["kind"] == "read" and step["title"] == "Read machine status" for step in document["run_steps"])

    for forbidden in [
        "done_all",
        "**Success**",
        "Machineid",
        "Machinename",
        "Capacityperhour",
        "Defaultsetuptime",
        "Defaultcleaningtime",
        "Defaultchangeovertime",
        "Utilizationrate",
        "Machine name",
        "Machine type",
        "Location",
        "Capacity per hour",
        "Last maintenance",
        "Maintenance interval",
        "CNC Mill 01",
        "CNC mill",
        "Line 1",
    ]:
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_phase13_mixed_read_summary_and_collection_identity_fields(db_session):
    created_at = datetime(2026, 5, 19, 8, 30, 0)
    session_id = "rd-phase13-mixed-read"
    plan_id = "rd-phase13-mixed-read-plan"
    prompt = (
        "Show M-CNC-01 status, then show JOB-SEED-001 status, then list the next 3 low priority jobs sorted by deadline."
    )
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=11,
                status="COMPLETED",
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-phase13-machine-status",
                completed_at=created_at + timedelta(seconds=2),
                rows=[],
                summary="Machine status retrieved.",
                tool_name="get__machines_{id}",
                args={"id": "M-CNC-01", "fields": "status"},
                result={"success": True, "data": {"machine_id": "M-CNC-01", "status": "running", "location": "Line 1"}},
            ),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-phase13-job-status",
                completed_at=created_at + timedelta(seconds=3),
                rows=[],
                summary="Job status retrieved.",
                tool_name="get__jobs_{id}",
                args={"id": "JOB-SEED-001", "fields": "status"},
                result={"success": True, "data": {"job_id": "JOB-SEED-001", "status": "queued", "priority": "high"}},
            ),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-phase13-low-jobs",
                completed_at=created_at + timedelta(seconds=4),
                rows=[
                    {"job_id": "JOB-RD-LOW-001", "priority": "low", "status": "planned", "deadline": "2026-05-21"},
                    {"job_id": "JOB-RD-LOW-002", "priority": "low", "status": "queued", "deadline": "2026-05-22"},
                    {"job_id": "JOB-RD-LOW-003", "priority": "low", "status": "ready", "deadline": "2026-05-23"},
                ],
                summary="Found 3 low-priority jobs. Details are shown in the table below.",
                tool_name="get__jobs",
                args={"priority": "low", "fields": "deadline", "sort_by": "deadline", "sort_dir": "asc", "limit": 3},
            ),
            _assistant_message(
                session_id=session_id,
                content="Found 3 low-priority jobs. Details are shown in the table below.",
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=5),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]

    assert document["state"] == "completed"
    assert "Machine M-CNC-01 is running" in document["message"]
    assert "Job JOB-SEED-001 is queued" in document["message"]
    assert "Found 3 low-priority jobs sorted by deadline" in document["message"]
    assert document["message"] != "Found 3 low-priority jobs. Details are shown in the table below."
    assert document["summary"] == document["message"]
    assert document["invariants"]["sort_fields"] is None
    block_types = [block["type"] for block in document["blocks"]]
    machine_index = next(
        index
        for index, block in enumerate(document["blocks"])
        if block["type"] == "status_result" and block["entity_type"] == "machine"
    )
    job_index = next(
        index
        for index, block in enumerate(document["blocks"])
        if block["type"] == "status_result" and block["entity_type"] == "job"
    )
    table_index = next(index for index, block in enumerate(document["blocks"]) if block["type"] == "result_table")
    assert machine_index < job_index < table_index
    assert block_types.count("status_result") == 2
    assert block_types.count("result_table") == 1
    assert not any(block["type"] == "approval_required" for block in document["blocks"])

    machine_block = document["blocks"][machine_index]
    job_block = document["blocks"][job_index]
    table = document["blocks"][table_index]
    assert machine_block["requested_fields"] == ["machine_id", "status"]
    assert job_block["requested_fields"] == ["job_id", "status"]
    assert table["entity_type"] == "job"
    assert table["requested_fields"] == ["deadline"]
    assert [list(row.keys()) for row in table["rows"]] == [["job_id", "deadline"]] * 3
    assert [row["deadline"] for row in table["rows"]] == ["2026-05-21", "2026-05-22", "2026-05-23"]


@pytest.mark.asyncio
async def test_phase37_status_only_projection_matrix_covers_machine_and_job(db_session):
    created_at = datetime(2026, 5, 19, 9, 0, 0)
    cases = [
        {
            "session_id": "rd-027-machine-status-only",
            "plan_id": "rd-027-machine-status-only-plan",
            "prompt": "Show status for machine with machine id M-CNC-01",
            "tool_name": "get__machines_{id}",
            "args": {"id": "M-CNC-01"},
            "payload": {
                "machineID": "M-CNC-01",
                "machineName": "CNC Mill 01",
                "machineType": "CNC mill",
                "location": "Line 1",
                "status": "RUNNING",
                "capacityPerHour": 40,
                "lastMaintenanceDate": "2026-05-01",
                "maintenanceIntervalDays": 30,
            },
            "expected_title": "Machine status",
            "expected_fields": [("machine_id", "Machine ID", "M-CNC-01"), ("status", "Status", "running")],
            "forbidden_labels": [
                "Machine name",
                "Machine type",
                "Location",
                "Capacity per hour",
                "Last maintenance",
                "Maintenance interval",
            ],
        },
        {
            "session_id": "rd-027-job-status-only",
            "plan_id": "rd-027-job-status-only-plan",
            "prompt": "find status for job with job id JOB-SEED-001",
            "tool_name": "get__jobs_{id}",
            "args": {"id": "JOB-SEED-001"},
            "payload": {
                "jobID": "JOB-SEED-001",
                "priority": "high",
                "machineID": "M-CNC-01",
                "status": "RUNNING",
                "dueDate": "2026-05-20",
            },
            "expected_title": "Job status",
            "expected_fields": [("job_id", "Job ID", "JOB-SEED-001"), ("status", "Status", "running")],
            "forbidden_labels": ["Priority", "Machine ID", "Due date"],
        },
    ]
    for index, case in enumerate(cases):
        db_session.add_all(
            [
                _session(
                    session_id=case["session_id"],
                    plan_id=case["plan_id"],
                    created_at=created_at + timedelta(minutes=index),
                    event_seq=8,
                    status="COMPLETED",
                    current_intent=case["prompt"],
                ),
                _user_message(
                    session_id=case["session_id"],
                    created_at=created_at + timedelta(minutes=index),
                    content=case["prompt"],
                ),
                _plan(
                    session_id=case["session_id"],
                    plan_id=case["plan_id"],
                    created_at=created_at + timedelta(minutes=index, seconds=1),
                ),
                _read_step(
                    session_id=case["session_id"],
                    plan_id=case["plan_id"],
                    step_id=f"{case['session_id']}-step",
                    completed_at=created_at + timedelta(minutes=index, seconds=2),
                    rows=[],
                    summary="Raw backend details should not drive status-only display.",
                    tool_name=case["tool_name"],
                    args=case["args"],
                    result={"success": True, "data": case["payload"]},
                ),
                _assistant_message(
                    session_id=case["session_id"],
                    content="Raw backend details should not drive status-only display.",
                    step_id=case["plan_id"],
                    created_at=created_at + timedelta(minutes=index, seconds=3),
                ),
            ]
        )
    await db_session.commit()

    for case in cases:
        document = (await _snapshot(db_session, case["session_id"]))["response_document"]
        status_block = next(block for block in document["blocks"] if block["type"] == "status_result")

        assert status_block["title"] == case["expected_title"]
        assert status_block["read_scope"] == "status_only"
        assert status_block["display_mode"] == "compact_status_card"
        assert status_block["entity_count"] == 1
        assert [(field["key"], field["label"], field["value"]) for field in status_block["fields"]] == case["expected_fields"]
        assert status_block["requested_fields"] == [case["expected_fields"][0][0], "status"]
        assert status_block["secondary_fields"] == []
        serialized = json.dumps(status_block)
        for forbidden in case["forbidden_labels"]:
            assert forbidden not in serialized


@pytest.mark.asyncio
async def test_hard_query_collection_requested_fields_project_result_table(db_session):
    created_at = datetime(2026, 5, 19, 9, 20, 0)
    session_id = "rd-hard-query-low-priority-fields"
    plan_id = "rd-hard-query-low-priority-fields-plan"
    prompt = "List low priority jobs, only job id and deadline, sorted by deadline ascending, limit 3."
    rows = [
        {
            "job_id": "JOB-RD-001",
            "priority": "low",
            "product_id": "P-001",
            "status": "planned",
            "deadline": "2026-05-21",
        },
        {
            "job_id": "JOB-RD-002",
            "priority": "low",
            "product_id": "P-002",
            "status": "planned",
            "deadline": "2026-05-22",
        },
        {
            "job_id": "JOB-RD-003",
            "priority": "low",
            "product_id": "P-003",
            "status": "ready",
            "deadline": "2026-05-23",
        },
    ]
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=8,
                status="COMPLETED",
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-hard-query-low-priority-fields-step",
                completed_at=created_at + timedelta(seconds=2),
                rows=rows,
                summary="Low priority jobs retrieved.",
                tool_name="get__jobs",
                args={
                    "priority": "low",
                    "fields": "job_id,deadline",
                    "sort_by": "deadline",
                    "sort_dir": "asc",
                    "limit": 3,
                },
            ),
            _assistant_message(
                session_id=session_id,
                content="Low priority jobs retrieved.",
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=3),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]

    assert document["invariants"]["read_scope"] == "records"
    assert document["invariants"]["requested_fields"] == ["job_id", "deadline"]
    assert document["invariants"]["display_mode"] == "collection_table"
    table = next(block for block in document["blocks"] if block["type"] == "result_table")
    assert table["read_scope"] == "records"
    assert table["requested_fields"] == ["job_id", "deadline"]
    assert table["display_mode"] == "collection_table"
    assert table["entity_type"] == "job"
    assert len(table["rows"]) == 3
    assert [list(row.keys()) for row in table["rows"]] == [["job_id", "deadline"]] * 3
    serialized_rows = json.dumps(table["rows"])
    assert "priority" not in serialized_rows
    assert "product_id" not in serialized_rows
    assert "status" not in serialized_rows


@pytest.mark.asyncio
async def test_parallel_read_response_document_preserves_step_order_over_completion_order(db_session):
    created_at = datetime(2026, 5, 29, 18, 49, 0)
    session_id = "rd-parallel-job-read-order"
    plan_id = "rd-parallel-job-read-order-plan"
    prompt = "Read jobs JOB-SEED-001, JOB-SEED-002, and JOB-SEED-003."
    job_ids = ["JOB-SEED-001", "JOB-SEED-002", "JOB-SEED-003"]
    completion_offsets = {
        "JOB-SEED-001": 30,
        "JOB-SEED-002": 10,
        "JOB-SEED-003": 20,
    }
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=8,
                status="COMPLETED",
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            *[
                _read_step(
                    session_id=session_id,
                    plan_id=plan_id,
                    step_id=f"rd-parallel-job-read-order-step-{index}",
                    step_index=index,
                    completed_at=created_at + timedelta(seconds=completion_offsets[job_id]),
                    rows=[],
                    summary=f"Found job {job_id}.",
                    tool_name="get__jobs_{id}",
                    args={"id": job_id},
                    result={
                        "success": True,
                        "data": {
                            "job_id": job_id,
                            "product_id": f"P-00{index + 1}",
                            "priority": "high" if index != 1 else "medium",
                            "status": "planned",
                        },
                    },
                )
                for index, job_id in enumerate(job_ids)
            ],
            _assistant_message(
                session_id=session_id,
                content="Found 1 job. Found 1 job. Found 1 job.",
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=31),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    read_blocks = [
        block
        for block in document["blocks"]
        if block["type"] in {"record_preview", "result_table", "status_result"}
    ]
    rendered_job_ids: list[str] = []
    for block in read_blocks:
        if block["type"] == "status_result":
            rendered_job_ids.append(block["entity_id"])
            continue
        rendered_job_ids.extend(
            row["job_id"]
            for row in block.get("rows", [])
            if row.get("job_id")
        )

    assert rendered_job_ids == job_ids
    read_steps = [step for step in document["run_steps"] if step["kind"] == "read"]
    assert len(read_steps) == 1
    assert read_steps[0]["title"] == "Read 3 job records"
    assert read_steps[0]["summary"] == "Found 3 jobs."
    assert read_steps[0]["record_count"] == 3


@pytest.mark.asyncio
async def test_mixed_parallel_status_blocks_preserve_step_order_over_completion_order(db_session):
    created_at = datetime(2026, 5, 29, 19, 4, 0)
    session_id = "rd-mixed-parallel-status-order"
    plan_id = "rd-mixed-parallel-status-order-plan"
    prompt = "Read machine M-CNC-01 status and job JOB-SEED-001 status."
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=8,
                status="COMPLETED",
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-mixed-parallel-status-order-step-0",
                step_index=0,
                completed_at=created_at + timedelta(seconds=20),
                rows=[],
                summary="Machine M-CNC-01 is running.",
                tool_name="get__machines_{id}",
                args={"id": "M-CNC-01"},
                result={"success": True, "data": {"machine_id": "M-CNC-01", "status": "running"}},
            ),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-mixed-parallel-status-order-step-1",
                step_index=1,
                completed_at=created_at + timedelta(seconds=10),
                rows=[],
                summary="Job JOB-SEED-001 is planned.",
                tool_name="get__jobs_{id}",
                args={"id": "JOB-SEED-001"},
                result={"success": True, "data": {"job_id": "JOB-SEED-001", "status": "planned"}},
            ),
            _assistant_message(
                session_id=session_id,
                content="Machine M-CNC-01 is running. Job JOB-SEED-001 is planned.",
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=21),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    status_blocks = [block for block in document["blocks"] if block["type"] == "status_result"]

    assert [block["entity_id"] for block in status_blocks] == ["M-CNC-01", "JOB-SEED-001"]


@pytest.mark.asyncio
async def test_phase37_details_prompt_keeps_secondary_fields_collapsed(db_session):
    created_at = datetime(2026, 5, 19, 9, 30, 0)
    session_id = "rd-029-machine-details"
    plan_id = "rd-029-machine-details-plan"
    prompt = "Show full details for machine with machine id M-CNC-01"
    machine_payload = {
        "machineID": "M-CNC-01",
        "machineName": "CNC Mill 01",
        "machineType": "CNC mill",
        "location": "Line 1",
        "status": "RUNNING",
        "capacityPerHour": 40,
        "lastMaintenanceDate": "2026-05-01",
        "maintenanceIntervalDays": 30,
    }
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=8,
                status="COMPLETED",
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-029-machine-details-step",
                completed_at=created_at + timedelta(seconds=2),
                rows=[],
                summary="Machine details retrieved.",
                tool_name="get__machines_{id}",
                args={"id": "M-CNC-01"},
                result={"success": True, "data": machine_payload},
            ),
            _assistant_message(
                session_id=session_id,
                content="Machine details retrieved.",
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=3),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    status_block = next(block for block in document["blocks"] if block["type"] == "status_result")

    assert status_block["read_scope"] == "details"
    assert status_block["requested_fields"] == ["machine_id", "status", "details"]
    assert status_block["display_mode"] == "detail_status_card"
    assert [(field["key"], field["value"]) for field in status_block["fields"]] == [
        ("machine_id", "M-CNC-01"),
        ("status", "running"),
    ]
    assert status_block["details_collapsed"] is True
    secondary = {field["key"]: field["value"] for field in status_block["secondary_fields"]}
    assert secondary["machine_name"] == "CNC Mill 01"
    assert secondary["machine_type"] == "CNC mill"
    assert secondary["location"] == "Line 1"
    assert secondary["capacity_per_hour"] == "40"
    assert secondary["last_maintenance_date"] == "2026-05-01"
    assert secondary["maintenance_interval_days"] == "30"


@pytest.mark.asyncio
async def test_phase37_multi_entity_status_read_returns_typed_collection_without_loop_shape(db_session):
    created_at = datetime(2026, 5, 19, 10, 0, 0)
    session_id = "rd-028-multi-job-status"
    plan_id = "rd-028-multi-job-status-plan"
    prompt = "find status for job with job id JOB-SEED-001 and JOB-SEED-002"
    raw_multi_status_answer = (
        "**Success** Job **P-001** is currently **planned**.\n"
        "- **Job ID:** JOB-SEED-001\n"
        "- **Product ID:** P-001\n"
        "- **Priority:** low\n"
        "- **Deadline:** 2026-06-02T08:00:00+08:00\n\n"
        "**Success** Job **P-002** is currently **planned**.\n"
        "- **Job ID:** JOB-SEED-002\n"
        "- **Product ID:** P-002\n"
        "- **Priority:** low\n"
        "- **Deadline:** 2026-06-02T08:00:00+08:00"
    )
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=9,
                status="COMPLETED",
                step_count=2,
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-028-job-1",
                completed_at=created_at + timedelta(seconds=2),
                rows=[],
                summary=raw_multi_status_answer,
                tool_name="get__jobs_{id}",
                args={"id": "JOB-SEED-001"},
                result={"success": True, "data": {"jobID": "JOB-SEED-001", "priority": "high", "status": "RUNNING"}},
            ),
            _read_step(
                session_id=session_id,
                plan_id=plan_id,
                step_id="rd-028-job-2",
                completed_at=created_at + timedelta(seconds=3),
                rows=[],
                summary=raw_multi_status_answer,
                tool_name="get__jobs_{id}",
                args={"id": "JOB-SEED-002"},
                result={"success": True, "data": {"jobID": "JOB-SEED-002", "priority": "medium", "status": "PLANNED"}},
            ),
            _assistant_message(
                session_id=session_id,
                content=raw_multi_status_answer,
                step_id=plan_id,
                created_at=created_at + timedelta(seconds=4),
            ),
        ]
    )
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    table = next(block for block in document["blocks"] if block["type"] == "result_table")

    assert document["state"] == "completed"
    assert document["invariants"]["read_status_contract"] == ENTITY_STATUS_CONTRACT
    assert document["invariants"]["read_scope"] == "status_only"
    assert document["invariants"]["requested_fields"] == ["job_id", "status"]
    assert document["invariants"]["display_mode"] == "collection_table"
    assert document["invariants"]["entity_count"] == 2
    assert table["contract"] == ENTITY_STATUS_CONTRACT
    assert table["read_scope"] == "status_only"
    assert table["requested_fields"] == ["job_id", "status"]
    assert table["display_mode"] == "collection_table"
    assert table["entity_type"] == "job"
    assert table["entity_count"] == 2
    assert table["details_collapsed"] is False
    assert table["rows"] == [
        {"job_id": "JOB-SEED-001", "status": "running"},
        {"job_id": "JOB-SEED-002", "status": "planned"},
    ]
    short_message = next(block for block in document["blocks"] if block["type"] == "short_message")
    assert document["message"] == "Found 2 job statuses."
    assert short_message["message"] == "Found 2 job statuses."
    serialized = json.dumps(document)
    assert "**Success**" not in serialized
    assert "Product ID" not in serialized
    assert "Priority" not in serialized
    assert "Deadline" not in serialized
    assert not any(block["type"] == "diagnostic" for block in document["blocks"])


@pytest.mark.asyncio
async def test_rag_response_document_includes_knowledge_answer_and_source_blocks(db_session):
    created_at = datetime(2026, 5, 18, 15, 0, 0)
    session_id = "rd-rag-sources"
    plan_id = "rd-rag-plan"
    answer = (
        ":::safety\n"
        "**SAFETY WARNING**: legacy markdown should not be visible.\n"
        ":::\n\n"
        "Notify affected employees before lockout starts [^1].\n\n"
        "[^1]: LOTO notification requirements."
    )
    source = {
        "machine_id": "M-CNC-01",
        "job_id": "JOB-SEED-001",
        "procedure_id": "LOTO-M-CNC-01",
        "title": "LOTO procedure",
        "organization": "Factory Safety",
        "file_path": "C:/local/docs/loto.pdf",
        "pdf_url": "/documents/LOTO-M-CNC-01/pdf",
        "page": 9,
        "char_range": [120, 188],
        "text_search": "Notify affected employees before lockout starts.",
    }
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=7, status="COMPLETED"),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content=answer,
                step_id=plan_id,
                tool_name="__conversation__",
                created_at=created_at + timedelta(seconds=2),
            ),
        ]
    )
    plan = await db_session.get(Plan, plan_id)
    assert plan is not None
    plan.sources = [source]
    plan.safety_content = "This topic involves high-risk industrial procedures. Follow the site-approved SOP before acting."
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert body["presentation"]["kind"] == "knowledge_answer"
    safety_block = next(block for block in document["blocks"] if block["type"] == "safety_notice")
    assert safety_block["contract"] == "safety_notice_v1"
    assert "site-approved SOP" in safety_block["safety_content"]
    assert ":::safety" not in safety_block["safety_content"]
    knowledge_block = next(block for block in document["blocks"] if block["type"] == "knowledge_answer")
    assert knowledge_block["contract"] == "knowledge_answer_v1"
    assert knowledge_block["answer"] == "Notify affected employees before lockout starts."
    assert "[^1]" not in knowledge_block["answer"]
    assert knowledge_block["segments"] == [
        {
            "text": "Notify affected employees before lockout starts.",
            "citation_ids": [knowledge_block["citations"][0]["citation_id"]],
        }
    ]
    assert knowledge_block["citations"][0]["contract"] == "source_citation_v1"
    assert knowledge_block["citations"][0]["doc_id"] == "LOTO-M-CNC-01"
    assert knowledge_block["citations"][0]["chunk_id"]
    assert knowledge_block["citations"][0]["pdf_url"] == "/documents/LOTO-M-CNC-01/pdf"
    assert knowledge_block["citations"][0]["page"] == 9
    assert knowledge_block["citations"][0]["char_range"] == [120, 188]
    assert knowledge_block["citations"][0]["text_search"] == "Notify affected employees before lockout starts."
    assert document["message"] != knowledge_block["answer"]
    assert document["message"] == "I found a source-backed answer."
    assert ":::safety" not in json.dumps(document)
    assert "[^1]" not in json.dumps(document)
    source_block = next(block for block in document["blocks"] if block["type"] == "source_list")
    assert source_block["contract"] == "source_list_v1"
    assert source_block["sources"][0]["procedure_id"] == "LOTO-M-CNC-01"
    source_payload = source_block["sources"][0]
    assert source_payload["contract"] == "source_locator_v1"
    for key in ("source_id", "source_number", "doc_id", "chunk_id", "title", "organization", "snippet"):
        assert source_payload[key]
    assert source_payload["job_id"] == "JOB-SEED-001"
    assert "file_path" not in source_payload
    assert source_payload["pdf_url"] == "/documents/LOTO-M-CNC-01/pdf"
    assert source_payload["page"] == 9
    assert source_payload["char_range"] == [120, 188]
    assert source_payload["text_search"] == "Notify affected employees before lockout starts."
    assert "C:/local/docs" not in json.dumps(document)
    assert any(step["kind"] == "knowledge" for step in document["run_steps"])
    completed_step = next(step for step in document["run_steps"] if step["kind"] == "completed")
    assert completed_step["summary"] == "Source-backed answer is ready."


def test_knowledge_answer_payload_keeps_procedure_steps_as_cited_segments():
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#c0027",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "c0027",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "Before beginning service or maintenance, steps must be completed in sequence.",
    }
    answer = (
        "1. Prepare for shutdown.[^1]\n"
        "2. Shut down the machine.[^1]\n"
        "3. Disconnect or isolate energy sources.[^1]"
    )

    clean_answer, segments, citations = _knowledge_answer_payload(answer, [source])

    assert clean_answer == (
        "1. Prepare for shutdown.\n"
        "2. Shut down the machine.\n"
        "3. Disconnect or isolate energy sources."
    )
    assert [segment["text"] for segment in segments] == [
        "1. Prepare for shutdown.",
        "2. Shut down the machine.",
        "3. Disconnect or isolate energy sources.",
    ]
    assert len(citations) == 3
    assert len({citation["citation_id"] for citation in citations}) == 3
    assert {citation["source_id"] for citation in citations} == {"osha_3120_lockout_tagout#c0027"}
    assert [segment["citation_ids"] for segment in segments] == [[citation["citation_id"]] for citation in citations]


def test_knowledge_answer_payload_flattens_grouped_procedure_intro_into_step_segments():
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#c0027",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "c0027",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "Before beginning service or maintenance, steps must be completed in sequence.",
    }
    answer = (
        "Before beginning service or maintenance, workers must complete the following steps in sequence "
        "according to the employer's energy-control procedure:\n"
        "1. Prepare for shutdown;\n"
        "2. Shut down the machine;\n"
        "3. Disconnect or isolate the machine from the energy source(s).[^1]"
    )

    clean_answer, segments, citations = _knowledge_answer_payload(answer, [source])

    assert clean_answer == (
        "1. Prepare for shutdown.\n"
        "2. Shut down the machine.\n"
        "3. Disconnect or isolate the machine from the energy source(s)."
    )
    assert "I do not have enough retrieved evidence" not in clean_answer
    assert [segment["text"] for segment in segments] == [
        "1. Prepare for shutdown.",
        "2. Shut down the machine.",
        "3. Disconnect or isolate the machine from the energy source(s).",
    ]
    assert len(citations) == 3
    assert len({citation["citation_id"] for citation in citations}) == 3


def test_knowledge_answer_payload_flattens_live_single_citation_procedure_shape():
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#rse-c0015",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "Before beginning service or maintenance, the following steps must be accomplished in sequence.",
        "page": 13,
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "char_range": [120, 260],
        "text_search": "Before beginning service or maintenance, the following steps must be accomplished in sequence",
    }
    answer = (
        "1. Prepare for shutdown. 2. Shut down the machine. "
        "3. Disconnect or isolate the machine from the energy source(s). "
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s). "
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy. "
        "If a possibility exists for reaccumulation of hazardous energy, regularly verify during the service "
        "and maintenance that such energy has not reaccumulated to hazardous levels. "
        "These steps must be accomplished in sequence and according to the specific provisions of the "
        "employer's energy-control procedure.[^1]"
    )

    clean_answer, segments, citations = _knowledge_answer_payload(answer, [source])

    assert clean_answer == (
        "1. Prepare for shutdown.\n"
        "2. Shut down the machine.\n"
        "3. Disconnect or isolate the machine from the energy source(s).\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s).\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy.\n"
        "6. If a possibility exists for reaccumulation of hazardous energy, regularly verify during the service "
        "and maintenance that such energy has not reaccumulated to hazardous levels."
    )
    assert [segment["text"] for segment in segments] == clean_answer.splitlines()
    assert len(citations) == 6
    assert len({citation["citation_id"] for citation in citations}) == 6
    assert all(citation["page"] == 13 for citation in citations)
    assert "These steps must be accomplished" not in json.dumps({"segments": segments, "citations": citations})


def test_knowledge_answer_payload_uses_claim_specific_evidence_locator():
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#rse-c0015",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "Before beginning service or maintenance, OSHA describes the energy-control sequence.",
        "page": 13,
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "text_search": "Before beginning service or maintenance, the following steps must be accomplished in sequence",
        "evidence_snippets": [
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0015",
                "page": 13,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Prepare for shutdown.",
            },
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0016",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Shut down the machine.",
            },
        ],
    }
    answer = "1. Prepare for shutdown. 2. Shut down the machine.[^1]"

    _clean_answer, segments, citations = _knowledge_answer_payload(answer, [source])

    assert [segment["text"] for segment in segments] == [
        "1. Prepare for shutdown.",
        "2. Shut down the machine.",
    ]
    assert len(citations) == 2
    shutdown_citation = citations[1]
    assert shutdown_citation["citation_id"].endswith(":claim-2")
    assert shutdown_citation["chunk_id"] == "osha_3120_lockout_tagout_c0016"
    assert shutdown_citation["page"] == 14
    assert shutdown_citation["text_search"] == "Shut down the machine"


def test_knowledge_answer_payload_keeps_snippet_only_evidence_page_only():
    source = {
        "source_number": 1,
        "source_id": "loto#rse-c0015",
        "doc_id": "loto",
        "chunk_id": "rse:loto:c0015",
        "title": "LOTO Procedure",
        "organization": "Safety",
        "snippet": "Broad source-card preview only.",
        "page": 13,
        "pdf_url": "/documents/loto/pdf",
        "evidence_snippets": [
            {
                "source_number": 1,
                "doc_id": "loto",
                "chunk_id": "loto_c0018",
                "page": 18,
                "pdf_url": "/documents/loto/pdf",
                "snippet": "This page discusses verification in general terms without the exact answer sentence.",
            },
        ],
    }
    answer = "1. Verify isolation before work starts. 2. Keep lockout devices applied until release.[^1]"

    _clean_answer, _segments, citations = _knowledge_answer_payload(answer, [source])

    assert len(citations) == 2
    assert citations[0]["page"] == 18
    assert citations[0]["chunk_id"] == "loto_c0018"
    assert "text_search" not in citations[0]


def test_knowledge_answer_payload_does_not_reuse_broad_source_search_for_step_claims():
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#rse-c0015",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "The source card preview is broad RSE context.",
        "page": 13,
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "text_search": (
            "Employers must develop, document, and use procedures to control potentially hazardous energy. "
            "The procedures explain what employees must know and do to control hazardous energy."
        ),
    }
    answer = "1. Prepare for shutdown. 2. Shut down the machine.[^1]"

    _clean_answer, _segments, citations = _knowledge_answer_payload(answer, [source])

    assert len(citations) == 2
    for citation in citations:
        assert citation["page"] == 13
        assert citation["pdf_url"] == "/documents/osha_3120_lockout_tagout/pdf"
        assert "text_search" not in citation
        assert "bbox" not in citation
        assert "char_range" not in citation


def test_knowledge_answer_payload_selects_child_page_from_rse_bundle_for_step_claim():
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#rse-c0015",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "A multi-page RSE bundle starts on page 13.",
        "page": 13,
        "page_start": 13,
        "page_end": 15,
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "evidence_snippets": [
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
                "page": 13,
                "page_start": 13,
                "page_end": 15,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "The RSE parent has broad energy-control procedure context.",
                "source_chunk_evidence": [
                    {
                        "doc_id": "osha_3120_lockout_tagout",
                        "chunk_id": "osha_3120_lockout_tagout_c0015",
                        "page": 13,
                        "snippet": "What must an energy-control procedure include?",
                    },
                    {
                        "doc_id": "osha_3120_lockout_tagout",
                        "chunk_id": "osha_3120_lockout_tagout_c0016",
                        "page": 14,
                        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                        "snippet": (
                            "Before beginning service or maintenance, the following steps must be accomplished "
                            "in sequence and according to the specific provisions of the employer's energy-control "
                            "procedure: (1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or "
                            "isolate the machine from the energy source(s);"
                        ),
                    },
                ],
            }
        ],
    }
    answer = "1. Shut down the machine.[^1]"

    _clean_answer, _segments, citations = _knowledge_answer_payload(answer, [source])

    assert len(citations) == 1
    citation = citations[0]
    assert citation["chunk_id"] == "osha_3120_lockout_tagout_c0016"
    assert citation["page"] == 14
    assert citation["text_search"] == "Shut down the machine"
    assert citation["evidence"][0]["locator_confidence"] == "exact"
    assert citation["evidence"][0]["page"] == 14
    assert citation["evidence"][0]["text_search"] == "Shut down the machine"


def test_knowledge_answer_payload_keeps_six_deterministic_procedure_steps_on_child_page():
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#rse-c0015",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "A multi-page RSE bundle starts on page 13.",
        "page": 13,
        "page_start": 13,
        "page_end": 15,
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "evidence_snippets": [
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0016",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Prepare for shutdown.",
                "text_search": "Prepare for shutdown",
            },
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0016",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Shut down the machine.",
                "text_search": "Shut down the machine",
            },
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0016",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Disconnect or isolate the machine from the energy source(s).",
                "text_search": "Disconnect or isolate the machine from the energy source(s)",
            },
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0016",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Apply the lockout or tagout device(s) to the energy-isolating device(s).",
                "text_search": "Apply the lockout or tagout device(s) to the energy-isolating device(s)",
            },
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0016",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": (
                    "Release, restrain, or otherwise render safe all potential hazardous stored or residual "
                    "energy. If a possibility exists for reaccumulation of hazardous energy, regularly verify "
                    "during the service and maintenance that such energy has not reaccumulated to hazardous levels."
                ),
                "text_search": (
                    "Release, restrain, or otherwise render safe all potential hazardous stored or residual "
                    "energy. If a possibility exists for reaccumulation of hazardous energy, regularly verify "
                    "during the service and maintenance that such energy has not reaccumulated to hazardous levels"
                ),
            },
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0016",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Verify the isolation and deenergization of the machine.",
                "text_search": "Verify the isolation and deenergization of the machine",
            },
        ],
    }
    answer = (
        "1. Prepare for shutdown.[^1]\n"
        "2. Shut down the machine.[^1]\n"
        "3. Disconnect or isolate the machine from the energy source(s).[^1]\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s).[^1]\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy. "
        "If a possibility exists for reaccumulation of hazardous energy, regularly verify during the service "
        "and maintenance that such energy has not reaccumulated to hazardous levels.[^1]\n"
        "6. Verify the isolation and deenergization of the machine.[^1]"
    )

    clean_answer, segments, citations = _knowledge_answer_payload(answer, [source])

    assert len(clean_answer.splitlines()) == 6
    assert [segment["text"] for segment in segments] == clean_answer.splitlines()
    assert len(citations) == 6
    assert len({citation["citation_id"] for citation in citations}) == 6
    verify_citation = citations[5]
    assert verify_citation["citation_id"].endswith(":claim-6")
    assert verify_citation["page"] == 14
    assert verify_citation["chunk_id"] == "osha_3120_lockout_tagout_c0016"
    assert verify_citation["text_search"] == "Verify the isolation and deenergization of the machine"
    assert verify_citation["evidence"][0]["locator_confidence"] == "exact"


def test_knowledge_answer_payload_filters_broad_and_unrelated_evidence_when_exact_child_support_exists():
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#rse-c0015",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "Prepare for shutdown.",
        "text_search": "Prepare for shutdown",
        "page": 13,
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "evidence_snippets": [
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
                "page": 13,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Prepare for shutdown.",
                "text_search": "Prepare for shutdown",
            },
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0015",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": (
                    "Before beginning service or maintenance, the following steps must be accomplished "
                    "in sequence and according to the specific provisions of the employer's energy-control "
                    "procedure: (1) Prepare for shutdown; (2) Shut down the machine."
                ),
            },
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0009",
                "page": 10,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": (
                    "An employee performs hot-tap operations when shutdown of the system is impractical "
                    "and continuity of service is essential."
                ),
            },
        ],
    }
    answer = "1. Prepare for shutdown.[^1]"

    _clean_answer, _segments, citations = _knowledge_answer_payload(answer, [source])

    assert len(citations) == 1
    citation = citations[0]
    assert citation["page"] == 14
    assert citation["chunk_id"] == "osha_3120_lockout_tagout_c0015"
    assert citation["snippet"] == "Prepare for shutdown"
    assert citation["text_search"] == "Prepare for shutdown"
    assert [item["page"] for item in citation["evidence"]] == [14]
    assert [item["chunk_id"] for item in citation["evidence"]] == ["osha_3120_lockout_tagout_c0015"]
    assert [item["snippet"] for item in citation["evidence"]] == ["Prepare for shutdown"]


def test_knowledge_answer_payload_keeps_multiple_verified_evidence_items_for_compound_claim():
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#rse-c0015",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "Procedure steps span one PDF page.",
        "page": 14,
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "evidence_snippets": [
            {
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_loto_prepare",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Prepare for shutdown.",
            },
            {
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_loto_shutdown",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Shut down the machine.",
            },
            {
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_loto_isolate",
                "page": 14,
                "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                "snippet": "Disconnect or isolate the machine from the energy source(s).",
            },
        ],
    }
    answer = (
        "Workers must prepare for shutdown, shut down the machine, and disconnect or isolate the machine "
        "from the energy source(s).[^1]"
    )

    _clean_answer, _segments, citations = _knowledge_answer_payload(answer, [source])

    assert len(citations) == 1
    citation = citations[0]
    assert citation["chunk_id"] == "osha_loto_isolate"
    assert citation["page"] == 14
    assert [item["chunk_id"] for item in citation["evidence"]] == [
        "osha_loto_isolate",
        "osha_loto_shutdown",
        "osha_loto_prepare",
    ]
    assert [item["text_search"] for item in citation["evidence"]] == [
        "Disconnect or isolate the machine from the energy source(s)",
        "Shut down the machine",
        "Prepare for shutdown",
    ]
    assert all(item["locator_confidence"] == "exact" for item in citation["evidence"])


@pytest.mark.asyncio
async def test_phase32_positive_osha_reenergizing_response_document_is_pdf_source_backed(db_session):
    created_at = datetime(2026, 5, 19, 10, 0, 0)
    session_id = "rd-phase32-positive-osha-reenergizing"
    plan_id = "rd-phase32-positive-plan"
    prompt = (
        "According to the OSHA lockout/tagout guide, what notification is required before reenergizing "
        "a machine after removing lockout or tagout devices?"
    )
    answer = (
        "Before reenergizing, notify affected employees who operate or work with the machine and employees "
        "in the service area that the lockout or tagout devices have been removed and that the machine can "
        "be reenergized [^1]."
    )
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "osha_3120_lockout_tagout_c0029",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": (
            "After removing the lockout or tagout devices but before reenergizing the machine, "
            "the employer must assure that employees know the devices have been removed and the machine "
            "is capable of being reenergized."
        ),
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "page": 15,
        "char_range": [0, 1017],
        "text_search": "After removing the lockout or tagout devices but before reenergizing the machine",
    }
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=7,
                status="COMPLETED",
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content=answer,
                step_id=plan_id,
                tool_name="__conversation__",
                created_at=created_at + timedelta(seconds=2),
            ),
        ]
    )
    plan = await db_session.get(Plan, plan_id)
    assert plan is not None
    plan.sources = [source]
    plan.safety_content = "This topic involves high-risk industrial procedures. Follow the site-approved SOP before acting."
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    serialized = json.dumps(document)
    knowledge_block = next(block for block in document["blocks"] if block["type"] == "knowledge_answer")
    source_block = next(block for block in document["blocks"] if block["type"] == "source_list")
    citation = knowledge_block["citations"][0]
    listed_source = source_block["sources"][0]

    assert document["message"] == "I found a source-backed answer."
    assert knowledge_block["contract"] == "knowledge_answer_v1"
    assert knowledge_block["answer"].startswith("Before reenergizing, notify affected employees")
    assert all(segment.get("citation_ids") for segment in knowledge_block["segments"])
    assert citation["contract"] == "source_citation_v1"
    for payload in (citation, listed_source):
        assert payload["source_id"] == "osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029"
        assert payload["doc_id"] == "osha_3120_lockout_tagout"
        assert payload["chunk_id"] == "osha_3120_lockout_tagout_c0029"
        assert payload["page"] == 15
        assert payload["pdf_url"] == "/documents/osha_3120_lockout_tagout/pdf"
        assert payload["char_range"] == [0, 1017]
        assert payload["text_search"]
    assert listed_source["contract"] == "source_locator_v1"
    assert "loto_notification_requirement" not in serialized
    assert "LOTO Notification Requirements" not in serialized
    assert "file_path" not in serialized
    assert document["invariants"]["safety_notice_contract"] == "safety_notice_v1"
    assert document["invariants"]["knowledge_answer_contract"] == "knowledge_answer_v1"
    assert document["invariants"]["source_list_contract"] == "source_list_v1"


@pytest.mark.asyncio
async def test_phase32_negative_osha_before_starting_lockout_uses_insufficient_context_with_related_sources(db_session):
    created_at = datetime(2026, 5, 19, 10, 8, 0)
    session_id = "rd-phase32-negative-osha-starting-lockout"
    plan_id = "rd-phase32-negative-plan"
    prompt = "According to the OSHA lockout/tagout guide, what notification is required before starting lockout?"
    answer = insufficient_context_answer(has_sources=True)
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0028",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "osha_3120_lockout_tagout_c0028",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": (
            "Before beginning service or maintenance, OSHA lists preparation, shutdown, isolation, applying "
            "lockout or tagout devices, controlling stored energy, and verifying deenergization."
        ),
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "page": 14,
        "text_search": "Before beginning service or maintenance, the following steps must be accomplished in sequence",
    }
    db_session.add_all(
        [
            _session(
                session_id=session_id,
                plan_id=plan_id,
                created_at=created_at,
                event_seq=7,
                status="COMPLETED",
                current_intent=prompt,
            ),
            _user_message(session_id=session_id, created_at=created_at, content=prompt),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content=answer,
                step_id=plan_id,
                tool_name="__conversation__",
                created_at=created_at + timedelta(seconds=2),
            ),
        ]
    )
    plan = await db_session.get(Plan, plan_id)
    assert plan is not None
    plan.sources = [source]
    plan.safety_content = "LOTO is safety-critical. Follow your site's approved energy-control procedure."
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    serialized = json.dumps(document)
    knowledge_block = next(block for block in document["blocks"] if block["type"] == "knowledge_answer")
    source_block = next(block for block in document["blocks"] if block["type"] == "source_list")

    assert document["message"] == "I do not have enough retrieved evidence to answer that safely."
    assert document["message"] != knowledge_block["answer"]
    assert knowledge_block["answer"] == answer
    assert knowledge_block["citations"] == []
    assert knowledge_block["segments"] == [{"text": answer, "citation_ids": []}]
    assert source_block["sources"][0]["doc_id"] == "osha_3120_lockout_tagout"
    assert source_block["sources"][0]["chunk_id"] == "osha_3120_lockout_tagout_c0028"
    assert source_block["sources"][0]["pdf_url"] == "/documents/osha_3120_lockout_tagout/pdf"
    assert source_block["sources"][0]["page"] == 14
    assert source_block["sources"][0]["text_search"]
    assert source_block["sources"][0].get("policy_only") is not True
    assert any(step["title"] == "Checked related sources" for step in document["run_steps"])
    assert "loto_notification_requirement" not in serialized
    assert "LOTO Notification Requirements" not in serialized
    assert "affected employees must be notified before lockout/tagout starts" not in serialized
    assert "Tell them the equipment will be locked out" not in serialized
    assert "Which machine ID" not in serialized
    assert "exact machine ID" not in serialized


@pytest.mark.asyncio
async def test_rag_response_document_source_identity_and_numbers_agree_after_normalization(db_session):
    created_at = datetime(2026, 5, 18, 15, 12, 0)
    session_id = "rd-rag-source-identity"
    plan_id = "rd-rag-source-identity-plan"
    answer = "Source A supports the first claim [^1]. Source B supports the second claim [^2]."
    sources = [
        {
            "source_number": 1,
            "source_id": "doc-a#chunk-a",
            "doc_id": "doc-a",
            "chunk_id": "chunk-a",
            "title": "Document A",
            "organization": "Org A",
            "snippet": "Source A supports the first claim.",
        },
        {
            "source_number": 1,
            "source_id": "doc-b#chunk-b",
            "doc_id": "doc-b",
            "chunk_id": "chunk-b",
            "title": "Document B",
            "organization": "Org B",
            "snippet": "Source B supports the second claim.",
        },
    ]
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=7, status="COMPLETED"),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content=answer,
                step_id=plan_id,
                tool_name="__conversation__",
                created_at=created_at + timedelta(seconds=2),
            ),
        ]
    )
    plan = await db_session.get(Plan, plan_id)
    assert plan is not None
    plan.sources = sources
    await db_session.commit()

    document = (await _snapshot(db_session, session_id))["response_document"]
    knowledge_block = next(block for block in document["blocks"] if block["type"] == "knowledge_answer")
    source_block = next(block for block in document["blocks"] if block["type"] == "source_list")
    listed_sources = source_block["sources"]
    listed_by_id = {source["source_id"]: source for source in listed_sources}

    assert [source["source_number"] for source in listed_sources] == [1, 2]
    assert len({source["source_number"] for source in listed_sources}) == len(listed_sources)
    assert {citation["source_number"] for citation in knowledge_block["citations"]} == {1, 2}
    for citation in knowledge_block["citations"]:
        listed = listed_by_id[citation["source_id"]]
        assert citation["doc_id"] == listed["doc_id"]
        assert citation["title"] == listed["title"]
        assert citation["source_number"] == listed["source_number"]


@pytest.mark.asyncio
async def test_rag_response_document_blocks_uncited_backend_added_factual_supplement(db_session):
    created_at = datetime(2026, 5, 18, 15, 18, 0)
    session_id = "rd-rag-uncited-supplement"
    plan_id = "rd-rag-uncited-supplement-plan"
    uncited_supplement = (
        "Before lockout/tagout starts, affected employees must be notified that the equipment will be "
        "locked out or tagged out and when the control begins."
    )
    answer = f"The retrieved procedure says to isolate hazardous energy first [^1]. {uncited_supplement}"
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0027",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "osha_3120_lockout_tagout_c0027",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "The procedure says to isolate hazardous energy first.",
    }
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=7, status="COMPLETED"),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content=answer,
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

    document = (await _snapshot(db_session, session_id))["response_document"]
    knowledge_block = next(block for block in document["blocks"] if block["type"] == "knowledge_answer")
    serialized_block = json.dumps(knowledge_block)

    assert knowledge_block["answer"] == "The retrieved procedure says to isolate hazardous energy first."
    assert all(segment.get("citation_ids") for segment in knowledge_block["segments"])
    assert uncited_supplement not in serialized_block
    assert "affected employees must be notified" not in serialized_block


@pytest.mark.asyncio
async def test_rag_response_document_converts_wholly_uncited_source_backed_answer_to_insufficient_context(db_session):
    created_at = datetime(2026, 5, 18, 15, 24, 0)
    session_id = "rd-rag-wholly-uncited"
    plan_id = "rd-rag-wholly-uncited-plan"
    answer = "The OSHA guide requires affected employee notification before lockout starts."
    source = {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0003",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "osha_3120_lockout_tagout_c0003",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": "This related source was checked.",
    }
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=7, status="COMPLETED"),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content=answer,
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

    document = (await _snapshot(db_session, session_id))["response_document"]
    knowledge_block = next(block for block in document["blocks"] if block["type"] == "knowledge_answer")

    assert document["message"] == "I do not have enough retrieved evidence to answer that safely."
    assert knowledge_block["answer"].startswith("I do not have enough retrieved evidence")
    assert "related sources checked" in knowledge_block["answer"]
    assert knowledge_block["citations"] == []
    assert knowledge_block["segments"] == [{"text": knowledge_block["answer"], "citation_ids": []}]
    assert any(step["title"] == "Checked related sources" for step in document["run_steps"])
    assert all("affected employee notification before lockout starts" not in step.get("summary", "") for step in document["run_steps"])
    assert "affected employee notification before lockout starts" not in json.dumps(knowledge_block)


@pytest.mark.asyncio
async def test_rag_no_source_fallback_keeps_safety_notice(db_session):
    created_at = datetime(2026, 5, 18, 15, 30, 0)
    session_id = "rd-rag-no-source-safety"
    plan_id = "rd-rag-no-source-plan"
    answer = (
        "Controlled seeded RAG fallback: I do not have an available cited LOTO source. "
        "Verify the site procedure before acting."
    )
    db_session.add_all(
        [
            _session(session_id=session_id, plan_id=plan_id, created_at=created_at, event_seq=7, status="COMPLETED"),
            _user_message(session_id=session_id, created_at=created_at),
            _plan(session_id=session_id, plan_id=plan_id, created_at=created_at + timedelta(seconds=1)),
            _assistant_message(
                session_id=session_id,
                content=answer,
                step_id=plan_id,
                tool_name="__conversation__",
                created_at=created_at + timedelta(seconds=2),
            ),
        ]
    )
    plan = await db_session.get(Plan, plan_id)
    assert plan is not None
    plan.sources = []
    plan.safety_content = "No retrievable seeded source was available for this LOTO answer."
    await db_session.commit()

    body = await _snapshot(db_session, session_id)
    document = body["response_document"]

    assert body["presentation"]["kind"] == "answer"
    safety_block = next(block for block in document["blocks"] if block["type"] == "safety_notice")
    assert safety_block["safety_content"] == "No retrievable seeded source was available for this LOTO answer."
    assert not any(block["type"] == "source_list" for block in document["blocks"])
    assert not any(block["type"] == "diagnostic" and block["reason"] == "no_results" for block in document["blocks"])
    assert "Controlled seeded RAG fallback" in json.dumps(document)


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


@pytest.mark.asyncio
async def test_response_document_revision_starts_from_zero_event_seq_not_updated_at(db_session):
    created_at = datetime(2026, 5, 18, 10, 0, 0)
    session_id = "rd-revision-zero-event-seq"
    session = Session(
        session_id=session_id,
        user_id="u1",
        status="IDLE",
        current_intent=None,
        plan_id=None,
        plan_version=0,
        current_step_index=0,
        step_count=0,
        llm_call_count=0,
        event_seq=0,
        session_started_at=created_at,
        created_at=created_at,
        updated_at=created_at + timedelta(seconds=30),
    )
    db_session.add(session)
    await db_session.commit()

    initial = await _snapshot(db_session, session_id)
    initial_document = initial["response_document"]
    assert initial_document["revision"] == 0
    assert initial_document["revision_source"] == "event_seq"

    session.status = "PLANNING"
    session.current_intent = "change all medium priority job to high"
    session.event_seq = 1
    db_session.add(_user_message(session_id=session_id, created_at=created_at + timedelta(seconds=31)))
    await db_session.commit()

    after_user_message = await _snapshot(db_session, session_id)
    after_document = after_user_message["response_document"]
    assert after_document["revision"] == 1
    assert after_document["revision"] > initial_document["revision"]
    assert after_document["revision_source"] == "event_seq"
