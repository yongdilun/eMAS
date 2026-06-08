from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from factory_agent.config import get_settings
from factory_agent.graph import v2_agent_graph as graph_module
from factory_agent.graph.v2_agent_graph import (
    LocalPlannerOwnedGraphTracer,
    PlannerOwnedAgentGraph,
    PlannerOwnedAgentGraphAdapters,
)
from factory_agent.planning.semantic_intake import DeterministicFallbackSemanticIntakeProposer
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_agent_state import (
    GraphToolCall,
    PendingApprovalState,
    PlannerDecisionRecord,
    PlannerOwnedAgentGraphState,
    build_initial_planner_owned_agent_graph_state,
    build_uncompiled_planner_owned_agent_graph_state,
)
from factory_agent.planning.v2_contracts import (
    CandidateTool,
    CandidateToolWindow,
    EvidenceCitation,
    EvidenceLedgerEntry,
    FinalValidationResult,
    HydratedToolCard,
    HydratedToolCards,
)
from factory_agent.planning.v2_graph_adapters import GraphToolExecutionResult
from factory_agent.planning.v2_planner_decisions import record_planner_decision
from factory_agent.planning.v2_planner_proposer import build_planner_decision_proposer
from factory_agent.planning.v2_rag_tool import V2_RAG_TOOL_NAME, ensure_v2_rag_tool
from factory_agent.schemas import ToolInfo


BENCHMARK_ROOT = Path(__file__).resolve().parent
CASE_DIR = BENCHMARK_ROOT / "cases"
BASELINE_DIR = BENCHMARK_ROOT / "baselines"
REPORT_DIR = BENCHMARK_ROOT / "reports"

VALID_NODES = (
    "semantic_intake_node",
    "requirement_ledger_node",
    "planner_decision_node",
    "tool_retrieval_node",
    "planner_choose_tool_node",
    "tool_execution_node",
    "evidence_observation_node",
    "satisfaction_node",
    "approval_node",
    "finalize_node",
    "response_document_node",
)

PENDING_EXECUTION_KEY = "phase5_pending_tool_execution"


class NodeBenchmarkCaseError(AssertionError):
    pass


class RecordingSelector:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        return ToolSelectionResult(self.names, backend_used="node_benchmark_retrieval", llm_calls=0)


class FakeRAGPipeline:
    def __init__(self, case: Mapping[str, Any]) -> None:
        self.case = case
        self.calls: list[dict[str, Any]] = []

    async def run(self, *, query: str, session_id: str | None = None, route: str = "RAG_ONLY", api_data=None):
        self.calls.append(
            {
                "query": query,
                "session_id": session_id,
                "route": route,
                "api_data_present": api_data is not None,
            }
        )

        class Result:
            pass

        result = Result()
        behavior = str(self.case.get("behavior") or "").lower()
        if "insufficient" in behavior:
            result.answer = "I could not find enough relevant knowledge-base material to answer that safely."
            result.sources = []
            result.safety_content = None
            return result
        if "exception" in behavior:
            raise RuntimeError("node benchmark controlled RAG exception")
        result.answer = "Follow the cited lockout/tagout procedure. [1]"
        result.sources = [
            {
                "source_id": "bench-loto-source-1",
                "source_number": 1,
                "doc_id": "bench-loto-doc",
                "chunk_id": "bench-loto-chunk-1",
                "title": "Benchmark LOTO Procedure",
                "snippet": query,
            }
        ]
        result.safety_content = None
        return result


def env_enabled() -> bool:
    return os.getenv("FACTORY_AGENT_RUN_NODE_BENCHMARKS", "0").strip().lower() in {"1", "true", "yes"}


def selected_node() -> str:
    return os.getenv("FACTORY_AGENT_NODE_BENCHMARK_NODE", "all").strip() or "all"


def update_baseline_enabled() -> bool:
    return os.getenv("FACTORY_AGENT_NODE_BENCHMARK_UPDATE_BASELINE", "0").strip().lower() in {"1", "true", "yes"}


def load_cases(node: str | None = None) -> list[dict[str, Any]]:
    selected = node or selected_node()
    case_files = sorted(CASE_DIR.glob("*.json"))
    if selected != "all":
        if selected not in VALID_NODES:
            raise NodeBenchmarkCaseError(f"unknown benchmark node: {selected}")
        case_files = [CASE_DIR / f"{selected}.json"]

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in case_files:
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise NodeBenchmarkCaseError(f"{path} must contain a list of benchmark cases")
        for item in raw:
            case = dict(item)
            case_id = str(case.get("id") or "").strip()
            case_node = str(case.get("node") or "").strip()
            behavior = str(case.get("behavior") or "").strip()
            expected = case.get("expected_evidence")
            if not case_id:
                raise NodeBenchmarkCaseError(f"{path} has a case without id")
            if case_id in seen_ids:
                raise NodeBenchmarkCaseError(f"duplicate benchmark case id: {case_id}")
            if case_node not in VALID_NODES:
                raise NodeBenchmarkCaseError(f"{case_id} has unknown node: {case_node}")
            if not behavior:
                raise NodeBenchmarkCaseError(f"{case_id} is missing behavior label")
            if not isinstance(expected, list) or not expected:
                raise NodeBenchmarkCaseError(f"{case_id} must declare expected_evidence paths")
            seen_ids.add(case_id)
            cases.append(case)
    return cases


def load_xfail_baseline(node: str) -> dict[str, Any]:
    path = BASELINE_DIR / f"{node}.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    xfails = raw.get("xfail", {})
    return xfails if isinstance(xfails, dict) else {}


def baseline_mark_for_case(case: Mapping[str, Any]) -> dict[str, Any] | None:
    xfails = load_xfail_baseline(str(case["node"]))
    entry = xfails.get(str(case["id"]))
    return entry if isinstance(entry, dict) else None


async def run_benchmark_case(case: Mapping[str, Any]) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    tracer = LocalPlannerOwnedGraphTracer()
    selector_names = list((case.get("fixture") or {}).get("selector_names") or _default_selector_names(case))
    selector = RecordingSelector(selector_names)
    settings = _settings_for_case(case)
    tools = _tools_for_case(case)
    rag_pipeline = FakeRAGPipeline(case)
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=tools,
            tool_selector=selector,
            http_executor=_fake_http_executor_for_case(case),
            rag_pipeline=rag_pipeline,
            approval_preview_provider=_approval_preview_provider,
            approval_persister=_approval_persister,
        ),
        proposer=build_planner_decision_proposer(settings),
        checkpointer=None,
        tracer=tracer,
    )

    result: dict[str, Any] = {
        "id": case["id"],
        "node": case["node"],
        "behavior": case["behavior"],
        "prompt": case["prompt"],
        "started_at": started.isoformat(),
        "status": "error",
        "duration_ms": 0,
        "failures": [],
        "error": None,
        "evidence": {},
    }
    try:
        state = await _run_target_node(graph=graph, case=case, tools=tools)
        evidence = _evidence_for_state(case, state, tracer=tracer, selector=selector, rag_pipeline=rag_pipeline)
        failures = _evaluate_expected_evidence(case, evidence)
        result["evidence"] = evidence
        result["failures"] = failures
        result["status"] = "passed" if not failures else "failed"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
    finally:
        result["duration_ms"] = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        _record_result(case, result)
        if update_baseline_enabled():
            _update_baseline_from_report(str(case["node"]))
    return result


def assert_benchmark_result(result: Mapping[str, Any]) -> None:
    if result.get("status") == "passed":
        return
    failures = result.get("failures") or []
    message = "; ".join(str(item) for item in failures) or str(result.get("error") or "benchmark failed")
    raise AssertionError(message)


def _settings_for_case(case: Mapping[str, Any]):
    fixture = case.get("fixture") if isinstance(case.get("fixture"), Mapping) else {}
    settings = replace(
        get_settings(),
        graph_checkpoint_backend="off",
        allow_offline_planner_proposer=False,
        tool_selector_backend="retrieval",
        tool_selector_top_k=10,
        tool_selector_candidate_pool=20,
        tool_selector_reranker_enabled=bool(fixture.get("reranker_enabled", False)),
        enforce_tool_registry_health=False,
        min_healthy_tool_count=0,
        http_timeout_s=1.0,
        max_replans=int(fixture.get("max_replans", 2)),
    )
    if fixture.get("clear_planner_provider"):
        settings = replace(
            settings,
            openai_api_key="",
            planner_openai_base_url=None,
            semantic_intake_openai_base_url=None,
        )
    return settings


def _tool(
    name: str,
    *,
    endpoint: str,
    tags: list[str],
    method: str = "GET",
    required: list[str] | None = None,
    query_params: list[str] | None = None,
    input_properties: dict[str, dict[str, Any]] | None = None,
    output_properties: dict[str, dict[str, Any]] | None = None,
    entity: str | None = None,
    response_contract: str | None = None,
) -> ToolInfo:
    input_schema: dict[str, Any] = {"type": "object", "properties": dict(input_properties or {})}
    if required:
        input_schema["required"] = list(required)
    if entity:
        input_schema["x-ai-entity"] = entity
    if response_contract:
        input_schema["x-ai-response-contracts"] = [response_contract]
    output_schema: dict[str, Any] = {"type": "object", "properties": dict(output_properties or {})}
    if entity:
        output_schema["x-ai-entity"] = entity
    if response_contract:
        output_schema["x-ai-response-contracts"] = [response_contract]
    path_params = [field for field in required or [] if f"{{{field}}}" in endpoint]
    param_sources = {field: "path" for field in path_params}
    for field in query_params or []:
        param_sources[field] = "query"
    read_only = method == "GET"
    return ToolInfo(
        name=name,
        description=name.replace("_", " "),
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        input_schema=input_schema,
        output_schema=output_schema,
        path_params=path_params,
        query_params=list(query_params or []),
        param_sources=param_sources,
        is_read_only=read_only,
        requires_approval=not read_only,
        side_effect_level="NONE" if read_only else "HIGH",
        capability_tags=tags,
    )


def _tools_for_case(case: Mapping[str, Any]) -> dict[str, ToolInfo]:
    fixture = case.get("fixture") if isinstance(case.get("fixture"), Mapping) else {}
    tools = {
        "get__machines_{id}": _tool(
            "get__machines_{id}",
            endpoint="/machines/{id}",
            tags=["machine", "lookup", "status", "operational_state"],
            required=["id"],
            query_params=["fields"],
            input_properties={
                "id": {"type": "string", "x-ai-id-field": "machine_id", "x-ai-entity": "machine"},
                "fields": {"type": "string"},
            },
            output_properties={
                "machine_id": {"type": "string"},
                "status": {"type": "string"},
                "active_job_id": {"type": "string"},
            },
            entity="machine",
            response_contract="entity_status_v1",
        ),
        "get__jobs": _tool(
            "get__jobs",
            endpoint="/jobs",
            tags=["job", "list", "priority", "deadline", "operational_state"],
            query_params=["priority", "fields", "sort_by", "sort_dir", "limit"],
            input_properties={
                "priority": {"type": "string"},
                "fields": {"type": "string"},
                "sort_by": {"type": "string"},
                "sort_dir": {"type": "string"},
                "limit": {"type": "integer"},
            },
            output_properties={
                "job_id": {"type": "string"},
                "priority": {"type": "string"},
                "deadline": {"type": "string"},
                "status": {"type": "string"},
            },
            entity="job",
            response_contract="result_collection_v1",
        ),
        "get__jobs_{id}": _tool(
            "get__jobs_{id}",
            endpoint="/jobs/{id}",
            tags=["job", "lookup", "status", "operational_state"],
            required=["id"],
            query_params=["fields"],
            input_properties={
                "id": {"type": "string", "x-ai-id-field": "job_id", "x-ai-entity": "job"},
                "fields": {"type": "string"},
            },
            output_properties={"job_id": {"type": "string"}, "status": {"type": "string"}},
            entity="job",
            response_contract="entity_status_v1",
        ),
        "patch__jobs_{id}": _tool(
            "patch__jobs_{id}",
            endpoint="/jobs/{id}",
            method="PATCH",
            tags=["job", "update", "priority", "approval_required"],
            required=["id"],
            input_properties={
                "id": {"type": "string", "x-ai-id-field": "job_id", "x-ai-entity": "job"},
                "priority": {"type": "string"},
            },
            output_properties={"job_id": {"type": "string"}, "priority": {"type": "string"}},
            entity="job",
            response_contract="business_change_v1",
        ),
        "post__jobs": _tool(
            "post__jobs",
            endpoint="/jobs",
            method="POST",
            tags=["job", "create", "approval_required"],
            required=["product_id"],
            input_properties={
                "product_id": {"type": "string", "x-ai-id-field": "product_id", "x-ai-entity": "product"},
                "quantity": {"type": "integer"},
            },
            output_properties={"job_id": {"type": "string"}, "status": {"type": "string"}},
            entity="job",
            response_contract="business_change_v1",
        ),
        "post__ai_scheduling_reschedule-all": _tool(
            "post__ai_scheduling_reschedule-all",
            endpoint="/ai/scheduling/reschedule-all",
            method="POST",
            tags=["schedule", "reschedule", "all", "approval_required"],
            input_properties={"reason": {"type": "string"}},
            output_properties={"updated_jobs": {"type": "integer"}},
            entity="job",
            response_contract="business_change_v1",
        ),
    }
    tools = ensure_v2_rag_tool(tools)
    for name in list(fixture.get("remove_tools") or []):
        tools.pop(str(name), None)
    return tools


def _default_selector_names(case: Mapping[str, Any]) -> list[str]:
    fixture = case.get("fixture") if isinstance(case.get("fixture"), Mapping) else {}
    if fixture.get("tool_name"):
        return [str(fixture["tool_name"])]
    behavior = str(case.get("behavior") or "").lower()
    prompt = str(case.get("prompt") or "").lower()
    if "rag" in behavior or "document" in behavior or "loto" in prompt:
        return [V2_RAG_TOOL_NAME]
    if "list" in behavior or "filtered" in behavior or "jobs" in prompt:
        return ["get__jobs"]
    if "create" in behavior:
        return ["post__jobs"]
    if "reschedule" in behavior:
        return ["post__ai_scheduling_reschedule-all"]
    if "write" in behavior or "approval" in behavior or "mutation" in behavior or "priority" in prompt:
        return ["patch__jobs_{id}"]
    return ["get__machines_{id}"]


def _fake_http_executor_for_case(case: Mapping[str, Any]):
    async def _executor(settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, extra_headers
        if not str(idempotency_key).startswith("planner-owned-agent-graph:"):
            raise AssertionError("graph idempotency key missing")
        behavior = str(case.get("behavior") or "").lower()
        if "500" in behavior:
            return {
                "ok": False,
                "http_status": 500,
                "latency_ms": 3,
                "body": {"error": "controlled benchmark API 500"},
                "infrastructure_error": True,
            }
        if "404" in behavior or "no-match" in behavior or "no matching record" in behavior:
            return {
                "ok": False,
                "http_status": 404,
                "latency_ms": 3,
                "body": {"error": "controlled benchmark no match", "data": None},
                "infrastructure_error": False,
            }
        if tool.name == "get__jobs":
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 3,
                "body": {
                    "data": [
                        {
                            "job_id": "JOB-BENCH-001",
                            "priority": args.get("priority", "low"),
                            "deadline": "2026-06-18",
                            "status": "queued",
                        },
                        {
                            "job_id": "JOB-BENCH-002",
                            "priority": args.get("priority", "low"),
                            "deadline": "2026-06-19",
                            "status": "queued",
                        },
                    ]
                },
                "infrastructure_error": False,
            }
        if tool.name.startswith(("patch__", "post__")):
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 5,
                "body": {"data": {"job_id": args.get("id", "JOB-BENCH-001"), "status": "updated", **dict(args)}},
                "infrastructure_error": False,
            }
        entity_key = "job_id" if "jobs" in tool.name else "machine_id"
        return {
            "ok": True,
            "http_status": 200,
            "latency_ms": 3,
            "body": {"data": {entity_key: args.get("id", "M-CNC-01"), "status": "running", "active_job_id": "JOB-BENCH-001"}},
            "infrastructure_error": False,
        }

    return _executor


async def _approval_preview_provider(*, state, tool_call, requirement, card):
    _ = state, requirement, card
    row = {"tool_name": tool_call.tool_name, **dict(tool_call.args)}
    return {
        "summary": f"Benchmark approval required for {tool_call.tool_name}",
        "count": 1,
        "rows": [row],
        "preview_rows": [row],
        "commit_args": dict(tool_call.args),
        "bundle_ui": {
            "kind": "node_benchmark_approval",
            "headline": "Benchmark approval preview",
            "rows": [row],
        },
    }


async def _approval_persister(*, state, payload):
    _ = state, payload
    return {"approval_id": "approval-node-benchmark", "persisted": True}


async def _run_target_node(
    *,
    graph: PlannerOwnedAgentGraph,
    case: Mapping[str, Any],
    tools: Mapping[str, ToolInfo],
) -> PlannerOwnedAgentGraphState:
    node = str(case["node"])
    if node == "semantic_intake_node":
        state = build_uncompiled_planner_owned_agent_graph_state(str(case["prompt"]), tools_by_name=dict(tools))
        return await _call_node(graph, node, state)

    state = _compiled_state(case, tools)
    if node == "requirement_ledger_node":
        return await _call_node(graph, node, state)
    if node == "planner_decision_node":
        _prepare_dependency_block_if_requested(state, case)
        return await _call_node(graph, node, state)
    if node == "tool_retrieval_node":
        _seed_retrieve_decision(state)
        _prepare_repeated_retrieval_if_requested(state, case)
        return await _call_node(graph, node, state)
    if node == "planner_choose_tool_node":
        _seed_retrieve_decision(state)
        state = await _call_node(graph, "tool_retrieval_node", state)
        _prepare_failed_tool_memory_if_requested(state, case)
        return await _call_node(graph, node, state)
    if node == "tool_execution_node":
        _seed_candidate_and_choice(state, case, tools)
        _prepare_parallel_read_batch_if_requested(state, case, tools)
        return await _call_node(graph, node, state)
    if node == "evidence_observation_node":
        _seed_candidate_and_choice(state, case, tools)
        state = await _call_node(graph, "tool_execution_node", state)
        _prepare_stale_pending_execution_if_requested(state, case)
        return await _call_node(graph, node, state)
    if node == "satisfaction_node":
        state = await _state_with_evidence(case, graph, tools)
        _prepare_satisfaction_variant(state, case)
        return await _call_node(graph, node, state)
    if node == "approval_node":
        _prepare_approval_variant(state, case, tools)
        return await _call_node(graph, node, state)
    if node == "finalize_node":
        state = await _state_with_evidence(case, graph, tools)
        _prepare_finalize_variant(state, case)
        return await _call_node(graph, node, state)
    if node == "response_document_node":
        state = await _state_with_evidence(case, graph, tools)
        _prepare_response_document_variant(state, case)
        return await _call_node(graph, node, state)
    raise NodeBenchmarkCaseError(f"unsupported node: {node}")


def _compiled_state(case: Mapping[str, Any], tools: Mapping[str, ToolInfo]) -> PlannerOwnedAgentGraphState:
    return build_initial_planner_owned_agent_graph_state(
        str(case["prompt"]),
        tools_by_name=dict(tools),
        semantic_intake_proposer=DeterministicFallbackSemanticIntakeProposer(),
    )


async def _call_node(
    graph: PlannerOwnedAgentGraph,
    node_name: str,
    state: PlannerOwnedAgentGraphState,
) -> PlannerOwnedAgentGraphState:
    method = getattr(graph, f"_{node_name}")
    raw = await method(state)
    return PlannerOwnedAgentGraphState.model_validate(raw)


def _first_requirement(state: PlannerOwnedAgentGraphState):
    for requirement in state.requirement_ledger.requirements:
        if requirement.status in {"open", "blocked"}:
            return requirement
    if state.requirement_ledger.requirements:
        return state.requirement_ledger.requirements[0]
    raise NodeBenchmarkCaseError("state has no requirements")


def _seed_retrieve_decision(state: PlannerOwnedAgentGraphState) -> PlannerDecisionRecord:
    requirement = _first_requirement(state)
    need = graph_module._capability_need_for_requirement(state, requirement.id)
    decision = PlannerDecisionRecord(
        decision_id=f"dec-retrieve-bench-{len(state.planner_decisions) + 1:03d}",
        decision_kind="retrieve_tools",
        author="deterministic_guard",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        reason="Node benchmark seeded retrieval decision.",
    )
    record_planner_decision(state, decision)
    return decision


def _seed_candidate_and_choice(
    state: PlannerOwnedAgentGraphState,
    case: Mapping[str, Any],
    tools: Mapping[str, ToolInfo],
) -> GraphToolCall:
    requirement = _first_requirement(state)
    need = graph_module._capability_need_for_requirement(state, requirement.id)
    fixture = case.get("fixture") if isinstance(case.get("fixture"), Mapping) else {}
    tool_name = str(fixture.get("tool_name") or _default_selector_names(case)[0])
    if tool_name not in tools:
        if fixture.get("allow_missing_tool"):
            tool = _tool(
                tool_name,
                endpoint="/missing-tool",
                tags=["missing", "benchmark"],
                output_properties={"missing": {"type": "string"}},
            )
        else:
            tool_name = next(iter(tools))
            tool = tools[tool_name]
    else:
        tool = tools[tool_name]
    source_of_truth = "document_knowledge" if tool_name == V2_RAG_TOOL_NAME else need.source_of_truth
    if not any(window.requirement_id == requirement.id for window in state.candidate_tool_windows):
        state.candidate_tool_windows.append(
            CandidateToolWindow(
                requirement_id=requirement.id,
                capability_need=need,
                candidates=[
                    CandidateTool(
                        tool_name=tool_name,
                        rank=1,
                        source_of_truth=source_of_truth,  # type: ignore[arg-type]
                        actions=[need.action],
                        reason="node benchmark seeded candidate",
                        requires_approval=tool.requires_approval,
                    )
                ],
                backend_used="node_benchmark_seeded_window",
            )
        )
    if not any(cards.requirement_id == requirement.id for cards in state.hydrated_tool_cards):
        state.hydrated_tool_cards.append(
            HydratedToolCards(
                requirement_id=requirement.id,
                cards=[
                    HydratedToolCard(
                        tool_name=tool_name,
                        description=tool.description,
                        source_of_truth=source_of_truth,  # type: ignore[arg-type]
                        actions=[need.action],
                        input_schema=tool.input_schema,
                        output_schema=tool.output_schema,
                        required_args=list(tool.input_schema.get("required") or []),
                        path_params=list(tool.path_params or []),
                        query_params=list(tool.query_params or []),
                        supports_filters=bool(tool.query_params),
                        supports_sort="sort_by" in (tool.query_params or []),
                        supports_limit="limit" in (tool.query_params or []),
                        supports_fields="fields" in (tool.query_params or []),
                        output_contract=(tool.output_schema.get("x-ai-response-contracts") or [None])[0],
                        is_read_only=tool.is_read_only,
                        requires_approval=tool.requires_approval,
                    )
                ],
            )
        )
    call = GraphToolCall(
        call_id=f"call-bench-{len(state.planner_decisions) + 1:03d}",
        kind="rag_tool" if tool_name == V2_RAG_TOOL_NAME else "api_tool",
        tool_name=tool_name,
        args=dict(fixture.get("args") or _default_args_for_tool(tool_name, requirement)),
        requirement_id=requirement.id,
        candidate_window_id=requirement.id,
    )
    decision = PlannerDecisionRecord(
        decision_id=f"dec-choose-bench-{len(state.planner_decisions) + 1:03d}",
        decision_kind="choose_tool",
        author="planner",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=call,
        reason="Node benchmark seeded tool choice.",
        diagnostics={"planner_proposer": _seeded_planner_diagnostics()},
    )
    call.decision_id = decision.decision_id
    state.planner_decisions.append(decision)
    return call


def _default_args_for_tool(tool_name: str, requirement: Any) -> dict[str, Any]:
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    if tool_name == V2_RAG_TOOL_NAME:
        return {"query": getattr(requirement, "goal", "LOTO procedure"), "limit": 3}
    if tool_name == "get__machines_{id}":
        return {"id": constraints.get("machine_id") or "M-CNC-01", "fields": "machine_id,status,active_job_id"}
    if tool_name == "get__jobs_{id}":
        return {"id": constraints.get("job_id") or "JOB-BENCH-001", "fields": "job_id,status"}
    if tool_name == "get__jobs":
        return {"priority": constraints.get("priority") or "low", "fields": "job_id,priority,deadline,status", "sort_by": "deadline", "sort_dir": "asc", "limit": 3}
    if tool_name == "patch__jobs_{id}":
        return {"id": constraints.get("job_id") or "JOB-BENCH-001", "priority": "high"}
    if tool_name == "post__jobs":
        return {"product_id": "P-BENCH-001", "quantity": 1}
    if tool_name == "post__ai_scheduling_reschedule-all":
        return {"reason": "node benchmark reschedule all"}
    return {}


def _seeded_planner_diagnostics() -> dict[str, Any]:
    return {
        "proposer_seam": True,
        "adapter": "node_benchmark_seeded_choice",
        "bounded_state_view": True,
        "full_openapi_catalog_visible": False,
        "llm_invoked": False,
        "real_llm_mode": False,
    }


async def _state_with_evidence(
    case: Mapping[str, Any],
    graph: PlannerOwnedAgentGraph,
    tools: Mapping[str, ToolInfo],
) -> PlannerOwnedAgentGraphState:
    state = _compiled_state(case, tools)
    _seed_candidate_and_choice(state, case, tools)
    state = await _call_node(graph, "tool_execution_node", state)
    return await _call_node(graph, "evidence_observation_node", state)


def _prepare_dependency_block_if_requested(state: PlannerOwnedAgentGraphState, case: Mapping[str, Any]) -> None:
    if "dependency-blocked" not in str(case.get("behavior") or "").lower():
        return
    if len(state.requirement_ledger.requirements) < 2:
        return
    first, second = state.requirement_ledger.requirements[0], state.requirement_ledger.requirements[1]
    second.depends_on = [first.id]


def _prepare_repeated_retrieval_if_requested(state: PlannerOwnedAgentGraphState, case: Mapping[str, Any]) -> None:
    if "repeated retrieval" not in str(case.get("behavior") or "").lower():
        return
    requirement = _first_requirement(state)
    state.execution_trace.diagnostics["repeated_retrieval_guard"] = {
        "requirement_id": requirement.id,
        "need_key": "node-benchmark-repeat",
        "attempts": 2,
    }


def _prepare_failed_tool_memory_if_requested(state: PlannerOwnedAgentGraphState, case: Mapping[str, Any]) -> None:
    if "failed-tool-memory" not in str(case.get("behavior") or "").lower():
        return
    state.execution_trace.diagnostics["failed_tool_memory"] = [
        {"tool_name": _default_selector_names(case)[0], "reason": "node benchmark failed memory"}
    ]


def _prepare_parallel_read_batch_if_requested(
    state: PlannerOwnedAgentGraphState,
    case: Mapping[str, Any],
    tools: Mapping[str, ToolInfo],
) -> None:
    if "parallel" not in str(case.get("behavior") or "").lower():
        return
    if len(state.requirement_ledger.requirements) < 2:
        return
    first_call = state.planner_decisions[-1].selected_tool_call
    if first_call is None:
        return
    second_req = state.requirement_ledger.requirements[1]
    second_need = graph_module._capability_need_for_requirement(state, second_req.id)
    second_tool_name = "get__jobs_{id}" if "get__jobs_{id}" in tools else first_call.tool_name
    second_tool = tools[second_tool_name]
    if not any(window.requirement_id == second_req.id for window in state.candidate_tool_windows):
        state.candidate_tool_windows.append(
            CandidateToolWindow(
                requirement_id=second_req.id,
                capability_need=second_need,
                candidates=[
                    CandidateTool(
                        tool_name=second_tool_name,
                        rank=1,
                        source_of_truth=second_need.source_of_truth,
                        actions=[second_need.action],
                        reason="node benchmark seeded parallel candidate",
                        requires_approval=second_tool.requires_approval,
                    )
                ],
                backend_used="node_benchmark_seeded_parallel_window",
            )
        )
    if not any(cards.requirement_id == second_req.id for cards in state.hydrated_tool_cards):
        state.hydrated_tool_cards.append(
            HydratedToolCards(
                requirement_id=second_req.id,
                cards=[
                    HydratedToolCard(
                        tool_name=second_tool_name,
                        description=second_tool.description,
                        source_of_truth=second_need.source_of_truth,
                        actions=[second_need.action],
                        input_schema=second_tool.input_schema,
                        output_schema=second_tool.output_schema,
                        required_args=list(second_tool.input_schema.get("required") or []),
                        path_params=list(second_tool.path_params or []),
                        query_params=list(second_tool.query_params or []),
                        supports_filters=bool(second_tool.query_params),
                        supports_sort="sort_by" in (second_tool.query_params or []),
                        supports_limit="limit" in (second_tool.query_params or []),
                        supports_fields="fields" in (second_tool.query_params or []),
                        output_contract=(second_tool.output_schema.get("x-ai-response-contracts") or [None])[0],
                        is_read_only=second_tool.is_read_only,
                        requires_approval=second_tool.requires_approval,
                    )
                ],
            )
        )
    second_call = GraphToolCall(
        call_id="call-bench-parallel-002",
        kind="api_tool",
        tool_name=second_tool_name,
        args={"id": "JOB-BENCH-002", "fields": "job_id,status"},
        requirement_id=second_req.id,
        candidate_window_id=second_req.id,
    )
    second_decision = PlannerDecisionRecord(
        decision_id=f"dec-choose-bench-{len(state.planner_decisions) + 1:03d}",
        decision_kind="choose_tool",
        author="planner",
        requirement_id=second_req.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=second_need,
        selected_tool_call=second_call,
        reason="Node benchmark seeded parallel tool choice.",
        diagnostics={"planner_proposer": _seeded_planner_diagnostics()},
    )
    second_call.decision_id = second_decision.decision_id
    state.planner_decisions.append(second_decision)


def _prepare_stale_pending_execution_if_requested(state: PlannerOwnedAgentGraphState, case: Mapping[str, Any]) -> None:
    if "stale" not in str(case.get("behavior") or "").lower():
        return
    pending = state.execution_trace.diagnostics.get(PENDING_EXECUTION_KEY)
    if not isinstance(pending, dict):
        return
    for raw in pending.get("execution_results") or []:
        metadata = raw.setdefault("diagnostic_metadata", {})
        metadata["active_revision_satisfaction"] = False
        metadata["stale_after_graph_revision"] = True
        metadata["ledger_revision"] = state.requirement_ledger.revision
        metadata["checkpoint_id"] = "old-checkpoint"


def _prepare_satisfaction_variant(state: PlannerOwnedAgentGraphState, case: Mapping[str, Any]) -> None:
    behavior = str(case.get("behavior") or "").lower()
    if "stale evidence" in behavior and state.evidence_ledger.evidence:
        _mark_evidence_stale_for_active_revision(state)
    if "write deferral" in behavior:
        _seed_candidate_and_choice(state, {"fixture": {"tool_name": "patch__jobs_{id}"}, "behavior": behavior, "prompt": case["prompt"]}, _tools_for_case(case))
    if "replan limit" in behavior:
        state.execution_trace.diagnostics["replan_spine"] = {
            "replan_limit_reached": True,
            "attempts": 2,
            "max_attempts": 2,
        }


def _prepare_approval_variant(
    state: PlannerOwnedAgentGraphState,
    case: Mapping[str, Any],
    tools: Mapping[str, ToolInfo],
) -> None:
    behavior = str(case.get("behavior") or "").lower()
    call = _seed_candidate_and_choice(state, {"fixture": {"tool_name": "patch__jobs_{id}"}, "behavior": behavior, "prompt": case["prompt"]}, tools)
    status = "pending"
    if "reject" in behavior:
        status = "rejected"
    elif "expired" in behavior:
        status = "expired"
    elif "stale" in behavior:
        status = "stale"
    elif "approve" in behavior:
        status = "approved"
    state.pending_approval = PendingApprovalState(
        status=status,  # type: ignore[arg-type]
        approval_id="approval-node-benchmark",
        requirement_id=call.requirement_id,
        decision_id=call.decision_id,
        ledger_revision=state.requirement_ledger.revision,
        checkpoint_id="checkpoint-node-benchmark",
        tool_call=call,
        payload={"kind": "node_benchmark_approval", "behavior": behavior},
    )


def _prepare_finalize_variant(state: PlannerOwnedAgentGraphState, case: Mapping[str, Any]) -> None:
    behavior = str(case.get("behavior") or "").lower()
    if "deferred" in behavior:
        state.pending_approval = PendingApprovalState(status="pending", approval_id="approval-finalize-benchmark")
    if "failed" in behavior:
        state.evidence_ledger.evidence = []
    graph_module.validate_graph_state_final_state(state)


def _prepare_response_document_variant(state: PlannerOwnedAgentGraphState, case: Mapping[str, Any]) -> None:
    behavior = str(case.get("behavior") or "").lower()
    if "approval required" in behavior or "approval decision" in behavior:
        state.pending_approval = PendingApprovalState(status="pending", approval_id="approval-response-benchmark")
    if "replan-limit" in behavior:
        state.evidence_ledger.evidence = []
        state.execution_trace.diagnostics["replan_spine"] = {
            "replan_limit_reached": True,
            "attempts": 2,
            "max_attempts": 2,
        }
    if "stale evidence" in behavior and state.evidence_ledger.evidence:
        _mark_evidence_stale_for_active_revision(state)
    graph_module.validate_graph_state_final_state(state)


def _mark_evidence_stale_for_active_revision(state: PlannerOwnedAgentGraphState) -> None:
    if not state.evidence_ledger.evidence:
        return
    metadata = dict(state.evidence_ledger.evidence[0].diagnostic_metadata or {})
    metadata["active_revision_satisfaction"] = False
    metadata["stale_after_graph_revision"] = True
    metadata["superseded_by_ledger_revision"] = state.requirement_ledger.revision
    state.evidence_ledger.evidence[0].diagnostic_metadata = metadata


def _evidence_for_state(
    case: Mapping[str, Any],
    state: PlannerOwnedAgentGraphState,
    *,
    tracer: LocalPlannerOwnedGraphTracer,
    selector: RecordingSelector,
    rag_pipeline: FakeRAGPipeline,
) -> dict[str, Any]:
    diagnostics = state.execution_trace.diagnostics
    planner_diagnostics = state.execution_trace.planner.diagnostics
    proposer = planner_diagnostics.get("planner_decision_proposer")
    return {
        "case_id": case["id"],
        "node": case["node"],
        "node_order": list(diagnostics.get("phase3_node_order") or []),
        "trace_events": list(tracer.events),
        "requirement_ledger": state.requirement_ledger.model_dump(mode="json"),
        "planner_decisions": [decision.model_dump(mode="json") for decision in state.planner_decisions],
        "candidate_tool_windows": [window.model_dump(mode="json") for window in state.candidate_tool_windows],
        "hydrated_tool_cards": [cards.model_dump(mode="json") for cards in state.hydrated_tool_cards],
        "selected_tool_names": list(state.execution_trace.selected_tool_names),
        "evidence_ledger": state.evidence_ledger.model_dump(mode="json"),
        "satisfaction_state": state.satisfaction_state.model_dump(mode="json"),
        "final_validation_result": state.final_validation_result.model_dump(mode="json") if state.final_validation_result else None,
        "pending_approval": state.pending_approval.model_dump(mode="json"),
        "response_document_context": state.response_document_context.model_dump(mode="json"),
        "planner_diagnostics": planner_diagnostics,
        "planner_proposer_diagnostics": proposer,
        "tool_retrieval_diagnostics": state.execution_trace.tool_retrieval.diagnostics,
        "graph_diagnostics": diagnostics,
        "selector_calls": selector.calls,
        "rag_calls": rag_pipeline.calls,
        "provider": _provider_snapshot(),
    }


def _provider_snapshot() -> dict[str, Any]:
    return {
        "planner_openai_base_url_present": bool(os.getenv("PLANNER_OPENAI_BASE_URL")),
        "openai_base_url_present": bool(os.getenv("OPENAI_BASE_URL")),
        "llm_base_url_present": bool(os.getenv("LLM_BASE_URL")),
        "planner_openai_api_key_present": bool(os.getenv("PLANNER_OPENAI_API_KEY")),
        "openai_api_key_present": bool(os.getenv("OPENAI_API_KEY")),
        "planner_model": os.getenv("PLANNER_MODEL") or os.getenv("LLM_MODEL") or "Qwen3.5-9B",
    }


def _evaluate_expected_evidence(case: Mapping[str, Any], evidence: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    node = str(case["node"])
    if node not in list(evidence.get("node_order") or []):
        failures.append(f"target node was not visited: {node}")
    for path in case.get("expected_evidence") or []:
        value = _path_get(evidence, str(path))
        if value in (None, "", [], {}):
            failures.append(f"expected evidence path is empty: {path}")
    equals = case.get("expected_equals") if isinstance(case.get("expected_equals"), Mapping) else {}
    for path, expected in equals.items():
        actual = _path_get(evidence, str(path))
        if actual != expected:
            failures.append(f"expected {path}={expected!r}, got {actual!r}")
    contains = case.get("expected_contains") if isinstance(case.get("expected_contains"), Mapping) else {}
    for path, expected in contains.items():
        actual = _path_get(evidence, str(path))
        if isinstance(actual, list):
            if expected not in actual:
                failures.append(f"expected {path} to contain {expected!r}, got {actual!r}")
        elif expected not in str(actual or ""):
            failures.append(f"expected {path} to contain {expected!r}, got {actual!r}")
    return failures


def _path_get(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _record_result(case: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    node = str(case["node"])
    latest_path = REPORT_DIR / f"{node}.latest.json"
    existing: dict[str, Any] = {"node": node, "results": []}
    if latest_path.exists():
        existing = json.loads(latest_path.read_text(encoding="utf-8"))
    results = [item for item in existing.get("results", []) if item.get("id") != result.get("id")]
    results.append(dict(result))
    results.sort(key=lambda item: str(item.get("id")))
    payload = {
        "node": node,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    _atomic_write_text(latest_path, json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n")
    _write_markdown_report(node, payload)


def _write_markdown_report(node: str, payload: Mapping[str, Any]) -> None:
    path = REPORT_DIR / f"{node}.first-run.md"
    results = list(payload.get("results") or [])
    passed = sum(1 for item in results if item.get("status") == "passed")
    failed = len(results) - passed
    lines = [
        f"# {node} first-run benchmark report",
        "",
        f"- Updated: {payload.get('updated_at')}",
        f"- Cases recorded: {len(results)}",
        f"- Passed: {passed}",
        f"- Failed/error: {failed}",
        "",
        "| Case | Behavior | Status | First failure |",
        "| --- | --- | --- | --- |",
    ]
    for item in results:
        failures = item.get("failures") or []
        first_failure = str(failures[0]) if failures else ""
        lines.append(
            f"| `{item.get('id')}` | {item.get('behavior')} | {item.get('status')} | {first_failure.replace('|', '/')[:180]} |"
        )
    _atomic_write_text(path, "\n".join(lines) + "\n")


def _update_baseline_from_report(node: str) -> None:
    latest_path = REPORT_DIR / f"{node}.latest.json"
    if not latest_path.exists():
        return
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    xfails: dict[str, Any] = {}
    for item in payload.get("results", []):
        if item.get("status") == "passed":
            continue
        failures = item.get("failures") or []
        xfails[str(item.get("id"))] = {
            "reason": str(failures[0] if failures else item.get("error") or "first-run failure")[:500],
            "first_status": item.get("status"),
            "behavior": item.get("behavior"),
        }
    baseline = {
        "node": node,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "strict_xfail_first_run",
        "xfail": xfails,
    }
    _atomic_write_text(
        BASELINE_DIR / f"{node}.json",
        json.dumps(baseline, default=_json_default, indent=2, sort_keys=True) + "\n",
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, set):
        return sorted(value)
    return repr(value)
