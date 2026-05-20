from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..config import FactoryAgentEngine, normalize_factory_agent_engine
from ..schemas import PlanDraft, PlanStepDraft, ToolInfo
from .intent import split_user_intents
from .tool_selector import ToolSelector
from .v2_capability_map import (
    build_capability_needs_for_text,
    build_requirement_ledger_from_sketch,
    build_requirement_sketch_for_text,
    build_v2_capability_map,
)
from .v2_contracts import (
    EvidenceLedgerEntry,
    ExecutionDetectors,
    ExecutionTrace,
    HydratedToolCard,
    LegacyRagRouteMetadata,
    LegacyRagShortcutTrace,
    LegacyWholeQueryToolScopeTrace,
    LegacyWorkingIntentExecutionTrace,
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
class LegacyExecutionSignals:
    generated_by: str = "legacy_graph_loop"
    planner_call_count: int = 0
    tool_retrieval_call_count: int = 0
    selected_candidate_tool_names: tuple[str, ...] = ()
    reranker_call_count: int = 0
    backend_used: str | None = None
    legacy_rag_route: str | None = None
    legacy_rag_source_function: str | None = None
    legacy_rag_policy_id: str | None = None
    legacy_rag_persisted_empty_plan: bool = False
    whole_query_tool_scope_used: bool = False
    whole_query_source_function: str | None = None
    working_intents_count: int | None = None
    intent_cursor_start: int | None = None
    intent_cursor_final: int | None = None
    intent_completed_count: int = 0
    planner_completion_only_call_count: int = 0


@dataclass(frozen=True)
class PlannerOwnedV2LoopRun:
    state: PlannerOwnedLoopV2State
    draft: PlanDraft | None = None
    tool_outputs: list[dict[str, Any]] | None = None


def legacy_graph_signals(
    *,
    intent: str,
    selected_candidate_tool_names: list[str] | tuple[str, ...] = (),
    planner_call_count: int = 0,
    reranker_call_count: int = 0,
    backend_used: str | None = None,
    source_function: str,
) -> LegacyExecutionSignals:
    return LegacyExecutionSignals(
        generated_by="legacy_working_intents",
        planner_call_count=max(0, planner_call_count),
        tool_retrieval_call_count=1 if selected_candidate_tool_names else 0,
        selected_candidate_tool_names=tuple(selected_candidate_tool_names),
        reranker_call_count=max(0, reranker_call_count),
        backend_used=backend_used,
        whole_query_tool_scope_used=bool(selected_candidate_tool_names),
        whole_query_source_function=source_function,
        working_intents_count=len(split_user_intents(intent)),
        intent_cursor_start=0,
        intent_cursor_final=None,
        intent_completed_count=0,
        planner_completion_only_call_count=0,
    )


def legacy_rag_signals(
    *,
    route: str,
    source_function: str,
    policy_id: str | None = None,
    persisted_empty_plan: bool = True,
) -> LegacyExecutionSignals:
    return LegacyExecutionSignals(
        generated_by="legacy_rag_route",
        planner_call_count=0,
        tool_retrieval_call_count=0,
        legacy_rag_route=route,
        legacy_rag_source_function=source_function,
        legacy_rag_policy_id=policy_id,
        legacy_rag_persisted_empty_plan=persisted_empty_plan,
    )


def build_legacy_execution_trace(
    signals: LegacyExecutionSignals | None = None,
    *,
    engine_version: FactoryAgentEngine = "legacy",
) -> ExecutionTrace:
    signals = signals or LegacyExecutionSignals()
    generated_by = signals.generated_by if signals.generated_by in {
        "legacy_graph_loop",
        "legacy_rag_route",
        "legacy_working_intents",
    } else "legacy_graph_loop"
    detectors = ExecutionDetectors()
    if signals.legacy_rag_route:
        detectors.legacy_rag_shortcut = LegacyRagShortcutTrace(
            used=True,
            route=signals.legacy_rag_route,
            source_function=signals.legacy_rag_source_function,
            policy_id=signals.legacy_rag_policy_id,
            persisted_empty_plan=signals.legacy_rag_persisted_empty_plan,
        )
    trace = ExecutionTrace(
        engine_version=engine_version,
        generated_by=generated_by,  # type: ignore[arg-type]
        detectors=detectors,
    )
    trace.planner.call_count = max(0, signals.planner_call_count)
    trace.tool_retrieval.call_count = max(0, signals.tool_retrieval_call_count)
    trace.tool_retrieval.selected_candidate_tool_names = list(signals.selected_candidate_tool_names)
    trace.tool_retrieval.backend_used = signals.backend_used
    trace.tool_retrieval.reranker.call_count = max(0, signals.reranker_call_count)
    trace.selected_tool_names = list(signals.selected_candidate_tool_names)
    _apply_legacy_detectors(trace, signals)
    return trace


def attach_legacy_trace_to_intent_contract(
    intent_contract: Mapping[str, Any] | None,
    *,
    intent: str,
    signals: LegacyExecutionSignals | None = None,
) -> dict[str, Any]:
    contract = dict(intent_contract or {})
    contract.setdefault("intent", intent)
    contract["engine_version"] = "legacy"
    contract["execution_trace"] = build_legacy_execution_trace(signals).model_dump(mode="json")
    return contract


def attach_v2_shadow_trace_to_intent_contract(
    intent_contract: Mapping[str, Any] | None,
    *,
    intent: str,
    v2_state: PlannerOwnedLoopV2State,
    legacy_signals: LegacyExecutionSignals | None = None,
) -> dict[str, Any]:
    contract = dict(intent_contract or {})
    contract.setdefault("intent", intent)
    legacy_trace = build_legacy_execution_trace(legacy_signals)
    contract["engine_version"] = "v2_shadow"
    contract["execution_trace"] = v2_state.execution_trace.model_dump(mode="json")
    contract["legacy_execution_trace"] = legacy_trace.model_dump(mode="json")
    contract["v2_shadow_state"] = v2_state.model_dump(mode="json")
    return contract


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

    async def run(
        self,
        *,
        intent: str,
        tools_by_name: Mapping[str, ToolInfo],
        engine_mode: str | None,
        legacy_signals: LegacyExecutionSignals | None = None,
        mode: str = "normal",
        direct_test_evidence: Sequence[EvidenceLedgerEntry | Mapping[str, Any]] | None = None,
    ) -> PlannerOwnedV2LoopRun:
        resolved_mode = normalize_factory_agent_engine(engine_mode)
        if resolved_mode == "legacy":
            state = PlannerOwnedLoopV2State(
                engine_version="legacy",
                execution_trace=build_legacy_execution_trace(legacy_signals),
            )
            return PlannerOwnedV2LoopRun(state=state)

        generated_by = "v2_shadow_planner_loop" if resolved_mode == "v2_shadow" else "v2_planner_loop"
        trace = ExecutionTrace(engine_version=resolved_mode, generated_by=generated_by)
        _apply_legacy_detectors(trace, legacy_signals or LegacyExecutionSignals())
        trace.diagnostics["visible_authority"] = "legacy" if resolved_mode == "v2_shadow" else "v2"
        trace.diagnostics["shadow_only"] = resolved_mode == "v2_shadow"
        trace.diagnostics["write_policy"] = (
            "trace_only_no_tool_execution"
            if resolved_mode == "v2_shadow"
            else "read_tools_only_writes_remain_dry_run"
        )

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

        if legacy_signals and legacy_signals.legacy_rag_route:
            state.evidence_ledger.evidence.append(
                EvidenceLedgerEntry(
                    id="legacy-rag-route-001",
                    requirement_id=(
                        requirement_ledger.requirements[0].id
                        if requirement_ledger.requirements
                        else "req-legacy-rag"
                    ),
                    source_type="legacy_rag_route",
                    source_of_truth="document_knowledge",
                    confidence="deterministic",
                    diagnostic_metadata={"represented_as": "legacy_route_not_v2_rag_tool"},
                    legacy_rag_route=LegacyRagRouteMetadata(
                        route=legacy_signals.legacy_rag_route,
                        source_function=legacy_signals.legacy_rag_source_function,
                        policy_id=legacy_signals.legacy_rag_policy_id,
                        persisted_empty_plan=legacy_signals.legacy_rag_persisted_empty_plan,
                    ),
                )
            )

        for raw_evidence in direct_test_evidence or ():
            evidence = (
                raw_evidence
                if isinstance(raw_evidence, EvidenceLedgerEntry)
                else EvidenceLedgerEntry.model_validate(raw_evidence)
            )
            state.evidence_ledger.evidence.append(evidence)

        if resolved_mode == "v2":
            apply_deterministic_evidence_satisfaction(state)
            validate_v2_final_state(state)
        else:
            trace.final_validator_status = "not_run_shadow_mode" if resolved_mode == "v2_shadow" else None

        draft = _direct_v2_draft(state, tools) if resolved_mode == "v2" else None
        return PlannerOwnedV2LoopRun(state=state, draft=draft, tool_outputs=[])


def _apply_legacy_detectors(trace: ExecutionTrace, signals: LegacyExecutionSignals) -> None:
    if signals.legacy_rag_route:
        trace.detectors.legacy_rag_shortcut = LegacyRagShortcutTrace(
            used=True,
            route=signals.legacy_rag_route,
            source_function=signals.legacy_rag_source_function,
            policy_id=signals.legacy_rag_policy_id,
            persisted_empty_plan=signals.legacy_rag_persisted_empty_plan,
        )
    if signals.working_intents_count is not None or signals.generated_by == "legacy_working_intents":
        trace.detectors.legacy_working_intent_execution = LegacyWorkingIntentExecutionTrace(
            used=True,
            working_intents_count=signals.working_intents_count,
            intent_cursor_start=signals.intent_cursor_start,
            intent_cursor_final=signals.intent_cursor_final,
        )
    if signals.whole_query_tool_scope_used:
        trace.detectors.legacy_whole_query_tool_scope = LegacyWholeQueryToolScopeTrace(
            used=True,
            source_function=signals.whole_query_source_function,
            selector_intent_scope="whole_user_query",
            selected_candidate_tool_names=list(signals.selected_candidate_tool_names),
        )
    trace.detectors.legacy_intent_completion_loop.used = (
        signals.intent_completed_count > 0 or signals.generated_by == "legacy_working_intents"
    )
    trace.detectors.legacy_intent_completion_loop.intent_completed_count = max(0, signals.intent_completed_count)
    trace.detectors.legacy_intent_completion_loop.planner_completion_only_call_count = max(
        0,
        signals.planner_completion_only_call_count,
    )


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
    cards_by_requirement: dict[str, list[HydratedToolCard]] = {
        cards.requirement_id: list(cards.cards) for cards in state.hydrated_tool_cards
    }
    for window in state.candidate_tool_windows:
        cards = cards_by_requirement.get(window.requirement_id, [])
        selected = next((card for card in cards if card.is_read_only), None)
        if selected is None:
            skipped_writes.extend(card.tool_name for card in cards if not card.is_read_only)
            continue
        steps.append(
            PlanStepDraft(
                step_index=len(steps),
                tool_name=selected.tool_name,
                args=_args_for_read_card(selected, window.capability_need),
                depends_on=[],
            )
        )

    if skipped_writes:
        state.execution_trace.diagnostics["dry_run_write_candidates"] = skipped_writes

    return PlanDraft(
        plan_explanation="V2 planner loop selected read-only tool candidates from capability needs.",
        risk_summary="Direct v2 test path only; writes are not committed and remain dry-run candidates.",
        steps=steps,
    )


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
    requested_fields = list(getattr(capability_need, "requested_fields", []) or [])
    if requested_fields and "fields" in query_params:
        args["fields"] = ",".join(str(field) for field in requested_fields)
    if card.source_of_truth == "document_knowledge" and "query" in query_params:
        args.setdefault("query", str(getattr(capability_need, "reason", "") or "document knowledge query"))
    return args
