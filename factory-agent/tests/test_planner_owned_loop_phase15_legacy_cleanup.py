from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from factory_agent.config import (
    get_settings,
    normalize_factory_agent_engine,
    resolve_factory_agent_engine_for_runtime,
)
from factory_agent.planning.v2_contracts import (
    EvidenceLedgerEntry,
    ExecutionTrace,
    LegacyRagRouteMetadata,
    LegacyRagShortcutTrace,
    PlannerOwnedLoopV2State,
    RequirementLedger,
    RequirementLedgerEntry,
    SatisfactionCheck,
)
from factory_agent.planning.v2_satisfaction import validate_v2_final_state


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / "factory-agent" / "factory_agent"
TESTS_ROOT = REPO_ROOT / "factory-agent" / "tests"

PARSE_ONLY_OR_QUARANTINED_RUNTIME_PATHS = {
    Path("planning/v2_contracts.py"),
    Path("planning/v2_satisfaction.py"),
    Path("planning/v2_interrupts.py"),
    Path("schemas.py"),
}

DISALLOWED_RUNTIME_AUTHORITY_FRAGMENTS = (
    "test_only_legacy_engine_enabled",
    "attach_legacy_trace_to_intent_contract",
    "attach_v2_shadow_trace_to_intent_contract",
    "build_legacy_execution_trace",
    "LegacyExecutionSignals",
    "legacy_graph_signals",
    "legacy_rag_signals",
    "planner_owned_loop_v2_shadow_emergency_fallback_used",
    "v2_shadow_trace_failed",
    "engine == \"legacy\"",
    "engine == 'legacy'",
)

HISTORICAL_TERMS = (
    "legacy_graph_loop",
    "legacy_rag_route",
    "legacy_working_intents",
    "v2_shadow",
    "working_intents",
    "intent_cursor",
    "intent_completed",
)

DISALLOWED_TEST_FRAGMENTS = (
    "pytest.mark." + "xfail",
    "pytest.mark." + "skip",
    "legacy" + "_compatibility",
    "LEGACY_RUNTIME_RETIRED_" + "XFAIL",
    "LEGACY_PLAN_STEP_PROJECTION_" + "XFAIL",
    "LEGACY_PHASE10_" + "REMOVAL",
)


def _runtime_files() -> list[Path]:
    return sorted(
        path
        for path in RUNTIME_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _relative_runtime(path: Path) -> Path:
    return path.relative_to(RUNTIME_ROOT)


def _is_parse_only_or_quarantined(path: Path) -> bool:
    relative = _relative_runtime(path)
    return relative in PARSE_ONLY_OR_QUARANTINED_RUNTIME_PATHS or relative.parts[:1] == ("graph",)


def test_phase15_runtime_engine_values_resolve_to_planner_owned_v2_only():
    assert normalize_factory_agent_engine(None) == "v2"
    assert normalize_factory_agent_engine("legacy") == "v2"
    assert normalize_factory_agent_engine("v2_shadow") == "v2"
    assert normalize_factory_agent_engine("unknown") == "v2"

    settings = replace(get_settings(), factory_agent_engine="legacy")  # type: ignore[arg-type]
    assert not hasattr(settings, "test_only_legacy_engine_enabled")
    assert resolve_factory_agent_engine_for_runtime(settings) == "v2"


def test_phase15_product_code_has_no_legacy_engine_or_shadow_activation_authority():
    hits: list[str] = []
    for path in _runtime_files():
        if _is_parse_only_or_quarantined(path):
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in DISALLOWED_RUNTIME_AUTHORITY_FRAGMENTS:
            if fragment in text:
                hits.append(f"{_relative_runtime(path).as_posix()}: {fragment}")

    assert hits == []


def test_phase15_historical_terms_are_parse_only_or_quarantined():
    hits: list[str] = []
    for path in _runtime_files():
        if _is_parse_only_or_quarantined(path):
            continue
        text = path.read_text(encoding="utf-8")
        for term in HISTORICAL_TERMS:
            if term in text:
                hits.append(f"{_relative_runtime(path).as_posix()}: {term}")

    assert hits == []


def test_phase15_legacy_compatibility_tests_and_xfails_are_retired():
    hits: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if path.name == "test_planner_owned_loop_phase15_legacy_cleanup.py":
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in DISALLOWED_TEST_FRAGMENTS:
            if fragment in text:
                hits.append(f"{path.relative_to(TESTS_ROOT).as_posix()}: {fragment}")

    assert hits == []
    assert not (TESTS_ROOT / "test_memory_planner_integration.py").exists()
    assert not (TESTS_ROOT / "test_reliability_e2e.py").exists()


def test_phase15_historical_trace_values_parse_but_cannot_satisfy_v2_requirements():
    trace = ExecutionTrace(
        engine_version="legacy",
        generated_by="legacy_rag_route",
        detectors={
            "legacy_rag_shortcut": LegacyRagShortcutTrace(
                used=True,
                route="rag.procedure",
                source_function="historical_trace_reader",
                policy_id="rag.procedure",
            )
        },
    )
    state = PlannerOwnedLoopV2State(engine_version="v2")
    state.execution_trace = trace
    state.requirement_ledger = RequirementLedger(
        user_goal="Answer a historical document question.",
        requirements=[
            RequirementLedgerEntry(
                id="req-document",
                goal="Answer the document question.",
                requirement_type="document_answer",
                intent_operation="answer_document_question",
                source_of_truth="document_knowledge",
                status="satisfied",
                evidence_refs=["ev-historical-rag"],
                satisfaction_checks=[
                    SatisfactionCheck(check="source_citation", passed=True, evidence_ref="ev-historical-rag")
                ],
            )
        ],
    )
    state.evidence_ledger.evidence.append(
        EvidenceLedgerEntry(
            id="ev-historical-rag",
            requirement_id="req-document",
            source_type="legacy_rag_route",
            source_of_truth="document_knowledge",
            legacy_rag_route=LegacyRagRouteMetadata(route="rag.procedure"),
        )
    )

    result = validate_v2_final_state(state)

    assert result.status == "failed"
    assert any(issue.issue == "legacy_rag_route_cannot_satisfy_v2" for issue in result.issues)
