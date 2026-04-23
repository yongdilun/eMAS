from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SessionStatus = Literal[
    "IDLE",
    "PLANNING",
    "WAITING_APPROVAL",
    "EXECUTING",
    "BLOCKED",
    "FAILED",
    "COMPLETED",
]

StepStatus = Literal[
    "NOT_STARTED",
    "IN_PROGRESS",
    "DONE",
    "FAILED",
    "SKIPPED",
    "AMBIGUOUS",
]

SideEffectLevel = Literal["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


class PlanStepDraft(BaseModel):
    step_index: int = Field(ge=0)
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)
    parallel_group: int | None = None


class PlanDraft(BaseModel):
    # Explainability fields (required by Phase 1)
    plan_explanation: str
    risk_summary: str

    # Steps + structure
    steps: list[PlanStepDraft]

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

    is_read_only: bool = False
    requires_approval: bool = False
    side_effect_level: SideEffectLevel = "NONE"
    is_concurrency_safe: bool = True
    is_strongly_idempotent: bool = False
    capability_tags: list[str] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    user_id: str


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    status: SessionStatus
    current_intent: str | None = None
    plan_id: str | None = None
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


class MessageCreateRequest(BaseModel):
    role: Literal["user", "assistant", "system", "tool_result"] = "user"
    content: str


class MessageResponse(BaseModel):
    message_id: str
    session_id: str
    role: str
    content: str
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
    dependency_graph: dict[int, list[int]] | None = None
    parallel_groups: list[list[int]] | None = None
    plan_hash: str
    plan_explanation: str | None = None
    risk_summary: str | None = None
    created_at: datetime
    created_by: str


class PlanStepResponse(BaseModel):
    step_id: str
    plan_id: str
    session_id: str
    step_index: int
    tool_name: str
    args: dict[str, Any]
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


class ApprovalResponse(BaseModel):
    approval_id: str
    session_id: str
    step_id: str
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
