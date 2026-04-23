import pytest
from datetime import datetime
import base64
import hashlib
import hmac
import json
import time

import httpx
from fastapi import FastAPI
from sqlalchemy import select

import database
from agent.api import build_router
from agent.config import Settings
from agent.schemas import PlanDraft, PlanStepDraft
from agent.tool_registry import ToolRegistry


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


async def _make_app(
    sessionmaker_override,
    enqueue_session=None,
    jwt_required=False,
    jwt_secret=None,
    planner_adapter=None,
    planner_fallback_to_legacy=True,
):
    settings = Settings(
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
        jwt_required=jwt_required,
        jwt_secret=jwt_secret,
        jwt_clock_skew_s=30,
        planner_fallback_to_legacy=planner_fallback_to_legacy,
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
        )
    )
    return app, event_bus


async def _seed_tool(db_session, *, name, endpoint, method, input_schema, capability_tags, is_read_only=True, requires_approval=False):
    from models import Tool, generate_uuid

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
    from models import Plan, PlanStep, Session, generate_uuid
    from agent.execution import compute_idempotency_key

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
        async def generate_plan(self, *, intent, scoped_tools, context=None, force_backend=None):
            del scoped_tools, context, force_backend
            return type(
                "X",
                (),
                {
                    "draft": PlanDraft(
                        plan_explanation=f"Auto plan for {intent}",
                        risk_summary="read-only",
                        steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={})],
                    ),
                    "backend_used": "legacy",
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
        assert created.json()["created_by"] == "legacy"


@pytest.mark.asyncio
async def test_langchain_planner_invalid_output_rejected(sessionmaker_override, db_session):
    from models import Plan

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
        async def generate_plan(self, *, intent, scoped_tools, context=None, force_backend=None):
            del intent, scoped_tools, context, force_backend
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
async def test_generated_write_plan_sets_requires_approval_and_waits_approval(sessionmaker_override, db_session):
    from models import Approval, PlanStep

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
        async def generate_plan(self, *, intent, scoped_tools, context=None, force_backend=None):
            del intent, scoped_tools, context, force_backend
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
async def test_langchain_invalid_output_fallback_enabled_uses_legacy_and_persists_only_valid_plan(sessionmaker_override, db_session):
    from models import PlanStep

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
        def __init__(self):
            self.fallback_called = False

        async def generate_plan(self, *, intent, scoped_tools, context=None, force_backend=None):
            del intent, scoped_tools, context
            if force_backend == "legacy":
                self.fallback_called = True
                return type(
                    "X",
                    (),
                    {
                        "draft": PlanDraft(
                            plan_explanation="fallback plan",
                            risk_summary="read-only",
                            steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={"id": 1})],
                        ),
                        "backend_used": "legacy",
                        "llm_calls": 0,
                    },
                )()
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

    planner = FakePlanner()
    app, _ = await _make_app(sessionmaker_override, planner_adapter=planner, planner_fallback_to_legacy=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "machine"})
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        assert created.json()["created_by"] == "legacy"

    assert planner.fallback_called is True
    steps = (
        await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))
    ).scalars().all()
    assert len(steps) == 1
    assert steps[0].tool_name == "get__machines"


@pytest.mark.asyncio
async def test_langchain_invalid_output_fallback_disabled_rejected_and_not_executable(sessionmaker_override, db_session):
    from models import Plan

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
        async def generate_plan(self, *, intent, scoped_tools, context=None, force_backend=None):
            del intent, scoped_tools, context, force_backend
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
        planner_fallback_to_legacy=False,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "machine"})
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 400

        execute = await client.post(f"/sessions/{session_id}/execute")
        assert execute.status_code == 200
        assert execute.json()["plan_id"] is None

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
async def test_reject_approval_sets_session_idle_and_step_skipped(sessionmaker_override, db_session):
    from models import Approval, PlanStep, Session, generate_uuid

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

    sess = await db_session.get(Session, "sess-reject")
    step = (await db_session.execute(select(PlanStep).where(PlanStep.step_id == step_id))).scalars().first()
    assert sess.status == "IDLE"
    assert step.status == "SKIPPED"


@pytest.mark.asyncio
async def test_cancel_marks_remaining_steps_skipped(sessionmaker_override, db_session):
    from models import PlanStep, Session

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
async def test_end_to_end_state_progression_with_approval_resume(sessionmaker_override, db_session, respx_mock):
    from models import PlanStep

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
async def test_dlq_dismiss_and_replay_endpoints(sessionmaker_override, db_session):
    from models import DeadLetter, generate_uuid

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
    from models import Session, generate_uuid

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
    from models import Session

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
async def test_dlq_replay_resets_step_and_marks_session_executing(sessionmaker_override, db_session):
    from models import DeadLetter, PlanStep, Session, generate_uuid

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
    from models import DeadLetter, Session, Tool, generate_uuid

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
        forbidden = await client.get("/admin/sessions", headers={"X-Admin-Key": "wrong-key"})
        assert forbidden.status_code == 403
        allowed = await client.get("/admin/sessions", headers={"X-Admin-Key": "test-admin-key"})
        assert allowed.status_code == 200
        assert isinstance(allowed.json(), list)


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_format(sessionmaker_override):
    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/metrics")
        assert res.status_code == 200
        assert "text/plain" in res.headers.get("content-type", "")
        assert "# HELP" in res.text
        assert "plan_validation_failure_rate" in res.text
        assert "db_connection_pool_usage" in res.text


@pytest.mark.asyncio
async def test_admin_dashboard_html_renders(sessionmaker_override):
    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/admin/dashboard", headers={"X-Admin-Key": "test-admin-key"})
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "Factory Agent Dashboard" in res.text


@pytest.mark.asyncio
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
async def test_json_injection_attempt_in_args_rejected_without_plan_write(sessionmaker_override, db_session):
    from models import Plan

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
