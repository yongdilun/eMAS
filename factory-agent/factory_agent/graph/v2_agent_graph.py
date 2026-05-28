from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from pydantic import Field

from ..config import Settings, get_settings
from ..planning.v2_agent_state import (
    GraphToolCall,
    PendingApprovalState,
    PlannerDecisionRecord,
    PlannerOwnedAgentGraphState,
    ResponseDocumentContext,
    build_initial_planner_owned_agent_graph_state,
    build_uncompiled_planner_owned_agent_graph_state,
    compile_planner_owned_agent_graph_state_semantic_intake,
    validate_graph_state_final_state,
)
from ..planning.v2_capability_map import build_capability_needs_for_text
from ..planning.v2_contracts import (
    CandidateToolWindow,
    ConditionalBranchContract,
    EvidenceLedger,
    EvidenceLedgerEntry,
    HydratedToolCard,
    HydratedToolCards,
    RequirementLedger,
    RequirementLedgerEntry,
    RequirementRevisionRecord,
    RequirementSatisfactionState,
    SatisfactionCheck,
    ToolRetrievalTrace,
    V2ContractModel,
    next_child_requirement_id,
    requirement_child_lineage,
)
from ..planning.v2_evidence_aggregation import aggregate_multi_entity_status_evidence
from ..planning.v2_failed_tool_memory import (
    failed_tool_calls_for_requirement,
    failed_tool_memory_filtered_candidates,
)
from ..planning.v2_graph_adapters import (
    GraphToolExecutionResult,
    GraphToolHttpExecutor,
    execute_graph_tool_call,
    observe_graph_tool_result,
)
from ..planning.v2_interrupts import apply_user_interrupt_to_v2_state, classify_user_interrupt
from ..planning.v2_planner_decisions import (
    PlannerDecisionSubmission,
    PlannerDecisionValidationError,
    record_planner_decision,
    validate_planner_decision,
)
from ..planning.v2_planner_proposer import (
    PlannerDecisionProposalContext,
    PlannerDecisionProposer,
    PlannerDecisionProposerError,
    build_planner_decision_proposer,
)
from ..planning.semantic_intake import build_semantic_intake_proposer
from ..planning.v2_rag_tool import ensure_v2_rag_tool
from ..planning.v2_satisfaction import V2RepeatedRetrievalGuard, apply_deterministic_evidence_satisfaction
from ..planning.v2_tool_retriever import V2CapabilityToolRetriever
from ..planning.tool_selector import ToolSelector
from ..schemas import ToolInfo
from .approval_summary import build_approval_required_payload
from .checkpointing import build_graph_checkpointer
from .v2_graph_approval import (
    PlannerOwnedGraphApprovalPreview,
    _commit_args_from_preview,
    _graph_write_approval_preview,
    _normalize_approval_preview,
    _pending_approval_response_block,
    _pending_staged_tool_calls,
    _staged_write_tool_calls_from_preview,
)
from .v2_graph_interrupts import (
    _apply_graph_revision_evidence_policy,
    _attach_graph_evidence_identity,
    _attach_graph_work_identity,
    _close_graph_after_cancel_interrupt,
    _evidence_can_satisfy_active_revision,
    _invalidate_graph_work_after_interrupt,
    _planner_decision_is_active_for_graph_revision,
    _record_graph_interrupt_revision_trace,
    _record_graph_requirement_update,
    _stale_background_result_reason,
    _store_graph_interrupt_pointer_for_ui,
)
from .v2_graph_response_projection import (
    _evidence_has_no_match,
    _is_document_insufficient_context_evidence,
    _phase6_response_blocks,
    _phase6_response_summary,
    _replan_limit_response_block,
)
from .v2_graph_state_utils import (
    PlannerOwnedAgentGraphRunOptions,
    _checkpoint_config,
    _checkpoint_tuple_id,
    _current_graph_checkpoint_id,
    _graph_checkpoint_identity,
    _graph_checkpoint_identity_for_current_revision,
    _normalize_options,
    _session_context_value,
    _state_update,
)
from .v2_graph_tool_choice import (
    _candidate_tool_calls_for_requirement,
    _capability_need_for_requirement,
    _card_supports_collection_read,
    _deterministic_choose_tool_if_state_proves_bounded_read_batch,
    _deterministic_choose_tool_if_state_proves_single_document_tool,
    _has_candidate_window_for_requirement,
    _has_choice_for_requirement,
    _has_decision_for_requirement,
    _has_execution_decision_for_call,
    _hydrated_card_for_tool_call,
    _hydrated_cards_for_requirement,
    _planner_decision_selected_tool_calls,
    _requirement_by_id,
    _select_graph_tool_card,
    _tool_calls_for_card,
    _tool_choice_requires_graph_approval,
)


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
_REPLAN_SPINE_DIAGNOSTIC_KEY = "replan_spine"
_CHECKPOINTER_UNSET = object()


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


def _trace_tool_names(state: PlannerOwnedAgentGraphState) -> list[str]:
    names: list[str] = []
    for decision in state.planner_decisions[-5:]:
        calls = list(getattr(decision, "selected_tool_calls", None) or [])
        selected = getattr(decision, "selected_tool_call", None)
        if selected is not None:
            calls.append(selected)
        for call in calls:
            tool_name = str(getattr(call, "tool_name", "") or "").strip()
            if tool_name and tool_name not in names:
                names.append(tool_name)
    for evidence in state.evidence_ledger.evidence[-5:]:
        tool_name = str(getattr(evidence, "tool_name", "") or "").strip()
        if tool_name and tool_name not in names:
            names.append(tool_name)
    return names


def _trace_source_types(state: PlannerOwnedAgentGraphState) -> list[str]:
    source_types: list[str] = []
    for evidence in state.evidence_ledger.evidence[-5:]:
        source_type = str(getattr(evidence, "source_type", "") or "").strip()
        if source_type and source_type not in source_types:
            source_types.append(source_type)
    return source_types


def _graph_recursion_limit(settings: Settings) -> int:
    max_replans = max(0, int(getattr(settings, "max_replans", 0) or 0))
    return max(25, 16 + ((max_replans + 1) * 8))


def _replan_retrieval_context_refs(state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
    replan = state.execution_trace.diagnostics.get(_REPLAN_SPINE_DIAGNOSTIC_KEY)
    replan = replan if isinstance(replan, Mapping) else {}
    active_refs = [
        evidence.id
        for evidence in state.evidence_ledger.evidence
        if _evidence_can_satisfy_active_revision(state, evidence)
    ]
    active_ref_set = set(active_refs)
    historical_refs = [
        evidence.id for evidence in state.evidence_ledger.evidence if evidence.id not in active_ref_set
    ]
    return {
        "replan_attempt": int(replan.get("attempt_count") or 0),
        "missing_evidence_reasons": [
            dict(reason)
            for reason in replan.get("missing_evidence_reasons", [])
            if isinstance(reason, Mapping)
        ],
        "failed_tool_calls": [
            dict(call)
            for call in replan.get("failed_tool_calls", [])
            if isinstance(call, Mapping)
        ],
        "active_evidence_refs": active_refs,
        "historical_evidence_refs": historical_refs,
        "stale_attempt_evidence_refs": [
            evidence.id
            for evidence in state.evidence_ledger.evidence
            if evidence.diagnostic_metadata.get("stale_after_graph_replan") is True
        ],
    }


def _capability_need_with_replan_reason(
    capability_need: Any,
    *,
    replan_context_refs: Mapping[str, Any],
) -> Any:
    attempt = int(replan_context_refs.get("replan_attempt") or 0)
    if attempt <= 0 or not hasattr(capability_need, "model_copy"):
        return capability_need
    reasons = [
        reason
        for reason in replan_context_refs.get("missing_evidence_reasons", [])
        if isinstance(reason, Mapping)
    ]
    primary_reason = str(reasons[-1].get("reason") if reasons else "missing_evidence").strip()
    return capability_need.model_copy(
        update={
            "reason": f"replan_spine:attempt_{attempt}:{primary_reason}",
        }
    )


@dataclass
class LocalPlannerOwnedGraphTracer:
    events: list[dict[str, Any]] = field(default_factory=list)
    on_node_recorded: Callable[[dict[str, Any]], Any] | None = None

    def record_node(self, node_name: str, state: PlannerOwnedAgentGraphState) -> None:
        diagnostics = state.execution_trace.diagnostics
        replan_spine = diagnostics.get(_REPLAN_SPINE_DIAGNOSTIC_KEY) if isinstance(diagnostics, Mapping) else None
        event = {
            "event": "planner_owned_agent_graph_node",
            "node": node_name,
            "ledger_revision": state.requirement_ledger.revision,
            "planner_decision_count": len(state.planner_decisions),
            "evidence_count": len(state.evidence_ledger.evidence),
            "tool_names": _trace_tool_names(state),
            "source_types": _trace_source_types(state),
        }
        if isinstance(replan_spine, Mapping):
            event["replan_spine"] = dict(replan_spine)
        self.events.append(event)
        if self.on_node_recorded is not None:
            self.on_node_recorded(dict(event))


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
        session_id: str | None = None,
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
        self._session_id = session_id
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
        replan_context_refs = _replan_retrieval_context_refs(state)
        capability_need = _capability_need_with_replan_reason(
            capability_need,
            replan_context_refs=replan_context_refs,
        )
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
                **replan_context_refs,
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
    ) -> GraphToolCall | list[GraphToolCall]:
        requirement_id = decision.requirement_id
        if requirement_id is None:
            raise ValueError("choose_tool transition requires a requirement id")
        requirement = _requirement_by_id(state, requirement_id)
        cards = _hydrated_cards_for_requirement(state, requirement_id)
        if requirement is None or not cards:
            raise ValueError("choose_tool transition requires hydrated cards")
        card = _select_graph_tool_card(requirement, cards)
        capability_need = decision.capability_need or _capability_need_for_requirement(state, requirement_id)
        return _tool_calls_for_card(
            state=state,
            card=card,
            requirement=requirement,
            capability_need=capability_need,
            requirement_id=requirement_id,
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
            session_id=self._session_id,
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
        return await _graph_write_approval_preview(
            settings=self._settings,
            state=state,
            tool_call=tool_call,
            requirement=requirement,
            card=card,
            cards=_hydrated_cards_for_requirement(state, tool_call.requirement_id),
            tools_by_name=self.tools_by_name,
            http_executor=self._http_executor,
            supports_collection_read=_card_supports_collection_read,
        )

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
        proposer: PlannerDecisionProposer | None = None,
        checkpointer: Any = _CHECKPOINTER_UNSET,
        tracer: LocalPlannerOwnedGraphTracer | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._adapters = adapters or PlannerOwnedAgentGraphAdapters(settings=self._settings)
        self._proposer = proposer or build_planner_decision_proposer(self._settings)
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
        state = build_uncompiled_planner_owned_agent_graph_state(
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
        checkpoint_config.setdefault("recursion_limit", _graph_recursion_limit(self._settings))
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
        saved_config = await self._compiled_graph.aupdate_state(
            checkpoint_config,
            _state_update(state),
            as_node="response_document_node",
        )
        state.execution_trace.diagnostics["phase8_resume_checkpoint"]["saved_checkpoint_config"] = saved_config
        return PlannerOwnedGraphResult(
            state=state,
            node_order=node_order,
            checkpoint_config=saved_config,
            trace_events=list(self._tracer.events[event_start:]),
        )

    async def interrupt_with_user_message(
        self,
        session_context: Mapping[str, Any] | Any,
        new_user_message: str,
        options: PlannerOwnedAgentGraphRunOptions | Mapping[str, Any] | None = None,
    ) -> PlannerOwnedGraphResult:
        if self._checkpointer is None:
            raise ValueError("planner-owned graph interruption requires a LangGraph checkpointer")

        normalized_options = _normalize_options(options)
        checkpoint_config = _checkpoint_config(normalized_options, session_context=session_context)
        event_start = len(self._tracer.events)
        state, checkpoint_tuple = await self._load_checkpoint_state(checkpoint_config)
        previous_revision = state.requirement_ledger.revision
        previous_checkpoint_identity = dict(
            state.execution_trace.diagnostics.get("graph_checkpoint_identity")
            or _graph_checkpoint_identity(checkpoint_config, ledger_revision=previous_revision)
        )
        loaded_checkpoint_id = _checkpoint_tuple_id(checkpoint_tuple)
        pending_before = state.pending_approval.model_copy(deep=True)
        old_evidence_ids = [evidence.id for evidence in state.evidence_ledger.evidence]

        interrupt = classify_user_interrupt(
            new_user_message,
            session_status=str(_session_context_value(session_context, "status") or ""),
            awaiting_approval=state.pending_approval.status == "pending",
            previous_goal=state.requirement_ledger.user_goal,
            target_requirement_id=_session_context_value(session_context, "target_requirement_id"),
            approval_id=state.pending_approval.approval_id,
            created_from_revision=previous_revision,
        )
        loop_state = state.as_loop_compat_state()
        apply_user_interrupt_to_v2_state(loop_state, interrupt, capability_map=state.capability_map)
        if loop_state.requirement_ledger is not None:
            state.requirement_ledger = loop_state.requirement_ledger
            state.original_query = state.requirement_ledger.user_goal
        state.evidence_ledger = loop_state.evidence_ledger
        state.satisfaction_state = loop_state.satisfaction_state
        state.final_validation_result = loop_state.final_validation_result
        state.revision_history = loop_state.revision_history
        state.execution_trace = loop_state.execution_trace

        carry_forward_refs = _explicit_carried_forward_evidence_refs(
            session_context=session_context,
            options=normalized_options,
        )
        evidence_policy = _apply_graph_revision_evidence_policy(
            state,
            previous_revision=previous_revision,
            old_evidence_ids=old_evidence_ids,
            carry_forward_evidence_refs=carry_forward_refs,
        )
        stale_work = _invalidate_graph_work_after_interrupt(
            state,
            interrupt=interrupt,
            previous_revision=previous_revision,
            previous_checkpoint_identity=previous_checkpoint_identity,
            pending_before=pending_before,
        )
        if interrupt.interrupt_type == "cancel_current_run":
            _close_graph_after_cancel_interrupt(state, interrupt)

        new_checkpoint_identity = _graph_checkpoint_identity(
            checkpoint_config,
            ledger_revision=state.requirement_ledger.revision,
        )
        state.execution_trace.diagnostics["graph_checkpoint_identity"] = new_checkpoint_identity
        _record_graph_interrupt_revision_trace(
            state,
            interrupt=interrupt,
            previous_revision=previous_revision,
            loaded_checkpoint_id=loaded_checkpoint_id,
            previous_checkpoint_identity=previous_checkpoint_identity,
            new_checkpoint_identity=new_checkpoint_identity,
            evidence_policy=evidence_policy,
            stale_work=stale_work,
        )
        _store_graph_interrupt_pointer_for_ui(
            session_context,
            interrupt=interrupt,
            previous_revision=previous_revision,
            current_revision=state.requirement_ledger.revision,
            previous_checkpoint_identity=previous_checkpoint_identity,
            current_checkpoint_identity=new_checkpoint_identity,
        )

        await self._response_document_node(state)
        saved_config = await self._compiled_graph.aupdate_state(
            checkpoint_config,
            _state_update(state),
            as_node="response_document_node",
        )
        state.execution_trace.diagnostics["phase9_interruption_revision"]["saved_checkpoint_config"] = saved_config
        return PlannerOwnedGraphResult(
            state=state,
            node_order=list(state.execution_trace.diagnostics.get("phase3_node_order") or []),
            checkpoint_config=saved_config,
            trace_events=list(self._tracer.events[event_start:]),
        )

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
        graph.add_conditional_edges(
            "satisfaction_node",
            self._route_after_satisfaction,
            {
                "replan": "planner_decision_node",
                "continue": "approval_node",
            },
        )
        graph.add_edge("approval_node", "finalize_node")
        graph.add_edge("finalize_node", "response_document_node")
        graph.add_edge("response_document_node", END)
        if self._checkpointer is None:
            return graph.compile()
        return graph.compile(checkpointer=self._checkpointer)

    def _route_after_satisfaction(self, state: PlannerOwnedAgentGraphState) -> str:
        replan = state.execution_trace.diagnostics.get(_REPLAN_SPINE_DIAGNOSTIC_KEY)
        if isinstance(replan, Mapping) and replan.get("route") == "planner_decision_node":
            return "replan"
        if _open_requirements_need_fresh_retrieval(state):
            return "replan"
        return "continue"

    async def _semantic_intake_node(
        self,
        state: PlannerOwnedAgentGraphState,
        config: RunnableConfig | None = None,
    ) -> dict[str, Any]:
        if _semantic_intake_should_compile_in_node(state):
            prior_diagnostics = dict(state.execution_trace.diagnostics)
            compiled_state = compile_planner_owned_agent_graph_state_semantic_intake(
                state,
                semantic_intake_proposer=build_semantic_intake_proposer(
                    self._settings,
                    parent_run_config=config,
                ),
            )
            _preserve_preinvoke_graph_diagnostics(compiled_state, prior_diagnostics)
            semantic_diagnostics = compiled_state.execution_trace.diagnostics.get("semantic_intake")
            if isinstance(semantic_diagnostics, dict):
                semantic_diagnostics["status"] = "compiled_in_langgraph_node"
                semantic_diagnostics["runs_inside_langgraph_node"] = True
            _record_node_visit(compiled_state, "semantic_intake_node", self._tracer)
            compiled_state.execution_trace.planner.diagnostics["semantic_intake"] = {
                "original_query_present": bool(compiled_state.original_query.strip()),
                "phase": "phase5_execution_observation",
                "compiled_in_langgraph_node": True,
            }
            return _state_update(compiled_state)

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

    async def _propose_and_record_planner_decision(
        self,
        state: PlannerOwnedAgentGraphState,
        context: PlannerDecisionProposalContext,
        *,
        node_name: str,
    ) -> PlannerDecisionRecord | None:
        state.execution_trace.planner.call_count += 1
        try:
            proposal = await _maybe_await(
                self._proposer.propose_decision(state=state, context=context)
            )
            submission = proposal.submission.model_copy(
                update={"candidate_tool_calls": list(context.candidate_tool_calls)},
                deep=True,
            )
            validation = record_planner_decision(state, submission)
        except (PlannerDecisionProposerError, PlannerDecisionValidationError, ValueError) as exc:
            diagnostics = getattr(exc, "diagnostics", {}) or {}
            _record_planner_proposer_rejection(
                state,
                node_name=node_name,
                context=context,
                reason=str(exc),
                diagnostics=diagnostics,
            )
            return None

        decision = submission.decision
        _record_planner_proposer_acceptance(
            state,
            node_name=node_name,
            context=context,
            decision=decision,
            validation_diagnostics=validation.diagnostics,
            proposer_diagnostics=proposal.diagnostics,
        )
        if (
            decision.decision_kind == "revise_requirements"
            and submission.proposed_requirement_ledger is not None
        ):
            _apply_planner_proposed_requirement_ledger(state, submission.proposed_requirement_ledger)
        return decision

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
            decision = await self._propose_and_record_planner_decision(
                state,
                PlannerDecisionProposalContext(
                    decision_id=f"dec-retrieve-{len(state.planner_decisions) + 1:03d}",
                    requested_decision_kind="retrieve_tools",
                    allowed_decision_kinds=[
                        "retrieve_tools",
                        "revise_requirements",
                        "request_clarification",
                        "finalize",
                        "fail",
                    ],
                    requirement_id=requirement.id,
                    capability_need=need,
                    reason="Declare the next bounded retrieval need.",
                ),
                node_name="planner_decision_node",
            )
            if decision is None:
                continue
            if decision.decision_kind != "retrieve_tools":
                decisions.append(decision)
                continue
            decisions.append(decision)

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
            and _planner_decision_is_active_for_graph_revision(state, decision)
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
            state.execution_trace.tool_retrieval.reranker.call_count += retrieval.trace.reranker.call_count
            state.execution_trace.tool_retrieval.compatibility_fallback_used = (
                state.execution_trace.tool_retrieval.compatibility_fallback_used
                or retrieval.trace.compatibility_fallback_used
            )

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
            and _planner_decision_is_active_for_graph_revision(state, decision)
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
            candidate_tool_calls = _candidate_tool_calls_for_requirement(
                state,
                requirement_id=retrieve_decision.requirement_id,
                capability_need=retrieve_decision.capability_need,
            )
            candidate_tool_calls = _candidate_tool_calls_after_failed_memory(
                state,
                requirement_id=retrieve_decision.requirement_id,
                candidate_tool_calls=candidate_tool_calls,
            )
            decision_id = f"dec-choose-{len(state.planner_decisions) + 1:03d}"
            decision = _deterministic_choose_tool_if_state_proves_bounded_read_batch(
                state=state,
                retrieve_decision=retrieve_decision,
                candidate_tool_calls=candidate_tool_calls,
                decision_id=decision_id,
            )
            if decision is None:
                decision = _deterministic_choose_tool_if_state_proves_single_document_tool(
                    state=state,
                    retrieve_decision=retrieve_decision,
                    candidate_tool_calls=candidate_tool_calls,
                    decision_id=decision_id,
                )
            if decision is not None:
                validation = validate_planner_decision(state, decision)
                if validation.accepted:
                    record_planner_decision(state, decision)
                else:
                    decision = None
            if decision is None:
                decision = await self._propose_and_record_planner_decision(
                    state,
                    PlannerDecisionProposalContext(
                        decision_id=decision_id,
                        requested_decision_kind="choose_tool",
                        allowed_decision_kinds=[
                            "choose_tool",
                            "revise_requirements",
                            "request_clarification",
                            "fail",
                        ],
                        requirement_id=retrieve_decision.requirement_id,
                        capability_need=retrieve_decision.capability_need,
                        candidate_tool_calls=candidate_tool_calls,
                        prior_decision_id=retrieve_decision.decision_id,
                        reason="Select an executable action from the hydrated candidate window.",
                    ),
                    node_name="planner_choose_tool_node",
                )
            if decision is None:
                continue
            if decision.selected_tool_call is not None:
                decision.selected_tool_call.decision_id = decision.decision_id
                state.execution_trace.selected_tool_names = list(
                    dict.fromkeys(
                        [
                            *state.execution_trace.selected_tool_names,
                            decision.selected_tool_call.tool_name,
                        ]
                    )
                )
            for tool_call in decision.selected_tool_calls:
                tool_call.decision_id = decision.decision_id
                state.execution_trace.selected_tool_names = list(
                    dict.fromkeys([*state.execution_trace.selected_tool_names, tool_call.tool_name])
                )
            decisions.append(decision)

        state.execution_trace.planner.diagnostics["planner_choose_tool_node"] = {
            "decision_count": len(decisions),
            "decision_ids": [decision.decision_id for decision in decisions],
            "tool_names": [
                tool_call.tool_name
                for decision in decisions
                for tool_call in _planner_decision_selected_tool_calls(decision)
            ],
            "batched_tool_call_count": sum(
                len(_planner_decision_selected_tool_calls(decision)) for decision in decisions
            ),
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
        pending_execution = state.execution_trace.diagnostics.get(_PENDING_EXECUTION_DIAGNOSTIC_KEY)
        if isinstance(pending_execution, Mapping) and pending_execution.get("status") == "observed_by_next_node":
            state.execution_trace.diagnostics["phase9_background_work"] = {
                "status": "awaiting_observation",
                "stale_check_deferred_to_evidence_observation": True,
            }
            return _state_update(state)

        choose_decisions = [
            decision
            for decision in state.planner_decisions
            if decision.decision_kind == "choose_tool"
            and _planner_decision_is_active_for_graph_revision(state, decision)
            and _planner_decision_selected_tool_calls(decision)
            and not _has_evidence_for_requirement(
                state,
                _planner_decision_selected_tool_calls(decision)[0].requirement_id,
            )
            and not all(
                _has_execution_decision_for_call(state, tool_call)
                for tool_call in _planner_decision_selected_tool_calls(decision)
            )
        ]
        if not choose_decisions:
            state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY] = {"status": "no_tool_choice"}
            return _state_update(state)

        executions: list[GraphToolExecutionResult] = []
        action_events: list[dict[str, Any]] = []
        for choose_decision in choose_decisions:
            selected_calls = [
                tool_call
                for tool_call in _planner_decision_selected_tool_calls(choose_decision)
                if not _has_execution_decision_for_call(state, tool_call)
            ]
            if not selected_calls:
                continue
            if len(selected_calls) > 1:
                guard_decision = PlannerDecisionRecord(
                    decision_id=f"dec-execute-{len(state.planner_decisions) + 1:03d}",
                    decision_kind="execute_parallel_read_batch",
                    author="deterministic_guard",
                    requirement_id=choose_decision.requirement_id,
                    ledger_revision=state.requirement_ledger.revision,
                    capability_need=choose_decision.capability_need,
                    selected_tool_calls=selected_calls,
                    reason="Execute the persisted planner-selected read batch.",
                )
                record_planner_decision(state, guard_decision)
                for selected_call in selected_calls:
                    execution_decision = guard_decision.model_copy(
                        update={"selected_tool_call": selected_call, "selected_tool_calls": []}
                    )
                    execution = await _maybe_await(self._adapters.execute_tool(state, execution_decision))
                    _attach_graph_work_identity(state, execution)
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
                continue

            selected_call = selected_calls[0]
            if _tool_choice_requires_graph_approval(state, choose_decision):
                await self._stage_write_approval(state, choose_decision)
                if state.pending_approval.status != "pending" and _write_choice_finished_without_pending_approval(
                    state,
                    choose_decision,
                ):
                    continue
                return _state_update(state)

            guard_decision = PlannerDecisionRecord(
                decision_id=f"dec-execute-{len(state.planner_decisions) + 1:03d}",
                decision_kind="execute_tool",
                author="deterministic_guard",
                requirement_id=choose_decision.requirement_id,
                ledger_revision=state.requirement_ledger.revision,
                capability_need=choose_decision.capability_need,
                selected_tool_call=selected_call,
                reason="Execute the persisted planner-selected read action.",
            )
            record_planner_decision(state, guard_decision)
            execution = await _maybe_await(self._adapters.execute_tool(state, guard_decision))
            _attach_graph_work_identity(state, execution)
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
        ignored_results: list[dict[str, Any]] = []
        for raw_execution in raw_executions:
            execution = GraphToolExecutionResult.model_validate(raw_execution)
            stale = _stale_background_result_reason(state, execution)
            if stale is not None:
                ignored_results.append(
                    {
                        "tool_call_id": execution.tool_call.call_id,
                        "tool_name": execution.tool_call.tool_name,
                        "requirement_id": execution.tool_call.requirement_id,
                        "reason": stale,
                        "result_ledger_revision": execution.diagnostic_metadata.get("ledger_revision"),
                        "active_ledger_revision": state.requirement_ledger.revision,
                        "result_checkpoint_id": execution.diagnostic_metadata.get("checkpoint_id"),
                        "active_checkpoint_id": _current_graph_checkpoint_id(state),
                    }
                )
                continue
            evidence = await _maybe_await(self._adapters.observe_tool_result(state, execution))
            _attach_graph_evidence_identity(state, evidence)
            state.evidence_ledger.evidence.append(evidence)
            evidence_items.append(evidence)
        if ignored_results:
            previous_ignored = list(state.execution_trace.diagnostics.get("stale_background_results_ignored") or [])
            state.execution_trace.diagnostics["stale_background_results_ignored"] = [
                *previous_ignored,
                *ignored_results,
            ]
        if not evidence_items:
            state.execution_trace.diagnostics["evidence_observation"] = {
                "status": "ignored_stale_background_result" if ignored_results else "no_pending_execution",
                "ignored_results": ignored_results,
                "stale_background_results_ignored": bool(ignored_results),
                "stale_checked_by_graph_revision_and_checkpoint": bool(ignored_results),
            }
            state.execution_trace.diagnostics.pop(_PENDING_EXECUTION_DIAGNOSTIC_KEY, None)
            return _state_update(state)
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
        aggregated = aggregate_multi_entity_status_evidence(
            requirement_ledger=state.requirement_ledger,
            evidence_ledger=state.evidence_ledger,
            diagnostic_metadata={
                "graph_execution_authority": True,
                "graph_evidence_aggregation": True,
                "direct_v2_execution": False,
            },
            replace=False,
        )
        if aggregated:
            executed_requirement_ids = {evidence.requirement_id for evidence in evidence_items}
            evidence_items = [
                evidence
                for evidence in state.evidence_ledger.evidence
                if evidence.requirement_id in executed_requirement_ids
                and _evidence_can_satisfy_active_revision(state, evidence)
            ]
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
            "ignored_results": ignored_results,
            "stale_checked_by_graph_revision_and_checkpoint": True,
            "multi_entity_evidence_aggregated": aggregated,
        }
        if len(evidence_items) == 1:
            state.execution_trace.diagnostics["evidence_observation"].update(
                {
                    "evidence_ref": evidence_items[0].id,
                    "source_type": evidence_items[0].source_type,
                    "source_of_truth": evidence_items[0].source_of_truth,
                }
            )
        _evaluate_conditional_branches_from_evidence(state, evidence_items)
        _expand_child_requirements_from_evidence(state, evidence_items)
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
        historical_evidence = state.evidence_ledger
        loop_state = state.as_loop_compat_state()
        active_evidence = [
            evidence
            for evidence in historical_evidence.evidence
            if _evidence_can_satisfy_active_revision(state, evidence)
        ]
        loop_state.evidence_ledger = EvidenceLedger(evidence=active_evidence)
        apply_deterministic_evidence_satisfaction(loop_state)
        state.requirement_ledger = loop_state.requirement_ledger or state.requirement_ledger
        state.satisfaction_state = loop_state.satisfaction_state
        state.revision_history = loop_state.revision_history
        state.execution_trace = loop_state.execution_trace
        state.evidence_ledger = historical_evidence
        state.execution_trace.diagnostics["phase9_active_revision_evidence"] = {
            "active_evidence_refs": [evidence.id for evidence in active_evidence],
            "historical_evidence_refs": [
                evidence.id
                for evidence in historical_evidence.evidence
                if evidence.id not in {active.id for active in active_evidence}
            ],
            "stale_evidence_excluded_from_satisfaction": any(
                not _evidence_can_satisfy_active_revision(state, evidence)
                for evidence in historical_evidence.evidence
            ),
        }
        validate_graph_state_final_state(state)
        current_missing_reasons = _current_missing_evidence_reasons(state)
        _prepare_replan_spine_after_satisfaction(
            state,
            current_missing_reasons=current_missing_reasons,
            max_attempts=max(0, int(getattr(self._settings, "max_replans", 0) or 0)),
        )
        _retain_replan_missing_evidence_reason_history(state)
        _refresh_replan_evidence_diagnostics(state)
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
            active_evidence_refs = [
                evidence.id
                for evidence in state.evidence_ledger.evidence
                if _evidence_can_satisfy_active_revision(state, evidence)
            ]
            decision = PlannerDecisionRecord(
                decision_id=f"dec-finalize-{len(state.planner_decisions) + 1:03d}",
                decision_kind="finalize",
                author="deterministic_guard",
                ledger_revision=state.requirement_ledger.revision,
                evidence_refs=active_evidence_refs,
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
        replan_spine = _response_replan_spine_diagnostics(state)
        replan_limit_safe_failure = validation_status != "passed" and replan_spine.get("replan_limit_reached")
        if replan_limit_safe_failure:
            response_blocks = [_replan_limit_response_block(state, replan_spine)]
        if state.pending_approval.status == "pending":
            approval_block = _pending_approval_response_block(state)
            if approval_block is not None:
                response_blocks.append(approval_block)
        response_summary = _phase6_response_summary(state, response_blocks)
        pending = state.pending_approval.status == "pending"
        graph_write_activity = _has_graph_write_activity(state)
        active_evidence_refs = [
            evidence.id
            for evidence in state.evidence_ledger.evidence
            if _evidence_can_satisfy_active_revision(state, evidence)
        ]
        historical_evidence_refs = [
            evidence.id
            for evidence in state.evidence_ledger.evidence
            if evidence.id not in set(active_evidence_refs)
        ]
        response_evidence_refs = [] if replan_limit_safe_failure else active_evidence_refs
        child_lineage = requirement_child_lineage(state.requirement_ledger)
        state.response_document_context = ResponseDocumentContext(
            state="draft" if pending or validation_status == "deferred" else ("rendered" if validation_status == "passed" else "failed"),
            document_id=(
                f"phase8-response-{uuid4().hex[:12]}"
                if graph_write_activity
                else f"phase7-response-{uuid4().hex[:12]}"
            ),
            revision=state.requirement_ledger.revision,
            requirement_ids=[requirement.id for requirement in state.requirement_ledger.requirements],
            evidence_refs=response_evidence_refs,
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
                "active_evidence_refs": active_evidence_refs,
                "active_final_evidence_refs": active_evidence_refs,
                "response_evidence_refs": response_evidence_refs,
                "historical_evidence_refs": historical_evidence_refs,
                "child_requirement_lineage": child_lineage,
                "conditional_branches": [
                    branch.model_dump(mode="json")
                    for branch in state.requirement_ledger.conditional_branches
                ],
                "answer_instructions": [
                    instruction.model_dump(mode="json")
                    for instruction in state.requirement_ledger.answer_instructions
                ],
                "clarification_needs": [
                    need.model_dump(mode="json")
                    for need in state.requirement_ledger.clarification_needs
                ],
                "stale_evidence_excluded_from_active_revision": bool(historical_evidence_refs),
                "replan_limit_reached": bool(replan_spine.get("replan_limit_reached")),
                "replan_spine": replan_spine,
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

        approval_index = _next_approval_index(state)
        approval_label = f"Approval {approval_index}"
        request_decision = await self._propose_and_record_planner_decision(
            state,
            PlannerDecisionProposalContext(
                decision_id=f"dec-approval-{len(state.planner_decisions) + 1:03d}",
                requested_decision_kind="request_approval",
                allowed_decision_kinds=[
                    "request_approval",
                    "revise_requirements",
                    "request_clarification",
                    "fail",
                ],
                requirement_id=requirement.id,
                capability_need=choose_decision.capability_need,
                candidate_tool_calls=[call],
                prior_decision_id=choose_decision.decision_id,
                reason="Request approval before committing a graph-selected write action.",
            ),
            node_name="approval_node",
        )
        if request_decision is None or request_decision.decision_kind != "request_approval":
            state.execution_trace.diagnostics["phase8_approval_staging"] = {
                "status": "not_authorized_by_planner_proposer",
                "requirement_id": requirement.id,
                "source_decision_id": choose_decision.decision_id,
                "accepted_decision_kind": (
                    request_decision.decision_kind if request_decision is not None else None
                ),
            }
            return

        preview = await self._adapters.build_approval_preview(state, call, requirement, card)
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

        staged_tool_calls = _staged_write_tool_calls_from_preview(
            state=state,
            base_call=call,
            card=card,
            requirement=requirement,
            preview=preview,
        )
        if staged_tool_calls:
            call.args = dict(staged_tool_calls[0].args)
        else:
            if preview.commit_args:
                call.args.update(preview.commit_args)
            else:
                call.args.update(_commit_args_from_preview(card=card, requirement=requirement, rows=preview.rows))
            staged_tool_calls = [call]

        staged_choose_decision_ids: list[str] = []
        for staged_call in staged_tool_calls:
            staged_choose = PlannerDecisionRecord(
                decision_id=f"dec-choose-{len(state.planner_decisions) + 1:03d}",
                decision_kind="choose_tool",
                author="system",
                requirement_id=requirement.id,
                ledger_revision=state.requirement_ledger.revision,
                capability_need=choose_decision.capability_need,
                selected_tool_call=staged_call,
                reason="Graph expands an approval preview row into an exact staged write call.",
                diagnostics={
                    "approval_preview_expansion": True,
                    "source_decision_id": choose_decision.decision_id,
                },
            )
            record_planner_decision(state, staged_choose)
            staged_call.decision_id = staged_choose.decision_id
            staged_choose_decision_ids.append(staged_choose.decision_id)

        request_decision.diagnostics["approval_index"] = approval_index
        request_decision.diagnostics["approval_label"] = approval_label
        request_decision.diagnostics["approval_node"] = "approval_node"
        request_decision.diagnostics["staged_tool_call_count"] = len(staged_tool_calls)
        staged = [
            {
                "tool_name": staged_call.tool_name,
                "args": dict(staged_call.args),
                "output_ref": staged_call.call_id,
                "requirement_id": requirement.id,
            }
            for staged_call in staged_tool_calls
        ]
        payload = build_approval_required_payload(staged, intent_text=state.original_query)
        checkpoint_identity = _graph_checkpoint_identity_for_current_revision(state)
        state.execution_trace.diagnostics["graph_checkpoint_identity"] = checkpoint_identity
        payload.update(
            {
                "kind": "graph_write_approval_required",
                "approval_index": approval_index,
                "approval_label": approval_label,
                "ledger_revision": state.requirement_ledger.revision,
                "requirement_ledger_revision": state.requirement_ledger.revision,
                "graph_checkpoint_identity": checkpoint_identity,
                "checkpoint_id": checkpoint_identity.get("checkpoint_id"),
                "selected_graph_tool_call": staged_tool_calls[0].model_dump(mode="json"),
                "staged_graph_tool_calls": [
                    staged_call.model_dump(mode="json") for staged_call in staged_tool_calls
                ],
                "staged_graph_tool_decision_ids": staged_choose_decision_ids,
                "selected_graph_tool_decision_id": choose_decision.decision_id,
                "approval_decision_id": request_decision.decision_id,
                "requirement_id": requirement.id,
                "preview_rows": preview.rows,
                "preview_details": dict(preview.details),
                "excluded_rows": preview.excluded_rows,
                "locked_constraints": dict(getattr(requirement, "constraints", {}) or {}),
                "entity_type": getattr(requirement, "entity", None),
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
            tool_call=staged_tool_calls[0],
            payload=payload,
        )
        state.execution_trace.diagnostics["phase8_approval_staging"] = {
            "status": "paused_at_approval_node",
            "approval_id": approval_id,
            "approval_label": approval_label,
            "requirement_id": requirement.id,
            "ledger_revision": state.requirement_ledger.revision,
            "checkpoint_id": state.pending_approval.checkpoint_id,
            "selected_graph_tool_call": staged_tool_calls[0].model_dump(mode="json"),
            "staged_graph_tool_call_count": len(staged_tool_calls),
            "preview_row_count": len(preview.rows),
            "excluded_row_count": len(preview.excluded_rows),
            "legacy_shortcut_used": False,
        }

    async def _stage_next_write_approval_if_needed(self, state: PlannerOwnedAgentGraphState) -> None:
        for choose_decision in state.planner_decisions:
            if (
                choose_decision.decision_kind == "choose_tool"
                and _planner_decision_is_active_for_graph_revision(state, choose_decision)
                and choose_decision.selected_tool_call is not None
                and not _has_evidence_for_requirement(state, choose_decision.selected_tool_call.requirement_id)
                and _tool_choice_requires_graph_approval(state, choose_decision)
            ):
                _record_node_visit(state, "tool_execution_node", self._tracer)
                await self._stage_write_approval(state, choose_decision)
                if state.pending_approval.status != "pending" and _write_choice_finished_without_pending_approval(
                    state,
                    choose_decision,
                ):
                    continue
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
        _record_node_visit(state, "tool_execution_node", self._tracer)
        staged_calls = _pending_staged_tool_calls(pending, fallback=call)
        executions: list[GraphToolExecutionResult] = []
        action_events: list[dict[str, Any]] = []
        for staged_call in staged_calls:
            guard_decision = PlannerDecisionRecord(
                decision_id=f"dec-execute-{len(state.planner_decisions) + 1:03d}",
                decision_kind="execute_tool",
                author="deterministic_guard",
                requirement_id=staged_call.requirement_id,
                ledger_revision=state.requirement_ledger.revision,
                capability_need=need,
                selected_tool_call=staged_call,
                reason="Execute graph-staged write after matching approval evidence.",
            )
            record_planner_decision(state, guard_decision)
            execution = await _maybe_await(self._adapters.execute_tool(state, guard_decision))
            _attach_graph_work_identity(state, execution)
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
                    "approval_id": pending.approval_id,
                    "legacy_shortcut_used": False,
                }
            )
        state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY] = {
            "status": "observed_by_next_node",
            "execution_results": [execution.model_dump(mode="json") for execution in executions],
            "approval_id": pending.approval_id,
        }
        if len(executions) == 1:
            state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY]["execution_result"] = (
                executions[0].model_dump(mode="json")
            )
        previous_actions = list(state.execution_trace.diagnostics.get("graph_tool_actions") or [])
        state.execution_trace.diagnostics["graph_tool_actions"] = [*previous_actions, *action_events]
        await self._evidence_observation_node(state)
        api_evidence = [
            evidence
            for evidence in state.evidence_ledger.evidence
            if evidence.requirement_id == call.requirement_id
            and evidence.source_type == "api_tool"
            and _evidence_can_satisfy_active_revision(state, evidence)
        ]
        execution_ok = bool(executions) and all(execution.ok for execution in executions)
        if requirement is not None and api_evidence:
            _record_graph_requirement_update(
                state,
                requirement,
                status="satisfied" if execution_ok else "failed",
                evidence_refs=[approval_evidence.id, *[evidence.id for evidence in api_evidence]],
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
                        actual=[evidence.normalized_result.get("status_code") for evidence in api_evidence],
                        actual_count=len(api_evidence),
                        passed=execution_ok,
                        evidence_ref=api_evidence[-1].id,
                    ),
                ],
                reason="approval_evidence_and_write_result" if execution_ok else "approved_write_failed",
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


def _record_planner_proposer_acceptance(
    state: PlannerOwnedAgentGraphState,
    *,
    node_name: str,
    context: PlannerDecisionProposalContext,
    decision: PlannerDecisionRecord,
    validation_diagnostics: Mapping[str, Any],
    proposer_diagnostics: Mapping[str, Any],
) -> None:
    trace = state.execution_trace.planner.diagnostics.setdefault(
        "planner_decision_proposer",
        {"accepted": [], "rejected": []},
    )
    if not isinstance(trace, dict):
        trace = {"accepted": [], "rejected": []}
        state.execution_trace.planner.diagnostics["planner_decision_proposer"] = trace
    accepted = trace.setdefault("accepted", [])
    if isinstance(accepted, list):
        accepted.append(
            {
                "node": node_name,
                "decision_id": decision.decision_id,
                "decision_kind": decision.decision_kind,
                "requirement_id": decision.requirement_id,
                "requested_decision_kind": context.requested_decision_kind,
                "adapter": proposer_diagnostics.get("adapter"),
                "llm_invoked": proposer_diagnostics.get("llm_invoked"),
                "offline_contract_mode": proposer_diagnostics.get("offline_contract_mode"),
                "real_llm_mode": proposer_diagnostics.get("real_llm_mode"),
                "openai_compatible_planner_adapter": proposer_diagnostics.get(
                    "openai_compatible_planner_adapter"
                ),
                "model_name": proposer_diagnostics.get("model_name"),
                "base_url_type": proposer_diagnostics.get("base_url_type"),
                "base_url_configured": proposer_diagnostics.get("base_url_configured"),
                "bounded_state_view": proposer_diagnostics.get("bounded_state_view"),
                "full_openapi_catalog_visible": proposer_diagnostics.get("full_openapi_catalog_visible"),
                "validation": dict(validation_diagnostics),
            }
        )


def _record_planner_proposer_rejection(
    state: PlannerOwnedAgentGraphState,
    *,
    node_name: str,
    context: PlannerDecisionProposalContext,
    reason: str,
    diagnostics: Mapping[str, Any],
) -> None:
    trace = state.execution_trace.planner.diagnostics.setdefault(
        "planner_decision_proposer",
        {"accepted": [], "rejected": []},
    )
    if not isinstance(trace, dict):
        trace = {"accepted": [], "rejected": []}
        state.execution_trace.planner.diagnostics["planner_decision_proposer"] = trace
    rejected = trace.setdefault("rejected", [])
    event = {
        "node": node_name,
        "decision_id": context.decision_id,
        "requested_decision_kind": context.requested_decision_kind,
        "allowed_decision_kinds": list(context.allowed_decision_kinds),
        "requirement_id": context.requirement_id,
        "reason": reason,
        "diagnostics": dict(diagnostics),
        "adapter": diagnostics.get("adapter"),
        "llm_invoked": diagnostics.get("llm_invoked"),
        "offline_contract_mode": diagnostics.get("offline_contract_mode"),
        "real_llm_mode": diagnostics.get("real_llm_mode"),
        "model_name": diagnostics.get("model_name"),
        "base_url_type": diagnostics.get("base_url_type"),
        "fail_closed": True,
        "tool_execution_allowed": False,
    }
    if isinstance(rejected, list):
        rejected.append(event)
    state.execution_trace.planner.diagnostics[node_name] = {
        "decision": "rejected",
        "reason": reason,
        "fail_closed": True,
        "tool_execution_allowed": False,
    }


def _apply_planner_proposed_requirement_ledger(
    state: PlannerOwnedAgentGraphState,
    proposed: RequirementLedger,
) -> None:
    previous_revision = state.requirement_ledger.revision
    state.requirement_ledger = proposed
    state.revision_history = list(proposed.revision_history)
    state.response_document_context = state.response_document_context.model_copy(
        update={
            "revision": proposed.revision,
            "requirement_ids": [requirement.id for requirement in proposed.requirements],
        }
    )
    state.execution_trace.diagnostics["planner_requirement_revision"] = {
        "previous_revision": previous_revision,
        "current_revision": proposed.revision,
        "author": "planner",
        "accepted_through_proposer": True,
    }


def _evaluate_conditional_branches_from_evidence(
    state: PlannerOwnedAgentGraphState,
    evidence_items: list[EvidenceLedgerEntry],
) -> None:
    pending = [
        branch
        for branch in state.requirement_ledger.conditional_branches
        if branch.status == "pending"
    ]
    if not pending:
        return

    for branch in pending:
        parent_evidence = [
            evidence
            for evidence in evidence_items
            if evidence.requirement_id == branch.parent_requirement_id
            and _evidence_can_satisfy_active_revision(state, evidence)
        ]
        if not parent_evidence:
            continue
        triggers = _conditional_branch_trigger_values(branch, parent_evidence)
        if not triggers:
            _skip_conditional_branch(state, branch, parent_evidence)
            continue
        _activate_conditional_branch(state, branch, triggers)


def _conditional_branch_trigger_values(
    branch: ConditionalBranchContract,
    evidence_items: list[EvidenceLedgerEntry],
) -> list[tuple[EvidenceLedgerEntry, Any, str]]:
    condition = dict(branch.condition or {})
    if condition.get("type") != "active_parent_evidence_has_any_field":
        return []
    field_any = [str(field) for field in condition.get("field_any", []) if str(field)]
    if not field_any:
        return []
    fan_out = dict(branch.on_true or {}).get("fan_out") == "all_unique_values"
    triggers: list[tuple[EvidenceLedgerEntry, Any, str]] = []
    seen_values: set[str] = set()
    for evidence in evidence_items:
        values = _flatten_evidence_values(evidence.normalized_result)
        for field in field_any:
            for key, value in values:
                if key != field or value in (None, "", [], {}):
                    continue
                value_key = _stable_json_key(value)
                if value_key in seen_values:
                    continue
                seen_values.add(value_key)
                triggers.append((evidence, value, field))
                if not fan_out:
                    return triggers
                if len(triggers) >= 2:
                    return triggers
    return triggers


def _skip_conditional_branch(
    state: PlannerOwnedAgentGraphState,
    branch: ConditionalBranchContract,
    evidence_items: list[EvidenceLedgerEntry],
) -> None:
    evidence_refs = [evidence.id for evidence in evidence_items]
    proposed = state.requirement_ledger.model_copy(deep=True)
    previous_revision = proposed.revision
    updated = _set_branch_status(
        proposed,
        branch.id,
        status="skipped",
        evidence_refs=evidence_refs,
        skipped_reason="conditional_branch_not_triggered",
        activated_child_requirement_ids=[],
        diagnostics={
            "condition": dict(branch.condition),
            "source": "active_parent_evidence",
            "reason": "condition_fields_absent_or_empty",
        },
    )
    if not updated:
        return

    proposed.revision = previous_revision + 1
    record = RequirementRevisionRecord(
        revision=proposed.revision,
        actor="system",
        change_type="conditional_branch_skipped",
        requirement_id=branch.parent_requirement_id,
        reason="conditional_branch_not_triggered",
        locked_constraints_preserved=True,
        details={
            "conditional_branch_id": branch.id,
            "parent_requirement_id": branch.parent_requirement_id,
            "derived_from_evidence_refs": evidence_refs,
            "status": "skipped",
            "skipped_reason": "conditional_branch_not_triggered",
        },
    )
    proposed.revision_history.append(record)
    decision = PlannerDecisionRecord(
        decision_id=f"dec-branch-{len(state.planner_decisions) + 1:03d}",
        decision_kind="revise_requirements",
        author="system",
        requirement_id=branch.parent_requirement_id,
        ledger_revision=state.requirement_ledger.revision,
        evidence_refs=evidence_refs,
        reason="Mark non-triggered conditional branch as skipped.",
        diagnostics={
            "conditional_branch": {
                "branch_id": branch.id,
                "status": "skipped",
                "reason": "conditional_branch_not_triggered",
            }
        },
    )
    record_planner_decision(
        state,
        PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=proposed),
    )
    _apply_planner_proposed_requirement_ledger(state, proposed)
    _record_conditional_branch_diagnostics(state)


def _activate_conditional_branch(
    state: PlannerOwnedAgentGraphState,
    branch: ConditionalBranchContract,
    triggers: list[tuple[EvidenceLedgerEntry, Any, str]],
) -> None:
    on_true = dict(branch.on_true or {})
    entity = str(on_true.get("entity") or "").strip()
    constraint_field = str(on_true.get("constraint_field") or (f"{entity}_id" if entity else "")).strip()
    evidence_items = [evidence for evidence, _value, _source_field in triggers]
    if not entity or not constraint_field:
        _skip_conditional_branch(state, branch, evidence_items)
        return

    proposed = state.requirement_ledger.model_copy(deep=True)
    previous_revision = proposed.revision
    existing_ids = [requirement.id for requirement in proposed.requirements]
    existing_child_keys = _existing_child_constraint_keys(state)
    added_children: list[RequirementLedgerEntry] = []
    child_evidence_refs: list[str] = []
    trigger_fields: list[str] = []
    trigger_values: list[Any] = []
    max_children = 2

    for evidence, value, source_field in triggers:
        if value in (None, "", [], {}):
            continue
        if _child_count_for_parent(state, branch.parent_requirement_id) + len(added_children) >= max_children:
            break
        signature = (branch.parent_requirement_id, constraint_field, _stable_json_key(value))
        if signature in existing_child_keys:
            continue
        try:
            child_id = next_child_requirement_id(branch.parent_requirement_id, existing_ids)
        except ValueError:
            break
        existing_ids.append(child_id)
        existing_child_keys.add(signature)
        child = RequirementLedgerEntry(
            id=child_id,
            goal=f"Read {entity} {value} conditional follow-up evidence",
            requirement_type="single_entity_status",
            entity=entity,
            intent_operation="report_status",
            source_of_truth=evidence.source_of_truth,
            constraints={constraint_field: value},
            requested_fields=[],
            locked_constraints=[constraint_field],
            status="open",
            parent_requirement_id=branch.parent_requirement_id,
            expansion_reason="Conditional branch triggered by parent evidence.",
            derived_from_evidence_refs=[evidence.id],
            derived_from_missing_reasons=[],
            depends_on=[evidence.id],
        )
        added_children.append(child)
        child_evidence_refs.append(evidence.id)
        trigger_fields.append(source_field)
        trigger_values.append(value)

    if not added_children:
        _skip_conditional_branch(state, branch, evidence_items)
        return

    evidence_refs = list(dict.fromkeys(child_evidence_refs))
    proposed.requirements.extend(added_children)
    _set_branch_status(
        proposed,
        branch.id,
        status="activated",
        evidence_refs=evidence_refs,
        skipped_reason=None,
        activated_child_requirement_ids=[child.id for child in added_children],
        diagnostics={
            "condition": dict(branch.condition),
            "trigger_field": trigger_fields[0] if trigger_fields else None,
            "trigger_fields": list(dict.fromkeys(trigger_fields)),
            "trigger_value": trigger_values[0] if trigger_values else None,
            "trigger_values": trigger_values,
            "source": "active_parent_evidence",
        },
    )

    proposed.revision = previous_revision + 1
    record = RequirementRevisionRecord(
        revision=proposed.revision,
        actor="system",
        change_type="add_child_requirements",
        requirement_id=branch.parent_requirement_id,
        reason="Conditional branch activated from parent evidence.",
        locked_constraints_preserved=True,
        details={
            "conditional_branch_id": branch.id,
            "conditional_branch_status": "activated",
            "parent_requirement_id": branch.parent_requirement_id,
            "parent_requirement_ids": [branch.parent_requirement_id],
            "added_child_requirement_ids": [child.id for child in added_children],
            "derived_from_evidence_refs": evidence_refs,
            "derived_from_missing_reasons": [],
            "locked_constraints_preserved": True,
            "trigger_field": trigger_fields[0] if trigger_fields else None,
            "trigger_fields": list(dict.fromkeys(trigger_fields)),
            "trigger_value": trigger_values[0] if trigger_values else None,
            "trigger_values": trigger_values,
            "tool_state_policy": "child_requires_fresh_retrieval",
        },
    )
    proposed.revision_history.append(record)
    decision = PlannerDecisionRecord(
        decision_id=f"dec-branch-{len(state.planner_decisions) + 1:03d}",
        decision_kind="revise_requirements",
        author="system",
        requirement_id=branch.parent_requirement_id,
        ledger_revision=state.requirement_ledger.revision,
        evidence_refs=evidence_refs,
        reason="Apply conditional branch child requirement from parent evidence.",
        diagnostics={
            "conditional_branch": {
                "branch_id": branch.id,
                "status": "activated",
                "added_child_requirement_ids": [child.id for child in added_children],
                "trigger_field": trigger_fields[0] if trigger_fields else None,
            }
        },
    )
    record_planner_decision(
        state,
        PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=proposed),
    )
    _apply_planner_proposed_requirement_ledger(state, proposed)
    expansion = dict(state.execution_trace.diagnostics.get("requirement_expansion") or {})
    expansion.update(
        {
            "status": "applied",
            "conditional_branch_id": branch.id,
            "conditional_branch_status": "activated",
            "previous_revision": previous_revision,
            "current_revision": proposed.revision,
            "added_child_requirement_ids": [child.id for child in added_children],
            "parent_requirement_ids": [branch.parent_requirement_id],
            "derived_from_evidence_refs": evidence_refs,
            "tool_state_policy": "child_requires_fresh_retrieval",
            "trigger_field": trigger_fields[0] if trigger_fields else None,
            "trigger_fields": list(dict.fromkeys(trigger_fields)),
        }
    )
    state.execution_trace.diagnostics["requirement_expansion"] = expansion
    _record_conditional_branch_diagnostics(state)


def _set_branch_status(
    ledger: RequirementLedger,
    branch_id: str,
    *,
    status: str,
    evidence_refs: list[str],
    skipped_reason: str | None,
    activated_child_requirement_ids: list[str],
    diagnostics: dict[str, Any],
) -> bool:
    for index, branch in enumerate(ledger.conditional_branches):
        if branch.id != branch_id:
            continue
        merged_diagnostics = {**dict(branch.diagnostics), **diagnostics}
        ledger.conditional_branches[index] = branch.model_copy(
            update={
                "status": status,
                "derived_from_evidence_refs": list(dict.fromkeys(evidence_refs)),
                "activated_child_requirement_ids": list(dict.fromkeys(activated_child_requirement_ids)),
                "skipped_reason": skipped_reason,
                "diagnostics": merged_diagnostics,
            },
            deep=True,
        )
        return True
    return False


def _record_conditional_branch_diagnostics(state: PlannerOwnedAgentGraphState) -> None:
    state.execution_trace.diagnostics["conditional_branches"] = [
        branch.model_dump(mode="json")
        for branch in state.requirement_ledger.conditional_branches
    ]


def _expand_child_requirements_from_evidence(
    state: PlannerOwnedAgentGraphState,
    evidence_items: list[EvidenceLedgerEntry],
) -> None:
    child_specs = _child_requirement_specs_from_evidence(state, evidence_items)
    if not child_specs:
        return

    proposed = state.requirement_ledger.model_copy(deep=True)
    previous_revision = proposed.revision
    added_children: list[RequirementLedgerEntry] = []
    existing_ids = [requirement.id for requirement in proposed.requirements]
    for parent, evidence, entity, entity_id in child_specs:
        try:
            child_id = next_child_requirement_id(parent.id, existing_ids)
        except ValueError:
            continue
        constraint_key = f"{entity}_id"
        child = RequirementLedgerEntry(
            id=child_id,
            goal=f"Read {entity} {entity_id} follow-up evidence",
            requirement_type="single_entity_status",
            entity=entity,
            intent_operation="report_status",
            source_of_truth=evidence.source_of_truth,
            constraints={constraint_key: entity_id},
            requested_fields=[],
            locked_constraints=[constraint_key],
            status="open",
            parent_requirement_id=parent.id,
            expansion_reason="Parent evidence exposed a bounded follow-up entity id.",
            derived_from_evidence_refs=[evidence.id],
            derived_from_missing_reasons=[],
            depends_on=[evidence.id],
        )
        proposed.requirements.append(child)
        existing_ids.append(child.id)
        added_children.append(child)

    if not added_children:
        return

    proposed.revision = previous_revision + 1
    parent_ids = list(dict.fromkeys(child.parent_requirement_id for child in added_children if child.parent_requirement_id))
    evidence_refs = list(
        dict.fromkeys(ref for child in added_children for ref in child.derived_from_evidence_refs)
    )
    record = RequirementRevisionRecord(
        revision=proposed.revision,
        actor="system",
        change_type="add_child_requirements",
        requirement_id=parent_ids[0] if len(parent_ids) == 1 else None,
        reason="Evidence-driven child requirement expansion.",
        locked_constraints_preserved=True,
        details={
            "parent_requirement_id": parent_ids[0] if len(parent_ids) == 1 else None,
            "parent_requirement_ids": parent_ids,
            "added_child_requirement_ids": [child.id for child in added_children],
            "derived_from_evidence_refs": evidence_refs,
            "derived_from_missing_reasons": [],
            "locked_constraints_preserved": True,
            "max_child_depth": 1,
            "max_children_per_parent": 2,
        },
    )
    proposed.revision_history.append(record)
    decision = PlannerDecisionRecord(
        decision_id=f"dec-expand-{len(state.planner_decisions) + 1:03d}",
        decision_kind="revise_requirements",
        author="system",
        requirement_id=parent_ids[0] if len(parent_ids) == 1 else None,
        ledger_revision=state.requirement_ledger.revision,
        evidence_refs=evidence_refs,
        reason="Apply bounded child requirements justified by parent evidence.",
        diagnostics={
            "requirement_expansion": {
                "system_child_expansion": True,
                "added_child_requirement_ids": [child.id for child in added_children],
                "derived_from_evidence_refs": evidence_refs,
            }
        },
    )
    record_planner_decision(
        state,
        PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=proposed),
    )
    _apply_planner_proposed_requirement_ledger(state, proposed)
    stale_decision_ids = _stale_planner_decision_ids_for_replan(state, parent_ids)
    expansion = dict(state.execution_trace.diagnostics.get("requirement_expansion") or {})
    expansion.update(
        {
            "status": "applied",
            "previous_revision": previous_revision,
            "current_revision": proposed.revision,
            "added_child_requirement_ids": [child.id for child in added_children],
            "parent_requirement_ids": parent_ids,
            "derived_from_evidence_refs": evidence_refs,
            "stale_planner_decision_ids": stale_decision_ids,
            "tool_state_policy": "child_requires_fresh_retrieval",
        }
    )
    state.execution_trace.diagnostics["requirement_expansion"] = expansion


def _child_requirement_specs_from_evidence(
    state: PlannerOwnedAgentGraphState,
    evidence_items: list[EvidenceLedgerEntry],
) -> list[tuple[RequirementLedgerEntry, EvidenceLedgerEntry, str, Any]]:
    specs: list[tuple[RequirementLedgerEntry, EvidenceLedgerEntry, str, Any]] = []
    existing_child_keys = _existing_child_constraint_keys(state)
    readable_entities = _readable_child_entities(state)
    if not readable_entities:
        return specs

    for evidence in evidence_items:
        parent = _requirement_by_id(state, evidence.requirement_id)
        if parent is None or parent.parent_requirement_id is not None or parent.status != "open":
            continue
        if _is_unbounded_collection_evidence(parent, evidence):
            continue
        if _child_count_for_parent(state, parent.id) >= 2:
            continue
        for key, value in _flatten_evidence_values(evidence.normalized_result):
            if value in (None, "", [], {}):
                continue
            entity = _entity_for_related_id_key(key, readable_entities)
            if not entity or entity == parent.entity:
                continue
            constraint_key = f"{entity}_id"
            signature = (parent.id, constraint_key, _stable_json_key(value))
            if signature in existing_child_keys:
                continue
            specs.append((parent, evidence, entity, value))
            existing_child_keys.add(signature)
            if _child_count_for_parent(state, parent.id) + sum(1 for spec in specs if spec[0].id == parent.id) >= 2:
                break
    return specs


def _is_unbounded_collection_evidence(
    parent: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
) -> bool:
    rows = evidence.normalized_result.get("rows")
    if not isinstance(rows, list):
        return False
    constraints = dict(parent.constraints or {})
    bounded_constraints = {
        key: value
        for key, value in constraints.items()
        if key not in {"limit", "sort_by", "sort_dir", "requested_fields"}
        and value not in (None, "", [], {})
    }
    if not bounded_constraints:
        return True
    return parent.requirement_type not in {"filtered_collection", "multi_entity_status"}


def _readable_child_entities(state: PlannerOwnedAgentGraphState) -> set[str]:
    entities: set[str] = set()
    for capability in state.capability_map.capabilities:
        entity = str(capability.entity or "").strip()
        if not entity:
            continue
        if capability.source_of_truth != "operational_state":
            continue
        if set(capability.actions).intersection({"read", "read_one", "read_many", "list", "search_documents"}):
            entities.add(entity)
    return entities


def _entity_for_related_id_key(key: str, readable_entities: set[str]) -> str | None:
    normalized = str(key or "").strip().lower()
    for entity in sorted(readable_entities, key=len, reverse=True):
        if normalized == f"{entity}_id" or normalized.endswith(f"_{entity}_id"):
            return entity
    return None


def _existing_child_constraint_keys(state: PlannerOwnedAgentGraphState) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for requirement in state.requirement_ledger.requirements:
        parent_id = requirement.parent_requirement_id
        if not parent_id:
            continue
        for key, value in requirement.constraints.items():
            keys.add((parent_id, str(key), _stable_json_key(value)))
    return keys


def _child_count_for_parent(state: PlannerOwnedAgentGraphState, parent_id: str) -> int:
    return sum(
        1
        for requirement in state.requirement_ledger.requirements
        if requirement.parent_requirement_id == parent_id
    )


def _flatten_evidence_values(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        flattened: list[tuple[str, Any]] = []
        for key, child in value.items():
            child_key = str(key)
            if isinstance(child, Mapping):
                flattened.extend(_flatten_evidence_values(child))
            elif isinstance(child, list):
                for item in child:
                    flattened.extend(_flatten_evidence_values(item))
            else:
                flattened.append((child_key, child))
        return flattened
    return []


def _stable_json_key(value: Any) -> str:
    try:
        import json

        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _explicit_carried_forward_evidence_refs(
    *,
    session_context: Mapping[str, Any] | Any | None,
    options: PlannerOwnedAgentGraphRunOptions,
) -> set[str]:
    values: list[Any] = []
    configured = options.configurable.get("carry_forward_evidence_refs")
    if configured is not None:
        values.append(configured)
    context_value = _session_context_value(session_context, "carry_forward_evidence_refs")
    if context_value is not None:
        values.append(context_value)
    replan_context = _session_context_value(session_context, "replan_context")
    if isinstance(replan_context, Mapping):
        nested = replan_context.get("planner_owned_graph_carry_forward_evidence_refs")
        if nested is not None:
            values.append(nested)

    refs: set[str] = set()
    for value in values:
        if value is True or value == "all":
            refs.add("*")
        elif isinstance(value, str):
            if value.strip():
                refs.add(value.strip())
        elif isinstance(value, (list, tuple, set)):
            refs.update(str(item).strip() for item in value if str(item).strip())
    return refs


def _semantic_intake_should_compile_in_node(state: PlannerOwnedAgentGraphState) -> bool:
    semantic_diagnostics = state.execution_trace.diagnostics.get("semantic_intake")
    if not isinstance(semantic_diagnostics, Mapping):
        return False
    return semantic_diagnostics.get("status") == "pending_langgraph_node"


def _preserve_preinvoke_graph_diagnostics(
    state: PlannerOwnedAgentGraphState,
    prior_diagnostics: Mapping[str, Any],
) -> None:
    for key in ("graph_checkpoint_identity",):
        if key in prior_diagnostics:
            state.execution_trace.diagnostics[key] = prior_diagnostics[key]


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


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _next_approval_index(state: PlannerOwnedAgentGraphState) -> int:
    return 1 + sum(
        1
        for decision in state.planner_decisions
        if decision.decision_kind == "request_approval"
        and decision.diagnostics.get("approval_index") is not None
    )


def _write_choice_finished_without_pending_approval(
    state: PlannerOwnedAgentGraphState,
    choose_decision: PlannerDecisionRecord,
) -> bool:
    requirement_id = choose_decision.requirement_id
    if requirement_id is None:
        return False
    requirement = _requirement_by_id(state, requirement_id)
    return bool(
        requirement is not None
        and requirement.status != "open"
        and _has_evidence_for_requirement(state, requirement_id)
    )


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
            "locked_constraints": (
                dict(pending.payload.get("locked_constraints"))
                if isinstance(pending.payload.get("locked_constraints"), Mapping)
                else {}
            ),
            "preview_rows": [
                dict(row) for row in (pending.payload.get("preview_rows") or []) if isinstance(row, Mapping)
            ],
            "staged_graph_tool_calls": [
                dict(call) for call in (pending.payload.get("staged_graph_tool_calls") or []) if isinstance(call, Mapping)
            ],
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


def _current_missing_evidence_reasons(state: PlannerOwnedAgentGraphState) -> list[dict[str, Any]]:
    satisfaction = state.execution_trace.diagnostics.get("satisfaction")
    if not isinstance(satisfaction, Mapping):
        return []
    reasons = satisfaction.get("missing_evidence_reasons")
    if not isinstance(reasons, list):
        return []
    return [dict(reason) for reason in reasons if isinstance(reason, Mapping)]


def _prepare_replan_spine_after_satisfaction(
    state: PlannerOwnedAgentGraphState,
    *,
    current_missing_reasons: list[dict[str, Any]],
    max_attempts: int,
) -> None:
    replan = _replan_spine_diagnostics(state)
    replan["max_attempts"] = max_attempts
    attempt_count = int(replan.get("attempt_count") or 0)
    next_attempt = attempt_count + 1
    current_failed_tool_calls = _failed_tool_calls_for_replan(
        state,
        [
            reason
            for reason in current_missing_reasons
            if reason.get("retriable") is True
            and str(reason.get("reason") or "") == "tool_error"
            and reason.get("evidence_refs")
            and str(reason.get("requirement_id") or "").strip()
        ],
        attempt=next_attempt,
    )
    if current_failed_tool_calls:
        replan["failed_tool_calls"] = _dedupe_failed_tool_calls(
            [
                *[dict(call) for call in replan.get("failed_tool_calls", []) if isinstance(call, Mapping)],
                *current_failed_tool_calls,
            ]
        )

    retry_reasons = [
        reason
        for reason in current_missing_reasons
        if reason.get("retriable") is True
        and reason.get("evidence_refs")
        and str(reason.get("requirement_id") or "").strip()
        and _missing_reason_can_retry_with_current_graph_state(state, reason)
    ]
    if not retry_reasons:
        replan["route"] = "approval_node"
        replan["replan_needed"] = False
        return

    if attempt_count >= max_attempts:
        replan["route"] = "approval_node"
        replan["replan_needed"] = False
        replan["replan_limit_reached"] = True
        replan["limit_reached_reasons"] = retry_reasons
        return

    attempt = next_attempt
    requirement_ids = list(
        dict.fromkeys(str(reason.get("requirement_id")) for reason in retry_reasons)
    )
    stale_evidence_refs = list(
        dict.fromkeys(
            str(evidence_ref)
            for reason in retry_reasons
            for evidence_ref in reason.get("evidence_refs", [])
            if str(evidence_ref)
        )
    )
    stale_decision_ids = _stale_planner_decision_ids_for_replan(state, requirement_ids)
    failed_tool_calls = _failed_tool_calls_for_replan(
        state,
        retry_reasons,
        attempt=attempt,
    )
    _mark_replan_stale_evidence(state, stale_evidence_refs, attempt=attempt)
    _reset_requirements_for_replan_retry(
        state,
        requirement_ids=requirement_ids,
        stale_evidence_refs=stale_evidence_refs,
        attempt=attempt,
    )
    state.candidate_tool_windows = [
        window for window in state.candidate_tool_windows if window.requirement_id not in set(requirement_ids)
    ]
    state.hydrated_tool_cards = [
        cards for cards in state.hydrated_tool_cards if cards.requirement_id not in set(requirement_ids)
    ]

    attempts = [item for item in replan.get("attempts", []) if isinstance(item, Mapping)]
    attempts.append(
        {
            "attempt": attempt,
            "requirement_ids": requirement_ids,
            "missing_evidence_reasons": retry_reasons,
            "stale_evidence_refs": stale_evidence_refs,
            "stale_planner_decision_ids": stale_decision_ids,
            "failed_tool_calls": failed_tool_calls,
        }
    )
    historical_reasons = [
        item for item in replan.get("missing_evidence_reasons", []) if isinstance(item, Mapping)
    ]
    historical_reasons.extend(retry_reasons)
    replan.update(
        {
            "route": "planner_decision_node",
            "replan_needed": True,
            "attempt_count": attempt,
            "current_attempt": attempt,
            "attempts": attempts,
            "missing_evidence_reasons": historical_reasons,
            "stale_evidence_refs": list(
                dict.fromkeys([*replan.get("stale_evidence_refs", []), *stale_evidence_refs])
            ),
            "stale_planner_decision_ids": list(
                dict.fromkeys([*replan.get("stale_planner_decision_ids", []), *stale_decision_ids])
            ),
            "failed_tool_calls": _dedupe_failed_tool_calls(
                [
                    *[dict(call) for call in replan.get("failed_tool_calls", []) if isinstance(call, Mapping)],
                    *failed_tool_calls,
                ]
            ),
        }
    )
    state.final_validation_result = None
    state.execution_trace.final_validator_status = None


def _replan_spine_diagnostics(state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
    existing = state.execution_trace.diagnostics.get(_REPLAN_SPINE_DIAGNOSTIC_KEY)
    if not isinstance(existing, dict):
        existing = {
            "attempt_count": 0,
            "attempts": [],
            "route": "approval_node",
            "replan_needed": False,
            "missing_evidence_reasons": [],
            "failed_tool_calls": [],
            "stale_evidence_refs": [],
            "stale_planner_decision_ids": [],
        }
        state.execution_trace.diagnostics[_REPLAN_SPINE_DIAGNOSTIC_KEY] = existing
    return existing


def _mark_replan_stale_evidence(
    state: PlannerOwnedAgentGraphState,
    stale_evidence_refs: list[str],
    *,
    attempt: int,
) -> None:
    stale = set(stale_evidence_refs)
    for evidence in state.evidence_ledger.evidence:
        if evidence.id not in stale:
            continue
        metadata = dict(evidence.diagnostic_metadata or {})
        metadata["active_revision_satisfaction"] = False
        metadata["stale_after_graph_replan"] = True
        metadata["stale_after_graph_revision"] = True
        metadata["superseded_reason"] = "replan_spine_retry"
        metadata["superseded_by_replan_attempt"] = attempt
        metadata["superseded_by_ledger_revision"] = state.requirement_ledger.revision + 1
        evidence.diagnostic_metadata = metadata


def _missing_reason_can_retry_with_current_graph_state(
    state: PlannerOwnedAgentGraphState,
    reason: Mapping[str, Any],
) -> bool:
    _ = state
    if str(reason.get("reason") or "") != "tool_error":
        return True
    return bool(reason.get("evidence_refs"))


def _failed_tool_calls_for_replan(
    state: PlannerOwnedAgentGraphState,
    retry_reasons: list[Mapping[str, Any]],
    *,
    attempt: int,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for reason in retry_reasons:
        if str(reason.get("reason") or "") != "tool_error":
            continue
        for evidence in _evidence_for_reason_refs(state, reason):
            if not evidence.tool_name:
                continue
            calls.append(
                {
                    "tool_name": evidence.tool_name,
                    "args": dict(evidence.args),
                    "requirement_id": evidence.requirement_id,
                    "evidence_ref": evidence.id,
                    "reason": "tool_error",
                    "attempt": attempt,
                    **(
                        {"error_type": str(evidence.diagnostic_metadata.get("error_type"))}
                        if evidence.diagnostic_metadata.get("error_type")
                        else {}
                    ),
                }
            )
    return _dedupe_failed_tool_calls(calls)


def _evidence_for_reason_refs(
    state: PlannerOwnedAgentGraphState,
    reason: Mapping[str, Any],
) -> list[EvidenceLedgerEntry]:
    refs = {
        str(evidence_ref)
        for evidence_ref in reason.get("evidence_refs", [])
        if str(evidence_ref)
    }
    return [evidence for evidence in state.evidence_ledger.evidence if evidence.id in refs]


def _dedupe_failed_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for call in calls:
        key = (
            str(call.get("requirement_id") or ""),
            str(call.get("tool_name") or ""),
            str(call.get("args") or {}),
            str(call.get("evidence_ref") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(call)
    return deduped


def _reset_requirements_for_replan_retry(
    state: PlannerOwnedAgentGraphState,
    *,
    requirement_ids: list[str],
    stale_evidence_refs: list[str],
    attempt: int,
) -> None:
    stale = set(stale_evidence_refs)
    retry_ids = set(requirement_ids)
    changed: list[dict[str, Any]] = []
    for requirement in state.requirement_ledger.requirements:
        if requirement.id not in retry_ids:
            continue
        previous_status = requirement.status
        previous_refs = list(requirement.evidence_refs)
        requirement.status = "open"
        requirement.evidence_refs = [
            evidence_ref for evidence_ref in requirement.evidence_refs if evidence_ref not in stale
        ]
        requirement.satisfaction_checks = [
            check
            for check in requirement.satisfaction_checks
            if check.evidence_ref is None or check.evidence_ref not in stale
        ]
        requirement.blockers = []
        changed.append(
            {
                "requirement_id": requirement.id,
                "previous_status": previous_status,
                "new_status": requirement.status,
                "previous_evidence_refs": previous_refs,
                "active_evidence_refs": list(requirement.evidence_refs),
            }
        )
    if not changed:
        return

    state.requirement_ledger.revision += 1
    record = RequirementRevisionRecord(
        revision=state.requirement_ledger.revision,
        actor="deterministic_guard",
        change_type="replan_spine_retry",
        reason="replan_spine_retry",
        locked_constraints_preserved=True,
        details={
            "attempt": attempt,
            "requirements": changed,
            "stale_evidence_refs": stale_evidence_refs,
        },
    )
    state.requirement_ledger.revision_history.append(record)
    state.revision_history.append(record)
    _sync_replan_satisfaction_state(state)


def _sync_replan_satisfaction_state(state: PlannerOwnedAgentGraphState) -> None:
    state.satisfaction_state.requirements = [
        RequirementSatisfactionState(
            requirement_id=requirement.id,
            status=requirement.status,
            evidence_refs=list(requirement.evidence_refs),
            satisfaction_checks=list(requirement.satisfaction_checks),
            blocker_reason=requirement.blockers[-1] if requirement.blockers else None,
        )
        for requirement in state.requirement_ledger.requirements
    ]


def _stale_planner_decision_ids_for_replan(
    state: PlannerOwnedAgentGraphState,
    requirement_ids: list[str],
) -> list[str]:
    retry_ids = set(requirement_ids)
    stale_decision_ids: list[str] = []
    for decision in state.planner_decisions:
        if decision.requirement_id in retry_ids:
            stale_decision_ids.append(decision.decision_id)
            continue
        if any(call.requirement_id in retry_ids for call in _planner_decision_selected_tool_calls(decision)):
            stale_decision_ids.append(decision.decision_id)
    return list(dict.fromkeys(stale_decision_ids))


def _candidate_tool_calls_after_failed_memory(
    state: PlannerOwnedAgentGraphState,
    *,
    requirement_id: str,
    candidate_tool_calls: list[GraphToolCall],
) -> list[GraphToolCall]:
    replan = state.execution_trace.diagnostics.get(_REPLAN_SPINE_DIAGNOSTIC_KEY)
    if not isinstance(replan, Mapping):
        return candidate_tool_calls
    failed_calls = failed_tool_calls_for_requirement(state, requirement_id)
    if not failed_calls:
        return candidate_tool_calls
    filtered = failed_tool_memory_filtered_candidates(candidate_tool_calls, failed_calls)
    if len(filtered) == len(candidate_tool_calls):
        return candidate_tool_calls
    replan["failed_tool_memory_applied"] = True
    replan["failed_tool_memory_filtered_call_count"] = len(candidate_tool_calls) - len(filtered)
    return filtered


def _retain_replan_missing_evidence_reason_history(state: PlannerOwnedAgentGraphState) -> None:
    replan = state.execution_trace.diagnostics.get(_REPLAN_SPINE_DIAGNOSTIC_KEY)
    satisfaction = state.execution_trace.diagnostics.get("satisfaction")
    if not isinstance(replan, Mapping) or not isinstance(satisfaction, dict):
        return
    historical = [item for item in replan.get("missing_evidence_reasons", []) if isinstance(item, Mapping)]
    if not historical:
        return
    current = [item for item in satisfaction.get("missing_evidence_reasons", []) if isinstance(item, Mapping)]
    if current:
        return
    satisfaction["missing_evidence_reasons"] = [dict(item) for item in historical]
    satisfaction["missing_evidence_reason_history_retained"] = True


def _refresh_replan_evidence_diagnostics(state: PlannerOwnedAgentGraphState) -> None:
    replan = state.execution_trace.diagnostics.get(_REPLAN_SPINE_DIAGNOSTIC_KEY)
    if not isinstance(replan, dict):
        return
    active_refs = [
        evidence.id
        for evidence in state.evidence_ledger.evidence
        if _evidence_can_satisfy_active_revision(state, evidence)
    ]
    stale_attempt_refs = [
        evidence.id
        for evidence in state.evidence_ledger.evidence
        if evidence.diagnostic_metadata.get("stale_after_graph_replan") is True
        or evidence.diagnostic_metadata.get("superseded_reason") == "replan_spine_retry"
    ]
    replan["active_evidence_refs"] = active_refs
    replan["stale_attempt_evidence_refs"] = stale_attempt_refs
    replan["historical_evidence_refs"] = [
        evidence.id
        for evidence in state.evidence_ledger.evidence
        if evidence.id not in set(active_refs)
    ]
    replan["active_final_evidence_refs"] = (
        active_refs
        if state.final_validation_result is not None and state.final_validation_result.status == "passed"
        else []
    )


def _response_replan_spine_diagnostics(state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
    replan = state.execution_trace.diagnostics.get(_REPLAN_SPINE_DIAGNOSTIC_KEY)
    if not isinstance(replan, Mapping):
        return {}
    return {
        key: value
        for key, value in dict(replan).items()
        if key
        in {
            "attempt_count",
            "max_attempts",
            "attempts",
            "route",
            "replan_needed",
            "replan_limit_reached",
            "limit_reached_reasons",
            "missing_evidence_reasons",
            "failed_tool_calls",
            "stale_evidence_refs",
            "stale_attempt_evidence_refs",
            "active_evidence_refs",
            "active_final_evidence_refs",
            "historical_evidence_refs",
        }
    }


def _open_requirements_without_evidence(state: PlannerOwnedAgentGraphState):
    evidence_requirement_ids = {
        evidence.requirement_id
        for evidence in state.evidence_ledger.evidence
        if _evidence_can_satisfy_active_revision(state, evidence)
    }
    return [
        requirement
        for requirement in state.requirement_ledger.requirements
        if requirement.status == "open" and requirement.id not in evidence_requirement_ids
    ]


def _open_requirements_need_fresh_retrieval(state: PlannerOwnedAgentGraphState) -> bool:
    return any(
        requirement.status == "open"
        and not _has_evidence_for_requirement(state, requirement.id)
        and not _has_decision_for_requirement(state, "retrieve_tools", requirement.id)
        and not _has_planner_proposer_rejection_for_requirement(
            state,
            requirement.id,
            requested_decision_kind="retrieve_tools",
        )
        for requirement in state.requirement_ledger.requirements
    )


def _has_planner_proposer_rejection_for_requirement(
    state: PlannerOwnedAgentGraphState,
    requirement_id: str,
    *,
    requested_decision_kind: str,
) -> bool:
    trace = state.execution_trace.planner.diagnostics.get("planner_decision_proposer")
    if not isinstance(trace, Mapping):
        return False
    rejected = trace.get("rejected")
    if not isinstance(rejected, list):
        return False
    return any(
        isinstance(item, Mapping)
        and item.get("requirement_id") == requirement_id
        and item.get("requested_decision_kind") == requested_decision_kind
        and item.get("fail_closed") is True
        for item in rejected
    )


def _has_evidence_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> bool:
    return any(
        evidence.requirement_id == requirement_id
        and _evidence_can_satisfy_active_revision(state, evidence)
        for evidence in state.evidence_ledger.evidence
    )
