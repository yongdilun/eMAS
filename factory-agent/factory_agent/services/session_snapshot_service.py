from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.analysis.presentation import extract_table_from_result
from factory_agent.analysis.result_normalizer import normalize_tool_result
from factory_agent.api.response_mappers import approval_to_response, plan_to_response, session_to_response, step_to_response
from factory_agent.graph.session_detection import is_graph_native_session, is_langgraph_plan
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.planning.tool_output_alignment import summarize_tool_result
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import (
    ActivityStepResponse,
    PlanStepResponse,
    ResumeHintResponse,
    SessionSnapshotResponse,
    TimelineEventResponse,
    ToolInfo,
)
from factory_agent.session_state import (
    USER_CANCELLED_ACTIVITY_DETAIL,
    USER_CANCELLED_ACTIVITY_LABEL,
    USER_CANCELLED_REASON,
    USER_CANCELLED_TIMELINE_CONTENT,
    is_user_cancelled_session,
    timeline_details_indicate_user_cancelled,
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
        return f"Checking {domain}"
    if ev.event_type == "tool_result":
        if label == "Could not complete that check":
            return "A check could not be completed"
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
        return {"group": "planning", "label": "Understanding your request", "state": "success"}
    if event_type == "execution_started":
        return {"group": "planning", "label": "Preparing the next step", "state": "running"}
    if event_type == "tool_started":
        return {"group": "research", "label": "Gathering information", "state": "running"}
    if event_type == "tool_result":
        if status in {"FAILED", "AMBIGUOUS"}:
            return {"group": "research", "label": "Could not complete that check", "state": "error"}
        return {"group": "research", "label": "Information checked", "state": "success"}
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
    return any(r.get("label") in toolish for r in rows)


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
    suppress_completion = has_pending_approval or session_status in {
        "PLANNING",
        "EXECUTING",
        "WAITING_APPROVAL",
        "WAITING_CONFIRMATION",
    }
    for ev in snapshot.timeline:
        base = _activity_base_for_timeline_event(ev)
        if base is None:
            continue
        # Suppress "Run complete" while the session is still active. A stale
        # completion row between approval gates can hide the next pending write set.
        if suppress_completion and ev.event_type == "session_completed":
            continue
        detail = _activity_detail_for_event(ev, label=base["label"])
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
        raw_steps.append(
            {
                "id": _activity_step_stable_id(ev, signature),
                "timestamp": int(ev.created_at.timestamp()),
                "group": base["group"],
                "label": base["label"],
                "detail": detail,
                "state": base["state"],
            }
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
    }


def _should_skip_semantic_timeline_event(ev: TimelineEventResponse) -> bool:
    """Non-pending approval_required rows stay on the timeline for audit; SSE clients ignore them."""
    if ev.event_type != "approval_required":
        return False
    st = str(ev.status or "").upper()
    return st not in {"", "PENDING"}


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
        allow_step_projection = (not graph_native_session) or is_langgraph_plan(current_plan)

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
                or _is_success_like_plan_text(useful_completion_message.content)
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
        if healed_pending_approval is not None:
            _effective_status = "WAITING_APPROVAL"
        elif healed_pending_approval is None and sess.status == "WAITING_APPROVAL":
            _effective_status = sess.status
        else:
            _effective_status = sess.status
        _session_response = session_to_response(sess)
        if _effective_status != sess.status:
            _session_response = _session_response.model_copy(
                update={
                    "status": _effective_status,
                    "completed_at": None if _effective_status != "COMPLETED" else _session_response.completed_at,
                }
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

        # Build server-authoritative activity steps.
        _snapshot_for_activity = SessionSnapshotResponse(
            session=_session_response,
            plan=plan_to_response(current_plan) if current_plan and not _is_noop_plan(current_plan) else None,
            steps=(checkpoint_step_responses or [step_to_response(step) for step in snapshot_step_rows]),
            pending_approval=approval_to_response(healed_pending_approval) if healed_pending_approval else None,
            timeline=events,
        )
        _activity_steps = _activity_steps_for_snapshot(_snapshot_for_activity)

        return SessionSnapshotResponse(
            session=_session_response,
            plan=plan_to_response(current_plan) if current_plan and not _is_noop_plan(current_plan) else None,
            steps=(checkpoint_step_responses or [step_to_response(step) for step in snapshot_step_rows]),
            pending_approval=approval_to_response(healed_pending_approval) if healed_pending_approval else None,
            timeline=events,
            cursor=int(getattr(sess, "event_seq", None) or 0),
            phase=_effective_status,
            resume_hint=_resume_hint,
            activity_steps=_activity_steps,
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
