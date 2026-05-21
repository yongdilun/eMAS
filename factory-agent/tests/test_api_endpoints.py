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
    openai_api_key=None,
    force_llm_trace_all=False,
    tool_selector_openai_base_url=None,
    rag_pipeline_adapter=None,
    factory_agent_engine=None,
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
        openai_api_key=openai_api_key,
        force_llm_trace_all=force_llm_trace_all,
        tool_selector_openai_base_url=tool_selector_openai_base_url,
        factory_agent_engine=factory_agent_engine or "v2",
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
async def test_list_sessions_is_bounded_and_recent_for_user(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Session

    base = datetime(2026, 1, 1, 12, 0, 0)
    db_session.add_all(
        [
            Session(
                session_id=f"recent-{index}",
                user_id="u1",
                name=f"Chat {index}",
                status="IDLE",
                updated_at=base + timedelta(minutes=index),
            )
            for index in range(120)
        ]
        + [
            Session(
                session_id="other-user-session",
                user_id="u2",
                name="Other user",
                status="IDLE",
                updated_at=base + timedelta(minutes=999),
            )
        ]
    )
    await db_session.commit()

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        default_response = await client.get("/sessions?user_id=u1")
        assert default_response.status_code == 200
        default_rows = default_response.json()
        assert len(default_rows) == 100
        assert default_rows[0]["session_id"] == "recent-119"
        assert default_rows[-1]["session_id"] == "recent-20"
        assert "other-user-session" not in {row["session_id"] for row in default_rows}

        limited_response = await client.get("/sessions?user_id=u1&limit=3")
        assert limited_response.status_code == 200
        assert [row["session_id"] for row in limited_response.json()] == ["recent-119", "recent-118", "recent-117"]


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
async def test_actionable_prompt_with_empty_generated_plan_blocks_instead_of_orphan_idle(
    sessionmaker_override,
    db_session,
):
    await _seed_tool(
        db_session,
        name="patch__jobs_{id}",
        endpoint="/jobs/{id}",
        method="PATCH",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}, "priority": {"type": "string"}},
            "required": ["id", "priority"],
        },
        capability_tags='["job","priority","update"]',
        is_read_only=False,
        requires_approval=True,
    )

    class EmptyActionPlanner:
        async def generate_plan(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            return type(
                "X",
                (),
                {
                    "draft": PlanDraft(
                        plan_explanation="No safe execution step could be produced.",
                        risk_summary="No approved action can be started.",
                        steps=[],
                    ),
                    "backend_used": "langchain",
                    "llm_calls": 1,
                },
            )()

    app, _ = await _make_app(sessionmaker_override, planner_adapter=EmptyActionPlanner())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={
                "role": "user",
                "content": "change all medium priority job to high then change all high priority job to low",
                "mode": "normal",
            },
        )

        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        snapshot = (await client.get(f"/sessions/{session_id}/snapshot")).json()

    assert snapshot["session"]["status"] == "WAITING_APPROVAL"
    assert snapshot["pending_approval"] is not None
    assert snapshot["plan"]["created_by"] == "planner_owned_agent_graph"
    assert "non_terminal_snapshot" not in json.dumps(snapshot["response_document"])


@pytest.mark.asyncio
async def test_phase14_active_pending_approval_uses_actionable_write_set_and_rejects_noop_stale_approval(
    sessionmaker_override,
    db_session,
):
    from factory_agent.persistence.models import Approval, PlanStep, Session

    session_id = "api-phase14-zero-match"
    active_approval_id = "api-phase14-medium-high"
    stale_noop_approval_id = "api-phase14-low-medium-noop"
    now = datetime.utcnow()
    medium_rows = [
        {"job_id": "JOB-API-MED-001", "priority": "medium", "previous_priority": "medium", "new_priority": "high"},
        {"job_id": "JOB-API-MED-002", "priority": "medium", "previous_priority": "medium", "new_priority": "high"},
    ]
    no_op = {
        "entity_type": "job",
        "selector_summary": "priority = low",
        "change_summary": "priority -> medium",
        "matched_count": 0,
        "changed_count": 0,
        "status": "not_changed",
        "reason": "no_matching_records",
    }
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            name="Phase 14 zero-match approval",
            status="WAITING_APPROVAL",
            current_intent="change all low priority job to medium, then change all medium priority job to high",
            plan_version=1,
            version=1,
            event_seq=4,
            session_started_at=now,
            created_at=now,
            updated_at=now,
            replan_context={
                "langgraph_pending_approval": {"approval_id": active_approval_id, "thread_id": session_id},
                "no_op_mutations": [no_op],
            },
        )
    )
    db_session.add_all(
        [
            Approval(
                approval_id=stale_noop_approval_id,
                session_id=session_id,
                subject_type="graph",
                tool_name="__langgraph_commit__",
                args={"count": 0, "no_op_mutations": [no_op], "bundle_ui": {"rows": []}},
                risk_summary="No low-priority jobs were found.",
                side_effect_level="HIGH",
                status="PENDING",
                expires_at=now + timedelta(hours=1),
                created_at=now,
            ),
            Approval(
                approval_id=active_approval_id,
                session_id=session_id,
                subject_type="graph",
                tool_name="__langgraph_commit__",
                args={
                    "summary": "Update 2 jobs from medium to high.",
                    "count": 2,
                    "no_op_mutations": [no_op],
                    "bundle_ui": {
                        "kind": "phase14_zero_match_first",
                        "headline": "Update 2 jobs from medium to high",
                        "rows": medium_rows,
                    },
                },
                risk_summary="Update 2 jobs from medium to high.",
                side_effect_level="HIGH",
                status="PENDING",
                expires_at=now + timedelta(hours=1),
                created_at=now + timedelta(seconds=1),
            ),
        ]
    )
    await db_session.commit()

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        snapshot = (await client.get(f"/sessions/{session_id}/snapshot")).json()
        assert snapshot["pending_approval"]["approval_id"] == active_approval_id
        assert [row["job_id"] for row in snapshot["pending_approval"]["args"]["bundle_ui"]["rows"]] == [
            "JOB-API-MED-001",
            "JOB-API-MED-002",
        ]
        assert "priority = low" not in json.dumps(snapshot["pending_approval"]["args"]["bundle_ui"]["rows"])

        stale = await client.post(f"/approvals/{stale_noop_approval_id}/approve", json={"decided_by": "u1"})
        assert stale.status_code == 409
        assert "stale" in stale.text.lower()

    stale_row = await db_session.get(Approval, stale_noop_approval_id)
    active_row = await db_session.get(Approval, active_approval_id)
    session = await db_session.get(Session, session_id)
    assert stale_row.status == "EXPIRED"
    assert active_row.status == "PENDING"
    assert session.status == "WAITING_APPROVAL"
    committed_steps = (
        await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))
    ).scalars().all()
    assert committed_steps == []


@pytest.mark.asyncio
async def test_phase14_direct_v2_resume_queues_second_actionable_approval(
    sessionmaker_override,
    db_session,
    monkeypatch,
):
    from factory_agent.persistence.models import Approval, PlanStep, Session

    session_id = "api-phase14-followup-approval"
    first_approval_id = "api-phase14-low-medium"
    now = datetime.utcnow()
    low_rows = [
        {"job_id": "JOB-LOW-001", "priority": "low", "previous_priority": "low", "new_priority": "medium"},
        {"job_id": "JOB-LOW-002", "priority": "low", "previous_priority": "low", "new_priority": "medium"},
    ]
    medium_rows = [
        {"job_id": "JOB-MED-001", "priority": "medium", "previous_priority": "medium", "new_priority": "high"},
        {"job_id": "JOB-MED-002", "priority": "medium", "previous_priority": "medium", "new_priority": "high"},
        {"job_id": "JOB-MED-003", "priority": "medium", "previous_priority": "medium", "new_priority": "high"},
    ]
    remaining_medium_high = {
        "summary": "Update 3 jobs from medium to high.",
        "count": 3,
        "rows": medium_rows,
        "excluded_rows": [],
        "preview": [
            {"tool_name": "put__jobs_{id}", "args": {"id": row["job_id"], "priority": "high"}}
            for row in medium_rows
        ],
        "locked_constraints": {"priority": "medium", "new_priority": "high"},
        "current_requirement_id": "req-medium-high",
        "entity_type": "job",
        "previous_priority": "medium",
        "new_priority": "high",
        "source_priority": "medium",
        "business_change_id": "job-priority-medium-to-high",
        "business_change": "Medium -> High",
        "selector_summary": "priority = medium",
    }
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            name="Phase 14 chained approvals",
            status="WAITING_APPROVAL",
            current_intent="change all low priority job to medium, then change all medium priority job to high",
            plan_version=1,
            version=1,
            event_seq=4,
            session_started_at=now,
            created_at=now,
            updated_at=now,
            replan_context={
                "langgraph_pending_approval": {"approval_id": first_approval_id, "thread_id": session_id},
            },
        )
    )
    db_session.add(
        Approval(
            approval_id=first_approval_id,
            session_id=session_id,
            subject_type="graph",
            tool_name="__langgraph_commit__",
            args={
                "summary": "Update 2 jobs from low to medium.",
                "count": 2,
                "preview": [
                    {"tool_name": "put__jobs_{id}", "args": {"id": row["job_id"], "priority": "medium"}}
                    for row in low_rows
                ],
                "remaining_business_changes": [remaining_medium_high],
                "actionable_business_change_count": 2,
                "bundle_ui": {
                    "kind": "v2_planner_owned_approval_preview",
                    "write_set": "job-priority-low-to-medium",
                    "headline": "Update 2 jobs from low to medium",
                    "rows": low_rows,
                    "excluded_rows": [],
                    "previous_priority": "low",
                    "new_priority": "medium",
                    "source_priority": "low",
                    "locked_constraints": {"priority": "low", "new_priority": "medium"},
                    "source_intent": "change all low priority job to medium, then change all medium priority job to high",
                    "write_tool_name": "put__jobs_{id}",
                    "business_change_id": "job-priority-low-to-medium",
                    "business_change": "Low -> Medium",
                    "selector_summary": "priority = low",
                },
                "current_requirement_id": "req-low-medium",
                "mutation_requirements": [
                    {
                        "id": "req-low-medium",
                        "goal": "change all low priority job to medium",
                        "constraints": {"priority": "low", "new_priority": "medium"},
                        "entity": "job",
                        "requirement_type": "mutation_request",
                    },
                    {
                        "id": "req-medium-high",
                        "goal": "change all medium priority job to high",
                        "constraints": {"priority": "medium", "new_priority": "high"},
                        "entity": "job",
                        "requirement_type": "mutation_request",
                    },
                ],
                "locked_constraints": {"priority": "low", "new_priority": "medium"},
                "commit_state": "not_committed",
                "session_id": session_id,
            },
            risk_summary="Update 2 jobs from low to medium.",
            side_effect_level="HIGH",
            status="PENDING",
            expires_at=now + timedelta(hours=1),
            created_at=now,
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
        capability_tags='["job","update"]',
        is_read_only=False,
        requires_approval=True,
    )

    committed_args = []

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key, extra_headers=None):
        del settings, tool, idempotency_key, extra_headers
        committed_args.append(dict(args))
        return {
            "ok": True,
            "http_status": 200,
            "body": {"data": {"job_id": args["id"], "priority": args["priority"]}},
            "latency_ms": 1,
            "infrastructure_error": False,
        }

    monkeypatch.setattr(
        "factory_agent.services.approval_resume_service.execute_tool_http",
        fake_execute_tool_http,
    )
    app, _ = await _make_app(sessionmaker_override, enforce_tool_registry_health=False, min_healthy_tool_count=0)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(f"/approvals/{first_approval_id}/approve", json={"decided_by": "u1"})
        assert first.status_code == 200
        assert first.json()["status"] == "APPROVED"

        after_first = (await client.get(f"/sessions/{session_id}/snapshot")).json()
        assert after_first["session"]["status"] == "WAITING_APPROVAL"
        pending = after_first["pending_approval"]
        assert pending["approval_id"] != first_approval_id
        assert pending["args"]["bundle_ui"]["business_change_id"] == "job-priority-medium-to-high"
        assert pending["args"]["bundle_ui"]["headline"] == "Update 3 jobs from medium to high"
        assert [row["job_id"] for row in pending["args"]["bundle_ui"]["rows"]] == [
            "JOB-MED-001",
            "JOB-MED-002",
            "JOB-MED-003",
        ]
        assert {args["priority"] for args in committed_args} == {"medium"}

        second_approval_id = pending["approval_id"]
        second = await client.post(f"/approvals/{second_approval_id}/approve", json={"decided_by": "u1"})
        assert second.status_code == 200
        assert second.json()["status"] == "APPROVED"

        final = (await client.get(f"/sessions/{session_id}/snapshot")).json()
        assert final["session"]["status"] == "COMPLETED"
        assert final["pending_approval"] is None

    assert [args["priority"] for args in committed_args] == ["medium", "medium", "high", "high", "high"]
    session = await db_session.get(Session, session_id)
    committed_steps = (
        await db_session.execute(
            select(PlanStep)
            .where(PlanStep.plan_id == session.plan_id)
            .order_by(PlanStep.step_index.asc())
        )
    ).scalars().all()
    assert len(committed_steps) == 5
    assert [step.args["priority"] for step in committed_steps] == ["medium", "medium", "high", "high", "high"]


@pytest.mark.asyncio
async def test_create_plan_answers_osha_loto_knowledge_question_without_tool_plan(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Session

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
                            "OSHA's lockout/tagout standard, 29 CFR 1910.147, covers the control of "
                            "hazardous energy during servicing and maintenance [^1]."
                        ),
                        "sources": [
                            {
                                "source_number": 1,
                            "source_id": "osha_3120_lockout_tagout#purpose-standard",
                            "doc_id": "osha_3120_lockout_tagout",
                            "chunk_id": "purpose-standard",
                            "title": "Control of Hazardous Energy Lockout/Tagout",
                            "organization": "OSHA",
                            "authority_level": "official_public_guidance",
                            "snippet": (
                                "OSHA's lockout/tagout standard, 29 CFR 1910.147, covers the control of "
                                "hazardous energy during servicing and maintenance and helps prevent unexpected "
                                "energization, startup, or release of stored energy."
                            ),
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
        assert body["created_by"] == "planner_owned_agent_graph"
        assert not body["plan_explanation"].startswith("I do not have enough retrieved evidence")
        assert "29 CFR 1910.147" in body["plan_explanation"]
        assert body["sources"][0]["organization"] == "OSHA"
        assert {source["doc_id"] for source in body["sources"]} == {"osha_3120_lockout_tagout"}
        assert body["sources"][0]["chunk_id"] == "purpose-standard"
        assert "approved SOP" in body["safety_content"]

        steps = await client.get(f"/sessions/{session_id}/steps")
        assert steps.status_code == 200
        assert steps.json() == []

    assert rag.calls
    assert rag.calls[0]["route"] == "RAG_ONLY"
    session_row = await db_session.get(Session, session_id)
    contract = (session_row.replan_context or {})["intent_contract"]
    trace = contract["execution_trace"]
    evidence = contract["v2_state"]["evidence_ledger"]["evidence"]
    assert contract["engine_version"] == "v2"
    assert trace["generated_by"] == "planner_owned_agent_graph"
    assert trace["detectors"]["legacy_rag_shortcut"]["used"] is False
    assert evidence[0]["source_type"] == "rag_tool"
    assert evidence[0]["tool_name"] == "rag_search_documents"
    assert "29 CFR 1910.147" in evidence[0]["normalized_result"]["answer"]


@pytest.mark.asyncio
async def test_create_plan_does_not_recover_uncited_osha_loto_answer_from_source_excerpt(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Session

    class FakeRAGPipeline:
        async def run(self, *, query, session_id=None, route="RAG_ONLY", api_data=None):
            del query, session_id, route, api_data
            return type(
                "Result",
                (),
                {
                    "answer": (
                        "OSHA's lockout/tagout standard, 29 CFR 1910.147, covers the control of "
                        "hazardous energy during servicing and maintenance."
                    ),
                    "sources": [
                        {
                            "source_number": 1,
                            "source_id": "osha_3120_lockout_tagout#purpose-standard",
                            "doc_id": "osha_3120_lockout_tagout",
                            "chunk_id": "purpose-standard",
                            "title": "Control of Hazardous Energy Lockout/Tagout",
                            "organization": "OSHA",
                            "authority_level": "official_public_guidance",
                            "snippet": (
                                "OSHA's lockout/tagout standard, 29 CFR 1910.147, covers the control of "
                                "hazardous energy during servicing and maintenance."
                            ),
                        }
                    ],
                    "safety_content": "This topic involves high-risk industrial procedures.",
                },
            )()

    app, _ = await _make_app(sessionmaker_override, rag_pipeline_adapter=FakeRAGPipeline())

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
        assert body["created_by"] == "planner_owned_agent_graph"
        assert body["plan_explanation"].startswith("I do not have enough retrieved evidence")
        assert "29 CFR 1910.147" not in body["plan_explanation"]
        assert body["sources"][0]["doc_id"] == "osha_3120_lockout_tagout"

    session_row = await db_session.get(Session, session_id)
    evidence = (session_row.replan_context or {})["intent_contract"]["v2_state"]["evidence_ledger"]["evidence"]
    assert evidence[0]["source_type"] == "system_guard"
    assert evidence[0]["tool_name"] == "rag_search_documents"
    assert evidence[0]["normalized_result"]["answer"].startswith("I do not have enough retrieved evidence")
    assert evidence[0]["diagnostic_metadata"]["graph_tool_action"] == "rag_tool"


@pytest.mark.asyncio
async def test_create_plan_uses_insufficient_context_when_osha_loto_rag_is_empty(sessionmaker_override):
    class FakeRAGPipeline:
        async def run(self, *, query, session_id=None, route="RAG_ONLY", api_data=None):
            del query, session_id, route, api_data
            return type(
                "Result",
                (),
                {
                    "answer": "No relevant documents or data found for this query.",
                    "sources": [],
                    "safety_content": None,
                },
            )()

    app, _ = await _make_app(sessionmaker_override, rag_pipeline_adapter=FakeRAGPipeline())

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
        assert body["plan_explanation"].startswith("I do not have enough retrieved evidence")
        assert "29 CFR 1910.147" not in body["plan_explanation"]
        assert body["sources"] == []
        assert "consult your safety officer" in body["safety_content"]


@pytest.mark.asyncio
async def test_create_plan_uses_insufficient_context_when_osha_loto_sources_do_not_prove_claim(sessionmaker_override):
    class FakeRAGPipeline:
        async def run(self, *, query, session_id=None, route="RAG_ONLY", api_data=None):
            del query, session_id, route, api_data
            return type(
                "Result",
                (),
                {
                    "answer": "The OSHA guide describes general energy-control responsibilities [^1].",
                    "sources": [
                        {
                            "source_number": 1,
                            "source_id": "osha_3120_lockout_tagout#general-energy-control",
                            "doc_id": "osha_3120_lockout_tagout",
                            "chunk_id": "general-energy-control",
                            "title": "Control of Hazardous Energy Lockout/Tagout",
                            "organization": "OSHA",
                            "snippet": "The guide describes energy-control program responsibilities for employers.",
                        }
                    ],
                    "safety_content": None,
                },
            )()

    app, _ = await _make_app(sessionmaker_override, rag_pipeline_adapter=FakeRAGPipeline())

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
        assert body["created_by"] == "planner_owned_agent_graph"
        assert body["plan_explanation"].startswith("I do not have enough retrieved evidence")
        assert "related sources checked" in body["plan_explanation"]
        assert "29 CFR 1910.147" not in body["plan_explanation"]
        assert body["sources"][0]["doc_id"] == "osha_3120_lockout_tagout"
        assert "consult your safety officer" in body["safety_content"]


@pytest.mark.asyncio
async def test_create_plan_unknown_non_loto_procedure_does_not_borrow_osha_policy(sessionmaker_override):
    class FakeRAGPipeline:
        async def run(self, *, query, session_id=None, route="RAG_ONLY", api_data=None):
            del query, session_id, route, api_data
            return type(
                "Result",
                (),
                {
                    "answer": "No relevant documents or data found for this query.",
                    "sources": [],
                    "safety_content": None,
                },
            )()

    app, _ = await _make_app(sessionmaker_override, rag_pipeline_adapter=FakeRAGPipeline())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={
                "role": "user",
                "content": "What SOP applies before cleaning Line 2?",
                "mode": "normal",
            },
        )

        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        body = created.json()
        assert "29 CFR 1910.147" not in body["plan_explanation"]
        assert "Lockout/Tagout" not in body["plan_explanation"]
        assert body["sources"] == []
        assert body["safety_content"] is None


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
async def test_conversation_message_returns_completed_empty_plan(sessionmaker_override, db_session):
    from factory_agent.persistence.models import PlanStep, Session

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
        snapshot_body = snapshot.json()
        assert snapshot_body["plan"]["status"] == "COMPLETED"
        assert snapshot_body["plan"]["created_by"] == "planner_owned_agent_graph"
        assert any(event["event_type"] == "plan_created" for event in snapshot_body["timeline"])
        assert any(
            event["event_type"] == "session_completed" and "factory operations" in event["content"]
            for event in snapshot_body["timeline"]
        )
        assert snapshot_body["response_document"]["state"] == "completed"

        executed = await client.post(f"/sessions/{session_id}/execute", json={})
        assert executed.status_code == 200
        assert executed.json()["status"] == "COMPLETED"

    steps = (await db_session.execute(select(PlanStep).where(PlanStep.session_id == session_id))).scalars().all()
    assert steps == []
    session_row = await db_session.get(Session, session_id)
    context = session_row.replan_context or {}
    assert context["planner_owned_agent_graph"]["runtime_adapter"] in {
        "non_operational_guard",
        "plan_creation_service",
    }


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
async def test_create_direct_v2_plan_records_forced_reranker_in_session_trace(
    sessionmaker_override,
    db_session,
    monkeypatch,
):
    from factory_agent.persistence.models import Session
    from factory_agent.planning.tool_selector import ToolSelector

    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        capability_tags='["machine","lookup","status"]',
        is_read_only=True,
    )
    await _seed_tool(
        db_session,
        name="get__machines_status",
        endpoint="/machines/status",
        method="GET",
        input_schema={"type": "object", "properties": {}},
        capability_tags='["machine","status","list"]',
        is_read_only=True,
    )

    called = {"count": 0}

    async def fake_invoke(self, *, prompt):
        del self, prompt
        called["count"] += 1
        return {
            "primary_tool": "get__machines_{id}",
            "additional_tools": ["get__machines_status"],
            "confidence": 1.0,
            "missing_fields": [],
            "reason": "forced trace accounting",
        }

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key, extra_headers=None):
        del settings, tool, idempotency_key, extra_headers
        return {
            "ok": True,
            "http_status": 200,
            "body": {
                "data": {
                    "machineID": str(args.get("id") or "5"),
                    "status": "RUNNING",
                }
            },
            "latency_ms": 1,
            "infrastructure_error": False,
        }

    monkeypatch.setattr(ToolSelector, "_invoke_reranker", fake_invoke)
    monkeypatch.setattr(
        ToolSelector,
        "_top_candidates",
        lambda self, **kwargs: [
            ("get__machines_{id}", 100),
            ("get__machines_status", 1),
        ],
    )
    monkeypatch.setattr(
        "factory_agent.planning.v2_graph_adapters._default_http_executor",
        fake_execute_tool_http,
    )

    app, _ = await _make_app(
        sessionmaker_override,
        force_llm_trace_all=True,
        tool_selector_openai_base_url="http://fake-selector",
        openai_api_key="test-key",
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Check machine 5 status", "mode": "normal"},
        )
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        assert created.json()["created_by"] == "planner_owned_agent_graph"

    session_row = await db_session.get(Session, session_id)
    assert called["count"] == 1
    assert session_row.llm_call_count == 1
    trace = (session_row.replan_context or {})["intent_contract"]["execution_trace"]
    assert trace["generated_by"] == "planner_owned_agent_graph"
    assert trace["tool_retrieval"]["reranker"]["call_count"] == 1
    assert "get__machines_{id}" in trace["tool_retrieval"]["selected_candidate_tool_names"]


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

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key, extra_headers=None):
        del settings, tool, idempotency_key, extra_headers
        return {
            "ok": True,
            "http_status": 200,
            "body": {"data": {"machine_id": str(args.get("id") or "5"), "status": "RUNNING"}},
            "latency_ms": 1,
            "infrastructure_error": False,
        }

    monkeypatch.setattr(
        "factory_agent.planning.v2_graph_adapters._default_http_executor",
        fake_execute_tool_http,
    )

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
async def test_late_plan_or_execute_after_cancel_does_not_revive_session(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Session

    await _seed_session_plan_with_steps(
        db_session,
        session_id="sess-cancel-late",
        plan_id="plan-cancel-late",
        plan_hash="hash-cancel-late",
        plan_version=1,
        steps=[
            {"step_index": 0, "tool_name": "get__machines", "args": {}, "status": "NOT_STARTED"},
        ],
    )

    app, _ = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        cancel = await client.post("/sessions/sess-cancel-late/cancel")
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "IDLE"

        late_plan = await client.post("/sessions/sess-cancel-late/plans", json={})
        assert late_plan.status_code == 200
        assert late_plan.json()["status"] == "COMPLETED"

        late_execute = await client.post("/sessions/sess-cancel-late/execute?background=true", json={})
        assert late_execute.status_code == 200
        assert late_execute.json()["status"] == "IDLE"

    sess = await db_session.get(Session, "sess-cancel-late")
    assert sess.status == "IDLE"
    assert sess.error == "Cancelled"


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
        during_doc = during["response_document"]
        assert during_doc["revision_source"] == "event_seq"
        assert during_doc["revision"] >= 1
        assert during_doc["state"] == "running"
        assert "approval_required" not in {block["type"] for block in during_doc["blocks"]}
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
    final_doc = final_body["response_document"]
    assert final_doc["revision"] > during_doc["revision"]
    assert final_doc["state"] == "completed"
    assert "approval_required" not in {block["type"] for block in final_doc["blocks"]}
    assert not any(
        step["kind"] == "approval" and step["state"] in {"waiting", "current"}
        for step in final_doc["run_steps"]
    )
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


