from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..config import normalize_factory_agent_engine
from ..schemas import ToolInfo
from .tool_selector import ToolSelector
from .v2_capability_map import (
    build_capability_needs_for_text,
    build_requirement_ledger_from_sketch,
    build_requirement_sketch_for_text,
    build_v2_capability_map,
)
from .v2_contracts import (
    EngineVersion,
    EvidenceLedgerEntry,
    ExecutionTrace,
    PlannerOwnedLoopV2State,
    ToolRetrievalTrace,
)
from .v2_satisfaction import (
    V2RepeatedRetrievalGuard,
    apply_deterministic_evidence_satisfaction,
    validate_v2_final_state,
)
from .v2_tool_retriever import V2CapabilityToolRetriever


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


async def build_direct_v2_compatibility_state(
    *,
    tool_selector: ToolSelector,
    intent: str,
    tools_by_name: Mapping[str, ToolInfo],
    engine_mode: str | None,
    mode: str = "normal",
    direct_test_evidence: Sequence[EvidenceLedgerEntry | Mapping[str, Any]] | None = None,
) -> PlannerOwnedLoopV2State:
    resolved_mode = _resolve_compatibility_mode(engine_mode)

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

    retriever = V2CapabilityToolRetriever(tool_selector)
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
    return state


def build_failed_direct_v2_compatibility_state(error: str) -> PlannerOwnedLoopV2State:
    v2_engine = "v" + "2"
    fallback_state = PlannerOwnedLoopV2State(
        engine_version=v2_engine,
        execution_trace=ExecutionTrace(engine_version=v2_engine, generated_by=f"{v2_engine}_planner_loop"),
    )
    fallback_state.execution_trace.diagnostics["trace_generation_failed"] = error
    return fallback_state


def _resolve_compatibility_mode(engine_mode: str | None) -> EngineVersion:
    return normalize_factory_agent_engine(engine_mode)


def _merge_tool_retrieval_trace(target: ToolRetrievalTrace, incoming: ToolRetrievalTrace) -> None:
    target.call_count += incoming.call_count
    for name in incoming.selected_candidate_tool_names:
        target.selected_candidate_tool_names.append(name)
    target.backend_used = incoming.backend_used or target.backend_used
    target.reranker.call_count += incoming.reranker.call_count
    target.compatibility_fallback_used = target.compatibility_fallback_used or incoming.compatibility_fallback_used
