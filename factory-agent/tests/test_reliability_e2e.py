import asyncio
import json

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
from factory_agent.api import build_router
from factory_agent.config import Settings
from factory_agent.graph.errors import LangGraphPlannerApprovalRequired
from factory_agent.persistence.database import Base
from factory_agent.persistence.models import Tool, generate_uuid
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import PlanDraft, PlanStepDraft
from factory_agent.services.planner_service import PlannerService


class FakeEventBus:
    def __init__(self):
        self.published = []

    async def publish(self, event):
        self.published.append(event)

    async def listen(self, handler):
        del handler
        return


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        admin_api_key="test-admin-key",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
        retry_base_delay_s=0.0,
        retry_max_delay_s=0.0,
        planner_max_retries=2,
        memory_enabled=False,
        checkpoint_enabled=False,
        enforce_tool_registry_health=False,
        auto_repair_tool_registry=False,
        min_healthy_tool_count=1,
        summary_backend="deterministic",
        tool_result_summary_backend="deterministic",
        tool_selector_backend="auto",
    )


async def _seed_tool(
    db: AsyncSession,
    *,
    name: str,
    endpoint: str,
    method: str,
    input_schema: dict,
    tags: list[str],
    is_read_only: bool,
    requires_approval: bool = False,
):
    db.add(
        Tool(
            tool_id=generate_uuid(),
            name=name,
            description=name,
            endpoint=endpoint,
            method=method,
            version=1,
            schema_version=1,
            input_schema=input_schema,
            output_schema={"type": "object"},
            is_read_only=is_read_only,
            requires_approval=requires_approval,
            side_effect_level="NONE" if is_read_only else "HIGH",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=json.dumps(tags),
        )
    )
    await db.commit()


async def _with_client(planner_cls, seed):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as db:
        await seed(db)

    app = FastAPI()

    async def override_get_db():
        async with maker() as db:
            yield db

    event_bus = FakeEventBus()
    app.dependency_overrides[database.get_db] = override_get_db
    app.include_router(
        build_router(
            settings=_settings(),
            tool_registry=ToolRegistry(),
            event_bus=event_bus,
        )
    )

    previous = PlannerService._langgraph_planner_cls
    PlannerService._langgraph_planner_cls = planner_cls
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, event_bus
    finally:
        PlannerService._langgraph_planner_cls = previous
        await engine.dispose()


async def _create_session_with_message(client: httpx.AsyncClient, content: str) -> str:
    created = await client.post("/sessions", json={"user_id": "reliability-user", "name": "reliability"})
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    added = await client.post(
        f"/sessions/{session_id}/messages",
        json={"role": "user", "content": content, "mode": "normal"},
    )
    assert added.status_code == 200, added.text
    return session_id


def test_pause_resume_live_instruction_update_rejects_stale_approval_and_completes():
    class PauseResumePlanner:
        generate_calls = 0
        resume_calls = 0

        def __init__(self, settings):
            del settings

        async def generate(self, *, intent, scoped_tools, context=None):
            del scoped_tools, context
            type(self).generate_calls += 1
            qty = 2 if type(self).generate_calls == 1 else 4
            raise LangGraphPlannerApprovalRequired(
                {
                    "kind": "approval_required",
                    "summary": f"Create job for P-005 quantity {qty}.",
                    "preview": [
                        {
                            "tool_name": "post__jobs",
                            "args": {"product_id": "P-005", "quantity_total": qty},
                        }
                    ],
                    "intent": intent,
                }
            )

        async def resume_after_approval(self, *, session_id, approved):
            type(self).resume_calls += 1
            assert approved is True
            return (
                PlanDraft(
                    plan_explanation="Approved revised job creation.",
                    risk_summary="Operator approved the revised write bundle.",
                    steps=[
                        PlanStepDraft(
                            step_index=0,
                            tool_name="post__jobs",
                            args={"product_id": "P-005", "quantity_total": 4},
                        )
                    ],
                ),
                {"intent": session_id, "backend": "langgraph", "steps": []},
                [
                    {
                        "tool_name": "post__jobs",
                        "args": {"product_id": "P-005", "quantity_total": 4},
                        "result": {"success": True, "data": {"job_id": "JOB-NEW-004"}},
                        "summary": "Created job JOB-NEW-004 for quantity 4.",
                    }
                ],
            )

    async def seed(db):
        await _seed_tool(
            db,
            name="post__jobs",
            endpoint="/jobs",
            method="POST",
            input_schema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "quantity_total": {"type": "integer"},
                },
                "required": ["product_id", "quantity_total"],
            },
            tags=["job", "create"],
            is_read_only=False,
            requires_approval=True,
        )

    async def run():
        async for client, _ in _with_client(PauseResumePlanner, seed):
            session_id = await _create_session_with_message(
                client,
                "create job for product P-005 quantity 2",
            )
            first_plan = await client.post(f"/sessions/{session_id}/plans", json={})
            assert first_plan.status_code == 200, first_plan.text

            snapshot = await client.get(f"/sessions/{session_id}/snapshot")
            assert snapshot.status_code == 200, snapshot.text
            first_pending = snapshot.json()["pending_approval"]
            assert first_pending["status"] == "PENDING"

            update = await client.post(
                f"/sessions/{session_id}/messages",
                json={
                    "role": "user",
                    "content": "create job for product P-005 quantity 4 instead",
                    "mode": "normal",
                },
            )
            assert update.status_code == 200, update.text

            old_approval = await client.get(f"/approvals/{first_pending['approval_id']}")
            assert old_approval.status_code == 200, old_approval.text
            old_body = old_approval.json()
            assert old_body["status"] == "REJECTED"
            assert old_body["rejection_reason"] == "Superseded by user message"

            after_update = await client.get(f"/sessions/{session_id}/snapshot")
            assert after_update.status_code == 200, after_update.text
            session_after_update = after_update.json()["session"]
            assert session_after_update["status"] == "PLANNING"
            assert session_after_update["replan_count"] >= 1
            assert after_update.json()["pending_approval"] is None

            second_plan = await client.post(f"/sessions/{session_id}/plans", json={})
            assert second_plan.status_code == 200, second_plan.text
            second_snapshot = await client.get(f"/sessions/{session_id}/snapshot")
            second_pending = second_snapshot.json()["pending_approval"]
            assert second_pending["approval_id"] != first_pending["approval_id"]
            assert "quantity 4" in second_pending["risk_summary"]

            approved = await client.post(
                f"/approvals/{second_pending['approval_id']}/approve",
                json={"decided_by": "operator"},
            )
            assert approved.status_code == 200, approved.text
            final_body = None
            for _ in range(20):
                final_snapshot = await client.get(f"/sessions/{session_id}/snapshot")
                final_body = final_snapshot.json()
                if final_body["session"]["status"] == "COMPLETED" and "JOB-NEW-004" in json.dumps(final_body):
                    break
                await asyncio.sleep(0.05)
            assert final_body is not None
            assert final_body["session"]["status"] == "COMPLETED"
            assert final_body["pending_approval"] is None
            assert "JOB-NEW-004" in json.dumps(final_body)
            assert PauseResumePlanner.generate_calls == 2
            assert PauseResumePlanner.resume_calls == 1

    asyncio.run(run())


def test_transient_llm_failure_is_retried_without_losing_session_state():
    class FlakyPlanner:
        attempts = 0

        def __init__(self, settings):
            del settings

        async def generate(self, *, intent, scoped_tools, context=None):
            del scoped_tools, context
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise TimeoutError("model gateway timeout")
            return (
                PlanDraft(
                    plan_explanation=f"Recovered plan for {intent}",
                    risk_summary="Read-only retry recovery.",
                    steps=[PlanStepDraft(step_index=0, tool_name="get__jobs", args={})],
                ),
                {"intent": intent, "backend": "langgraph", "steps": []},
                [
                    {
                        "tool_name": "get__jobs",
                        "args": {},
                        "result": {"success": True, "data": [{"job_id": "JOB-SEED-001"}]},
                        "summary": "Retrieved JOB-SEED-001 after retry.",
                    }
                ],
            )

        async def resume_after_approval(self, *, session_id, approved):
            raise AssertionError(f"unexpected resume for {session_id} approved={approved}")

    async def seed(db):
        await _seed_tool(
            db,
            name="get__jobs",
            endpoint="/jobs",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            tags=["job", "list", "read"],
            is_read_only=True,
        )

    async def run():
        async for client, _ in _with_client(FlakyPlanner, seed):
            session_id = await _create_session_with_message(client, "show jobs")
            created = await client.post(f"/sessions/{session_id}/plans", json={})
            assert created.status_code == 200, created.text
            assert FlakyPlanner.attempts == 2

            snapshot = await client.get(f"/sessions/{session_id}/snapshot")
            body = snapshot.json()
            assert body["session"]["status"] == "COMPLETED"
            assert body["session"]["current_intent"] == "show jobs"
            assert "JOB-SEED-001" in json.dumps(body)

            messages = await client.get(f"/sessions/{session_id}/messages")
            user_messages = [m for m in messages.json() if m["role"] == "user"]
            assert [m["content"] for m in user_messages] == ["show jobs"]

    asyncio.run(run())


def test_rag_sources_and_normal_tool_output_share_the_same_snapshot():
    class RagToolPlanner:
        def __init__(self, settings):
            del settings

        async def generate(self, *, intent, scoped_tools, context=None):
            del scoped_tools, context
            return (
                PlanDraft(
                    plan_explanation=f"Use safety guidance and machine state for: {intent}",
                    risk_summary="Read-only API lookup plus cited safety guidance.",
                    sources=[
                        {
                            "doc_id": "osha_3120_lockout_tagout",
                            "title": "OSHA Lockout/Tagout Guidance",
                            "source_type": "rag",
                        }
                    ],
                    safety_content="LOTO guidance is safety critical; verify with an authorized operator.",
                    steps=[
                        PlanStepDraft(
                            step_index=0,
                            tool_name="get__machines_{id}",
                            args={"id": "M-CNC-01"},
                        )
                    ],
                ),
                {"intent": intent, "backend": "langgraph", "steps": []},
                [
                    {
                        "tool_name": "get__machines_{id}",
                        "args": {"id": "M-CNC-01"},
                        "result": {
                            "success": True,
                            "data": {"machine_id": "M-CNC-01", "status": "maintenance"},
                        },
                        "summary": "Machine M-CNC-01 is currently in maintenance.",
                    }
                ],
            )

        async def resume_after_approval(self, *, session_id, approved):
            raise AssertionError(f"unexpected resume for {session_id} approved={approved}")

    async def seed(db):
        await _seed_tool(
            db,
            name="get__machines_{id}",
            endpoint="/machines/{id}",
            method="GET",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            tags=["machine", "status", "read"],
            is_read_only=True,
        )

    async def run():
        async for client, _ in _with_client(RagToolPlanner, seed):
            session_id = await _create_session_with_message(
                client,
                "Use OSHA LOTO guidance and show machine M-CNC-01 status",
            )
            created = await client.post(f"/sessions/{session_id}/plans", json={})
            assert created.status_code == 200, created.text
            snapshot = await client.get(f"/sessions/{session_id}/snapshot")
            body = snapshot.json()
            assert body["session"]["status"] == "COMPLETED"
            assert body["plan"]["sources"][0]["doc_id"] == "osha_3120_lockout_tagout"
            assert "safety critical" in body["plan"]["safety_content"]
            assert body["steps"][0]["tool_name"] == "get__machines_{id}"
            assert body["steps"][0]["status"] == "DONE"
            searchable = json.dumps(body).lower()
            assert "m-cnc-01" in searchable
            assert "osha lockout/tagout guidance" in searchable

    asyncio.run(run())
