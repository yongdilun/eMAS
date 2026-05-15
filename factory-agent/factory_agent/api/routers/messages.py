from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.response_mappers import message_to_response
from factory_agent.graph.session_detection import is_graph_native_session
from factory_agent.observability.events import AgentEvent, EventBus
from factory_agent.observability.telemetry import log_step_status_changed
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.schemas import MessageCreateRequest, MessageResponse


def build_messages_router(
    *,
    session_mgr: SessionManager,
    memory_manager: MemoryManager,
    event_bus: EventBus,
    require_jwt: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    async def _load_current_plan(*, db: AsyncSession, session_id: str) -> PlanRow | None:
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess or not sess.plan_id:
            return None
        return (await db.execute(select(PlanRow).where(PlanRow.plan_id == sess.plan_id))).scalars().first()

    def _session_duration_s(sess: SessionRow) -> int:
        if not sess.session_started_at:
            return 0
        return int((datetime.utcnow() - sess.session_started_at).total_seconds())

    def _log_step_status(sess: SessionRow, step: PlanStepRow, status: str) -> None:
        log_step_status_changed(
            session_id=sess.session_id,
            plan_id=sess.plan_id,
            plan_version=sess.plan_version,
            step_id=step.step_id,
            step_index=step.step_index,
            tool=step.tool_name,
            status=status,
            idempotency_key=step.idempotency_key,
            required_approval=bool(step.requires_approval),
            session_step_count=sess.step_count,
            session_llm_call_count=sess.llm_call_count,
            session_replan_count=sess.replan_count,
            session_duration_s=_session_duration_s(sess),
            user_id=sess.user_id,
        )

    @router.post("/sessions/{session_id}/messages", response_model=MessageResponse)
    async def add_message(
        session_id: str,
        req: MessageCreateRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        msg = await session_mgr.add_message(db, session_id=session_id, role=req.role, content=req.content, mode=req.mode)
        await memory_manager.index_message(
            db,
            session_id=session_id,
            message_id=msg.message_id,
            role=req.role,
            content=req.content,
        )
        if req.role == "user":
            sess.current_intent = req.content[:5000]
            lowered = req.content.strip().lower()
            current_plan = await _load_current_plan(db=db, session_id=session_id)
            is_langgraph = await is_graph_native_session(db, sess, plan=current_plan)
            if any(token in lowered for token in ("stop", "cancel", "don't do this", "do not do this")):
                if not is_langgraph:
                    step_rows = (
                        await db.execute(
                            select(PlanStepRow)
                            .where(PlanStepRow.session_id == session_id)
                            .order_by(PlanStepRow.step_index.asc())
                        )
                    ).scalars().all()
                    for step in step_rows:
                        if step.status == "DONE":
                            continue
                        if step.status not in ("SKIPPED", "FAILED", "AMBIGUOUS"):
                            step.status = "SKIPPED"
                            step.completed_at = step.completed_at or datetime.utcnow()
                            step.last_error = step.last_error or "Cancelled by user message"
                            _log_step_status(sess, step, step.status)
                else:
                    pending_graph_approvals = (
                        await db.execute(
                            select(ApprovalRow)
                            .where(ApprovalRow.session_id == session_id)
                            .where(ApprovalRow.subject_type == "graph")
                            .where(ApprovalRow.status == "PENDING")
                        )
                    ).scalars().all()
                    for ap in pending_graph_approvals:
                        ap.status = "REJECTED"
                        ap.decided_by = "system"
                        ap.decided_at = datetime.utcnow()
                        ap.rejection_reason = "Cancelled by user message"
                sess.status = "IDLE"
                sess.error = "Cancelled by user message"
                sess.pending_user_message = None
                sess.version += 1
                await event_bus.publish(
                    AgentEvent(
                        event_type="session_cancel",
                        session_id=session_id,
                        payload={},
                        published_at=datetime.utcnow(),
                    )
                )
            elif sess.status == "WAITING_APPROVAL":
                if current_plan and not current_plan.invalidated_at:
                    current_plan.invalidated_at = datetime.utcnow()
                    current_plan.invalidated_reason = "mid_execution_user_message"
                completed_steps: list[dict[str, Any]] = []
                if not is_langgraph:
                    steps = (
                        await db.execute(
                            select(PlanStepRow)
                            .where(PlanStepRow.plan_id == sess.plan_id)
                            .order_by(PlanStepRow.step_index.asc())
                        )
                    ).scalars().all()
                    completed_steps = [
                        {"step_index": s.step_index, "tool_name": s.tool_name, "args": s.args, "result": s.result}
                        for s in steps
                        if s.status == "DONE"
                    ]
                else:
                    pending_graph_approvals = (
                        await db.execute(
                            select(ApprovalRow)
                            .where(ApprovalRow.session_id == session_id)
                            .where(ApprovalRow.subject_type == "graph")
                            .where(ApprovalRow.status == "PENDING")
                        )
                    ).scalars().all()
                    for ap in pending_graph_approvals:
                        ap.status = "REJECTED"
                        ap.decided_by = "system"
                        ap.decided_at = datetime.utcnow()
                        ap.rejection_reason = "Superseded by user message"
                sess.replan_count += 1
                sess.plan_version = (sess.plan_version or 0) + 1
                sess.replan_context = {
                    "original_intent": sess.current_intent,
                    "plan_id": sess.plan_id,
                    "plan_version": sess.plan_version,
                    "completed_steps": completed_steps,
                    "error": "mid_execution_user_message",
                    "user_message": req.content,
                }
                sess.status = "PLANNING"
                sess.error = "Replan requested from user message"
                sess.pending_user_message = None
                sess.version += 1
            elif sess.status == "EXECUTING":
                sess.pending_user_message = req.content[:5000]
                sess.version += 1
            await db.commit()
        return message_to_response(msg)

    @router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
    async def list_messages(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        rows = (
            await db.execute(
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .order_by(MessageRow.created_at.asc())
            )
        ).scalars().all()
        return [message_to_response(row) for row in rows]

    return router
