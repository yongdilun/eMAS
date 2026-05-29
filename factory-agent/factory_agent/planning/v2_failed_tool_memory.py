from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .v2_agent_state import GraphToolCall, PlannerOwnedAgentGraphState


REPLAN_SPINE_DIAGNOSTIC_KEY = "replan_spine"
TRANSIENT_RETRYABLE_ERROR_TYPES = {"timeout", "network"}


def failed_tool_calls_for_requirement(
    state: PlannerOwnedAgentGraphState,
    requirement_id: str | None,
) -> list[dict[str, Any]]:
    if not requirement_id:
        return []
    replan = state.execution_trace.diagnostics.get(REPLAN_SPINE_DIAGNOSTIC_KEY)
    if not isinstance(replan, Mapping):
        return []
    return [
        dict(call)
        for call in replan.get("failed_tool_calls", [])
        if isinstance(call, Mapping) and call.get("requirement_id") == requirement_id
    ]


def failed_tool_memory_filtered_candidates(
    candidate_tool_calls: list[GraphToolCall],
    failed_calls: list[Mapping[str, Any]],
) -> list[GraphToolCall]:
    filtered = [
        call
        for call in candidate_tool_calls
        if not tool_call_matches_failed_memory(call, failed_calls)
    ]
    return filtered or candidate_tool_calls


def tool_call_matches_failed_memory(
    call: GraphToolCall,
    failed_calls: list[Mapping[str, Any]],
) -> bool:
    return any(tool_call_matches_failed_tool_call(call, failed) for failed in failed_calls)


def tool_call_matches_failed_tool_call(
    call: GraphToolCall,
    failed_call: Mapping[str, Any],
) -> bool:
    error_type = str(failed_call.get("error_type") or "").strip().lower()
    if error_type in TRANSIENT_RETRYABLE_ERROR_TYPES:
        return False
    failed_requirement_id = str(failed_call.get("requirement_id") or "")
    if failed_requirement_id and failed_requirement_id != call.requirement_id:
        return False
    if call.tool_name != failed_call.get("tool_name"):
        return False
    return _json_equal(dict(call.args), dict(failed_call.get("args") or {}))


def same_tool_call_signature(left: GraphToolCall, right: GraphToolCall) -> bool:
    return (
        left.kind == right.kind
        and left.tool_name == right.tool_name
        and left.requirement_id == right.requirement_id
        and _json_equal(left.args, right.args)
    )


def tool_call_signature(call: GraphToolCall) -> dict[str, Any]:
    return {
        "call_id": call.call_id,
        "kind": call.kind,
        "tool_name": call.tool_name,
        "requirement_id": call.requirement_id,
        "args": dict(call.args),
    }


def _json_equal(left: Any, right: Any) -> bool:
    return _json_key(left) == _json_key(right)


def _json_key(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        value = {str(key): child for key, child in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
        value = list(value)
    return json.dumps(value, sort_keys=True, default=str)
