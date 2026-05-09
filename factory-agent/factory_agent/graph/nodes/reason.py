from __future__ import annotations

from typing import Any

from ...config import Settings
from ...llm.models import build_planner_chat_model
from ...llm.structured_output import parse_agent_plan_output
from ...observability.telemetry import log_event, log_llm_prompt
from ..errors import LangGraphPlannerError
from ..planner_graph_helpers import (
    _build_agent_prompt,
    _deterministic_plan_repair,
    _extract_json_obj,
    _message_content_text,
    _normalize_plan_dict,
)
from ..state import AgentState


def make_reason_node(settings: Settings):
    async def reason_node(state: AgentState) -> AgentState:
        if not (settings.planner_openai_base_url or settings.openai_api_key):
            raise LangGraphPlannerError(
                "LangGraph planner requires PLANNER_OPENAI_BASE_URL (or OPENAI_BASE_URL) or OPENAI_API_KEY."
            )

        intent = state.get("intent") or ""
        context = state.get("context") or {}
        tool_cards = state.get("tool_cards") or []
        prompt = _build_agent_prompt(intent=intent, context=context, tool_cards=tool_cards)
        log_llm_prompt(
            component="planner",
            backend="langgraph",
            model=settings.planner_model,
            prompt=prompt,
            metadata={"intent": intent, "scoped_tool_count": len(tool_cards)},
        )
        model = build_planner_chat_model(settings, json_mode=True)
        try:
            raw_resp = await model.ainvoke(prompt)
        except Exception as exc:
            raise LangGraphPlannerError(str(exc)) from exc
        content = _message_content_text(raw_resp)
        parsed = _extract_json_obj(content)
        if not isinstance(parsed, dict):
            log_event(
                "langgraph_planner_invalid_json",
                level="WARNING",
                intent=intent,
                content_preview=content[:500],
            )
            repaired = _deterministic_plan_repair(intent, state.get("scoped_tools") or [])
            if repaired is not None:
                log_event(
                    "langgraph_planner_deterministic_repair",
                    level="WARNING",
                    intent=intent,
                    reason="invalid_json",
                    tool_names=[step.tool_name for step in repaired.steps],
                )
                return {**state, "raw_plan": repaired, "risk_summary": repaired.risk_summary}
            raise LangGraphPlannerError("LangGraph planner returned invalid JSON.")
        try:
            plan = parse_agent_plan_output(parsed)
        except Exception as exc:
            normalized = _normalize_plan_dict(parsed)
            log_event(
                "langgraph_planner_invalid_schema",
                level="WARNING",
                intent=intent,
                parsed_keys=sorted(parsed.keys()),
                normalized_keys=sorted(normalized.keys()) if isinstance(normalized, dict) else [],
                error=str(exc),
            )
            raise LangGraphPlannerError("LangGraph planner returned JSON that does not match AgentPlanOutput.") from exc
        return {**state, "raw_plan": plan, "risk_summary": plan.risk_summary}

    return reason_node

