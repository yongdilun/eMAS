from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import PlannerOwnedAgentGraph, PlannerOwnedAgentGraphAdapters
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_agent_state import GraphToolCall, PlannerDecisionRecord
from factory_agent.planning.v2_planner_decisions import PlannerDecisionSubmission
from factory_agent.planning.v2_planner_proposer import (
    OfflineStructuredPlannerDecisionProposer,
    PlannerDecisionProposalResult,
)
from factory_agent.planning.v2_tool_retriever import V2CapabilityToolRetriever
from factory_agent.schemas import ToolInfo


FACTORY_AGENT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "graph" / "v2_agent_graph.py"


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
    description: str | None = None,
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
        description=description or name.replace("_", " "),
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


def _machine_status_tool(name: str = "get__machines_{id}") -> ToolInfo:
    return _tool(
        name,
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


async def _fake_http_executor(settings, tool, args, *, idempotency_key, extra_headers=None):
    _ = settings, extra_headers
    assert idempotency_key.startswith("planner-owned-agent-graph:")
    if "jobs" in tool.name and "{id}" not in tool.name:
        return {
            "ok": True,
            "http_status": 200,
            "latency_ms": 5,
            "body": {
                "data": [
                    {
                        "job_id": "JOB-LOCAL-1",
                        "status": "queued",
                        "priority": args.get("priority", "low"),
                        "deadline": "2026-06-01",
                    }
                ]
            },
            "infrastructure_error": False,
        }
    identifier_field = "job_id" if "jobs" in tool.name else "machine_id"
    return {
        "ok": True,
        "http_status": 200,
        "latency_ms": 5,
        "body": {"data": {identifier_field: args.get("id"), "status": "running"}},
        "infrastructure_error": False,
    }


class FakeRAGPipeline:
    async def run(self, *, query: str, session_id: str | None = None, route: str = "RAG_ONLY", api_data=None):
        _ = session_id, route, api_data

        class Result:
            answer = "Follow the cited procedure. [1]"
            sources = [
                {
                    "source_id": "src-procedure-1",
                    "source_number": 1,
                    "doc_id": "doc-procedure-1",
                    "chunk_id": "chunk-1",
                    "title": "Procedure",
                    "snippet": query,
                }
            ]
            safety_content = None

        return Result()


def _graph(
    tools_by_name: dict[str, ToolInfo],
    *,
    selector: Any | None = None,
    adapters: PlannerOwnedAgentGraphAdapters | None = None,
) -> PlannerOwnedAgentGraph:
    settings = _settings()
    graph_adapters = adapters or PlannerOwnedAgentGraphAdapters(
        settings=settings,
        tools_by_name=tools_by_name,
        tool_selector=selector,
        http_executor=_fake_http_executor,
        rag_pipeline=FakeRAGPipeline(),
    )
    return PlannerOwnedAgentGraph(
        settings=settings,
        adapters=graph_adapters,
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=None,
    )


class RecordingSelector:
    def __init__(self, result: ToolSelectionResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        return self.result


@pytest.mark.asyncio
async def test_phase4_graph_retrieval_receives_capability_need_not_whole_query():
    selector = RecordingSelector(ToolSelectionResult(["get__machines_{id}"], backend_used="retrieval"))
    graph = _graph({"get__machines_{id}": _machine_status_tool()}, selector=selector)
    whole_query = "Show machine M-LTH-77 status, then explain OSHA lockout-tagout policy."

    result = await graph.run(whole_query, session_context={"session_id": "phase4-capability-need"})

    assert selector.calls
    call = selector.calls[0]
    adapter_request = call["context"]["v2_tool_selector_adapter_request"]
    assert call["intent"] != whole_query
    assert "machine" in call["intent"]
    assert "status" in call["intent"]
    assert "OSHA" not in call["intent"]
    assert call["max_tools"] == 5
    assert adapter_request["entity"] == "machine"
    assert adapter_request["capability_need"]["requirement_id"] == result.state.candidate_tool_windows[0].requirement_id
    assert result.state.planner_decisions[0].capability_need is not None


@pytest.mark.asyncio
async def test_phase4_candidate_window_max_and_hydration_come_from_retriever_result():
    tools = {
        f"machine_status_reader_{index}": _tool(
            f"machine_status_reader_{index}",
            endpoint=f"/machines/{{id}}/status-{index}",
            tags=["machine", "lookup", "status"],
            required=["id"],
            query_params=["fields"],
            input_properties={"id": {"type": "string"}, "fields": {"type": "string"}},
            output_properties={"status": {"type": "string"}},
            entity="machine",
            response_contract="entity_status_v1",
        )
        for index in range(7)
    }
    tools["zzz_secret_unselected"] = _tool(
        "zzz_secret_unselected",
        endpoint="/inventory/secret",
        tags=["inventory", "list"],
        output_properties={"secret_unselected_marker": {"type": "string"}},
    )

    result = await _graph(tools).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase4-window-bound"},
    )

    window = result.state.candidate_tool_windows[0]
    cards = result.state.hydrated_tool_cards[0]
    diagnostics = result.state.execution_trace.tool_retrieval.diagnostics["phase4_retrieval"]

    assert len(window.candidates) == 5
    assert window.max_candidates == 5
    assert len(cards.cards) == 5
    assert cards.max_cards == 5
    assert {candidate.tool_name for candidate in window.candidates} == {card.tool_name for card in cards.cards}
    assert diagnostics["max_candidates_per_need"] == 5
    assert diagnostics["hydrated_cards_from_retriever_result"] is True
    assert "secret_unselected_marker" not in repr(cards.model_dump(mode="json"))
    assert "phase3_local_adapter" not in repr(result.state.model_dump(mode="json"))


class BadChoiceAdapters(PlannerOwnedAgentGraphAdapters):
    async def choose_tool(self, state, decision):  # type: ignore[override]
        requirement_id = decision.requirement_id or decision.capability_need.requirement_id
        return GraphToolCall(
            call_id="call-outside-window",
            kind="api_tool",
            tool_name="not_a_candidate_tool",
            args={},
            requirement_id=requirement_id,
        )


class BadChoiceProposer(OfflineStructuredPlannerDecisionProposer):
    async def propose_decision(self, *, state, context):  # type: ignore[override]
        if context.requested_decision_kind != "choose_tool":
            return await super().propose_decision(state=state, context=context)
        decision = PlannerDecisionRecord(
            decision_id=context.decision_id,
            decision_kind="choose_tool",
            requirement_id=context.requirement_id,
            ledger_revision=state.requirement_ledger.revision,
            capability_need=context.capability_need,
            selected_tool_call=GraphToolCall(
                call_id="call-outside-window",
                kind="api_tool",
                tool_name="not_a_candidate_tool",
                args={},
                requirement_id=context.requirement_id or "req-001",
            ),
            reason="Test proposer selected a tool outside the hydrated window.",
            diagnostics={
                "planner_proposer": {
                    "proposer_seam": True,
                    "adapter": "phase4_bad_choice_test_proposer",
                    "bounded_state_view": True,
                    "full_openapi_catalog_visible": False,
                }
            },
        )
        return PlannerDecisionProposalResult(
            submission=PlannerDecisionSubmission(decision=decision),
            diagnostics=decision.diagnostics["planner_proposer"],
        )


@pytest.mark.asyncio
async def test_phase4_planner_cannot_choose_non_candidate_tool():
    settings = _settings()
    adapters = BadChoiceAdapters(settings=settings, tools_by_name={"get__machines_{id}": _machine_status_tool()})
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=adapters,
        proposer=BadChoiceProposer(),
        checkpointer=None,
    )

    result = await graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase4-bad-choice"},
    )

    rejections = result.state.execution_trace.planner.diagnostics["planner_decision_proposer"]["rejected"]
    assert "selected tool is not in the hydrated candidate window" in rejections[0]["reason"]
    assert result.state.evidence_ledger.evidence == []


@pytest.mark.asyncio
async def test_phase4_rag_candidate_is_graph_tool_action_not_legacy_route():
    result = await _graph({}).run(
        "Explain the lockout tagout procedure.",
        session_context={"session_id": "phase4-rag-candidate"},
    )

    window = result.state.candidate_tool_windows[0]
    card = result.state.hydrated_tool_cards[0].cards[0]
    choose_decision = next(
        decision for decision in result.state.planner_decisions if decision.decision_kind == "choose_tool"
    )

    assert window.candidates[0].tool_name == "rag_search_documents"
    assert "search_documents" in window.candidates[0].actions
    assert card.tool_name == "rag_search_documents"
    assert card.source_of_truth == "document_knowledge"
    assert card.metadata["evidence_source_type"] == "rag_tool"
    assert card.metadata["rag_execution_policy"] == "planner_owned_tool_execution"
    assert choose_decision.selected_tool_call is not None
    assert choose_decision.selected_tool_call.kind == "rag_tool"
    assert result.state.execution_trace.generated_by == "planner_owned_agent_graph"
    assert result.state.execution_trace.detectors.legacy_rag_shortcut.used is False
    assert all(evidence.source_type != "legacy_rag_route" for evidence in result.state.evidence_ledger.evidence)


def test_phase4_graph_uses_existing_v2_retriever_stack():
    settings = _settings()
    adapters = PlannerOwnedAgentGraphAdapters(settings=settings, tools_by_name={})
    source = GRAPH_SOURCE.read_text(encoding="utf-8")

    assert isinstance(adapters.tool_retriever, V2CapabilityToolRetriever)
    assert "V2CapabilityToolRetriever" in source
    assert "_select_local_tools_for_need" not in source
    assert "phase3_local_adapter" not in source


@pytest.mark.asyncio
async def test_phase4_graph_does_not_use_direct_v2_execution_helpers(monkeypatch):
    from factory_agent.services.plan_creation_service import PlanCreationService

    async def _boom(*args, **kwargs):  # pragma: no cover - only runs on regression
        raise AssertionError("Graph retrieval/execution path must not use direct-v2 service helpers")

    assert not hasattr(PlanCreationService, "_execute_direct_v2_steps")
    monkeypatch.setattr(PlanCreationService, "_execute_direct_v2_api_step", _boom)
    monkeypatch.setattr(PlanCreationService, "_execute_direct_v2_rag_step", _boom)

    result = await _graph({}).run(
        "Explain the lockout tagout procedure.",
        session_context={"session_id": "phase4-no-real-execution"},
    )

    evidence = result.state.evidence_ledger.evidence[0]
    assert evidence.source_type == "rag_tool"
    assert evidence.diagnostic_metadata["graph_authorized_execution"] is True
    assert evidence.diagnostic_metadata["direct_v2_execution"] is False
    assert result.state.response_document_context.diagnostics["real_response_renderer_called"] is False
