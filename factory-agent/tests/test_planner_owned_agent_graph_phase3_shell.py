from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import (
    PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER,
    LocalPlannerOwnedGraphTracer,
    PlannerOwnedAgentGraph,
    PlannerOwnedAgentGraphAdapters,
)
from factory_agent.schemas import ToolInfo


def _settings():
    return replace(get_settings(), graph_checkpoint_backend="off")


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


def _tools() -> dict[str, ToolInfo]:
    return {
        "get__machines_{id}": _tool(
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
        ),
        "get__jobs_{id}": _tool(
            "get__jobs_{id}",
            endpoint="/jobs/{id}",
            tags=["job", "lookup", "status"],
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
    }


async def _fake_http_executor(settings, tool, args, *, idempotency_key, extra_headers=None):
    _ = settings, extra_headers
    assert idempotency_key.startswith("planner-owned-agent-graph:")
    identifier_field = "job_id" if "jobs" in tool.name else "machine_id"
    return {
        "ok": True,
        "http_status": 200,
        "latency_ms": 4,
        "body": {
            "data": {
                identifier_field: args.get("id"),
                "status": "running",
            }
        },
        "infrastructure_error": False,
    }


def _graph(*, checkpointer: Any = None, tracer: LocalPlannerOwnedGraphTracer | None = None):
    settings = _settings()
    return PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=_tools(),
            http_executor=_fake_http_executor,
        ),
        checkpointer=checkpointer,
        tracer=tracer,
    )


@pytest.mark.asyncio
async def test_phase3_simple_read_query_flows_through_graph_nodes_in_order():
    tracer = LocalPlannerOwnedGraphTracer()
    graph = _graph(tracer=tracer)

    result = await graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase3-node-order"},
    )

    assert result.node_order == list(PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER)
    assert [event["node"] for event in result.trace_events] == list(PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER)
    assert result.state.evidence_ledger.evidence[0].tool_name == "get__machines_{id}"
    assert result.state.final_validation_result is not None
    assert result.state.final_validation_result.status == "passed"
    assert result.state.response_document_context.state == "rendered"


@pytest.mark.asyncio
async def test_phase3_planner_decisions_are_written_into_state():
    graph = _graph()

    result = await graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase3-decisions"},
    )

    decisions = result.state.planner_decisions
    assert [decision.decision_kind for decision in decisions] == [
        "retrieve_tools",
        "choose_tool",
        "execute_tool",
        "finalize",
    ]
    assert [decision.author for decision in decisions] == [
        "planner",
        "planner",
        "deterministic_guard",
        "deterministic_guard",
    ]
    assert decisions[0].capability_need is not None
    assert decisions[1].selected_tool_call is not None
    assert decisions[1].selected_tool_call.tool_name == "get__machines_{id}"
    assert decisions[2].selected_tool_call is not None
    assert decisions[2].selected_tool_call.call_id == decisions[1].selected_tool_call.call_id
    assert decisions[3].evidence_refs == ["ev-api-req-001"]


@pytest.mark.asyncio
async def test_phase3_old_graph_fields_are_not_execution_authority():
    graph = _graph()
    legacy_context = {
        "session_id": "phase3-old-fields",
        "working_intents": [{"intent_id": "legacy", "constraints": {"machine_id": "M-LEGACY-01"}}],
        "intent_cursor": 99,
        "intent_completed": True,
    }

    result = await graph.run("Show machine M-LTH-77 status.", session_context=legacy_context)

    tool_call = next(
        decision.selected_tool_call
        for decision in result.state.planner_decisions
        if decision.decision_kind == "choose_tool"
    )
    evidence = result.state.evidence_ledger.evidence[0]
    assert tool_call.args["id"] == "M-LTH-77"
    assert evidence.normalized_result["entity_id"] == "M-LTH-77"
    assert result.node_order == list(PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER)


@pytest.mark.asyncio
async def test_phase3_graph_accepts_injected_and_configured_checkpointers(monkeypatch):
    injected = MemorySaver()
    injected_graph = _graph(checkpointer=injected)

    assert injected_graph.compiled_graph.checkpointer is injected
    injected_result = await injected_graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase3-injected-checkpointer"},
    )
    assert injected_result.checkpoint_config["configurable"]["thread_id"] == "phase3-injected-checkpointer"

    configured = MemorySaver()
    import factory_agent.graph.v2_agent_graph as v2_agent_graph

    monkeypatch.setattr(v2_agent_graph, "build_graph_checkpointer", lambda settings: configured)
    configured_settings = replace(get_settings(), graph_checkpoint_backend="memory")
    configured_graph = PlannerOwnedAgentGraph(
        settings=configured_settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=configured_settings,
            tools_by_name=_tools(),
            http_executor=_fake_http_executor,
        ),
    )

    assert configured_graph.compiled_graph.checkpointer is configured


@pytest.mark.asyncio
async def test_phase3_direct_service_execution_is_not_called(monkeypatch):
    from factory_agent.services.plan_creation_service import PlanCreationService

    async def _boom(*args, **kwargs):  # pragma: no cover - only runs on regression
        raise AssertionError("direct service execution must not be called by the graph shell")

    monkeypatch.setattr(PlanCreationService, "_execute_direct_v2_steps", _boom)
    graph = _graph()

    result = await graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase3-no-direct-service"},
    )

    assert result.state.evidence_ledger.evidence[0].diagnostic_metadata["graph_authorized_execution"] is True
    assert result.state.evidence_ledger.evidence[0].diagnostic_metadata["direct_v2_execution"] is False
    assert result.state.response_document_context.diagnostics["real_response_renderer_called"] is False


@pytest.mark.asyncio
async def test_phase3_resume_state_is_not_stored_in_session_replan_context():
    class SessionContext:
        session_id = "phase3-replan-context"
        replan_context = {
            "agent_state": {"original_query": "stale state must not resume the graph"},
            "langgraph_pending_approval": {"approval_id": "approval-stale"},
        }

    session = SessionContext()
    original_replan_context = deepcopy(session.replan_context)
    graph = _graph()

    result = await graph.run("Show machine M-LTH-77 status.", session_context=session)

    assert session.replan_context == original_replan_context
    assert result.state.original_query == "Show machine M-LTH-77 status."
    assert "replan_context" not in result.state.execution_trace.diagnostics
    assert result.state.pending_approval.status == "none"
