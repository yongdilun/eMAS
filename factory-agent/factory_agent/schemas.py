from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


SessionStatus = Literal[
    "IDLE",
    "PLANNING",
    "WAITING_APPROVAL",
    "WAITING_CONFIRMATION",
    "EXECUTING",
    "BLOCKED",
    "FAILED",
    "COMPLETED",
]

IntentOperator = Literal["=", "!=", "<", "<=", ">", ">=", "in", "not_in", "before", "after", "prefer"]
IntentConstraintStrength = Literal["hard", "soft"]
IntentLifecycleStatus = Literal[
    "pending",
    "in_progress",
    "waiting_clarification",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
    "cancelled_due_to_dependency_failure",
]
IntentCategory = Literal["scheduling", "inventory", "machine", "job", "reporting", "general", "unknown"]


class ExplicitConstraint(BaseModel):
    """User-demanded parameter captured at split time (no validation — Phase 2 dumb splitter)."""

    field: str
    operator: IntentOperator = "="
    value: Any = None
    source_text: str | None = None
    strength: IntentConstraintStrength = "hard"
    mutable: bool = False


class Intent(BaseModel):
    """Structured work unit extracted from natural language (Phase 2)."""

    intent_id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    explicit_constraints: list[ExplicitConstraint] = Field(default_factory=list)
    status: IntentLifecycleStatus = "pending"
    failure_reason: str | None = None
    category: IntentCategory = "unknown"


PlannerDecisionKind = Literal[
    "domain_tool",
    "parallel_read_tools",
    "request_clarification",
    "request_approval",
    "intent_completed",
    "intent_failed",
    "halt",
]
PlannerRiskLevel = Literal["read", "write_dry_run", "write_commit", "high_risk"]
ControlActionName = Literal["request_clarification", "mark_intent_completed", "mark_intent_failed"]


class ToolCall(BaseModel):
    """Single tool invocation proposed by the planner (Phase 3)."""

    tool_call_id: str = Field(default_factory=lambda: f"tc-{uuid4().hex[:12]}")
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    # Phase 4: optional stable handle for same-turn dependent write chaining ($ref:...).
    output_ref: str | None = None


class ControlAction(BaseModel):
    """Structured control payload when the planner chooses a non-domain action."""

    name: ControlActionName
    payload: dict[str, Any] = Field(default_factory=dict)


class PlannerDecision(BaseModel):
    """Normalized planner output for routing, guards, and observability (Phase 3)."""

    decision_id: str = Field(default_factory=lambda: f"dec-{uuid4().hex[:12]}")
    intent_id: str
    kind: PlannerDecisionKind
    tool_calls: list[ToolCall] = Field(default_factory=list)
    control_action: ControlAction | None = None
    decision_summary: str
    risk_level: PlannerRiskLevel = "read"
    violates_constraints: bool = False


AgentGraphRunStatus = Literal[
    "init",
    "intent_split_pending",
    "planning",
    "awaiting_clarification",
    "awaiting_approval",
    "tool_running",
    "validating",
    "completed",
    "failed",
]
MessageMode = Literal["normal", "plan"]
PlanKind = Literal["execution", "discovery"]
PlanStatus = Literal["DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "COMPLETED", "FAILED", "INVALIDATED"]
ApprovalSubjectType = Literal["step", "plan", "graph"]

StepStatus = Literal[
    "NOT_STARTED",
    "IN_PROGRESS",
    "DONE",
    "FAILED",
    "SKIPPED",
    "AMBIGUOUS",
]

SideEffectLevel = Literal["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
BindingMode = Literal["single", "foreach"]


class PlanBinding(BaseModel):
    from_step: int = Field(ge=0)
    result_path: str = "data"
    field: str
    target_arg: str
    mode: BindingMode = "single"


class AgentPlanStep(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    missing_required: list[str] = Field(default_factory=list)
    depends_on: list[int] = Field(default_factory=list)
    execution_mode: str = "single"
    bindings: list[PlanBinding] = Field(default_factory=list)


class AgentPlanOutput(BaseModel):
    plan_explanation: str
    risk_summary: str
    steps: list[AgentPlanStep] = Field(default_factory=list)
    clarification: str | None = None


class PlanStepDraft(BaseModel):
    step_index: int = Field(ge=0)
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)
    parallel_group: int | None = None
    execution_mode: BindingMode = "single"
    bindings: list[PlanBinding] = Field(default_factory=list)


class PlanDraft(BaseModel):
    # Explainability fields (required by Phase 1)
    plan_explanation: str
    risk_summary: str

    # Steps + structure
    steps: list[PlanStepDraft]

    # RAG metadata
    sources: list[dict[str, Any]] = Field(default_factory=list)
    safety_content: str | None = None

    # Optional precomputed forms (allowed; validator will reconcile)
    dependency_graph: dict[int, list[int]] | None = None
    parallel_groups: list[list[int]] | None = None

    @field_validator("plan_explanation", "risk_summary")
    @classmethod
    def _non_empty_explainability(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must be non-empty")
        return normalized


class ToolInfo(BaseModel):
    name: str
    description: str
    endpoint: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    path_params: list[str] = Field(default_factory=list)
    query_params: list[str] = Field(default_factory=list)
    body_fields: list[str] = Field(default_factory=list)
    required_body_fields: list[str] = Field(default_factory=list)
    body_schema: dict[str, Any] | None = None
    param_sources: dict[str, str] = Field(default_factory=dict)

    is_read_only: bool = False
    # When true, RelevanceFilterNode must run an LLM usefulness check (Phase 4).
    requires_semantic_filter: bool = False
    requires_approval: bool = False
    side_effect_level: SideEffectLevel = "NONE"
    is_concurrency_safe: bool = True
    is_strongly_idempotent: bool = False
    capability_tags: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    user_id: str
    name: str | None = None


class SessionUpdateRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must be non-empty")
        return normalized


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    name: str | None = None
    status: SessionStatus
    current_intent: str | None = None
    plan_id: str | None = None
    operation_id: str | None = Field(
        default=None,
        description="Primary plan id for the active logical operation; matches timeline.operation_id when set.",
    )
    plan_version: int
    plan_hash: str | None = None
    current_step_index: int

    step_count: int
    replan_count: int
    llm_call_count: int
    session_started_at: datetime
    replan_context: dict[str, Any] | None = None
    pending_user_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error: str | None = None


class SessionBulkDeleteResponse(BaseModel):
    ok: bool
    user_id: str
    deleted_count: int
    session_ids: list[str] = Field(default_factory=list)


class MessageCreateRequest(BaseModel):
    role: Literal["user", "assistant", "system", "tool_result"] = "user"
    content: str
    mode: MessageMode = "normal"


class MessageResponse(BaseModel):
    message_id: str
    session_id: str
    role: str
    content: str
    mode: MessageMode = "normal"
    created_at: datetime
    step_id: str | None = None
    tool_name: str | None = None


class PlanCreateRequest(BaseModel):
    # If provided, the server validates & stores it. If omitted, planner is invoked server-side.
    draft: PlanDraft | None = None


class PlanResponse(BaseModel):
    plan_id: str
    session_id: str
    version: int
    kind: PlanKind = "execution"
    status: PlanStatus = "DRAFT"
    dependency_graph: dict[int, list[int]] | None = None
    parallel_groups: list[list[int]] | None = None
    plan_hash: str
    approved_plan_hash: str | None = None
    derived_from_plan_id: str | None = None
    plan_explanation: str | None = None
    risk_summary: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    safety_content: str | None = None
    created_at: datetime
    created_by: str


class PlanStepResponse(BaseModel):
    step_id: str
    plan_id: str
    session_id: str
    step_index: int
    tool_name: str
    args: dict[str, Any]
    execution_mode: BindingMode = "single"
    bindings: list[PlanBinding] = Field(default_factory=list)
    bulk_state: dict[str, Any] | None = None
    status: StepStatus
    idempotency_key: str
    requires_approval: bool
    approval_id: str | None = None
    retry_count: int
    max_retries: int
    last_error: str | None = None
    result: dict[str, Any] | None = None
    result_summary: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ApprovalDecisionRequest(BaseModel):
    decided_by: str | None = None
    rejection_reason: str | None = None
    args: dict[str, Any] | None = None


class ConfirmationDecisionRequest(BaseModel):
    field: str
    value: str | None = None


class ApprovalResponse(BaseModel):
    approval_id: str
    session_id: str
    subject_type: ApprovalSubjectType = "step"
    plan_id: str | None = None
    step_id: str | None = None
    tool_name: str
    args: dict[str, Any]
    risk_summary: str
    side_effect_level: SideEffectLevel
    status: Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED"]
    expires_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime


PresentationKind = Literal[
    "answer",
    "approval_required",
    "mutation_result",
    "partial_failure",
    "diagnostic",
    "cancelled",
    "rejected",
    "expired",
    "knowledge_answer",
]
PresentationState = Literal[
    "pending",
    "completed",
    "failed",
    "blocked",
    "rejected",
    "expired",
    "cancelled",
]

ResponseDocumentState = Literal[
    "running",
    "waiting_approval",
    "waiting_confirmation",
    "completed",
    "failed",
    "blocked",
    "rejected",
    "expired",
    "cancelled",
]
RunStepKind = Literal[
    "analysis",
    "read",
    "approval",
    "mutation",
    "knowledge",
    "diagnostic",
    "cancelled",
    "completed",
]
RunStepState = Literal[
    "pending",
    "current",
    "waiting",
    "completed",
    "failed",
    "rejected",
    "expired",
    "cancelled",
]


class RunStep(BaseModel):
    step_id: str = Field(min_length=1)
    kind: RunStepKind
    state: RunStepState
    title: str = Field(min_length=1)
    summary: str | None = None
    approval_id: str | None = None
    operation_id: str | None = None
    record_count: int | None = Field(default=None, ge=0)
    current: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ResponseBlockBase(BaseModel):
    id: str = Field(min_length=1)


class RunActivityBlock(ResponseBlockBase):
    type: Literal["run_activity"] = "run_activity"
    title: str = "Run activity"
    step_ids: list[str] = Field(default_factory=list)


class ShortMessageBlock(ResponseBlockBase):
    type: Literal["short_message"] = "short_message"
    message: str = Field(min_length=1)
    status: ResponseDocumentState | None = None


class ApprovalRequiredBlock(ResponseBlockBase):
    type: Literal["approval_required"] = "approval_required"
    contract: Literal["business_change_v1"] | None = None
    approval_id: str = Field(min_length=1)
    operation_id: str | None = None
    args: dict[str, Any] | None = None
    title: str = "Approval required"
    summary: str = Field(min_length=1)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    details_collapsed: bool = True


class MutationResultBlock(ResponseBlockBase):
    type: Literal["mutation_result"] = "mutation_result"
    contract: Literal["business_change_v1"] | None = None
    operation_id: str | None = None
    approval_id: str | None = None
    title: str = "Mutation result"
    summary: str = Field(min_length=1)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    groups: list[dict[str, Any]] = Field(default_factory=list)
    preview_limit: int = Field(default=5, ge=1)
    details_collapsed: bool = True
    status: Literal["completed", "partial_failure", "failed"] = "completed"


class CompletedStepBlock(ResponseBlockBase):
    type: Literal["completed_step"] = "completed_step"
    step_id: str | None = None
    operation_id: str | None = None
    approval_id: str | None = None
    title: str = Field(default="Completed step", min_length=1)
    summary: str = Field(min_length=1)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    details_collapsed: bool = True


class ResultSummaryBlock(ResponseBlockBase):
    type: Literal["result_summary"] = "result_summary"
    operation_id: str | None = None
    title: str = Field(default="Result summary", min_length=1)
    summary: str = Field(min_length=1)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    total_count: int | None = Field(default=None, ge=0)
    status: Literal["completed", "partial_failure", "failed", "empty"] = "completed"


class ResultTableBlock(ResponseBlockBase):
    type: Literal["result_table"] = "result_table"
    contract: str | None = None
    title: str = "Affected records"
    rows: list[dict[str, Any]] = Field(min_length=1)
    operation_id: str | None = None
    approval_id: str | None = None
    read_scope: str | None = None
    requested_fields: list[str] = Field(default_factory=list)
    display_mode: str | None = None
    entity_type: str | None = None
    entity_count: int | None = Field(default=None, ge=0)
    preview_limit: int = Field(default=5, ge=1)
    details_collapsed: bool = True


class StatusResultBlock(ResponseBlockBase):
    type: Literal["status_result"] = "status_result"
    contract: Literal["entity_status_v1"] = "entity_status_v1"
    operation_id: str | None = None
    title: str = Field(default="Status", min_length=1)
    summary: str = Field(min_length=1)
    entity_type: str | None = None
    entity_id: str | None = None
    primary_status: str | None = None
    fields: list[dict[str, Any]] = Field(default_factory=list)
    secondary_fields: list[dict[str, Any]] = Field(default_factory=list)
    read_scope: str | None = None
    requested_fields: list[str] = Field(default_factory=list)
    display_mode: str | None = None
    entity_count: int | None = Field(default=None, ge=0)
    preview_limit: int = Field(default=5, ge=1)
    details_collapsed: bool = True


class RecordPreviewBlock(ResponseBlockBase):
    type: Literal["record_preview"] = "record_preview"
    contract: str | None = None
    title: str = Field(default="Records", min_length=1)
    rows: list[dict[str, Any]] = Field(min_length=1)
    operation_id: str | None = None
    approval_id: str | None = None
    read_scope: str | None = None
    requested_fields: list[str] = Field(default_factory=list)
    display_mode: str | None = None
    entity_type: str | None = None
    entity_count: int | None = Field(default=None, ge=0)
    preview_limit: int = Field(default=5, ge=1)
    details_collapsed: bool = True


class KnowledgeAnswerBlock(ResponseBlockBase):
    type: Literal["knowledge_answer"] = "knowledge_answer"
    contract: Literal["knowledge_answer_v1"] | None = None
    answer: str = Field(min_length=1)
    operation_id: str | None = None
    segments: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)


class SafetyNoticeBlock(ResponseBlockBase):
    type: Literal["safety_notice"] = "safety_notice"
    contract: Literal["safety_notice_v1"] = "safety_notice_v1"
    title: str = Field(default="Safety notice", min_length=1)
    safety_content: str = Field(min_length=1)
    severity: Literal["info", "warning"] = "warning"
    operation_id: str | None = None


class SourceListBlock(ResponseBlockBase):
    type: Literal["source_list"] = "source_list"
    contract: Literal["source_list_v1"] | None = None
    sources: list[dict[str, Any]] = Field(min_length=1)
    operation_id: str | None = None


class DiagnosticBlock(ResponseBlockBase):
    type: Literal["diagnostic"] = "diagnostic"
    severity: Literal["info", "warning", "error"] = "error"
    reason: str = Field(min_length=1)
    title: str = "Needs attention"
    user_message: str = Field(min_length=1)
    cause: str | None = None
    impact: dict[str, Any] = Field(default_factory=dict)
    current_state: str | None = None
    next_action: str | None = None
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    retry_safety: dict[str, Any] = Field(default_factory=dict)
    technical_details: dict[str, Any] = Field(default_factory=dict)
    details_collapsed: bool = True


ResponseBlock = Annotated[
    RunActivityBlock
    | ShortMessageBlock
    | ApprovalRequiredBlock
    | MutationResultBlock
    | CompletedStepBlock
    | ResultSummaryBlock
    | ResultTableBlock
    | StatusResultBlock
    | RecordPreviewBlock
    | KnowledgeAnswerBlock
    | SafetyNoticeBlock
    | SourceListBlock
    | DiagnosticBlock,
    Field(discriminator="type"),
]


class ResponseDocument(BaseModel):
    version: Literal[1] = 1
    id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    turn_id: str | None = None
    operation_id: str | None = None
    revision: int = Field(ge=0)
    revision_source: str = Field(min_length=1)
    state: ResponseDocumentState
    status: ResponseDocumentState
    summary: str | None = None
    message: str | None = None
    current_step_id: str | None = None
    run_steps: list[RunStep] = Field(default_factory=list)
    blocks: list[ResponseBlock] = Field(default_factory=list)
    invariants: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class PresentationResponse(BaseModel):
    kind: PresentationKind
    state: PresentationState
    operation_id: str | None = None
    approval_id: str | None = None
    summary: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    invariants: dict[str, Any] = Field(default_factory=dict)


class TimelineEventResponse(BaseModel):
    event_id: str
    event_type: Literal[
        "user_message",
        "plan_created",
        "execution_started",
        "tool_started",
        "tool_result",
        "approval_required",
        "approval_decided",
        "confirmation_required",
        "confirmation_decided",
        "replan_requested",
        "session_blocked",
        "session_failed",
        "session_completed",
    ]
    content: str
    created_at: datetime
    role: Literal["user", "assistant", "system"] = "assistant"
    mode: MessageMode | None = None
    turn_id: str | None = None
    operation_id: str | None = Field(
        default=None,
        description="Logical operation scope (plan_id) for grouping activity across turns and approval resumes.",
    )
    step_context: dict[str, Any] | None = None
    step_id: str | None = None
    approval_id: str | None = None
    tool_name: str | None = None
    status: str | None = None
    details: dict[str, Any] | None = None
    presentation: PresentationResponse | None = Field(
        default=None,
        description="Typed display contract for this event. Legacy content/details remain for compatibility.",
    )


class ActivityStepResponse(BaseModel):
    id: str
    timestamp: int
    group: Literal["planning", "research", "approval", "response", "system"]
    label: str
    detail: str | None = None
    state: Literal["running", "success", "retry", "waiting", "error", "complete"]


class ResumeHintResponse(BaseModel):
    applying_after_approval: bool
    approval_id: str | None = None
    decided_at: str | None = None


class SessionSnapshotResponse(BaseModel):
    session: SessionResponse
    plan: PlanResponse | None = None
    steps: list[PlanStepResponse] = Field(default_factory=list)
    pending_approval: ApprovalResponse | None = None
    timeline: list[TimelineEventResponse] = Field(default_factory=list)
    snapshot_revision: int = Field(
        default=0,
        description="Monotonic session snapshot revision. Mirrors event_seq during the response-document migration.",
    )
    cursor: int = Field(
        default=0,
        description="Monotonic event_seq cursor. Advances on every state-changing write. Used by the notification SSE stream to detect staleness.",
    )
    phase: SessionStatus = Field(
        default="IDLE",
        description="Authoritative session phase, derived from session.status. Clients should gate terminal UI on phase=='COMPLETED'.",
    )
    resume_hint: ResumeHintResponse | None = Field(
        default=None,
        description="Server-derived hint that the session is applying approved changes. Replaces the client-side isResumingAfterApproval flag.",
    )
    activity_steps: list[ActivityStepResponse] = Field(
        default_factory=list,
        description="Server-rendered activity timeline steps. Stable ids act:{event_id}. Clients should prefer these over client-side derivation.",
    )
    presentation: PresentationResponse = Field(
        default_factory=lambda: PresentationResponse(
            kind="diagnostic",
            state="blocked",
            summary="Snapshot presentation has not been derived.",
            diagnostics={"reason": "presentation_not_derived"},
        ),
        description="Authoritative typed presentation for the current snapshot/final response.",
    )
    response_document: ResponseDocument | None = Field(
        default=None,
        description="Additive typed response document. Frontend rendering continues to use presentation until migration phases enable this contract.",
    )


class ValidationErrorResponse(BaseModel):
    errors: list[str]


class DeadLetterResponse(BaseModel):
    dlq_id: str
    session_id: str
    step_id: str | None = None
    failure_type: str
    reason: str
    payload: dict[str, Any]
    status: str
    replayed_at: datetime | None = None
    replayed_by: str | None = None
    dismissed_at: datetime | None = None
    dismissed_reason: str | None = None
    created_at: datetime


class DeadLetterDismissRequest(BaseModel):
    dismissed_reason: str
    dismissed_by: str | None = None


class DeadLetterPushRequest(BaseModel):
    session_id: str
    step_id: str | None = None
    failure_type: str
    reason: str
    payload: dict[str, Any] = Field(default_factory=dict)


class DeadLetterReplayRequest(BaseModel):
    replayed_by: str | None = None
