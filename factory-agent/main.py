import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from sqlalchemy import select

import models  # noqa: F401 (ensure models are imported for SQLAlchemy metadata)
from database import AsyncSessionLocal, Base, engine
from models import Approval as ApprovalRow
from models import DeadLetter as DeadLetterRow
from models import PlanStep as PlanStepRow
from models import Session as SessionRow

from agent.api import build_router
from agent.config import get_settings
from agent.events import AgentEvent, EventBus
from agent.execution import ExecutionEngine
from agent.tool_registry import ToolRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    tool_registry = ToolRegistry()
    event_bus = EventBus(redis_url=settings.redis_url)
    executor = ExecutionEngine(settings, event_bus)

    session_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.session_queue_size)
    worker_tasks: list[asyncio.Task] = []

    # Create DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Connect Redis (best-effort)
    try:
        await event_bus.connect()
    except Exception:
        pass

    async def enqueue_session(session_id: str) -> None:
        session_queue.put_nowait(session_id)

    async def worker_loop(worker_id: int) -> None:
        while True:
            session_id = await session_queue.get()
            try:
                async with AsyncSessionLocal() as db:
                    session = (
                        await db.execute(select(SessionRow).where(SessionRow.session_id == session_id))
                    ).scalars().first()
                    if not session:
                        continue
                    tools_by_name = await tool_registry.get_tools_by_name(db)
                    await executor.execute_until_blocked(db, session=session, tools_by_name=tools_by_name)
            finally:
                session_queue.task_done()

    for i in range(max(0, settings.worker_count)):
        worker_tasks.append(asyncio.create_task(worker_loop(i)))

    async def handle_event(event: AgentEvent) -> None:
        async with AsyncSessionLocal() as db:
            if event.event_type == "approval_decided":
                approval_id = event.payload.get("approval_id")
                if not approval_id:
                    return
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
                else:
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
                if approval.status == "APPROVED":
                    with contextlib.suppress(Exception):
                        await enqueue_session(session.session_id)
                return

            if event.event_type == "session_cancel":
                session = (
                    await db.execute(select(SessionRow).where(SessionRow.session_id == event.session_id))
                ).scalars().first()
                if not session:
                    return
                steps = (
                    await db.execute(
                        select(PlanStepRow)
                        .where(PlanStepRow.session_id == session.session_id)
                        .order_by(PlanStepRow.step_index.asc())
                    )
                ).scalars().all()
                for step in steps:
                    if step.status == "DONE":
                        continue
                    if step.status not in ("SKIPPED", "FAILED", "AMBIGUOUS"):
                        step.status = "SKIPPED"
                        step.completed_at = step.completed_at or datetime.utcnow()
                        step.last_error = step.last_error or "Cancelled"
                session.status = "IDLE"
                session.error = "Cancelled"
                session.updated_at = datetime.utcnow()
                await db.commit()
                return

            if event.event_type == "dlq_replay_requested":
                dlq_id = event.payload.get("dlq_id")
                if not dlq_id:
                    return
                dlq = (
                    await db.execute(select(DeadLetterRow).where(DeadLetterRow.dlq_id == dlq_id))
                ).scalars().first()
                if not dlq:
                    return
                if dlq.step_id:
                    step = (
                        await db.execute(select(PlanStepRow).where(PlanStepRow.step_id == dlq.step_id))
                    ).scalars().first()
                    if step:
                        step.status = "NOT_STARTED"
                        step.last_error = None
                        step.started_at = None
                        step.completed_at = None
                        step.retry_count = 0
                dlq.status = "REPLAYED"
                dlq.replayed_at = dlq.replayed_at or datetime.utcnow()
                session = (
                    await db.execute(select(SessionRow).where(SessionRow.session_id == dlq.session_id))
                ).scalars().first()
                if session:
                    if dlq.step_id:
                        step = (
                            await db.execute(select(PlanStepRow).where(PlanStepRow.step_id == dlq.step_id))
                        ).scalars().first()
                        if step is not None:
                            session.current_step_index = min(session.current_step_index or 0, step.step_index)
                    session.status = "EXECUTING"
                    session.error = None
                await db.commit()
                if session:
                    with contextlib.suppress(Exception):
                        await enqueue_session(session.session_id)
                return

    listener_task: asyncio.Task | None = None
    if settings.redis_url:
        listener_task = asyncio.create_task(event_bus.listen(handle_event))

    app.state.settings = settings
    app.state.tool_registry = tool_registry
    app.state.event_bus = event_bus

    app.state.session_queue = session_queue
    app.state.worker_tasks = worker_tasks

    app.include_router(
        build_router(
            settings=settings,
            tool_registry=tool_registry,
            event_bus=event_bus,
            enqueue_session=enqueue_session,
        )
    )

    yield

    if listener_task:
        listener_task.cancel()
        with contextlib.suppress(Exception):
            await listener_task
    for t in worker_tasks:
        t.cancel()
    for t in worker_tasks:
        with contextlib.suppress(Exception):
            await t
    await event_bus.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
