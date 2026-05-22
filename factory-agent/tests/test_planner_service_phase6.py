from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from factory_agent.config import get_settings
from factory_agent.persistence.models import (
    Approval,
    Message,
    Plan,
    PlanStep,
    Session,
    WorkflowCheckpoint,
    generate_uuid,
)
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.api import build_router
from factory_agent.persistence import database


class _FakeEventBus:
    def __init__(self):
        self.published = []

    async def publish(self, event):
        self.published.append(event)

    async def listen(self, handler):
        return


async def _make_phase6_app(sessionmaker_override):
    settings = replace(
        get_settings(),
        database_url="sqlite+aiosqlite:///:memory:",
        worker_count=0,
        enforce_tool_registry_health=False,
        auto_repair_tool_registry=False,
    )
    app = FastAPI()

    async def override_get_db():
        async with sessionmaker_override() as session:
            yield session

    app.dependency_overrides[database.get_db] = override_get_db
    app.include_router(
        build_router(
            settings=settings,
            tool_registry=ToolRegistry(),
            event_bus=_FakeEventBus(),
        )
    )
    return app


@pytest.mark.asyncio
async def test_graph_native_snapshot_uses_checkpoint_projection_not_legacy_steps(sessionmaker_override, db_session):
    session_id = "phase6-snapshot"
    plan_id = "legacy-plan"
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="WAITING_APPROVAL",
            current_intent="create a job",
            replan_context={"langgraph_pending_approval": {"approval_id": "graph-approval", "thread_id": session_id}},
        )
    )
    db_session.add(
        Plan(
            plan_id=plan_id,
            session_id=session_id,
            version=1,
            kind="execution",
            status="DRAFT",
            plan_hash="legacy-hash",
            created_by="llm",
        )
    )
    db_session.add(
        PlanStep(
            step_id="legacy-step",
            plan_id=plan_id,
            session_id=session_id,
            step_index=0,
            tool_name="get__machines",
            args={},
            status="DONE",
            idempotency_key="legacy-step-key",
            result={"legacy": True},
            result_summary="legacy step should not appear",
            completed_at=datetime.utcnow(),
        )
    )
    db_session.add(
        Message(
            message_id=generate_uuid(),
            session_id=session_id,
            role="tool_result",
            content="legacy tool event should not appear",
            step_id="legacy-step",
        )
    )
    db_session.add(
        Approval(
            approval_id="graph-approval",
            session_id=session_id,
            subject_type="graph",
            tool_name="__langgraph_commit__",
            args={},
            risk_summary="approve graph commit",
            side_effect_level="HIGH",
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(hours=1),
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
                        "plan_explanation": "graph plan",
                        "risk_summary": "graph risk",
                        "steps": [
                            {
                                "step_index": 0,
                                "tool_name": "post__jobs",
                                "args": {"product_id": "P-001"},
                                "requires_approval": True,
                            }
                        ],
                    },
                    "tool_outputs": [],
                    "completed_actions": [],
                },
            },
        )
    )
    await db_session.commit()

    app = await _make_phase6_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/sessions/{session_id}/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert [step["tool_name"] for step in body["steps"]] == ["post__jobs"]
    assert all(event["tool_name"] != "get__machines" for event in body["timeline"])
    assert body["pending_approval"]["subject_type"] == "graph"


@pytest.mark.asyncio
async def test_legacy_step_reject_cannot_mutate_graph_native_session(sessionmaker_override, db_session):
    session_id = "phase6-step-reject"
    approval_id = "legacy-step-approval"
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="WAITING_APPROVAL",
            current_intent="create a job",
            error="waiting",
            replan_context={"langgraph_pending_approval": {"approval_id": "graph-approval", "thread_id": session_id}},
        )
    )
    db_session.add(
        Approval(
            approval_id=approval_id,
            session_id=session_id,
            subject_type="step",
            step_id="legacy-step",
            tool_name="post__jobs",
            args={},
            risk_summary="legacy approval",
            side_effect_level="HIGH",
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    await db_session.commit()

    app = await _make_phase6_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/approvals/{approval_id}/reject",
            json={"decided_by": "u1", "rejection_reason": "no"},
        )

    assert response.status_code == 410
    approval = await db_session.get(Approval, approval_id)
    session = await db_session.get(Session, session_id)
    assert approval.status == "PENDING"
    assert approval.decided_at is None
    assert session.status == "WAITING_APPROVAL"
    assert session.error == "waiting"
