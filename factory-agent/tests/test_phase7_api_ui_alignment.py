from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

import database
from factory_agent.api import build_router
from factory_agent.api.routes import (
    _activity_steps_for_snapshot,
    _semantic_payload_for_timeline_event,
    _should_skip_semantic_timeline_event,
)
from factory_agent.config import Settings
from factory_agent.observability.events import AgentEvent
from factory_agent.persistence import database as persistence_database
from factory_agent.persistence.models import Approval, Message, Plan, PlanStep, Session, WorkflowCheckpoint
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import PlanResponse, PlanStepResponse, SessionSnapshotResponse, TimelineEventResponse
from tests.support.stateful_oracle_harness import load_oracle


class _FakeEventBus:
    def __init__(self):
        self.published: list[AgentEvent] = []

    async def publish(self, event: AgentEvent) -> None:
        self.published.append(event)

    async def listen(self, handler: Any) -> None:
        return None


RAW_ACTIVITY_LEAK_PATTERNS = [
    "__",
    "{id}",
    "tool_name",
    "get__",
    "post__",
    "planner_reentered",
    "validator_failed",
    "tool_rerun",
    "IN_PROGRESS",
    "DONE",
    "args",
    "result",
    "checkpoint",
]


def _assert_no_activity_leaks(steps):
    serialized = json.dumps([step.model_dump(exclude_none=True) for step in steps])
    for pattern in RAW_ACTIVITY_LEAK_PATTERNS:
        assert pattern not in serialized


async def _make_phase7_app(sessionmaker_override) -> FastAPI:
    settings = Settings(
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
        jwt_required=False,
        enforce_tool_registry_health=False,
        auto_repair_tool_registry=False,
        min_healthy_tool_count=0,
    )
    app = FastAPI()

    async def override_get_db():
        async with sessionmaker_override() as s:
            yield s

    app.dependency_overrides[database.get_db] = override_get_db
    app.dependency_overrides[persistence_database.get_db] = override_get_db
    app.include_router(
        build_router(
            settings=settings,
            tool_registry=ToolRegistry(),
            event_bus=_FakeEventBus(),
        )
    )
    return app


@pytest.mark.asyncio
async def test_phase7_snapshot_projects_graph_checkpoint_without_legacy_steps(sessionmaker_override, db_session):
    session_id = "phase7-checkpoint-only"
    created_at = datetime(2026, 5, 13, 9, 0, 0)
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="WAITING_APPROVAL",
            current_intent="list machines then create a job",
            session_started_at=created_at,
            created_at=created_at,
            updated_at=created_at + timedelta(seconds=2),
            replan_context={},
        )
    )
    db_session.add(
        Message(
            message_id="phase7-user-message",
            session_id=session_id,
            role="user",
            content="List machines and create a job for product P-001",
            created_at=created_at,
        )
    )
    db_session.add(
        Approval(
            approval_id="phase7-approval",
            session_id=session_id,
            subject_type="graph",
            tool_name="__langgraph_commit__",
            args={"staged_writes": 1},
            risk_summary="High-risk write bundle requires approval.",
            side_effect_level="HIGH",
            status="PENDING",
            expires_at=created_at + timedelta(hours=1),
            created_at=created_at + timedelta(milliseconds=30),
        )
    )
    db_session.add(
        WorkflowCheckpoint(
            thread_id=session_id,
            session_id=session_id,
            state={
                "kind": "langgraph_native_checkpoint",
                "agent_state": {
                    "validated_plan": {
                        "plan_explanation": "Graph-native plan from checkpoint.",
                        "risk_summary": "Read plus staged write.",
                        "steps": [
                            {
                                "step_index": 0,
                                "tool_name": "get__machines",
                                "args": {},
                                "requires_approval": False,
                            }
                        ],
                    },
                    "completed_actions": [
                        {
                            "phase": "tool_execution",
                            "tool_name": "get__machines",
                            "args": {},
                            "status": "http_ok",
                        }
                    ],
                    "tool_outputs": [
                        {
                            "tool_name": "get__machines",
                            "tool_call_id": "tool-call-1",
                            "args": {},
                            "status": "DONE",
                            "summary": "Retrieved 1 machine.",
                            "result": {"data": [{"machine_id": "M-001", "status": "idle"}]},
                        }
                    ],
                },
            },
        )
    )
    await db_session.commit()

    step_rows = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().all()
    assert step_rows == []

    app = await _make_phase7_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/sessions/{session_id}/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None
    assert [step["tool_name"] for step in body["steps"]] == ["get__machines"]
    event_types = [event["event_type"] for event in body["timeline"]]
    assert "plan_created" in event_types
    assert "tool_started" in event_types
    assert "tool_result" in event_types
    assert "approval_required" in event_types
    semantic_types = [
        _semantic_payload_for_timeline_event(TimelineEventResponse(**event), session_id=session_id)["type"]
        for event in body["timeline"]
    ]
    assert "PLANNER_THINKING" in semantic_types
    assert "TOOL_STARTED" in semantic_types
    assert "TOOL_RESULT" in semantic_types
    assert "APPROVAL_REQUIRED" in semantic_types
    serialized = json.dumps(body)
    assert "agent_state" not in serialized
    assert "langgraph_checkpoint" not in serialized


def test_phase7_activity_adapter_sanitizes_tool_and_runtime_details():
    created_at = datetime(2026, 5, 13, 9, 0, 0)
    snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-s1",
            "user_id": "u1",
            "status": "COMPLETED",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 1,
            "llm_call_count": 2,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=5),
        },
        timeline=[
            TimelineEventResponse(
                event_id="user:activity",
                event_type="user_message",
                content="Check machine status",
                created_at=created_at,
                role="user",
            ),
            TimelineEventResponse(
                event_id="plan:activity",
                event_type="plan_created",
                content="planner_reentered validator_failed",
                created_at=created_at + timedelta(seconds=1),
                status="PLANNING",
                details={"status": "DRAFT", "node": "planner_reentered"},
            ),
            TimelineEventResponse(
                event_id="step-started:activity",
                event_type="tool_started",
                content="Tool started.",
                created_at=created_at + timedelta(seconds=2),
                step_id="trace-step-1",
                tool_name="get__machines_{id}",
                status="IN_PROGRESS",
                details={"args": {"id": "M-001"}, "node": "tool_router_v2"},
            ),
            TimelineEventResponse(
                event_id="step:activity",
                event_type="tool_result",
                content="get__machines_{id} completed.",
                created_at=created_at + timedelta(seconds=3),
                step_id="trace-step-1",
                tool_name="get__machines_{id}",
                status="DONE",
                details={"result": {"machine_id": "M-001"}},
            ),
            TimelineEventResponse(
                event_id="replan:activity",
                event_type="replan_requested",
                content="tool_rerun after validator_failed",
                created_at=created_at + timedelta(seconds=4),
                status="PLANNING",
            ),
            TimelineEventResponse(
                event_id="completed:activity",
                event_type="session_completed",
                content="Execution completed successfully.",
                created_at=created_at + timedelta(seconds=5),
                status="COMPLETED",
            ),
        ],
    )

    steps = _activity_steps_for_snapshot(snapshot)
    assert [step.label for step in steps] == [
        "Understood request",
        "Reading machine records",
        "Checked machine records",
        "Improving the response",
        "Run complete",
    ]
    assert steps[-1].state == "complete"
    assert steps[1].detail == "Checking machine records"
    assert steps[3].state == "success"
    assert set(step.state for step in steps) <= {"running", "success", "retry", "waiting", "error", "complete"}
    _assert_no_activity_leaks(steps)


def test_replan_spine_activity_steps_show_attempt_numbers_and_retry_reason():
    created_at = datetime(2026, 5, 13, 9, 30, 0)
    replan_spine = {
        "attempt_count": 1,
        "max_attempts": 2,
        "attempts": [
            {
                "attempt": 1,
                "missing_evidence_reasons": [
                    {
                        "reason": "tool_error",
                        "requirement_id": "req-machine-status",
                        "evidence_refs": ["ev-timeout"],
                        "retriable": True,
                    }
                ],
                "failed_tool_calls": [
                    {
                        "tool_name": "get__machines_{id}",
                        "args": {"id": "M-001", "fields": "status"},
                        "requirement_id": "req-machine-status",
                        "evidence_ref": "ev-timeout",
                        "reason": "tool_error",
                        "attempt": 1,
                    }
                ],
            }
        ],
        "missing_evidence_reasons": [
            {
                "reason": "tool_error",
                "requirement_id": "req-machine-status",
                "evidence_refs": ["ev-timeout"],
                "retriable": True,
            }
        ],
        "failed_tool_calls": [
            {
                "tool_name": "get__machines_{id}",
                "args": {"id": "M-001", "fields": "status"},
                "requirement_id": "req-machine-status",
                "evidence_ref": "ev-timeout",
                "reason": "tool_error",
                "attempt": 1,
            }
        ],
    }
    snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-replan-story",
            "user_id": "u1",
            "status": "COMPLETED",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 1,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=8),
            "replan_context": {
                "intent_contract": {
                    "replan_spine": replan_spine,
                }
            },
        },
        timeline=[
            TimelineEventResponse(
                event_id="plan:replan-story",
                event_type="plan_created",
                content="Check machine status",
                created_at=created_at + timedelta(seconds=1),
                status="PLANNING",
            ),
            TimelineEventResponse(
                event_id="started:replan-story-1",
                event_type="tool_started",
                content="Tool started.",
                created_at=created_at + timedelta(seconds=2),
                tool_name="get__machines_{id}",
                status="IN_PROGRESS",
                details={"args": {"id": "M-001", "fields": "status"}},
            ),
            TimelineEventResponse(
                event_id="result:replan-story-1",
                event_type="tool_result",
                content="Machine status API timed out.",
                created_at=created_at + timedelta(seconds=3),
                tool_name="get__machines_{id}",
                status="FAILED",
                details={
                    "args": {"id": "M-001", "fields": "status"},
                    "result": {
                        "status": "tool_failed",
                        "status_code": 504,
                        "error": {"code": "tool_error", "error_type": "timeout"},
                    },
                },
            ),
            TimelineEventResponse(
                event_id="replan:replan-story",
                event_type="replan_requested",
                content="Retry after missing evidence.",
                created_at=created_at + timedelta(seconds=4),
                status="PLANNING",
                details={"reason": "tool_error"},
            ),
            TimelineEventResponse(
                event_id="started:replan-story-2",
                event_type="tool_started",
                content="Tool started.",
                created_at=created_at + timedelta(seconds=5),
                tool_name="get__machines_{id}",
                status="IN_PROGRESS",
                details={"args": {"id": "M-001", "fields": "status"}},
            ),
            TimelineEventResponse(
                event_id="result:replan-story-2",
                event_type="tool_result",
                content="Machine status checked.",
                created_at=created_at + timedelta(seconds=6),
                tool_name="get__machines_{id}",
                status="DONE",
                details={
                    "args": {"id": "M-001", "fields": "status"},
                    "result": {"data": {"machine_id": "M-001", "status": "running"}},
                },
            ),
            TimelineEventResponse(
                event_id="completed:replan-story",
                event_type="session_completed",
                content="Machine status is available.",
                created_at=created_at + timedelta(seconds=7),
                status="COMPLETED",
            ),
        ],
    )

    steps = _activity_steps_for_snapshot(snapshot)

    assert [step.label for step in steps] == [
        "Understood request",
        "Running selected tool",
        "Checking evidence",
        "Replanning after timeout",
        "Retrying machine status read",
        "Checking new evidence",
        "Run complete",
    ]
    assert "Attempt 1 of 3" in (steps[1].detail or "")
    assert "Previous read timed out" in (steps[2].detail or "")
    assert "Attempt 2 of 3" in (steps[3].detail or "")
    assert "Previous read timed out" in (steps[3].detail or "")
    assert "Attempt 2 of 3" in (steps[5].detail or "")
    assert "Attempt 2 of 3" in (steps[-1].detail or "")


def test_replan_spine_activity_steps_collapse_noisy_retry_attempts():
    created_at = datetime(2026, 5, 13, 9, 45, 0)
    attempts = []
    for attempt in range(1, 6):
        attempts.append(
            {
                "attempt": attempt,
                "missing_evidence_reasons": [
                    {
                        "reason": "tool_error",
                        "requirement_id": "req-machine-status",
                        "evidence_refs": [f"ev-timeout-{attempt}"],
                        "retriable": True,
                    }
                ],
                "failed_tool_calls": [
                    {
                        "tool_name": "get__machines_{id}",
                        "args": {"id": "M-001", "fields": "status"},
                        "requirement_id": "req-machine-status",
                        "evidence_ref": f"ev-timeout-{attempt}",
                        "reason": "tool_error",
                        "error_type": "timeout",
                        "attempt": attempt,
                    }
                ],
            }
        )
    replan_spine = {
        "attempt_count": 5,
        "max_attempts": 5,
        "replan_limit_reached": True,
        "attempts": attempts,
        "missing_evidence_reasons": [
            {
                "reason": "tool_error",
                "requirement_id": "req-machine-status",
                "evidence_refs": ["ev-timeout-5"],
                "retriable": True,
            }
        ],
        "failed_tool_calls": attempts[-1]["failed_tool_calls"],
    }
    snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-replan-noisy",
            "user_id": "u1",
            "status": "BLOCKED",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 5,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=30),
            "replan_context": {
                "intent_contract": {
                    "replan_spine": replan_spine,
                }
            },
        },
        timeline=[
            TimelineEventResponse(
                event_id="plan:replan-noisy",
                event_type="plan_created",
                content="Check machine status",
                created_at=created_at + timedelta(seconds=1),
                status="PLANNING",
            ),
            TimelineEventResponse(
                event_id="blocked:replan-noisy",
                event_type="session_blocked",
                content="Evidence could not be verified.",
                created_at=created_at + timedelta(seconds=29),
                status="BLOCKED",
            ),
        ],
    )

    steps = _activity_steps_for_snapshot(snapshot)
    labels = [step.label for step in steps]

    assert "Earlier retry attempts" in labels
    assert (steps[labels.index("Earlier retry attempts")].detail or "") == "4 earlier attempts collapsed"
    assert len([label for label in labels if label.startswith("Replanning")]) == 1
    assert "Attempt 6 of 6" in (steps[-2].detail or "")
    assert "needs attention" in steps[-1].label.lower()
    assert "Attempt 6 of 6" in (steps[-1].detail or "")


def test_phase7_activity_adapter_uses_specific_server_stage_labels_for_tool_and_rag_runs():
    created_at = datetime(2026, 5, 13, 9, 0, 0)

    normal_snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-specific-tool",
            "user_id": "u1",
            "status": "COMPLETED",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 0,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=5),
        },
        timeline=[
            TimelineEventResponse(
                event_id="plan:specific-tool",
                event_type="plan_created",
                content="Check machine status",
                created_at=created_at + timedelta(seconds=1),
                status="PLANNING",
            ),
            TimelineEventResponse(
                event_id="started:specific-tool",
                event_type="tool_started",
                content="Tool started.",
                created_at=created_at + timedelta(seconds=2),
                tool_name="get__machines_{id}",
                status="IN_PROGRESS",
            ),
            TimelineEventResponse(
                event_id="result:specific-tool",
                event_type="tool_result",
                content="Machine status checked.",
                created_at=created_at + timedelta(seconds=3),
                tool_name="get__machines_{id}",
                status="DONE",
            ),
            TimelineEventResponse(
                event_id="completed:specific-tool",
                event_type="session_completed",
                content="Machine status is available.",
                created_at=created_at + timedelta(seconds=4),
                status="COMPLETED",
            ),
        ],
    )

    normal_steps = _activity_steps_for_snapshot(normal_snapshot)
    assert [step.label for step in normal_steps] == [
        "Understood request",
        "Reading machine records",
        "Checked machine records",
        "Run complete",
    ]

    rag_snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-specific-rag",
            "user_id": "u1",
            "status": "COMPLETED",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 0,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=5),
        },
        timeline=[
            TimelineEventResponse(
                event_id="plan:specific-rag",
                event_type="plan_created",
                content="Answer from OSHA LOTO sources.",
                created_at=created_at + timedelta(seconds=1),
                status="PLANNING",
            ),
            TimelineEventResponse(
                event_id="started:specific-rag",
                event_type="tool_started",
                content="Searching retrieved documents.",
                created_at=created_at + timedelta(seconds=2),
                tool_name="rag_search_documents",
                status="IN_PROGRESS",
            ),
            TimelineEventResponse(
                event_id="result:specific-rag",
                event_type="tool_result",
                content="Prepared cited LOTO answer.",
                created_at=created_at + timedelta(seconds=3),
                tool_name="rag_search_documents",
                status="DONE",
                details={"sources": [{"doc_id": "osha_3120_lockout_tagout", "source_number": 1}]},
            ),
            TimelineEventResponse(
                event_id="completed:specific-rag",
                event_type="session_completed",
                content="Source-backed answer is ready.",
                created_at=created_at + timedelta(seconds=4),
                status="COMPLETED",
                details={"sources": [{"doc_id": "osha_3120_lockout_tagout", "source_number": 1}]},
            ),
        ],
    )

    rag_steps = _activity_steps_for_snapshot(rag_snapshot)
    assert [step.label for step in rag_steps] == [
        "Understood request",
        "Searching knowledge sources",
        "Building cited answer",
        "Run complete",
    ]
    assert rag_steps[2].detail == "Checking citation support"


def test_phase7_activity_adapter_uses_live_graph_activity_while_session_is_active():
    created_at = datetime(2026, 5, 13, 9, 0, 0)
    live_rows = [
        {
            "id": "graph:semantic_intake_node",
            "timestamp": int((created_at + timedelta(seconds=1)).timestamp()),
            "group": "planning",
            "label": "Understood request",
            "detail": "Reviewing your request and recent context",
            "state": "running",
        },
        {
            "id": "graph:tool_retrieval_node",
            "timestamp": int((created_at + timedelta(seconds=2)).timestamp()),
            "group": "research",
            "label": "Searching knowledge sources",
            "detail": "Finding relevant source material",
            "state": "running",
        },
        {
            "id": "graph:evidence_observation_node",
            "timestamp": int((created_at + timedelta(seconds=3)).timestamp()),
            "group": "response",
            "label": "Checking citations",
            "detail": "Checking evidence support",
            "state": "running",
        },
    ]
    active_snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-live-graph",
            "user_id": "u1",
            "status": "EXECUTING",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 0,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=3),
            "replan_context": {"live_activity_steps": live_rows},
        },
        timeline=[
            TimelineEventResponse(
                event_id="plan:live-graph",
                event_type="plan_created",
                content="Answer from retrieved safety sources.",
                created_at=created_at + timedelta(seconds=1),
                status="PLANNING",
            )
        ],
    )

    active_steps = _activity_steps_for_snapshot(active_snapshot)
    assert [step.label for step in active_steps] == [
        "Understood request",
        "Searching knowledge sources",
        "Checking citations",
    ]
    assert active_steps[-1].state == "running"
    _assert_no_activity_leaks(active_steps)

    completed_snapshot = active_snapshot.model_copy(
        deep=True,
        update={
            "session": {
                **active_snapshot.session.model_dump(),
                "status": "COMPLETED",
            },
            "timeline": [
                *active_snapshot.timeline,
                TimelineEventResponse(
                    event_id="completed:live-graph",
                    event_type="session_completed",
                    content="Source-backed answer is ready.",
                    created_at=created_at + timedelta(seconds=4),
                    status="COMPLETED",
                ),
            ],
        },
    )
    assert [step.label for step in _activity_steps_for_snapshot(completed_snapshot)] == [
        "Understood request",
        "Run complete",
    ]


def test_phase7_activity_adapter_caps_and_groups_verbose_timelines():
    created_at = datetime(2026, 5, 13, 9, 0, 0)
    domains = ["machines", "jobs", "products", "inventory", "reports"]
    timeline = [
        TimelineEventResponse(
            event_id=f"tool:{idx}",
            event_type="tool_result",
            content=f"get__{domains[idx % len(domains)]} completed.",
            created_at=created_at + timedelta(seconds=idx),
            tool_name=f"get__{domains[idx % len(domains)]}_{idx}",
            status="DONE",
            details={"args": {"idx": idx}, "result": {"ok": True}},
        )
        for idx in range(20)
    ]
    snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-cap",
            "user_id": "u1",
            "status": "EXECUTING",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 20,
            "replan_count": 0,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=20),
        },
        timeline=timeline,
    )

    steps = _activity_steps_for_snapshot(snapshot)
    assert len(steps) == 5
    assert [step.detail for step in steps] == [
        "Checked machine records (4 updates)",
        "Checked job records (4 updates)",
        "Checked product records (4 updates)",
        "Checked inventory records (4 updates)",
        "Checked report records (4 updates)",
    ]
    assert len({step.id for step in steps}) == len(steps)
    assert all(str(step.id).startswith("act:") for step in steps)
    _assert_no_activity_leaks(steps)


def test_phase7_semantic_payload_names_terminal_events():
    created_at = datetime(2026, 5, 13, 10, 0, 0)
    completed = TimelineEventResponse(
        event_id="completed:s1",
        event_type="session_completed",
        content="Done.",
        created_at=created_at,
        status="COMPLETED",
    )
    failed = TimelineEventResponse(
        event_id="failed:s1",
        event_type="session_failed",
        content="Failed.",
        created_at=created_at,
        status="FAILED",
    )

    assert _semantic_payload_for_timeline_event(completed, session_id="s1")["type"] == "SESSION_COMPLETED"
    assert _semantic_payload_for_timeline_event(failed, session_id="s1")["type"] == "SESSION_FAILED"


@pytest.mark.asyncio
async def test_phase7_completed_session_without_completed_at_gets_terminal_timeline_event(sessionmaker_override, db_session):
    session_id = "phase7-completed-without-completed-at"
    user_message_id = "phase7-completed-user"
    plan_id = "phase7-completed-plan"
    step_id = "phase7-completed-step"
    created_at = datetime(2026, 5, 13, 9, 35, 0)
    plan_at = created_at + timedelta(seconds=46)
    updated_at = plan_at + timedelta(seconds=1)

    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="COMPLETED",
            current_intent="Check machine 5 status",
            plan_id=plan_id,
            plan_version=1,
            plan_hash="phase7-completed-hash",
            current_step_index=0,
            step_count=0,
            llm_call_count=2,
            session_started_at=created_at,
            created_at=created_at,
            updated_at=updated_at,
            completed_at=None,
            replan_context={"intent_contract": {"backend": "langgraph"}},
        )
    )
    db_session.add(
        Message(
            message_id=user_message_id,
            session_id=session_id,
            role="user",
            content="Check machine 5 status",
            mode="normal",
            created_at=created_at + timedelta(seconds=3),
        )
    )
    db_session.add(
        Plan(
            plan_id=plan_id,
            session_id=session_id,
            version=1,
            kind="execution",
            status="COMPLETED",
            dependency_graph={"0": []},
            parallel_groups=[],
            plan_hash="phase7-completed-hash",
            plan_explanation="Fetching status of machine 5. Requested resource was not found.",
            risk_summary="Review tool calls before execution.",
            created_at=plan_at,
            created_by="langgraph",
        )
    )
    db_session.add(
        Message(
            message_id="phase7-completed-assistant",
            session_id=session_id,
            role="assistant",
            content="Machine 5 was not found.",
            mode="normal",
            tool_name="__plan__",
            created_at=plan_at,
        )
    )
    db_session.add(
        PlanStep(
            step_id=step_id,
            plan_id=plan_id,
            session_id=session_id,
            step_index=0,
            tool_name="get__machines_{id}",
            args={"id": "5"},
            bindings=[],
            status="DONE",
            idempotency_key="phase7-completed-idempotency",
            requires_approval=False,
            retry_count=0,
            max_retries=3,
            completed_at=plan_at,
        )
    )
    await db_session.commit()

    app = await _make_phase7_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/sessions/{session_id}/snapshot")

    assert response.status_code == 200
    body = response.json()
    completed_events = [event for event in body["timeline"] if event["event_type"] == "session_completed"]
    assert completed_events
    assert completed_events[-1]["content"] == "Machine 5 was not found."
    assert (
        _semantic_payload_for_timeline_event(
            TimelineEventResponse(**completed_events[-1]),
            session_id=session_id,
        )["type"]
        == "SESSION_COMPLETED"
    )


@pytest.mark.asyncio
async def test_phase7_snapshot_steps_are_scoped_to_current_plan_after_followup(sessionmaker_override, db_session):
    session_id = "phase7-followup-current-plan-steps"
    old_plan_id = "phase7-followup-old-plan"
    new_plan_id = "phase7-followup-new-plan"
    created_at = datetime(2026, 5, 17, 9, 0, 0)
    old_plan_at = created_at + timedelta(seconds=1)
    new_plan_at = created_at + timedelta(seconds=5)

    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="COMPLETED",
            current_intent="What LOTO procedure applies before working on it?",
            replan_context={
                "contextual_resolution": {
                    "entity_type": "machine",
                    "machine_id": "M-CNC-01",
                    "source": "previous_turn",
                    "original_intent": "What LOTO procedure applies before working on it?",
                    "rag_query": (
                        "What LOTO procedure applies before working on it?\n\n"
                        "Resolved context from the immediately previous turn: machine M-CNC-01."
                    ),
                }
            },
            plan_id=new_plan_id,
            plan_version=2,
            plan_hash="phase7-followup-new-hash",
            current_step_index=0,
            step_count=0,
            llm_call_count=0,
            session_started_at=created_at,
            created_at=created_at,
            updated_at=new_plan_at,
            completed_at=new_plan_at,
        )
    )
    db_session.add_all(
        [
            Plan(
                plan_id=old_plan_id,
                session_id=session_id,
                version=1,
                kind="execution",
                status="INVALIDATED",
                dependency_graph={"0": []},
                parallel_groups=[],
                plan_hash="phase7-followup-old-hash",
                plan_explanation="Machine M-CNC-01 status lookup.",
                risk_summary="Read-only machine status.",
                created_at=old_plan_at,
                created_by="langgraph",
                invalidated_at=new_plan_at,
                invalidated_reason="Replanned",
            ),
            Plan(
                plan_id=new_plan_id,
                session_id=session_id,
                version=2,
                kind="execution",
                status="COMPLETED",
                dependency_graph={},
                parallel_groups=[],
                plan_hash="phase7-followup-new-hash",
                plan_explanation="Controlled seeded RAG answer for M-CNC-01 LOTO.",
                risk_summary="No tool execution required.",
                created_at=new_plan_at,
                created_by="system",
                sources=[{"machine_id": "M-CNC-01", "procedure_id": "LOTO-M-CNC-01"}],
            ),
        ]
    )
    db_session.add(
        PlanStep(
            step_id="phase7-followup-stale-step",
            plan_id=old_plan_id,
            session_id=session_id,
            step_index=0,
            tool_name="get__machines_{id}",
            args={"id": "M-CNC-01"},
            bindings=[],
            status="DONE",
            idempotency_key="phase7-followup-stale-idempotency",
            requires_approval=False,
            retry_count=0,
            max_retries=3,
            completed_at=old_plan_at,
            result_summary="Machine M-CNC-01 is running in the seeded Go API data.",
        )
    )
    db_session.add_all(
        [
            Message(
                message_id="phase7-followup-user-1",
                session_id=session_id,
                role="user",
                content="What is the status of M-CNC-01?",
                mode="normal",
                created_at=created_at,
            ),
            Message(
                message_id="phase7-followup-user-2",
                session_id=session_id,
                role="user",
                content="What LOTO procedure applies before working on it?",
                mode="normal",
                created_at=new_plan_at - timedelta(milliseconds=20),
            ),
            Message(
                message_id="phase7-followup-assistant-2",
                session_id=session_id,
                role="assistant",
                content="Controlled seeded RAG answer for M-CNC-01 LOTO.",
                mode="normal",
                tool_name="__conversation__",
                created_at=new_plan_at,
            ),
        ]
    )
    await db_session.commit()

    app = await _make_phase7_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/sessions/{session_id}/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["current_intent"] == "What LOTO procedure applies before working on it?"
    assert body["session"]["replan_context"]["contextual_resolution"]["machine_id"] == "M-CNC-01"
    assert body["plan"] is None
    assert body["steps"] == []
    assert "seeded Go API data" not in json.dumps(body["steps"])


@pytest.mark.asyncio
async def test_phase7_cancelled_idle_session_projects_terminal_cancel_event(sessionmaker_override, db_session):
    session_id = "phase7-cancelled-idle-terminal"
    plan_id = "phase7-cancelled-plan"
    created_at = datetime(2026, 5, 17, 10, 0, 0)
    cancelled_at = created_at + timedelta(seconds=3)

    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="IDLE",
            current_intent="Start a seeded cancel jobs run and keep it executing",
            plan_id=plan_id,
            plan_version=1,
            plan_hash="phase7-cancelled-hash",
            current_step_index=0,
            step_count=1,
            llm_call_count=0,
            session_started_at=created_at,
            created_at=created_at,
            updated_at=cancelled_at,
            completed_at=None,
            error="Cancelled",
        )
    )
    db_session.add(
        Message(
            message_id="phase7-cancelled-user",
            session_id=session_id,
            role="user",
            content="Start a seeded cancel jobs run and keep it executing",
            mode="normal",
            created_at=created_at,
        )
    )
    db_session.add(
        Plan(
            plan_id=plan_id,
            session_id=session_id,
            version=1,
            kind="execution",
            status="DRAFT",
            dependency_graph={"0": []},
            parallel_groups=[],
            plan_hash="phase7-cancelled-hash",
            plan_explanation="Seeded cancellable run is staged and ready to execute.",
            risk_summary="Seeded L3 test draft; execution is intentionally backgrounded.",
            created_at=created_at + timedelta(seconds=1),
            created_by="seeded-fake",
        )
    )
    await db_session.commit()

    app = await _make_phase7_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/sessions/{session_id}/snapshot")

    assert response.status_code == 200
    body = response.json()
    cancelled_events = [event for event in body["timeline"] if event["event_type"] == "session_failed"]
    assert cancelled_events
    assert cancelled_events[-1]["content"] == "Run cancelled by operator request."
    assert cancelled_events[-1]["details"]["reason"] == "cancelled_by_user"
    assert body["activity_steps"][-1]["label"] == "Run cancelled"
    assert body["activity_steps"][-1]["detail"] == "Cancelled by operator request"


@pytest.mark.asyncio
async def test_phase7_failed_session_plan_event_uses_failure_guidance_not_stale_success(sessionmaker_override, db_session):
    session_id = "phase7-failed-no-stale-success"
    plan_id = "phase7-failed-plan"
    step_id = "phase7-failed-step"
    created_at = datetime(2026, 5, 16, 10, 0, 0)
    plan_at = created_at + timedelta(seconds=1)
    failed_at = created_at + timedelta(seconds=3)
    safe_guidance = (
        "Could not complete the requested job priority change because the Go API returned "
        "database unavailable. No job rows were changed and no audit rows were created. "
        "Please retry after the backend recovers."
    )

    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="FAILED",
            current_intent="Run Phase 14 Go API 500 commit failure for JOB-SEED-001",
            plan_id=plan_id,
            plan_version=1,
            plan_hash="phase7-failed-hash",
            current_step_index=0,
            step_count=1,
            llm_call_count=0,
            session_started_at=created_at,
            created_at=created_at,
            updated_at=failed_at,
            completed_at=None,
            error="HTTP 500: database unavailable",
        )
    )
    db_session.add(
        Message(
            message_id="phase7-failed-user",
            session_id=session_id,
            role="user",
            content="Run Phase 14 Go API 500 commit failure for JOB-SEED-001",
            mode="normal",
            created_at=created_at,
        )
    )
    db_session.add(
        Plan(
            plan_id=plan_id,
            session_id=session_id,
            version=1,
            kind="execution",
            status="COMPLETED",
            dependency_graph={"0": []},
            parallel_groups=[],
            plan_hash="phase7-failed-hash",
            plan_explanation=safe_guidance,
            risk_summary="Seeded Go API 500 failure must fail safely.",
            created_at=plan_at,
            created_by="seeded-fake",
        )
    )
    db_session.add(
        Message(
            message_id="phase7-failed-stale-plan-message",
            session_id=session_id,
            role="assistant",
            content="**Success**\n\nUpdated **1** job(s).\n\nPriority: **medium**",
            mode="normal",
            tool_name="__plan__",
            step_id=plan_id,
            created_at=plan_at,
        )
    )
    db_session.add(
        PlanStep(
            step_id=step_id,
            plan_id=plan_id,
            session_id=session_id,
            step_index=0,
            tool_name="put__jobs_{id}",
            args={"id": "JOB-SEED-001", "priority": "medium"},
            bindings=[],
            status="FAILED",
            idempotency_key="phase7-failed-idempotency",
            requires_approval=True,
            retry_count=0,
            max_retries=3,
            completed_at=failed_at,
            last_error="HTTP 500: database unavailable",
            result={"error": "database unavailable"},
            result_summary=safe_guidance,
        )
    )
    await db_session.commit()

    app = await _make_phase7_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/sessions/{session_id}/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "FAILED"
    plan_events = [event for event in body["timeline"] if event["event_type"] == "plan_created"]
    assert plan_events
    assert "Could not complete" in plan_events[-1]["content"]
    assert "database unavailable" in plan_events[-1]["content"]
    assert "Please retry" in plan_events[-1]["content"]
    assert "**Success**" not in plan_events[-1]["content"]
    assert "Updated **1** job" not in plan_events[-1]["content"]
    failed_events = [event for event in body["timeline"] if event["event_type"] == "session_failed"]
    assert failed_events[-1]["content"] == "HTTP 500: database unavailable"


@pytest.mark.asyncio
async def test_phase7_completed_graph_checkpoint_prefers_result_summary_over_plan_prose(sessionmaker_override, db_session):
    session_id = "phase7-completed-result-summary"
    created_at = datetime(2026, 5, 13, 10, 44, 22)
    raw_result_text = json.dumps(
        {
            "success": True,
            "data": [
                {"job_id": "JOB-SEED-005", "priority": "low"},
                {"job_id": "JOB-SEED-009", "priority": "low"},
            ],
        }
    )
    expected = (
        "Found 2 low-priority jobs: JOB-SEED-005, JOB-SEED-009. "
        "Details are shown in the table below."
    )

    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="COMPLETED",
            current_intent="find low priority job",
            session_started_at=created_at,
            created_at=created_at,
            updated_at=created_at + timedelta(seconds=9),
            completed_at=created_at + timedelta(seconds=9),
            replan_context={"intent_contract": {"backend": "langgraph"}},
        )
    )
    db_session.add(
        Message(
            message_id="phase7-summary-user",
            session_id=session_id,
            role="user",
            content="find low priority job",
            created_at=created_at + timedelta(seconds=2),
        )
    )
    db_session.add(
        Message(
            message_id="phase7-summary-plan-message",
            session_id=session_id,
            role="assistant",
            content=(
                "Operators can find low priority jobs by executing the following plan:\n\n"
                "1. Fetch low priority jobs.\n\n"
                "Risk summary:\nBefore executing, review tool calls."
            ),
            tool_name="__plan__",
            created_at=created_at + timedelta(seconds=8),
        )
    )
    db_session.add(
        WorkflowCheckpoint(
            thread_id=session_id,
            session_id=session_id,
            state={
                "kind": "langgraph_native_checkpoint",
                "agent_state": {
                    "validated_plan": {
                        "plan_explanation": "Fetch low priority jobs.",
                        "risk_summary": "Review tool calls before execution.",
                        "steps": [
                            {
                                "step_index": 0,
                                "tool_name": "get__jobs",
                                "args": {"priority": "low"},
                                "requires_approval": False,
                            }
                        ],
                    },
                    "completed_actions": [
                        {
                            "phase": "tool_execution",
                            "tool_name": "get__jobs",
                            "args": {"priority": "low"},
                            "status": "http_ok",
                        }
                    ],
                    "tool_outputs": [
                        {
                            "tool_name": "get__jobs",
                            "tool_call_id": "tool-call-jobs",
                            "args": {"priority": "low"},
                            "status": "DONE",
                            "summary": raw_result_text,
                            "result": {
                                "success": True,
                                "data": [
                                    {"job_id": "JOB-SEED-005", "priority": "low"},
                                    {"job_id": "JOB-SEED-009", "priority": "low"},
                                ],
                            },
                        }
                    ],
                },
            },
        )
    )
    await db_session.commit()

    app = await _make_phase7_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/sessions/{session_id}/snapshot")

    assert response.status_code == 200
    body = response.json()
    tool_events = [event for event in body["timeline"] if event["event_type"] == "tool_result"]
    completed_events = [event for event in body["timeline"] if event["event_type"] == "session_completed"]
    assert tool_events[-1]["content"] == expected
    assert completed_events[-1]["content"] == expected
    assert "Operators can" not in completed_events[-1]["content"]


@pytest.mark.asyncio
async def test_phase7_completed_mutation_keeps_rich_final_summary_over_read_tool_summary(sessionmaker_override, db_session):
    session_id = "phase7-rich-mutation-final"
    plan_id = "phase7-rich-mutation-plan"
    created_at = datetime(2026, 5, 17, 17, 42, 12)
    final_summary = (
        "**Success**\n\n"
        "Updated **21** job(s) across **2** write set(s).\n\n"
        "- 10 medium priority jobs changed to high\n"
        "- 11 original high priority jobs changed to low\n\n"
        "No jobs were created or deleted."
    )
    stale_read_summary = (
        "Found 11 high-priority jobs: JOB-SEED-001, JOB-SEED-003, +9 more. "
        "Details are shown in the table below."
    )

    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="COMPLETED",
            current_intent="change all medium priority job to high then change all high priority job to low",
            plan_id=plan_id,
            plan_version=1,
            plan_hash="phase7-rich-mutation-hash",
            current_step_index=0,
            step_count=2,
            llm_call_count=0,
            session_started_at=created_at,
            created_at=created_at,
            updated_at=created_at + timedelta(seconds=3),
            completed_at=created_at + timedelta(seconds=3),
            replan_context={"intent_contract": {"backend": "langgraph"}},
        )
    )
    db_session.add(
        Plan(
            plan_id=plan_id,
            session_id=session_id,
            version=1,
            kind="execution",
            status="COMPLETED",
            dependency_graph={"0": [], "1": [0]},
            parallel_groups=[],
            plan_hash="phase7-rich-mutation-hash",
            plan_explanation="Stage priority update for high-priority jobs.",
            risk_summary="Review tool calls before execution.",
            created_at=created_at + timedelta(seconds=1),
            created_by="langgraph",
        )
    )
    db_session.add(
        Message(
            message_id="phase7-rich-user",
            session_id=session_id,
            role="user",
            content="change all medium priority job to high then change all high priority job to low",
            created_at=created_at + timedelta(milliseconds=100),
        )
    )
    db_session.add(
        Message(
            message_id="phase7-rich-final",
            session_id=session_id,
            role="assistant",
            content=final_summary,
            tool_name="__plan__",
            step_id=plan_id,
            created_at=created_at + timedelta(seconds=3, milliseconds=1),
        )
    )
    db_session.add_all(
        [
            PlanStep(
                step_id="phase7-rich-read",
                plan_id=plan_id,
                session_id=session_id,
                step_index=0,
                tool_name="get__jobs",
                args={"priority": "high"},
                bindings=[],
                status="DONE",
                idempotency_key="phase7-rich-read-key",
                requires_approval=False,
                retry_count=0,
                max_retries=0,
                result={
                    "success": True,
                    "data": [
                        {"job_id": "JOB-SEED-001", "priority": "high"},
                        {"job_id": "JOB-SEED-003", "priority": "high"},
                    ],
                },
                result_summary=stale_read_summary,
                completed_at=created_at + timedelta(seconds=3),
            ),
            PlanStep(
                step_id="phase7-rich-write",
                plan_id=plan_id,
                session_id=session_id,
                step_index=1,
                tool_name="put__jobs_{id}",
                args={"id": "JOB-SEED-001", "priority": "low"},
                bindings=[],
                status="DONE",
                idempotency_key="phase7-rich-write-key",
                requires_approval=True,
                retry_count=0,
                max_retries=0,
                result={
                    "success": True,
                    "data": {
                        "job_id": "JOB-SEED-001",
                        "priority": "low",
                        "previous_priority": "high",
                    },
                },
                result_summary='{"success": true}',
                completed_at=created_at + timedelta(seconds=3),
            ),
        ]
    )
    await db_session.commit()

    app = await _make_phase7_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/sessions/{session_id}/snapshot")

    assert response.status_code == 200
    body = response.json()
    completed_events = [event for event in body["timeline"] if event["event_type"] == "session_completed"]
    assert completed_events[-1]["content"] == final_summary
    assert body["presentation"]["kind"] == "mutation_result"
    assert body["presentation"]["summary"] == final_summary
    assert stale_read_summary not in completed_events[-1]["content"]


def test_phase7_semantic_skips_non_pending_approval_required_event():
    ev = TimelineEventResponse(
        event_id="ar:x",
        event_type="approval_required",
        content="wait",
        created_at=datetime(2026, 5, 13, 9, 0, 0),
        status="APPROVED",
    )
    assert _should_skip_semantic_timeline_event(ev) is True
    pending_ev = ev.model_copy(update={"status": "PENDING"})
    assert _should_skip_semantic_timeline_event(pending_ev) is False


def test_phase7_activity_adapter_skips_non_pending_approval_required():
    created_at = datetime(2026, 5, 13, 9, 0, 0)
    snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-ar-skip",
            "user_id": "u1",
            "status": "EXECUTING",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 0,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=2),
        },
        timeline=[
            TimelineEventResponse(
                event_id="user:ar-skip",
                event_type="user_message",
                content="bulk",
                created_at=created_at,
                role="user",
            ),
            TimelineEventResponse(
                event_id="ar:hist",
                event_type="approval_required",
                content="Waiting",
                created_at=created_at + timedelta(seconds=1),
                approval_id="a-hist",
                status="APPROVED",
            ),
            TimelineEventResponse(
                event_id="ad:hist",
                event_type="approval_decided",
                content="Approved.",
                created_at=created_at + timedelta(seconds=2),
                approval_id="a-hist",
                status="APPROVED",
            ),
        ],
    )
    steps = _activity_steps_for_snapshot(snapshot)
    labels = [s.label for s in steps]
    assert "Waiting for your approval" not in labels
    assert "Approval received" in labels


def test_phase7_activity_waiting_approval_trims_later_replan_noise():
    created_at = datetime(2026, 5, 13, 10, 0, 0)
    snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-waiting-trim",
            "user_id": "u1",
            "status": "WAITING_APPROVAL",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 1,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=5),
        },
        pending_approval={
            "approval_id": "approval-2",
            "session_id": "activity-waiting-trim",
            "subject_type": "graph",
            "subject_id": "tool-2",
            "tool_name": "__langgraph_commit__",
            "args": {},
            "risk_summary": "11 jobs will be updated from high to low priority.",
            "side_effect_level": "HIGH",
            "status": "PENDING",
            "expires_at": created_at + timedelta(hours=1),
            "created_at": created_at + timedelta(seconds=3),
        },
        timeline=[
            TimelineEventResponse(
                event_id="ar:one",
                event_type="approval_required",
                content="Waiting for your approval: 10 jobs will be updated from medium to high priority.",
                created_at=created_at + timedelta(seconds=1),
                approval_id="approval-1",
                status="PENDING",
            ),
            TimelineEventResponse(
                event_id="ad:one",
                event_type="approval_decided",
                content="Approved request to change record.",
                created_at=created_at + timedelta(seconds=2),
                approval_id="approval-1",
                status="APPROVED",
            ),
            TimelineEventResponse(
                event_id="ar:two",
                event_type="approval_required",
                content="Waiting for your approval: 11 jobs will be updated from high to low priority.",
                created_at=created_at + timedelta(seconds=3),
                approval_id="approval-2",
                status="PENDING",
            ),
            TimelineEventResponse(
                event_id="replan:after-second-approval",
                event_type="replan_requested",
                content="Refining response copy after approval projection.",
                created_at=created_at + timedelta(seconds=4),
                status="PLANNING",
            ),
        ],
    )

    steps = _activity_steps_for_snapshot(snapshot)

    assert steps[-1].label == "Waiting for your approval"
    assert steps[-1].state == "waiting"
    assert "Improving the response" not in [step.label for step in steps]


def test_phase7_activity_does_not_merge_plan_created_across_different_plan_ids():
    created_at = datetime(2026, 5, 13, 11, 0, 0)
    snapshot = SessionSnapshotResponse(
        session={
            "session_id": "activity-plan-merge",
            "user_id": "u1",
            "status": "COMPLETED",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 0,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=5),
        },
        timeline=[
            TimelineEventResponse(
                event_id="pc-a",
                event_type="plan_created",
                content="first",
                created_at=created_at + timedelta(seconds=1),
                details={"plan_id": "plan-a"},
            ),
            TimelineEventResponse(
                event_id="pc-b",
                event_type="plan_created",
                content="second",
                created_at=created_at + timedelta(seconds=2),
                details={"plan_id": "plan-b"},
            ),
            TimelineEventResponse(
                event_id="sc-merge",
                event_type="session_completed",
                content="ok",
                created_at=created_at + timedelta(seconds=3),
                status="COMPLETED",
            ),
        ],
    )
    steps = _activity_steps_for_snapshot(snapshot)
    assert [s.label for s in steps if s.label == "Understood request"] == [
        "Understood request",
        "Understood request",
    ]


def test_phase7_activity_injects_plan_execution_when_timeline_omits_tool_rows():
    created_at = datetime(2026, 5, 13, 12, 0, 0)
    plan = PlanResponse(
        plan_id="p-inject",
        session_id="s-inject",
        version=1,
        plan_hash="h1",
        created_at=created_at,
        created_by="u1",
    )
    step_row = PlanStepResponse(
        step_id="st1",
        plan_id="p-inject",
        session_id="s-inject",
        step_index=0,
        tool_name="get__jobs_{id}",
        args={},
        execution_mode="single",
        bindings=[],
        bulk_state=None,
        status="DONE",
        idempotency_key="k1",
        requires_approval=False,
        approval_id=None,
        retry_count=0,
        max_retries=0,
    )
    snapshot = SessionSnapshotResponse(
        session={
            "session_id": "s-inject",
            "user_id": "u1",
            "status": "COMPLETED",
            "plan_version": 1,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 0,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=2),
        },
        plan=plan,
        steps=[step_row],
        timeline=[
            TimelineEventResponse(
                event_id="u-inj",
                event_type="user_message",
                content="hi",
                created_at=created_at,
                role="user",
            ),
            TimelineEventResponse(
                event_id="pl-inj",
                event_type="plan_created",
                content="plan",
                created_at=created_at + timedelta(seconds=1),
                details={"plan_id": "p-inject"},
            ),
            TimelineEventResponse(
                event_id="sc-inj",
                event_type="session_completed",
                content="done",
                created_at=created_at + timedelta(seconds=2),
                status="COMPLETED",
            ),
        ],
    )
    steps = _activity_steps_for_snapshot(snapshot)
    labels = [s.label for s in steps]
    assert "Understood request" in labels
    assert "Updating job records" in labels
    assert labels[-1] == "Run complete"


def test_so012_semantic_timeline_projection_keeps_both_approval_ids():
    oracle = load_oracle("SO-012")
    created_at = datetime(2026, 5, 13, 13, 0, 0)
    approval_events = [
        TimelineEventResponse(
            event_id=f"so012:{index}",
            event_type="approval_required" if row["event"] == "approval_requested" else "approval_decided",
            content=f"{row['event']} {row['approval_id']}",
            created_at=created_at + timedelta(seconds=index),
            approval_id=row["approval_id"],
            status="PENDING" if row["event"] == "approval_requested" else "APPROVED",
        )
        for index, row in enumerate(oracle["expected_timeline"])
        if row.get("event") in {"approval_requested", "approval_decided"}
    ]

    payloads = [
        _semantic_payload_for_timeline_event(event, session_id="so012-session")
        for event in approval_events
        if not _should_skip_semantic_timeline_event(event)
    ]

    assert [payload["approval_id"] for payload in payloads] == [
        "approval-so-012-1",
        "approval-so-012-1",
        "approval-so-012-2",
        "approval-so-012-2",
    ]
    assert [payload["type"] for payload in payloads] == [
        "APPROVAL_REQUIRED",
        "APPROVAL_DECIDED",
        "APPROVAL_REQUIRED",
        "APPROVAL_DECIDED",
    ]


def test_so013_activity_suppresses_completion_until_terminal_snapshot():
    oracle = load_oracle("SO-013")
    created_at = datetime(2026, 5, 13, 14, 0, 0)
    active = SessionSnapshotResponse(
        session={
            "session_id": "so013-active",
            "user_id": "u1",
            "status": "EXECUTING",
            "plan_version": 0,
            "current_step_index": 0,
            "step_count": 1,
            "replan_count": 0,
            "llm_call_count": 1,
            "session_started_at": created_at,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=3),
        },
        timeline=[
            TimelineEventResponse(
                event_id="so013:approval",
                event_type="approval_decided",
                content="Approved.",
                created_at=created_at + timedelta(seconds=1),
                approval_id="approval-so-013-1",
                status="APPROVED",
            ),
            TimelineEventResponse(
                event_id="so013:premature-complete",
                event_type="session_completed",
                content="2 high priority jobs changed to medium",
                created_at=created_at + timedelta(seconds=2),
                status="COMPLETED",
            ),
        ],
    )
    terminal = active.model_copy(
        deep=True,
        update={
            "session": {
                **active.session.model_dump(),
                "status": oracle["expected_final_state"]["session_phase"],
            }
        },
    )

    assert "Run complete" not in [step.label for step in _activity_steps_for_snapshot(active)]
    assert _activity_steps_for_snapshot(terminal)[-1].label == "Run complete"
