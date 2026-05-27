from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..planning.v2_agent_state import (
    PendingApprovalState,
    PlannerDecisionRecord,
    PlannerOwnedAgentGraphState,
    validate_graph_state_final_state,
)
from ..planning.v2_contracts import (
    EvidenceLedgerEntry,
    RequirementRevisionRecord,
    RequirementSatisfactionState,
    SatisfactionCheck,
    UserInterrupt,
)
from ..planning.v2_graph_adapters import GraphToolExecutionResult
from ..planning.v2_planner_decisions import record_planner_decision
from .v2_graph_state_utils import (
    _coerce_positive_int,
    _current_graph_checkpoint_id,
    _session_context_value,
)


def _apply_graph_revision_evidence_policy(
    state: PlannerOwnedAgentGraphState,
    *,
    previous_revision: int,
    old_evidence_ids: list[str],
    carry_forward_evidence_refs: set[str],
) -> dict[str, Any]:
    old_ids = set(old_evidence_ids)
    carry_all = "*" in carry_forward_evidence_refs
    carried: list[str] = []
    stale: list[str] = []
    active_requirement_ids = {
        requirement.id
        for requirement in state.requirement_ledger.requirements
        if requirement.status not in {"superseded", "skipped"}
    }
    for evidence in state.evidence_ledger.evidence:
        if evidence.id not in old_ids:
            continue
        metadata = dict(evidence.diagnostic_metadata or {})
        explicit_carry = carry_all or evidence.id in carry_forward_evidence_refs
        if explicit_carry and evidence.requirement_id in active_requirement_ids:
            metadata["carried_forward_explicit"] = True
            metadata["carried_forward_from_ledger_revision"] = previous_revision
            metadata["carried_forward_to_ledger_revision"] = state.requirement_ledger.revision
            metadata["active_revision_satisfaction"] = True
            carried.append(evidence.id)
        else:
            metadata["stale_after_user_interrupt"] = True
            metadata["stale_after_graph_revision"] = True
            metadata["active_revision_satisfaction"] = False
            metadata["superseded_by_ledger_revision"] = state.requirement_ledger.revision
            metadata.setdefault("superseded_reason", "graph_user_interrupt")
            stale.append(evidence.id)
        evidence.diagnostic_metadata = metadata

    stale_set = set(stale)
    for requirement in state.requirement_ledger.requirements:
        if requirement.status in {"superseded", "skipped"}:
            continue
        previous_refs = list(requirement.evidence_refs)
        requirement.evidence_refs = [
            evidence_ref for evidence_ref in requirement.evidence_refs if evidence_ref not in stale_set
        ]
        requirement.satisfaction_checks = [
            check
            for check in requirement.satisfaction_checks
            if check.evidence_ref is None or check.evidence_ref not in stale_set
        ]
        if previous_refs and not requirement.evidence_refs and requirement.status in {
            "satisfied",
            "impossible",
            "blocked",
            "failed",
        }:
            requirement.status = "open"
            requirement.blockers = []
            requirement.satisfaction_checks = []

    _sync_graph_satisfaction_state(state)
    return {
        "previous_ledger_revision": previous_revision,
        "current_ledger_revision": state.requirement_ledger.revision,
        "stale_evidence_refs": stale,
        "carried_forward_evidence_refs": carried,
        "explicit_carry_forward_required": True,
    }


def _invalidate_graph_work_after_interrupt(
    state: PlannerOwnedAgentGraphState,
    *,
    interrupt: UserInterrupt,
    previous_revision: int,
    previous_checkpoint_identity: Mapping[str, Any],
    pending_before: PendingApprovalState,
) -> dict[str, Any]:
    stale_decision_ids = [
        decision.decision_id
        for decision in state.planner_decisions
        if decision.ledger_revision <= previous_revision
    ]
    cleared_candidate_windows = len(state.candidate_tool_windows)
    cleared_hydrated_cards = len(state.hydrated_tool_cards)
    state.candidate_tool_windows = []
    state.hydrated_tool_cards = []

    stale_pending_approval: dict[str, Any] | None = None
    if pending_before.status == "pending":
        payload = dict(pending_before.payload)
        payload.update(
            {
                "stale_after_interrupt_id": interrupt.interrupt_id,
                "stale_after_ledger_revision": state.requirement_ledger.revision,
                "stale_reason": "graph_user_interrupt_revised_ledger",
                "previous_graph_checkpoint_identity": dict(previous_checkpoint_identity),
            }
        )
        state.pending_approval = PendingApprovalState(
            status="stale",
            approval_id=pending_before.approval_id,
            requirement_id=pending_before.requirement_id,
            decision_id=pending_before.decision_id,
            ledger_revision=pending_before.ledger_revision,
            checkpoint_id=pending_before.checkpoint_id,
            tool_call=pending_before.tool_call,
            payload=payload,
        )
        stale_pending_approval = {
            "approval_id": pending_before.approval_id,
            "requirement_id": pending_before.requirement_id,
            "approval_ledger_revision": pending_before.ledger_revision,
            "approval_checkpoint_id": pending_before.checkpoint_id,
            "stale_after_ledger_revision": state.requirement_ledger.revision,
        }

    diagnostics = {
        "previous_ledger_revision": previous_revision,
        "current_ledger_revision": state.requirement_ledger.revision,
        "stale_planner_decision_ids": stale_decision_ids,
        "cleared_candidate_window_count": cleared_candidate_windows,
        "cleared_hydrated_card_count": cleared_hydrated_cards,
        "stale_pending_approval": stale_pending_approval,
        "stale_checks_use_graph_revision_and_checkpoint": True,
    }
    state.execution_trace.diagnostics["phase9_stale_work"] = diagnostics
    return diagnostics


def _close_graph_after_cancel_interrupt(
    state: PlannerOwnedAgentGraphState,
    interrupt: UserInterrupt,
) -> None:
    closed_requirement_ids: list[str] = []
    for requirement in state.requirement_ledger.requirements:
        if requirement.status in {"superseded", "impossible"}:
            continue
        evidence = EvidenceLedgerEntry(
            id=_unique_graph_evidence_id(state, f"ev-user-cancel-{requirement.id}"),
            requirement_id=requirement.id,
            source_type="system_guard",
            source_of_truth=requirement.source_of_truth,
            confidence="deterministic",
            normalized_result={
                "status": "cancelled",
                "reason": "user_cancelled_current_run",
                "interrupt_id": interrupt.interrupt_id,
                "ledger_revision": state.requirement_ledger.revision,
            },
            satisfies=["user_cancelled_current_run"],
            diagnostic_metadata={
                "graph_user_interrupt": True,
                "interrupt_id": interrupt.interrupt_id,
                "interrupt_type": interrupt.interrupt_type,
                "ledger_revision": state.requirement_ledger.revision,
                "active_revision_satisfaction": True,
            },
        )
        state.evidence_ledger.evidence.append(evidence)
        requirement.status = "impossible"
        requirement.evidence_refs = [evidence.id]
        requirement.satisfaction_checks = [
            SatisfactionCheck(
                check="user_cancelled_current_run",
                expected="continue_execution",
                actual="cancelled_by_user",
                passed=True,
                evidence_ref=evidence.id,
                message="The user cancelled the active graph run.",
            )
        ]
        if "user_cancelled_current_run" not in requirement.blockers:
            requirement.blockers.append("user_cancelled_current_run")
        closed_requirement_ids.append(requirement.id)

    state.pending_approval = PendingApprovalState(status="none")
    _sync_graph_satisfaction_state(state)
    validate_graph_state_final_state(state)
    if state.final_validation_result is not None and state.final_validation_result.status == "passed":
        decision = PlannerDecisionRecord(
            decision_id=f"dec-finalize-{len(state.planner_decisions) + 1:03d}",
            decision_kind="finalize",
            author="deterministic_guard",
            ledger_revision=state.requirement_ledger.revision,
            evidence_refs=[evidence.id for evidence in state.evidence_ledger.evidence],
            reason="User cancelled the active graph run and the graph closed it with typed cancellation evidence.",
        )
        record_planner_decision(state, decision)
    state.execution_trace.diagnostics["phase9_cancel_interrupt"] = {
        "status": "closed",
        "closed_requirement_ids": closed_requirement_ids,
        "final_validation_status": state.final_validation_result.status if state.final_validation_result else None,
    }


def _record_graph_interrupt_revision_trace(
    state: PlannerOwnedAgentGraphState,
    *,
    interrupt: UserInterrupt,
    previous_revision: int,
    loaded_checkpoint_id: str | None,
    previous_checkpoint_identity: Mapping[str, Any],
    new_checkpoint_identity: Mapping[str, Any],
    evidence_policy: Mapping[str, Any],
    stale_work: Mapping[str, Any],
) -> None:
    event = {
        "status": "applied",
        "interrupt": interrupt.model_dump(mode="json"),
        "previous_ledger_revision": previous_revision,
        "new_ledger_revision": state.requirement_ledger.revision,
        "loaded_checkpoint_id": loaded_checkpoint_id,
        "previous_checkpoint_identity": dict(previous_checkpoint_identity),
        "new_checkpoint_identity": dict(new_checkpoint_identity),
        "native_langgraph_checkpoint_used": True,
        "session_replan_context_authoritative": False,
        "evidence_policy": dict(evidence_policy),
        "stale_work": dict(stale_work),
    }
    state.execution_trace.diagnostics["phase9_interruption_revision"] = event
    state.execution_trace.planner.diagnostics["phase9_interruption_revision"] = {
        "interrupt_id": interrupt.interrupt_id,
        "interrupt_type": interrupt.interrupt_type,
        "previous_ledger_revision": previous_revision,
        "new_ledger_revision": state.requirement_ledger.revision,
    }
    history = [
        item
        for item in state.execution_trace.diagnostics.get("graph_revision_metadata", [])
        if isinstance(item, dict)
    ]
    history.append(event)
    state.execution_trace.diagnostics["graph_revision_metadata"] = history


def _store_graph_interrupt_pointer_for_ui(
    session_context: Mapping[str, Any] | Any | None,
    *,
    interrupt: UserInterrupt,
    previous_revision: int,
    current_revision: int,
    previous_checkpoint_identity: Mapping[str, Any],
    current_checkpoint_identity: Mapping[str, Any],
) -> None:
    pointer = {
        "interrupt_id": interrupt.interrupt_id,
        "interrupt_type": interrupt.interrupt_type,
        "ledger_revision": current_revision,
        "previous_ledger_revision": previous_revision,
        "checkpoint_id": current_checkpoint_identity.get("checkpoint_id"),
        "previous_checkpoint_id": previous_checkpoint_identity.get("checkpoint_id"),
        "session_replan_context_authoritative": False,
        "source": "planner_owned_agent_graph_checkpoint_pointer",
    }
    if session_context is None:
        return
    existing = _session_context_value(session_context, "replan_context")
    context = dict(existing) if isinstance(existing, Mapping) else {}
    context["planner_owned_graph_interrupt"] = pointer
    history = [item for item in context.get("planner_owned_graph_interrupt_history", []) if isinstance(item, dict)]
    history.append(pointer)
    context["planner_owned_graph_interrupt_history"] = history
    if isinstance(session_context, dict):
        session_context["replan_context"] = context
        return
    try:
        setattr(session_context, "replan_context", context)
    except Exception:
        return


def _attach_graph_work_identity(
    state: PlannerOwnedAgentGraphState,
    execution: GraphToolExecutionResult,
) -> None:
    metadata = dict(execution.diagnostic_metadata or {})
    metadata.setdefault("ledger_revision", state.requirement_ledger.revision)
    checkpoint_id = _current_graph_checkpoint_id(state)
    if checkpoint_id is not None:
        metadata.setdefault("checkpoint_id", checkpoint_id)
    metadata.setdefault("graph_checkpoint_identity", state.execution_trace.diagnostics.get("graph_checkpoint_identity"))
    execution.diagnostic_metadata = metadata


def _attach_graph_evidence_identity(
    state: PlannerOwnedAgentGraphState,
    evidence: EvidenceLedgerEntry,
) -> None:
    metadata = dict(evidence.diagnostic_metadata or {})
    metadata.setdefault("ledger_revision", state.requirement_ledger.revision)
    checkpoint_id = _current_graph_checkpoint_id(state)
    if checkpoint_id is not None:
        metadata.setdefault("checkpoint_id", checkpoint_id)
    metadata.setdefault("active_revision_satisfaction", True)
    evidence.diagnostic_metadata = metadata


def _stale_background_result_reason(
    state: PlannerOwnedAgentGraphState,
    execution: GraphToolExecutionResult,
) -> str | None:
    metadata = dict(execution.diagnostic_metadata or {})
    result_revision = _coerce_positive_int(metadata.get("ledger_revision"))
    if result_revision is not None and result_revision != state.requirement_ledger.revision:
        return "ledger_revision_mismatch"
    result_checkpoint_id = metadata.get("checkpoint_id")
    current_checkpoint_id = _current_graph_checkpoint_id(state)
    if (
        result_checkpoint_id not in (None, "")
        and current_checkpoint_id not in (None, "")
        and str(result_checkpoint_id) != str(current_checkpoint_id)
    ):
        return "checkpoint_id_mismatch"
    requirement = _requirement_by_id(state, execution.tool_call.requirement_id)
    if requirement is None:
        return "requirement_missing"
    if requirement.status == "superseded":
        return "requirement_superseded"
    if metadata.get("stale_after_graph_revision") is True or metadata.get("active_revision_satisfaction") is False:
        return "result_marked_stale"
    return None


def _evidence_can_satisfy_active_revision(
    state: PlannerOwnedAgentGraphState,
    evidence: EvidenceLedgerEntry,
) -> bool:
    metadata = dict(evidence.diagnostic_metadata or {})
    if metadata.get("active_revision_satisfaction") is False:
        return False
    if metadata.get("stale_after_graph_revision") is True or metadata.get("stale_after_user_interrupt") is True:
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


def _planner_decision_is_active_for_graph_revision(
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
) -> bool:
    stale_ids: set[str] = set()
    stale = state.execution_trace.diagnostics.get("phase9_stale_work")
    if isinstance(stale, Mapping):
        stale_ids.update(
            str(decision_id)
            for decision_id in stale.get("stale_planner_decision_ids", [])
            if str(decision_id)
        )
    replan = state.execution_trace.diagnostics.get("replan_spine")
    if isinstance(replan, Mapping):
        stale_ids.update(
            str(decision_id)
            for decision_id in replan.get("stale_planner_decision_ids", [])
            if str(decision_id)
        )
    expansion = state.execution_trace.diagnostics.get("requirement_expansion")
    if isinstance(expansion, Mapping):
        stale_ids.update(
            str(decision_id)
            for decision_id in expansion.get("stale_planner_decision_ids", [])
            if str(decision_id)
        )
    if not stale_ids:
        return True
    return decision.decision_id not in stale_ids


def _record_graph_requirement_update(
    state: PlannerOwnedAgentGraphState,
    requirement: Any,
    *,
    status: str,
    evidence_refs: list[str],
    checks: list[SatisfactionCheck],
    reason: str,
) -> None:
    previous_status = requirement.status
    requirement.status = status
    requirement.evidence_refs = list(dict.fromkeys(evidence_refs))
    requirement.satisfaction_checks = list(checks)
    if status in {"blocked", "failed", "impossible"} and reason not in requirement.blockers:
        requirement.blockers.append(reason)
    state.requirement_ledger.revision += 1
    record = RequirementRevisionRecord(
        revision=state.requirement_ledger.revision,
        actor="deterministic_guard",
        change_type=f"graph_approval_satisfaction:{status}",
        requirement_id=requirement.id,
        reason=reason,
        locked_constraints_preserved=True,
        details={
            "previous_status": previous_status,
            "new_status": status,
            "evidence_refs": list(evidence_refs),
            "satisfaction_checks": [check.model_dump(mode="json") for check in checks],
        },
    )
    state.requirement_ledger.revision_history.append(record)
    state.revision_history.append(record)
    existing = [
        item
        for item in state.satisfaction_state.requirements
        if item.requirement_id != requirement.id
    ]
    existing.append(
        RequirementSatisfactionState(
            requirement_id=requirement.id,
            status=requirement.status,
            evidence_refs=list(requirement.evidence_refs),
            satisfaction_checks=list(requirement.satisfaction_checks),
            blocker_reason=reason if requirement.status in {"blocked", "failed", "impossible"} else None,
        )
    )
    state.satisfaction_state.requirements = existing


def _sync_graph_satisfaction_state(state: PlannerOwnedAgentGraphState) -> None:
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


def _unique_graph_evidence_id(state: PlannerOwnedAgentGraphState, base: str) -> str:
    existing = {evidence.id for evidence in state.evidence_ledger.evidence}
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _requirement_by_id(state: PlannerOwnedAgentGraphState, requirement_id: str | None):
    if requirement_id is None:
        return None
    return next(
        (requirement for requirement in state.requirement_ledger.requirements if requirement.id == requirement_id),
        None,
    )
