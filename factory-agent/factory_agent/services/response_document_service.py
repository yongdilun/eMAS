from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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
    ShortMessageBlock,
    SourceListBlock,
    TimelineEventResponse,
)


_SUCCESS_ROW_STATES = {"ok", "success", "succeeded", "done", "updated", "created", "deleted", "applied"}
_FAILED_ROW_STATES = {"failed", "error", "errored", "rejected", "conflict", "skipped_failed"}
_WRITE_TOOL_RE = re.compile(r"^(post|put|patch|delete)__", re.IGNORECASE)
_READ_TOOL_RE = re.compile(r"^(get|list|search|read)__", re.IGNORECASE)


@dataclass
class MutationGroup:
    key: str
    operation_id: str | None
    approval_id: str | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    step_ids: list[str] = field(default_factory=list)
    completed_at: datetime | None = None
    status: str = "completed"


@dataclass
class ReadEvidence:
    key: str
    operation_id: str | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    step_ids: list[str] = field(default_factory=list)
    completed_at: datetime | None = None


def _trimmed(value: Any) -> str:
    return str(value or "").strip()


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


def _normalize_row_status(status: Any, *, default: str) -> str:
    normalized = _trimmed(status).lower()
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
    candidate_lists = [bundle_ui.get("rows"), payload.get("preview"), payload.get("staged_writes")]
    rows: list[dict[str, Any]] = []
    for candidate in candidate_lists:
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            if not isinstance(item, dict):
                continue
            row_payload = item.get("args") if isinstance(item.get("args"), dict) else item
            row = _presentation_row(
                dict(row_payload),
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
        key = json.dumps(row, sort_keys=True, default=str)
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
    if cursor > 0:
        return cursor, "event_seq"
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


def _approval_position_by_id(approvals: list[ApprovalResponse]) -> dict[str, int]:
    ordered = sorted(approvals, key=lambda row: (row.created_at, row.approval_id))
    return {row.approval_id: index for index, row in enumerate(ordered, start=1)}


def _group_sort_key(group: MutationGroup, approval_positions: dict[str, int]) -> tuple[int, datetime, str]:
    approval_rank = approval_positions.get(group.approval_id or "", 10_000)
    completed_at = group.completed_at or datetime.min
    return approval_rank, completed_at, group.key


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
        group = MutationGroup(key=key, operation_id=operation_id, approval_id=approval_id)
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
    else:
        group.status = "completed"


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
        if not _is_write_tool_name(step.tool_name) and not step.requires_approval:
            continue
        default_status = "failed" if status in {"FAILED", "AMBIGUOUS"} else "succeeded"
        approval_id = step.approval_id
        if isinstance(step.result, dict):
            approval_id = _trimmed(step.result.get("approval_id") or step.result.get("_approval_id") or approval_id) or None
        rows = _operation_rows_from_result(
            step.result if isinstance(step.result, dict) else None,
            default_status=default_status,
            operation_id=operation_id or step.plan_id,
            approval_id=approval_id,
            step_id=step.step_id,
            tool_name=step.tool_name,
            fallback_args=step.args if _is_write_tool_name(step.tool_name) else None,
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
    return sorted(groups.values(), key=lambda group: _group_sort_key(group, approval_positions))


def _read_evidence(
    *,
    steps: list[PlanStepResponse],
    timeline: list[TimelineEventResponse],
    presentation: PresentationResponse,
    operation_id: str | None,
) -> list[ReadEvidence]:
    rows_by_key: dict[str, ReadEvidence] = {}

    def add_rows(key: str, rows: list[dict[str, Any]], step_id: str | None, completed_at: datetime | None) -> None:
        if key not in rows_by_key:
            rows_by_key[key] = ReadEvidence(key=key, operation_id=operation_id)
        evidence = rows_by_key[key]
        evidence.rows.extend(rows)
        if step_id and step_id not in evidence.step_ids:
            evidence.step_ids.append(step_id)
        if completed_at and (evidence.completed_at is None or completed_at > evidence.completed_at):
            evidence.completed_at = completed_at

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
        add_rows(f"read:{step.step_id}", rows, step.step_id, step.completed_at or step.started_at)

    for event in timeline:
        if event.event_type != "tool_result" or _is_write_tool_name(event.tool_name):
            continue
        details = event.details if isinstance(event.details, dict) else {}
        result = details.get("result") if isinstance(details.get("result"), dict) else None
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
        add_rows(f"read:{event.step_id or event.event_id}", rows, event.step_id, event.created_at)

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
        or row.get("before_priority")
    ).lower()


def _target_priority(row: dict[str, Any]) -> str:
    return _trimmed(
        row.get("new_priority")
        or row.get("priority")
        or row.get("requested_priority")
        or row.get("after_priority")
    ).lower()


def _rows_use_original_state(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if row.get("original_priority") or _trimmed(row.get("source_state_basis")).lower() == "original":
            return True
        write_set = _trimmed(row.get("write_set")).lower()
        bundle_kind = _trimmed(row.get("bundle_kind")).lower()
        if write_set.startswith("original_") or "cascade" in bundle_kind:
            return True
    return False


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
    if all(_row_identifier(row).upper().startswith("JOB-") for row in all_rows if _row_identifier(row)):
        return "jobs"
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
    presentation: PresentationResponse,
    timeline: list[TimelineEventResponse],
    activity_steps: list[ActivityStepResponse],
    session: Any,
) -> list[RunStep]:
    run_steps: list[RunStep] = []
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
    for approval in sorted(approvals, key=lambda row: (row.created_at, row.approval_id)):
        approval_index = approval_positions.get(approval.approval_id, 1)
        approval_status = str(approval.status or "").upper()
        expired = _approval_is_expired(approval)
        row_status = "pending"
        if approval_status in {"APPROVED", "ACCEPTED"}:
            row_status = "succeeded"
        elif approval_status == "REJECTED":
            row_status = "rejected"
        elif expired:
            row_status = "expired"
        rows = _approval_rows(approval, operation_id=operation_id, default_status=row_status)
        if rows:
            run_steps.append(
                RunStep(
                    step_id=f"read:{approval.approval_id}",
                    kind="read",
                    state="completed",
                    title=f"Found {len(rows)} {_plural(len(rows), 'record')}",
                    summary=_approval_summary(approval),
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
                summary=_approval_summary(approval),
                approval_id=approval.approval_id,
                operation_id=_approval_operation_id(approval, operation_id),
                record_count=len(rows) if rows else None,
                current=current,
            )
        )

        group = groups_by_approval.get(approval.approval_id)
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
        if group.approval_id:
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

    if not approvals and read_evidence:
        total_rows = sum(len(item.rows) for item in read_evidence)
        run_steps.append(
            RunStep(
                step_id=f"read:{operation_id or document_id}",
                kind="read",
                state="completed",
                title=f"Read {total_rows} {_plural(total_rows, 'record')}",
                summary=_read_summary([row for item in read_evidence for row in item.rows], presentation.summary),
                operation_id=operation_id,
                record_count=total_rows,
            )
        )

    if sources:
        run_steps.append(
            RunStep(
                step_id=f"knowledge:{operation_id or document_id}",
                kind="knowledge",
                state="completed",
                title="Prepared sourced answer",
                summary=f"{len(sources)} {_plural(len(sources), 'source')} attached.",
                operation_id=operation_id,
                record_count=len(sources),
            )
        )

    if presentation.kind in {"diagnostic", "cancelled", "rejected", "expired"}:
        diagnostic_state = state if state in {"failed", "rejected", "expired", "cancelled"} else "failed"
        run_steps.append(
            RunStep(
                step_id=f"diagnostic:{operation_id or document_id}",
                kind="diagnostic" if presentation.kind != "cancelled" else "cancelled",
                state=diagnostic_state,  # type: ignore[arg-type]
                title="Needs attention" if presentation.kind == "diagnostic" else presentation.kind.title(),
                summary=_trimmed(presentation.summary) or None,
                operation_id=operation_id,
                current=state in {"failed", "blocked"},
                diagnostics= presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {},
            )
        )

    if state == "completed" and not latest_pending:
        run_steps.append(
            RunStep(
                step_id=f"completed:{operation_id or document_id}",
                kind="completed",
                state="completed",
                title="Run complete",
                summary=_trimmed(presentation.summary) or None,
                operation_id=operation_id,
            )
        )

    if not run_steps:
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


def _aggregate_mutation_summary(groups: list[MutationGroup]) -> str:
    total = sum(len(group.rows) for group in groups)
    step_count = len(groups)
    noun = _mutation_total_noun(groups)
    return f"Updated {total} {noun} across {step_count} approved {_plural(step_count, 'step')}."


def _aggregate_step_payloads(groups: list[MutationGroup]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        payloads.append(
            {
                "step_number": index,
                "approval_id": group.approval_id,
                "operation_id": group.operation_id,
                "summary": _mutation_group_summary(group),
                "record_count": len(group.rows),
                "status": group.status,
            }
        )
    return payloads


def _short_message(
    *,
    state: str,
    latest_pending: ApprovalResponse | None,
    approvals: list[ApprovalResponse],
    mutation_groups: list[MutationGroup],
    read_rows: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    presentation: PresentationResponse,
    session: Any,
) -> str:
    if latest_pending is not None:
        pending_text = _approval_summary(latest_pending)
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
        return _trimmed(presentation.summary) or "I found a source-backed answer."

    if read_rows:
        return _read_summary(read_rows, presentation.summary)

    if presentation.kind == "answer" and state == "completed":
        return _trimmed(presentation.summary) or "No matching records were found."

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
) -> list[ResponseBlock]:
    if not rows:
        return []
    shape = _read_result_shape(rows)
    if shape == "table":
        return [
            ResultTableBlock(
                id=f"table:{id_prefix}",
                title=title,
                rows=rows,
                operation_id=operation_id,
                approval_id=approval_id,
            )
        ]
    return [
        RecordPreviewBlock(
            id=f"record-preview:{id_prefix}",
            title=title,
            rows=rows,
            operation_id=operation_id,
            approval_id=approval_id,
        )
    ]


def _compose_blocks(
    *,
    document_id: str,
    operation_id: str | None,
    state: str,
    message: str,
    run_steps: list[RunStep],
    latest_pending: ApprovalResponse | None,
    approvals: list[ApprovalResponse],
    mutation_groups: list[MutationGroup],
    read_rows: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    presentation: PresentationResponse,
) -> list[ResponseBlock]:
    blocks: list[ResponseBlock] = []
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
        pending_summary = _approval_summary(latest_pending)
        blocks.append(
            ApprovalRequiredBlock(
                id=f"approval:{latest_pending.approval_id}",
                approval_id=latest_pending.approval_id,
                operation_id=_approval_operation_id(latest_pending, operation_id),
                summary=pending_summary,
                rows=pending_rows,
            )
        )
        if pending_rows:
            blocks.append(
                RecordPreviewBlock(
                    id=f"record-preview:{latest_pending.approval_id}:pending",
                    title="Affected records",
                    rows=pending_rows[:5],
                    operation_id=_approval_operation_id(latest_pending, operation_id),
                    approval_id=latest_pending.approval_id,
                )
            )
            blocks.append(
                ResultTableBlock(
                    id=f"table:{latest_pending.approval_id}:affected-records",
                    title="Affected records",
                    rows=pending_rows,
                    operation_id=_approval_operation_id(latest_pending, operation_id),
                    approval_id=latest_pending.approval_id,
                )
            )
        return blocks

    if mutation_groups:
        all_rows = [row for group in mutation_groups for row in group.rows]
        summary = _aggregate_mutation_summary(mutation_groups)
        status = "partial_failure" if any(group.status == "partial_failure" for group in mutation_groups) else "completed"
        if any(group.status == "failed" for group in mutation_groups) and not any(group.status == "completed" for group in mutation_groups):
            status = "failed"
        blocks.append(
            ResultSummaryBlock(
                id=f"result-summary:{operation_id or document_id}",
                operation_id=operation_id,
                summary=summary,
                steps=_aggregate_step_payloads(mutation_groups),
                total_count=len(all_rows),
                status=status,  # type: ignore[arg-type]
            )
        )
        blocks.append(
            MutationResultBlock(
                id=f"mutation:{operation_id or anchor}",
                operation_id=operation_id,
                approval_id=presentation.approval_id,
                summary=summary,
                rows=all_rows,
                status=status,  # type: ignore[arg-type]
            )
        )
        if all_rows:
            blocks.append(
                ResultTableBlock(
                    id=f"table:{operation_id or anchor}:affected-records",
                    title="Affected records",
                    rows=all_rows,
                    operation_id=operation_id,
                    approval_id=presentation.approval_id,
                )
            )

    if presentation.kind == "knowledge_answer" and message:
        blocks.append(KnowledgeAnswerBlock(id=f"knowledge:{operation_id or document_id}", answer=message, operation_id=operation_id))

    if read_rows and not mutation_groups:
        blocks.extend(
            _record_blocks_for_rows(
                id_prefix=f"{operation_id or document_id}:read-results",
                operation_id=operation_id,
                approval_id=None,
                rows=read_rows,
                title="Results",
            )
        )

    if sources:
        blocks.append(SourceListBlock(id=f"sources:{operation_id or document_id}", sources=sources, operation_id=operation_id))

    no_result = presentation.kind == "answer" and not read_rows and not sources and state == "completed"
    diagnostic_kind = presentation.kind in {"diagnostic", "cancelled", "rejected", "expired", "partial_failure"}
    if no_result or diagnostic_kind:
        diagnostics = presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {}
        reason = "no_results" if no_result else str(diagnostics.get("reason") or presentation.kind)
        blocks.append(
            DiagnosticBlock(
                id=f"diagnostic:{anchor}:{reason}",
                severity=_diagnostic_severity(state, info=no_result),  # type: ignore[arg-type]
                reason=reason,
                title="No results" if no_result else "Needs attention",
                user_message=message,
                technical_details=diagnostics,
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
    read_groups = _read_evidence(steps=steps, timeline=timeline, presentation=presentation, operation_id=operation_id)
    read_rows = _dedupe_rows([row for item in read_groups for row in item.rows if not _is_empty_result_envelope(row)])
    sources = presentation.sources if isinstance(presentation.sources, list) else []

    run_steps = _compose_run_steps(
        document_id=document_id,
        operation_id=operation_id,
        state=state,
        approvals=approvals,
        latest_pending=latest_pending,
        mutation_groups=mutation_groups,
        read_evidence=read_groups,
        sources=sources,
        presentation=presentation,
        timeline=timeline,
        activity_steps=activity_steps,
        session=session,
    )
    message = _short_message(
        state=state,
        latest_pending=latest_pending,
        approvals=approvals,
        mutation_groups=mutation_groups,
        read_rows=read_rows,
        sources=sources,
        presentation=presentation,
        session=session,
    )
    blocks = _compose_blocks(
        document_id=document_id,
        operation_id=operation_id,
        state=state,
        message=message,
        run_steps=run_steps,
        latest_pending=latest_pending,
        approvals=approvals,
        mutation_groups=mutation_groups,
        read_rows=read_rows,
        sources=sources,
        presentation=presentation,
    )

    read_shape = _read_result_shape(read_rows) if read_rows or presentation.kind == "answer" else None
    diagnostics = dict(presentation.diagnostics if isinstance(presentation.diagnostics, dict) else {})
    if presentation.kind == "answer" and state == "completed" and not read_rows and not sources:
        diagnostics["reason"] = "no_results"
    invariants = {
        **(presentation.invariants if isinstance(presentation.invariants, dict) else {}),
        "response_document_composer": "deterministic_v2",
        "latest_pending_approval_id": latest_pending.approval_id if latest_pending else None,
        "completed_approval_ids": [group.approval_id for group in mutation_groups if group.approval_id],
        "mutation_group_count": len(mutation_groups),
        "read_result_shape": read_shape,
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
