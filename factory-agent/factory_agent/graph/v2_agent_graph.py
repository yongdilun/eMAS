from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langgraph.graph import END, StateGraph
from pydantic import Field

from ..rag.source_metadata import is_insufficient_context_answer
from ..config import Settings, get_settings
from ..planning.v2_agent_state import (
    GraphToolCall,
    PendingApprovalState,
    PlannerDecisionRecord,
    PlannerOwnedAgentGraphState,
    ResponseDocumentContext,
    build_initial_planner_owned_agent_graph_state,
    validate_graph_state_final_state,
)
from ..planning.v2_capability_map import build_capability_needs_for_text
from ..planning.v2_contracts import (
    CandidateToolWindow,
    EvidenceLedgerEntry,
    HydratedToolCard,
    HydratedToolCards,
    RequirementRevisionRecord,
    RequirementSatisfactionState,
    SatisfactionCheck,
    ToolRetrievalTrace,
    V2ContractModel,
)
from ..planning.v2_graph_adapters import (
    GraphToolExecutionResult,
    GraphToolHttpExecutor,
    execute_graph_tool_call,
    observe_graph_tool_result,
)
from ..planning.v2_planner_decisions import record_planner_decision, validate_planner_decision
from ..planning.v2_rag_tool import ensure_v2_rag_tool
from ..planning.v2_satisfaction import V2RepeatedRetrievalGuard, apply_deterministic_evidence_satisfaction
from ..planning.v2_tool_retriever import V2CapabilityToolRetriever
from ..planning.tool_selector import ToolSelector
from ..schemas import ToolInfo
from .approval_summary import build_approval_required_payload
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

_PENDING_EXECUTION_DIAGNOSTIC_KEY = "phase5_pending_tool_execution"
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
class PlannerOwnedGraphApprovalPreview:
    rows: list[dict[str, Any]]
    details: dict[str, Any] = field(default_factory=dict)
    excluded_rows: list[dict[str, Any]] = field(default_factory=list)
    commit_args: dict[str, Any] = field(default_factory=dict)
    no_records_message: str = "No matching records were found."


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
    """Graph adapters for retrieval, authorized execution, and evidence observation.

    Retrieval uses the existing v2 capability retriever, which wraps the
    existing ToolSelector. Execution is allowed only through persisted graph
    decisions and converts results into typed evidence before satisfaction.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        tools_by_name: Mapping[str, ToolInfo] | None = None,
        tool_selector: ToolSelector | None = None,
        tool_retriever: V2CapabilityToolRetriever | None = None,
        retrieval_mode: str = "normal",
        http_executor: GraphToolHttpExecutor | None = None,
        rag_pipeline: Any | None = None,
        approval_preview_provider: Any | None = None,
        approval_persister: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.tools_by_name = ensure_v2_rag_tool(dict(tools_by_name or {}))
        self._tool_selector = tool_selector or ToolSelector(self._settings)
        self._tool_retriever = tool_retriever or V2CapabilityToolRetriever(self._tool_selector)
        self._retrieval_mode = retrieval_mode
        self._http_executor = http_executor
        self._rag_pipeline = rag_pipeline
        self._approval_preview_provider = approval_preview_provider
        self._approval_persister = approval_persister

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
                "phase5_execution_adapter_ready": True,
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
    ) -> GraphToolExecutionResult:
        return await execute_graph_tool_call(
            settings=self._settings,
            state=state,
            decision=decision,
            tools_by_name=self.tools_by_name,
            http_executor=self._http_executor,
            rag_pipeline=self._rag_pipeline,
        )

    async def observe_tool_result(
        self,
        state: PlannerOwnedAgentGraphState,
        execution: GraphToolExecutionResult,
    ) -> EvidenceLedgerEntry:
        return observe_graph_tool_result(state, execution)

    async def build_approval_preview(
        self,
        state: PlannerOwnedAgentGraphState,
        tool_call: GraphToolCall,
        requirement: Any,
        card: HydratedToolCard,
    ) -> PlannerOwnedGraphApprovalPreview:
        if self._approval_preview_provider is not None:
            raw_preview = await _maybe_await(
                self._approval_preview_provider(
                    state=state,
                    tool_call=tool_call,
                    requirement=requirement,
                    card=card,
                )
            )
            return _normalize_approval_preview(raw_preview)
        return _default_approval_preview(tool_call=tool_call, requirement=requirement, card=card)

    async def persist_approval_request(
        self,
        state: PlannerOwnedAgentGraphState,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._approval_persister is None:
            return {"approval_id": f"graph-approval-{uuid4().hex[:12]}", "persisted": False}
        result = await _maybe_await(self._approval_persister(state=state, payload=payload))
        if isinstance(result, Mapping):
            return dict(result)
        return {"approval_id": str(result), "persisted": True}


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
        state.execution_trace.diagnostics["graph_checkpoint_identity"] = _graph_checkpoint_identity(
            checkpoint_config,
            ledger_revision=state.requirement_ledger.revision,
        )
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
        if self._checkpointer is None:
            raise ValueError("planner-owned graph approval resume requires a LangGraph checkpointer")

        normalized_options = _normalize_options(options)
        checkpoint_config = _checkpoint_config(normalized_options, session_context=session_context)
        event_start = len(self._tracer.events)
        state, checkpoint_tuple = await self._load_checkpoint_state(checkpoint_config)
        state.execution_trace.diagnostics["phase8_resume_checkpoint"] = {
            "native_langgraph_checkpoint_used": True,
            "session_replan_context_authoritative": False,
            "checkpoint_config": checkpoint_config,
            "loaded_checkpoint_id": _checkpoint_tuple_id(checkpoint_tuple),
        }

        _record_node_visit(state, "approval_node", self._tracer)
        pending = state.pending_approval
        if pending.status != "pending" or pending.tool_call is None:
            _record_graph_resume_no_pending_approval(state, approval_decision)
        elif not _approval_decision_matches_pending(approval_decision, pending):
            _record_graph_approval_decision_evidence(
                state,
                pending=pending,
                status="stale",
                reason="stale_approval_rejected",
                rejection_reason="Approval payload did not match the current graph checkpoint state.",
            )
        elif bool(approval_decision.get("approved", True)):
            await self._resume_approved_graph_approval(state, pending, approval_decision)
        else:
            _record_graph_approval_decision_evidence(
                state,
                pending=pending,
                status="rejected",
                reason="approval_rejected",
                rejection_reason=str(approval_decision.get("rejection_reason") or "Approval was rejected."),
            )

        if state.pending_approval.status == "none":
            await self._stage_next_write_approval_if_needed(state)

        await self._satisfaction_node(state)
        await self._approval_node(state)
        await self._finalize_node(state)
        await self._response_document_node(state)
        node_order = list(state.execution_trace.diagnostics.get("phase3_node_order") or [])
        return PlannerOwnedGraphResult(
            state=state,
            node_order=node_order,
            checkpoint_config=checkpoint_config,
            trace_events=list(self._tracer.events[event_start:]),
        )

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
            "phase": "phase5_execution_observation",
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
        requirements = [
            requirement
            for requirement in _open_requirements_without_evidence(state)
            if not _has_decision_for_requirement(state, "retrieve_tools", requirement.id)
        ]
        if not requirements:
            state.execution_trace.planner.diagnostics["planner_decision_node"] = {"decision": "none"}
            return _state_update(state)

        decisions: list[PlannerDecisionRecord] = []
        for requirement in requirements:
            need = _capability_need_for_requirement(state, requirement.id)
            decision = PlannerDecisionRecord(
                decision_id=f"dec-retrieve-{len(state.planner_decisions) + 1:03d}",
                decision_kind="retrieve_tools",
                requirement_id=requirement.id,
                ledger_revision=state.requirement_ledger.revision,
                capability_need=need,
                reason="Graph requests a bounded retriever-backed candidate window.",
            )
            record_planner_decision(state, decision)
            decisions.append(decision)

        state.execution_trace.planner.call_count += len(decisions)
        state.execution_trace.planner.diagnostics["planner_decision_node"] = {
            "decision_count": len(decisions),
            "decision_ids": [decision.decision_id for decision in decisions],
            "decision_kinds": [decision.decision_kind for decision in decisions],
            "requirement_ids": [decision.requirement_id for decision in decisions],
        }
        if len(decisions) == 1:
            state.execution_trace.planner.diagnostics["planner_decision_node"].update(
                {
                    "decision_id": decisions[0].decision_id,
                    "decision_kind": decisions[0].decision_kind,
                }
            )
        return _state_update(state)

    async def _tool_retrieval_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "tool_retrieval_node", self._tracer)
        decisions = [
            decision
            for decision in state.planner_decisions
            if decision.decision_kind == "retrieve_tools"
            and decision.requirement_id is not None
            and not _has_candidate_window_for_requirement(state, decision.requirement_id)
            and not _has_evidence_for_requirement(state, decision.requirement_id)
        ]
        if not decisions:
            state.execution_trace.tool_retrieval.diagnostics["phase4_retrieval"] = {"status": "no_decision"}
            return _state_update(state)

        retrievals: list[PlannerOwnedGraphRetrieval] = []
        blocked: list[dict[str, Any]] = []
        for decision in decisions:
            validate_planner_decision(state, decision)
            guard_decision = _record_repeated_retrieval_guard_trace(state, decision.capability_need)
            if guard_decision is not None and guard_decision.blocked:
                blocked.append(
                    {
                        "decision_id": decision.decision_id,
                        "requirement_id": decision.requirement_id,
                        "guard": guard_decision.as_diagnostics(),
                    }
                )
                continue
            retrieval = await _maybe_await(self._adapters.retrieve_tools(state, decision))
            retrievals.append(retrieval)
            if not any(
                window.requirement_id == retrieval.candidate_window.requirement_id
                for window in state.candidate_tool_windows
            ):
                state.candidate_tool_windows.append(retrieval.candidate_window)
            if not any(
                cards.requirement_id == retrieval.hydrated_tool_cards.requirement_id
                for cards in state.hydrated_tool_cards
            ):
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

        if len(retrievals) == 1 and not blocked:
            state.execution_trace.tool_retrieval.diagnostics["phase4_retrieval"] = retrievals[0].trace.diagnostics
        else:
            state.execution_trace.tool_retrieval.diagnostics["phase4_retrieval"] = {
                "status": "ok" if retrievals else "blocked_by_repeated_retrieval_guard",
                "retrieval_count": len(retrievals),
                "retrieved_requirement_ids": [
                    retrieval.candidate_window.requirement_id for retrieval in retrievals
                ],
                "blocked": blocked,
                "retrievals": [retrieval.trace.diagnostics for retrieval in retrievals],
            }
        return _state_update(state)

    async def _planner_choose_tool_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "planner_choose_tool_node", self._tracer)
        retrieve_decisions = [
            decision
            for decision in state.planner_decisions
            if decision.decision_kind == "retrieve_tools"
            and decision.requirement_id is not None
            and _has_candidate_window_for_requirement(state, decision.requirement_id)
            and not _has_choice_for_requirement(state, decision.requirement_id)
            and not _has_evidence_for_requirement(state, decision.requirement_id)
        ]
        if not retrieve_decisions:
            state.execution_trace.planner.diagnostics["planner_choose_tool_node"] = {"decision": "none"}
            return _state_update(state)

        decisions: list[PlannerDecisionRecord] = []
        for retrieve_decision in retrieve_decisions:
            tool_call = await _maybe_await(self._adapters.choose_tool(state, retrieve_decision))
            decision = PlannerDecisionRecord(
                decision_id=f"dec-choose-{len(state.planner_decisions) + 1:03d}",
                decision_kind="choose_tool",
                requirement_id=tool_call.requirement_id,
                ledger_revision=state.requirement_ledger.revision,
                capability_need=retrieve_decision.capability_need,
                selected_tool_call=tool_call,
                reason="Graph selects from the hydrated candidate window.",
            )
            tool_call.decision_id = decision.decision_id
            record_planner_decision(state, decision)
            decisions.append(decision)
            state.execution_trace.selected_tool_names = list(
                dict.fromkeys([*state.execution_trace.selected_tool_names, tool_call.tool_name])
            )

        state.execution_trace.planner.call_count += len(decisions)
        state.execution_trace.planner.diagnostics["planner_choose_tool_node"] = {
            "decision_count": len(decisions),
            "decision_ids": [decision.decision_id for decision in decisions],
            "tool_names": [
                decision.selected_tool_call.tool_name
                for decision in decisions
                if decision.selected_tool_call is not None
            ],
        }
        if len(decisions) == 1 and decisions[0].selected_tool_call is not None:
            state.execution_trace.planner.diagnostics["planner_choose_tool_node"].update(
                {
                    "decision_id": decisions[0].decision_id,
                    "tool_name": decisions[0].selected_tool_call.tool_name,
                }
            )
        return _state_update(state)

    async def _tool_execution_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "tool_execution_node", self._tracer)
        if state.pending_approval.status == "pending":
            state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY] = {
                "status": "paused_for_approval",
                "approval_id": state.pending_approval.approval_id,
            }
            return _state_update(state)

        choose_decisions = [
            decision
            for decision in state.planner_decisions
            if decision.decision_kind == "choose_tool"
            and decision.selected_tool_call is not None
            and not _has_evidence_for_requirement(state, decision.selected_tool_call.requirement_id)
            and not _has_execution_decision_for_call(state, decision.selected_tool_call)
        ]
        if not choose_decisions:
            state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY] = {"status": "no_tool_choice"}
            return _state_update(state)

        executions: list[GraphToolExecutionResult] = []
        action_events: list[dict[str, Any]] = []
        for choose_decision in choose_decisions:
            if _tool_choice_requires_graph_approval(state, choose_decision):
                await self._stage_write_approval(state, choose_decision)
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
            executions.append(execution)
            action_events.append(
                {
                    "decision_id": guard_decision.decision_id,
                    "tool_call_id": execution.tool_call.call_id,
                    "tool_call_kind": execution.tool_call.kind,
                    "tool_name": execution.tool_call.tool_name,
                    "requirement_id": execution.tool_call.requirement_id,
                    "source_type": execution.source_type,
                    "source_of_truth": execution.source_of_truth,
                    "graph_tool_action": execution.diagnostic_metadata.get(
                        "graph_tool_action",
                        execution.tool_call.kind,
                    ),
                    "legacy_shortcut_used": False,
                }
            )

        state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY] = {
            "status": "observed_by_next_node",
            "execution_results": [execution.model_dump(mode="json") for execution in executions],
        }
        previous_actions = list(state.execution_trace.diagnostics.get("graph_tool_actions") or [])
        state.execution_trace.diagnostics["graph_tool_actions"] = [*previous_actions, *action_events]
        if len(executions) == 1:
            state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY]["execution_result"] = (
                executions[0].model_dump(mode="json")
            )
        return _state_update(state)

    async def _evidence_observation_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "evidence_observation_node", self._tracer)
        pending = state.execution_trace.diagnostics.get(_PENDING_EXECUTION_DIAGNOSTIC_KEY)
        if not isinstance(pending, dict) or pending.get("status") != "observed_by_next_node":
            state.execution_trace.diagnostics["evidence_observation"] = {"status": "no_pending_execution"}
            return _state_update(state)
        raw_executions = pending.get("execution_results")
        if not isinstance(raw_executions, list):
            raw_executions = [pending["execution_result"]]
        evidence_items: list[EvidenceLedgerEntry] = []
        for raw_execution in raw_executions:
            execution = GraphToolExecutionResult.model_validate(raw_execution)
            evidence = await _maybe_await(self._adapters.observe_tool_result(state, execution))
            state.evidence_ledger.evidence.append(evidence)
            evidence_items.append(evidence)
        graph_evidence_events = [
            {
                "evidence_ref": evidence.id,
                "tool_name": evidence.tool_name,
                "requirement_id": evidence.requirement_id,
                "source_type": evidence.source_type,
                "source_of_truth": evidence.source_of_truth,
                "graph_tool_action": evidence.diagnostic_metadata.get("graph_tool_action"),
                "legacy_shortcut_used": False,
            }
            for evidence in evidence_items
        ]
        state.execution_trace.diagnostics["evidence_observation"] = {
            "status": "recorded",
            "evidence_refs": [evidence.id for evidence in evidence_items],
            "source_types": [evidence.source_type for evidence in evidence_items],
            "source_of_truths": [evidence.source_of_truth for evidence in evidence_items],
            "graph_evidence": graph_evidence_events,
        }
        if len(evidence_items) == 1:
            state.execution_trace.diagnostics["evidence_observation"].update(
                {
                    "evidence_ref": evidence_items[0].id,
                    "source_type": evidence_items[0].source_type,
                    "source_of_truth": evidence_items[0].source_of_truth,
                }
            )
        state.execution_trace.diagnostics.pop(_PENDING_EXECUTION_DIAGNOSTIC_KEY, None)
        return _state_update(state)

    async def _satisfaction_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "satisfaction_node", self._tracer)
        if state.pending_approval.status == "pending":
            state.execution_trace.diagnostics["satisfaction"] = {
                "status": "paused_for_approval",
                "approval_id": state.pending_approval.approval_id,
                "final_validation_deferred": True,
            }
            return _state_update(state)
        if _has_open_graph_write_requirement(state):
            state.execution_trace.diagnostics["satisfaction"] = {
                "status": "paused_for_graph_write_followup",
                "open_write_requirement_ids": _open_graph_write_requirement_ids(state),
                "final_validation_deferred": True,
            }
            return _state_update(state)
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
            "approval_id": state.pending_approval.approval_id,
            "requirement_id": state.pending_approval.requirement_id,
            "checkpoint_id": state.pending_approval.checkpoint_id,
            "phase": "phase8_graph_write_approval_pause",
            "native_langgraph_checkpoint_required_for_resume": state.pending_approval.status == "pending",
        }
        return _state_update(state)

    async def _finalize_node(self, state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
        _record_node_visit(state, "finalize_node", self._tracer)
        if state.pending_approval.status == "pending":
            state.execution_trace.planner.diagnostics["finalize_node"] = {
                "decision_kind": "deferred",
                "reason": "approval_pending",
                "approval_id": state.pending_approval.approval_id,
            }
            return _state_update(state)
        if _has_open_graph_write_requirement(state):
            state.execution_trace.planner.diagnostics["finalize_node"] = {
                "decision_kind": "deferred",
                "reason": "open_graph_write_requirement",
                "open_write_requirement_ids": _open_graph_write_requirement_ids(state),
            }
            return _state_update(state)
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
        validation_status = state.final_validation_result.status if state.final_validation_result else "deferred"
        response_blocks = _phase6_response_blocks(state)
        if state.pending_approval.status == "pending":
            approval_block = _pending_approval_response_block(state)
            if approval_block is not None:
                response_blocks.append(approval_block)
        response_summary = _phase6_response_summary(state, response_blocks)
        pending = state.pending_approval.status == "pending"
        graph_write_activity = _has_graph_write_activity(state)
        state.response_document_context = ResponseDocumentContext(
            state="draft" if pending or validation_status == "deferred" else ("rendered" if validation_status == "passed" else "failed"),
            document_id=(
                f"phase8-response-{uuid4().hex[:12]}"
                if graph_write_activity
                else f"phase7-response-{uuid4().hex[:12]}"
            ),
            revision=state.requirement_ledger.revision,
            requirement_ids=[requirement.id for requirement in state.requirement_ledger.requirements],
            evidence_refs=[evidence.id for evidence in state.evidence_ledger.evidence],
            pending_approval_id=state.pending_approval.approval_id if pending else None,
            render_contract=(
                "phase8_graph_write_approval_response_document_context"
                if graph_write_activity
                else "phase7_rag_graph_tool_response_document_context"
            ),
            diagnostics={
                "phase": "phase8_graph_write_approval" if graph_write_activity else "phase7_rag_graph_tool",
                "real_response_renderer_called": False,
                "final_validation_status": validation_status,
                "summary": response_summary,
                "blocks": response_blocks,
                "fulfilled_requirement_ids": [
                    requirement.id
                    for requirement in state.requirement_ledger.requirements
                    if requirement.status in {"satisfied", "impossible"}
                ],
                "terminal_requirement_statuses": {
                    requirement.id: requirement.status
                    for requirement in state.requirement_ledger.requirements
                    if requirement.status != "open"
                },
                "no_record_evidence_refs": [
                    evidence.id
                    for evidence in state.evidence_ledger.evidence
                    if _evidence_has_no_match(evidence)
                    and not _is_document_insufficient_context_evidence(evidence)
                ],
                "document_evidence_refs": [
                    evidence.id
                    for evidence in state.evidence_ledger.evidence
                    if evidence.source_of_truth == "document_knowledge"
                ],
                "insufficient_context_evidence_refs": [
                    evidence.id
                    for evidence in state.evidence_ledger.evidence
                    if _is_document_insufficient_context_evidence(evidence)
                ],
                "preview_blocks": 0,
                "approval_blocks": 1 if pending else 0,
                "pending_approval": state.pending_approval.payload if pending else None,
                "stale_response_context_reused": False,
            },
        )
        return _state_update(state)

    async def _stage_write_approval(
        self,
        state: PlannerOwnedAgentGraphState,
        choose_decision: PlannerDecisionRecord,
    ) -> None:
        call = choose_decision.selected_tool_call
        if call is None:
            raise ValueError("approval staging requires a selected graph tool call")
        requirement = _requirement_by_id(state, call.requirement_id)
        card = _hydrated_card_for_tool_call(state, call)
        if requirement is None or card is None:
            raise ValueError("approval staging requires requirement and hydrated tool card")

        preview = await self._adapters.build_approval_preview(state, call, requirement, card)
        if preview.commit_args:
            call.args.update(preview.commit_args)
        else:
            call.args.update(_commit_args_from_preview(card=card, requirement=requirement, rows=preview.rows))
        if not preview.rows:
            evidence = _append_no_record_preview_evidence(
                state,
                call=call,
                requirement=requirement,
                preview=preview,
                decision_id=choose_decision.decision_id,
            )
            _record_graph_requirement_update(
                state,
                requirement,
                status="impossible",
                evidence_refs=[evidence.id],
                checks=[
                    SatisfactionCheck(
                        check="approval_preview_records",
                        expected="one_or_more_matching_records",
                        actual_count=0,
                        passed=True,
                        evidence_ref=evidence.id,
                        message=preview.no_records_message,
                    )
                ],
                reason="approval_preview_no_records",
            )
            state.pending_approval = PendingApprovalState(status="none")
            state.execution_trace.diagnostics["phase8_approval_staging"] = {
                "status": "no_records_found",
                "requirement_id": requirement.id,
                "evidence_ref": evidence.id,
                "future_approval_details_suppressed": True,
            }
            return

        approval_index = _next_approval_index(state)
        approval_label = f"Approval {approval_index}"
        request_decision = PlannerDecisionRecord(
            decision_id=f"dec-approval-{len(state.planner_decisions) + 1:03d}",
            decision_kind="request_approval",
            requirement_id=requirement.id,
            ledger_revision=state.requirement_ledger.revision,
            capability_need=choose_decision.capability_need,
            selected_tool_call=call,
            reason="Graph stages a write preview and pauses for approval before commit.",
            diagnostics={
                "approval_index": approval_index,
                "approval_label": approval_label,
                "approval_node": "approval_node",
            },
        )
        record_planner_decision(state, request_decision)
        staged = [
            {
                "tool_name": call.tool_name,
                "args": dict(call.args),
                "output_ref": call.call_id,
                "requirement_id": requirement.id,
            }
        ]
        payload = build_approval_required_payload(staged, intent_text=state.original_query)
        checkpoint_identity = dict(
            state.execution_trace.diagnostics.get("graph_checkpoint_identity")
            or _graph_checkpoint_identity({}, ledger_revision=state.requirement_ledger.revision)
        )
        payload.update(
            {
                "kind": "graph_write_approval_required",
                "approval_index": approval_index,
                "approval_label": approval_label,
                "ledger_revision": state.requirement_ledger.revision,
                "requirement_ledger_revision": state.requirement_ledger.revision,
                "graph_checkpoint_identity": checkpoint_identity,
                "checkpoint_id": checkpoint_identity.get("checkpoint_id"),
                "selected_graph_tool_call": call.model_dump(mode="json"),
                "selected_graph_tool_decision_id": choose_decision.decision_id,
                "approval_decision_id": request_decision.decision_id,
                "requirement_id": requirement.id,
                "preview_rows": preview.rows,
                "preview_details": dict(preview.details),
                "excluded_rows": preview.excluded_rows,
                "blocked_rows_excluded": any(
                    str(row.get("status") or "").lower() == "blocked"
                    for row in preview.excluded_rows
                ),
                "graph_tool_action": "approval_node",
                "legacy_shortcut_used": False,
            }
        )
        persisted = await self._adapters.persist_approval_request(state, payload)
        approval_id = str(persisted.get("approval_id") or f"graph-approval-{uuid4().hex[:12]}")
        payload["approval_id"] = approval_id
        payload["approval_persistence"] = {
            key: value
            for key, value in persisted.items()
            if key != "approval_id"
        }
        state.pending_approval = PendingApprovalState(
            status="pending",
            approval_id=approval_id,
            requirement_id=requirement.id,
            decision_id=request_decision.decision_id,
            ledger_revision=state.requirement_ledger.revision,
            checkpoint_id=str(payload["checkpoint_id"]),
            tool_call=call,
            payload=payload,
        )
        state.execution_trace.diagnostics["phase8_approval_staging"] = {
            "status": "paused_at_approval_node",
            "approval_id": approval_id,
            "approval_label": approval_label,
            "requirement_id": requirement.id,
            "ledger_revision": state.requirement_ledger.revision,
            "checkpoint_id": state.pending_approval.checkpoint_id,
            "selected_graph_tool_call": call.model_dump(mode="json"),
            "preview_row_count": len(preview.rows),
            "excluded_row_count": len(preview.excluded_rows),
            "legacy_shortcut_used": False,
        }

    async def _stage_next_write_approval_if_needed(self, state: PlannerOwnedAgentGraphState) -> None:
        for choose_decision in state.planner_decisions:
            if (
                choose_decision.decision_kind == "choose_tool"
                and choose_decision.selected_tool_call is not None
                and not _has_evidence_for_requirement(state, choose_decision.selected_tool_call.requirement_id)
                and _tool_choice_requires_graph_approval(state, choose_decision)
            ):
                _record_node_visit(state, "tool_execution_node", self._tracer)
                await self._stage_write_approval(state, choose_decision)
                return

    async def _resume_approved_graph_approval(
        self,
        state: PlannerOwnedAgentGraphState,
        pending: PendingApprovalState,
        approval_decision: Mapping[str, Any],
    ) -> None:
        approval_evidence = _record_graph_approval_decision_evidence(
            state,
            pending=pending,
            status="approved",
            reason="approval_granted",
            decided_by=str(approval_decision.get("decided_by") or "user"),
        )
        call = pending.tool_call
        if call is None:
            return
        requirement = _requirement_by_id(state, call.requirement_id)
        need = _capability_need_for_requirement(state, call.requirement_id)
        guard_decision = PlannerDecisionRecord(
            decision_id=f"dec-execute-{len(state.planner_decisions) + 1:03d}",
            decision_kind="execute_tool",
            author="deterministic_guard",
            requirement_id=call.requirement_id,
            ledger_revision=state.requirement_ledger.revision,
            capability_need=need,
            selected_tool_call=call,
            reason="Execute graph-staged write after matching approval evidence.",
        )
        record_planner_decision(state, guard_decision)
        _record_node_visit(state, "tool_execution_node", self._tracer)
        execution = await _maybe_await(self._adapters.execute_tool(state, guard_decision))
        state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY] = {
            "status": "observed_by_next_node",
            "execution_results": [execution.model_dump(mode="json")],
            "execution_result": execution.model_dump(mode="json"),
            "approval_id": pending.approval_id,
        }
        previous_actions = list(state.execution_trace.diagnostics.get("graph_tool_actions") or [])
        previous_actions.append(
            {
                "decision_id": guard_decision.decision_id,
                "tool_call_id": execution.tool_call.call_id,
                "tool_call_kind": execution.tool_call.kind,
                "tool_name": execution.tool_call.tool_name,
                "requirement_id": execution.tool_call.requirement_id,
                "source_type": execution.source_type,
                "source_of_truth": execution.source_of_truth,
                "graph_tool_action": execution.diagnostic_metadata.get("graph_tool_action", execution.tool_call.kind),
                "approval_id": pending.approval_id,
                "legacy_shortcut_used": False,
            }
        )
        state.execution_trace.diagnostics["graph_tool_actions"] = previous_actions
        await self._evidence_observation_node(state)
        api_evidence = next(
            (
                evidence
                for evidence in reversed(state.evidence_ledger.evidence)
                if evidence.requirement_id == call.requirement_id and evidence.source_type == "api_tool"
            ),
            None,
        )
        if requirement is not None and api_evidence is not None:
            _record_graph_requirement_update(
                state,
                requirement,
                status="satisfied" if execution.ok else "failed",
                evidence_refs=[approval_evidence.id, api_evidence.id],
                checks=[
                    SatisfactionCheck(
                        check="approval_evidence",
                        expected="approved",
                        actual=approval_evidence.normalized_result.get("approval_status"),
                        passed=True,
                        evidence_ref=approval_evidence.id,
                    ),
                    SatisfactionCheck(
                        check="write_commit_after_approval",
                        expected="api_tool_result_ok",
                        actual=api_evidence.normalized_result.get("status_code"),
                        passed=bool(execution.ok),
                        evidence_ref=api_evidence.id,
                    ),
                ],
                reason="approval_evidence_and_write_result" if execution.ok else "approved_write_failed",
            )
        state.pending_approval = PendingApprovalState(status="none")

    async def _load_checkpoint_state(
        self,
        checkpoint_config: dict[str, Any],
    ) -> tuple[PlannerOwnedAgentGraphState, Any]:
        get_tuple = getattr(self._checkpointer, "aget_tuple", None)
        if get_tuple is not None:
            checkpoint_tuple = await get_tuple(checkpoint_config)
        else:
            checkpoint_tuple = await _maybe_await(self._checkpointer.get_tuple(checkpoint_config))
        if checkpoint_tuple is None:
            raise ValueError("no LangGraph checkpoint found for approval resume")
        checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
        channel_values = checkpoint.get("channel_values")
        if not isinstance(channel_values, Mapping):
            raise ValueError("LangGraph checkpoint did not contain graph channel values")
        allowed = set(PlannerOwnedAgentGraphState.model_fields)
        payload = {key: value for key, value in channel_values.items() if key in allowed}
        return PlannerOwnedAgentGraphState.model_validate(payload), checkpoint_tuple


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


def _normalize_approval_preview(value: Any) -> PlannerOwnedGraphApprovalPreview:
    if isinstance(value, PlannerOwnedGraphApprovalPreview):
        return value
    if not isinstance(value, Mapping):
        return PlannerOwnedGraphApprovalPreview(rows=[])
    rows = value.get("rows") or value.get("preview_rows") or value.get("records") or []
    excluded = value.get("excluded_rows") or value.get("blocked_rows") or []
    details = value.get("details") or value.get("preview_details") or {}
    commit_args = value.get("commit_args") or {}
    return PlannerOwnedGraphApprovalPreview(
        rows=[dict(row) for row in rows if isinstance(row, Mapping)],
        excluded_rows=[dict(row) for row in excluded if isinstance(row, Mapping)],
        details=dict(details) if isinstance(details, Mapping) else {"value": details},
        commit_args=dict(commit_args) if isinstance(commit_args, Mapping) else {},
        no_records_message=str(value.get("no_records_message") or "No matching records were found."),
    )


def _default_approval_preview(
    *,
    tool_call: GraphToolCall,
    requirement: Any,
    card: HydratedToolCard,
) -> PlannerOwnedGraphApprovalPreview:
    args = _commit_args_from_preview(card=card, requirement=requirement, rows=[])
    args.update(tool_call.args)
    rows = [dict(args)] if args else []
    return PlannerOwnedGraphApprovalPreview(
        rows=rows,
        details={
            "source": "default_graph_write_preview",
            "tool_name": tool_call.tool_name,
        },
        commit_args=args,
    )


def _commit_args_from_preview(
    *,
    card: HydratedToolCard,
    requirement: Any,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    input_properties = card.input_schema.get("properties", {}) if isinstance(card.input_schema, Mapping) else {}
    first_row = rows[0] if rows else {}
    entity = str(getattr(requirement, "entity", "") or "").strip()

    for path_param in card.path_params:
        value = constraints.get(path_param)
        if value in (None, "", [], {}) and path_param == "id" and entity:
            value = constraints.get(f"{entity}_id")
        if value in (None, "", [], {}) and first_row:
            value = first_row.get(path_param) or first_row.get(f"{entity}_id") or first_row.get("id")
        if value not in (None, "", [], {}):
            args[path_param] = value

    for key, value in constraints.items():
        if key.startswith("new_"):
            target = key.removeprefix("new_")
            if target in input_properties and value not in (None, "", [], {}):
                args[target] = value
            continue
        if key in input_properties and key not in {"requires_approval"} and value not in (None, "", [], {}):
            args.setdefault(key, value)

    return args


def _graph_checkpoint_identity(
    checkpoint_config: Mapping[str, Any],
    *,
    ledger_revision: int,
) -> dict[str, Any]:
    configurable = checkpoint_config.get("configurable") if isinstance(checkpoint_config, Mapping) else {}
    if not isinstance(configurable, Mapping):
        configurable = {}
    thread_id = str(configurable.get("thread_id") or "planner-owned-agent-graph")
    checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
    checkpoint_id = str(configurable.get("checkpoint_id") or f"{thread_id}:ledger-{ledger_revision}:approval")
    return {
        "thread_id": thread_id,
        "checkpoint_ns": checkpoint_ns,
        "checkpoint_id": checkpoint_id,
        "ledger_revision": ledger_revision,
        "native_langgraph_checkpoint": True,
    }


def _checkpoint_tuple_id(checkpoint_tuple: Any) -> str | None:
    config = getattr(checkpoint_tuple, "config", None)
    if isinstance(config, Mapping):
        configurable = config.get("configurable")
        if isinstance(configurable, Mapping):
            checkpoint_id = configurable.get("checkpoint_id")
            return str(checkpoint_id) if checkpoint_id not in (None, "") else None
    checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
    if isinstance(checkpoint, Mapping):
        checkpoint_id = checkpoint.get("id")
        return str(checkpoint_id) if checkpoint_id not in (None, "") else None
    return None


def _tool_choice_requires_graph_approval(
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
) -> bool:
    call = decision.selected_tool_call
    if call is None or call.kind != "api_tool":
        return False
    requirement = _requirement_by_id(state, call.requirement_id)
    card = _hydrated_card_for_tool_call(state, call)
    if getattr(requirement, "requirement_type", None) in {"mutation_request", "approval_request"}:
        return True
    if card is None:
        return False
    return bool(card.requires_approval) or not bool(card.is_read_only)


def _hydrated_card_for_tool_call(
    state: PlannerOwnedAgentGraphState,
    call: GraphToolCall,
) -> HydratedToolCard | None:
    return next((card for card in _hydrated_cards_for_requirement(state, call.requirement_id) if card.tool_name == call.tool_name), None)


def _next_approval_index(state: PlannerOwnedAgentGraphState) -> int:
    return 1 + sum(1 for decision in state.planner_decisions if decision.decision_kind == "request_approval")


def _approval_decision_matches_pending(
    approval_decision: Mapping[str, Any],
    pending: PendingApprovalState,
) -> bool:
    if approval_decision.get("approval_id") != pending.approval_id:
        return False
    ledger_revision = approval_decision.get("ledger_revision", approval_decision.get("requirement_ledger_revision"))
    if ledger_revision is not None and int(ledger_revision) != pending.ledger_revision:
        return False
    checkpoint_id = approval_decision.get("checkpoint_id")
    if checkpoint_id is not None and str(checkpoint_id) != str(pending.checkpoint_id):
        return False
    return True


def _record_graph_resume_no_pending_approval(
    state: PlannerOwnedAgentGraphState,
    approval_decision: Mapping[str, Any],
) -> None:
    evidence = EvidenceLedgerEntry(
        id=_unique_graph_evidence_id(state, "ev-approval-no-pending"),
        requirement_id=str(approval_decision.get("requirement_id") or state.requirement_ledger.requirements[0].id),
        source_type="approval",
        source_of_truth="operational_state",
        confidence="deterministic",
        approval_id=str(approval_decision.get("approval_id") or ""),
        normalized_result={
            "approval_status": "stale",
            "status": "rejected",
            "reason": "no_pending_graph_approval",
            "committed": False,
        },
        diagnostic_metadata={
            "graph_approval_resume": True,
            "native_langgraph_checkpoint_used": True,
            "session_replan_context_authoritative": False,
            "reason": "no_pending_graph_approval",
        },
    )
    state.evidence_ledger.evidence.append(evidence)
    requirement = _requirement_by_id(state, evidence.requirement_id)
    if requirement is not None and requirement.status == "open":
        _record_graph_requirement_update(
            state,
            requirement,
            status="impossible",
            evidence_refs=[evidence.id],
            checks=[
                SatisfactionCheck(
                    check="approval_resume_state",
                    expected="pending_graph_approval",
                    actual="none",
                    passed=True,
                    evidence_ref=evidence.id,
                )
            ],
            reason="no_pending_graph_approval",
        )
    state.pending_approval = PendingApprovalState(status="stale")


def _record_graph_approval_decision_evidence(
    state: PlannerOwnedAgentGraphState,
    *,
    pending: PendingApprovalState,
    status: str,
    reason: str,
    rejection_reason: str | None = None,
    decided_by: str | None = None,
) -> EvidenceLedgerEntry:
    requirement_id = pending.requirement_id or (pending.tool_call.requirement_id if pending.tool_call else None)
    if requirement_id is None:
        requirement_id = state.requirement_ledger.requirements[0].id
    evidence = EvidenceLedgerEntry(
        id=_unique_graph_evidence_id(state, f"ev-approval-{status}-{requirement_id}"),
        requirement_id=requirement_id,
        source_type="approval",
        source_of_truth="operational_state",
        confidence="deterministic",
        approval_id=pending.approval_id,
        normalized_result={
            "approval_status": status,
            "status": status,
            "reason": reason,
            "rejection_reason": rejection_reason,
            "committed": False,
            "ledger_revision": pending.ledger_revision,
            "checkpoint_id": pending.checkpoint_id,
        },
        diagnostic_metadata={
            "graph_approval_resume": True,
            "approval_id": pending.approval_id,
            "approval_status": status,
            "reason": reason,
            "decided_by": decided_by,
            "native_langgraph_checkpoint_used": True,
            "session_replan_context_authoritative": False,
            "selected_graph_tool_call": pending.tool_call.model_dump(mode="json") if pending.tool_call else None,
        },
    )
    state.evidence_ledger.evidence.append(evidence)
    if status in {"rejected", "stale"}:
        requirement = _requirement_by_id(state, requirement_id)
        if requirement is not None and requirement.status == "open":
            _record_graph_requirement_update(
                state,
                requirement,
                status="impossible",
                evidence_refs=[evidence.id],
                checks=[
                    SatisfactionCheck(
                        check="approval_decision",
                        expected="approved",
                        actual=status,
                        passed=True,
                        evidence_ref=evidence.id,
                        message=rejection_reason or reason,
                    )
                ],
                reason=reason,
            )
        state.pending_approval = PendingApprovalState(
            status="stale" if status == "stale" else "rejected",
            approval_id=pending.approval_id,
            requirement_id=requirement_id,
            decision_id=pending.decision_id,
            ledger_revision=pending.ledger_revision,
            checkpoint_id=pending.checkpoint_id,
            tool_call=pending.tool_call,
            payload=dict(pending.payload),
        )
    return evidence


def _append_no_record_preview_evidence(
    state: PlannerOwnedAgentGraphState,
    *,
    call: GraphToolCall,
    requirement: Any,
    preview: PlannerOwnedGraphApprovalPreview,
    decision_id: str | None,
) -> EvidenceLedgerEntry:
    evidence = EvidenceLedgerEntry(
        id=_unique_graph_evidence_id(state, f"ev-approval-preview-no-records-{call.requirement_id}"),
        requirement_id=call.requirement_id,
        source_type="system_guard",
        source_of_truth="operational_state",
        confidence="deterministic",
        tool_name=call.tool_name,
        args=dict(call.args),
        normalized_result={
            "match_status": "no_match",
            "no_match": True,
            "summary": preview.no_records_message,
            "message": preview.no_records_message,
            "entity": getattr(requirement, "entity", None),
            "preview_rows": [],
            "preview_details": dict(preview.details),
            "excluded_rows": preview.excluded_rows,
        },
        satisfies=["typed_no_match"],
        diagnostic_metadata={
            "graph_tool_action": "approval_preview",
            "decision_id": decision_id,
            "reason": "approval_preview_no_records",
            "future_approval_details_suppressed": True,
            "legacy_shortcut_used": False,
        },
    )
    state.evidence_ledger.evidence.append(evidence)
    return evidence


def _record_graph_requirement_update(
    state: PlannerOwnedAgentGraphState,
    requirement: Any,
    *,
    status: str,
    evidence_refs: list[str],
    checks: list[SatisfactionCheck],
    reason: str,
) -> None:
    previous_status = requirement.status
    requirement.status = status
    requirement.evidence_refs = list(dict.fromkeys(evidence_refs))
    requirement.satisfaction_checks = list(checks)
    if status in {"blocked", "failed", "impossible"} and reason not in requirement.blockers:
        requirement.blockers.append(reason)
    state.requirement_ledger.revision += 1
    record = RequirementRevisionRecord(
        revision=state.requirement_ledger.revision,
        actor="deterministic_guard",
        change_type=f"graph_approval_satisfaction:{status}",
        requirement_id=requirement.id,
        reason=reason,
        locked_constraints_preserved=True,
        details={
            "previous_status": previous_status,
            "new_status": status,
            "evidence_refs": list(evidence_refs),
            "satisfaction_checks": [check.model_dump(mode="json") for check in checks],
        },
    )
    state.requirement_ledger.revision_history.append(record)
    state.revision_history.append(record)
    existing = [
        item
        for item in state.satisfaction_state.requirements
        if item.requirement_id != requirement.id
    ]
    existing.append(
        RequirementSatisfactionState(
            requirement_id=requirement.id,
            status=requirement.status,
            evidence_refs=list(requirement.evidence_refs),
            satisfaction_checks=list(requirement.satisfaction_checks),
            blocker_reason=reason if requirement.status in {"blocked", "failed", "impossible"} else None,
        )
    )
    state.satisfaction_state.requirements = existing


def _unique_graph_evidence_id(state: PlannerOwnedAgentGraphState, base: str) -> str:
    existing = {evidence.id for evidence in state.evidence_ledger.evidence}
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _has_open_graph_write_requirement(state: PlannerOwnedAgentGraphState) -> bool:
    return bool(_open_graph_write_requirement_ids(state))


def _open_graph_write_requirement_ids(state: PlannerOwnedAgentGraphState) -> list[str]:
    return [
        requirement.id
        for requirement in state.requirement_ledger.requirements
        if requirement.status == "open"
        and requirement.requirement_type in {"mutation_request", "approval_request"}
    ]


def _has_graph_write_activity(state: PlannerOwnedAgentGraphState) -> bool:
    if state.pending_approval.status != "none":
        return True
    if any(
        requirement.requirement_type in {"mutation_request", "approval_request"}
        for requirement in state.requirement_ledger.requirements
    ):
        return True
    return any(evidence.source_type == "approval" for evidence in state.evidence_ledger.evidence)


def _latest_decision(state: PlannerOwnedAgentGraphState, decision_kind: str) -> PlannerDecisionRecord | None:
    return next(
        (
            decision
            for decision in reversed(state.planner_decisions)
            if decision.decision_kind == decision_kind
        ),
        None,
    )


def _record_repeated_retrieval_guard_trace(
    state: PlannerOwnedAgentGraphState,
    active_need: Any | None,
):
    needs = build_capability_needs_for_text(state.original_query, capability_map=state.capability_map)
    if active_need is not None and not any(need.requirement_id == active_need.requirement_id for need in needs):
        needs = [active_need, *needs]

    guard = V2RepeatedRetrievalGuard()
    decisions: list[dict[str, Any]] = []
    repeated_keys: list[str] = []
    active_decision = None
    for need in needs:
        decision = guard.check(need, state=state.as_loop_compat_state())
        diagnostics = decision.as_diagnostics()
        diagnostics["requirement_id"] = need.requirement_id
        decisions.append(diagnostics)
        if decision.blocked:
            repeated_keys.append(decision.need_key)
        if active_need is not None and need.requirement_id == active_need.requirement_id:
            active_decision = decision

    state.execution_trace.diagnostics["repeated_retrieval_guard"] = {
        "status": "blocked_repeated_need" if repeated_keys else "not_triggered",
        "repeated_need_keys": repeated_keys,
        "decisions": decisions,
    }
    return active_decision


def _open_requirements_without_evidence(state: PlannerOwnedAgentGraphState):
    evidence_requirement_ids = {evidence.requirement_id for evidence in state.evidence_ledger.evidence}
    return [
        requirement
        for requirement in state.requirement_ledger.requirements
        if requirement.status == "open" and requirement.id not in evidence_requirement_ids
    ]


def _has_decision_for_requirement(
    state: PlannerOwnedAgentGraphState,
    decision_kind: str,
    requirement_id: str,
) -> bool:
    return any(
        decision.decision_kind == decision_kind and decision.requirement_id == requirement_id
        for decision in state.planner_decisions
    )


def _has_candidate_window_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> bool:
    return any(window.requirement_id == requirement_id for window in state.candidate_tool_windows) and any(
        cards.requirement_id == requirement_id for cards in state.hydrated_tool_cards
    )


def _has_choice_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> bool:
    return any(
        decision.decision_kind == "choose_tool" and decision.requirement_id == requirement_id
        for decision in state.planner_decisions
    )


def _has_evidence_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> bool:
    return any(evidence.requirement_id == requirement_id for evidence in state.evidence_ledger.evidence)


def _has_execution_decision_for_call(
    state: PlannerOwnedAgentGraphState,
    tool_call: GraphToolCall,
) -> bool:
    return any(
        decision.decision_kind == "execute_tool"
        and decision.selected_tool_call is not None
        and decision.selected_tool_call.call_id == tool_call.call_id
        for decision in state.planner_decisions
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


def _phase6_response_blocks(state: PlannerOwnedAgentGraphState) -> list[dict[str, Any]]:
    requirements_by_id = {requirement.id: requirement for requirement in state.requirement_ledger.requirements}
    blocks: list[dict[str, Any]] = []
    for evidence in state.evidence_ledger.evidence:
        requirement = requirements_by_id.get(evidence.requirement_id)
        block = _phase6_response_block_for_evidence(requirement, evidence)
        if block:
            blocks.append(block)
    return blocks


def _phase6_response_summary(state: PlannerOwnedAgentGraphState, blocks: list[dict[str, Any]]) -> str:
    _ = state
    parts = [
        str(block.get("summary") or "").strip()
        for block in blocks
        if str(block.get("summary") or "").strip()
    ]
    if not parts:
        return "No fulfilled read evidence was available for response rendering."
    return " ".join(dict.fromkeys(parts))


def _phase6_response_block_for_evidence(requirement: Any | None, evidence: EvidenceLedgerEntry) -> dict[str, Any]:
    if evidence.source_type == "approval":
        status = str(evidence.normalized_result.get("approval_status") or evidence.normalized_result.get("status") or "")
        if status == "approved":
            return {
                "type": "approval_decision",
                "requirement_id": evidence.requirement_id,
                "evidence_ref": evidence.id,
                "approval_id": evidence.approval_id,
                "status": "approved",
                "summary": "Approval was recorded; the graph committed the staged write after approval.",
                "source_type": evidence.source_type,
            }
        return {
            "type": "approval_decision",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "approval_id": evidence.approval_id,
            "status": status or "rejected",
            "summary": str(
                evidence.normalized_result.get("rejection_reason")
                or evidence.normalized_result.get("reason")
                or "Approval was not applied."
            ),
            "source_type": evidence.source_type,
        }

    if _is_document_insufficient_context_evidence(evidence):
        answer = str(evidence.normalized_result.get("answer") or "").strip()
        sources_checked = evidence.normalized_result.get("sources_checked")
        source_count = len(sources_checked) if isinstance(sources_checked, list) else 0
        return {
            "type": "document_insufficient_context",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "summary": answer or "I do not have enough retrieved evidence to answer that safely.",
            "sources_checked_count": source_count,
            "source_type": evidence.source_type,
            "source_of_truth": evidence.source_of_truth,
        }

    if _evidence_has_no_match(evidence):
        return {
            "type": "no_record",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "entity_type": getattr(requirement, "entity", None),
            "summary": _no_match_summary(requirement, evidence),
            "source_type": evidence.source_type,
        }

    if evidence.source_type == "rag_tool":
        answer = str(evidence.normalized_result.get("answer") or "").strip()
        return {
            "type": "document_answer",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "summary": answer or "Document evidence was retrieved.",
            "citation_count": len(evidence.citations),
            "source_type": evidence.source_type,
        }

    rows = _phase6_rows(evidence.normalized_result)
    if rows is not None:
        return {
            "type": (
                "mutation_result"
                if getattr(requirement, "requirement_type", None) == "mutation_request"
                else ("result_table" if getattr(requirement, "requirement_type", None) == "filtered_collection" else "multi_status")
            ),
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "entity_type": getattr(requirement, "entity", None),
            "summary": _collection_summary(requirement, evidence, rows),
            "row_count": len(rows),
            "rows": rows,
            "requested_fields": list(getattr(requirement, "requested_fields", []) or []),
            "source_type": evidence.source_type,
        }

    fields = _phase6_fields(evidence.normalized_result)
    if getattr(requirement, "requirement_type", None) == "mutation_request" and evidence.source_type == "api_tool":
        entity = str(getattr(requirement, "entity", "") or evidence.normalized_result.get("entity") or "record")
        entity_id = evidence.normalized_result.get("entity_id") or _first_field_value(
            fields,
            [f"{entity}_id", "entity_id", "id", "machine_ref"],
        )
        return {
            "type": "mutation_result",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "entity_type": entity,
            "entity_id": entity_id,
            "summary": _mutation_summary(entity=entity, entity_id=entity_id, fields=fields),
            "fields": fields,
            "source_type": evidence.source_type,
        }

    entity = str(getattr(requirement, "entity", "") or evidence.normalized_result.get("entity") or "record")
    entity_id = evidence.normalized_result.get("entity_id") or _first_field_value(
        fields,
        [f"{entity}_id", "entity_id", "id", "machine_ref"],
    )
    status = _first_field_value(fields, ["status", "state"])
    summary = _single_status_summary(entity=entity, entity_id=entity_id, status=status)
    requested_fields = [f"{entity}_id", *list(getattr(requirement, "requested_fields", []) or [])]
    return {
        "type": "status_result",
        "requirement_id": evidence.requirement_id,
        "evidence_ref": evidence.id,
        "entity_type": entity,
        "entity_id": entity_id,
        "summary": summary,
        "primary_status": str(status).lower() if status not in (None, "") else None,
        "requested_fields": list(dict.fromkeys(field for field in requested_fields if field)),
        "fields": fields,
        "source_type": evidence.source_type,
    }


def _evidence_has_no_match(evidence: EvidenceLedgerEntry) -> bool:
    result = evidence.normalized_result
    return (
        result.get("no_match") is True
        or str(result.get("match_status") or "").lower() == "no_match"
        or str(result.get("status") or "").lower() == "no_match"
    )


def _is_document_insufficient_context_evidence(evidence: EvidenceLedgerEntry) -> bool:
    result = evidence.normalized_result
    if evidence.source_of_truth != "document_knowledge":
        return False
    return (
        evidence.diagnostic_metadata.get("reason") == "insufficient_context"
        or is_insufficient_context_answer(result.get("answer"))
    )


def _phase6_rows(result: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    for key in ("rows", "items", "results", "records", "data"):
        value = result.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return None


def _phase6_fields(result: Mapping[str, Any]) -> dict[str, Any]:
    fields = result.get("fields")
    if isinstance(fields, Mapping):
        return dict(fields)
    data = result.get("data")
    if isinstance(data, Mapping):
        return dict(data)
    return {
        key: value
        for key, value in result.items()
        if key not in {"status_code", "request_args", "entity", "entity_id", "rows", "applied_filters"}
    }


def _first_field_value(fields: Mapping[str, Any], names: list[str]) -> Any:
    for name in names:
        value = fields.get(name)
        if value not in (None, ""):
            return value
    return None


def _single_status_summary(*, entity: str, entity_id: Any, status: Any) -> str:
    label = entity.strip().capitalize() or "Record"
    if entity_id not in (None, "") and status not in (None, ""):
        return f"{label} {entity_id} is {str(status).lower()}."
    if entity_id not in (None, ""):
        return f"{label} {entity_id} was retrieved."
    return f"{label} status was retrieved."


def _collection_summary(requirement: Any | None, evidence: EvidenceLedgerEntry, rows: list[dict[str, Any]]) -> str:
    entity = str(getattr(requirement, "entity", "") or evidence.normalized_result.get("entity") or "record")
    plural = _plural_entity(entity)
    filters = dict(evidence.normalized_result.get("applied_filters") or {})
    priority = filters.get("priority") or getattr(requirement, "constraints", {}).get("priority")
    sort_by = getattr(requirement, "constraints", {}).get("sort_by") if requirement is not None else None
    descriptor = f"{priority}-priority " if priority not in (None, "", [], {}) else ""
    sorted_by = f" sorted by {sort_by}" if sort_by not in (None, "", [], {}) else ""
    return f"Found {len(rows)} {descriptor}{plural}{sorted_by}."


def _mutation_summary(*, entity: str, entity_id: Any, fields: Mapping[str, Any]) -> str:
    label = entity.strip().capitalize() or "Record"
    changed = [
        f"{key}={value}"
        for key, value in fields.items()
        if key not in {f"{entity}_id", "entity_id", "id", "machine_ref"}
    ]
    target = f" {entity_id}" if entity_id not in (None, "") else ""
    if changed:
        return f"{label}{target} updated ({', '.join(changed)})."
    return f"{label}{target} updated."


def _no_match_summary(requirement: Any | None, evidence: EvidenceLedgerEntry) -> str:
    base = str(evidence.normalized_result.get("summary") or evidence.normalized_result.get("message") or "").strip()
    if "no matching records were found" in base.lower():
        return base
    entity = str(getattr(requirement, "entity", "") or evidence.normalized_result.get("entity") or "").strip()
    filters = dict(evidence.normalized_result.get("applied_filters") or {})
    priority = filters.get("priority") or getattr(requirement, "constraints", {}).get("priority")
    if entity and priority not in (None, "", [], {}):
        return f"No matching records were found for {priority}-priority {_plural_entity(entity)}."
    if entity:
        return f"No matching records were found for {_plural_entity(entity)}."
    return "No matching records were found."


def _plural_entity(entity: str) -> str:
    normalized = entity.strip().lower() or "record"
    if normalized.endswith("s"):
        return normalized
    return f"{normalized}s"


def _pending_approval_response_block(state: PlannerOwnedAgentGraphState) -> dict[str, Any] | None:
    pending = state.pending_approval
    if pending.status != "pending":
        return None
    payload = dict(pending.payload)
    return {
        "type": "approval_required",
        "approval_id": pending.approval_id,
        "approval_label": payload.get("approval_label"),
        "requirement_id": pending.requirement_id,
        "summary": str(payload.get("summary") or "Approval required before committing staged changes."),
        "rows": list(payload.get("preview_rows") or payload.get("preview") or []),
        "details": dict(payload.get("preview_details") or {}),
        "ledger_revision": pending.ledger_revision,
        "checkpoint_id": pending.checkpoint_id,
        "selected_graph_tool_call": payload.get("selected_graph_tool_call"),
        "source_type": "approval",
    }
