from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from factory_agent.planning.v2_contracts import requirement_child_lineage


_ACTIVE_STATUSES = {"PLANNING", "EXECUTING", "WAITING_APPROVAL", "WAITING_CONFIRMATION", "WAITING_USER_ACTION"}
_READ_INTENT_OPERATIONS = {
    "report_status",
    "report_multi_status",
    "report_filtered_collection",
    "answer_document_question",
    "report_diagnostic",
}
_READ_REQUIREMENT_TYPES = {
    "single_entity_status",
    "multi_entity_status",
    "filtered_collection",
    "document_answer",
    "diagnostic",
}
_SAFE_ENTITY_LABELS: dict[str, tuple[str, str]] = {
    "approval": ("approval request", "approval requests"),
    "inventory": ("inventory record", "inventory records"),
    "job": ("job record", "job records"),
    "machine": ("machine record", "machine records"),
    "maintenance": ("maintenance record", "maintenance records"),
    "material": ("inventory record", "inventory records"),
    "process": ("process record", "process records"),
    "product": ("product record", "product records"),
    "production": ("production record", "production records"),
    "proposal": ("proposal record", "proposal records"),
    "quality": ("quality record", "quality records"),
    "report": ("report record", "report records"),
    "scheduling": ("scheduling record", "scheduling records"),
    "storage": ("storage record", "storage records"),
}
_STATIC_SAFE_LABELS = {
    "Activated dependent read",
    "Prerequisite read complete",
    "Replanning after failed read",
    "Replanning after timeout",
    "Replanning for more evidence",
    "Replanning with a different tool",
    "Skipped dependent read",
    "Waiting for parent evidence",
}
_REPLAN_LABEL_BY_REASON = {
    "timeout": "Replanning after timeout",
    "incomplete": "Replanning for more evidence",
    "different_tool": "Replanning with a different tool",
    "tool_error": "Replanning after failed read",
}
_RETRY_REASON_BY_KIND = {
    "timeout": "Previous read timed out",
    "incomplete": "Evidence was incomplete",
    "different_tool": "Trying a different tool",
    "tool_error": "Previous read failed",
}


@dataclass(frozen=True)
class ActivityCaption:
    group: str
    label: str
    detail: str | None
    state: str


def build_activity_caption_context_from_graph_state(state: Any) -> dict[str, Any]:
    """Extract the small structured slice needed to caption activity rows."""

    diagnostics = _mapping(getattr(getattr(state, "execution_trace", None), "diagnostics", {}))
    planner_decisions = list(getattr(state, "planner_decisions", []) or [])
    requirements = list(getattr(getattr(state, "requirement_ledger", None), "requirements", []) or [])
    evidence_items = list(getattr(getattr(state, "evidence_ledger", None), "evidence", []) or [])
    response_context = getattr(state, "response_document_context", None)
    response_diagnostics = _mapping(getattr(response_context, "diagnostics", {}))
    ledger = getattr(state, "requirement_ledger", None)
    branches = list(getattr(ledger, "conditional_branches", []) or [])
    pending_approval = getattr(state, "pending_approval", None)

    return {
        "requirements": [_requirement_row(item) for item in requirements],
        "evidence": [_evidence_row(item) for item in evidence_items],
        "planner_decisions": [_planner_decision_row(item) for item in planner_decisions],
        "pending_approval": {
            "status": getattr(pending_approval, "status", None),
            "approval_id": getattr(pending_approval, "approval_id", None),
        },
        "dependency_plan": _jsonish(diagnostics.get("dependency_plan")),
        "dependency_plan_history": _jsonish(diagnostics.get("dependency_plan_history")) or [],
        "conditional_branches": [_jsonish(branch) for branch in branches],
        "child_requirement_lineage": requirement_child_lineage(ledger) if ledger is not None else [],
        "replan_spine": _jsonish(diagnostics.get("replan_spine")) or {},
        "phase5_pending_tool_execution": _jsonish(diagnostics.get("phase5_pending_tool_execution")) or {},
        "phase8_approval_staging": _jsonish(diagnostics.get("phase8_approval_staging")) or {},
        "graph_tool_actions": _jsonish(diagnostics.get("graph_tool_actions")) or [],
        "active_evidence_refs": _string_list(response_diagnostics.get("active_evidence_refs")),
        "active_final_evidence_refs": _string_list(response_diagnostics.get("active_final_evidence_refs")),
        "response_evidence_refs": _string_list(getattr(response_context, "evidence_refs", []) or response_diagnostics.get("response_evidence_refs")),
    }


def enrich_activity_step_rows(
    rows: list[dict[str, Any]],
    session_context: Mapping[str, Any] | None,
    *,
    fallback_timestamp: int,
    session_status: str,
) -> list[dict[str, Any]]:
    """Add backend-authored captions from structured graph/session state."""

    context = _caption_context_from_session_context(session_context)
    if not context:
        return rows

    out = [dict(row) for row in rows if isinstance(row, dict)]
    status = str(session_status or "").upper()
    terminal = status not in _ACTIVE_STATUSES

    _add_simple_read_caption(out, context, fallback_timestamp=fallback_timestamp, terminal=terminal)
    _add_parallel_read_batch_caption(out, context, fallback_timestamp=fallback_timestamp, terminal=terminal)
    _add_replan_caption(out, context, fallback_timestamp=fallback_timestamp, terminal=terminal)
    _add_dependency_wait_captions(out, context, fallback_timestamp=fallback_timestamp, terminal=terminal)
    _add_child_lineage_captions(out, context, fallback_timestamp=fallback_timestamp, terminal=terminal)
    _add_conditional_branch_captions(out, context, fallback_timestamp=fallback_timestamp, terminal=terminal)
    _add_approval_prerequisite_caption(out, context, fallback_timestamp=fallback_timestamp, terminal=terminal)

    return sorted(out, key=_row_sort_key)


def caption_for_graph_event(event: Mapping[str, Any], fallback: ActivityCaption) -> ActivityCaption:
    """Return an enriched live caption for a graph node event when state proves one."""

    node = str(event.get("node") or "").strip()
    context = _caption_context_from_session_context(
        {
            "activity_caption_context": event.get("activity_caption_context"),
            "intent_contract": {"activity_caption_context": event.get("activity_caption_context")},
            "live_replan_spine": event.get("replan_spine"),
        }
    )
    if not context:
        return fallback

    replan = _mapping(event.get("replan_spine")) or _mapping(context.get("replan_spine"))
    if node in {"planner_decision_node", "tool_retrieval_node", "planner_choose_tool_node"}:
        replan_caption = _replan_caption(replan)
        if replan_caption is not None:
            return replan_caption

    if node == "planner_decision_node" and _dependency_wait_rows(context):
        return ActivityCaption(
            group="planning",
            label="Waiting for parent evidence",
            detail="Dependent read needs parent evidence first",
            state="running",
        )

    if node == "tool_execution_node":
        batch = _parallel_batch_row(context, timestamp=0, terminal=False)
        if batch is not None:
            return ActivityCaption(
                group="research",
                label=str(batch["label"]),
                detail=str(batch["detail"]),
                state="running",
            )
        read = _read_caption_row(context, timestamp=0, terminal=False)
        if read is not None:
            return ActivityCaption(
                group="research",
                label=str(read["label"]),
                detail=str(read["detail"]),
                state="running",
            )

    if node == "approval_node" and _approval_waited_for_read_evidence(context):
        return ActivityCaption(
            group="planning",
            label=fallback.label,
            detail="Read evidence is ready before approval",
            state=fallback.state,
        )

    return fallback


def is_safe_dynamic_activity_label(label: str) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    if text in _STATIC_SAFE_LABELS:
        return True
    lowered = text.lower()
    if lowered.startswith("reading "):
        subject = lowered.removeprefix("reading ").strip()
        if subject and subject[0].isdigit():
            subject = " ".join(subject.split()[1:])
        return subject in {plural for _singular, plural in _SAFE_ENTITY_LABELS.values()} or subject == "records"
    if lowered.startswith("retrying ") and lowered.endswith(" read"):
        subject = lowered.removeprefix("retrying ").removesuffix(" read").strip()
        return subject in {entity for entity in _SAFE_ENTITY_LABELS} or subject in {
            plural.removesuffix(" records")
            for _singular, plural in _SAFE_ENTITY_LABELS.values()
            if plural.endswith(" records")
        }
    return False


def _caption_context_from_session_context(session_context: Mapping[str, Any] | None) -> dict[str, Any]:
    context = _mapping(session_context)
    if not context:
        return {}
    direct = _mapping(context.get("activity_caption_context"))
    if direct:
        return dict(direct)

    candidates = [
        _mapping(context.get("intent_contract")),
        _mapping(context.get("planner_owned_agent_graph")),
    ]
    for candidate in candidates:
        nested = _mapping(candidate.get("activity_caption_context"))
        if nested:
            return dict(nested)

    merged: dict[str, Any] = {}
    for candidate in candidates:
        if not candidate:
            continue
        for key in (
            "dependency_plan",
            "dependency_plan_history",
            "conditional_branches",
            "child_requirement_lineage",
            "replan_spine",
        ):
            if key in candidate and key not in merged:
                merged[key] = candidate[key]
        trace = _mapping(candidate.get("execution_trace"))
        diagnostics = _mapping(trace.get("diagnostics"))
        for key in (
            "phase5_pending_tool_execution",
            "phase8_approval_staging",
            "graph_tool_actions",
            "dependency_plan",
            "dependency_plan_history",
            "conditional_branches",
            "replan_spine",
        ):
            if key in diagnostics and key not in merged:
                merged[key] = diagnostics[key]
        state = _mapping(candidate.get("planner_owned_agent_graph_state")) or _mapping(candidate.get("v2_state"))
        ledger = _mapping(state.get("requirement_ledger"))
        if ledger and "requirements" not in merged:
            merged["requirements"] = ledger.get("requirements") or []
            merged["conditional_branches"] = merged.get("conditional_branches") or ledger.get("conditional_branches") or []
        evidence_ledger = _mapping(state.get("evidence_ledger"))
        if evidence_ledger and "evidence" not in merged:
            merged["evidence"] = evidence_ledger.get("evidence") or []
        response_context = _mapping(candidate.get("response_document_context"))
        response_diagnostics = _mapping(response_context.get("diagnostics"))
        for key in ("active_evidence_refs", "active_final_evidence_refs", "response_evidence_refs"):
            if key in response_diagnostics and key not in merged:
                merged[key] = response_diagnostics[key]
        if "evidence_refs" in response_context and "response_evidence_refs" not in merged:
            merged["response_evidence_refs"] = response_context.get("evidence_refs") or []

    if context.get("live_replan_spine") and "replan_spine" not in merged:
        merged["replan_spine"] = context["live_replan_spine"]
    return merged


def _add_simple_read_caption(
    rows: list[dict[str, Any]],
    context: Mapping[str, Any],
    *,
    fallback_timestamp: int,
    terminal: bool,
) -> None:
    if any(str(row.get("label") or "").startswith("Reading ") for row in rows):
        return
    if _latest_parallel_ready_group(context) is not None:
        return
    row = _read_caption_row(context, timestamp=_timestamp_after_current_activity(rows, fallback_timestamp), terminal=terminal)
    if row is not None:
        row.update(_sort_after_latest_safe_action(rows))
        _append_unique(rows, row)


def _add_parallel_read_batch_caption(
    rows: list[dict[str, Any]],
    context: Mapping[str, Any],
    *,
    fallback_timestamp: int,
    terminal: bool,
) -> None:
    row = _parallel_batch_row(
        context,
        timestamp=_timestamp_after_current_activity(rows, fallback_timestamp),
        terminal=terminal,
    )
    if row is not None:
        row.update(_sort_after_latest_safe_action(rows))
        _append_unique(rows, row)


def _add_dependency_wait_captions(
    rows: list[dict[str, Any]],
    context: Mapping[str, Any],
    *,
    fallback_timestamp: int,
    terminal: bool,
) -> None:
    for idx, item in enumerate(_dependency_wait_rows(context)):
        req_id = str(item.get("requirement_id") or idx)
        _append_unique(
            rows,
            {
                "id": f"act:caption:dependency_wait:{req_id}",
                "timestamp": _timestamp_before_first_research(rows, fallback_timestamp) - 1,
                "group": "planning",
                "label": "Waiting for parent evidence",
                "detail": "Dependent read needs parent evidence first",
                "state": "success" if terminal else "waiting",
            },
        )


def _add_replan_caption(
    rows: list[dict[str, Any]],
    context: Mapping[str, Any],
    *,
    fallback_timestamp: int,
    terminal: bool,
) -> None:
    if any(str(row.get("label") or "").startswith("Replanning") for row in rows):
        return
    caption = _replan_caption(_mapping(context.get("replan_spine")))
    if caption is None:
        return
    _append_unique(
        rows,
        {
            "id": "act:caption:replan_attempt",
            "timestamp": _timestamp_before_first_research(rows, fallback_timestamp) + 1,
            "group": caption.group,
            "label": caption.label,
            "detail": caption.detail,
            "state": "success" if terminal else caption.state,
        },
    )


def _add_child_lineage_captions(
    rows: list[dict[str, Any]],
    context: Mapping[str, Any],
    *,
    fallback_timestamp: int,
    terminal: bool,
) -> None:
    requirements = _requirements_by_id(context)
    for idx, lineage in enumerate(_list(context.get("child_requirement_lineage"))):
        lineage = _mapping(lineage)
        child_ids = _string_list(lineage.get("child_requirement_ids"))
        if not child_ids:
            continue
        entity = _first_entity_for_requirements(requirements, child_ids)
        _append_unique(
            rows,
            {
                "id": f"act:caption:child_lineage:{str(lineage.get('parent_requirement_id') or idx)}",
                "timestamp": _timestamp_after_current_activity(rows, fallback_timestamp),
                **_sort_after_parent_evidence(rows),
                "group": "planning",
                "label": "Activated dependent read",
                "detail": f"Parent evidence supplied {_entity_id_label(entity)}",
                "state": "success" if terminal else "running",
            },
        )


def _add_conditional_branch_captions(
    rows: list[dict[str, Any]],
    context: Mapping[str, Any],
    *,
    fallback_timestamp: int,
    terminal: bool,
) -> None:
    branches = [_mapping(branch) for branch in _list(context.get("conditional_branches"))]
    requirements = _requirements_by_id(context)
    for idx, branch in enumerate(branches):
        branch_id = str(branch.get("id") or idx)
        status = str(branch.get("status") or "").strip().lower()
        if status == "activated":
            child_ids = _string_list(branch.get("activated_child_requirement_ids"))
            entity = _first_entity_for_requirements(requirements, child_ids)
            detail = f"Parent evidence supplied {_entity_id_label(entity)}"
            _append_unique(
                rows,
                {
                    "id": f"act:caption:conditional_activated:{branch_id}",
                    "timestamp": _timestamp_after_current_activity(rows, fallback_timestamp),
                    **_sort_after_parent_evidence(rows),
                    "group": "planning",
                    "label": "Activated dependent read",
                    "detail": detail,
                    "state": "success" if terminal else "running",
                },
            )
        elif status == "skipped":
            _append_unique(
                rows,
                {
                    "id": f"act:caption:conditional_skipped:{branch_id}",
                    "timestamp": _timestamp_after_current_activity(rows, fallback_timestamp),
                    **_sort_after_parent_evidence(rows),
                    "group": "planning",
                    "label": "Skipped dependent read",
                    "detail": _conditional_skip_detail(branch),
                    "state": "success",
                },
            )


def _add_approval_prerequisite_caption(
    rows: list[dict[str, Any]],
    context: Mapping[str, Any],
    *,
    fallback_timestamp: int,
    terminal: bool,
) -> None:
    if not _approval_waited_for_read_evidence(context):
        return
    approval_ts = _first_approval_timestamp(rows, fallback_timestamp + 2)
    _append_unique(
        rows,
        {
            "id": "act:caption:approval_prerequisite_read",
            "timestamp": approval_ts - 1,
            **_sort_before_first_approval(rows),
            "group": "research",
            "label": "Prerequisite read complete",
            "detail": "Approval waited for read evidence",
            "state": "success" if terminal else "running",
        },
    )
    for row in rows:
        label = str(row.get("label") or "")
        if label not in {"Waiting for approval", "Waiting for your approval", "Checking approvals"}:
            continue
        if row.get("detail") in (None, "", "Checking approval requirements", "Reviewing approval requirements"):
            row["detail"] = "Read evidence is ready; checking approval requirements"


def _read_caption_row(context: Mapping[str, Any], *, timestamp: int, terminal: bool) -> dict[str, Any] | None:
    evidence = _active_read_evidence(context)
    if not evidence:
        return None
    requirements = _requirements_by_id(context)
    entities = [
        _requirement_entity(requirements.get(str(item.get("requirement_id") or "")))
        for item in evidence
    ]
    label = f"Reading {_record_subject(entities, len(evidence), include_count=False)}"
    detail = f"Checking {_record_subject(entities, len(evidence), include_count=False)}"
    return {
        "id": "act:caption:simple_read",
        "timestamp": timestamp,
        "group": "research",
        "label": label,
        "detail": detail,
        "state": "success" if terminal else "running",
    }


def _parallel_batch_row(context: Mapping[str, Any], *, timestamp: int, terminal: bool) -> dict[str, Any] | None:
    group = _latest_parallel_ready_group(context)
    if group is None:
        return None
    requirement_ids = _string_list(group.get("requirement_ids"))
    count = _parallel_batch_count(group)
    if count <= 1:
        return None
    requirements = _requirements_by_id(context)
    entities = [_requirement_entity(requirements.get(req_id)) for req_id in requirement_ids]
    label = f"Reading {_record_subject(entities, count, include_count=True)}"
    return {
        "id": f"act:caption:parallel_read_batch:{str(group.get('group_id') or 'group')}",
        "timestamp": timestamp,
        "group": "research",
        "label": label,
        "detail": "Parallel read batch scheduled",
        "state": "success" if terminal else "running",
    }


def _dependency_wait_rows(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in _dependency_history_entries(context):
        labels = _mapping(entry.get("labels"))
        for req_id, label in labels.items():
            if label == "depends_on_evidence":
                out.append({"requirement_id": str(req_id)})
    plan = _mapping(context.get("dependency_plan"))
    for item in _list(plan.get("requirements")):
        item = _mapping(item)
        if item.get("label") == "depends_on_evidence":
            out.append({"requirement_id": str(item.get("requirement_id") or "")})
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in out:
        req_id = str(item.get("requirement_id") or "")
        if not req_id or req_id in seen:
            continue
        seen.add(req_id)
        deduped.append(item)
    return deduped


def _active_read_evidence(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence = [_mapping(item) for item in _list(context.get("evidence"))]
    if not evidence:
        return []
    active_refs = (
        _string_list(context.get("active_final_evidence_refs"))
        or _string_list(context.get("response_evidence_refs"))
        or _string_list(context.get("active_evidence_refs"))
    )
    if active_refs:
        evidence = [item for item in evidence if str(item.get("id") or "") in set(active_refs)]
    else:
        evidence = [
            item
            for item in evidence
            if _mapping(item.get("diagnostic_metadata")).get("active_revision_satisfaction") is not False
        ]
    requirements = _requirements_by_id(context)
    return [
        item
        for item in evidence
        if str(item.get("source_type") or "") in {"api_tool", "rag_tool"}
        and _requirement_is_read(requirements.get(str(item.get("requirement_id") or "")))
    ]


def _latest_parallel_ready_group(context: Mapping[str, Any]) -> dict[str, Any] | None:
    entries = _dependency_history_entries(context)
    for entry in reversed(entries):
        for group in _list(entry.get("ready_groups")):
            group = _mapping(group)
            if group.get("mode") == "parallel_read_batch" and _parallel_batch_count(group) > 1:
                return dict(group)
    plan = _mapping(context.get("dependency_plan"))
    for group in _list(plan.get("ready_groups")):
        group = _mapping(group)
        if group.get("mode") == "parallel_read_batch" and _parallel_batch_count(group) > 1:
            return dict(group)
    return None


def _parallel_batch_count(group: Mapping[str, Any]) -> int:
    requirement_count = len(_string_list(group.get("requirement_ids")))
    diagnostics = _mapping(group.get("diagnostic_metadata"))
    estimated_count = (
        _int(group.get("estimated_tool_call_count"))
        or _int(diagnostics.get("estimated_tool_call_count"))
        or 0
    )
    return max(requirement_count, estimated_count)


def _dependency_history_entries(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [_mapping(item) for item in _list(context.get("dependency_plan_history"))]


def _approval_waited_for_read_evidence(context: Mapping[str, Any]) -> bool:
    pending = _mapping(context.get("phase5_pending_tool_execution"))
    deferred = _list(pending.get("deferred_approval_decisions"))
    if any(_mapping(item).get("reason") == "prior_read_execution_requires_evidence_observation" for item in deferred):
        return True
    staging = _mapping(context.get("phase8_approval_staging"))
    if staging.get("status") == "paused_at_approval_node":
        if _active_read_evidence(context):
            return True
        plan = _mapping(context.get("dependency_plan"))
        for item in _list(plan.get("requirements")):
            item = _mapping(item)
            if item.get("label") == "approval_required" and _string_list(item.get("depends_on_requirement_ids")):
                return True
    return False


def _replan_caption(replan: Mapping[str, Any]) -> ActivityCaption | None:
    attempt_count = _int(replan.get("attempt_count")) or _int(replan.get("current_attempt")) or 0
    if attempt_count <= 0:
        return None
    total = (_int(replan.get("max_attempts")) or attempt_count) + 1
    kind = _replan_reason_kind(replan)
    next_attempt = min(total, attempt_count + 1)
    reason = _RETRY_REASON_BY_KIND.get(kind, _RETRY_REASON_BY_KIND["tool_error"])
    return ActivityCaption(
        group="planning",
        label=_REPLAN_LABEL_BY_REASON.get(kind, _REPLAN_LABEL_BY_REASON["tool_error"]),
        detail=f"Attempt {next_attempt} of {total} - {reason}",
        state="retry",
    )


def _replan_reason_kind(replan: Mapping[str, Any]) -> str:
    failed_calls = _list(replan.get("failed_tool_calls"))
    for call in failed_calls:
        call = _mapping(call)
        error_type = str(call.get("error_type") or "").strip().lower()
        if error_type == "timeout":
            return "timeout"
    attempts = _list(replan.get("attempts"))
    for attempt in reversed(attempts):
        for reason in _list(_mapping(attempt).get("missing_evidence_reasons")):
            kind = _missing_reason_kind(_mapping(reason))
            if kind:
                return kind
    for reason in reversed(_list(replan.get("missing_evidence_reasons"))):
        kind = _missing_reason_kind(_mapping(reason))
        if kind:
            return kind
    return "tool_error"


def _missing_reason_kind(reason: Mapping[str, Any]) -> str | None:
    code = str(reason.get("reason") or "").strip().lower()
    if code in {"insufficient_context", "missing_evidence", "no_match", "empty_data"}:
        return "incomplete"
    if code == "timeout":
        return "timeout"
    if code == "different_tool":
        return "different_tool"
    if code == "tool_error":
        return "tool_error"
    return None


def _requirements_by_id(context: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id") or ""): item
        for item in (_mapping(row) for row in _list(context.get("requirements")))
        if str(item.get("id") or "")
    }


def _requirement_row(requirement: Any) -> dict[str, Any]:
    data = _mapping(_jsonish(requirement))
    if data:
        return data
    return {
        "id": str(getattr(requirement, "id", "") or ""),
        "entity": getattr(requirement, "entity", None),
        "status": getattr(requirement, "status", None),
        "requirement_type": getattr(requirement, "requirement_type", None),
        "intent_operation": getattr(requirement, "intent_operation", None),
        "source_of_truth": getattr(requirement, "source_of_truth", None),
        "constraints": dict(getattr(requirement, "constraints", {}) or {}),
        "depends_on": list(getattr(requirement, "depends_on", []) or []),
        "parent_requirement_id": getattr(requirement, "parent_requirement_id", None),
        "derived_from_evidence_refs": list(getattr(requirement, "derived_from_evidence_refs", []) or []),
        "evidence_refs": list(getattr(requirement, "evidence_refs", []) or []),
    }


def _evidence_row(evidence: Any) -> dict[str, Any]:
    data = _mapping(_jsonish(evidence))
    if data:
        return data
    return {
        "id": str(getattr(evidence, "id", "") or ""),
        "requirement_id": str(getattr(evidence, "requirement_id", "") or ""),
        "source_type": getattr(evidence, "source_type", None),
        "source_of_truth": getattr(evidence, "source_of_truth", None),
        "args": dict(getattr(evidence, "args", {}) or {}),
        "diagnostic_metadata": dict(getattr(evidence, "diagnostic_metadata", {}) or {}),
        "normalized_result": dict(getattr(evidence, "normalized_result", {}) or {}),
    }


def _planner_decision_row(decision: Any) -> dict[str, Any]:
    calls = list(getattr(decision, "selected_tool_calls", []) or [])
    selected = getattr(decision, "selected_tool_call", None)
    if selected is not None:
        calls.append(selected)
    return {
        "decision_id": str(getattr(decision, "decision_id", "") or ""),
        "decision_kind": str(getattr(decision, "decision_kind", "") or ""),
        "requirement_id": str(getattr(decision, "requirement_id", "") or ""),
        "selected_tool_calls": [
            {
                "call_id": str(getattr(call, "call_id", "") or ""),
                "requirement_id": str(getattr(call, "requirement_id", "") or ""),
                "kind": str(getattr(call, "kind", "") or ""),
            }
            for call in calls
        ],
        "diagnostics": _jsonish(getattr(decision, "diagnostics", {})) or {},
    }


def _requirement_is_read(requirement: Mapping[str, Any] | None) -> bool:
    if not requirement:
        return True
    if requirement.get("source_of_truth") == "document_knowledge":
        return False
    return (
        str(requirement.get("intent_operation") or "") in _READ_INTENT_OPERATIONS
        or str(requirement.get("requirement_type") or "") in _READ_REQUIREMENT_TYPES
    )


def _requirement_entity(requirement: Mapping[str, Any] | None) -> str:
    if not requirement:
        return ""
    entity = str(requirement.get("entity") or "").strip().lower()
    return entity if entity in _SAFE_ENTITY_LABELS else ""


def _first_entity_for_requirements(requirements: Mapping[str, dict[str, Any]], ids: list[str]) -> str:
    for req_id in ids:
        entity = _requirement_entity(requirements.get(req_id))
        if entity:
            return entity
    return ""


def _record_subject(entities: list[str], count: int, *, include_count: bool) -> str:
    safe = [entity for entity in entities if entity in _SAFE_ENTITY_LABELS]
    entity = safe[0] if safe and all(item == safe[0] for item in safe) else ""
    if not entity:
        return f"{count} records" if include_count and count > 1 else "records"
    singular, plural = _SAFE_ENTITY_LABELS[entity]
    subject = singular if count == 1 else plural
    return f"{count} {subject}" if include_count and count > 1 else plural


def _entity_id_label(entity: str) -> str:
    if entity in _SAFE_ENTITY_LABELS:
        return f"{entity} id"
    return "record id"


def _conditional_skip_detail(branch: Mapping[str, Any]) -> str:
    condition = _mapping(branch.get("condition"))
    field_any = [str(field).strip() for field in _list(condition.get("field_any")) if str(field).strip()]
    if field_any:
        return f"No {_field_label(field_any[0])} found"
    reason = str(branch.get("skipped_reason") or "").strip()
    if reason:
        return "Conditional branch was not triggered"
    return "Dependent read was not needed"


def _field_label(field_name: str) -> str:
    cleaned = field_name.strip().lower().replace("_", " ")
    return " ".join(part for part in cleaned.split() if part)


def _append_unique(rows: list[dict[str, Any]], row: dict[str, Any]) -> None:
    row_id = str(row.get("id") or "")
    if row_id and any(str(existing.get("id") or "") == row_id for existing in rows):
        return
    signature = (
        str(row.get("group") or ""),
        str(row.get("label") or ""),
        str(row.get("detail") or ""),
    )
    for existing in rows:
        if (
            str(existing.get("group") or ""),
            str(existing.get("label") or ""),
            str(existing.get("detail") or ""),
        ) == signature:
            return
    rows.append(row)


def _timestamp_before_first_research(rows: list[dict[str, Any]], fallback_timestamp: int) -> int:
    candidates = [
        _int(row.get("timestamp"))
        for row in rows
        if row.get("group") in {"research", "response", "approval"} and _int(row.get("timestamp")) is not None
    ]
    if candidates:
        return min(candidates) - 1
    return int(fallback_timestamp)


def _timestamp_after_current_activity(rows: list[dict[str, Any]], fallback_timestamp: int) -> int:
    timestamps: list[int] = []
    terminal_timestamps: list[int] = []
    for row in rows:
        timestamp = _int(row.get("timestamp"))
        if timestamp is None:
            continue
        timestamps.append(timestamp)
        if row.get("state") in {"complete", "error"}:
            terminal_timestamps.append(timestamp)
    if not timestamps:
        return int(fallback_timestamp)
    if terminal_timestamps:
        return min(terminal_timestamps) - 1
    return max(timestamps) + 1


def _sort_after_parent_evidence(rows: list[dict[str, Any]]) -> dict[str, float]:
    evidence_order = _first_order_for_labels(rows, {"Verifying result"})
    if evidence_order is None:
        evidence_order = _first_order_for_labels(rows, {"Checking result", "Checking evidence", "Checking new evidence"})
    if evidence_order is None:
        return {}
    return {"_sort_after_order": evidence_order + 0.5}


def _sort_before_first_approval(rows: list[dict[str, Any]]) -> dict[str, float]:
    approval_order = _first_order_for_labels(
        rows,
        {"Checking approvals", "Waiting for approval", "Waiting for your approval"},
    )
    if approval_order is None:
        return _sort_after_parent_evidence(rows)
    return {"_sort_after_order": approval_order - 0.5}


def _sort_after_latest_safe_action(rows: list[dict[str, Any]]) -> dict[str, float]:
    order = _last_order_for_labels(rows, {"Selecting safe action"})
    if order is None:
        return {}
    return {"_sort_after_order": order + 0.5}


def _first_order_for_labels(rows: list[dict[str, Any]], labels: set[str]) -> float | None:
    candidates: list[float] = []
    for row in rows:
        if str(row.get("label") or "") not in labels:
            continue
        order = _number(row.get("order") or row.get("_order"))
        if order is not None:
            candidates.append(order)
    if not candidates:
        return None
    return min(candidates)


def _last_order_for_labels(rows: list[dict[str, Any]], labels: set[str]) -> float | None:
    candidates: list[float] = []
    for row in rows:
        if str(row.get("label") or "") not in labels:
            continue
        order = _number(row.get("order") or row.get("_order"))
        if order is not None:
            candidates.append(order)
    if not candidates:
        return None
    return max(candidates)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_approval_timestamp(rows: list[dict[str, Any]], fallback_timestamp: int) -> int:
    candidates = [
        _int(row.get("timestamp"))
        for row in rows
        if row.get("group") == "approval" and _int(row.get("timestamp")) is not None
    ]
    if candidates:
        return min(candidates)
    return int(fallback_timestamp)


def _row_sort_key(row: Mapping[str, Any]) -> tuple[int, int, str]:
    return (
        _int(row.get("timestamp")) or 0,
        _int(row.get("order") or row.get("_order")) or 0,
        str(row.get("id") or ""),
    )


def _jsonish(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonish(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonish(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonish(item) for item in value]
    return value


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
