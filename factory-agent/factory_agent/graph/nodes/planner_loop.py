"""Phase 3 planner loop: Planner → DecisionGuard → Tool execution → Planner."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from ...config import Settings
from ...llm.models import build_planner_chat_model
from ...observability.telemetry import log_event, log_llm_prompt
from ...schemas import ControlAction, PlannerDecision, ToolCall, ToolInfo
from ...security.guardrails import promote_user_provenance, sanitize_tool_args_against_schema, strip_unsupported_optional_args
from ..errors import LangGraphPlannerError
from ..planner_graph_helpers import (
    _deterministic_plan_repair,
    _infer_bulk_job_priority_mutation,
    _message_content_text,
    _tool_cards,
)
from ..state import AgentPlanOutput, AgentPlanStep, AgentState, user_query_text

RouteKey = Literal["clarify_end", "continue_planner", "decision_guard", "synthesize_plan"]

# Intent splitters emit *_ref / *_id fields; OpenAPI path templates often use ``id`` only.
# Only consult these when the tool's route collection matches ``_constraint_entity(field)``.
ENTITY_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "machine_ref": ("id", "machine_id", "machineID", "machineId", "machine_name", "machineName"),
    "job_ref": ("id", "job_id", "jobID", "jobId", "job_name", "jobName"),
    "product_ref": ("id", "product_id", "productID", "productId", "product_name", "productName"),
}


def _get_by_path(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _singular_entity(value: str) -> str:
    lowered = value.strip().lower().replace("-", "_")
    if lowered.endswith("ies") and len(lowered) > 3:
        return lowered[:-3] + "y"
    if lowered.endswith("s") and len(lowered) > 1:
        return lowered[:-1]
    return lowered


def _endpoint_entity_before_param(endpoint: str, param_name: str) -> str | None:
    segments = [segment for segment in (endpoint or "").split("/") if segment]
    target = f"{{{param_name}}}"
    for idx, segment in enumerate(segments):
        if segment != target:
            continue
        prior = next((item for item in reversed(segments[:idx]) if not item.startswith("{")), "")
        return _singular_entity(prior) if prior else None
    return None


def _constraint_entity(field: str) -> str | None:
    for suffix in ("_id", "_ref"):
        if field.endswith(suffix) and len(field) > len(suffix):
            return _singular_entity(field[: -len(suffix)])
    return None


def _tool_route_collection_entity(tool: ToolInfo) -> str | None:
    """First path segment of the tool name after METHOD__, e.g. ``get__machines_{id}`` → ``machine``."""
    m = re.match(r"^[a-z]+__(.+)$", (tool.name or "").strip(), re.I)
    if not m:
        return None
    tail = m.group(1)
    head = tail.split("_")[0].split("{")[0]
    if not head:
        return None
    return _singular_entity(head.replace("-", "_"))


def _constraint_applies_to_tool(
    *,
    constraint: dict[str, Any],
    tool_args: dict[str, Any],
    tool: ToolInfo | None,
) -> bool:
    """Whether a hard user constraint should bind to this tool call (skip unrelated reads in batches)."""
    field = str(constraint.get("field") or "")
    if not field:
        return False
    if tool_args.get(field) not in (None, ""):
        return True
    if tool is None:
        return True
    entity = _constraint_entity(field)
    if not entity:
        return True
    for pn in tool.path_params or re.findall(r"\{([a-zA-Z0-9_]+)\}", tool.endpoint or ""):
        if _endpoint_entity_before_param(tool.endpoint or "", pn) == entity:
            return True
    if _tool_route_collection_entity(tool) == entity:
        return True
    for key in (f"{entity}_id", f"{entity}_ref", f"{entity}_name"):
        if key in tool_args and tool_args.get(key) not in (None, ""):
            return True
    return False


def _constraint_actual(
    *,
    constraint: dict[str, Any],
    tool_args: dict[str, Any],
    tool: ToolInfo | None = None,
) -> Any:
    field = str(constraint.get("field") or "")
    actual = _get_by_path(tool_args, field) if "." in field else tool_args.get(field)
    if actual is not None or tool is None:
        return actual

    entity = _constraint_entity(field)
    if not entity:
        return None
    param_names = tool.path_params or re.findall(r"\{([a-zA-Z0-9_]+)\}", tool.endpoint or "")
    for param_name in param_names:
        if param_name not in tool_args:
            continue
        if _endpoint_entity_before_param(tool.endpoint, param_name) == entity:
            return tool_args.get(param_name)
    # Query/body aliases: intents often emit explicit_constraints like machine_ref=… while
    # tools use machine_id (query) or id (path). Without this mapping, DecisionGuard treats
    # correct calls as violations and loops planner→guard until LangGraph recursion_limit.
    if entity:
        if _tool_route_collection_entity(tool) == entity:
            for alias in ENTITY_FIELD_ALIASES.get(field, ()):
                v = tool_args.get(alias)
                if v is not None and v != "":
                    return v
        for key in (f"{entity}_id", f"{entity}_ref", f"{entity}_name"):
            v = tool_args.get(key)
            if v is not None and v != "":
                return v
        lone = param_names[0] if len(param_names) == 1 else None
        if lone and lone in tool_args and tool_args.get(lone) not in (None, ""):
            ep_ent = _endpoint_entity_before_param(tool.endpoint or "", lone)
            if ep_ent == entity:
                return tool_args.get(lone)
    return None


def _constraint_violated(
    *,
    constraint: dict[str, Any],
    tool_args: dict[str, Any],
    tool: ToolInfo | None = None,
) -> bool:
    if constraint.get("strength") == "soft":
        return False
    field = str(constraint.get("field") or "")
    if not field:
        return False
    op = str(constraint.get("operator") or "=")
    expected = constraint.get("value")
    actual = _constraint_actual(constraint=constraint, tool_args=tool_args, tool=tool)
    if op == "=":
        if actual is None:
            return True
        if isinstance(expected, str) and isinstance(actual, str):
            return expected.strip().upper() != actual.strip().upper()
        return actual != expected
    if op == "!=":
        return actual == expected
    if op == "in":
        if not isinstance(expected, list):
            return True
        return actual not in expected
    if op == "not_in":
        if not isinstance(expected, list):
            return False
        return actual in expected
    return False


def _collect_ref_tokens(obj: Any, out: set[str]) -> None:
    if isinstance(obj, str) and obj.startswith("$ref:") and len(obj) < 200:
        out.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_ref_tokens(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_ref_tokens(v, out)


def _assign_missing_output_refs(raw_calls: list[dict[str, Any]], tools_by_name: dict[str, ToolInfo]) -> None:
    for i, tc in enumerate(raw_calls):
        tool = tools_by_name.get(str(tc.get("tool_name") or ""))
        if not tool or tool.is_read_only:
            continue
        ref = tc.get("output_ref")
        if isinstance(ref, str) and ref.startswith("$ref:"):
            continue
        nm = re.sub(r"[^A-Za-z0-9_]+", "_", str(tc.get("tool_name") or "tool"))[:40]
        tc["output_ref"] = f"$ref:{nm}_{i}"


def planner_tool_output_tail(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Same slice as the planner prompt's \"Recent tool_outputs\" (last up to 4, post-truncation)."""
    recent = state.get("tool_outputs") or []
    if not isinstance(recent, list):
        return []
    truncated_at = int(state.get("tool_outputs_truncated_at") or 0)
    visible = recent[max(0, truncated_at) :]
    return visible[-4:] if len(visible) > 4 else list(visible)


def _forward_ref_violation(
    raw_calls: list[dict[str, Any]],
    tools_by_name: dict[str, ToolInfo],
    *,
    tool_output_tail: list[dict[str, Any]] | None = None,
) -> str | None:
    """Validate $ref placeholders against prior tool outputs and same-batch ordering.

    Naming (aligned with the planner prompt tail):
    - ``$ref:j`` for ``j < len(tail)`` → j-th row in ``tool_output_tail`` (cross-turn / earlier reads).
    - ``$ref:{len(tail)+k}`` → k-th *read* tool call in this batch (0-based among reads only).
    - Write tools still declare explicit ``output_ref`` names for same-turn write chaining.
    """
    tail = tool_output_tail or []
    tail_len = len(tail)

    declared: dict[str, int] = {}
    # Historical outputs always precede the current batch (producer index -1).
    for j in range(tail_len):
        declared[f"$ref:{j}"] = -1

    for i, tc in enumerate(raw_calls):
        if not isinstance(tc, dict):
            continue
        tool = tools_by_name.get(str(tc.get("tool_name") or ""))
        if not tool or tool.is_read_only:
            continue
        ref = tc.get("output_ref")
        if isinstance(ref, str) and ref.startswith("$ref:"):
            if ref in declared:
                return f"duplicate_output_ref:{ref}"
            declared[ref] = i

    # Validate each call's args against refs declared *before* this call, then register
    # implicit read outputs for later calls (fixes forward_or_self_ref when tail is empty).
    read_slot = 0
    for i, tc in enumerate(raw_calls):
        if not isinstance(tc, dict):
            continue
        need: set[str] = set()
        _collect_ref_tokens(tc.get("args"), need)
        for r in need:
            if r not in declared:
                return f"unknown_ref:{r}"
            prod = declared[r]
            if prod >= i:
                return f"forward_or_self_ref:{r}"
        tool = tools_by_name.get(str(tc.get("tool_name") or ""))
        if tool and tool.is_read_only:
            declared[f"$ref:{tail_len + read_slot}"] = i
            read_slot += 1
    return None


def _constraints_violated(
    *,
    constraints: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    tools_by_name: dict[str, ToolInfo] | None = None,
) -> bool:
    """Each hard constraint must be satisfiable by at least one *applicable* tool, and no applicable tool may violate it."""
    tbn = tools_by_name or {}
    for c in constraints:
        if not isinstance(c, dict) or c.get("strength") == "soft":
            continue
        applicable: list[dict[str, Any]] = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            tool = tbn.get(str(tc.get("tool_name") or ""))
            if _constraint_applies_to_tool(constraint=c, tool_args=args, tool=tool):
                applicable.append(tc)
        if not applicable:
            return True
        for tc in applicable:
            args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            tool = tbn.get(str(tc.get("tool_name") or ""))
            if _constraint_violated(constraint=c, tool_args=args, tool=tool):
                return True
    return False


def _intent_dependencies_satisfied(working: list[dict[str, Any]], idx: int) -> bool:
    intent = working[idx]
    for dep_id in intent.get("depends_on") or []:
        if not isinstance(dep_id, str):
            continue
        dep = next((x for x in working if x.get("intent_id") == dep_id), None)
        if dep is None:
            continue
        if dep.get("status") != "completed":
            return False
    return True


def _next_active_intent_index(working: list[dict[str, Any]], start: int) -> int | None:
    for i in range(max(0, start), len(working)):
        st = working[i].get("status")
        if st in ("pending", "in_progress") and _intent_dependencies_satisfied(working, i):
            return i
    return None


def _cascade_cancel_dependents(working: list[dict[str, Any]], failed_id: str, *, reason: str) -> None:
    bad: set[str] = {failed_id}
    while True:
        progressed = False
        for it in working:
            if it.get("status") != "pending":
                continue
            deps = {str(d) for d in (it.get("depends_on") or []) if isinstance(d, str)}
            if deps & bad:
                it["status"] = "cancelled_due_to_dependency_failure"
                it["failure_reason"] = reason
                iid = str(it.get("intent_id") or "")
                if iid:
                    bad.add(iid)
                progressed = True
        if not progressed:
            break


def _risk_for_tools(tool_calls: list[ToolCall], tools_by_name: dict[str, ToolInfo]) -> str:
    for tc in tool_calls:
        info = tools_by_name.get(tc.tool_name)
        if not info:
            continue
        if info.method != "GET" or not info.is_read_only:
            return "write_dry_run"
    return "read"


def _is_write_tool_name(tool_name: str, tools_by_name: dict[str, ToolInfo]) -> bool:
    tool = tools_by_name.get(tool_name)
    return tool is not None and not tool.is_read_only


def _deterministic_write_decision_from_repair(
    *,
    clause: str,
    scoped_tools: list[ToolInfo],
    current_intent: dict[str, Any],
    tools_by_name: dict[str, ToolInfo],
) -> PlannerDecision | None:
    repaired = _deterministic_plan_repair(clause, scoped_tools, context={})
    if repaired is None or not repaired.steps:
        return None
    calls = [ToolCall(tool_name=s.tool_name, args=dict(s.args or {})) for s in repaired.steps]
    if not calls or any(not _is_write_tool_name(tc.tool_name, tools_by_name) for tc in calls):
        return None
    return PlannerDecision(
        intent_id=str(current_intent.get("intent_id") or "unknown"),
        kind="domain_tool",
        tool_calls=calls,
        decision_summary="Deterministic write intent is complete; stage it for bundled approval.",
        risk_level=_risk_for_tools(calls, tools_by_name),
    )


def _job_rows_from_result(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if not isinstance(result, dict):
        return []
    data = result.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    for key in ("items", "results"):
        value = result.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _job_ids_from_rows(rows: list[dict[str, Any]], *, source_priority: str | None = None) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if source_priority:
            priority = row.get("priority")
            if isinstance(priority, str) and priority.strip().lower() != source_priority:
                continue
        value = row.get("job_id") or row.get("id")
        if value in (None, ""):
            continue
        job_id = str(value).strip()
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        ids.append(job_id)
    return ids


def _bulk_job_selection_ids(
    state: AgentState,
    *,
    source_priority: str,
) -> list[str] | None:
    outputs = state.get("tool_outputs") or []
    if not isinstance(outputs, list):
        return None
    truncated_at = int(state.get("tool_outputs_truncated_at") or 0)
    for row in reversed(outputs[max(0, truncated_at) :]):
        if not isinstance(row, dict) or row.get("tool_name") != "get__jobs":
            continue
        args = row.get("args") if isinstance(row.get("args"), dict) else {}
        if str(args.get("priority") or "").strip().lower() != source_priority:
            continue
        if row.get("http_status") is not None and int(row.get("http_status") or 0) >= 400:
            continue
        result = row.get("result")
        return _job_ids_from_rows(_job_rows_from_result(result), source_priority=source_priority)
    return None


def _bulk_job_priority_lookup_args(source_priority: str, tool: ToolInfo | None) -> dict[str, Any]:
    args: dict[str, Any] = {"priority": source_priority}
    if tool is None:
        return args
    query_params = set(tool.query_params or [])
    if "fields" in query_params:
        args["fields"] = "job_id,priority"
    if "limit" in query_params:
        args["limit"] = 500
    return args


def _bulk_job_priority_decision(
    *,
    state: AgentState,
    current_intent: dict[str, Any],
    tools_by_name: dict[str, ToolInfo],
    settings: Settings,
) -> PlannerDecision | None:
    mutation = _infer_bulk_job_priority_mutation(str(current_intent.get("description") or user_query_text(state)))
    if mutation is None:
        return None
    source = mutation["source_priority"]
    ids = _bulk_job_selection_ids(state, source_priority=source)
    if ids is None:
        get_jobs = tools_by_name.get("get__jobs")
        if get_jobs is None:
            return None
        return PlannerDecision(
            intent_id=str(current_intent.get("intent_id") or "unknown"),
            kind="domain_tool",
            tool_calls=[ToolCall(tool_name="get__jobs", args=_bulk_job_priority_lookup_args(source, get_jobs))],
            decision_summary=(
                f"Fetch only {source}-priority job identifiers before staging the requested bulk change."
            ),
            risk_level="read",
        )
    if not ids:
        return PlannerDecision(
            intent_id=str(current_intent.get("intent_id") or "unknown"),
            kind="intent_completed",
            tool_calls=[],
            decision_summary=f"No {source}-priority jobs were found to change.",
            risk_level="read",
        )

    capped = ids[: max(1, int(getattr(settings, "max_foreach_items", 50) or 50))]
    if mutation["action"] == "delete":
        if "delete__jobs_{id}" not in tools_by_name:
            return None
        calls = [ToolCall(tool_name="delete__jobs_{id}", args={"id": job_id}) for job_id in capped]
        summary = f"Stage deletion for {len(calls)} {source}-priority job(s) in one approval bundle."
    else:
        target = mutation.get("target_priority")
        if not target or "put__jobs_{id}" not in tools_by_name:
            return None
        calls = [
            ToolCall(tool_name="put__jobs_{id}", args={"id": job_id, "priority": target})
            for job_id in capped
        ]
        summary = f"Stage priority update for {len(calls)} {source}-priority job(s) in one approval bundle."
    return PlannerDecision(
        intent_id=str(current_intent.get("intent_id") or "unknown"),
        kind="domain_tool",
        tool_calls=calls,
        decision_summary=summary,
        risk_level="write_dry_run",
    )


def _next_bundleable_write_intent_index(state: AgentState) -> int | None:
    working = [dict(x) for x in (state.get("working_intents") or []) if isinstance(x, dict)]
    if not working:
        return None
    scoped = state.get("scoped_tools") or []
    tools_by_name = {t.name: t for t in scoped if getattr(t, "name", None)}
    cursor = int(state.get("intent_cursor") or 0)
    nxt = _next_active_intent_index(working, cursor + 1)
    if nxt is None:
        return None
    decision = _deterministic_write_decision_from_repair(
        clause=str(working[nxt].get("description") or ""),
        scoped_tools=scoped,
        current_intent=working[nxt],
        tools_by_name=tools_by_name,
    )
    return nxt if decision is not None else None


def _read_not_found_summary(*, state: AgentState, tools_by_name: dict[str, ToolInfo]) -> str | None:
    outputs = state.get("tool_outputs") or []
    if not isinstance(outputs, list):
        return None
    truncated_at = int(state.get("tool_outputs_truncated_at") or 0)
    for row in reversed(outputs[max(0, truncated_at) :]):
        if not isinstance(row, dict):
            continue
        name = row.get("tool_name")
        tool = tools_by_name.get(str(name)) if isinstance(name, str) else None
        if tool is None or not tool.is_read_only:
            continue
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        if row.get("http_status") != 404 and not result.get("not_found"):
            continue
        detail = result.get("_summary") or result.get("detail") or result.get("message")
        return str(detail or "Requested resource was not found.")
    return None


def _build_planner_decision_prompt(*, state: AgentState, current: dict[str, Any], tools_by_name: dict[str, ToolInfo]) -> str:
    tool_cards = state.get("tool_cards") or _tool_cards(list(tools_by_name.values()))
    recent_outputs = state.get("tool_outputs") or []
    truncated_at = int(state.get("tool_outputs_truncated_at") or 0)
    if isinstance(recent_outputs, list):
        visible = recent_outputs[max(0, truncated_at) :]
        tail = visible[-4:]
    else:
        tail = []
    failed = state.get("failed_strategies") or []
    return (
        "You are the factory planner brain (Phase 3). Emit ONE strict JSON object only — no markdown.\n"
        "Shape:\n"
        '{"intent_id":"string","kind":"domain_tool|parallel_read_tools|request_clarification|request_approval|'
        'intent_completed|intent_failed|halt",'
        '"tool_calls":[{"tool_name":"string","args":{}}],'
        '"control_action":null|{"name":"request_clarification|mark_intent_completed|mark_intent_failed","payload":{}},'
        '"decision_summary":"string",'
        '"risk_level":"read|write_dry_run|write_commit|high_risk"}\n'
        "Rules:\n"
        "- intent_id MUST match the current intent id.\n"
        "- For domain_tool / parallel_read_tools, only use tool_name values from the tool catalog.\n"
        "- For dependent writes in one decision, use $ref:... placeholders in args and optional output_ref per write call; "
        "the guard auto-fills missing output_ref.\n"
        "- $ref:j refers to the j-th row in Recent tool_outputs (0-based); additional reads in this same decision continue indexing after those rows.\n"
        "- Prefer read-only GET tools before writes; keep args minimal and schema-safe.\n"
        "- For every GET, use available filters/sort/limit/fields from the tool catalog to avoid broad table reads.\n"
        "- If a GET is only selecting records for a later write, request only identifiers plus predicate fields "
        "(for jobs, prefer fields=job_id,priority when available).\n"
        "- If mandatory user facts are missing, use kind request_clarification with control_action "
        '{"name":"request_clarification","payload":{"question":"..."}} and empty tool_calls.\n'
        "- Do NOT request clarification for a job/entity id when the user query or recent conversation already "
        'includes an explicit prefixed id (e.g. "JOB-…"); emit domain_tool / parallel_read_tools with args.id set instead.\n'
        "- When the current intent is fully satisfied using tool results already in state, use intent_completed "
        'with empty tool_calls and a short summary in decision_summary.\n'
        "- If the intent is impossible or unsafe, use intent_failed with decision_summary explaining why.\n"
        "- halt stops planning for this session (rare; catastrophic issues only).\n"
        f"Current intent JSON: {json.dumps(current, ensure_ascii=False)}\n"
        f"User query: {user_query_text(state)}\n"
        f"Recent tool_outputs (last up to 4): {json.dumps(tail, ensure_ascii=False)}\n"
        f"failed_strategies: {json.dumps(failed[-3:], ensure_ascii=False)}\n"
        f"Tool catalog: {json.dumps(tool_cards, ensure_ascii=False)}\n"
    )


def _coerce_decision_dict(raw: dict[str, Any], *, tools_by_name: dict[str, ToolInfo]) -> PlannerDecision:
    tcs: list[ToolCall] = []
    for item in raw.get("tool_calls") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("tool_name")
        if not isinstance(name, str) or not name.strip():
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        out_ref = item.get("output_ref")
        out_ref_s = out_ref.strip() if isinstance(out_ref, str) else None
        tcs.append(
            ToolCall(
                tool_name=name.strip(),
                args=args,
                output_ref=out_ref_s if out_ref_s and out_ref_s.startswith("$ref:") else None,
            )
        )
    ctrl = raw.get("control_action")
    control = ControlAction.model_validate(ctrl) if isinstance(ctrl, dict) else None
    kind = raw.get("kind")
    if kind not in (
        "domain_tool",
        "parallel_read_tools",
        "request_clarification",
        "request_approval",
        "intent_completed",
        "intent_failed",
        "halt",
    ):
        kind = "halt"
    summary = raw.get("decision_summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = "Planner step."
    risk = raw.get("risk_level")
    if risk not in ("read", "write_dry_run", "write_commit", "high_risk"):
        risk = _risk_for_tools(tcs, tools_by_name)
    intent_id = str(raw.get("intent_id") or "")
    if not intent_id:
        intent_id = "unknown"
    return PlannerDecision(
        intent_id=intent_id,
        kind=kind,  # type: ignore[arg-type]
        tool_calls=tcs,
        control_action=control,
        decision_summary=summary.strip(),
        risk_level=risk,  # type: ignore[arg-type]
        violates_constraints=bool(raw.get("violates_constraints")),
    )


def _fallback_decision_from_repair(
    *,
    clause: str,
    scoped_tools: list[ToolInfo],
    current_intent: dict[str, Any],
) -> PlannerDecision | None:
    repaired = _deterministic_plan_repair(clause, scoped_tools, context={})
    if repaired is None or not repaired.steps:
        return None
    first = repaired.steps[0]
    tools_by_name = {t.name: t for t in scoped_tools}
    tcs = [ToolCall(tool_name=first.tool_name, args=dict(first.args or {}))]
    return PlannerDecision(
        intent_id=str(current_intent.get("intent_id") or "unknown"),
        kind="domain_tool",
        tool_calls=tcs,
        decision_summary="Deterministic repair selected the first safe tool step.",
        risk_level=_risk_for_tools(tcs, tools_by_name),
    )


def make_planner_node(settings: Settings):
    async def planner_node(state: AgentState) -> dict[str, Any]:
        staged_existing = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]
        if staged_existing:
            scoped_existing = state.get("scoped_tools") or []
            tools_by_name_existing = {t.name: t for t in scoped_existing if getattr(t, "name", None)}
            working_existing = [dict(x) for x in (state.get("working_intents") or []) if isinstance(x, dict)]
            cursor_existing = int(state.get("intent_cursor") or 0)
            next_write_idx = _next_bundleable_write_intent_index(state)
            if next_write_idx is not None and 0 <= next_write_idx < len(working_existing):
                if 0 <= cursor_existing < len(working_existing):
                    working_existing[cursor_existing]["status"] = "completed"
                current_next = working_existing[next_write_idx]
                current_next["status"] = "in_progress"
                working_existing[next_write_idx] = current_next
                decision = _deterministic_write_decision_from_repair(
                    clause=str(current_next.get("description") or ""),
                    scoped_tools=scoped_existing,
                    current_intent=current_next,
                    tools_by_name=tools_by_name_existing,
                )
                if decision is not None:
                    iteration = int(state.get("planner_iteration") or 0) + 1
                    return {
                        "planner_iteration": iteration,
                        "working_intents": working_existing,
                        "intent_cursor": next_write_idx,
                        "current_intent": current_next,
                        "pending_decision": decision.model_dump(mode="json"),
                        "decisions": [decision.model_dump(mode="json")],
                        "completed_actions": [
                            {
                                "phase": "planner",
                                "intent_id": decision.intent_id,
                                "kind": decision.kind,
                                "summary": decision.decision_summary,
                                "iteration": iteration,
                            }
                        ],
                        "next_route": "decision_guard",
                        "status": "planning",
                    }
            return {
                "pending_decision": None,
                "next_route": "synthesize_plan",
                "status": "validating",
            }

        scoped = state.get("scoped_tools") or []
        tools_by_name = {t.name: t for t in scoped if getattr(t, "name", None)}
        working = [dict(x) for x in (state.get("working_intents") or [])]
        if not working:
            working = [
                {
                    "intent_id": "intent-fallback",
                    "description": user_query_text(state),
                    "depends_on": [],
                    "explicit_constraints": [],
                    "status": "pending",
                    "category": "unknown",
                }
            ]

        iteration = int(state.get("planner_iteration") or 0) + 1
        max_loops = max(settings.max_plan_steps * 3, 12)

        if iteration > max_loops:
            rep = _deterministic_plan_repair(user_query_text(state), scoped, context=state.get("context") or {})
            if rep is not None:
                steps = [
                    ToolCall(tool_name=s.tool_name, args=dict(s.args or {}))
                    for s in rep.steps[: settings.max_plan_steps]
                ]
                dec = PlannerDecision(
                    intent_id=str(working[min(state.get("intent_cursor") or 0, len(working) - 1)].get("intent_id")),
                    kind="domain_tool",
                    tool_calls=steps,
                    decision_summary="Iteration cap reached; using deterministic repair sequence.",
                    risk_level=_risk_for_tools(steps, tools_by_name),
                )
                return {
                    "planner_iteration": iteration,
                    "working_intents": working,
                    "pending_decision": dec.model_dump(mode="json"),
                    "next_route": "decision_guard",
                    "status": "planning",
                }
            return {
                "planner_iteration": iteration,
                "working_intents": working,
                "next_route": "synthesize_plan",
                "status": "planning",
            }

        cursor = int(state.get("intent_cursor") or 0)
        nxt = _next_active_intent_index(working, cursor)
        if nxt is None:
            return {
                "planner_iteration": iteration,
                "working_intents": working,
                "pending_decision": None,
                "next_route": "synthesize_plan",
                "status": "validating",
            }

        if nxt != cursor:
            cursor = nxt
        current = working[cursor]
        if current.get("status") == "pending":
            current["status"] = "in_progress"
        working[cursor] = current
        prev_decisions = list(state.get("decisions") or [])

        bulk_decision = _bulk_job_priority_decision(
            state=state,
            current_intent=current,
            tools_by_name=tools_by_name,
            settings=settings,
        )
        if bulk_decision is not None:
            if bulk_decision.kind == "intent_completed":
                current["status"] = "completed"
                working[cursor] = current
                later = _next_active_intent_index(working, cursor + 1)
                return {
                    "planner_iteration": iteration,
                    "working_intents": working,
                    "intent_cursor": later if later is not None else cursor,
                    "current_intent": working[later] if later is not None else current,
                    "pending_decision": None,
                    "decisions": prev_decisions + [bulk_decision.model_dump(mode="json")],
                    "completed_actions": [
                        {
                            "phase": "planner",
                            "intent_id": bulk_decision.intent_id,
                            "kind": bulk_decision.kind,
                            "summary": bulk_decision.decision_summary,
                            "iteration": iteration,
                        }
                    ],
                    "next_route": "continue_planner" if later is not None else "synthesize_plan",
                    "status": "planning" if later is not None else "validating",
                }
            return {
                "planner_iteration": iteration,
                "working_intents": working,
                "intent_cursor": cursor,
                "current_intent": current,
                "pending_decision": bulk_decision.model_dump(mode="json"),
                "decisions": prev_decisions + [bulk_decision.model_dump(mode="json")],
                "completed_actions": [
                    {
                        "phase": "planner",
                        "intent_id": bulk_decision.intent_id,
                        "kind": bulk_decision.kind,
                        "summary": bulk_decision.decision_summary,
                        "iteration": iteration,
                    }
                ],
                "next_route": "decision_guard",
                "status": "planning",
            }

        direct_write_decision = _deterministic_write_decision_from_repair(
            clause=str(current.get("description") or user_query_text(state)),
            scoped_tools=scoped,
            current_intent=current,
            tools_by_name=tools_by_name,
        )
        if direct_write_decision is not None:
            return {
                "planner_iteration": iteration,
                "working_intents": working,
                "intent_cursor": cursor,
                "current_intent": current,
                "pending_decision": direct_write_decision.model_dump(mode="json"),
                "decisions": prev_decisions + [direct_write_decision.model_dump(mode="json")],
                "completed_actions": [
                    {
                        "phase": "planner",
                        "intent_id": direct_write_decision.intent_id,
                        "kind": direct_write_decision.kind,
                        "summary": direct_write_decision.decision_summary,
                        "iteration": iteration,
                    }
                ],
                "next_route": "decision_guard",
                "status": "planning",
            }

        not_found_summary = _read_not_found_summary(state=state, tools_by_name=tools_by_name)
        if not_found_summary:
            current["status"] = "completed"
            working[cursor] = current
            later = _next_active_intent_index(working, cursor + 1)
            return {
                "planner_iteration": iteration,
                "working_intents": working,
                "intent_cursor": later if later is not None else cursor,
                "current_intent": current,
                "pending_decision": None,
                "completed_actions": [
                    {
                        "phase": "planner",
                        "intent_id": current.get("intent_id"),
                        "kind": "intent_completed",
                        "summary": not_found_summary,
                    }
                ],
                "next_route": "continue_planner" if later is not None else "synthesize_plan",
                "status": "planning" if later is not None else "validating",
            }

        if not (settings.planner_openai_base_url or settings.openai_api_key):
            raise LangGraphPlannerError(
                "LangGraph planner requires PLANNER_OPENAI_BASE_URL (or OPENAI_BASE_URL) or OPENAI_API_KEY."
            )

        prompt = _build_planner_decision_prompt(state=state, current=current, tools_by_name=tools_by_name)
        log_llm_prompt(
            component="planner_loop",
            backend="langgraph",
            model=settings.planner_model,
            prompt=prompt,
            metadata={"intent_cursor": cursor, "intent_id": current.get("intent_id")},
        )
        model = build_planner_chat_model(settings, json_mode=True)
        try:
            raw_resp = await model.ainvoke(prompt)
        except Exception as exc:
            raise LangGraphPlannerError(str(exc)) from exc
        content = _message_content_text(raw_resp)
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}

        decision = _coerce_decision_dict(parsed, tools_by_name=tools_by_name)
        if decision.intent_id != str(current.get("intent_id")):
            fb = _fallback_decision_from_repair(
                clause=str(current.get("description") or user_query_text(state)),
                scoped_tools=scoped,
                current_intent=current,
            )
            if fb is not None:
                decision = fb
            else:
                decision = PlannerDecision(
                    intent_id=str(current.get("intent_id")),
                    kind="request_clarification",
                    tool_calls=[],
                    control_action=None,
                    decision_summary="Model returned mismatched intent_id or invalid JSON.",
                    risk_level="read",
                )

        if decision.kind in ("domain_tool", "parallel_read_tools") and decision.tool_calls:
            unknown = [tc.tool_name for tc in decision.tool_calls if tc.tool_name not in tools_by_name]
            if unknown:
                log_event(
                    "planner_unknown_tools",
                    level="WARNING",
                    unknown_tools=unknown,
                    intent_id=current.get("intent_id"),
                )
                fb = _fallback_decision_from_repair(
                    clause=str(current.get("description") or user_query_text(state)),
                    scoped_tools=scoped,
                    current_intent=current,
                )
                decision = fb or PlannerDecision(
                    intent_id=str(current.get("intent_id")),
                    kind="request_clarification",
                    tool_calls=[],
                    decision_summary=f"Planner proposed unsupported tools: {unknown}.",
                    risk_level="read",
                )

        if decision.kind in ("domain_tool", "parallel_read_tools", "request_approval") and not decision.tool_calls:
            fb = _fallback_decision_from_repair(
                clause=str(current.get("description") or user_query_text(state)),
                scoped_tools=scoped,
                current_intent=current,
            )
            if fb is not None:
                decision = fb

        next_route: RouteKey = "decision_guard"
        extra: dict[str, Any] = {}
        pending_payload: dict[str, Any] | None = decision.model_dump(mode="json")

        if decision.kind == "request_clarification":
            rep = _deterministic_plan_repair(
                str(current.get("description") or user_query_text(state)),
                scoped,
                context=state.get("context") or {},
            )
            if rep is not None and rep.steps:
                steps_tc = [
                    ToolCall(tool_name=s.tool_name, args=dict(s.args or {}))
                    for s in rep.steps[: settings.max_plan_steps]
                ]
                decision = PlannerDecision(
                    intent_id=str(current.get("intent_id")),
                    kind="domain_tool",
                    tool_calls=steps_tc,
                    decision_summary="Deterministic repair replaced an unnecessary clarification request.",
                    risk_level=_risk_for_tools(steps_tc, tools_by_name),
                )
                next_route = "decision_guard"
                pending_payload = decision.model_dump(mode="json")
            else:
                q = None
                if decision.control_action and isinstance(decision.control_action.payload, dict):
                    q = decision.control_action.payload.get("question")
                if not isinstance(q, str) or not q.strip():
                    q = decision.decision_summary
                extra["clarification"] = q.strip()
                extra["status"] = "awaiting_clarification"
                next_route = "clarify_end"
                pending_payload = None
        elif decision.kind == "intent_completed":
            current["status"] = "completed"
            working[cursor] = current
            later = _next_active_intent_index(working, cursor + 1)
            if later is not None:
                extra["intent_cursor"] = later
                next_route = "continue_planner"
            else:
                next_route = "synthesize_plan"
                extra["status"] = "validating"
        elif decision.kind == "intent_failed":
            reason = decision.decision_summary
            current["status"] = "failed"
            current["failure_reason"] = reason
            working[cursor] = current
            failed_id = str(current.get("intent_id"))
            _cascade_cancel_dependents(working, failed_id, reason=reason)
            nxt2 = _next_active_intent_index(working, 0)
            if nxt2 is not None:
                extra["intent_cursor"] = nxt2
                next_route = "continue_planner"
            else:
                next_route = "synthesize_plan"
                extra["status"] = "validating"
        elif decision.kind == "halt":
            next_route = "synthesize_plan"
            extra["status"] = "validating"
        elif decision.kind in ("domain_tool", "parallel_read_tools", "request_approval"):
            next_route = "decision_guard"
        else:
            next_route = "decision_guard"

        prev_decisions = list(state.get("decisions") or [])
        planner_trace = [
            {
                "phase": "planner",
                "intent_id": decision.intent_id,
                "kind": decision.kind,
                "summary": decision.decision_summary,
                "iteration": iteration,
            }
        ]

        new_cursor = int(extra.get("intent_cursor", cursor))
        if working and 0 <= new_cursor < len(working):
            cur_obj: dict[str, Any] | None = working[new_cursor]
        else:
            cur_obj = working[cursor] if working and 0 <= cursor < len(working) else None

        out: dict[str, Any] = {
            "planner_iteration": iteration,
            "working_intents": working,
            "intent_cursor": new_cursor,
            "current_intent": cur_obj,
            "pending_decision": pending_payload,
            "decisions": prev_decisions + [decision.model_dump(mode="json")],
            "completed_actions": planner_trace,
            "next_route": next_route,
            "status": extra.get("status", "planning"),
        }
        out.update({k: v for k, v in extra.items() if k != "intent_cursor"})
        return out

    return planner_node


def decision_guard_node(state: AgentState) -> dict[str, Any]:
    pending = state.get("pending_decision")
    if not isinstance(pending, dict):
        return {"next_route": "continue_planner"}
    scoped = state.get("scoped_tools") or []
    tools_by_name = {t.name: t for t in scoped if getattr(t, "name", None)}
    current = state.get("current_intent")
    constraints: list[dict[str, Any]] = []
    if isinstance(current, dict):
        constraints = [c for c in (current.get("explicit_constraints") or []) if isinstance(c, dict)]

    raw_calls = pending.get("tool_calls") or []
    if not isinstance(raw_calls, list):
        raw_calls = []
    raw_ref_calls = [dict(item) for item in raw_calls if isinstance(item, dict)]
    _assign_missing_output_refs(raw_ref_calls, tools_by_name)
    raw_ref_err = _forward_ref_violation(
        raw_ref_calls,
        tools_by_name,
        tool_output_tail=planner_tool_output_tail(state),
    )
    if raw_ref_err:
        pending2 = dict(pending)
        pending2["violates_constraints"] = True
        pending2["tool_calls"] = []
        pending2["decision_summary"] = (
            str(pending2.get("decision_summary") or "") + f" [guard: invalid transaction refs: {raw_ref_err}]"
        ).strip()
        log_event(
            "decision_guard_blocked",
            level="WARNING",
            intent_id=pending2.get("intent_id"),
            detail=raw_ref_err,
        )
        return {
            "pending_decision": pending2,
            "next_route": "continue_planner",
            "failed_strategies": [
                {
                    "phase": "decision_guard",
                    "intent_id": pending2.get("intent_id"),
                    "reason": "transaction_ref_violation",
                    "detail": raw_ref_err,
                    "repair_instruction": "Revise the decision without forward, missing, duplicate, or self references.",
                }
            ],
            "completed_actions": [
                {
                    "phase": "decision_guard",
                    "intent_id": pending2.get("intent_id"),
                    "kind": "transaction_ref_violation",
                    "summary": raw_ref_err,
                }
            ],
        }
    fixed_calls: list[dict[str, Any]] = []
    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    intent_memory = context.get("intent_memory") if isinstance(context.get("intent_memory"), dict) else {}
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        fixed = dict(item)
        tool = tools_by_name.get(str(fixed.get("tool_name") or ""))
        if tool is not None:
            raw_args = fixed.get("args") if isinstance(fixed.get("args"), dict) else {}
            sanitized_args, _ = sanitize_tool_args_against_schema(tool, dict(raw_args))
            provenance = promote_user_provenance(
                tool=tool,
                args=sanitized_args,
                intent=user_query_text(state),
                evidence={},
            )
            clean_args, _ = strip_unsupported_optional_args(
                tool=tool,
                args=sanitized_args,
                intent=user_query_text(state),
                intent_memory=intent_memory,
                arg_provenance=provenance,
            )
            fixed["args"] = clean_args
        fixed_calls.append(fixed)
    _assign_missing_output_refs(fixed_calls, tools_by_name)
    ref_err = _forward_ref_violation(
        fixed_calls,
        tools_by_name,
        tool_output_tail=planner_tool_output_tail(state),
    )
    if ref_err:
        pending2 = dict(pending)
        pending2["violates_constraints"] = True
        pending2["tool_calls"] = []
        pending2["decision_summary"] = (
            str(pending2.get("decision_summary") or "") + f" [guard: invalid transaction refs: {ref_err}]"
        ).strip()
        log_event(
            "decision_guard_blocked",
            level="WARNING",
            intent_id=pending2.get("intent_id"),
            detail=ref_err,
        )
        return {
            "pending_decision": pending2,
            "next_route": "continue_planner",
            "failed_strategies": [
                {
                    "phase": "decision_guard",
                    "intent_id": pending2.get("intent_id"),
                    "reason": "transaction_ref_violation",
                    "detail": ref_err,
                    "repair_instruction": "Revise the decision without forward, missing, duplicate, or self references.",
                }
            ],
            "completed_actions": [
                {
                    "phase": "decision_guard",
                    "intent_id": pending2.get("intent_id"),
                    "kind": "transaction_ref_violation",
                    "summary": ref_err,
                }
            ],
        }

    pending = dict(pending)
    pending["tool_calls"] = fixed_calls

    if (
        constraints
        and fixed_calls
        and _constraints_violated(
            constraints=constraints,
            tool_calls=fixed_calls,
            tools_by_name=tools_by_name,
        )
    ):
        if isinstance(current, dict):
            fb = _fallback_decision_from_repair(
                clause=str(current.get("description") or user_query_text(state)),
                scoped_tools=scoped,
                current_intent=current,
            )
            if fb is not None:
                repaired_calls = [tc.model_dump(mode="json") for tc in fb.tool_calls]
                _assign_missing_output_refs(repaired_calls, tools_by_name)
                if not _constraints_violated(
                    constraints=constraints,
                    tool_calls=repaired_calls,
                    tools_by_name=tools_by_name,
                ):
                    return {
                        "pending_decision": {
                            **fb.model_dump(mode="json"),
                            "tool_calls": repaired_calls,
                        },
                        "next_route": "tool_execution",
                        "completed_actions": [
                            {
                                "phase": "decision_guard",
                                "intent_id": fb.intent_id,
                                "kind": "constraint_repair",
                                "summary": "Deterministic repair preserved explicit user constraints.",
                            }
                        ],
                    }
        pending["violates_constraints"] = True
        pending["tool_calls"] = []
        pending["decision_summary"] = (
            str(pending.get("decision_summary") or "")
            + " [guard: proposed args violated explicit user constraints; skipped tool execution]"
        ).strip()
        log_event(
            "decision_guard_blocked",
            level="WARNING",
            intent_id=pending.get("intent_id"),
            constraints=constraints,
        )
        return {
            "pending_decision": pending,
            "next_route": "continue_planner",
            "failed_strategies": [
                {
                    "phase": "decision_guard",
                    "intent_id": pending.get("intent_id"),
                    "reason": "constraint_violation",
                    "constraints": constraints,
                    "repair_instruction": "Revise tool args so every hard explicit user constraint is preserved.",
                }
            ],
            "completed_actions": [
                {
                    "phase": "decision_guard",
                    "intent_id": pending.get("intent_id"),
                    "kind": "constraint_violation",
                    "summary": "Skipped tool execution; routing to planner for repair.",
                }
            ],
        }
    return {"pending_decision": pending, "next_route": "tool_execution"}


def _plan_step_key(tool_name: str, args: dict[str, Any]) -> str:
    return f"{tool_name}::{json.dumps(args, sort_keys=True, default=str)}"


def synthesize_plan_node(state: AgentState) -> dict[str, Any]:
    """Build a structured plan blueprint from the graph execution trace."""
    scoped = state.get("scoped_tools") or []
    tools_by_name = {t.name: t for t in scoped if getattr(t, "name", None)}
    steps: list[AgentPlanStep] = []
    seen_keys: set[str] = set()
    for entry in state.get("completed_actions") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("phase") != "tool_execution":
            continue
        name = entry.get("tool_name")
        if not isinstance(name, str) or name not in tools_by_name:
            continue
        args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
        args_copy = dict(args)
        tool_def = tools_by_name[name]
        sanitized, _ = sanitize_tool_args_against_schema(tool_def, args_copy)
        key = _plan_step_key(name, sanitized)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        steps.append(
            AgentPlanStep(
                tool_name=name,
                args=dict(sanitized),
                evidence={},
                confidence=0.85,
                missing_required=[],
                depends_on=[len(steps) - 1] if steps else [],
            )
        )

    if not steps:
        rep = _deterministic_plan_repair(user_query_text(state), scoped, context=state.get("context") or {})
        if rep is not None:
            return {"plan_blueprint": rep, "risk_summary": rep.risk_summary, "status": "planning"}

        return {
            "plan_blueprint": AgentPlanOutput(
                plan_explanation=f"No tool steps recorded; cannot map request: {user_query_text(state)}",
                risk_summary="Empty planner trace.",
                steps=[],
                clarification="I could not derive executable tool steps from the planner loop.",
            ),
            "status": "awaiting_clarification",
        }

    expl_parts = [str(s.get("summary", "")) for s in (state.get("completed_actions") or []) if isinstance(s, dict) and s.get("phase") == "planner"]
    plan_explanation = " ".join(expl_parts).strip() or f"Planned tool sequence for: {user_query_text(state)}"
    risk = state.get("risk_summary") or "Review tool calls before execution."
    return {
        "plan_blueprint": AgentPlanOutput(
            plan_explanation=plan_explanation,
            risk_summary=str(risk),
            steps=steps,
            clarification=None,
        ),
        "status": "planning",
    }


def clarify_end_node(state: AgentState) -> dict[str, Any]:
    return {"status": "awaiting_clarification", "next_route": "clarify_end"}


def route_after_planner(state: AgentState) -> str:
    r = state.get("next_route")
    if r in ("clarify_end", "continue_planner", "decision_guard", "synthesize_plan"):
        return str(r)
    return "decision_guard"


def route_after_guard(state: AgentState) -> str:
    r = state.get("next_route")
    if r == "continue_planner":
        return "continue_planner"
    if r == "tool_execution":
        return "tool_execution"
    return "tool_execution"
