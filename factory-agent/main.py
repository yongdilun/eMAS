import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, inspect, select, text

import factory_agent.persistence.models as models  # noqa: F401 (ensure models are imported for SQLAlchemy metadata)
from factory_agent.persistence.database import AsyncSessionLocal, Base, engine
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import DeadLetter as DeadLetterRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.persistence.models import Tool as ToolRow
from factory_agent.persistence.models import generate_uuid

from factory_agent.api import build_router
from factory_agent.config import get_settings
from factory_agent.graph.session_detection import is_graph_native_session
from factory_agent.observability.events import AgentEvent, EventBus
from factory_agent.orchestration.execution import ExecutionEngine
from factory_agent.observability.metrics import metrics
from factory_agent.observability.telemetry import log_event, log_step_status_changed, setup_logging
from factory_agent.registry.tool_registry import ToolRegistry


def _ensure_schema_compatibility(sync_conn) -> None:
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if "sessions" not in tables:
        return

    def ensure_column(table: str, column_name: str, ddl: str) -> None:
        if table not in tables:
            return
        columns = {column["name"] for column in inspector.get_columns(table)}
        if column_name not in columns:
            sync_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column_name} {ddl}")

    ensure_column("sessions", "name", "VARCHAR(255)")
    ensure_column("messages", "mode", "VARCHAR(20) NOT NULL DEFAULT 'normal'")
    ensure_column("plans", "kind", "VARCHAR(20) NOT NULL DEFAULT 'execution'")
    ensure_column("plans", "status", "VARCHAR(30) NOT NULL DEFAULT 'DRAFT'")
    ensure_column("plans", "approved_plan_hash", "VARCHAR(255)")
    ensure_column("plans", "derived_from_plan_id", "VARCHAR(36)")
    ensure_column("plan_steps", "bindings", "JSON")
    ensure_column("plan_steps", "execution_mode", "VARCHAR(20) NOT NULL DEFAULT 'single'")
    ensure_column("plan_steps", "bulk_state", "JSON")
    ensure_column("approvals", "subject_type", "VARCHAR(20) NOT NULL DEFAULT 'step'")
    ensure_column("approvals", "plan_id", "VARCHAR(36)")

    # MySQL: older schemas used VARCHAR(1000) for capability_tags; toolgen can emit longer JSON.
    if "tools" in tables and getattr(sync_conn.dialect, "name", "") == "mysql":
        with contextlib.suppress(Exception):
            sync_conn.execute(text("ALTER TABLE tools MODIFY capability_tags TEXT NOT NULL"))


async def _is_graph_native_session(db, session: SessionRow | None) -> bool:
    return await is_graph_native_session(db, session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    tool_registry = ToolRegistry()
    event_bus = EventBus(redis_url=settings.redis_url)
    setattr(event_bus, "_fault_injected", False)
    executor = ExecutionEngine(settings, event_bus)

    session_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.session_queue_size)
    queued_sessions: set[str] = set()
    inflight_sessions: set[str] = set()
    queue_lock = asyncio.Lock()
    worker_tasks: list[asyncio.Task] = []
    busy_workers = 0
    listener_task: asyncio.Task | None = None

    # Create DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_schema_compatibility)

    # Connect Redis (best-effort)
    try:
        await event_bus.connect()
    except Exception:
        pass

    async with AsyncSessionLocal() as db:
        await tool_registry.load_from_db(db)

    async def refresh_operational_gauges(db) -> None:
        active_count = (
            await db.execute(
                select(func.count())
                .select_from(SessionRow)
                .where(SessionRow.status.in_(("PLANNING", "EXECUTING", "WAITING_APPROVAL", "BLOCKED")))
            )
        ).scalar_one()
        pending_approvals = (
            await db.execute(select(func.count()).select_from(ApprovalRow).where(ApprovalRow.status == "PENDING"))
        ).scalar_one()
        pending_dlq = (
            await db.execute(select(func.count()).select_from(DeadLetterRow).where(DeadLetterRow.status == "PENDING"))
        ).scalar_one()
        ambiguous_steps = (
            await db.execute(select(func.count()).select_from(PlanStepRow).where(PlanStepRow.status == "AMBIGUOUS"))
        ).scalar_one()

        metrics.set_gauge("active_sessions", float(active_count))
        metrics.set_gauge("pending_approvals", float(pending_approvals))
        metrics.set_gauge("dlq_pending_count", float(pending_dlq))
        metrics.set_gauge("ambiguous_step_count", float(ambiguous_steps))
        metrics.set_gauge("session_queue_depth", float(session_queue.qsize()))
        utilization = 0.0 if settings.worker_count <= 0 else float(busy_workers) / float(settings.worker_count)
        metrics.set_gauge("worker_pool_utilization", utilization)
        metrics.set_gauge("redis_event_queue_depth", -1.0 if not settings.redis_url else 0.0)
        pool = engine.sync_engine.pool
        checked_out = float(pool.checkedout()) if hasattr(pool, "checkedout") else 0.0
        size = float(pool.size()) if hasattr(pool, "size") else 0.0
        db_usage = (checked_out / size) if size > 0 else 0.0
        metrics.set_gauge("db_connection_pool_usage", db_usage)

    async def enqueue_session(session_id: str) -> None:
        async with queue_lock:
            if session_id in queued_sessions or session_id in inflight_sessions:
                metrics.inc("sessions_rejected_429_total", labels={"reason": "duplicate_session"})
                raise RuntimeError(f"session already queued or in progress: {session_id}")
            try:
                session_queue.put_nowait(session_id)
            except asyncio.QueueFull as e:
                metrics.inc("sessions_rejected_429_total", labels={"reason": "queue_full"})
                raise RuntimeError("session queue full") from e
            queued_sessions.add(session_id)
            metrics.set_gauge("session_queue_depth", float(session_queue.qsize()))

    async def worker_loop(worker_id: int) -> None:
        nonlocal busy_workers
        while True:
            session_id = await session_queue.get()
            async with queue_lock:
                queued_sessions.discard(session_id)
                inflight_sessions.add(session_id)
            busy_workers += 1
            metrics.set_gauge("worker_pool_utilization", float(busy_workers) / float(max(settings.worker_count, 1)))
            metrics.set_gauge("session_queue_depth", float(session_queue.qsize()))
            try:
                async with AsyncSessionLocal() as db:
                    session = (
                        await db.execute(select(SessionRow).where(SessionRow.session_id == session_id))
                    ).scalars().first()
                    if not session:
                        continue
                    if settings.redis_url and not event_bus.healthy:
                        session.status = "BLOCKED"
                        session.error = "Redis unavailable - execution paused"
                        session.updated_at = datetime.utcnow()
                        await db.commit()
                        await refresh_operational_gauges(db)
                        continue
                    if await _is_graph_native_session(db, session):
                        log_event(
                            "worker_skipped_graph_native_session",
                            session_id=session.session_id,
                            status=session.status,
                        )
                        await refresh_operational_gauges(db)
                        continue
                    tools_by_name = await tool_registry.get_tools_by_name(db)
                    try:
                        await executor.execute_until_blocked(db, session=session, tools_by_name=tools_by_name)
                    except Exception as e:
                        session.status = "BLOCKED"
                        session.error = f"Worker execution error: {e}"
                        session.updated_at = datetime.utcnow()
                        await db.commit()
                        log_event(
                            "worker_session_error",
                            level="ERROR",
                            worker_id=worker_id,
                            session_id=session_id,
                            error=str(e),
                        )
                    await refresh_operational_gauges(db)
            finally:
                async with queue_lock:
                    inflight_sessions.discard(session_id)
                busy_workers = max(0, busy_workers - 1)
                metrics.set_gauge("worker_pool_utilization", float(busy_workers) / float(max(settings.worker_count, 1)))
                session_queue.task_done()
                metrics.set_gauge("session_queue_depth", float(session_queue.qsize()))

    async def cold_start_recovery_sweep() -> None:
        async with AsyncSessionLocal() as db:
            stuck_sessions = (
                await db.execute(
                    select(SessionRow).where(SessionRow.status.in_(("EXECUTING", "PLANNING", "WAITING_APPROVAL")))
                )
            ).scalars().all()
            recovered_count = 0
            for session in stuck_sessions:
                if await _is_graph_native_session(db, session):
                    log_event(
                        "cold_start_skipped_graph_native_session",
                        session_id=session.session_id,
                        status=session.status,
                    )
                    continue
                if not session.plan_id:
                    session.status = "FAILED"
                    session.error = "Recovered from cold start without plan"
                    continue

                in_progress_steps = (
                    await db.execute(
                        select(PlanStepRow)
                        .where(PlanStepRow.session_id == session.session_id)
                        .where(PlanStepRow.status == "IN_PROGRESS")
                    )
                ).scalars().all()

                blocked_by_ambiguous = False
                for step in in_progress_steps:
                    tool = (
                        await db.execute(select(ToolRow).where(ToolRow.name == step.tool_name))
                    ).scalars().first()
                    strongly_idempotent = bool(tool and tool.is_strongly_idempotent)
                    if strongly_idempotent:
                        step.status = "NOT_STARTED"
                        step.started_at = None
                        step.last_error = "Recovered from cold start (idempotent step reset)"
                        log_step_status_changed(
                            session_id=session.session_id,
                            plan_id=session.plan_id,
                            plan_version=session.plan_version,
                            step_id=step.step_id,
                            step_index=step.step_index,
                            tool=step.tool_name,
                            status=step.status,
                            idempotency_key=step.idempotency_key,
                            is_strongly_idempotent=True,
                            required_approval=bool(step.requires_approval),
                            session_step_count=session.step_count,
                            session_llm_call_count=session.llm_call_count,
                            session_replan_count=session.replan_count,
                            session_duration_s=0,
                            user_id=session.user_id,
                        )
                    else:
                        step.status = "AMBIGUOUS"
                        step.last_error = "Recovered from cold start (non-idempotent in-progress step)"
                        blocked_by_ambiguous = True
                        dlq = DeadLetterRow(
                            dlq_id=generate_uuid(),
                            session_id=session.session_id,
                            step_id=step.step_id,
                            failure_type="ambiguous_execution",
                            reason="Cold-start recovery found non-idempotent IN_PROGRESS step",
                            payload={"tool": step.tool_name, "step_index": step.step_index, "recovery": "cold_start"},
                            status="PENDING",
                        )
                        db.add(dlq)
                        metrics.inc("dlq_push_total", labels={"failure_type": "ambiguous_execution"})
                        metrics.inc("dlq_push_rate", labels={"failure_type": "ambiguous_execution"})
                        log_step_status_changed(
                            session_id=session.session_id,
                            plan_id=session.plan_id,
                            plan_version=session.plan_version,
                            step_id=step.step_id,
                            step_index=step.step_index,
                            tool=step.tool_name,
                            status=step.status,
                            idempotency_key=step.idempotency_key,
                            is_strongly_idempotent=False,
                            required_approval=bool(step.requires_approval),
                            session_step_count=session.step_count,
                            session_llm_call_count=session.llm_call_count,
                            session_replan_count=session.replan_count,
                            session_duration_s=0,
                            user_id=session.user_id,
                        )

                if session.status == "WAITING_APPROVAL":
                    waiting_step = (
                        await db.execute(
                            select(PlanStepRow)
                            .where(PlanStepRow.session_id == session.session_id)
                            .where(PlanStepRow.approval_id.is_not(None))
                            .where(PlanStepRow.status.in_(("NOT_STARTED", "IN_PROGRESS")))
                            .order_by(PlanStepRow.step_index.asc())
                        )
                    ).scalars().first()
                    if waiting_step and waiting_step.approval_id:
                        approval = (
                            await db.execute(
                                select(ApprovalRow).where(ApprovalRow.approval_id == waiting_step.approval_id)
                            )
                        ).scalars().first()
                        if approval and approval.status == "APPROVED":
                            waiting_step.status = "NOT_STARTED"
                            waiting_step.started_at = None
                            waiting_step.last_error = None
                            log_step_status_changed(
                                session_id=session.session_id,
                                plan_id=session.plan_id,
                                plan_version=session.plan_version,
                                step_id=waiting_step.step_id,
                                step_index=waiting_step.step_index,
                                tool=waiting_step.tool_name,
                                status=waiting_step.status,
                                idempotency_key=waiting_step.idempotency_key,
                                required_approval=True,
                                session_step_count=session.step_count,
                                session_llm_call_count=session.llm_call_count,
                                session_replan_count=session.replan_count,
                                session_duration_s=0,
                                user_id=session.user_id,
                            )
                            session.status = "EXECUTING"
                            session.error = None
                            recovered_count += 1
                        elif approval and approval.status == "REJECTED":
                            waiting_step.status = "SKIPPED"
                            waiting_step.last_error = approval.rejection_reason or "Rejected while server was down"
                            waiting_step.completed_at = waiting_step.completed_at or datetime.utcnow()
                            session.status = "IDLE"
                            session.error = waiting_step.last_error
                            log_step_status_changed(
                                session_id=session.session_id,
                                plan_id=session.plan_id,
                                plan_version=session.plan_version,
                                step_id=waiting_step.step_id,
                                step_index=waiting_step.step_index,
                                tool=waiting_step.tool_name,
                                status=waiting_step.status,
                                idempotency_key=waiting_step.idempotency_key,
                                required_approval=True,
                                session_step_count=session.step_count,
                                session_llm_call_count=session.llm_call_count,
                                session_replan_count=session.replan_count,
                                session_duration_s=0,
                                user_id=session.user_id,
                            )
                elif blocked_by_ambiguous:
                    session.status = "BLOCKED"
                    session.error = "Cold-start recovery requires operator review"
                else:
                    session.status = "EXECUTING"
                    session.error = None
                    recovered_count += 1
                session.updated_at = datetime.utcnow()
            await db.commit()
            for session in stuck_sessions:
                if session.status == "EXECUTING" and not await _is_graph_native_session(db, session):
                    with contextlib.suppress(Exception):
                        await enqueue_session(session.session_id)
            await refresh_operational_gauges(db)
            log_event("cold_start_recovery_sweep", recovered_sessions=recovered_count)

    async def reconcile_stuck_in_progress_steps() -> None:
        while True:
            await asyncio.sleep(10)
            cutoff = datetime.utcnow() - timedelta(seconds=45)
            async with AsyncSessionLocal() as db:
                stuck_steps = (
                    await db.execute(
                        select(PlanStepRow)
                        .where(PlanStepRow.status == "IN_PROGRESS")
                        .where(PlanStepRow.started_at.is_not(None))
                        .where(PlanStepRow.started_at < cutoff)
                    )
                ).scalars().all()
                if not stuck_steps:
                    continue
                for step in stuck_steps:
                    session = (
                        await db.execute(select(SessionRow).where(SessionRow.session_id == step.session_id))
                    ).scalars().first()
                    if not session:
                        continue
                    if await _is_graph_native_session(db, session):
                        continue
                    tool = (
                        await db.execute(select(ToolRow).where(ToolRow.name == step.tool_name))
                    ).scalars().first()
                    strongly_idempotent = bool(tool and tool.is_strongly_idempotent)
                    if strongly_idempotent:
                        step.status = "NOT_STARTED"
                        step.started_at = None
                        step.last_error = "Recovered from stale IN_PROGRESS step"
                        session.status = "EXECUTING"
                        session.error = None
                        session.current_step_index = min(session.current_step_index or 0, step.step_index)
                    else:
                        step.status = "AMBIGUOUS"
                        step.last_error = "Stale non-idempotent IN_PROGRESS step requires operator review"
                        session.status = "BLOCKED"
                        session.error = "Stale non-idempotent IN_PROGRESS step"
                        db.add(
                            DeadLetterRow(
                                dlq_id=generate_uuid(),
                                session_id=session.session_id,
                                step_id=step.step_id,
                                failure_type="ambiguous_execution",
                                reason="Stale non-idempotent IN_PROGRESS step",
                                payload={"tool": step.tool_name, "step_index": step.step_index, "recovery": "stuck_step"},
                                status="PENDING",
                            )
                        )
                        metrics.inc("dlq_push_total", labels={"failure_type": "ambiguous_execution"})
                        metrics.inc("dlq_push_rate", labels={"failure_type": "ambiguous_execution"})
                    session.updated_at = datetime.utcnow()
                await db.commit()
                for step in stuck_steps:
                    if step.status == "NOT_STARTED":
                        with contextlib.suppress(Exception):
                            await enqueue_session(step.session_id)
                await refresh_operational_gauges(db)
                log_event("stuck_step_reconciliation", recovered=len(stuck_steps))

    async def redis_health_monitor() -> None:
        nonlocal listener_task
        redis_was_healthy = event_bus.healthy
        while True:
            await asyncio.sleep(2)
            if not settings.redis_url:
                continue
            if getattr(event_bus, "_fault_injected", False):
                healthy = False
                event_bus._healthy = False
            else:
                healthy = await event_bus.ping()
                if not healthy:
                    healthy = await event_bus.reconnect()
            metrics.set_gauge("redis_event_queue_depth", 0.0 if healthy else -1.0)

            if healthy:
                if listener_task is None or listener_task.done():
                    listener_task = asyncio.create_task(event_bus.listen(handle_event))
                async with AsyncSessionLocal() as db:
                    paused_sessions = (
                        await db.execute(
                            select(SessionRow)
                            .where(SessionRow.status == "BLOCKED")
                            .where(SessionRow.error == "Redis unavailable - execution paused")
                        )
                    ).scalars().all()
                    if paused_sessions:
                        for paused in paused_sessions:
                            paused.status = "EXECUTING"
                            paused.error = None
                            paused.updated_at = datetime.utcnow()
                        await db.commit()
                        for paused in paused_sessions:
                            with contextlib.suppress(Exception):
                                await enqueue_session(paused.session_id)
                        await refresh_operational_gauges(db)
                        log_event("redis_recovered", resumed_sessions=len(paused_sessions))
                    elif not redis_was_healthy:
                        log_event("redis_recovered", resumed_sessions=0)

            if (not healthy) and redis_was_healthy:
                log_event("redis_unavailable", level="WARNING")

            redis_was_healthy = healthy

    for i in range(max(0, settings.worker_count)):
        worker_tasks.append(asyncio.create_task(worker_loop(i)))

    await cold_start_recovery_sweep()

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
                if await _is_graph_native_session(db, session):
                    await refresh_operational_gauges(db)
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
                        log_step_status_changed(
                            session_id=session.session_id,
                            plan_id=session.plan_id,
                            plan_version=session.plan_version,
                            step_id=step.step_id,
                            step_index=step.step_index,
                            tool=step.tool_name,
                            status=step.status,
                            idempotency_key=step.idempotency_key,
                            required_approval=bool(step.requires_approval),
                            session_step_count=session.step_count,
                            session_llm_call_count=session.llm_call_count,
                            session_replan_count=session.replan_count,
                            session_duration_s=0,
                            user_id=session.user_id,
                        )
                    session.status = "IDLE"
                    session.error = approval.rejection_reason or f"Approval {approval_id} rejected"
                    session.updated_at = datetime.utcnow()
                await db.commit()
                if approval.status == "APPROVED":
                    with contextlib.suppress(Exception):
                        await enqueue_session(session.session_id)
                await refresh_operational_gauges(db)
                return

            if event.event_type == "session_cancel":
                session = (
                    await db.execute(select(SessionRow).where(SessionRow.session_id == event.session_id))
                ).scalars().first()
                if not session:
                    return
                if await _is_graph_native_session(db, session):
                    await refresh_operational_gauges(db)
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
                        log_step_status_changed(
                            session_id=session.session_id,
                            plan_id=session.plan_id,
                            plan_version=session.plan_version,
                            step_id=step.step_id,
                            step_index=step.step_index,
                            tool=step.tool_name,
                            status=step.status,
                            idempotency_key=step.idempotency_key,
                            required_approval=bool(step.requires_approval),
                            session_step_count=session.step_count,
                            session_llm_call_count=session.llm_call_count,
                            session_replan_count=session.replan_count,
                            session_duration_s=0,
                            user_id=session.user_id,
                        )
                session.status = "IDLE"
                session.error = "Cancelled"
                session.updated_at = datetime.utcnow()
                await db.commit()
                await refresh_operational_gauges(db)
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
                session = (
                    await db.execute(select(SessionRow).where(SessionRow.session_id == dlq.session_id))
                ).scalars().first()
                if session and await _is_graph_native_session(db, session):
                    await refresh_operational_gauges(db)
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
                        session_for_log = (
                            await db.execute(select(SessionRow).where(SessionRow.session_id == dlq.session_id))
                        ).scalars().first()
                        if session_for_log:
                            log_step_status_changed(
                                session_id=session_for_log.session_id,
                                plan_id=session_for_log.plan_id,
                                plan_version=session_for_log.plan_version,
                                step_id=step.step_id,
                                step_index=step.step_index,
                                tool=step.tool_name,
                                status=step.status,
                                idempotency_key=step.idempotency_key,
                                required_approval=bool(step.requires_approval),
                                session_step_count=session_for_log.step_count,
                                session_llm_call_count=session_for_log.llm_call_count,
                                session_replan_count=session_for_log.replan_count,
                                session_duration_s=0,
                                user_id=session_for_log.user_id,
                            )
                dlq.status = "REPLAYED"
                dlq.replayed_at = dlq.replayed_at or datetime.utcnow()
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
                await refresh_operational_gauges(db)
                return

    redis_monitor_task: asyncio.Task | None = None
    stuck_step_task: asyncio.Task | None = None
    if settings.redis_url:
        listener_task = asyncio.create_task(event_bus.listen(handle_event))
        redis_monitor_task = asyncio.create_task(redis_health_monitor())
    stuck_step_task = asyncio.create_task(reconcile_stuck_in_progress_steps())

    app.state.settings = settings
    app.state.tool_registry = tool_registry
    app.state.event_bus = event_bus
    app.state.redis_fault_injected = False

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
    log_event("agent_server_started", worker_count=settings.worker_count, session_queue_size=settings.session_queue_size)

    yield

    if listener_task:
        listener_task.cancel()
        with contextlib.suppress(Exception):
            await listener_task
    if redis_monitor_task:
        redis_monitor_task.cancel()
        with contextlib.suppress(Exception):
            await redis_monitor_task
    if stuck_step_task:
        stuck_step_task.cancel()
        with contextlib.suppress(Exception):
            await stuck_step_task
    for t in worker_tasks:
        t.cancel()
    for t in worker_tasks:
        with contextlib.suppress(Exception):
            await t
    await event_bus.close()
    log_event("agent_server_stopped")


app = FastAPI(lifespan=lifespan)

# Allow browser preflight requests from local frontend dev servers.
cors_origins_raw = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "http://127.0.0.1:4173,http://localhost:4173,http://127.0.0.1:5173,http://localhost:5173",
)
cors_allow_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/_mock/slow")
async def mock_slow(ms: int = 1000):
    await asyncio.sleep(max(0, min(ms, 15000)) / 1000.0)
    return {"ok": True, "slept_ms": ms}
