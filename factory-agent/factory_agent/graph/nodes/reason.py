from __future__ import annotations

from typing import Any

from ...config import Settings
from ...llm.models import build_planner_chat_model
from ...llm.plan_parsing import _normalize_plan_dict
from ...llm.structured_output import parse_agent_plan_output
from ...observability.telemetry import log_event, log_llm_prompt
from ..errors import LangGraphPlannerError
from ..planner_graph_helpers import (
    _build_agent_prompt,
    _deterministic_plan_repair,
    _extract_json_obj,
    _message_content_text,
)
from ..state import AgentPlanOutput, AgentPlanStep, AgentState, user_query_text


def _coerce_confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return 0.0
    return 0.0


def _coerce_depends_on(value: Any, *, step_idx: int) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            dep = item
        elif isinstance(item, float) and item.is_integer():
            dep = int(item)
        elif isinstance(item, str):
            try:
                dep = int(item.strip(), 10)
            except Exception:
                continue
        else:
            continue
        if 0 <= dep < step_idx and dep not in out:
            out.append(dep)
    return out


def _salvage_plan_from_normalized(
    normalized: dict[str, Any] | Any,
    *,
    scoped_tool_names: set[str],
) -> AgentPlanOutput | None:
    if not isinstance(normalized, dict):
        return None
    raw_steps = normalized.get("steps")
    if not isinstance(raw_steps, list):
        return None

    salvaged_steps: list[AgentPlanStep] = []
    for idx, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            continue
        tool_name = raw_step.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            continue
        tool_name = tool_name.strip()
        if scoped_tool_names and tool_name not in scoped_tool_names:
            continue
        args = raw_step.get("args") if isinstance(raw_step.get("args"), dict) else {}
        evidence = raw_step.get("evidence") if isinstance(raw_step.get("evidence"), dict) else {}
        missing_required = raw_step.get("missing_required")
        if isinstance(missing_required, list):
            missing_required = [str(item) for item in missing_required if isinstance(item, str)]
        else:
            missing_required = []
        step = AgentPlanStep(
            tool_name=tool_name,
            args=args,
            evidence=evidence,
            confidence=_coerce_confidence(raw_step.get("confidence")),
            missing_required=missing_required,
            depends_on=_coerce_depends_on(raw_step.get("depends_on"), step_idx=idx),
            execution_mode="single",
            bindings=[],
        )
        salvaged_steps.append(step)

    if not salvaged_steps:
        return None

    plan_explanation = normalized.get("plan_explanation")
    if not isinstance(plan_explanation, str) or not plan_explanation.strip():
        plan_explanation = "Execute the safest supported steps from planner output."
    risk_summary = normalized.get("risk_summary")
    if not isinstance(risk_summary, str) or not risk_summary.strip():
        risk_summary = "Planner output was partially malformed; unsupported fields were dropped."
    clarification = normalized.get("clarification")
    if isinstance(clarification, str):
        clarification = clarification.strip() or None
    else:
        clarification = None
    return AgentPlanOutput(
        plan_explanation=plan_explanation,
        risk_summary=risk_summary,
        steps=salvaged_steps,
        clarification=clarification,
    )


def make_reason_node(settings: Settings):
    async def reason_node(state: AgentState) -> AgentState:
        if not (settings.planner_openai_base_url or settings.openai_api_key):
            raise LangGraphPlannerError(
                "LangGraph planner requires PLANNER_OPENAI_BASE_URL (or OPENAI_BASE_URL) or OPENAI_API_KEY."
            )

        intent = user_query_text(state)
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
            repaired = _deterministic_plan_repair(
                intent,
                state.get("scoped_tools") or [],
                context=state.get("context") or {},
            )
            if repaired is not None:
                log_event(
                    "langgraph_planner_deterministic_repair",
                    level="WARNING",
                    intent=intent,
                    reason="invalid_json",
                    tool_names=[step.tool_name for step in repaired.steps],
                )
                return {"plan_blueprint": repaired, "risk_summary": repaired.risk_summary, "status": "planning"}
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
            repaired = _deterministic_plan_repair(
                intent,
                state.get("scoped_tools") or [],
                context=state.get("context") or {},
            )
            if repaired is not None:
                log_event(
                    "langgraph_planner_deterministic_repair",
                    level="WARNING",
                    intent=intent,
                    reason="invalid_schema",
                    tool_names=[step.tool_name for step in repaired.steps],
                )
                return {"plan_blueprint": repaired, "risk_summary": repaired.risk_summary, "status": "planning"}
            salvaged = _salvage_plan_from_normalized(
                normalized,
                scoped_tool_names={tool.name for tool in (state.get("scoped_tools") or []) if getattr(tool, "name", None)},
            )
            if salvaged is not None:
                log_event(
                    "langgraph_planner_schema_salvage",
                    level="WARNING",
                    intent=intent,
                    step_count=len(salvaged.steps),
                    tool_names=[step.tool_name for step in salvaged.steps],
                )
                return {"plan_blueprint": salvaged, "risk_summary": salvaged.risk_summary, "status": "planning"}
            raise LangGraphPlannerError("LangGraph planner returned JSON that does not match AgentPlanOutput.") from exc
        return {"plan_blueprint": plan, "risk_summary": plan.risk_summary, "status": "planning"}

    return reason_node
