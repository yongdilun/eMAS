from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from factory_agent.config import Settings, get_settings, normalize_factory_agent_engine
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_planner_loop import (
    PlannerOwnedV2Loop,
    attach_v2_shadow_trace_to_intent_contract,
    legacy_graph_signals,
    legacy_rag_signals,
)
from factory_agent.schemas import ToolInfo


def _settings(**overrides: Any) -> Settings:
    values = replace(
        get_settings(),
        database_url="sqlite+aiosqlite:///:memory:",
        go_api_base_url="http://testserver",
        tool_selector_backend="retrieval",
        tool_selector_reranker_enabled=False,
        factory_agent_engine="v2",
        **overrides,
    )
    return values


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
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(input_properties or {}),
    }
    if required:
        input_schema["required"] = list(required)
    if entity:
        input_schema["x-ai-entity"] = entity
    if response_contract:
        input_schema["x-ai-response-contracts"] = [response_contract]
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(output_properties or {}),
    }
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


def _job_write_tool() -> ToolInfo:
    return _tool(
        "patch__jobs_{id}",
        endpoint="/jobs/{id}",
        tags=["job", "update", "priority"],
        method="PATCH",
        required=["id"],
        input_properties={"id": {"type": "string"}, "priority": {"type": "string"}},
        output_properties={"job_id": {"type": "string"}, "priority": {"type": "string"}},
        entity="job",
        response_contract="business_change_v1",
    )


def _rag_tool() -> ToolInfo:
    return _tool(
        "rag_search_documents",
        endpoint="/rag/documents/search",
        tags=["rag", "document", "knowledge", "search", "citation", "procedure"],
        required=["query"],
        query_params=["query", "limit"],
        input_properties={"query": {"type": "string"}, "limit": {"type": "integer"}},
        output_properties={"answer": {"type": "string"}, "citations": {"type": "array"}},
        response_contract="knowledge_answer_v1",
    )


class RecordingSelector:
    def __init__(self, names: list[str], *, llm_calls: int = 0) -> None:
        self.names = names
        self.llm_calls = llm_calls
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        return ToolSelectionResult(self.names, backend_used="retrieval", llm_calls=self.llm_calls)


def test_phase5_engine_modes_remain_explicit_while_phase8_default_is_v2():
    assert normalize_factory_agent_engine(None) == "v2"
    assert normalize_factory_agent_engine("not-a-mode") == "v2"
    assert normalize_factory_agent_engine("legacy") == "v2"
    assert _settings().factory_agent_engine == "v2"


@pytest.mark.asyncio
async def test_phase5_v2_shadow_records_trace_while_legacy_remains_visible_authority():
    selector = RecordingSelector(["get__machines_{id}"], llm_calls=1)
    tools = {"get__machines_{id}": _machine_status_tool()}
    legacy_signals = legacy_graph_signals(
        intent="Show machine M-LTH-77 status.",
        selected_candidate_tool_names=["get__machines_{id}"],
        planner_call_count=2,
        reranker_call_count=1,
        backend_used="retrieval",
        source_function="test.legacy_graph",
    )

    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-LTH-77 status.",
        tools_by_name=tools,
        engine_mode="v2_shadow",
        legacy_signals=legacy_signals,
    )
    contract = attach_v2_shadow_trace_to_intent_contract(
        {"intent": "Show machine M-LTH-77 status.", "visible_answer": "legacy answer"},
        intent="Show machine M-LTH-77 status.",
        v2_state=run.state,
        legacy_signals=legacy_signals,
    )

    assert run.draft is None
    assert contract["engine_version"] == "v2_shadow"
    assert contract["visible_answer"] == "legacy answer"
    assert contract["execution_trace"]["generated_by"] == "v2_shadow_planner_loop"
    assert contract["execution_trace"]["diagnostics"]["visible_authority"] == "legacy"
    assert contract["legacy_execution_trace"]["generated_by"] == "legacy_working_intents"
    assert contract["execution_trace"]["planner"]["call_count"] == 1
    assert contract["execution_trace"]["tool_retrieval"]["call_count"] == 1
    assert contract["execution_trace"]["tool_retrieval"]["reranker"]["call_count"] == 1
    assert contract["execution_trace"]["tool_retrieval"]["selected_candidate_tool_names"] == [
        "get__machines_{id}"
    ]


@pytest.mark.asyncio
async def test_phase5_shadow_mode_does_not_execute_or_commit_write_candidates():
    selector = RecordingSelector(["patch__jobs_{id}"])
    tools = {"patch__jobs_{id}": _job_write_tool()}

    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Change a job priority to low and ask approval first.",
        tools_by_name=tools,
        engine_mode="v2_shadow",
        legacy_signals=legacy_graph_signals(
            intent="Change a job priority to low and ask approval first.",
            source_function="test.legacy_graph",
        ),
    )

    assert run.draft is None
    assert run.tool_outputs == []
    assert run.state.execution_trace.diagnostics["shadow_only"] is True
    assert run.state.execution_trace.diagnostics["write_policy"] == "trace_only_no_tool_execution"
    assert run.state.hydrated_tool_cards[0].cards[0].requires_approval is True


@pytest.mark.asyncio
async def test_phase5_direct_v2_test_path_records_v2_generated_by_and_read_draft():
    selector = RecordingSelector(["get__machines_{id}"])
    tools = {"get__machines_{id}": _machine_status_tool()}

    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-LTH-77 status.",
        tools_by_name=tools,
        engine_mode="v2",
    )

    assert run.state.engine_version == "v2"
    assert run.state.execution_trace.generated_by == "v2_planner_loop"
    assert run.draft is not None
    assert run.draft.steps[0].tool_name == "get__machines_{id}"
    assert run.draft.steps[0].args["id"] == "M-LTH-77"
    assert run.draft.steps[0].args["fields"] == "status"


@pytest.mark.asyncio
async def test_phase5_v2_path_uses_v2_retriever_and_records_candidate_windows_and_detectors():
    selector = RecordingSelector(["get__machines_{id}"])
    tools = {"get__machines_{id}": _machine_status_tool()}
    legacy_signals = legacy_graph_signals(
        intent="Show machine M-LTH-77 status.",
        selected_candidate_tool_names=["get__machines_{id}"],
        source_function="test.legacy_graph",
    )

    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-LTH-77 status.",
        tools_by_name=tools,
        engine_mode="v2_shadow",
        legacy_signals=legacy_signals,
    )
    trace = run.state.execution_trace.model_dump(mode="json")

    assert selector.calls
    assert selector.calls[0]["context"]["v2_tool_selector_adapter_request"]["entity"] == "machine"
    assert trace["diagnostics"]["tool_selector_adapter"] == "V2CapabilityToolRetriever"
    assert trace["diagnostics"]["used_v2_capability_tool_retriever"] is True
    assert trace["diagnostics"]["capability_needs"][0]["entity"] == "machine"
    assert trace["diagnostics"]["candidate_tool_windows"][0]["candidates"][0]["tool_name"] == "get__machines_{id}"
    assert trace["detectors"]["legacy_working_intent_execution"]["used"] is True
    assert trace["detectors"]["legacy_whole_query_tool_scope"]["used"] is True
    assert trace["detectors"]["legacy_intent_completion_loop"]["used"] is True
    assert trace["diagnostics"]["repeated_retrieval_guard"]["status"] == "not_triggered"


@pytest.mark.asyncio
async def test_phase5_legacy_rag_shortcut_is_legacy_evidence_not_v2_rag_tool_evidence():
    selector = RecordingSelector(["rag_search_documents"])
    tools = {"rag_search_documents": _rag_tool()}

    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Explain the lockout tagout procedure.",
        tools_by_name=tools,
        engine_mode="v2_shadow",
        legacy_signals=legacy_rag_signals(
            route="rag.procedure",
            source_function="PlanCreationService.create_plan",
            policy_id="rag.procedure",
        ),
    )

    trace = run.state.execution_trace.model_dump(mode="json")
    evidence = run.state.evidence_ledger.model_dump(mode="json")["evidence"]
    assert trace["detectors"]["legacy_rag_shortcut"]["used"] is True
    assert evidence[0]["source_type"] == "legacy_rag_route"
    assert evidence[0]["tool_name"] is None
    assert not any(item["source_type"] == "rag_tool" for item in evidence)
    assert run.state.hydrated_tool_cards[0].cards[0].metadata["evidence_source_type"] == "rag_tool"


@pytest.mark.asyncio
async def test_phase5_planner_trace_does_not_receive_full_catalog_before_capability_need():
    selector = RecordingSelector(["get__machines_{id}"])
    tools = {
        "get__machines_{id}": _machine_status_tool(),
        "secret_unselected_tool": _tool(
            "secret_unselected_tool",
            endpoint="/secret",
            tags=["secret"],
            output_properties={"secret_unselected_marker": {"type": "string"}},
        ),
    }

    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-LTH-77 status.",
        tools_by_name=tools,
        engine_mode="v2",
    )
    trace = run.state.execution_trace.model_dump(mode="json")
    hydrated_dump = str(trace["diagnostics"]["hydrated_tool_cards"])
    candidate_dump = str(trace["diagnostics"]["candidate_tool_windows"])

    assert run.state.execution_trace.planner.diagnostics["received_full_tool_catalog_before_need"] is False
    assert "secret_unselected_marker" not in hydrated_dump
    assert "secret_unselected_tool" not in candidate_dump
