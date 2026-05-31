from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.dependencies import require_session_owner
from factory_agent.api.response_mappers import session_to_response
from factory_agent.config import Settings
from factory_agent.graph.http_tool_client import execute_tool_http
from factory_agent.observability.events import AgentEvent, EventBus
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.persistence.models import generate_uuid
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import InteractionDecisionRequest, SessionResponse, ToolInfo
from factory_agent.services.session_revision import bump_session_revision
from factory_agent.session_state import USER_CANCELLED_MESSAGE


_RESCHEDULE_REVIEW_KIND = "reschedule_all_review"
_VERIFY_OVERLAPS_TOOL = "post__ai_scheduling_verify-overlaps"
_APPROVE_PROPOSAL_TOOL = "post__ai_scheduling_proposals_{id}_approve"
_APPLY_PROPOSAL_TOOL = "post__ai_scheduling_proposals_{id}_apply"
_REJECT_PROPOSAL_TOOL = "post__ai_scheduling_proposals_{id}_reject"


def build_interactions_router(
    *,
    settings: Settings,
    session_mgr: SessionManager,
    tool_registry: ToolRegistry,
    event_bus: EventBus,
    require_jwt: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    async def _tools(db: AsyncSession) -> dict[str, ToolInfo]:
        return await tool_registry.get_tools_by_name(db)

    async def _execute(
        *,
        tool: ToolInfo,
        args: dict[str, Any],
        session_id: str,
        interaction_id: str,
        action: str,
    ) -> dict[str, Any]:
        return await execute_tool_http(
            settings,
            tool,
            args,
            idempotency_key=f"interaction:{session_id}:{interaction_id}:{action}",
        )

    @router.post("/sessions/{session_id}/interactions/{interaction_id}/decide", response_model=SessionResponse)
    async def decide_interaction(
        session_id: str,
        interaction_id: str,
        req: InteractionDecisionRequest,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(sess, user)

        context = dict(sess.replan_context or {})
        pending = context.get("pending_interaction")
        if not isinstance(pending, dict):
            raise HTTPException(status_code=409, detail="session is not waiting for an interaction")
        if sess.status != "WAITING_USER_ACTION":
            raise HTTPException(status_code=409, detail="session is not waiting for user action")
        if str(pending.get("interaction_id") or "") != interaction_id:
            raise HTTPException(status_code=409, detail="interaction is stale because the session changed state")
        if str(pending.get("status") or "").lower() != "pending":
            raise HTTPException(status_code=409, detail="interaction has already been decided")
        if str(pending.get("kind") or "") != _RESCHEDULE_REVIEW_KIND:
            raise HTTPException(status_code=400, detail="unsupported interaction kind")

        proposal_ids = _selected_proposal_ids(req=req, pending=pending)
        if not proposal_ids:
            raise HTTPException(status_code=400, detail="no proposal ids were provided for this interaction")

        tools_by_name = await _tools(db)
        now = datetime.utcnow()
        if req.decision == "cancel":
            result = await _cancel_reschedule_interaction(
                tools_by_name=tools_by_name,
                execute=_execute,
                session_id=session_id,
                interaction_id=interaction_id,
                proposal_ids=proposal_ids,
            )
            pending["status"] = "cancelled"
            pending["decided_at"] = now.isoformat() + "Z"
            pending["decided_by"] = req.decided_by
            context["pending_interaction"] = pending
            context["interaction_result"] = result
            context.pop("pending_interaction", None)
            sess.replan_context = context
            sess.status = "IDLE"
            sess.error = USER_CANCELLED_MESSAGE
            sess.completed_at = None
            message = "Reschedule cancelled. No proposal batch was applied."
        else:
            result = await _apply_reschedule_interaction(
                tools_by_name=tools_by_name,
                execute=_execute,
                session_id=session_id,
                interaction_id=interaction_id,
                proposal_ids=proposal_ids,
            )
            pending["status"] = "applied" if result["applied"] else "failed"
            pending["decided_at"] = now.isoformat() + "Z"
            pending["decided_by"] = req.decided_by
            context["pending_interaction"] = pending
            context["interaction_result"] = result
            context.pop("pending_interaction", None)
            sess.replan_context = context
            sess.status = "COMPLETED" if result["applied"] else "FAILED"
            sess.completed_at = now if result["applied"] else None
            sess.error = None if result["applied"] else result["summary"]
            message = result["summary"]

        db.add(
            MessageRow(
                message_id=generate_uuid(),
                session_id=session_id,
                role="assistant",
                content=message,
                mode="normal",
                tool_name="__pending_interaction__",
            )
        )
        sess.updated_at = now
        bump_session_revision(sess)
        await db.commit()
        await _publish_resume(event_bus=event_bus, session_id=session_id, payload={
            "interaction_id": interaction_id,
            "decision": req.decision,
            "status": sess.status,
            "runtime": "pending_interaction",
        })
        return session_to_response(sess)

    return router


def _selected_proposal_ids(*, req: InteractionDecisionRequest, pending: Mapping[str, Any]) -> list[str]:
    raw = req.proposal_ids or pending.get("proposal_ids") or []
    ids = [str(item).strip() for item in raw if str(item or "").strip()]
    return list(dict.fromkeys(ids))


async def _apply_reschedule_interaction(
    *,
    tools_by_name: Mapping[str, ToolInfo],
    execute: Callable[..., Any],
    session_id: str,
    interaction_id: str,
    proposal_ids: list[str],
) -> dict[str, Any]:
    verify_tool = tools_by_name.get(_VERIFY_OVERLAPS_TOOL)
    if verify_tool is not None:
        verify = await execute(
            tool=verify_tool,
            args={"proposal_ids": proposal_ids, "scope": "proposals"},
            session_id=session_id,
            interaction_id=interaction_id,
            action="verify-proposals",
        )
        body = verify.get("body") if isinstance(verify.get("body"), dict) else {}
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        if verify.get("ok") is False or data.get("valid") is False:
            return {
                "decision": "apply",
                "applied": 0,
                "total": len(proposal_ids),
                "failed": len(proposal_ids),
                "proposal_ids": proposal_ids,
                "summary": "Reschedule could not be applied because proposal overlap verification failed.",
                "verify": data,
            }

    approve_tool = tools_by_name.get(_APPROVE_PROPOSAL_TOOL)
    apply_tool = tools_by_name.get(_APPLY_PROPOSAL_TOOL)
    if apply_tool is None:
        return {
            "decision": "apply",
            "applied": 0,
            "total": len(proposal_ids),
            "failed": len(proposal_ids),
            "proposal_ids": proposal_ids,
            "summary": "Reschedule could not be applied because the proposal apply tool is unavailable.",
        }

    applied_ids: list[str] = []
    failed: list[dict[str, Any]] = []
    for proposal_id in proposal_ids:
        if approve_tool is not None:
            approve = await execute(
                tool=approve_tool,
                args={"id": proposal_id, "skip_staleness_check": True},
                session_id=session_id,
                interaction_id=interaction_id,
                action=f"approve-{proposal_id}",
            )
            if approve.get("ok") is False and not _already_approved_error(approve):
                failed.append({"proposal_id": proposal_id, "stage": "approve", "result": approve})
                continue
        applied = await execute(
            tool=apply_tool,
            args={"id": proposal_id, "skip_staleness_check": True},
            session_id=session_id,
            interaction_id=interaction_id,
            action=f"apply-{proposal_id}",
        )
        if applied.get("ok"):
            applied_ids.append(proposal_id)
        else:
            failed.append({"proposal_id": proposal_id, "stage": "apply", "result": applied})

    applied_count = len(applied_ids)
    failed_count = len(failed)
    summary = (
        f"Reschedule applied successfully. Applied {applied_count}/{len(proposal_ids)} proposal(s)."
        if applied_count and not failed_count
        else f"Reschedule partially applied. Applied {applied_count}/{len(proposal_ids)} proposal(s); {failed_count} failed."
        if applied_count
        else f"Reschedule was not applied. {failed_count}/{len(proposal_ids)} proposal(s) failed."
    )
    return {
        "decision": "apply",
        "applied": applied_count,
        "total": len(proposal_ids),
        "failed": failed_count,
        "proposal_ids": applied_ids,
        "failed_proposals": failed,
        "summary": summary,
    }


async def _cancel_reschedule_interaction(
    *,
    tools_by_name: Mapping[str, ToolInfo],
    execute: Callable[..., Any],
    session_id: str,
    interaction_id: str,
    proposal_ids: list[str],
) -> dict[str, Any]:
    reject_tool = tools_by_name.get(_REJECT_PROPOSAL_TOOL)
    rejected = 0
    failed: list[dict[str, Any]] = []
    if reject_tool is not None:
        for proposal_id in proposal_ids:
            result = await execute(
                tool=reject_tool,
                args={"id": proposal_id},
                session_id=session_id,
                interaction_id=interaction_id,
                action=f"reject-{proposal_id}",
            )
            if result.get("ok"):
                rejected += 1
            else:
                failed.append({"proposal_id": proposal_id, "result": result})
    return {
        "decision": "cancel",
        "total": len(proposal_ids),
        "rejected": rejected,
        "failed": len(failed),
        "failed_proposals": failed,
        "summary": "Reschedule cancelled. No proposal batch was applied.",
    }


def _already_approved_error(result: Mapping[str, Any]) -> bool:
    body = result.get("body") if isinstance(result.get("body"), Mapping) else {}
    text = str(body.get("error") or body.get("message") or body).lower()
    return "only draft proposals can be approved" in text or "already approved" in text


async def _publish_resume(*, event_bus: EventBus, session_id: str, payload: dict[str, Any]) -> None:
    await event_bus.publish(
        AgentEvent(
            event_type="session_resume",
            session_id=session_id,
            payload=payload,
            published_at=datetime.utcnow(),
        )
    )
