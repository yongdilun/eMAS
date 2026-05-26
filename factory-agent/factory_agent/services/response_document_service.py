from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from factory_agent.graph.noop_mutations import (
    NO_OP_MUTATION_REASON,
    NO_OP_MUTATION_STATUS,
    normalize_no_op_mutation,
)
from factory_agent.planning.query_shape import parse_fields_arg
from factory_agent.rag.source_metadata import (
    insufficient_context_answer,
    is_insufficient_context_answer,
    normalize_source_locators,
    sanitize_rag_answer_text,
)
from factory_agent.schemas import (
    ActivityStepResponse,
    ApprovalRequiredBlock,
    ApprovalResponse,
    CompletedStepBlock,
    DiagnosticBlock,
    KnowledgeAnswerBlock,
    MutationResultBlock,
    PlanResponse,
    PlanStepResponse,
    PresentationResponse,
    RecordPreviewBlock,
    ResponseBlock,
    ResponseDocument,
    ResultSummaryBlock,
    ResultTableBlock,
    RunActivityBlock,
    RunStep,
    SafetyNoticeBlock,
    ShortMessageBlock,
    SourceListBlock,
    StatusResultBlock,
    TimelineEventResponse,
)


_SUCCESS_ROW_STATES = {"ok", "success", "succeeded", "done", "updated", "created", "deleted", "applied"}
_FAILED_ROW_STATES = {"failed", "error", "errored", "rejected", "conflict", "skipped_failed"}
_WRITE_TOOL_RE = re.compile(r"^(post|put|patch|delete)__", re.IGNORECASE)
_READ_TOOL_RE = re.compile(r"^(get|list|search|read)__", re.IGNORECASE)
_SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|authorization|bearer|password|secret|token)", re.IGNORECASE)
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|password|secret|token)\s*[:=]\s*['\"]?[^,\s'\"]+"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]+")
_STACK_TRACE_RE = re.compile(r"(?is)traceback\s+\(most recent call last\):.*")
_HTTP_STATUS_RE = re.compile(r"\bhttp\s*(?P<status>[45]\d\d)\b", re.IGNORECASE)
_AUTH_DENIED_RE = re.compile(
    r"\b(unauthori[sz]ed|forbidden|access denied|permission denied|insufficient permissions?|"
    r"authentication required|authorization denied|not authorized|requires? authentication|401|403)\b",
    re.IGNORECASE,
)
_USER_FACING_FAILURE_RE = re.compile(
    r"\b(could\s+not|cannot|failed|failure|error|unavailable|retry|expired|stale|did\s+not\s+apply|not\s+apply|no\s+\w+\s+(?:rows?\s+)?(?:were\s+)?changed|no\s+audit\s+rows?)\b",
    re.IGNORECASE,
)

_ACTION_LABELS = {
    "retry_from_checkpoint": "Retry from last safe point",
    "retry_failed_rows_only": "Retry failed rows only",
    "check_status": "Check current status",
    "request_new_approval": "Request a new approval",
    "start_new_request": "Start a new request",
    "sign_in_again": "Sign in again",
    "view_affected_records": "View affected records",
    "view_diagnostics": "View diagnostics",
    "export_audit_details": "Export audit details",
}

ENTITY_STATUS_CONTRACT = "entity_status_v1"
BUSINESS_CHANGE_CONTRACT = "business_change_v1"
NO_OP_MUTATION_CONTRACT = "entity_agnostic_no_matching_records_v1"
SAFETY_NOTICE_CONTRACT = "safety_notice_v1"
KNOWLEDGE_ANSWER_CONTRACT = "knowledge_answer_v1"
SOURCE_CITATION_CONTRACT = "source_citation_v1"
SOURCE_LIST_CONTRACT = "source_list_v1"
SOURCE_LOCATOR_CONTRACT = "source_locator_v1"
READ_DISPLAY_PREVIEW_LIMIT = 5
READ_SCOPE_STATUS_ONLY = "status_only"
READ_SCOPE_DETAILS = "details"
READ_SCOPE_RECORDS = "records"
DISPLAY_MODE_COMPACT_STATUS_CARD = "compact_status_card"
DISPLAY_MODE_DETAIL_STATUS_CARD = "detail_status_card"
DISPLAY_MODE_COLLECTION_TABLE = "collection_table"
DISPLAY_MODE_COLLAPSED_COLLECTION_TABLE = "collapsed_collection_table"
DISPLAY_MODE_RECORD_PREVIEW = "record_preview"
DISPLAY_MODE_NO_MATCH_DIAGNOSTIC = "no_match_diagnostic"


@dataclass(frozen=True)
class FailureTemplate:
    reason: str
    title: str
    user_message: str
    cause: str
    current_state: str
    next_action: str
    action_ids: tuple[str, ...]
    retry_policy: str
    safe_to_retry: bool
    severity: str = "error"


@dataclass
class FailureProfile:
    reason: str
    severity: str
    title: str
    user_message: str
    cause: str
    impact: dict[str, Any]
    current_state: str
    next_action: str
    next_actions: list[dict[str, Any]]
    retry_safety: dict[str, Any]
    technical_details: dict[str, Any]


_FAILURE_TEMPLATES: dict[str, FailureTemplate] = {
    "planner_timeout": FailureTemplate(
        reason="planner_timeout",
        title="Run interrupted",
        user_message="I could not finish this request because the planner timed out while preparing the next step.",
        cause="The planner timed out before it produced a safe next step.",
        current_state="The run stopped before any unconfirmed next action could continue.",
        next_action="Retry from the last safe point, or start a new request if the context changed.",
        action_ids=("retry_from_checkpoint", "start_new_request", "view_diagnostics"),
        retry_policy="safe_from_checkpoint_when_no_commit_is_uncertain",
        safe_to_retry=True,
    ),
    "planner_validation_loop": FailureTemplate(
        reason="planner_validation_loop",
        title="Planner stopped safely",
        user_message="I stopped the run because repeated planner repairs still did not satisfy the execution guard.",
        cause="The decision guard rejected repeated planner repairs before unsafe execution.",
        current_state="No guarded step was allowed to continue from the failed planner decision.",
        next_action="Start a clearer request or review diagnostics before retrying.",
        action_ids=("start_new_request", "view_diagnostics"),
        retry_policy="retry_requires_request_change",
        safe_to_retry=False,
    ),
    "llm_timeout": FailureTemplate(
        reason="llm_timeout",
        title="Answer timed out",
        user_message="I could not finish the generated answer before the model timed out.",
        cause="The language-model call timed out.",
        current_state="The run stopped while preparing the answer.",
        next_action="Retry from the last safe point.",
        action_ids=("retry_from_checkpoint", "start_new_request", "view_diagnostics"),
        retry_policy="safe_from_checkpoint",
        safe_to_retry=True,
    ),
    "tool_timeout": FailureTemplate(
        reason="tool_timeout",
        title="Tool timed out",
        user_message="I could not finish because a backend tool timed out.",
        cause="A backend tool call exceeded its timeout.",
        current_state="The run stopped at the timed-out tool call.",
        next_action="Check current status before retrying if the tool may have changed data.",
        action_ids=("check_status", "retry_from_checkpoint", "view_diagnostics"),
        retry_policy="check_status_before_retry_when_write_was_attempted",
        safe_to_retry=True,
    ),
    "tool_http_error": FailureTemplate(
        reason="tool_http_error",
        title="Backend tool failed",
        user_message="Could not complete because a backend tool returned an error. Please retry only after checking current status.",
        cause="A backend tool returned an unsuccessful HTTP response.",
        current_state="The run stopped at the failed backend tool call.",
        next_action="Check current status before retrying.",
        action_ids=("check_status", "start_new_request", "view_diagnostics"),
        retry_policy="check_status_first",
        safe_to_retry=False,
    ),
    "tool_schema_error": FailureTemplate(
        reason="tool_schema_error",
        title="Tool payload was rejected",
        user_message="I could not finish because a tool payload did not match the expected schema.",
        cause="The backend rejected the tool request or response schema.",
        current_state="The run stopped before the invalid payload could be trusted.",
        next_action="Review diagnostics and start a new request.",
        action_ids=("start_new_request", "view_diagnostics"),
        retry_policy="retry_requires_payload_fix",
        safe_to_retry=False,
    ),
    "approval_expired": FailureTemplate(
        reason="approval_expired",
        title="Approval expired",
        user_message="The approval expired, so I did not apply that pending change.",
        cause="The approval reached its expiry time before it was accepted.",
        current_state="No action is available on the expired approval.",
        next_action="Request a new approval if you still want to make the change.",
        action_ids=("request_new_approval", "start_new_request", "view_diagnostics"),
        retry_policy="requires_new_approval",
        safe_to_retry=False,
    ),
    "approval_rejected": FailureTemplate(
        reason="approval_rejected",
        title="Approval rejected",
        user_message="The approval was rejected, so I did not apply that pending change.",
        cause="The operator rejected the approval.",
        current_state="The rejected approval is closed and cannot be applied.",
        next_action="Start a new request if you want a different change.",
        action_ids=("start_new_request", "view_diagnostics"),
        retry_policy="requires_new_request",
        safe_to_retry=False,
    ),
    "approval_stale": FailureTemplate(
        reason="approval_stale",
        title="Approval is stale",
        user_message="That approval is stale because the session changed state, so I did not apply it.",
        cause="The approval no longer matched the current session state.",
        current_state="The stale approval is closed and cannot mutate data.",
        next_action="Check current status, then request a new approval if needed.",
        action_ids=("check_status", "request_new_approval", "view_diagnostics"),
        retry_policy="requires_fresh_approval",
        safe_to_retry=False,
    ),
    "network_disconnect": FailureTemplate(
        reason="network_disconnect",
        title="Connection interrupted",
        user_message="I could not finish because the backend connection was interrupted.",
        cause="A network connection closed before the backend operation completed.",
        current_state="The commit state may be unknown until status is checked.",
        next_action="Check current status before retrying.",
        action_ids=("check_status", "start_new_request", "view_diagnostics"),
        retry_policy="check_status_first",
        safe_to_retry=False,
    ),
    "sse_stream_interrupted": FailureTemplate(
        reason="sse_stream_interrupted",
        title="Stream interrupted",
        user_message="The live update stream was interrupted before the run could report a clean final state.",
        cause="The server-sent event stream disconnected.",
        current_state="The latest snapshot should be checked before taking another action.",
        next_action="Check current status.",
        action_ids=("check_status", "view_diagnostics"),
        retry_policy="refresh_snapshot_before_retry",
        safe_to_retry=False,
    ),
    "snapshot_contract_invalid": FailureTemplate(
        reason="snapshot_contract_invalid",
        title="Snapshot invalid",
        user_message="I could not render the run state because the snapshot payload was invalid.",
        cause="The backend snapshot did not match the expected contract.",
        current_state="The UI should treat this as a diagnostic state.",
        next_action="View diagnostics and retry after the snapshot is healthy.",
        action_ids=("check_status", "view_diagnostics"),
        retry_policy="retry_after_contract_fix",
        safe_to_retry=False,
    ),
    "response_document_invalid": FailureTemplate(
        reason="response_document_invalid",
        title="Response document invalid",
        user_message="I could not render a valid response document for this run.",
        cause="The response document payload did not match the expected contract.",
        current_state="The run is shown as diagnostic instead of falling back to older presentation text.",
        next_action="View diagnostics and start a new request if needed.",
        action_ids=("start_new_request", "view_diagnostics"),
        retry_policy="retry_after_contract_fix",
        safe_to_retry=False,
    ),
    "auth_denied": FailureTemplate(
        reason="auth_denied",
        title="Access denied",
        user_message="I could not continue because backend authorization was denied.",
        cause="The backend rejected the request for authorization reasons.",
        current_state="No protected action was allowed to continue.",
        next_action="Sign in again or ask an administrator to check access.",
        action_ids=("sign_in_again", "view_diagnostics"),
        retry_policy="requires_auth_fix",
        safe_to_retry=False,
    ),
    "cancelled_by_user": FailureTemplate(
        reason="cancelled_by_user",
        title="Run cancelled",
        user_message="The run was cancelled. I stopped work and did not continue pending actions.",
        cause="The operator cancelled the run.",
        current_state="The run is closed in a cancelled state.",
        next_action="Start a new request if you want to run it again.",
        action_ids=("start_new_request", "view_diagnostics"),
        retry_policy="requires_new_request",
        safe_to_retry=False,
    ),
    "partial_commit_failure": FailureTemplate(
        reason="partial_commit_failure",
        title="Partial failure",
        user_message="Some rows were updated, but other rows failed.",
        cause="The bulk operation completed only part of the write set.",
        current_state="Successful rows remain applied; failed rows still need attention.",
        next_action="Retry failed rows only after checking the current status.",
        action_ids=("view_affected_records", "retry_failed_rows_only", "export_audit_details", "view_diagnostics"),
        retry_policy="retry_failed_rows_only",
        safe_to_retry=True,
    ),
    "planner_no_action": FailureTemplate(
        reason="planner_no_action",
        title="Request could not start",
        user_message=(
            "I could not start this request because the planner did not produce a safe plan, approval, "
            "or final result."
        ),
        cause="The planner returned no executable steps or approval request for an actionable prompt.",
        current_state="The request is blocked before execution; no data changes were applied.",
        next_action="Check tool availability or refine the request, then start a new request.",
        action_ids=("check_status", "start_new_request", "view_diagnostics"),
        retry_policy="retry_requires_plan_or_tool_fix",
        safe_to_retry=False,
    ),
    "unable_to_start_request": FailureTemplate(
        reason="unable_to_start_request",
        title="Request could not start",
        user_message="I could not start this request before the backend reached a safe running or terminal state.",
        cause="The backend stopped before it created a plan, approval, or terminal result.",
        current_state="The request is failed before execution; no successful result is being claimed.",
        next_action="Check diagnostics, then retry only after confirming the current state.",
        action_ids=("check_status", "start_new_request", "view_diagnostics"),
        retry_policy="check_status_first",
        safe_to_retry=False,
    ),
    "orphan_turn_state": FailureTemplate(
        reason="orphan_turn_state",
        title="Request state needs repair",
        user_message=(
            "I could not continue because the current state has a user request but no running work, "
            "approval, or terminal result."
        ),
        cause="The session snapshot violated the orphan-turn invariant.",
        current_state="The request is blocked; no data changes are being claimed.",
        next_action="Check current status, then start a new request if the original one did not continue.",
        action_ids=("check_status", "start_new_request", "view_diagnostics"),
        retry_policy="check_status_first",
        safe_to_retry=False,
    ),
    "malformed_response_payload": FailureTemplate(
        reason="malformed_response_payload",
        title="Malformed response",
        user_message="I could not finish because a backend response payload was malformed or invalid.",
        cause="A backend response could not be parsed into the expected structure.",
        current_state="The run stopped before the malformed payload could be used as final truth.",
        next_action="Check current status and review diagnostics.",
        action_ids=("check_status", "view_diagnostics"),
        retry_policy="check_status_first",
        safe_to_retry=False,
    ),
    "no_results": FailureTemplate(
        reason="no_results",
        title="No results",
        user_message="I could not produce a usable final response for this run.",
        cause="The final response payload was empty or contained no renderable result.",
        current_state="No successful result is being claimed.",
        next_action="Start a new request or view diagnostics.",
        action_ids=("start_new_request", "view_diagnostics"),
        retry_policy="safe_new_request",
        safe_to_retry=True,
        severity="warning",
    ),
    "unknown_failure": FailureTemplate(
        reason="unknown_failure",
        title="Run needs attention",
        user_message="I could not finish this request. The run stopped before a safe final result was available.",
        cause="The backend reported a failure that does not match a more specific failure type.",
        current_state="The run is in a diagnostic state.",
        next_action="Check current status before retrying.",
        action_ids=("check_status", "start_new_request", "view_diagnostics"),
        retry_policy="check_status_first",
        safe_to_retry=False,
    ),
}


@dataclass
class MutationGroup:
    key: str
    operation_id: str | None
    approval_id: str | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    step_ids: list[str] = field(default_factory=list)
    completed_at: datetime | None = None
    status: str = "completed"
    first_seen: int = 0
    entity_type: str | None = None
    selector_summary: str | None = None
    change_summary: str | None = None
    matched_count: int | None = None
    changed_count: int | None = None
    reason: str | None = None


@dataclass
class ReadEvidence:
    key: str
    operation_id: str | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    step_ids: list[str] = field(default_factory=list)
    completed_at: datetime | None = None
    tool_name: str | None = None
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReadDisplayPolicy:
    read_scope: str
    requested_fields: list[str]
    display_mode: str
    entity_count: int
    preview_limit: int = READ_DISPLAY_PREVIEW_LIMIT
    details_collapsed: bool = True
    entity_type: str | None = None
    contract: str | None = None
    sort_fields: list[str] = field(default_factory=list)


def _trimmed(value: Any) -> str:
    return str(value or "").strip()


_FOOTNOTE_DEFINITION_RE = re.compile(
    r"(?m)^[ \t]*\[\^[^\]\n]+\]:[^\n]*(?:\n[ \t]+[^\n]*)*"
)
_FOOTNOTE_MARKER_RE = re.compile(r"\[\^([^\]\n]+)\]|\[(\d+)\]")
_FOOTNOTE_MARKER_CLUSTER_RE = re.compile(r"((?:\s*(?:\[\^[^\]\n]+\]|\[\d+\]))+)")
_NUMBERED_SEGMENT_START_RE = re.compile(r"^\s*(?:[-*]\s*)?\d+[\.)]\s+")
_NUMBERED_INLINE_STEP_RE = re.compile(r"(?<!\w)(\d+)[\.)]\s+")
_PROCEDURE_INTRO_SEGMENT_RE = re.compile(
    r"\b(?:following|these)\b.{0,160}\b(?:steps?|sequence|procedure)\b|"
    r"\b(?:before|prior to)\b.{0,160}\b(?:service|maintenance|shutdown)\b.{0,160}"
    r"\b(?:steps?|complete|accomplished)\b",
    re.IGNORECASE,
)
_PROCEDURE_TRAILING_SUMMARY_RE = re.compile(
    r"\b(?:these|the)\s+steps?\s+must\s+be\s+accomplished\b|"
    r"\b(?:these|the)\s+steps?\s+must\b",
    re.IGNORECASE,
)
_PROCEDURE_ACTION_TERMS_RE = re.compile(
    r"\b(apply|block|check|complete|confirm|disconnect|deenergiz|energiz|isolate|lockout|lock\s+out|"
    r"notify|prepare|release|remove|restrain|service|shut\s+down|shutdown|tagout|tag\s+out|verify)\b",
    re.IGNORECASE,
)
_CONDITIONAL_STEP_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=(?:If|When|After|Before|Once)\b)")
_SOURCE_PAGE_TEXT_RE = re.compile(
    r"\[Source page\s+(\d+)\s+text\]\s*(.*?)(?=\n\s*\[Source page\s+\d+\s+text\]|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_CLAIM_TOKEN_STOPWORDS = {
    "according",
    "after",
    "all",
    "and",
    "are",
    "before",
    "be",
    "been",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "must",
    "of",
    "or",
    "s",
    "that",
    "the",
    "these",
    "this",
    "to",
    "with",
    "workers",
}


def _strip_footnote_markup(value: Any) -> str:
    text = sanitize_rag_answer_text(value)
    text = _FOOTNOTE_DEFINITION_RE.sub("", text)
    text = _FOOTNOTE_MARKER_RE.sub("", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def _citation_marker_values(value: str) -> list[str]:
    markers: list[str] = []
    for match in _FOOTNOTE_MARKER_RE.finditer(value):
        marker = match.group(1) or match.group(2)
        if marker:
            markers.append(marker)
    return markers


def _merge_adjacent_knowledge_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        citation_ids = [
            str(citation_id)
            for citation_id in dict.fromkeys(segment.get("citation_ids") or [])
            if str(citation_id or "").strip()
        ]
        normalized = {"text": text, "citation_ids": citation_ids}
        if merged and merged[-1].get("citation_ids") == citation_ids:
            previous = str(merged[-1].get("text") or "").strip()
            separator = "\n" if _should_join_knowledge_segments_with_newline(previous, text) else " "
            merged[-1]["text"] = f"{previous}{separator}{text}".strip()
            continue
        merged.append(normalized)
    return merged


def _should_join_knowledge_segments_with_newline(previous: str, current: str) -> bool:
    return (
        "\n" in previous
        or "\n" in current
        or (
            _NUMBERED_SEGMENT_START_RE.search(previous) is not None
            and _NUMBERED_SEGMENT_START_RE.search(current) is not None
        )
    )


def _expand_procedure_knowledge_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    changed = False
    for segment in segments:
        split_steps = _procedure_step_segments_from_text(
            str(segment.get("text") or ""),
            [
                str(citation_id)
                for citation_id in segment.get("citation_ids") or []
                if str(citation_id or "").strip()
            ],
        )
        if split_steps:
            expanded.extend(split_steps)
            changed = True
        else:
            expanded.append(segment)
    return expanded if changed else segments


def _procedure_step_segments_from_text(text: str, citation_ids: list[str]) -> list[dict[str, Any]] | None:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not citation_ids:
        return None
    steps: list[str] = []
    skipped_intro = False

    numbered_line_count = sum(1 for line in lines if _NUMBERED_SEGMENT_START_RE.match(line))
    if numbered_line_count >= 2:
        for line in lines:
            if _is_procedure_intro_segment(line) or _is_procedure_summary_segment(line):
                skipped_intro = True
                continue
            match = _NUMBERED_SEGMENT_START_RE.match(line)
            if not match:
                return None
            step_texts = _split_procedure_segment_text(line[match.end() :])
            if not step_texts:
                return None
            steps.extend(step_texts)
    else:
        matches = list(_NUMBERED_INLINE_STEP_RE.finditer(str(text or "")))
        if len(matches) < 2:
            return None
        prefix = str(text or "")[: matches[0].start()].strip()
        if prefix:
            if not _is_procedure_intro_segment(prefix):
                return None
            skipped_intro = True
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(str(text or ""))
            step_texts = _split_procedure_segment_text(str(text or "")[match.end() : end])
            if not step_texts:
                return None
            steps.extend(step_texts)

    if len(steps) < 2:
        return None
    return [
        {
            "text": f"{index}. {step_text}",
            "citation_ids": citation_ids,
        }
        for index, step_text in enumerate(steps, start=1)
    ]


def _is_procedure_intro_segment(text: str) -> bool:
    stripped = str(text or "").strip()
    return bool(stripped.endswith(":") and _PROCEDURE_INTRO_SEGMENT_RE.search(stripped))


def _is_procedure_summary_segment(text: str) -> bool:
    stripped = _strip_footnote_markup(text)
    return bool(_PROCEDURE_TRAILING_SUMMARY_RE.search(stripped))


def _split_procedure_segment_text(text: str) -> list[str]:
    stripped = _strip_footnote_markup(_drop_trailing_procedure_summary(text))
    stripped = re.sub(r"\s+", " ", stripped).strip(" \t\r\n;:")
    if not stripped:
        return []
    pieces = [piece.strip() for piece in _CONDITIONAL_STEP_BOUNDARY_RE.split(stripped) if piece.strip()]
    if len(pieces) <= 1:
        return [_normalize_procedure_step_text(stripped)]
    split_steps: list[str] = [_normalize_procedure_step_text(pieces[0])]
    for piece in pieces[1:]:
        if _PROCEDURE_ACTION_TERMS_RE.search(piece):
            split_steps.append(_normalize_procedure_step_text(piece))
        else:
            split_steps[-1] = _normalize_procedure_step_text(f"{split_steps[-1]} {piece}")
    return [step for step in split_steps if step]


def _drop_trailing_procedure_summary(text: str) -> str:
    match = _PROCEDURE_TRAILING_SUMMARY_RE.search(text or "")
    if not match:
        return text
    return text[: match.start()].strip()


def _normalize_procedure_step_text(text: str) -> str:
    stripped = _strip_footnote_markup(text)
    stripped = re.sub(r"\s+", " ", stripped).strip(" \t\r\n;:")
    if not stripped:
        return ""
    if stripped[-1] not in ".!?":
        stripped = f"{stripped}."
    return stripped


def _segments_are_procedure_steps(segments: list[dict[str, Any]]) -> bool:
    if len(segments) < 1:
        return False
    return all(_NUMBERED_SEGMENT_START_RE.match(str(segment.get("text") or "")) for segment in segments)


def _claim_text_for_support(text: Any) -> str:
    stripped = _strip_footnote_markup(text)
    stripped = _NUMBERED_SEGMENT_START_RE.sub("", stripped).strip()
    return _normalize_procedure_step_text(stripped)


def _claim_support_stem(token: str) -> str:
    if token.startswith("deenerg"):
        return "deenerg"
    if token.startswith("energ"):
        return "energ"
    if token.startswith("notif"):
        return "notif"
    if token.startswith("reaccumul"):
        return "reaccumul"
    if token.startswith("reenerg"):
        return "reenerg"
    if token.startswith("verif"):
        return "verif"
    if token.endswith("ces") and len(token) > 4:
        return token[:-1]
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


def _claim_support_tokens(text: Any) -> set[str]:
    normalized = re.sub(r"\block\s+out\b", "lockout", str(text or "").lower())
    normalized = re.sub(r"\btag\s+out\b", "tagout", normalized)
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", normalized):
        token = _claim_support_stem(raw)
        if len(token) < 3 or token in _CLAIM_TOKEN_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _compact_evidence_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _evidence_text(evidence: dict[str, Any]) -> str:
    parts = [
        evidence.get("snippet"),
        evidence.get("text"),
        evidence.get("text_search"),
        evidence.get("section_title"),
    ]
    section_path = evidence.get("section_path")
    if isinstance(section_path, list):
        parts.append(" ".join(str(part) for part in section_path if part))
    else:
        parts.append(section_path)
    return " ".join(str(part or "") for part in parts)


def _inherit_evidence_fields(
    child: dict[str, Any],
    parent: dict[str, Any],
    citation: dict[str, Any],
) -> dict[str, Any]:
    inherited = dict(child)
    for key in (
        "source_number",
        "source_id",
        "doc_id",
        "title",
        "organization",
        "pdf_url",
        "page_count",
    ):
        if inherited.get(key) in (None, "", [], {}):
            inherited[key] = parent.get(key) if parent.get(key) not in (None, "", [], {}) else citation.get(key)
    return {key: value for key, value in inherited.items() if value not in (None, "", [], {})}


def _page_text_evidence_items(evidence: dict[str, Any], citation: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    text = str(evidence.get("text") or evidence.get("snippet") or "")
    for match in _SOURCE_PAGE_TEXT_RE.finditer(text):
        page = int(match.group(1))
        snippet = re.sub(r"\s+", " ", match.group(2)).strip()
        if not snippet:
            continue
        items.append(
            _inherit_evidence_fields(
                {
                    "chunk_id": f"{evidence.get('chunk_id') or citation.get('chunk_id')}:page:{page}",
                    "page": page,
                    "snippet": snippet,
                },
                evidence,
                citation,
            )
        )
    return items


def _flatten_claim_evidence_items(citation: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = [item for item in citation.get("evidence_snippets") or [] if isinstance(item, dict) and item]
    flattened: list[dict[str, Any]] = []

    def add_item(item: dict[str, Any], parent: dict[str, Any] | None = None) -> None:
        base_parent = parent or citation
        normalized = _inherit_evidence_fields(item, base_parent, citation)
        for page_item in _page_text_evidence_items(normalized, citation):
            flattened.append(page_item)
        nested_found = False
        for key in ("source_chunk_evidence", "evidence", "evidence_snippets"):
            nested = normalized.get(key)
            if not isinstance(nested, list):
                continue
            for child in nested:
                if isinstance(child, dict) and child:
                    nested_found = True
                    add_item(child, normalized)
        if normalized.get("snippet") or normalized.get("text") or normalized.get("text_search"):
            flattened.append(normalized)

    for item in raw_items:
        add_item(item)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in flattened:
        key = (
            str(item.get("doc_id") or ""),
            str(item.get("chunk_id") or ""),
            str(item.get("page") or ""),
            _compact_evidence_text(item.get("text_search") or item.get("snippet") or item.get("text"))[:160],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _strip_support_text(value: Any) -> str:
    text = _strip_footnote_markup(value)
    text = re.sub(r"^\s*\(?\d+\)?[\.)]?\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n;:,.")
    return text


def _support_text_from_evidence_snippet(claim: str, evidence: dict[str, Any]) -> str | None:
    evidence_text = _evidence_text(evidence)
    evidence_snippet = _strip_support_text(evidence.get("text_search") or evidence.get("snippet") or evidence.get("text"))
    claim_tokens = _claim_support_tokens(claim)
    evidence_tokens = _claim_support_tokens(evidence_snippet)
    if evidence_snippet and evidence_tokens and evidence_tokens <= claim_tokens:
        return evidence_snippet

    claim_words = re.findall(r"[A-Za-z0-9()/-]+", claim)
    if len(claim_words) >= 2:
        pattern = r"\b" + r"\W+".join(re.escape(word) for word in claim_words) + r"\b"
        match = re.search(pattern, evidence_text, flags=re.IGNORECASE)
        if match:
            return _strip_support_text(match.group(0))

    compact_claim = _compact_evidence_text(_strip_support_text(claim))
    if compact_claim and compact_claim in _compact_evidence_text(evidence_text):
        return _strip_support_text(claim)
    return None


def _claim_evidence_payload(
    *,
    claim_text: Any,
    evidence: dict[str, Any],
    citation: dict[str, Any],
    evidence_index: int,
) -> dict[str, Any]:
    support_text = _support_text_from_evidence_snippet(_claim_text_for_support(claim_text), evidence)
    payload: dict[str, Any] = {
        "contract": "source_evidence_v1",
        "evidence_id": f"{citation.get('citation_id')}:evidence-{evidence_index}",
        "locator_confidence": "exact" if support_text else "page_only",
        "source_id": evidence.get("source_id") or citation.get("source_id"),
        "source_number": evidence.get("source_number") or citation.get("source_number"),
        "doc_id": evidence.get("doc_id") or citation.get("doc_id"),
        "chunk_id": evidence.get("chunk_id") or citation.get("chunk_id"),
        "title": evidence.get("title") or citation.get("title"),
        "organization": evidence.get("organization") or citation.get("organization"),
        "snippet": support_text or evidence.get("snippet") or evidence.get("text") or evidence.get("text_search"),
        "page": evidence.get("page") or citation.get("page"),
        "page_label": evidence.get("page_label") or citation.get("page_label"),
        "pdf_url": evidence.get("pdf_url") or citation.get("pdf_url"),
        "page_count": evidence.get("page_count") or citation.get("page_count"),
    }
    for key in ("bbox", "char_range"):
        if evidence.get(key) not in (None, "", [], {}):
            payload[key] = evidence.get(key)
            payload["locator_confidence"] = "exact"
    if support_text:
        payload["text_search"] = support_text
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _ranked_evidence_for_claim(claim_text: Any, citation: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_items = _flatten_claim_evidence_items(citation)
    if not evidence_items:
        return []
    claim = _claim_text_for_support(claim_text)
    claim_tokens = _claim_support_tokens(claim)
    if not claim_tokens:
        return []

    scored: list[tuple[float, int, dict[str, Any]]] = []
    for evidence in evidence_items:
        evidence_tokens = _claim_support_tokens(_evidence_text(evidence))
        overlap = len(claim_tokens & evidence_tokens)
        if overlap <= 0:
            continue
        support_text = _support_text_from_evidence_snippet(claim, evidence)
        coverage = overlap / max(1, len(claim_tokens))
        locator = 1 if any(evidence.get(key) not in (None, "", [], {}) for key in ("char_range", "bbox", "text_search")) else 0
        score = (100.0 if support_text else 0.0) + 10.0 * locator + 5.0 * overlap + coverage
        scored.append((score, overlap, evidence))

    if not scored:
        return []
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    payloads: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for _score, _overlap, evidence in scored:
        payload = _claim_evidence_payload(
            claim_text=claim_text,
            evidence=evidence,
            citation=citation,
            evidence_index=len(payloads) + 1,
        )
        key = (
            str(payload.get("doc_id") or ""),
            str(payload.get("chunk_id") or ""),
            str(payload.get("text_search") or payload.get("snippet") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        payloads.append(payload)
        if len(payloads) >= 5:
            break
    payloads = _filter_claim_evidence_payloads(payloads)
    return payloads


def _filter_claim_evidence_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exact_payloads = [
        payload
        for payload in payloads
        if payload.get("locator_confidence") == "exact"
        or payload.get("text_search") not in (None, "", [], {})
        or payload.get("bbox") not in (None, "", [], {})
        or payload.get("char_range") not in (None, "", [], {})
    ]
    if not exact_payloads:
        return payloads

    non_rse_exact = [payload for payload in exact_payloads if not _is_rse_parent_payload(payload)]
    if non_rse_exact:
        return _dedupe_claim_evidence_payloads(non_rse_exact)
    return _dedupe_claim_evidence_payloads(exact_payloads)


def _is_rse_parent_payload(payload: dict[str, Any]) -> bool:
    chunk_id = str(payload.get("chunk_id") or "")
    return chunk_id.startswith("rse:")


def _dedupe_claim_evidence_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for payload in payloads:
        key = (
            str(payload.get("doc_id") or ""),
            str(payload.get("chunk_id") or ""),
            str(payload.get("page") or ""),
            _compact_evidence_text(payload.get("text_search") or payload.get("snippet"))[:160],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(payload)
    return deduped


def _best_evidence_for_claim(claim_text: Any, citation: dict[str, Any]) -> dict[str, Any] | None:
    ranked = _ranked_evidence_for_claim(claim_text, citation)
    return ranked[0] if ranked else None


def _apply_evidence_payload_to_claim(claim: dict[str, Any], evidence: dict[str, Any]) -> None:
    for key in (
        "doc_id",
        "chunk_id",
        "page",
        "page_label",
        "pdf_url",
        "page_count",
        "section_title",
        "section_path",
        "snippet",
        "bbox",
        "char_range",
        "text_search",
    ):
        if evidence.get(key) not in (None, "", [], {}):
            claim[key] = evidence.get(key)


def _claim_specific_text_search(claim_text: Any, evidence: dict[str, Any]) -> str | None:
    claim = _claim_text_for_support(claim_text)
    if not claim:
        return None
    compact_claim = _compact_evidence_text(claim)
    evidence_text = _evidence_text(evidence)
    if compact_claim and compact_claim in _compact_evidence_text(evidence_text):
        return claim

    explicit = str(evidence.get("text_search") or "").strip()
    if not explicit:
        return None
    claim_tokens = _claim_support_tokens(claim)
    explicit_tokens = _claim_support_tokens(explicit)
    overlap = len(claim_tokens & explicit_tokens)
    if overlap >= 2 or overlap / max(1, len(claim_tokens)) >= 0.5:
        return explicit
    return None


def _apply_claim_evidence_locator(claim: dict[str, Any], evidence: dict[str, Any], claim_text: Any) -> None:
    for key in ("bbox", "char_range", "text_search"):
        claim.pop(key, None)
    for key in (
        "doc_id",
        "chunk_id",
        "page",
        "page_label",
        "pdf_url",
        "page_start",
        "page_end",
        "section_title",
        "section_path",
        "snippet",
        "bbox",
        "char_range",
    ):
        if evidence.get(key) not in (None, "", [], {}):
            claim[key] = evidence.get(key)
    text_search = _claim_specific_text_search(claim_text, evidence)
    if text_search:
        claim["text_search"] = text_search


def _with_claim_level_citations(
    segments: list[dict[str, Any]],
    citations_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    claim_citations_by_id: dict[str, dict[str, Any]] = {}
    claim_segments: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments, start=1):
        claim_ids: list[str] = []
        for citation_id in segment.get("citation_ids") or []:
            base = citations_by_id.get(str(citation_id))
            if not base:
                continue
            claim = dict(base)
            claim_id = f"{base.get('citation_id')}:claim-{segment_index}"
            claim["citation_id"] = claim_id
            for key in ("bbox", "char_range", "text_search"):
                claim.pop(key, None)
            evidence_items = _ranked_evidence_for_claim(segment.get("text"), claim)
            if evidence_items:
                claim["evidence"] = evidence_items
                _apply_evidence_payload_to_claim(claim, evidence_items[0])
            else:
                text_search = _claim_specific_text_search(segment.get("text"), base)
                if text_search:
                    claim["text_search"] = text_search
                    for key in ("bbox", "char_range"):
                        if base.get(key) not in (None, "", [], {}):
                            claim[key] = base.get(key)
            claim_citations_by_id[claim_id] = claim
            claim_ids.append(claim_id)
        if claim_ids:
            claim_segments.append({"text": segment.get("text"), "citation_ids": claim_ids})
    return claim_segments, claim_citations_by_id


def _source_key(value: Any) -> str:
    return str(value or "").strip()


def _citation_payload(source: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": SOURCE_CITATION_CONTRACT,
        "citation_id": f"citation:{_source_key(source.get('source_id') or source.get('doc_id') or source.get('source_number'))}",
        "source_id": source.get("source_id"),
        "source_number": source.get("source_number"),
        "doc_id": source.get("doc_id"),
        "chunk_id": source.get("chunk_id"),
        "title": source.get("title"),
        "organization": source.get("organization"),
        "snippet": source.get("snippet"),
    }
    for key in (
        "page",
        "page_start",
        "page_end",
        "page_count",
        "page_label",
        "pdf_url",
        "bbox",
        "char_range",
        "text_search",
        "section_title",
        "section_path",
        "supporting_chunk_ids",
        "supporting_pages",
        "supporting_sections",
        "evidence_snippets",
        "policy_only",
        "source_kind",
    ):
        if source.get(key) not in (None, "", [], {}):
            payload[key] = source.get(key)
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _knowledge_answer_payload(answer: Any, sources: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    raw_answer = sanitize_rag_answer_text(answer)
    answer_without_definitions = _FOOTNOTE_DEFINITION_RE.sub("", raw_answer).strip()
    source_by_number = {
        str(source.get("source_number")): source
        for source in sources
        if source.get("source_number") not in (None, "")
    }
    citations_by_id: dict[str, dict[str, Any]] = {}
    segments: list[dict[str, Any]] = []
    cursor = 0

    for match in _FOOTNOTE_MARKER_CLUSTER_RE.finditer(answer_without_definitions):
        end = match.end()
        trailing_punctuation = ""
        while end < len(answer_without_definitions) and answer_without_definitions[end] in ".,;:!?":
            trailing_punctuation += answer_without_definitions[end]
            end += 1
        text = f"{answer_without_definitions[cursor:match.start()]}{trailing_punctuation}"
        refs: list[dict[str, Any]] = []
        for marker in _citation_marker_values(match.group(0)):
            source = source_by_number.get(str(marker).strip())
            if not source:
                continue
            citation = _citation_payload(source)
            citation_id = str(citation.get("citation_id") or "")
            if citation_id:
                citations_by_id[citation_id] = citation
                refs.append({"citation_id": citation_id, "source_id": source.get("source_id"), "source_number": source.get("source_number")})
        clean_text = _strip_footnote_markup(text)
        if clean_text:
            segments.append(
                {
                    "text": clean_text,
                    "citation_ids": [ref["citation_id"] for ref in refs if ref.get("citation_id")],
                }
            )
        elif refs and segments:
            existing = segments[-1].setdefault("citation_ids", [])
            for ref in refs:
                citation_id = ref.get("citation_id")
                if citation_id and citation_id not in existing:
                    existing.append(citation_id)
        cursor = end

    tail = _strip_footnote_markup(answer_without_definitions[cursor:])
    if tail:
        segments.append({"text": tail, "citation_ids": []})

    clean_answer = _strip_footnote_markup(answer_without_definitions)
    if clean_answer and not segments:
        segments.append({"text": clean_answer, "citation_ids": []})

    if sources and segments:
        if is_insufficient_context_answer(clean_answer):
            citations_by_id = {}
            segments = [{"text": clean_answer, "citation_ids": []}]
        else:
            cited_segments = [segment for segment in segments if segment.get("citation_ids")]
            if cited_segments:
                cited_segments = _expand_procedure_knowledge_segments(cited_segments)
                if _segments_are_procedure_steps(cited_segments):
                    claim_segments, claim_citations_by_id = _with_claim_level_citations(cited_segments, citations_by_id)
                    if claim_segments:
                        segments = claim_segments
                        citations_by_id = claim_citations_by_id
                        clean_answer = "\n".join(str(segment.get("text") or "").strip() for segment in segments).strip()
                    else:
                        segments = cited_segments
                        clean_answer = "\n".join(str(segment.get("text") or "").strip() for segment in segments).strip()
                else:
                    merged_segments = _merge_adjacent_knowledge_segments(cited_segments)
                    claim_segments, claim_citations_by_id = _with_claim_level_citations(merged_segments, citations_by_id)
                    if claim_segments:
                        segments = claim_segments
                        citations_by_id = claim_citations_by_id
                    else:
                        segments = merged_segments
                    clean_answer = "\n\n".join(str(segment.get("text") or "").strip() for segment in segments).strip()
            else:
                clean_answer = insufficient_context_answer(has_sources=True)
                citations_by_id = {}
                segments = [{"text": clean_answer, "citation_ids": []}]

    return clean_answer, segments, list(citations_by_id.values())


def _knowledge_answer_text_for_sources(answer: Any, sources: list[dict[str, Any]]) -> str:
    clean_answer, _segments, _citations = _knowledge_answer_payload(answer, sources)
    return clean_answer


def _action(action_id: str) -> dict[str, str]:
    return {"id": action_id, "label": _ACTION_LABELS.get(action_id, action_id.replace("_", " ").title())}


def _actions(action_ids: tuple[str, ...]) -> list[dict[str, str]]:
    return [_action(action_id) for action_id in action_ids]


def _redact_sensitive_text(value: Any) -> str:
    text = _trimmed(value)
    if not text:
        return ""
    text = _STACK_TRACE_RE.sub("[stack_trace_redacted]", text)
    text = _SENSITIVE_VALUE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    return text[:240]


def _error_code(value: Any, *, fallback: str = "unknown_error") -> str:
    text = _redact_sensitive_text(value).lower()
    if not text:
        return fallback
    if "[stack_trace_redacted]" in text:
        return "stack_trace_redacted"
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return (text or fallback)[:80]


def _sanitize_diagnostic_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if key and _SENSITIVE_KEY_RE.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_diagnostic_value(item_value, key=str(item_key), depth=depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_diagnostic_value(item, depth=depth + 1) for item in value[:25]]
    if isinstance(value, str):
        if key in {"session_error", "last_error", "error", "exception", "message", "detail"}:
            return _error_code(value)
        return _redact_sensitive_text(value)
    return value


def _row_ids_by_status(rows: list[dict[str, Any]], status: str) -> list[str]:
    out: list[str] = []
    for row in rows:
        if _normalize_row_status(row.get("status"), default="unknown") != status:
            continue
        out.append(_row_identifier(row) or f"row-{len(out) + 1}")
    return out


def _approval_is_stale(approval: ApprovalResponse | None) -> bool:
    if approval is None:
        return False
    text = f"{approval.rejection_reason or ''} {approval.status or ''}".lower()
    return "stale" in text or "superseded" in text or "changed state" in text


def _latest_closed_approval(approvals: list[ApprovalResponse]) -> ApprovalResponse | None:
    closed = [
        approval
        for approval in approvals
        if str(approval.status or "").upper() in {"REJECTED", "EXPIRED"} or _approval_is_expired(approval)
    ]
    if not closed:
        return None
    return max(closed, key=lambda row: row.decided_at or row.created_at)


def _failure_probe_text(
    *,
    presentation: PresentationResponse,
    steps: list[PlanStepResponse],
    approvals: list[ApprovalResponse],
) -> str:
    diagnostics = presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {}
    parts: list[str] = [
        str(diagnostics.get("reason") or ""),
        str(diagnostics.get("session_error") or ""),
        str(presentation.summary or ""),
    ]
    for step in steps:
        parts.extend([str(step.last_error or ""), json.dumps(step.result, default=str) if step.result else ""])
    for approval in approvals:
        parts.append(str(approval.rejection_reason or ""))
    return " ".join(parts).lower()


def _failure_reason(
    *,
    presentation: PresentationResponse,
    steps: list[PlanStepResponse],
    approvals: list[ApprovalResponse],
    mutation_groups: list[MutationGroup],
) -> str | None:
    if presentation.kind not in {"diagnostic", "cancelled", "rejected", "expired", "partial_failure"}:
        return None

    diagnostics = presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {}
    legacy_reason = _trimmed(diagnostics.get("reason"))
    if mutation_groups and all(_is_no_op_group(group) for group in mutation_groups) and legacy_reason in {
        "empty_final_response",
        "no_results",
    }:
        return None
    latest_closed_approval = _latest_closed_approval(approvals)
    text = _failure_probe_text(presentation=presentation, steps=steps, approvals=approvals)

    if legacy_reason in {"planner_no_action", "unable_to_start_request", "orphan_turn_state"}:
        return legacy_reason
    if "planner_no_action" in text:
        return "planner_no_action"
    if "unable_to_start_request" in text:
        return "unable_to_start_request"
    if "orphan_turn_state" in text:
        return "orphan_turn_state"
    if presentation.kind == "cancelled" or legacy_reason == "cancelled_by_user":
        return "cancelled_by_user"
    if presentation.kind == "rejected" or legacy_reason == "approval_rejected":
        return "approval_rejected"
    if presentation.kind == "expired" or legacy_reason == "approval_expired":
        return "approval_stale" if _approval_is_stale(latest_closed_approval) else "approval_expired"
    if presentation.kind == "partial_failure" or legacy_reason == "partial_failure":
        return "partial_commit_failure"
    if legacy_reason == "empty_final_response":
        return "no_results"
    if any(group.status == "partial_failure" for group in mutation_groups):
        return "partial_commit_failure"
    if "decision_guard_constraint_repair_limit" in text or "constraint_violation_loop" in text:
        return "planner_validation_loop"
    if "decision guard" in text and ("repair loop" in text or "validation loop" in text or "recursion" in text):
        return "planner_validation_loop"
    if "response_document" in text and ("invalid" in text or "contract" in text):
        return "response_document_invalid"
    if "snapshot" in text and ("invalid" in text or "contract" in text):
        return "snapshot_contract_invalid"
    if "sse" in text or "server-sent" in text or "event stream" in text:
        if "disconnect" in text or "interrupted" in text or "closed" in text:
            return "sse_stream_interrupted"
    if _AUTH_DENIED_RE.search(text):
        return "auth_denied"
    if "malformed" in text or ("invalid" in text and "payload" in text) or "invalid response" in text:
        return "malformed_response_payload"
    if "schema" in text or "validation" in text:
        return "tool_schema_error"
    if "timeout" in text or "timed out" in text:
        if any(step.last_error and ("timeout" in step.last_error.lower() or "timed out" in step.last_error.lower()) for step in steps):
            return "tool_timeout"
        if "llm" in text or "model" in text or "answer" in text or "rag" in text:
            return "llm_timeout"
        return "planner_timeout"
    if "network" in text or "connection reset" in text or "connection refused" in text or "disconnect" in text:
        return "network_disconnect"
    if _HTTP_STATUS_RE.search(text) or "http_500" in text or "http 500" in text or "status 500" in text:
        return "tool_http_error"
    if legacy_reason in {"session_failed", "session_blocked"}:
        return "unknown_failure"
    return None


def _failure_rows(
    *,
    mutation_groups: list[MutationGroup],
    presentation: PresentationResponse,
) -> list[dict[str, Any]]:
    rows = [row for group in mutation_groups for row in group.rows]
    if rows:
        return rows
    return [dict(row) for row in presentation.rows]


def _failure_technical_details(
    *,
    reason: str,
    presentation: PresentationResponse,
    steps: list[PlanStepResponse],
) -> dict[str, Any]:
    diagnostics = presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {}
    terminal_event_id = diagnostics.get("terminal_event_id")
    terminal_event_type = diagnostics.get("terminal_event_type")
    step_errors = []
    for step in steps:
        if str(step.status or "").upper() not in {"FAILED", "AMBIGUOUS"} and not step.last_error:
            continue
        step_errors.append(
            {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "status": step.status,
                "error_code": _error_code(step.last_error or (step.result or {}).get("error")),
            }
        )
    session_error = diagnostics.get("session_error")
    return {
        "error_code": reason,
        "legacy_reason": _trimmed(diagnostics.get("reason")) or None,
        "session_status": diagnostics.get("session_status"),
        "original_session_status": diagnostics.get("original_session_status"),
        "session_error_code": _error_code(session_error) if session_error else None,
        "terminal_event_id": terminal_event_id,
        "terminal_event_type": terminal_event_type,
        "step_errors": step_errors,
        "sanitized": True,
    }


def _failure_impact(
    *,
    reason: str,
    template: FailureTemplate,
    state: str,
    approvals: list[ApprovalResponse],
    latest_pending: ApprovalResponse | None,
    mutation_groups: list[MutationGroup],
    steps: list[PlanStepResponse],
    presentation: PresentationResponse,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    rows = _failure_rows(mutation_groups=mutation_groups, presentation=presentation)
    succeeded_rows = _row_ids_by_status(rows, "succeeded")
    failed_rows = _row_ids_by_status(rows, "failed")
    pending_rows = _row_ids_by_status(rows, "pending")
    completed_steps: list[str] = []
    for group in mutation_groups:
        if not _row_ids_by_status(group.rows, "succeeded"):
            continue
        completed_steps.append(group.approval_id or (group.step_ids[0] if group.step_ids else group.key))
    failed_step_ids = [step.step_id for step in steps if str(step.status or "").upper() in {"FAILED", "AMBIGUOUS"}]
    incomplete_steps: list[str] = list(failed_step_ids)
    if latest_pending is not None:
        incomplete_steps.append(f"approval:{latest_pending.approval_id}")
    for approval in approvals:
        status = str(approval.status or "").upper()
        if status in {"REJECTED", "EXPIRED"} or _approval_is_expired(approval):
            incomplete_steps.append(f"approval:{approval.approval_id}")
    if reason in {"planner_timeout", "planner_validation_loop", "llm_timeout"} and not incomplete_steps:
        incomplete_steps.append(f"diagnostic:{reason}")

    if succeeded_rows and failed_rows:
        changes_applied: bool | str = "partial"
    elif succeeded_rows:
        changes_applied = True
    elif reason in {"tool_http_error", "tool_timeout", "network_disconnect"} and any(
        str(step.tool_name or "").lower().startswith(("post__", "put__", "patch__", "delete__")) for step in steps
    ):
        changes_applied = "unknown"
    else:
        changes_applied = False

    duplicate_mutation_risk = bool(succeeded_rows and reason != "partial_commit_failure")
    safe_to_retry = template.safe_to_retry and not duplicate_mutation_risk
    retry_policy = template.retry_policy
    action_ids = template.action_ids
    if duplicate_mutation_risk or changes_applied == "unknown":
        safe_to_retry = False
        retry_policy = "check_status_first"
        action_ids = ("check_status", "start_new_request", "view_diagnostics")
    elif reason == "partial_commit_failure":
        safe_to_retry = True
        retry_policy = "retry_failed_rows_only"
        action_ids = ("view_affected_records", "retry_failed_rows_only", "export_audit_details", "view_diagnostics")

    safe_resume_step = completed_steps[-1] if completed_steps and safe_to_retry else None
    impact = {
        "changes_applied": changes_applied,
        "completed_steps": completed_steps,
        "incomplete_steps": list(dict.fromkeys(incomplete_steps)),
        "changed_count": len(succeeded_rows),
        "unchanged_count": len(failed_rows) + len(pending_rows),
        "succeeded_rows": succeeded_rows,
        "failed_rows": failed_rows,
        "pending_rows": pending_rows,
        "safe_to_retry": safe_to_retry,
        "safe_resume_step": safe_resume_step,
        "state": state,
    }
    retry_safety = {
        "safe_to_retry": safe_to_retry,
        "policy": retry_policy,
        "duplicate_mutation_risk": duplicate_mutation_risk,
        "safe_resume_step": safe_resume_step,
    }
    return impact, retry_safety, _actions(action_ids)


def _failure_profile(
    *,
    state: str,
    presentation: PresentationResponse,
    steps: list[PlanStepResponse],
    approvals: list[ApprovalResponse],
    latest_pending: ApprovalResponse | None,
    mutation_groups: list[MutationGroup],
) -> FailureProfile | None:
    reason = _failure_reason(
        presentation=presentation,
        steps=steps,
        approvals=approvals,
        mutation_groups=mutation_groups,
    )
    if reason is None:
        return None
    template = _FAILURE_TEMPLATES.get(reason, _FAILURE_TEMPLATES["unknown_failure"])
    impact, retry_safety, next_actions = _failure_impact(
        reason=template.reason,
        template=template,
        state=state,
        approvals=approvals,
        latest_pending=latest_pending,
        mutation_groups=mutation_groups,
        steps=steps,
        presentation=presentation,
    )
    user_message = _user_facing_failure_summary(presentation.summary) or template.user_message
    return FailureProfile(
        reason=template.reason,
        severity=template.severity,
        title=template.title,
        user_message=user_message,
        cause=template.cause,
        impact=impact,
        current_state=template.current_state,
        next_action=template.next_action,
        next_actions=next_actions,
        retry_safety=retry_safety,
        technical_details=_failure_technical_details(
            reason=template.reason,
            presentation=presentation,
            steps=steps,
        ),
    )


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _is_write_tool_name(tool_name: str | None) -> bool:
    return bool(_WRITE_TOOL_RE.search(_trimmed(tool_name)))


def _is_read_tool_name(tool_name: str | None) -> bool:
    return bool(_READ_TOOL_RE.search(_trimmed(tool_name)))


def _row_identifier(row: dict[str, Any]) -> str | None:
    for key in (
        "row_id",
        "job_id",
        "id",
        "machine_id",
        "product_id",
        "material_id",
        "record_id",
        "approval_id",
    ):
        value = _trimmed(row.get(key))
        if value:
            return value
    return None


def _business_record_identifier(row: dict[str, Any]) -> str | None:
    for key in (
        "job_id",
        "machine_id",
        "product_id",
        "material_id",
        "record_id",
        "id",
        "row_id",
    ):
        value = _trimmed(row.get(key))
        if value:
            return value
    return None


def _is_no_op_group(group: MutationGroup) -> bool:
    return group.status == NO_OP_MUTATION_STATUS or group.reason == NO_OP_MUTATION_REASON


def _noop_group_count(group: MutationGroup) -> int:
    return max(0, int(group.changed_count or 0))


def _mutation_group_record_count(group: MutationGroup) -> int:
    if _is_no_op_group(group):
        return _noop_group_count(group)
    return len(group.rows)


def _entity_noun(entity_type: str | None, count: int) -> str:
    base = _trimmed(entity_type).lower() or "record"
    if base.endswith("s"):
        singular = base[:-1] or base
    else:
        singular = base
    return singular if count == 1 else f"{singular}s"


def _noop_change_summary(group: MutationGroup) -> str:
    entity = _entity_noun(group.entity_type, int(group.matched_count or 0))
    selector = _trimmed(group.selector_summary) or "requested selector"
    change = _trimmed(group.change_summary) or "requested change"
    return f"Not changed: no matching {entity} for {selector}; {change}."


def _normalize_row_status(status: Any, *, default: str) -> str:
    normalized = _trimmed(status).lower()
    if normalized in {NO_OP_MUTATION_STATUS, "unchanged", "no_op", "noop", "skipped_no_match"}:
        return NO_OP_MUTATION_STATUS
    if normalized in _SUCCESS_ROW_STATES:
        return "succeeded"
    if normalized in _FAILED_ROW_STATES:
        return "failed"
    if normalized in {"pending", "staged", "dry_run"}:
        return "pending"
    if normalized in {"expired", "superseded", "stale"}:
        return "expired"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    return normalized or default


def _presentation_row(
    payload: dict[str, Any],
    *,
    default_status: str,
    operation_id: str | None,
    approval_id: str | None,
    step_id: str | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    row = dict(payload)
    row["status"] = _normalize_row_status(
        row.get("status") or row.get("result") or row.get("outcome"),
        default=default_status,
    )
    row_id = _row_identifier(row)
    if row_id:
        row["row_id"] = row_id
    if operation_id:
        row.setdefault("operation_id", operation_id)
    if approval_id:
        row.setdefault("approval_id", approval_id)
    if step_id:
        row.setdefault("step_id", step_id)
    if tool_name:
        row.setdefault("tool_name", tool_name)
    return row


def _operation_rows_from_result(
    result: dict[str, Any] | None,
    *,
    default_status: str,
    operation_id: str | None,
    approval_id: str | None,
    step_id: str | None = None,
    tool_name: str | None = None,
    fallback_args: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        result = {}

    rows: list[dict[str, Any]] = []
    raw_outcomes = result.get("outcomes")
    if isinstance(raw_outcomes, list):
        for outcome in raw_outcomes:
            if isinstance(outcome, dict):
                rows.append(
                    _presentation_row(
                        outcome,
                        default_status=default_status,
                        operation_id=operation_id,
                        approval_id=approval_id or _trimmed(result.get("approval_id")) or None,
                        step_id=step_id,
                        tool_name=tool_name,
                    )
                )
        if rows:
            return rows

    data = result.get("data")
    raw_operations = result.get("operations")
    if isinstance(data, dict) and isinstance(data.get("operations"), list):
        raw_operations = data.get("operations")
    if isinstance(raw_operations, list):
        for operation in raw_operations:
            if not isinstance(operation, dict):
                continue
            payload = operation.get("data") if isinstance(operation.get("data"), dict) else {}
            row_payload = {**payload, **{k: v for k, v in operation.items() if k != "data"}}
            rows.append(
                _presentation_row(
                    row_payload,
                    default_status=default_status,
                    operation_id=operation_id,
                    approval_id=approval_id or _trimmed(result.get("approval_id")) or None,
                    step_id=step_id,
                    tool_name=tool_name,
                )
            )
        if rows:
            return rows

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                rows.append(
                    _presentation_row(
                        item,
                        default_status=default_status,
                        operation_id=operation_id,
                        approval_id=approval_id or _trimmed(result.get("approval_id")) or None,
                        step_id=step_id,
                        tool_name=tool_name,
                    )
                )
        return rows

    if isinstance(data, dict):
        return [
            _presentation_row(
                data,
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id or _trimmed(result.get("approval_id")) or None,
                step_id=step_id,
                tool_name=tool_name,
            )
        ]

    if fallback_args:
        return [
            _presentation_row(
                dict(fallback_args),
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id or _trimmed(result.get("approval_id")) or None,
                step_id=step_id,
                tool_name=tool_name,
            )
        ]

    if result:
        return [
            _presentation_row(
                result,
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id or _trimmed(result.get("approval_id")) or None,
                step_id=step_id,
                tool_name=tool_name,
            )
        ]
    return []


def _approval_rows_from_args(
    args: dict[str, Any] | None,
    *,
    default_status: str,
    operation_id: str | None,
    approval_id: str | None,
    tool_name: str | None,
) -> list[dict[str, Any]]:
    payload = args if isinstance(args, dict) else {}
    bundle_ui = payload.get("bundle_ui") if isinstance(payload.get("bundle_ui"), dict) else {}
    candidate_lists = [
        (bundle_ui.get("rows"), {}),
        (payload.get("preview"), {}),
        (payload.get("staged_writes"), {}),
        (bundle_ui.get("excluded_rows"), {"approval_effect": "excluded"}),
    ]
    rows: list[dict[str, Any]] = []
    for candidate, defaults in candidate_lists:
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            if not isinstance(item, dict):
                continue
            row_payload = item.get("args") if isinstance(item.get("args"), dict) else item
            row_payload = {**dict(row_payload), **defaults}
            row = _presentation_row(
                row_payload,
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id,
                tool_name=_trimmed(item.get("tool_name")) or tool_name,
            )
            if bundle_ui.get("write_set"):
                row.setdefault("write_set", bundle_ui.get("write_set"))
            if bundle_ui.get("kind"):
                row.setdefault("bundle_kind", bundle_ui.get("kind"))
            if bundle_ui.get("previous_approval_id"):
                row.setdefault("previous_approval_id", bundle_ui.get("previous_approval_id"))
            if bundle_ui.get("original_state_semantics"):
                row.setdefault("original_state_semantics", bundle_ui.get("original_state_semantics"))
            rows.append(row)
        if rows:
            return rows

    if payload and not {"bundle_ui", "preview", "staged_writes"} & set(payload):
        return [
            _presentation_row(
                payload,
                default_status=default_status,
                operation_id=operation_id,
                approval_id=approval_id,
                tool_name=tool_name,
            )
        ]
    return []


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = _business_row_dedupe_key(row) or json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _row_status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = _normalize_row_status(row.get("status"), default="unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _approval_is_expired(approval: ApprovalResponse, *, now: datetime | None = None) -> bool:
    if str(approval.status or "").upper() == "EXPIRED":
        return True
    expires_at = approval.expires_at
    if expires_at is None or str(approval.status or "").upper() != "PENDING":
        return False
    current = now or datetime.utcnow()
    try:
        if expires_at.tzinfo is not None and current.tzinfo is None:
            current = current.replace(tzinfo=expires_at.tzinfo)
        if expires_at.tzinfo is None and current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        return expires_at <= current
    except TypeError:
        return False


def _latest_approval(approvals: list[ApprovalResponse]) -> ApprovalResponse | None:
    if not approvals:
        return None
    return max(approvals, key=lambda row: row.decided_at or row.created_at)


def _latest_pending_approval(
    pending_approval: ApprovalResponse | None,
    approvals: list[ApprovalResponse],
) -> ApprovalResponse | None:
    if pending_approval is not None and str(pending_approval.status or "").upper() == "PENDING":
        return pending_approval
    pending = [row for row in approvals if str(row.status or "").upper() == "PENDING" and not _approval_is_expired(row)]
    if not pending:
        return None
    return max(pending, key=lambda row: row.created_at)


def _response_document_turn_id(timeline: list[TimelineEventResponse], *, session_id: str) -> str:
    for event in reversed(timeline):
        if event.turn_id:
            return event.turn_id
    return f"session:{session_id}"


def _response_document_revision(
    *,
    cursor: int,
    session: Any,
    timeline: list[TimelineEventResponse],
) -> tuple[int, str]:
    event_seq = getattr(session, "event_seq", None)
    if event_seq is not None:
        try:
            return max(0, int(event_seq or 0)), "event_seq"
        except (TypeError, ValueError):
            pass
    try:
        return max(0, int(cursor or 0)), "event_seq"
    except (TypeError, ValueError):
        pass
    updated_at = getattr(session, "updated_at", None)
    if isinstance(updated_at, datetime):
        return max(0, int(updated_at.timestamp() * 1000)), "session_updated_at"
    if timeline:
        latest = max(event.created_at for event in timeline)
        return max(0, int(latest.timestamp() * 1000)), "timeline_timestamp"
    return 0, "empty_snapshot"


def _response_document_state(
    *,
    session: Any,
    latest_pending: ApprovalResponse | None,
    presentation: PresentationResponse,
) -> str:
    session_status = str(getattr(session, "status", "") or "").upper()
    if latest_pending is not None:
        return "waiting_approval"
    if session_status == "WAITING_CONFIRMATION":
        return "waiting_confirmation"
    if presentation.state == "completed":
        return "completed"
    if presentation.state == "failed":
        return "failed"
    if presentation.state == "blocked":
        return "blocked"
    if presentation.state == "rejected":
        return "rejected"
    if presentation.state == "expired":
        return "expired"
    if presentation.state == "cancelled":
        return "cancelled"
    return "running"


def _approval_operation_id(approval: ApprovalResponse, fallback: str | None) -> str | None:
    return approval.plan_id or fallback


def _approval_rows(approval: ApprovalResponse, *, operation_id: str | None, default_status: str) -> list[dict[str, Any]]:
    return _approval_rows_from_args(
        approval.args,
        default_status=default_status,
        operation_id=_approval_operation_id(approval, operation_id),
        approval_id=approval.approval_id,
        tool_name=approval.tool_name,
    )


def _approval_summary(approval: ApprovalResponse, *, fallback: str = "Approval is required before the operation can continue.") -> str:
    args = approval.args if isinstance(approval.args, dict) else {}
    bundle_ui = args.get("bundle_ui") if isinstance(args.get("bundle_ui"), dict) else {}
    for candidate in (bundle_ui.get("headline"), args.get("summary"), approval.risk_summary):
        text = _trimmed(candidate)
        if text:
            return text
    return fallback


def _pending_priority_change_summary(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    sources = {_source_priority(row) for row in rows if _source_priority(row)}
    targets = {_target_priority(row) for row in rows if _target_priority(row)}
    if len(sources) != 1 or len(targets) != 1:
        return None
    source = next(iter(sources))
    target = next(iter(targets))
    count = len(rows)
    entity_types = {_row_entity_type(row) for row in rows}
    entity_types.discard("record")
    noun = _entity_noun(next(iter(entity_types)), count) if len(entity_types) == 1 else _plural(count, "record")
    return f"{count} {noun} will be updated from {source} to {target} priority."


def _pending_approval_summary(approval: ApprovalResponse, rows: list[dict[str, Any]]) -> str:
    priority_summary = _pending_priority_change_summary(rows)
    approval_summary = _approval_summary(approval)
    if priority_summary and approval_summary:
        approval_lower = approval_summary.lower()
        priority_lower = priority_summary.rstrip(".").lower()
        if ("approval" in approval_lower or "original" in approval_lower) and priority_lower not in approval_lower:
            return f"{approval_summary.rstrip('.')} {priority_summary}"
    return priority_summary or approval_summary


def _approval_contract(approval: ApprovalResponse, rows: list[dict[str, Any]]) -> str | None:
    args = approval.args if isinstance(approval.args, dict) else {}
    bundle_ui = args.get("bundle_ui") if isinstance(args.get("bundle_ui"), dict) else {}
    if rows or any(key in args for key in ("preview", "staged_writes")):
        return BUSINESS_CHANGE_CONTRACT
    if any(key in bundle_ui for key in ("rows", "excluded_rows", "write_set", "kind", "write_tool_name")):
        return BUSINESS_CHANGE_CONTRACT
    return None


def _approval_action_args(args: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(args, dict):
        return None
    allowed = {
        "summary",
        "count",
        "preview",
        "staged_writes",
        "requirement_ledger_revision",
        "current_requirement_id",
        "mutation_requirements",
        "locked_constraints",
        "commit_state",
        "session_id",
    }
    out = {key: args[key] for key in allowed if key in args}
    bundle_ui = args.get("bundle_ui") if isinstance(args.get("bundle_ui"), dict) else {}
    if bundle_ui:
        bundle_allowed = {
            "kind",
            "write_set",
            "headline",
            "rows",
            "previous_priority",
            "new_priority",
            "locked_constraints",
            "requirement_ledger_revision",
            "source_intent",
            "write_tool_name",
            "previous_approval_id",
            "original_state_semantics",
        }
        out["bundle_ui"] = {key: bundle_ui[key] for key in bundle_allowed if key in bundle_ui}
    return out or None


def _no_op_payloads_from_args(args: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = args if isinstance(args, dict) else {}
    candidates: list[Any] = []
    for key in ("no_op_mutations", "noop_mutations", "not_changed"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.append(value)
    bundle_ui = payload.get("bundle_ui") if isinstance(payload.get("bundle_ui"), dict) else {}
    for key in ("no_op_mutations", "noop_mutations", "not_changed"):
        value = bundle_ui.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.append(value)
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        normalized = normalize_no_op_mutation(candidate)
        if normalized is not None:
            out.append(normalized)
    return out


def _no_op_payloads_from_session(session: Any) -> list[dict[str, Any]]:
    context = getattr(session, "replan_context", None)
    if not isinstance(context, dict):
        return []
    candidates: list[Any] = []
    contract = context.get("intent_contract")
    if isinstance(contract, dict):
        value = contract.get("no_op_mutations")
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.append(value)
    value = context.get("no_op_mutations")
    if isinstance(value, list):
        candidates.extend(value)
    elif isinstance(value, dict):
        candidates.append(value)
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        normalized = normalize_no_op_mutation(candidate)
        if normalized is not None:
            out.append(normalized)
    return out


def _no_op_mutation_groups(
    *,
    session: Any,
    approvals: list[ApprovalResponse],
    operation_id: str | None,
) -> list[MutationGroup]:
    raw: list[tuple[dict[str, Any], str | None, datetime | None]] = []
    for payload in _no_op_payloads_from_session(session):
        raw.append((payload, None, None))
    for approval in approvals:
        for payload in _no_op_payloads_from_args(approval.args if isinstance(approval.args, dict) else None):
            raw.append((payload, _approval_operation_id(approval, operation_id), approval.created_at))

    groups: list[MutationGroup] = []
    seen: set[str] = set()
    for index, (payload, payload_operation_id, completed_at) in enumerate(raw):
        key_payload = {
            "entity_type": payload["entity_type"],
            "selector_summary": payload["selector_summary"],
            "change_summary": payload["change_summary"],
            "status": payload["status"],
            "reason": payload["reason"],
        }
        key = f"noop:{json.dumps(key_payload, sort_keys=True)}"
        if key in seen:
            continue
        seen.add(key)
        groups.append(
            MutationGroup(
                key=key,
                operation_id=payload_operation_id or operation_id,
                approval_id=None,
                rows=[],
                step_ids=[],
                completed_at=completed_at,
                status=NO_OP_MUTATION_STATUS,
                first_seen=-1000 + index,
                entity_type=payload["entity_type"],
                selector_summary=payload["selector_summary"],
                change_summary=payload["change_summary"],
                matched_count=int(payload["matched_count"]),
                changed_count=int(payload["changed_count"]),
                reason=payload["reason"],
            )
        )
    return groups


def _approval_position_by_id(approvals: list[ApprovalResponse]) -> dict[str, int]:
    ordered = sorted(approvals, key=lambda row: (row.created_at, row.approval_id))
    return {row.approval_id: index for index, row in enumerate(ordered, start=1)}


def _group_sort_key(group: MutationGroup, approval_positions: dict[str, int]) -> tuple[int, datetime, int, str]:
    if _is_no_op_group(group):
        return -1, group.completed_at or datetime.min, group.first_seen, group.key
    approval_rank = approval_positions.get(group.approval_id or "", 10_000)
    completed_at = group.completed_at or datetime.min
    return approval_rank, completed_at, group.first_seen, group.key


def _add_group_rows(
    groups: dict[str, MutationGroup],
    *,
    rows: list[dict[str, Any]],
    operation_id: str | None,
    approval_id: str | None,
    step_id: str | None,
    completed_at: datetime | None,
) -> None:
    if not rows:
        return
    key = approval_id or step_id or operation_id or "ungated"
    group = groups.get(key)
    if group is None:
        group = MutationGroup(key=key, operation_id=operation_id, approval_id=approval_id, first_seen=len(groups))
        groups[key] = group
    group.rows.extend(rows)
    if step_id and step_id not in group.step_ids:
        group.step_ids.append(step_id)
    if completed_at and (group.completed_at is None or completed_at > group.completed_at):
        group.completed_at = completed_at
    counts = _row_status_counts(group.rows)
    if counts.get("succeeded", 0) and counts.get("failed", 0):
        group.status = "partial_failure"
    elif counts.get("failed", 0) and not counts.get("succeeded", 0):
        group.status = "failed"
    elif counts.get(NO_OP_MUTATION_STATUS, 0) and not counts.get("succeeded", 0):
        group.status = NO_OP_MUTATION_STATUS
    else:
        group.status = "completed"


def _priority_business_key(source: str, target: str) -> str:
    return json.dumps(["priority", source, target], sort_keys=True)


def _business_group_key(row: dict[str, Any], *, fallback: str) -> str:
    if _row_has_business_change_contract(row):
        business_change_id = _row_business_change_id(row)
        if business_change_id:
            return json.dumps([BUSINESS_CHANGE_CONTRACT, business_change_id], sort_keys=True)
        changes = _row_field_changes(row)
        if changes:
            return json.dumps(
                [
                    BUSINESS_CHANGE_CONTRACT,
                    _row_entity_type(row),
                    _row_selector_summary(row),
                    changes,
                ],
                sort_keys=True,
                default=str,
            )
    source = _source_priority(row)
    target = _target_priority(row)
    if source or target:
        return _priority_business_key(source, target)
    write_set = _trimmed(row.get("write_set")).lower()
    if write_set:
        return json.dumps(["write_set", write_set], sort_keys=True)
    return json.dumps(["group", fallback], sort_keys=True)


def _business_change_order_from_text(text: str) -> dict[str, int]:
    order: dict[str, int] = {}
    patterns = [
        r"\b(?:original\s+)?(?P<source>low|medium|high)\s+priority\s+jobs?\s+changed\s+to\s+(?P<target>low|medium|high)\b",
        r"\b(?P<source>low|medium|high)\s*->\s*(?P<target>low|medium|high)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            source = match.group("source").lower()
            target = match.group("target").lower()
            key = _priority_business_key(source, target)
            if key not in order:
                order[key] = len(order)
    return order


def _business_group_sort_key(
    group: MutationGroup,
    approval_positions: dict[str, int],
    business_order: dict[str, int],
) -> tuple[int, int, int, datetime, str]:
    if _is_no_op_group(group):
        return -1, group.first_seen, group.first_seen, group.completed_at or datetime.min, group.key
    approval_rank = approval_positions.get(group.approval_id or "", 10_000)
    business_key = _typed_business_group_key(group) or group.key
    business_rank = business_order.get(business_key, 10_000 + group.first_seen)
    return approval_rank, business_rank, group.first_seen, group.completed_at or datetime.min, group.key


def _merge_mutation_groups_by_business_change(groups: list[MutationGroup]) -> list[MutationGroup]:
    merged: dict[str, MutationGroup] = {}
    seen_rows: dict[str, set[str]] = {}
    hints_by_approval_record: dict[tuple[str, str], dict[str, Any]] = {}
    hints_by_record: dict[str, dict[str, Any]] = {}

    for group in groups:
        for row in group.rows:
            record_id = _business_record_identifier(row)
            source = _source_priority(row)
            target = _target_priority(row)
            if not record_id or not (source and target):
                continue
            hint = {
                "previous_priority": source,
                "new_priority": target,
                "write_set": _trimmed(row.get("write_set")),
                "bundle_kind": _trimmed(row.get("bundle_kind")),
                "source_state_basis": _trimmed(row.get("source_state_basis")),
            }
            hints_by_record.setdefault(record_id, hint)
            if group.approval_id:
                hints_by_approval_record.setdefault((group.approval_id, record_id), hint)

    for group in groups:
        if _is_no_op_group(group):
            target = merged.get(group.key)
            if target is None:
                target = MutationGroup(
                    key=group.key,
                    operation_id=group.operation_id,
                    approval_id=None,
                    completed_at=group.completed_at,
                    status=NO_OP_MUTATION_STATUS,
                    first_seen=group.first_seen,
                    entity_type=group.entity_type,
                    selector_summary=group.selector_summary,
                    change_summary=group.change_summary,
                    matched_count=group.matched_count,
                    changed_count=group.changed_count,
                    reason=group.reason or NO_OP_MUTATION_REASON,
                )
                merged[group.key] = target
                seen_rows[group.key] = set()
            if group.first_seen < target.first_seen:
                target.first_seen = group.first_seen
            if target.operation_id is None and group.operation_id:
                target.operation_id = group.operation_id
            if group.completed_at and (target.completed_at is None or group.completed_at > target.completed_at):
                target.completed_at = group.completed_at
            continue
        for index, row in enumerate(group.rows):
            record_id = _business_record_identifier(row)
            hint = None
            if record_id and group.approval_id:
                hint = hints_by_approval_record.get((group.approval_id, record_id))
            if hint is None and record_id:
                hint = hints_by_record.get(record_id)
            if hint and not (_source_priority(row) and _target_priority(row)):
                row = {
                    **row,
                    **{key: value for key, value in hint.items() if value},
                }
            key = _business_group_key(row, fallback=group.key)
            target = merged.get(key)
            if target is None:
                target = MutationGroup(
                    key=key,
                    operation_id=group.operation_id,
                    approval_id=group.approval_id,
                    completed_at=group.completed_at,
                    status=group.status,
                    first_seen=group.first_seen,
                )
                merged[key] = target
                seen_rows[key] = set()
            elif target.approval_id is None and group.approval_id:
                target.approval_id = group.approval_id
            if group.first_seen < target.first_seen:
                target.first_seen = group.first_seen
            if target.operation_id is None and group.operation_id:
                target.operation_id = group.operation_id
            if group.completed_at and (target.completed_at is None or group.completed_at > target.completed_at):
                target.completed_at = group.completed_at
            for step_id in group.step_ids:
                if step_id not in target.step_ids:
                    target.step_ids.append(step_id)

            row_key = _business_row_dedupe_key(row) or json.dumps(
                ["row", group.key, _row_identifier(row), index],
                sort_keys=True,
            )
            if row_key in seen_rows[key]:
                continue
            seen_rows[key].add(row_key)
            target.rows.append(row)

    for group in merged.values():
        if _is_no_op_group(group):
            group.status = NO_OP_MUTATION_STATUS
            continue
        counts = _row_status_counts(group.rows)
        if counts.get("succeeded", 0) and counts.get("failed", 0):
            group.status = "partial_failure"
        elif counts.get("failed", 0) and not counts.get("succeeded", 0):
            group.status = "failed"
        elif counts.get(NO_OP_MUTATION_STATUS, 0) and not counts.get("succeeded", 0):
            group.status = NO_OP_MUTATION_STATUS
        else:
            group.status = "completed"

    return list(merged.values())


def _mutation_groups(
    *,
    steps: list[PlanStepResponse],
    timeline: list[TimelineEventResponse],
    presentation: PresentationResponse,
    operation_id: str | None,
    approvals: list[ApprovalResponse],
) -> list[MutationGroup]:
    groups: dict[str, MutationGroup] = {}
    approval_ids = {approval.approval_id for approval in approvals}

    for step in steps:
        status = str(step.status or "").upper()
        if status not in {"DONE", "FAILED", "AMBIGUOUS"}:
            continue
        is_write = _is_write_tool_name(step.tool_name)
        if not is_write and not step.requires_approval:
            continue
        default_status = "failed" if status in {"FAILED", "AMBIGUOUS"} else "succeeded"
        approval_id = step.approval_id
        if isinstance(step.result, dict):
            approval_id = _trimmed(step.result.get("approval_id") or step.result.get("_approval_id") or approval_id) or None
        if approvals and approval_id is None and is_write:
            continue
        if not is_write and approval_id is None:
            continue
        rows = _operation_rows_from_result(
            step.result if isinstance(step.result, dict) else None,
            default_status=default_status,
            operation_id=operation_id or step.plan_id,
            approval_id=approval_id,
            step_id=step.step_id,
            tool_name=step.tool_name,
            fallback_args=step.args if is_write else None,
        )
        _add_group_rows(
            groups,
            rows=rows,
            operation_id=operation_id or step.plan_id,
            approval_id=approval_id,
            step_id=step.step_id,
            completed_at=step.completed_at or step.started_at,
        )

    for event in timeline:
        if event.event_type != "tool_result":
            continue
        details = event.details if isinstance(event.details, dict) else {}
        result = details.get("result") if isinstance(details.get("result"), dict) else None
        args = details.get("args") if isinstance(details.get("args"), dict) else {}
        status = str(event.status or "").upper()
        default_status = "failed" if status in {"FAILED", "AMBIGUOUS"} else "succeeded"
        event_approval_id = event.approval_id
        if isinstance(result, dict):
            event_approval_id = _trimmed(result.get("approval_id") or result.get("_approval_id") or event_approval_id) or None
        if approvals and event_approval_id is None and _is_write_tool_name(event.tool_name):
            continue
        if not (_is_write_tool_name(event.tool_name) or event_approval_id in approval_ids):
            continue
        rows = _operation_rows_from_result(
            result,
            default_status=default_status,
            operation_id=event.operation_id or operation_id,
            approval_id=event_approval_id,
            step_id=event.step_id,
            tool_name=event.tool_name,
            fallback_args=args if _is_write_tool_name(event.tool_name) else None,
        )
        _add_group_rows(
            groups,
            rows=rows,
            operation_id=event.operation_id or operation_id,
            approval_id=event_approval_id,
            step_id=event.step_id,
            completed_at=event.created_at,
        )

    if presentation.kind in {"mutation_result", "partial_failure"} and presentation.rows:
        for row in presentation.rows:
            approval_id = _trimmed(row.get("approval_id") or presentation.approval_id) or None
            _add_group_rows(
                groups,
                rows=[dict(row)],
                operation_id=_trimmed(row.get("operation_id") or presentation.operation_id or operation_id) or None,
                approval_id=approval_id,
                step_id=_trimmed(row.get("step_id")) or None,
                completed_at=None,
            )

    for group in groups.values():
        group.rows = _dedupe_rows(group.rows)

    approval_positions = _approval_position_by_id(approvals)
    sorted_groups = sorted(groups.values(), key=lambda group: _group_sort_key(group, approval_positions))
    business_groups = _merge_mutation_groups_by_business_change(sorted_groups)
    # Typed business-change groups carry their own ids, field changes, selector, and
    # source-state basis. Summary text ordering is only a legacy compatibility path
    # for older untyped mutation rows.
    business_order = (
        {}
        if any(_group_has_business_change_contract(group) for group in business_groups)
        else _business_change_order_from_text(presentation.summary)
    )
    return sorted(business_groups, key=lambda group: _business_group_sort_key(group, approval_positions, business_order))


def _read_evidence(
    *,
    steps: list[PlanStepResponse],
    timeline: list[TimelineEventResponse],
    presentation: PresentationResponse,
    operation_id: str | None,
) -> list[ReadEvidence]:
    rows_by_key: dict[str, ReadEvidence] = {}

    def add_rows(
        key: str,
        rows: list[dict[str, Any]],
        step_id: str | None,
        completed_at: datetime | None,
        *,
        tool_name: str | None = None,
        args: dict[str, Any] | None = None,
    ) -> None:
        if key not in rows_by_key:
            rows_by_key[key] = ReadEvidence(key=key, operation_id=operation_id)
        evidence = rows_by_key[key]
        evidence.rows.extend(rows)
        if step_id and step_id not in evidence.step_ids:
            evidence.step_ids.append(step_id)
        if completed_at and (evidence.completed_at is None or completed_at > evidence.completed_at):
            evidence.completed_at = completed_at
        if tool_name and not evidence.tool_name:
            evidence.tool_name = tool_name
        if args and not evidence.args:
            evidence.args = dict(args)

    for step in steps:
        status = str(step.status or "").upper()
        if status not in {"DONE", "FAILED", "AMBIGUOUS"} or _is_write_tool_name(step.tool_name):
            continue
        if not (_is_read_tool_name(step.tool_name) or isinstance(step.result, dict)):
            continue
        default_status = "failed" if status in {"FAILED", "AMBIGUOUS"} else "succeeded"
        rows = _operation_rows_from_result(
            step.result if isinstance(step.result, dict) else None,
            default_status=default_status,
            operation_id=operation_id or step.plan_id,
            approval_id=None,
            step_id=step.step_id,
            tool_name=step.tool_name,
        )
        add_rows(
            f"read:{step.step_id}",
            rows,
            step.step_id,
            step.completed_at or step.started_at,
            tool_name=step.tool_name,
            args=step.args if isinstance(step.args, dict) else {},
        )

    for event in timeline:
        if event.event_type != "tool_result" or _is_write_tool_name(event.tool_name):
            continue
        details = event.details if isinstance(event.details, dict) else {}
        result = details.get("result") if isinstance(details.get("result"), dict) else None
        args = details.get("args") if isinstance(details.get("args"), dict) else {}
        status = str(event.status or "").upper()
        default_status = "failed" if status in {"FAILED", "AMBIGUOUS"} else "succeeded"
        rows = _operation_rows_from_result(
            result,
            default_status=default_status,
            operation_id=event.operation_id or operation_id,
            approval_id=None,
            step_id=event.step_id,
            tool_name=event.tool_name,
        )
        add_rows(
            f"read:{event.step_id or event.event_id}",
            rows,
            event.step_id,
            event.created_at,
            tool_name=event.tool_name,
            args=args,
        )

    if presentation.kind == "answer" and presentation.rows:
        add_rows("read:presentation", [dict(row) for row in presentation.rows], None, None)

    out: list[ReadEvidence] = []
    for evidence in rows_by_key.values():
        evidence.rows = _dedupe_rows(evidence.rows)
        out.append(evidence)
    return sorted(out, key=lambda item: (item.completed_at or datetime.min, item.key))


def _source_priority(row: dict[str, Any]) -> str:
    return _trimmed(
        row.get("previous_priority")
        or row.get("original_priority")
        or row.get("from_priority")
        or row.get("source_priority")
        or row.get("before_priority")
    ).lower()


def _target_priority(row: dict[str, Any]) -> str:
    return _trimmed(
        row.get("new_priority")
        or row.get("priority")
        or row.get("requested_priority")
        or row.get("to_priority")
        or row.get("target_priority")
        or row.get("after_priority")
    ).lower()


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _trimmed(row.get(key))
        if value:
            return value
    return ""


def _business_contract_value(row: dict[str, Any]) -> str:
    value = _first_text(
        row,
        (
            "contract",
            "business_contract",
            "business_change_contract",
            "response_contract",
            "result_contract",
        ),
    )
    if value:
        return value
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        return _first_text(
            metadata,
            (
                "contract",
                "business_contract",
                "business_change_contract",
                "response_contract",
                "result_contract",
            ),
        )
    return ""


def _row_is_job_priority_business_change(row: dict[str, Any]) -> bool:
    if _row_entity_type(row) != "job":
        return False
    return bool(_source_priority(row) and _target_priority(row))


def _row_has_business_change_contract(row: dict[str, Any]) -> bool:
    return _business_contract_value(row) == BUSINESS_CHANGE_CONTRACT or _row_is_job_priority_business_change(row)


def _row_entity_type(row: dict[str, Any]) -> str:
    explicit = _first_text(row, ("entity_type", "entity", "record_type", "resource_type"))
    if explicit:
        return explicit
    if _trimmed(row.get("job_id")):
        return "job"
    if _trimmed(row.get("machine_id")):
        return "machine"
    if _trimmed(row.get("product_id")):
        return "product"
    if _trimmed(row.get("material_id")):
        return "material"
    return "record"


def _priority_field_change(row: dict[str, Any]) -> dict[str, Any] | None:
    source = _source_priority(row)
    target = _target_priority(row)
    if not (source and target):
        return None
    return {"field": "priority", "label": "Priority", "from": source, "to": target}


def _normalized_field_change(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    field = _first_text(value, ("field", "key", "name", "path"))
    before = (
        value.get("from")
        if "from" in value
        else value.get("from_value")
        if "from_value" in value
        else value.get("before")
        if "before" in value
        else value.get("old_value")
    )
    after = (
        value.get("to")
        if "to" in value
        else value.get("to_value")
        if "to_value" in value
        else value.get("after")
        if "after" in value
        else value.get("new_value")
    )
    if not field and before in (None, "") and after in (None, ""):
        return None
    label = _first_text(value, ("label", "display_label", "field_label")) or _human_status_label(field)
    out: dict[str, Any] = {
        "field": field or "value",
        "label": label,
    }
    if before not in (None, ""):
        out["from"] = before
    if after not in (None, ""):
        out["to"] = after
    return out


def _row_field_changes(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("field_changes")
    if raw is None:
        raw = row.get("changes")
    changes: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for value in raw:
            change = _normalized_field_change(value)
            if change is not None:
                changes.append(change)
    if not changes and _row_is_job_priority_business_change(row):
        priority_change = _priority_field_change(row)
        if priority_change is not None:
            changes.append(priority_change)
    return changes


def _row_source_state_basis(row: dict[str, Any]) -> str:
    explicit = _first_text(row, ("source_state_basis", "basis", "state_basis"))
    if explicit:
        return explicit
    write_set = _trimmed(row.get("write_set")).lower()
    bundle_kind = _trimmed(row.get("bundle_kind")).lower()
    if row.get("original_priority") or write_set.startswith("original_") or "cascade" in bundle_kind:
        return "original"
    return "current"


def _row_selector_summary(row: dict[str, Any]) -> str:
    explicit = _first_text(row, ("selector_summary", "selector", "filter_summary"))
    if explicit:
        return explicit
    source = _source_priority(row)
    if source:
        return f"priority = {source}"
    record_id = _business_record_identifier(row)
    entity_type = _row_entity_type(row)
    if record_id:
        return f"{entity_type}_id = {record_id}"
    return ""


def _row_business_change_id(row: dict[str, Any]) -> str:
    explicit = _first_text(row, ("business_change_id", "change_id", "business_id"))
    if explicit:
        return explicit
    if _row_is_job_priority_business_change(row):
        basis = _row_source_state_basis(row).replace(" ", "_").lower()
        return f"job-priority-{basis}-{_source_priority(row)}-to-{_target_priority(row)}"
    return ""


def _group_common_text(group: MutationGroup, keys: tuple[str, ...]) -> str:
    for row in group.rows:
        value = _first_text(row, keys)
        if value:
            return value
    return ""


def _group_common_source_state_basis(group: MutationGroup) -> str:
    for row in group.rows:
        basis = _row_source_state_basis(row)
        if basis:
            return basis
    return "current"


def _group_common_selector_summary(group: MutationGroup) -> str:
    for row in group.rows:
        selector = _row_selector_summary(row)
        if selector:
            return selector
    return ""


def _typed_business_group_key(group: MutationGroup) -> str | None:
    for row in group.rows:
        if not _row_has_business_change_contract(row):
            continue
        return _business_group_key(row, fallback=group.key)
    sources = {_source_priority(row) for row in group.rows if _source_priority(row)}
    targets = {_target_priority(row) for row in group.rows if _target_priority(row)}
    if len(sources) == 1 and len(targets) == 1:
        return _priority_business_key(next(iter(sources)), next(iter(targets)))
    return None


def _group_entity_type(group: MutationGroup) -> str:
    if _is_no_op_group(group):
        return _trimmed(group.entity_type) or "record"
    explicit = _group_common_text(group, ("entity_type", "entity", "record_type", "resource_type"))
    if explicit:
        return explicit
    for row in group.rows:
        entity_type = _row_entity_type(row)
        if entity_type and entity_type != "record":
            return entity_type
    return "record"


def _group_has_business_change_contract(group: MutationGroup) -> bool:
    return any(_row_has_business_change_contract(row) for row in group.rows)


def _group_field_changes(group: MutationGroup) -> list[dict[str, Any]]:
    seen: set[str] = set()
    changes: list[dict[str, Any]] = []
    for row in group.rows:
        for change in _row_field_changes(row):
            key = json.dumps(change, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            changes.append(change)
    return changes


def _field_changes_summary(changes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for change in changes:
        label = _trimmed(change.get("label") or change.get("field")) or "Value"
        before = _trimmed(change.get("from"))
        after = _trimmed(change.get("to"))
        if before and after:
            parts.append(f"{label}: {before} -> {after}")
        elif after:
            parts.append(f"{label}: {after}")
        elif before:
            parts.append(f"{label}: {before}")
    return "; ".join(parts)


def _business_row_dedupe_key(row: dict[str, Any]) -> str | None:
    record_id = _business_record_identifier(row)
    if not record_id:
        return None
    if _row_has_business_change_contract(row):
        return json.dumps(
            [
                BUSINESS_CHANGE_CONTRACT,
                record_id,
                _row_business_change_id(row),
                _row_field_changes(row),
                _normalize_row_status(row.get("status"), default=""),
            ],
            sort_keys=True,
            default=str,
        )
    source = _source_priority(row)
    target = _target_priority(row)
    status = _normalize_row_status(row.get("status"), default="")
    if source or target:
        return json.dumps(["mutation", record_id, source, target, status], sort_keys=True)
    write_set = _trimmed(row.get("write_set"))
    if write_set:
        return json.dumps(["write_set", record_id, write_set, status], sort_keys=True)
    return None


def _rows_use_original_state(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if row.get("original_priority") or _trimmed(row.get("source_state_basis")).lower() == "original":
            return True
        write_set = _trimmed(row.get("write_set")).lower()
        bundle_kind = _trimmed(row.get("bundle_kind")).lower()
        if write_set.startswith("original_") or "cascade" in bundle_kind:
            return True
    return False


def _priority_label(value: str) -> str:
    text = _trimmed(value).lower()
    return text.capitalize() if text else "Unknown"


def _business_change_label(group: MutationGroup, *, index: int) -> str:
    if _is_no_op_group(group):
        return "Not changed"
    explicit = _group_common_text(group, ("business_change", "business_change_label", "change_label"))
    if explicit:
        return explicit
    sources = {_source_priority(row) for row in group.rows if _source_priority(row)}
    targets = {_target_priority(row) for row in group.rows if _target_priority(row)}
    if len(sources) == 1 and len(targets) == 1:
        source = next(iter(sources))
        target = next(iter(targets))
        original_prefix = "Original " if index > 1 and _rows_use_original_state(group.rows) else ""
        return f"{original_prefix}{_priority_label(source)} -> {_priority_label(target)}"
    return f"Business change {index}"


def _business_change_summary(group: MutationGroup, *, index: int) -> str:
    if _is_no_op_group(group):
        return _noop_change_summary(group)
    label = _business_change_label(group, index=index)
    count = len(group.rows)
    if _group_has_business_change_contract(group):
        noun = _entity_noun(_group_entity_type(group), count)
    else:
        noun = "jobs" if _mutation_total_noun([group]) == "jobs" else _plural(count, "record")
    return f"{label}: {count} {noun}"


def _clean_business_mutation_row(row: dict[str, Any], *, business_change: str) -> dict[str, Any]:
    if _row_has_business_change_contract(row):
        clean: dict[str, Any] = {"business_change": business_change}
        record_id = _business_record_identifier(row)
        if record_id:
            clean["record_id"] = record_id
        display_id = _first_text(row, ("display_id", "display_name", "name", "label")) or record_id
        if display_id:
            clean["display_id"] = display_id
        entity_type = _row_entity_type(row)
        if entity_type:
            clean["entity_type"] = entity_type
        business_change_id = _row_business_change_id(row)
        if business_change_id:
            clean["business_change_id"] = business_change_id
        changes = _row_field_changes(row)
        if changes:
            clean["field_changes"] = changes
            summary = _field_changes_summary(changes)
            if summary:
                clean["change"] = summary
        status = _normalize_row_status(row.get("status"), default="")
        if status:
            clean["status"] = status
            clean["outcome"] = status
        error = _trimmed(row.get("error"))
        if error and status == "failed":
            clean["error"] = _redact_sensitive_text(error)
        return clean

    clean: dict[str, Any] = {}
    record_id = _business_record_identifier(row)
    if record_id:
        if _trimmed(row.get("job_id")):
            clean["job_id"] = record_id
        else:
            clean["record_id"] = record_id
    source = _source_priority(row)
    target = _target_priority(row)
    if source:
        clean["from_priority"] = source
    if target:
        clean["to_priority"] = target
    if source and target:
        clean["change"] = f"{source} -> {target}"
    clean["business_change"] = business_change
    status = _normalize_row_status(row.get("status"), default="")
    if status:
        clean["status"] = status
    error = _trimmed(row.get("error"))
    if error and status == "failed":
        clean["error"] = _redact_sensitive_text(error)
    return clean


def _business_change_contract_payload(group: MutationGroup, *, index: int) -> dict[str, Any]:
    if not _group_has_business_change_contract(group):
        return {}
    field_changes = _group_field_changes(group)
    return {
        "contract": BUSINESS_CHANGE_CONTRACT,
        "business_change_id": _group_common_text(group, ("business_change_id", "change_id", "business_id"))
        or next((_row_business_change_id(row) for row in group.rows if _row_business_change_id(row)), "")
        or f"business-change-{index}",
        "entity_type": _group_entity_type(group),
        "change_type": _group_common_text(group, ("change_type", "mutation_type", "operation_type")) or "update",
        "selector_summary": _group_common_text(group, ("selector_summary", "selector", "filter_summary"))
        or _group_common_selector_summary(group),
        "source_state_basis": _group_common_text(group, ("source_state_basis", "basis", "state_basis"))
        or _group_common_source_state_basis(group),
        "field_changes": field_changes,
    }


def _mutation_business_payloads(groups: list[MutationGroup]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    group_payloads: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        label = _business_change_label(group, index=index)
        rows = [] if _is_no_op_group(group) else _dedupe_rows(
            [_clean_business_mutation_row(row, business_change=label) for row in group.rows]
        )
        summary = _business_change_summary(group, index=index)
        group_payload = {
            "business_change": label,
            "summary": summary,
            "record_count": _mutation_group_record_count(group),
            "rows": rows,
        }
        group_payload.update(_business_change_contract_payload(group, index=index))
        if _is_no_op_group(group):
            group_payload.update(
                {
                    "contract": NO_OP_MUTATION_CONTRACT,
                    "entity_type": group.entity_type,
                    "selector_summary": group.selector_summary,
                    "change_summary": group.change_summary,
                    "matched_count": int(group.matched_count or 0),
                    "changed_count": int(group.changed_count or 0),
                    "status": group.status,
                    "reason": group.reason or NO_OP_MUTATION_REASON,
                }
            )
        group_payloads.append(group_payload)
        all_rows.extend(rows)
    return group_payloads, all_rows


def _priority_change_summary(rows: list[dict[str, Any]], *, approval_id: str | None = None) -> str | None:
    if not rows:
        return None
    sources = {_source_priority(row) for row in rows if _source_priority(row)}
    targets = {_target_priority(row) for row in rows if _target_priority(row)}
    if len(sources) != 1 or len(targets) != 1:
        return None
    source = next(iter(sources))
    target = next(iter(targets))
    count = len(rows)
    original_text = "original " if _rows_use_original_state(rows) else ""
    job_word = _plural(count, "job")
    suffix = f" under approval {approval_id}" if approval_id else ""
    return f"{count} {original_text}{source} priority {job_word} changed to {target}{suffix}."


def _generic_mutation_summary(group: MutationGroup) -> str:
    if _is_no_op_group(group):
        return _noop_change_summary(group)
    count = len(group.rows)
    counts = _row_status_counts(group.rows)
    if counts.get("failed", 0) and counts.get("succeeded", 0):
        return f"{counts.get('succeeded', 0)} of {count} {_plural(count, 'record')} updated; {counts.get('failed', 0)} failed."
    if counts.get("failed", 0):
        return f"{count} {_plural(count, 'record')} failed to update."
    return f"Updated {count} {_plural(count, 'record')}."


def _mutation_group_summary(group: MutationGroup, *, include_approval: bool = False) -> str:
    priority = _priority_change_summary(group.rows, approval_id=group.approval_id if include_approval else None)
    if priority:
        return priority
    return _generic_mutation_summary(group)


def _mutation_total_noun(groups: list[MutationGroup]) -> str:
    all_rows = [row for group in groups for row in group.rows]
    if not all_rows:
        entity_types = {_trimmed(group.entity_type).lower() for group in groups if _is_no_op_group(group) and _trimmed(group.entity_type)}
        if len(entity_types) == 1:
            return _entity_noun(next(iter(entity_types)), 2)
        return "records"
    contract_entity_types = {
        _group_entity_type(group)
        for group in groups
        if _group_has_business_change_contract(group) and _group_entity_type(group)
    }
    if len(contract_entity_types) == 1:
        return _entity_noun(next(iter(contract_entity_types)), len(all_rows))
    return "records"


def _read_result_shape(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "empty"
    if len(rows) == 1:
        return "list"
    key_sets = [set(row.keys()) - {"status", "operation_id", "step_id", "tool_name"} for row in rows if isinstance(row, dict)]
    common = set.intersection(*key_sets) if key_sets else set()
    return "table" if len(common) >= 2 else "list"


def _is_empty_result_envelope(row: dict[str, Any]) -> bool:
    data = row.get("data")
    if not isinstance(data, list) or data:
        return False
    meaningful_keys = set(row) - {"success", "data", "status", "operation_id", "step_id", "tool_name"}
    return not meaningful_keys and not _row_identifier(row)


def _read_summary(rows: list[dict[str, Any]], fallback: str | None) -> str:
    text = _trimmed(fallback)
    if text:
        return text
    if not rows:
        return "No matching records were found."
    return f"Found {len(rows)} {_plural(len(rows), 'record')}."


def _read_policy_summary(
    rows: list[dict[str, Any]],
    policy: ReadDisplayPolicy | None,
    fallback: str | None,
) -> str:
    if policy and policy.contract == ENTITY_STATUS_CONTRACT:
        count = max(int(policy.entity_count or 0), len(rows))
        entity_label = _human_status_label(policy.entity_type or "record").lower()
        if count <= 0:
            return f"No matching {entity_label} statuses were found."
        status_noun = f"{entity_label} status" if count == 1 else f"{entity_label} statuses"
        return f"Found {count} {status_noun}."
    if policy and policy.display_mode == DISPLAY_MODE_NO_MATCH_DIAGNOSTIC:
        return "No matching records were found."
    return _read_summary(rows, fallback)


def _read_scope_for_request(session: Any) -> str:
    text = _trimmed(getattr(session, "current_intent", None))
    if _status_request_wants_full_details(session):
        return READ_SCOPE_DETAILS
    if _STATUS_INTENT_RE.search(text):
        return READ_SCOPE_STATUS_ONLY
    return READ_SCOPE_RECORDS


_STATUS_VALUE_KEYS = ("currentstatus", "machinestatus", "operationalstatus", "state", "status")
_STATUS_OUTCOME_VALUES = {"succeeded", "success", "ok", "done", "updated", "created", "deleted", "applied", "pending"}
_STATUS_METADATA_KEYS = {
    "operationid",
    "stepid",
    "toolname",
    "rowid",
    "approvalid",
    "success",
    "data",
    "result",
    "outcome",
}
_STATUS_LOW_VALUE_KEYS = {
    "defaultsetuptime",
    "defaultcleaningtime",
    "defaultchangeovertime",
    "utilizationrate",
}
_STATUS_INTENT_RE = re.compile(r"\b(status|state|health|condition|running|availability|available|alarms?)\b", re.IGNORECASE)
_DETAILS_INTENT_RE = re.compile(
    r"\b(full|technical|raw|all\s+fields?|every\s+field|complete\s+details?|details?)\b",
    re.IGNORECASE,
)
_STATUS_ENTITY_ID_KEYS: dict[str, tuple[str, ...]] = {
    "machine": ("machineid", "id", "recordid", "rowid"),
    "job": ("jobid", "id", "recordid", "rowid"),
    "product": ("productid", "id", "recordid", "rowid"),
    "inventory": ("inventoryid", "materialid", "id", "recordid", "rowid"),
    "record": ("id", "recordid", "rowid"),
}
_STATUS_FIELD_ORDER: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
    "machine": [
        ("machine_id", "Machine ID", ("machineid", "id")),
        ("machine_name", "Machine name", ("machinename", "name")),
        ("machine_type", "Machine type", ("machinetype", "type")),
        ("location", "Location", ("location",)),
        ("status", "Status", _STATUS_VALUE_KEYS),
        ("capacity_per_hour", "Capacity per hour", ("capacityperhour",)),
        ("last_maintenance", "Last maintenance", ("lastmaintenancedate", "lastmaintenance")),
        ("maintenance_interval", "Maintenance interval", ("maintenanceintervaldays", "maintenanceinterval")),
    ],
}


def _singular_entity_token(value: Any) -> str:
    token = re.sub(r"[^a-z0-9_]+", "_", str(value or "").lower()).strip("_")
    if not token:
        return ""
    if token.endswith("ies") and len(token) > 3:
        return f"{token[:-3]}y"
    if token.endswith("s") and not token.endswith("ss") and len(token) > 1:
        return token[:-1]
    return token


def _tool_entity_type(tool_name: Any) -> str | None:
    text = _trimmed(tool_name).lower()
    match = re.search(r"^[a-z]+__([a-z][a-z0-9_-]*?)(?:_\{|$|__)", text)
    if not match:
        return None
    entity_type = _singular_entity_token(match.group(1).replace("-", "_"))
    return entity_type or None


def _canonical_status_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key or "").lower())


def _human_status_label(key: Any) -> str:
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key or "field"))
    raw = raw.replace("_", " ").replace("-", " ")
    parts = [part for part in raw.split() if part]
    if not parts:
        return "Field"
    return " ".join("ID" if part.lower() == "id" else part.capitalize() for part in parts)


def _snake_status_key(key: Any) -> str:
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key or "field"))
    raw = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_")
    lowered = raw.lower()
    return lowered or "field"


def _status_row_value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    wanted = {_canonical_status_key(alias) for alias in aliases}
    for key, value in row.items():
        if _canonical_status_key(key) in wanted and value not in (None, ""):
            return value
    return None


def _status_entity_type(row: dict[str, Any]) -> str:
    tool_entity = _tool_entity_type(row.get("tool_name"))
    if tool_entity and _status_entity_id(row, tool_entity):
        return tool_entity
    tool_name = _trimmed(row.get("tool_name")).lower()
    key_text = " ".join(_canonical_status_key(key) for key in row)
    probe = f"{tool_name} {key_text}"
    if "machine" in probe:
        return "machine"
    if "job" in probe:
        return "job"
    if "product" in probe:
        return "product"
    if "inventory" in probe or "material" in probe:
        return "inventory"
    return "record"


def _status_display_value(canonical: str, value: Any) -> str:
    text = _trimmed(value)
    if not text:
        return ""
    if canonical in {"status", "machine_status"}:
        return text.replace("_", " ").lower()
    if canonical == "maintenance_interval" and text.isdigit():
        count = int(text)
        return f"{count} {_plural(count, 'day')}"
    return text


def _is_zeroish(value: Any) -> bool:
    if value in (None, ""):
        return True
    if isinstance(value, (int, float)):
        return float(value) == 0.0
    text = _trimmed(value).lower()
    return text in {"0", "0.0", "0%", "none", "n/a", "null", "false"}


def _status_request_wants_full_details(session: Any) -> bool:
    text = _trimmed(getattr(session, "current_intent", None)).lower()
    if re.search(r"\b(?:do\s+not|don't|dont|without|no)\s+(?:show\s+)?(?:other\s+)?(?:machine\s+|job\s+|record\s+)?details?\b", text):
        return False
    return bool(_DETAILS_INTENT_RE.search(text))


def _status_primary_value(row: dict[str, Any]) -> str | None:
    for key in _STATUS_VALUE_KEYS:
        value = _status_row_value(row, (key,))
        display = _status_display_value("status", value)
        if display and display not in _STATUS_OUTCOME_VALUES:
            return display
    return None


def _status_entity_id(row: dict[str, Any], entity_type: str) -> str | None:
    value = _status_row_value(row, _STATUS_ENTITY_ID_KEYS.get(entity_type, _STATUS_ENTITY_ID_KEYS["record"]))
    text = _trimmed(value)
    return text or None


def _status_identity_field_key(row: dict[str, Any], entity_type: str) -> str:
    aliases = _STATUS_ENTITY_ID_KEYS.get(entity_type, _STATUS_ENTITY_ID_KEYS["record"])
    alias_tokens = {_canonical_status_key(alias) for alias in aliases}
    for key, value in row.items():
        canonical = _canonical_status_key(key)
        if canonical not in alias_tokens or canonical in {"id", "recordid", "rowid"}:
            continue
        if value not in (None, ""):
            return _snake_status_key(key)
    if entity_type and entity_type != "record":
        return f"{entity_type}_id"
    return "record_id"


def _status_requested_fields(row: dict[str, Any], entity_type: str, read_scope: str) -> list[str]:
    fields = [_status_identity_field_key(row, entity_type), "status"]
    if read_scope == READ_SCOPE_DETAILS:
        fields.append("details")
    return fields


def _status_visible_fields(row: dict[str, Any], entity_type: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    entity_id = _status_entity_id(row, entity_type)
    status = _status_primary_value(row)
    if entity_id:
        identity_key = _status_identity_field_key(row, entity_type)
        fields.append({"key": identity_key, "label": _human_status_label(identity_key), "value": entity_id})
    if status:
        fields.append({"key": "status", "label": "Status", "value": status, "primary": True})
    return fields


def _status_visible_key_tokens(row: dict[str, Any], entity_type: str, fields: list[dict[str, Any]]) -> set[str]:
    visible_key_tokens = {
        _canonical_status_key(field.get("key"))
        for field in fields
        if isinstance(field, dict)
    }
    visible_key_tokens.update(_canonical_status_key(alias) for alias in _STATUS_ENTITY_ID_KEYS.get(entity_type, ()))
    visible_key_tokens.update(_canonical_status_key(alias) for alias in _STATUS_VALUE_KEYS)
    visible_key_tokens.update(
        _canonical_status_key(key)
        for key, value in row.items()
        if _canonical_status_key(key) in visible_key_tokens and value not in (None, "")
    )
    return visible_key_tokens


def _status_secondary_fields(row: dict[str, Any], *, visible_keys: set[str], include: bool) -> list[dict[str, Any]]:
    if not include:
        return []
    fields: list[dict[str, Any]] = []
    for key, value in row.items():
        canonical = _canonical_status_key(key)
        if canonical in visible_keys or canonical in _STATUS_METADATA_KEYS:
            continue
        if canonical in _STATUS_LOW_VALUE_KEYS and _is_zeroish(value):
            continue
        display = _status_display_value(canonical, value)
        if not display:
            continue
        fields.append({"key": _snake_status_key(key), "label": _human_status_label(key), "value": display})
    return fields[:12]


def _project_status_row(row: dict[str, Any], entity_type: str | None = None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    resolved_entity_type = entity_type or _status_entity_type(row)
    entity_id = _status_entity_id(row, resolved_entity_type)
    primary_status = _status_primary_value(row)
    if not entity_id or not primary_status:
        return None
    return {
        _status_identity_field_key(row, resolved_entity_type): entity_id,
        "status": primary_status,
    }


def _status_rows_are_projectable(rows: list[dict[str, Any]]) -> bool:
    return bool(rows) and all(_project_status_row(row) is not None for row in rows if isinstance(row, dict))


def _read_policy_entity_type(rows: list[dict[str, Any]], status_result: dict[str, Any] | None) -> str | None:
    if status_result and status_result.get("entity_type"):
        return _trimmed(status_result.get("entity_type")) or None
    entity_types = {
        _status_entity_type(row)
        for row in rows
        if isinstance(row, dict) and _status_entity_id(row, _status_entity_type(row))
    }
    if len(entity_types) == 1:
        return next(iter(entity_types))
    return None


def _requested_fields_from_read_evidence(read_evidence: list[ReadEvidence] | None) -> list[str]:
    if not read_evidence:
        return []
    field_sets: list[tuple[str, ...]] = []
    for evidence in read_evidence:
        fields = tuple(parse_fields_arg(evidence.args.get("fields") if isinstance(evidence.args, dict) else None))
        if fields:
            field_sets.append(fields)
    unique = list(dict.fromkeys(field_sets))
    return list(unique[0]) if len(unique) == 1 else []


def _sort_fields_from_args(args: dict[str, Any] | None) -> list[str]:
    if not isinstance(args, dict):
        return []
    raw = args.get("sort_by") or args.get("order_by")
    values = raw if isinstance(raw, list) else [raw]
    fields = [
        _canonical_requested_field_key(value)
        for value in values
        if _canonical_requested_field_key(value)
    ]
    return list(dict.fromkeys(fields))


def _sort_fields_from_read_evidence(read_evidence: list[ReadEvidence] | None) -> list[str]:
    if not read_evidence:
        return []
    field_sets = [tuple(_sort_fields_from_args(evidence.args)) for evidence in read_evidence]
    field_sets = [fields for fields in field_sets if fields]
    unique = list(dict.fromkeys(field_sets))
    return list(unique[0]) if len(unique) == 1 else []


def _read_display_policy(
    rows: list[dict[str, Any]],
    *,
    session: Any,
    status_result: dict[str, Any] | None,
    has_read_evidence: bool,
    read_evidence: list[ReadEvidence] | None = None,
) -> ReadDisplayPolicy | None:
    if not rows:
        if has_read_evidence:
            return ReadDisplayPolicy(
                read_scope=READ_SCOPE_RECORDS,
                requested_fields=[],
                display_mode=DISPLAY_MODE_NO_MATCH_DIAGNOSTIC,
                entity_count=0,
            )
        return None

    read_scope = _read_scope_for_request(session)
    entity_type = _read_policy_entity_type(rows, status_result)
    entity_count = len(rows)
    if status_result:
        requested_fields = list(status_result.get("requested_fields") or [])
        display_mode = (
            DISPLAY_MODE_DETAIL_STATUS_CARD
            if read_scope == READ_SCOPE_DETAILS
            else DISPLAY_MODE_COMPACT_STATUS_CARD
        )
        return ReadDisplayPolicy(
            read_scope=read_scope,
            requested_fields=requested_fields,
            display_mode=display_mode,
            entity_count=entity_count,
            entity_type=entity_type,
            contract=ENTITY_STATUS_CONTRACT,
        )

    if read_scope in {READ_SCOPE_STATUS_ONLY, READ_SCOPE_DETAILS} and _status_rows_are_projectable(rows):
        first_row = rows[0]
        resolved_entity_type = entity_type or _status_entity_type(first_row)
        display_mode = (
            DISPLAY_MODE_COLLAPSED_COLLECTION_TABLE
            if entity_count > READ_DISPLAY_PREVIEW_LIMIT
            else DISPLAY_MODE_COLLECTION_TABLE
        )
        return ReadDisplayPolicy(
            read_scope=read_scope,
            requested_fields=_status_requested_fields(first_row, resolved_entity_type, read_scope),
            display_mode=display_mode,
            entity_count=entity_count,
            entity_type=resolved_entity_type,
            contract=ENTITY_STATUS_CONTRACT,
            details_collapsed=entity_count > READ_DISPLAY_PREVIEW_LIMIT,
        )

    display_mode = (
        DISPLAY_MODE_COLLAPSED_COLLECTION_TABLE
        if entity_count > READ_DISPLAY_PREVIEW_LIMIT
        else DISPLAY_MODE_COLLECTION_TABLE
        if entity_count > 1
        else DISPLAY_MODE_RECORD_PREVIEW
    )
    return ReadDisplayPolicy(
        read_scope=READ_SCOPE_RECORDS,
        requested_fields=_requested_fields_from_read_evidence(read_evidence),
        display_mode=display_mode,
        entity_count=entity_count,
        entity_type=entity_type,
        preview_limit=READ_DISPLAY_PREVIEW_LIMIT,
        details_collapsed=entity_count > READ_DISPLAY_PREVIEW_LIMIT,
        sort_fields=_sort_fields_from_read_evidence(read_evidence),
    )


def _canonical_requested_field_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _collection_identity_fields(row: dict[str, Any], entity_type: str | None) -> list[str]:
    if not isinstance(row, dict):
        return []
    metadata_ids = {"operation_id", "step_id", "tool_id", "approval_id", "row_id"}
    preferred: list[str] = []
    if entity_type:
        preferred.append(f"{entity_type}_id")
    preferred.extend(["id", "entity_id", "job_id", "machine_id", "record_id"])
    by_canonical = {_canonical_requested_field_key(key): key for key in row.keys()}
    fields: list[str] = []
    for candidate in preferred:
        canonical = _canonical_requested_field_key(candidate)
        if canonical not in metadata_ids and canonical in by_canonical and row.get(by_canonical[canonical]) not in (None, ""):
            fields.append(canonical)
    for key, value in row.items():
        canonical = _canonical_requested_field_key(key)
        if (
            not fields
            and canonical.endswith("_id")
            and canonical not in metadata_ids
            and value not in (None, "")
        ):
            fields.append(canonical)
    return list(dict.fromkeys(fields))


def _collection_projection_fields(
    row: dict[str, Any],
    fields: list[str],
    *,
    entity_type: str | None,
    sort_fields: list[str] | None = None,
) -> list[str]:
    requested = [_canonical_requested_field_key(field) for field in fields if _canonical_requested_field_key(field)]
    sorted_by = [_canonical_requested_field_key(field) for field in sort_fields or [] if _canonical_requested_field_key(field)]
    identity = _collection_identity_fields(row, entity_type)
    return list(dict.fromkeys([*identity, *requested, *sorted_by]))


def _project_requested_fields_row(
    row: dict[str, Any],
    fields: list[str],
    *,
    entity_type: str | None = None,
    sort_fields: list[str] | None = None,
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    by_canonical = {_canonical_requested_field_key(key): key for key in row.keys()}
    for field in _collection_projection_fields(row, fields, entity_type=entity_type, sort_fields=sort_fields):
        key = by_canonical.get(_canonical_requested_field_key(field))
        if key is not None:
            projected[_canonical_requested_field_key(field)] = row.get(key)
    return projected


def _project_read_rows_for_policy(rows: list[dict[str, Any]], policy: ReadDisplayPolicy | None) -> list[dict[str, Any]]:
    if policy is None:
        return rows
    if policy.contract != ENTITY_STATUS_CONTRACT and policy.requested_fields:
        return [
            _project_requested_fields_row(
                row,
                policy.requested_fields,
                entity_type=policy.entity_type,
                sort_fields=policy.sort_fields,
            )
            for row in rows
            if isinstance(row, dict)
        ]
    if (
        policy.contract != ENTITY_STATUS_CONTRACT
        or policy.read_scope != READ_SCOPE_STATUS_ONLY
        or policy.entity_count <= 1
    ):
        return rows
    projected: list[dict[str, Any]] = []
    for row in rows:
        projected_row = _project_status_row(row, policy.entity_type)
        if projected_row is None:
            return rows
        projected.append(projected_row)
    return projected


def _status_result_from_read_rows(
    rows: list[dict[str, Any]],
    *,
    operation_id: str | None,
    session: Any,
) -> dict[str, Any] | None:
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    intent_probe = f"{_trimmed(getattr(session, 'current_intent', None))} {_trimmed(row.get('tool_name'))}"
    read_scope = _read_scope_for_request(session)
    if read_scope not in {READ_SCOPE_STATUS_ONLY, READ_SCOPE_DETAILS} and not _STATUS_INTENT_RE.search(intent_probe):
        return None
    primary_status = _status_primary_value(row)
    if not primary_status:
        return None
    entity_type = _status_entity_type(row)
    entity_id = _status_entity_id(row, entity_type)
    if not entity_id:
        return None

    entity_label = entity_type.capitalize()
    summary = f"{entity_label} {entity_id} is {primary_status}."
    fields = _status_visible_fields(row, entity_type)
    visible_key_tokens = _status_visible_key_tokens(row, entity_type, fields)
    secondary_fields = _status_secondary_fields(
        row,
        visible_keys=visible_key_tokens,
        include=read_scope == READ_SCOPE_DETAILS,
    )
    return {
        "contract": ENTITY_STATUS_CONTRACT,
        "operation_id": operation_id,
        "title": f"{entity_label} status",
        "summary": summary,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "primary_status": primary_status,
        "fields": fields,
        "secondary_fields": secondary_fields,
        "read_scope": read_scope,
        "requested_fields": _status_requested_fields(row, entity_type, read_scope),
        "display_mode": (
            DISPLAY_MODE_DETAIL_STATUS_CARD
            if read_scope == READ_SCOPE_DETAILS
            else DISPLAY_MODE_COMPACT_STATUS_CARD
        ),
        "entity_count": 1,
        "preview_limit": READ_DISPLAY_PREVIEW_LIMIT,
        "details_collapsed": True,
    }


def _is_non_terminal_progress_presentation(*, presentation: PresentationResponse, state: str) -> bool:
    diagnostics = presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {}
    return (
        presentation.kind == "diagnostic"
        and state in {"running", "waiting_confirmation"}
        and _trimmed(diagnostics.get("reason")) == "non_terminal_snapshot"
    )


def _stateful_activity_fallback(
    *,
    activity_steps: list[ActivityStepResponse],
    operation_id: str | None,
    latest_pending: ApprovalResponse | None,
) -> list[RunStep]:
    run_steps: list[RunStep] = []
    for step in activity_steps:
        state = str(step.state or "")
        if state == "running":
            step_state = "current"
        elif state == "waiting":
            step_state = "waiting"
        elif state in {"success", "complete"}:
            step_state = "completed"
        elif state == "error":
            step_state = "failed"
        else:
            step_state = "pending"
        group = str(step.group or "")
        if group == "planning":
            kind = "analysis"
        elif group == "approval":
            kind = "approval"
        elif group == "response":
            kind = "completed"
        elif group == "system":
            kind = "diagnostic"
        else:
            kind = "mutation" if "updating" in str(step.label or "").lower() else "read"
        run_steps.append(
            RunStep(
                step_id=step.id,
                kind=kind,  # type: ignore[arg-type]
                state=step_state,  # type: ignore[arg-type]
                title=step.label,
                summary=step.detail,
                approval_id=latest_pending.approval_id if latest_pending and kind == "approval" and step_state == "waiting" else None,
                operation_id=operation_id,
                current=step_state in {"current", "waiting"},
            )
        )
    return run_steps


def _read_evidence_entity(item: ReadEvidence) -> str | None:
    tool_name = _trimmed(item.tool_name).lower()
    match = re.match(r"^(?:get|list|search|read)__([a-z0-9_-]+)", tool_name)
    if not match:
        return None
    head = match.group(1).split("_", 1)[0].split("{", 1)[0].replace("-", "_")
    if head.endswith("ies") and len(head) > 3:
        return head[:-3] + "y"
    if head.endswith("s") and len(head) > 1:
        return head[:-1]
    return head or None


def _read_evidence_title(item: ReadEvidence) -> str:
    rows = [row for row in item.rows if isinstance(row, dict)]
    entity = _read_evidence_entity(item)
    fields = parse_fields_arg(item.args.get("fields") if isinstance(item.args, dict) else None)
    wants_status = "status" in fields or (
        not fields and rows and all(_status_primary_value(row) for row in rows)
    )
    if rows and len(rows) == 1 and wants_status:
        return f"Read {_human_status_label(entity or 'record').lower()} status"
    if entity:
        return f"Read {len(rows)} {_entity_noun(entity, len(rows))}"
    return f"Read {len(rows)} {_plural(len(rows), 'record')}"


def _read_evidence_collection_summary(item: ReadEvidence, *, rows: list[dict[str, Any]]) -> str:
    count = len(rows)
    entity = _read_evidence_entity(item)
    noun = _entity_noun(entity, count) if entity else _plural(count, "record")
    args = item.args if isinstance(item.args, dict) else {}
    priority = _trimmed(args.get("priority")).lower()
    status_filter = _trimmed(args.get("status")).lower()
    descriptor = ""
    if priority:
        descriptor = f"{priority}-priority "
    elif status_filter:
        descriptor = f"{status_filter} "
    sort_fields = _sort_fields_from_args(args)
    sort_suffix = f" sorted by {_human_status_label(sort_fields[0]).lower()}" if sort_fields else ""
    if count <= 0:
        return f"No matching {descriptor}{noun} were found."
    if _read_rows_include_business_rule(rows):
        return f"Rule Applied: found {count} {descriptor}{noun}{sort_suffix}."
    return f"Found {count} {descriptor}{noun}{sort_suffix}."


def _read_rows_include_business_rule(rows: list[dict[str, Any]]) -> bool:
    return any(
        _trimmed(row.get("rule") or row.get("business_rule") or row.get("rule_result"))
        for row in rows
        if isinstance(row, dict)
    )


def _read_evidence_summary_for_mixed_read(item: ReadEvidence, *, session: Any) -> str | None:
    rows = [row for row in item.rows if isinstance(row, dict) and not _is_empty_result_envelope(row)]
    if not rows:
        return None
    requested_fields = parse_fields_arg(item.args.get("fields") if isinstance(item.args, dict) else None)
    entity_type = _read_evidence_entity(item)
    status_like = _read_evidence_is_status_only(
        rows=rows,
        requested_fields=requested_fields,
        entity_type=entity_type,
        session=session,
    )
    if status_like and len(rows) == 1:
        status_result = _status_result_from_read_rows(
            rows,
            operation_id=item.operation_id,
            session=session,
        )
        if status_result:
            return _trimmed(status_result.get("summary")) or None
    return _read_evidence_collection_summary(item, rows=rows)


def _mixed_read_summary(read_evidence: list[ReadEvidence], *, session: Any) -> str | None:
    tool_read_evidence = [item for item in read_evidence if item.tool_name]
    read_step_ids = {
        step_id
        for item in tool_read_evidence
        for step_id in item.step_ids
    }
    if len(read_step_ids) <= 1:
        return None
    profiles: list[tuple[str | None, bool]] = []
    for item in tool_read_evidence:
        rows = [row for row in item.rows if isinstance(row, dict) and not _is_empty_result_envelope(row)]
        if not rows:
            continue
        requested_fields = parse_fields_arg(item.args.get("fields") if isinstance(item.args, dict) else None)
        entity_type = _read_evidence_entity(item)
        profiles.append(
            (
                entity_type,
                _read_evidence_is_status_only(
                    rows=rows,
                    requested_fields=requested_fields,
                    entity_type=entity_type,
                    session=session,
                ),
            )
        )
    if profiles and all(status_like for _entity, status_like in profiles):
        entity_types = {entity for entity, _status_like in profiles if entity}
        if len(entity_types) <= 1:
            return None
    summaries: list[str] = []
    for item in tool_read_evidence:
        summary = _read_evidence_summary_for_mixed_read(item, session=session)
        if summary:
            summaries.append(summary.rstrip("."))
    if len(summaries) <= 1:
        return None
    return ". ".join(summaries) + "."


def _compose_run_steps(
    *,
    document_id: str,
    operation_id: str | None,
    state: str,
    approvals: list[ApprovalResponse],
    latest_pending: ApprovalResponse | None,
    mutation_groups: list[MutationGroup],
    read_evidence: list[ReadEvidence],
    sources: list[dict[str, Any]],
    status_result: dict[str, Any] | None,
    read_policy: ReadDisplayPolicy | None,
    presentation: PresentationResponse,
    timeline: list[TimelineEventResponse],
    activity_steps: list[ActivityStepResponse],
    session: Any,
    failure_profile: FailureProfile | None,
) -> list[RunStep]:
    run_steps: list[RunStep] = []
    non_terminal_progress = _is_non_terminal_progress_presentation(presentation=presentation, state=state)
    has_request_evidence = bool(timeline or approvals or mutation_groups or read_evidence or sources)
    if has_request_evidence:
        run_steps.append(
            RunStep(
                step_id=f"analysis:{operation_id or document_id}",
                kind="analysis",
                state="completed",
                title="Understood request",
                summary=_trimmed(getattr(session, "current_intent", None)) or None,
                operation_id=operation_id,
            )
        )

    groups_by_approval = {group.approval_id: group for group in mutation_groups if group.approval_id}
    approval_positions = _approval_position_by_id(approvals)
    emitted_no_op_keys: set[str] = set()
    for group in mutation_groups:
        if not _is_no_op_group(group):
            continue
        emitted_no_op_keys.add(group.key)
        run_steps.append(
            RunStep(
                step_id=f"mutation:{group.key}",
                kind="mutation",
                state="completed",
                title="Not changed",
                summary=_mutation_group_summary(group),
                operation_id=group.operation_id or operation_id,
                record_count=_mutation_group_record_count(group),
                diagnostics={
                    "entity_type": group.entity_type,
                    "selector_summary": group.selector_summary,
                    "change_summary": group.change_summary,
                    "matched_count": int(group.matched_count or 0),
                    "changed_count": int(group.changed_count or 0),
                    "status": group.status,
                    "reason": group.reason or NO_OP_MUTATION_REASON,
                },
            )
        )
    for approval in sorted(approvals, key=lambda row: (row.created_at, row.approval_id)):
        approval_index = approval_positions.get(approval.approval_id, 1)
        approval_status = str(approval.status or "").upper()
        group = groups_by_approval.get(approval.approval_id)
        approved_with_result = approval_status in {"APPROVED", "ACCEPTED"} and group is not None
        expired = _approval_is_expired(approval)
        row_status = "pending"
        if approval_status in {"APPROVED", "ACCEPTED"}:
            row_status = "succeeded"
        elif approval_status == "REJECTED":
            row_status = "rejected"
        elif expired:
            row_status = "expired"
        rows = _approval_rows(approval, operation_id=operation_id, default_status=row_status)
        if approved_with_result:
            approval_summary = _mutation_group_summary(group)
        elif approval_status in {"APPROVED", "ACCEPTED"}:
            record_text = f" for {len(rows)} {_plural(len(rows), 'record')}" if rows else ""
            approval_summary = f"Approval {approval_index} was received{record_text}."
        else:
            approval_summary = _pending_approval_summary(approval, rows)
        if rows:
            run_steps.append(
                RunStep(
                    step_id=f"read:{approval.approval_id}",
                    kind="read",
                    state="completed",
                    title=f"Found {len(rows)} {_plural(len(rows), 'record')}",
                    summary=approval_summary,
                    approval_id=approval.approval_id,
                    operation_id=_approval_operation_id(approval, operation_id),
                    record_count=len(rows),
                )
            )

        if latest_pending and approval.approval_id == latest_pending.approval_id:
            approval_state = "waiting"
            title = f"Waiting for approval {approval_index}"
            current = True
        elif approval_status in {"APPROVED", "ACCEPTED"}:
            approval_state = "completed"
            title = f"Approval {approval_index} received"
            current = False
        elif approval_status == "REJECTED":
            approval_state = "rejected"
            title = f"Approval {approval_index} rejected"
            current = False
        elif expired:
            approval_state = "expired"
            title = f"Approval {approval_index} expired"
            current = False
        else:
            approval_state = "pending"
            title = f"Approval {approval_index} pending"
            current = False
        run_steps.append(
            RunStep(
                step_id=f"approval:{approval.approval_id}",
                kind="approval",
                state=approval_state,  # type: ignore[arg-type]
                title=title,
                summary=approval_summary,
                approval_id=approval.approval_id,
                operation_id=_approval_operation_id(approval, operation_id),
                record_count=len(rows) if rows else None,
                current=current,
            )
        )

        if group is not None:
            mutation_state = "failed" if group.status == "failed" else "completed"
            run_steps.append(
                RunStep(
                    step_id=f"mutation:{group.approval_id or group.key}",
                    kind="mutation",
                    state=mutation_state,  # type: ignore[arg-type]
                    title=f"Updated {len(group.rows)} {_plural(len(group.rows), 'record')}",
                    summary=_mutation_group_summary(group),
                    approval_id=group.approval_id,
                    operation_id=group.operation_id or operation_id,
                    record_count=len(group.rows),
                )
            )

    latest = _latest_approval(approvals)
    session_status = str(getattr(session, "status", "") or "").upper()
    if latest and not latest_pending and str(latest.status or "").upper() in {"APPROVED", "ACCEPTED"}:
        if latest.approval_id not in groups_by_approval and session_status in {"EXECUTING", "PLANNING"}:
            run_steps.append(
                RunStep(
                    step_id=f"mutation:{latest.approval_id}",
                    kind="mutation",
                    state="current",
                    title="Applying approved change",
                    summary="Approval was received; applying the approved mutation.",
                    approval_id=latest.approval_id,
                    operation_id=_approval_operation_id(latest, operation_id),
                    current=True,
                )
            )

    for group in mutation_groups:
        if group.approval_id or group.key in emitted_no_op_keys:
            continue
        run_steps.append(
            RunStep(
                step_id=f"mutation:{group.key}",
                kind="mutation",
                state="failed" if group.status == "failed" else "completed",
                title=f"Updated {len(group.rows)} {_plural(len(group.rows), 'record')}",
                summary=_mutation_group_summary(group),
                operation_id=group.operation_id or operation_id,
                record_count=len(group.rows),
            )
        )

    read_step_ids = {
        step_id
        for item in read_evidence
        if item.tool_name
        for step_id in item.step_ids
    }
    if not approvals and read_evidence and len(read_step_ids) > 1:
        tool_read_evidence = [item for item in read_evidence if item.tool_name]
        for index, item in enumerate(tool_read_evidence):
            rows = [row for row in item.rows if isinstance(row, dict)]
            requested_fields = parse_fields_arg(item.args.get("fields") if isinstance(item.args, dict) else None)
            status_like = rows and _status_rows_are_projectable(rows) and (
                "status" in requested_fields or _STATUS_INTENT_RE.search(_trimmed(getattr(session, "current_intent", None)))
            )
            row_policy = ReadDisplayPolicy(
                read_scope=READ_SCOPE_STATUS_ONLY if status_like else READ_SCOPE_RECORDS,
                requested_fields=requested_fields or (
                    _status_requested_fields(rows[0], _status_entity_type(rows[0]), READ_SCOPE_STATUS_ONLY)
                    if status_like
                    else []
                ),
                display_mode=DISPLAY_MODE_RECORD_PREVIEW if len(rows) <= 1 else DISPLAY_MODE_COLLECTION_TABLE,
                entity_count=len(rows),
                entity_type=_read_evidence_entity(item),
                contract=ENTITY_STATUS_CONTRACT if status_like else None,
                sort_fields=_sort_fields_from_args(item.args),
            )
            run_steps.append(
                RunStep(
                    step_id=f"{item.key or 'read'}:{index}",
                    kind="read",
                    state="completed",
                    title=_read_evidence_title(item),
                    summary=_read_policy_summary(rows, row_policy, presentation.summary),
                    operation_id=item.operation_id or operation_id,
                    record_count=len(rows),
                )
            )
    elif not approvals and read_evidence:
        total_rows = sum(len(item.rows) for item in read_evidence)
        read_rows = [row for item in read_evidence for row in item.rows]
        run_steps.append(
            RunStep(
                step_id=f"read:{operation_id or document_id}",
                kind="read",
                state="completed",
                title=(
                    f"Read {status_result['entity_type']} status"
                    if status_result and status_result.get("entity_type")
                    else f"Read {_human_status_label(read_policy.entity_type).lower()} statuses"
                    if read_policy and read_policy.contract == ENTITY_STATUS_CONTRACT and read_policy.entity_type
                    else f"Read {total_rows} {_plural(total_rows, 'record')}"
                ),
                summary=(
                    status_result.get("summary")
                    if status_result
                    else _read_policy_summary(read_rows, read_policy, presentation.summary)
                ),
                operation_id=operation_id,
                record_count=total_rows,
            )
        )

    knowledge_answer_text = _knowledge_answer_text_for_sources(presentation.summary, sources) if sources else ""
    if sources:
        insufficient_context = is_insufficient_context_answer(knowledge_answer_text)
        run_steps.append(
            RunStep(
                step_id=f"knowledge:{operation_id or document_id}",
                kind="knowledge",
                state="completed",
                title="Checked related sources" if insufficient_context else "Prepared sourced answer",
                summary=(
                    f"{len(sources)} related {_plural(len(sources), 'source')} checked."
                    if insufficient_context
                    else f"{len(sources)} {_plural(len(sources), 'source')} attached."
                ),
                operation_id=operation_id,
                record_count=len(sources),
            )
        )

    if presentation.kind in {"diagnostic", "cancelled", "rejected", "expired", "partial_failure"} and not non_terminal_progress:
        diagnostic_state = state if state in {"failed", "rejected", "expired", "cancelled"} else "failed"
        run_steps.append(
            RunStep(
                step_id=f"diagnostic:{failure_profile.reason if failure_profile else operation_id or document_id}",
                kind="diagnostic" if presentation.kind != "cancelled" else "cancelled",
                state=diagnostic_state,  # type: ignore[arg-type]
                title=(
                    failure_profile.title
                    if failure_profile
                    else "Needs attention"
                    if presentation.kind == "diagnostic"
                    else presentation.kind.title()
                ),
                summary=(failure_profile.user_message if failure_profile else _trimmed(presentation.summary) or None),
                operation_id=operation_id,
                current=state in {"failed", "blocked"},
                diagnostics=failure_profile.technical_details if failure_profile else _sanitize_diagnostic_value(
                    presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {}
                ),
            )
        )

    if state == "completed" and not latest_pending:
        if mutation_groups:
            completion_summary = _visible_mutation_summary(mutation_groups, fallback_summary=presentation.summary)
        elif status_result:
            completion_summary = _trimmed(status_result.get("summary")) or None
        elif read_evidence:
            read_rows = [row for item in read_evidence for row in item.rows]
            completion_summary = _mixed_read_summary(read_evidence, session=session) or _read_policy_summary(read_rows, read_policy, presentation.summary)
        elif sources:
            completion_summary = "Source-backed answer is ready."
        else:
            completion_summary = _trimmed(presentation.summary) or None
        run_steps.append(
            RunStep(
                step_id=f"completed:{operation_id or document_id}",
                kind="completed",
                state="completed",
                title="Run complete",
                summary=completion_summary,
                operation_id=operation_id,
            )
        )

    if not run_steps:
        if non_terminal_progress:
            return [
                RunStep(
                    step_id=f"analysis:{operation_id or document_id}",
                    kind="analysis",
                    state="current",
                    title="Working on request",
                    summary="The backend is preparing the next state.",
                    operation_id=operation_id,
                    current=True,
                )
            ]
        return _stateful_activity_fallback(
            activity_steps=activity_steps,
            operation_id=operation_id,
            latest_pending=latest_pending,
        )
    return run_steps


def _current_response_step_id(run_steps: list[RunStep]) -> str | None:
    current = next((step for step in reversed(run_steps) if step.current), None)
    if current is not None:
        return current.step_id
    return run_steps[-1].step_id if run_steps else None


def _safe_operator_summary(value: str | None) -> str | None:
    text = _strip_footnote_markup(_trimmed(value))
    if not text or len(text) > 1200:
        return None
    text = re.sub(r"(?is)^\s*\*\*(?:success|failed|failure|result)\*\*\s*", "", text).strip()
    if "\n" in text:
        kept_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            if lowered.startswith("please approve") or lowered.startswith("waiting for your approval"):
                continue
            kept_lines.append(line)
        text = "\n".join(kept_lines).strip()
        if not text:
            return None
    lower = text.lower()
    if (
        lower.startswith("done_all")
        or "**" in text
        or "operation id:" in lower
        or "step id:" in lower
        or "row id:" in lower
        or lower in {"the backend operation completed.", "mutation completed.", "execution completed successfully."}
    ):
        return None
    if text[:1] in {"{", "["}:
        try:
            json.loads(text)
            return None
        except Exception:
            pass
    if _SENSITIVE_VALUE_RE.search(text) or _BEARER_RE.search(text) or _STACK_TRACE_RE.search(text):
        return None
    return text


def _user_facing_failure_summary(value: str | None) -> str | None:
    text = _safe_operator_summary(value)
    if not text or not _USER_FACING_FAILURE_RE.search(text):
        return None
    if _HTTP_STATUS_RE.search(text) and "please retry" not in text.lower():
        return None
    return text


def _visible_mutation_summary(groups: list[MutationGroup], *, fallback_summary: str | None = None) -> str:
    generated = _aggregate_mutation_summary(groups, fallback_summary=fallback_summary)
    changed_groups = [group for group in groups if not _is_no_op_group(group)]
    if changed_groups and all(_group_has_business_change_contract(group) for group in changed_groups):
        fallback = _safe_operator_summary(fallback_summary)
        if fallback and fallback != generated and _is_concise_operator_note(fallback):
            return f"{generated} {fallback}"
        return generated
    fallback = _safe_operator_summary(fallback_summary)
    if fallback and fallback != generated:
        return fallback
    return generated


def _is_concise_operator_note(value: str) -> bool:
    text = _trimmed(value)
    if not text or len(text) > 420:
        return False
    sentence_count = len([part for part in re.split(r"[.!?]+", text) if part.strip()])
    return sentence_count <= 3


def _aggregate_mutation_summary(groups: list[MutationGroup], *, fallback_summary: str | None = None) -> str:
    fallback = _trimmed(fallback_summary)
    if fallback and "exactly once" in fallback.lower():
        return fallback
    changed_groups = [group for group in groups if not _is_no_op_group(group)]
    no_op_groups = [group for group in groups if _is_no_op_group(group)]
    if no_op_groups and not changed_groups:
        return "No changes were made."

    total = sum(len(group.rows) for group in changed_groups)
    change_count = len(changed_groups)
    noun = _mutation_total_noun(changed_groups)
    no_op_suffix = ""
    if no_op_groups:
        no_op_count = len(no_op_groups)
        no_op_suffix = (
            f" {no_op_count} {_plural(no_op_count, 'business change')} not changed "
            "because no matching records were found."
        )
    if changed_groups and all(group.status == "completed" for group in changed_groups):
        return (
            f"Done. I updated {total} {noun} across {change_count} "
            f"{_plural(change_count, 'approved business change')}.{no_op_suffix}"
        )
    succeeded = sum(_row_status_counts(group.rows).get("succeeded", 0) for group in changed_groups)
    failed = sum(_row_status_counts(group.rows).get("failed", 0) for group in changed_groups)
    if succeeded and failed:
        return (
            f"{succeeded} of {total} {noun} updated across {change_count} "
            f"{_plural(change_count, 'approved business change')}; {failed} failed.{no_op_suffix}"
        )
    if failed and not succeeded:
        return f"{total} {noun} failed across {change_count} {_plural(change_count, 'approved business change')}.{no_op_suffix}"
    return f"Updated {total} {noun} across {change_count} {_plural(change_count, 'approved business change')}.{no_op_suffix}"


def _aggregate_step_payloads(groups: list[MutationGroup]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        payload = {
            "step_number": index,
            "business_change": _business_change_label(group, index=index),
            "summary": _business_change_summary(group, index=index),
            "record_count": _mutation_group_record_count(group),
            "status": group.status,
        }
        payload.update(_business_change_contract_payload(group, index=index))
        if _is_no_op_group(group):
            payload.update(
                {
                    "contract": NO_OP_MUTATION_CONTRACT,
                    "entity_type": group.entity_type,
                    "selector_summary": group.selector_summary,
                    "change_summary": group.change_summary,
                    "matched_count": int(group.matched_count or 0),
                    "changed_count": int(group.changed_count or 0),
                    "reason": group.reason or NO_OP_MUTATION_REASON,
                }
            )
        payloads.append(payload)
    return payloads


def _mutation_business_contract(groups: list[MutationGroup], *, state: str, latest_pending: ApprovalResponse | None) -> str | None:
    if not groups or state != "completed" or latest_pending is not None:
        return None
    changed_groups = [group for group in groups if not _is_no_op_group(group)]
    if changed_groups and all(_group_has_business_change_contract(group) for group in changed_groups):
        return BUSINESS_CHANGE_CONTRACT
    return "business_level_v1"


def _short_message(
    *,
    state: str,
    latest_pending: ApprovalResponse | None,
    approvals: list[ApprovalResponse],
    mutation_groups: list[MutationGroup],
    read_evidence: list[ReadEvidence],
    read_rows: list[dict[str, Any]],
    status_result: dict[str, Any] | None,
    read_policy: ReadDisplayPolicy | None,
    sources: list[dict[str, Any]],
    presentation: PresentationResponse,
    session: Any,
    failure_profile: FailureProfile | None,
) -> str:
    if failure_profile is not None:
        return failure_profile.user_message

    if latest_pending is not None:
        pending_rows = _approval_rows(latest_pending, operation_id=presentation.operation_id, default_status="pending")
        pending_text = _pending_approval_summary(latest_pending, pending_rows)
        if mutation_groups:
            completed = "; ".join(_mutation_group_summary(group).rstrip(".") for group in mutation_groups)
            return f"Done. {completed}. {pending_text}"
        return pending_text

    latest = _latest_approval(approvals)
    session_status = str(getattr(session, "status", "") or "").upper()
    if latest and str(latest.status or "").upper() in {"APPROVED", "ACCEPTED"} and session_status in {"EXECUTING", "PLANNING"}:
        latest_group = next((group for group in mutation_groups if group.approval_id == latest.approval_id), None)
        if latest_group is None:
            return "Approval received. I'm applying the approved change now."

    if mutation_groups and state == "completed":
        return _aggregate_mutation_summary(mutation_groups)

    if presentation.kind == "partial_failure":
        return _trimmed(presentation.summary) or "Some rows failed while others succeeded."

    if sources:
        knowledge_answer_text = _knowledge_answer_text_for_sources(presentation.summary, sources)
        if is_insufficient_context_answer(knowledge_answer_text):
            clean_summary = _strip_footnote_markup(knowledge_answer_text)
            if clean_summary:
                return clean_summary.split(" The related sources checked", 1)[0].rstrip(".") + "."
            return "I do not have enough retrieved evidence to answer that safely."
        return "I found a source-backed answer."

    if status_result:
        return _trimmed(status_result.get("summary")) or "Status is ready."

    mixed_summary = _mixed_read_summary(read_evidence, session=session)
    if mixed_summary:
        return mixed_summary

    if read_rows:
        return _read_policy_summary(read_rows, read_policy, presentation.summary)

    if presentation.kind == "answer" and state == "completed":
        return _trimmed(presentation.summary) or "No matching records were found."

    if _is_non_terminal_progress_presentation(presentation=presentation, state=state):
        if state == "waiting_confirmation":
            return _trimmed(presentation.summary) or "Please confirm the next step before I continue."
        return _trimmed(presentation.summary) or "I'm working on the request and waiting for the next backend update."

    return _trimmed(presentation.summary) or "The request needs attention before it can continue."


def _diagnostic_severity(state: str, *, info: bool = False) -> str:
    if info:
        return "info"
    if state in {"failed", "blocked", "rejected", "expired", "cancelled"}:
        return "error"
    if state == "running":
        return "info"
    return "warning"


def _stable_block_anchor(*, document_id: str, operation_id: str | None, approval_id: str | None) -> str:
    return approval_id or operation_id or document_id


def _record_blocks_for_rows(
    *,
    id_prefix: str,
    operation_id: str | None,
    approval_id: str | None,
    rows: list[dict[str, Any]],
    title: str,
    policy: ReadDisplayPolicy | None = None,
) -> list[ResponseBlock]:
    if not rows:
        return []
    preview_limit = policy.preview_limit if policy else READ_DISPLAY_PREVIEW_LIMIT
    details_collapsed = policy.details_collapsed if policy else True
    read_scope = policy.read_scope if policy else None
    requested_fields = policy.requested_fields if policy else []
    display_mode = policy.display_mode if policy else None
    entity_type = policy.entity_type if policy else None
    entity_count = policy.entity_count if policy else len(rows)
    contract = policy.contract if policy else None
    shape = _read_result_shape(rows)
    if (
        policy
        and policy.entity_count > 1
        and policy.display_mode in {DISPLAY_MODE_COLLECTION_TABLE, DISPLAY_MODE_COLLAPSED_COLLECTION_TABLE}
    ):
        shape = "table"
    if shape == "table":
        return [
            ResultTableBlock(
                id=f"table:{id_prefix}",
                contract=contract,
                title=title,
                rows=rows,
                operation_id=operation_id,
                approval_id=approval_id,
                read_scope=read_scope,
                requested_fields=requested_fields,
                display_mode=display_mode,
                entity_type=entity_type,
                entity_count=entity_count,
                preview_limit=preview_limit,
                details_collapsed=details_collapsed,
            )
        ]
    return [
        RecordPreviewBlock(
            id=f"record-preview:{id_prefix}",
            contract=contract,
            title=title,
            rows=rows,
            operation_id=operation_id,
            approval_id=approval_id,
            read_scope=read_scope,
            requested_fields=requested_fields,
            display_mode=display_mode,
            entity_type=entity_type,
            entity_count=entity_count,
            preview_limit=preview_limit,
            details_collapsed=details_collapsed,
        )
    ]


def _read_evidence_is_status_only(
    *,
    rows: list[dict[str, Any]],
    requested_fields: list[str],
    entity_type: str | None,
    session: Any,
) -> bool:
    if not rows or not _status_rows_are_projectable(rows):
        return False
    if not requested_fields:
        return bool(_STATUS_INTENT_RE.search(_trimmed(getattr(session, "current_intent", None))))
    requested = {_canonical_requested_field_key(field) for field in requested_fields}
    identity_fields = {_canonical_requested_field_key("id")}
    if entity_type:
        identity_fields.add(_canonical_requested_field_key(f"{entity_type}_id"))
    return "status" in requested and requested <= {*identity_fields, "status"}


def _read_blocks_for_evidence_groups(
    *,
    read_evidence: list[ReadEvidence],
    session: Any,
    operation_id: str | None,
    document_id: str,
) -> list[ResponseBlock]:
    blocks: list[ResponseBlock] = []
    tool_read_evidence = [item for item in read_evidence if item.tool_name]
    read_step_ids = {
        step_id
        for item in tool_read_evidence
        for step_id in item.step_ids
    }
    if len(read_step_ids) <= 1:
        return blocks

    profiles: list[tuple[str | None, bool]] = []
    for item in tool_read_evidence:
        rows = [row for row in item.rows if isinstance(row, dict) and not _is_empty_result_envelope(row)]
        if not rows:
            continue
        requested_fields = parse_fields_arg(item.args.get("fields") if isinstance(item.args, dict) else None)
        entity_type = _read_evidence_entity(item)
        profiles.append(
            (
                entity_type,
                _read_evidence_is_status_only(
                    rows=rows,
                    requested_fields=requested_fields,
                    entity_type=entity_type,
                    session=session,
                ),
            )
        )
    if profiles and all(status_like for _entity, status_like in profiles):
        entity_types = {entity for entity, _status_like in profiles if entity}
        if len(entity_types) <= 1:
            return blocks

    for index, item in enumerate(tool_read_evidence):
        rows = [row for row in item.rows if isinstance(row, dict) and not _is_empty_result_envelope(row)]
        if not rows:
            continue
        requested_fields = parse_fields_arg(item.args.get("fields") if isinstance(item.args, dict) else None)
        entity_type = _read_evidence_entity(item)
        status_like = _read_evidence_is_status_only(
            rows=rows,
            requested_fields=requested_fields,
            entity_type=entity_type,
            session=session,
        )
        if status_like and len(rows) == 1:
            status_result = _status_result_from_read_rows(
                rows,
                operation_id=item.operation_id or operation_id,
                session=session,
            )
            if status_result:
                blocks.append(
                    StatusResultBlock(
                        id=f"status:{operation_id or document_id}:{index}",
                        contract=ENTITY_STATUS_CONTRACT,
                        operation_id=status_result.get("operation_id") or item.operation_id or operation_id,
                        title=_trimmed(status_result.get("title")) or "Status",
                        summary=_trimmed(status_result.get("summary")) or None,
                        entity_type=_trimmed(status_result.get("entity_type")) or None,
                        entity_id=_trimmed(status_result.get("entity_id")) or None,
                        primary_status=_trimmed(status_result.get("primary_status")) or None,
                        fields=status_result.get("fields") if isinstance(status_result.get("fields"), list) else [],
                        secondary_fields=(
                            status_result.get("secondary_fields")
                            if isinstance(status_result.get("secondary_fields"), list)
                            else []
                        ),
                        read_scope=_trimmed(status_result.get("read_scope")) or None,
                        requested_fields=(
                            status_result.get("requested_fields")
                            if isinstance(status_result.get("requested_fields"), list)
                            else []
                        ),
                        display_mode=_trimmed(status_result.get("display_mode")) or None,
                        entity_count=int(status_result.get("entity_count") or 1),
                        preview_limit=int(status_result.get("preview_limit") or READ_DISPLAY_PREVIEW_LIMIT),
                        details_collapsed=bool(status_result.get("details_collapsed", True)),
                    )
                )
                continue

        policy = ReadDisplayPolicy(
            read_scope=READ_SCOPE_STATUS_ONLY if status_like else READ_SCOPE_RECORDS,
            requested_fields=requested_fields or (
                _status_requested_fields(rows[0], _status_entity_type(rows[0]), READ_SCOPE_STATUS_ONLY)
                if status_like
                else []
            ),
            display_mode=(
                DISPLAY_MODE_COLLECTION_TABLE
                if len(rows) > 1
                else DISPLAY_MODE_RECORD_PREVIEW
            ),
            entity_count=len(rows),
            entity_type=entity_type,
            contract=ENTITY_STATUS_CONTRACT if status_like else None,
            details_collapsed=False,
            sort_fields=_sort_fields_from_args(item.args),
        )
        projected_rows = _project_read_rows_for_policy(rows, policy)
        blocks.extend(
            _record_blocks_for_rows(
                id_prefix=f"{operation_id or document_id}:read-results:{index}",
                operation_id=item.operation_id or operation_id,
                approval_id=None,
                rows=projected_rows,
                title=_read_evidence_title(item),
                policy=policy,
            )
        )
    return blocks


def _compose_blocks(
    *,
    document_id: str,
    operation_id: str | None,
    session: Any,
    state: str,
    message: str,
    safety_content: str | None,
    run_steps: list[RunStep],
    latest_pending: ApprovalResponse | None,
    approvals: list[ApprovalResponse],
    mutation_groups: list[MutationGroup],
    read_evidence: list[ReadEvidence],
    read_rows: list[dict[str, Any]],
    has_read_evidence: bool,
    status_result: dict[str, Any] | None,
    read_policy: ReadDisplayPolicy | None,
    sources: list[dict[str, Any]],
    presentation: PresentationResponse,
    failure_profile: FailureProfile | None,
) -> list[ResponseBlock]:
    blocks: list[ResponseBlock] = []
    knowledge_blocks: list[ResponseBlock] = []
    if run_steps:
        blocks.append(RunActivityBlock(id=f"activity:{document_id}", step_ids=[step.step_id for step in run_steps]))

    anchor = _stable_block_anchor(
        document_id=document_id,
        operation_id=operation_id,
        approval_id=latest_pending.approval_id if latest_pending else presentation.approval_id,
    )
    if message:
        blocks.append(
            ShortMessageBlock(
                id=f"message:{anchor}:{state}",
                message=message,
                status=state,  # type: ignore[arg-type]
            )
        )

    show_completed_step_blocks = latest_pending is not None or state != "completed" or any(
        group.status in {"failed", "partial_failure"} for group in mutation_groups
    )
    if show_completed_step_blocks:
        for group in mutation_groups:
            blocks.append(
                CompletedStepBlock(
                    id=f"completed-step:{group.approval_id or group.key}",
                    step_id=group.step_ids[0] if group.step_ids else None,
                    operation_id=group.operation_id or operation_id,
                    approval_id=group.approval_id,
                    title="Completed step",
                    summary=_mutation_group_summary(group),
                    rows=group.rows,
                )
            )

    if latest_pending is not None:
        pending_rows = _approval_rows(latest_pending, operation_id=operation_id, default_status="pending")
        pending_summary = _pending_approval_summary(latest_pending, pending_rows)
        pending_contract = _approval_contract(latest_pending, pending_rows)
        blocks.append(
            ApprovalRequiredBlock(
                id=f"approval:{latest_pending.approval_id}",
                contract=pending_contract,
                approval_id=latest_pending.approval_id,
                operation_id=_approval_operation_id(latest_pending, operation_id),
                args=_approval_action_args(latest_pending.args),
                summary=pending_summary,
                rows=pending_rows,
            )
        )
        if pending_rows:
            blocks.append(
                RecordPreviewBlock(
                    id=f"record-preview:{latest_pending.approval_id}:pending",
                    contract=pending_contract,
                    title="Affected records",
                    rows=pending_rows[:5],
                    operation_id=_approval_operation_id(latest_pending, operation_id),
                    approval_id=latest_pending.approval_id,
                )
            )
            blocks.append(
                ResultTableBlock(
                    id=f"table:{latest_pending.approval_id}:affected-records",
                    contract=pending_contract,
                    title="Affected records",
                    rows=pending_rows,
                    operation_id=_approval_operation_id(latest_pending, operation_id),
                    approval_id=latest_pending.approval_id,
                )
            )
        return blocks

    if mutation_groups:
        all_rows = [row for group in mutation_groups for row in group.rows]
        summary = _visible_mutation_summary(mutation_groups, fallback_summary=presentation.summary)
        all_no_op = all(_is_no_op_group(group) for group in mutation_groups)
        status = "partial_failure" if any(group.status == "partial_failure" for group in mutation_groups) else "completed"
        if any(group.status == "failed" for group in mutation_groups) and not any(group.status == "completed" for group in mutation_groups):
            status = "failed"
        changed_groups = [group for group in mutation_groups if not _is_no_op_group(group)]
        all_changed_groups_are_typed = bool(changed_groups) and all(
            _group_has_business_change_contract(group) for group in changed_groups
        )
        business_groups, business_rows = _mutation_business_payloads(mutation_groups)
        result_rows = business_rows if status == "completed" else all_rows
        blocks.append(
            ResultSummaryBlock(
                id=f"result-summary:{operation_id or document_id}",
                operation_id=operation_id,
                title="No changes made" if all_no_op else "Changes completed" if status == "completed" else "Result summary",
                summary=summary,
                steps=_aggregate_step_payloads(mutation_groups),
                total_count=len(result_rows),
                status=status,  # type: ignore[arg-type]
            )
        )
        blocks.append(
            MutationResultBlock(
                id=f"mutation:{operation_id or anchor}",
                contract=BUSINESS_CHANGE_CONTRACT if all_changed_groups_are_typed else None,
                operation_id=operation_id,
                approval_id=presentation.approval_id,
                title="Not changed" if all_no_op else "Affected records" if status == "completed" else "Mutation result",
                summary=summary,
                rows=result_rows,
                groups=business_groups if status == "completed" else [],
                preview_limit=5,
                details_collapsed=True,
                status=status,  # type: ignore[arg-type]
            )
        )
        if all_rows and status != "completed":
            blocks.append(
                ResultTableBlock(
                    id=f"table:{operation_id or anchor}:affected-records",
                    title="Affected records",
                    rows=all_rows,
                    operation_id=operation_id,
                    approval_id=presentation.approval_id,
                )
            )

    if presentation.kind in {"answer", "knowledge_answer"}:
        safety_text = _strip_footnote_markup(safety_content)
        if safety_text:
            knowledge_blocks.append(
                SafetyNoticeBlock(
                    id=f"safety:{operation_id or document_id}",
                    contract=SAFETY_NOTICE_CONTRACT,
                    title="Safety notice",
                    safety_content=safety_text,
                    operation_id=operation_id,
                )
            )
    if presentation.kind == "knowledge_answer":
        answer, segments, citations = _knowledge_answer_payload(presentation.summary, sources)
        if answer:
            knowledge_blocks.append(
                KnowledgeAnswerBlock(
                    id=f"knowledge:{operation_id or document_id}",
                    contract=KNOWLEDGE_ANSWER_CONTRACT,
                    answer=answer,
                    operation_id=operation_id,
                    segments=segments,
                    citations=citations,
                )
            )

    grouped_read_blocks = (
        _read_blocks_for_evidence_groups(
            read_evidence=read_evidence,
            session=session,
            operation_id=operation_id,
            document_id=document_id,
        )
        if not mutation_groups
        else []
    )

    if grouped_read_blocks:
        blocks.extend(grouped_read_blocks)
    elif status_result and not mutation_groups:
        blocks.append(
            StatusResultBlock(
                id=f"status:{operation_id or document_id}",
                contract=ENTITY_STATUS_CONTRACT,
                operation_id=status_result.get("operation_id") or operation_id,
                title=_trimmed(status_result.get("title")) or "Status",
                summary=_trimmed(status_result.get("summary")) or message,
                entity_type=_trimmed(status_result.get("entity_type")) or None,
                entity_id=_trimmed(status_result.get("entity_id")) or None,
                primary_status=_trimmed(status_result.get("primary_status")) or None,
                fields=status_result.get("fields") if isinstance(status_result.get("fields"), list) else [],
                secondary_fields=(
                    status_result.get("secondary_fields")
                    if isinstance(status_result.get("secondary_fields"), list)
                    else []
                ),
                read_scope=_trimmed(status_result.get("read_scope")) or None,
                requested_fields=(
                    status_result.get("requested_fields")
                    if isinstance(status_result.get("requested_fields"), list)
                    else []
                ),
                display_mode=_trimmed(status_result.get("display_mode")) or None,
                entity_count=int(status_result.get("entity_count") or 1),
                preview_limit=int(status_result.get("preview_limit") or READ_DISPLAY_PREVIEW_LIMIT),
                details_collapsed=bool(status_result.get("details_collapsed", True)),
            )
        )
    elif read_rows and not mutation_groups:
        blocks.extend(
            _record_blocks_for_rows(
                id_prefix=f"{operation_id or document_id}:read-results",
                operation_id=operation_id,
                approval_id=None,
                rows=read_rows,
                title="Results",
                policy=read_policy,
            )
        )

    blocks.extend(knowledge_blocks)

    if sources:
        blocks.append(
            SourceListBlock(
                id=f"sources:{operation_id or document_id}",
                contract=SOURCE_LIST_CONTRACT,
                sources=sources,
                operation_id=operation_id,
            )
        )

    no_result = (
        presentation.kind == "answer"
        and has_read_evidence
        and not read_rows
        and not sources
        and state == "completed"
        and not mutation_groups
    )
    diagnostic_kind = (
        presentation.kind in {"diagnostic", "cancelled", "rejected", "expired", "partial_failure"}
        and not _is_non_terminal_progress_presentation(presentation=presentation, state=state)
    )
    if no_result or diagnostic_kind:
        diagnostics = _sanitize_diagnostic_value(presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {})
        reason = (
            failure_profile.reason
            if failure_profile
            else "no_results"
            if no_result
            else str(diagnostics.get("reason") or presentation.kind)
        )
        title = failure_profile.title if failure_profile else "No results" if no_result else "Needs attention"
        severity = failure_profile.severity if failure_profile else _diagnostic_severity(state, info=no_result)
        user_message = failure_profile.user_message if failure_profile else message
        blocks.append(
            DiagnosticBlock(
                id=f"diagnostic:{anchor}:{reason}",
                severity=severity,  # type: ignore[arg-type]
                reason=reason,
                title=title,
                user_message=user_message,
                cause=failure_profile.cause if failure_profile else None,
                impact=failure_profile.impact if failure_profile else {},
                current_state=failure_profile.current_state if failure_profile else None,
                next_action=failure_profile.next_action if failure_profile else None,
                next_actions=failure_profile.next_actions if failure_profile else [],
                retry_safety=failure_profile.retry_safety if failure_profile else {},
                technical_details=failure_profile.technical_details if failure_profile else diagnostics,
            )
        )

    return blocks


def compose_response_document(
    *,
    session: Any,
    plan: PlanResponse | None,
    steps: list[PlanStepResponse],
    pending_approval: ApprovalResponse | None,
    approvals: list[ApprovalResponse],
    timeline: list[TimelineEventResponse],
    activity_steps: list[ActivityStepResponse],
    presentation: PresentationResponse,
    cursor: int,
) -> ResponseDocument:
    session_id = str(getattr(session, "session_id", "") or "unknown-session")
    turn_id = _response_document_turn_id(timeline, session_id=session_id)
    operation_id = presentation.operation_id or (plan.plan_id if plan else None)
    document_id = f"rd:{session_id}:{turn_id}"
    revision, revision_source = _response_document_revision(cursor=cursor, session=session, timeline=timeline)
    latest_pending = _latest_pending_approval(pending_approval, approvals)
    state = _response_document_state(session=session, latest_pending=latest_pending, presentation=presentation)

    mutation_groups = _mutation_groups(
        steps=steps,
        timeline=timeline,
        presentation=presentation,
        operation_id=operation_id,
        approvals=approvals,
    )
    no_op_groups = _no_op_mutation_groups(session=session, approvals=approvals, operation_id=operation_id)
    if no_op_groups:
        approval_positions = _approval_position_by_id(approvals)
        # Typed business-change groups already carry their own field/basis evidence. Text order
        # parsing remains only as compatibility for older untyped mutation summaries.
        business_order = (
            {}
            if any(_group_has_business_change_contract(group) for group in mutation_groups)
            else _business_change_order_from_text(presentation.summary)
        )
        mutation_groups = sorted(
            _merge_mutation_groups_by_business_change([*no_op_groups, *mutation_groups]),
            key=lambda group: _business_group_sort_key(group, approval_positions, business_order),
        )
    read_groups = _read_evidence(steps=steps, timeline=timeline, presentation=presentation, operation_id=operation_id)
    raw_read_rows = _dedupe_rows([row for item in read_groups for row in item.rows if not _is_empty_result_envelope(row)])
    status_result = _status_result_from_read_rows(raw_read_rows, operation_id=operation_id, session=session)
    read_policy = _read_display_policy(
        raw_read_rows,
        session=session,
        status_result=status_result,
        has_read_evidence=bool(read_groups),
        read_evidence=read_groups,
    )
    read_rows = _project_read_rows_for_policy(raw_read_rows, read_policy)
    sources = normalize_source_locators(
        presentation.sources if isinstance(presentation.sources, list) else [],
        fallback_snippet=presentation.summary,
    )
    for source in sources:
        source.setdefault("contract", SOURCE_LOCATOR_CONTRACT)
    safety_content = _trimmed(getattr(plan, "safety_content", None)) or None
    failure_profile = _failure_profile(
        state=state,
        presentation=presentation,
        steps=steps,
        approvals=approvals,
        latest_pending=latest_pending,
        mutation_groups=mutation_groups,
    )

    run_steps = _compose_run_steps(
        document_id=document_id,
        operation_id=operation_id,
        state=state,
        approvals=approvals,
        latest_pending=latest_pending,
        mutation_groups=mutation_groups,
        read_evidence=read_groups,
        sources=sources,
        status_result=status_result,
        read_policy=read_policy,
        presentation=presentation,
        timeline=timeline,
        activity_steps=activity_steps,
        session=session,
        failure_profile=failure_profile,
    )
    message = sanitize_rag_answer_text(_short_message(
        state=state,
        latest_pending=latest_pending,
        approvals=approvals,
        mutation_groups=mutation_groups,
        read_evidence=read_groups,
        read_rows=read_rows,
        status_result=status_result,
        read_policy=read_policy,
        sources=sources,
        presentation=presentation,
        session=session,
        failure_profile=failure_profile,
    ))
    blocks = _compose_blocks(
        document_id=document_id,
        operation_id=operation_id,
        session=session,
        state=state,
        message=message,
        safety_content=safety_content,
        run_steps=run_steps,
        latest_pending=latest_pending,
        approvals=approvals,
        mutation_groups=mutation_groups,
        read_evidence=read_groups,
        read_rows=read_rows,
        has_read_evidence=bool(read_groups),
        status_result=status_result,
        read_policy=read_policy,
        sources=sources,
        presentation=presentation,
        failure_profile=failure_profile,
    )

    read_shape = "status" if status_result else _read_result_shape(read_rows) if read_rows or presentation.kind == "answer" else None
    diagnostics = _sanitize_diagnostic_value(dict(presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {}))
    if presentation.kind == "answer" and state == "completed" and not read_rows and not sources and not mutation_groups:
        diagnostics["reason"] = "no_results"
    if failure_profile is not None:
        diagnostics = {
            **failure_profile.technical_details,
            "reason": failure_profile.reason,
            "cause": failure_profile.cause,
            "current_state": failure_profile.current_state,
            "next_action": failure_profile.next_action,
            "retry_safety": failure_profile.retry_safety,
        }
    changed_mutation_groups = [group for group in mutation_groups if not _is_no_op_group(group)]
    no_op_mutation_groups = [group for group in mutation_groups if _is_no_op_group(group)]
    invariants = {
        **(presentation.invariants if isinstance(presentation.invariants, dict) else {}),
        "response_document_composer": "deterministic_v3_failure_recovery",
        "latest_pending_approval_id": latest_pending.approval_id if latest_pending else None,
        "completed_approval_ids": [group.approval_id for group in mutation_groups if group.approval_id],
        "mutation_group_count": len(mutation_groups),
        "not_changed_group_count": len(no_op_mutation_groups) if no_op_mutation_groups else None,
        "no_op_mutation_count": len(no_op_mutation_groups) if no_op_mutation_groups else None,
        "no_op_mutation_contract": NO_OP_MUTATION_CONTRACT if no_op_mutation_groups else None,
        "mutation_business_contract": _mutation_business_contract(
            mutation_groups,
            state=state,
            latest_pending=latest_pending,
        ),
        "affected_record_count": sum(len(group.rows) for group in changed_mutation_groups) if mutation_groups else None,
        "approved_business_change_count": len(changed_mutation_groups) if mutation_groups and not latest_pending else None,
        "affected_record_preview_limit": 5 if mutation_groups else None,
        "read_result_shape": read_shape,
        "read_scope": read_policy.read_scope if read_policy else None,
        "requested_fields": read_policy.requested_fields if read_policy else None,
        "display_mode": read_policy.display_mode if read_policy else None,
        "sort_fields": read_policy.sort_fields if read_policy and read_policy.sort_fields else None,
        "entity_count": read_policy.entity_count if read_policy else None,
        "preview_limit": read_policy.preview_limit if read_policy else None,
        "read_details_collapsed": read_policy.details_collapsed if read_policy else None,
        "read_status_contract": (
            ENTITY_STATUS_CONTRACT
            if status_result or (read_policy and read_policy.contract == ENTITY_STATUS_CONTRACT)
            else None
        ),
        "read_status_entity_type": (
            status_result.get("entity_type")
            if status_result
            else read_policy.entity_type
            if read_policy and read_policy.contract == ENTITY_STATUS_CONTRACT
            else None
        ),
        "safety_notice_contract": SAFETY_NOTICE_CONTRACT if safety_content else None,
        "knowledge_answer_contract": KNOWLEDGE_ANSWER_CONTRACT if presentation.kind == "knowledge_answer" else None,
        "source_list_contract": SOURCE_LIST_CONTRACT if sources else None,
        "source_locator_contract": SOURCE_LOCATOR_CONTRACT if sources else None,
        "failure_reason": failure_profile.reason if failure_profile else None,
        "orphan_turn_state": (
            failure_profile.reason == "orphan_turn_state"
            if failure_profile
            else diagnostics.get("reason") == "orphan_turn_state"
        ),
        "diagnostics_sanitized": True,
        "full_success_forbidden": bool(latest_pending) or bool(
            (presentation.invariants if isinstance(presentation.invariants, dict) else {}).get("full_success_forbidden")
        ),
    }

    return ResponseDocument(
        id=document_id,
        document_id=document_id,
        turn_id=turn_id,
        operation_id=operation_id,
        revision=revision,
        revision_source=revision_source,
        state=state,  # type: ignore[arg-type]
        status=state,  # type: ignore[arg-type]
        summary=message,
        message=message,
        current_step_id=_current_response_step_id(run_steps),
        run_steps=run_steps,
        blocks=blocks,
        invariants=invariants,
        diagnostics=diagnostics,
    )
