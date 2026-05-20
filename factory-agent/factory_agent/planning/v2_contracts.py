from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EngineVersion = Literal["legacy", "v2_shadow", "v2"]
ExecutionTraceGeneratedBy = Literal[
    "legacy_graph_loop",
    "legacy_rag_route",
    "legacy_working_intents",
    "v2_shadow_planner_loop",
    "v2_planner_loop",
]
SourceOfTruth = Literal["operational_state", "document_knowledge", "mixed", "unknown"]

RequirementType = Literal[
    "single_entity_status",
    "multi_entity_status",
    "filtered_collection",
    "document_answer",
    "mutation_request",
    "approval_request",
    "clarification_request",
    "safety_refusal",
    "diagnostic",
]
RequirementStatus = Literal[
    "open",
    "blocked",
    "satisfied",
    "skipped",
    "impossible",
    "superseded",
    "failed",
]
IntentOperation = Literal[
    "report_status",
    "report_multi_status",
    "report_filtered_collection",
    "answer_document_question",
    "stage_mutation",
    "request_approval",
    "request_clarification",
    "refuse_for_safety",
    "report_diagnostic",
]
CapabilityAction = Literal[
    "read",
    "read_one",
    "read_many",
    "list",
    "search_documents",
    "update",
    "create",
    "approve",
    "reject",
    "cancel",
]
AdapterSafety = Literal["read_only", "dry_run_write", "write_requires_approval", "high_risk", "unknown"]
EndpointShape = Literal["single", "collection", "document_search", "mutation", "approval", "unknown"]
EvidenceSourceType = Literal[
    "api_tool",
    "rag_tool",
    "legacy_rag_route",
    "approval",
    "user_input",
    "system_guard",
    "diagnostic",
]
EvidenceConfidence = Literal["deterministic", "planner_inferred", "ambiguous"]
AgendaPatchOperation = Literal[
    "add_requirement",
    "revise_requirement",
    "split_requirement",
    "merge_requirements",
    "remove_dependency",
    "reorder_requirements",
    "supersede_requirement",
    "mark_blocked",
]
RevisionActor = Literal["planner", "deterministic_guard", "user", "final_validator", "system"]
FinalValidationStatus = Literal["passed", "failed"]


class V2ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannerTrace(V2ContractModel):
    call_count: int = Field(default=0, ge=0)
    model_name: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RerankerTrace(V2ContractModel):
    call_count: int = Field(default=0, ge=0)
    model_name: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ToolRetrievalTrace(V2ContractModel):
    call_count: int = Field(default=0, ge=0)
    selected_candidate_tool_names: list[str] = Field(default_factory=list)
    backend_used: str | None = None
    reranker: RerankerTrace = Field(default_factory=RerankerTrace)
    compatibility_fallback_used: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class LegacyRagShortcutTrace(V2ContractModel):
    used: bool = False
    route: str | None = None
    source_function: str | None = None
    policy_id: str | None = None
    persisted_empty_plan: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class LegacyWorkingIntentExecutionTrace(V2ContractModel):
    used: bool = False
    working_intents_count: int | None = Field(default=None, ge=0)
    intent_cursor_start: int | None = Field(default=None, ge=0)
    intent_cursor_final: int | None = Field(default=None, ge=0)


class LegacyWholeQueryToolScopeTrace(V2ContractModel):
    used: bool = False
    source_function: str | None = None
    selector_intent_scope: Literal["whole_user_query"] | None = None
    selected_candidate_tool_names: list[str] = Field(default_factory=list)


class LegacyIntentCompletionLoopTrace(V2ContractModel):
    used: bool = False
    intent_completed_count: int = Field(default=0, ge=0)
    planner_completion_only_call_count: int = Field(default=0, ge=0)


class ExecutionDetectors(V2ContractModel):
    legacy_rag_shortcut: LegacyRagShortcutTrace = Field(default_factory=LegacyRagShortcutTrace)
    legacy_working_intent_execution: LegacyWorkingIntentExecutionTrace = Field(
        default_factory=LegacyWorkingIntentExecutionTrace
    )
    legacy_whole_query_tool_scope: LegacyWholeQueryToolScopeTrace = Field(
        default_factory=LegacyWholeQueryToolScopeTrace
    )
    legacy_intent_completion_loop: LegacyIntentCompletionLoopTrace = Field(
        default_factory=LegacyIntentCompletionLoopTrace
    )


class ExecutionTrace(V2ContractModel):
    engine_version: EngineVersion = "legacy"
    generated_by: ExecutionTraceGeneratedBy = "legacy_graph_loop"
    planner: PlannerTrace = Field(default_factory=PlannerTrace)
    tool_retrieval: ToolRetrievalTrace = Field(default_factory=ToolRetrievalTrace)
    detectors: ExecutionDetectors = Field(default_factory=ExecutionDetectors)
    selected_tool_names: list[str] = Field(default_factory=list)
    final_validator_status: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _legacy_rag_trace_must_name_shortcut(self) -> "ExecutionTrace":
        if self.generated_by == "legacy_rag_route" and not self.detectors.legacy_rag_shortcut.used:
            raise ValueError("legacy RAG route traces must set legacy_rag_shortcut.used")
        return self


class FieldAlias(V2ContractModel):
    canonical_field: str = Field(min_length=1)
    user_terms: list[str] = Field(default_factory=list)
    entity: str | None = None
    source: str | None = None


class FieldAliases(V2ContractModel):
    aliases: list[FieldAlias] = Field(default_factory=list)


class CapabilityMapEntry(V2ContractModel):
    capability_id: str = Field(min_length=1)
    source_of_truth: SourceOfTruth
    entity: str | None = None
    actions: list[CapabilityAction] = Field(default_factory=list)
    supports: list[str] = Field(default_factory=list)
    output_contract: str | None = None
    requires_approval: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityMap(V2ContractModel):
    capabilities: list[CapabilityMapEntry] = Field(default_factory=list)
    field_aliases: FieldAliases = Field(default_factory=FieldAliases)


class CapabilityNeed(V2ContractModel):
    source_of_truth: SourceOfTruth
    entity: str | None = None
    action: CapabilityAction
    known_args: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_fields: list[str] = Field(default_factory=list)
    requirement_id: str | None = None
    reason: str | None = None


class ToolRetrievalSlice(V2ContractModel):
    slice_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_of_truth_hint: SourceOfTruth = "unknown"
    entity: str | None = None
    actions: list[CapabilityAction] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_fields: list[str] = Field(default_factory=list)


class ToolSelectorAdapterRequest(V2ContractModel):
    requirement_id: str = Field(min_length=1)
    entity: str | None = None
    actions: list[CapabilityAction] = Field(default_factory=list)
    safety: AdapterSafety = "unknown"
    endpoint_shape: EndpointShape = "unknown"
    source_of_truth: SourceOfTruth = "unknown"
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_fields: list[str] = Field(default_factory=list)
    retrieval_phrase: str | None = None
    capability_need: CapabilityNeed | None = None


class CandidateTool(V2ContractModel):
    tool_name: str = Field(min_length=1)
    rank: int = Field(ge=1)
    score: float | None = None
    source_of_truth: SourceOfTruth = "unknown"
    actions: list[CapabilityAction] = Field(default_factory=list)
    reason: str | None = None
    requires_approval: bool = False


class CandidateToolWindow(V2ContractModel):
    requirement_id: str = Field(min_length=1)
    capability_need: CapabilityNeed
    candidates: list[CandidateTool] = Field(default_factory=list)
    max_candidates: int = Field(default=5, ge=1, le=5)
    backend_used: str | None = None
    adapter_request: ToolSelectorAdapterRequest | None = None

    @model_validator(mode="after")
    def _candidate_count_within_window(self) -> "CandidateToolWindow":
        if len(self.candidates) > self.max_candidates:
            raise ValueError("candidate tool window cannot exceed max_candidates")
        return self


class HydratedToolCard(V2ContractModel):
    tool_name: str = Field(min_length=1)
    description: str | None = None
    source_of_truth: SourceOfTruth = "unknown"
    actions: list[CapabilityAction] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_args: list[str] = Field(default_factory=list)
    path_params: list[str] = Field(default_factory=list)
    query_params: list[str] = Field(default_factory=list)
    supports_filters: bool = False
    supports_sort: bool = False
    supports_limit: bool = False
    supports_fields: bool = False
    output_contract: str | None = None
    is_read_only: bool = True
    requires_approval: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class HydratedToolCards(V2ContractModel):
    requirement_id: str = Field(min_length=1)
    cards: list[HydratedToolCard] = Field(default_factory=list)
    max_cards: int = Field(default=5, ge=1, le=5)

    @model_validator(mode="after")
    def _hydrated_card_count_within_window(self) -> "HydratedToolCards":
        if len(self.cards) > self.max_cards:
            raise ValueError("hydrated tool cards cannot exceed max_cards")
        return self


class RequirementOrigin(V2ContractModel):
    goal: str | None = None
    constraints: str | None = None
    fields: str | None = None
    source_of_truth: str | None = None


class RequirementSketchItem(V2ContractModel):
    id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    requirement_type: RequirementType
    entity: str | None = None
    intent_operation: IntentOperation
    source_of_truth: SourceOfTruth = "unknown"
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_fields: list[str] = Field(default_factory=list)
    locked_constraints: list[str] = Field(default_factory=list)
    origin: RequirementOrigin = Field(default_factory=RequirementOrigin)


class RequirementSketch(V2ContractModel):
    user_goal: str = Field(min_length=1)
    requirements: list[RequirementSketchItem] = Field(default_factory=list)
    field_aliases: FieldAliases = Field(default_factory=FieldAliases)
    tool_retrieval_slices: list[ToolRetrievalSlice] = Field(default_factory=list)


class SatisfactionCheck(V2ContractModel):
    check: str = Field(min_length=1)
    expected: Any = None
    actual: Any = None
    actual_count: int | None = Field(default=None, ge=0)
    passed: bool
    evidence_ref: str | None = None
    message: str | None = None


class RequirementLedgerEntry(V2ContractModel):
    id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    requirement_type: RequirementType
    entity: str | None = None
    intent_operation: IntentOperation
    source_of_truth: SourceOfTruth = "unknown"
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_fields: list[str] = Field(default_factory=list)
    locked_constraints: list[str] = Field(default_factory=list)
    status: RequirementStatus = "open"
    evidence_refs: list[str] = Field(default_factory=list)
    required: bool = True
    depends_on: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    satisfaction_checks: list[SatisfactionCheck] = Field(default_factory=list)
    origin: RequirementOrigin = Field(default_factory=RequirementOrigin)


class RequirementRevisionRecord(V2ContractModel):
    revision: int = Field(ge=1)
    actor: RevisionActor
    change_type: str = Field(min_length=1)
    requirement_id: str | None = None
    patch_id: str | None = None
    reason: str | None = None
    locked_constraints_preserved: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class AgendaPatch(V2ContractModel):
    patch_id: str = Field(min_length=1)
    operation: AgendaPatchOperation
    reason: str = Field(min_length=1)
    requirement_id: str | None = None
    locked_constraints_before: list[str] = Field(default_factory=list)
    proposed_requirement: RequirementLedgerEntry | None = None
    proposed_requirements: list[RequirementLedgerEntry] = Field(default_factory=list)
    user_revision_ref: str | None = None
    guard_approved_reason: str | None = None

    @model_validator(mode="after")
    def _locked_constraints_are_not_silently_dropped(self) -> "AgendaPatch":
        locked_before = set(self.locked_constraints_before)
        if not locked_before:
            return self

        if self.user_revision_ref or self.guard_approved_reason:
            return self

        proposed_entries = list(self.proposed_requirements)
        if self.proposed_requirement is not None:
            proposed_entries.append(self.proposed_requirement)

        if self.operation in {"remove_dependency", "reorder_requirements", "mark_blocked"}:
            return self

        if not proposed_entries:
            raise ValueError("agenda patch touching locked constraints needs a replacement requirement")

        preserved = set().union(*(entry.locked_constraints for entry in proposed_entries))
        missing = sorted(locked_before - preserved)
        if missing:
            raise ValueError(f"agenda patch drops locked constraints: {', '.join(missing)}")
        return self


class RequirementLedger(V2ContractModel):
    user_goal: str = Field(min_length=1)
    requirements: list[RequirementLedgerEntry] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)
    revision_history: list[RequirementRevisionRecord] = Field(default_factory=list)


class EvidenceCitation(V2ContractModel):
    source_id: str = Field(min_length=1)
    title: str | None = None
    doc_id: str | None = None
    chunk_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    locator: dict[str, Any] = Field(default_factory=dict)
    snippet: str | None = None


class LegacyRagRouteMetadata(V2ContractModel):
    route: str = Field(min_length=1)
    source_function: str | None = None
    policy_id: str | None = None
    persisted_empty_plan: bool = True
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class EvidenceLedgerEntry(V2ContractModel):
    id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    source_type: EvidenceSourceType
    source_of_truth: SourceOfTruth = "unknown"
    confidence: EvidenceConfidence = "deterministic"
    tool_name: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    result_ref: str | None = None
    normalized_result: dict[str, Any] = Field(default_factory=dict)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    satisfies: list[str] = Field(default_factory=list)
    approval_id: str | None = None
    diagnostic_metadata: dict[str, Any] = Field(default_factory=dict)
    legacy_rag_route: LegacyRagRouteMetadata | None = None

    @model_validator(mode="after")
    def _evidence_source_requirements(self) -> "EvidenceLedgerEntry":
        if self.source_type in {"api_tool", "rag_tool"} and not self.tool_name:
            raise ValueError("tool evidence must include tool_name")
        if self.source_type == "rag_tool" and not self.citations:
            raise ValueError("RAG tool evidence must include typed citations")
        if self.source_type == "legacy_rag_route" and self.tool_name:
            raise ValueError("legacy RAG route evidence must not be represented as a v2 tool call")
        if self.source_type == "legacy_rag_route" and self.legacy_rag_route is None:
            raise ValueError("legacy RAG route evidence must include legacy route metadata")
        return self


class EvidenceLedger(V2ContractModel):
    evidence: list[EvidenceLedgerEntry] = Field(default_factory=list)


class RequirementSatisfactionState(V2ContractModel):
    requirement_id: str = Field(min_length=1)
    status: RequirementStatus
    evidence_refs: list[str] = Field(default_factory=list)
    satisfaction_checks: list[SatisfactionCheck] = Field(default_factory=list)
    blocker_reason: str | None = None


class SatisfactionState(V2ContractModel):
    requirements: list[RequirementSatisfactionState] = Field(default_factory=list)


class FinalValidationIssue(V2ContractModel):
    issue: str = Field(min_length=1)
    requirement_id: str | None = None
    evidence_ref: str | None = None
    check: str | None = None
    expected: Any = None
    actual: Any = None
    message: str | None = None


class FinalValidationResult(V2ContractModel):
    status: FinalValidationStatus
    issues: list[FinalValidationIssue] = Field(default_factory=list)
    checked_requirement_ids: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class PlannerOwnedLoopV2State(V2ContractModel):
    engine_version: EngineVersion = "legacy"
    execution_trace: ExecutionTrace = Field(default_factory=ExecutionTrace)
    requirement_sketch: RequirementSketch | None = None
    requirement_ledger: RequirementLedger | None = None
    capability_map: CapabilityMap = Field(default_factory=CapabilityMap)
    evidence_ledger: EvidenceLedger = Field(default_factory=EvidenceLedger)
    satisfaction_state: SatisfactionState = Field(default_factory=SatisfactionState)
    final_validation_result: FinalValidationResult | None = None
    candidate_tool_windows: list[CandidateToolWindow] = Field(default_factory=list)
    hydrated_tool_cards: list[HydratedToolCards] = Field(default_factory=list)
    revision_history: list[RequirementRevisionRecord] = Field(default_factory=list)
