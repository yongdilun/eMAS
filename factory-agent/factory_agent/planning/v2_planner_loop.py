from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..config import normalize_factory_agent_engine
from ..schemas import PlanDraft, PlanStepDraft, ToolInfo
from .tool_selector import ToolSelector
from .v2_capability_map import (
    build_capability_needs_for_text,
    build_requirement_ledger_from_sketch,
    build_requirement_sketch_for_text,
    build_v2_capability_map,
)
from .v2_contracts import (
    EvidenceLedgerEntry,
    ExecutionTrace,
    EngineVersion,
    HydratedToolCard,
    PlannerOwnedLoopV2State,
    ToolRetrievalTrace,
)
from .v2_satisfaction import (
    V2RepeatedRetrievalGuard,
    apply_deterministic_evidence_satisfaction,
    validate_v2_final_state,
)
from .v2_tool_retriever import V2CapabilityToolRetriever


@dataclass(frozen=True)
class PlannerOwnedV2LoopRun:
    state: PlannerOwnedLoopV2State
    draft: PlanDraft | None = None
    tool_outputs: list[dict[str, Any]] | None = None


def attach_direct_v2_trace_to_intent_contract(
    intent_contract: Mapping[str, Any] | None,
    *,
    intent: str,
    v2_state: PlannerOwnedLoopV2State,
) -> dict[str, Any]:
    contract = dict(intent_contract or {})
    contract.setdefault("intent", intent)
    contract["engine_version"] = "v2"
    contract["execution_trace"] = v2_state.execution_trace.model_dump(mode="json")
    contract["v2_state"] = v2_state.model_dump(mode="json")
    return contract


class PlannerOwnedV2Loop:
    """Phase 5 planner-owned loop scaffold behind explicit engine modes.

    The loop declares capability needs from the v2 ledger, retrieves small tool
    windows through ``V2CapabilityToolRetriever``, and records trace state. It
    does not commit writes. Direct v2 mode may produce a read-only draft for
    tests; shadow mode is trace-only.
    """

    def __init__(self, tool_selector: ToolSelector) -> None:
        self._tool_selector = tool_selector

    def _resolve_loop_mode(self, engine_mode: str | None) -> EngineVersion:
        return normalize_factory_agent_engine(engine_mode)

    async def run(
        self,
        *,
        intent: str,
        tools_by_name: Mapping[str, ToolInfo],
        engine_mode: str | None,
        mode: str = "normal",
        direct_test_evidence: Sequence[EvidenceLedgerEntry | Mapping[str, Any]] | None = None,
    ) -> PlannerOwnedV2LoopRun:
        resolved_mode = self._resolve_loop_mode(engine_mode)

        trace = ExecutionTrace(engine_version=resolved_mode, generated_by="v2_planner_loop")
        trace.diagnostics["visible_authority"] = "v2"
        trace.diagnostics["shadow_only"] = False
        trace.diagnostics["write_policy"] = "read_tools_only_writes_remain_dry_run"

        tools = dict(tools_by_name)
        capability_map = build_v2_capability_map(tools)
        requirement_sketch = build_requirement_sketch_for_text(intent, capability_map=capability_map)
        requirement_ledger = build_requirement_ledger_from_sketch(requirement_sketch)
        needs = build_capability_needs_for_text(intent, capability_map=capability_map)

        state = PlannerOwnedLoopV2State(
            engine_version=resolved_mode,
            execution_trace=trace,
            requirement_sketch=requirement_sketch,
            requirement_ledger=requirement_ledger,
            capability_map=capability_map,
        )
        trace.planner.call_count = 1 if requirement_sketch.requirements else 0
        trace.planner.diagnostics.update(
            {
                "planner_kind": "phase5_minimal_planner_owned_loop",
                "saw_original_request": bool(intent.strip()),
                "saw_high_level_capability_map": True,
                "saw_requirement_ledger": True,
                "saw_evidence_ledger": True,
                "received_full_tool_catalog_before_need": False,
                "capability_need_count": len(needs),
            }
        )
        trace.diagnostics["capability_needs"] = [need.model_dump(mode="json") for need in needs]
        trace.diagnostics["tool_selector_adapter"] = "V2CapabilityToolRetriever"
        trace.diagnostics["used_v2_capability_tool_retriever"] = True

        retriever = V2CapabilityToolRetriever(self._tool_selector)
        repeated_guard = V2RepeatedRetrievalGuard()
        guard_decisions: list[dict[str, Any]] = []
        repeated_keys: list[str] = []
        retrieval_diagnostics: list[dict[str, Any]] = []
        for need in needs:
            guard_decision = repeated_guard.check(need, state=state)
            guard_decisions.append(guard_decision.as_diagnostics())
            if guard_decision.blocked:
                repeated_keys.append(guard_decision.need_key)
                continue
            result = await retriever.retrieve_tools_for_need(
                need,
                tools_by_name=tools,
                requirement_id=need.requirement_id,
                requirement_refs={
                    "ledger_revision": requirement_ledger.revision,
                    "open_requirement_ids": [
                        req.id for req in requirement_ledger.requirements if req.status == "open"
                    ],
                },
                context_refs={"original_user_query": intent},
                mode=mode,
            )
            state.candidate_tool_windows.append(result.candidate_window)
            state.hydrated_tool_cards.append(result.hydrated_tool_cards)
            _merge_tool_retrieval_trace(trace.tool_retrieval, result.trace)
            trace.selected_tool_names = list(trace.tool_retrieval.selected_candidate_tool_names)
            retrieval_diagnostics.append(result.trace.diagnostics)

        guard_status = "blocked_repeated_need" if repeated_keys else "not_triggered"
        trace.diagnostics["repeated_retrieval_guard"] = {
            "status": guard_status,
            "repeated_need_keys": repeated_keys,
            "decisions": guard_decisions,
        }
        trace.tool_retrieval.diagnostics["retrievals"] = retrieval_diagnostics
        trace.diagnostics["candidate_tool_windows"] = [
            window.model_dump(mode="json") for window in state.candidate_tool_windows
        ]
        trace.diagnostics["hydrated_tool_cards"] = [
            cards.model_dump(mode="json") for cards in state.hydrated_tool_cards
        ]

        for raw_evidence in direct_test_evidence or ():
            evidence = (
                raw_evidence
                if isinstance(raw_evidence, EvidenceLedgerEntry)
                else EvidenceLedgerEntry.model_validate(raw_evidence)
            )
            state.evidence_ledger.evidence.append(evidence)

        apply_deterministic_evidence_satisfaction(state)
        validate_v2_final_state(state)

        draft = _direct_v2_draft(state, tools)
        return PlannerOwnedV2LoopRun(state=state, draft=draft, tool_outputs=[])


def _merge_tool_retrieval_trace(target: ToolRetrievalTrace, incoming: ToolRetrievalTrace) -> None:
    target.call_count += incoming.call_count
    for name in incoming.selected_candidate_tool_names:
        target.selected_candidate_tool_names.append(name)
    target.backend_used = incoming.backend_used or target.backend_used
    target.reranker.call_count += incoming.reranker.call_count
    target.compatibility_fallback_used = target.compatibility_fallback_used or incoming.compatibility_fallback_used


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
