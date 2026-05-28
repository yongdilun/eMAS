from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from .v2_agent_state import GraphToolCall, PlannerOwnedAgentGraphState
from .v2_contracts import (
    CapabilityAction,
    DependencyPlan,
    DependencyReadyGroup,
    DependencyRequirementPlan,
    EvidenceLedgerEntry,
    HydratedToolCard,
    RequirementLedgerEntry,
    SourceOfTruth,
)
from .v2_tool_card_selection import card_supports_collection_read, identity_arg_names


DEPENDENCY_PLAN_DIAGNOSTIC_KEY = "dependency_plan"
DEPENDENCY_PLAN_HISTORY_DIAGNOSTIC_KEY = "dependency_plan_history"
MAX_PARALLEL_READ_BATCH_SIZE = 3

_TERMINAL_REQUIREMENT_STATUSES = {"satisfied", "skipped", "impossible", "superseded", "failed"}
_APPROVAL_REQUIREMENT_TYPES = {"mutation_request", "approval_request"}
_APPROVAL_OPERATIONS = {"stage_mutation", "request_approval"}
_READ_ACTIONS = {"read", "read_one", "read_many", "list", "search_documents"}
_SEQUENTIAL_READ_TYPES = {"filtered_collection", "document_answer"}
_SAFE_SIDE_EFFECT_LEVELS = {"", "NONE", "LOW"}


def build_dependency_plan(state: PlannerOwnedAgentGraphState) -> DependencyPlan:
    """Return the planner-owned dependency execution plan for the current graph state."""

    active_evidence = _active_evidence_by_ref(state)
    active_evidence_by_requirement = _active_evidence_by_requirement(active_evidence.values())
    items = [
        _requirement_plan(
            state,
            requirement,
            active_evidence=active_evidence,
            active_evidence_by_requirement=active_evidence_by_requirement,
        )
        for requirement in state.requirement_ledger.requirements
    ]
    ready_groups = _ready_groups(items)
    blocked = [
        {
            "requirement_id": item.requirement_id,
            "label": item.label,
            "blocked_reasons": list(item.blocked_reasons),
        }
        for item in items
        if item.blocked_reasons
    ]
    label_counts = Counter(item.label for item in items)
    return DependencyPlan(
        ledger_revision=state.requirement_ledger.revision,
        requirements=items,
        ready_groups=ready_groups,
        blocked=blocked,
        diagnostics={
            "scheduler": "planner_owned_dependency_scheduler",
            "max_parallel_read_batch_size": MAX_PARALLEL_READ_BATCH_SIZE,
            "label_counts": dict(sorted(label_counts.items())),
        },
    )


def attach_dependency_plan_diagnostics(state: PlannerOwnedAgentGraphState) -> DependencyPlan:
    plan = build_dependency_plan(state)
    payload = plan.model_dump(mode="json")
    state.execution_trace.diagnostics[DEPENDENCY_PLAN_DIAGNOSTIC_KEY] = payload
    history = list(state.execution_trace.diagnostics.get(DEPENDENCY_PLAN_HISTORY_DIAGNOSTIC_KEY) or [])
    compact = {
        "ledger_revision": plan.ledger_revision,
        "labels": {item.requirement_id: item.label for item in plan.requirements},
        "ready_requirement_ids": [item.requirement_id for item in plan.requirements if item.ready],
        "ready_groups": [group.model_dump(mode="json") for group in plan.ready_groups],
    }
    if not history or history[-1] != compact:
        history.append(compact)
    state.execution_trace.diagnostics[DEPENDENCY_PLAN_HISTORY_DIAGNOSTIC_KEY] = history[-20:]
    state.execution_trace.planner.diagnostics[DEPENDENCY_PLAN_DIAGNOSTIC_KEY] = {
        "ledger_revision": plan.ledger_revision,
        "label_counts": dict(plan.diagnostics.get("label_counts") or {}),
        "ready_group_count": len(plan.ready_groups),
    }
    return plan


def dependency_item_for_requirement(
    plan: DependencyPlan,
    requirement_id: str | None,
) -> DependencyRequirementPlan | None:
    if requirement_id is None:
        return None
    return next((item for item in plan.requirements if item.requirement_id == requirement_id), None)


def dependency_allows_requirement_action(
    plan: DependencyPlan,
    requirement_id: str | None,
) -> bool:
    item = dependency_item_for_requirement(plan, requirement_id)
    return bool(item is not None and item.ready)


def dependency_rejection_reason(
    plan: DependencyPlan,
    requirement_id: str | None,
) -> str:
    item = dependency_item_for_requirement(plan, requirement_id)
    if item is None:
        return f"dependency plan has no requirement label for {requirement_id or '<missing>'}"
    if item.ready:
        return ""
    reasons = ", ".join(item.blocked_reasons) or item.label
    return f"requirement {item.requirement_id} is not dependency-ready ({item.label}: {reasons})"


def dependency_allows_tool_call(
    plan: DependencyPlan,
    call: GraphToolCall,
) -> bool:
    return dependency_allows_requirement_action(plan, call.requirement_id)


def requirement_ids_for_parallel_read_batch(plan: DependencyPlan) -> set[str]:
    requirement_ids: set[str] = set()
    for group in plan.ready_groups:
        if group.mode == "parallel_read_batch":
            requirement_ids.update(group.requirement_ids)
    return requirement_ids


def _requirement_plan(
    state: PlannerOwnedAgentGraphState,
    requirement: RequirementLedgerEntry,
    *,
    active_evidence: Mapping[str, EvidenceLedgerEntry],
    active_evidence_by_requirement: Mapping[str, list[EvidenceLedgerEntry]],
) -> DependencyRequirementPlan:
    dependency_requirement_ids = _dependency_requirement_ids(requirement)
    dependency_evidence_refs = _dependency_evidence_refs(requirement)
    dependency_blockers = _dependency_blockers(
        requirement,
        dependency_requirement_ids=dependency_requirement_ids,
        dependency_evidence_refs=dependency_evidence_refs,
        active_evidence=active_evidence,
        active_evidence_by_requirement=active_evidence_by_requirement,
    )
    source = requirement.source_of_truth
    action = _action_for_requirement(requirement)
    cards = _hydrated_cards_for_requirement(state, requirement.id)
    tool_names = [card.tool_name for card in cards]

    if not requirement.required or requirement.status in _TERMINAL_REQUIREMENT_STATUSES:
        return DependencyRequirementPlan(
            requirement_id=requirement.id,
            label="satisfied_or_terminal",
            ready=False,
            depends_on_requirement_ids=dependency_requirement_ids,
            depends_on_evidence_refs=dependency_evidence_refs,
            source_of_truth=source,
            action=action,
            tool_names=tool_names,
            diagnostic_metadata={"requirement_status": requirement.status, "required": requirement.required},
        )

    if requirement.status == "blocked":
        return DependencyRequirementPlan(
            requirement_id=requirement.id,
            label="blocked",
            ready=False,
            depends_on_requirement_ids=dependency_requirement_ids,
            depends_on_evidence_refs=dependency_evidence_refs,
            blocked_reasons=["requirement_status_blocked", *list(requirement.blockers)],
            source_of_truth=source,
            action=action,
            tool_names=tool_names,
        )

    if _is_approval_requirement(requirement):
        return DependencyRequirementPlan(
            requirement_id=requirement.id,
            label="approval_required",
            ready=not dependency_blockers,
            can_batch=False,
            depends_on_requirement_ids=dependency_requirement_ids,
            depends_on_evidence_refs=dependency_evidence_refs,
            blocked_reasons=dependency_blockers,
            source_of_truth=source,
            action=action,
            tool_names=tool_names,
            diagnostic_metadata={"serialized": True},
        )

    if dependency_blockers:
        return DependencyRequirementPlan(
            requirement_id=requirement.id,
            label="depends_on_evidence",
            ready=False,
            depends_on_requirement_ids=dependency_requirement_ids,
            depends_on_evidence_refs=dependency_evidence_refs,
            blocked_reasons=dependency_blockers,
            source_of_truth=source,
            action=action,
            tool_names=tool_names,
        )

    read_profile = _read_profile(state, requirement, cards)
    if read_profile["label"] == "blocked":
        return DependencyRequirementPlan(
            requirement_id=requirement.id,
            label="blocked",
            ready=False,
            depends_on_requirement_ids=dependency_requirement_ids,
            depends_on_evidence_refs=dependency_evidence_refs,
            blocked_reasons=list(read_profile["blocked_reasons"]),
            source_of_truth=source,
            action=action,
            tool_names=tool_names,
            diagnostic_metadata=dict(read_profile["diagnostic_metadata"]),
        )
    return DependencyRequirementPlan(
        requirement_id=requirement.id,
        label=read_profile["label"],
        ready=True,
        can_batch=bool(read_profile["can_batch"]),
        depends_on_requirement_ids=dependency_requirement_ids,
        depends_on_evidence_refs=dependency_evidence_refs,
        batch_key=read_profile["batch_key"],
        source_of_truth=source,
        action=action,
        tool_names=tool_names,
        estimated_tool_call_count=int(read_profile["estimated_tool_call_count"]),
        diagnostic_metadata=dict(read_profile["diagnostic_metadata"]),
    )


def _dependency_requirement_ids(requirement: RequirementLedgerEntry) -> list[str]:
    ids: list[str] = []
    evidence_refs = set(_dependency_evidence_refs(requirement))
    if requirement.parent_requirement_id:
        ids.append(requirement.parent_requirement_id)
    ids.extend(ref for ref in requirement.depends_on if ref not in evidence_refs)
    return list(dict.fromkeys(str(value) for value in ids if str(value)))


def _dependency_evidence_refs(requirement: RequirementLedgerEntry) -> list[str]:
    return list(dict.fromkeys(str(value) for value in requirement.derived_from_evidence_refs if str(value)))


def _dependency_blockers(
    requirement: RequirementLedgerEntry,
    *,
    dependency_requirement_ids: list[str],
    dependency_evidence_refs: list[str],
    active_evidence: Mapping[str, EvidenceLedgerEntry],
    active_evidence_by_requirement: Mapping[str, list[EvidenceLedgerEntry]],
) -> list[str]:
    blockers: list[str] = []
    for requirement_id in dependency_requirement_ids:
        if not active_evidence_by_requirement.get(requirement_id):
            blockers.append(f"missing_active_parent_evidence:{requirement_id}")
    for evidence_ref in dependency_evidence_refs:
        evidence = active_evidence.get(evidence_ref)
        if evidence is None:
            blockers.append(f"missing_active_evidence_ref:{evidence_ref}")
            continue
        parent_id = requirement.parent_requirement_id
        if parent_id and evidence.requirement_id != parent_id:
            blockers.append(f"evidence_ref_not_from_parent:{evidence_ref}")
    return list(dict.fromkeys(blockers))


def _active_evidence_by_ref(state: PlannerOwnedAgentGraphState) -> dict[str, EvidenceLedgerEntry]:
    return {
        evidence.id: evidence
        for evidence in state.evidence_ledger.evidence
        if _evidence_can_satisfy_current_dependency_plan(state, evidence)
    }


def _active_evidence_by_requirement(
    evidence_items: Iterable[EvidenceLedgerEntry],
) -> dict[str, list[EvidenceLedgerEntry]]:
    by_requirement: dict[str, list[EvidenceLedgerEntry]] = {}
    for evidence in evidence_items:
        by_requirement.setdefault(evidence.requirement_id, []).append(evidence)
    return by_requirement


def _evidence_can_satisfy_current_dependency_plan(
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
    superseded_by = _coerce_positive_int(metadata.get("superseded_by_ledger_revision"))
    if superseded_by is not None and superseded_by <= state.requirement_ledger.revision:
        return False
    return True


def _is_approval_requirement(requirement: RequirementLedgerEntry) -> bool:
    return (
        requirement.requirement_type in _APPROVAL_REQUIREMENT_TYPES
        or requirement.intent_operation in _APPROVAL_OPERATIONS
        or requirement.constraints.get("requires_approval") is True
    )


def _action_for_requirement(requirement: RequirementLedgerEntry) -> CapabilityAction | None:
    if requirement.source_of_truth == "document_knowledge":
        return "search_documents"
    if requirement.intent_operation == "report_filtered_collection":
        return "list"
    if requirement.requirement_type == "multi_entity_status":
        return "read_many"
    if requirement.requirement_type == "single_entity_status":
        return "read_one"
    if requirement.intent_operation == "stage_mutation":
        return "update"
    if requirement.intent_operation == "request_approval":
        return "approve"
    return "read" if requirement.source_of_truth == "operational_state" else None


def _read_profile(
    state: PlannerOwnedAgentGraphState,
    requirement: RequirementLedgerEntry,
    cards: list[HydratedToolCard],
) -> dict[str, Any]:
    if requirement.source_of_truth == "document_knowledge" or requirement.requirement_type == "document_answer":
        return _sequential_read_profile("document_or_knowledge_read")
    if requirement.source_of_truth != "operational_state":
        return _blocked_read_profile("dependency_label_not_proven")
    if requirement.intent_operation not in {
        "report_status",
        "report_multi_status",
        "report_filtered_collection",
        "answer_document_question",
        "report_diagnostic",
    }:
        return _blocked_read_profile("dependency_label_not_proven")
    if requirement.requirement_type in _SEQUENTIAL_READ_TYPES:
        return _sequential_read_profile("collection_or_document_shape")
    if not cards:
        if _requirement_has_bounded_identity(requirement):
            return _independent_read_profile(
                can_batch=False,
                reason="bounded_identity_without_hydrated_tool_metadata",
                estimated_tool_call_count=_bounded_identity_count(requirement),
            )
        if _requirement_is_collection_read_shape(requirement):
            return _sequential_read_profile("collection_shape_without_hydrated_tool_metadata")
        return _blocked_read_profile("dependency_label_not_proven")

    candidate_sources = _candidate_source_by_tool(state, requirement.id)
    safe_cards = [
        card
        for card in cards
        if _card_is_safe_bounded_single_entity_api_read(card, requirement, candidate_sources=candidate_sources)
    ]
    if safe_cards:
        return _independent_read_profile(
            can_batch=True,
            reason="safe_bounded_single_entity_api_read",
            estimated_tool_call_count=_bounded_identity_count(requirement),
            tool_name=safe_cards[0].tool_name,
        )
    if any(_card_is_sequential_read(card, requirement, candidate_sources=candidate_sources) for card in cards):
        return _sequential_read_profile("readable_but_not_parallel_batch_safe")
    return _blocked_read_profile("dependency_label_not_proven")


def _independent_read_profile(
    *,
    can_batch: bool,
    reason: str,
    estimated_tool_call_count: int,
    tool_name: str | None = None,
) -> dict[str, Any]:
    return {
        "label": "independent_read",
        "can_batch": can_batch,
        "batch_key": "read:operational_state:bounded_single_entity_api" if can_batch else None,
        "estimated_tool_call_count": max(1, estimated_tool_call_count),
        "blocked_reasons": [],
        "diagnostic_metadata": {"reason": reason, "selected_batch_tool_name": tool_name},
    }


def _sequential_read_profile(reason: str) -> dict[str, Any]:
    return {
        "label": "sequential_read",
        "can_batch": False,
        "batch_key": None,
        "estimated_tool_call_count": 1,
        "blocked_reasons": [],
        "diagnostic_metadata": {"reason": reason},
    }


def _blocked_read_profile(reason: str) -> dict[str, Any]:
    return {
        "label": "blocked",
        "can_batch": False,
        "batch_key": None,
        "estimated_tool_call_count": 0,
        "blocked_reasons": [reason],
        "diagnostic_metadata": {"reason": reason, "fail_closed": True},
    }


def _card_is_safe_bounded_single_entity_api_read(
    card: HydratedToolCard,
    requirement: RequirementLedgerEntry,
    *,
    candidate_sources: Mapping[str, SourceOfTruth],
) -> bool:
    if _effective_card_source_of_truth(card, candidate_sources) != "operational_state":
        return False
    if not bool(card.is_read_only) or bool(card.requires_approval):
        return False
    if str(card.metadata.get("side_effect_level") or "NONE").upper() not in _SAFE_SIDE_EFFECT_LEVELS:
        return False
    if card_supports_collection_read(card):
        return False
    endpoint_shape = str(card.metadata.get("endpoint_shape") or "").strip().lower()
    if endpoint_shape in {"collection", "document_search", "mutation", "approval"}:
        return False
    if "search_documents" in set(card.actions):
        return False
    if not {"read_one", "read"}.intersection(set(card.actions)):
        return False
    if not _requirement_has_bounded_identity(requirement):
        return False
    required_identity_args = set(card.required_args) | set(card.path_params)
    if required_identity_args and not required_identity_args.intersection(identity_arg_names(requirement)):
        return False
    return True


def _card_is_sequential_read(
    card: HydratedToolCard,
    requirement: RequirementLedgerEntry,
    *,
    candidate_sources: Mapping[str, SourceOfTruth],
) -> bool:
    if not bool(card.is_read_only) or bool(card.requires_approval):
        return False
    if _effective_card_source_of_truth(card, candidate_sources) == "document_knowledge" or "search_documents" in set(card.actions):
        return True
    if card_supports_collection_read(card):
        return True
    if requirement.requirement_type in _SEQUENTIAL_READ_TYPES:
        return True
    return False


def _requirement_has_bounded_identity(requirement: RequirementLedgerEntry) -> bool:
    for arg_name in identity_arg_names(requirement):
        value = requirement.constraints.get(arg_name)
        if _is_bounded_identity_value(value):
            return True
    return False


def _bounded_identity_count(requirement: RequirementLedgerEntry) -> int:
    for arg_name in identity_arg_names(requirement):
        value = requirement.constraints.get(arg_name)
        if isinstance(value, list):
            return len([item for item in value if item not in (None, "", [], {})])
        if value not in (None, "", [], {}):
            return 1
    return 1


def _is_bounded_identity_value(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value) and all(item not in (None, "", [], {}) and not isinstance(item, (list, dict)) for item in value)
    return value not in (None, "", [], {}) and not isinstance(value, (list, dict))


def _requirement_is_collection_read_shape(requirement: RequirementLedgerEntry) -> bool:
    if requirement.requirement_type in _SEQUENTIAL_READ_TYPES:
        return True
    if requirement.intent_operation == "report_filtered_collection":
        return True
    return requirement.requirement_type == "multi_entity_status" and not _requirement_has_bounded_identity(requirement)


def _candidate_source_by_tool(
    state: PlannerOwnedAgentGraphState,
    requirement_id: str,
) -> dict[str, SourceOfTruth]:
    sources: dict[str, SourceOfTruth] = {}
    for window in state.candidate_tool_windows:
        if window.requirement_id != requirement_id:
            continue
        for candidate in window.candidates:
            if candidate.source_of_truth != "unknown":
                sources[candidate.tool_name] = candidate.source_of_truth
    return sources


def _effective_card_source_of_truth(
    card: HydratedToolCard,
    candidate_sources: Mapping[str, SourceOfTruth],
) -> SourceOfTruth:
    if card.source_of_truth != "unknown":
        return card.source_of_truth
    return candidate_sources.get(card.tool_name, "unknown")


def _ready_groups(items: list[DependencyRequirementPlan]) -> list[DependencyReadyGroup]:
    groups: list[DependencyReadyGroup] = []
    by_key: dict[str, list[DependencyRequirementPlan]] = {}
    for item in items:
        if item.ready and item.can_batch and item.batch_key:
            by_key.setdefault(item.batch_key, []).append(item)
    for key, key_items in by_key.items():
        selected: list[DependencyRequirementPlan] = []
        selected_call_count = 0
        for item in key_items:
            estimated = max(1, item.estimated_tool_call_count)
            if selected_call_count >= MAX_PARALLEL_READ_BATCH_SIZE:
                break
            if selected_call_count + estimated > MAX_PARALLEL_READ_BATCH_SIZE and selected:
                break
            selected.append(item)
            selected_call_count += min(estimated, MAX_PARALLEL_READ_BATCH_SIZE - selected_call_count)
        if selected_call_count < 2:
            continue
        groups.append(
            DependencyReadyGroup(
                group_id=f"dependency-group-{len(groups) + 1:03d}",
                mode="parallel_read_batch",
                requirement_ids=[item.requirement_id for item in selected],
                batch_key=key,
                max_batch_size=MAX_PARALLEL_READ_BATCH_SIZE,
                diagnostic_metadata={"estimated_tool_call_count": selected_call_count},
            )
        )
    return groups


def _hydrated_cards_for_requirement(
    state: PlannerOwnedAgentGraphState,
    requirement_id: str,
) -> list[HydratedToolCard]:
    return [
        card
        for group in state.hydrated_tool_cards
        if group.requirement_id == requirement_id
        for card in group.cards
    ]


def _requirement_by_id(
    state: PlannerOwnedAgentGraphState,
    requirement_id: str,
) -> RequirementLedgerEntry | None:
    return next(
        (requirement for requirement in state.requirement_ledger.requirements if requirement.id == requirement_id),
        None,
    )


def _coerce_positive_int(value: Any) -> int | None:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None
