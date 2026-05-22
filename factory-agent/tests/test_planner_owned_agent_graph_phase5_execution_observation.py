from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import PlannerOwnedAgentGraph, PlannerOwnedAgentGraphAdapters
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_agent_state import GraphToolCall, PlannerDecisionRecord, build_initial_planner_owned_agent_graph_state
from factory_agent.planning.v2_contracts import (
    CandidateTool,
    CandidateToolWindow,
    CapabilityNeed,
    HydratedToolCard,
    HydratedToolCards,
)
from factory_agent.planning.v2_graph_adapters import GraphExecutionAuthorizationError
from factory_agent.planning.v2_planner_decisions import record_planner_decision
from factory_agent.planning.v2_planner_proposer import OfflineStructuredPlannerDecisionProposer
from factory_agent.schemas import ToolInfo


FACTORY_AGENT_ROOT = Path(__file__).resolve().parents[1]
PLAN_CREATION_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "services" / "plan_creation_service.py"
RUNTIME_ADAPTER_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "services" / "planner_owned_graph_runtime.py"


def _settings():
    return replace(
        get_settings(),
        graph_checkpoint_backend="off",
        tool_selector_backend="retrieval",
        tool_selector_top_k=10,
        tool_selector_candidate_pool=20,
        tool_selector_reranker_enabled=False,
    )


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


def _machine_status_tool() -> ToolInfo:
    return _tool(
        "get__machines_{id}",
        endpoint="/machines/{id}",
        tags=["machine", "lookup", "status"],
        required=["id"],
        query_params=["fields"],
        input_properties={
            "id": {"type": "string", "x-ai-id-field": "machine_id", "x-ai-entity": "machine"},
            "fields": {"type": "string"},
        },
        output_properties={"machine_id": {"type": "string"}, "status": {"type": "string"}},
        entity="machine",
        response_contract="entity_status_v1",
    )


class RecordingSelector:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        return ToolSelectionResult(self.names, backend_used="retrieval", llm_calls=0)


class FakeRAGPipeline:
    def __init__(self, *, answer: str, sources: list[dict[str, Any]]) -> None:
        self.answer = answer
        self.sources = sources
        self.calls: list[dict[str, Any]] = []

    async def run(self, *, query: str, session_id: str | None = None, route: str = "RAG_ONLY", api_data=None):
        self.calls.append({"query": query, "session_id": session_id, "route": route, "api_data": api_data})

        class Result:
            pass

        result = Result()
        result.answer = self.answer
        result.sources = self.sources
        result.safety_content = None
        return result


async def _successful_http_executor(settings, tool, args, *, idempotency_key, extra_headers=None):
    _ = settings, extra_headers
    assert idempotency_key.startswith("planner-owned-agent-graph:")
    return {
        "ok": True,
        "http_status": 200,
        "latency_ms": 6,
        "body": {
            "data": {
                "machine_id": args.get("id"),
                "status": "running",
            }
        },
        "infrastructure_error": False,
    }


async def _failed_http_executor(settings, tool, args, *, idempotency_key, extra_headers=None):
    _ = settings, tool, args, idempotency_key, extra_headers
    return {
        "ok": False,
        "http_status": 503,
        "latency_ms": 2,
        "body": {"error": "upstream unavailable"},
        "infrastructure_error": True,
    }


def _graph(
    *,
    tools_by_name: dict[str, ToolInfo] | None = None,
    selector: RecordingSelector | None = None,
    http_executor=_successful_http_executor,
    rag_pipeline: Any | None = None,
) -> PlannerOwnedAgentGraph:
    settings = _settings()
    adapters = PlannerOwnedAgentGraphAdapters(
        settings=settings,
        tools_by_name=tools_by_name or {"get__machines_{id}": _machine_status_tool()},
        tool_selector=selector or RecordingSelector(["get__machines_{id}"]),  # type: ignore[arg-type]
        http_executor=http_executor,
        rag_pipeline=rag_pipeline,
    )
    return PlannerOwnedAgentGraph(
        settings=settings,
        adapters=adapters,
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=None,
    )


def _state_with_persisted_choice():
    state = build_initial_planner_owned_agent_graph_state(
        "Show machine M-LTH-77 status.",
        tools_by_name={"get__machines_{id}": _machine_status_tool()},
    )
    requirement = state.requirement_ledger.requirements[0]
    need = CapabilityNeed(
        requirement_id=requirement.id,
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        known_args={"machine_id": "M-LTH-77"},
        constraints=dict(requirement.constraints),
        requested_fields=list(requirement.requested_fields),
    )
    state.candidate_tool_windows.append(
        CandidateToolWindow(
            requirement_id=requirement.id,
            capability_need=need,
            candidates=[
                CandidateTool(
                    tool_name="get__machines_{id}",
                    rank=1,
                    source_of_truth="operational_state",
                    actions=["read_one", "read"],
                )
            ],
        )
    )
    state.hydrated_tool_cards.append(
        HydratedToolCards(
            requirement_id=requirement.id,
            cards=[
                HydratedToolCard(
                    tool_name="get__machines_{id}",
                    source_of_truth="operational_state",
                    actions=["read_one", "read"],
                    required_args=["id"],
                    path_params=["id"],
                    query_params=["fields"],
                    supports_fields=True,
                    output_contract="entity_status_v1",
                )
            ],
        )
    )
    call = GraphToolCall(
        call_id="call-machine-status",
        kind="api_tool",
        tool_name="get__machines_{id}",
        args={"id": "M-LTH-77", "fields": "status"},
        requirement_id=requirement.id,
    )
    choose = PlannerDecisionRecord(
        decision_id="dec-choose-machine",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=call,
        reason="Planner selected the bounded machine reader.",
        diagnostics={
            "planner_proposer": {
                "proposer_seam": True,
                "adapter": "phase5_test_proposer",
                "decision_id": "dec-choose-machine",
                "bounded_state_view": True,
                "full_openapi_catalog_visible": False,
            }
        },
    )
    record_planner_decision(state, choose)
    return state, requirement, need, call


@pytest.mark.asyncio
async def test_phase5_tool_execution_requires_persisted_validated_decision():
    state, requirement, need, call = _state_with_persisted_choice()
    adapters = PlannerOwnedAgentGraphAdapters(
        settings=_settings(),
        tools_by_name={"get__machines_{id}": _machine_status_tool()},
        http_executor=_successful_http_executor,
    )
    execute = PlannerDecisionRecord(
        decision_id="dec-execute-machine",
        decision_kind="execute_tool",
        author="deterministic_guard",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=call,
        reason="Execute persisted planner-selected read.",
    )

    with pytest.raises(GraphExecutionAuthorizationError, match="persisted validated planner or guard decision"):
        await adapters.execute_tool(state, execute)

    record_planner_decision(state, execute)
    result = await adapters.execute_tool(state, execute)

    assert result.ok is True
    assert result.tool_call.call_id == call.call_id


@pytest.mark.asyncio
async def test_phase5_api_result_creates_typed_api_tool_evidence():
    result = await _graph().run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase5-api-evidence"},
    )

    evidence = result.state.evidence_ledger.evidence[0]
    requirement = result.state.requirement_ledger.requirements[0]

    assert evidence.source_type == "api_tool"
    assert evidence.source_of_truth == "operational_state"
    assert evidence.requirement_id == requirement.id
    assert evidence.tool_name == "get__machines_{id}"
    assert evidence.args == {"id": "M-LTH-77", "fields": "status"}
    assert evidence.result_ref == "graph-api-result-call-002"
    assert evidence.normalized_result["entity_id"] == "M-LTH-77"
    assert evidence.normalized_result["fields"]["status"] == "running"
    assert evidence.diagnostic_metadata["tool_call_id"] == "call-002"
    assert evidence.diagnostic_metadata["http_status"] == 200
    assert requirement.status == "satisfied"
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_phase5_rag_result_creates_rag_tool_citation_evidence():
    selector = RecordingSelector(["rag_search_documents"])
    rag = FakeRAGPipeline(
        answer="Follow the documented isolation procedure. [1]",
        sources=[
            {
                "source_id": "src-procedure-1",
                "source_number": 1,
                "doc_id": "doc-procedure-1",
                "chunk_id": "chunk-1",
                "title": "Isolation Procedure",
                "snippet": "Lockout tagout procedure evidence.",
                "page": 2,
            }
        ],
    )

    result = await _graph(
        tools_by_name={},
        selector=selector,
        rag_pipeline=rag,
    ).run("Explain the lockout tagout procedure.", session_context={"session_id": "phase5-rag-citation"})

    evidence = result.state.evidence_ledger.evidence[0]
    choose_decision = next(
        decision for decision in result.state.planner_decisions if decision.decision_kind == "choose_tool"
    )

    assert choose_decision.selected_tool_call is not None
    assert choose_decision.selected_tool_call.kind == "rag_tool"
    assert result.state.candidate_tool_windows[0].max_candidates == 5
    assert evidence.source_type == "rag_tool"
    assert evidence.source_of_truth == "document_knowledge"
    assert evidence.tool_name == "rag_search_documents"
    assert evidence.citations[0].source_id == "src-procedure-1"
    assert evidence.normalized_result["answer"] == "Follow the documented isolation procedure. [1]"
    assert result.state.requirement_ledger.requirements[0].status == "satisfied"


@pytest.mark.asyncio
async def test_phase5_insufficient_rag_result_creates_explicit_insufficient_context_evidence():
    rag = FakeRAGPipeline(answer="", sources=[])

    result = await _graph(
        tools_by_name={},
        selector=RecordingSelector(["rag_search_documents"]),
        rag_pipeline=rag,
    ).run("Explain the lockout tagout procedure.", session_context={"session_id": "phase5-rag-insufficient"})

    evidence = result.state.evidence_ledger.evidence[0]
    requirement = result.state.requirement_ledger.requirements[0]

    assert evidence.source_type == "system_guard"
    assert evidence.source_of_truth == "document_knowledge"
    assert evidence.tool_name == "rag_search_documents"
    assert evidence.normalized_result["no_match"] is True
    assert evidence.normalized_result["match_status"] == "no_match"
    assert evidence.diagnostic_metadata["reason"] == "insufficient_context"
    assert requirement.status == "impossible"
    assert requirement.status != "satisfied"


@pytest.mark.asyncio
async def test_phase5_failed_tool_execution_does_not_satisfy_requirement():
    result = await _graph(http_executor=_failed_http_executor).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase5-api-failure"},
    )

    evidence = result.state.evidence_ledger.evidence[0]
    requirement = result.state.requirement_ledger.requirements[0]
    decisions = [decision.decision_kind for decision in result.state.planner_decisions]

    assert evidence.source_type == "api_tool"
    assert evidence.normalized_result["error"]["code"] == "tool_error"
    assert evidence.diagnostic_metadata["ok"] is False
    assert requirement.status == "failed"
    assert requirement.status != "satisfied"
    assert result.state.final_validation_result.status == "failed"  # type: ignore[union-attr]
    assert decisions[-1] == "fail"


@pytest.mark.asyncio
async def test_phase5_repeated_retrieval_guard_trace_is_preserved():
    selector = RecordingSelector(["get__machines_{id}"])

    result = await _graph(selector=selector).run(
        "Show machine M-LTH-77 status, then show machine M-LTH-77 status.",
        session_context={"session_id": "phase5-repeated-guard"},
    )

    guard = result.state.execution_trace.diagnostics["repeated_retrieval_guard"]
    assert guard["status"] == "blocked_repeated_need"
    assert guard["decisions"][1]["blocked"] is True
    assert len(selector.calls) == 1


@pytest.mark.asyncio
async def test_phase5_direct_v2_execution_helpers_are_not_used(monkeypatch):
    from factory_agent.services.plan_creation_service import PlanCreationService

    async def _boom(*args, **kwargs):  # pragma: no cover - only runs on regression
        raise AssertionError("direct-v2 service execution helper was called")

    monkeypatch.setattr(PlanCreationService, "_execute_direct_v2_steps", _boom)
    monkeypatch.setattr(PlanCreationService, "_execute_direct_v2_api_step", _boom)
    monkeypatch.setattr(PlanCreationService, "_execute_direct_v2_rag_step", _boom)

    result = await _graph().run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase5-no-direct-v2"},
    )

    assert result.state.evidence_ledger.evidence[0].diagnostic_metadata["direct_v2_execution"] is False


def test_phase5_normal_runtime_switches_to_graph_after_phase10():
    source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    runtime_source = RUNTIME_ADAPTER_SOURCE.read_text(encoding="utf-8")

    assert "PlannerOwnedGraphRuntimeAdapter" in source
    assert "PlannerOwnedAgentGraph" in runtime_source
    assert '"thread_id": sess.session_id' in runtime_source
    assert "_create_historical_direct_v2_plan" in source
