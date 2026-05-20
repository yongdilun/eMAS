from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.dependencies import is_admin_claims, principal_user_id, require_session_owner
from factory_agent.api.response_mappers import approval_to_response
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.planner import PlannerBackendError, PlannerPlanRejected
from factory_agent.planning.v2_interrupts import approval_payload_matches_newest_ledger_revision
from factory_agent.schemas import ApprovalDecisionRequest, ApprovalResponse


PublishAgentEvent = Callable[[str, str, dict[str, Any]], Awaitable[None]]
StartGraphApprovalResumeTask = Callable[[AsyncSession, str], None]
ResumeApprovedGraphApproval = Callable[..., Awaitable[None]]


def _merge_approval_args(existing: Any, override: dict[str, Any]) -> dict[str, Any]:
    base = dict(existing) if isinstance(existing, dict) else {}
    merged = {**base, **override}
    existing_bundle = base.get("bundle_ui") if isinstance(base.get("bundle_ui"), dict) else {}
    override_bundle = override.get("bundle_ui") if isinstance(override.get("bundle_ui"), dict) else {}
    if existing_bundle or override_bundle:
        merged["bundle_ui"] = {**existing_bundle, **override_bundle}
    return merged


def build_approvals_router(
    *,
    session_mgr: SessionManager,
    planner: Any,
    require_jwt: Callable[..., dict[str, Any]],
    publish_agent_event: PublishAgentEvent,
    start_graph_approval_resume_task: StartGraphApprovalResumeTask,
    should_resume_graph_approval_inline: Callable[[], bool],
    resume_approved_graph_approval: ResumeApprovedGraphApproval,
) -> APIRouter:
    router = APIRouter()

    @router.get("/approvals/pending", response_model=list[ApprovalResponse])
    async def list_pending_approvals(
        session_id: str | None = Query(None),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(ApprovalRow).where(ApprovalRow.status == "PENDING")
        if session_id:
            stmt = stmt.where(ApprovalRow.session_id == session_id)
        rows = (await db.execute(stmt.order_by(ApprovalRow.created_at.asc()))).scalars().all()
        principal = principal_user_id(user)
        if principal and not is_admin_claims(user):
            visible = []
            for row in rows:
                sess = await session_mgr.get_session(db, session_id=row.session_id)
                if sess is None or sess.user_id == principal:
                    visible.append(row)
            rows = visible
        return [approval_to_response(row) for row in rows]

    @router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
    async def get_approval(
        approval_id: str,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        sess = await session_mgr.get_session(db, session_id=row.session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(sess, user)
        return approval_to_response(row)

    @router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
    async def approve_approval(
        approval_id: str,
        req: ApprovalDecisionRequest,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        owner_session = await session_mgr.get_session(db, session_id=row.session_id)
        if not owner_session:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(owner_session, user)
        if (getattr(row, "subject_type", "step") or "step") == "graph":
            now = datetime.utcnow()
            if row.status == "APPROVED":
                sess = await session_mgr.get_session(db, session_id=row.session_id)
                context = sess.replan_context if sess and isinstance(sess.replan_context, dict) else {}
                if isinstance(context.get("langgraph_approval_resume"), dict):
                    start_graph_approval_resume_task(db, row.approval_id)
                return approval_to_response(row)
            if row.status != "PENDING":
                raise HTTPException(status_code=409, detail=f"approval is already {row.status.lower()}")
            sess = await session_mgr.get_session(db, session_id=row.session_id)
            if not sess:
                raise HTTPException(status_code=404, detail="session not found")
            context = dict(sess.replan_context or {})
            pending = context.get("langgraph_pending_approval") if isinstance(context, dict) else None
            pending_approval_id = pending.get("approval_id") if isinstance(pending, dict) else None
            if row.expires_at <= now:
                row.status = "EXPIRED"
                row.decided_by = req.decided_by or "system"
                row.decided_at = now
                row.rejection_reason = "Approval expired before it was approved"
                if pending_approval_id == row.approval_id:
                    context.pop("langgraph_pending_approval", None)
                    sess.replan_context = context
                    sess.status = "IDLE"
                    sess.error = row.rejection_reason
                    sess.updated_at = now
                    sess.version += 1
                    sess.event_seq = (getattr(sess, "event_seq", None) or 0) + 1
                await db.commit()
                raise HTTPException(status_code=409, detail="approval expired before it was approved")
            if sess.status != "WAITING_APPROVAL" or pending_approval_id != row.approval_id:
                row.status = "EXPIRED"
                row.decided_by = req.decided_by or "system"
                row.decided_at = now
                row.rejection_reason = "Approval is stale because the session changed state"
                await db.commit()
                raise HTTPException(status_code=409, detail="approval is stale because the session changed state")
            if not approval_payload_matches_newest_ledger_revision(row.args if isinstance(row.args, dict) else {}, context):
                row.status = "EXPIRED"
                row.decided_by = req.decided_by or "system"
                row.decided_at = now
                row.rejection_reason = "Approval payload is stale for the newest requirement ledger revision"
                context.pop("langgraph_pending_approval", None)
                sess.replan_context = context
                sess.status = "PLANNING"
                sess.completed_at = None
                sess.error = row.rejection_reason
                sess.version += 1
                sess.event_seq = (getattr(sess, "event_seq", None) or 0) + 1
                sess.updated_at = now
                await db.commit()
                raise HTTPException(
                    status_code=409,
                    detail="approval payload is stale for the newest requirement ledger revision",
                )
            if isinstance(req.args, dict) and req.args:
                if not approval_payload_matches_newest_ledger_revision(req.args, context):
                    row.status = "EXPIRED"
                    row.decided_by = req.decided_by or "system"
                    row.decided_at = now
                    row.rejection_reason = "Approval payload is stale for the newest requirement ledger revision"
                    context.pop("langgraph_pending_approval", None)
                    sess.replan_context = context
                    sess.status = "PLANNING"
                    sess.completed_at = None
                    sess.error = row.rejection_reason
                    sess.version += 1
                    sess.event_seq = (getattr(sess, "event_seq", None) or 0) + 1
                    sess.updated_at = now
                    await db.commit()
                    raise HTTPException(
                        status_code=409,
                        detail="approval payload is stale for the newest requirement ledger revision",
                    )
                row.args = _merge_approval_args(row.args, req.args)
            row.status = "APPROVED"
            row.decided_by = req.decided_by
            row.decided_at = now
            context["langgraph_approval_resume"] = {
                "approval_id": row.approval_id,
                "thread_id": sess.session_id,
                "status": "approved",
                "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            }
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
            sess.status = "EXECUTING"
            sess.completed_at = None
            sess.error = "Approval received. Continuing with approved changes."
            sess.version += 1
            sess.event_seq = (getattr(sess, "event_seq", None) or 0) + 1
            sess.updated_at = datetime.utcnow()
            await db.commit()
            await publish_agent_event(
                "approval_decided",
                row.session_id,
                {"approval_id": row.approval_id, "status": "APPROVED", "subject_type": "graph"},
            )
            if should_resume_graph_approval_inline():
                await resume_approved_graph_approval(db=db, approval_id=row.approval_id)
            else:
                start_graph_approval_resume_task(db, row.approval_id)
            return approval_to_response(row)

        if (getattr(row, "subject_type", "step") or "step") == "plan":
            raise HTTPException(
                status_code=410,
                detail="legacy plan approvals are retired; graph-native approvals use subject_type=graph",
            )

        raise HTTPException(
            status_code=410,
            detail="legacy step approvals are retired; graph-native approvals use subject_type=graph",
        )

    @router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
    async def reject_approval(
        approval_id: str,
        req: ApprovalDecisionRequest,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        owner_session = await session_mgr.get_session(db, session_id=row.session_id)
        if not owner_session:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(owner_session, user)
        if (getattr(row, "subject_type", "step") or "step") == "graph":
            sess = await session_mgr.get_session(db, session_id=row.session_id)
            if not sess:
                raise HTTPException(status_code=404, detail="session not found")
            if row.status != "PENDING":
                raise HTTPException(status_code=409, detail=f"approval is already {row.status.lower()}")
            context = dict(sess.replan_context or {})
            pending = context.get("langgraph_pending_approval") if isinstance(context, dict) else None
            pending_approval_id = pending.get("approval_id") if isinstance(pending, dict) else None
            if sess.status != "WAITING_APPROVAL" or (
                pending_approval_id is not None and pending_approval_id != row.approval_id
            ):
                row.status = "EXPIRED"
                row.decided_by = req.decided_by or "system"
                row.decided_at = datetime.utcnow()
                row.rejection_reason = "Approval is stale because the session changed state"
                await db.commit()
                raise HTTPException(status_code=409, detail="approval is stale because the session changed state")
            try:
                await planner.resume_after_approval(session_id=sess.session_id, approved=False)
            except PlannerPlanRejected as e:
                sess.status = "BLOCKED"
                sess.error = str(e)
                sess.version += 1
                await db.commit()
                raise HTTPException(status_code=400, detail={"errors": [str(e)]}) from e
            except PlannerBackendError as e:
                sess.status = "FAILED"
                sess.error = str(e)
                sess.version += 1
                await db.commit()
                raise HTTPException(status_code=503, detail={"errors": [str(e)]}) from e
            row.status = "REJECTED"
            row.decided_by = req.decided_by
            row.decided_at = datetime.utcnow()
            row.rejection_reason = req.rejection_reason
            context.pop("langgraph_pending_approval", None)
            context.pop("langgraph_approval_resume", None)
            sess.replan_context = context
            sess.status = "IDLE"
            sess.error = req.rejection_reason or f"Approval {row.approval_id} rejected"
            sess.updated_at = datetime.utcnow()
            sess.version += 1
            sess.event_seq = (getattr(sess, "event_seq", None) or 0) + 1
            await db.commit()
            await publish_agent_event(
                "approval_decided",
                row.session_id,
                {"approval_id": row.approval_id, "status": "REJECTED", "subject_type": "graph"},
            )
            return approval_to_response(row)
        if (getattr(row, "subject_type", "step") or "step") == "plan":
            raise HTTPException(
                status_code=410,
                detail="legacy plan approvals are retired; graph-native approvals use subject_type=graph",
            )

        raise HTTPException(
            status_code=410,
            detail="legacy step approvals are retired; graph-native approvals use subject_type=graph",
        )

    return router
