"""Test-only planner that mimics LangGraphPlanner output without LLM or langgraph imports."""

from __future__ import annotations

import re
from typing import Any

from factory_agent.config import Settings
from factory_agent.graph.errors import LangGraphPlannerClarification, LangGraphPlannerError
from factory_agent.graph.nodes.validate import make_validate_node
from factory_agent.graph.planner_graph_helpers import (
    _TOKEN_ID_RE,
    _deterministic_plan_repair,
    _extract_entity_id,
    _extract_user_supported_path_args,
    _tool_cards,
)
from factory_agent.graph.state import AgentPlanOutput, AgentPlanStep, AgentState
from factory_agent.security.guardrails import missing_required_fields
from factory_agent.schemas import ToolInfo
from factory_agent.services.planner_service import PlannerConfirmationRequired, _split_compound_intent


class OfflineLangGraphPlanner:
    """Builds a raw plan from intent + scoped tools, then runs the real validate node."""

    def __init__(self, settings: Settings):
        self._settings = settings

    async def generate(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        tools_by_name = {t.name: t for t in scoped_tools}

        steps: list[AgentPlanStep] = []

        if re.search(r"\bfind\s+all\s+CNC\s+machine\b", intent, re.I):
            memory = (context or {}).get("intent_memory") if isinstance((context or {}).get("intent_memory"), dict) else {}
            bindings = memory.get("positive_bindings") if isinstance(memory.get("positive_bindings"), list) else []
            already_machine_type = any(
                isinstance(b, dict)
                and str(b.get("field") or "").strip().lower() == "machine_type"
                and str(b.get("value") or "").strip().upper() == "CNC"
                and str(b.get("source") or "").strip().lower() == "operator_confirmation"
                for b in bindings
            )
            if already_machine_type:
                tm = tools_by_name.get("get__machines")
                if tm:
                    steps = [
                        AgentPlanStep(
                            tool_name="get__machines",
                            args={"machine_type": "CNC"},
                            evidence={"machine_type": "CNC"},
                            confidence=0.95,
                        )
                    ]
            else:
                raise PlannerConfirmationRequired(
                    "Please confirm how CNC should be interpreted.",
                    confirmation={
                        "message": "Please confirm the intended filter.",
                        "entity": "machine",
                        "raw_term": "CNC",
                        "options": [
                            {"field": "machine_type", "label": "Machine type", "value": "CNC"},
                            {"field": "location", "label": "Location", "value": "CNC"},
                        ],
                    },
                )

        if not steps:
            match_unknown = re.search(r"\bfind\s+all\s+(\w+)\s+machine\b", intent, re.I)
            if match_unknown:
                term = match_unknown.group(1).lower()
                tm = tools_by_name.get("get__machines")
                if tm and isinstance(tm.input_schema, dict):
                    status_schema = (tm.input_schema.get("properties") or {}).get("status") or {}
                    enum_vals = [str(v).lower() for v in (status_schema.get("enum") or [])]
                    if enum_vals and term not in enum_vals:
                        raise LangGraphPlannerClarification(
                            f'I couldn\'t match "{term}" to any supported machine field or filter.'
                        )

            clauses = _split_compound_intent(intent)
            for clause in clauses:
                steps.extend(self._plan_clause(clause, scoped_tools, tools_by_name))

        if not steps:
            raise LangGraphPlannerClarification("I could not map that request to a safe factory tool plan.")

        raw = AgentPlanOutput(
            plan_explanation=f"Offline planner for: {intent}",
            risk_summary="Deterministic offline test planner with normal validation.",
            steps=steps,
        )
        state: AgentState = {
            "session_id": str((context or {}).get("session_id") or "") or None,
            "intent": intent,
            "messages": list((context or {}).get("messages") or []),
            "context": context or {},
            "scoped_tools": scoped_tools,
            "tool_cards": _tool_cards(scoped_tools),
            "pending_tool_call": None,
            "approved_args": {},
            "tool_results": [],
            "errors": [],
            "raw_plan": raw,
        }
        validated = make_validate_node(self._settings)(state)
        clarification = validated.get("clarification")
        if clarification:
            raise LangGraphPlannerClarification(str(clarification))
        draft = validated.get("draft")
        if draft is None:
            raise LangGraphPlannerError("Offline planner validation returned no draft.")
        contract = validated.get("intent_contract") or {"intent": intent, "backend": "langgraph", "steps": []}
        return draft, contract

    def _plan_clause(
        self,
        clause: str,
        scoped_tools: list[ToolInfo],
        tools_by_name: dict[str, ToolInfo],
    ) -> list[AgentPlanStep]:
        lowered = clause.lower()

        # Product ID listing (matches legacy / structured selector expectations)
        if "get__products" in tools_by_name and re.search(
            r"\b(get\s+all\s+product|give\s+me\s+a\s+product\s+id|product\s+id)\b", lowered
        ):
            return [
                AgentPlanStep(
                    tool_name="get__products",
                    args={"fields": "product_id"},
                    evidence={"fields": "product id listing"},
                    confidence=0.9,
                )
            ]

        job_id = _extract_entity_id(clause, "job")
        if job_id and re.search(r"\bslots?\b", lowered):
            slots_tool = next(
                (
                    t
                    for t in scoped_tools
                    if t.method == "GET" and "{id}" in (t.endpoint or "") and "slots" in (t.endpoint or "").lower()
                ),
                None,
            )
            if slots_tool:
                return [
                    AgentPlanStep(
                        tool_name=slots_tool.name,
                        args={"id": job_id},
                        evidence={"id": job_id},
                        confidence=0.92,
                    )
                ]

        if re.search(r"\bcreate\b", lowered):
            posts = [t for t in scoped_tools if t.method == "POST"]
            posts.sort(key=lambda t: len(t.endpoint or ""))
            for tool in posts:
                tags = " ".join(tool.capability_tags or []).lower()
                if "machine" in lowered and "machine" in tags:
                    args, evidence = _extract_user_supported_path_args(intent=clause, tool=tool, existing_args={})
                    miss = sorted(set(missing_required_fields(tool, args)))
                    return [
                        AgentPlanStep(
                            tool_name=tool.name,
                            args=args,
                            evidence=evidence,
                            confidence=0.88,
                            missing_required=miss,
                        )
                    ]

        if re.search(r"\b(?:check|show|inspect|view)\s+(?:the\s+)?machine\b", lowered):
            has_machine_id = bool(
                _TOKEN_ID_RE.search(clause)
                or re.search(r"\bmachine\s+\d+\b", lowered)
                or re.search(r"\bmachine\s+[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", clause)
            )
            if not has_machine_id:
                raise LangGraphPlannerClarification("Need id")

        candidates = sorted(
            scoped_tools,
            key=lambda t: (
                0 if t.method == "GET" else 1,
                -sum(1 for seg in (t.endpoint or "").split("/") if "{" in seg),
            ),
        )
        for tool in candidates:
            args, evidence = _extract_user_supported_path_args(intent=clause, tool=tool, existing_args={})
            miss = sorted(set(missing_required_fields(tool, args)))
            if not miss:
                return [
                    AgentPlanStep(
                        tool_name=tool.name,
                        args=args,
                        evidence=evidence,
                        confidence=0.85,
                    )
                ]
            if tool.requires_approval and tool.method != "GET":
                return [
                    AgentPlanStep(
                        tool_name=tool.name,
                        args=args,
                        evidence=evidence,
                        confidence=0.82,
                        missing_required=miss,
                    )
                ]

        repaired = _deterministic_plan_repair(clause, scoped_tools)
        if repaired is not None:
            return list(repaired.steps)

        return []

