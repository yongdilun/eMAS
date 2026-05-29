from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import PlannerOwnedAgentGraph, PlannerOwnedAgentGraphAdapters
from factory_agent.planning.intent import semantic_frame_for_text
from factory_agent.planning.tool_selector import ToolSelector
from factory_agent.planning.v2_planner_proposer import OfflineStructuredPlannerDecisionProposer
from factory_agent.schemas import ToolInfo


def _settings(**overrides: Any):
    return replace(
        get_settings(),
        graph_checkpoint_backend="off",
        tool_selector_backend="retrieval",
        tool_selector_top_k=10,
        tool_selector_candidate_pool=20,
        tool_selector_reranker_enabled=False,
        openai_api_key=None,
        openai_base_url=None,
        planner_openai_base_url=None,
        semantic_intake_openai_base_url=None,
        **overrides,
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
    required = list(required or [])
    input_schema: dict[str, Any] = {"type": "object", "properties": dict(input_properties or {})}
    if required:
        input_schema["required"] = required
    if entity:
        input_schema["x-ai-entity"] = entity
    if response_contract:
        input_schema["x-ai-response-contracts"] = [response_contract]

    output_schema: dict[str, Any] = {"type": "object", "properties": dict(output_properties or {})}
    if entity:
        output_schema["x-ai-entity"] = entity
    if response_contract:
        output_schema["x-ai-response-contracts"] = [response_contract]

    path_params = [field for field in required if f"{{{field}}}" in endpoint]
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


def _machine_tool() -> ToolInfo:
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


def _job_lookup_tool() -> ToolInfo:
    return _tool(
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
    )


def _job_list_tool() -> ToolInfo:
    return _tool(
        "get__jobs",
        endpoint="/jobs",
        tags=["job", "list", "status"],
        query_params=["priority", "fields", "sort_by", "sort_dir", "limit"],
        input_properties={
            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
            "fields": {"type": "string"},
            "sort_by": {"type": "string", "enum": ["deadline", "created_at", "priority"]},
            "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer"},
        },
        output_properties={
            "job_id": {"type": "string"},
            "priority": {"type": "string"},
            "deadline": {"type": "string"},
        },
        entity="job",
        response_contract="entity_list_v1",
    )


async def _run_active_graph(prompt: str) -> dict[str, Any]:
    settings = _settings()
    calls: list[dict[str, Any]] = []

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, idempotency_key, extra_headers
        calls.append({"tool_name": tool.name, "args": dict(args)})
        if tool.name == "get__machines_{id}":
            data: dict[str, Any] | list[dict[str, Any]] = {"machine_id": args.get("id"), "status": "running"}
        elif tool.name == "get__jobs_{id}":
            data = {"job_id": args.get("id"), "status": "scheduled"}
        else:
            data = [
                {
                    "job_id": "JOB-SEED-001",
                    "priority": args.get("priority", "high"),
                    "deadline": "2026-05-30",
                }
            ]
        return {
            "ok": True,
            "http_status": 200,
            "body": {"data": data},
            "latency_ms": 1,
            "infrastructure_error": False,
        }

    tools = {tool.name: tool for tool in [_machine_tool(), _job_lookup_tool(), _job_list_tool()]}
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=tools,
            http_executor=fake_execute_tool_http,
        ),
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=None,
    )

    result = await graph.run(prompt, session_context={"session_id": f"route-contract-{abs(hash(prompt))}"})
    return {
        "frame": semantic_frame_for_text(prompt),
        "result": result,
        "executed": calls,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        "What is the status of M-CNC-01?",
        "Show status for machine M-CNC-01",
        "Is M-CNC-01 running?",
        "What is the current condition of m-cnc-01?",
        "Show machine M-CNC-01 health",
    ],
)
async def test_machine_status_route_reaches_active_graph_execution_with_preserved_machine_id(prompt):
    contract = await _run_active_graph(prompt)

    assert contract["frame"].route == "tool.read.machine_status"
    assert contract["executed"][0]["tool_name"] == "get__machines_{id}"
    assert contract["executed"][0]["args"]["id"] == "M-CNC-01"
    result = contract["result"]
    assert result.state.final_validation_result is not None
    assert result.state.final_validation_result.status == "passed"
    assert result.state.evidence_ledger.evidence[0].normalized_result["entity_id"] == "M-CNC-01"


@pytest.mark.asyncio
async def test_job_status_route_reaches_active_graph_execution_with_preserved_job_id():
    contract = await _run_active_graph("What is the status of job JOB-SEED-001?")

    assert contract["frame"].route == "tool.read.jobs"
    assert contract["executed"] == [
        {"tool_name": "get__jobs_{id}", "args": {"id": "JOB-SEED-001", "fields": "status"}}
    ]
    assert contract["result"].state.evidence_ledger.evidence[0].normalized_result["entity_id"] == "JOB-SEED-001"


@pytest.mark.asyncio
async def test_job_list_route_preserves_read_filter_in_active_graph_execution():
    contract = await _run_active_graph("Show high priority jobs")

    assert contract["frame"].route == "tool.read.jobs"
    assert contract["executed"] == [{"tool_name": "get__jobs", "args": {"priority": "high"}}]
    assert contract["result"].state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_hard_query_job_list_preserves_fields_sort_and_limit_in_active_graph_execution():
    contract = await _run_active_graph(
        "List low priority jobs, only job id and deadline, sorted by deadline ascending, limit 3."
    )

    expected_args = {
        "priority": "low",
        "sort_by": "deadline",
        "sort_dir": "asc",
        "limit": 3,
        "fields": "job_id,deadline",
    }
    assert contract["frame"].route == "tool.read.jobs"
    assert contract["executed"] == [{"tool_name": "get__jobs", "args": expected_args}]


@pytest.mark.asyncio
async def test_machine_details_route_uses_same_read_tool_without_status_word():
    prompt = "Show full details for machine with machine id M-CNC-01"
    tools = {_machine_tool().name: _machine_tool(), _job_lookup_tool().name: _job_lookup_tool()}
    selector = ToolSelector(_settings())
    selection = await selector.select_tools(intent=prompt, tools_by_name=tools, max_tools=8)
    frame = semantic_frame_for_text(prompt)

    assert frame.route == "tool.read.machine_status"
    assert frame.domain_intent == "machine_query"
    assert frame.normalized_entities["machine_id"] == ["M-CNC-01"]
    assert selection.tool_names == ["get__machines_{id}"]


@pytest.mark.asyncio
async def test_multi_job_status_route_keeps_all_job_ids_in_semantic_contract():
    prompt = "find status for job with job id JOB-SEED-001 and JOB-SEED-002"
    tools = {_machine_tool().name: _machine_tool(), _job_lookup_tool().name: _job_lookup_tool()}
    selector = ToolSelector(_settings())
    selection = await selector.select_tools(intent=prompt, tools_by_name=tools, max_tools=8)
    frame = semantic_frame_for_text(prompt)

    assert frame.route == "tool.read.jobs"
    assert frame.normalized_entities["job_id"] == ["JOB-SEED-001", "JOB-SEED-002"]
    assert selection.tool_names == ["get__jobs_{id}"]


@pytest.mark.asyncio
async def test_hard_query_multi_read_selection_unions_clause_tools():
    prompt = "Show M-CNC-01 status, then show JOB-SEED-001 status, then list the next 3 low priority jobs sorted by deadline."
    tools = {
        tool.name: tool
        for tool in [
            _machine_tool(),
            _job_lookup_tool(),
            _job_list_tool(),
        ]
    }
    selector = ToolSelector(_settings())

    selection = await selector.select_tools(intent=prompt, tools_by_name=tools, max_tools=8)

    assert selection.tool_names[:3] == ["get__machines_{id}", "get__jobs_{id}", "get__jobs"]


@pytest.mark.asyncio
async def test_loto_route_bypasses_live_machine_status_tools():
    prompt = "What LOTO procedure applies before working on M-CNC-01?"
    tools = {_machine_tool().name: _machine_tool(), _job_lookup_tool().name: _job_lookup_tool()}
    selector = ToolSelector(_settings())
    selection = await selector.select_tools(intent=prompt, tools_by_name=tools, max_tools=8)
    frame = semantic_frame_for_text(prompt)

    assert frame.route == "rag.loto_procedure"
    assert "tool.read.machine_status" in (frame.negative_route_assertions or [])
    assert selection.tool_names == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected_route", "expected_question_type"),
    [
        (
            "According to the LOTO procedure, what notification is required before starting lockout",
            "rag.procedure",
            "document_content_question",
        ),
        (
            "What does the LOTO procedure say about notifying affected employees?",
            "rag.procedure",
            "document_content_question",
        ),
        (
            "Before lockout, who needs to be notified according to LOTO?",
            "rag.procedure",
            "document_content_question",
        ),
        (
            "What are the notification requirements before lockout/tagout?",
            "rag.procedure",
            "document_content_question",
        ),
        (
            "According to OSHA LOTO guidance, what notification is required before lockout?",
            "rag.safety_policy",
            "safety_policy_question",
        ),
    ],
)
async def test_loto_document_content_routes_to_rag_without_machine_id_clarification(
    prompt,
    expected_route,
    expected_question_type,
):
    tools = {_machine_tool().name: _machine_tool(), _job_lookup_tool().name: _job_lookup_tool()}
    selector = ToolSelector(_settings())
    selection = await selector.select_tools(intent=prompt, tools_by_name=tools, max_tools=8)
    frame = semantic_frame_for_text(prompt)

    assert frame.route == expected_route
    assert frame.question_type == expected_question_type
    assert frame.missing_required_entities == []
    assert "machine_id" not in frame.normalized_entities
    assert "tool.read.machine_status" in (frame.negative_route_assertions or [])
    assert selection.tool_names == []
