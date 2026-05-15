from __future__ import annotations

from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import DeadLetter as DeadLetterRow
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.schemas import (
    ApprovalResponse,
    DeadLetterResponse,
    MessageResponse,
    PlanResponse,
    PlanStepResponse,
    SessionResponse,
)


def normalize_session_name(name: str | None) -> str | None:
    normalized = (name or "").strip()
    return normalized or None


def session_to_response(session: SessionRow) -> SessionResponse:
    return SessionResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        name=normalize_session_name(getattr(session, "name", None)),
        status=session.status,
        current_intent=session.current_intent,
        plan_id=session.plan_id,
        operation_id=session.plan_id,
        plan_version=session.plan_version or 0,
        plan_hash=session.plan_hash,
        current_step_index=session.current_step_index or 0,
        step_count=session.step_count or 0,
        replan_count=session.replan_count or 0,
        llm_call_count=session.llm_call_count or 0,
        session_started_at=session.session_started_at,
        replan_context=session.replan_context,
        pending_user_message=session.pending_user_message,
        created_at=session.created_at,
        updated_at=session.updated_at,
        completed_at=session.completed_at,
        error=session.error,
    )


def message_to_response(message: MessageRow) -> MessageResponse:
    return MessageResponse(
        message_id=message.message_id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        mode=(getattr(message, "mode", None) or "normal"),
        created_at=message.created_at,
        step_id=message.step_id,
        tool_name=message.tool_name,
    )


def plan_to_response(plan: PlanRow) -> PlanResponse:
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
        sources=plan.sources or [],
        safety_content=plan.safety_content,
        created_at=plan.created_at,
        created_by=plan.created_by,
    )


def step_to_response(step: PlanStepRow) -> PlanStepResponse:
    return PlanStepResponse(
        step_id=step.step_id,
        plan_id=step.plan_id,
        session_id=step.session_id,
        step_index=step.step_index,
        tool_name=step.tool_name,
        args=step.args or {},
        execution_mode=(getattr(step, "execution_mode", None) or "single"),
        bindings=getattr(step, "bindings", None) or [],
        bulk_state=getattr(step, "bulk_state", None),
        status=step.status,
        idempotency_key=step.idempotency_key,
        requires_approval=bool(step.requires_approval),
        approval_id=step.approval_id,
        retry_count=step.retry_count or 0,
        max_retries=step.max_retries or 0,
        last_error=step.last_error,
        result=step.result,
        result_summary=step.result_summary,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


def approval_to_response(approval: ApprovalRow) -> ApprovalResponse:
    return ApprovalResponse(
        approval_id=approval.approval_id,
        session_id=approval.session_id,
        subject_type=(getattr(approval, "subject_type", None) or "step"),
        plan_id=getattr(approval, "plan_id", None),
        step_id=(approval.step_id or None),
        tool_name=approval.tool_name,
        args=approval.args,
        risk_summary=approval.risk_summary,
        side_effect_level=approval.side_effect_level,
        status=approval.status,
        expires_at=approval.expires_at,
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        rejection_reason=approval.rejection_reason,
        created_at=approval.created_at,
    )


def dead_letter_to_response(dead_letter: DeadLetterRow) -> DeadLetterResponse:
    return DeadLetterResponse(
        dlq_id=dead_letter.dlq_id,
        session_id=dead_letter.session_id,
        step_id=dead_letter.step_id,
        failure_type=dead_letter.failure_type,
        reason=dead_letter.reason,
        payload=dead_letter.payload,
        status=dead_letter.status,
        replayed_at=dead_letter.replayed_at,
        replayed_by=dead_letter.replayed_by,
        dismissed_at=dead_letter.dismissed_at,
        dismissed_reason=dead_letter.dismissed_reason,
        created_at=dead_letter.created_at,
    )
