from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PLAN = REPO_ROOT / "docs" / "qa" / "PLANNER_OWNED_AGENT_LOOP_MIGRATION.md"
RUNTIME_ROOT = REPO_ROOT / "factory-agent" / "factory_agent"


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_phase1_documents_trace_schema_that_separates_legacy_from_v2_authority():
    plan = MIGRATION_PLAN.read_text(encoding="utf-8")

    required_trace_fields = [
        "engine_version",
        "execution_trace.generated_by",
        "execution_trace.planner.call_count",
        "execution_trace.tool_retrieval.call_count",
        "execution_trace.tool_retrieval.selected_candidate_tool_names",
        "execution_trace.tool_retrieval.reranker.call_count",
        "execution_trace.detectors.legacy_rag_shortcut.used",
        "execution_trace.detectors.legacy_working_intent_execution.used",
        "execution_trace.detectors.legacy_whole_query_tool_scope.used",
    ]
    for field in required_trace_fields:
        assert field in plan

    for authority_label in (
        "legacy_graph_loop",
        "legacy_rag_route",
        "legacy_working_intents",
        "v2_planner_loop",
    ):
        assert authority_label in plan


def test_phase1_legacy_boundary_sources_are_still_explicitly_detectable():
    plan_service = _read("factory-agent/factory_agent/services/plan_creation_service.py")
    intent_split = _read("factory-agent/factory_agent/graph/nodes/intent_split.py")
    planner_loop = _read("factory-agent/factory_agent/graph/nodes/planner_loop.py")
    tool_selector = _read("factory-agent/factory_agent/planning/tool_selector.py")

    rag_shortcut = 'if semantic_frame.route in {"rag.loto_procedure", "rag.procedure", "rag.safety_policy"}'
    create_plan_start = plan_service.index("async def create_plan")
    assert rag_shortcut in plan_service
    assert plan_service.index(rag_shortcut, create_plan_start) < plan_service.index(
        "selection = await self._tool_selector.select_tools",
        create_plan_start,
    )
    assert 'route="RAG_ONLY"' in plan_service
    assert "_answer_knowledge_question_as_plan" in plan_service

    assert '"working_intents": [dict(x) for x in payload]' in intent_split
    assert '"intent_cursor": 0' in intent_split
    assert "state.get(\"working_intents\")" in planner_loop
    assert "state.get(\"intent_cursor\")" in planner_loop
    assert "intent_completed" in planner_loop

    assert "semantic_frame_for_text(intent)" in tool_selector
    assert "self._top_candidates(" in tool_selector
    assert "filter_tools_for_intent(" in tool_selector


def test_phase1_runtime_does_not_claim_v2_engine_before_v2_loop_exists():
    pretend_v2_patterns = [
        re.compile(r"engine_version[\"']?\s*[:=]\s*[\"']v2(?:_shadow)?[\"']"),
        re.compile(r"generated_by[\"']?\s*[:=]\s*[\"']v2_planner_loop[\"']"),
    ]
    hits: list[str] = []
    for path in RUNTIME_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in pretend_v2_patterns:
            for match in pattern.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                hits.append(f"{path.relative_to(REPO_ROOT)}:{line}: {match.group(0)}")

    assert hits == [], "Phase 1 must not claim v2 runtime execution yet:\n" + "\n".join(hits)
