from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from factory_agent.config import Settings
from factory_agent.planning.tool_selector import ToolSelectionResult, ToolSelector
from factory_agent.planning.v2_capability_map import build_capability_needs_for_text, build_v2_capability_map
from factory_agent.planning.v2_contracts import CapabilityNeed
from factory_agent.planning.v2_tool_retriever import V2CapabilityToolRetriever
from factory_agent.schemas import ToolInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / "factory-agent" / "factory_agent"


def _settings(**overrides: object) -> Settings:
    base = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=1,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=2.0,
        tool_selector_backend="retrieval",
        tool_selector_top_k=10,
        tool_selector_candidate_pool=20,
    )
    values = base.__dict__.copy()
    values.update(overrides)
    return Settings(**values)


def _selector(**overrides: object) -> ToolSelector:
    return ToolSelector(_settings(**overrides))


def _tool(
    name: str,
    *,
    endpoint: str,
    tags: list[str],
    method: str = "GET",
    input_properties: dict[str, dict[str, Any]] | None = None,
    output_properties: dict[str, dict[str, Any]] | None = None,
    required: list[str] | None = None,
    query_params: list[str] | None = None,
    body_fields: list[str] | None = None,
    required_body_fields: list[str] | None = None,
    entity: str | None = None,
    response_contract: str | None = None,
    path_params: list[str] | None = None,
    param_sources: dict[str, str] | None = None,
    description: str | None = None,
    requires_approval: bool | None = None,
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

    sources = dict(param_sources or {field: "query" for field in query_params or []})
    path_values = list(path_params or [field for field in required or [] if f"{{{field}}}" in endpoint])
    for field in path_values:
        sources[field] = "path"
    read_only = method == "GET"

    return ToolInfo(
        name=name,
        description=description or name.replace("_", " "),
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        input_schema=input_schema,
        output_schema=output_schema,
        path_params=path_values,
        query_params=list(query_params or []),
        body_fields=list(body_fields or []),
        required_body_fields=list(required_body_fields or []),
        param_sources=sources,
        is_read_only=read_only,
        requires_approval=(not read_only) if requires_approval is None else requires_approval,
        side_effect_level="NONE" if read_only else "HIGH",
        capability_tags=tags,
    )


def _machine_status_tool(*, tags: list[str] | None = None) -> ToolInfo:
    return _tool(
        "get__machines_{id}",
        endpoint="/machines/{id}",
        tags=["machine", "lookup", "status"] if tags is None else tags,
        required=["id"],
        query_params=["fields"],
        input_properties={
            "id": {"type": "string", "x-ai-id-field": "machine_id", "x-ai-entity": "machine"},
            "fields": {"type": "string"},
        },
        output_properties={
            "machine_id": {"type": "string", "x-ai-aliases": ["machine id"]},
            "status": {"type": "string", "enum": ["running", "idle", "down"]},
        },
        entity="machine",
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
            "status": {"type": "string"},
            "priority": {"type": "string"},
            "deadline": {"type": "string"},
        },
        entity="job",
        response_contract="result_collection_v1",
    )


def _job_lookup_tool() -> ToolInfo:
    return _tool(
        "get__jobs_{id}",
        endpoint="/jobs/{id}",
        tags=["job", "lookup", "status"],
        required=["id"],
        query_params=["fields"],
        input_properties={"id": {"type": "string"}, "fields": {"type": "string"}},
        output_properties={"job_id": {"type": "string"}, "status": {"type": "string"}},
        entity="job",
        response_contract="entity_status_v1",
    )


def _job_create_tool() -> ToolInfo:
    return _tool(
        "post__jobs",
        endpoint="/jobs",
        method="POST",
        tags=["job", "create"],
        required=["product_id", "quantity_total"],
        input_properties={
            "product_id": {"type": "string"},
            "quantity_total": {"type": "integer"},
        },
        output_properties={
            "job_id": {"type": "string"},
            "product_id": {"type": "string"},
            "quantity_total": {"type": "integer"},
        },
        body_fields=["product_id", "quantity_total"],
        required_body_fields=["product_id", "quantity_total"],
        entity="job",
        response_contract="business_change_v1",
    )


def _reschedule_all_tool() -> ToolInfo:
    return _tool(
        "post__ai_scheduling_reschedule-all",
        endpoint="/ai/scheduling/reschedule-all",
        method="POST",
        tags=["ai", "scheduling", "reschedule", "all", "job", "create"],
        input_properties={"order_by": {"type": "string", "enum": ["epo", "edd", "fifo", "readiness"]}},
        output_properties={
            "proposals": {"type": "array", "items": {"type": "object"}},
            "summary": {"type": "object"},
        },
        body_fields=["order_by"],
        entity=None,
        response_contract="business_change_v1",
    )


def _rag_tool() -> ToolInfo:
    return _tool(
        "rag_search_documents",
        endpoint="/rag/documents/search",
        tags=["rag", "document", "knowledge", "search", "citation", "procedure", "policy"],
        query_params=["query", "source_type", "limit"],
        input_properties={
            "query": {"type": "string"},
            "source_type": {"type": "string", "enum": ["procedure", "policy"]},
            "limit": {"type": "integer"},
        },
        output_properties={
            "answer": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "object"}},
        },
        required=["query"],
        response_contract="knowledge_answer_v1",
        description="Search document knowledge sources and return cited evidence.",
    )


class RecordingSelector:
    def __init__(self, result: ToolSelectionResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        return self.result


@pytest.mark.asyncio
async def test_phase4_machine_status_need_retrieves_machine_status_api_candidate():
    retriever = V2CapabilityToolRetriever(_selector())
    tools = {
        "get__machines_{id}": _machine_status_tool(),
        "get__jobs": _job_list_tool(),
    }
    need = CapabilityNeed(
        requirement_id="req-machine",
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        known_args={"machine_id": "M-LTH-77"},
        requested_fields=["status"],
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)

    assert result.status == "ok"
    assert result.adapter_request.retrieval_phrase is not None
    assert "machine" in result.adapter_request.retrieval_phrase
    assert result.candidate_window.candidates[0].tool_name == "get__machines_{id}"
    card = result.hydrated_tool_cards.cards[0]
    assert card.tool_name == "get__machines_{id}"
    assert card.required_args == ["id"]
    assert card.path_params == ["id"]
    assert card.query_params == ["fields"]
    assert card.supports_fields is True
    assert card.output_contract == "entity_status_v1"
    assert card.metadata["evidence_source_type"] == "api_tool"


@pytest.mark.asyncio
async def test_phase4_job_list_need_hydrates_filter_sort_limit_and_fields_schema():
    retriever = V2CapabilityToolRetriever(_selector())
    tools = {
        "get__jobs": _job_list_tool(),
        "get__jobs_{id}": _job_lookup_tool(),
    }
    need = CapabilityNeed(
        requirement_id="req-jobs",
        source_of_truth="operational_state",
        entity="job",
        action="list",
        constraints={"priority": "low", "sort_by": "deadline", "sort_dir": "asc", "limit": 3},
        requested_fields=["job_id", "status", "priority", "deadline"],
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)

    assert result.status == "ok"
    assert result.candidate_window.candidates[0].tool_name == "get__jobs"
    card = next(card for card in result.hydrated_tool_cards.cards if card.tool_name == "get__jobs")
    assert card.supports_filters is True
    assert card.supports_sort is True
    assert card.supports_limit is True
    assert card.supports_fields is True
    assert card.query_params == ["priority", "fields", "sort_by", "sort_dir", "limit"]
    assert card.metadata["filter_params"] == ["priority"]
    assert card.metadata["filter_enums"] == {"priority": ["high", "medium", "low"]}
    assert card.metadata["sort_fields"] == ["deadline", "created_at", "priority"]
    assert card.metadata["limit_params"] == ["limit"]
    assert card.output_contract == "result_collection_v1"


@pytest.mark.asyncio
async def test_phase4_read_list_need_keeps_matching_read_card_when_selector_returns_write_only():
    selector = RecordingSelector(ToolSelectionResult(["patch__jobs_{id}"], backend_used="retrieval"))
    retriever = V2CapabilityToolRetriever(selector)  # type: ignore[arg-type]
    tools = {
        "patch__jobs_{id}": _tool(
            "patch__jobs_{id}",
            endpoint="/jobs/{id}",
            method="PATCH",
            tags=["job", "update", "priority"],
            required=["id"],
            input_properties={"id": {"type": "string"}, "priority": {"type": "string"}},
            entity="job",
            response_contract="business_change_v1",
        ),
        "get__jobs": _job_list_tool(),
    }
    need = CapabilityNeed(
        requirement_id="req-jobs",
        source_of_truth="operational_state",
        entity="job",
        action="list",
        constraints={"priority": "low", "limit": 3},
        requested_fields=["job_id", "status", "priority", "deadline"],
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)

    assert [candidate.tool_name for candidate in result.candidate_window.candidates] == [
        "patch__jobs_{id}",
        "get__jobs",
    ]
    assert result.trace.diagnostics["metadata_read_completion_used"] is True
    assert any(card.tool_name == "get__jobs" and card.is_read_only for card in result.hydrated_tool_cards.cards)


@pytest.mark.asyncio
async def test_phase4_write_need_completes_with_read_preflight_and_write_candidate_from_metadata():
    selector = RecordingSelector(ToolSelectionResult([], backend_used="retrieval"))
    retriever = V2CapabilityToolRetriever(selector)  # type: ignore[arg-type]
    tools = {
        "get__jobs": _job_list_tool(),
        "put__jobs_{id}": _tool(
            "put__jobs_{id}",
            endpoint="/jobs/{id}",
            method="PUT",
            tags=["job", "update", "priority"],
            required=["id"],
            body_fields=["priority"],
            required_body_fields=["priority"],
            input_properties={"id": {"type": "string"}, "priority": {"type": "string"}},
            output_properties={"job_id": {"type": "string"}, "priority": {"type": "string"}},
            entity="job",
            response_contract="business_change_v1",
        ),
    }
    need = CapabilityNeed(
        requirement_id="req-update",
        source_of_truth="operational_state",
        entity="job",
        action="update",
        constraints={"priority": "high", "new_priority": "medium", "date": "this week"},
        requested_fields=["job_id", "priority", "status", "deadline"],
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)

    assert result.status == "ok"
    assert [candidate.tool_name for candidate in result.candidate_window.candidates] == [
        "get__jobs",
        "put__jobs_{id}",
    ]
    assert result.trace.diagnostics["metadata_candidate_completion"] == {
        "read_preflight": ["get__jobs"],
        "write_candidates": ["put__jobs_{id}"],
    }
    cards = {card.tool_name: card for card in result.hydrated_tool_cards.cards}
    assert cards["get__jobs"].is_read_only is True
    assert cards["put__jobs_{id}"].is_read_only is False
    assert cards["put__jobs_{id}"].requires_approval is True


@pytest.mark.asyncio
async def test_phase4_create_job_need_retrieves_post_jobs_candidate_from_metadata_completion():
    selector = RecordingSelector(ToolSelectionResult([], backend_used="retrieval"))
    retriever = V2CapabilityToolRetriever(selector)  # type: ignore[arg-type]
    tools = {"post__jobs": _job_create_tool()}
    need = CapabilityNeed(
        requirement_id="req-create",
        source_of_truth="operational_state",
        entity="job",
        action="create",
        constraints={"requires_approval": True},
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)

    assert result.status == "ok"
    assert [candidate.tool_name for candidate in result.candidate_window.candidates] == ["post__jobs"]
    assert result.trace.diagnostics["metadata_candidate_completion"] == {
        "read_preflight": [],
        "write_candidates": ["post__jobs"],
    }
    assert result.hydrated_tool_cards.cards[0].required_args == ["product_id", "quantity_total"]


def test_phase4_incomplete_create_job_intake_maps_to_create_capability_action():
    tools = {"post__jobs": _job_create_tool()}
    capability_map = build_v2_capability_map(tools)

    needs = build_capability_needs_for_text("help me to create a job", capability_map=capability_map)

    assert len(needs) == 1
    assert needs[0].entity == "job"
    assert needs[0].action == "create"


@pytest.mark.asyncio
async def test_phase4_reschedule_all_jobs_retrieves_scheduling_reschedule_candidate():
    selector = RecordingSelector(ToolSelectionResult([], backend_used="retrieval"))
    retriever = V2CapabilityToolRetriever(selector)  # type: ignore[arg-type]
    tools = {
        "get__jobs": _job_list_tool(),
        "post__jobs": _job_create_tool(),
        "post__ai_scheduling_reschedule-all": _reschedule_all_tool(),
    }
    capability_map = build_v2_capability_map(tools)
    needs = build_capability_needs_for_text("help me to reschedule all job", capability_map=capability_map)

    assert len(needs) == 1
    assert needs[0].entity == "job"
    assert needs[0].action == "update"
    assert needs[0].constraints["operation"] == "reschedule_all"

    result = await retriever.retrieve_tools_for_need(needs[0], tools_by_name=tools)

    assert result.status == "ok"
    assert "reschedule all" in (result.adapter_request.retrieval_phrase or "")
    assert [candidate.tool_name for candidate in result.candidate_window.candidates] == [
        "get__jobs",
        "post__ai_scheduling_reschedule-all",
    ]
    assert result.trace.diagnostics["metadata_candidate_completion"]["write_candidates"] == [
        "post__ai_scheduling_reschedule-all",
    ]


@pytest.mark.asyncio
async def test_phase4_document_knowledge_need_retrieves_rag_candidate_as_v2_tool_contract():
    retriever = V2CapabilityToolRetriever(_selector())
    tools = {
        "rag_search_documents": _rag_tool(),
        "get__machines_{id}": _machine_status_tool(),
    }
    need = CapabilityNeed(
        requirement_id="req-procedure",
        source_of_truth="document_knowledge",
        entity="procedure",
        action="search_documents",
        constraints={"topic": "lockout-tagout"},
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)

    assert result.status == "ok"
    assert result.candidate_window.candidates[0].tool_name == "rag_search_documents"
    card = result.hydrated_tool_cards.cards[0]
    assert card.source_of_truth == "document_knowledge"
    assert card.actions == ["search_documents", "read"]
    assert card.output_contract == "knowledge_answer_v1"
    assert card.metadata["evidence_source_type"] == "rag_tool"
    assert "historical_route_name" not in card.metadata
    assert card.metadata["rag_execution_policy"] == "planner_owned_tool_execution"
    assert card.metadata["executes_rag"] is True
    assert result.trace.diagnostics["retrieval_phrase"] != "Which OSHA LOTO procedure applies?"


@pytest.mark.asyncio
async def test_phase4_adapter_calls_tool_selector_with_capability_phrase_not_whole_user_query():
    selector = RecordingSelector(ToolSelectionResult(["get__machines_{id}"], backend_used="retrieval"))
    retriever = V2CapabilityToolRetriever(selector)  # type: ignore[arg-type]
    tools = {"get__machines_{id}": _machine_status_tool()}
    whole_user_query = "Show machine M-LTH-77 status, then explain OSHA lockout-tagout policy."
    need = CapabilityNeed(
        requirement_id="req-machine",
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        known_args={"machine_id": "M-LTH-77"},
        requested_fields=["status"],
    )

    result = await retriever.retrieve_tools_for_need(
        need,
        tools_by_name=tools,
        context_refs={"original_user_query": whole_user_query},
    )

    assert result.status == "ok"
    assert selector.calls[0]["intent"] != whole_user_query
    assert "machine" in selector.calls[0]["intent"]
    assert "status" in selector.calls[0]["intent"]
    assert "OSHA" not in selector.calls[0]["intent"]
    assert selector.calls[0]["max_tools"] == 5


@pytest.mark.asyncio
async def test_phase4_hydrates_no_more_than_five_selected_cards_and_never_full_catalog():
    retriever = V2CapabilityToolRetriever(_selector(tool_selector_top_k=10))
    tools = {
        f"machine_status_reader_{index}": _tool(
            f"machine_status_reader_{index}",
            endpoint=f"/machines/{{id}}/status-{index}",
            tags=["machine", "lookup", "status"],
            required=["id"],
            input_properties={"id": {"type": "string"}},
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
    need = CapabilityNeed(
        requirement_id="req-machine",
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        known_args={"machine_id": "M-LTH-77"},
        requested_fields=["status"],
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)
    dumped = repr(result.hydrated_tool_cards.model_dump(mode="json"))

    assert result.status == "ok"
    assert len(result.candidate_window.candidates) == 5
    assert len(result.hydrated_tool_cards.cards) == 5
    assert {card.tool_name for card in result.hydrated_tool_cards.cards} == {
        candidate.tool_name for candidate in result.candidate_window.candidates
    }
    assert "secret_unselected_marker" not in dumped


@pytest.mark.asyncio
async def test_phase4_each_capability_need_gets_its_own_candidate_window():
    retriever = V2CapabilityToolRetriever(_selector(tool_selector_top_k=10))
    tools: dict[str, ToolInfo] = {}
    for index in range(6):
        tools[f"machine_status_reader_{index}"] = _tool(
            f"machine_status_reader_{index}",
            endpoint=f"/machines/{{id}}/status-{index}",
            tags=["machine", "lookup", "status"],
            required=["id"],
            input_properties={"id": {"type": "string"}},
            entity="machine",
            response_contract="entity_status_v1",
        )
        tools[f"job_collection_reader_{index}"] = _tool(
            f"job_collection_reader_{index}",
            endpoint=f"/jobs/search-{index}",
            tags=["job", "list", "status"],
            query_params=["limit"],
            input_properties={"limit": {"type": "integer"}},
            entity="job",
            response_contract="result_collection_v1",
        )

    machine = await retriever.retrieve_tools_for_need(
        CapabilityNeed(
            requirement_id="req-machine",
            source_of_truth="operational_state",
            entity="machine",
            action="read_one",
            known_args={"machine_id": "M-LTH-77"},
            requested_fields=["status"],
        ),
        tools_by_name=tools,
    )
    jobs = await retriever.retrieve_tools_for_need(
        CapabilityNeed(
            requirement_id="req-jobs",
            source_of_truth="operational_state",
            entity="job",
            action="list",
            constraints={"limit": 5},
            requested_fields=["job_id", "status"],
        ),
        tools_by_name=tools,
    )

    assert machine.candidate_window.requirement_id == "req-machine"
    assert jobs.candidate_window.requirement_id == "req-jobs"
    assert len(machine.candidate_window.candidates) == 5
    assert len(jobs.candidate_window.candidates) == 5
    assert len(machine.candidate_window.candidates) + len(jobs.candidate_window.candidates) == 10
    assert all(candidate.tool_name.startswith("machine_") for candidate in machine.candidate_window.candidates)
    assert all(candidate.tool_name.startswith("job_") for candidate in jobs.candidate_window.candidates)


@pytest.mark.asyncio
async def test_phase4_no_match_returns_typed_failure_without_expanding_window():
    selector = RecordingSelector(ToolSelectionResult([], backend_used="retrieval"))
    retriever = V2CapabilityToolRetriever(selector)  # type: ignore[arg-type]
    need = CapabilityNeed(
        requirement_id="req-missing",
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        requested_fields=["status"],
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name={})

    assert result.status == "no_match"
    assert result.candidate_window.candidates == []
    assert result.hydrated_tool_cards.cards == []
    assert result.trace.diagnostics["reason"] == "tool_selector_returned_no_candidates"
    assert selector.calls[0]["max_tools"] == 5


@pytest.mark.asyncio
async def test_phase4_low_confidence_returns_typed_diagnostic_state():
    selector = RecordingSelector(ToolSelectionResult(["get__misc"], backend_used="retrieval"))
    retriever = V2CapabilityToolRetriever(selector, min_candidate_score=10_000)  # type: ignore[arg-type]
    tools = {
        "get__misc": _tool(
            "get__misc",
            endpoint="/misc",
            tags=["misc"],
            output_properties={"value": {"type": "string"}},
        )
    }
    need = CapabilityNeed(
        requirement_id="req-jobs",
        source_of_truth="operational_state",
        entity="job",
        action="list",
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)

    assert result.status == "low_confidence"
    assert result.trace.diagnostics["reason"] == "candidate_scores_below_threshold"
    assert result.trace.diagnostics["min_candidate_score"] == 10_000
    assert len(result.candidate_window.candidates) == 1


@pytest.mark.asyncio
async def test_phase4_missing_required_schema_returns_typed_diagnostic_state():
    selector = RecordingSelector(ToolSelectionResult(["broken_machine_reader"], backend_used="retrieval"))
    retriever = V2CapabilityToolRetriever(selector)  # type: ignore[arg-type]
    tools = {
        "broken_machine_reader": ToolInfo(
            name="broken_machine_reader",
            description="Broken machine reader",
            endpoint="/machines/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "lookup", "status"],
        )
    }
    need = CapabilityNeed(
        requirement_id="req-machine",
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        requested_fields=["status"],
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)

    assert result.status == "missing_required_schema"
    assert result.trace.diagnostics["reason"] == "selected_candidate_missing_required_schema"
    assert result.hydrated_tool_cards.cards[0].metadata["schema_diagnostics"] == [
        "endpoint_path_params_missing_from_tool_metadata",
        "required_path_arg_missing_input_schema:id",
    ]


@pytest.mark.asyncio
async def test_phase4_compatibility_fallback_use_is_traced_for_untagged_legacy_tool():
    retriever = V2CapabilityToolRetriever(_selector())
    tools = {"get__machines_{id}": _machine_status_tool(tags=[])}
    need = CapabilityNeed(
        requirement_id="req-machine",
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        known_args={"machine_id": "M-LTH-77"},
        requested_fields=["status"],
    )

    result = await retriever.retrieve_tools_for_need(need, tools_by_name=tools)

    assert result.status == "ok"
    assert result.candidate_window.candidates[0].tool_name == "get__machines_{id}"
    assert result.trace.compatibility_fallback_used is True
