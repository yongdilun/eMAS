from __future__ import annotations

from typing import Any

from ..config import Settings
from ..schemas import PlanDraft, ToolInfo
from .builder import compile_planner_graph
from .errors import LangGraphPlannerApprovalRequired, LangGraphPlannerClarification, LangGraphPlannerError
from .state import AgentState, normalize_graph_messages

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

    async def generate(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
    ) -> tuple[PlanDraft, dict[str, Any]]:
        graph = compile_planner_graph(self._settings)
        state: AgentState = _initial_planner_state(intent=intent, scoped_tools=scoped_tools, context=context)
        thread_id = str(state.get("session_id") or "langgraph-local-thread")
        config = {"recursion_limit": 64, "configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(
            state,
            config=config,
        )
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
        if not isinstance(draft, PlanDraft):
            raise LangGraphPlannerError("LangGraph planner did not return a validated PlanDraft.")
        return draft, result.get("intent_contract") or {
            "intent": intent,
            "backend": "langgraph",
            "steps": [],
        }

    async def resume_after_approval(
        self,
        *,
        session_id: str,
        approved: bool,
    ) -> tuple[PlanDraft, dict[str, Any]]:
        graph = compile_planner_graph(self._settings)
        if Command is None:
            raise LangGraphPlannerError("LangGraph Command resume is unavailable in this runtime.")
        config = {"recursion_limit": 64, "configurable": {"thread_id": session_id}}
        result = await graph.ainvoke(
            Command(resume={"approved": approved}),
            config=config,
        )
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
        return draft, result.get("intent_contract") or {
            "intent": "",
            "backend": "langgraph",
            "steps": [],
        }
