from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from factory_agent.rag.source_metadata import is_insufficient_context_answer

from .historical_legacy_rag_route_compatibility import (
    historical_legacy_rag_route_cannot_satisfy_issue,
    is_historical_legacy_rag_route_evidence,
)
from .v2_contracts import (
    CapabilityNeed,
    EvidenceLedgerEntry,
    FinalValidationIssue,
    FinalValidationResult,
    PlannerOwnedLoopV2State,
    RequirementLedgerEntry,
    RequirementRevisionRecord,
    RequirementSatisfactionState,
    SatisfactionCheck,
)


_TERMINAL_UPDATE_STATUSES = {"satisfied", "skipped", "impossible", "blocked", "failed"}
_CONTROL_CONSTRAINTS = {
    "fields",
    "limit",
    "offset",
    "page",
    "page_size",
    "sort",
    "sort_by",
    "sort_dir",
}
_NON_FILTER_CONSTRAINTS = {
    *_CONTROL_CONSTRAINTS,
    "conditional_branches",
    "observation_fields",
    "preview_before_apply",
    "requires_approval",
    "safety_constraints",
}
_RESULT_META_FIELDS = {
    "answer",
    "citations",
    "data",
    "entity",
    "entity_id",
    "error",
    "fields",
    "items",
    "match_status",
    "message",
    "no_match",
    "records",
    "result",
    "results",
    "rows",
    "status_code",
    "summary",
    "text",
}


@dataclass(frozen=True)
class RetrievalGuardDecision:
    blocked: bool
    status: str
    need_key: str
    state_fingerprint: str
    reason: str | None = None

    def as_diagnostics(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "status": self.status,
            "need_key": self.need_key,
            "state_fingerprint": self.state_fingerprint,
            "reason": self.reason,
        }


class V2RepeatedRetrievalGuard:
    """Blocks unchanged repeated retrieval needs without becoming a retriever."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def check(self, capability_need: CapabilityNeed, *, state: PlannerOwnedLoopV2State) -> RetrievalGuardDecision:
        need_key = capability_need_guard_key(capability_need)
        fingerprint = retrieval_state_fingerprint(state)
        previous = self._seen.get(need_key)
        if previous == fingerprint:
            return RetrievalGuardDecision(
                blocked=True,
                status="blocked_repeated_need",
                need_key=need_key,
                state_fingerprint=fingerprint,
                reason="same_capability_need_without_new_evidence_or_requirement_change",
            )
        self._seen[need_key] = fingerprint
        return RetrievalGuardDecision(
            blocked=False,
            status="allowed_state_changed" if previous is not None else "allowed_first_request",
            need_key=need_key,
            state_fingerprint=fingerprint,
            reason=None if previous is None else "new_evidence_or_requirement_change_detected",
        )


def capability_need_guard_key(capability_need: CapabilityNeed) -> str:
    payload = capability_need.model_dump(mode="json")
    comparable = {
        key: value
        for key, value in payload.items()
        if key not in {"requirement_id", "reason"}
    }
    return json.dumps(comparable, sort_keys=True, default=str)


def retrieval_state_fingerprint(state: PlannerOwnedLoopV2State) -> str:
    ledger = state.requirement_ledger
    requirements = []
    if ledger is not None:
        requirements = [
            {
                "id": req.id,
                "status": req.status,
                "required": req.required,
                "constraints": req.constraints,
                "requested_fields": req.requested_fields,
                "locked_constraints": req.locked_constraints,
            }
            for req in ledger.requirements
        ]
    evidence = [
        {
            "id": item.id,
            "requirement_id": item.requirement_id,
            "source_type": item.source_type,
            "confidence": item.confidence,
            "normalized_result": item.normalized_result,
        }
        for item in state.evidence_ledger.evidence
    ]
    return json.dumps(
        {
            "ledger_revision": ledger.revision if ledger is not None else None,
            "requirements": requirements,
            "evidence": evidence,
        },
        sort_keys=True,
        default=str,
    )


def apply_deterministic_evidence_satisfaction(state: PlannerOwnedLoopV2State) -> PlannerOwnedLoopV2State:
    """Apply Phase 6 deterministic satisfaction to obvious typed evidence only."""

    ledger = state.requirement_ledger
    if ledger is None:
        state.execution_trace.diagnostics["satisfaction"] = {
            "status": "not_run",
            "reason": "missing_requirement_ledger",
        }
        return state

    evidence_by_requirement: dict[str, list[EvidenceLedgerEntry]] = {}
    for evidence in state.evidence_ledger.evidence:
        evidence_by_requirement.setdefault(evidence.requirement_id, []).append(evidence)

    changes: list[dict[str, Any]] = []
    for requirement in ledger.requirements:
        if requirement.status != "open":
            continue
        evidence_items = evidence_by_requirement.get(requirement.id, [])
        if requirement.requirement_type in {"mutation_request", "approval_request"}:
            evidence = _append_diagnostic_evidence(
                state,
                requirement,
                reason="write_or_approval_requires_planner",
            )
            checks = [
                _check(
                    "approval_state",
                    expected="planner_or_approval_required",
                    actual=requirement.requirement_type,
                    passed=True,
                    evidence_ref=evidence.id,
                    message="Writes and approval requirements are not deterministically finalized.",
                )
            ]
            _record_requirement_update(
                state,
                requirement,
                status="blocked",
                evidence_refs=[evidence.id],
                checks=checks,
                reason="write_or_approval_requires_planner",
                changes=changes,
            )
            continue

        if not evidence_items:
            continue

        if requirement.source_of_truth in {"mixed", "unknown"}:
            checks = [
                _check(
                    "source_of_truth",
                    expected="single_clear_source_of_truth",
                    actual=requirement.source_of_truth,
                    passed=False,
                    evidence_ref=evidence_items[0].id,
                    message="Source of truth is mixed or unclear.",
                )
            ]
            _record_requirement_update(
                state,
                requirement,
                status="blocked",
                evidence_refs=[evidence_items[0].id],
                checks=checks,
                reason="source_of_truth_unclear",
                changes=changes,
            )
            continue

        ambiguous_reason = _ambiguous_evidence_reason(evidence_items)
        if ambiguous_reason:
            checks = [
                _check(
                    "failure_state",
                    expected="deterministic_unambiguous_evidence",
                    actual=ambiguous_reason,
                    passed=False,
                    evidence_ref=evidence_items[0].id,
                    message="Evidence is ambiguous and must return to planner control.",
                )
            ]
            _record_requirement_update(
                state,
                requirement,
                status="blocked",
                evidence_refs=[item.id for item in evidence_items],
                checks=checks,
                reason=ambiguous_reason,
                changes=changes,
            )
            continue

        evidence = evidence_items[0]
        failed_reason = _typed_failure_reason(evidence)
        if failed_reason:
            checks = [
                _check(
                    "failure_state",
                    expected="successful_typed_tool_evidence",
                    actual=failed_reason,
                    passed=False,
                    evidence_ref=evidence.id,
                    message="Tool failure cannot be fast-pathed to final success.",
                )
            ]
            _record_requirement_update(
                state,
                requirement,
                status="failed",
                evidence_refs=[evidence.id],
                checks=checks,
                reason=failed_reason,
                changes=changes,
            )
            continue

        if _has_explicit_no_match(evidence):
            checks = [
                _check(
                    "failure_state",
                    expected="typed_no_match",
                    actual="typed_no_match",
                    passed=True,
                    evidence_ref=evidence.id,
                    message="No matching record was explicit typed evidence.",
                )
            ]
            _record_requirement_update(
                state,
                requirement,
                status="impossible",
                evidence_refs=[evidence.id],
                checks=checks,
                reason="typed_no_match",
                changes=changes,
            )
            continue

        status, checks, reason = _evaluate_requirement(requirement, evidence)
        if status is None:
            continue
        _record_requirement_update(
            state,
            requirement,
            status=status,
            evidence_refs=[evidence.id],
            checks=checks,
            reason=reason,
            changes=changes,
        )

    open_ids = [req.id for req in ledger.requirements if req.status == "open"]
    state.execution_trace.diagnostics["satisfaction"] = {
        "status": "applied",
        "changes": changes,
        "open_requirement_ids": open_ids,
        "missing_evidence_reasons": _missing_evidence_reasons(ledger.requirements),
    }
    return state


def _missing_evidence_reasons(requirements: Sequence[RequirementLedgerEntry]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    for requirement in requirements:
        if requirement.status not in {"open", "blocked", "failed"}:
            continue
        failed_checks = [
            {
                "check": check.check,
                "expected": check.expected,
                "actual": check.actual,
                "evidence_ref": check.evidence_ref,
            }
            for check in requirement.satisfaction_checks
            if not check.passed
        ]
        reason = requirement.blockers[-1] if requirement.blockers else "missing_active_evidence"
        reasons.append(
            {
                "requirement_id": requirement.id,
                "status": requirement.status,
                "reason": reason,
                "retriable": _missing_evidence_reason_is_retriable(requirement, reason=reason),
                "evidence_refs": list(requirement.evidence_refs),
                "failed_checks": failed_checks,
            }
        )
    return reasons


def _missing_evidence_reason_is_retriable(
    requirement: RequirementLedgerEntry,
    *,
    reason: str,
) -> bool:
    if requirement.status == "open":
        return True
    if requirement.requirement_type in {"mutation_request", "approval_request"}:
        return False
    if reason in {
        "failed",
        "failure",
        "error",
        "write_or_approval_requires_planner",
        "source_of_truth_unclear",
    }:
        return False
    return requirement.status in {"blocked", "failed"}


def validate_v2_final_state(state: PlannerOwnedLoopV2State) -> FinalValidationResult:
    """Validate that v2 is allowed to finalize from typed requirement evidence."""

    issues: list[FinalValidationIssue] = []
    ledger = state.requirement_ledger
    if ledger is None:
        issues.append(FinalValidationIssue(issue="missing_requirement_ledger"))
        result = _final_validation_result(state, issues, checked_requirement_ids=[])
        return result

    evidence_by_id = {evidence.id: evidence for evidence in state.evidence_ledger.evidence}
    checked_ids: list[str] = []

    _validate_locked_constraints_preserved(state, issues)

    for record in [*ledger.revision_history, *state.revision_history]:
        if not record.locked_constraints_preserved:
            issues.append(
                FinalValidationIssue(
                    issue="locked_constraints_not_preserved",
                    requirement_id=record.requirement_id,
                    message=record.reason,
                )
            )

    for requirement in ledger.requirements:
        checked_ids.append(requirement.id)
        if not requirement.required:
            continue
        if requirement.status == "open":
            issues.append(
                FinalValidationIssue(
                    issue="required_requirement_open",
                    requirement_id=requirement.id,
                    expected="terminal_status",
                    actual=requirement.status,
                )
            )
            continue
        if requirement.status in {"blocked", "failed", "skipped", "superseded"}:
            issues.append(
                FinalValidationIssue(
                    issue="required_requirement_not_finalizable",
                    requirement_id=requirement.id,
                    expected="satisfied_or_typed_impossible",
                    actual=requirement.status,
                )
            )
        if requirement.status in _TERMINAL_UPDATE_STATUSES:
            if not requirement.evidence_refs:
                issues.append(
                    FinalValidationIssue(
                        issue="terminal_update_missing_evidence_refs",
                        requirement_id=requirement.id,
                    )
                )
            if not requirement.satisfaction_checks:
                issues.append(
                    FinalValidationIssue(
                        issue="terminal_update_missing_proof_checks",
                        requirement_id=requirement.id,
                    )
                )
        if requirement.status == "satisfied":
            if any(not check.passed for check in requirement.satisfaction_checks):
                issues.append(
                    FinalValidationIssue(
                        issue="satisfied_requirement_has_failed_check",
                        requirement_id=requirement.id,
                        actual=[
                            check.model_dump(mode="json")
                            for check in requirement.satisfaction_checks
                            if not check.passed
                        ],
                    )
                )
        for evidence_ref in requirement.evidence_refs:
            evidence = evidence_by_id.get(evidence_ref)
            if evidence is None:
                issues.append(
                    FinalValidationIssue(
                        issue="missing_typed_evidence",
                        requirement_id=requirement.id,
                        evidence_ref=evidence_ref,
                    )
                )
                continue
            _validate_typed_evidence(requirement, evidence, issues)
        for check in requirement.satisfaction_checks:
            if check.evidence_ref is None:
                issues.append(
                    FinalValidationIssue(
                        issue="proof_check_missing_evidence_ref",
                        requirement_id=requirement.id,
                        check=check.check,
                    )
                )

    return _final_validation_result(state, issues, checked_requirement_ids=checked_ids)


def _evaluate_requirement(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
) -> tuple[str | None, list[SatisfactionCheck], str]:
    if requirement.requirement_type == "single_entity_status":
        return _evaluate_single_entity_requirement(requirement, evidence)
    if requirement.requirement_type == "multi_entity_status":
        return _evaluate_multi_entity_requirement(requirement, evidence)
    if requirement.requirement_type == "filtered_collection":
        return _evaluate_collection_requirement(requirement, evidence)
    if requirement.requirement_type == "document_answer":
        return _evaluate_document_requirement(requirement, evidence)
    return None, [], "unsupported_requirement_type"


def _evaluate_single_entity_requirement(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
) -> tuple[str, list[SatisfactionCheck], str]:
    checks: list[SatisfactionCheck] = []
    if evidence.source_type != "api_tool" or evidence.source_of_truth != "operational_state":
        checks.append(
            _check(
                "source_of_truth",
                expected="api_tool:operational_state",
                actual=f"{evidence.source_type}:{evidence.source_of_truth}",
                passed=False,
                evidence_ref=evidence.id,
            )
        )
        return "blocked", checks, "wrong_evidence_source"

    fields = _typed_fields(evidence.normalized_result)
    expected_id_key, expected_id = _expected_entity_id(requirement)
    actual_id = _actual_entity_id(requirement, evidence, fields)
    if expected_id is not None:
        checks.append(
            _check(
                "entity_match",
                expected={expected_id_key: expected_id},
                actual=actual_id,
                passed=_same_value(expected_id, actual_id),
                evidence_ref=evidence.id,
            )
        )
    checks.extend(_locked_constraint_checks(requirement, evidence, fields=fields, rows=None))
    checks.append(_requested_fields_check(requirement, evidence, fields=fields))

    return _status_from_checks(checks)


def _evaluate_multi_entity_requirement(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
) -> tuple[str, list[SatisfactionCheck], str]:
    checks: list[SatisfactionCheck] = []
    if evidence.source_type != "api_tool" or evidence.source_of_truth != "operational_state":
        checks.append(
            _check(
                "source_of_truth",
                expected="api_tool:operational_state",
                actual=f"{evidence.source_type}:{evidence.source_of_truth}",
                passed=False,
                evidence_ref=evidence.id,
            )
        )
        return "blocked", checks, "wrong_evidence_source"

    rows = _typed_rows(evidence.normalized_result)
    if rows is None:
        checks.append(
            _check(
                "collection_rows",
                expected="typed_rows",
                actual=sorted(evidence.normalized_result.keys()),
                passed=False,
                evidence_ref=evidence.id,
                message="Multi-entity status requirements need typed rows, not prose summary.",
            )
        )
        return "blocked", checks, "missing_typed_multi_entity_rows"

    expected_ids = _expected_entity_ids(requirement)
    actual_ids = [_row_entity_id(requirement, row) for row in rows]
    checks.append(
        _check(
            "entity_match",
            expected=expected_ids,
            actual=actual_ids,
            actual_count=len([item for item in actual_ids if item not in (None, "")]),
            passed=bool(expected_ids) and set(map(str, expected_ids)) == set(map(str, actual_ids)),
            evidence_ref=evidence.id,
        )
    )
    checks.append(_multi_status_requested_fields_check(requirement, evidence, rows))
    return _status_from_checks(checks)


def _evaluate_collection_requirement(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
) -> tuple[str, list[SatisfactionCheck], str]:
    checks: list[SatisfactionCheck] = []
    if evidence.source_type != "api_tool" or evidence.source_of_truth != "operational_state":
        checks.append(
            _check(
                "source_of_truth",
                expected="api_tool:operational_state",
                actual=f"{evidence.source_type}:{evidence.source_of_truth}",
                passed=False,
                evidence_ref=evidence.id,
            )
        )
        return "blocked", checks, "wrong_evidence_source"

    rows = _typed_rows(evidence.normalized_result)
    if rows is None:
        checks.append(
            _check(
                "collection_rows",
                expected="typed_rows",
                actual=sorted(evidence.normalized_result.keys()),
                passed=False,
                evidence_ref=evidence.id,
                message="Collection requirements need typed rows, not prose summary.",
            )
        )
        return "blocked", checks, "missing_typed_collection_rows"

    checks.extend(_locked_constraint_checks(requirement, evidence, fields={}, rows=rows))
    checks.extend(_filter_checks(requirement, evidence, rows))
    checks.append(_sort_check(requirement, evidence, rows))
    checks.append(_limit_check(requirement, evidence, rows))
    checks.append(_collection_requested_fields_check(requirement, evidence, rows))
    checks.extend(_conditional_branch_checks(requirement, evidence, rows))
    return _status_from_checks(checks)


def _evaluate_document_requirement(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
) -> tuple[str, list[SatisfactionCheck], str]:
    checks: list[SatisfactionCheck] = []
    source_ok = evidence.source_type == "rag_tool" and evidence.source_of_truth == "document_knowledge"
    answer = evidence.normalized_result.get("answer")
    citations = evidence.citations
    typed_citations = [
        citation
        for citation in citations
        if citation.source_id and (citation.doc_id or citation.chunk_id or citation.page or citation.locator or citation.title)
    ]
    checks.append(
        _check(
            "source_citation",
            expected="rag_tool_with_typed_citations",
            actual={
                "source_type": evidence.source_type,
                "source_of_truth": evidence.source_of_truth,
                "citation_count": len(citations),
                "typed_citation_count": len(typed_citations),
            },
            passed=source_ok and bool(typed_citations),
            evidence_ref=evidence.id,
        )
    )
    checks.append(
        _check(
            "document_answer",
            expected="typed_answer_or_explicit_no_match",
            actual=(
                "insufficient_context"
                if is_insufficient_context_answer(answer)
                else "typed_answer"
                if isinstance(answer, str) and answer.strip()
                else None
            ),
            passed=isinstance(answer, str) and bool(answer.strip()) and not is_insufficient_context_answer(answer),
            evidence_ref=evidence.id,
        )
    )
    return _status_from_checks(checks)


def _status_from_checks(checks: list[SatisfactionCheck]) -> tuple[str, list[SatisfactionCheck], str]:
    if checks and all(check.passed for check in checks):
        return "satisfied", checks, "deterministic_checks_passed"
    return "blocked", checks, "deterministic_checks_failed"


def _record_requirement_update(
    state: PlannerOwnedLoopV2State,
    requirement: RequirementLedgerEntry,
    *,
    status: str,
    evidence_refs: list[str],
    checks: list[SatisfactionCheck],
    reason: str,
    changes: list[dict[str, Any]],
) -> None:
    if status in _TERMINAL_UPDATE_STATUSES and (not evidence_refs or not checks):
        raise ValueError("terminal requirement updates require evidence refs and proof checks")
    checks = _checks_with_evidence_refs(checks, evidence_refs)
    previous_status = requirement.status
    requirement.status = status  # type: ignore[assignment]
    requirement.evidence_refs = list(dict.fromkeys(evidence_refs))
    requirement.satisfaction_checks = checks
    if status in {"blocked", "failed", "impossible"} and reason not in requirement.blockers:
        requirement.blockers.append(reason)

    ledger = state.requirement_ledger
    revision = (ledger.revision + 1) if ledger is not None else 1
    if ledger is not None:
        ledger.revision = revision
    record = RequirementRevisionRecord(
        revision=revision,
        actor="deterministic_guard",
        change_type=f"evidence_satisfaction:{status}",
        requirement_id=requirement.id,
        reason=reason,
        locked_constraints_preserved=True,
        details={
            "previous_status": previous_status,
            "new_status": status,
            "evidence_refs": evidence_refs,
            "satisfaction_checks": [check.model_dump(mode="json") for check in checks],
        },
    )
    if ledger is not None:
        ledger.revision_history.append(record)
    state.revision_history.append(record)
    _upsert_satisfaction_state(state, requirement, reason=reason)
    changes.append(record.details | {"requirement_id": requirement.id})


def _upsert_satisfaction_state(
    state: PlannerOwnedLoopV2State,
    requirement: RequirementLedgerEntry,
    *,
    reason: str,
) -> None:
    entry = RequirementSatisfactionState(
        requirement_id=requirement.id,
        status=requirement.status,
        evidence_refs=list(requirement.evidence_refs),
        satisfaction_checks=list(requirement.satisfaction_checks),
        blocker_reason=reason if requirement.status in {"blocked", "failed", "impossible"} else None,
    )
    existing = [
        item
        for item in state.satisfaction_state.requirements
        if item.requirement_id != requirement.id
    ]
    existing.append(entry)
    state.satisfaction_state.requirements = existing


def _append_diagnostic_evidence(
    state: PlannerOwnedLoopV2State,
    requirement: RequirementLedgerEntry,
    *,
    reason: str,
) -> EvidenceLedgerEntry:
    evidence = EvidenceLedgerEntry(
        id=_unique_evidence_id(state, f"ev-{requirement.id}-{reason}"),
        requirement_id=requirement.id,
        source_type="system_guard",
        source_of_truth=requirement.source_of_truth,
        confidence="deterministic",
        normalized_result={"failure_state": reason},
        diagnostic_metadata={"reason": reason},
    )
    state.evidence_ledger.evidence.append(evidence)
    return evidence


def _unique_evidence_id(state: PlannerOwnedLoopV2State, base: str) -> str:
    existing = {evidence.id for evidence in state.evidence_ledger.evidence}
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _check(
    check: str,
    *,
    expected: Any = None,
    actual: Any = None,
    actual_count: int | None = None,
    passed: bool,
    evidence_ref: str | None,
    message: str | None = None,
) -> SatisfactionCheck:
    return SatisfactionCheck(
        check=check,
        expected=expected,
        actual=actual,
        actual_count=actual_count,
        passed=passed,
        evidence_ref=evidence_ref,
        message=message,
    )


def _checks_with_evidence_refs(
    checks: list[SatisfactionCheck],
    evidence_refs: list[str],
) -> list[SatisfactionCheck]:
    fallback = evidence_refs[0] if evidence_refs else None
    return [
        check.model_copy(update={"evidence_ref": check.evidence_ref or fallback})
        for check in checks
    ]


def _ambiguous_evidence_reason(evidence_items: list[EvidenceLedgerEntry]) -> str | None:
    aggregated_from = {
        str(evidence_id)
        for item in evidence_items
        for evidence_id in (item.diagnostic_metadata.get("aggregated_from") or [])
        if str(evidence_id)
    }
    effective_items = [item for item in evidence_items if item.id not in aggregated_from]
    if any(item.confidence == "ambiguous" for item in effective_items):
        return "ambiguous_evidence_confidence"
    deterministic = [item for item in effective_items if item.confidence == "deterministic"]
    if len(deterministic) <= 1:
        return None
    normalized_payloads = {
        json.dumps(item.normalized_result, sort_keys=True, default=str)
        for item in deterministic
    }
    if len(normalized_payloads) > 1:
        return "conflicting_deterministic_evidence"
    return None


def _typed_failure_reason(evidence: EvidenceLedgerEntry) -> str | None:
    status = str(
        evidence.normalized_result.get("status_code")
        or evidence.normalized_result.get("status")
        or evidence.diagnostic_metadata.get("status")
        or ""
    ).lower()
    if evidence.source_type == "diagnostic":
        return str(evidence.diagnostic_metadata.get("reason") or "diagnostic_evidence")
    if evidence.normalized_result.get("error"):
        return "tool_error"
    if evidence.diagnostic_metadata.get("error"):
        return "tool_error"
    if status in {"failed", "failure", "error", "tool_failed"}:
        return status
    return None


def _has_explicit_no_match(evidence: EvidenceLedgerEntry) -> bool:
    result = evidence.normalized_result
    return (
        result.get("no_match") is True
        or str(result.get("match_status") or "").lower() == "no_match"
        or str(result.get("status") or "").lower() == "no_match"
    )


def _typed_fields(result: Mapping[str, Any]) -> dict[str, Any]:
    fields = result.get("fields")
    if isinstance(fields, Mapping):
        return dict(fields)
    data = result.get("data")
    if isinstance(data, Mapping):
        return {
            str(key): value
            for key, value in data.items()
            if key not in _RESULT_META_FIELDS
        }
    return {
        str(key): value
        for key, value in result.items()
        if key not in _RESULT_META_FIELDS
    }


def _typed_rows(result: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    for key in ("rows", "items", "results", "records"):
        value = result.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            rows: list[dict[str, Any]] = []
            for item in value:
                if not isinstance(item, Mapping):
                    return None
                row_fields = item.get("fields")
                rows.append(dict(row_fields if isinstance(row_fields, Mapping) else item))
            return rows
    data = result.get("data")
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        rows = []
        for item in data:
            if not isinstance(item, Mapping):
                return None
            rows.append(dict(item))
        return rows
    return None


def _expected_entity_id(requirement: RequirementLedgerEntry) -> tuple[str | None, Any]:
    entity = requirement.entity
    preferred_keys = []
    if entity:
        preferred_keys.append(f"{entity}_id")
    preferred_keys.extend(["id", "machine_ref"])
    preferred_keys.extend(key for key in requirement.constraints if key.endswith("_id"))
    for key in dict.fromkeys(preferred_keys):
        value = requirement.constraints.get(key)
        if value not in (None, "", [], {}):
            return key, value
    return None, None


def _expected_entity_ids(requirement: RequirementLedgerEntry) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()
    entity = requirement.entity
    preferred_keys = []
    if entity:
        preferred_keys.append(f"{entity}_id")
    preferred_keys.extend(["id", "machine_ref"])
    preferred_keys.extend(key for key in requirement.constraints if key.endswith("_id"))
    for key in dict.fromkeys(preferred_keys):
        value = requirement.constraints.get(key)
        if value in (None, "", [], {}):
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            marker = str(candidate)
            if marker in seen:
                continue
            seen.add(marker)
            values.append(candidate)
    return values


def _actual_entity_id(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    fields: Mapping[str, Any],
) -> Any:
    result = evidence.normalized_result
    if result.get("entity_id") not in (None, ""):
        return result.get("entity_id")
    expected_id_key, _expected_id = _expected_entity_id(requirement)
    candidate_keys = []
    if expected_id_key:
        candidate_keys.append(expected_id_key)
    if requirement.entity:
        candidate_keys.append(f"{requirement.entity}_id")
    candidate_keys.append("id")
    for key in dict.fromkeys(candidate_keys):
        if key in fields:
            return fields[key]
        if key in result:
            return result[key]
    return None


def _row_entity_id(requirement: RequirementLedgerEntry, row: Mapping[str, Any]) -> Any:
    candidate_keys = []
    if requirement.entity:
        candidate_keys.append(f"{requirement.entity}_id")
    candidate_keys.extend(["entity_id", "id", "machine_ref"])
    candidate_keys.extend(key for key in requirement.constraints if key.endswith("_id"))
    for key in dict.fromkeys(candidate_keys):
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _identity_field_keys(requirement: RequirementLedgerEntry) -> set[str]:
    keys = {"id", "entity_id", "machine_ref"}
    if requirement.entity:
        keys.add(f"{requirement.entity}_id")
    keys.update(key for key in requirement.constraints if key.endswith("_id"))
    return keys


def _locked_constraint_checks(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    *,
    fields: Mapping[str, Any],
    rows: list[dict[str, Any]] | None,
) -> list[SatisfactionCheck]:
    checks: list[SatisfactionCheck] = []
    for locked in requirement.locked_constraints:
        if locked == "requested_fields":
            continue
        expected = _locked_value(requirement, locked)
        if locked in {
            "conditional_branches",
            "preview_before_apply",
            "requires_approval",
            "safety_constraints",
            "sort_by",
            "sort_dir",
            "limit",
        }:
            continue
        if expected in (None, "", [], {}):
            continue
        actual = _actual_value_for_locked_constraint(requirement, evidence, locked, fields=fields, rows=rows)
        checks.append(
            _check(
                f"locked_constraint:{locked}",
                expected=expected,
                actual=actual,
                passed=_constraint_actual_matches(expected, actual),
                evidence_ref=evidence.id,
            )
        )
    return checks


def _actual_value_for_locked_constraint(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    locked: str,
    *,
    fields: Mapping[str, Any],
    rows: list[dict[str, Any]] | None,
) -> Any:
    if locked.endswith("_id") or locked in {"id", "machine_ref"}:
        return _actual_entity_id(requirement, evidence, fields)
    if rows is not None:
        applied_filters = _evidence_applied_filters(evidence)
        if locked in applied_filters:
            return applied_filters[locked]
        return sorted({row.get(locked) for row in rows})
    if locked in fields:
        return fields[locked]
    return evidence.normalized_result.get(locked)


def _requested_fields_check(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    *,
    fields: Mapping[str, Any],
) -> SatisfactionCheck:
    expected = list(requirement.requested_fields)
    actual = list(fields.keys())
    if not expected:
        return _check(
            "requested_fields",
            expected=[],
            actual=actual,
            passed=bool(actual),
            evidence_ref=evidence.id,
            message="No explicit requested fields; typed fields must still be present.",
        )
    identity_extras = _identity_field_keys(requirement).difference(expected)
    observation_fields = requirement.constraints.get("observation_fields")
    observation_extras = (
        {str(field) for field in observation_fields if str(field)}
        if isinstance(observation_fields, list)
        else set()
    )
    actual_for_pass = [
        field
        for field in actual
        if field not in identity_extras and field not in observation_extras
    ]
    return _check(
        "requested_fields",
        expected=expected,
        actual=actual,
        passed=set(actual_for_pass) == set(expected),
        evidence_ref=evidence.id,
    )


def _collection_requested_fields_check(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    rows: list[dict[str, Any]],
) -> SatisfactionCheck:
    expected = list(requirement.requested_fields)
    actual = sorted({str(key) for row in rows for key in row.keys()})
    if not expected:
        return _check(
            "requested_fields",
            expected=[],
            actual=actual,
            passed=bool(actual) or not rows,
            evidence_ref=evidence.id,
        )
    supporting_fields = _identity_field_keys(requirement)
    sort_by = requirement.constraints.get("sort_by")
    if sort_by not in (None, "", [], {}):
        supporting_fields.add(str(sort_by))
    for key, value in requirement.constraints.items():
        if key in _NON_FILTER_CONSTRAINTS or value in (None, "", [], {}):
            continue
        supporting_fields.add(str(key))
    actual_for_pass = [field for field in actual if field not in supporting_fields.difference(expected)]
    return _check(
        "requested_fields",
        expected=expected,
        actual=actual,
        passed=set(actual_for_pass) == set(expected),
        evidence_ref=evidence.id,
    )


def _multi_status_requested_fields_check(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    rows: list[dict[str, Any]],
) -> SatisfactionCheck:
    expected = list(requirement.requested_fields)
    identity_fields = _identity_field_keys(requirement)
    actual = sorted({str(key) for row in rows for key in row.keys()})
    if not expected:
        return _check(
            "requested_fields",
            expected=[],
            actual=actual,
            passed=bool(actual) or not rows,
            evidence_ref=evidence.id,
        )
    actual_for_pass = [field for field in actual if field not in identity_fields.difference(expected)]
    return _check(
        "requested_fields",
        expected=expected,
        actual=actual,
        passed=set(actual_for_pass) == set(expected),
        evidence_ref=evidence.id,
    )


def _conditional_branch_checks(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    rows: list[dict[str, Any]],
) -> list[SatisfactionCheck]:
    raw_branches = requirement.constraints.get("conditional_branches")
    if not isinstance(raw_branches, list):
        return []

    supporting = _conditional_supporting_evidence(evidence)
    checks: list[SatisfactionCheck] = []
    for branch in raw_branches:
        if not isinstance(branch, Mapping):
            continue
        field = str(branch.get("condition_field") or "")
        value = branch.get("condition_value")
        matched_rows = [row for row in rows if _same_value(value, row.get(field))]
        if not matched_rows:
            checks.append(
                _check(
                    "conditional_branch:typed_explanation",
                    expected={field: value, "required_evidence": branch.get("required_evidence")},
                    actual={"matching_row_count": 0, "planner_continuation_required": False},
                    actual_count=0,
                    passed=True,
                    evidence_ref=evidence.id,
                    message="Conditional branch did not trigger because no returned row matched the condition.",
                )
            )
            continue

        matched_ids = {
            str(_row_entity_id(requirement, row))
            for row in matched_rows
            if _row_entity_id(requirement, row) not in (None, "")
        }
        explained_ids = {
            str(item.get("entity_id") or item.get("row_id") or item.get("id"))
            for item in supporting
            if isinstance(item, Mapping) and (item.get("reason") or item.get("explanation"))
        }
        passed = bool(matched_ids) and matched_ids.issubset(explained_ids)
        checks.append(
            _check(
                "conditional_branch:typed_explanation",
                expected={
                    "condition": {field: value},
                    "matched_entity_ids": sorted(matched_ids),
                    "required_evidence": branch.get("required_evidence"),
                },
                actual={
                    "explained_entity_ids": sorted(explained_ids),
                    "planner_continuation_required": bool(matched_rows),
                },
                actual_count=len(matched_rows),
                passed=passed,
                evidence_ref=evidence.id,
            )
        )
    return checks


def _conditional_supporting_evidence(evidence: EvidenceLedgerEntry) -> list[Mapping[str, Any]]:
    for container in (
        evidence.normalized_result.get("supporting_evidence"),
        evidence.diagnostic_metadata.get("conditional_branch_evidence"),
    ):
        if isinstance(container, Mapping):
            raw_items = container.get("conditional_branches") or container.get("explanations")
            if isinstance(raw_items, Sequence) and not isinstance(raw_items, (str, bytes, bytearray)):
                return [item for item in raw_items if isinstance(item, Mapping)]
        if isinstance(container, Sequence) and not isinstance(container, (str, bytes, bytearray)):
            return [item for item in container if isinstance(item, Mapping)]
    return []


def _filter_checks(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    rows: list[dict[str, Any]],
) -> list[SatisfactionCheck]:
    checks: list[SatisfactionCheck] = []
    applied_filters = _evidence_applied_filters(evidence)
    for key, expected in _filter_constraints(requirement).items():
        if all(key in row for row in rows):
            actual_values: Any = [row.get(key) for row in rows]
            passed = all(_same_value(expected, value) for value in actual_values)
        elif key in applied_filters:
            actual_values = applied_filters[key]
            passed = _same_value(expected, actual_values)
        else:
            actual_values = [row.get(key) for row in rows]
            passed = False
        checks.append(
            _check(
                f"filter_match:{key}",
                expected=expected,
                actual=actual_values,
                passed=passed,
                evidence_ref=evidence.id,
            )
        )
    return checks


def _evidence_applied_filters(evidence: EvidenceLedgerEntry) -> dict[str, Any]:
    filters = evidence.normalized_result.get("applied_filters")
    return dict(filters) if isinstance(filters, Mapping) else {}


def _filter_constraints(requirement: RequirementLedgerEntry) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    for key, value in requirement.constraints.items():
        if key in _NON_FILTER_CONSTRAINTS or key.startswith("new_") or key.endswith("_id") or key == "id":
            continue
        if value not in (None, "", [], {}):
            filters[key] = value
    return filters


def _sort_check(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    rows: list[dict[str, Any]],
) -> SatisfactionCheck:
    sort_by = requirement.constraints.get("sort_by")
    if not sort_by:
        return _check("sort_match", expected=None, actual=None, passed=True, evidence_ref=evidence.id)
    sort_dir = str(requirement.constraints.get("sort_dir") or "asc").lower()
    values = [row.get(str(sort_by)) for row in rows]
    comparable = [_sort_value(value) for value in values]
    expected = sorted(comparable, reverse=sort_dir == "desc")
    return _check(
        "sort_match",
        expected={"sort_by": sort_by, "sort_dir": sort_dir},
        actual=values,
        passed=comparable == expected,
        evidence_ref=evidence.id,
    )


def _limit_check(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    rows: list[dict[str, Any]],
) -> SatisfactionCheck:
    limit = requirement.constraints.get("limit")
    if limit is None:
        return _check("limit_match", expected=None, actual_count=len(rows), passed=True, evidence_ref=evidence.id)
    try:
        expected_limit = int(limit)
    except (TypeError, ValueError):
        expected_limit = -1
    return _check(
        "limit_match",
        expected=expected_limit,
        actual_count=len(rows),
        actual=len(rows),
        passed=expected_limit >= 0 and len(rows) <= expected_limit,
        evidence_ref=evidence.id,
    )


def _sort_value(value: Any) -> tuple[str, str]:
    if value is None:
        return ("", "")
    if isinstance(value, (int, float)):
        return ("number", f"{value:020.8f}")
    return ("string", str(value))


def _same_value(expected: Any, actual: Any) -> bool:
    if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes, bytearray)):
        return all(_same_value(expected, item) for item in actual)
    return str(expected) == str(actual)


def _constraint_actual_matches(expected: Any, actual: Any) -> bool:
    if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes, bytearray)):
        return all(_same_value(expected, item) for item in actual)
    return _same_value(expected, actual)


def _locked_value(requirement: RequirementLedgerEntry, locked: str) -> Any:
    if locked == "requested_fields":
        return list(requirement.requested_fields)
    return requirement.constraints.get(locked)


def _validate_locked_constraints_preserved(
    state: PlannerOwnedLoopV2State,
    issues: list[FinalValidationIssue],
) -> None:
    ledger = state.requirement_ledger
    sketch = state.requirement_sketch
    if ledger is None or sketch is None:
        return
    current_by_id = {req.id: req for req in ledger.requirements}
    for original in sketch.requirements:
        current = current_by_id.get(original.id)
        if current is None:
            issues.append(
                FinalValidationIssue(
                    issue="locked_requirement_dropped",
                    requirement_id=original.id,
                )
            )
            continue
        for locked in original.locked_constraints:
            if locked not in current.locked_constraints:
                issues.append(
                    FinalValidationIssue(
                        issue="locked_constraint_dropped",
                        requirement_id=current.id,
                        check=f"locked_constraint:{locked}",
                        expected=locked,
                        actual=current.locked_constraints,
                    )
                )
                continue
            expected = _sketch_locked_value(original, locked)
            actual = _locked_value(current, locked)
            if not _locked_values_equal(expected, actual):
                issues.append(
                    FinalValidationIssue(
                        issue="locked_constraint_value_changed",
                        requirement_id=current.id,
                        check=f"locked_constraint:{locked}",
                        expected=expected,
                        actual=actual,
                    )
                )


def _sketch_locked_value(original: Any, locked: str) -> Any:
    if locked == "requested_fields":
        return list(original.requested_fields)
    return original.constraints.get(locked)


def _locked_values_equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, list) or isinstance(actual, list):
        return [str(item) for item in (expected or [])] == [str(item) for item in (actual or [])]
    return expected == actual


def _validate_typed_evidence(
    requirement: RequirementLedgerEntry,
    evidence: EvidenceLedgerEntry,
    issues: list[FinalValidationIssue],
) -> None:
    if _evidence_marked_stale(evidence):
        issues.append(
            FinalValidationIssue(
                issue="stale_evidence_not_finalizable",
                requirement_id=requirement.id,
                evidence_ref=evidence.id,
                expected="active_revision_evidence",
                actual=evidence.diagnostic_metadata,
            )
        )
    if requirement.status == "satisfied" and evidence.confidence != "deterministic":
        issues.append(
            FinalValidationIssue(
                issue="satisfied_evidence_not_deterministic",
                requirement_id=requirement.id,
                evidence_ref=evidence.id,
                expected="deterministic",
                actual=evidence.confidence,
            )
        )
    if requirement.status == "satisfied" and is_historical_legacy_rag_route_evidence(evidence):
        issues.append(
            FinalValidationIssue(
                issue=historical_legacy_rag_route_cannot_satisfy_issue(),
                requirement_id=requirement.id,
                evidence_ref=evidence.id,
            )
        )
    if evidence.source_type == "api_tool" and not evidence.normalized_result:
        issues.append(
            FinalValidationIssue(
                issue="api_evidence_missing_typed_result",
                requirement_id=requirement.id,
                evidence_ref=evidence.id,
            )
        )
    if evidence.source_type == "rag_tool" and not evidence.citations:
        issues.append(
            FinalValidationIssue(
                issue="rag_evidence_missing_typed_citations",
                requirement_id=requirement.id,
                evidence_ref=evidence.id,
            )
        )


def _evidence_marked_stale(evidence: EvidenceLedgerEntry) -> bool:
    metadata = evidence.diagnostic_metadata or {}
    return (
        metadata.get("active_revision_satisfaction") is False
        or metadata.get("stale_after_graph_revision") is True
        or metadata.get("stale_after_graph_replan") is True
        or metadata.get("stale_after_user_interrupt") is True
    )


def _final_validation_result(
    state: PlannerOwnedLoopV2State,
    issues: list[FinalValidationIssue],
    *,
    checked_requirement_ids: list[str],
) -> FinalValidationResult:
    result = FinalValidationResult(
        status="failed" if issues else "passed",
        issues=issues,
        checked_requirement_ids=checked_requirement_ids,
        diagnostics={
            "issue_count": len(issues),
            "non_success_terminal_requirements": [
                req.id
                for req in (state.requirement_ledger.requirements if state.requirement_ledger else [])
                if req.required and req.status in {"impossible", "blocked", "failed", "skipped"}
            ],
        },
    )
    state.final_validation_result = result
    state.execution_trace.final_validator_status = result.status
    state.execution_trace.diagnostics["final_validation"] = result.model_dump(mode="json")
    return result
