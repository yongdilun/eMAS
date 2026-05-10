from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from jsonschema import Draft202012Validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import DeadLetter as DeadLetterRow
from factory_agent.persistence.models import ExecutionSnapshot as ExecutionSnapshotRow
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.persistence.models import generate_uuid

from ..config import Settings
from ..observability.events import AgentEvent, EventBus
from ..orchestration.execution import ExecutionEngine, compute_idempotency_key
from ..orchestration.memory_manager import MemoryManager
from ..planning.intent import assess_intent
from ..observability.metrics import metrics
from ..security.permissions import filter_tools_for_role, role_from_claims
from ..planner import PlannerBackendError, PlannerClarificationError, PlannerConfirmationRequired
from ..services.planner_service import PlannerService
from ..planning.plan_validator import validate_plan
from ..schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    ConfirmationDecisionRequest,
    DeadLetterDismissRequest,
    DeadLetterPushRequest,
    DeadLetterReplayRequest,
    DeadLetterResponse,
    MessageCreateRequest,
    MessageResponse,
    PlanStepResponse,
    PlanCreateRequest,
    PlanResponse,
    SessionCreateRequest,
    SessionSnapshotResponse,
    SessionResponse,
    SessionUpdateRequest,
    TimelineEventResponse,
    ToolInfo,
    ValidationErrorResponse,
)
from ..orchestration.router import QueryRouter
from ..llm.models import build_planner_chat_model
from ..orchestration.session_manager import SessionManager, TransitionError, VersionConflictError
from ..security import JwtValidationError, validate_bearer_token
from ..analysis.summary_backend import SummaryAdapter, SummaryBackendError
from ..observability.telemetry import log_event, log_step_status_changed
from ..registry.tool_registry import ToolRegistry
from ..planning.tool_selector import ToolSelector
from ..analysis.presentation import extract_table_from_result


def _normalize_session_name(name: str | None) -> str | None:
    normalized = (name or "").strip()
    return normalized or None


def _session_to_response(s: SessionRow) -> SessionResponse:
    return SessionResponse(
        session_id=s.session_id,
        user_id=s.user_id,
        name=_normalize_session_name(getattr(s, "name", None)),
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


def _plan_to_response(plan: PlanRow) -> PlanResponse:
    return PlanResponse(
        plan_id=plan.plan_id,
        session_id=plan.session_id,
        version=plan.version,
        kind=plan.kind or "execution",
        status=plan.status or "DRAFT",
        dependency_graph=plan.dependency_graph,
        parallel_groups=plan.parallel_groups,
        plan_hash=plan.plan_hash,
        approved_plan_hash=plan.approved_plan_hash,
        derived_from_plan_id=plan.derived_from_plan_id,
        plan_explanation=plan.plan_explanation,
        risk_summary=plan.risk_summary,
        created_at=plan.created_at,
        created_by=plan.created_by,
    )


def _message_to_response(m: MessageRow) -> MessageResponse:
    return MessageResponse(
        message_id=m.message_id,
        session_id=m.session_id,
        role=m.role,
        content=m.content,
        mode=(getattr(m, "mode", None) or "normal"),
        created_at=m.created_at,
        step_id=m.step_id,
        tool_name=m.tool_name,
    )


def _approval_to_response(a: ApprovalRow) -> ApprovalResponse:
    return ApprovalResponse(
        approval_id=a.approval_id,
        session_id=a.session_id,
        subject_type=(getattr(a, "subject_type", None) or "step"),
        plan_id=getattr(a, "plan_id", None),
        step_id=(a.step_id or None),
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


def _step_to_response(s: PlanStepRow) -> PlanStepResponse:
    return PlanStepResponse(
        step_id=s.step_id,
        plan_id=s.plan_id,
        session_id=s.session_id,
        step_index=s.step_index,
        tool_name=s.tool_name,
        args=s.args or {},
        execution_mode=(getattr(s, "execution_mode", None) or "single"),
        bindings=getattr(s, "bindings", None) or [],
        bulk_state=getattr(s, "bulk_state", None),
        status=s.status,
        idempotency_key=s.idempotency_key,
        requires_approval=bool(s.requires_approval),
        approval_id=s.approval_id,
        retry_count=s.retry_count or 0,
        max_retries=s.max_retries or 0,
        last_error=s.last_error,
        result=s.result,
        result_summary=s.result_summary,
        started_at=s.started_at,
        completed_at=s.completed_at,
    )


def _timeline_event(
    *,
    event_id: str,
    event_type: str,
    content: str,
    created_at: datetime,
    role: str = "assistant",
    mode: str | None = None,
    turn_id: str | None = None,
    step_context: dict[str, Any] | None = None,
    step_id: str | None = None,
    approval_id: str | None = None,
    tool_name: str | None = None,
    status: str | None = None,
    details: dict[str, Any] | None = None,
) -> TimelineEventResponse:
    return TimelineEventResponse(
        event_id=event_id,
        event_type=event_type,  # type: ignore[arg-type]
        content=content,
        created_at=created_at,
        role=role,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        turn_id=turn_id,
        step_context=step_context,
        step_id=step_id,
        approval_id=approval_id,
        tool_name=tool_name,
        status=status,
        details=details,
    )


def _build_tool_result_details(
    *,
    tool_name: str | None,
    args: dict[str, Any] | None,
    result: dict[str, Any] | None,
    last_error: str | None,
    content: str | None,
    intent: str | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {"args": args, "result": result, "last_error": last_error}
    presentation = extract_table_from_result(tool_name=tool_name, result=result, intent=intent)
    if presentation:
        presentation["message"] = content or ""
        details["presentation"] = presentation
    return details


_TIMELINE_EVENT_PRIORITY = {
    "user_message": 0,
    "plan_created": 1,
    "execution_started": 2,
    "tool_started": 3,
    "approval_required": 3,
    "tool_result": 4,
    "approval_decided": 5,
    "replan_requested": 6,
    "session_blocked": 7,
    "session_failed": 8,
    "session_completed": 9,
}

_APPROVAL_AUX_TAGS = {"list", "lookup", "status", "pending", "create", "update", "delete", "approve", "reject"}


def build_router(
    *,
    settings: Settings,
    tool_registry: ToolRegistry,
    event_bus: EventBus,
    enqueue_session: Any | None = None,
    planner_adapter: PlannerService | None = None,
) -> APIRouter:
    router = APIRouter()
    session_mgr = SessionManager(settings)
    memory_manager = MemoryManager(settings)
    executor = ExecutionEngine(settings, event_bus)
    planner = planner_adapter or PlannerService(settings=settings, tool_registry=tool_registry)
    tool_selector = ToolSelector(settings)
    summary_adapter = SummaryAdapter(settings)
    query_router = QueryRouter(llm=build_planner_chat_model(settings, json_mode=True))

    def _should_enforce_registry_health() -> bool:
        if not settings.enforce_tool_registry_health:
            return False
        return not settings.database_url.startswith("sqlite+aiosqlite:///:memory:")

    async def _latest_user_message(*, db: AsyncSession, session_id: str) -> MessageRow | None:
        return (
            await db.execute(
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .where(MessageRow.role == "user")
                .order_by(MessageRow.created_at.desc())
            )
        ).scalars().first()

    async def _load_current_plan(*, db: AsyncSession, session_id: str) -> PlanRow | None:
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess or not sess.plan_id:
            return None
        return (await db.execute(select(PlanRow).where(PlanRow.plan_id == sess.plan_id))).scalars().first()

    async def _persist_conversation_reply_as_empty_plan(
        *,
        db: AsyncSession,
        sess: SessionRow,
        reply: str,
        mode: str,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        context_to_keep: dict[str, Any] | None = None,
    ) -> PlanResponse:
        from ..schemas import PlanDraft

        db.add(
            MessageRow(
                message_id=generate_uuid(),
                session_id=sess.session_id,
                role="assistant",
                content=reply,
                mode=mode,
                tool_name="__conversation__",
            )
        )
        await db.commit()
        empty_draft = PlanDraft(
            plan_explanation=reply,
            risk_summary="No tool execution required.",
            steps=[],
        )
        return await _persist_plan(
            db=db,
            sess=sess,
            draft=empty_draft,
            tools_by_name=tools_by_name,
            backend_used="system",
            kind="execution",
            status="COMPLETED",
            intent=intent,
            context_to_keep=context_to_keep,
        )

    def _remember_negative_predicate_bindings(
        *,
        sess: SessionRow,
        bindings: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not bindings:
            return sess.replan_context if isinstance(sess.replan_context, dict) else None
        context = dict(sess.replan_context or {})
        memory = context.get("intent_memory") if isinstance(context.get("intent_memory"), dict) else {}
        negatives = memory.get("negative_bindings") if isinstance(memory.get("negative_bindings"), list) else []
        existing = {
            (str(item.get("entity")), str(item.get("normalized_term") or item.get("term")), str(item.get("field")))
            for item in negatives
            if isinstance(item, dict)
        }
        added: list[dict[str, Any]] = []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            key = (
                str(binding.get("entity")),
                str(binding.get("normalized_term") or binding.get("term")),
                str(binding.get("field")),
            )
            if key in existing:
                continue
            negatives.append(dict(binding))
            existing.add(key)
            added.append(dict(binding))
        if not added:
            return context
        memory["negative_bindings"] = negatives
        context["intent_memory"] = memory
        sess.replan_context = context
        log_event(
            "predicate_memory_updated",
            session_id=sess.session_id,
            memory_type="negative_binding",
            bindings=added,
        )
        return context

    async def _persist_confirmation_request_as_empty_plan(
        *,
        db: AsyncSession,
        sess: SessionRow,
        confirmation: dict[str, Any],
        mode: str,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
    ) -> PlanResponse:
        reply = str(confirmation.get("message") or "Please confirm the intended filter.")
        context = dict(sess.replan_context or {})
        context["confirmation_request"] = confirmation
        context.setdefault("intent_memory", {})
        db.add(
            MessageRow(
                message_id=generate_uuid(),
                session_id=sess.session_id,
                role="assistant",
                content=reply,
                mode=mode,
                tool_name="__confirmation__",
            )
        )
        await db.commit()
        from ..schemas import PlanDraft

        empty_draft = PlanDraft(
            plan_explanation=reply,
            risk_summary="Waiting for operator confirmation before tool execution.",
            steps=[],
        )
        response = await _persist_plan(
            db=db,
            sess=sess,
            draft=empty_draft,
            tools_by_name=tools_by_name,
            backend_used="system",
            kind="execution",
            status="COMPLETED",
            intent=intent,
            context_to_keep=context,
        )
        sess.status = "WAITING_CONFIRMATION"
        sess.replan_context = context
        sess.error = reply
        sess.version += 1
        await db.commit()
        log_event(
            "predicate_confirmation_requested",
            session_id=sess.session_id,
            intent=intent,
            confirmation=confirmation,
        )
        return response

    async def _ensure_registry_health(*, db: AsyncSession) -> dict[str, ToolInfo]:
        tools_by_name = await tool_registry.get_tools_by_name(db)
        if _should_enforce_registry_health():
            health = tool_registry.assess_health(tools_by_name, min_tool_count=settings.min_healthy_tool_count)
            if not health.ok:
                repair_error: str | None = None
                if settings.auto_repair_tool_registry:
                    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                    local_swagger = os.path.join(repo_root, "emas", "docs", "swagger.json")
                    openapi_url = os.environ.get("OPENAPI_URL", "http://localhost:8080/swagger/doc.json")
                    try:
                        await tool_registry.regenerate_from_openapi(
                            db,
                            openapi_url=openapi_url,
                            local_swagger_json_path=local_swagger,
                            force_local=os.path.exists(local_swagger),
                            replace_db=True,
                        )
                        tools_by_name = await tool_registry.get_tools_by_name(db)
                        health = tool_registry.assess_health(
                            tools_by_name,
                            min_tool_count=settings.min_healthy_tool_count,
                        )
                        if health.ok:
                            log_event(
                                "tool_registry_auto_repaired",
                                tool_count=len(tools_by_name),
                                source="local_swagger" if os.path.exists(local_swagger) else "openapi_url",
                            )
                    except Exception as exc:
                        repair_error = str(exc)
                if not health.ok:
                    errors = [health.message or "Tool registry is unhealthy."]
                    if repair_error:
                        errors.append(f"Auto-repair failed: {repair_error}")
                    raise HTTPException(status_code=503, detail={"errors": errors})
        return tools_by_name

    async def _persist_plan(
        *,
        db: AsyncSession,
        sess: SessionRow,
        draft,
        tools_by_name: dict[str, ToolInfo],
        backend_used: str,
        kind: str,
        status: str,
        intent: str,
        derived_from_plan_id: str | None = None,
        context_to_keep: dict[str, Any] | None = None,
    ) -> PlanResponse:
        validation = validate_plan(draft, tools_by_name, max_steps=settings.max_plan_steps)
        if not validation.ok:
            raise HTTPException(status_code=400, detail={"errors": validation.errors})

        if sess.plan_id:
            existing = (await db.execute(select(PlanRow).where(PlanRow.plan_id == sess.plan_id))).scalars().first()
            if existing and not existing.invalidated_at:
                existing.invalidated_at = datetime.utcnow()
                existing.invalidated_reason = "Replanned"
                existing.status = "INVALIDATED"

        plan_version = (sess.plan_version or 0) + 1
        plan_row = PlanRow(
            plan_id=generate_uuid(),
            session_id=sess.session_id,
            version=plan_version,
            kind=kind,
            status=status,
            dependency_graph=validation.normalized_dependency_graph,
            parallel_groups=validation.normalized_parallel_groups,
            plan_hash=validation.plan_hash,
            plan_explanation=draft.plan_explanation,
            risk_summary=draft.risk_summary,
            derived_from_plan_id=derived_from_plan_id,
            created_at=datetime.utcnow(),
            created_by=backend_used,
        )
        db.add(plan_row)
        await db.commit()
        await db.refresh(plan_row)

        for step in draft.steps:
            tool = tools_by_name.get(step.tool_name)
            step_row = PlanStepRow(
                step_id=generate_uuid(),
                plan_id=plan_row.plan_id,
                session_id=sess.session_id,
                step_index=step.step_index,
                tool_name=step.tool_name,
                args=step.args,
                bindings=[binding.model_dump() for binding in (getattr(step, "bindings", []) or [])],
                execution_mode=getattr(step, "execution_mode", "single") or "single",
                bulk_state=None,
                status="NOT_STARTED",
                idempotency_key=compute_idempotency_key(
                    session_id=sess.session_id,
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

        sess.plan_id = plan_row.plan_id
        sess.plan_version = plan_version
        sess.plan_hash = plan_row.plan_hash
        sess.current_step_index = 0
        sess.pending_user_message = None
        sess.replan_context = context_to_keep if context_to_keep else None
        sess.error = None
        sess.version += 1
        sess.status = "PLANNING" if draft.steps else "IDLE"
        if not sess.name:
            sess.name = "New chat"
        await db.commit()

        latest_user = await _latest_user_message(db=db, session_id=sess.session_id)
        quick_summary = draft.plan_explanation or "Execution plan created."
        plan_message = MessageRow(
            message_id=generate_uuid(),
            session_id=sess.session_id,
            role="assistant",
            content=quick_summary,
            mode=(latest_user.mode if latest_user else "normal"),
            tool_name="__plan__",
        )
        db.add(plan_message)
        await db.commit()

        # Two-phase response for better UX:
        # 1) quick summary appears immediately
        # 2) richer summary replaces it when ready
        try:
            summary = await summary_adapter.summarize_plan(intent=intent, draft=draft)
            summary_text = (summary.text or "").strip()
            if summary_text and summary_text != (plan_message.content or "").strip():
                plan_message.content = summary_text
            sess.llm_call_count += summary.llm_calls
            sess.version += 1
            await db.commit()
        except SummaryBackendError:
            pass
        return _plan_to_response(plan_row)

    async def _create_plan_approval(
        *,
        db: AsyncSession,
        sess: SessionRow,
        plan_row: PlanRow,
        tools_by_name: dict[str, ToolInfo],
    ) -> ApprovalRow:
        side_effect_level = "HIGH"
        for step in (
            await db.execute(
                select(PlanStepRow).where(PlanStepRow.plan_id == plan_row.plan_id).order_by(PlanStepRow.step_index.asc())
            )
        ).scalars().all():
            tool = tools_by_name.get(step.tool_name)
            if tool and tool.side_effect_level == "CRITICAL":
                side_effect_level = "CRITICAL"
                break
        approval = ApprovalRow(
            approval_id=generate_uuid(),
            session_id=sess.session_id,
            subject_type="plan",
            plan_id=plan_row.plan_id,
            step_id="",
            tool_name="__plan__",
            args={"plan_id": plan_row.plan_id, "plan_hash": plan_row.plan_hash},
            risk_summary=plan_row.risk_summary or "Approve this plan before execution.",
            side_effect_level=side_effect_level,
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        db.add(approval)
        plan_row.status = "PENDING_APPROVAL"
        sess.status = "WAITING_APPROVAL"
        sess.error = None
        sess.version += 1
        await db.commit()
        return approval

    async def _promote_discovery_to_execution(
        *,
        db: AsyncSession,
        sess: SessionRow,
        discovery_plan: PlanRow,
        tools_by_name: dict[str, ToolInfo],
    ) -> PlanRow | None:
        intent = sess.current_intent or ""
        selection = await tool_selector.select_tools(
            intent=intent,
            tools_by_name=tools_by_name,
            mode="normal",
            context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        )
        scoped_tools = [tools_by_name[name] for name in selection.tool_names if name in tools_by_name]
        planner_context = await memory_manager.build_planner_context(
            db,
            session_id=sess.session_id,
            intent=intent,
            base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        )
        try:
            generated = await planner.generate_plan(
                intent=intent,
                scoped_tools=scoped_tools,
                context=planner_context,
            )
        except (PlannerClarificationError, PlannerBackendError):
            return None

        sess.llm_call_count += selection.llm_calls
        sess.llm_call_count += generated.llm_calls
        context_to_keep = None
        intent_contract = getattr(generated, "intent_contract", None)
        if intent_contract:
            context_to_keep = dict(sess.replan_context or {})
            context_to_keep["intent_contract"] = intent_contract
        response = await _persist_plan(
            db=db,
            sess=sess,
            draft=generated.draft,
            tools_by_name=tools_by_name,
            backend_used=generated.backend_used,
            kind="execution",
            status="PENDING_APPROVAL",
            intent=intent,
            derived_from_plan_id=discovery_plan.plan_id,
            context_to_keep=context_to_keep,
        )
        plan_row = (await db.execute(select(PlanRow).where(PlanRow.plan_id == response.plan_id))).scalars().first()
        if not plan_row:
            return None
        await _create_plan_approval(db=db, sess=sess, plan_row=plan_row, tools_by_name=tools_by_name)
        discovery_plan.status = "COMPLETED"
        sess.completed_at = None
        sess.error = None
        await db.commit()
        return plan_row

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

    def require_admin(x_admin_key: str = Header(..., alias="X-Admin-Key")) -> None:
        if x_admin_key != settings.admin_api_key:
            raise HTTPException(status_code=403, detail="forbidden")

    def require_jwt(
        authorization: str | None = Header(None, alias="Authorization"),
        x_user_role: str | None = Header(None, alias="X-User-Role"),
    ) -> dict[str, Any]:
        try:
            claims = validate_bearer_token(authorization, settings=settings)
        except JwtValidationError as e:
            raise HTTPException(status_code=401, detail=str(e))
        if x_user_role and "role" not in claims and "user_role" not in claims:
            claims["role"] = x_user_role.strip().lower()
        claims.setdefault(
            "role",
            role_from_claims(claims, default="viewer" if settings.jwt_required else "admin"),
        )
        return claims

    async def load_session_snapshot(*, db: AsyncSession, session_id: str) -> SessionSnapshotResponse | None:
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            return None
        tools_by_name = await tool_registry.get_tools_by_name(db)

        current_plan = None
        if sess.plan_id:
            current_plan = (
                await db.execute(select(PlanRow).where(PlanRow.plan_id == sess.plan_id))
            ).scalars().first()

        plan_rows = (
            await db.execute(
                select(PlanRow)
                .where(PlanRow.session_id == session_id)
                .order_by(PlanRow.created_at.asc())
            )
        ).scalars().all()
        step_rows = (
            await db.execute(
                select(PlanStepRow)
                .where(PlanStepRow.session_id == session_id)
                .order_by(PlanStepRow.step_index.asc())
            )
        ).scalars().all()
        message_rows = (
            await db.execute(
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .order_by(MessageRow.created_at.asc())
            )
        ).scalars().all()
        approval_rows = (
            await db.execute(
                select(ApprovalRow)
                .where(ApprovalRow.session_id == session_id)
                .order_by(ApprovalRow.created_at.asc())
            )
        ).scalars().all()

        pending_approval = next((row for row in reversed(approval_rows) if row.status == "PENDING"), None)
        tool_result_messages = [row for row in message_rows if row.role == "tool_result"]
        user_messages = [row for row in message_rows if row.role == "user"]
        assistant_messages = [row for row in message_rows if row.role == "assistant"]
        plan_messages = [row for row in assistant_messages if row.tool_name == "__plan__"]
        conversation_messages = [row for row in assistant_messages if row.tool_name == "__conversation__"]
        confirmation_messages = [row for row in assistant_messages if row.tool_name == "__confirmation__"]
        step_ids_by_plan: dict[str, list[str]] = {}
        for step in step_rows:
            step_ids_by_plan.setdefault(step.plan_id, []).append(step.step_id)

        user_messages_sorted = sorted(user_messages, key=lambda m: m.created_at)

        def _turn_id_for_time(ts: datetime | None) -> str | None:
            if not user_messages_sorted:
                return None
            if ts is None:
                return user_messages_sorted[-1].message_id
            selected = None
            for msg in user_messages_sorted:
                if msg.created_at <= ts:
                    selected = msg
                else:
                    break
            return (selected or user_messages_sorted[-1]).message_id

        def _session_ctx() -> dict[str, Any]:
            return {
                "session_id": sess.session_id,
                "status": sess.status,
                "plan_version": sess.plan_version or 0,
                "current_step_index": sess.current_step_index or 0,
            }

        def _missing_required_fields(tool_name: str | None, args: dict[str, Any] | None) -> list[str]:
            if not tool_name:
                return []
            tool = tools_by_name.get(tool_name)
            schema = tool.input_schema if tool else {}
            required = schema.get("required") if isinstance(schema, dict) else None
            if not isinstance(required, list):
                return []
            payload = args if isinstance(args, dict) else {}
            missing: list[str] = []
            for key in required:
                if not isinstance(key, str) or not key:
                    continue
                if key not in payload or payload.get(key) is None or payload.get(key) == "":
                    missing.append(key)
            return missing

        def _approval_entity_label(tool: ToolInfo | None, tool_name: str, args: dict[str, Any] | None) -> str:
            payload = args if isinstance(args, dict) else {}
            if tool:
                for tag in tool.capability_tags or []:
                    normalized = str(tag).strip().lower()
                    if normalized and normalized not in _APPROVAL_AUX_TAGS:
                        entity = normalized
                        break
                else:
                    entity = ""
                if not entity:
                    endpoint = (tool.endpoint or "").strip("/").split("/", 1)[0]
                    entity = endpoint[:-1] if endpoint.endswith("s") else endpoint
            else:
                entity = ""

            if not entity:
                lower_name = (tool_name or "").lower()
                if "machine" in lower_name:
                    entity = "machine"
                elif "inventory" in lower_name or "material" in lower_name:
                    entity = "inventory item"
                elif "job" in lower_name:
                    entity = "job"
                elif "proposal" in lower_name:
                    entity = "proposal"
                else:
                    entity = "record"

            target = (
                payload.get("machine_id")
                or payload.get("job_id")
                or payload.get("inventory_id")
                or payload.get("material_id")
                or payload.get("proposal_id")
                or payload.get("approval_id")
                or payload.get("id")
            )
            if target not in (None, ""):
                return f"{entity} {target}"
            return entity

        def _approval_action_phrase(approval: ApprovalRow, tool: ToolInfo | None) -> str:
            if (getattr(approval, "subject_type", "step") or "step") == "plan":
                return "execution plan"
            method = (tool.method if tool else "").upper()
            entity_label = _approval_entity_label(tool, approval.tool_name, approval.args)
            if method == "POST":
                return f"create {entity_label}"
            if method in {"PUT", "PATCH"}:
                return f"update {entity_label}"
            if method == "DELETE":
                return f"delete {entity_label}"
            return f"change {entity_label}"

        def _approval_decision_text(approval: ApprovalRow, tool: ToolInfo | None) -> str:
            decision = "approved" if approval.status == "APPROVED" else "rejected"
            phrase = _approval_action_phrase(approval, tool)
            content = f"{decision.capitalize()} request to {phrase}."
            if approval.rejection_reason:
                content = f"{content[:-1]}: {approval.rejection_reason}"
            return content

        def _is_noop_plan(plan_row: PlanRow | None) -> bool:
            if not plan_row:
                return False
            if (plan_row.created_by or "") != "system":
                return False
            if (plan_row.status or "") != "COMPLETED":
                return False
            return len(step_ids_by_plan.get(plan_row.plan_id, [])) == 0

        events: list[TimelineEventResponse] = []
        for msg in user_messages:
            events.append(
                _timeline_event(
                    event_id=f"user:{msg.message_id}",
                    event_type="user_message",
                    content=msg.content,
                    created_at=msg.created_at,
                    role="user",
                    mode=(getattr(msg, "mode", None) or "normal"),
                    turn_id=msg.message_id,
                    step_context={**_session_ctx(), "message_id": msg.message_id},
                )
            )

        for msg in conversation_messages:
            events.append(
                _timeline_event(
                    event_id=f"conversation:{msg.message_id}",
                    event_type="session_completed",
                    content=msg.content,
                    created_at=msg.created_at,
                    status="COMPLETED",
                    role="assistant",
                    mode=(getattr(msg, "mode", None) or "normal"),
                    turn_id=_turn_id_for_time(msg.created_at),
                    step_context={**_session_ctx(), "message_id": msg.message_id},
                )
            )

        confirmation_request = None
        if isinstance(sess.replan_context, dict):
            maybe = sess.replan_context.get("confirmation_request")
            if isinstance(maybe, dict):
                confirmation_request = maybe
        for msg in confirmation_messages:
            events.append(
                _timeline_event(
                    event_id=f"confirmation:{msg.message_id}",
                    event_type="confirmation_required",
                    content=msg.content,
                    created_at=msg.created_at,
                    status="WAITING_CONFIRMATION",
                    role="assistant",
                    mode=(getattr(msg, "mode", None) or "normal"),
                    turn_id=_turn_id_for_time(msg.created_at),
                    step_context={**_session_ctx(), "message_id": msg.message_id},
                    details={"confirmation": confirmation_request},
                )
            )

        for idx, plan_row in enumerate(plan_rows):
            if _is_noop_plan(plan_row):
                continue
            plan_message = plan_messages[idx] if idx < len(plan_messages) else None
            content = (
                plan_message.content
                if plan_message and plan_message.content
                else (plan_row.plan_explanation or "Execution plan created.")
            )
            events.append(
                _timeline_event(
                    event_id=f"plan:{plan_row.plan_id}",
                    event_type="plan_created",
                    content=content,
                    created_at=plan_row.created_at,
                    status="PLANNING",
                    mode=(plan_message.mode if plan_message and getattr(plan_message, "mode", None) else None),
                    turn_id=_turn_id_for_time(plan_row.created_at),
                    step_context={**_session_ctx(), "plan_id": plan_row.plan_id, "plan_version": plan_row.version},
                    details={
                        "plan_id": plan_row.plan_id,
                        "version": plan_row.version,
                        "kind": plan_row.kind,
                        "status": plan_row.status,
                        "plan_explanation": plan_row.plan_explanation,
                        "risk_summary": plan_row.risk_summary,
                    },
                )
            )
            if plan_row.invalidated_at:
                reason = plan_row.invalidated_reason or "replan requested"
                events.append(
                    _timeline_event(
                        event_id=f"replan:{plan_row.plan_id}",
                        event_type="replan_requested",
                        content=f"Replan requested: {reason}.",
                        created_at=plan_row.invalidated_at,
                        status="PLANNING",
                        turn_id=_turn_id_for_time(plan_row.invalidated_at),
                        step_context={**_session_ctx(), "plan_id": plan_row.plan_id, "plan_version": plan_row.version},
                        details={"plan_id": plan_row.plan_id, "reason": reason},
                    )
                )

        execution_started_at = min((step.started_at for step in step_rows if step.started_at), default=None)
        if execution_started_at:
            events.append(
                _timeline_event(
                    event_id=f"exec:{session_id}",
                    event_type="execution_started",
                    content="Execution started.",
                    created_at=execution_started_at,
                    status="EXECUTING",
                    turn_id=_turn_id_for_time(execution_started_at),
                    step_context=_session_ctx(),
                )
            )

        tool_messages_by_step = {msg.step_id: msg for msg in tool_result_messages if msg.step_id}
        for step in step_rows:
            if step.status == "IN_PROGRESS" and step.started_at:
                events.append(
                    _timeline_event(
                        event_id=f"step-started:{step.step_id}",
                        event_type="tool_started",
                        content="Step started.",
                        created_at=step.started_at,
                        turn_id=_turn_id_for_time(step.started_at),
                        step_context={
                            **_session_ctx(),
                            "step_id": step.step_id,
                            "step_index": step.step_index,
                            "tool_name": step.tool_name,
                            "approval_id": step.approval_id,
                        },
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        status=step.status,
                        details={"args": step.args},
                    )
                )
                continue

            if step.step_id in tool_messages_by_step:
                msg = tool_messages_by_step[step.step_id]
                created_at = msg.created_at
                content = msg.content
            elif step.status in ("DONE", "FAILED", "AMBIGUOUS") and (step.completed_at or step.started_at):
                created_at = step.completed_at or step.started_at
                content = (
                    step.result_summary
                    or (f"{step.tool_name} failed: {step.last_error}" if step.status == "FAILED" else f"{step.tool_name} completed.")
                )
            else:
                continue

            events.append(
                _timeline_event(
                    event_id=f"step:{step.step_id}",
                    event_type="tool_result",
                    content=content,
                    created_at=created_at,
                    turn_id=_turn_id_for_time(created_at),
                    step_context={
                        **_session_ctx(),
                        "step_id": step.step_id,
                        "step_index": step.step_index,
                        "tool_name": step.tool_name,
                        "approval_id": step.approval_id,
                    },
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    status=step.status,
                    details=_build_tool_result_details(
                        tool_name=step.tool_name,
                        args=step.args,
                        result=step.result,
                        last_error=step.last_error,
                        content=content,
                        intent=sess.current_intent,
                    ),
                )
            )

        for approval in approval_rows:
            tool = tools_by_name.get(approval.tool_name)
            missing_required = _missing_required_fields(approval.tool_name, approval.args)
            tool_schema = tool.input_schema if tool else None
            if approval.status == "PENDING":
                events.append(
                    _timeline_event(
                        event_id=f"approval-required:{approval.approval_id}",
                        event_type="approval_required",
                        content=(
                            "Waiting for your approval."
                            if not approval.risk_summary
                            else f"Waiting for your approval: {approval.risk_summary}"
                        ),
                        created_at=approval.created_at,
                        turn_id=_turn_id_for_time(approval.created_at),
                        step_context={
                            **_session_ctx(),
                            "approval_id": approval.approval_id,
                            "step_id": approval.step_id,
                            "tool_name": approval.tool_name,
                        },
                        approval_id=approval.approval_id,
                        step_id=approval.step_id,
                        tool_name=approval.tool_name,
                        status=approval.status,
                        details={
                            "subject_type": getattr(approval, "subject_type", "step"),
                            "plan_id": getattr(approval, "plan_id", None),
                            "args": approval.args,
                            "side_effect_level": approval.side_effect_level,
                            "expires_at": approval.expires_at.isoformat(),
                            "tool": {
                                "name": tool.name if tool else approval.tool_name,
                                "description": tool.description if tool else None,
                                "method": tool.method if tool else None,
                                "endpoint": tool.endpoint if tool else None,
                            },
                            "input_schema": tool_schema,
                            "missing_required": missing_required,
                        },
                    )
                )
            if approval.decided_at:
                content = _approval_decision_text(approval, tool)
                events.append(
                    _timeline_event(
                        event_id=f"approval-decided:{approval.approval_id}",
                        event_type="approval_decided",
                        content=content,
                        created_at=approval.decided_at,
                        turn_id=_turn_id_for_time(approval.decided_at),
                        step_context={
                            **_session_ctx(),
                            "approval_id": approval.approval_id,
                            "step_id": approval.step_id,
                            "tool_name": approval.tool_name,
                        },
                        approval_id=approval.approval_id,
                        step_id=approval.step_id,
                        tool_name=approval.tool_name,
                        status=approval.status,
                        details={
                            "subject_type": getattr(approval, "subject_type", "step"),
                            "plan_id": getattr(approval, "plan_id", None),
                            "decided_by": approval.decided_by,
                            "rejection_reason": approval.rejection_reason,
                        },
                    )
                )

        ambiguous_step = next((step for step in step_rows if step.status == "AMBIGUOUS" and (step.completed_at or step.started_at)), None)
        if sess.status == "BLOCKED":
            blocked_at = (ambiguous_step.completed_at if ambiguous_step and ambiguous_step.completed_at else sess.updated_at)
            events.append(
                _timeline_event(
                    event_id=f"blocked:{session_id}",
                    event_type="session_blocked",
                    content=sess.error or "Execution blocked.",
                    created_at=blocked_at,
                    status=sess.status,
                    turn_id=_turn_id_for_time(blocked_at),
                    step_context=_session_ctx(),
                )
            )
        if sess.status == "FAILED":
            events.append(
                _timeline_event(
                    event_id=f"failed:{session_id}",
                    event_type="session_failed",
                    content=sess.error or "Session failed.",
                    created_at=sess.updated_at,
                    status=sess.status,
                    turn_id=_turn_id_for_time(sess.updated_at),
                    step_context=_session_ctx(),
                )
            )
        if sess.completed_at:
            completion_message = next((msg for msg in reversed(assistant_messages) if "Execution completed successfully" in msg.content), None)
            events.append(
                _timeline_event(
                    event_id=f"completed:{session_id}",
                    event_type="session_completed",
                    content=(
                        completion_message.content
                        if completion_message and completion_message.content
                        else "Execution completed successfully."
                    ),
                    created_at=sess.completed_at,
                    status="COMPLETED",
                    turn_id=_turn_id_for_time(sess.completed_at),
                    step_context=_session_ctx(),
                )
            )

        events.sort(
            key=lambda event: (
                event.created_at,
                _TIMELINE_EVENT_PRIORITY.get(event.event_type, 99),
                event.event_id,
            )
        )
        return SessionSnapshotResponse(
            session=_session_to_response(sess),
            plan=_plan_to_response(current_plan) if current_plan and not _is_noop_plan(current_plan) else None,
            steps=[_step_to_response(step) for step in step_rows],
            pending_approval=_approval_to_response(pending_approval) if pending_approval else None,
            timeline=events,
        )

    @router.post("/sessions", response_model=SessionResponse)
    async def create_session(
        req: SessionCreateRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.create_session(
            db,
            user_id=req.user_id,
            name=_normalize_session_name(req.name) or "New chat",
        )
        return _session_to_response(sess)

    @router.get("/sessions", response_model=list[SessionResponse])
    async def list_sessions(
        user_id: str | None = Query(None),
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(SessionRow).order_by(SessionRow.updated_at.desc())
        if user_id:
            stmt = stmt.where(SessionRow.user_id == user_id)
        rows = (await db.execute(stmt)).scalars().all()
        return [_session_to_response(row) for row in rows]

    @router.get("/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        return _session_to_response(sess)

    @router.delete("/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")

        # Manual cleanup (no ORM cascades configured).
        await db.execute(delete(MessageRow).where(MessageRow.session_id == session_id))
        await db.execute(delete(ApprovalRow).where(ApprovalRow.session_id == session_id))
        await db.execute(delete(DeadLetterRow).where(DeadLetterRow.session_id == session_id))
        await db.execute(delete(PlanStepRow).where(PlanStepRow.session_id == session_id))
        await db.execute(delete(PlanRow).where(PlanRow.session_id == session_id))
        await db.execute(delete(ExecutionSnapshotRow).where(ExecutionSnapshotRow.session_id == session_id))

        await db.execute(delete(SessionRow).where(SessionRow.session_id == session_id))
        await db.commit()

        return {"ok": True, "session_id": session_id}

    @router.patch("/sessions/{session_id}", response_model=SessionResponse)
    async def update_session(
        session_id: str,
        req: SessionUpdateRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        sess.name = _normalize_session_name(req.name)
        sess.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(sess)
        return _session_to_response(sess)

    @router.get("/sessions/{session_id}/snapshot", response_model=SessionSnapshotResponse)
    async def get_session_snapshot(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        snapshot = await load_session_snapshot(db=db, session_id=session_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="session not found")
        return snapshot

    @router.get("/tools", response_model=list[ToolInfo])
    async def list_tools(
        intent: str | None = Query(None, description="Optional user intent to scope tools."),
        max_tools: int = Query(30, ge=1, le=200, description="Maximum tools returned."),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        tools_by_name = await tool_registry.get_tools_by_name(db)
        tools_by_name = filter_tools_for_role(tools_by_name, role=role_from_claims(user))
        if intent:
            selection = await tool_selector.select_tools(intent=intent, tools_by_name=tools_by_name, max_tools=max_tools)
            return [tools_by_name[name] for name in selection.tool_names if name in tools_by_name]
        names = sorted(tools_by_name.keys())[:max_tools]
        return [tools_by_name[name] for name in names]

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
                        _log_step_status(sess, step, step.status)
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
        return [_message_to_response(r) for r in rows]

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
        return _session_to_response(sess)

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
        return [_step_to_response(r) for r in rows]

    @router.post(
        "/sessions/{session_id}/plans",
        response_model=PlanResponse,
        responses={400: {"model": ValidationErrorResponse}},
    )
    async def create_plan(
        session_id: str,
        req: PlanCreateRequest,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        started = time.perf_counter()
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")

        intent = sess.current_intent or ""
        latest_user = await _latest_user_message(db=db, session_id=session_id)
        mode = latest_user.mode if latest_user else "normal"
        assessment = assess_intent(intent)
        
        if assessment.kind == "operations" and intent:
            route_decision = await query_router.route(intent)
            route_type = route_decision.get("route", "API_ONLY")
            route_source = route_decision.get("route_source", "unknown")
            if not isinstance(sess.replan_context, dict):
                sess.replan_context = {}
            sess.replan_context["route_decision"] = route_decision
            log_event(
                "query_routed",
                session_id=session_id,
                intent=intent,
                route=route_type,
                route_source=route_source
            )
            
            if route_type == "RAG_ONLY":
                tools_by_name = await tool_registry.get_tools_by_name(db)
                reply = "RAG lookup will be performed for: " + intent
                plan_resp = await _persist_conversation_reply_as_empty_plan(
                    db=db,
                    sess=sess,
                    reply=reply,
                    mode=mode,
                    tools_by_name=tools_by_name,
                    intent=intent,
                )
                metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
                return plan_resp

            if route_type == "CLARIFY":
                tools_by_name = await tool_registry.get_tools_by_name(db)
                clarify_reason = route_decision.get("clarify_reason") or "the request is missing required specifics"
                reply = f"I need clarification before execution: {clarify_reason}."
                plan_resp = await _persist_conversation_reply_as_empty_plan(
                    db=db,
                    sess=sess,
                    reply=reply,
                    mode=mode,
                    tools_by_name=tools_by_name,
                    intent=intent,
                    context_to_keep=sess.replan_context,
                )
                metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
                return plan_resp

            if route_type == "API_THEN_RAG":
                sess.replan_context["rag_required"] = True
            if route_type == "RAG_THEN_API":
                sess.replan_context["rag_context_required"] = True

        tools_by_name = await tool_registry.get_tools_by_name(db)
        tools_by_name = filter_tools_for_role(tools_by_name, role=role_from_claims(user))
        backend_used = "langgraph" if req.draft is None else "client"
        draft = req.draft

        if assessment.kind != "operations":
            reply = assessment.reply or "I need an operation request before I can create a plan."
            plan_resp = await _persist_conversation_reply_as_empty_plan(
                db=db,
                sess=sess,
                reply=reply,
                mode=mode,
                tools_by_name=tools_by_name,
                intent=intent,
            )
            metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
            return plan_resp

        tools_by_name = await _ensure_registry_health(db=db)
        tools_by_name = filter_tools_for_role(tools_by_name, role=role_from_claims(user))
        if not tools_by_name:
            raise HTTPException(status_code=403, detail={"errors": ["No tools are allowed for this user role."]})

        selection = await tool_selector.select_tools(
            intent=intent,
            tools_by_name=tools_by_name,
            mode=mode,
            context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        )
        scoped_names = set(selection.tool_names)

        if draft is None:
            if not intent.strip():
                raise HTTPException(status_code=400, detail={"errors": ["Cannot auto-generate plan without a current intent."]})
            scoped_tools = [tools_by_name[name] for name in selection.tool_names if name in tools_by_name]
            if mode == "plan":
                scoped_tools = [tool for tool in scoped_tools if tool.is_read_only]
            context_to_keep: dict[str, Any] | None = None
            try:
                if scoped_tools:
                    planner_context = await memory_manager.build_planner_context(
                        db,
                        session_id=sess.session_id,
                        intent=intent,
                        base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
                    )
                    generated = await planner.generate_plan(
                        intent=intent,
                        scoped_tools=scoped_tools,
                        context=planner_context,
                    )
                    draft = generated.draft
                    backend_used = generated.backend_used
                    intent_contract = getattr(generated, "intent_contract", None)
                    if intent_contract:
                        context = dict(sess.replan_context or {})
                        context["intent_contract"] = intent_contract
                        sess.replan_context = context
                        context_to_keep = context
                    sess.llm_call_count += selection.llm_calls
                    sess.llm_call_count += generated.llm_calls
                else:
                    from ..schemas import PlanDraft

                    draft = PlanDraft(
                        plan_explanation="No safe discovery steps are required before preparing an execution proposal.",
                        risk_summary="This stage is read-only and performs no writes.",
                        steps=[],
                    )
                    backend_used = "system"
            except PlannerConfirmationRequired as e:
                plan_resp = await _persist_confirmation_request_as_empty_plan(
                    db=db,
                    sess=sess,
                    confirmation=e.confirmation,
                    mode=mode,
                    tools_by_name=tools_by_name,
                    intent=intent,
                )
                metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
                return plan_resp
            except PlannerClarificationError as e:
                reply = str(e)
                if ('could not safely map "' in reply and "Allowed " in reply) or (
                    'couldn\'t match "' in reply and "supported " in reply
                ):
                    context_to_keep = _remember_negative_predicate_bindings(
                        sess=sess,
                        bindings=getattr(e, "negative_bindings", []) or [],
                    )
                    plan_resp = await _persist_conversation_reply_as_empty_plan(
                        db=db,
                        sess=sess,
                        reply=reply,
                        mode=mode,
                        tools_by_name=tools_by_name,
                        intent=intent,
                        context_to_keep=context_to_keep,
                    )
                    metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
                    return plan_resp
                raise HTTPException(status_code=400, detail={"errors": [reply]}) from e
            except PlannerBackendError as e:
                raise HTTPException(status_code=503, detail={"errors": [str(e)]}) from e
            except Exception as e:
                log_event(
                    "planner_unexpected_exception",
                    level="ERROR",
                    session_id=session_id,
                    error=str(e),
                )
                raise HTTPException(status_code=503, detail={"errors": ["Planner failed unexpectedly. Please retry."]}) from e
            sess.version += 1
            await db.commit()
            metrics.inc("plan_backend_used_total", labels={"backend_used": backend_used})

        invalid_scoped = [s.tool_name for s in draft.steps if s.tool_name not in scoped_names]
        if invalid_scoped:
            raise HTTPException(status_code=400, detail={"errors": [f"Tool not allowed by scope: {t}" for t in invalid_scoped]})

        validation = validate_plan(draft, tools_by_name, max_steps=settings.max_plan_steps)
        if not validation.ok:
            metrics.inc("plan_validation_failure_total")
            metrics.inc("plan_validation_failure_rate")
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
                    db.add(
                        DeadLetterRow(
                            dlq_id=generate_uuid(),
                            session_id=session_id,
                            step_id=None,
                                failure_type="replan_limit_reached",
                                reason="Plan validation failed 3 consecutive times",
                                payload={"errors": validation.errors, "validation_failure_count": failures},
                                status="PENDING",
                            )
                        )
                await db.commit()
                raise HTTPException(status_code=400, detail={"errors": validation.errors})

        plan_kind = "discovery" if mode == "plan" else "execution"
        plan_status = "DRAFT"
        response = await _persist_plan(
            db=db,
            sess=sess,
            draft=draft,
            tools_by_name=tools_by_name,
            backend_used=backend_used,
            kind=plan_kind,
            status=plan_status,
            intent=intent,
            context_to_keep=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        )
        await memory_manager.save_checkpoint(
            db,
            session_id=sess.session_id,
            thread_id=sess.session_id,
            state={
                "status": sess.status,
                "plan_id": sess.plan_id,
                "plan_version": sess.plan_version,
                "current_step_index": sess.current_step_index,
                "step_count": sess.step_count,
                "replan_count": sess.replan_count,
                "llm_call_count": sess.llm_call_count,
            },
        )
        metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
        return response

    @router.post("/sessions/{session_id}/execute", response_model=SessionResponse)
    async def execute(
        session_id: str,
        background: bool = Query(False, description="If true, enqueue execution to the worker pool (when enabled)."),
        expected_version: int | None = Query(None, ge=1, description="Optional optimistic-lock expected session version."),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        if expected_version is not None and sess.version != expected_version:
            raise HTTPException(status_code=409, detail=f"version_conflict expected={expected_version} actual={sess.version}")
        current_plan = await _load_current_plan(db=db, session_id=session_id)
        if current_plan and current_plan.status == "COMPLETED":
            return _session_to_response(sess)
        if current_plan and current_plan.status == "PENDING_APPROVAL":
            pending_plan_approval = (
                await db.execute(
                    select(ApprovalRow)
                    .where(ApprovalRow.session_id == session_id)
                    .where(ApprovalRow.plan_id == current_plan.plan_id)
                    .where(ApprovalRow.subject_type == "plan")
                    .where(ApprovalRow.status == "PENDING")
                )
            ).scalars().first()
            if pending_plan_approval:
                return _session_to_response(sess)
        try:
            session_mgr.enforce_limits(sess)
        except TransitionError as e:
            raise HTTPException(status_code=429, detail=str(e))
        # Background execution only works when the worker pool is enabled.
        if background and settings.worker_count <= 0:
            background = False
        if current_plan and current_plan.kind == "discovery":
            background = False

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

        tools_by_name = await _ensure_registry_health(db=db)
        tools_by_name = filter_tools_for_role(tools_by_name, role=role_from_claims(user))
        await executor.execute_until_blocked(db, session=sess, tools_by_name=tools_by_name)
        sess = await session_mgr.get_session(db, session_id=session_id)
        current_plan = await _load_current_plan(db=db, session_id=session_id)
        if current_plan and current_plan.kind == "discovery" and sess and sess.status == "COMPLETED":
            promoted = await _promote_discovery_to_execution(
                db=db,
                sess=sess,
                discovery_plan=current_plan,
                tools_by_name=tools_by_name,
            )
            if promoted:
                sess = await session_mgr.get_session(db, session_id=session_id)
        return _session_to_response(sess)

    @router.post("/sessions/{session_id}/cancel", response_model=SessionResponse)
    async def cancel_session(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
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
                _log_step_status(sess, step, step.status)
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
    async def list_pending_approvals(
        session_id: str | None = Query(None),
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(ApprovalRow).where(ApprovalRow.status == "PENDING")
        if session_id:
            stmt = stmt.where(ApprovalRow.session_id == session_id)
        rows = (
            await db.execute(stmt.order_by(ApprovalRow.created_at.asc()))
        ).scalars().all()
        return [_approval_to_response(r) for r in rows]

    @router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
    async def get_approval(
        approval_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        return _approval_to_response(row)

    @router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
    async def approve_approval(
        approval_id: str,
        req: ApprovalDecisionRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")

        if (getattr(row, "subject_type", "step") or "step") == "plan":
            plan_row = None
            if getattr(row, "plan_id", None):
                plan_row = (await db.execute(select(PlanRow).where(PlanRow.plan_id == row.plan_id))).scalars().first()
            row.status = "APPROVED"
            row.decided_by = req.decided_by
            row.decided_at = datetime.utcnow()
            if plan_row:
                plan_row.status = "APPROVED"
                plan_row.approved_plan_hash = plan_row.plan_hash
            sess = await session_mgr.get_session(db, session_id=row.session_id)
            if sess:
                sess.status = "IDLE"
                sess.error = None
                sess.version += 1
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

        if req.args is not None:
            if not isinstance(req.args, dict):
                raise HTTPException(status_code=400, detail="args must be an object")
            tools_by_name = await tool_registry.get_tools_by_name(db)
            tool = tools_by_name.get(row.tool_name)
            if not tool:
                raise HTTPException(status_code=400, detail=f"unknown tool: {row.tool_name}")
            try:
                Draft202012Validator(tool.input_schema).validate(req.args)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"invalid args: {e}")

            row.args = req.args
            step = (await db.execute(select(PlanStepRow).where(PlanStepRow.step_id == row.step_id))).scalars().first()
            if step:
                step.args = req.args
                sess = await session_mgr.get_session(db, session_id=row.session_id)
                plan_version = (sess.plan_version or 0) if sess else 0
                step.idempotency_key = compute_idempotency_key(
                    session_id=row.session_id,
                    step_index=step.step_index,
                    plan_version=plan_version,
                    args=req.args,
                )

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
    async def reject_approval(
        approval_id: str,
        req: ApprovalDecisionRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        if (getattr(row, "subject_type", "step") or "step") == "plan":
            sess = await session_mgr.get_session(db, session_id=row.session_id)
            row.status = "REJECTED"
            row.decided_by = req.decided_by
            row.decided_at = datetime.utcnow()
            row.rejection_reason = req.rejection_reason
            if getattr(row, "plan_id", None):
                plan_row = (await db.execute(select(PlanRow).where(PlanRow.plan_id == row.plan_id))).scalars().first()
                if plan_row:
                    plan_row.status = "REJECTED"
            if sess:
                sess.status = "IDLE"
                sess.error = req.rejection_reason or f"Approval {row.approval_id} rejected"
                sess.updated_at = datetime.utcnow()
                sess.version += 1
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
        sess = await session_mgr.get_session(db, session_id=row.session_id)
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
            if sess:
                _log_step_status(sess, step, step.status)
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
    async def push_dlq(
        req: DeadLetterPushRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
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
        metrics.inc("dlq_push_total", labels={"failure_type": req.failure_type})
        metrics.inc("dlq_push_rate", labels={"failure_type": req.failure_type})
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
    async def replay_dlq(
        dlq_id: str,
        req: DeadLetterReplayRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        row = (await db.execute(select(DeadLetterRow).where(DeadLetterRow.dlq_id == dlq_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="dlq entry not found")
        sess = await session_mgr.get_session(db, session_id=row.session_id)
        if row.step_id:
            step = (await db.execute(select(PlanStepRow).where(PlanStepRow.step_id == row.step_id))).scalars().first()
            if step:
                step.status = "NOT_STARTED"
                step.last_error = None
                step.started_at = None
                step.completed_at = None
                step.retry_count = 0
                if sess:
                    _log_step_status(sess, step, step.status)
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
        metrics.inc("dlq_replay_total")
        metrics.inc("dlq_replay_success_total")
        metrics.inc("dlq_replay_success_rate")
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
    async def request_dlq_replay(
        dlq_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        return await replay_dlq(dlq_id, DeadLetterReplayRequest(), {}, db)

    @router.post("/dlq/{dlq_id}/dismiss")
    async def dismiss_dlq(
        dlq_id: str,
        req: DeadLetterDismissRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
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
    async def regenerate_tools(
        _: None = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
    ):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        local_swagger = os.path.join(repo_root, "emas", "docs", "swagger.json")
        openapi_url = os.environ.get("OPENAPI_URL", "http://localhost:8080/swagger/doc.json")
        force_local = os.environ.get("OPENAPI_LOCAL", "").strip() == "1" or os.path.exists(local_swagger)

        result = await tool_registry.regenerate_from_openapi(
            db,
            openapi_url=openapi_url,
            local_swagger_json_path=local_swagger,
            force_local=force_local,
            replace_db=True,
        )
        await event_bus.publish(
            AgentEvent(
                event_type="tool_registry_updated",
                session_id="",
                payload={"tool_count": result.tool_count, "tools_md_hash": result.tools_md_hash},
                published_at=datetime.utcnow(),
            )
        )
        log_event("tool_registry_regenerated", tool_count=result.tool_count, tools_md_hash=result.tools_md_hash)
        return {"ok": True, "tool_count": result.tool_count, "tools_md_hash": result.tools_md_hash}

    @router.get("/metrics", response_class=PlainTextResponse)
    async def get_metrics():
        return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")

    @router.get("/admin/sessions", dependencies=[Depends(require_admin)])
    async def admin_list_sessions(
        status: str | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(SessionRow).order_by(SessionRow.updated_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(SessionRow.status == status)
        rows = (await db.execute(stmt)).scalars().all()
        return [_session_to_response(s) for s in rows]

    @router.get("/admin/approvals/pending", dependencies=[Depends(require_admin)], response_model=list[ApprovalResponse])
    async def admin_pending_approvals(db: AsyncSession = Depends(get_db)):
        rows = (
            await db.execute(select(ApprovalRow).where(ApprovalRow.status == "PENDING").order_by(ApprovalRow.created_at.asc()))
        ).scalars().all()
        return [_approval_to_response(r) for r in rows]

    @router.get("/admin/dlq", dependencies=[Depends(require_admin)], response_model=list[DeadLetterResponse])
    async def admin_list_dlq(
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

    @router.get("/admin/tools", dependencies=[Depends(require_admin)])
    async def admin_list_tools(db: AsyncSession = Depends(get_db)):
        tools_by_name = await tool_registry.get_tools_by_name(db)
        return [tools_by_name[name] for name in sorted(tools_by_name.keys())]

    @router.post("/admin/faults/redis/down", dependencies=[Depends(require_admin)])
    async def admin_fault_redis_down():
        # Fault injection hook for chaos testing (E4.3).
        setattr(event_bus, "_fault_injected", True)
        setattr(event_bus, "_healthy", False)
        return {"ok": True, "redis_fault": "down"}

    @router.post("/admin/faults/redis/up", dependencies=[Depends(require_admin)])
    async def admin_fault_redis_up():
        setattr(event_bus, "_fault_injected", False)
        with contextlib.suppress(Exception):
            await event_bus.reconnect()
        return {"ok": True, "redis_fault": "up"}

    @router.get("/admin/dashboard", dependencies=[Depends(require_admin)], response_class=HTMLResponse)
    async def admin_dashboard(db: AsyncSession = Depends(get_db)):
        sessions = (
            await db.execute(select(SessionRow).order_by(SessionRow.updated_at.desc()).limit(200))
        ).scalars().all()
        approvals = (
            await db.execute(select(ApprovalRow).where(ApprovalRow.status == "PENDING").order_by(ApprovalRow.created_at.asc()))
        ).scalars().all()
        dlq_rows = (
            await db.execute(select(DeadLetterRow).where(DeadLetterRow.status == "PENDING").order_by(DeadLetterRow.created_at.desc()))
        ).scalars().all()
        tools_by_name = await tool_registry.get_tools_by_name(db)

        session_rows = "".join(
            f"<tr><td>{s.session_id}</td><td>{s.user_id}</td><td>{s.status}</td><td>{s.current_step_index}</td><td>{s.error or ''}</td></tr>"
            for s in sessions
        )
        approval_rows = "".join(
            f"<tr><td>{a.approval_id}</td><td>{a.session_id}</td><td>{a.tool_name}</td><td>{a.status}</td></tr>"
            for a in approvals
        )
        dlq_html_rows = "".join(
            f"<tr><td>{d.dlq_id}</td><td>{d.session_id}</td><td>{d.failure_type}</td><td>{d.reason}</td></tr>"
            for d in dlq_rows
        )
        tool_rows = "".join(
            f"<tr><td>{t.name}</td><td>{t.method}</td><td>{t.endpoint}</td><td>{'yes' if t.requires_approval else 'no'}</td></tr>"
            for t in sorted(tools_by_name.values(), key=lambda x: x.name)
        )

        html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Factory Agent Admin Dashboard</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, sans-serif; margin: 24px; background: #f2f7fb; color: #112; }}
    h1 {{ margin: 0 0 8px 0; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
    section {{ background: #fff; border-radius: 12px; padding: 14px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #e7edf4; }}
    th {{ background: #eef5ff; }}
  </style>
</head>
<body>
  <h1>Factory Agent Dashboard</h1>
  <p>Sessions: {len(sessions)} | Pending approvals: {len(approvals)} | Pending DLQ: {len(dlq_rows)} | Tools: {len(tools_by_name)}</p>
  <div class="grid">
    <section>
      <h2>Sessions</h2>
      <table><thead><tr><th>Session</th><th>User</th><th>Status</th><th>Step</th><th>Error</th></tr></thead><tbody>{session_rows}</tbody></table>
    </section>
    <section>
      <h2>Approval Queue</h2>
      <table><thead><tr><th>Approval</th><th>Session</th><th>Tool</th><th>Status</th></tr></thead><tbody>{approval_rows}</tbody></table>
    </section>
    <section>
      <h2>DLQ Viewer</h2>
      <table><thead><tr><th>DLQ</th><th>Session</th><th>Failure Type</th><th>Reason</th></tr></thead><tbody>{dlq_html_rows}</tbody></table>
    </section>
    <section>
      <h2>Tool Registry</h2>
      <table><thead><tr><th>Name</th><th>Method</th><th>Endpoint</th><th>Approval</th></tr></thead><tbody>{tool_rows}</tbody></table>
    </section>
  </div>
</body>
</html>
"""
        return HTMLResponse(content=html)

    return router


