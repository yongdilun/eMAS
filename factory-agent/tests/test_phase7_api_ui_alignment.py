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
from factory_agent.api.routes import _semantic_payload_for_timeline_event
from factory_agent.config import Settings
from factory_agent.observability.events import AgentEvent
from factory_agent.persistence import database as persistence_database
from factory_agent.persistence.models import Approval, Message, Plan, PlanStep, Session, WorkflowCheckpoint
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import TimelineEventResponse


class _FakeEventBus:
    def __init__(self):
        self.published: list[AgentEvent] = []

    async def publish(self, event: AgentEvent) -> None:
        self.published.append(event)

    async def listen(self, handler: Any) -> None:
        return None


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
