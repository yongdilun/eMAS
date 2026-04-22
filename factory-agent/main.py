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
from models import Session as SessionRow

from agent.api import build_router
from agent.config import get_settings
from agent.events import AgentEvent, EventBus
from agent.tool_registry import ToolRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    tool_registry = ToolRegistry()
    event_bus = EventBus(redis_url=settings.redis_url)

    # Create DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Connect Redis (best-effort)
    try:
        await event_bus.connect()
    except Exception:
        pass

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
                    session.status = "FAILED"
                    session.error = f"Approval {approval_id} rejected"
                    session.updated_at = datetime.utcnow()
                await db.commit()
                return

            if event.event_type == "session_cancel":
                session = (
                    await db.execute(select(SessionRow).where(SessionRow.session_id == event.session_id))
                ).scalars().first()
                if not session:
                    return
                session.status = "FAILED"
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
                dlq.status = "REPLAY_REQUESTED"
                await db.commit()
                return

    listener_task: asyncio.Task | None = None
    if settings.redis_url:
        listener_task = asyncio.create_task(event_bus.listen(handle_event))

    app.state.settings = settings
    app.state.tool_registry = tool_registry
    app.state.event_bus = event_bus

    app.include_router(build_router(settings=settings, tool_registry=tool_registry, event_bus=event_bus))

    yield

    if listener_task:
        listener_task.cancel()
        with contextlib.suppress(Exception):
            await listener_task
    await event_bus.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
