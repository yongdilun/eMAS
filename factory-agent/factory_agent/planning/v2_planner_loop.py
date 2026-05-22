from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..schemas import PlanDraft, PlanStepDraft, ToolInfo
from .tool_selector import ToolSelector
from .v2_contracts import (
    EvidenceLedgerEntry,
    HydratedToolCard,
    PlannerOwnedLoopV2State,
)
from .v2_trace_compatibility import (
    attach_direct_v2_trace_to_intent_contract,
    build_direct_v2_compatibility_state,
)


@dataclass(frozen=True)
class PlannerOwnedV2LoopRun:
    state: PlannerOwnedLoopV2State
    draft: PlanDraft | None = None
    tool_outputs: list[dict[str, Any]] | None = None


class PlannerOwnedV2Loop:
    """Phase 5 planner-owned loop scaffold behind explicit engine modes.

    The loop declares capability needs from the v2 ledger, retrieves small tool
    windows through ``V2CapabilityToolRetriever``, and records trace state. It
    does not commit writes. Direct v2 mode may produce a read-only draft for
    tests; shadow mode is trace-only.
    """

    def __init__(self, tool_selector: ToolSelector) -> None:
        self._tool_selector = tool_selector

    async def run(
        self,
        *,
        intent: str,
        tools_by_name: Mapping[str, ToolInfo],
        engine_mode: str | None,
        mode: str = "normal",
        direct_test_evidence: Sequence[EvidenceLedgerEntry | Mapping[str, Any]] | None = None,
    ) -> PlannerOwnedV2LoopRun:
        state = await build_direct_v2_compatibility_state(
            tool_selector=self._tool_selector,
            intent=intent,
            tools_by_name=tools_by_name,
            engine_mode=engine_mode,
            mode=mode,
            direct_test_evidence=direct_test_evidence,
        )
        draft = _direct_v2_draft(state, tools_by_name)
        return PlannerOwnedV2LoopRun(state=state, draft=draft, tool_outputs=[])


def _direct_v2_draft(
    state: PlannerOwnedLoopV2State,
    tools_by_name: Mapping[str, ToolInfo],
) -> PlanDraft:
    steps: list[PlanStepDraft] = []
    skipped_writes: list[str] = []
    step_requirements: list[dict[str, Any]] = []
    cards_by_requirement: dict[str, list[HydratedToolCard]] = {
        cards.requirement_id: list(cards.cards) for cards in state.hydrated_tool_cards
    }
    for window in state.candidate_tool_windows:
        cards = cards_by_requirement.get(window.requirement_id, [])
        skipped_writes.extend(card.tool_name for card in cards if not card.is_read_only)
        selected = _select_read_card_for_need(cards, window.capability_need)
        if selected is None:
            continue
        for args in _expanded_args_for_read_card(selected, window.capability_need):
            steps.append(
                PlanStepDraft(
                    step_index=len(steps),
                    tool_name=selected.tool_name,
                    args=args,
                    depends_on=[],
                )
            )
            step_requirements.append(
                {
                    "step_index": len(steps) - 1,
                    "requirement_id": window.requirement_id,
                    "tool_name": selected.tool_name,
                    "capability_need": window.capability_need.model_dump(mode="json"),
                }
            )

    if skipped_writes:
        state.execution_trace.diagnostics["dry_run_write_candidates"] = skipped_writes
    if step_requirements:
        state.execution_trace.diagnostics["direct_v2_step_requirements"] = step_requirements

    return PlanDraft(
        plan_explanation="V2 planner loop selected read-only tool candidates from capability needs.",
        risk_summary="Direct v2 test path only; writes are not committed and remain dry-run candidates.",
        steps=steps,
    )


def _select_read_card_for_need(cards: Sequence[HydratedToolCard], capability_need: Any) -> HydratedToolCard | None:
    candidates: list[tuple[tuple[int, int, int, int, int], HydratedToolCard]] = []
    need_entity = str(getattr(capability_need, "entity", "") or "").strip().lower()
    need_action = str(getattr(capability_need, "action", "") or "").strip().lower()
    expected_shape = (
        "item"
        if _need_has_multiple_entity_ids(capability_need)
        else "collection"
        if need_action in {"list", "read_many", "search_documents"}
        else "item"
    )

    for index, card in enumerate(cards):
        if not card.is_read_only:
            continue
        args = _args_for_read_card(card, capability_need)
        missing_required = [arg for arg in card.required_args if args.get(arg) in (None, "", [], {})]
        if missing_required:
            continue
        metadata = card.metadata if isinstance(card.metadata, dict) else {}
        endpoint_root = str(metadata.get("endpoint_root") or "").strip().lower()
        endpoint_shape = str(metadata.get("endpoint_shape") or "").strip().lower()
        entity_match = int(bool(need_entity and endpoint_root == need_entity))
        shape_match = int(bool(expected_shape and endpoint_shape == expected_shape))
        action_match = int(need_action in {str(action).lower() for action in card.actions})
        source_match = int(card.source_of_truth == getattr(capability_need, "source_of_truth", None))
        candidates.append(((entity_match, shape_match, action_match, source_match, -index), card))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _need_has_multiple_entity_ids(capability_need: Any) -> bool:
    entity = str(getattr(capability_need, "entity", "") or "").strip()
    keys = ["id"]
    if entity:
        keys.extend([f"{entity}_id", f"{entity}_ref"])
    merged = {
        **dict(getattr(capability_need, "constraints", {}) or {}),
        **dict(getattr(capability_need, "known_args", {}) or {}),
    }
    return any(isinstance(merged.get(key), list) and len(merged.get(key) or []) > 1 for key in keys)


def _args_for_read_card(card: HydratedToolCard, capability_need: Any) -> dict[str, Any]:
    known_args = dict(getattr(capability_need, "known_args", {}) or {})
    constraints = dict(getattr(capability_need, "constraints", {}) or {})
    merged = {**constraints, **known_args}
    entity = getattr(capability_need, "entity", None)
    args: dict[str, Any] = {}

    for required in card.required_args:
        value = merged.get(required)
        if value is None and required == "id" and entity:
            value = merged.get(f"{entity}_id") or merged.get(f"{entity}_ref")
        if value is not None:
            args[required] = value

    query_params = set(card.query_params)
    for key, value in merged.items():
        if key in query_params and value not in (None, "", [], {}):
            args[key] = value
    requested_fields = _requested_fields_for_read_card(card, capability_need)
    if requested_fields and "fields" in query_params:
        args["fields"] = ",".join(str(field) for field in requested_fields)
    if card.source_of_truth == "document_knowledge" and "query" in query_params:
        args.setdefault("query", str(getattr(capability_need, "reason", "") or "document knowledge query"))
    return args


def _expanded_args_for_read_card(card: HydratedToolCard, capability_need: Any) -> list[dict[str, Any]]:
    args = _args_for_read_card(card, capability_need)
    for required in card.required_args:
        value = args.get(required)
        if isinstance(value, list):
            expanded = []
            for item in value:
                if item in (None, "", [], {}):
                    continue
                expanded.append({**args, required: item})
            return expanded or [args]
    return [args]


def _requested_fields_for_read_card(card: HydratedToolCard, capability_need: Any) -> list[str]:
    fields = [str(field) for field in (getattr(capability_need, "requested_fields", []) or []) if str(field)]
    action = str(getattr(capability_need, "action", "") or "").strip().lower()
    entity = str(getattr(capability_need, "entity", "") or "").strip().lower()
    identity_fields = {"id", "entity_id", "record_id"}
    if entity:
        identity_fields.add(f"{entity}_id")
        if entity.endswith("ies") and len(entity) > 3:
            identity_fields.add(f"{entity[:-3]}y_id")
        elif entity.endswith("s") and len(entity) > 1:
            identity_fields.add(f"{entity[:-1]}_id")
    normalized_fields = {field.strip().lower() for field in fields}
    path_identity_args = {str(arg).strip().lower() for arg in card.required_args or []}
    if (
        "status" in normalized_fields
        and normalized_fields <= {*identity_fields, "status"}
        and path_identity_args.intersection(identity_fields)
    ):
        return [field for field in fields if field.strip().lower() not in identity_fields] or ["status"]
    if action not in {"update", "create"}:
        if action not in {"list", "read_many"}:
            if "status" in normalized_fields and normalized_fields <= {*identity_fields, "status"}:
                return [field for field in fields if field.strip().lower() not in identity_fields] or ["status"]
            return fields
        constraints = dict(getattr(capability_need, "constraints", {}) or {})
        collection_identity_fields: list[str] = []
        if entity:
            collection_identity_fields.append(f"{entity}_id")
        collection_evidence_fields = []
        if constraints.get("sort_by") not in (None, "", [], {}):
            collection_evidence_fields.append(str(constraints.get("sort_by")))
        for key in ("priority", "status"):
            if not fields and constraints.get(key) not in (None, "", [], {}):
                collection_evidence_fields.append(key)
        return list(dict.fromkeys([*collection_identity_fields, *fields, *collection_evidence_fields]))

    entity = str(getattr(capability_need, "entity", "") or "").strip().lower()
    constraints = dict(getattr(capability_need, "constraints", {}) or {})
    safety_text = " ".join(str(item) for item in constraints.get("safety_constraints", []) or [])
    inferred: list[str] = []
    if entity:
        inferred.append(f"{entity}_id")
    for key in constraints:
        normalized = str(key)
        if normalized in {
            "new_priority",
            "requires_approval",
            "preview_before_apply",
            "safety_constraints",
            "conditional_branches",
        }:
            continue
        if normalized == "date":
            inferred.append("deadline")
        else:
            inferred.append(normalized)
    if "blocked" in safety_text.lower():
        inferred.append("status")
    output_fields = {
        str(field)
        for field in ((card.metadata or {}).get("output_fields") or [])
        if str(field)
    }
    merged = list(dict.fromkeys([*fields, *inferred]))
    if output_fields:
        merged = [field for field in merged if field in output_fields]
    return merged
