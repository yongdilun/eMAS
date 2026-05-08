from __future__ import annotations

from typing import Any

from ..config import Settings
from ..guardrails import (
    build_unsupported_enum_clarification,
    missing_required_fields,
    promote_user_provenance,
    sanitize_tool_args_against_schema,
    strip_unsupported_optional_args,
)
from ..plan_validator import validate_plan
from ..schemas import PlanBinding, PlanDraft, PlanStepDraft, ToolInfo
from ..telemetry import log_event, log_llm_prompt
from .planner_graph_helpers import (
    _tool_cards,
    _build_agent_prompt,
    _extract_quantity,
    _extract_prefixed_id,
    _generated_id_prefixes_by_entity,
    _generated_id_prefixes_by_field,
    _extract_entity_id,
    _schema_properties,
    _word_pattern,
    _has_word,
    _enum_value_in_intent,
    _collection_entity,
    _is_collection_read_tool,
    _infer_enum_collection_filter,
    _infer_enum_status_update,
    _candidate_id_prefixes_for_path_arg,
    _deterministic_plan_repair,
    _infer_clear_read_tool,
    _extract_json_obj,
    _coerce_non_negative_int,
    _normalize_plan_dict,
    _message_content_text,
    _reference_tool_preference,
    _find_get_tool_for_endpoint,
    _same_args,
    _singularize_entity,
    _endpoint_entity_before_param,
    _extract_user_supported_path_args,
    _insert_delete_preflights,
)
from .state import AgentPlanOutput, AgentState


class LangGraphPlannerError(RuntimeError):
    pass


class LangGraphPlannerClarification(LangGraphPlannerError):
    pass

class LangGraphPlanner:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _build_chat_model(self, *, json_mode: bool = False):
        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:
            raise LangGraphPlannerError("LangGraph planner requires langchain-openai.") from exc

        kwargs: dict[str, Any] = {
            "model": self._settings.planner_model,
            "temperature": 0,
            "timeout": self._settings.planner_timeout_s,
            "max_retries": 0,
            "max_tokens": max(self._settings.planner_max_tokens, 900),
        }
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        if self._settings.planner_openai_base_url:
            kwargs["base_url"] = self._settings.planner_openai_base_url
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    def _prepare_node(self, state: AgentState) -> AgentState:
        scoped_tools = state.get("scoped_tools") or []
        return {
            **state,
            "tool_cards": _tool_cards(scoped_tools),
            "errors": list(state.get("errors") or []),
            "tool_results": list(state.get("tool_results") or []),
        }

    async def _reason_node(self, state: AgentState) -> AgentState:
        if not (self._settings.planner_openai_base_url or self._settings.openai_api_key):
            raise LangGraphPlannerError("LangGraph planner requires PLANNER_OPENAI_BASE_URL (or OPENAI_BASE_URL) or OPENAI_API_KEY.")

        intent = state.get("intent") or ""
        context = state.get("context") or {}
        tool_cards = state.get("tool_cards") or []
        prompt = _build_agent_prompt(intent=intent, context=context, tool_cards=tool_cards)
        log_llm_prompt(
            component="planner",
            backend="langgraph",
            model=self._settings.planner_model,
            prompt=prompt,
            metadata={"intent": intent, "scoped_tool_count": len(tool_cards)},
        )
        model = self._build_chat_model(json_mode=True)
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
        normalized = _normalize_plan_dict(parsed)
        try:
            plan = AgentPlanOutput.model_validate(normalized)
        except Exception as exc:
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

    def _validate_node(self, state: AgentState) -> AgentState:
        raw_plan = state.get("raw_plan")
        if raw_plan is None:
            raise LangGraphPlannerError("LangGraph planner did not produce a plan.")
        if raw_plan.clarification:
            return {**state, "clarification": raw_plan.clarification, "draft": None}

        tools_by_name = {tool.name: tool for tool in state.get("scoped_tools") or []}
        repaired = _deterministic_plan_repair(state.get("intent") or "", state.get("scoped_tools") or [])
        repaired_tool_names = {step.tool_name for step in repaired.steps} if repaired is not None else set()
        raw_tool_names = {step.tool_name for step in raw_plan.steps or []}
        incomplete_repairable_plan = bool(repaired_tool_names and not repaired_tool_names <= raw_tool_names)
        if not raw_plan.steps or any(step.tool_name not in tools_by_name for step in raw_plan.steps) or incomplete_repairable_plan:
            if repaired is not None:
                log_event(
                    "langgraph_planner_deterministic_repair",
                    level="WARNING",
                    intent=state.get("intent"),
                    reason="empty_unsupported_or_incomplete_plan",
                    raw_step_count=len(raw_plan.steps or []),
                    raw_tool_names=[step.tool_name for step in raw_plan.steps or []],
                    tool_names=[step.tool_name for step in repaired.steps],
                )
                raw_plan = repaired
        context = state.get("context") or {}
        intent_memory = context.get("intent_memory") if isinstance(context.get("intent_memory"), dict) else {}
        step_drafts: list[PlanStepDraft] = []
        contract_steps: list[dict[str, Any]] = []

        for idx, raw_step in enumerate(raw_plan.steps[: self._settings.max_plan_steps]):
            tool = tools_by_name.get(raw_step.tool_name)
            if not tool:
                raise LangGraphPlannerClarification(f"I could not safely select a supported tool for step {idx + 1}.")
            preferred_tool = _reference_tool_preference(state.get("intent") or "", tool, tools_by_name)
            if preferred_tool.name != tool.name:
                log_event(
                    "langgraph_planner_tool_preference_applied",
                    level="INFO",
                    intent=state.get("intent"),
                    original_tool_name=tool.name,
                    preferred_tool_name=preferred_tool.name,
                    reason="reference_data_preference",
                )
                tool = preferred_tool

            raw_args = dict(raw_step.args or {})
            raw_evidence = dict(raw_step.evidence or {})
            supported_args, supported_evidence = _extract_user_supported_path_args(
                intent=state.get("intent") or "",
                tool=tool,
                existing_args=raw_args,
            )
            if supported_args:
                raw_args.update(supported_args)
                for field, proof in supported_evidence.items():
                    raw_evidence.setdefault(field, proof)

            sanitized_args, dropped_fields = sanitize_tool_args_against_schema(tool, raw_args)
            if dropped_fields:
                clarification = build_unsupported_enum_clarification(
                    tool=tool,
                    raw_args=raw_args,
                    sanitized_args=sanitized_args,
                    dropped_fields=dropped_fields,
                    intent=state.get("intent") or "",
                    clause=state.get("intent") or "",
                )
                if clarification:
                    raise LangGraphPlannerClarification(clarification)
                log_event(
                    "langgraph_planner_args_sanitized",
                    level="WARNING",
                    tool_name=tool.name,
                    dropped_fields=dropped_fields,
                    raw_args=raw_args,
                    intent=state.get("intent"),
                )

            missing = sorted(
                set(missing_required_fields(tool, sanitized_args))
                | {field for field in raw_step.missing_required if sanitized_args.get(field) in (None, "")}
            )
            if missing and not tool.requires_approval:
                raise LangGraphPlannerClarification(
                    f"Need {', '.join(missing)} before I can use `{tool.name}` for this request."
                )

            provenance = promote_user_provenance(
                tool=tool,
                args=sanitized_args,
                intent=state.get("intent") or "",
                evidence=raw_evidence,
            )
            clean_args, provenance_dropped = strip_unsupported_optional_args(
                tool=tool,
                args=sanitized_args,
                intent=state.get("intent") or "",
                intent_memory=intent_memory,
                arg_provenance=provenance,
            )

            bindings: list[PlanBinding] = []
            for binding in raw_step.bindings or []:
                bindings.append(binding)
            depends_on = [dep for dep in raw_step.depends_on if 0 <= dep < idx]
            for binding in bindings:
                if binding.from_step < idx:
                    depends_on.append(binding.from_step)
            execution_mode = raw_step.execution_mode if raw_step.execution_mode in {"single", "foreach"} else "single"
            if any(binding.mode == "foreach" for binding in bindings):
                execution_mode = "foreach"

            step_drafts.append(
                PlanStepDraft(
                    step_index=idx,
                    tool_name=tool.name,
                    args=clean_args,
                    depends_on=sorted(set(depends_on)) or ([idx - 1] if idx > 0 else []),
                    execution_mode=execution_mode,  # type: ignore[arg-type]
                    bindings=bindings,
                )
            )
            contract_steps.append(
                {
                    "step_index": idx,
                    "tool_name": tool.name,
                    "args": clean_args,
                    "evidence": raw_evidence,
                    "confidence": raw_step.confidence,
                    "missing_required": [] if tool.requires_approval else missing,
                    "provenance_dropped": provenance_dropped,
                    "arg_provenance": provenance,
                    "bindings": [binding.model_dump() for binding in bindings],
                    "execution_mode": execution_mode,
                }
            )

        if not step_drafts:
            log_event(
                "langgraph_planner_empty_plan",
                level="WARNING",
                intent=state.get("intent"),
                raw_step_count=len(raw_plan.steps or []),
                raw_tool_names=[s.tool_name for s in raw_plan.steps or [] if isinstance(getattr(s, "tool_name", None), str)],
                scoped_tool_count=len(tools_by_name),
            )
            raise LangGraphPlannerClarification("I could not map that request to a safe factory tool plan.")

        step_drafts, contract_steps, inserted_preflights = _insert_delete_preflights(
            steps=step_drafts,
            contract_steps=contract_steps,
            tools_by_name=tools_by_name,
        )
        if inserted_preflights:
            log_event(
                "langgraph_planner_delete_preflight_inserted",
                level="INFO",
                intent=state.get("intent"),
                inserted_steps=inserted_preflights,
            )

        draft = PlanDraft(
            plan_explanation=raw_plan.plan_explanation.strip() or f"Plan prepared for intent: {state.get('intent') or 'user request'}.",
            risk_summary=raw_plan.risk_summary.strip() or "Review the proposed tool calls before execution.",
            steps=step_drafts,
        )
        validation = validate_plan(draft, tools_by_name, max_steps=self._settings.max_plan_steps)
        if not validation.ok:
            raise LangGraphPlannerError("; ".join(validation.errors))
        return {
            **state,
            "draft": draft,
            "intent_contract": {
                "intent": state.get("intent") or "",
                "backend": "langgraph",
                "steps": contract_steps,
            },
            "final_response": draft.plan_explanation,
        }

    def _compile_graph(self):
        try:
            from langgraph.graph import END, StateGraph
        except Exception as exc:
            raise LangGraphPlannerError("langgraph is required for AGENT_RUNTIME=langgraph_agent.") from exc

        graph = StateGraph(AgentState)
        graph.add_node("prepare", self._prepare_node)
        graph.add_node("reason", self._reason_node)
        graph.add_node("validate", self._validate_node)
        graph.set_entry_point("prepare")
        graph.add_edge("prepare", "reason")
        graph.add_edge("reason", "validate")
        graph.add_edge("validate", END)
        return graph.compile()

    async def generate(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
    ) -> tuple[PlanDraft, dict[str, Any]]:
        graph = self._compile_graph()
        state: AgentState = {
            "session_id": str((context or {}).get("session_id") or "") or None,
            "intent": intent,
            "messages": list((context or {}).get("messages") or []),
            "context": context or {},
            "scoped_tools": scoped_tools,
            "pending_tool_call": None,
            "approved_args": {},
            "tool_results": [],
            "errors": [],
        }
        result = await graph.ainvoke(state)
        clarification = result.get("clarification")
        if clarification:
            raise LangGraphPlannerClarification(str(clarification))
        draft = result.get("draft")
        if not isinstance(draft, PlanDraft):
            raise LangGraphPlannerError("LangGraph planner did not return a validated PlanDraft.")
        return draft, result.get("intent_contract") or {"intent": intent, "backend": "langgraph", "steps": []}
