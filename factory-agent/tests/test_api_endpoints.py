import pytest
import sys
import types
import asyncio
from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import json
import time

import httpx
from fastapi import FastAPI
from sqlalchemy import select

import database
from factory_agent.api import build_router
from factory_agent.config import Settings
from factory_agent.schemas import PlanDraft, PlanStepDraft
from factory_agent.registry.tool_registry import ToolRegistry


LEGACY_PLAN_STEP_PROJECTION_XFAIL = pytest.mark.xfail(
    reason=(
        "Legacy compatibility expectation from the pre-Phase-9 create-plan/execute "
        "contract; graph-native execution no longer treats auto-created PlanStep rows "
        "as execution truth."
    ),
    strict=True,
)

LEGACY_RUNTIME_RETIRED_XFAIL = pytest.mark.xfail(
    reason=(
        "Legacy relational PlanStep execution, step approvals, DLQ replay, and "
        "background worker execution are retired; graph-native checkpoint execution "
        "is now the only active runtime."
    ),
    strict=True,
)


class FakeEventBus:
    def __init__(self):
        self.published = []

    async def publish(self, event):
        self.published.append(event)

    async def listen(self, handler):
        return


def _sign_test_jwt(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    encoded_header = b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    encoded_payload = b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    encoded_sig = b64url(signature)
    return f"{encoded_header}.{encoded_payload}.{encoded_sig}"


def _auth_headers(secret: str, sub: str = "u1") -> dict[str, str]:
    now = int(time.time())
    token = _sign_test_jwt({"sub": sub, "exp": now + 300}, secret)
    return {"Authorization": f"Bearer {token}"}


async def _make_app(
    sessionmaker_override,
    enqueue_session=None,
    jwt_required=False,
    jwt_secret=None,
    planner_adapter=None,
    database_url="sqlite+aiosqlite:///:memory:",
    enforce_tool_registry_health=True,
    auto_repair_tool_registry=True,
    min_healthy_tool_count=20,
    tool_selector_backend="auto",
    openai_base_url=None,
    rag_pipeline_adapter=None,
):
    worker_count = 1 if enqueue_session is not None else 0
    settings = Settings(
        database_url=database_url,
        redis_url=None,
        go_api_base_url="http://testserver",
        admin_api_key="test-admin-key",
        worker_count=worker_count,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
        jwt_required=jwt_required,
        jwt_secret=jwt_secret,
        jwt_clock_skew_s=30,
        enforce_tool_registry_health=enforce_tool_registry_health,
        auto_repair_tool_registry=auto_repair_tool_registry,
        min_healthy_tool_count=min_healthy_tool_count,
        tool_selector_backend=tool_selector_backend,
        openai_base_url=openai_base_url,
    )
    tool_registry = ToolRegistry()
    event_bus = FakeEventBus()

    app = FastAPI()

    async def override_get_db():
        async with sessionmaker_override() as s:
            yield s

    app.dependency_overrides[database.get_db] = override_get_db
    app.include_router(
        build_router(
            settings=settings,
            tool_registry=tool_registry,
            event_bus=event_bus,
            enqueue_session=enqueue_session,
            planner_adapter=planner_adapter,
            rag_pipeline_adapter=rag_pipeline_adapter,
        )
    )
    return app, event_bus


async def _seed_tool(db_session, *, name, endpoint, method, input_schema, capability_tags, is_read_only=True, requires_approval=False):
    from factory_agent.persistence.models import Tool, generate_uuid

    db_session.add(
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
            capability_tags=capability_tags,
        )
    )
    await db_session.commit()


async def _seed_session_plan_with_steps(
    db_session,
    *,
    session_id: str,
    plan_id: str,
    plan_hash: str,
    plan_version: int,
    steps: list[dict],
):
    from factory_agent.persistence.models import Plan, PlanStep, Session, generate_uuid
    from factory_agent.tools.arguments import compute_idempotency_key

    sess = Session(
        session_id=session_id,
        user_id="u1",
        status="WAITING_APPROVAL",
        plan_id=plan_id,
        plan_version=plan_version,
        plan_hash=plan_hash,
        current_step_index=0,
        step_count=0,
        replan_count=0,
        llm_call_count=0,
        session_started_at=datetime.utcnow(),
    )
    plan = Plan(
        plan_id=plan_id,
        session_id=session_id,
        version=plan_version,
        dependency_graph={},
        parallel_groups=[],
        plan_hash=plan_hash,
        plan_explanation="x",
        risk_summary="x",
        created_by="llm",
    )
    db_session.add_all([sess, plan])
    await db_session.commit()

    for step in steps:
        args = step.get("args", {})
        step_index = step["step_index"]
        row = PlanStep(
            step_id=step.get("step_id", generate_uuid()),
            plan_id=plan_id,
            session_id=session_id,
            step_index=step_index,
            tool_name=step["tool_name"],
            args=args,
            status=step.get("status", "NOT_STARTED"),
            idempotency_key=compute_idempotency_key(
                session_id=session_id,
                step_index=step_index,
                plan_version=plan_version,
                args=args,
            ),
            requires_approval=step.get("requires_approval", False),
            approval_id=step.get("approval_id"),
            retry_count=0,
            max_retries=3,
        )
        db_session.add(row)
    await db_session.commit()


@pytest.mark.asyncio
async def test_create_session_and_message_updates_intent(sessionmaker_override, db_session):
    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/sessions", json={"user_id": "u1"})
        assert r.status_code == 200
        session_id = r.json()["session_id"]

        r2 = await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "machine status"})
        assert r2.status_code == 200

        r3 = await client.get(f"/sessions/{session_id}")
        assert r3.status_code == 200
        assert "machine status" in (r3.json().get("current_intent") or "")


@pytest.mark.asyncio
async def test_create_plan_rejects_tool_not_in_scope(sessionmaker_override, db_session):
    # Seed 8 machine tools + 1 inventory tool (should be excluded once picked>=8 and score==0)
    machine_schema = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    for i in range(8):
        await _seed_tool(
            db_session,
            name=f"get__machines_{i}",
            endpoint=f"/machines_{i}",
            method="GET",
            input_schema=machine_schema,
            capability_tags='["machine"]',
            is_read_only=True,
        )
    await _seed_tool(
        db_session,
        name="post__inventory_update",
        endpoint="/inventory",
        method="POST",
        input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        capability_tags='["inventory"]',
        is_read_only=False,
        requires_approval=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/sessions", json={"user_id": "u1"})
        session_id = r.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "machine"})

        draft = PlanDraft(
            plan_explanation="do it",
            risk_summary="writes inventory",
            steps=[PlanStepDraft(step_index=0, tool_name="post__inventory_update", args={"id": 1})],
        )
        r2 = await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        assert r2.status_code == 400


@pytest.mark.asyncio
async def test_create_plan_persists_plan_and_steps(sessionmaker_override, db_session):
    schema = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema=schema,
        capability_tags='["machine"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/sessions", json={"user_id": "u1"})
        session_id = r.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "machine"})

        draft = PlanDraft(
            plan_explanation="fetch machines",
            risk_summary="read-only",
            steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={"id": 1})],
        )
        r2 = await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        assert r2.status_code == 200
        body = r2.json()
        assert body["session_id"] == session_id
        assert body["plan_hash"]


@pytest.mark.asyncio
async def test_create_plan_rolls_back_when_plan_message_persistence_fails(
    sessionmaker_override,
    db_session,
    monkeypatch,
):
    from factory_agent.api import routes
    from factory_agent.persistence.models import Message, Plan, PlanStep, Session

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        capability_tags='["machine"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/sessions", json={"user_id": "u1"})
        session_id = r.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "machine"})

    ids = iter(["phase2-plan-id", "phase2-step-id"])

    def fail_on_plan_message_id():
        try:
            return next(ids)
        except StopIteration:
            raise RuntimeError("injected plan message failure")

    monkeypatch.setattr(routes, "generate_uuid", fail_on_plan_message_id)
    draft = PlanDraft(
        plan_explanation="fetch machines",
        risk_summary="read-only",
        steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={"id": 1})],
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        failed = await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        assert failed.status_code == 500

    db_session.expire_all()
    plans = (await db_session.execute(select(Plan).where(Plan.session_id == session_id))).scalars().all()
    steps = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().all()
    messages = (await db_session.execute(select(Message).where(Message.session_id == session_id))).scalars().all()
    sess = await db_session.get(Session, session_id)

    assert plans == []
    assert steps == []
    assert [msg.role for msg in messages] == ["user"]
    assert sess.plan_id is None
    assert sess.plan_version == 0


@pytest.mark.asyncio
async def test_create_plan_without_draft_uses_planner_adapter(sessionmaker_override, db_session):
    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["machine"]',
        is_read_only=True,
    )

    class FakePlanner:
        async def generate_plan(self, *, intent, scoped_tools, context=None):
            del scoped_tools, context
            return type(
                "X",
                (),
                {
                    "draft": PlanDraft(
                        plan_explanation=f"Auto plan for {intent}",
                        risk_summary="read-only",
                        steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={})],
                    ),
                    "backend_used": "langgraph",
                    "llm_calls": 0,
                },
            )()

    app, _ = await _make_app(sessionmaker_override, planner_adapter=FakePlanner())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/sessions", json={"user_id": "u1"})
        session_id = r.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "machine"})

        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        assert created.json()["created_by"] == "langgraph"


@pytest.mark.asyncio
async def test_create_plan_answers_osha_loto_knowledge_question_without_tool_plan(sessionmaker_override):
    class FakeRAGPipeline:
        def __init__(self):
            self.calls = []

        async def run(self, *, query, session_id=None, route="RAG_ONLY", api_data=None):
            self.calls.append(
                {
                    "query": query,
                    "session_id": session_id,
                    "route": route,
                    "api_data": api_data,
                }
            )
            return type(
                "Result",
                (),
                {
                    "answer": (
                        "According to OSHA, Lockout/Tagout procedures control hazardous energy so "
                        "machines are isolated and rendered safe before servicing or maintenance."
                    ),
                    "sources": [
                        {
                            "source_number": 1,
                            "doc_id": "osha_3120_lockout_tagout",
                            "title": "Control of Hazardous Energy Lockout/Tagout",
                            "organization": "OSHA",
                            "authority_level": "official_public_guidance",
                        }
                    ],
                    "safety_content": (
                        "This topic involves high-risk industrial procedures. Follow your site's approved SOP."
                    ),
                },
            )()

    rag = FakeRAGPipeline()
    app, _ = await _make_app(sessionmaker_override, rag_pipeline_adapter=rag)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={
                "role": "user",
                "content": (
                    "What is the purpose of Lockout/Tagout (LOTO) procedures according to OSHA? "
                    "Is there any specific OSHA regulation or standard that defines this?"
                ),
                "mode": "normal",
            },
        )

        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        body = created.json()
        assert body["status"] == "COMPLETED"
        assert body["created_by"] == "system"
        assert "29 CFR 1910.147" in body["plan_explanation"]
        assert body["sources"][0]["organization"] == "OSHA"

        steps = await client.get(f"/sessions/{session_id}/steps")
        assert steps.status_code == 200
        assert steps.json() == []

    assert rag.calls
    assert rag.calls[0]["route"] == "RAG_ONLY"


@pytest.mark.asyncio
async def test_legacy_planner_prefers_entity_machine_tool_when_id_present(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        capability_tags='["machine","status"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        capability_tags='["machine","status"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Check machine 5 status"})

        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (
        await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))
    ).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "get__machines_{id}"
    assert step_row.args == {"id": "5"}


@pytest.mark.asyncio
async def test_legacy_planner_returns_clarification_when_required_args_missing(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Plan

    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        capability_tags='["machine","status"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Check machine status"})

        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 400
        assert "Need id" in json.dumps(plan.json())

    rows = (await db_session.execute(select(Plan).where(Plan.session_id == session_id))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_PLAN_STEP_PROJECTION_XFAIL
async def test_legacy_planner_allows_partial_args_for_write_tool_and_waits_approval(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Approval, PlanStep

    await _seed_tool(
        db_session,
        name="post__inventory_update",
        endpoint="/inventory",
        method="POST",
        input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        capability_tags='["inventory", "update"]',
        is_read_only=False,
        requires_approval=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Update inventory"},
        )

        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

        execute = await client.post(f"/sessions/{session_id}/execute")
        assert execute.status_code == 200
        assert execute.json()["status"] == "WAITING_APPROVAL"

        snapshot = await client.get(f"/sessions/{session_id}/snapshot")
        assert snapshot.status_code == 200
        body = snapshot.json()
        missing = [
            event.get("details", {}).get("missing_required")
            for event in body.get("timeline", [])
            if event.get("event_type") == "approval_required"
        ]
        assert any(isinstance(v, list) and "id" in v for v in missing)

    step = (
        await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))
    ).scalars().first()
    assert step is not None
    assert step.args == {}
    assert step.requires_approval is True
    approvals = (await db_session.execute(select(Approval).where(Approval.session_id == session_id))).scalars().all()
    assert len(approvals) == 1


@pytest.mark.asyncio
async def test_legacy_planner_extracts_seed_machine_id(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["machine","status"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        capability_tags='["machine","status"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Check machine M-LTH-02 status"})
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "get__machines_{id}"
    assert step_row.args == {"id": "M-LTH-02"}


@pytest.mark.asyncio
async def test_legacy_planner_extracts_seed_job_id(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__jobs",
        endpoint="/jobs",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["job","status"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__jobs_{id}",
        endpoint="/jobs/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        capability_tags='["job","status"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Check job JOB-SEED-001 status"})
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "get__jobs_{id}"
    assert step_row.args == {"id": "JOB-SEED-001"}


@pytest.mark.asyncio
async def test_legacy_planner_prefers_seed_job_slots_tool_for_slots_intent(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__jobs_{id}",
        endpoint="/jobs/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        capability_tags='["job","status"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__jobs_{id}_slots",
        endpoint="/jobs/{id}/slots",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        capability_tags='["job","schedule","slot"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Show slots for job JOB-SEED-001"})
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "get__jobs_{id}_slots"
    assert step_row.args == {"id": "JOB-SEED-001"}


@pytest.mark.asyncio
async def test_legacy_planner_prefers_resource_create_over_specialized_subresource(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="post__machines",
        endpoint="/machines",
        method="POST",
        input_schema={
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "machine_name": {"type": "string"},
                "machine_type": {"type": "string"},
            },
            "required": ["machine_id", "machine_name", "machine_type"],
        },
        capability_tags='["machine","create"]',
        is_read_only=False,
        requires_approval=True,
    )
    await _seed_tool(
        db_session,
        name="post__machines_downtime",
        endpoint="/machines/downtime",
        method="POST",
        input_schema={
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
            },
            "required": ["machine_id"],
        },
        capability_tags='["machine","create","downtime"]',
        is_read_only=False,
        requires_approval=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "create new machine"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "post__machines"


@pytest.mark.asyncio
async def test_legacy_planner_adds_fields_for_id_only_list_requests(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__products",
        endpoint="/products",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {"fields": {"type": "string"}},
            "x-query-params": ["fields"],
            "x-param-sources": {"fields": "query"},
        },
        capability_tags='["product","list"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "get all product id"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "get__products"
    assert step_row.args == {"fields": "product_id"}


@pytest.mark.asyncio
async def test_legacy_planner_prefers_products_list_over_product_process_lookup_when_id_missing(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__products",
        endpoint="/products",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {"fields": {"type": "string"}},
            "x-query-params": ["fields"],
            "x-param-sources": {"fields": "query"},
        },
        capability_tags='["product","list"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__processes_product_{id}",
        endpoint="/processes/product/{id}",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "x-path-params": ["id"],
            "x-param-sources": {"id": "path"},
        },
        capability_tags='["product","process","lookup"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "give me a product id"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "get__products"
    assert step_row.args == {"fields": "product_id"}


@pytest.mark.asyncio
async def test_llm_structured_tool_selection_contract_is_applied(sessionmaker_override, db_session, monkeypatch):
    from factory_agent.persistence.models import PlanStep

    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        async def ainvoke(self, prompt: str):
            if "Select one best tool for this user clause" in prompt:
                return _FakeResponse(
                    json.dumps(
                        {
                            "tool_name": "get__products",
                            "args": {"fields": "product_id"},
                            "confidence": 0.98,
                            "missing_args": [],
                            "reason": "IDs requested without specific process id.",
                        }
                    )
                )
            if "Generate plan explainability as strict JSON" in prompt:
                return _FakeResponse(
                    json.dumps(
                        {
                            "plan_explanation": "Use products list to return product IDs.",
                            "risk_summary": "Read-only retrieval with no write side effects.",
                        }
                    )
                )
            return _FakeResponse(json.dumps({"message": "ok"}))

    fake_langchain = types.SimpleNamespace(ChatOpenAI=_FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain)

    await _seed_tool(
        db_session,
        name="get__products",
        endpoint="/products",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {"fields": {"type": "string"}},
            "x-query-params": ["fields"],
            "x-param-sources": {"fields": "query"},
        },
        capability_tags='["product","list"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__processes_product_{id}",
        endpoint="/processes/product/{id}",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "x-path-params": ["id"],
            "x-param-sources": {"id": "path"},
        },
        capability_tags='["product","process","lookup"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override, openai_base_url="http://fake-llm")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "give me a product id"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "get__products"
    assert step_row.args == {"fields": "product_id"}


@pytest.mark.asyncio
async def test_plan_creation_survives_summary_model_failure(sessionmaker_override, db_session, monkeypatch):
    from factory_agent.persistence.models import Plan

    class _FailingChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        async def ainvoke(self, prompt: str):
            del prompt
            raise RuntimeError("model 'Qwen3.5-9B' not found")

    fake_langchain = types.SimpleNamespace(ChatOpenAI=_FailingChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain)

    await _seed_tool(
        db_session,
        name="get__products",
        endpoint="/products",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["product","list"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override, openai_base_url="http://fake-llm")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "list products"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    rows = (await db_session.execute(select(Plan).where(Plan.session_id == session_id))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_legacy_planner_splits_compound_intent_into_multiple_steps(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        capability_tags='["machine","status"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__jobs_{id}_slots",
        endpoint="/jobs/{id}/slots",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        capability_tags='["job","schedule","slot"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Check machine M-LTH-02 status and then show slots for JOB-SEED-001"},
        )

        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200
        body = plan.json()
        assert body["created_by"] == "langgraph"
        assert "machine" in body["plan_explanation"].lower()
        assert "slots" in body["plan_explanation"].lower()

    step_rows = (
        await db_session.execute(
            select(PlanStep)
            .where(PlanStep.session_id == session_id)
            .order_by(PlanStep.step_index.asc())
        )
    ).scalars().all()
    assert len(step_rows) == 2
    assert step_rows[0].tool_name == "get__machines_{id}"
    assert step_rows[0].args == {"id": "M-LTH-02"}
    assert step_rows[1].tool_name == "get__jobs_{id}_slots"
    assert step_rows[1].args == {"id": "JOB-SEED-001"}


@pytest.mark.asyncio
async def test_legacy_planner_extracts_seed_material_id(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__inventory_materials",
        endpoint="/inventory/materials",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["inventory","material"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__inventory_materials_{id}",
        endpoint="/inventory/materials/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        capability_tags='["inventory","material"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Check material MAT-010 stock"})
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "get__inventory_materials_{id}"
    assert step_row.args == {"id": "MAT-010"}


@pytest.mark.asyncio
async def test_legacy_planner_extracts_seed_proposal_id(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__ai_scheduling_proposals",
        endpoint="/ai/scheduling/proposals",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["proposal","scheduling"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__ai_scheduling_proposals_{id}",
        endpoint="/ai/scheduling/proposals/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        capability_tags='["proposal","scheduling"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Open proposal AIPROP-SEED-001"})
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.tool_name == "get__ai_scheduling_proposals_{id}"
    assert step_row.args == {"id": "AIPROP-SEED-001"}


@pytest.mark.asyncio
async def test_langchain_planner_invalid_output_rejected(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Plan

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        capability_tags='["machine"]',
        is_read_only=True,
    )

    class FakePlanner:
        async def generate_plan(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            return type(
                "X",
                (),
                {
                    "draft": PlanDraft(
                        plan_explanation="bad schema args",
                        risk_summary="read-only",
                        steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={})],
                    ),
                    "backend_used": "langchain",
                    "llm_calls": 1,
                },
            )()

    app, _ = await _make_app(sessionmaker_override, planner_adapter=FakePlanner())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/sessions", json={"user_id": "u1"})
        session_id = r.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "machine"})
        res = await client.post(f"/sessions/{session_id}/plans", json={})
        assert res.status_code == 400

    plan_rows = (await db_session.execute(select(Plan).where(Plan.session_id == session_id))).scalars().all()
    assert len(plan_rows) == 0


@pytest.mark.asyncio
async def test_delete_session_removes_session_and_related_rows(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Approval
    from factory_agent.persistence.models import DeadLetter
    from factory_agent.persistence.models import ExecutionSnapshot
    from factory_agent.persistence.models import Message
    from factory_agent.persistence.models import Plan
    from factory_agent.persistence.models import PlanStep
    from factory_agent.persistence.models import Session
    from factory_agent.persistence.models import VectorMemory
    from factory_agent.persistence.models import WorkflowCheckpoint
    from factory_agent.persistence.models import generate_uuid

    app, _ = await _make_app(
        sessionmaker_override,
        jwt_required=True,
        jwt_secret="test-secret",
    )
    headers = _auth_headers("test-secret")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"}, headers=headers)
        session_id = created.json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "hello"},
            headers=headers,
        )

        plan_id = generate_uuid()
        step_id = generate_uuid()
        db_session.add_all(
            [
                Plan(
                    plan_id=plan_id,
                    session_id=session_id,
                    version=1,
                    kind="execution",
                    status="DRAFT",
                    plan_hash="hash-1",
                ),
                PlanStep(
                    step_id=step_id,
                    plan_id=plan_id,
                    session_id=session_id,
                    step_index=0,
                    tool_name="get__machines",
                    args={},
                    status="NOT_STARTED",
                    idempotency_key=f"delete-session-{step_id}",
                ),
                Approval(
                    approval_id=generate_uuid(),
                    session_id=session_id,
                    subject_type="graph",
                    tool_name="__langgraph_commit__",
                    args={},
                    risk_summary="test approval",
                    side_effect_level="HIGH",
                    status="PENDING",
                    expires_at=datetime.utcnow() + timedelta(hours=1),
                ),
                DeadLetter(
                    dlq_id=generate_uuid(),
                    session_id=session_id,
                    step_id=step_id,
                    failure_type="test",
                    reason="test failure",
                    payload={},
                    status="PENDING",
                ),
                ExecutionSnapshot(
                    snapshot_id=generate_uuid(),
                    step_id=step_id,
                    session_id=session_id,
                    tool_name="get__machines",
                    tool_version=1,
                    schema_version=1,
                    input_args={},
                    plan_hash="hash-1",
                    plan_version=1,
                    idempotency_key=f"snapshot-{step_id}",
                ),
                WorkflowCheckpoint(
                    checkpoint_id=generate_uuid(),
                    thread_id=session_id,
                    session_id=session_id,
                    user_id="u1",
                    state={"kind": "test"},
                ),
                VectorMemory(
                    memory_id=generate_uuid(),
                    session_id=session_id,
                    user_id="u1",
                    memory_type="message",
                    content="hello",
                    source_message_id=generate_uuid(),
                    reusable_scope="session",
                ),
            ]
        )
        await db_session.commit()

        deleted = await client.delete(f"/sessions/{session_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True

        missing = await client.get(f"/sessions/{session_id}", headers=headers)
        assert missing.status_code == 404

    session_row = await db_session.get(Session, session_id)
    assert session_row is None
    for model in (Message, Plan, PlanStep, Approval, DeadLetter, ExecutionSnapshot, WorkflowCheckpoint, VectorMemory):
        rows = (await db_session.execute(select(model).where(model.session_id == session_id))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_normal_mode_create_machine_prefers_post_tool(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["machine","list"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="post__machines",
        endpoint="/machines",
        method="POST",
        input_schema={"type": "object", "properties": {"machine_name": {"type": "string"}}, "required": ["machine_name"]},
        capability_tags='["machine","create"]',
        is_read_only=False,
        requires_approval=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "create new machine", "mode": "normal"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

    step = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step is not None
    assert step.tool_name == "post__machines"


@pytest.mark.asyncio
async def test_conversation_message_returns_completed_empty_plan(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["machine","list"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "hi", "mode": "normal"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200
        assert plan.json()["status"] == "COMPLETED"

        snapshot = await client.get(f"/sessions/{session_id}/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.json()["plan"] is None
        assert all(event["event_type"] != "plan_created" for event in snapshot.json()["timeline"])
        assert any(
            event["event_type"] == "session_completed" and "factory operations" in event["content"]
            for event in snapshot.json()["timeline"]
        )

        executed = await client.post(f"/sessions/{session_id}/execute", json={})
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

    steps = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().all()
    assert steps == []


@pytest.mark.asyncio
async def test_planner_clarification_returns_message_not_error(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Message, Session
    from factory_agent.planner import PlannerClarificationError

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
            },
        },
        capability_tags='["machine","list"]',
        is_read_only=True,
    )

    class FakePlanner:
        async def generate_plan(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            raise PlannerClarificationError(
                'I found machines, but I could not safely map "broke" to a valid status. '
                "Allowed status values are: idle, running, maintenance, offline.",
                negative_bindings=[
                    {
                        "term": "broke",
                        "normalized_term": "broke",
                        "entity": "machine",
                        "field": "status",
                        "reason": "semantic enum mapping was not an allowed value",
                    }
                ],
            )

    app, _ = await _make_app(sessionmaker_override, planner_adapter=FakePlanner())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "find all broke machine", "mode": "normal"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200
        assert plan.json()["status"] == "COMPLETED"

        snapshot = await client.get(f"/sessions/{session_id}/snapshot")
        assert snapshot.status_code == 200
        assert any(
            event["event_type"] == "session_completed" and "could not safely map" in event["content"]
            for event in snapshot.json()["timeline"]
        )

    messages = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "assistant")
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    session = (
        await db_session.execute(select(Session).where(Session.session_id == session_id))
    ).scalars().one()
    memory = (session.replan_context or {}).get("intent_memory", {})
    assert memory["negative_bindings"][0]["field"] == "status"
    assert any("Allowed status values are: idle, running, maintenance, offline." in msg.content for msg in messages)


@pytest.mark.asyncio
async def test_langgraph_read_only_not_found_plan_returns_200_not_400(
    sessionmaker_override,
    db_session,
):
    from factory_agent.planner import PlannerClarificationError

    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        capability_tags='["machine","status"]',
        is_read_only=True,
    )

    class FakePlanner:
        async def generate_plan(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            raise PlannerClarificationError("Is there any specific information you need about machine 5, given that it does not exist?")

    app, _ = await _make_app(sessionmaker_override, planner_adapter=FakePlanner())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Check machine 5 status", "mode": "normal"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})

    assert plan.status_code == 200
    assert plan.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_planner_unknown_term_clarification_returns_message_not_error(sessionmaker_override, db_session, monkeypatch):
    from factory_agent.persistence.models import Message
    from factory_agent.planning.reasoning_pipeline import ReasoningPipeline

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
            },
        },
        capability_tags='["machine","list"]',
        is_read_only=True,
    )

    async def _fake_classify_unknown_term(self, *, clause, term, entity, tool):
        del self, clause, entity, tool
        assert term == "bsn"
        return {"field_name": None, "confidence": 0.0, "reason": "no matching schema field"}

    monkeypatch.setattr(ReasoningPipeline, "classify_unknown_term", _fake_classify_unknown_term)

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "find all bsn machine", "mode": "normal"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200
        assert plan.json()["status"] == "COMPLETED"

    messages = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "assistant")
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    assert any('couldn\'t match "bsn" to any supported machine field or filter' in msg.content.lower() for msg in messages)


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_PLAN_STEP_PROJECTION_XFAIL
async def test_predicate_confirmation_round_trip_resumes_with_selected_filter(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep, Session

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "machine_type": {"type": "string"},
                "location": {"type": "string"},
            },
        },
        capability_tags='["machine","list"]',
        is_read_only=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "find all CNC machine", "mode": "normal"},
        )
        plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan.status_code == 200

        snapshot = await client.get(f"/sessions/{session_id}/snapshot")
        assert snapshot.status_code == 200
        body = snapshot.json()
        assert body["session"]["status"] == "WAITING_CONFIRMATION"
        confirmation_event = next(event for event in body["timeline"] if event["event_type"] == "confirmation_required")
        assert {opt["field"] for opt in confirmation_event["details"]["confirmation"]["options"]} >= {"machine_type", "location"}

        confirmed = await client.post(f"/sessions/{session_id}/confirm", json={"field": "machine_type", "value": "CNC"})
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "IDLE"

        plan2 = await client.post(f"/sessions/{session_id}/plans", json={})
        assert plan2.status_code == 200

    sess = await db_session.get(Session, session_id)
    step = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert sess.status == "PLANNING"
    assert step.args == {"machine_type": "CNC"}


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_PLAN_STEP_PROJECTION_XFAIL
async def test_plan_mode_creates_plan_level_approval_after_discovery(sessionmaker_override, db_session, respx_mock):
    from factory_agent.persistence.models import Approval, Plan

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["machine","list"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="post__machines",
        endpoint="/machines",
        method="POST",
        input_schema={"type": "object", "properties": {"machine_name": {"type": "string"}}, "required": ["machine_name"]},
        capability_tags='["machine","create"]',
        is_read_only=False,
        requires_approval=True,
    )
    respx_mock.get("http://testserver/machines").respond(200, json={"items": []})

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "create new machine", "mode": "plan"},
        )
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        assert created.json()["kind"] == "discovery"

        executed = await client.post(f"/sessions/{session_id}/execute", json={})
        assert executed.status_code == 200
        assert executed.json()["status"] == "WAITING_APPROVAL"

        snapshot = await client.get(f"/sessions/{session_id}/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.json()["pending_approval"]["subject_type"] == "plan"
        assert snapshot.json()["plan"]["kind"] == "execution"
        assert snapshot.json()["plan"]["status"] == "PENDING_APPROVAL"

    approvals = (await db_session.execute(select(Approval).where(Approval.session_id == session_id))).scalars().all()
    assert any(a.subject_type == "plan" for a in approvals)
    plans = (await db_session.execute(select(Plan).where(Plan.session_id == session_id).order_by(Plan.created_at.asc()))).scalars().all()
    assert len(plans) == 2


@pytest.mark.asyncio
async def test_tool_registry_load_normalizes_legacy_string_tags(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Tool, generate_uuid

    db_session.add(
        Tool(
            tool_id=generate_uuid(),
            name="get__machines",
            description="List machines",
            endpoint="/machines",
            method="GET",
            version=1,
            schema_version=1,
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object"},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags="machine",
        )
    )
    await db_session.commit()

    registry = ToolRegistry()
    tools = await registry.get_tools_by_name(db_session)
    assert tools["get__machines"].capability_tags == ["machine"]
    row = (await db_session.execute(select(Tool).where(Tool.name == "get__machines"))).scalars().first()
    assert row is not None
    assert row.capability_tags == '["machine"]'


@pytest.mark.asyncio
async def test_create_plan_auto_repairs_incomplete_registry(sessionmaker_override, db_session, monkeypatch):
    from factory_agent.registry.tool_registry import ToolRegistry
    from factory_agent.persistence.models import Tool
    from factory_agent.persistence.models import PlanStep

    for idx in range(5):
        await _seed_tool(
            db_session,
            name=f"legacy_tool_{idx}",
            endpoint=f"/legacy/{idx}",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            capability_tags='["machine"]' if idx == 0 else '["legacy"]',
            is_read_only=True,
        )

    async def fake_regenerate(self, db, *, openapi_url, local_swagger_json_path, force_local=False, replace_db=True):
        del openapi_url, local_swagger_json_path, force_local, replace_db
        await _seed_tool(
            db,
            name="get__machines_{id}",
            endpoint="/machines/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            capability_tags='["machine","status"]',
            is_read_only=True,
        )
        await _seed_tool(
            db,
            name="post__machines",
            endpoint="/machines",
            method="POST",
            input_schema={"type": "object", "properties": {"machine_name": {"type": "string"}}, "required": ["machine_name"]},
            capability_tags='["machine","create"]',
            is_read_only=False,
            requires_approval=True,
        )
        await _seed_tool(
            db,
            name="get__chatbot_approval_pending",
            endpoint="/chatbot/approval/pending",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            capability_tags='["approval","pending","list"]',
            is_read_only=True,
        )
        rows = (await db.execute(select(Tool))).scalars().all()
        for idx in range(20 - len(rows)):
            await _seed_tool(
                db,
                name=f"extra_tool_{idx}",
                endpoint=f"/extra/{idx}",
                method="GET",
                input_schema={"type": "object", "properties": {}},
                capability_tags='["extra"]',
                is_read_only=True,
            )

        class Result:
            tool_count = 20
            tools_md_hash = "test-hash"

        await self.refresh(db)
        return Result()

    monkeypatch.setattr(ToolRegistry, "regenerate_from_openapi", fake_regenerate)

    app, _ = await _make_app(
        sessionmaker_override,
        database_url="mysql+aiomysql://test",
        enforce_tool_registry_health=True,
        auto_repair_tool_registry=True,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "check machine 5 status", "mode": "normal"},
        )
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200

    step = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step is not None
    assert step.tool_name == "get__machines_{id}"
    assert step.args == {"id": "5"}


@pytest.mark.asyncio
async def test_create_plan_uses_tool_selector_reranker_when_enabled(sessionmaker_override, db_session, monkeypatch):
    from factory_agent.planning.tool_selector import ToolSelector
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["machine","list"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="post__machines",
        endpoint="/machines",
        method="POST",
        input_schema={"type": "object", "properties": {"machine_name": {"type": "string"}}, "required": ["machine_name"]},
        capability_tags='["machine","create"]',
        is_read_only=False,
        requires_approval=True,
    )

    async def fake_invoke(self, *, prompt):
        del self, prompt
        return {
            "primary_tool": "post__machines",
            "additional_tools": ["get__machines"],
            "confidence": 0.91,
            "missing_fields": ["machine_name"],
            "reason": "Create action aligns with POST /machines.",
        }

    monkeypatch.setattr(ToolSelector, "_should_rerank", lambda self, intent, candidates, tools_by_name: True)
    monkeypatch.setattr(ToolSelector, "_invoke_reranker", fake_invoke)

    app, _ = await _make_app(
        sessionmaker_override,
        tool_selector_backend="langchain",
        openai_base_url="http://fake-llm",
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "create new machine", "mode": "normal"},
        )
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200

    step = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step is not None
    assert step.tool_name == "post__machines"


@pytest.mark.asyncio
async def test_create_plan_falls_back_when_tool_selector_reranker_errors(sessionmaker_override, db_session, monkeypatch):
    from factory_agent.planning.tool_selector import ToolSelector
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        capability_tags='["machine","lookup"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__ai_scheduling_job-steps_{id}_machine-ranking",
        endpoint="/ai/scheduling/job-steps/{id}/machine-ranking",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        capability_tags='["machine","job","lookup"]',
        is_read_only=True,
    )

    monkeypatch.setattr(ToolSelector, "_should_rerank", lambda self, intent, candidates, tools_by_name: True)

    async def fake_invoke(self, *, prompt):
        del self, prompt
        raise RuntimeError("LLM backend unavailable")

    monkeypatch.setattr(ToolSelector, "_invoke_reranker", fake_invoke)

    app, _ = await _make_app(
        sessionmaker_override,
        tool_selector_backend="langchain",
        openai_base_url="http://fake-llm",
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Check machine 5 status", "mode": "normal"},
        )
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200

    step = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step is not None
    assert step.tool_name == "get__machines_{id}"
    assert step.args == {"id": "5"}


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_generated_write_plan_sets_requires_approval_and_waits_approval(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Approval, PlanStep

    await _seed_tool(
        db_session,
        name="post__inventory_update",
        endpoint="/inventory",
        method="POST",
        input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        capability_tags='["inventory", "update"]',
        is_read_only=False,
        requires_approval=True,
    )

    class FakePlanner:
        async def generate_plan(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            return type(
                "X",
                (),
                {
                    "draft": PlanDraft(
                        plan_explanation="write inventory",
                        risk_summary="write op",
                        steps=[PlanStepDraft(step_index=0, tool_name="post__inventory_update", args={"id": 9})],
                    ),
                    "backend_used": "langchain",
                    "llm_calls": 1,
                },
            )()

    app, _ = await _make_app(sessionmaker_override, planner_adapter=FakePlanner())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "update inventory"})
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200

        execute = await client.post(f"/sessions/{session_id}/execute")
        assert execute.status_code == 200
        assert execute.json()["status"] == "WAITING_APPROVAL"

    step = (
        await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))
    ).scalars().first()
    assert step is not None
    assert step.requires_approval is True
    approvals = (await db_session.execute(select(Approval).where(Approval.session_id == session_id))).scalars().all()
    assert len(approvals) == 1


@pytest.mark.asyncio
async def test_langchain_invalid_output_fallback_disabled_rejected_and_not_executable(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Plan

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        capability_tags='["machine"]',
        is_read_only=True,
    )

    class FakePlanner:
        async def generate_plan(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            return type(
                "X",
                (),
                {
                    "draft": PlanDraft(
                        plan_explanation="invalid langchain",
                        risk_summary="bad",
                        steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={})],
                    ),
                    "backend_used": "langchain",
                    "llm_calls": 1,
                },
            )()

    app, _ = await _make_app(
        sessionmaker_override,
        planner_adapter=FakePlanner(),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "machine"})
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 400

        execute = await client.post(f"/sessions/{session_id}/execute")
        assert execute.status_code == 400

    plan_rows = (await db_session.execute(select(Plan).where(Plan.session_id == session_id))).scalars().all()
    assert len(plan_rows) == 0


@pytest.mark.asyncio
async def test_get_tools_lists_and_scopes(sessionmaker_override, db_session):
    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["machine"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="post__inventory_update",
        endpoint="/inventory",
        method="POST",
        input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        capability_tags='["inventory"]',
        is_read_only=False,
        requires_approval=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r_all = await client.get("/tools")
        assert r_all.status_code == 200
        assert len(r_all.json()) == 2

        r_scoped = await client.get("/tools", params={"intent": "machine health", "max_tools": 1})
        assert r_scoped.status_code == 200
        body = r_scoped.json()
        assert len(body) == 1
        assert body[0]["name"] == "get__machines"


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_reject_approval_sets_session_idle_and_step_skipped(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Approval, PlanStep, Session, generate_uuid

    step_id = generate_uuid()
    approval_id = generate_uuid()
    await _seed_session_plan_with_steps(
        db_session,
        session_id="sess-reject",
        plan_id="plan-reject",
        plan_hash="hash-reject",
        plan_version=1,
        steps=[
            {
                "step_id": step_id,
                "step_index": 0,
                "tool_name": "post__inventory_update",
                "args": {"id": 1},
                "status": "NOT_STARTED",
                "requires_approval": True,
                "approval_id": approval_id,
            }
        ],
    )
    db_session.add(
        Approval(
            approval_id=approval_id,
            session_id="sess-reject",
            step_id=step_id,
            tool_name="post__inventory_update",
            args={"id": 1},
            risk_summary="write op",
            side_effect_level="HIGH",
            status="PENDING",
            expires_at=datetime.utcnow(),
        )
    )
    await db_session.commit()

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            f"/approvals/{approval_id}/reject",
            json={"decided_by": "u1", "rejection_reason": "Not safe"},
        )
        assert res.status_code == 200

        snapshot = await client.get("/sessions/sess-reject/snapshot")
        assert snapshot.status_code == 200
        approval_events = [event for event in snapshot.json()["timeline"] if event["event_type"].startswith("approval_")]
        assert len([event for event in approval_events if event["event_type"] == "approval_required"]) == 0
        assert any(
            event["event_type"] == "approval_decided" and event["status"] == "REJECTED"
            for event in approval_events
        )
        decided = next(event for event in approval_events if event["event_type"] == "approval_decided")
        assert decided["content"] == "Rejected request to change inventory item 1: Not safe"
        assert "post__inventory_update" not in decided["content"]

    sess = await db_session.get(Session, "sess-reject")
    step = (await db_session.execute(select(PlanStep).where(PlanStep.step_id == step_id))).scalars().first()
    assert sess.status == "IDLE"
    assert step.status == "SKIPPED"


@pytest.mark.asyncio
async def test_cancel_marks_remaining_steps_skipped(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep, Session

    await _seed_session_plan_with_steps(
        db_session,
        session_id="sess-cancel",
        plan_id="plan-cancel",
        plan_hash="hash-cancel",
        plan_version=1,
        steps=[
            {"step_index": 0, "tool_name": "get__machines", "args": {}, "status": "DONE"},
            {"step_index": 1, "tool_name": "post__inventory_update", "args": {"id": 1}, "status": "NOT_STARTED"},
            {"step_index": 2, "tool_name": "post__inventory_update", "args": {"id": 2}, "status": "IN_PROGRESS"},
        ],
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/sessions/sess-cancel/cancel")
        assert res.status_code == 200
        assert res.json()["status"] == "IDLE"

    sess = await db_session.get(Session, "sess-cancel")
    steps = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == "sess-cancel"))).scalars().all()
    status_by_index = {s.step_index: s.status for s in steps}
    assert sess.status == "IDLE"
    assert status_by_index[0] == "DONE"
    assert status_by_index[1] == "SKIPPED"
    assert status_by_index[2] == "SKIPPED"


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_end_to_end_state_progression_with_approval_resume(sessionmaker_override, db_session, respx_mock):
    from factory_agent.persistence.models import PlanStep

    await _seed_tool(
        db_session,
        name="get__machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["machine"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="post__inventory_update",
        endpoint="/inventory",
        method="POST",
        input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        capability_tags='["inventory"]',
        is_read_only=False,
        requires_approval=True,
    )

    respx_mock.get("http://testserver/machines").respond(200, json={"items": []})
    respx_mock.post("http://testserver/inventory").respond(200, json={"ok": True})

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "check machine then write inventory"})
        draft = PlanDraft(
            plan_explanation="Read machines then update inventory",
            risk_summary="Second step writes inventory",
            steps=[
                PlanStepDraft(step_index=0, tool_name="get__machines", args={}),
                PlanStepDraft(step_index=1, tool_name="post__inventory_update", args={"id": 1}),
            ],
        )
        created = await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        assert created.status_code == 200

        execute1 = await client.post(f"/sessions/{session_id}/execute")
        assert execute1.status_code == 200
        assert execute1.json()["status"] == "WAITING_APPROVAL"

        pending = await client.get("/approvals/pending")
        assert pending.status_code == 200
        approval_id = pending.json()[0]["approval_id"]
        rejected = await client.post(f"/approvals/{approval_id}/approve", json={"decided_by": "u1"})
        assert rejected.status_code == 200

        execute2 = await client.post(f"/sessions/{session_id}/execute")
        assert execute2.status_code == 200
        assert execute2.json()["status"] == "COMPLETED"

    steps = (
        await db_session.execute(
            select(PlanStep)
            .where(PlanStep.session_id == session_id)
            .order_by(PlanStep.step_index.asc())
        )
    ).scalars().all()
    assert [s.status for s in steps] == ["DONE", "DONE"]


@pytest.mark.asyncio
async def test_session_snapshot_returns_plan_steps_pending_approval_and_timeline(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Approval, Message, Plan, PlanStep, Session, generate_uuid
    from factory_agent.tools.arguments import compute_idempotency_key

    session_id = "sess-snapshot"
    plan_id = "plan-snapshot"
    step_id = generate_uuid()
    approval_id = generate_uuid()
    created_at = datetime.utcnow()

    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            name="Snapshot chat",
            status="WAITING_APPROVAL",
            current_intent="Update machine 5 to maintenance",
            plan_id=plan_id,
            plan_version=1,
            plan_hash="hash-snapshot",
            current_step_index=0,
            session_started_at=created_at,
        )
    )
    db_session.add(
        Plan(
            plan_id=plan_id,
            session_id=session_id,
            version=1,
            dependency_graph={},
            parallel_groups=[],
            plan_hash="hash-snapshot",
            plan_explanation="Update machine 5 to maintenance after confirmation.",
            risk_summary="This changes machine state.",
            created_by="langgraph",
            created_at=created_at,
        )
    )
    db_session.add(
        PlanStep(
            step_id=step_id,
            plan_id=plan_id,
            session_id=session_id,
            step_index=0,
            tool_name="put__machines_{id}",
            args={"id": "5", "status": "maintenance"},
            status="NOT_STARTED",
            idempotency_key=compute_idempotency_key(
                session_id=session_id,
                step_index=0,
                plan_version=1,
                args={"id": "5", "status": "maintenance"},
            ),
            requires_approval=True,
            approval_id=approval_id,
        )
    )
    db_session.add(
        Approval(
            approval_id=approval_id,
            session_id=session_id,
            step_id=step_id,
            tool_name="put__machines_{id}",
            args={"id": "5", "status": "maintenance"},
            risk_summary="This will change machine state for id=5.",
            side_effect_level="HIGH",
            status="PENDING",
            expires_at=created_at,
            created_at=created_at,
        )
    )
    db_session.add(
        Message(
            message_id=generate_uuid(),
            session_id=session_id,
            role="user",
            content="Update machine 5 to maintenance",
            created_at=created_at,
        )
    )
    db_session.add(
        Message(
            message_id=generate_uuid(),
            session_id=session_id,
            role="assistant",
            content="Intent: Update machine 5 to maintenance. Plan has 1 step(s). Risk summary: This changes machine state.",
            tool_name="__plan__",
            created_at=created_at,
        )
    )
    await db_session.commit()

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        snapshot = await client.get(f"/sessions/{session_id}/snapshot")
        assert snapshot.status_code == 200
        body = snapshot.json()
        assert body["session"]["name"] == "Snapshot chat"
        assert body["plan"]["plan_hash"] == "hash-snapshot"
        assert len(body["steps"]) == 1
        assert body["pending_approval"]["approval_id"] == approval_id
        event_types = [event["event_type"] for event in body["timeline"]]
        assert event_types[:3] == ["user_message", "plan_created", "approval_required"]
        assert "user_message" in event_types
        assert "plan_created" in event_types
        assert "approval_required" in event_types


@pytest.mark.asyncio
async def test_graph_approval_returns_before_resume_and_keeps_one_activity_operation(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Approval, Message, Plan, Session
    from factory_agent.services.planner_service import PlannerResult

    class BlockingResumePlanner:
        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def resume_after_approval(self, *, session_id: str, approved: bool):
            self.calls += 1
            assert approved is True
            self.started.set()
            await self.release.wait()
            return PlannerResult(
                draft=PlanDraft(
                    plan_explanation="Updated job priority after approval.",
                    risk_summary="Approved write completed.",
                    steps=[
                        PlanStepDraft(
                            step_index=0,
                            tool_name="put__jobs_{id}",
                            args={"id": "JOB-SEED-002", "priority": "high"},
                        )
                    ],
                ),
                backend_used="langgraph",
                intent_contract={"backend": "langgraph", "steps": []},
                tool_outputs=[
                    {
                        "tool_name": "put__jobs_{id}",
                        "status": "DONE",
                        "summary": "Updated job JOB-SEED-002 to high priority.",
                        "result": {"job_id": "JOB-SEED-002", "priority": "high"},
                    }
                ],
            )

    created_at = datetime.utcnow() - timedelta(minutes=5)
    session_id = "graph-approval-nonblocking"
    initial_plan_id = "graph-approval-nonblocking-plan-initial"
    approval_id = "graph-approval-nonblocking-apr"
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="WAITING_APPROVAL",
            current_intent="Set JOB-SEED-002 priority to high",
            plan_id=initial_plan_id,
            plan_version=1,
            session_started_at=created_at,
            created_at=created_at,
            updated_at=created_at,
            replan_context={
                "langgraph_pending_approval": {
                    "approval_id": approval_id,
                    "thread_id": session_id,
                }
            },
        )
    )
    db_session.add(
        Plan(
            plan_id=initial_plan_id,
            session_id=session_id,
            version=1,
            kind="execution",
            status="PENDING_APPROVAL",
            dependency_graph={},
            parallel_groups=[],
            plan_hash="hash-initial-approval-plan",
            plan_explanation="1 job will be updated.",
            risk_summary="1 job will be updated.",
            created_by="langgraph",
            created_at=created_at + timedelta(milliseconds=500),
        )
    )
    db_session.add(
        Message(
            message_id="graph-approval-user-message",
            session_id=session_id,
            role="user",
            content="Set JOB-SEED-002 priority to high",
            mode="normal",
            created_at=created_at,
        )
    )
    db_session.add(
        Approval(
            approval_id=approval_id,
            session_id=session_id,
            subject_type="graph",
            tool_name="__langgraph_commit__",
            args={"bundle_ui": {"headline": "1 job will be updated."}},
            risk_summary="1 job will be updated.",
            side_effect_level="HIGH",
            status="PENDING",
            expires_at=created_at + timedelta(hours=1),
            created_at=created_at + timedelta(seconds=1),
        )
    )
    await db_session.commit()
    await _seed_tool(
        db_session,
        name="put__jobs_{id}",
        endpoint="/jobs/{id}",
        method="PUT",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}, "priority": {"type": "string"}},
            "required": ["id", "priority"],
        },
        capability_tags='["job"]',
        is_read_only=False,
        requires_approval=True,
    )

    planner = BlockingResumePlanner()
    app, event_bus = await _make_app(
        sessionmaker_override,
        planner_adapter=planner,
        enforce_tool_registry_health=False,
        min_healthy_tool_count=0,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        approved = await client.post(f"/approvals/{approval_id}/approve", json={"decided_by": "u1"})
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED"

        await asyncio.wait_for(planner.started.wait(), timeout=1)
        during = (await client.get(f"/sessions/{session_id}/snapshot")).json()
        assert during["session"]["status"] == "EXECUTING"
        assert during["pending_approval"] is None
        during_events = [event["event_type"] for event in during["timeline"]]
        assert "approval_required" in during_events
        assert "approval_decided" in during_events
        assert any(event.event_type == "approval_decided" for event in event_bus.published)

        planner.release.set()
        final_body = None
        for _ in range(40):
            await asyncio.sleep(0.025)
            final_body = (await client.get(f"/sessions/{session_id}/snapshot")).json()
            if final_body["session"]["status"] == "COMPLETED":
                break

    assert final_body is not None
    assert final_body["session"]["status"] == "COMPLETED"
    event_types = [event["event_type"] for event in final_body["timeline"]]
    assert event_types.index("plan_created") < event_types.index("approval_required")
    assert event_types.index("approval_required") < event_types.index("approval_decided")
    assert event_types.index("approval_decided") < event_types.index("tool_result")
    assert event_types.index("tool_result") < event_types.index("session_completed")
    plan_events = [event for event in final_body["timeline"] if event["event_type"] == "plan_created"]
    assert len(plan_events) >= 2
    assert plan_events[-1]["details"]["status"] == "COMPLETED"
    assert "JOB-SEED-002" in plan_events[-1]["content"]
    assert "high" in plan_events[-1]["content"].lower()
    assert plan_events[-1]["content"] != "1 job will be updated."
    operation_events = [
        event
        for event in final_body["timeline"]
        if event["event_type"] in {"plan_created", "approval_required", "approval_decided", "tool_result", "session_completed"}
    ]
    operation_ids = {event.get("operation_id") for event in operation_events}
    assert operation_ids == {final_body["session"]["operation_id"]}


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_approve_endpoint_allows_overriding_args_before_execution(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Approval as ApprovalRow, PlanStep as PlanStep

    schema = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    await _seed_tool(
        db_session,
        name="post__inventory_update",
        endpoint="/inventory",
        method="POST",
        input_schema=schema,
        capability_tags='["inventory"]',
        is_read_only=False,
        requires_approval=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    draft = PlanDraft(
        plan_explanation="update inventory",
        risk_summary="write op",
        steps=[PlanStepDraft(step_index=0, tool_name="post__inventory_update", args={"id": 1})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "update inventory"})
        plan_created = await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        assert plan_created.status_code == 200

        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "WAITING_APPROVAL"

        pending = await client.get("/approvals/pending", params={"session_id": session_id})
        assert pending.status_code == 200
        approval_id = pending.json()[0]["approval_id"]

        approved = await client.post(
            f"/approvals/{approval_id}/approve",
            json={"decided_by": "u1", "args": {"id": 2}},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED"
        assert approved.json()["args"] == {"id": 2}

    approval_row = await db_session.get(ApprovalRow, approval_id)
    assert approval_row is not None
    assert approval_row.args == {"id": 2}

    step_row = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().first()
    assert step_row is not None
    assert step_row.args == {"id": 2}


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_dlq_dismiss_and_replay_endpoints(sessionmaker_override, db_session):
    from factory_agent.persistence.models import DeadLetter, generate_uuid

    dlq_id = generate_uuid()
    db_session.add(
        DeadLetter(
            dlq_id=dlq_id,
            session_id="sess-dlq",
            step_id=None,
            failure_type="unrecoverable_error",
            reason="boom",
            payload={},
            status="PENDING",
        )
    )
    await db_session.commit()

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        dismissed = await client.post(f"/dlq/{dlq_id}/dismiss", json={"dismissed_reason": "handled", "dismissed_by": "ops"})
        assert dismissed.status_code == 200
        replayed = await client.post(f"/dlq/{dlq_id}/replay", json={"replayed_by": "ops"})
        assert replayed.status_code == 200
        listed = await client.get("/dlq", params={"status": "REPLAYED"})
        assert listed.status_code == 200
        assert any(row["dlq_id"] == dlq_id for row in listed.json())


@pytest.mark.asyncio
async def test_execute_expected_version_conflict_returns_409(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Session, generate_uuid

    session_id = generate_uuid()
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="IDLE",
            version=2,
            session_started_at=datetime.utcnow(),
        )
    )
    await db_session.commit()

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(f"/sessions/{session_id}/execute", params={"expected_version": 1})
        assert res.status_code == 409


@pytest.mark.asyncio
async def test_waiting_approval_user_message_triggers_replan_context(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Session

    await _seed_session_plan_with_steps(
        db_session,
        session_id="sess-replan-msg",
        plan_id="plan-replan-msg",
        plan_hash="hash-replan-msg",
        plan_version=1,
        steps=[{"step_index": 0, "tool_name": "post__inventory_update", "args": {"id": 1}, "status": "NOT_STARTED"}],
    )
    sess = await db_session.get(Session, "sess-replan-msg")
    sess.status = "WAITING_APPROVAL"
    await db_session.commit()

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/sessions/sess-replan-msg/messages",
            json={"role": "user", "content": "also include maintenance schedule"},
        )
        assert res.status_code == 200
        session = await client.get("/sessions/sess-replan-msg")
        assert session.status_code == 200
        body = session.json()
        assert body["status"] == "PLANNING"
        assert body["replan_context"] is not None


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_dlq_replay_resets_step_and_marks_session_executing(sessionmaker_override, db_session):
    from factory_agent.persistence.models import DeadLetter, PlanStep, Session, generate_uuid

    session_id = "sess-replay-reset"
    plan_id = "plan-replay-reset"
    step_id = generate_uuid()
    await _seed_session_plan_with_steps(
        db_session,
        session_id=session_id,
        plan_id=plan_id,
        plan_hash="hash-replay-reset",
        plan_version=1,
        steps=[
            {
                "step_id": step_id,
                "step_index": 0,
                "tool_name": "post__inventory_update",
                "args": {"id": 1},
                "status": "AMBIGUOUS",
            }
        ],
    )
    sess = await db_session.get(Session, session_id)
    sess.status = "BLOCKED"
    dlq_id = generate_uuid()
    db_session.add(
        DeadLetter(
            dlq_id=dlq_id,
            session_id=session_id,
            step_id=step_id,
            failure_type="ambiguous_execution",
            reason="timeout",
            payload={},
            status="PENDING",
        )
    )
    await db_session.commit()

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        replayed = await client.post(f"/dlq/{dlq_id}/replay", json={"replayed_by": "ops"})
        assert replayed.status_code == 200

    db_session.expire_all()
    sess2 = await db_session.get(Session, session_id)
    step = (await db_session.execute(select(PlanStep).where(PlanStep.step_id == step_id))).scalars().first()
    assert sess2.status == "EXECUTING"
    assert step.status == "NOT_STARTED"


@pytest.mark.asyncio
async def test_replan_validation_failure_three_times_blocks_and_pushes_dlq(sessionmaker_override, db_session):
    from factory_agent.persistence.models import DeadLetter, Session, Tool, generate_uuid

    session_id = "sess-validate-fail"
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="PLANNING",
            current_intent="machine work",
            replan_context={"original_intent": "machine work"},
            session_started_at=datetime.utcnow(),
        )
    )
    # Seed one scoped tool so failure is from schema validation, not scope denial.
    db_session.add(
        Tool(
            tool_id=generate_uuid(),
            name="get__machines",
            description="get machines",
            endpoint="/machines",
            method="GET",
            version=1,
            schema_version=1,
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
            output_schema={"type": "object"},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags='["machine"]',
        )
    )
    await db_session.commit()

    app, _ = await _make_app(sessionmaker_override)
    bad_draft = {
        "plan_explanation": "bad",
        "risk_summary": "bad",
        "steps": [{"step_index": 0, "tool_name": "get__machines", "args": {}}],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(3):
            res = await client.post(f"/sessions/{session_id}/plans", json={"draft": bad_draft})
            assert res.status_code == 400

        session = await client.get(f"/sessions/{session_id}")
        assert session.status_code == 200
        assert session.json()["status"] == "BLOCKED"

    dlq = (await db_session.execute(select(DeadLetter).where(DeadLetter.session_id == session_id))).scalars().first()
    assert dlq is not None
    assert dlq.failure_type == "replan_limit_reached"


@pytest.mark.asyncio
async def test_admin_dashboard_requires_x_admin_key(sessionmaker_override):
    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/admin/sessions")
        assert missing.status_code == 403
        forbidden = await client.get("/admin/sessions", headers={"X-Admin-Key": "wrong-key"})
        assert forbidden.status_code == 403
        allowed = await client.get("/admin/sessions", headers={"X-Admin-Key": "test-admin-key"})
        assert allowed.status_code == 200
        assert isinstance(allowed.json(), list)


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_format(sessionmaker_override):
    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/metrics")
        assert missing.status_code == 403

        res = await client.get("/metrics", headers={"X-Admin-Key": "test-admin-key"})
        assert res.status_code == 200
        assert "text/plain" in res.headers.get("content-type", "")
        assert "# HELP" in res.text
        assert "plan_validation_failure_rate" in res.text
        assert "db_connection_pool_usage" in res.text


@pytest.mark.asyncio
async def test_stream_dlq_and_metrics_reads_require_auth(sessionmaker_override):
    secret = "phase2-secret"
    app, _ = await _make_app(sessionmaker_override, jwt_required=True, jwt_secret=secret)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in (
            "/sessions/missing/events/semantic",
            "/sessions/missing/events/activity",
            "/sessions/missing/events",
            "/dlq",
        ):
            unauthorized = await client.get(path)
            assert unauthorized.status_code == 401

        for path in (
            "/sessions/missing/events/semantic",
            "/sessions/missing/events/activity",
            "/sessions/missing/events",
        ):
            async with client.stream("GET", path, headers=_auth_headers(secret)) as authorized:
                assert authorized.status_code == 200

        dlq = await client.get("/dlq", headers=_auth_headers(secret))
        assert dlq.status_code == 200
        assert dlq.json() == []

        metrics_missing = await client.get("/metrics")
        assert metrics_missing.status_code == 403
        metrics_ok = await client.get("/metrics", headers={"X-Admin-Key": "test-admin-key"})
        assert metrics_ok.status_code == 200


@pytest.mark.asyncio
async def test_admin_dashboard_html_renders(sessionmaker_override):
    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/admin/dashboard", headers={"X-Admin-Key": "test-admin-key"})
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "Factory Agent Dashboard" in res.text


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_background_execute_returns_429_when_enqueue_fails(sessionmaker_override):
    async def fail_enqueue(_session_id: str) -> None:
        raise RuntimeError("session queue full")

    app, _ = await _make_app(sessionmaker_override, enqueue_session=fail_enqueue)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post("/sessions", json={"user_id": "u1"})
        session_id = create.json()["session_id"]

        res = await client.post(f"/sessions/{session_id}/execute", params={"background": "true"})
        assert res.status_code == 429
        assert "queue full or enqueue failed" in res.text


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_background_execute_rejects_duplicate_enqueue_for_same_session(sessionmaker_override):
    queued: set[str] = set()

    async def dedupe_enqueue(session_id: str) -> None:
        if session_id in queued:
            raise RuntimeError("session already queued or in progress")
        queued.add(session_id)

    app, _ = await _make_app(sessionmaker_override, enqueue_session=dedupe_enqueue)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post("/sessions", json={"user_id": "u1"})
        session_id = create.json()["session_id"]

        first = await client.post(f"/sessions/{session_id}/execute", params={"background": "true"})
        assert first.status_code == 200

        second = await client.post(f"/sessions/{session_id}/execute", params={"background": "true"})
        assert second.status_code == 429
        assert "already queued or in progress" in second.text


@pytest.mark.asyncio
async def test_tampered_jwt_rejected_with_401(sessionmaker_override):
    secret = "phase4-secret"
    app, _ = await _make_app(sessionmaker_override, jwt_required=True, jwt_secret=secret)
    now = int(time.time())
    valid_token = _sign_test_jwt({"sub": "u1", "exp": now + 300}, secret)
    header_part, payload_part, sig_part = valid_token.split(".")
    tampered_payload = payload_part[:-1] + ("a" if payload_part[-1] != "a" else "b")
    tampered_token = f"{header_part}.{tampered_payload}.{sig_part}"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.post("/sessions", json={"user_id": "u1"}, headers={"Authorization": f"Bearer {valid_token}"})
        assert ok.status_code == 200

        bad = await client.post(
            "/sessions",
            json={"user_id": "u1"},
            headers={"Authorization": f"Bearer {tampered_token}"},
        )
        assert bad.status_code == 401


@pytest.mark.asyncio
async def test_pending_approval_read_endpoints_require_jwt_and_support_session_filter(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Approval, generate_uuid

    first = generate_uuid()
    second = generate_uuid()
    now = datetime.utcnow()
    db_session.add_all(
        [
            Approval(
                approval_id=first,
                session_id="sess-1",
                step_id=generate_uuid(),
                tool_name="put__machines_{id}",
                args={"id": "5"},
                risk_summary="x",
                side_effect_level="HIGH",
                status="PENDING",
                expires_at=now,
                created_at=now,
            ),
            Approval(
                approval_id=second,
                session_id="sess-2",
                step_id=generate_uuid(),
                tool_name="put__machines_{id}",
                args={"id": "6"},
                risk_summary="y",
                side_effect_level="HIGH",
                status="PENDING",
                expires_at=now,
                created_at=now,
            ),
        ]
    )
    await db_session.commit()

    secret = "phase4-secret"
    app, _ = await _make_app(sessionmaker_override, jwt_required=True, jwt_secret=secret)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        unauthorized = await client.get("/approvals/pending")
        assert unauthorized.status_code == 401

        authorized = await client.get(
            "/approvals/pending",
            headers=_auth_headers(secret),
            params={"session_id": "sess-2"},
        )
        assert authorized.status_code == 200
        body = authorized.json()
        assert len(body) == 1
        assert body[0]["session_id"] == "sess-2"


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_machine_tool_result_summary_is_operator_readable(sessionmaker_override, db_session, respx_mock):
    from factory_agent.persistence.models import Message

    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        capability_tags='["machine","status"]',
        is_read_only=True,
    )
    respx_mock.get("http://testserver/machines/5").respond(200, json={"id": "5", "name": "Machine 5", "status": "Idle"})

    app, _ = await _make_app(sessionmaker_override)
    draft = PlanDraft(
        plan_explanation="Read machine 5",
        risk_summary="read-only",
        steps=[PlanStepDraft(step_index=0, tool_name="get__machines_{id}", args={"id": "5"})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Check machine 5 status"})
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

    tool_message = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "tool_result")
        )
    ).scalars().first()
    assert tool_message is not None
    assert "Idle" in tool_message.content


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_product_ids_result_summary_returns_ids_not_generic_record_count(sessionmaker_override, db_session, respx_mock, monkeypatch):
    from factory_agent.persistence.models import Message

    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        async def ainvoke(self, prompt: str):
            if "tool result" in prompt.lower():
                return _FakeResponse("Found 3 IDs: P-001, P-002, P-003.")
            return _FakeResponse("Completed.")

    fake_langchain = types.SimpleNamespace(ChatOpenAI=_FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain)

    await _seed_tool(
        db_session,
        name="get__products",
        endpoint="/products",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {"fields": {"type": "string"}},
            "x-query-params": ["fields"],
            "x-param-sources": {"fields": "query"},
        },
        capability_tags='["product","list"]',
        is_read_only=True,
    )
    respx_mock.get("http://testserver/products").respond(
        200,
        json={
            "success": True,
            "data": [
                {"ProductID": "P-001"},
                {"ProductID": "P-002"},
                {"ProductID": "P-003"},
            ],
        },
    )

    app, _ = await _make_app(sessionmaker_override, openai_base_url="http://fake-llm")
    draft = PlanDraft(
        plan_explanation="List product IDs",
        risk_summary="read-only",
        steps=[PlanStepDraft(step_index=0, tool_name="get__products", args={"fields": "product_id"})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "get all product id"})
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

    tool_message = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "tool_result")
        )
    ).scalars().first()
    assert tool_message is not None
    assert "found 3 id(s)" in tool_message.content.lower()
    assert "p-001" in tool_message.content.lower()
    assert "record(s)" not in tool_message.content.lower()


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_product_ids_result_summary_works_without_llm(sessionmaker_override, db_session, respx_mock):
    from factory_agent.persistence.models import Message

    await _seed_tool(
        db_session,
        name="get__products",
        endpoint="/products",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {"fields": {"type": "string"}},
            "x-query-params": ["fields"],
            "x-param-sources": {"fields": "query"},
        },
        capability_tags='["product","list"]',
        is_read_only=True,
    )
    respx_mock.get("http://testserver/products").respond(
        200,
        json={
            "success": True,
            "data": [
                {"product_id": "P-001"},
                {"product_id": "P-002"},
                {"product_id": "P-003"},
            ],
        },
    )

    app, _ = await _make_app(sessionmaker_override, openai_base_url=None)
    draft = PlanDraft(
        plan_explanation="List product IDs",
        risk_summary="read-only",
        steps=[PlanStepDraft(step_index=0, tool_name="get__products", args={"fields": "product_id"})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "give me allthe product id"})
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

    tool_message = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "tool_result")
        )
    ).scalars().first()
    assert tool_message is not None
    assert "found 3 id(s)" in tool_message.content.lower()
    assert "p-001" in tool_message.content.lower()
    assert "record(s)" not in tool_message.content.lower()


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_job_list_result_summary_uses_llm_in_hybrid_mode(sessionmaker_override, db_session, respx_mock, monkeypatch):
    from factory_agent.persistence.models import Message

    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        async def ainvoke(self, prompt: str):
            lowered = prompt.lower()
            if '"message"' in prompt or "write a concise user-facing response" in lowered:
                return _FakeResponse('{"message":"Retrieved 4 jobs. Sample statuses include planned, scheduled, and done."}')
            if '"grounded"' in prompt or "verify whether the response is fully grounded" in lowered:
                return _FakeResponse('{"grounded": true, "issues": []}')
            if '"answer_type"' in prompt or "extract grounded facts" in lowered:
                return _FakeResponse(
                    '{"answer_type":"summary","facts":["Retrieved 4 jobs. Sample statuses include planned, scheduled, and done."],"ids":[],"counts":{"records":4},"warnings":[],"grounding_refs":["$.data[0].job_id"]}'
                )
            return _FakeResponse("Completed.")

    fake_langchain = types.SimpleNamespace(ChatOpenAI=_FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain)

    await _seed_tool(
        db_session,
        name="get__jobs",
        endpoint="/jobs",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["job","list"]',
        is_read_only=True,
    )
    respx_mock.get("http://testserver/jobs").respond(
        200,
        json={
            "success": True,
            "data": [
                {"job_id": "JOB-001", "product_id": "P-100", "status": "planned", "quantity_total": 40},
                {"job_id": "JOB-002", "product_id": "P-200", "status": "scheduled", "quantity_total": 25},
                {"job_id": "JOB-003", "product_id": "P-300", "status": "done", "quantity_total": 10},
                {"job_id": "JOB-004", "product_id": "P-400", "status": "planned", "quantity_total": 15},
            ],
        },
    )

    app, _ = await _make_app(sessionmaker_override, openai_base_url="http://fake-llm")
    draft = PlanDraft(
        plan_explanation="List jobs",
        risk_summary="read-only",
        steps=[PlanStepDraft(step_index=0, tool_name="get__jobs", args={})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "list all job"})
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

    tool_message = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "tool_result")
        )
    ).scalars().first()
    assert tool_message is not None
    content_lower = tool_message.content.lower()
    assert "retrieved 4 records" in content_lower
    assert "table" in content_lower


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_job_list_result_summary_recovers_from_structured_fact_dump(sessionmaker_override, db_session, respx_mock, monkeypatch):
    from factory_agent.persistence.models import Message

    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        async def ainvoke(self, prompt: str):
            lowered = prompt.lower()
            if '"message"' in prompt or "write a concise user-facing response" in lowered:
                return _FakeResponse('{"message":"Retrieved 26 jobs. One example is JOB-SEED-001, a high-priority planned job for product P-001 with quantity 320 due on 2026-05-12."}')
            if '"grounded"' in prompt or "verify whether the response is fully grounded" in lowered:
                return _FakeResponse('{"grounded": true, "issues": []}')
            if '"answer_type"' in prompt or "extract grounded facts" in lowered:
                return _FakeResponse(
                    '{"answer_type":"summary","facts":["{\\"job_id\\": \\"JOB-SEED-001\\", \\"product_id\\": \\"P-001\\", \\"quantity_total\\": 320, \\"quantity_completed\\": 0, \\"priority\\": \\"high\\", \\"deadline\\": \\"2026-05-12T08:00:00+08:00\\", \\"status\\": \\"planned\\"}"],"ids":[],"counts":{"records":26},"warnings":[],"grounding_refs":["$.data[0].job_id"]}'
                )
            return _FakeResponse("Completed.")

    fake_langchain = types.SimpleNamespace(ChatOpenAI=_FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain)

    await _seed_tool(
        db_session,
        name="get__jobs",
        endpoint="/jobs",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["job","list"]',
        is_read_only=True,
    )
    respx_mock.get("http://testserver/jobs").respond(
        200,
        json={
            "success": True,
            "data": [
                {"job_id": "JOB-SEED-001", "product_id": "P-001", "quantity_total": 320, "quantity_completed": 0, "priority": "high", "deadline": "2026-05-12T08:00:00+08:00", "status": "planned"},
                {"job_id": "JOB-SEED-002", "product_id": "P-002", "quantity_total": 420, "quantity_completed": 0, "priority": "medium", "deadline": "2026-05-12T08:00:00+08:00", "status": "planned"},
            ],
        },
    )

    app, _ = await _make_app(sessionmaker_override, openai_base_url="http://fake-llm")
    draft = PlanDraft(
        plan_explanation="List jobs",
        risk_summary="read-only",
        steps=[PlanStepDraft(step_index=0, tool_name="get__jobs", args={})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "list all job"})
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

    tool_message = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "tool_result")
        )
    ).scalars().first()
    assert tool_message is not None
    content_lower = tool_message.content.lower()
    assert "retrieved 2 records" in content_lower
    assert "table" in content_lower
    assert "{" not in tool_message.content

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        snapshot = await client.get(f"/sessions/{session_id}/snapshot")
        assert snapshot.status_code == 200
        timeline = snapshot.json()["timeline"]

    tool_event = next(event for event in timeline if event["event_type"] == "tool_result")
    presentation = tool_event["details"]["presentation"]
    assert presentation["render_hint"] == "table"
    assert presentation["table"]["total_rows"] == 2
    assert len(presentation["table"]["rows"]) == 2


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_job_list_result_summary_deterministically_extracts_analysis_intent(sessionmaker_override, db_session, respx_mock):
    from factory_agent.persistence.models import Message

    await _seed_tool(
        db_session,
        name="get__jobs",
        endpoint="/jobs",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "priority": {"type": "string"},
                "status": {"type": "string"},
            },
            "x-query-params": ["priority", "status"],
            "x-param-sources": {"priority": "query", "status": "query"},
        },
        capability_tags='["job","list"]',
        is_read_only=True,
    )
    respx_mock.get("http://testserver/jobs", params={"priority": "low", "status": "planned"}).respond(
        200,
        json={
            "success": True,
            "data": [
                {"job_id": "JOB-SEED-005", "product_id": "P-005", "quantity_total": 520, "deadline": "2026-05-19T08:00:00+08:00", "priority": "low", "status": "planned"},
                {"job_id": "JOB-SEED-009", "product_id": "P-003", "quantity_total": 140, "deadline": "2026-05-19T08:00:00+08:00", "priority": "low", "status": "planned"},
                {"job_id": "JOB-SEED-012", "product_id": "P-009", "quantity_total": 240, "deadline": "2026-05-19T08:00:00+08:00", "priority": "low", "status": "planned"},
                {"job_id": "JOB-SEED-017", "product_id": "P-004", "quantity_total": 180, "deadline": "2026-05-19T08:00:00+08:00", "priority": "low", "status": "planned"},
                {"job_id": "JOB-SEED-024", "product_id": "P-002", "quantity_total": 480, "deadline": "2026-05-07T08:00:00+08:00", "priority": "low", "status": "planned"},
            ],
        },
    )

    app, _ = await _make_app(sessionmaker_override, openai_base_url=None)
    draft = PlanDraft(
        plan_explanation="List low-priority planned jobs",
        risk_summary="read-only",
        steps=[PlanStepDraft(step_index=0, tool_name="get__jobs", args={"priority": "low", "status": "planned"})],
    )
    prompt = "Show low-priority planned jobs and highlight the earliest deadline and largest quantity."
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": prompt})
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

        snapshot = await client.get(f"/sessions/{session_id}/snapshot")
        assert snapshot.status_code == 200
        timeline = snapshot.json()["timeline"]

    tool_message = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "tool_result")
        )
    ).scalars().first()
    assert tool_message is not None
    content = tool_message.content.lower()
    assert "retrieved 5 records" in content
    assert "earliest deadline: job-seed-024" in content
    assert "largest quantity: job-seed-005" in content

    tool_event = next(event for event in timeline if event["event_type"] == "tool_result")
    result = tool_event["details"]["result"]
    assert result["_analysis"]["dataset"]["row_count"] == 5
    assert "earliest deadline: job-seed-024" in tool_event["details"]["presentation"]["analysis"]["facts"][0].lower()


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_read_only_machine_not_found_returns_operator_friendly_completion(sessionmaker_override, db_session, respx_mock):
    from factory_agent.persistence.models import Message, Session

    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        capability_tags='["machine","status"]',
        is_read_only=True,
    )
    respx_mock.get("http://testserver/machines/5").respond(404, json={"detail": "machine not found"})

    app, _ = await _make_app(sessionmaker_override)
    draft = PlanDraft(
        plan_explanation="Read machine 5",
        risk_summary="read-only",
        steps=[PlanStepDraft(step_index=0, tool_name="get__machines_{id}", args={"id": "5"})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Check machine 5 status"})
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

    session_row = await db_session.get(Session, session_id)
    assert session_row is not None
    assert session_row.status == "COMPLETED"
    assert session_row.replan_count == 0
    assert session_row.error in (None, "")

    tool_message = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "tool_result")
        )
    ).scalars().first()
    assert tool_message is not None
    assert "not found" in tool_message.content.lower()


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_write_machine_not_found_is_checked_before_approval(sessionmaker_override, db_session, respx_mock):
    from factory_agent.persistence.models import Approval, Message

    read_schema = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
    write_schema = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "status": {"type": "string"}},
        "required": ["id", "status"],
    }
    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema=read_schema,
        capability_tags='["machine","status"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="put__machines_{id}",
        endpoint="/machines/{id}",
        method="PUT",
        input_schema=write_schema,
        capability_tags='["machine","update"]',
        is_read_only=False,
        requires_approval=True,
    )
    respx_mock.get("http://testserver/machines/5").respond(404, json={"detail": "machine not found"})

    app, _ = await _make_app(sessionmaker_override)
    draft = PlanDraft(
        plan_explanation="Update machine 5",
        risk_summary="write",
        steps=[PlanStepDraft(step_index=0, tool_name="put__machines_{id}", args={"id": "5", "status": "maintenance"})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Update machine 5 to maintenance"},
        )
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

        pending = await client.get("/approvals/pending", params={"session_id": session_id})
        assert pending.status_code == 200
        assert pending.json() == []

    approvals = (await db_session.execute(select(Approval).where(Approval.session_id == session_id))).scalars().all()
    assert approvals == []
    tool_message = (
        await db_session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .where(Message.role == "tool_result")
        )
    ).scalars().first()
    assert tool_message is not None
    assert "not found" in tool_message.content.lower()
    assert "No changes were made." in tool_message.content


@pytest.mark.asyncio
@pytest.mark.legacy_compatibility
@LEGACY_RUNTIME_RETIRED_XFAIL
async def test_write_machine_approval_includes_target_preview(sessionmaker_override, db_session, respx_mock):
    read_schema = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
    write_schema = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "status": {"type": "string"}},
        "required": ["id", "status"],
    }
    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema=read_schema,
        capability_tags='["machine","status"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="put__machines_{id}",
        endpoint="/machines/{id}",
        method="PUT",
        input_schema=write_schema,
        capability_tags='["machine","update"]',
        is_read_only=False,
        requires_approval=True,
    )
    respx_mock.get("http://testserver/machines/5").respond(
        200,
        json={"id": "5", "name": "Machine 5", "status": "Idle"},
    )

    app, _ = await _make_app(sessionmaker_override)
    draft = PlanDraft(
        plan_explanation="Update machine 5",
        risk_summary="write",
        steps=[PlanStepDraft(step_index=0, tool_name="put__machines_{id}", args={"id": "5", "status": "maintenance"})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Update machine 5 to maintenance"})
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "WAITING_APPROVAL"

        pending = await client.get("/approvals/pending", params={"session_id": session_id})
        assert pending.status_code == 200
        rows = pending.json()
        assert len(rows) == 1
        assert "Target check" in rows[0]["risk_summary"]
        assert "Idle" in rows[0]["risk_summary"]


@pytest.mark.asyncio
async def test_write_machine_not_found_skips_approval_without_read_tool_registered(sessionmaker_override, db_session, respx_mock):
    from factory_agent.persistence.models import Approval

    write_schema = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "status": {"type": "string"}},
        "required": ["id", "status"],
    }
    await _seed_tool(
        db_session,
        name="put__machines_{id}",
        endpoint="/machines/{id}",
        method="PUT",
        input_schema=write_schema,
        capability_tags='["machine","update"]',
        is_read_only=False,
        requires_approval=True,
    )
    respx_mock.get("http://testserver/machines/5").respond(404, json={"detail": "machine not found"})

    app, _ = await _make_app(sessionmaker_override)
    draft = PlanDraft(
        plan_explanation="Update machine 5",
        risk_summary="write",
        steps=[PlanStepDraft(step_index=0, tool_name="put__machines_{id}", args={"id": "5", "status": "maintenance"})],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions", json={"user_id": "u1"})
        session_id = created.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "Update machine 5 to maintenance"})
        await client.post(f"/sessions/{session_id}/plans", json={"draft": draft.model_dump()})
        executed = await client.post(f"/sessions/{session_id}/execute")
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

        pending = await client.get("/approvals/pending", params={"session_id": session_id})
        assert pending.status_code == 200
        assert pending.json() == []

    approvals = (await db_session.execute(select(Approval).where(Approval.session_id == session_id))).scalars().all()
    assert approvals == []


@pytest.mark.asyncio
async def test_json_injection_attempt_in_args_rejected_without_plan_write(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Plan

    schema = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    await _seed_tool(
        db_session,
        name="post__inventory_update",
        endpoint="/inventory",
        method="POST",
        input_schema=schema,
        capability_tags='["inventory"]',
        is_read_only=False,
        requires_approval=True,
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post("/sessions", json={"user_id": "u1"})
        session_id = create.json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "update inventory"})

        res = await client.post(
            f"/sessions/{session_id}/plans",
            json={
                "draft": {
                    "plan_explanation": "attempt injection",
                    "risk_summary": "write op",
                    "steps": [
                        {
                            "step_index": 0,
                            "tool_name": "post__inventory_update",
                            "args": {"id": {"$gt": 0}},
                        }
                    ],
                }
            },
        )
        assert res.status_code == 400

    plan_rows = (await db_session.execute(select(Plan).where(Plan.session_id == session_id))).scalars().all()
    assert len(plan_rows) == 0


