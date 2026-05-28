from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .v2_capability_map import (
    build_capability_needs_from_sketch,
    build_requirement_ledger_from_sketch,
    build_requirement_sketch_for_text,
    build_v2_capability_map,
)
from .semantic_intake import SemanticIntakeProposer
from .v2_contracts import (
    CapabilityMap,
    CapabilityNeed,
    CandidateToolWindow,
    EngineVersion,
    EvidenceLedger,
    ExecutionTrace,
    FinalValidationResult,
    HydratedToolCards,
    RequirementLedger,
    RequirementRevisionRecord,
    SatisfactionState,
    ToolRetrievalTrace,
    V2ContractModel,
)
from .v2_satisfaction import validate_v2_final_state


PLANNER_OWNED_AGENT_GRAPH_TRACE_ID = "planner_owned_agent_graph"

PlannerOwnedGraphDecisionKind = Literal[
    "retrieve_tools",
    "choose_tool",
    "execute_tool",
    "execute_parallel_read_batch",
    "request_approval",
    "revise_requirements",
    "request_clarification",
    "finalize",
    "fail",
]
PlannerOwnedGraphDecisionAuthor = Literal["planner", "deterministic_guard", "system"]
PlannerOwnedGraphToolCallKind = Literal["api_tool", "rag_tool"]
PlannerOwnedGraphResponseDocumentState = Literal["not_started", "draft", "rendered", "failed"]
PlannerOwnedGraphApprovalStatus = Literal["none", "pending", "approved", "rejected", "expired", "stale"]


class GraphToolCall(V2ContractModel):
    """Exact executable action chosen by the graph, separate from requirements and evidence."""

    call_id: str = Field(min_length=1)
    kind: PlannerOwnedGraphToolCallKind
    tool_name: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    requirement_id: str = Field(min_length=1)
    decision_id: str | None = None
    candidate_window_id: str | None = None


class PlannerDecisionRecord(V2ContractModel):
    """Persisted graph decision authorizing a later graph transition."""

    decision_id: str = Field(min_length=1)
    decision_kind: PlannerOwnedGraphDecisionKind
    author: PlannerOwnedGraphDecisionAuthor = "planner"
    requirement_id: str | None = None
    ledger_revision: int = Field(default=1, ge=1)
    capability_need: CapabilityNeed | None = None
    selected_tool_call: GraphToolCall | None = None
    selected_tool_calls: list[GraphToolCall] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _selected_tool_call_matches_requirement(self) -> "PlannerDecisionRecord":
        if (
            self.selected_tool_call is not None
            and self.requirement_id is not None
            and self.selected_tool_call.requirement_id != self.requirement_id
        ):
            raise ValueError("selected tool call must target the planner decision requirement")
        for tool_call in self.selected_tool_calls:
            if self.requirement_id is not None and tool_call.requirement_id != self.requirement_id:
                raise ValueError("selected tool calls must target the planner decision requirement")
        return self


class PendingApprovalState(V2ContractModel):
    status: PlannerOwnedGraphApprovalStatus = "none"
    approval_id: str | None = None
    requirement_id: str | None = None
    decision_id: str | None = None
    ledger_revision: int | None = Field(default=None, ge=1)
    checkpoint_id: str | None = None
    tool_call: GraphToolCall | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _pending_approval_requires_identity(self) -> "PendingApprovalState":
        if self.status == "pending" and not self.approval_id:
            raise ValueError("pending approval state must include approval_id")
        return self


class ResponseDocumentContext(V2ContractModel):
    state: PlannerOwnedGraphResponseDocumentState = "not_started"
    document_id: str | None = None
    revision: int = Field(default=0, ge=0)
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    pending_approval_id: str | None = None
    render_contract: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class PlannerOwnedAgentGraphState(V2ContractModel):
    """Serializable Phase 1 state owned by the future planner graph.

    The graph state reuses v2 requirement, capability, evidence, satisfaction,
    and retrieval contracts. It adds graph-only identity, planner decisions,
    approval checkpoint state, response-document context, and the original
    query without changing the existing direct-v2 runtime.
    """

    original_query: str = Field(min_length=1)
    requirement_ledger: RequirementLedger
    capability_map: CapabilityMap = Field(default_factory=CapabilityMap)
    candidate_tool_windows: list[CandidateToolWindow] = Field(default_factory=list)
    hydrated_tool_cards: list[HydratedToolCards] = Field(default_factory=list)
    planner_decisions: list[PlannerDecisionRecord] = Field(default_factory=list)
    evidence_ledger: EvidenceLedger = Field(default_factory=EvidenceLedger)
    pending_approval: PendingApprovalState = Field(default_factory=PendingApprovalState)
    satisfaction_state: SatisfactionState = Field(default_factory=SatisfactionState)
    final_validation_result: FinalValidationResult | None = None
    response_document_context: ResponseDocumentContext = Field(default_factory=ResponseDocumentContext)
    revision_history: list[RequirementRevisionRecord] = Field(default_factory=list)
    execution_trace: ExecutionTrace = Field(
        default_factory=lambda: ExecutionTrace(
            engine_version="v2",
            generated_by=PLANNER_OWNED_AGENT_GRAPH_TRACE_ID,
            tool_retrieval=ToolRetrievalTrace(call_count=0),
        )
    )
    engine_version: EngineVersion = "v2"

    @model_validator(mode="after")
    def _trace_identity_must_be_graph_owned(self) -> "PlannerOwnedAgentGraphState":
        if self.execution_trace.generated_by != PLANNER_OWNED_AGENT_GRAPH_TRACE_ID:
            raise ValueError("planner-owned agent graph state must use graph trace identity")
        if self.execution_trace.engine_version != self.engine_version:
            raise ValueError("graph state engine_version must match execution trace")
        return self

    def as_loop_compat_state(self):
        from .v2_contracts import PlannerOwnedLoopV2State

        return PlannerOwnedLoopV2State(
            engine_version=self.engine_version,
            execution_trace=self.execution_trace,
            requirement_ledger=self.requirement_ledger,
            capability_map=self.capability_map,
            evidence_ledger=self.evidence_ledger,
            satisfaction_state=self.satisfaction_state,
            final_validation_result=self.final_validation_result,
            candidate_tool_windows=self.candidate_tool_windows,
            hydrated_tool_cards=self.hydrated_tool_cards,
            revision_history=self.revision_history,
        )


def build_initial_planner_owned_agent_graph_state(
    original_query: str,
    *,
    tools_by_name: dict[str, Any] | None = None,
    semantic_intake_proposer: SemanticIntakeProposer | None = None,
) -> PlannerOwnedAgentGraphState:
    """Build Phase 1 graph state through intake and ledger creation only."""

    capability_map = build_v2_capability_map(tools_by_name or {})
    requirement_sketch = build_requirement_sketch_for_text(
        original_query,
        capability_map=capability_map,
        semantic_intake_proposer=semantic_intake_proposer,
    )
    requirement_ledger = build_requirement_ledger_from_sketch(requirement_sketch)
    capability_needs = build_capability_needs_from_sketch(requirement_sketch)
    trace = ExecutionTrace(
        engine_version="v2",
        generated_by=PLANNER_OWNED_AGENT_GRAPH_TRACE_ID,
        tool_retrieval=ToolRetrievalTrace(call_count=0),
    )
    trace.planner.call_count = 0
    trace.planner.diagnostics.update(
        {
            "planner_kind": "planner_owned_agent_graph_phase1_state_contract",
            "saw_original_query": True,
            "saw_requirement_ledger": True,
            "saw_high_level_capability_map": True,
            "received_full_tool_catalog_before_need": False,
            "execution_started": False,
            "capability_need_count": len(capability_needs),
        }
    )
    trace.diagnostics["capability_needs"] = [need.model_dump(mode="json") for need in capability_needs]
    trace.diagnostics["graph_state_phase"] = "phase1_contracts_only"
    trace.diagnostics["semantic_intake"] = dict(requirement_ledger.intake_diagnostics)

    return PlannerOwnedAgentGraphState(
        original_query=original_query,
        requirement_ledger=requirement_ledger,
        capability_map=capability_map,
        revision_history=list(requirement_ledger.revision_history),
        execution_trace=trace,
        response_document_context=ResponseDocumentContext(
            state="not_started",
            revision=requirement_ledger.revision,
            requirement_ids=[requirement.id for requirement in requirement_ledger.requirements],
        ),
    )


def validate_graph_state_final_state(state: PlannerOwnedAgentGraphState) -> FinalValidationResult:
    """Reuse v2 final validation without making the direct-v2 loop graph authority."""

    result = validate_v2_final_state(state.as_loop_compat_state())
    state.final_validation_result = result
    state.execution_trace.final_validator_status = result.status
    return result
