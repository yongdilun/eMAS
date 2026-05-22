"""LangGraph / AgentState test fixtures (not a pytest module — name does not use ``test_`` prefix)."""

from __future__ import annotations

from typing import Any

from factory_agent.schemas import AgentPlanOutput, ToolInfo


def stub_agent_state(
    *,
    query: str,
    scoped_tools: list[ToolInfo],
    context: dict[str, Any] | None = None,
    plan_blueprint: AgentPlanOutput | None = None,
    tool_cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Minimal state dict for validate/reason nodes."""
    out: dict[str, Any] = {
        "original_query": query,
        "intent": query,
        "context": context or {},
        "scoped_tools": scoped_tools,
    }
    if plan_blueprint is not None:
        out["plan_blueprint"] = plan_blueprint
    if tool_cards is not None:
        out["tool_cards"] = tool_cards
    return out
