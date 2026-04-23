from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
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
    DeadLetterDismissRequest,
    DeadLetterPushRequest,
    DeadLetterReplayRequest,
    DeadLetterResponse,
    MessageCreateRequest,
    MessageResponse,
    PlanCreateRequest,
    PlanResponse,
    SessionCreateRequest,
    SessionResponse,
    ToolInfo,
    ValidationErrorResponse,
)
from .session_manager import SessionManager, TransitionError, VersionConflictError
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
        replan_context=s.replan_context,
        pending_user_message=s.pending_user_message,
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


def build_router(
    *,
    settings: Settings,
    tool_registry: ToolRegistry,
    event_bus: EventBus,
    enqueue_session: Any | None = None,
) -> APIRouter:
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

    @router.get("/tools", response_model=list[ToolInfo])
    async def list_tools(
        intent: str | None = Query(None, description="Optional user intent to scope tools."),
        max_tools: int = Query(30, ge=1, le=200, description="Maximum tools returned."),
        db: AsyncSession = Depends(get_db),
    ):
        tools_by_name = await tool_registry.get_tools_by_name(db)
        if intent:
            scoped = filter_tools_for_intent(intent=intent, tools_by_name=tools_by_name, max_tools=max_tools)
            return [tools_by_name[name] for name in scoped.tool_names if name in tools_by_name]
        names = sorted(tools_by_name.keys())[:max_tools]
        return [tools_by_name[name] for name in names]

    @router.post("/sessions/{session_id}/messages", response_model=MessageResponse)
    async def add_message(session_id: str, req: MessageCreateRequest, db: AsyncSession = Depends(get_db)):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        msg = await session_mgr.add_message(db, session_id=session_id, role=req.role, content=req.content)
        if req.role == "user":
            sess.current_intent = req.content[:5000]
            lowered = req.content.strip().lower()
            if any(token in lowered for token in ("stop", "cancel", "don't do this", "do not do this")):
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
                current_plan = (
                    await db.execute(select(PlanRow).where(PlanRow.plan_id == sess.plan_id))
                ).scalars().first()
                steps = (
                    await db.execute(
                        select(PlanStepRow)
                        .where(PlanStepRow.plan_id == sess.plan_id)
                        .order_by(PlanStepRow.step_index.asc())
                    )
                ).scalars().all()
                if current_plan and not current_plan.invalidated_at:
                    current_plan.invalidated_at = datetime.utcnow()
                    current_plan.invalidated_reason = "mid_execution_user_message"
                completed_steps = [
                    {"step_index": s.step_index, "tool_name": s.tool_name, "args": s.args, "result": s.result}
                    for s in steps
                    if s.status == "DONE"
                ]
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
            if sess.status == "PLANNING":
                context = dict(sess.replan_context or {})
                failures = int(context.get("validation_failure_count", 0)) + 1
                context["validation_failure_count"] = failures
                context["last_validation_errors"] = validation.errors
                sess.replan_context = context
                sess.error = "Plan validation failed"
                sess.version += 1
                if failures >= 3:
                    sess.status = "BLOCKED"
                    dlq = DeadLetterRow(
                        dlq_id=generate_uuid(),
                        session_id=session_id,
                        step_id=None,
                        failure_type="replan_limit_reached",
                        reason="Plan validation failed 3 consecutive times",
                        payload={"errors": validation.errors, "validation_failure_count": failures},
                        status="PENDING",
                    )
                    db.add(dlq)
                await db.commit()
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

        if sess.replan_context:
            plan_version = max(1, sess.plan_version or 1)
        else:
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
        sess.replan_context = None
        sess.pending_user_message = None
        sess.error = None
        sess.version += 1
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
    async def execute(
        session_id: str,
        background: bool = Query(False, description="If true, enqueue execution to the worker pool (when enabled)."),
        expected_version: int | None = Query(None, ge=1, description="Optional optimistic-lock expected session version."),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        if expected_version is not None and sess.version != expected_version:
            raise HTTPException(status_code=409, detail=f"version_conflict expected={expected_version} actual={sess.version}")
        try:
            session_mgr.enforce_limits(sess)
        except TransitionError as e:
            raise HTTPException(status_code=429, detail=str(e))
        if background and enqueue_session is not None:
            # Mark as executing and enqueue.
            try:
                sess = await session_mgr.update_with_version(
                    db,
                    session_id=sess.session_id,
                    expected_version=sess.version,
                    values={"status": "EXECUTING", "error": None},
                )
            except VersionConflictError as e:
                raise HTTPException(status_code=409, detail=str(e))
            try:
                await enqueue_session(session_id)
            except Exception as e:
                raise HTTPException(status_code=429, detail=f"queue full or enqueue failed: {e}")
            return _session_to_response(sess)

        tools_by_name = await tool_registry.get_tools_by_name(db)
        await executor.execute_until_blocked(db, session=sess, tools_by_name=tools_by_name)
        sess = await session_mgr.get_session(db, session_id=session_id)
        return _session_to_response(sess)

    @router.post("/sessions/{session_id}/cancel", response_model=SessionResponse)
    async def cancel_session(session_id: str, db: AsyncSession = Depends(get_db)):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
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
                step.last_error = step.last_error or "Cancelled"
        sess.status = "IDLE"
        sess.error = "Cancelled"
        sess.updated_at = datetime.utcnow()
        await db.commit()
        await event_bus.publish(
            AgentEvent(
                event_type="session_cancel",
                session_id=session_id,
                payload={},
                published_at=datetime.utcnow(),
            )
        )
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
        step = (await db.execute(select(PlanStepRow).where(PlanStepRow.step_id == row.step_id))).scalars().first()
        if step and step.status not in ("DONE", "SKIPPED", "FAILED", "AMBIGUOUS"):
            step.status = "SKIPPED"
            step.completed_at = datetime.utcnow()
            reason = req.rejection_reason or f"Approval {row.approval_id} rejected"
            step.last_error = reason
        sess = await session_mgr.get_session(db, session_id=row.session_id)
        if sess:
            sess.status = "IDLE"
            sess.error = req.rejection_reason or f"Approval {row.approval_id} rejected"
            sess.updated_at = datetime.utcnow()
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
    async def list_dlq(
        status: str | None = Query(None),
        session_id: str | None = Query(None),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(DeadLetterRow)
        if status:
            stmt = stmt.where(DeadLetterRow.status == status)
        if session_id:
            stmt = stmt.where(DeadLetterRow.session_id == session_id)
        rows = (
            await db.execute(stmt.order_by(DeadLetterRow.created_at.desc()))
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
                replayed_at=r.replayed_at,
                replayed_by=r.replayed_by,
                dismissed_at=r.dismissed_at,
                dismissed_reason=r.dismissed_reason,
                created_at=r.created_at,
            )
            for r in rows
        ]

    @router.post("/dlq/push", response_model=DeadLetterResponse)
    async def push_dlq(req: DeadLetterPushRequest, db: AsyncSession = Depends(get_db)):
        row = DeadLetterRow(
            dlq_id=generate_uuid(),
            session_id=req.session_id,
            step_id=req.step_id,
            failure_type=req.failure_type,
            reason=req.reason,
            payload=req.payload,
            status="PENDING",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return DeadLetterResponse(
            dlq_id=row.dlq_id,
            session_id=row.session_id,
            step_id=row.step_id,
            failure_type=row.failure_type,
            reason=row.reason,
            payload=row.payload,
            status=row.status,
            replayed_at=row.replayed_at,
            replayed_by=row.replayed_by,
            dismissed_at=row.dismissed_at,
            dismissed_reason=row.dismissed_reason,
            created_at=row.created_at,
        )

    @router.post("/dlq/{dlq_id}/replay")
    async def replay_dlq(dlq_id: str, req: DeadLetterReplayRequest, db: AsyncSession = Depends(get_db)):
        row = (await db.execute(select(DeadLetterRow).where(DeadLetterRow.dlq_id == dlq_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="dlq entry not found")
        if row.step_id:
            step = (await db.execute(select(PlanStepRow).where(PlanStepRow.step_id == row.step_id))).scalars().first()
            if step:
                step.status = "NOT_STARTED"
                step.last_error = None
                step.started_at = None
                step.completed_at = None
                step.retry_count = 0
        sess = await session_mgr.get_session(db, session_id=row.session_id)
        if sess:
            if row.step_id:
                step = (await db.execute(select(PlanStepRow).where(PlanStepRow.step_id == row.step_id))).scalars().first()
                if step is not None:
                    sess.current_step_index = min(sess.current_step_index or 0, step.step_index)
            sess.status = "EXECUTING"
            sess.error = None
            sess.version += 1
        row.status = "REPLAYED"
        row.replayed_at = datetime.utcnow()
        row.replayed_by = req.replayed_by
        row.dismissed_at = None
        row.dismissed_reason = None
        await db.commit()
        await event_bus.publish(
            AgentEvent(
                event_type="dlq_replay_requested",
                session_id=row.session_id,
                payload={"dlq_id": dlq_id},
                published_at=datetime.utcnow(),
            )
        )
        return {"ok": True}

    @router.post("/dlq/{dlq_id}/replay-request")
    async def request_dlq_replay(dlq_id: str, db: AsyncSession = Depends(get_db)):
        return await replay_dlq(dlq_id, DeadLetterReplayRequest(), db)

    @router.post("/dlq/{dlq_id}/dismiss")
    async def dismiss_dlq(dlq_id: str, req: DeadLetterDismissRequest, db: AsyncSession = Depends(get_db)):
        row = (await db.execute(select(DeadLetterRow).where(DeadLetterRow.dlq_id == dlq_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="dlq entry not found")
        row.status = "DISMISSED"
        row.dismissed_at = datetime.utcnow()
        who = req.dismissed_by or "ops"
        row.dismissed_reason = f"{who}: {req.dismissed_reason}"
        await db.commit()
        return {"ok": True}

    @router.post("/admin/regenerate-tools")
    async def regenerate_tools(db: AsyncSession = Depends(get_db)):
        # Best-effort regeneration: fetch spec (HTTP then local fallback) and store tools.md hash in DB.
        from agent.toolgen import fetch_openapi_spec, tools_from_openapi, write_tools_md_and_meta
        import os

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        local_swagger = os.path.join(repo_root, "emas", "docs", "swagger.json")
        tools_md_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools.md"))
        openapi_url = os.environ.get("OPENAPI_URL", "http://localhost:8080/swagger/doc.json")
        force_local = os.environ.get("OPENAPI_LOCAL", "").strip() == "1"

        spec = fetch_openapi_spec(openapi_url=openapi_url, local_swagger_json_path=local_swagger, force_local=force_local)
        tools = tools_from_openapi(spec)
        result = await write_tools_md_and_meta(db, tools=tools, tools_md_path=tools_md_path, replace_db=True)
        await event_bus.publish(
            AgentEvent(
                event_type="tool_registry_updated",
                session_id="",
                payload={"tool_count": result.tool_count, "tools_md_hash": result.tools_md_hash},
                published_at=datetime.utcnow(),
            )
        )
        return {"ok": True, "tool_count": result.tool_count, "tools_md_hash": result.tools_md_hash}

    return router
