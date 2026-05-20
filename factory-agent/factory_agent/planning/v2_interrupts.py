from __future__ import annotations

import re
from collections.abc import Mapping
from uuid import uuid4
from typing import Any

from .v2_capability_map import build_requirement_sketch_for_text
from .v2_contracts import (
    CapabilityMap,
    EvidenceLedgerEntry,
    PlannerOwnedLoopV2State,
    RequirementLedger,
    RequirementLedgerEntry,
    RequirementOrigin,
    RequirementRevisionRecord,
    RequirementSatisfactionState,
    UserInterrupt,
    UserInterruptType,
)


_CANCEL_RE = re.compile(
    r"\b(?:stop|cancel|abort|halt|never\s+mind|nevermind|do\s+not\s+continue|don't\s+continue)\b",
    re.IGNORECASE,
)
_APPEND_RE = re.compile(
    r"\b(?:also|add|append|include|plus|as\s+well|along\s+with)\b",
    re.IGNORECASE,
)
_REPLACE_RE = re.compile(
    r"\b(?:replace|start\s+over|new\s+goal|new\s+request|forget\s+(?:that|the\s+previous)|ignore\s+(?:that|the\s+previous)|instead\s+show|instead\s+do|do\s+this\s+instead)\b",
    re.IGNORECASE,
)
_MODIFY_RE = re.compile(
    r"\b(?:change|modify|revise|actually|instead\s+of|rather\s+than|do\s+not|don't|exclude|except|only)\b",
    re.IGNORECASE,
)
_APPROVAL_WORD_RE = re.compile(r"\bapproval|approve|approved|reject|rejected|decline|deny\b", re.IGNORECASE)
_APPROVE_RE = re.compile(r"\b(?:approve|approved|yes|confirm|go\s+ahead|proceed|continue)\b", re.IGNORECASE)
_REJECT_RE = re.compile(r"\b(?:reject|rejected|decline|deny|no|do\s+not\s+approve|don't\s+approve)\b", re.IGNORECASE)


def classify_user_interrupt(
    user_message: str,
    *,
    session_status: str | None = None,
    awaiting_approval: bool = False,
    previous_goal: str | None = None,
    target_requirement_id: str | None = None,
    approval_id: str | None = None,
    created_from_revision: int | None = None,
) -> UserInterrupt:
    """Classify a user message into a generic interrupt type.

    This classifier intentionally uses broad control-language patterns rather
    than prompt, fixture-id, or entity-label branches. The planner remains
    responsible for semantic replanning after the checkpoint is recorded.
    """

    text = user_message.strip()
    lowered_status = str(session_status or "").upper()
    interrupt_type: UserInterruptType
    approval_context = awaiting_approval or lowered_status == "WAITING_APPROVAL" or bool(approval_id)

    if _CANCEL_RE.search(text):
        interrupt_type = "cancel_current_run"
    elif approval_context and (_REJECT_RE.search(text) and (_APPROVAL_WORD_RE.search(text) or text.strip().lower() == "no")):
        interrupt_type = "reject_approval"
    elif approval_context and (_APPROVE_RE.search(text) and (_APPROVAL_WORD_RE.search(text) or text.strip().lower() in {"yes", "confirm"})):
        interrupt_type = "approve_approval"
    elif _REPLACE_RE.search(text):
        interrupt_type = "replace_goal"
    elif _APPEND_RE.search(text):
        interrupt_type = "append_requirement"
    elif _MODIFY_RE.search(text):
        interrupt_type = "modify_requirement"
    elif lowered_status in {"WAITING_CONFIRMATION", "BLOCKED"}:
        interrupt_type = "answer_clarification"
    else:
        interrupt_type = "modify_requirement" if previous_goal else "replace_goal"

    return UserInterrupt(
        interrupt_id=f"interrupt-{uuid4().hex[:12]}",
        interrupt_type=interrupt_type,
        user_message=text,
        previous_goal=previous_goal,
        target_requirement_id=target_requirement_id,
        approval_id=approval_id,
        created_from_revision=created_from_revision,
        metadata={"classifier": "generic_control_language"},
    )


def apply_user_interrupt_to_v2_state(
    state: PlannerOwnedLoopV2State,
    interrupt: UserInterrupt,
    *,
    capability_map: CapabilityMap | None = None,
) -> PlannerOwnedLoopV2State:
    ledger = state.requirement_ledger
    if ledger is None:
        state.execution_trace.diagnostics.setdefault("user_interrupts", []).append(
            {
                "interrupt": interrupt.model_dump(mode="json"),
                "status": "not_applied",
                "reason": "missing_requirement_ledger",
            }
        )
        return state

    if interrupt.interrupt_type == "cancel_current_run":
        return _record_control_interrupt(
            state,
            ledger,
            interrupt,
            change_type="user_interrupt:cancel_current_run",
            details={"cancelled": True},
        )
    if interrupt.interrupt_type in {"approve_approval", "reject_approval", "answer_clarification"}:
        return _record_control_interrupt(
            state,
            ledger,
            interrupt,
            change_type=f"user_interrupt:{interrupt.interrupt_type}",
            details={"approval_id": interrupt.approval_id},
        )
    if interrupt.interrupt_type == "append_requirement":
        return _apply_append_interrupt(state, ledger, interrupt, capability_map=capability_map)
    if interrupt.interrupt_type == "replace_goal":
        return _apply_replace_interrupt(state, ledger, interrupt, capability_map=capability_map)
    return _apply_modify_interrupt(state, ledger, interrupt, capability_map=capability_map)


def apply_user_interrupt_to_context(
    context: Mapping[str, Any] | None,
    interrupt: UserInterrupt,
    *,
    previous_status: str | None = None,
    revised_goal: str | None = None,
) -> dict[str, Any]:
    """Apply a v2 interrupt to any v2 state embedded in replan context."""

    updated = dict(context or {})
    intent_contract = dict(updated.get("intent_contract") or {})
    state_key, state = _v2_state_from_intent_contract(intent_contract)
    if state is not None:
        apply_user_interrupt_to_v2_state(state, interrupt)
        intent_contract[state_key] = state.model_dump(mode="json")
        if state_key == "v2_shadow_state":
            intent_contract["execution_trace"] = state.execution_trace.model_dump(mode="json")
        elif state_key == "v2_state":
            intent_contract["execution_trace"] = state.execution_trace.model_dump(mode="json")
        updated["intent_contract"] = intent_contract

    checkpoint = {
        "interrupt_id": interrupt.interrupt_id,
        "interrupt_type": interrupt.interrupt_type,
        "user_message": interrupt.user_message,
        "previous_status": previous_status,
        "previous_goal": interrupt.previous_goal,
        "revised_goal": revised_goal,
        "ledger_revision": newest_v2_ledger_revision_from_context(updated),
        "replaces_pending_user_message": True,
    }
    updated["planner_owned_loop_interrupt"] = checkpoint
    history = [
        item
        for item in updated.get("planner_owned_loop_interrupt_history", [])
        if isinstance(item, dict)
    ]
    history.append(checkpoint)
    updated["planner_owned_loop_interrupt_history"] = history
    return updated


def approval_payload_matches_newest_ledger_revision(
    approval_payload: Mapping[str, Any] | None,
    context: Mapping[str, Any] | None,
) -> bool:
    newest_revision = newest_v2_ledger_revision_from_context(context)
    if newest_revision is None:
        return True
    payload_revision = _ledger_revision_from_mapping(approval_payload)
    if payload_revision is None:
        return True
    return payload_revision == newest_revision


def newest_v2_ledger_revision_from_context(context: Mapping[str, Any] | None) -> int | None:
    if not isinstance(context, Mapping):
        return None
    checkpoint = context.get("planner_owned_loop_interrupt")
    if isinstance(checkpoint, Mapping):
        revision = _coerce_revision(checkpoint.get("ledger_revision"))
        if revision is not None:
            return revision
    revision = _ledger_revision_from_mapping(context)
    if revision is not None:
        return revision
    intent_contract = context.get("intent_contract")
    if isinstance(intent_contract, Mapping):
        for key in ("v2_state", "v2_shadow_state"):
            state_payload = intent_contract.get(key)
            revision = _ledger_revision_from_mapping(state_payload if isinstance(state_payload, Mapping) else None)
            if revision is not None:
                return revision
    return None


def revised_goal_for_interrupt(previous_goal: str, interrupt: UserInterrupt) -> str:
    message = interrupt.user_message.strip()
    if interrupt.interrupt_type == "append_requirement":
        return _join_goal_parts(previous_goal, message)
    if interrupt.interrupt_type == "modify_requirement":
        return _join_goal_parts(previous_goal, message)
    if interrupt.interrupt_type == "replace_goal":
        return message
    return previous_goal


def execution_result_is_stale_after_interrupt(
    *,
    session_status: str | None,
    current_intent: str | None,
    started_intent: str,
    replan_context: Mapping[str, Any] | None,
) -> bool:
    if str(session_status or "").upper() == "PLANNING":
        checkpoint = (replan_context or {}).get("planner_owned_loop_interrupt") if isinstance(replan_context, Mapping) else None
        if isinstance(checkpoint, Mapping):
            return True
    return str(current_intent or "") != str(started_intent or "")


def _apply_append_interrupt(
    state: PlannerOwnedLoopV2State,
    ledger: RequirementLedger,
    interrupt: UserInterrupt,
    *,
    capability_map: CapabilityMap | None,
) -> PlannerOwnedLoopV2State:
    before = _ledger_snapshot(ledger)
    new_requirements = _requirements_from_interrupt_message(ledger, interrupt, capability_map=capability_map)
    ledger.requirements.extend(new_requirements)
    ledger.user_goal = _join_goal_parts(ledger.user_goal, interrupt.user_message)
    revision = _next_revision(ledger)
    record = _revision_record(
        revision,
        interrupt,
        change_type="user_interrupt:append_requirement",
        requirement_id=new_requirements[0].id if new_requirements else None,
        details={
            "previous_ledger": before,
            "added_requirement_ids": [requirement.id for requirement in new_requirements],
            "new_user_goal": ledger.user_goal,
        },
    )
    _commit_revision(state, ledger, record)
    return state


def _apply_replace_interrupt(
    state: PlannerOwnedLoopV2State,
    ledger: RequirementLedger,
    interrupt: UserInterrupt,
    *,
    capability_map: CapabilityMap | None,
) -> PlannerOwnedLoopV2State:
    before = _ledger_snapshot(ledger)
    old_ids = [req.id for req in ledger.requirements if req.status != "superseded"]
    new_requirements = _requirements_from_interrupt_message(ledger, interrupt, capability_map=capability_map)
    revision = _next_revision(ledger)
    first_new_id = new_requirements[0].id if new_requirements else None
    for requirement in ledger.requirements:
        if requirement.status != "superseded":
            requirement.status = "superseded"
            requirement.superseded_by = first_new_id
    ledger.requirements.extend(new_requirements)
    ledger.user_goal = interrupt.user_message
    _mark_evidence_superseded(
        state.evidence_ledger.evidence,
        requirement_ids=old_ids,
        revision=revision,
        reason="replace_goal",
    )
    record = _revision_record(
        revision,
        interrupt,
        change_type="user_interrupt:replace_goal",
        requirement_id=first_new_id,
        details={
            "previous_ledger": before,
            "superseded_requirement_ids": old_ids,
            "added_requirement_ids": [requirement.id for requirement in new_requirements],
            "new_user_goal": ledger.user_goal,
        },
    )
    _commit_revision(state, ledger, record)
    return state


def _apply_modify_interrupt(
    state: PlannerOwnedLoopV2State,
    ledger: RequirementLedger,
    interrupt: UserInterrupt,
    *,
    capability_map: CapabilityMap | None,
) -> PlannerOwnedLoopV2State:
    before = _ledger_snapshot(ledger)
    targets = _target_requirements_for_modify(ledger, interrupt, capability_map=capability_map)
    if not targets:
        return _apply_append_interrupt(state, ledger, interrupt, capability_map=capability_map)

    change_requirements = _requirements_from_interrupt_message(
        ledger,
        interrupt,
        capability_map=capability_map,
        remap_ids=False,
    )
    change = change_requirements[0] if change_requirements else None
    revision = _next_revision(ledger)
    replacements: list[RequirementLedgerEntry] = []
    next_index = _next_requirement_index(ledger)
    for offset, target in enumerate(targets):
        replacement = _replacement_requirement_for_modify(
            target,
            change,
            interrupt,
            requirement_id=f"req-{next_index + offset:03d}",
        )
        target.status = "superseded"
        target.superseded_by = replacement.id
        replacements.append(replacement)

    ledger.requirements.extend(replacements)
    ledger.user_goal = _join_goal_parts(ledger.user_goal, interrupt.user_message)
    _mark_evidence_superseded(
        state.evidence_ledger.evidence,
        requirement_ids=[requirement.id for requirement in targets],
        revision=revision,
        reason="modify_requirement",
    )
    record = _revision_record(
        revision,
        interrupt,
        change_type="user_interrupt:modify_requirement",
        requirement_id=targets[0].id,
        details={
            "previous_ledger": before,
            "superseded_requirement_ids": [requirement.id for requirement in targets],
            "replacement_requirement_ids": [requirement.id for requirement in replacements],
            "new_user_goal": ledger.user_goal,
        },
    )
    _commit_revision(state, ledger, record)
    return state


def _record_control_interrupt(
    state: PlannerOwnedLoopV2State,
    ledger: RequirementLedger,
    interrupt: UserInterrupt,
    *,
    change_type: str,
    details: dict[str, Any],
) -> PlannerOwnedLoopV2State:
    before = _ledger_snapshot(ledger)
    revision = _next_revision(ledger)
    merged_details = {"previous_ledger": before, **details}
    if interrupt.interrupt_type == "cancel_current_run":
        for requirement in ledger.requirements:
            if requirement.status == "open":
                requirement.status = "skipped"
                if "cancelled_by_user" not in requirement.blockers:
                    requirement.blockers.append("cancelled_by_user")
    record = _revision_record(
        revision,
        interrupt,
        change_type=change_type,
        requirement_id=interrupt.target_requirement_id,
        details=merged_details,
    )
    _commit_revision(state, ledger, record)
    return state


def _requirements_from_interrupt_message(
    ledger: RequirementLedger,
    interrupt: UserInterrupt,
    *,
    capability_map: CapabilityMap | None,
    remap_ids: bool = True,
) -> list[RequirementLedgerEntry]:
    sketch = build_requirement_sketch_for_text(interrupt.user_message, capability_map=capability_map)
    next_index = _next_requirement_index(ledger)
    requirements: list[RequirementLedgerEntry] = []
    for offset, item in enumerate(sketch.requirements):
        requirement_id = f"req-{next_index + offset:03d}" if remap_ids else item.id
        requirements.append(
            RequirementLedgerEntry(
                id=requirement_id,
                goal=item.goal,
                requirement_type=item.requirement_type,
                entity=item.entity,
                intent_operation=item.intent_operation,
                source_of_truth=item.source_of_truth,
                constraints=dict(item.constraints),
                requested_fields=list(item.requested_fields),
                locked_constraints=list(item.locked_constraints),
                status="open",
                required=True,
                origin=RequirementOrigin(
                    goal="user_interrupt",
                    constraints=item.origin.constraints,
                    fields=item.origin.fields,
                    source_of_truth=item.origin.source_of_truth,
                ),
            )
        )
    return requirements


def _target_requirements_for_modify(
    ledger: RequirementLedger,
    interrupt: UserInterrupt,
    *,
    capability_map: CapabilityMap | None,
) -> list[RequirementLedgerEntry]:
    active = [requirement for requirement in ledger.requirements if requirement.status != "superseded"]
    if interrupt.target_requirement_id:
        return [requirement for requirement in active if requirement.id == interrupt.target_requirement_id]

    sketch = build_requirement_sketch_for_text(interrupt.user_message, capability_map=capability_map)
    hinted_entities = {item.entity for item in sketch.requirements if item.entity}
    hinted_sources = {item.source_of_truth for item in sketch.requirements if item.source_of_truth != "unknown"}
    hinted_types = {item.requirement_type for item in sketch.requirements}
    matches = [
        requirement
        for requirement in active
        if (
            (requirement.entity and requirement.entity in hinted_entities)
            or (requirement.source_of_truth != "unknown" and requirement.source_of_truth in hinted_sources)
            or requirement.requirement_type in hinted_types
        )
    ]
    if matches:
        return matches
    return active[:1]


def _replacement_requirement_for_modify(
    target: RequirementLedgerEntry,
    change: RequirementLedgerEntry | None,
    interrupt: UserInterrupt,
    *,
    requirement_id: str,
) -> RequirementLedgerEntry:
    replacement = target.model_copy(deep=True)
    replacement.id = requirement_id
    replacement.goal = _join_goal_parts(target.goal, interrupt.user_message)
    replacement.status = "open"
    replacement.evidence_refs = []
    replacement.satisfaction_checks = []
    replacement.blockers = []
    replacement.superseded_by = None
    replacement.origin = RequirementOrigin(
        goal="user_interrupt",
        constraints=target.origin.constraints,
        fields=target.origin.fields,
        source_of_truth=target.origin.source_of_truth,
    )
    if change is not None:
        replacement.constraints = _merge_dicts(target.constraints, change.constraints)
        replacement.requested_fields = _merge_list(target.requested_fields, change.requested_fields)
        replacement.locked_constraints = _merge_list(target.locked_constraints, change.locked_constraints)
        if change.source_of_truth != "unknown":
            replacement.source_of_truth = change.source_of_truth
        if change.entity:
            replacement.entity = change.entity
    for key in replacement.constraints:
        if key not in replacement.locked_constraints and replacement.constraints[key] not in (None, "", [], {}):
            replacement.locked_constraints.append(key)
    if replacement.requested_fields and "requested_fields" not in replacement.locked_constraints:
        replacement.locked_constraints.append("requested_fields")
    return replacement


def _next_requirement_index(ledger: RequirementLedger) -> int:
    max_index = 0
    for requirement in ledger.requirements:
        match = re.match(r"req-(\d+)$", requirement.id)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def _next_revision(ledger: RequirementLedger) -> int:
    ledger.revision = (ledger.revision or 0) + 1
    return ledger.revision


def _revision_record(
    revision: int,
    interrupt: UserInterrupt,
    *,
    change_type: str,
    requirement_id: str | None,
    details: dict[str, Any],
) -> RequirementRevisionRecord:
    return RequirementRevisionRecord(
        revision=revision,
        actor="user",
        change_type=change_type,
        requirement_id=requirement_id,
        reason=interrupt.user_message,
        locked_constraints_preserved=True,
        details={"interrupt": interrupt.model_dump(mode="json"), **details},
    )


def _commit_revision(
    state: PlannerOwnedLoopV2State,
    ledger: RequirementLedger,
    record: RequirementRevisionRecord,
) -> None:
    ledger.revision_history.append(record)
    state.revision_history.append(record)
    state.satisfaction_state.requirements = [
        RequirementSatisfactionState(
            requirement_id=requirement.id,
            status=requirement.status,
            evidence_refs=list(requirement.evidence_refs),
            satisfaction_checks=list(requirement.satisfaction_checks),
            blocker_reason=requirement.blockers[-1] if requirement.blockers else None,
        )
        for requirement in ledger.requirements
    ]
    state.final_validation_result = None
    state.execution_trace.final_validator_status = "invalidated_by_user_interrupt"
    diagnostics = state.execution_trace.diagnostics.setdefault("user_interrupts", [])
    diagnostics.append(record.model_dump(mode="json"))


def _mark_evidence_superseded(
    evidence: list[EvidenceLedgerEntry],
    *,
    requirement_ids: list[str],
    revision: int,
    reason: str,
) -> None:
    targets = set(requirement_ids)
    for item in evidence:
        if item.requirement_id not in targets:
            continue
        metadata = dict(item.diagnostic_metadata or {})
        metadata["superseded_by_ledger_revision"] = revision
        metadata["superseded_reason"] = reason
        metadata["stale_after_user_interrupt"] = True
        item.diagnostic_metadata = metadata


def _v2_state_from_intent_contract(intent_contract: Mapping[str, Any]) -> tuple[str, PlannerOwnedLoopV2State | None]:
    for key in ("v2_state", "v2_shadow_state"):
        payload = intent_contract.get(key)
        if not isinstance(payload, Mapping):
            continue
        try:
            return key, PlannerOwnedLoopV2State.model_validate(payload)
        except Exception:
            return key, None
    return "v2_state", None


def _ledger_revision_from_mapping(payload: Mapping[str, Any] | None) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("requirement_ledger_revision", "ledger_revision", "revision"):
        revision = _coerce_revision(payload.get(key))
        if revision is not None:
            return revision
    nested_names = ("planner_owned_loop", "v2", "requirement_ledger", "ledger")
    for key in nested_names:
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            revision = _ledger_revision_from_mapping(nested)
            if revision is not None:
                return revision
    return None


def _coerce_revision(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed >= 1 else None
    return None


def _ledger_snapshot(ledger: RequirementLedger) -> dict[str, Any]:
    return {
        "user_goal": ledger.user_goal,
        "revision": ledger.revision,
        "requirements": [requirement.model_dump(mode="json") for requirement in ledger.requirements],
    }


def _join_goal_parts(first: str, second: str) -> str:
    left = first.strip()
    right = second.strip()
    if not left:
        return right
    if not right:
        return left
    separator = "" if left.endswith((".", "!", "?")) else "."
    return f"{left}{separator} {right}"


def _merge_dicts(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(first)
    for key, value in second.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _merge_list(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))
