from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.response_mappers import session_to_response
from factory_agent.graph.session_detection import is_graph_native_session
from factory_agent.observability.events import AgentEvent, EventBus
from factory_agent.observability.telemetry import log_event
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.persistence.models import generate_uuid
from factory_agent.schemas import ConfirmationDecisionRequest, PlanStepResponse, SessionResponse


LogStepStatus = Callable[[SessionRow, PlanStepRow, str], None]
StepToResponse = Callable[[PlanStepRow], PlanStepResponse]


def build_session_controls_router(
    *,
    session_mgr: SessionManager,
    event_bus: EventBus,
    require_jwt: Callable[..., dict[str, Any]],
    log_step_status: LogStepStatus,
    step_to_response: StepToResponse,
) -> APIRouter:
    router = APIRouter()

    async def _load_current_plan(*, db: AsyncSession, session_id: str) -> PlanRow | None:
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess or not sess.plan_id:
            return None
        return (await db.execute(select(PlanRow).where(PlanRow.plan_id == sess.plan_id))).scalars().first()

    @router.post("/sessions/{session_id}/confirm", response_model=SessionResponse)
    async def confirm_predicate(
        session_id: str,
        req: ConfirmationDecisionRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        context = dict(sess.replan_context or {})
        confirmation = context.get("confirmation_request")
        if sess.status != "WAITING_CONFIRMATION" or not isinstance(confirmation, dict):
            raise HTTPException(status_code=409, detail="session is not waiting for confirmation")
        options: list[dict[str, Any]] = []
        for key in ("options", "all_options", "other_possible_fields"):
            raw_options = confirmation.get(key)
            if not isinstance(raw_options, list):
                continue
            for opt in raw_options:
                if not isinstance(opt, dict):
                    continue
                if any(existing.get("field") == opt.get("field") for existing in options):
                    continue
                options.append(opt)
        selected = next((opt for opt in options if isinstance(opt, dict) and opt.get("field") == req.field), None)
        if not selected:
            raise HTTPException(status_code=400, detail="confirmation option is not valid for this session")

        raw_term = str(confirmation.get("raw_term") or selected.get("value") or req.value or "").strip()
        value = str(req.value or selected.get("value") or raw_term).strip()
        entity = str(confirmation.get("entity") or "record")
        memory = context.get("intent_memory") if isinstance(context.get("intent_memory"), dict) else {}
        positives = memory.get("positive_bindings") if isinstance(memory.get("positive_bindings"), list) else []
        positives.append(
            {
                "entity": entity,
                "term": raw_term,
                "normalized_term": raw_term.lower().replace("_", " ").replace("-", " "),
                "field": req.field,
                "value": value,
                "source": "operator_confirmation",
                "confirmed_at": datetime.utcnow().isoformat() + "Z",
            }
        )
        memory["positive_bindings"] = positives
        context["intent_memory"] = memory
        context.pop("confirmation_request", None)
        sess.replan_context = context
        sess.status = "IDLE"
        sess.error = None
        sess.version += 1
        db.add(
            MessageRow(
                message_id=generate_uuid(),
                session_id=session_id,
                role="assistant",
                content=f'Confirmed: use {req.field}="{value}".',
                mode="normal",
                tool_name="__confirmation_decision__",
            )
        )
        await db.commit()
        log_event(
            "predicate_confirmation_decided",
            session_id=session_id,
            field=req.field,
            value=value,
            raw_term=raw_term,
        )
        return session_to_response(sess)

    @router.get("/sessions/{session_id}/steps", response_model=list[PlanStepResponse])
    async def list_steps(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        rows = (
            await db.execute(
                select(PlanStepRow)
                .where(PlanStepRow.session_id == session_id)
                .order_by(PlanStepRow.step_index.asc())
            )
        ).scalars().all()
        return [step_to_response(row) for row in rows]

    @router.post("/sessions/{session_id}/cancel", response_model=SessionResponse)
    async def cancel_session(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        current_plan = await _load_current_plan(db=db, session_id=session_id)
        if await is_graph_native_session(db, sess, plan=current_plan):
            pending_graph_approvals = (
                await db.execute(
                    select(ApprovalRow)
                    .where(ApprovalRow.session_id == session_id)
                    .where(ApprovalRow.status == "PENDING")
                )
            ).scalars().all()
            for ap in pending_graph_approvals:
                ap.status = "REJECTED"
                ap.decided_by = "system"
                ap.decided_at = datetime.utcnow()
                ap.rejection_reason = "Cancelled"
            context = dict(sess.replan_context or {})
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
        else:
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
                    log_step_status(sess, step, step.status)
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
        return session_to_response(sess)

    return router
