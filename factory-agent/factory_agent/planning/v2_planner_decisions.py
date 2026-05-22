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
    FinalValidationResult,
    HydratedToolCard,
    RequirementLedger,
    RequirementLedgerEntry,
    V2ContractModel,
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
    "execute_parallel_read_batch",
    "request_approval",
    "request_clarification",
}
_ACTIVE_REQUIREMENT_STATUSES = {"open", "blocked"}
_PLANNER_PROPOSER_DIAGNOSTIC_KEY = "planner_proposer"


class PlannerDecisionValidationError(ValueError):
    """Raised when a planner decision cannot authorize a graph transition."""


class PlannerDecisionSubmission(V2ContractModel):
    """Serializable decision gate input.

    Most decisions can be validated against the current graph state alone.
    Requirement-revision decisions carry a proposed ledger so locked
    constraints can be checked before the state changes.
    """

    decision: PlannerDecisionRecord
    proposed_requirement_ledger: RequirementLedger | None = None


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

    _validate_decision_shape(state, normalized, errors)
    _validate_planner_author_has_proposer_diagnostics(normalized, errors)
    _validate_locked_constraints_preserved(state, normalized, errors)
    _validate_kind_specific_transition(state, normalized, errors)
    _validate_deterministic_guard_authority(state, normalized, errors)

    if errors:
        raise PlannerDecisionValidationError("; ".join(errors))

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
        if not current.locked_constraints:
            continue
        replacement = proposed_by_id.get(current.id)
        if replacement is None:
            errors.append(f"locked requirement was dropped: {current.id}")
            continue
        _validate_requirement_locks(current, replacement, errors)


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
            cards_by_call_id[call.call_id] = _validate_tool_call_from_hydrated_window(state, call, errors)
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
            _validate_tool_call_from_hydrated_window(state, call, errors)
        return

    if kind == "execute_parallel_read_batch":
        calls = _selected_tool_calls(decision)
        if not calls:
            errors.append("execute_parallel_read_batch decision requires selected_tool_calls")
            return
        for call in calls:
            card = _validate_tool_call_from_hydrated_window(state, call, errors)
            if card is not None and (not card.is_read_only or card.requires_approval):
                errors.append(f"parallel read batch cannot include mutating or approval tool: {call.tool_name}")
        return

    if kind == "request_approval":
        call = _single_selected_tool_call(decision, errors)
        if call is not None:
            card = _validate_tool_call_from_hydrated_window(state, call, errors)
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
        if not _state_proves_single_document_tool_choice(state, decision):
            errors.append("deterministic choose_tool guard requires exactly one bounded document tool choice")
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
) -> HydratedToolCard | None:
    if _requirement_by_id(state, call.requirement_id) is None:
        errors.append(f"selected tool call targets missing requirement: {call.requirement_id}")

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
    expected_call_kind = "rag_tool" if card.source_of_truth == "document_knowledge" else "api_tool"
    if call.kind != expected_call_kind:
        errors.append(
            "selected tool call kind does not match hydrated card source "
            f"({call.kind} != {expected_call_kind})"
        )
    return card


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


def _state_has_prior_tool_choice(state: PlannerOwnedAgentGraphState, call: GraphToolCall) -> bool:
    return any(
        previous.decision_kind == "choose_tool"
        and previous.author in {"planner", "system", "deterministic_guard"}
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


def _decision_is_not_stale_after_graph_interrupt(
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
) -> bool:
    diagnostics = getattr(state.execution_trace, "diagnostics", {}) or {}
    stale = diagnostics.get("phase9_stale_work") if isinstance(diagnostics, Mapping) else None
    if not isinstance(stale, Mapping):
        return True
    stale_ids = {
        str(decision_id)
        for decision_id in stale.get("stale_planner_decision_ids", [])
        if str(decision_id)
    }
    return decision.decision_id not in stale_ids
