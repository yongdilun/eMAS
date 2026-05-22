from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph.message import add_messages

from ..schemas import AgentGraphRunStatus, AgentPlanOutput, PlanDraft, ToolInfo


def replaceable_list_reducer(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """Append reducer with an explicit replacement escape hatch.

    Most graph list fields are traces and should append. A few runtime buffers
    such as staged writes must also be clearable during forward-only repair; a
    plain ``operator.add`` reducer would silently keep stale writes alive.
    """
    if right and len(right) == 1 and isinstance(right[0], dict) and right[0].get("__replace__") is True:
        value = right[0].get("value", [])
        return list(value) if isinstance(value, list) else []
    return list(left or []) + list(right or [])


def replace_list(value: list[Any] | None = None) -> list[dict[str, Any]]:
    return [{"__replace__": True, "value": list(value or [])}]


def normalize_graph_messages(raw: Any) -> list[AnyMessage]:
    """Turn mixed context payloads into LangChain messages for ``add_messages`` state."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[AnyMessage] = []
    for item in raw:
        if isinstance(item, BaseMessage):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().lower()
        content = item.get("content")
        text = content if isinstance(content, str) else str(content or "")
        if role == "system":
            out.append(SystemMessage(content=text))
        elif role == "assistant":
            out.append(AIMessage(content=text))
        elif role == "tool_result":
            out.append(ToolMessage(content=text, tool_call_id=str(item.get("tool_call_id") or "context")))
        else:
            out.append(HumanMessage(content=text))
    return out


def user_query_text(state: dict[str, Any]) -> str:
    """Resolve the primary user request from canonical or legacy keys."""
    q = state.get("original_query")
    if isinstance(q, str) and q.strip():
        return q.strip()
    legacy = state.get("intent")
    return legacy.strip() if isinstance(legacy, str) else ""


class AgentState(TypedDict, total=False):
    """LangGraph single source of truth (Phase 1 schema + reducers).

    List fields marked with ``operator.add`` or ``add_messages`` must only be
    updated via deltas in node returns (never echo the full accumulated list).
    """

    # --- Session / routing (overwrite) ---
    session_id: str | None
    original_query: str
    intent: str
    context: dict[str, Any]
    scoped_tools: list[ToolInfo]
    tool_cards: list[dict[str, Any]]
    # Phase 3: mutable copy of split intents (overwrite each tick; ``intents`` stays append-only trace).
    working_intents: list[dict[str, Any]]
    intent_cursor: int
    pending_decision: dict[str, Any] | None
    planner_iteration: int
    current_intent: dict[str, Any] | str | None
    retrieved_info: dict[str, Any]
    decisions: list[dict[str, Any]]
    approval_requests: list[dict[str, Any]]
    validation_results: list[dict[str, Any]]
    status: AgentGraphRunStatus | None
    intent_contract: dict[str, Any] | None
    clarification: str | None
    final_response: str | None
    risk_summary: str | None
    next_route: str | None
    # Phase 4: tool execution / staging / commit
    write_generation: int
    pending_relevance_batch: list[dict[str, Any]] | None
    fatal_system_error: str | None
    bundle_dry_run_result: dict[str, Any] | None
    last_commit_result: dict[str, Any] | None
    repair_attempts: int
    tool_outputs_truncated_at: int

    # --- LangGraph message channel ---
    messages: Annotated[list[AnyMessage], add_messages]

    # --- Append-only traces (reducers) ---
    intents: Annotated[list[dict[str, Any]], operator.add]
    tool_outputs: Annotated[list[dict[str, Any]], operator.add]
    completed_actions: Annotated[list[dict[str, Any]], operator.add]
    staged_writes: Annotated[list[dict[str, Any]], replaceable_list_reducer]
    failed_strategies: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    idempotency_audit: Annotated[list[dict[str, Any]], operator.add]

    # --- Planner artifacts (LangGraph-native names) ---
    plan_blueprint: AgentPlanOutput | None
    validated_plan: PlanDraft | None
