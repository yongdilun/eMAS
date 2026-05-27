from __future__ import annotations

from typing import Any

from ..planning.v2_agent_state import GraphToolCall, PlannerDecisionRecord, PlannerOwnedAgentGraphState
from ..planning.v2_capability_map import build_capability_needs_for_text
from ..planning.v2_contracts import CapabilityNeed, HydratedToolCard
from ..planning.v2_tool_card_selection import (
    card_entity_matches_requirement as _card_entity_matches_requirement,
    card_supports_collection_read as _card_supports_collection_read,
    card_supports_single_entity_read as _card_supports_single_entity_read,
    identity_arg_names as _identity_arg_names,
)
from .v2_graph_interrupts import _planner_decision_is_active_for_graph_revision


def _candidate_tool_calls_for_requirement(
    state: PlannerOwnedAgentGraphState,
    *,
    requirement_id: str,
    capability_need: Any | None,
) -> list[GraphToolCall]:
    requirement = _requirement_by_id(state, requirement_id)
    if requirement is None:
        return []
    calls: list[GraphToolCall] = []
    for card in _hydrated_cards_for_requirement(state, requirement_id):
        raw = _tool_calls_for_card(
            state=state,
            card=card,
            requirement=requirement,
            capability_need=capability_need or _capability_need_for_requirement(state, requirement_id),
            requirement_id=requirement_id,
        )
        if isinstance(raw, list):
            calls.extend(raw)
        else:
            calls.append(raw)
    return calls


def _deterministic_choose_tool_if_state_proves_single_document_tool(
    *,
    state: PlannerOwnedAgentGraphState,
    retrieve_decision: PlannerDecisionRecord,
    candidate_tool_calls: list[GraphToolCall],
    decision_id: str,
) -> PlannerDecisionRecord | None:
    if len(candidate_tool_calls) != 1:
        return None
    call = candidate_tool_calls[0]
    if call.kind != "rag_tool":
        return None
    requirement = _requirement_by_id(state, call.requirement_id)
    card = _hydrated_card_for_tool_call(state, call)
    if requirement is None or requirement.status != "open" or card is None:
        return None
    if card.source_of_truth != "document_knowledge" or not card.is_read_only or card.requires_approval:
        return None
    return PlannerDecisionRecord(
        decision_id=decision_id,
        decision_kind="choose_tool",
        author="deterministic_guard",
        requirement_id=retrieve_decision.requirement_id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=retrieve_decision.capability_need,
        selected_tool_call=call,
        reason="Choose the only bounded document-knowledge tool call proven by retrieval.",
    )


def _tool_choice_requires_graph_approval(
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
) -> bool:
    calls = _planner_decision_selected_tool_calls(decision)
    call = calls[0] if len(calls) == 1 else None
    if call is None or call.kind != "api_tool":
        return False
    requirement = _requirement_by_id(state, call.requirement_id)
    card = _hydrated_card_for_tool_call(state, call)
    if card is not None:
        return bool(card.requires_approval) or not bool(card.is_read_only)
    return getattr(requirement, "requirement_type", None) in {"mutation_request", "approval_request"}


def _tool_calls_for_card(
    *,
    state: PlannerOwnedAgentGraphState,
    card: HydratedToolCard,
    requirement: Any,
    capability_need: Any,
    requirement_id: str,
) -> GraphToolCall | list[GraphToolCall]:
    candidate_window_id = _candidate_window_id_for_requirement(state, requirement_id)
    kind = "rag_tool" if card.source_of_truth == "document_knowledge" else "api_tool"
    args = _args_for_tool_call(card, requirement, capability_need)
    identity_values = _multi_entity_identity_values(requirement, capability_need)
    batch_arg = _batch_identity_arg(card, requirement)
    if (
        getattr(requirement, "requirement_type", None) == "multi_entity_status"
        and batch_arg is not None
        and len(identity_values) > 1
    ):
        base_args = {key: value for key, value in args.items() if key != batch_arg}
        return [
            GraphToolCall(
                call_id=f"call-{len(state.planner_decisions) + 1:03d}-{index:03d}",
                kind=kind,
                tool_name=card.tool_name,
                args={**base_args, batch_arg: value},
                requirement_id=requirement_id,
                candidate_window_id=candidate_window_id,
            )
            for index, value in enumerate(identity_values, start=1)
            if value not in (None, "", [], {})
        ]
    return GraphToolCall(
        call_id=f"call-{len(state.planner_decisions) + 1:03d}",
        kind=kind,
        tool_name=card.tool_name,
        args=args,
        requirement_id=requirement_id,
        candidate_window_id=candidate_window_id,
    )


def _select_graph_tool_card(requirement: Any, cards: list[HydratedToolCard]) -> HydratedToolCard:
    if getattr(requirement, "requirement_type", None) in {"mutation_request", "approval_request"}:
        for card in cards:
            if bool(card.requires_approval) or not bool(card.is_read_only):
                return card
    if getattr(requirement, "requirement_type", None) == "single_entity_status":
        for card in cards:
            if _card_supports_single_entity_read(card, requirement):
                return card
        for card in cards:
            if _card_entity_matches_requirement(card, requirement) and not _card_supports_collection_read(card):
                return card
    if getattr(requirement, "requirement_type", None) == "multi_entity_status":
        for card in cards:
            if _card_supports_collection_identity_read(card, requirement):
                return card
        for card in cards:
            if _card_supports_batched_item_read(card, requirement):
                return card
        for card in cards:
            if _card_supports_collection_read(card):
                return card
        for card in cards:
            if "{id}" not in card.tool_name and "id" not in set(card.required_args):
                return card
    if getattr(requirement, "requirement_type", None) == "filtered_collection":
        for card in cards:
            if _card_supports_collection_read(card):
                return card
        for card in cards:
            if "{id}" not in card.tool_name and "id" not in set(card.required_args):
                return card
    return cards[0]


def _card_supports_collection_identity_read(card: HydratedToolCard, requirement: Any) -> bool:
    if not _card_supports_collection_read(card):
        return False
    return bool(set(card.query_params).intersection(_identity_arg_names(requirement)))


def _card_supports_batched_item_read(card: HydratedToolCard, requirement: Any) -> bool:
    if not bool(card.is_read_only) or bool(card.requires_approval):
        return False
    if getattr(requirement, "requirement_type", None) != "multi_entity_status":
        return False
    return _batch_identity_arg(card, requirement) is not None


def _batch_identity_arg(card: HydratedToolCard, requirement: Any) -> str | None:
    path_or_required = list(dict.fromkeys([*card.path_params, *card.required_args]))
    if not path_or_required:
        return None
    identity_names = _identity_arg_names(requirement)
    for arg_name in path_or_required:
        if arg_name in identity_names:
            return arg_name
    if "id" in path_or_required:
        return "id"
    return path_or_required[0]


def _multi_entity_identity_values(requirement: Any, capability_need: Any) -> list[Any]:
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    constraints.update(getattr(capability_need, "known_args", {}) or {})
    for key in _identity_arg_names(requirement):
        value = constraints.get(key)
        if isinstance(value, list):
            return list(value)
    return []


def _hydrated_card_for_tool_call(
    state: PlannerOwnedAgentGraphState,
    call: GraphToolCall,
) -> HydratedToolCard | None:
    return next((card for card in _hydrated_cards_for_requirement(state, call.requirement_id) if card.tool_name == call.tool_name), None)


def _has_decision_for_requirement(
    state: PlannerOwnedAgentGraphState,
    decision_kind: str,
    requirement_id: str,
) -> bool:
    return any(
        decision.decision_kind == decision_kind and decision.requirement_id == requirement_id
        and _planner_decision_is_active_for_graph_revision(state, decision)
        for decision in state.planner_decisions
    )


def _has_candidate_window_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> bool:
    return any(window.requirement_id == requirement_id for window in state.candidate_tool_windows) and any(
        cards.requirement_id == requirement_id for cards in state.hydrated_tool_cards
    )


def _has_choice_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> bool:
    return any(
        decision.decision_kind == "choose_tool"
        and decision.requirement_id == requirement_id
        and _planner_decision_is_active_for_graph_revision(state, decision)
        for decision in state.planner_decisions
    )


def _has_execution_decision_for_call(
    state: PlannerOwnedAgentGraphState,
    tool_call: GraphToolCall,
) -> bool:
    return any(
        decision.decision_kind in {"execute_tool", "execute_parallel_read_batch"}
        and _planner_decision_is_active_for_graph_revision(state, decision)
        and any(selected.call_id == tool_call.call_id for selected in _planner_decision_selected_tool_calls(decision))
        for decision in state.planner_decisions
    )


def _planner_decision_selected_tool_calls(decision: PlannerDecisionRecord) -> list[GraphToolCall]:
    calls: list[GraphToolCall] = []
    if decision.selected_tool_call is not None:
        calls.append(decision.selected_tool_call)
    calls.extend(decision.selected_tool_calls)
    deduped: list[GraphToolCall] = []
    seen_call_ids: set[str] = set()
    for call in calls:
        if call.call_id in seen_call_ids:
            continue
        seen_call_ids.add(call.call_id)
        deduped.append(call)
    return deduped


def _capability_need_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> CapabilityNeed:
    needs = build_capability_needs_for_text(state.original_query, capability_map=state.capability_map)
    for need in needs:
        if need.requirement_id == requirement_id:
            return need
    requirement = _requirement_by_id(state, requirement_id)
    if requirement is None:
        raise ValueError(f"missing requirement for capability need: {requirement_id}")
    return CapabilityNeed(
        requirement_id=requirement.id,
        source_of_truth=requirement.source_of_truth,
        entity=requirement.entity,
        action="search_documents" if requirement.source_of_truth == "document_knowledge" else "read",
        known_args={
            key: value
            for key, value in requirement.constraints.items()
            if key.endswith("_id") or key in {"id", "machine_ref"}
        },
        constraints=dict(requirement.constraints),
        requested_fields=list(requirement.requested_fields),
        reason="phase4_graph_requirement_fallback",
    )


def _requirement_by_id(state: PlannerOwnedAgentGraphState, requirement_id: str | None):
    if requirement_id is None:
        return None
    return next(
        (requirement for requirement in state.requirement_ledger.requirements if requirement.id == requirement_id),
        None,
    )


def _candidate_window_id_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> str | None:
    for index, window in enumerate(state.candidate_tool_windows, start=1):
        if window.requirement_id == requirement_id:
            return f"window-{index:03d}"
    return None


def _hydrated_cards_for_requirement(state: PlannerOwnedAgentGraphState, requirement_id: str) -> list[HydratedToolCard]:
    return [
        card
        for cards in state.hydrated_tool_cards
        if cards.requirement_id == requirement_id
        for card in cards.cards
    ]


def _args_for_tool_call(card: HydratedToolCard, requirement: Any, capability_need: Any) -> dict[str, Any]:
    args: dict[str, Any] = {}
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    for arg_name in dict.fromkeys([*card.required_args, *card.path_params]):
        value = _argument_value_for(arg_name, requirement, capability_need)
        if value not in (None, "", [], {}):
            args[arg_name] = value
    for key, value in constraints.items():
        if key in card.query_params or key in card.input_schema.get("properties", {}):
            args.setdefault(key, value)
    output_fields = list(getattr(requirement, "requested_fields", []) or [])
    observation_fields = constraints.get("observation_fields")
    if isinstance(observation_fields, list):
        output_fields.extend(str(field) for field in observation_fields if str(field))
    if card.supports_fields and output_fields:
        args.setdefault("fields", ",".join(dict.fromkeys(output_fields)))
    return args


def _argument_value_for(arg_name: str, requirement: Any, capability_need: Any) -> Any:
    constraints = dict(requirement.constraints)
    constraints.update(getattr(capability_need, "known_args", {}) or {})
    if arg_name in constraints:
        return constraints[arg_name]
    if arg_name == "id" and requirement.entity:
        entity_id = constraints.get(f"{requirement.entity}_id")
        if isinstance(entity_id, list):
            return None
        if entity_id not in (None, "", [], {}):
            return entity_id
    if arg_name == "id":
        for key, value in constraints.items():
            if isinstance(value, list):
                continue
            if key.endswith("_id") or key in {"machine_ref"}:
                return value
    if arg_name == "query" and requirement.source_of_truth == "document_knowledge":
        return requirement.goal
    return None
