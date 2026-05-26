from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.analysis.presentation import extract_table_from_result
from factory_agent.analysis.result_normalizer import normalize_tool_result
from factory_agent.api.response_mappers import approval_to_response, plan_to_response, session_to_response, step_to_response
from factory_agent.graph.session_detection import (
    allows_persisted_step_projection,
    is_graph_native_session,
)
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.planning.intent import assess_intent
from factory_agent.planning.tool_output_alignment import summarize_tool_result
from factory_agent.rag.source_metadata import normalize_source_locator, sanitize_rag_answer_text
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import (
    ActivityStepResponse,
    ApprovalRequiredBlock,
    ApprovalResponse,
    DiagnosticBlock,
    KnowledgeAnswerBlock,
    MutationResultBlock,
    PlanResponse,
    PlanStepResponse,
    PresentationResponse,
    ResponseBlock,
    ResponseDocument,
    ResultTableBlock,
    ResumeHintResponse,
    RunActivityBlock,
    RunStep,
    ShortMessageBlock,
    SessionSnapshotResponse,
    TimelineEventResponse,
    ToolInfo,
    SourceListBlock,
)
from factory_agent.services.response_document_service import compose_response_document
from factory_agent.session_state import (
    USER_CANCELLED_ACTIVITY_DETAIL,
    USER_CANCELLED_ACTIVITY_LABEL,
    USER_CANCELLED_REASON,
    USER_CANCELLED_TIMELINE_CONTENT,
    is_user_cancelled_session,
    timeline_details_indicate_user_cancelled,
)

ORPHAN_TURN_REASON = "orphan_turn_state"
ORPHAN_TURN_MESSAGE = (
    "orphan_turn_state: The session has a user request but no running work, pending approval, or terminal result. "
    "Current state: blocked for operator review. Next action: check current status and start a new request if needed."
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
    answer = normalize_tool_result(tool_name=tool_name, endpoint=None, result=result, intent=intent)
    if answer is not None:
        details["answer_model"] = {
            "answer_type": answer.answer_type,
            "entity_type": answer.entity_type,
            "entity_id": answer.entity_id,
            "title": answer.title,
            "primary_status": answer.primary_status,
            "fields": [{"label": f.label, "value": f.value, "key": f.key, "primary": f.primary} for f in answer.fields],
        }
    return details


def _looks_like_raw_json_text(value: str | None) -> bool:
    text = (value or "").strip()
    if not text or text[0] not in "{[":
        return False
    try:
        json.loads(text)
        return True
    except Exception:
        return False


def _is_plan_like_completion_text(value: str | None) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return (
        "executing the following plan" in text
        or "risk summary:" in text
        or "before executing" in text
        or text.startswith("operators can")
    )


def _is_approval_wait_text(value: str | None) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return (
        "waiting for your approval" in text
        or "please approve" in text
        or "will be updated from" in text
        or "change list is shown" in text
    )


def _is_operator_result_text(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if "execution completed successfully" in lower:
        return False
    if lower in {"tool started.", "step started.", "execution started."}:
        return False
    if lower.endswith(" completed.") and "__" in lower:
        return False
    return not _looks_like_raw_json_text(text) and not _is_plan_like_completion_text(text)


def _operator_result_content_for_completion(event: TimelineEventResponse | None) -> str | None:
    if event is None:
        return None
    details = event.details if isinstance(event.details, dict) else {}
    presentation = details.get("presentation") if isinstance(details.get("presentation"), dict) else {}
    presentation_message = str(presentation.get("message") or "").strip()
    if _is_operator_result_text(presentation_message):
        return presentation_message
    content = str(event.content or "").strip()
    return content if _is_operator_result_text(content) else None


def _tool_result_completion_sort_key(event: TimelineEventResponse) -> tuple[datetime, int]:
    step_context = event.step_context if isinstance(event.step_context, dict) else {}
    try:
        step_index = int(step_context.get("step_index"))
    except (TypeError, ValueError):
        step_index = -1
    return event.created_at, step_index


def _is_success_like_plan_text(value: str | None) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return (
        text.startswith("**success**")
        or "updated **" in text
        or "all requested changes completed" in text
        or "run complete" in text
    )


def _is_rich_operator_completion_text(value: str | None) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return (
        "write set" in text
        or "affected records:" in text
        or "changed to" in text
        or "created or deleted" in text
    )


def _is_failure_guidance_text(value: str | None) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return (
        "could not complete" in text
        or "failed" in text
        or "database unavailable" in text
        or "please retry" in text
    )


def _plan_timeline_content(
    *,
    session_status: str | None,
    plan_row: PlanRow,
    plan_message: MessageRow | None,
) -> str:
    content = (
        plan_message.content
        if plan_message and plan_message.content
        else (plan_row.plan_explanation or "Execution plan created.")
    )
    explanation = plan_row.plan_explanation or ""
    if (
        str(session_status or "").upper() == "FAILED"
        and explanation
        and _is_failure_guidance_text(explanation)
        and _is_success_like_plan_text(content)
    ):
        return explanation
    return content


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


def _timeline_event_plan_id(ev: TimelineEventResponse) -> str | None:
    d = ev.details if isinstance(ev.details, dict) else {}
    pid = d.get("plan_id")
    if isinstance(pid, str) and pid.strip():
        return pid.strip()
    sc = ev.step_context if isinstance(ev.step_context, dict) else {}
    pid2 = sc.get("plan_id")
    if isinstance(pid2, str) and pid2.strip():
        return pid2.strip()
    return None


def _timeline_plan_spans(events: list[TimelineEventResponse]) -> list[tuple[datetime, str]]:
    spans: list[tuple[datetime, str]] = []
    for ev in events:
        if ev.event_type != "plan_created":
            continue
        pid = _timeline_event_plan_id(ev)
        if pid:
            spans.append((ev.created_at, pid))
    spans.sort(key=lambda item: item[0])
    return spans


def _operation_id_for_timestamp(ts: datetime, spans: list[tuple[datetime, str]]) -> str | None:
    last: str | None = None
    for created, pid in spans:
        if created <= ts:
            last = pid
    if last:
        return last
    for created, pid in spans:
        if created > ts:
            return pid
    return None


def _annotate_timeline_operation_ids(events: list[TimelineEventResponse]) -> list[TimelineEventResponse]:
    if not events:
        return events
    spans = _timeline_plan_spans(events)
    ordered = sorted(
        events,
        key=lambda ev: (
            ev.created_at,
            _TIMELINE_EVENT_PRIORITY.get(ev.event_type, 99),
            ev.event_id,
        ),
    )
    out: list[TimelineEventResponse] = []
    for ev in ordered:
        oid: str | None
        if ev.event_type == "plan_created":
            oid = _timeline_event_plan_id(ev)
        elif ev.event_type == "user_message":
            oid = _operation_id_for_timestamp(ev.created_at, spans)
        else:
            oid = _timeline_event_plan_id(ev) or _operation_id_for_timestamp(ev.created_at, spans)
        out.append(ev.model_copy(update={"operation_id": oid}))
    return out


_APPROVAL_AUX_TAGS = {"list", "lookup", "status", "pending", "create", "update", "delete", "approve", "reject"}

_SEMANTIC_EVENT_MAP: dict[str, str] = {
    "user_message": "USER_MESSAGE",
    "plan_created": "PLANNER_THINKING",
    "execution_started": "EXECUTION_STARTED",
    "tool_started": "TOOL_STARTED",
    "tool_result": "TOOL_RESULT",
    "approval_required": "APPROVAL_REQUIRED",
    "approval_decided": "APPROVAL_DECIDED",
    "replan_requested": "REPLAN_REQUESTED",
    "session_blocked": "SESSION_BLOCKED",
    "session_failed": "SESSION_FAILED",
    "session_completed": "SESSION_COMPLETED",
}


_ACTIVITY_MAX_VISIBLE_STEPS = 12
_ACTIVITY_FINALIZE_STATES = {"running", "retry", "waiting"}
_ACTIVITY_MERGEABLE_STATES = {"running", "success"}
_ACTIVITY_ACTIVE_SESSION_STATUSES = {"PLANNING", "EXECUTING", "WAITING_APPROVAL", "WAITING_CONFIRMATION"}
_LIVE_ACTIVITY_ALLOWED_GROUPS = {"planning", "research", "approval", "response", "system"}
_LIVE_ACTIVITY_ALLOWED_STATES = {"running", "success", "retry", "waiting", "error", "complete"}
_LIVE_ACTIVITY_ALLOWED_LABELS = {
    "Understood request",
    "Preparing next action",
    "Structuring request",
    "Choosing next action",
    "Finding information path",
    "Selecting safe action",
    "Searching knowledge sources",
    "Building cited answer",
    "Checking citations",
    "Running selected tool",
    "Checking result",
    "Checking approvals",
    "Waiting for approval",
    "Applying approved changes",
    "Preparing response",
}
_LIVE_ACTIVITY_UNSAFE_TEXT_FRAGMENTS = {
    "__",
    "{id}",
    "tool_name",
    "args",
    "checkpoint",
    "planner_reentered",
    "validator_failed",
    "tool_rerun",
}
_ACTIVITY_ALLOWED_DOMAIN_TOKENS = {
    "approval": "approval requests",
    "approvals": "approval requests",
    "inventory": "inventory records",
    "job": "job records",
    "jobs": "job records",
    "machine": "machine records",
    "machines": "machine records",
    "maintenance": "maintenance records",
    "material": "inventory records",
    "materials": "inventory records",
    "process": "process records",
    "processes": "process records",
    "product": "product records",
    "products": "product records",
    "production": "production records",
    "proposal": "proposal records",
    "proposals": "proposal records",
    "quality": "quality records",
    "report": "report records",
    "reports": "report records",
    "scheduling": "scheduling records",
    "storage": "storage records",
}


def _safe_activity_domain_label(ev: TimelineEventResponse) -> str:
    candidates = [
        ev.tool_name or "",
        str((ev.step_context or {}).get("tool_name") or ""),
        str((ev.details or {}).get("tool_name") or ""),
        str((ev.details or {}).get("subject_type") or ""),
        ev.content or "",
    ]
    text = " ".join(candidates).lower()
    text = text.replace("{id}", " ")
    text = text.replace("__", " ")
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    for token, label in _ACTIVITY_ALLOWED_DOMAIN_TOKENS.items():
        if token in text:
            return label
    return "relevant records"


def _activity_event_args(ev: TimelineEventResponse) -> dict[str, Any]:
    details = ev.details if isinstance(ev.details, dict) else {}
    args = details.get("args")
    if isinstance(args, dict):
        return dict(args)
    result = details.get("result")
    if isinstance(result, dict) and isinstance(result.get("request_args"), dict):
        return dict(result["request_args"])
    return {}


def _activity_domain_subject(ev: TimelineEventResponse) -> str:
    label = _safe_activity_domain_label(ev)
    if label.endswith(" records"):
        return label[: -len(" records")]
    if label.endswith(" requests"):
        return label[: -len(" requests")]
    return ""


def _activity_read_target_label(ev: TimelineEventResponse | None) -> str:
    if ev is None:
        return "selected read"
    subject = _activity_domain_subject(ev)
    args = _activity_event_args(ev)
    fields = args.get("fields") or args.get("requested_fields")
    if isinstance(fields, str):
        requested = {item.strip().lower() for item in fields.split(",") if item.strip()}
    elif isinstance(fields, list):
        requested = {str(item).strip().lower() for item in fields if str(item).strip()}
    else:
        requested = set()
    if subject and "status" in requested:
        return f"{subject} status read"
    if subject:
        return f"{subject} read"
    return "selected read"


def _activity_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _activity_replan_total_attempts(replan_spine: dict[str, Any]) -> int:
    max_replans = _activity_int(replan_spine.get("max_attempts")) or 0
    attempt_count = _activity_int(replan_spine.get("attempt_count")) or 0
    if max_replans > 0:
        return max_replans + 1
    if attempt_count > 0:
        return attempt_count + 1
    return 0


def _activity_attempt_text(attempt: int, total: int, message: str) -> str:
    if attempt > 0 and total > 0:
        return f"Attempt {attempt} of {total} - {message}"
    return message


def _activity_result_error_kind(ev: TimelineEventResponse | None) -> str | None:
    if ev is None:
        return None
    details = ev.details if isinstance(ev.details, dict) else {}
    result = details.get("result")
    result = result if isinstance(result, dict) else {}
    error = result.get("error")
    error = error if isinstance(error, dict) else {}
    error_type = str(
        error.get("error_type")
        or result.get("error_type")
        or details.get("error_type")
        or ""
    ).strip().lower()
    status_code = (
        _activity_int(result.get("status_code"))
        or _activity_int(result.get("http_status"))
        or _activity_int(details.get("http_status"))
    )
    if error_type == "timeout" or status_code in {408, 504}:
        return "timeout"
    if error_type in {"empty_data", "insufficient_context", "no_match", "missing_evidence"}:
        return "incomplete"
    if error_type in {"http_error", "http_500", "network", "tool_execution_exception"}:
        return "tool_error"
    if status_code is not None and status_code >= 400:
        return "tool_error"
    return None


def _activity_attempt_reason_kind(
    *,
    replan_spine: dict[str, Any],
    replan_attempt: int,
    failed_event: TimelineEventResponse | None,
) -> str:
    event_kind = _activity_result_error_kind(failed_event)
    if event_kind:
        return event_kind
    attempts = replan_spine.get("attempts")
    if isinstance(attempts, list):
        for item in attempts:
            if not isinstance(item, dict):
                continue
            if _activity_int(item.get("attempt")) != replan_attempt:
                continue
            for reason in item.get("missing_evidence_reasons") or []:
                if not isinstance(reason, dict):
                    continue
                code = str(reason.get("reason") or "").strip().lower()
                if code in {"insufficient_context", "missing_evidence", "no_match"}:
                    return "incomplete"
                if code == "tool_error":
                    return "tool_error"
    for reason in replan_spine.get("missing_evidence_reasons") or []:
        if not isinstance(reason, dict):
            continue
        code = str(reason.get("reason") or "").strip().lower()
        if code in {"insufficient_context", "missing_evidence", "no_match"}:
            return "incomplete"
        if code == "tool_error":
            return "tool_error"
    return "tool_error"


def _activity_retry_reason_text(kind: str) -> str:
    if kind == "timeout":
        return "Previous read timed out"
    if kind == "incomplete":
        return "Evidence was incomplete"
    if kind == "different_tool":
        return "Trying a different tool"
    return "Previous read failed"


def _activity_replan_label(kind: str) -> str:
    if kind == "timeout":
        return "Replanning after timeout"
    if kind == "incomplete":
        return "Replanning for more evidence"
    if kind == "different_tool":
        return "Replanning with a different tool"
    return "Replanning after failed read"


def _activity_is_read_event(ev: TimelineEventResponse) -> bool:
    tool_name = str(ev.tool_name or (ev.step_context or {}).get("tool_name") or "").strip().lower()
    return not tool_name.startswith(_WRITE_TOOL_PREFIXES) and not _is_rag_activity_event(ev)


def _activity_replan_attempt_base(base: Mapping[str, Any], attempt: int) -> dict[str, Any]:
    tagged = dict(base)
    tagged["_replan_attempt"] = attempt
    return tagged


def _activity_replan_story_step(
    ev: TimelineEventResponse,
    base: dict[str, str],
    detail: str | None,
    *,
    replan_spine: dict[str, Any],
    prior_replans: int,
    failed_event: TimelineEventResponse | None,
    later_replan: bool,
) -> tuple[dict[str, Any], str | None]:
    total = _activity_replan_total_attempts(replan_spine)
    event_type = ev.event_type
    if total <= 0:
        return base, detail

    if event_type == "replan_requested":
        next_attempt = prior_replans + 2
        kind = _activity_attempt_reason_kind(
            replan_spine=replan_spine,
            replan_attempt=max(1, next_attempt - 1),
            failed_event=failed_event,
        )
        reason = _activity_retry_reason_text(kind)
        return (
            _activity_replan_attempt_base(
                {"group": "planning", "label": _activity_replan_label(kind), "state": "retry"},
                next_attempt,
            ),
            _activity_attempt_text(next_attempt, total, reason),
        )

    if event_type in {"execution_started", "tool_started"} and _activity_is_read_event(ev):
        attempt = prior_replans + 1
        if attempt <= 1:
            return (
                _activity_replan_attempt_base(
                    {"group": "research", "label": "Running selected tool", "state": "running"},
                    attempt,
                ),
                _activity_attempt_text(attempt, total, "Running the selected read"),
            )
        return (
            _activity_replan_attempt_base(
                {"group": "research", "label": f"Retrying {_activity_read_target_label(ev)}", "state": "running"},
                attempt,
            ),
            _activity_attempt_text(attempt, total, "Running the next selected read"),
        )

    if event_type == "tool_result" and _activity_is_read_event(ev):
        attempt = prior_replans + 1
        status = str(ev.status or "").upper()
        domain = _safe_activity_domain_label(ev)
        if status in {"FAILED", "AMBIGUOUS"}:
            kind = _activity_attempt_reason_kind(
                replan_spine=replan_spine,
                replan_attempt=max(1, attempt),
                failed_event=ev,
            )
            reason = _activity_retry_reason_text(kind)
            if later_replan:
                return (
                    _activity_replan_attempt_base(
                        {"group": "response", "label": "Checking evidence", "state": "success"},
                        attempt,
                    ),
                    _activity_attempt_text(attempt, total, reason),
                )
            return (
                _activity_replan_attempt_base(
                    {"group": "response", "label": "Checking evidence", "state": "error"},
                    attempt,
                ),
                _activity_attempt_text(attempt, total, "Evidence could not be verified"),
            )
        if status == "DONE":
            label = "Checking new evidence" if prior_replans > 0 else "Checking evidence"
            return (
                _activity_replan_attempt_base({"group": "response", "label": label, "state": "success"}, attempt),
                _activity_attempt_text(attempt, total, f"Verified {domain}"),
            )

    if event_type == "session_completed" and prior_replans > 0:
        attempt = min(total, max(prior_replans + 1, (_activity_int(replan_spine.get("attempt_count")) or 0) + 1))
        return (
            _activity_replan_attempt_base(base, attempt),
            _activity_attempt_text(attempt, total, "Completed with verified evidence"),
        )

    if event_type in {"session_failed", "session_blocked"} and replan_spine.get("replan_limit_reached"):
        attempt = min(total, max(prior_replans + 1, (_activity_int(replan_spine.get("attempt_count")) or 0) + 1))
        return (
            _activity_replan_attempt_base(base, attempt),
            _activity_attempt_text(attempt, total, "Evidence could not be verified after retries"),
        )

    return base, detail


def _activity_probe_event_from_failed_call(call: Mapping[str, Any] | None) -> TimelineEventResponse | None:
    if not isinstance(call, Mapping):
        return None
    tool_name = str(call.get("tool_name") or "").strip()
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    if not tool_name:
        return None
    error: dict[str, Any] = {"code": str(call.get("reason") or "tool_error")}
    if call.get("error_type"):
        error["error_type"] = str(call.get("error_type"))
    return TimelineEventResponse(
        event_id="activity:failed-call-probe",
        event_type="tool_result",
        content="",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
        tool_name=tool_name,
        status="FAILED",
        details={
            "args": dict(args),
            "result": {
                "status": "tool_failed",
                "error": error,
            },
        },
    )


def _activity_replan_story_from_diagnostics(
    raw_steps: list[dict[str, Any]],
    snapshot: SessionSnapshotResponse,
    replan_spine: dict[str, Any],
) -> list[dict[str, Any]]:
    if not raw_steps or any(str(step.get("label") or "").startswith("Replanning") for step in raw_steps):
        return raw_steps
    attempts = replan_spine.get("attempts")
    failed_calls = replan_spine.get("failed_tool_calls")
    if not isinstance(attempts, list) or not attempts:
        return raw_steps
    if not isinstance(failed_calls, list) or not failed_calls:
        failed_calls = []
        for item in attempts:
            if not isinstance(item, Mapping):
                continue
            item_failed_calls = item.get("failed_tool_calls")
            if not isinstance(item_failed_calls, list):
                continue
            failed_calls.extend(call for call in item_failed_calls if isinstance(call, Mapping))
    if not failed_calls:
        return raw_steps

    total = _activity_replan_total_attempts(replan_spine)
    if total <= 0:
        return raw_steps

    terminal = next((step for step in reversed(raw_steps) if step.get("state") in {"complete", "error"}), None)
    terminal_state = str(terminal.get("state") if terminal else "")
    terminal_ts = int(terminal.get("timestamp") or snapshot.session.updated_at.timestamp()) if terminal else int(snapshot.session.updated_at.timestamp())
    leading = [step for step in raw_steps if step.get("label") == "Understood request"][:1]
    first_call = next((call for call in failed_calls if isinstance(call, Mapping)), None)
    probe = _activity_probe_event_from_failed_call(first_call)
    kind = _activity_attempt_reason_kind(replan_spine=replan_spine, replan_attempt=1, failed_event=probe)
    reason = _activity_retry_reason_text(kind)
    target = _activity_read_target_label(probe)
    domain = _safe_activity_domain_label(probe) if probe is not None else "relevant records"
    active_attempt = min(total, max((_activity_int(replan_spine.get("attempt_count")) or 0) + 1, 1))

    story: list[dict[str, Any]] = [dict(step) for step in leading]
    story_ids = {str(step.get("id") or "") for step in story}
    first_run_index = next(
        (idx for idx, step in enumerate(raw_steps) if step.get("label") == "Running selected tool"),
        -1,
    )
    first_check_search_start = first_run_index + 1 if first_run_index >= 0 else 0
    first_check_index = next(
        (
            idx
            for idx, step in enumerate(
                raw_steps[first_check_search_start:],
                start=first_check_search_start,
            )
            if step.get("label") in {"Checking result", "Checking evidence"}
        ),
        -1,
    )
    prelude_limit = first_run_index if first_run_index >= 0 else len(raw_steps)
    for step in raw_steps[:prelude_limit]:
        step_id = str(step.get("id") or "")
        if step_id in story_ids or step.get("state") in {"complete", "error"}:
            continue
        if step.get("label") in {"Running selected tool", "Checking result", "Checking evidence"}:
            continue
        story.append({**step, "state": "success" if step.get("state") in _ACTIVITY_FINALIZE_STATES else step.get("state")})
        story_ids.add(step_id)

    base_ts = max((int(step.get("timestamp") or 0) for step in story), default=terminal_ts - 10)

    def add(offset: int, group: str, label: str, state: str, detail: str, *, attempt: int | None = None) -> None:
        row: dict[str, Any] = {
            "id": f"act:replan_story:{len(story) + 1}",
            "timestamp": base_ts + offset,
            "group": group,
            "label": label,
            "detail": detail,
            "state": state,
        }
        if attempt is not None:
            row["_replan_attempt"] = attempt
        story.append(row)

    if first_run_index >= 0:
        story.append(
            {
                **raw_steps[first_run_index],
                "detail": _activity_attempt_text(1, total, "Running the selected read"),
                "state": "success",
                "_replan_attempt": 1,
            }
        )
    else:
        add(
            1,
            "research",
            "Running selected tool",
            "success",
            _activity_attempt_text(1, total, "Running the selected read"),
            attempt=1,
        )
    base_ts = max((int(step.get("timestamp") or 0) for step in story), default=base_ts)
    if first_check_index >= 0:
        story.append(
            {
                **raw_steps[first_check_index],
                "detail": _activity_attempt_text(1, total, reason),
                "state": "success",
                "_replan_attempt": 1,
            }
        )
    else:
        add(
            2,
            "response",
            "Checking evidence",
            "success",
            _activity_attempt_text(1, total, reason),
            attempt=1,
        )
    base_ts = max((int(step.get("timestamp") or 0) for step in story), default=base_ts)
    for item in attempts:
        if not isinstance(item, Mapping):
            continue
        replan_attempt = _activity_int(item.get("attempt")) or len(story)
        next_attempt = min(total, replan_attempt + 1)
        attempt_call = next(
            (
                call for call in item.get("failed_tool_calls", [])
                if isinstance(call, Mapping) and call.get("tool_name")
            ),
            first_call,
        )
        attempt_probe = _activity_probe_event_from_failed_call(attempt_call)
        attempt_kind = _activity_attempt_reason_kind(
            replan_spine=replan_spine,
            replan_attempt=max(1, replan_attempt),
            failed_event=attempt_probe,
        )
        attempt_reason = _activity_retry_reason_text(attempt_kind)
        attempt_target = _activity_read_target_label(attempt_probe) if attempt_probe is not None else target
        if replan_attempt > 1:
            add(
                2 + (replan_attempt * 3) - 2,
                "response",
                "Checking evidence",
                "success",
                _activity_attempt_text(replan_attempt, total, attempt_reason),
                attempt=replan_attempt,
            )
        add(
            2 + (replan_attempt * 3) - 1,
            "planning",
            _activity_replan_label(attempt_kind),
            "success",
            _activity_attempt_text(next_attempt, total, attempt_reason),
            attempt=next_attempt,
        )
        add(
            2 + (replan_attempt * 3),
            "research",
            f"Retrying {attempt_target}",
            "success" if terminal_state or next_attempt != active_attempt else "running",
            _activity_attempt_text(next_attempt, total, "Running the next selected read"),
            attempt=next_attempt,
        )

    final_attempt = min(total, max((_activity_int(replan_spine.get("attempt_count")) or 0) + 1, 1))
    if terminal_state == "complete":
        add(
            total + 20,
            "response",
            "Checking new evidence",
            "success",
            _activity_attempt_text(final_attempt, total, f"Verified {domain}"),
            attempt=final_attempt,
        )
    if terminal:
        terminal_detail = (
            _activity_attempt_text(final_attempt, total, "Completed with verified evidence")
            if terminal_state == "complete"
            else _activity_attempt_text(final_attempt, total, "Evidence could not be verified after retries")
        )
        story.append({**terminal, "detail": terminal_detail, "_replan_attempt": final_attempt})
    return story


def _activity_collapse_noisy_replan_attempts(
    raw_steps: list[dict[str, Any]],
    replan_spine: dict[str, Any],
) -> list[dict[str, Any]]:
    if not replan_spine:
        return raw_steps
    attempt_numbers = sorted(
        {
            attempt
            for step in raw_steps
            if (attempt := _activity_int(step.get("_replan_attempt"))) is not None
        }
    )
    if len(attempt_numbers) <= 3:
        return raw_steps
    has_terminal = any(step.get("state") in {"complete", "error"} for step in raw_steps)
    tail_attempts_to_keep = 1 if has_terminal else 2
    collapse_until = max(len(attempt_numbers) - tail_attempts_to_keep, 1)
    collapsed_attempts = set(attempt_numbers[1:collapse_until])
    if not collapsed_attempts:
        return raw_steps

    collapsed_seen: set[int] = set()
    summary: dict[str, Any] | None = None
    compacted: list[dict[str, Any]] = []
    for step in raw_steps:
        attempt = _activity_int(step.get("_replan_attempt"))
        if attempt in collapsed_attempts:
            collapsed_seen.add(attempt)
            if summary is None:
                summary = {
                    "id": "act:replan_attempts_collapsed",
                    "timestamp": int(step.get("timestamp") or 0),
                    "group": "system",
                    "label": "Earlier retry attempts",
                    "detail": "",
                    "state": "success",
                }
                compacted.append(summary)
            continue
        compacted.append(step)

    if not collapsed_seen or summary is None:
        return raw_steps
    attempt_word = "attempt" if len(collapsed_seen) == 1 else "attempts"
    summary["detail"] = f"{len(collapsed_seen)} earlier {attempt_word} collapsed"
    return compacted


def _is_rag_activity_event(ev: TimelineEventResponse) -> bool:
    details = ev.details if isinstance(ev.details, dict) else {}
    tool_name = " ".join(
        [
            ev.tool_name or "",
            str((ev.step_context or {}).get("tool_name") or ""),
            str(details.get("tool_name") or ""),
        ]
    ).lower()
    if "rag" in tool_name or "search_documents" in tool_name or "knowledge" in tool_name:
        return True
    return isinstance(details.get("sources"), list) and bool(details.get("sources"))


def _activity_detail_for_event(ev: TimelineEventResponse, *, label: str) -> str | None:
    domain = _safe_activity_domain_label(ev)
    if ev.event_type == "session_failed" and isinstance(ev.details, dict):
        if timeline_details_indicate_user_cancelled(ev.details):
            return USER_CANCELLED_ACTIVITY_DETAIL
    if ev.event_type == "plan_created":
        return "Reviewing your request and recent context"
    if ev.event_type == "execution_started":
        return "Preparing the next safe action"
    if ev.event_type == "tool_started":
        if _is_rag_activity_event(ev):
            return "Searching retrieved documents"
        return f"Checking {domain}"
    if ev.event_type == "tool_result":
        if label == "Could not complete that check":
            return "A check could not be completed"
        if _is_rag_activity_event(ev):
            return "Checking citation support"
        return f"Checked {domain}"
    if ev.event_type == "approval_required":
        return "Reviewing approval requirements"
    if ev.event_type == "approval_decided":
        if str(ev.status or "").upper() == "APPROVED":
            return "Continuing with your approved changes"
        return "Approval decision recorded"
    if ev.event_type == "replan_requested":
        return "Refining the response with updated information"
    if ev.event_type == "session_completed":
        return "All steps finished. See the thread below."
    if ev.event_type in {"session_failed", "session_blocked"}:
        return "The request could not be completed"
    return None


def _activity_base_for_timeline_event(ev: TimelineEventResponse) -> dict[str, str] | None:
    event_type = ev.event_type
    status = str(ev.status or "").upper()
    if event_type == "user_message":
        return None
    if event_type == "plan_created":
        return {"group": "planning", "label": "Understood request", "state": "success"}
    if event_type == "execution_started":
        return {"group": "planning", "label": "Preparing next action", "state": "running"}
    if event_type == "tool_started":
        if _is_rag_activity_event(ev):
            return {"group": "research", "label": "Searching knowledge sources", "state": "running"}
        return {"group": "research", "label": f"Reading {_safe_activity_domain_label(ev)}", "state": "running"}
    if event_type == "tool_result":
        if status in {"FAILED", "AMBIGUOUS"}:
            return {"group": "research", "label": "Could not complete that check", "state": "error"}
        if _is_rag_activity_event(ev):
            return {"group": "research", "label": "Building cited answer", "state": "success"}
        return {"group": "research", "label": f"Checked {_safe_activity_domain_label(ev)}", "state": "success"}
    if event_type == "approval_required":
        if status not in {"", "PENDING"}:
            return None
        return {"group": "approval", "label": "Waiting for your approval", "state": "waiting"}
    if event_type == "approval_decided":
        state = "error" if status == "REJECTED" else "success"
        if status == "APPROVED":
            return {"group": "approval", "label": "Approval received", "state": state}
        return {"group": "approval", "label": "Approval updated", "state": state}
    if event_type == "confirmation_required":
        return {"group": "approval", "label": "Waiting for your confirmation", "state": "waiting"}
    if event_type == "confirmation_decided":
        return {"group": "approval", "label": "Confirmation received", "state": "success"}
    if event_type == "replan_requested":
        return {"group": "planning", "label": "Improving the response", "state": "retry"}
    if event_type in {"session_failed", "session_blocked"}:
        if event_type == "session_failed" and isinstance(ev.details, dict):
            if timeline_details_indicate_user_cancelled(ev.details):
                return {"group": "system", "label": USER_CANCELLED_ACTIVITY_LABEL, "state": "complete"}
        return {"group": "system", "label": "Something needs attention", "state": "error"}
    if event_type == "session_completed":
        return {"group": "response", "label": "Run complete", "state": "complete"}
    return None


def _activity_step_stable_id(ev: TimelineEventResponse, signature: tuple[Any, ...]) -> str:
    """Stable id so activity SSE + snapshot merges do not treat re-ordered rows as all-new steps."""
    eid = str(getattr(ev, "event_id", None) or "").strip()
    if eid:
        return f"act:{eid}"
    digest = hashlib.sha256(
        f"{ev.event_type}|{ev.created_at.isoformat() if ev.created_at else ''}|{signature!r}".encode()
    ).hexdigest()[:16]
    return f"act:fb:{digest}"


def _activity_merge_signature(
    ev: TimelineEventResponse, base: dict[str, str], detail: str | None
) -> tuple[str, str, str, str, str]:
    """Include plan scope so unrelated plan_created rows (replans / new plans) are not merged into one."""
    plan_key = str(_timeline_event_plan_id(ev) or getattr(ev, "operation_id", None) or "").strip() or "__"
    return (base["group"], base["label"], detail or "", base["state"], plan_key)


def _live_activity_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if any(fragment.lower() in lowered for fragment in _LIVE_ACTIVITY_UNSAFE_TEXT_FRAGMENTS):
        return ""
    return text


def _live_activity_steps_for_snapshot(
    snapshot: SessionSnapshotResponse,
    *,
    session_status: str,
) -> list[dict[str, Any]]:
    """Expose server-authored in-flight graph activity without trusting arbitrary context text."""
    if session_status not in _ACTIVITY_ACTIVE_SESSION_STATUSES:
        return []
    context = snapshot.session.replan_context if isinstance(snapshot.session.replan_context, dict) else {}
    rows = context.get("live_activity_steps")
    if not isinstance(rows, list):
        return []

    fallback_ts = int(snapshot.session.updated_at.timestamp())
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        label = _live_activity_text(row.get("label"))
        if label not in _LIVE_ACTIVITY_ALLOWED_LABELS:
            continue
        step_id = _live_activity_text(row.get("id")) or f"graph:live:{idx}"
        if not step_id.startswith("graph:"):
            step_id = f"graph:{step_id}"
        if step_id in seen_ids:
            continue
        seen_ids.add(step_id)
        group = str(row.get("group") or "").strip()
        if group not in _LIVE_ACTIVITY_ALLOWED_GROUPS:
            group = "system"
        state = str(row.get("state") or "").strip()
        if state not in _LIVE_ACTIVITY_ALLOWED_STATES:
            state = "running"
        try:
            timestamp = int(row.get("timestamp") or fallback_ts + idx)
        except (TypeError, ValueError):
            timestamp = fallback_ts + idx
        detail = _live_activity_text(row.get("detail")) or None
        order = _activity_int(row.get("order") or row.get("_order")) or idx + 1
        out.append(
            {
                "id": step_id,
                "timestamp": timestamp,
                "order": order,
                "_order": order,
                "group": group,
                "label": label,
                "detail": detail,
                "state": state,
            }
        )
    return sorted(
        out,
        key=lambda step: (
            int(step.get("order") or step.get("_order") or 0),
            int(step["timestamp"]),
            str(step["id"]),
        ),
    )


def _snapshot_plan_scoped_steps(
    plan_steps: list[PlanStepResponse], plan: PlanResponse | None
) -> list[PlanStepResponse]:
    if not plan_steps:
        return []
    if plan is None:
        return list(plan_steps)
    pid = str(plan.plan_id or "").strip()
    if not pid:
        return list(plan_steps)
    return [s for s in plan_steps if str(s.plan_id or "").strip() == pid]


def _activity_raw_rows_show_tool_execution(rows: list[dict[str, Any]]) -> bool:
    toolish = {"Information checked", "Gathering information", "Could not complete that check"}
    return any(
        r.get("label") in toolish
        or str(r.get("label") or "").startswith(("Reading ", "Checked "))
        or r.get("label") in {"Searching knowledge sources", "Building cited answer"}
        for r in rows
    )


def _activity_domain_label_for_tool_name(tool_name: str) -> str:
    probe = TimelineEventResponse(
        event_id="activity:domain_probe",
        event_type="tool_result",
        content="",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
        tool_name=tool_name,
        status="DONE",
    )
    return _safe_activity_domain_label(probe)


def _activity_inject_plan_execution_summary(
    raw_steps: list[dict[str, Any]], snapshot: SessionSnapshotResponse
) -> list[dict[str, Any]]:
    """If the timeline omitted tool rows (checkpoint / LangGraph gaps) but plan steps finished, add one row."""
    if len(raw_steps) > 3:
        return raw_steps
    if _activity_raw_rows_show_tool_execution(raw_steps):
        return raw_steps
    scoped = _snapshot_plan_scoped_steps(list(snapshot.steps or []), snapshot.plan)
    finished = [s for s in scoped if str(s.status or "").upper() in {"DONE", "FAILED", "AMBIGUOUS"}]
    if not finished or not any(str(s.tool_name or "").strip() for s in finished):
        return raw_steps

    last_terminal_index = -1
    for idx in range(len(raw_steps) - 1, -1, -1):
        if raw_steps[idx].get("state") in {"complete", "error"}:
            last_terminal_index = idx
            break
    if last_terminal_index < 0:
        return raw_steps

    first_tool = next((str(s.tool_name or "").strip() for s in finished if str(s.tool_name or "").strip()), "")
    domain = _activity_domain_label_for_tool_name(first_tool) if first_tool else "relevant records"
    any_fail = any(str(s.status or "").upper() in {"FAILED", "AMBIGUOUS"} for s in finished)
    base_ts = int(raw_steps[last_terminal_index]["timestamp"])
    row: dict[str, Any] = {
        "id": "act:server_plan_execution_summary",
        "timestamp": base_ts - 1,
        "group": "research",
        "label": "Could not complete that check" if any_fail else "Updating job records",
        "detail": (
            f"Checked {domain}; some steps did not complete"
            if any_fail
            else f"Checked {domain} ({len(finished)} update{'s' if len(finished) != 1 else ''})"
        ),
        "state": "error" if any_fail else "success",
    }
    return [*raw_steps[:last_terminal_index], row, *raw_steps[last_terminal_index:]]


def _activity_steps_for_snapshot(snapshot: SessionSnapshotResponse) -> list[ActivityStepResponse]:
    raw_steps: list[dict[str, Any]] = []
    repeated_by_signature: dict[tuple[str, str, str, str, str], int] = {}
    index_by_signature: dict[tuple[str, str, str, str, str], int] = {}

    has_pending_approval = snapshot.pending_approval is not None
    session_status = str(getattr(snapshot.session, "status", "") or "").upper()
    suppress_completion = has_pending_approval or session_status in _ACTIVITY_ACTIVE_SESSION_STATUSES
    replan_spine = _replan_spine_from_session_context(snapshot.session)
    use_replan_story = bool(
        replan_spine
        and (
            replan_spine.get("attempt_count")
            or replan_spine.get("attempts")
            or replan_spine.get("replan_limit_reached")
        )
    )
    prior_replans = 0
    last_failed_read_event: TimelineEventResponse | None = None
    timeline_events = list(snapshot.timeline)
    later_replan_by_index = [
        any(later.event_type == "replan_requested" for later in timeline_events[idx + 1 :])
        for idx, _ in enumerate(timeline_events)
    ]

    for idx_ev, ev in enumerate(timeline_events):
        base = _activity_base_for_timeline_event(ev)
        if base is None:
            continue
        # Suppress "Run complete" while the session is still active. A stale
        # completion row between approval gates can hide the next pending write set.
        if suppress_completion and ev.event_type == "session_completed":
            continue
        detail = _activity_detail_for_event(ev, label=base["label"])
        if use_replan_story:
            base, detail = _activity_replan_story_step(
                ev,
                base,
                detail,
                replan_spine=replan_spine,
                prior_replans=prior_replans,
                failed_event=last_failed_read_event,
                later_replan=later_replan_by_index[idx_ev],
            )
        signature = _activity_merge_signature(ev, base, detail)
        if base["state"] in _ACTIVITY_MERGEABLE_STATES and signature in index_by_signature:
            count = repeated_by_signature.get(signature, 1) + 1
            repeated_by_signature[signature] = count
            idx = index_by_signature[signature]
            raw_steps[idx]["detail"] = f"{detail or base['label']} ({count} updates)"
            raw_steps[idx]["timestamp"] = int(ev.created_at.timestamp())
            raw_steps[idx]["state"] = base["state"]
            continue
        index_by_signature[signature] = len(raw_steps)
        repeated_by_signature[signature] = 1
        row = {
            "id": _activity_step_stable_id(ev, signature),
            "timestamp": int(ev.created_at.timestamp()),
            "group": base["group"],
            "label": base["label"],
            "detail": detail,
            "state": base["state"],
        }
        if base.get("_replan_attempt") is not None:
            row["_replan_attempt"] = base["_replan_attempt"]
        raw_steps.append(row)
        if ev.event_type == "tool_result" and str(ev.status or "").upper() in {"FAILED", "AMBIGUOUS"} and _activity_is_read_event(ev):
            last_failed_read_event = ev
        if ev.event_type == "replan_requested":
            prior_replans += 1

    live_steps = _live_activity_steps_for_snapshot(snapshot, session_status=session_status)
    if live_steps:
        existing_label_groups = {
            (str(step.get("group") or ""), str(step.get("label") or ""))
            for step in raw_steps
        }
        filtered_live_steps: list[dict[str, Any]] = []
        for step in live_steps:
            label_group = (str(step.get("group") or ""), str(step.get("label") or ""))
            if label_group in existing_label_groups:
                continue
            existing_label_groups.add(label_group)
            filtered_live_steps.append(step)
        live_steps = filtered_live_steps
    if live_steps:
        live_ids = {str(step["id"]) for step in live_steps}
        raw_steps = [step for step in raw_steps if str(step.get("id") or "") not in live_ids]
        raw_steps.extend(live_steps)
        raw_steps.sort(
            key=lambda step: (
                int(step["timestamp"]),
                int(step.get("order") or step.get("_order") or 0),
                str(step["id"]),
            )
        )

    if session_status == "WAITING_APPROVAL":
        latest_waiting_approval_index = -1
        for idx in range(len(raw_steps) - 1, -1, -1):
            step = raw_steps[idx]
            if (
                step.get("group") == "approval"
                and step.get("state") == "waiting"
                and str(step.get("label") or "").lower()
                in {"waiting for approval", "waiting for your approval"}
            ):
                latest_waiting_approval_index = idx
                break
        if latest_waiting_approval_index >= 0:
            raw_steps = raw_steps[: latest_waiting_approval_index + 1]

    # Find the LAST terminal step (complete/error), not the first.
    # Noise events (e.g. replan_requested) that arrive after session_completed
    # must be truncated so the activity strip shows the terminal step last.
    last_terminal_index = -1
    for idx in range(len(raw_steps) - 1, -1, -1):
        if raw_steps[idx].get("state") in {"complete", "error"}:
            last_terminal_index = idx
            break

    if last_terminal_index >= 0:
        # Finalize everything before the terminal to success.
        for idx in range(last_terminal_index):
            if raw_steps[idx].get("state") in _ACTIVITY_FINALIZE_STATES:
                raw_steps[idx]["state"] = "success"
        # Truncate noise steps that appear after the terminal.
        raw_steps = raw_steps[: last_terminal_index + 1]
    else:
        # No terminal yet — finalize all but the last step (still in progress).
        upper_bound = len(raw_steps) - 1
        for idx in range(upper_bound):
            if raw_steps[idx].get("state") in _ACTIVITY_FINALIZE_STATES:
                raw_steps[idx]["state"] = "success"

    raw_steps = _activity_inject_plan_execution_summary(raw_steps, snapshot)
    if use_replan_story:
        raw_steps = _activity_replan_story_from_diagnostics(raw_steps, snapshot, replan_spine)
        raw_steps = _activity_collapse_noisy_replan_attempts(raw_steps, replan_spine)

    if len(raw_steps) > _ACTIVITY_MAX_VISIBLE_STEPS:
        older = raw_steps[: -(_ACTIVITY_MAX_VISIBLE_STEPS - 1)]
        recent = raw_steps[-(_ACTIVITY_MAX_VISIBLE_STEPS - 1) :]
        grouped = {
            "id": "act:grouped_earlier",
            "timestamp": older[-1]["timestamp"],
            "group": "system",
            "label": "Earlier activity",
            "detail": f"{len(older)} earlier updates grouped",
            "state": "success",
        }
        raw_steps = [grouped, *recent]

    return [
        ActivityStepResponse(
            id=str(step["id"]),
            timestamp=int(step["timestamp"]),
            order=_activity_int(step.get("order") or step.get("_order")),
            replan_attempt=_activity_int(step.get("replan_attempt") or step.get("_replan_attempt")),
            group=step["group"],
            label=step["label"],
            detail=step.get("detail"),
            state=step["state"],
        )
        for step in raw_steps
    ]


def _semantic_payload_for_timeline_event(ev: TimelineEventResponse, *, session_id: str) -> dict[str, Any]:
    return {
        "type": _SEMANTIC_EVENT_MAP.get(ev.event_type, str(ev.event_type).upper()),
        "event_id": ev.event_id,
        "session_id": session_id,
        "created_at": ev.created_at.isoformat(),
        "content": ev.content,
        "details": ev.details or {},
        "tool_name": ev.tool_name,
        "approval_id": ev.approval_id,
        "status": ev.status,
        "presentation": ev.presentation.model_dump(mode="json") if ev.presentation is not None else None,
    }


def _should_skip_semantic_timeline_event(ev: TimelineEventResponse) -> bool:
    """Non-pending approval_required rows stay on the timeline for audit; SSE clients ignore them."""
    if ev.event_type != "approval_required":
        return False
    st = str(ev.status or "").upper()
    return st not in {"", "PENDING"}


_WRITE_TOOL_PREFIXES = ("post__", "put__", "patch__", "delete__")
_SUCCESS_ROW_STATES = {"success", "succeeded", "done", "completed", "committed", "ok", "http_ok"}
_FAILED_ROW_STATES = {"failed", "failure", "error", "errored", "version_conflict", "conflict", "rejected"}
_PRESENTATION_TERMINAL_EVENTS = {"session_completed", "session_failed", "session_blocked"}
_ROW_ID_KEYS = (
    "row_id",
    "job_id",
    "machine_id",
    "product_id",
    "inventory_id",
    "material_id",
    "proposal_id",
    "id",
    "primary_id",
)


def _is_write_tool_name(tool_name: str | None) -> bool:
    lower = str(tool_name or "").strip().lower()
    return lower.startswith(_WRITE_TOOL_PREFIXES)


def _trimmed(value: Any) -> str:
    return str(value or "").strip()


def _presentation_operation_id(
    *,
    session: Any,
    plan: PlanResponse | None,
    timeline: list[TimelineEventResponse],
) -> str | None:
    for candidate in (
        getattr(session, "operation_id", None),
        getattr(session, "plan_id", None),
        getattr(plan, "plan_id", None),
    ):
        text = _trimmed(candidate)
        if text:
            return text
    for event in reversed(timeline):
        text = _trimmed(getattr(event, "operation_id", None))
        if text:
            return text
    return None


def _presentation_sources(
    *,
    plan: PlanResponse | None,
    timeline: list[TimelineEventResponse],
) -> list[dict[str, Any]]:
    raw_sources: list[Any] = []
    if plan and isinstance(plan.sources, list) and plan.sources:
        raw_sources.extend(plan.sources)
    for event in reversed(timeline):
        details = event.details if isinstance(event.details, dict) else {}
        sources = details.get("sources")
        if isinstance(sources, list) and sources:
            raw_sources.extend(sources)
            break

    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, source in enumerate(raw_sources):
        row = normalize_source_locator(source, index, fallback_snippet=getattr(plan, "plan_explanation", None))
        key = (str(row.get("source_id") or ""), str(row.get("doc_id") or ""), str(row.get("chunk_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        row.setdefault("source_index", len(sources))
        sources.append(row)
    return sources


def _row_identifier(row: dict[str, Any]) -> str | None:
    for key in _ROW_ID_KEYS:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _normalize_row_status(status: Any, *, default: str) -> str:
    normalized = _trimmed(status).lower()
    if normalized in _SUCCESS_ROW_STATES:
        return "succeeded"
    if normalized in _FAILED_ROW_STATES:
        return "failed"
    if normalized in {"pending", "staged", "dry_run"}:
        return "pending"
    if normalized in {"expired", "superseded", "stale"}:
        return "expired"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if normalized:
        return normalized
    return default


def _presentation_row(
    payload: dict[str, Any],
    *,
    default_status: str,
    operation_id: str | None,
    approval_id: str | None,
    step_id: str | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    row = dict(payload)
    status = _normalize_row_status(row.get("status") or row.get("result") or row.get("outcome"), default=default_status)
    row["status"] = status
    row_id = _row_identifier(row)
    if row_id:
        row["row_id"] = row_id
    if operation_id:
        row.setdefault("operation_id", operation_id)
    if approval_id:
        row.setdefault("approval_id", approval_id)
    if step_id:
        row.setdefault("step_id", step_id)
    if tool_name:
        row.setdefault("tool_name", tool_name)
    return row


def _operation_rows_from_result(
    result: dict[str, Any] | None,
    *,
    default_status: str,
    operation_id: str | None,
    approval_id: str | None,
    step_id: str | None = None,
    tool_name: str | None = None,
    fallback_args: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        result = {}

    rows: list[dict[str, Any]] = []
    raw_outcomes = result.get("outcomes")
    if isinstance(raw_outcomes, list):
        for outcome in raw_outcomes:
            if isinstance(outcome, dict):
                rows.append(
                    _presentation_row(
                        outcome,
                        default_status=default_status,
                        operation_id=operation_id,
                        approval_id=approval_id,
                        step_id=step_id,
                        tool_name=tool_name,
                    )
                )
        if rows:
            return rows

    data = result.get("data")
    raw_operations = result.get("operations")
    if isinstance(data, dict) and isinstance(data.get("operations"), list):
        raw_operations = data.get("operations")
    if isinstance(raw_operations, list):
        for operation in raw_operations:
            if not isinstance(operation, dict):
                continue
            payload = operation.get("data") if isinstance(operation.get("data"), dict) else {}
            row_payload = {**payload, **{k: v for k, v in operation.items() if k != "data"}}
            rows.append(
                _presentation_row(
                    row_payload,
                    default_status=default_status,
                    operation_id=operation_id,
                    approval_id=approval_id,
                    step_id=step_id,
                    tool_name=tool_name,
                )
            )
        if rows:
            return rows

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                rows.append(
                    _presentation_row(
                        item,
                        default_status=default_status,
                        operation_id=operation_id,
                        approval_id=approval_id,
                        step_id=step_id,
                        tool_name=tool_name,
                    )
                )
        if rows:
            return rows

    if isinstance(data, dict):
        return [
            _presentation_row(
                data,
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id,
                step_id=step_id,
                tool_name=tool_name,
            )
        ]

    if fallback_args:
        return [
            _presentation_row(
                dict(fallback_args),
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id,
                step_id=step_id,
                tool_name=tool_name,
            )
        ]

    if result:
        return [
            _presentation_row(
                result,
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id,
                step_id=step_id,
                tool_name=tool_name,
            )
        ]
    return []


def _approval_rows_from_args(
    args: dict[str, Any] | None,
    *,
    default_status: str,
    operation_id: str | None,
    approval_id: str | None,
    tool_name: str | None,
) -> list[dict[str, Any]]:
    payload = args if isinstance(args, dict) else {}
    bundle_ui = payload.get("bundle_ui") if isinstance(payload.get("bundle_ui"), dict) else {}
    candidate_lists = [
        bundle_ui.get("rows"),
        payload.get("preview"),
        payload.get("staged_writes"),
    ]
    rows: list[dict[str, Any]] = []
    for candidate in candidate_lists:
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            if not isinstance(item, dict):
                continue
            row_payload = item.get("args") if isinstance(item.get("args"), dict) else item
            row = _presentation_row(
                dict(row_payload),
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id,
                tool_name=str(item.get("tool_name") or tool_name or ""),
            )
            if bundle_ui.get("write_set"):
                row.setdefault("write_set", bundle_ui.get("write_set"))
            if bundle_ui.get("kind"):
                row.setdefault("bundle_kind", bundle_ui.get("kind"))
            rows.append(row)
        if rows:
            return rows

    if payload and not {"bundle_ui", "preview", "staged_writes"} & set(payload):
        return [
            _presentation_row(
                payload,
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id,
                tool_name=tool_name,
            )
        ]
    return []


def _approval_is_expired(approval: ApprovalResponse, *, now: datetime | None = None) -> bool:
    if str(approval.status or "").upper() == "EXPIRED":
        return True
    expires_at = approval.expires_at
    if expires_at is None:
        return False
    current = now or datetime.utcnow()
    try:
        if expires_at.tzinfo is not None and current.tzinfo is None:
            current = current.replace(tzinfo=expires_at.tzinfo)
        if expires_at.tzinfo is None and current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        return expires_at <= current and str(approval.status or "").upper() == "PENDING"
    except TypeError:
        return False


def _latest_approval(approvals: list[ApprovalResponse]) -> ApprovalResponse | None:
    if not approvals:
        return None
    return max(approvals, key=lambda row: row.decided_at or row.created_at)


def _latest_terminal_event(timeline: list[TimelineEventResponse]) -> TimelineEventResponse | None:
    terminal_events = [event for event in timeline if event.event_type in _PRESENTATION_TERMINAL_EVENTS]
    if not terminal_events:
        return None
    return max(terminal_events, key=lambda event: event.created_at)


def _latest_user_event(timeline: list[TimelineEventResponse]) -> TimelineEventResponse | None:
    user_events = [event for event in timeline if event.event_type == "user_message"]
    if not user_events:
        return None
    return max(user_events, key=lambda event: event.created_at)


def _has_terminal_event_after_latest_user(timeline: list[TimelineEventResponse]) -> bool:
    latest_user = _latest_user_event(timeline)
    if latest_user is None:
        return False
    return any(
        (
            event.event_type in _PRESENTATION_TERMINAL_EVENTS
            or (
                event.event_type == "approval_decided"
                and str(event.status or "").upper() in {"REJECTED", "EXPIRED"}
            )
        )
        and event.created_at >= latest_user.created_at
        and (not latest_user.turn_id or event.turn_id in {None, latest_user.turn_id})
        for event in timeline
    )


def _is_actionable_prompt_text(text: str | None) -> bool:
    if not text or not text.strip():
        return False
    try:
        return assess_intent(text).kind == "operations"
    except Exception:
        return False


def _is_orphan_turn_state(
    *,
    session: Any,
    pending_approval: ApprovalResponse | None,
    timeline: list[TimelineEventResponse],
) -> bool:
    session_status = str(getattr(session, "status", "") or "").upper()
    if session_status != "IDLE" or pending_approval is not None or is_user_cancelled_session(session):
        return False
    latest_user = _latest_user_event(timeline)
    if latest_user is None:
        return False
    if _has_terminal_event_after_latest_user(timeline):
        return False
    intent = getattr(session, "current_intent", None) or latest_user.content
    return _is_actionable_prompt_text(intent)


def _rows_from_steps(
    steps: list[PlanStepResponse],
    *,
    operation_id: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in steps:
        status = str(step.status or "").upper()
        default_status = "failed" if status in {"FAILED", "AMBIGUOUS"} else "succeeded"
        approval_id = step.approval_id
        if isinstance(step.result, dict):
            approval_id = str(
                step.result.get("approval_id")
                or step.result.get("_approval_id")
                or approval_id
                or ""
            ).strip() or None
        if status in {"DONE", "FAILED", "AMBIGUOUS"}:
            rows.extend(
                _operation_rows_from_result(
                    step.result if isinstance(step.result, dict) else None,
                    default_status=default_status,
                    operation_id=operation_id or step.plan_id,
                    approval_id=approval_id,
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    fallback_args=step.args if _is_write_tool_name(step.tool_name) else None,
                )
            )
    return rows


def _rows_from_tool_events(timeline: list[TimelineEventResponse]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in timeline:
        if event.event_type != "tool_result":
            continue
        details = event.details if isinstance(event.details, dict) else {}
        result = details.get("result") if isinstance(details.get("result"), dict) else None
        args = details.get("args") if isinstance(details.get("args"), dict) else {}
        status = str(event.status or "").upper()
        default_status = "failed" if status in {"FAILED", "AMBIGUOUS"} else "succeeded"
        rows.extend(
            _operation_rows_from_result(
                result,
                default_status=default_status,
                operation_id=event.operation_id,
                approval_id=event.approval_id,
                step_id=event.step_id,
                tool_name=event.tool_name,
                fallback_args=args if _is_write_tool_name(event.tool_name) or status in {"FAILED", "AMBIGUOUS"} else None,
            )
        )
    return rows


def _dedupe_presentation_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _row_status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = _normalize_row_status(row.get("status"), default="unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _presentation_invariants(
    *,
    session: Any,
    approvals: list[ApprovalResponse],
    steps: list[PlanStepResponse],
    rows: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    terminal_event: TimelineEventResponse | None,
    pending_approval: ApprovalResponse | None,
) -> dict[str, Any]:
    counts = _row_status_counts(rows)
    rejected = [row.approval_id for row in approvals if str(row.status or "").upper() == "REJECTED"]
    expired = [row.approval_id for row in approvals if _approval_is_expired(row)]
    failed_steps = [step.step_id for step in steps if str(step.status or "").upper() in {"FAILED", "AMBIGUOUS"}]
    completed_mutation_steps = [
        step.step_id
        for step in steps
        if _is_write_tool_name(step.tool_name) and str(step.status or "").upper() == "DONE"
    ]
    return {
        "session_status": getattr(session, "status", None),
        "has_pending_approval": pending_approval is not None,
        "pending_approval_id": pending_approval.approval_id if pending_approval else None,
        "has_rejected_approval": bool(rejected),
        "rejected_approval_ids": rejected,
        "has_expired_approval": bool(expired),
        "expired_approval_ids": expired,
        "has_failed_steps": bool(failed_steps),
        "failed_step_ids": failed_steps,
        "has_completed_mutation_steps": bool(completed_mutation_steps),
        "completed_mutation_step_ids": completed_mutation_steps,
        "has_sources": bool(sources),
        "row_status_counts": counts,
        "has_partial_failure_rows": counts.get("succeeded", 0) > 0 and counts.get("failed", 0) > 0,
        "has_empty_final_response": bool(terminal_event and not _trimmed(terminal_event.content)),
    }


def _presentation_diagnostics(
    *,
    session: Any,
    terminal_event: TimelineEventResponse | None,
    reason: str,
    steps: list[PlanStepResponse],
) -> dict[str, Any]:
    diagnostics = {
        "reason": reason,
        "session_status": getattr(session, "status", None),
        "session_error": getattr(session, "error", None),
        "terminal_event_id": terminal_event.event_id if terminal_event else None,
        "terminal_event_type": terminal_event.event_type if terminal_event else None,
        "step_errors": [
            {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "status": step.status,
                "last_error": step.last_error,
            }
            for step in steps
            if str(step.status or "").upper() in {"FAILED", "AMBIGUOUS"} or step.last_error
        ],
    }
    replan_spine = _replan_spine_from_session_context(session)
    if replan_spine:
        diagnostics["replan_spine"] = replan_spine
        diagnostics["replan_limit_reached"] = bool(replan_spine.get("replan_limit_reached"))
    return diagnostics


def _replan_spine_from_session_context(session: Any) -> dict[str, Any]:
    context = getattr(session, "replan_context", None)
    if not isinstance(context, dict):
        return {}
    live_replan_spine = context.get("live_replan_spine")
    if isinstance(live_replan_spine, dict):
        return dict(live_replan_spine)
    for candidate in _replan_context_candidates(context):
        replan_spine = candidate.get("replan_spine")
        if isinstance(replan_spine, dict):
            return dict(replan_spine)
        response_context = candidate.get("response_document_context")
        if not isinstance(response_context, dict):
            continue
        response_diagnostics = response_context.get("diagnostics")
        if not isinstance(response_diagnostics, dict):
            continue
        replan_spine = response_diagnostics.get("replan_spine")
        if isinstance(replan_spine, dict):
            return dict(replan_spine)
    return {}


def _replan_context_candidates(context: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [context]
    for key in ("intent_contract", "planner_owned_agent_graph"):
        nested = context.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    return candidates


def _response_document_context_from_replan_context(context: dict[str, Any]) -> dict[str, Any]:
    for candidate in _replan_context_candidates(context):
        response_context = candidate.get("response_document_context")
        if isinstance(response_context, dict):
            return response_context
    return {}


def _response_document_diagnostics_from_replan_context(context: dict[str, Any]) -> dict[str, Any]:
    response_context = _response_document_context_from_replan_context(context)
    if not isinstance(response_context, dict):
        return {}
    response_diagnostics = response_context.get("diagnostics")
    if not isinstance(response_diagnostics, dict):
        return {}
    return response_diagnostics


def _replan_limit_reached(session: Any) -> bool:
    replan_spine = _replan_spine_from_session_context(session)
    return bool(replan_spine.get("replan_limit_reached"))


def _replan_limit_summary(session: Any) -> str | None:
    context = getattr(session, "replan_context", None)
    if not isinstance(context, dict):
        return None
    response_diagnostics = _response_document_diagnostics_from_replan_context(context)
    summary = str(response_diagnostics.get("summary") or "").strip()
    return summary or None


def _typed_blocked_reason(session: Any, *, default: str = "session_blocked") -> str:
    if _replan_limit_reached(session):
        return "replan_limit_reached"
    context = getattr(session, "replan_context", None)
    if isinstance(context, dict):
        reason = str(context.get("blocked_reason") or "").strip()
        if reason:
            return reason
    error = str(getattr(session, "error", "") or "")
    for reason in ("planner_no_action", "unable_to_start_request", "orphan_turn_state"):
        if reason in error:
            return reason
    return default


def _derive_snapshot_presentation(
    *,
    session: Any,
    plan: PlanResponse | None,
    steps: list[PlanStepResponse],
    pending_approval: ApprovalResponse | None,
    approvals: list[ApprovalResponse],
    timeline: list[TimelineEventResponse],
) -> PresentationResponse:
    operation_id = _presentation_operation_id(session=session, plan=plan, timeline=timeline)
    sources = _presentation_sources(plan=plan, timeline=timeline)
    terminal_event = _latest_terminal_event(timeline)
    latest_approval = _latest_approval(approvals)

    step_rows = _dedupe_presentation_rows(
        _rows_from_steps(steps, operation_id=operation_id) + _rows_from_tool_events(timeline)
    )
    invariants = _presentation_invariants(
        session=session,
        approvals=approvals,
        steps=steps,
        rows=step_rows,
        sources=sources,
        terminal_event=terminal_event,
        pending_approval=pending_approval,
    )
    session_status = str(getattr(session, "status", "") or "").upper()

    if is_user_cancelled_session(session):
        return PresentationResponse(
            kind="cancelled",
            state="cancelled",
            operation_id=operation_id,
            summary=USER_CANCELLED_TIMELINE_CONTENT,
            rows=step_rows,
            sources=sources,
            diagnostics=_presentation_diagnostics(
                session=session,
                terminal_event=terminal_event,
                reason=USER_CANCELLED_REASON,
                steps=steps,
            ),
            invariants={**invariants, "full_success_forbidden": True},
        )

    if pending_approval is not None and _approval_is_expired(pending_approval):
        rows = _approval_rows_from_args(
            pending_approval.args,
            default_status="expired",
            operation_id=operation_id or pending_approval.plan_id,
            approval_id=pending_approval.approval_id,
            tool_name=pending_approval.tool_name,
        )
        return PresentationResponse(
            kind="expired",
            state="expired",
            operation_id=operation_id or pending_approval.plan_id,
            approval_id=pending_approval.approval_id,
            summary=pending_approval.risk_summary or "Approval expired before it could be applied.",
            rows=rows,
            sources=sources,
            diagnostics=_presentation_diagnostics(
                session=session,
                terminal_event=terminal_event,
                reason="approval_expired",
                steps=steps,
            ),
            invariants={**invariants, "full_success_forbidden": True},
        )

    if pending_approval is not None:
        rows = _approval_rows_from_args(
            pending_approval.args,
            default_status="pending",
            operation_id=operation_id or pending_approval.plan_id,
            approval_id=pending_approval.approval_id,
            tool_name=pending_approval.tool_name,
        )
        return PresentationResponse(
            kind="approval_required",
            state="pending",
            operation_id=operation_id or pending_approval.plan_id,
            approval_id=pending_approval.approval_id,
            summary=pending_approval.risk_summary or "Approval is required before the operation can continue.",
            rows=rows,
            sources=sources,
            diagnostics={
                "reason": "approval_pending",
                "expires_at": pending_approval.expires_at.isoformat() if pending_approval.expires_at else None,
                "side_effect_level": pending_approval.side_effect_level,
            },
            invariants={**invariants, "full_success_forbidden": True},
        )

    if latest_approval is not None and str(latest_approval.status or "").upper() == "REJECTED":
        rows = _approval_rows_from_args(
            latest_approval.args,
            default_status="rejected",
            operation_id=operation_id or latest_approval.plan_id,
            approval_id=latest_approval.approval_id,
            tool_name=latest_approval.tool_name,
        )
        return PresentationResponse(
            kind="rejected",
            state="rejected",
            operation_id=operation_id or latest_approval.plan_id,
            approval_id=latest_approval.approval_id,
            summary=latest_approval.rejection_reason or "Approval was rejected; the requested mutation was not applied.",
            rows=rows,
            sources=sources,
            diagnostics=_presentation_diagnostics(
                session=session,
                terminal_event=terminal_event,
                reason="approval_rejected",
                steps=steps,
            ),
            invariants={**invariants, "full_success_forbidden": True},
        )

    if latest_approval is not None and _approval_is_expired(latest_approval):
        rows = _approval_rows_from_args(
            latest_approval.args,
            default_status="expired",
            operation_id=operation_id or latest_approval.plan_id,
            approval_id=latest_approval.approval_id,
            tool_name=latest_approval.tool_name,
        )
        return PresentationResponse(
            kind="expired",
            state="expired",
            operation_id=operation_id or latest_approval.plan_id,
            approval_id=latest_approval.approval_id,
            summary=latest_approval.risk_summary or "Approval expired; the stale approval cannot be applied.",
            rows=rows,
            sources=sources,
            diagnostics=_presentation_diagnostics(
                session=session,
                terminal_event=terminal_event,
                reason="approval_expired",
                steps=steps,
            ),
            invariants={**invariants, "full_success_forbidden": True},
        )

    if session_status == "BLOCKED":
        reason = _typed_blocked_reason(session)
        diagnostics = _presentation_diagnostics(
            session=session,
            terminal_event=terminal_event,
            reason=reason,
            steps=steps,
        )
        context = getattr(session, "replan_context", None)
        if isinstance(context, dict) and context.get("original_session_status"):
            diagnostics["original_session_status"] = context.get("original_session_status")
        summary = (
            _replan_limit_summary(session)
            if reason == "replan_limit_reached"
            else None
        )
        return PresentationResponse(
            kind="diagnostic",
            state="blocked",
            operation_id=operation_id,
            summary=summary or getattr(session, "error", None) or (terminal_event.content if terminal_event else "Execution blocked."),
            rows=step_rows,
            sources=sources,
            diagnostics=diagnostics,
            invariants={**invariants, "full_success_forbidden": True},
        )

    row_counts = invariants.get("row_status_counts") if isinstance(invariants.get("row_status_counts"), dict) else {}
    has_partial_rows = bool(row_counts.get("succeeded", 0) and row_counts.get("failed", 0))
    if has_partial_rows:
        return PresentationResponse(
            kind="partial_failure",
            state="failed",
            operation_id=operation_id,
            approval_id=next((row.get("approval_id") for row in step_rows if row.get("approval_id")), None),
            summary=(terminal_event.content if terminal_event and terminal_event.content else "Some rows failed while others succeeded."),
            rows=step_rows,
            sources=sources,
            diagnostics=_presentation_diagnostics(
                session=session,
                terminal_event=terminal_event,
                reason="partial_failure",
                steps=steps,
            ),
            invariants={**invariants, "full_success_forbidden": True},
        )

    if session_status == "FAILED":
        return PresentationResponse(
            kind="diagnostic",
            state="failed",
            operation_id=operation_id,
            approval_id=next((row.get("approval_id") for row in step_rows if row.get("approval_id")), None),
            summary=getattr(session, "error", None) or (terminal_event.content if terminal_event else "Session failed."),
            rows=step_rows,
            sources=sources,
            diagnostics=_presentation_diagnostics(
                session=session,
                terminal_event=terminal_event,
                reason="session_failed",
                steps=steps,
            ),
            invariants={**invariants, "full_success_forbidden": True},
        )

    if terminal_event is not None and terminal_event.event_type == "session_completed" and not _trimmed(terminal_event.content):
        return PresentationResponse(
            kind="diagnostic",
            state="failed",
            operation_id=operation_id,
            summary="Unable to render final response; assistant content was empty.",
            rows=step_rows,
            sources=sources,
            diagnostics=_presentation_diagnostics(
                session=session,
                terminal_event=terminal_event,
                reason="empty_final_response",
                steps=steps,
            ),
            invariants={**invariants, "full_success_forbidden": True},
        )

    has_completed_write = any(_is_write_tool_name(step.tool_name) and str(step.status or "").upper() == "DONE" for step in steps)
    if session_status == "COMPLETED" and has_completed_write:
        approval_id = next((row.get("approval_id") for row in step_rows if row.get("approval_id")), None)
        if approval_id is None and latest_approval and str(latest_approval.status or "").upper() == "APPROVED":
            approval_id = latest_approval.approval_id
        return PresentationResponse(
            kind="mutation_result",
            state="completed",
            operation_id=operation_id,
            approval_id=approval_id,
            summary=terminal_event.content if terminal_event else "Mutation completed.",
            rows=step_rows,
            sources=sources,
            diagnostics={"reason": "mutation_completed"},
            invariants={**invariants, "full_success_forbidden": False},
        )

    if session_status == "COMPLETED" and sources:
        answer_summary = sanitize_rag_answer_text(terminal_event.content if terminal_event else (plan.plan_explanation if plan else None))
        return PresentationResponse(
            kind="knowledge_answer",
            state="completed",
            operation_id=operation_id,
            summary=answer_summary,
            rows=step_rows,
            sources=sources,
            diagnostics={"reason": "source_backed_answer"},
            invariants={**invariants, "full_success_forbidden": False},
        )

    if session_status == "COMPLETED":
        return PresentationResponse(
            kind="answer",
            state="completed",
            operation_id=operation_id,
            summary=terminal_event.content if terminal_event else (plan.plan_explanation if plan else None),
            rows=step_rows,
            sources=sources,
            diagnostics={"reason": "completed_answer"},
            invariants={**invariants, "full_success_forbidden": False},
        )

    pending_state = "pending" if session_status in {"PLANNING", "EXECUTING", "WAITING_CONFIRMATION"} else "blocked"
    return PresentationResponse(
        kind="diagnostic",
        state=pending_state,
        operation_id=operation_id,
        summary=terminal_event.content if terminal_event else None,
        rows=step_rows,
        sources=sources,
        diagnostics=_presentation_diagnostics(
            session=session,
            terminal_event=terminal_event,
            reason="non_terminal_snapshot",
            steps=steps,
        ),
        invariants=invariants,
    )


def _presentation_for_event(ev: TimelineEventResponse) -> PresentationResponse | None:
    operation_id = ev.operation_id or _trimmed((ev.step_context or {}).get("plan_id")) or None
    details = ev.details if isinstance(ev.details, dict) else {}
    if ev.event_type == "approval_required":
        status = str(ev.status or "").upper()
        args = details.get("args") if isinstance(details.get("args"), dict) else {}
        if status == "REJECTED":
            kind = "rejected"
            state = "rejected"
            row_status = "rejected"
            reason = "approval_rejected"
        elif status == "EXPIRED":
            kind = "expired"
            state = "expired"
            row_status = "expired"
            reason = "approval_expired"
        elif status in {"APPROVED", "ACCEPTED"}:
            kind = "approval_required"
            state = "completed"
            row_status = "succeeded"
            reason = "approval_completed"
        else:
            kind = "approval_required"
            state = "pending"
            row_status = "pending"
            reason = "approval_pending"
        return PresentationResponse(
            kind=kind,  # type: ignore[arg-type]
            state=state,  # type: ignore[arg-type]
            operation_id=operation_id,
            approval_id=ev.approval_id,
            summary=ev.content,
            rows=_approval_rows_from_args(
                args,
                default_status=row_status,
                operation_id=operation_id,
                approval_id=ev.approval_id,
                tool_name=ev.tool_name,
            ),
            diagnostics={"reason": reason, "event_type": ev.event_type, "event_status": ev.status},
            invariants={"full_success_forbidden": state in {"pending", "rejected", "expired"}},
        )
    if ev.event_type == "approval_decided":
        rejected = str(ev.status or "").upper() == "REJECTED"
        return PresentationResponse(
            kind="rejected" if rejected else "approval_required",
            state="rejected" if rejected else "completed",
            operation_id=operation_id,
            approval_id=ev.approval_id,
            summary=ev.content,
            diagnostics={
                "reason": "approval_rejected" if rejected else "approval_decided",
                "event_type": ev.event_type,
                "event_status": ev.status,
            },
            invariants={"full_success_forbidden": rejected},
        )
    if ev.event_type == "tool_result":
        status = str(ev.status or "").upper()
        default_status = "failed" if status in {"FAILED", "AMBIGUOUS"} else "succeeded"
        rows = _operation_rows_from_result(
            details.get("result") if isinstance(details.get("result"), dict) else None,
            default_status=default_status,
            operation_id=operation_id,
            approval_id=ev.approval_id,
            step_id=ev.step_id,
            tool_name=ev.tool_name,
            fallback_args=details.get("args") if isinstance(details.get("args"), dict) else None,
        )
        counts = _row_status_counts(rows)
        partial = bool(counts.get("succeeded", 0) and counts.get("failed", 0))
        failed = status in {"FAILED", "AMBIGUOUS"}
        kind = "partial_failure" if partial else "diagnostic" if failed else "mutation_result" if _is_write_tool_name(ev.tool_name) else "answer"
        state = "failed" if (partial or failed) else "completed"
        return PresentationResponse(
            kind=kind,  # type: ignore[arg-type]
            state=state,  # type: ignore[arg-type]
            operation_id=operation_id,
            approval_id=ev.approval_id,
            summary=ev.content,
            rows=rows,
            diagnostics={"reason": "tool_result", "event_status": ev.status},
            invariants={
                "row_status_counts": counts,
                "has_partial_failure_rows": partial,
                "full_success_forbidden": partial or failed,
            },
        )
    return None


def _attach_typed_presentations_to_events(
    events: list[TimelineEventResponse],
    *,
    snapshot_presentation: PresentationResponse,
) -> list[TimelineEventResponse]:
    terminal = _latest_terminal_event(events)
    terminal_id = terminal.event_id if terminal is not None else None
    out: list[TimelineEventResponse] = []
    for event in events:
        presentation = snapshot_presentation if event.event_id == terminal_id else _presentation_for_event(event)
        out.append(event.model_copy(update={"presentation": presentation}) if presentation is not None else event)
    return out


def _response_document_turn_id(timeline: list[TimelineEventResponse], *, session_id: str) -> str:
    for event in reversed(timeline):
        if event.turn_id:
            return event.turn_id
    return f"session:{session_id}"


def _response_document_revision(
    *,
    cursor: int,
    session: Any,
    timeline: list[TimelineEventResponse],
) -> tuple[int, str]:
    event_seq = getattr(session, "event_seq", None)
    if event_seq is not None:
        try:
            return max(0, int(event_seq or 0)), "event_seq"
        except (TypeError, ValueError):
            pass
    try:
        return max(0, int(cursor or 0)), "event_seq"
    except (TypeError, ValueError):
        pass
    updated_at = getattr(session, "updated_at", None)
    if isinstance(updated_at, datetime):
        return max(0, int(updated_at.timestamp() * 1000)), "session_updated_at"
    if timeline:
        latest = max(event.created_at for event in timeline)
        return max(0, int(latest.timestamp() * 1000)), "timeline_timestamp"
    return 0, "empty_snapshot"


def _response_document_state(
    *,
    session: Any,
    pending_approval: ApprovalResponse | None,
    presentation: PresentationResponse,
) -> str:
    session_status = str(getattr(session, "status", "") or "").upper()
    if pending_approval is not None:
        return "waiting_approval"
    if session_status == "WAITING_CONFIRMATION":
        return "waiting_confirmation"
    if presentation.state == "completed":
        return "completed"
    if presentation.state == "failed":
        return "failed"
    if presentation.state == "blocked":
        return "blocked"
    if presentation.state == "rejected":
        return "rejected"
    if presentation.state == "expired":
        return "expired"
    if presentation.state == "cancelled":
        return "cancelled"
    return "running"


def _run_step_kind_for_activity(step: ActivityStepResponse) -> str:
    group = str(step.group or "")
    label = str(step.label or "").lower()
    if group == "planning":
        return "analysis"
    if group == "approval":
        return "approval"
    if group == "response":
        return "completed"
    if group == "system":
        return "cancelled" if "cancel" in label else "diagnostic"
    if group == "research":
        return "mutation" if "updating" in label or "updated" in label else "read"
    return "analysis"


def _run_step_state_for_activity(step: ActivityStepResponse) -> str:
    state = str(step.state or "")
    if state == "running":
        return "current"
    if state == "waiting":
        return "waiting"
    if state in {"success", "complete"}:
        return "completed"
    if state == "error":
        return "failed"
    return "pending"


def _run_steps_from_activity(
    *,
    activity_steps: list[ActivityStepResponse],
    operation_id: str | None,
    pending_approval: ApprovalResponse | None,
    presentation: PresentationResponse,
) -> list[RunStep]:
    rows = presentation.rows if isinstance(presentation.rows, list) else []
    run_steps: list[RunStep] = []
    for step in activity_steps:
        step_state = _run_step_state_for_activity(step)
        step_kind = _run_step_kind_for_activity(step)
        approval_id = (
            pending_approval.approval_id
            if pending_approval is not None and step_kind == "approval" and step_state in {"waiting", "current"}
            else None
        )
        run_steps.append(
            RunStep(
                step_id=step.id,
                kind=step_kind,  # type: ignore[arg-type]
                state=step_state,  # type: ignore[arg-type]
                title=step.label,
                summary=step.detail,
                approval_id=approval_id,
                operation_id=operation_id,
                record_count=len(rows) if step_kind in {"approval", "mutation"} and rows else None,
                current=step_state in {"current", "waiting"},
            )
        )
    return run_steps


def _current_response_step_id(run_steps: list[RunStep]) -> str | None:
    current = next((step for step in reversed(run_steps) if step.current), None)
    if current is not None:
        return current.step_id
    return run_steps[-1].step_id if run_steps else None


def _response_block_anchor(*, document_id: str, operation_id: str | None, approval_id: str | None) -> str:
    return approval_id or operation_id or document_id


def _diagnostic_severity(state: str) -> str:
    if state in {"failed", "blocked", "rejected", "expired", "cancelled"}:
        return "error"
    if state == "running":
        return "info"
    return "warning"


def _response_blocks_from_presentation(
    *,
    document_id: str,
    state: str,
    run_steps: list[RunStep],
    presentation: PresentationResponse,
) -> list[ResponseBlock]:
    operation_id = presentation.operation_id
    approval_id = presentation.approval_id
    anchor = _response_block_anchor(document_id=document_id, operation_id=operation_id, approval_id=approval_id)
    summary = _trimmed(presentation.summary) or ""
    rows = presentation.rows if isinstance(presentation.rows, list) else []
    sources = presentation.sources if isinstance(presentation.sources, list) else []
    diagnostics = presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {}
    reason = str(diagnostics.get("reason") or presentation.kind)

    blocks: list[ResponseBlock] = []
    if run_steps:
        blocks.append(
            RunActivityBlock(
                id=f"activity:{document_id}",
                step_ids=[step.step_id for step in run_steps],
            )
        )
    if summary:
        blocks.append(
            ShortMessageBlock(
                id=f"message:{anchor}:{state}",
                message=summary,
                status=state,  # type: ignore[arg-type]
            )
        )

    if presentation.kind == "approval_required" and presentation.state == "pending" and approval_id:
        blocks.append(
            ApprovalRequiredBlock(
                id=f"approval:{approval_id}",
                approval_id=approval_id,
                operation_id=operation_id,
                summary=summary or "Approval is required before the operation can continue.",
                rows=rows,
            )
        )

    if presentation.kind in {"mutation_result", "partial_failure"}:
        blocks.append(
            MutationResultBlock(
                id=f"mutation:{anchor}",
                operation_id=operation_id,
                approval_id=approval_id,
                summary=summary or "Mutation completed.",
                rows=rows,
                status="partial_failure" if presentation.kind == "partial_failure" else "completed",
            )
        )

    if presentation.kind == "knowledge_answer" and summary:
        blocks.append(
            KnowledgeAnswerBlock(
                id=f"knowledge:{anchor}",
                answer=summary,
                operation_id=operation_id,
            )
        )

    if rows:
        blocks.append(
            ResultTableBlock(
                id=f"table:{anchor}:affected-records",
                rows=rows,
                operation_id=operation_id,
                approval_id=approval_id,
            )
        )

    if sources:
        blocks.append(
            SourceListBlock(
                id=f"sources:{anchor}",
                sources=sources,
                operation_id=operation_id,
            )
        )

    if presentation.kind in {"diagnostic", "cancelled", "rejected", "expired", "partial_failure"}:
        blocks.append(
            DiagnosticBlock(
                id=f"diagnostic:{anchor}:{reason}",
                severity=_diagnostic_severity(state),  # type: ignore[arg-type]
                reason=reason,
                user_message=summary or "The request needs attention before it can continue.",
                technical_details=diagnostics,
            )
        )

    return blocks


def _build_response_document(
    *,
    session: Any,
    plan: PlanResponse | None,
    pending_approval: ApprovalResponse | None,
    timeline: list[TimelineEventResponse],
    activity_steps: list[ActivityStepResponse],
    presentation: PresentationResponse,
    cursor: int,
) -> ResponseDocument:
    session_id = str(getattr(session, "session_id", "") or "unknown-session")
    turn_id = _response_document_turn_id(timeline, session_id=session_id)
    operation_id = presentation.operation_id or (plan.plan_id if plan else None)
    document_id = f"rd:{session_id}:{turn_id}"
    revision, revision_source = _response_document_revision(cursor=cursor, session=session, timeline=timeline)
    state = _response_document_state(session=session, pending_approval=pending_approval, presentation=presentation)
    run_steps = _run_steps_from_activity(
        activity_steps=activity_steps,
        operation_id=operation_id,
        pending_approval=pending_approval,
        presentation=presentation,
    )
    blocks = _response_blocks_from_presentation(
        document_id=document_id,
        state=state,
        run_steps=run_steps,
        presentation=presentation,
    )
    summary = _trimmed(presentation.summary)
    return ResponseDocument(
        id=document_id,
        document_id=document_id,
        turn_id=turn_id,
        operation_id=operation_id,
        revision=revision,
        revision_source=revision_source,
        state=state,  # type: ignore[arg-type]
        status=state,  # type: ignore[arg-type]
        summary=summary,
        message=summary,
        current_step_id=_current_response_step_id(run_steps),
        run_steps=run_steps,
        blocks=blocks,
        invariants=presentation.invariants,
        diagnostics=presentation.diagnostics,
    )


class SessionSnapshotService:
    def __init__(
        self,
        *,
        session_mgr: SessionManager,
        memory_manager: MemoryManager,
        tool_registry: ToolRegistry,
    ) -> None:
        self._session_mgr = session_mgr
        self._memory_manager = memory_manager
        self._tool_registry = tool_registry

    async def load_session_snapshot(self, *, db: AsyncSession, session_id: str) -> SessionSnapshotResponse | None:
        sess = await self._session_mgr.get_session(db, session_id=session_id)
        if not sess:
            return None
        tools_by_name = await self._tool_registry.get_tools_by_name(db)
        checkpoint_payload = await self._memory_manager.load_checkpoint(db, session_id=session_id)

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

        def _checkpoint_state_dict(payload: dict[str, Any] | None) -> dict[str, Any]:
            if not isinstance(payload, dict):
                return {}
            state = payload.get("state")
            if not isinstance(state, dict):
                return {}
            if "validated_plan" in state or "tool_outputs" in state or "completed_actions" in state:
                return state
            for key in ("values", "channel_values", "agent_state"):
                candidate = state.get(key)
                if isinstance(candidate, dict) and (
                    "validated_plan" in candidate or "tool_outputs" in candidate or "completed_actions" in candidate
                ):
                    return candidate
            return state

        graph_native_session = await is_graph_native_session(db, sess, plan=current_plan)
        if not graph_native_session and isinstance(checkpoint_payload, dict):
            state_payload = checkpoint_payload.get("state")
            graph_native_session = (
                isinstance(state_payload, dict)
                and state_payload.get("kind") == "langgraph_native_checkpoint"
            )
        allow_step_projection = (not graph_native_session) or allows_persisted_step_projection(current_plan)

        checkpoint_state = _checkpoint_state_dict(checkpoint_payload if isinstance(checkpoint_payload, dict) else None)
        checkpoint_draft = checkpoint_state.get("validated_plan") if isinstance(checkpoint_state.get("validated_plan"), dict) else {}
        checkpoint_steps = checkpoint_draft.get("steps") if isinstance(checkpoint_draft.get("steps"), list) else []
        checkpoint_tool_outputs = (
            checkpoint_state.get("tool_outputs") if isinstance(checkpoint_state.get("tool_outputs"), list) else []
        )
        checkpoint_completed_actions = (
            checkpoint_state.get("completed_actions") if isinstance(checkpoint_state.get("completed_actions"), list) else []
        )

        pending_approval = next((row for row in reversed(approval_rows) if row.status == "PENDING"), None)
        tool_result_messages = [row for row in message_rows if row.role == "tool_result"]
        user_messages = [row for row in message_rows if row.role == "user"]
        assistant_messages = [row for row in message_rows if row.role == "assistant"]
        plan_messages = [row for row in assistant_messages if row.tool_name == "__plan__"]
        plan_messages_by_plan_id = {
            row.step_id: row
            for row in plan_messages
            if isinstance(row.step_id, str) and row.step_id.strip()
        }
        unscoped_plan_messages = [row for row in plan_messages if not row.step_id]
        conversation_messages = [row for row in assistant_messages if row.tool_name == "__conversation__"]
        confirmation_messages = [row for row in assistant_messages if row.tool_name == "__confirmation__"]
        snapshot_step_rows: list[PlanStepRow] = []

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

        _raw_plan_id = (current_plan.plan_id if current_plan else None) or sess.plan_id
        snapshot_plan_id = (
            _raw_plan_id.strip()
            if isinstance(_raw_plan_id, str) and _raw_plan_id.strip()
            else None
        )
        if allow_step_projection:
            snapshot_step_rows = (
                [step for step in step_rows if step.plan_id == snapshot_plan_id]
                if snapshot_plan_id
                else list(step_rows)
            )
        step_ids_by_plan: dict[str, list[str]] = {}
        for step in snapshot_step_rows:
            step_ids_by_plan.setdefault(step.plan_id, []).append(step.step_id)

        def _step_ctx(extra: dict[str, Any] | None = None) -> dict[str, Any]:
            base: dict[str, Any] = {**_session_ctx(), **(extra or {})}
            if snapshot_plan_id:
                base.setdefault("plan_id", snapshot_plan_id)
            return base

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

        graph_approval_rows = [
            row
            for row in approval_rows
            if (getattr(row, "subject_type", "step") or "step") == "graph"
        ]
        def _plan_timeline_created_at(plan_row: PlanRow) -> datetime:
            return plan_row.created_at

        approval_decided_at_by_id = {
            row.approval_id: row.decided_at
            for row in approval_rows
            if row.approval_id and row.decided_at
        }

        def _approval_id_from_payload(*payloads: Any, fallback: str | None = None) -> str | None:
            for payload in payloads:
                if not isinstance(payload, dict):
                    continue
                candidate = (
                    payload.get("approval_id")
                    or payload.get("_approval_id")
                    or (payload.get("result") if isinstance(payload.get("result"), dict) else {}).get("approval_id")
                )
                if candidate:
                    return str(candidate)
            return fallback

        def _commit_event_time(default: datetime, approval_id: str | None, offset_ms: int) -> datetime:
            if approval_id and approval_id in approval_decided_at_by_id:
                return approval_decided_at_by_id[approval_id] + timedelta(milliseconds=offset_ms)
            return default

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

        # Pair each RAG conversation message with its corresponding no-op plan
        # so that sources/safety_content carried on the plan can be surfaced on
        # the timeline event the frontend actually consumes for these turns.
        noop_plans_in_order = [p for p in plan_rows if _is_noop_plan(p)]
        plan_by_conversation_id: dict[str, PlanRow] = {}
        for idx_msg, msg in enumerate(conversation_messages):
            if idx_msg < len(noop_plans_in_order):
                plan_by_conversation_id[msg.message_id] = noop_plans_in_order[idx_msg]

        for msg in conversation_messages:
            if _is_approval_wait_text(msg.content):
                continue
            associated_plan = plan_by_conversation_id.get(msg.message_id)
            convo_details: dict[str, Any] = {}
            if associated_plan is not None:
                plan_sources = associated_plan.sources or []
                if plan_sources:
                    convo_details["sources"] = plan_sources
                if associated_plan.safety_content:
                    convo_details["safety_content"] = associated_plan.safety_content
                convo_details["plan_id"] = associated_plan.plan_id
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
                    details=(convo_details or None),
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
            plan_message = plan_messages_by_plan_id.get(plan_row.plan_id)
            if plan_message is None and idx < len(unscoped_plan_messages):
                plan_message = unscoped_plan_messages[idx]
            plan_event_created_at = _plan_timeline_created_at(plan_row)
            content = _plan_timeline_content(
                session_status=sess.status,
                plan_row=plan_row,
                plan_message=plan_message,
            )
            events.append(
                _timeline_event(
                    event_id=f"plan:{plan_row.plan_id}",
                    event_type="plan_created",
                    content=content,
                    created_at=plan_event_created_at,
                    status="PLANNING",
                    mode=(plan_message.mode if plan_message and getattr(plan_message, "mode", None) else None),
                    turn_id=_turn_id_for_time(plan_event_created_at),
                    step_context={**_session_ctx(), "plan_id": plan_row.plan_id, "plan_version": plan_row.version},
                    details={
                        "plan_id": plan_row.plan_id,
                        "version": plan_row.version,
                        "kind": plan_row.kind,
                        "status": plan_row.status,
                        "plan_explanation": plan_row.plan_explanation,
                        "risk_summary": plan_row.risk_summary,
                        "sources": plan_row.sources,
                        "safety_content": plan_row.safety_content,
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

        execution_started_at = min((step.started_at for step in snapshot_step_rows if step.started_at), default=None)
        if execution_started_at:
            events.append(
                _timeline_event(
                    event_id=f"exec:{session_id}",
                    event_type="execution_started",
                    content="Execution started.",
                    created_at=execution_started_at,
                    status="EXECUTING",
                    turn_id=_turn_id_for_time(execution_started_at),
                    step_context=_step_ctx(),
                )
            )

        tool_messages_by_step = {msg.step_id: msg for msg in tool_result_messages if msg.step_id}
        for step in snapshot_step_rows:
            if step.status == "IN_PROGRESS" and step.started_at:
                events.append(
                    _timeline_event(
                        event_id=f"step-started:{step.step_id}",
                        event_type="tool_started",
                        content="Step started.",
                        created_at=step.started_at,
                        turn_id=_turn_id_for_time(step.started_at),
                        step_context=_step_ctx(
                            {
                                "step_id": step.step_id,
                                "step_index": step.step_index,
                                "tool_name": step.tool_name,
                                "approval_id": step.approval_id,
                            }
                        ),
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
                deterministic_summary = summarize_tool_result(
                    tool_name=step.tool_name,
                    result=step.result if isinstance(step.result, dict) else None,
                    args=step.args if isinstance(step.args, dict) else {},
                )
                content = (
                    step.result_summary
                    or deterministic_summary
                    or (f"{step.tool_name} failed: {step.last_error}" if step.status == "FAILED" else f"{step.tool_name} completed.")
                )
            else:
                continue
            result_approval_id = _approval_id_from_payload(
                step.result if isinstance(step.result, dict) else None,
                step.args if isinstance(step.args, dict) else None,
                fallback=step.approval_id,
            )
            created_at = _commit_event_time(created_at, result_approval_id, 5 + step.step_index)

            events.append(
                _timeline_event(
                    event_id=f"step:{step.step_id}",
                    event_type="tool_result",
                    content=content,
                    created_at=created_at,
                    turn_id=_turn_id_for_time(created_at),
                    step_context=_step_ctx(
                        {
                            "step_id": step.step_id,
                            "step_index": step.step_index,
                            "tool_name": step.tool_name,
                            "approval_id": step.approval_id,
                        }
                    ),
                    step_id=step.step_id,
                    approval_id=result_approval_id,
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

        def _graph_event_base_time() -> datetime:
            if user_messages_sorted:
                return user_messages_sorted[-1].created_at
            return sess.session_started_at or sess.created_at or sess.updated_at or datetime.utcnow()

        def _graph_event_time(offset: int) -> datetime:
            return _graph_event_base_time() + timedelta(milliseconds=offset)

        def _graph_tool_event_key(row: dict[str, Any], idx: int) -> str:
            raw_key = row.get("tool_call_id") or row.get("output_ref") or row.get("idempotency_key") or idx
            return str(raw_key).replace(":", "_")

        should_project_checkpoint_timeline = bool(
            graph_native_session
            and checkpoint_state
            and not snapshot_step_rows
        )
        if should_project_checkpoint_timeline:
            has_plan_timeline = any(
                event.event_type == "plan_created"
                for event in events
            )
            if checkpoint_draft and not has_plan_timeline:
                plan_content = str(checkpoint_draft.get("plan_explanation") or "Execution plan created.")
                events.append(
                    _timeline_event(
                        event_id=f"graph-plan:{session_id}",
                        event_type="plan_created",
                        content=plan_content,
                        created_at=_graph_event_time(10),
                        status="PLANNING",
                        turn_id=_turn_id_for_time(_graph_event_time(10)),
                        step_context=_step_ctx({"source": "checkpoint_projection"}),
                        details={
                            "plan_id": snapshot_plan_id,
                            "plan_explanation": plan_content,
                            "risk_summary": checkpoint_draft.get("risk_summary"),
                        },
                    )
                )

            graph_tool_actions = [
                action
                for action in checkpoint_completed_actions
                if isinstance(action, dict) and action.get("phase") == "tool_execution"
            ]
            for idx_action, action in enumerate(graph_tool_actions):
                tool_name = str(action.get("tool_name") or "")
                if not tool_name:
                    continue
                key = _graph_tool_event_key(action, idx_action)
                args = action.get("args") if isinstance(action.get("args"), dict) else {}
                approval_id = _approval_id_from_payload(action, args)
                created_at = _commit_event_time(_graph_event_time(20 + idx_action * 20), approval_id, 2 + idx_action)
                events.append(
                    _timeline_event(
                        event_id=f"graph-tool-started:{session_id}:{idx_action}:{key}",
                        event_type="tool_started",
                        content="Tool started.",
                        created_at=created_at,
                        turn_id=_turn_id_for_time(created_at),
                        step_context=_step_ctx(
                            {
                                "source": "checkpoint_projection",
                                "tool_name": tool_name,
                            }
                        ),
                        step_id=f"lg-step-{idx_action}",
                        approval_id=approval_id,
                        tool_name=tool_name,
                        status="IN_PROGRESS",
                        details={"args": args},
                    )
                )

            for idx_out, output in enumerate(checkpoint_tool_outputs):
                if not isinstance(output, dict):
                    continue
                tool_name = str(output.get("tool_name") or output.get("tool") or "")
                if not tool_name:
                    continue
                args = output.get("args") if isinstance(output.get("args"), dict) else {}
                result = output.get("result") if isinstance(output.get("result"), dict) else None
                last_error = str(output.get("error") or output.get("last_error") or "") or None
                status = str(output.get("status") or ("FAILED" if last_error else "DONE"))
                summary = str(output.get("summary") or output.get("result_summary") or "").strip()
                if _looks_like_raw_json_text(summary):
                    summary = ""
                deterministic_summary = summarize_tool_result(tool_name=tool_name, result=result, args=args)
                fallback_content = deterministic_summary or (
                    f"{tool_name} failed: {last_error}" if last_error else f"{tool_name} completed."
                )
                content = summary or fallback_content
                key = _graph_tool_event_key(output, idx_out)
                approval_id = _approval_id_from_payload(output, result, args)
                created_at = _commit_event_time(_graph_event_time(25 + idx_out * 20), approval_id, 5 + idx_out)
                events.append(
                    _timeline_event(
                        event_id=f"graph-tool-result:{session_id}:{idx_out}:{key}",
                        event_type="tool_result",
                        content=content,
                        created_at=created_at,
                        turn_id=_turn_id_for_time(created_at),
                        step_context=_step_ctx(
                            {
                                "source": "checkpoint_projection",
                                "tool_name": tool_name,
                            }
                        ),
                        step_id=f"lg-step-{idx_out}",
                        approval_id=approval_id,
                        tool_name=tool_name,
                        status=status,
                        details=_build_tool_result_details(
                            tool_name=tool_name,
                            args=args,
                            result=result,
                            last_error=last_error,
                            content=content,
                            intent=sess.current_intent,
                        ),
                    )
                )

        for approval in approval_rows:
            tool = tools_by_name.get(approval.tool_name)
            missing_required = _missing_required_fields(approval.tool_name, approval.args)
            tool_schema = tool.input_schema if tool else None
            approval_subject_type = getattr(approval, "subject_type", "step") or "step"
            if approval.status == "PENDING" or approval_subject_type == "graph":
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
                        step_context=_step_ctx(
                            {
                                "approval_id": approval.approval_id,
                                "step_id": approval.step_id,
                                "tool_name": approval.tool_name,
                                "plan_id": getattr(approval, "plan_id", None) or snapshot_plan_id,
                            }
                        ),
                        approval_id=approval.approval_id,
                        step_id=approval.step_id,
                        tool_name=approval.tool_name,
                        status=approval.status,
                        details={
                            "subject_type": approval_subject_type,
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
                        step_context=_step_ctx(
                            {
                                "approval_id": approval.approval_id,
                                "step_id": approval.step_id,
                                "tool_name": approval.tool_name,
                                "plan_id": getattr(approval, "plan_id", None) or snapshot_plan_id,
                            }
                        ),
                        approval_id=approval.approval_id,
                        step_id=approval.step_id,
                        tool_name=approval.tool_name,
                        status=approval.status,
                        details={
                            "subject_type": approval_subject_type,
                            "plan_id": getattr(approval, "plan_id", None),
                            "decided_by": approval.decided_by,
                            "rejection_reason": approval.rejection_reason,
                        },
                    )
                )

        ambiguous_step = next((step for step in snapshot_step_rows if step.status == "AMBIGUOUS" and (step.completed_at or step.started_at)), None)
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
        if is_user_cancelled_session(sess):
            events.append(
                _timeline_event(
                    event_id=f"cancelled:{session_id}",
                    event_type="session_failed",
                    content=USER_CANCELLED_TIMELINE_CONTENT,
                    created_at=sess.updated_at,
                    status=sess.status,
                    turn_id=_turn_id_for_time(sess.updated_at),
                    step_context=_session_ctx(),
                    details={"reason": USER_CANCELLED_REASON},
                )
            )
        latest_user_at = user_messages_sorted[-1].created_at if user_messages_sorted else None
        has_completion_for_latest_turn = any(
            event.event_type == "session_completed"
            and (latest_user_at is None or event.created_at >= latest_user_at)
            for event in events
        )
        if sess.status == "COMPLETED" and pending_approval is None and not has_completion_for_latest_turn:
            useful_completion_message = next(
                (
                    msg
                    for msg in reversed(assistant_messages)
                    if (msg.content or "").strip()
                    and "Execution completed successfully" not in msg.content
                    and (msg.tool_name in {"__plan__", "__conversation__"} or msg.tool_name is None)
                ),
                None,
            )
            generic_completion_message = next(
                (msg for msg in reversed(assistant_messages) if "Execution completed successfully" in msg.content),
                None,
            )
            useful_tool_result_events = [
                event
                for event in events
                if event.event_type == "tool_result" and _is_operator_result_text(event.content)
            ]
            useful_tool_result_event = (
                max(useful_tool_result_events, key=_tool_result_completion_sort_key)
                if useful_tool_result_events
                else None
            )
            completed_at = (
                sess.completed_at
                or sess.updated_at
                or max((event.created_at for event in events), default=None)
                or datetime.utcnow()
            )
            completion_content = (
                useful_completion_message.content
                if useful_completion_message and useful_completion_message.content
                else generic_completion_message.content
                if generic_completion_message and generic_completion_message.content
                else "Execution completed successfully."
            )
            if useful_tool_result_event and (
                not useful_completion_message
                or _is_plan_like_completion_text(useful_completion_message.content)
                or (
                    _is_success_like_plan_text(useful_completion_message.content)
                    and not _is_rich_operator_completion_text(useful_completion_message.content)
                )
                or _is_approval_wait_text(useful_completion_message.content)
                or _looks_like_raw_json_text(useful_completion_message.content)
            ):
                completion_content = _operator_result_content_for_completion(useful_tool_result_event) or useful_tool_result_event.content
            events.append(
                _timeline_event(
                    event_id=f"completed:{session_id}",
                    event_type="session_completed",
                    content=completion_content,
                    created_at=completed_at,
                    status="COMPLETED",
                    turn_id=_turn_id_for_time(completed_at),
                    step_context=_step_ctx(),
                    details={
                        "plan_id": current_plan.plan_id if current_plan else sess.plan_id,
                        "sources": current_plan.sources if current_plan else [],
                        "safety_content": current_plan.safety_content if current_plan else None,
                    },
                )
            )

        events.sort(
            key=lambda event: (
                event.created_at,
                _TIMELINE_EVENT_PRIORITY.get(event.event_type, 99),
                event.event_id,
            )
        )
        events = _annotate_timeline_operation_ids(events)
        if graph_approval_rows and snapshot_plan_id:
            approval_turn_ids = {
                turn_id
                for turn_id in (_turn_id_for_time(row.created_at) for row in graph_approval_rows)
                if turn_id
            }
            if approval_turn_ids:
                operation_event_types = {
                    "user_message",
                    "plan_created",
                    "execution_started",
                    "tool_started",
                    "tool_result",
                    "approval_required",
                    "approval_decided",
                    "replan_requested",
                    "session_completed",
                    "session_blocked",
                    "session_failed",
                }
                events = [
                    event.model_copy(update={"operation_id": snapshot_plan_id})
                    if event.turn_id in approval_turn_ids and event.event_type in operation_event_types
                    else event
                    for event in events
                ]

        checkpoint_step_responses: list[PlanStepResponse] = []
        if graph_native_session and checkpoint_steps:
            outputs_by_tool: dict[str, dict[str, Any]] = {}
            for out in checkpoint_tool_outputs:
                if not isinstance(out, dict):
                    continue
                key = str(out.get("tool_name") or out.get("tool") or "").strip()
                if key and key not in outputs_by_tool:
                    outputs_by_tool[key] = out
            for idx_cp, raw_step in enumerate(checkpoint_steps):
                if not isinstance(raw_step, dict):
                    continue
                tool_name = str(raw_step.get("tool_name") or "")
                args = raw_step.get("args") if isinstance(raw_step.get("args"), dict) else {}
                output = outputs_by_tool.get(tool_name, {})
                output_result = output.get("result") if isinstance(output.get("result"), dict) else None
                output_error = str(output.get("error") or output.get("last_error") or "") or None
                output_summary = str(output.get("summary") or output.get("result_summary") or "")
                cp_status = str(output.get("status") or ("FAILED" if output_error else "NOT_STARTED"))
                if cp_status == "NOT_STARTED" and output_result:
                    cp_status = "DONE"
                checkpoint_step_responses.append(
                    PlanStepResponse(
                        step_id=f"lg-step-{idx_cp}",
                        plan_id=(current_plan.plan_id if current_plan else (sess.plan_id or "langgraph")),
                        session_id=sess.session_id,
                        step_index=idx_cp,
                        tool_name=tool_name,
                        args=args,
                        execution_mode=str(raw_step.get("execution_mode") or "single"),
                        bindings=raw_step.get("bindings") if isinstance(raw_step.get("bindings"), list) else [],
                        bulk_state=None,
                        status=cp_status,
                        idempotency_key=f"langgraph:{sess.session_id}:{idx_cp}",
                        requires_approval=bool(raw_step.get("requires_approval")),
                        approval_id=None,
                        retry_count=0,
                        max_retries=0,
                        last_error=output_error,
                        result=output_result,
                        result_summary=(output_summary or None),
                        started_at=None,
                        completed_at=None,
                    )
                )
        # Self-heal: pending_approval must reference a row that is still PENDING.
        # If the row was decided (APPROVED/REJECTED) but session.replan_context still
        # references it (e.g. crash mid-decide), null it out so the UI never re-shows
        # a stale approval card.
        healed_pending_approval = pending_approval
        if pending_approval is not None and pending_approval.status != "PENDING":
            healed_pending_approval = None

        # Also cross-check against approval state: a pending approval must keep the
        # browser in WAITING_APPROVAL even if a stale terminal row is still present.
        orphan_turn_state = _is_orphan_turn_state(
            session=sess,
            pending_approval=approval_to_response(healed_pending_approval) if healed_pending_approval else None,
            timeline=events,
        )
        if healed_pending_approval is not None:
            _effective_status = "WAITING_APPROVAL"
        elif orphan_turn_state:
            _effective_status = "BLOCKED"
        elif healed_pending_approval is None and sess.status == "WAITING_APPROVAL":
            _effective_status = sess.status
        else:
            _effective_status = sess.status
        _session_response = session_to_response(sess)
        if _effective_status != sess.status:
            update_payload: dict[str, Any] = {
                "status": _effective_status,
                "completed_at": None if _effective_status != "COMPLETED" else _session_response.completed_at,
            }
            if orphan_turn_state:
                context = dict(_session_response.replan_context or {})
                context["blocked_reason"] = ORPHAN_TURN_REASON
                context["original_session_status"] = sess.status
                update_payload["error"] = ORPHAN_TURN_MESSAGE
                update_payload["replan_context"] = context
            _session_response = _session_response.model_copy(
                update=update_payload
            )

        # Derive resume_hint: session is applying approved changes if it is EXECUTING
        # and replan_context carries a recent approval resume marker (decided within
        # the last 60 s and no tool results have arrived after that point yet).
        _resume_hint: ResumeHintResponse | None = None
        _rc = sess.replan_context if isinstance(sess.replan_context, dict) else {}
        _lr = _rc.get("langgraph_approval_resume")
        if (
            isinstance(_lr, dict)
            and str(_lr.get("status") or "").lower() == "approved"
            and _effective_status == "EXECUTING"
        ):
            _approval_decided_at_str = str(_lr.get("decided_at") or "").strip()
            _has_post_approval_tool = False
            if _approval_decided_at_str:
                try:
                    _decided_dt = datetime.fromisoformat(_approval_decided_at_str)
                    _has_post_approval_tool = any(
                        ev.event_type == "tool_started"
                        and ev.created_at is not None
                        and ev.created_at > _decided_dt
                        for ev in events
                    )
                except (ValueError, TypeError):
                    pass
            if not _has_post_approval_tool:
                _resume_hint = ResumeHintResponse(
                    applying_after_approval=True,
                    approval_id=str(_lr.get("approval_id") or "").strip() or None,
                    decided_at=_approval_decided_at_str or None,
                )

        _plan_response = plan_to_response(current_plan) if current_plan and not _is_noop_plan(current_plan) else None
        _step_responses = checkpoint_step_responses or [step_to_response(step) for step in snapshot_step_rows]
        _pending_approval_response = approval_to_response(healed_pending_approval) if healed_pending_approval else None
        _approval_responses = [approval_to_response(row) for row in approval_rows]
        _presentation = _derive_snapshot_presentation(
            session=_session_response,
            plan=_plan_response,
            steps=_step_responses,
            pending_approval=_pending_approval_response,
            approvals=_approval_responses,
            timeline=events,
        )
        events = _attach_typed_presentations_to_events(events, snapshot_presentation=_presentation)

        # Build server-authoritative activity steps.
        _snapshot_for_activity = SessionSnapshotResponse(
            session=_session_response,
            plan=_plan_response,
            steps=_step_responses,
            pending_approval=_pending_approval_response,
            timeline=events,
            presentation=_presentation,
        )
        _activity_steps = _activity_steps_for_snapshot(_snapshot_for_activity)
        _cursor = int(getattr(sess, "event_seq", None) or 0)
        _response_document = compose_response_document(
            session=_session_response,
            plan=_plan_response,
            steps=_step_responses,
            pending_approval=_pending_approval_response,
            approvals=_approval_responses,
            timeline=events,
            activity_steps=_activity_steps,
            presentation=_presentation,
            cursor=_cursor,
        )

        return SessionSnapshotResponse(
            session=_session_response,
            plan=_plan_response,
            steps=_step_responses,
            pending_approval=_pending_approval_response,
            timeline=events,
            snapshot_revision=_response_document.revision,
            cursor=_cursor,
            phase=_effective_status,
            resume_hint=_resume_hint,
            activity_steps=_activity_steps,
            presentation=_presentation,
            response_document=_response_document,
        )

    @staticmethod
    def activity_steps_for_snapshot(snapshot: SessionSnapshotResponse) -> list[ActivityStepResponse]:
        return _activity_steps_for_snapshot(snapshot)

    @staticmethod
    def semantic_payload_for_timeline_event(ev: TimelineEventResponse, *, session_id: str) -> dict[str, Any]:
        return _semantic_payload_for_timeline_event(ev, session_id=session_id)

    @staticmethod
    def should_skip_semantic_timeline_event(ev: TimelineEventResponse) -> bool:
        return _should_skip_semantic_timeline_event(ev)
