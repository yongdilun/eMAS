from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from ...persistence.models import Session as SessionRow
from ...persistence.models import Plan as PlanRow
from ...persistence.models import PlanStep as PlanStepRow
from ...schemas import ToolInfo
from ...observability.metrics import metrics
from ...observability.telemetry import log_event
from .tool_caller import ToolHTTPError, ToolNetworkError, ToolInputError
from .predicate_guard import PredicateVerificationError
from .dlq import push_dlq


FailureDecision = Literal["RETRY", "REPLAN", "FAIL_HARD", "AMBIGUOUS"]


def classify_error(err: Exception, tool: ToolInfo, step: PlanStepRow) -> FailureDecision:
    from ..execution.parallel import AmbiguousExecutionError
    if isinstance(err, AmbiguousExecutionError):
        return "AMBIGUOUS"
    if isinstance(err, PredicateVerificationError):
        return "REPLAN"
    if isinstance(err, ToolNetworkError):
        if tool.is_strongly_idempotent and step.retry_count < step.max_retries:
            return "RETRY"
        if err.request_was_sent:
            return "AMBIGUOUS"
        return "REPLAN"

    if isinstance(err, ToolHTTPError):
        status_code = err.status_code
        if status_code in (400, 404, 409):
            return "REPLAN"
        if status_code in (401, 403):
            return "FAIL_HARD"
        if status_code >= 500:
            if tool.is_strongly_idempotent and step.retry_count < step.max_retries:
                return "RETRY"
            return "REPLAN"
        return "FAIL_HARD"

    if isinstance(err, ToolInputError):
        return "REPLAN"

    return "FAIL_HARD"


def build_replan_context(
    session: SessionRow,
    steps: list[PlanStepRow],
    failed_step: PlanStepRow | None,
    reason: str,
    user_message: str | None = None,
) -> dict[str, Any]:
    completed = []
    for s in steps:
        if s.status == "DONE":
            completed.append(
                {
                    "step_index": s.step_index,
                    "tool_name": s.tool_name,
                    "args": s.args,
                    "result": s.result,
                }
            )
    context: dict[str, Any] = {
        "original_intent": session.current_intent,
        "plan_id": session.plan_id,
        "plan_version": session.plan_version,
        "completed_steps": completed,
        "error": reason,
        "failed_step": None,
    }
    if failed_step is not None:
        context["failed_step"] = {
            "step_id": failed_step.step_id,
            "step_index": failed_step.step_index,
            "tool_name": failed_step.tool_name,
            "args": failed_step.args,
            "last_error": failed_step.last_error,
        }
    if user_message:
        context["user_message"] = user_message
    return context


async def trigger_replan(
    engine: Any,
    db: Any,
    *,
    session: SessionRow,
    plan: PlanRow,
    steps: list[PlanStepRow],
    failed_step: PlanStepRow | None,
    reason: str,
    user_message: str | None = None,
) -> Any:
    from .engine import ExecuteResult
    if failed_step is not None:
        failed_step.status = "FAILED"
        failed_step.last_error = reason
        failed_step.completed_at = datetime.utcnow()
        engine._log_step_status_change(
            session=session,
            plan=plan,
            step=failed_step,
            tool=None,
            status=failed_step.status,
        )

    if not plan.invalidated_at:
        plan.invalidated_at = datetime.utcnow()
        plan.invalidated_reason = reason

    session.replan_count += 1
    metrics.inc("replan_total")
    metrics.inc("replan_rate")
    session.plan_version = (session.plan_version or 0) + 1
    session.replan_context = build_replan_context(
        session=session,
        steps=steps,
        failed_step=failed_step,
        reason=reason,
        user_message=user_message,
    )
    session.pending_user_message = None

    if reason.startswith("predicate_") and session.replan_count > max(0, int(engine._settings.intent_repair_attempts)):
        session.status = "BLOCKED"
        session.error = f"Predicate repair attempts exceeded ({reason})"
        session.version += 1
        await db.commit()
        await push_dlq(
            db,
            session_id=session.session_id,
            step_id=failed_step.step_id if failed_step else None,
            failure_type="predicate_repair_limit_reached",
            reason=reason,
            payload=session.replan_context or {},
        )
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

    if session.replan_count >= engine._settings.max_replans:
        session.status = "BLOCKED"
        session.error = f"Session exceeded MAX_REPLANS ({reason})"
        session.version += 1
        await db.commit()
        await push_dlq(
            db,
            session_id=session.session_id,
            step_id=failed_step.step_id if failed_step else None,
            failure_type="replan_limit_reached",
            reason=reason,
            payload=session.replan_context or {},
        )
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

    session.status = "PLANNING"
    session.error = reason
    session.version += 1
    await db.commit()
    log_event(
        "session_replan_triggered",
        level="WARNING",
        session_id=session.session_id,
        plan_id=plan.plan_id,
        reason=reason,
        replan_count=session.replan_count,
        failed_step_id=failed_step.step_id if failed_step else None,
    )
    return ExecuteResult(status=session.status, current_step_index=session.current_step_index)


async def fail_hard(
    engine: Any,
    db: Any,
    *,
    session: SessionRow,
    step: PlanStepRow,
    reason: str,
    failure_type: str,
    payload: dict[str, Any],
) -> Any:
    from .engine import ExecuteResult
    step.status = "FAILED"
    step.last_error = reason
    step.completed_at = datetime.utcnow()
    engine._log_step_status_change(session=session, plan=None, step=step, tool=None, status=step.status)
    session.status = "FAILED"
    session.error = reason
    session.version += 1
    await db.commit()
    metrics.inc("session_failed_total", labels={"reason": failure_type})
    metrics.observe("steps_per_session", float(session.step_count))
    log_event(
        "session_failed",
        level="ERROR",
        session_id=session.session_id,
        step_id=step.step_id,
        tool=step.tool_name,
        failure_type=failure_type,
        reason=reason,
    )
    await push_dlq(
        db,
        session_id=session.session_id,
        step_id=step.step_id,
        failure_type=failure_type,
        reason=reason,
        payload=payload,
    )
    return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
