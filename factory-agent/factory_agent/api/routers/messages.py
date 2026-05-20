from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.dependencies import require_session_owner
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
from factory_agent.planning.v2_interrupts import (
    apply_user_interrupt_to_context,
    classify_user_interrupt,
    revised_goal_for_interrupt,
)
from factory_agent.schemas import MessageCreateRequest, MessageResponse
from factory_agent.services.plan_creation_service import _bump_session_revision
from factory_agent.session_state import USER_CANCELLED_MESSAGE


_CANCEL_COMMAND_RE = re.compile(
    r"^\s*(?:"
    r"stop\b.*|"
    r"cancel(?:\s+(?:the\s+)?(?:current\s+)?(?:run|request|session|operation|job|it|this))?\b.*|"
    r"don't\s+do\s+this\b.*|"
    r"do\s+not\s+do\s+this\b.*"
    r")$",
    re.IGNORECASE,
)


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
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(sess, user)
        msg = await session_mgr.add_message(db, session_id=session_id, role=req.role, content=req.content, mode=req.mode)
        await memory_manager.index_message(
            db,
            session_id=session_id,
            message_id=msg.message_id,
            role=req.role,
            content=req.content,
        )
        if req.role == "user":
            previous_intent = str(sess.current_intent or "")
            user_message = req.content[:5000]
            lowered = req.content.strip().lower()
            current_plan = await _load_current_plan(db=db, session_id=session_id)
            is_langgraph = await is_graph_native_session(db, sess, plan=current_plan)
            if _CANCEL_COMMAND_RE.match(lowered):
                interrupt = classify_user_interrupt(
                    user_message,
                    session_status=sess.status,
                    previous_goal=previous_intent,
                )
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
                            step.last_error = step.last_error or USER_CANCELLED_MESSAGE
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
                        ap.rejection_reason = USER_CANCELLED_MESSAGE
                    context = apply_user_interrupt_to_context(
                        sess.replan_context if isinstance(sess.replan_context, dict) else None,
                        interrupt,
                        previous_status=sess.status,
                        revised_goal=previous_intent,
                    )
                    context.pop("langgraph_pending_approval", None)
                    context.pop("langgraph_approval_resume", None)
                    sess.replan_context = context
                sess.status = "IDLE"
                sess.error = USER_CANCELLED_MESSAGE
                sess.pending_user_message = None
                _bump_session_revision(sess)
                await event_bus.publish(
                    AgentEvent(
                        event_type="session_cancel",
                        session_id=session_id,
                        payload={},
                        published_at=datetime.utcnow(),
                    )
                )
            elif sess.status == "WAITING_APPROVAL":
                pending_approval_id: str | None = None
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
                        pending_approval_id = pending_approval_id or ap.approval_id
                        ap.status = "REJECTED"
                        ap.decided_by = "system"
                        ap.decided_at = datetime.utcnow()
                        ap.rejection_reason = "Superseded by user message"
                interrupt = classify_user_interrupt(
                    user_message,
                    session_status=sess.status,
                    awaiting_approval=True,
                    previous_goal=previous_intent,
                    approval_id=pending_approval_id,
                )
                revised_goal = revised_goal_for_interrupt(previous_intent, interrupt)
                context = apply_user_interrupt_to_context(
                    sess.replan_context if isinstance(sess.replan_context, dict) else None,
                    interrupt,
                    previous_status="WAITING_APPROVAL",
                    revised_goal=revised_goal,
                )
                context.pop("langgraph_pending_approval", None)
                context.pop("langgraph_approval_resume", None)
                context["mid_execution_replan"] = {
                    "original_intent": previous_intent,
                    "plan_id": sess.plan_id,
                    "completed_steps": completed_steps,
                    "error": "mid_execution_user_message",
                    "user_message": req.content,
                    "interrupt_type": interrupt.interrupt_type,
                }
                sess.replan_count += 1
                sess.plan_version = (sess.plan_version or 0) + 1
                context["mid_execution_replan"]["plan_version"] = sess.plan_version
                sess.replan_context = context
                sess.current_intent = revised_goal[:5000]
                sess.status = "PLANNING"
                sess.error = "Replan requested from user message"
                sess.pending_user_message = None
                _bump_session_revision(sess)
            elif sess.status == "EXECUTING":
                interrupt = classify_user_interrupt(
                    user_message,
                    session_status=sess.status,
                    previous_goal=previous_intent,
                )
                revised_goal = revised_goal_for_interrupt(previous_intent, interrupt)
                context = apply_user_interrupt_to_context(
                    sess.replan_context if isinstance(sess.replan_context, dict) else None,
                    interrupt,
                    previous_status="EXECUTING",
                    revised_goal=revised_goal,
                )
                context["mid_execution_replan"] = {
                    "original_intent": previous_intent,
                    "plan_id": sess.plan_id,
                    "plan_version": (sess.plan_version or 0) + 1,
                    "completed_steps": [],
                    "error": "mid_execution_user_message",
                    "user_message": req.content,
                    "interrupt_type": interrupt.interrupt_type,
                    "checkpoint": "interrupt_replan",
                }
                context.pop("langgraph_pending_approval", None)
                context.pop("langgraph_approval_resume", None)
                sess.current_intent = revised_goal[:5000]
                sess.replan_context = context
                sess.replan_count += 1
                sess.plan_version = (sess.plan_version or 0) + 1
                sess.status = "PLANNING"
                sess.error = "Interrupted by user message; replan required"
                sess.pending_user_message = None
                _bump_session_revision(sess)
            elif sess.status in {"IDLE", "COMPLETED", "BLOCKED", "FAILED"}:
                sess.current_intent = user_message
                sess.status = "PLANNING"
                sess.error = None
                sess.completed_at = None
                sess.pending_user_message = None
                _bump_session_revision(sess)
            await db.commit()
        return message_to_response(msg)

    @router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
    async def list_messages(
        session_id: str,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(sess, user)
        rows = (
            await db.execute(
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .order_by(MessageRow.created_at.asc())
            )
        ).scalars().all()
        return [message_to_response(row) for row in rows]

    return router
