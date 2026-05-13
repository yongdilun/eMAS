import asyncio
import contextlib
import os
import time
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

pytestmark = pytest.mark.legacy_compatibility

LEGACY_COMPATIBILITY_SCOPE = (
    "This module covers legacy step-approval resume behavior for non-graph "
    "sessions. Graph approvals resume through LangGraph Command(resume=...) tests."
)

import database
from factory_agent.api import build_router
from factory_agent.config import Settings
from factory_agent.observability.events import AgentEvent, EventBus
from factory_agent.orchestration.execution import ExecutionEngine
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow


async def _seed_tool(
    db_session,
    *,
    name,
    endpoint,
    method,
    input_schema,
    capability_tags,
    is_read_only=True,
    requires_approval=False,
):
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


async def _make_app_with_worker_queue(sessionmaker_override, redis_url: str):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=redis_url,
        go_api_base_url="http://testserver",
        worker_count=1,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )
    tool_registry = ToolRegistry()
    event_bus = EventBus(redis_url=redis_url)
    await event_bus.connect()
    executor = ExecutionEngine(settings, event_bus)

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=10)

    async def enqueue_session(session_id: str) -> None:
        queue.put_nowait(session_id)

    async def worker_loop() -> None:
        while True:
            session_id = await queue.get()
            try:
                async with sessionmaker_override() as db:
                    session = (
                        await db.execute(select(SessionRow).where(SessionRow.session_id == session_id))
                    ).scalars().first()
                    if not session:
                        continue
                    tools_by_name = await tool_registry.get_tools_by_name(db)
                    await executor.execute_until_blocked(db, session=session, tools_by_name=tools_by_name)
            finally:
                queue.task_done()

    async def handle_event(event: AgentEvent) -> None:
        if event.event_type != "approval_decided":
            return
        approval_id = event.payload.get("approval_id")
        if not approval_id:
            return
        async with sessionmaker_override() as db:
            approval = (
                await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))
            ).scalars().first()
            if not approval:
                return
            session = (
                await db.execute(select(SessionRow).where(SessionRow.session_id == approval.session_id))
            ).scalars().first()
            if not session:
                return
            if approval.status == "APPROVED":
                session.status = "EXECUTING"
                session.updated_at = datetime.utcnow()
                await db.commit()
                with contextlib.suppress(Exception):
                    await enqueue_session(session.session_id)
                return
            step = (
                await db.execute(select(PlanStepRow).where(PlanStepRow.step_id == approval.step_id))
            ).scalars().first()
            if step and step.status not in ("DONE", "SKIPPED", "FAILED", "AMBIGUOUS"):
                step.status = "SKIPPED"
                step.completed_at = datetime.utcnow()
                step.last_error = approval.rejection_reason or f"Approval {approval_id} rejected"
            session.status = "IDLE"
            session.error = approval.rejection_reason or f"Approval {approval_id} rejected"
            session.updated_at = datetime.utcnow()
            await db.commit()

    worker_task = asyncio.create_task(worker_loop())
    listener_task = asyncio.create_task(event_bus.listen(handle_event))

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
        )
    )

    async def cleanup():
        listener_task.cancel()
        worker_task.cancel()
        with contextlib.suppress(BaseException):
            await listener_task
        with contextlib.suppress(BaseException):
            await worker_task
        await event_bus.close()

    return app, cleanup


async def _wait_for_status(client: httpx.AsyncClient, session_id: str, expected: str, timeout_s: float) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        res = await client.get(f"/sessions/{session_id}")
        if res.status_code == 200 and res.json().get("status") == expected:
            return res.json()
        await asyncio.sleep(0.1)
    raise AssertionError(f"Session {session_id} did not reach {expected} within {timeout_s}s")


@pytest.mark.asyncio
async def test_approval_approve_resumes_within_2s(sessionmaker_override, db_session, respx_mock):
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        pytest.skip("REDIS_URL not set")

    try:
        app, cleanup = await _make_app_with_worker_queue(sessionmaker_override, redis_url)
    except Exception as e:
        pytest.skip(f"Redis unavailable at {redis_url}: {e}")

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
    respx_mock.post("http://testserver/inventory").respond(200, json={"ok": True})

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
            await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "update inventory"})
            draft = {
                "plan_explanation": "Update inventory with approval",
                "risk_summary": "Writes inventory",
                "steps": [{"step_index": 0, "tool_name": "post__inventory_update", "args": {"id": 1}}],
            }
            created = await client.post(f"/sessions/{session_id}/plans", json={"draft": draft})
            assert created.status_code == 200

            execute = await client.post(f"/sessions/{session_id}/execute", params={"background": "true"})
            assert execute.status_code == 200

            await _wait_for_status(client, session_id, "WAITING_APPROVAL", timeout_s=2.0)
            pending = await client.get("/approvals/pending")
            assert pending.status_code == 200
            approval_id = pending.json()[0]["approval_id"]

            approved = await client.post(f"/approvals/{approval_id}/approve", json={"decided_by": "u1"})
            assert approved.status_code == 200

            await _wait_for_status(client, session_id, "COMPLETED", timeout_s=2.0)
    finally:
        await cleanup()


