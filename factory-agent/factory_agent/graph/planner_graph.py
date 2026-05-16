from __future__ import annotations

from typing import Any

from ..config import Settings
from ..schemas import PlanDraft, PlanStepDraft, ToolInfo
from .approval_summary import build_approval_required_payload
from .builder import compile_planner_graph
from .errors import LangGraphPlannerApprovalRequired, LangGraphPlannerClarification, LangGraphPlannerError
from .state import AgentState, normalize_graph_messages, user_query_text

try:
    from langgraph.types import Command
except Exception:  # pragma: no cover
    Command = None  # type: ignore[assignment]


def _interrupt_payload_from_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    interrupts = result.get("__interrupt__")
    if isinstance(interrupts, list) and interrupts:
        payload = getattr(interrupts[0], "value", None)
        return payload if isinstance(payload, dict) else {"kind": "approval_required"}
    return None


def _interrupt_payload_from_snapshot(snapshot: Any) -> dict[str, Any] | None:
    tasks = getattr(snapshot, "tasks", ()) or ()
    for task in tasks:
        for item in getattr(task, "interrupts", ()) or ():
            payload = getattr(item, "value", None)
            return payload if isinstance(payload, dict) else {"kind": "approval_required"}
    return None


def _approval_payload_from_state(state: Any) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    staged = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]
    if not staged:
        return None
    dry = state.get("bundle_dry_run_result")
    if not isinstance(dry, dict) or dry.get("ok") is not True:
        return None
    intent_text = ""
    cur = state.get("current_intent")
    if isinstance(cur, dict):
        intent_text = str(cur.get("description") or "").strip()
    if not intent_text:
        intent_text = user_query_text(state)
    return build_approval_required_payload(staged, intent_text=intent_text)


def _not_found_clarification_from_state(state: Any) -> str | None:
    if not isinstance(state, dict):
        return None
    staged = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]
    if not staged:
        return None
    dry = state.get("bundle_dry_run_result")
    if not isinstance(dry, dict) or dry.get("ok") is not False:
        return None
    body = dry.get("body") if isinstance(dry.get("body"), dict) else {}
    detail = body.get("error") or body.get("detail") or body.get("message") or dry.get("error")
    text = str(detail or "")
    if "not found" in text.lower() or "does not exist" in text.lower():
        return text or "Requested resource was not found."
    return None


def _snapshot_values(snapshot: Any) -> dict[str, Any] | None:
    values = getattr(snapshot, "values", None)
    return values if isinstance(values, dict) else None


def _append_create_followup_read(
    draft: PlanDraft,
    contract: dict[str, Any],
    state: dict[str, Any] | None,
) -> tuple[PlanDraft, dict[str, Any]]:
    if not isinstance(state, dict):
        return draft, contract
    query = str(state.get("original_query") or state.get("intent") or "").lower()
    if not (("show it" in query) or ("then show" in query) or ("show the" in query)):
        return draft, contract
    scoped = state.get("scoped_tools") or []
    if not any(getattr(tool, "name", None) == "get__jobs_{id}" for tool in scoped):
        return draft, contract
    staged = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]
    if not any(x.get("tool_name") == "post__jobs" for x in staged):
        return draft, contract
    if any(step.tool_name == "get__jobs_{id}" for step in draft.steps):
        return draft, contract

    steps = list(draft.steps)
    idx = len(steps)
    steps.append(
        PlanStepDraft(
            step_index=idx,
            tool_name="get__jobs_{id}",
            args={"id": "$ref:post__jobs_0"},
            depends_on=[idx - 1] if idx > 0 else [],
        )
    )
    updated_draft = draft.model_copy(update={"steps": steps})
    updated_contract = dict(contract or {})
    contract_steps = list(updated_contract.get("steps") or [])
    contract_steps.append(
        {
            "step_index": idx,
            "tool_name": "get__jobs_{id}",
            "args": {"id": "$ref:post__jobs_0"},
            "evidence": {"id": "created job"},
            "confidence": 0.8,
            "missing_required": [],
            "bindings": [],
            "execution_mode": "single",
            "derived_from": "create_followup_read",
        }
    )
    updated_contract["steps"] = contract_steps
    return updated_draft, updated_contract


def _initial_planner_state(
    *,
    intent: str,
    scoped_tools: list[ToolInfo],
    context: dict[str, Any] | None,
) -> AgentState:
    ctx = context or {}
    return {
        "session_id": str(ctx.get("session_id") or "") or None,
        "original_query": intent,
        "intent": intent,
        "messages": normalize_graph_messages(ctx.get("messages")),
        "context": ctx,
        "scoped_tools": scoped_tools,
        "retrieved_info": {},
        "decisions": [],
        "approval_requests": [],
        "validation_results": [],
        "intents": [],
        "working_intents": [],
        "intent_cursor": 0,
        "pending_decision": None,
        "planner_iteration": 0,
        "tool_outputs": [],
        "completed_actions": [],
        "staged_writes": [],
        "failed_strategies": [],
        "errors": [],
        "status": "init",
        "next_route": None,
        "write_generation": 0,
        "pending_relevance_batch": None,
        "fatal_system_error": None,
        "bundle_dry_run_result": None,
        "last_commit_result": None,
        "idempotency_audit": [],
        "repair_attempts": 0,
        "tool_outputs_truncated_at": 0,
    }


class LangGraphPlanner:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def _resume_from_staged_checkpoint(
        self,
        *,
        graph: Any,
        config: dict[str, Any],
        approved: bool,
    ) -> tuple[PlanDraft, dict[str, Any], list[dict[str, Any]]] | None:
        try:
            snapshot = await graph.aget_state(config)
        except Exception:
            return None
        values = _snapshot_values(snapshot)
        if not isinstance(values, dict):
            return None
        staged = [x for x in (values.get("staged_writes") or []) if isinstance(x, dict)]
        if not staged:
            return None

        raw_outputs = values.get("tool_outputs")
        tool_outputs = raw_outputs if isinstance(raw_outputs, list) else []
        if not approved:
            return (
                PlanDraft(
                    plan_explanation="Approval was rejected; no writes were committed.",
                    risk_summary="Operator rejected the staged write bundle.",
                    steps=[],
                ),
                values.get("intent_contract") or {
                    "intent": str(values.get("intent") or values.get("original_query") or ""),
                    "backend": "langgraph",
                    "steps": [],
                },
                tool_outputs,
            )

        from .nodes.tool_pipeline import commit_node_impl
        from .nodes.validate import _commit_tool_outputs_from_state, make_validate_node

        validated = make_validate_node(self._settings)(values)
        draft = validated.get("validated_plan")
        if not isinstance(draft, PlanDraft):
            return None
        intent_text = ""
        cur = values.get("current_intent")
        if isinstance(cur, dict):
            intent_text = str(cur.get("description") or "").strip()
        if not intent_text:
            intent_text = user_query_text(values)
        payload = _approval_payload_from_state(values) or build_approval_required_payload(
            staged, intent_text=intent_text
        )
        commit_state = {
            **values,
            **validated,
            "approval_requests": [{"status": "approved", **payload}],
            "validation_results": validated.get("validation_results") or [{"ok": True, "phase": "manual_resume"}],
        }
        commit = await commit_node_impl(commit_state, settings=self._settings)
        last_commit = commit.get("last_commit_result") if isinstance(commit, dict) else None
        if isinstance(last_commit, dict) and last_commit.get("ok") is False:
            raise LangGraphPlannerError(str(last_commit.get("error") or last_commit.get("body") or "commit failed"))
        commit_outputs = _commit_tool_outputs_from_state({**commit_state, **(commit if isinstance(commit, dict) else {})})
        contract = validated.get("intent_contract") or values.get("intent_contract") or {
                "intent": str(values.get("intent") or values.get("original_query") or ""),
                "backend": "langgraph",
                "steps": [],
            }
        draft, contract = _append_create_followup_read(draft, contract, values)
        return (draft, contract, [*tool_outputs, *commit_outputs])

    async def generate(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
    ) -> tuple[PlanDraft, dict[str, Any], list[dict[str, Any]]]:
        graph = compile_planner_graph(self._settings)
        state: AgentState = _initial_planner_state(intent=intent, scoped_tools=scoped_tools, context=context)
        thread_id = str(state.get("session_id") or "langgraph-local-thread")
        config = {"recursion_limit": 200, "configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(
            state,
            config=config,
        )
        payload = _interrupt_payload_from_result(result)
        snapshot_values: dict[str, Any] | None = None
        if payload is None:
            try:
                snapshot = await graph.aget_state(config)
                payload = _interrupt_payload_from_snapshot(snapshot)
                snapshot_values = _snapshot_values(snapshot)
            except Exception:
                payload = None
        state_for_fallback = snapshot_values if snapshot_values is not None else result
        if payload is None:
            payload = _approval_payload_from_state(state_for_fallback)
        if payload is not None:
            raise LangGraphPlannerApprovalRequired(payload)
        clarification = _not_found_clarification_from_state(state_for_fallback)
        if clarification:
            raise LangGraphPlannerClarification(clarification)
        clarification = result.get("clarification")
        if clarification:
            raise LangGraphPlannerClarification(str(clarification))
        draft = result.get("validated_plan")
        if not isinstance(draft, PlanDraft):
            raise LangGraphPlannerError("LangGraph planner did not return a validated PlanDraft.")
        raw_outputs = result.get("tool_outputs")
        tool_outputs = raw_outputs if isinstance(raw_outputs, list) else []
        return draft, result.get("intent_contract") or {
            "intent": intent,
            "backend": "langgraph",
            "steps": [],
        }, tool_outputs

    async def resume_after_approval(
        self,
        *,
        session_id: str,
        approved: bool,
    ) -> tuple[PlanDraft, dict[str, Any], list[dict[str, Any]]]:
        graph = compile_planner_graph(self._settings)
        if Command is None:
            raise LangGraphPlannerError("LangGraph Command resume is unavailable in this runtime.")
        config = {"recursion_limit": 200, "configurable": {"thread_id": session_id}}
        try:
            # LangGraph START maps Command.update through state keys; resume-only Command yields no
            # tuples from Command._update_as_tuples(), which triggers InvalidUpdateError
            # ("Must write to at least one of [...]"). Include a harmless state tick on session_id.
            result = await graph.ainvoke(
                Command(
                    resume={"approved": approved},
                    update={"session_id": str(session_id)},
                ),
                config=config,
            )
        except Exception:
            fallback = await self._resume_from_staged_checkpoint(graph=graph, config=config, approved=approved)
            if fallback is not None:
                return fallback
            raise
        payload = _interrupt_payload_from_result(result)
        if payload is None:
            try:
                payload = _interrupt_payload_from_snapshot(await graph.aget_state(config))
            except Exception:
                payload = None
        if payload is not None:
            raise LangGraphPlannerApprovalRequired(payload)
        clarification = result.get("clarification")
        if clarification:
            raise LangGraphPlannerClarification(str(clarification))
        draft = result.get("validated_plan")
        if not approved and not isinstance(draft, PlanDraft):
            draft = PlanDraft(
                plan_explanation="Approval was rejected; no writes were committed.",
                risk_summary="Operator rejected the staged write bundle.",
                steps=[],
            )
        if not isinstance(draft, PlanDraft):
            raise LangGraphPlannerError("LangGraph planner did not return a validated PlanDraft on resume.")
        try:
            snapshot_values = _snapshot_values(await graph.aget_state(config))
        except Exception:
            snapshot_values = None
        contract = result.get("intent_contract") or {
            "intent": "",
            "backend": "langgraph",
            "steps": [],
        }
        draft, contract = _append_create_followup_read(draft, contract, snapshot_values)
        raw_outputs = result.get("tool_outputs")
        tool_outputs = raw_outputs if isinstance(raw_outputs, list) else []
        return draft, contract, tool_outputs
