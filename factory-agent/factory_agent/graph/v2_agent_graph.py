from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langgraph.graph import END, StateGraph
from pydantic import Field

from ..config import Settings, get_settings
from ..planning.v2_agent_state import (
    GraphToolCall,
    PlannerDecisionRecord,
    PlannerOwnedAgentGraphState,
    ResponseDocumentContext,
    build_initial_planner_owned_agent_graph_state,
    validate_graph_state_final_state,
)
from ..planning.v2_capability_map import build_capability_needs_for_text
from ..planning.v2_contracts import (
    CandidateToolWindow,
    EvidenceCitation,
    EvidenceLedgerEntry,
    HydratedToolCard,
    HydratedToolCards,
    ToolRetrievalTrace,
    V2ContractModel,
)
from ..planning.v2_planner_decisions import record_planner_decision, validate_planner_decision
from ..planning.v2_rag_tool import ensure_v2_rag_tool
from ..planning.v2_satisfaction import apply_deterministic_evidence_satisfaction
from ..planning.v2_tool_retriever import V2CapabilityToolRetriever
from ..planning.tool_selector import ToolSelector
from ..schemas import ToolInfo
from .checkpointing import build_graph_checkpointer


PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER: tuple[str, ...] = (
    "semantic_intake_node",
    "requirement_ledger_node",
    "planner_decision_node",
    "tool_retrieval_node",
    "planner_choose_tool_node",
    "tool_execution_node",
    "evidence_observation_node",
    "satisfaction_node",
    "approval_node",
    "finalize_node",
    "response_document_node",
)

_PENDING_EXECUTION_DIAGNOSTIC_KEY = "phase4_pending_tool_execution"
_CHECKPOINTER_UNSET = object()


class PlannerOwnedAgentGraphRunOptions(V2ContractModel):
    thread_id: str | None = None
    configurable: dict[str, Any] = Field(default_factory=dict)


class PlannerOwnedGraphResult(V2ContractModel):
    state: PlannerOwnedAgentGraphState
    node_order: list[str] = Field(default_factory=list)
    checkpoint_config: dict[str, Any] = Field(default_factory=dict)
    trace_events: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(frozen=True)
class PlannerOwnedGraphRetrieval:
    candidate_window: CandidateToolWindow
    hydrated_tool_cards: HydratedToolCards
    trace: ToolRetrievalTrace


@dataclass(frozen=True)
class PlannerOwnedGraphExecution:
    tool_call: GraphToolCall
    normalized_result: dict[str, Any]
    result_ref: str
    citations: list[EvidenceCitation] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class LocalPlannerOwnedGraphTracer:
    events: list[dict[str, Any]] = field(default_factory=list)

    def record_node(self, node_name: str, state: PlannerOwnedAgentGraphState) -> None:
        self.events.append(
            {
                "event": "planner_owned_agent_graph_node",
                "node": node_name,
                "ledger_revision": state.requirement_ledger.revision,
                "planner_decision_count": len(state.planner_decisions),
                "evidence_count": len(state.evidence_ledger.evidence),
            }
        )


class PlannerOwnedAgentGraphAdapters:
    """Phase 4 graph adapters.

    Retrieval uses the existing v2 capability retriever, which wraps the
    existing ToolSelector. Execution remains an explicit non-product placeholder
    until the graph execution/evidence phase.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        tools_by_name: Mapping[str, ToolInfo] | None = None,
        tool_selector: ToolSelector | None = None,
        tool_retriever: V2CapabilityToolRetriever | None = None,
        retrieval_mode: str = "normal",
    ) -> None:
        self._settings = settings or get_settings()
        self.tools_by_name = ensure_v2_rag_tool(dict(tools_by_name or {}))
        self._tool_selector = tool_selector or ToolSelector(self._settings)
        self._tool_retriever = tool_retriever or V2CapabilityToolRetriever(self._tool_selector)
        self._retrieval_mode = retrieval_mode

    @property
    def tool_retriever(self) -> V2CapabilityToolRetriever:
        return self._tool_retriever

    async def retrieve_tools(
        self,
        state: PlannerOwnedAgentGraphState,
        decision: PlannerDecisionRecord,
    ) -> PlannerOwnedGraphRetrieval:
        capability_need = decision.capability_need
        if capability_need is None:
            raise ValueError("retrieve_tools transition requires a capability need")
        requirement_id = decision.requirement_id or capability_need.requirement_id
        if not requirement_id:
            raise ValueError("retrieve_tools transition requires a requirement id")

        result = await self._tool_retriever.retrieve_tools_for_need(
            capability_need,
            tools_by_name=self.tools_by_name,
            requirement_id=requirement_id,
            requirement_refs={
                "ledger_revision": state.requirement_ledger.revision,
                "open_requirement_ids": [
                    requirement.id
                    for requirement in state.requirement_ledger.requirements
                    if requirement.status == "open"
                ],
            },
            context_refs={
                "original_user_query": state.original_query,
                "graph_phase": "phase4_retrieval_and_tool_choice",
            },
            mode=self._retrieval_mode,
        )
        trace = result.trace.model_copy(deep=True)
        trace.diagnostics.update(
            {
                "graph_phase": "phase4_retrieval_and_tool_choice",
                "tool_selector_adapter": "V2CapabilityToolRetriever",
                "hydrated_cards_from_retriever_result": True,
                "real_product_execution": False,
            }
        )
        return PlannerOwnedGraphRetrieval(
            candidate_window=result.candidate_window,
            hydrated_tool_cards=result.hydrated_tool_cards,
            trace=trace,
        )

    async def choose_tool(
        self,
        state: PlannerOwnedAgentGraphState,
        decision: PlannerDecisionRecord,
    ) -> GraphToolCall:
        requirement_id = decision.requirement_id
        if requirement_id is None:
            raise ValueError("choose_tool transition requires a requirement id")
        requirement = _requirement_by_id(state, requirement_id)
        cards = _hydrated_cards_for_requirement(state, requirement_id)
        if requirement is None or not cards:
            raise ValueError("choose_tool transition requires hydrated cards")
        card = cards[0]
        capability_need = decision.capability_need or _capability_need_for_requirement(state, requirement_id)
        args = _args_for_tool_call(card, requirement, capability_need)
        return GraphToolCall(
            call_id=f"call-{len(state.planner_decisions) + 1:03d}",
            kind="rag_tool" if card.source_of_truth == "document_knowledge" else "api_tool",
            tool_name=card.tool_name,
            args=args,
            requirement_id=requirement_id,
            candidate_window_id=_candidate_window_id_for_requirement(state, requirement_id),
        )

    async def execute_tool(
        self,
        state: PlannerOwnedAgentGraphState,
        decision: PlannerDecisionRecord,
    ) -> PlannerOwnedGraphExecution:
        call = decision.selected_tool_call
        if call is None:
            raise ValueError("execute_tool transition requires a selected tool call")
        requirement = _requirement_by_id(state, call.requirement_id)
        if requirement is None:
            raise ValueError("execute_tool transition targets a missing requirement")
        normalized_result = _fake_normalized_result_for_requirement(requirement, call)
        citations = [
            EvidenceCitation(source_id="phase4-placeholder-rag", title="Phase 4 placeholder citation")
        ] if call.kind == "rag_tool" else []
        return PlannerOwnedGraphExecution(
            tool_call=call,
            normalized_result=normalized_result,
            result_ref=f"phase4-placeholder-result-{len(state.evidence_ledger.evidence) + 1:03d}",
            citations=citations,
            diagnostics={
                "phase": "phase4_retrieval_and_tool_choice",
                "real_product_execution": False,
                "execution_policy": "placeholder_only_until_phase5",
            },
        )


class PlannerOwnedAgentGraph:
    """Small public shell for the future planner-owned LangGraph runtime."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        adapters: PlannerOwnedAgentGraphAdapters | None = None,
        checkpointer: Any = _CHECKPOINTER_UNSET,
        tracer: LocalPlannerOwnedGraphTracer | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._adapters = adapters or PlannerOwnedAgentGraphAdapters(settings=self._settings)
        self._tracer = tracer or LocalPlannerOwnedGraphTracer()
        self._checkpointer = (
            build_graph_checkpointer(self._settings)
            if checkpointer is _CHECKPOINTER_UNSET
            else checkpointer
        )
        self._compiled_graph = self._compile_graph()

    @property
    def compiled_graph(self) -> Any:
        return self._compiled_graph

    @property
    def checkpointer(self) -> Any:
        return self._checkpointer

    async def run(
        self,
        user_message: str,
        *,
        session_context: Mapping[str, Any] | Any | None = None,
        options: PlannerOwnedAgentGraphRunOptions | Mapping[str, Any] | None = None,
    ) -> PlannerOwnedGraphResult:
        state = build_initial_planner_owned_agent_graph_state(
            user_message,
            tools_by_name=getattr(self._adapters, "tools_by_name", {}),
        )
        return await self.run_state(state, session_context=session_context, options=options)

    async def run_state(
        self,
        state: PlannerOwnedAgentGraphState,
        *,
        session_context: Mapping[str, Any] | Any | None = None,
        options: PlannerOwnedAgentGraphRunOptions | Mapping[str, Any] | None = None,
    ) -> PlannerOwnedGraphResult:
        normalized_options = _normalize_options(options)
        checkpoint_config = _checkpoint_config(normalized_options, session_context=session_context)
        event_start = len(self._tracer.events)
        raw_state = await self._compiled_graph.ainvoke(state, config=checkpoint_config)
        final_state = PlannerOwnedAgentGraphState.model_validate(raw_state)
        node_order = list(final_state.execution_trace.diagnostics.get("phase3_node_order") or [])
        return PlannerOwnedGraphResult(
            state=final_state,
            node_order=node_order,
            checkpoint_config=checkpoint_config,
            trace_events=list(self._tracer.events[event_start:]),
        )

    async def resume_from_approval(
        self,
        session_context: Mapping[str, Any] | Any,
        approval_decision: Mapping[str, Any],
        options: PlannerOwnedAgentGraphRunOptions | Mapping[str, Any] | None = None,
    ) -> PlannerOwnedGraphResult:
        raise NotImplementedError("approval resume is scheduled for a later planner-owned graph phase")

    async def interrupt_with_user_message(
        self,
        session_context: Mapping[str, Any] | Any,
        new_user_message: str,
        options: PlannerOwnedAgentGraphRunOptions | Mapping[str, Any] | None = None,
    ) -> PlannerOwnedGraphResult:
        raise NotImplementedError("graph interruption is scheduled for a later planner-owned graph phase")

    def _compile_graph(self) -> Any:
        graph = StateGraph(PlannerOwnedAgentGraphState)
        graph.add_node("semantic_intake_node", self._semantic_intake_node)
        graph.add_node("requirement_ledger_node", self._requirement_ledger_node)
        graph.add_node("planner_decision_node", self._planner_decision_node)
        graph.add_node("tool_retrieval_node", self._tool_retrieval_node)
        graph.add_node("planner_choose_tool_node", self._planner_choose_tool_node)
        graph.add_node("tool_execution_node", self._tool_execution_node)
        graph.add_node("evidence_observation_node", self._evidence_observation_node)
        graph.add_node("satisfaction_node", self._satisfaction_node)
        graph.add_node("approval_node", self._approval_node)
        graph.add_node("finalize_node", self._finalize_node)
        graph.add_node("response_document_node", self._response_document_node)

        graph.set_entry_point("semantic_intake_node")
        graph.add_edge("semantic_intake_node", "requirement_ledger_node")
        graph.add_edge("requirement_ledger_node", "planner_decision_node")
        graph.add_edge("planner_decision_node", "tool_retrieval_node")
        graph.add_edge("tool_retrieval_node", "planner_choose_tool_node")
        graph.add_edge("planner_choose_tool_node", "tool_execution_node")
        graph.add_edge("tool_execution_node", "evidence_observation_node")
        graph.add_edge("evidence_observation_node", "satisfaction_node")
        graph.add_edge("satisfaction_node", "approval_node")
        graph.add_edge("approval_node", "finalize_node")
        graph.add_edge("finalize_node", "response_document_node")
        graph.add_edge("response_document_node", END)
        if self._checkpointer is None:
            return graph.compile()
        return graph.compile(checkpointer=self._checkpointer)

    async def _semantic_intake_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "semantic_intake_node", self._tracer)
        state.execution_trace.planner.diagnostics["semantic_intake"] = {
            "original_query_present": bool(state.original_query.strip()),
            "phase": "phase4_retrieval_choice_shell",
        }
        return _state_update(state)

    async def _requirement_ledger_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "requirement_ledger_node", self._tracer)
        state.response_document_context = state.response_document_context.model_copy(
            update={
                "revision": state.requirement_ledger.revision,
                "requirement_ids": [requirement.id for requirement in state.requirement_ledger.requirements],
            }
        )
        state.execution_trace.planner.diagnostics["requirement_ledger_node"] = {
            "requirement_count": len(state.requirement_ledger.requirements),
            "ledger_revision": state.requirement_ledger.revision,
        }
        return _state_update(state)

    async def _planner_decision_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "planner_decision_node", self._tracer)
        requirement = _first_open_requirement_without_evidence(state)
        if requirement is None:
            state.execution_trace.planner.diagnostics["planner_decision_node"] = {"decision": "none"}
            return _state_update(state)
        need = _capability_need_for_requirement(state, requirement.id)
        decision = PlannerDecisionRecord(
            decision_id=f"dec-retrieve-{len(state.planner_decisions) + 1:03d}",
            decision_kind="retrieve_tools",
            requirement_id=requirement.id,
            ledger_revision=state.requirement_ledger.revision,
            capability_need=need,
            reason="Phase 4 graph requests a bounded retriever-backed candidate window.",
        )
        record_planner_decision(state, decision)
        state.execution_trace.planner.call_count += 1
        state.execution_trace.planner.diagnostics["planner_decision_node"] = {
            "decision_id": decision.decision_id,
            "decision_kind": decision.decision_kind,
        }
        return _state_update(state)

    async def _tool_retrieval_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "tool_retrieval_node", self._tracer)
        decision = _latest_decision(state, "retrieve_tools")
        if decision is None:
            state.execution_trace.tool_retrieval.diagnostics["phase4_retrieval"] = {"status": "no_decision"}
            return _state_update(state)
        validate_planner_decision(state, decision)
        retrieval = await _maybe_await(self._adapters.retrieve_tools(state, decision))
        if not any(window.requirement_id == retrieval.candidate_window.requirement_id for window in state.candidate_tool_windows):
            state.candidate_tool_windows.append(retrieval.candidate_window)
        if not any(cards.requirement_id == retrieval.hydrated_tool_cards.requirement_id for cards in state.hydrated_tool_cards):
            state.hydrated_tool_cards.append(retrieval.hydrated_tool_cards)
        state.execution_trace.tool_retrieval.call_count += retrieval.trace.call_count
        state.execution_trace.tool_retrieval.selected_candidate_tool_names = list(
            dict.fromkeys(
                [
                    *state.execution_trace.tool_retrieval.selected_candidate_tool_names,
                    *retrieval.trace.selected_candidate_tool_names,
                ]
            )
        )
        state.execution_trace.tool_retrieval.backend_used = retrieval.trace.backend_used
        state.execution_trace.tool_retrieval.diagnostics["phase4_retrieval"] = retrieval.trace.diagnostics
        return _state_update(state)

    async def _planner_choose_tool_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "planner_choose_tool_node", self._tracer)
        retrieve_decision = _latest_decision(state, "retrieve_tools")
        if retrieve_decision is None:
            state.execution_trace.planner.diagnostics["planner_choose_tool_node"] = {"decision": "none"}
            return _state_update(state)
        tool_call = await _maybe_await(self._adapters.choose_tool(state, retrieve_decision))
        decision = PlannerDecisionRecord(
            decision_id=f"dec-choose-{len(state.planner_decisions) + 1:03d}",
            decision_kind="choose_tool",
            requirement_id=tool_call.requirement_id,
            ledger_revision=state.requirement_ledger.revision,
            capability_need=retrieve_decision.capability_need,
            selected_tool_call=tool_call,
            reason="Phase 4 graph selects from the hydrated candidate window.",
        )
        tool_call.decision_id = decision.decision_id
        record_planner_decision(state, decision)
        state.execution_trace.planner.call_count += 1
        state.execution_trace.selected_tool_names = list(
            dict.fromkeys([*state.execution_trace.selected_tool_names, tool_call.tool_name])
        )
        state.execution_trace.planner.diagnostics["planner_choose_tool_node"] = {
            "decision_id": decision.decision_id,
            "tool_name": tool_call.tool_name,
        }
        return _state_update(state)

    async def _tool_execution_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "tool_execution_node", self._tracer)
        choose_decision = _latest_decision(state, "choose_tool")
        if choose_decision is None or choose_decision.selected_tool_call is None:
            state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY] = {"status": "no_tool_choice"}
            return _state_update(state)
        guard_decision = PlannerDecisionRecord(
            decision_id=f"dec-execute-{len(state.planner_decisions) + 1:03d}",
            decision_kind="execute_tool",
            author="deterministic_guard",
            requirement_id=choose_decision.requirement_id,
            ledger_revision=state.requirement_ledger.revision,
            capability_need=choose_decision.capability_need,
            selected_tool_call=choose_decision.selected_tool_call,
            reason="Execute the persisted planner-selected read action.",
        )
        record_planner_decision(state, guard_decision)
        execution = await _maybe_await(self._adapters.execute_tool(state, guard_decision))
        state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY] = {
            "status": "observed_by_next_node",
            "tool_call": execution.tool_call.model_dump(mode="json"),
            "normalized_result": execution.normalized_result,
            "result_ref": execution.result_ref,
            "citations": [citation.model_dump(mode="json") for citation in execution.citations],
            "diagnostics": execution.diagnostics,
        }
        return _state_update(state)

    async def _evidence_observation_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "evidence_observation_node", self._tracer)
        pending = state.execution_trace.diagnostics.get(_PENDING_EXECUTION_DIAGNOSTIC_KEY)
        if not isinstance(pending, dict) or pending.get("status") != "observed_by_next_node":
            state.execution_trace.diagnostics["evidence_observation"] = {"status": "no_pending_execution"}
            return _state_update(state)
        tool_call = GraphToolCall.model_validate(pending["tool_call"])
        source_type = "rag_tool" if tool_call.kind == "rag_tool" else "api_tool"
        citations = [EvidenceCitation.model_validate(item) for item in pending.get("citations") or []]
        evidence = EvidenceLedgerEntry(
            id=f"ev-{len(state.evidence_ledger.evidence) + 1:03d}",
            requirement_id=tool_call.requirement_id,
            source_type=source_type,
            source_of_truth="document_knowledge" if tool_call.kind == "rag_tool" else "operational_state",
            tool_name=tool_call.tool_name,
            args=dict(tool_call.args),
            result_ref=str(pending.get("result_ref") or ""),
            normalized_result=dict(pending.get("normalized_result") or {}),
            citations=citations,
            satisfies=["phase4_placeholder_tool_result"],
            diagnostic_metadata=dict(pending.get("diagnostics") or {}),
        )
        state.evidence_ledger.evidence.append(evidence)
        state.execution_trace.diagnostics["evidence_observation"] = {
            "status": "recorded",
            "evidence_ref": evidence.id,
        }
        state.execution_trace.diagnostics.pop(_PENDING_EXECUTION_DIAGNOSTIC_KEY, None)
        return _state_update(state)

    async def _satisfaction_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "satisfaction_node", self._tracer)
        loop_state = state.as_loop_compat_state()
        apply_deterministic_evidence_satisfaction(loop_state)
        state.requirement_ledger = loop_state.requirement_ledger or state.requirement_ledger
        state.satisfaction_state = loop_state.satisfaction_state
        state.revision_history = loop_state.revision_history
        state.execution_trace = loop_state.execution_trace
        validate_graph_state_final_state(state)
        return _state_update(state)

    async def _approval_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "approval_node", self._tracer)
        state.execution_trace.diagnostics["approval_node"] = {
            "status": state.pending_approval.status,
            "phase": "phase4_retrieval_choice_no_interrupt",
        }
        return _state_update(state)

    async def _finalize_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "finalize_node", self._tracer)
        if state.final_validation_result is not None and state.final_validation_result.status == "passed":
            decision = PlannerDecisionRecord(
                decision_id=f"dec-finalize-{len(state.planner_decisions) + 1:03d}",
                decision_kind="finalize",
                author="deterministic_guard",
                ledger_revision=state.requirement_ledger.revision,
                evidence_refs=[evidence.id for evidence in state.evidence_ledger.evidence],
                reason="All active requirements have typed evidence and passed final validation.",
            )
            record_planner_decision(state, decision)
            state.execution_trace.planner.diagnostics["finalize_node"] = {
                "decision_id": decision.decision_id,
                "decision_kind": decision.decision_kind,
            }
            return _state_update(state)

        reason = "Final validation did not pass."
        decision = PlannerDecisionRecord(
            decision_id=f"dec-fail-{len(state.planner_decisions) + 1:03d}",
            decision_kind="fail",
            author="deterministic_guard",
            ledger_revision=state.requirement_ledger.revision,
            reason=reason,
        )
        record_planner_decision(state, decision)
        state.execution_trace.planner.diagnostics["finalize_node"] = {
            "decision_id": decision.decision_id,
            "decision_kind": decision.decision_kind,
        }
        return _state_update(state)

    async def _response_document_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "response_document_node", self._tracer)
        validation_status = state.final_validation_result.status if state.final_validation_result else "failed"
        state.response_document_context = ResponseDocumentContext(
            state="rendered" if validation_status == "passed" else "failed",
            document_id=f"phase4-response-{uuid4().hex[:12]}",
            revision=state.requirement_ledger.revision,
            requirement_ids=[requirement.id for requirement in state.requirement_ledger.requirements],
            evidence_refs=[evidence.id for evidence in state.evidence_ledger.evidence],
            pending_approval_id=state.pending_approval.approval_id,
            render_contract="phase4_retrieval_choice_response_document_context",
            diagnostics={
                "phase": "phase4_retrieval_and_tool_choice",
                "real_response_renderer_called": False,
                "final_validation_status": validation_status,
            },
        )
        return _state_update(state)


def _record_node_visit(
    state: PlannerOwnedAgentGraphState,
    node_name: str,
    tracer: LocalPlannerOwnedGraphTracer,
) -> None:
    order = list(state.execution_trace.diagnostics.get("phase3_node_order") or [])
    order.append(node_name)
    state.execution_trace.diagnostics["phase3_node_order"] = order
    state.execution_trace.diagnostics["phase3_last_node"] = node_name
    tracer.record_node(node_name, state)


def _state_update(state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
    return state.model_dump(mode="python")


def _normalize_options(
    options: PlannerOwnedAgentGraphRunOptions | Mapping[str, Any] | None,
) -> PlannerOwnedAgentGraphRunOptions:
    if options is None:
        return PlannerOwnedAgentGraphRunOptions()
    if isinstance(options, PlannerOwnedAgentGraphRunOptions):
        return options
    return PlannerOwnedAgentGraphRunOptions.model_validate(dict(options))


def _checkpoint_config(
    options: PlannerOwnedAgentGraphRunOptions,
    *,
    session_context: Mapping[str, Any] | Any | None,
) -> dict[str, Any]:
    thread_id = options.thread_id or _session_context_value(session_context, "session_id")
    if not thread_id:
        thread_id = f"planner-owned-agent-graph-{uuid4().hex[:12]}"
    configurable = dict(options.configurable)
    configurable["thread_id"] = str(thread_id)
    configurable.setdefault("checkpoint_ns", "")
    return {"configurable": configurable}


def _session_context_value(session_context: Mapping[str, Any] | Any | None, key: str) -> Any:
    if session_context is None:
        return None
    if isinstance(session_context, Mapping):
        return session_context.get(key)
    return getattr(session_context, key, None)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _latest_decision(state: PlannerOwnedAgentGraphState, decision_kind: str) -> PlannerDecisionRecord | None:
    return next(
        (
            decision
            for decision in reversed(state.planner_decisions)
            if decision.decision_kind == decision_kind
        ),
        None,
    )


def _first_open_requirement_without_evidence(state: PlannerOwnedAgentGraphState):
    evidence_requirement_ids = {evidence.requirement_id for evidence in state.evidence_ledger.evidence}
    return next(
        (
            requirement
            for requirement in state.requirement_ledger.requirements
            if requirement.status == "open" and requirement.id not in evidence_requirement_ids
        ),
        None,
    )


def _capability_need_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str):
    needs = build_capability_needs_for_text(state.original_query, capability_map=state.capability_map)
    for need in needs:
        if need.requirement_id == requirement_id:
            return need
    requirement = _requirement_by_id(state, requirement_id)
    if requirement is None:
        raise ValueError(f"missing requirement for capability need: {requirement_id}")
    from ..planning.v2_contracts import CapabilityNeed

    return CapabilityNeed(
        requirement_id=requirement.id,
        source_of_truth=requirement.source_of_truth,
        entity=requirement.entity,
        action="search_documents" if requirement.source_of_truth == "document_knowledge" else "read",
        known_args={
            key: value
            for key, value in requirement.constraints.items()
            if key.endswith("_id") or key in {"id", "machine_ref"}
        },
        constraints=dict(requirement.constraints),
        requested_fields=list(requirement.requested_fields),
        reason="phase4_graph_requirement_fallback",
    )


def _requirement_by_id(state: PlannerOwnedAgentGraphState, requirement_id: str | None):
    if requirement_id is None:
        return None
    return next(
        (requirement for requirement in state.requirement_ledger.requirements if requirement.id == requirement_id),
        None,
    )


def _candidate_window_id_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> str | None:
    for index, window in enumerate(state.candidate_tool_windows, start=1):
        if window.requirement_id == requirement_id:
            return f"window-{index:03d}"
    return None


def _hydrated_cards_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> list[HydratedToolCard]:
    return [
        card
        for cards in state.hydrated_tool_cards
        if cards.requirement_id == requirement_id
        for card in cards.cards
    ]


def _args_for_tool_call(card: HydratedToolCard, requirement: Any, capability_need: Any) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for arg_name in dict.fromkeys([*card.required_args, *card.path_params]):
        value = _argument_value_for(arg_name, requirement, capability_need)
        if value not in (None, "", [], {}):
            args[arg_name] = value
    for key, value in requirement.constraints.items():
        if key in card.query_params or key in card.input_schema.get("properties", {}):
            args.setdefault(key, value)
    if card.supports_fields and requirement.requested_fields:
        args.setdefault("fields", ",".join(requirement.requested_fields))
    return args


def _argument_value_for(arg_name: str, requirement: Any, capability_need: Any) -> Any:
    constraints = dict(requirement.constraints)
    constraints.update(getattr(capability_need, "known_args", {}) or {})
    if arg_name in constraints:
        return constraints[arg_name]
    if arg_name == "id" and requirement.entity:
        return constraints.get(f"{requirement.entity}_id")
    if arg_name == "id":
        for key, value in constraints.items():
            if key.endswith("_id") or key in {"machine_ref"}:
                return value
    if arg_name == "query" and requirement.source_of_truth == "document_knowledge":
        return requirement.goal
    return None


def _fake_normalized_result_for_requirement(requirement: Any, tool_call: GraphToolCall) -> dict[str, Any]:
    if requirement.requirement_type == "filtered_collection":
        row = _fake_row_for_requirement(requirement)
        return {
            "entity": requirement.entity,
            "rows": [row],
            "applied_filters": {
                key: value
                for key, value in requirement.constraints.items()
                if key not in {"limit", "sort_by", "sort_dir"}
            },
            "status_code": 200,
            "phase4_placeholder_execution": True,
        }
    if requirement.source_of_truth == "document_knowledge":
        return {
            "answer": "Phase 4 document tool action placeholder.",
            "citations": [{"source_id": "phase4-placeholder-rag"}],
            "status_code": 200,
            "phase4_placeholder_execution": True,
        }
    entity_id = _entity_id_for_requirement(requirement, tool_call)
    fields = {
        field: f"phase4_{field}"
        for field in (requirement.requested_fields or ["status"])
    }
    return {
        "entity": requirement.entity,
        "entity_id": entity_id,
        "fields": fields,
        "status_code": 200,
        "phase4_placeholder_execution": True,
    }


def _fake_row_for_requirement(requirement: Any) -> dict[str, Any]:
    row: dict[str, Any] = {}
    if requirement.entity:
        row[f"{requirement.entity}_id"] = requirement.constraints.get(f"{requirement.entity}_id") or "phase4-placeholder-id"
    for field in requirement.requested_fields or ["status"]:
        row.setdefault(field, f"phase4_{field}")
    for key, value in requirement.constraints.items():
        if key not in {"limit", "sort_by", "sort_dir"}:
            row.setdefault(key, value)
    sort_by = requirement.constraints.get("sort_by")
    if sort_by:
        row.setdefault(str(sort_by), f"phase4_{sort_by}")
    return row


def _entity_id_for_requirement(requirement: Any, tool_call: GraphToolCall) -> Any:
    if requirement.entity:
        value = requirement.constraints.get(f"{requirement.entity}_id")
        if value not in (None, "", [], {}):
            return value
    for key in ("id", "machine_ref"):
        value = requirement.constraints.get(key)
        if value not in (None, "", [], {}):
            return value
    return tool_call.args.get("id")
