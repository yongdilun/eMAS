from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..planning.api_result_projection import api_row_id, project_api_body
from ..planning.v2_agent_state import GraphToolCall, PendingApprovalState, PlannerOwnedAgentGraphState
from ..planning.v2_contracts import HydratedToolCard
from ..planning.v2_graph_adapters import GraphToolHttpExecutor
from ..schemas import ToolInfo


@dataclass(frozen=True)
class PlannerOwnedGraphApprovalPreview:
    rows: list[dict[str, Any]]
    details: dict[str, Any] = field(default_factory=dict)
    excluded_rows: list[dict[str, Any]] = field(default_factory=list)
    commit_args: dict[str, Any] = field(default_factory=dict)
    no_records_message: str = "No matching records were found."


def _normalize_approval_preview(value: Any) -> PlannerOwnedGraphApprovalPreview:
    if isinstance(value, PlannerOwnedGraphApprovalPreview):
        return value
    if not isinstance(value, Mapping):
        return PlannerOwnedGraphApprovalPreview(rows=[])
    rows = value.get("rows") or value.get("preview_rows") or value.get("records") or []
    excluded = value.get("excluded_rows") or value.get("blocked_rows") or []
    details = value.get("details") or value.get("preview_details") or {}
    commit_args = value.get("commit_args") or {}
    return PlannerOwnedGraphApprovalPreview(
        rows=[dict(row) for row in rows if isinstance(row, Mapping)],
        excluded_rows=[dict(row) for row in excluded if isinstance(row, Mapping)],
        details=dict(details) if isinstance(details, Mapping) else {"value": details},
        commit_args=dict(commit_args) if isinstance(commit_args, Mapping) else {},
        no_records_message=str(value.get("no_records_message") or "No matching records were found."),
    )


async def _graph_write_approval_preview(
    *,
    settings: Settings,
    state: PlannerOwnedAgentGraphState,
    tool_call: GraphToolCall,
    requirement: Any,
    card: HydratedToolCard,
    cards: list[HydratedToolCard],
    tools_by_name: Mapping[str, ToolInfo],
    http_executor: GraphToolHttpExecutor | None,
    supports_collection_read: Callable[[HydratedToolCard], bool],
) -> PlannerOwnedGraphApprovalPreview:
    read_card = _approval_preview_read_card(
        requirement,
        cards,
        supports_collection_read=supports_collection_read,
    )
    read_tool = tools_by_name.get(read_card.tool_name) if read_card is not None else None
    if read_card is None or read_tool is None:
        return _default_approval_preview(tool_call=tool_call, requirement=requirement, card=card)

    read_args = _approval_preview_read_args(read_card, requirement)
    env = await _execute_approval_preview_read(
        settings=settings,
        tool=read_tool,
        args=read_args,
        state=state,
        requirement_id=tool_call.requirement_id,
        http_executor=http_executor,
    )
    body = _mapping_or_empty(env.get("body"))
    entity = str(getattr(requirement, "entity", "") or "").strip().lower()
    projected = project_api_body(body, requirement=requirement, entity=entity)
    source_rows = _rows_from_projected_body(projected)
    rows, excluded_rows = _approval_preview_rows_from_read(
        rows=source_rows,
        state=state,
        requirement=requirement,
    )
    details = {
        "source": "graph_read_preview",
        "read_tool_name": read_card.tool_name,
        "read_args": read_args,
        "http_status": env.get("http_status"),
        "ok": bool(env.get("ok")),
        "source_row_count": len(source_rows),
        "preview_row_count": len(rows),
        "excluded_row_count": len(excluded_rows),
        "graph_execution_authority": True,
    }
    if not bool(env.get("ok")):
        details["reason"] = "approval_preview_read_failed"
        return PlannerOwnedGraphApprovalPreview(
            rows=[],
            excluded_rows=excluded_rows,
            details=details,
            no_records_message="The graph could not build a safe approval preview from current records.",
        )
    return PlannerOwnedGraphApprovalPreview(
        rows=rows,
        excluded_rows=excluded_rows,
        details=details,
        no_records_message=_no_records_preview_message(requirement),
    )


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _approval_preview_read_card(
    requirement: Any,
    cards: list[HydratedToolCard],
    *,
    supports_collection_read: Callable[[HydratedToolCard], bool],
) -> HydratedToolCard | None:
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    constrained_fields = {str(key) for key, value in constraints.items() if value not in (None, "", [], {})}
    for candidate in cards:
        if candidate.source_of_truth != "operational_state":
            continue
        if not candidate.is_read_only or candidate.requires_approval:
            continue
        if not supports_collection_read(candidate):
            continue
        filter_names = set(candidate.query_params) | set(candidate.metadata.get("filter_fields") or [])
        if constrained_fields and filter_names.intersection(constrained_fields):
            return candidate
    for candidate in cards:
        if (
            candidate.source_of_truth == "operational_state"
            and candidate.is_read_only
            and not candidate.requires_approval
            and supports_collection_read(candidate)
        ):
            return candidate
    return None


def _approval_preview_read_args(card: HydratedToolCard, requirement: Any) -> dict[str, Any]:
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    filter_names = set(card.query_params) | set(card.metadata.get("filter_fields") or [])
    args: dict[str, Any] = {}
    for key, value in constraints.items():
        if key.startswith("new_") or key in {"requires_approval"}:
            continue
        if value in (None, "", [], {}):
            continue
        if key in filter_names or card.supports_filters:
            args[key] = value
    if "fields" in set(card.query_params):
        entity = str(getattr(requirement, "entity", "") or "").strip().lower()
        fields = list(dict.fromkeys([f"{entity}_id" if entity else "id", "priority", "status"]))
        args.setdefault("fields", ",".join(field for field in fields if field))
    return args


async def _execute_approval_preview_read(
    *,
    settings: Settings,
    tool: ToolInfo,
    args: dict[str, Any],
    state: PlannerOwnedAgentGraphState,
    requirement_id: str,
    http_executor: GraphToolHttpExecutor | None,
) -> dict[str, Any]:
    idempotency_key = (
        f"graph-preview-{state.requirement_ledger.revision}-"
        f"{requirement_id}-{tool.name}"
    )
    if http_executor is not None:
        return await http_executor(
            settings,
            tool,
            dict(args),
            idempotency_key=idempotency_key,
        )
    from .http_tool_client import execute_tool_http

    return await execute_tool_http(settings, tool, dict(args), idempotency_key=idempotency_key)


def _rows_from_projected_body(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [dict(row) for row in body if isinstance(row, Mapping)]
    if not isinstance(body, Mapping):
        return []
    data = body.get("data")
    if isinstance(data, list):
        return [dict(row) for row in data if isinstance(row, Mapping)]
    if isinstance(data, Mapping):
        return [dict(data)]
    rows = body.get("rows") or body.get("records") or body.get("items")
    if isinstance(rows, list):
        return [dict(row) for row in rows if isinstance(row, Mapping)]
    if any(key not in {"success", "ok", "message", "count", "total", "meta"} for key in body):
        return [dict(body)]
    return []


def _approval_preview_rows_from_read(
    *,
    rows: list[dict[str, Any]],
    state: PlannerOwnedAgentGraphState,
    requirement: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    entity = str(getattr(requirement, "entity", "") or "").strip().lower()
    source_priority = _source_priority_constraint(constraints)
    target_priority = _target_priority_constraint(constraints)
    prior_write_excluded_ids = _prior_write_ids_moved_into_source_priority(
        state=state,
        requirement=requirement,
        source_priority=source_priority,
    )
    preview_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    for row in rows:
        normalized = dict(row)
        row_id = api_row_id(normalized, entity=entity)
        if row_id not in (None, "") and str(row_id) in prior_write_excluded_ids:
            excluded = dict(normalized)
            excluded["exclusion_reason"] = "changed_by_prior_requirement"
            excluded_rows.append(excluded)
            continue
        row_priority = str(normalized.get("priority") or "").strip().lower()
        if source_priority and row_priority and row_priority != source_priority:
            excluded = dict(normalized)
            excluded["exclusion_reason"] = "priority_constraint"
            excluded_rows.append(excluded)
            continue
        if row_id not in (None, ""):
            if entity:
                normalized.setdefault(f"{entity}_id", row_id)
            normalized.setdefault("id", row_id)
            if entity == "job":
                normalized.setdefault("job_id", row_id)
        if source_priority:
            normalized.setdefault("previous_priority", normalized.get("priority") or source_priority)
            normalized.setdefault("original_priority", normalized.get("previous_priority") or source_priority)
        if target_priority:
            normalized["new_priority"] = target_priority
        preview_rows.append(normalized)
    return preview_rows, excluded_rows


def _prior_write_ids_moved_into_source_priority(
    *,
    state: PlannerOwnedAgentGraphState,
    requirement: Any,
    source_priority: str | None,
) -> set[str]:
    if not source_priority:
        return set()
    current_requirement_id = str(getattr(requirement, "id", "") or "")
    entity = str(getattr(requirement, "entity", "") or "").strip().lower()
    excluded: set[str] = set()
    for evidence in state.evidence_ledger.evidence:
        if evidence.source_type != "approval" or evidence.requirement_id == current_requirement_id:
            continue
        metadata = evidence.diagnostic_metadata if isinstance(evidence.diagnostic_metadata, Mapping) else {}
        if metadata.get("approval_status") != "approved":
            continue
        locked = metadata.get("locked_constraints") if isinstance(metadata.get("locked_constraints"), Mapping) else {}
        previous_source = _source_priority_constraint(locked)
        previous_target = _target_priority_constraint(locked)
        rows = [row for row in (metadata.get("preview_rows") or []) if isinstance(row, Mapping)]
        if previous_source is None or previous_target is None:
            row_source, row_target = _priority_pair_from_preview_rows(rows)
            previous_source = previous_source or row_source
            previous_target = previous_target or row_target
        if previous_target != source_priority or previous_source == source_priority:
            continue
        for row in rows:
            row_id = api_row_id(dict(row), entity=entity)
            if row_id not in (None, ""):
                excluded.add(str(row_id))
    return excluded


def _priority_pair_from_preview_rows(rows: list[Mapping[str, Any]]) -> tuple[str | None, str | None]:
    sources = {
        str(row.get("previous_priority") or row.get("original_priority") or row.get("priority") or "").strip().lower()
        for row in rows
        if str(row.get("previous_priority") or row.get("original_priority") or row.get("priority") or "").strip()
    }
    targets = {
        str(row.get("new_priority") or "").strip().lower()
        for row in rows
        if str(row.get("new_priority") or "").strip()
    }
    source = next(iter(sources)) if len(sources) == 1 else None
    target = next(iter(targets)) if len(targets) == 1 else None
    return source, target


def _staged_write_tool_calls_from_preview(
    *,
    state: PlannerOwnedAgentGraphState,
    base_call: GraphToolCall,
    card: HydratedToolCard,
    requirement: Any,
    preview: PlannerOwnedGraphApprovalPreview,
) -> list[GraphToolCall]:
    _ = state
    if not preview.rows:
        return []
    calls: list[GraphToolCall] = []
    for index, row in enumerate(preview.rows, start=1):
        args = _commit_args_from_preview(card=card, requirement=requirement, rows=[row])
        common_args = {
            key: value
            for key, value in preview.commit_args.items()
            if key not in set(card.path_params) and value not in (None, "", [], {})
        }
        args = {**common_args, **args}
        if not args:
            continue
        calls.append(
            GraphToolCall(
                call_id=f"{base_call.call_id}-stage-{index:03d}",
                kind=base_call.kind,
                tool_name=base_call.tool_name,
                args=args,
                requirement_id=base_call.requirement_id,
                candidate_window_id=base_call.candidate_window_id,
            )
        )
    if calls:
        return calls
    return [base_call]


def _pending_staged_tool_calls(
    pending: PendingApprovalState,
    *,
    fallback: GraphToolCall,
) -> list[GraphToolCall]:
    payload = pending.payload if isinstance(pending.payload, Mapping) else {}
    raw_calls = payload.get("staged_graph_tool_calls")
    if not isinstance(raw_calls, list):
        return [fallback]
    calls: list[GraphToolCall] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, Mapping):
            continue
        try:
            calls.append(GraphToolCall.model_validate(dict(raw_call)))
        except Exception:
            continue
    return calls or [fallback]


def _source_priority_constraint(constraints: Mapping[str, Any]) -> str | None:
    raw = constraints.get("priority") or constraints.get("priority_from") or constraints.get("source_priority")
    if raw in (None, "", [], {}):
        return None
    return str(raw).strip().lower()


def _target_priority_constraint(constraints: Mapping[str, Any]) -> str | None:
    raw = constraints.get("new_priority") or constraints.get("priority_to") or constraints.get("target_priority")
    if raw in (None, "", [], {}):
        return None
    return str(raw).strip().lower()


def _no_records_preview_message(requirement: Any) -> str:
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    entity = str(getattr(requirement, "entity", "") or "records").strip().lower()
    source_priority = _source_priority_constraint(constraints)
    if source_priority:
        return f"No matching {entity} records were found for priority = {source_priority}."
    return "No matching records were found."


def _default_approval_preview(
    *,
    tool_call: GraphToolCall,
    requirement: Any,
    card: HydratedToolCard,
) -> PlannerOwnedGraphApprovalPreview:
    args = _commit_args_from_preview(card=card, requirement=requirement, rows=[])
    args.update(tool_call.args)
    rows = [dict(args)] if args else []
    return PlannerOwnedGraphApprovalPreview(
        rows=rows,
        details={
            "source": "default_graph_write_preview",
            "tool_name": tool_call.tool_name,
        },
        commit_args=args,
    )


def _commit_args_from_preview(
    *,
    card: HydratedToolCard,
    requirement: Any,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    input_properties = card.input_schema.get("properties", {}) if isinstance(card.input_schema, Mapping) else {}
    first_row = rows[0] if rows else {}
    entity = str(getattr(requirement, "entity", "") or "").strip()

    for path_param in card.path_params:
        value = constraints.get(path_param)
        if value in (None, "", [], {}) and path_param == "id" and entity:
            value = constraints.get(f"{entity}_id")
        if value in (None, "", [], {}) and first_row:
            value = first_row.get(path_param) or first_row.get(f"{entity}_id") or first_row.get("id")
        if value not in (None, "", [], {}):
            args[path_param] = value

    for key, value in constraints.items():
        if key.startswith("new_"):
            target = key.removeprefix("new_")
            if target in input_properties and value not in (None, "", [], {}):
                args[target] = value
            continue
        if key in input_properties and key not in {"requires_approval"} and value not in (None, "", [], {}):
            args.setdefault(key, value)

    return args


def _pending_approval_response_block(state: PlannerOwnedAgentGraphState) -> dict[str, Any] | None:
    pending = state.pending_approval
    if pending.status != "pending":
        return None
    payload = dict(pending.payload)
    return {
        "type": "approval_required",
        "approval_id": pending.approval_id,
        "approval_label": payload.get("approval_label"),
        "requirement_id": pending.requirement_id,
        "summary": str(payload.get("summary") or "Approval required before committing staged changes."),
        "rows": list(payload.get("preview_rows") or payload.get("preview") or []),
        "details": dict(payload.get("preview_details") or {}),
        "ledger_revision": pending.ledger_revision,
        "checkpoint_id": pending.checkpoint_id,
        "selected_graph_tool_call": payload.get("selected_graph_tool_call"),
        "source_type": "approval",
    }
