from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Approval as ApprovalRow
from models import DeadLetter as DeadLetterRow
from models import Message as MessageRow
from models import Plan as PlanRow
from models import PlanStep as PlanStepRow
from models import Session as SessionRow
from models import generate_uuid

from .config import Settings
from .events import AgentEvent, EventBus
from .execution import ExecutionEngine, compute_idempotency_key
from .plan_validator import validate_plan
from .schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    DeadLetterResponse,
    MessageCreateRequest,
    MessageResponse,
    PlanCreateRequest,
    PlanResponse,
    SessionCreateRequest,
    SessionResponse,
    ValidationErrorResponse,
)
from .session_manager import SessionManager
from .tool_registry import ToolRegistry
from .tool_scope import filter_tools_for_intent


def _session_to_response(s: SessionRow) -> SessionResponse:
    return SessionResponse(
        session_id=s.session_id,
        user_id=s.user_id,
        status=s.status,
        current_intent=s.current_intent,
        plan_id=s.plan_id,
        plan_version=s.plan_version or 0,
        plan_hash=s.plan_hash,
        current_step_index=s.current_step_index or 0,
        step_count=s.step_count or 0,
        replan_count=s.replan_count or 0,
        llm_call_count=s.llm_call_count or 0,
        session_started_at=s.session_started_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
        completed_at=s.completed_at,
        error=s.error,
    )


def _message_to_response(m: MessageRow) -> MessageResponse:
    return MessageResponse(
        message_id=m.message_id,
        session_id=m.session_id,
        role=m.role,
        content=m.content,
        created_at=m.created_at,
        step_id=m.step_id,
        tool_name=m.tool_name,
    )


def _approval_to_response(a: ApprovalRow) -> ApprovalResponse:
    return ApprovalResponse(
        approval_id=a.approval_id,
        session_id=a.session_id,
        step_id=a.step_id,
        tool_name=a.tool_name,
        args=a.args,
        risk_summary=a.risk_summary,
        side_effect_level=a.side_effect_level,
        status=a.status,
        expires_at=a.expires_at,
        decided_by=a.decided_by,
        decided_at=a.decided_at,
        rejection_reason=a.rejection_reason,
        created_at=a.created_at,
    )


def build_router(*, settings: Settings, tool_registry: ToolRegistry, event_bus: EventBus) -> APIRouter:
    router = APIRouter()
    session_mgr = SessionManager(settings)
    executor = ExecutionEngine(settings, event_bus)

    @router.post("/sessions", response_model=SessionResponse)
    async def create_session(req: SessionCreateRequest, db: AsyncSession = Depends(get_db)):
        sess = await session_mgr.create_session(db, user_id=req.user_id)
        return _session_to_response(sess)

    @router.get("/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        return _session_to_response(sess)

    @router.post("/sessions/{session_id}/messages", response_model=MessageResponse)
    async def add_message(session_id: str, req: MessageCreateRequest, db: AsyncSession = Depends(get_db)):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        msg = await session_mgr.add_message(db, session_id=session_id, role=req.role, content=req.content)
        if req.role == "user":
            sess.current_intent = req.content[:5000]
            await db.commit()
        return _message_to_response(msg)

    @router.post(
        "/sessions/{session_id}/plans",
        response_model=PlanResponse,
        responses={400: {"model": ValidationErrorResponse}},
    )
    async def create_plan(session_id: str, req: PlanCreateRequest, db: AsyncSession = Depends(get_db)):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")

        tools_by_name = await tool_registry.get_tools_by_name(db)
        intent = sess.current_intent or ""
        scoped = filter_tools_for_intent(intent=intent, tools_by_name=tools_by_name)

        # Validate plan against full registry (schema correctness), but ensure steps use only scoped tools.
        invalid_scoped = [s.tool_name for s in req.draft.steps if s.tool_name not in scoped.tool_names]
        if invalid_scoped:
            raise HTTPException(status_code=400, detail={"errors": [f"Tool not allowed by scope: {t}" for t in invalid_scoped]})

        validation = validate_plan(req.draft, tools_by_name, max_steps=settings.max_plan_steps)
        if not validation.ok:
            raise HTTPException(status_code=400, detail={"errors": validation.errors})

        # Invalidate existing plan if any
        if sess.plan_id:
            existing = (
                await db.execute(select(PlanRow).where(PlanRow.plan_id == sess.plan_id))
            ).scalars().first()
            if existing and not existing.invalidated_at:
                existing.invalidated_at = datetime.utcnow()
                existing.invalidated_reason = "Replanned"
                sess.replan_count += 1

        plan_version = (sess.plan_version or 0) + 1
        plan_row = PlanRow(
            plan_id=generate_uuid(),
            session_id=session_id,
            version=plan_version,
            dependency_graph=validation.normalized_dependency_graph,
            parallel_groups=validation.normalized_parallel_groups,
            plan_hash=validation.plan_hash,
            plan_explanation=req.draft.plan_explanation,
            risk_summary=req.draft.risk_summary,
            created_at=datetime.utcnow(),
            created_by="llm",
        )
        db.add(plan_row)
        await db.commit()
        await db.refresh(plan_row)

        # Store steps
        for step in req.draft.steps:
            tool = tools_by_name.get(step.tool_name)
            step_row = PlanStepRow(
                step_id=generate_uuid(),
                plan_id=plan_row.plan_id,
                session_id=session_id,
                step_index=step.step_index,
                tool_name=step.tool_name,
                args=step.args,
                status="NOT_STARTED",
                idempotency_key=compute_idempotency_key(
                    session_id=session_id,
                    step_index=step.step_index,
                    plan_version=plan_version,
                    args=step.args,
                ),
                requires_approval=bool(tool.requires_approval) if tool else False,
                retry_count=0,
                max_retries=3,
            )
            db.add(step_row)
        await db.commit()

        # Attach plan to session
        sess.plan_id = plan_row.plan_id
        sess.plan_version = plan_version
        sess.plan_hash = plan_row.plan_hash
        sess.current_step_index = 0
        sess.status = "PLANNING"
        await db.commit()

        return PlanResponse(
            plan_id=plan_row.plan_id,
            session_id=plan_row.session_id,
            version=plan_row.version,
            dependency_graph=plan_row.dependency_graph,
            parallel_groups=plan_row.parallel_groups,
            plan_hash=plan_row.plan_hash,
            plan_explanation=plan_row.plan_explanation,
            risk_summary=plan_row.risk_summary,
            created_at=plan_row.created_at,
            created_by=plan_row.created_by,
        )

    @router.post("/sessions/{session_id}/execute", response_model=SessionResponse)
    async def execute(session_id: str, db: AsyncSession = Depends(get_db)):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        session_mgr.enforce_limits(sess)
        tools_by_name = await tool_registry.get_tools_by_name(db)
        await executor.execute_until_blocked(db, session=sess, tools_by_name=tools_by_name)
        # reload session for updated fields
        sess = await session_mgr.get_session(db, session_id=session_id)
        return _session_to_response(sess)

    @router.get("/approvals/pending", response_model=list[ApprovalResponse])
    async def list_pending_approvals(db: AsyncSession = Depends(get_db)):
        rows = (
            await db.execute(select(ApprovalRow).where(ApprovalRow.status == "PENDING").order_by(ApprovalRow.created_at.asc()))
        ).scalars().all()
        return [_approval_to_response(r) for r in rows]

    @router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
    async def get_approval(approval_id: str, db: AsyncSession = Depends(get_db)):
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        return _approval_to_response(row)

    @router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
    async def approve_approval(approval_id: str, req: ApprovalDecisionRequest, db: AsyncSession = Depends(get_db)):
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        row.status = "APPROVED"
        row.decided_by = req.decided_by
        row.decided_at = datetime.utcnow()
        await db.commit()
        await event_bus.publish(
            AgentEvent(
                event_type="approval_decided",
                session_id=row.session_id,
                payload={"approval_id": row.approval_id, "status": "APPROVED"},
                published_at=datetime.utcnow(),
            )
        )
        return _approval_to_response(row)

    @router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
    async def reject_approval(approval_id: str, req: ApprovalDecisionRequest, db: AsyncSession = Depends(get_db)):
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        row.status = "REJECTED"
        row.decided_by = req.decided_by
        row.decided_at = datetime.utcnow()
        row.rejection_reason = req.rejection_reason
        await db.commit()
        await event_bus.publish(
            AgentEvent(
                event_type="approval_decided",
                session_id=row.session_id,
                payload={"approval_id": row.approval_id, "status": "REJECTED"},
                published_at=datetime.utcnow(),
            )
        )
        return _approval_to_response(row)

    @router.get("/dlq", response_model=list[DeadLetterResponse])
    async def list_dlq(db: AsyncSession = Depends(get_db)):
        rows = (
            await db.execute(select(DeadLetterRow).order_by(DeadLetterRow.created_at.desc()))
        ).scalars().all()
        return [
            DeadLetterResponse(
                dlq_id=r.dlq_id,
                session_id=r.session_id,
                step_id=r.step_id,
                failure_type=r.failure_type,
                reason=r.reason,
                payload=r.payload,
                status=r.status,
                created_at=r.created_at,
            )
            for r in rows
        ]

    @router.post("/dlq/{dlq_id}/replay-request")
    async def request_dlq_replay(dlq_id: str, db: AsyncSession = Depends(get_db)):
        row = (await db.execute(select(DeadLetterRow).where(DeadLetterRow.dlq_id == dlq_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="dlq entry not found")
        await event_bus.publish(
            AgentEvent(
                event_type="dlq_replay_requested",
                session_id=row.session_id,
                payload={"dlq_id": dlq_id},
                published_at=datetime.utcnow(),
            )
        )
        return {"ok": True}

    return router
