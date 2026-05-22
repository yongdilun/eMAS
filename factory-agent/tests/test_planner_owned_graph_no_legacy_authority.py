from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from factory_agent.config import (
    get_settings,
    normalize_factory_agent_engine,
    resolve_factory_agent_engine_for_runtime,
)
from factory_agent.planning.historical_legacy_rag_route_compatibility import (
    historical_legacy_rag_route_cannot_satisfy_issue,
    historical_legacy_rag_route_generated_by,
    historical_legacy_rag_route_source_type,
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
from factory_agent.planning.v2_planner_proposer import (
    OfflineStructuredPlannerDecisionProposer,
    OpenAICompatibleQwenPlannerDecisionProposer,
    planner_proposer_diagnostics_satisfy_real_llm_release_proof,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / "factory-agent" / "factory_agent"
TESTS_ROOT = REPO_ROOT / "factory-agent" / "tests"
PLAN_CREATION_SOURCE = RUNTIME_ROOT / "services" / "plan_creation_service.py"
PLAN_CREATION_COMPATIBILITY_SOURCE = RUNTIME_ROOT / "services" / "plan_creation_compatibility.py"
PLANNER_SERVICE_SOURCE = RUNTIME_ROOT / "services" / "planner_service.py"
EXECUTION_SERVICE_SOURCE = RUNTIME_ROOT / "services" / "execution_service.py"
APPROVAL_RESUME_SERVICE_SOURCE = RUNTIME_ROOT / "services" / "approval_resume_service.py"
APPROVALS_ROUTER_SOURCE = RUNTIME_ROOT / "api" / "routers" / "approvals.py"
SESSION_DETECTION_SOURCE = RUNTIME_ROOT / "graph" / "session_detection.py"
GRAPH_RUNTIME_SOURCE = RUNTIME_ROOT / "services" / "planner_owned_graph_runtime.py"
V2_AGENT_GRAPH_SOURCE = RUNTIME_ROOT / "graph" / "v2_agent_graph.py"
APPROVAL_SUMMARY_SOURCE = RUNTIME_ROOT / "graph" / "approval_summary.py"
STRUCTURED_OUTPUT_SOURCE = RUNTIME_ROOT / "llm" / "structured_output.py"
PLAN_PARSING_SOURCE = RUNTIME_ROOT / "llm" / "plan_parsing.py"
SCHEMAS_SOURCE = RUNTIME_ROOT / "schemas.py"
V2_TRACE_COMPATIBILITY_SOURCE = RUNTIME_ROOT / "planning" / "v2_trace_compatibility.py"
HISTORICAL_DIRECT_V2_COMPATIBILITY_SOURCE = RUNTIME_ROOT / "planning" / "historical_direct_v2_compatibility.py"
HISTORICAL_LEGACY_RAG_ROUTE_COMPATIBILITY_SOURCE = (
    RUNTIME_ROOT / "planning" / "historical_legacy_rag_route_compatibility.py"
)
V2_PLANNER_LOOP_SOURCE = RUNTIME_ROOT / "planning" / "v2_planner_loop.py"
CLEANUP_TRACK_SOURCE = REPO_ROOT / "docs" / "qa" / "PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md"

TRACKER_BLOCKED_PLAN_CREATION_DIRECT_V2_HELPERS: set[str] = set()

DELETED_PLAN_CREATION_DIRECT_V2_HELPERS = {
    "_append_direct_v2_api_evidence",
    "_direct_v2_aggregate_multi_entity_evidence",
    "_direct_v2_approval_payload",
    "_direct_v2_business_change_id",
    "_direct_v2_business_change_label",
    "_direct_v2_business_change_plan",
    "_direct_v2_canonical_output_key",
    "_direct_v2_change_summary",
    "_direct_v2_current_week_window",
    "_direct_v2_entity_from_tool",
    "_direct_v2_entity_from_tool_name",
    "_direct_v2_entity_noun",
    "_direct_v2_error_summary",
    "_direct_v2_evidence_has_error",
    "_direct_v2_final_validation_failed",
    "_direct_v2_first_mapping",
    "_direct_v2_has_failed_output",
    "_direct_v2_identity_fields",
    "_direct_v2_is_source_hint_query",
    "_direct_v2_is_rag_tool",
    "_direct_v2_llm_call_count",
    "_direct_v2_mutation_requirements",
    "_direct_v2_no_op_mutation_for_requirement",
    "_direct_v2_parse_date",
    "_direct_v2_prepare_evidence_for_satisfaction",
    "_direct_v2_project_api_body",
    "_direct_v2_project_api_row",
    "_direct_v2_production_week_window",
    "_direct_v2_rag_execution_query",
    "_direct_v2_requirement",
    "_direct_v2_row_due_date",
    "_direct_v2_row_matches_date_constraint",
    "_direct_v2_rows_from_evidence",
    "_direct_v2_schema_entity",
    "_direct_v2_selector_summary",
    "_direct_v2_serialized_business_change",
    "_direct_v2_should_stage_approval",
    "_direct_v2_source_priority_constraint",
    "_direct_v2_stage_rows",
    "_direct_v2_step_requirement_map",
    "_direct_v2_write_tool_name",
    "_execute_direct_v2_api_step",
    "_execute_direct_v2_rag_step",
    "_execute_direct_v2_steps",
    "_maybe_create_direct_v2_rag_response",
}

PARSE_ONLY_OR_QUARANTINED_RUNTIME_PATHS = {
    Path("planning/v2_contracts.py"),
    Path("planning/v2_satisfaction.py"),
    Path("planning/v2_interrupts.py"),
    Path("planning/v2_trace_compatibility.py"),
    Path("planning/historical_direct_v2_compatibility.py"),
    Path("planning/historical_legacy_rag_route_compatibility.py"),
    Path("schemas.py"),
}

HISTORICAL_GRAPH_QUARANTINE_RUNTIME_PATHS: set[Path] = set()

DELETED_OLD_GRAPH_SCAFFOLD_RUNTIME_PATHS = {
    Path("graph/builder.py"),
    Path("graph/errors.py"),
    Path("graph/planner_graph.py"),
    Path("graph/planner_graph_helpers.py"),
    Path("graph/state.py"),
    Path("graph/nodes/__init__.py"),
    Path("graph/nodes/intent_split.py"),
    Path("graph/nodes/planner_loop.py"),
    Path("graph/nodes/prepare.py"),
    Path("graph/nodes/reason.py"),
    Path("graph/nodes/tool_pipeline.py"),
    Path("graph/nodes/validate.py"),
}

OLD_GRAPH_SCAFFOLD_RUNTIME_PATHS = DELETED_OLD_GRAPH_SCAFFOLD_RUNTIME_PATHS

OLD_GRAPH_SCAFFOLD_IMPORT_MODULES = {
    "factory_agent.graph.builder",
    "factory_agent.graph.errors",
    "factory_agent.graph.planner_graph",
    "factory_agent.graph.planner_graph_helpers",
    "factory_agent.graph.state",
    "factory_agent.graph.nodes",
    "factory_agent.graph.nodes.intent_split",
    "factory_agent.graph.nodes.planner_loop",
    "factory_agent.graph.nodes.prepare",
    "factory_agent.graph.nodes.reason",
    "factory_agent.graph.nodes.tool_pipeline",
    "factory_agent.graph.nodes.validate",
}

ACTIVE_RUNTIME_OLD_GRAPH_COMPATIBILITY_IMPORTS: set[tuple[str, str, tuple[str, ...]]] = set()

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

QUARANTINED_MODULE_MARKER = "pytestmark = pytest.mark.legacy_architecture_quarantine"
QUARANTINED_MODULE_TESTS = {
    Path("test_historical_direct_v2_trace_compatibility.py"),
    Path("test_historical_direct_v2_hard_query_compatibility.py"),
}
QUARANTINED_TEST_FUNCTIONS = {
    Path("test_api_endpoints.py"): {
        "test_phase14_historical_approval_payload_resume_queues_second_actionable_approval",
    },
}


def _runtime_files() -> list[Path]:
    return sorted(
        path
        for path in RUNTIME_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _relative_runtime(path: Path) -> Path:
    return path.relative_to(RUNTIME_ROOT)


def _absolute_import_module(path: Path, module: str, level: int) -> str:
    if level == 0:
        return module
    relative = _relative_runtime(path)
    package_parts = ["factory_agent", *relative.parent.parts]
    if level > 1:
        package_parts = package_parts[: -(level - 1)]
    if module:
        package_parts.extend(module.split("."))
    return ".".join(package_parts)


def _is_parse_only_or_quarantined(path: Path) -> bool:
    relative = _relative_runtime(path)
    return relative in PARSE_ONLY_OR_QUARANTINED_RUNTIME_PATHS | HISTORICAL_GRAPH_QUARANTINE_RUNTIME_PATHS


def _function_node(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    module = ast.parse(source)
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()

    def _name(expr: ast.AST) -> str:
        if isinstance(expr, ast.Call):
            return _name(expr.func)
        if isinstance(expr, ast.Attribute):
            parent = _name(expr.value)
            return f"{parent}.{expr.attr}" if parent else expr.attr
        if isinstance(expr, ast.Name):
            return expr.id
        return ""

    for decorator in node.decorator_list:
        name = _name(decorator)
        if name:
            names.add(name)
    return names


def _defined_function_names(source: str) -> set[str]:
    return {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_runtime_engine_values_resolve_to_planner_owned_v2_only():
    assert normalize_factory_agent_engine(None) == "v2"
    assert normalize_factory_agent_engine("legacy") == "v2"
    assert normalize_factory_agent_engine("v2_shadow") == "v2"
    assert normalize_factory_agent_engine("unknown") == "v2"

    settings = replace(get_settings(), factory_agent_engine="legacy")  # type: ignore[arg-type]
    assert not hasattr(settings, "test_only_legacy_engine_enabled")
    assert resolve_factory_agent_engine_for_runtime(settings) == "v2"


def test_product_code_has_no_legacy_engine_or_shadow_activation_authority():
    hits: list[str] = []
    for path in _runtime_files():
        if _is_parse_only_or_quarantined(path):
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in DISALLOWED_RUNTIME_AUTHORITY_FRAGMENTS:
            if fragment in text:
                hits.append(f"{_relative_runtime(path).as_posix()}: {fragment}")

    assert hits == []


def test_historical_terms_are_parse_only_or_quarantined():
    hits: list[str] = []
    for path in _runtime_files():
        if _is_parse_only_or_quarantined(path):
            continue
        text = path.read_text(encoding="utf-8")
        for term in HISTORICAL_TERMS:
            if term in text:
                hits.append(f"{_relative_runtime(path).as_posix()}: {term}")

    assert hits == []


def test_historical_graph_authority_modules_are_deleted():
    remaining = [
        relative.as_posix()
        for relative in sorted(DELETED_OLD_GRAPH_SCAFFOLD_RUNTIME_PATHS)
        if (RUNTIME_ROOT / relative).exists()
    ]

    assert remaining == []


def test_active_runtime_does_not_import_old_graph_scaffold_authority():
    hits: list[str] = []
    for path in _runtime_files():
        relative = _relative_runtime(path)
        if relative in OLD_GRAPH_SCAFFOLD_RUNTIME_PATHS:
            continue
        source = path.read_text(encoding="utf-8-sig")
        module = ast.parse(source)
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom):
                imported_module = _absolute_import_module(path, node.module or "", node.level)
                names = tuple(alias.name for alias in node.names)
                if not (
                    imported_module in OLD_GRAPH_SCAFFOLD_IMPORT_MODULES
                    or imported_module.startswith("factory_agent.graph.nodes.")
                ):
                    continue
                allowlist_key = (relative.as_posix(), imported_module, names)
                if allowlist_key in ACTIVE_RUNTIME_OLD_GRAPH_COMPATIBILITY_IMPORTS:
                    continue
                hits.append(f"{relative.as_posix()}:{node.lineno}: from {imported_module} import {', '.join(names)}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in OLD_GRAPH_SCAFFOLD_IMPORT_MODULES or alias.name.startswith(
                        "factory_agent.graph.nodes."
                    ):
                        hits.append(f"{relative.as_posix()}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in {"LangGraphPlanner", "compile_planner_graph"}:
                    hits.append(f"{relative.as_posix()}:{node.lineno}: call {func.id}")
                elif isinstance(func, ast.Attribute) and func.attr in {"LangGraphPlanner", "compile_planner_graph"}:
                    hits.append(f"{relative.as_posix()}:{node.lineno}: call {func.attr}")

    assert hits == []


def test_old_graph_scaffold_classification_is_tracked():
    tracker = CLEANUP_TRACK_SOURCE.read_text(encoding="utf-8")

    required_fragments = [
        "Phase 3.6 old graph scaffold classification complete",
        "Phase 3.8 old graph scaffold deleted",
        "Old Graph Scaffold Classification",
        "Active runtime import proof",
        "`factory-agent/factory_agent/graph/planner_graph.py`",
        "`factory-agent/factory_agent/graph/planner_graph_helpers.py`",
        "`factory-agent/factory_agent/graph/nodes/intent_split.py`",
        "`factory-agent/factory_agent/graph/nodes/planner_loop.py`",
        "`factory-agent/factory_agent/graph/nodes/validate.py`",
        "`factory-agent/factory_agent/graph/state.py`",
        "`factory-agent/tests/test_route_to_execution_contract.py`",
        "`factory-agent/tests/test_planner_service_phase6.py`",
    ]

    missing = [fragment for fragment in required_fragments if fragment not in tracker]

    assert missing == []


def test_historical_graph_vocabulary_cleanup_is_tracked():
    tracker = CLEANUP_TRACK_SOURCE.read_text(encoding="utf-8")

    required_fragments = [
        "Phase 4.0 historical documentation and guard vocabulary cleanup complete",
        "Historical Documentation And Guard Vocabulary Cleanup",
        "historical documentation, static guard vocabulary, compatibility schema values",
        "`LangGraphPlanner` | Historical docs OK and static guard OK",
        "`compile_planner_graph` | Historical docs OK and static guard OK",
        "`planner_graph.py` | Historical docs OK and deletion candidate already completed",
        "`working_intents` | Historical docs OK, static guard OK, compatibility schema OK",
        "`intent_cursor` | Historical docs OK, static guard OK, compatibility schema OK",
        "`intent_completed` | Historical docs OK, static guard OK, compatibility schema OK",
        "`v2_planner_loop` | Compatibility schema OK, historical docs OK, frontend release-harness vocabulary",
        "direct-v2 loop as current runtime | Misleading/current wording fixed",
    ]

    missing = [fragment for fragment in required_fragments if fragment not in tracker]

    assert missing == []


def test_old_graph_scaffold_deletion_blockers_are_explicitly_owned():
    tracker = CLEANUP_TRACK_SOURCE.read_text(encoding="utf-8")

    planner_service_source = PLANNER_SERVICE_SOURCE.read_text(encoding="utf-8")
    execution_service_source = EXECUTION_SERVICE_SOURCE.read_text(encoding="utf-8")
    approval_resume_source = APPROVAL_RESUME_SERVICE_SOURCE.read_text(encoding="utf-8")
    approvals_router_source = APPROVALS_ROUTER_SOURCE.read_text(encoding="utf-8")
    plan_creation_source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    plan_creation_compatibility_source = PLAN_CREATION_COMPATIBILITY_SOURCE.read_text(encoding="utf-8")
    structured_output_source = STRUCTURED_OUTPUT_SOURCE.read_text(encoding="utf-8")
    approval_summary_source = APPROVAL_SUMMARY_SOURCE.read_text(encoding="utf-8")
    plan_parsing_source = PLAN_PARSING_SOURCE.read_text(encoding="utf-8")
    schemas_source = SCHEMAS_SOURCE.read_text(encoding="utf-8")

    assert "LangGraphPlanner" not in planner_service_source
    assert "_langgraph_planner_cls" not in planner_service_source
    assert "async def generate_plan(" not in planner_service_source
    assert "async def resume_after_approval(" not in planner_service_source
    assert "run_langgraph_session" not in execution_service_source
    assert "await self._planner.generate_plan(" not in execution_service_source
    assert "await self._plan_service.create_plan(" in execution_service_source
    assert "planner.resume_after_approval" not in approvals_router_source
    assert "planner:" not in approvals_router_source
    assert "self._planner =" not in approval_resume_source
    assert "self._planner.resume_after_approval" not in approval_resume_source
    assert "seed_resume_context" not in approval_resume_source
    assert "old graph fallback is retired" in approval_resume_source
    assert "resume_planner_owned_graph_approval(" in approval_resume_source
    assert "_resume_direct_v2_planner_approval(" in approval_resume_source
    assert "_resume_seeded_planner_compatibility_approval(" in approval_resume_source
    assert "await self._planner.generate_plan(" not in plan_creation_source
    assert "generate_seeded_planner_compatibility_plan(" in plan_creation_source
    assert "resume_seeded_planner_compatibility_approval(" in plan_creation_source
    assert "await generate_plan(" in plan_creation_compatibility_source
    assert "await resume_after_approval(" in plan_creation_compatibility_source
    assert "seed_resume_context(" in plan_creation_compatibility_source
    assert "factory_agent.graph.planner_graph_helpers" not in structured_output_source
    assert "from ..graph.state import AgentPlanOutput" not in structured_output_source
    assert "from ..schemas import AgentPlanOutput" in structured_output_source
    assert "def _infer_bulk_job_priority_mutation(" in approval_summary_source
    assert "from .planner_graph_helpers import _infer_bulk_job_priority_mutation" not in approval_summary_source
    assert "class AgentPlanOutput" in schemas_source
    assert "class AgentPlanStep" in schemas_source
    assert "from .plan_parsing import _normalize_plan_dict" in structured_output_source
    assert "def _normalize_plan_dict(" in plan_parsing_source
    assert all(not (RUNTIME_ROOT / relative).exists() for relative in DELETED_OLD_GRAPH_SCAFFOLD_RUNTIME_PATHS)

    assert "PlannerService old graph adapter boundary retired" in tracker
    assert "Phase 3.7 compatibility seams split" in tracker
    assert "Phase 3.8 old graph scaffold deleted" in tracker

    assert "ApprovalResumeService graph approval fallback retired" in tracker
    assert "ExecutionService execution trigger" in tracker
    assert "ExecutionService.run_langgraph_session() retired" in tracker
    assert "structured-output parsing owner resolved" in tracker
    assert "PlanCreationService seeded planner compatibility adapter" in tracker


def test_tests_do_not_import_deleted_old_graph_scaffold():
    hits: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if path.name == "test_planner_owned_graph_no_legacy_authority.py":
            continue
        source = path.read_text(encoding="utf-8-sig")
        module = ast.parse(source)
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom):
                imported_module = node.module or ""
                if imported_module in OLD_GRAPH_SCAFFOLD_IMPORT_MODULES or imported_module.startswith(
                    "factory_agent.graph.nodes."
                ):
                    hits.append(f"{path.relative_to(TESTS_ROOT).as_posix()}:{node.lineno}: from {imported_module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in OLD_GRAPH_SCAFFOLD_IMPORT_MODULES or alias.name.startswith(
                        "factory_agent.graph.nodes."
                    ):
                        hits.append(f"{path.relative_to(TESTS_ROOT).as_posix()}:{node.lineno}: import {alias.name}")

    assert hits == []


def test_legacy_compatibility_tests_and_xfails_are_retired():
    hits: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if path.name == "test_planner_owned_graph_no_legacy_authority.py":
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in DISALLOWED_TEST_FRAGMENTS:
            if fragment in text:
                hits.append(f"{path.relative_to(TESTS_ROOT).as_posix()}: {fragment}")

    assert hits == []
    assert not (TESTS_ROOT / "test_memory_planner_integration.py").exists()
    assert not (TESTS_ROOT / "test_reliability_e2e.py").exists()


def test_historical_direct_v2_tests_are_marked_as_quarantined():
    missing_module_markers = [
        relative.as_posix()
        for relative in sorted(QUARANTINED_MODULE_TESTS)
        if QUARANTINED_MODULE_MARKER not in (TESTS_ROOT / relative).read_text(encoding="utf-8")
    ]
    missing_function_markers: list[str] = []
    for relative, functions in QUARANTINED_TEST_FUNCTIONS.items():
        source = (TESTS_ROOT / relative).read_text(encoding="utf-8-sig")
        module = ast.parse(source)
        nodes = {
            node.name: node
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for function_name in sorted(functions):
            node = nodes.get(function_name)
            if node is None:
                missing_function_markers.append(f"{relative.as_posix()}::{function_name}: missing function")
                continue
            if "pytest.mark.legacy_architecture_quarantine" not in _decorator_names(node):
                missing_function_markers.append(f"{relative.as_posix()}::{function_name}: missing marker")

    assert missing_module_markers == []
    assert missing_function_markers == []


def test_normal_runtime_cannot_call_historical_direct_v2_execution():
    source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    graph_adapter = _function_node(source, "_create_planner_owned_graph_plan")

    graph_calls = _called_names(graph_adapter)
    defined_functions = {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_create_direct_v2_plan" not in defined_functions
    assert "_create_planner_owned_graph_v2_plan" not in defined_functions
    assert "_planner_owned_graph_runtime" in graph_calls
    assert "run_plan" in graph_calls
    assert "_execute_direct_v2_steps" not in graph_calls
    assert "_create_historical_direct_v2_plan" not in graph_calls
    assert "PlannerOwnedV2Loop" not in graph_calls
    assert "_create_historical_direct_v2_plan" not in defined_functions
    assert "_execute_direct_v2_steps" not in defined_functions
    assert "factory_agent.planning.v2_planner_loop" not in source


def test_active_trace_context_compatibility_is_separated_from_direct_loop():
    service_source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    compatibility_source = V2_TRACE_COMPATIBILITY_SOURCE.read_text(encoding="utf-8")

    assert "build_direct_v2_compatibility_state" in service_source
    assert "build_failed_direct_v2_compatibility_state" in service_source
    assert "PlannerOwnedV2Loop" not in service_source
    assert "class PlannerOwnedV2Loop" not in compatibility_source
    assert "def attach_direct_v2_trace_to_intent_contract" in compatibility_source
    assert "def build_direct_v2_compatibility_state" in compatibility_source
    assert "def build_direct_v2_compatibility_run" in compatibility_source
    assert "def build_direct_v2_compatibility_draft" in compatibility_source
    assert not V2_PLANNER_LOOP_SOURCE.exists()


def test_historical_direct_v2_literals_are_owned_by_compatibility_helper():
    compatibility_source = HISTORICAL_DIRECT_V2_COMPATIBILITY_SOURCE.read_text(encoding="utf-8")
    trace_compatibility_source = V2_TRACE_COMPATIBILITY_SOURCE.read_text(encoding="utf-8")
    plan_creation_source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    approval_resume_source = APPROVAL_RESUME_SERVICE_SOURCE.read_text(encoding="utf-8")
    session_detection_source = SESSION_DETECTION_SOURCE.read_text(encoding="utf-8")

    assert 'HISTORICAL_DIRECT_V2_CREATED_BY: HistoricalDirectV2CreatedBy = "v2_planner_loop"' in compatibility_source
    assert 'HISTORICAL_DIRECT_V2_GENERATED_BY: HistoricalDirectV2GeneratedBy = "v2_planner_loop"' in compatibility_source
    assert "def is_historical_direct_v2_created_by" in compatibility_source
    assert "def is_historical_direct_v2_generated_by" in compatibility_source
    assert "def is_historical_direct_v2_approval_payload" in compatibility_source
    assert "historical_direct_v2_generated_by()" in trace_compatibility_source
    assert '"v2_planner_loop"' not in trace_compatibility_source
    assert '"v2_planner_loop"' not in plan_creation_source
    assert '"v2_planner_loop"' not in approval_resume_source
    assert '"v2_planner_loop"' not in session_detection_source
    assert "is_historical_direct_v2_created_by" in plan_creation_source
    assert "is_historical_direct_v2_approval_payload" in approval_resume_source
    assert "historical_direct_v2_created_by()" in approval_resume_source
    assert "is_historical_direct_v2_created_by" in session_detection_source


def test_historical_legacy_rag_route_literals_are_owned_by_compatibility_helper():
    compatibility_source = HISTORICAL_LEGACY_RAG_ROUTE_COMPATIBILITY_SOURCE.read_text(encoding="utf-8")
    contracts_source = (RUNTIME_ROOT / "planning" / "v2_contracts.py").read_text(encoding="utf-8")
    satisfaction_source = (RUNTIME_ROOT / "planning" / "v2_satisfaction.py").read_text(encoding="utf-8")
    tracker = CLEANUP_TRACK_SOURCE.read_text(encoding="utf-8")

    assert (
        'HISTORICAL_LEGACY_RAG_ROUTE_GENERATED_BY: HistoricalLegacyRagRouteGeneratedBy = "legacy_rag_route"'
        in compatibility_source
    )
    assert (
        'HISTORICAL_LEGACY_RAG_ROUTE_SOURCE_TYPE: HistoricalLegacyRagRouteSourceType = "legacy_rag_route"'
        in compatibility_source
    )
    assert "def is_historical_legacy_rag_route_generated_by" in compatibility_source
    assert "def is_historical_legacy_rag_route_source_type" in compatibility_source
    assert "def is_historical_legacy_rag_route_evidence" in compatibility_source
    assert "is_historical_legacy_rag_route_generated_by" in contracts_source
    assert "is_historical_legacy_rag_route_source_type" in contracts_source
    assert "is_historical_legacy_rag_route_evidence" in satisfaction_source
    assert '"legacy_rag_route"' not in satisfaction_source
    assert "Phase 5: Legacy RAG Route Compatibility Cleanup" in tracker
    assert "historical_legacy_rag_route_compatibility.py" in tracker


def test_direct_v2_followup_tests_use_trace_compatibility_seam_not_planner_owned_loop():
    forbidden_import = "from factory_agent.planning.v2_planner_loop import PlannerOwnedV2Loop"
    forbidden_constructor = "PlannerOwnedV2Loop("
    hits: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if path.name == "test_planner_owned_graph_no_legacy_authority.py":
            continue
        text = path.read_text(encoding="utf-8")
        if forbidden_import in text:
            hits.append(f"{path.relative_to(TESTS_ROOT).as_posix()}: old loop import")
        if forbidden_constructor in text:
            hits.append(f"{path.relative_to(TESTS_ROOT).as_posix()}: old loop constructor")

    assert hits == []


def test_plan_creation_direct_v2_helpers_are_retired():
    source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    tracker = CLEANUP_TRACK_SOURCE.read_text(encoding="utf-8")
    defined_functions = _defined_function_names(source)
    remaining_direct_helpers = {
        name
        for name in defined_functions
        if name.startswith("_direct_v2_")
        or name.startswith("_execute_direct_v2_")
        or name.startswith("_maybe_create_direct_v2_")
    }

    assert remaining_direct_helpers == TRACKER_BLOCKED_PLAN_CREATION_DIRECT_V2_HELPERS
    assert DELETED_PLAN_CREATION_DIRECT_V2_HELPERS.isdisjoint(defined_functions)
    for helper in TRACKER_BLOCKED_PLAN_CREATION_DIRECT_V2_HELPERS:
        assert helper in tracker
    assert "_direct_v2_rag_execution_query" not in source
    assert "_direct_v2_stage_rows" not in source


def test_planner_owned_v2_loop_public_wrapper_is_retired():
    runtime_hits: list[str] = []
    for path in _runtime_files():
        text = path.read_text(encoding="utf-8")
        if "PlannerOwnedV2Loop" in text:
            runtime_hits.append(_relative_runtime(path).as_posix())

    assert runtime_hits == []
    assert not V2_PLANNER_LOOP_SOURCE.exists()


def test_graph_runtime_sources_do_not_use_old_graph_or_legacy_rag_authority():
    sources = {
        "planner_owned_graph_runtime.py": GRAPH_RUNTIME_SOURCE.read_text(encoding="utf-8"),
        "v2_agent_graph.py": V2_AGENT_GRAPH_SOURCE.read_text(encoding="utf-8"),
    }
    banned = (
        "working_intents",
        "intent_cursor",
        "intent_completed",
        "legacy_rag_route",
        "legacy_graph_loop",
        "compile_planner_graph",
        "LangGraphPlanner",
        "from .state import AgentState",
        "from factory_agent.graph.state import AgentState",
    )

    hits = [
        f"{name}: {fragment}"
        for name, source in sources.items()
        for fragment in banned
        if fragment in source
    ]

    assert hits == []


def test_planner_authored_graph_decisions_still_require_proposer_diagnostics():
    source = V2_AGENT_GRAPH_SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    graph_record_calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PlannerDecisionRecord"
    ]

    for call in graph_record_calls:
        author_keywords = [keyword for keyword in call.keywords if keyword.arg == "author"]
        assert author_keywords, "graph-owned PlannerDecisionRecord calls must spell out non-planner authors"
        author = author_keywords[0].value
        assert not (isinstance(author, ast.Constant) and author.value == "planner")

    assert "propose_decision(state=state, context=context)" in source
    assert "record_planner_decision(state, proposal.submission)" in source
    assert "planner_proposer" in source


def test_offline_proposer_diagnostics_do_not_satisfy_release_proof():
    offline_diagnostics = {
        "adapter": OfflineStructuredPlannerDecisionProposer.adapter_name,
        "llm_invoked": False,
        "offline_contract_mode": True,
        "real_llm_mode": False,
        "model_name": None,
        "base_url_type": None,
    }
    qwen_diagnostics = {
        "adapter": OpenAICompatibleQwenPlannerDecisionProposer.adapter_name,
        "llm_invoked": True,
        "offline_contract_mode": False,
        "real_llm_mode": True,
        "openai_compatible_planner_adapter": True,
        "model_name": "Qwen-phase11-policy-proof",
        "base_url_type": "local",
    }

    assert planner_proposer_diagnostics_satisfy_real_llm_release_proof(offline_diagnostics) is False
    assert planner_proposer_diagnostics_satisfy_real_llm_release_proof(qwen_diagnostics) is True


def test_historical_trace_values_parse_but_cannot_satisfy_v2_requirements():
    trace = ExecutionTrace(
        engine_version="legacy",
        generated_by=historical_legacy_rag_route_generated_by(),
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
            source_type=historical_legacy_rag_route_source_type(),
            source_of_truth="document_knowledge",
            legacy_rag_route=LegacyRagRouteMetadata(route="rag.procedure"),
        )
    )

    result = validate_v2_final_state(state)

    assert result.status == "failed"
    assert any(issue.issue == historical_legacy_rag_route_cannot_satisfy_issue() for issue in result.issues)
