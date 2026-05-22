from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage

from factory_agent.config import get_settings
from factory_agent.graph.checkpointing import clear_graph_checkpointer_cache
from factory_agent.graph.errors import LangGraphPlannerApprovalRequired
from factory_agent.graph.planner_graph import LangGraphPlanner
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
from factory_agent.schemas import ToolInfo
from factory_agent.api import build_router
from factory_agent.persistence import database


@pytest.mark.asyncio
async def test_durable_checkpoint_resumes_approval_after_process_restart(monkeypatch):
    session_id = f"phase6-{uuid.uuid4()}"
    db_dir = Path(".pytest-phase6")
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"graph-checkpoints-{uuid.uuid4()}.db"
    settings = replace(
        get_settings(),
        database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        openai_api_key="test-key",
        planner_openai_base_url=None,
        graph_checkpoint_backend="db",
        go_api_base_url="http://testserver",
        max_plan_steps=8,
    )
    write_tool = ToolInfo(
        name="post__jobs",
        description="create job",
        endpoint="/jobs",
        method="POST",
        input_schema={"type": "object"},
        is_read_only=False,
        requires_approval=True,
    )
    planner_prompts: list[str] = []
    events: list[str] = []

    class FakeModel:
        async def ainvoke(self, prompt: str):
            planner_prompts.append(prompt)
            marker = "Current intent JSON: "
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\nUser query:", start)
            intent_id = json.loads(prompt[start:end])["intent_id"]
            if len(planner_prompts) == 1:
                payload = {
                    "intent_id": intent_id,
                    "kind": "domain_tool",
                    "tool_calls": [
                        {
                            "tool_name": "post__jobs",
                            "args": {"product_id": "P-001", "quantity_total": 10},
                            "output_ref": "$ref:job",
                        }
                    ],
                    "decision_summary": "Stage the requested job.",
                    "risk_level": "write_dry_run",
                }
            else:
                payload = {
                    "intent_id": intent_id,
                    "kind": "intent_completed",
                    "tool_calls": [],
                    "decision_summary": "The staged job satisfies the request.",
                    "risk_level": "write_commit",
                }
            return AIMessage(content=json.dumps(payload))

    async def fake_dry_run(state, *, settings):
        events.append("bundle_dry_run")
        return {
            "bundle_dry_run_result": {"ok": True, "http_status": 200, "body": {"validated": True}},
            "completed_actions": [{"phase": "bundle_dry_run", "status": "ok"}],
        }

    async def fake_commit(state, *, settings):
        events.append("commit")
        assert state["approval_requests"][0]["status"] == "approved"
        return {
            "last_commit_result": {"ok": True, "http_status": 200, "body": {"committed": True}},
            "completed_actions": [{"phase": "commit", "status": "ok"}],
        }

    clear_graph_checkpointer_cache()
    monkeypatch.setattr(
        "factory_agent.graph.nodes.planner_loop.build_planner_chat_model",
        lambda settings, json_mode=True: FakeModel(),
    )
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.bundle_dry_run_node", fake_dry_run)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.commit_node_impl", fake_commit)

    with pytest.raises(LangGraphPlannerApprovalRequired):
        await LangGraphPlanner(settings).generate(
            intent="Create a job for product P-001 quantity 10",
            scoped_tools=[write_tool],
            context={"session_id": session_id},
        )

    assert events == ["bundle_dry_run"]
    prompt_count_before_resume = len(planner_prompts)

    clear_graph_checkpointer_cache()
    draft, contract, _outputs = await LangGraphPlanner(settings).resume_after_approval(session_id=session_id, approved=True)

    assert events == ["bundle_dry_run", "commit"]
    assert len(planner_prompts) == prompt_count_before_resume
    assert draft.steps[0].tool_name == "post__jobs"
    assert contract["backend"] == "langgraph"


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
