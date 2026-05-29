from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import Field

from .v2_agent_state import (
    GraphToolCall,
    PlannerDecisionRecord,
    PlannerOwnedAgentGraphState,
    validate_graph_state_final_state,
)
from .v2_contracts import (
    CapabilityNeed,
    EvidenceLedgerEntry,
    FinalValidationResult,
    HydratedToolCard,
    RequirementLedger,
    RequirementLedgerEntry,
    V2ContractModel,
)
from .v2_dependency_scheduler import (
    MAX_PARALLEL_READ_BATCH_SIZE,
    build_dependency_plan,
    dependency_allows_requirement_action,
    dependency_allows_tool_call,
    dependency_rejection_reason,
    requirement_ids_for_parallel_read_batch,
)
from .v2_failed_tool_memory import (
    failed_tool_calls_for_requirement,
    same_tool_call_signature,
    tool_call_matches_failed_memory,
    tool_call_signature,
)


SUPPORTED_PLANNER_DECISION_KINDS: tuple[str, ...] = (
    "retrieve_tools",
    "choose_tool",
    "execute_tool",
    "execute_parallel_read_batch",
    "request_approval",
    "revise_requirements",
    "request_clarification",
    "finalize",
    "fail",
)

_DECISION_KINDS_REQUIRING_REQUIREMENT = {
    "retrieve_tools",
    "choose_tool",
    "execute_tool",
    "request_approval",
    "request_clarification",
}
_ACTIVE_REQUIREMENT_STATUSES = {"open", "blocked"}
_PLANNER_PROPOSER_DIAGNOSTIC_KEY = "planner_proposer"
_DECISION_KINDS_WITH_SELECTED_TOOL_CALLS = {
    "choose_tool",
    "execute_tool",
    "execute_parallel_read_batch",
    "request_approval",
}


class PlannerDecisionValidationError(ValueError):
    """Raised when a planner decision cannot authorize a graph transition."""

    def __init__(self, message: str, *, diagnostics: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


class PlannerDecisionSubmission(V2ContractModel):
    """Serializable decision gate input.

    Most decisions can be validated against the current graph state alone.
    Requirement-revision decisions carry a proposed ledger so locked
    constraints can be checked before the state changes.
    """

    decision: PlannerDecisionRecord
    proposed_requirement_ledger: RequirementLedger | None = None
    candidate_tool_calls: list[GraphToolCall] = Field(default_factory=list)


class PlannerDecisionValidationResult(V2ContractModel):
    accepted: Literal[True] = True
    decision_id: str = Field(min_length=1)
    decision_kind: str = Field(min_length=1)
    author: str = Field(min_length=1)
    ledger_revision: int = Field(ge=1)
    deterministic_guard: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def validate_planner_decision(
    state: PlannerOwnedAgentGraphState,
    submission: PlannerDecisionSubmission | PlannerDecisionRecord,
) -> PlannerDecisionValidationResult:
    """Validate that a decision can authorize its requested next transition."""

    normalized = _as_submission(submission)
    decision = normalized.decision
    errors: list[str] = []
    error_diagnostics: dict[str, Any] = {}

    _validate_decision_shape(state, normalized, errors)
    _validate_planner_author_has_proposer_diagnostics(normalized, errors)
    _validate_locked_constraints_preserved(state, normalized, errors)
    _validate_kind_specific_transition(state, normalized, errors)
    _validate_dependency_plan_readiness(state, normalized, errors, error_diagnostics)
    _validate_failed_tool_memory_filtered_selection(state, normalized, errors, error_diagnostics)
    _validate_deterministic_guard_authority(state, normalized, errors)

    if errors:
        raise PlannerDecisionValidationError("; ".join(errors), diagnostics=error_diagnostics)

    diagnostics: dict[str, Any] = {
        "validated_by": "planner_owned_agent_graph_decision_gate",
        "decision_kind": decision.decision_kind,
        "author": decision.author,
    }
    if normalized.proposed_requirement_ledger is not None:
        diagnostics["proposed_ledger_revision"] = normalized.proposed_requirement_ledger.revision

    return PlannerDecisionValidationResult(
        decision_id=decision.decision_id,
        decision_kind=decision.decision_kind,
        author=decision.author,
        ledger_revision=decision.ledger_revision,
        deterministic_guard=decision.author == "deterministic_guard",
        diagnostics=diagnostics,
    )


def record_planner_decision(
    state: PlannerOwnedAgentGraphState,
    submission: PlannerDecisionSubmission | PlannerDecisionRecord,
) -> PlannerDecisionValidationResult:
    """Validate and persist a planner decision on graph state.

    This function records the authorization only. Later graph phases remain
    responsible for retrieval, execution, evidence observation, and rendering.
    """

    normalized = _as_submission(submission)
    result = validate_planner_decision(state, normalized)
    state.planner_decisions.append(normalized.decision)
    return result


def _as_submission(submission: PlannerDecisionSubmission | PlannerDecisionRecord) -> PlannerDecisionSubmission:
    if isinstance(submission, PlannerDecisionSubmission):
        return submission
    return PlannerDecisionSubmission(decision=submission)


def _validate_decision_shape(
    state: PlannerOwnedAgentGraphState,
    submission: PlannerDecisionSubmission,
    errors: list[str],
) -> None:
    decision = submission.decision
    if decision.decision_kind not in SUPPORTED_PLANNER_DECISION_KINDS:
        errors.append(f"unsupported planner decision kind: {decision.decision_kind}")

    if decision.ledger_revision != state.requirement_ledger.revision:
        errors.append(
            "planner decision ledger_revision must match current requirement ledger revision "
            f"({decision.ledger_revision} != {state.requirement_ledger.revision})"
        )

    requirement = _requirement_by_id(state, decision.requirement_id)
    if decision.decision_kind in _DECISION_KINDS_REQUIRING_REQUIREMENT and requirement is None:
        errors.append("planner decision must target an existing requirement")

    if decision.capability_need is not None:
        _validate_capability_need_matches_requirement(decision.capability_need, decision.requirement_id, errors)

    evidence_ids = {item.id for item in state.evidence_ledger.evidence}
    missing_evidence = [evidence_ref for evidence_ref in decision.evidence_refs if evidence_ref not in evidence_ids]
    if missing_evidence:
        errors.append(f"planner decision references missing evidence: {', '.join(sorted(missing_evidence))}")


def _validate_planner_author_has_proposer_diagnostics(
    submission: PlannerDecisionSubmission,
    errors: list[str],
) -> None:
    decision = submission.decision
    if decision.author != "planner":
        return
    diagnostics = decision.diagnostics.get(_PLANNER_PROPOSER_DIAGNOSTIC_KEY)
    if not isinstance(diagnostics, Mapping) or diagnostics.get("proposer_seam") is not True:
        errors.append("planner-authored decisions require planner proposer diagnostics")
        return
    if not diagnostics.get("adapter"):
        errors.append("planner proposer diagnostics must name the adapter")
    if diagnostics.get("bounded_state_view") is not True:
        errors.append("planner proposer diagnostics must prove bounded state view")
    if diagnostics.get("full_openapi_catalog_visible") is not False:
        errors.append("planner proposer must not receive the full OpenAPI catalog")


def _validate_capability_need_matches_requirement(
    capability_need: CapabilityNeed,
    requirement_id: str | None,
    errors: list[str],
) -> None:
    if requirement_id is not None and capability_need.requirement_id not in {None, requirement_id}:
        errors.append("capability need must reference the planner decision requirement")


def _validate_locked_constraints_preserved(
    state: PlannerOwnedAgentGraphState,
    submission: PlannerDecisionSubmission,
    errors: list[str],
) -> None:
    decision = submission.decision
    proposed = submission.proposed_requirement_ledger

    if decision.decision_kind == "revise_requirements" and proposed is None:
        errors.append("revise_requirements decision must include a proposed requirement ledger")
        return
    if proposed is None:
        return

    if proposed.revision <= state.requirement_ledger.revision:
        errors.append("proposed requirement ledger revision must advance the current ledger revision")

    proposed_by_id = {requirement.id: requirement for requirement in proposed.requirements}
    for current in state.requirement_ledger.requirements:
        if current.id not in proposed_by_id:
            errors.append(f"existing requirement was dropped: {current.id}")
        if not current.locked_constraints:
            continue
        replacement = proposed_by_id.get(current.id)
        if replacement is None:
            errors.append(f"locked requirement was dropped: {current.id}")
            continue
        _validate_requirement_locks(current, replacement, errors)

    _validate_child_requirement_expansion(state, proposed, errors)


def _validate_requirement_locks(
    current: RequirementLedgerEntry,
    proposed: RequirementLedgerEntry,
    errors: list[str],
) -> None:
    for locked in current.locked_constraints:
        if locked not in proposed.locked_constraints:
            errors.append(f"locked constraint was dropped for {current.id}: {locked}")
            continue
        expected = _locked_value(current, locked)
        actual = _locked_value(proposed, locked)
        if not _json_equal(expected, actual):
            errors.append(
                "locked constraint value changed for "
                f"{current.id}:{locked} expected={expected!r} actual={actual!r}"
            )


def _validate_child_requirement_expansion(
    state: PlannerOwnedAgentGraphState,
    proposed: RequirementLedger,
    errors: list[str],
) -> None:
    current_by_id = {requirement.id: requirement for requirement in state.requirement_ledger.requirements}
    proposed_by_id = {requirement.id: requirement for requirement in proposed.requirements}
    added = [requirement for requirement in proposed.requirements if requirement.id not in current_by_id]
    if not added:
        return

    for requirement in added:
        parent_id = requirement.parent_requirement_id
        if not parent_id:
            errors.append(f"new requirement additions must be child requirements: {requirement.id}")
            continue
        parent = current_by_id.get(parent_id)
        if parent is None:
            errors.append(f"child requirement parent is missing: {requirement.id}")
            continue
        if parent.parent_requirement_id is not None:
            errors.append(f"child requirement depth exceeds maximum: {requirement.id}")
        if parent.status not in _ACTIVE_REQUIREMENT_STATUSES:
            errors.append(f"child requirement parent is not active: {requirement.id}")
        _validate_child_requirement_id(parent, requirement, proposed_by_id, errors)
        _validate_child_requirement_locks(parent, requirement, errors)
        _validate_child_requirement_justification(state, parent, requirement, errors)


def _validate_child_requirement_id(
    parent: RequirementLedgerEntry,
    child: RequirementLedgerEntry,
    proposed_by_id: Mapping[str, RequirementLedgerEntry],
    errors: list[str],
) -> None:
    prefix = f"{parent.id}."
    if not child.id.startswith(prefix):
        errors.append(f"child requirement id must be scoped to parent: {child.id}")
        return
    suffix = child.id[len(prefix):]
    if suffix not in {"a", "b"}:
        errors.append(f"child requirement id exceeds bounded child window: {child.id}")
        return
    child_ids = [
        requirement.id
        for requirement in proposed_by_id.values()
        if requirement.parent_requirement_id == parent.id
    ]
    if len(set(child_ids)) > 2:
        errors.append(f"child requirement limit exceeded for parent: {parent.id}")


def _validate_child_requirement_locks(
    parent: RequirementLedgerEntry,
    child: RequirementLedgerEntry,
    errors: list[str],
) -> None:
    for locked in parent.locked_constraints:
        if locked not in child.constraints:
            continue
        expected = _locked_value(parent, locked)
        actual = _locked_value(child, locked)
        if not _json_equal(expected, actual):
            errors.append(
                "child requirement contradicts parent locked constraint "
                f"{parent.id}:{locked} expected={expected!r} actual={actual!r}"
            )
    if child.requirement_type == "mutation_request":
        requires_approval = child.constraints.get("requires_approval") is True
        if not requires_approval or "requires_approval" not in child.locked_constraints:
            errors.append("child mutation requirements must remain approval-gated")


def _validate_child_requirement_justification(
    state: PlannerOwnedAgentGraphState,
    parent: RequirementLedgerEntry,
    child: RequirementLedgerEntry,
    errors: list[str],
) -> None:
    evidence_items = _child_justifying_evidence(state, parent, child, errors)
    missing_reasons = _child_justifying_missing_reasons(state, parent, child, errors)
    if not evidence_items and not missing_reasons:
        errors.append("child requirement expansion requires evidence or missing-evidence justification")
        return
    if not _child_supported_by_justification(parent, child, evidence_items=evidence_items, missing_reasons=missing_reasons):
        errors.append(f"child requirement is not supported by current evidence gap: {child.id}")


def _child_justifying_evidence(
    state: PlannerOwnedAgentGraphState,
    parent: RequirementLedgerEntry,
    child: RequirementLedgerEntry,
    errors: list[str],
) -> list[EvidenceLedgerEntry]:
    refs = [str(ref).strip() for ref in child.derived_from_evidence_refs if str(ref).strip()]
    evidence_by_id = {evidence.id: evidence for evidence in state.evidence_ledger.evidence}
    evidence_items: list[EvidenceLedgerEntry] = []
    for ref in refs:
        evidence = evidence_by_id.get(ref)
        if evidence is None:
            errors.append(f"child requirement references missing evidence: {ref}")
            continue
        if evidence.requirement_id != parent.id:
            errors.append(f"child requirement evidence does not belong to parent: {ref}")
            continue
        if not _evidence_can_justify_child_expansion(state, evidence):
            errors.append(f"child requirement evidence is not active for current ledger revision: {ref}")
            continue
        evidence_items.append(evidence)
    return evidence_items


def _evidence_can_justify_child_expansion(
    state: PlannerOwnedAgentGraphState,
    evidence: EvidenceLedgerEntry,
) -> bool:
    metadata = dict(evidence.diagnostic_metadata or {})
    if metadata.get("active_revision_satisfaction") is False:
        return False
    if (
        metadata.get("stale_after_graph_revision") is True
        or metadata.get("stale_after_graph_replan") is True
        or metadata.get("stale_after_user_interrupt") is True
    ):
        return False
    requirement = _requirement_by_id(state, evidence.requirement_id)
    if requirement is None or requirement.status == "superseded":
        return False

    current_revision = state.requirement_ledger.revision
    carried_to = _coerce_positive_int(metadata.get("carried_forward_to_ledger_revision"))
    if carried_to == current_revision:
        return True
    superseded_by = _coerce_positive_int(metadata.get("superseded_by_ledger_revision"))
    if superseded_by is not None and superseded_by <= current_revision:
        return False
    return True


def _child_justifying_missing_reasons(
    state: PlannerOwnedAgentGraphState,
    parent: RequirementLedgerEntry,
    child: RequirementLedgerEntry,
    errors: list[str],
) -> list[Mapping[str, Any]]:
    declared = [
        dict(reason)
        for reason in child.derived_from_missing_reasons
        if isinstance(reason, Mapping)
    ]
    if not declared:
        return []
    known = _known_missing_evidence_reasons(state)
    matched: list[Mapping[str, Any]] = []
    for reason in declared:
        if str(reason.get("requirement_id") or "") != parent.id:
            errors.append(f"child requirement missing-evidence reason does not belong to parent: {child.id}")
            continue
        known_match = next((known_reason for known_reason in known if _json_equal(reason, known_reason)), None)
        if known_match is None:
            errors.append(f"child requirement missing-evidence reason is not current: {child.id}")
            continue
        matched.append(known_match)
    return matched


def _known_missing_evidence_reasons(state: PlannerOwnedAgentGraphState) -> list[Mapping[str, Any]]:
    diagnostics = state.execution_trace.diagnostics
    reasons: list[Mapping[str, Any]] = []
    for key in ("satisfaction", "replan_spine"):
        section = diagnostics.get(key)
        if not isinstance(section, Mapping):
            continue
        raw_reasons = section.get("missing_evidence_reasons")
        if isinstance(raw_reasons, list):
            reasons.extend(dict(reason) for reason in raw_reasons if isinstance(reason, Mapping))
    return reasons


def _child_supported_by_justification(
    parent: RequirementLedgerEntry,
    child: RequirementLedgerEntry,
    *,
    evidence_items: list[EvidenceLedgerEntry],
    missing_reasons: list[Mapping[str, Any]],
) -> bool:
    if child.source_of_truth not in {parent.source_of_truth, "unknown"}:
        if not any(evidence.source_of_truth == child.source_of_truth for evidence in evidence_items):
            return False
    if evidence_items and child.entity == parent.entity and child.source_of_truth == parent.source_of_truth:
        return True
    if any(_evidence_supports_child_requirement(evidence, child) for evidence in evidence_items):
        return True
    return any(_missing_reason_supports_child_requirement(reason, child) for reason in missing_reasons)


def _evidence_supports_child_requirement(
    evidence: EvidenceLedgerEntry,
    child: RequirementLedgerEntry,
) -> bool:
    evidence_values = _flatten_mapping_values(evidence.normalized_result)
    for key, value in child.constraints.items():
        if key in {"requires_approval"} or value in (None, "", [], {}):
            continue
        if _constraint_value_supported_by_values(key, value, evidence_values):
            return True
    entity = str(child.entity or "").strip()
    return bool(entity and any(key.endswith(f"{entity}_id") for key, _value in evidence_values))


def _missing_reason_supports_child_requirement(
    reason: Mapping[str, Any],
    child: RequirementLedgerEntry,
) -> bool:
    reason_values = _flatten_mapping_values(reason)
    for key, value in child.constraints.items():
        if key in {"requires_approval"} or value in (None, "", [], {}):
            continue
        if _constraint_value_supported_by_values(key, value, reason_values):
            return True
    entity = str(child.entity or "").strip()
    return bool(entity and any(key.endswith(f"{entity}_id") for key, _value in reason_values))


def _constraint_value_supported_by_values(
    key: str,
    value: Any,
    evidence_values: list[tuple[str, Any]],
) -> bool:
    comparable = _json_key(value)
    for evidence_key, evidence_value in evidence_values:
        if evidence_key != key and not evidence_key.endswith(f"_{key}"):
            continue
        if _json_key(evidence_value) == comparable:
            return True
    return False


def _flatten_mapping_values(value: Any, *, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        flattened: list[tuple[str, Any]] = []
        for key, child in value.items():
            child_key = str(key)
            flattened.extend(_flatten_mapping_values(child, prefix=child_key))
        return flattened
    if isinstance(value, list):
        flattened = []
        for item in value:
            flattened.extend(_flatten_mapping_values(item, prefix=prefix))
        return flattened
    return [(prefix, value)] if prefix else []


def _validate_kind_specific_transition(
    state: PlannerOwnedAgentGraphState,
    submission: PlannerDecisionSubmission,
    errors: list[str],
) -> None:
    decision = submission.decision
    kind = decision.decision_kind

    if kind == "retrieve_tools":
        if decision.capability_need is None:
            errors.append("retrieve_tools decision requires a capability_need")
        return

    if kind == "choose_tool":
        calls = _selected_tool_calls(decision)
        if not calls:
            errors.append("choose_tool decision requires a selected API/RAG tool call")
            return
        cards_by_call_id: dict[str, HydratedToolCard | None] = {}
        for call in calls:
            cards_by_call_id[call.call_id] = _validate_tool_call_from_hydrated_window(
                state,
                call,
                errors,
                candidate_tool_calls=submission.candidate_tool_calls,
                require_current_candidates=decision.author == "planner",
            )
        requirement = _requirement_by_id(state, calls[0].requirement_id)
        if (
            requirement is not None
            and requirement.requirement_type == "mutation_request"
            and not any(
                card is not None and (not card.is_read_only or card.requires_approval)
                for card in cards_by_call_id.values()
            )
        ):
            errors.append(
                "approval-required mutation choose_tool requires a write or approval-gated tool"
            )
        if len(calls) > 1:
            for call in calls:
                card = cards_by_call_id.get(call.call_id)
                if card is not None and (not card.is_read_only or card.requires_approval):
                    errors.append(f"choose_tool batch cannot include mutating or approval tool: {call.tool_name}")
        return

    if kind == "execute_tool":
        call = _single_selected_tool_call(decision, errors)
        if call is not None:
            _validate_tool_call_from_hydrated_window(
                state,
                call,
                errors,
                candidate_tool_calls=submission.candidate_tool_calls,
                require_current_candidates=False,
            )
        return

    if kind == "execute_parallel_read_batch":
        calls = _selected_tool_calls(decision)
        if not calls:
            errors.append("execute_parallel_read_batch decision requires selected_tool_calls")
            return
        for call in calls:
            card = _validate_tool_call_from_hydrated_window(
                state,
                call,
                errors,
                candidate_tool_calls=submission.candidate_tool_calls,
                require_current_candidates=False,
            )
            if card is not None and (not card.is_read_only or card.requires_approval):
                errors.append(f"parallel read batch cannot include mutating or approval tool: {call.tool_name}")
        return

    if kind == "request_approval":
        call = _single_selected_tool_call(decision, errors)
        if call is not None:
            card = _validate_tool_call_from_hydrated_window(
                state,
                call,
                errors,
                candidate_tool_calls=submission.candidate_tool_calls,
                require_current_candidates=False,
            )
            if card is not None and card.is_read_only and not card.requires_approval:
                errors.append(f"request_approval requires an approval-gated tool call: {call.tool_name}")
        return

    if kind == "revise_requirements":
        return

    if kind == "request_clarification":
        requirement = _requirement_by_id(state, decision.requirement_id)
        if requirement is not None and requirement.status not in _ACTIVE_REQUIREMENT_STATUSES:
            errors.append("request_clarification can only target an active requirement")
        if not decision.reason:
            errors.append("request_clarification decision requires a reason")
        return

    if kind == "finalize":
        result = _final_validation_result_for(state)
        if result.status != "passed":
            issue_names = sorted({issue.issue for issue in result.issues})
            issue_text = ", ".join(issue_names) or "unknown_final_validation_failure"
            errors.append(f"finalize decision requires passed final validation; issues: {issue_text}")
        return

    if kind == "fail" and not decision.reason:
        errors.append("fail decision requires a reason")


def _validate_dependency_plan_readiness(
    state: PlannerOwnedAgentGraphState,
    submission: PlannerDecisionSubmission,
    errors: list[str],
    diagnostics: dict[str, Any],
) -> None:
    decision = submission.decision
    if decision.decision_kind not in {
        "retrieve_tools",
        "choose_tool",
        "execute_tool",
        "execute_parallel_read_batch",
        "request_approval",
    }:
        return

    plan = build_dependency_plan(state)
    rejected: list[dict[str, Any]] = []
    if decision.decision_kind == "retrieve_tools":
        if not dependency_allows_requirement_action(plan, decision.requirement_id):
            rejected.append(
                {
                    "requirement_id": decision.requirement_id,
                    "reason": dependency_rejection_reason(plan, decision.requirement_id),
                }
            )
    else:
        for call in _selected_tool_calls(decision):
            if dependency_allows_tool_call(plan, call):
                continue
            rejected.append(
                {
                    "requirement_id": call.requirement_id,
                    "tool_name": call.tool_name,
                    "reason": dependency_rejection_reason(plan, call.requirement_id),
                }
            )

    if decision.decision_kind == "execute_parallel_read_batch":
        calls = _selected_tool_calls(decision)
        parallel_requirement_ids = requirement_ids_for_parallel_read_batch(plan)
        if len(calls) > MAX_PARALLEL_READ_BATCH_SIZE:
            rejected.append(
                {
                    "requirement_id": decision.requirement_id,
                    "reason": (
                        "parallel read batch exceeds dependency plan max size "
                        f"({len(calls)} > {MAX_PARALLEL_READ_BATCH_SIZE})"
                    ),
                }
            )
        for call in calls:
            if call.requirement_id not in parallel_requirement_ids:
                rejected.append(
                    {
                        "requirement_id": call.requirement_id,
                        "tool_name": call.tool_name,
                        "reason": (
                            "parallel read batch requires a dependency plan ready group "
                            f"for requirement {call.requirement_id}"
                        ),
                    }
                )

    if not rejected:
        return

    diagnostics["dependency_plan"] = {
        "ledger_revision": plan.ledger_revision,
        "rejected": rejected,
        "requirements": [item.model_dump(mode="json") for item in plan.requirements],
    }
    errors.append(
        "planner decision selected work that is not dependency-ready: "
        + "; ".join(item["reason"] for item in rejected)
    )


def _validate_failed_tool_memory_filtered_selection(
    state: PlannerOwnedAgentGraphState,
    submission: PlannerDecisionSubmission,
    errors: list[str],
    diagnostics: dict[str, Any],
) -> None:
    decision = submission.decision
    if decision.decision_kind not in _DECISION_KINDS_WITH_SELECTED_TOOL_CALLS:
        return

    selected_calls = _selected_tool_calls(decision)
    if not selected_calls or not submission.candidate_tool_calls:
        return

    rejections: list[dict[str, Any]] = []
    for requirement_id in dict.fromkeys(call.requirement_id for call in selected_calls):
        failed_calls = failed_tool_calls_for_requirement(state, requirement_id)
        if not failed_calls:
            continue
        candidate_calls = [
            call for call in submission.candidate_tool_calls if call.requirement_id == requirement_id
        ]
        if not candidate_calls:
            continue
        filtered_candidates = [
            call for call in candidate_calls if not tool_call_matches_failed_memory(call, failed_calls)
        ]
        if not filtered_candidates:
            continue
        for selected in [call for call in selected_calls if call.requirement_id == requirement_id]:
            if any(same_tool_call_signature(selected, candidate) for candidate in filtered_candidates):
                continue
            if not tool_call_matches_failed_memory(selected, failed_calls):
                continue
            rejections.append(
                {
                    "requirement_id": requirement_id,
                    "selected_tool_call": tool_call_signature(selected),
                    "filtered_candidate_tool_calls": [
                        tool_call_signature(candidate) for candidate in filtered_candidates
                    ],
                    "failed_tool_calls": [dict(call) for call in failed_calls],
                }
            )

    if not rejections:
        return

    diagnostics["failed_tool_memory"] = {
        "rejected_selected_tool_calls": rejections,
        "reason": "selected_tool_call_excluded_by_failed_tool_memory",
    }
    rejected_names = ", ".join(
        item["selected_tool_call"]["tool_name"] for item in rejections
    )
    errors.append(
        "selected tool call was excluded by failed-tool memory while a viable alternate exists: "
        f"{rejected_names}"
    )


def _validate_deterministic_guard_authority(
    state: PlannerOwnedAgentGraphState,
    submission: PlannerDecisionSubmission,
    errors: list[str],
) -> None:
    decision = submission.decision
    if decision.author != "deterministic_guard":
        return

    kind = decision.decision_kind
    if kind == "retrieve_tools":
        if decision.capability_need is None or not _state_proves_retrieval_needed(state, decision.capability_need):
            errors.append("deterministic retrieve_tools guard requires an active unmet requirement with no candidates")
        return

    if kind == "choose_tool":
        if not (
            _state_proves_single_document_tool_choice(state, decision)
            or _state_proves_bounded_read_batch_tool_choice(state, decision)
        ):
            errors.append(
                "deterministic choose_tool guard requires a bounded document tool choice or read batch"
            )
        return

    if kind == "execute_tool":
        call = decision.selected_tool_call
        if call is None or not _state_has_prior_tool_choice(state, call):
            errors.append("deterministic execute_tool guard requires a prior persisted choose_tool decision")
        return

    if kind == "execute_parallel_read_batch":
        calls = _selected_tool_calls(decision)
        if not calls or any(not _state_has_prior_tool_choice(state, call) for call in calls):
            errors.append("deterministic parallel execute guard requires prior persisted choose_tool decisions")
        return

    if kind == "finalize":
        result = _final_validation_result_for(state)
        if result.status != "passed":
            errors.append("deterministic finalize guard requires already-passed final validation")
        return

    if kind == "fail":
        final_result = state.final_validation_result
        if final_result is None or final_result.status != "failed":
            errors.append("deterministic fail guard requires an existing failed final validation result")
        return

    errors.append(f"deterministic guard cannot author {kind} without state proof")


def _single_selected_tool_call(
    decision: PlannerDecisionRecord,
    errors: list[str],
) -> GraphToolCall | None:
    calls = _selected_tool_calls(decision)
    if not calls:
        errors.append(f"{decision.decision_kind} decision requires a selected API/RAG tool call")
        return None
    if len(calls) > 1:
        errors.append(f"{decision.decision_kind} decision requires exactly one selected tool call")
        return None
    return calls[0]


def _selected_tool_calls(decision: PlannerDecisionRecord) -> list[GraphToolCall]:
    calls: list[GraphToolCall] = []
    if decision.selected_tool_call is not None:
        calls.append(decision.selected_tool_call)
    calls.extend(decision.selected_tool_calls)
    return calls


def _validate_tool_call_from_hydrated_window(
    state: PlannerOwnedAgentGraphState,
    call: GraphToolCall,
    errors: list[str],
    *,
    candidate_tool_calls: list[GraphToolCall] | None = None,
    require_current_candidates: bool = False,
) -> HydratedToolCard | None:
    requirement = _requirement_by_id(state, call.requirement_id)
    if requirement is None:
        errors.append(f"selected tool call targets missing requirement: {call.requirement_id}")
    elif requirement.status != "open":
        errors.append(f"selected tool call targets non-open requirement: {call.requirement_id}")

    _validate_tool_call_matches_current_candidates(
        call,
        candidate_tool_calls or [],
        errors,
        require_current_candidates=require_current_candidates,
    )

    if call.decision_id:
        previous = next(
            (
                decision
                for decision in state.planner_decisions
                if decision.decision_id == call.decision_id
            ),
            None,
        )
        if previous is not None and previous.ledger_revision != state.requirement_ledger.revision:
            errors.append("selected tool call comes from a previous ledger revision")

    candidate_names = {
        candidate.tool_name
        for window in state.candidate_tool_windows
        if window.requirement_id == call.requirement_id
        for candidate in window.candidates
    }
    if call.tool_name not in candidate_names:
        errors.append(f"selected tool is not in the hydrated candidate window: {call.tool_name}")

    hydrated_cards = [
        card
        for cards in state.hydrated_tool_cards
        if cards.requirement_id == call.requirement_id
        for card in cards.cards
        if card.tool_name == call.tool_name
    ]
    if not hydrated_cards:
        errors.append(f"selected tool does not have a hydrated card: {call.tool_name}")
        return None

    card = hydrated_cards[0]
    if requirement is not None:
        _validate_tool_call_locked_identity_args(call, requirement, card, errors)
    expected_call_kind = "rag_tool" if card.source_of_truth == "document_knowledge" else "api_tool"
    if call.kind != expected_call_kind:
        errors.append(
            "selected tool call kind does not match hydrated card source "
            f"({call.kind} != {expected_call_kind})"
        )
    return card


def _validate_tool_call_matches_current_candidates(
    call: GraphToolCall,
    candidate_tool_calls: list[GraphToolCall],
    errors: list[str],
    *,
    require_current_candidates: bool,
) -> None:
    if not candidate_tool_calls:
        if require_current_candidates:
            errors.append("planner choose_tool decision requires current candidate_tool_calls")
        return
    current_candidates = [
        candidate for candidate in candidate_tool_calls if candidate.requirement_id == call.requirement_id
    ]
    if not current_candidates:
        errors.append(
            "selected tool call has no current candidate tool calls for requirement: "
            f"{call.requirement_id}"
        )
        return
    if any(_same_current_candidate_call(call, candidate) for candidate in current_candidates):
        return
    errors.append(f"selected tool call does not match current candidate tool calls: {call.tool_name}")


def _same_current_candidate_call(selected: GraphToolCall, candidate: GraphToolCall) -> bool:
    if not same_tool_call_signature(selected, candidate):
        return False
    if (
        selected.candidate_window_id not in (None, "")
        and candidate.candidate_window_id not in (None, "")
        and selected.candidate_window_id != candidate.candidate_window_id
    ):
        return False
    return True


def _validate_tool_call_locked_identity_args(
    call: GraphToolCall,
    requirement: RequirementLedgerEntry,
    card: HydratedToolCard,
    errors: list[str],
) -> None:
    for locked in requirement.locked_constraints:
        if locked == "requested_fields" or locked not in requirement.constraints:
            continue
        if not _locked_constraint_is_identity(locked):
            continue
        expected = requirement.constraints.get(locked)
        if expected in (None, "", [], {}):
            continue
        candidate_arg_names = _call_arg_names_for_locked_identity(locked)
        selected_arg_names = [name for name in candidate_arg_names if name in call.args]
        for arg_name in selected_arg_names:
            actual = call.args.get(arg_name)
            if not _locked_identity_value_matches(actual, expected):
                errors.append(
                    "selected tool call args contradict locked identity constraint "
                    f"{requirement.id}:{locked} expected={expected!r} actual={actual!r}"
                )
                return
        card_identity_args = set(card.required_args) | set(card.path_params)
        if card_identity_args.intersection(candidate_arg_names) and not selected_arg_names:
            errors.append(
                "selected tool call args omit locked identity constraint "
                f"{requirement.id}:{locked}"
            )


def _locked_constraint_is_identity(locked: str) -> bool:
    normalized = str(locked or "").strip()
    return normalized in {"id", "entity_id", "record_id"} or normalized.endswith("_id") or normalized.endswith("_ref")


def _locked_identity_value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        if isinstance(actual, list):
            return all(any(_json_equal(item, expected_item) for expected_item in expected) for item in actual)
        return any(_json_equal(actual, expected_item) for expected_item in expected)
    if isinstance(actual, list):
        return any(_json_equal(item, expected) for item in actual)
    return _json_equal(actual, expected)


def _call_arg_names_for_locked_identity(locked: str) -> set[str]:
    names = {locked}
    if locked.endswith("_id") or locked.endswith("_ref"):
        names.add("id")
    return names


def _state_proves_retrieval_needed(
    state: PlannerOwnedAgentGraphState,
    capability_need: CapabilityNeed,
) -> bool:
    requirement_id = capability_need.requirement_id
    requirement = _requirement_by_id(state, requirement_id)
    if requirement is None or not requirement.required or requirement.status != "open":
        return False
    has_candidates = any(window.requirement_id == requirement.id for window in state.candidate_tool_windows)
    has_hydrated_cards = any(cards.requirement_id == requirement.id for cards in state.hydrated_tool_cards)
    has_evidence = any(evidence.requirement_id == requirement.id for evidence in state.evidence_ledger.evidence)
    return not has_candidates and not has_hydrated_cards and not has_evidence


def _state_proves_single_document_tool_choice(
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
) -> bool:
    calls = _selected_tool_calls(decision)
    if len(calls) != 1:
        return False
    call = calls[0]
    requirement = _requirement_by_id(state, call.requirement_id)
    if requirement is None or not requirement.required or requirement.status != "open":
        return False
    candidate_names = {
        candidate.tool_name
        for window in state.candidate_tool_windows
        if window.requirement_id == call.requirement_id
        for candidate in window.candidates
    }
    hydrated_cards = [
        card
        for group in state.hydrated_tool_cards
        if group.requirement_id == call.requirement_id
        for card in group.cards
        if not candidate_names or card.tool_name in candidate_names
    ]
    if len(hydrated_cards) != 1:
        return False
    card = hydrated_cards[0]
    return (
        call.kind == "rag_tool"
        and call.tool_name == card.tool_name
        and card.source_of_truth == "document_knowledge"
        and card.is_read_only
        and not card.requires_approval
    )


def _state_proves_bounded_read_batch_tool_choice(
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
) -> bool:
    calls = _selected_tool_calls(decision)
    if len(calls) <= 1:
        return False
    requirement_ids = {call.requirement_id for call in calls}
    if len(requirement_ids) != 1:
        return False
    requirement = _requirement_by_id(state, calls[0].requirement_id)
    if requirement is None or not requirement.required or requirement.status != "open":
        return False
    if requirement.requirement_type != "multi_entity_status":
        return False
    expected_values = _multi_entity_identity_value_keys(requirement, decision.capability_need)
    if len(expected_values) <= 1:
        return False
    actual_values = {_json_key(_call_identity_value(call, requirement)) for call in calls}
    if actual_values != expected_values:
        return False
    tool_names = {call.tool_name for call in calls}
    if len(tool_names) != 1:
        return False
    for call in calls:
        card = _hydrated_card_for_call(state, call)
        if card is None or not card.is_read_only or card.requires_approval:
            return False
    return True


def _multi_entity_identity_value_keys(
    requirement: RequirementLedgerEntry,
    capability_need: CapabilityNeed | None,
) -> set[str]:
    constraints = dict(requirement.constraints or {})
    if capability_need is not None:
        constraints.update(capability_need.known_args or {})
    for key in _identity_arg_names(requirement):
        value = constraints.get(key)
        if isinstance(value, list):
            return {_json_key(item) for item in value if item not in (None, "", [], {})}
    return set()


def _call_identity_value(call: GraphToolCall, requirement: RequirementLedgerEntry) -> Any:
    for key in _identity_arg_names(requirement):
        value = call.args.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _identity_arg_names(requirement: RequirementLedgerEntry) -> set[str]:
    entity = str(requirement.entity or "").strip()
    names = {"id", "entity_id", "record_id"}
    if entity:
        names.update({f"{entity}_id", f"{entity}_ref"})
    return names


def _hydrated_card_for_call(
    state: PlannerOwnedAgentGraphState,
    call: GraphToolCall,
) -> HydratedToolCard | None:
    return next(
        (
            card
            for group in state.hydrated_tool_cards
            if group.requirement_id == call.requirement_id
            for card in group.cards
            if card.tool_name == call.tool_name
        ),
        None,
    )


def _state_has_prior_tool_choice(state: PlannerOwnedAgentGraphState, call: GraphToolCall) -> bool:
    return any(
        previous.decision_kind == "choose_tool"
        and previous.author in {"planner", "system", "deterministic_guard"}
        and previous.ledger_revision == state.requirement_ledger.revision
        and _decision_is_not_stale_after_graph_interrupt(state, previous)
        and any(_same_tool_call(call, previous_call) for previous_call in _selected_tool_calls(previous))
        for previous in state.planner_decisions
    )


def _same_tool_call(left: GraphToolCall, right: GraphToolCall) -> bool:
    if left.call_id and right.call_id and left.call_id == right.call_id:
        return True
    return (
        left.kind == right.kind
        and left.tool_name == right.tool_name
        and left.requirement_id == right.requirement_id
        and _json_equal(left.args, right.args)
    )


def _final_validation_result_for(state: PlannerOwnedAgentGraphState) -> FinalValidationResult:
    validation_state = state.model_copy(deep=True)
    return validate_graph_state_final_state(validation_state)


def _requirement_by_id(
    state: PlannerOwnedAgentGraphState,
    requirement_id: str | None,
) -> RequirementLedgerEntry | None:
    if requirement_id is None:
        return None
    return next(
        (requirement for requirement in state.requirement_ledger.requirements if requirement.id == requirement_id),
        None,
    )


def _locked_value(requirement: RequirementLedgerEntry, locked: str) -> Any:
    if locked == "requested_fields":
        return list(requirement.requested_fields)
    return requirement.constraints.get(locked)


def _json_equal(left: Any, right: Any) -> bool:
    return _json_key(left) == _json_key(right)


def _json_key(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        value = {str(key): child for key, child in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
        value = list(value)
    return json.dumps(value, sort_keys=True, default=str)


def _coerce_positive_int(value: Any) -> int | None:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _decision_is_not_stale_after_graph_interrupt(
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
) -> bool:
    diagnostics = getattr(state.execution_trace, "diagnostics", {}) or {}
    if not isinstance(diagnostics, Mapping):
        return True
    stale_ids: set[str] = set()
    for key in ("phase9_stale_work", "replan_spine", "requirement_expansion"):
        stale = diagnostics.get(key)
        if not isinstance(stale, Mapping):
            continue
        stale_ids.update(
            str(decision_id)
            for decision_id in stale.get("stale_planner_decision_ids", [])
            if str(decision_id)
        )
    return decision.decision_id not in stale_ids
