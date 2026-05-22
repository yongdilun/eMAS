from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import PlannerOwnedAgentGraph, PlannerOwnedAgentGraphAdapters
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_planner_proposer import OfflineStructuredPlannerDecisionProposer
from factory_agent.schemas import ToolInfo


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


def _tools() -> dict[str, ToolInfo]:
    priority_schema = {"type": "string", "enum": ["low", "medium", "high"]}
    sort_schema = {"type": "string", "enum": ["deadline", "priority", "status"]}
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
        "get__machines": _tool(
            "get__machines",
            endpoint="/machines",
            tags=["machine", "list", "status"],
            query_params=["machine_id", "fields"],
            input_properties={
                "machine_id": {"type": "string", "x-ai-id-field": "machine_id", "x-ai-entity": "machine"},
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
        "get__jobs": _tool(
            "get__jobs",
            endpoint="/jobs",
            tags=["job", "list", "priority", "deadline"],
            query_params=["priority", "sort_by", "sort_dir", "limit", "fields"],
            input_properties={
                "priority": priority_schema,
                "sort_by": sort_schema,
                "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer"},
                "fields": {"type": "string"},
            },
            output_properties={
                "job_id": {"type": "string"},
                "priority": priority_schema,
                "status": {"type": "string"},
                "deadline": {"type": "string"},
            },
            entity="job",
            response_contract="result_collection_v1",
        ),
    }


class Phase6Selector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        request = kwargs["context"]["v2_tool_selector_adapter_request"]
        source = request["source_of_truth"]
        entity = request.get("entity")
        shape = request.get("endpoint_shape")
        constraints = request.get("constraints") or {}
        if source == "document_knowledge":
            names = ["rag_search_documents"]
        elif entity == "machine" and isinstance(constraints.get("machine_id"), list):
            names = ["get__machines"]
        elif entity == "machine" and shape == "single":
            names = ["get__machines_{id}"]
        elif entity == "machine":
            names = ["get__machines"]
        elif entity == "job" and shape == "single":
            names = ["get__jobs_{id}"]
        else:
            names = ["get__jobs"]
        return ToolSelectionResult(names, backend_used="retrieval", llm_calls=0)


class Phase6RAGPipeline:
    async def run(self, *, query: str, session_id: str | None = None, route: str = "RAG_ONLY", api_data=None):
        _ = session_id, route, api_data

        class Result:
            answer = "Follow the lockout tagout procedure with isolation verification. [1]"
            sources = [
                {
                    "source_id": "src-loto-1",
                    "source_number": 1,
                    "doc_id": "doc-loto",
                    "chunk_id": "chunk-loto-1",
                    "title": "Lockout Tagout Procedure",
                    "snippet": query,
                    "page": 3,
                }
            ]
            safety_content = None

        return Result()


class Phase6HttpExecutor:
    def __init__(self, *, empty_jobs: bool = False) -> None:
        self.empty_jobs = empty_jobs
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, extra_headers
        assert idempotency_key.startswith("planner-owned-agent-graph:")
        self.calls.append({"tool_name": tool.name, "args": dict(args), "idempotency_key": idempotency_key})
        if tool.name == "get__machines_{id}":
            return _ok({"data": {"machine_id": args.get("id"), "status": "running"}})
        if tool.name == "get__machines":
            machine_ids = args.get("machine_id")
            if not isinstance(machine_ids, list):
                machine_ids = [machine_ids]
            return _ok(
                {
                    "data": [
                        {"machine_id": machine_id, "status": "running"}
                        for machine_id in machine_ids
                        if machine_id
                    ]
                }
            )
        if tool.name == "get__jobs_{id}":
            return _ok({"data": {"job_id": args.get("id"), "status": "queued"}})
        if self.empty_jobs:
            return _ok({"data": []})
        rows = [
            {"job_id": "JOB-LOW-001", "priority": "low", "deadline": "2026-05-21"},
            {"job_id": "JOB-LOW-002", "priority": "low", "deadline": "2026-05-22"},
            {"job_id": "JOB-LOW-003", "priority": "low", "deadline": "2026-05-23"},
            {"job_id": "JOB-LOW-004", "priority": "low", "deadline": "2026-05-24"},
        ]
        limit = int(args.get("limit") or len(rows))
        return _ok({"data": rows[:limit]})


def _ok(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "http_status": 200,
        "latency_ms": 3,
        "body": body,
        "infrastructure_error": False,
    }


def _graph(*, http_executor: Phase6HttpExecutor | None = None) -> tuple[PlannerOwnedAgentGraph, Phase6Selector, Phase6HttpExecutor]:
    settings = _settings()
    selector = Phase6Selector()
    executor = http_executor or Phase6HttpExecutor()
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=_tools(),
            tool_selector=selector,  # type: ignore[arg-type]
            http_executor=executor,
            rag_pipeline=Phase6RAGPipeline(),
        ),
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=None,
    )
    return graph, selector, executor


def _context(result) -> dict[str, Any]:
    return result.state.response_document_context.diagnostics


@pytest.mark.asyncio
async def test_phase6_simple_machine_and_job_status_use_typed_graph_evidence():
    graph, _selector, _executor = _graph()

    machine = await graph.run("Show M-CNC-01 status.", session_context={"session_id": "phase6-machine"})
    job = await graph.run("Show JOB-SEED-001 status.", session_context={"session_id": "phase6-job"})

    machine_evidence = machine.state.evidence_ledger.evidence[0]
    job_evidence = job.state.evidence_ledger.evidence[0]

    assert machine_evidence.source_type == "api_tool"
    assert machine_evidence.normalized_result["entity_id"] == "M-CNC-01"
    assert machine_evidence.normalized_result["fields"] == {"machine_id": "M-CNC-01", "status": "running"}
    assert _context(machine)["summary"] == "Machine M-CNC-01 is running."
    assert job_evidence.source_type == "api_tool"
    assert job_evidence.normalized_result["entity_id"] == "JOB-SEED-001"
    assert job_evidence.normalized_result["fields"] == {"job_id": "JOB-SEED-001", "status": "queued"}
    assert _context(job)["summary"] == "Job JOB-SEED-001 is queued."
    assert machine.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert job.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_phase6_multi_id_machine_status_returns_typed_rows():
    graph, _selector, _executor = _graph()

    result = await graph.run(
        "Show status for machines M-CNC-01 and M-LTH-77.",
        session_context={"session_id": "phase6-multi-id"},
    )

    evidence = result.state.evidence_ledger.evidence[0]
    requirement = result.state.requirement_ledger.requirements[0]
    block = _context(result)["blocks"][0]

    assert requirement.requirement_type == "multi_entity_status"
    assert evidence.tool_name == "get__machines"
    assert evidence.args["machine_id"] == ["M-CNC-01", "M-LTH-77"]
    assert [row["machine_id"] for row in evidence.normalized_result["rows"]] == ["M-CNC-01", "M-LTH-77"]
    assert block["type"] == "multi_status"
    assert block["row_count"] == 2
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_phase6_filtered_jobs_preserve_sort_limit_and_requested_fields():
    graph, _selector, executor = _graph()

    result = await graph.run(
        "List the next 3 low priority jobs sorted by deadline with fields job id and deadline.",
        session_context={"session_id": "phase6-filtered-jobs"},
    )

    evidence = result.state.evidence_ledger.evidence[0]
    requirement = result.state.requirement_ledger.requirements[0]
    block = _context(result)["blocks"][0]

    assert executor.calls[0]["tool_name"] == "get__jobs"
    assert executor.calls[0]["args"] == {
        "priority": "low",
        "sort_by": "deadline",
        "sort_dir": "asc",
        "limit": 3,
        "fields": "job_id,deadline",
    }
    assert requirement.constraints == {"priority": "low", "sort_by": "deadline", "sort_dir": "asc", "limit": 3}
    assert requirement.requested_fields == ["job_id", "deadline"]
    assert len(evidence.normalized_result["rows"]) == 3
    assert [row["deadline"] for row in evidence.normalized_result["rows"]] == [
        "2026-05-21",
        "2026-05-22",
        "2026-05-23",
    ]
    assert evidence.normalized_result["applied_filters"] == {"priority": "low"}
    assert block["type"] == "result_table"
    assert block["requested_fields"] == ["job_id", "deadline"]
    assert "Found 3 low-priority jobs sorted by deadline" in _context(result)["summary"]
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_phase6_mixed_machine_job_and_list_summary_reflects_all_requirements():
    graph, _selector, _executor = _graph()

    result = await graph.run(
        "Show M-CNC-01 status, then show JOB-SEED-001 status, then list the next 3 low priority jobs sorted by deadline.",
        session_context={"session_id": "phase6-mixed-read"},
    )

    evidence = result.state.evidence_ledger.evidence
    context = _context(result)
    summary = context["summary"]

    assert [item.tool_name for item in evidence] == ["get__machines_{id}", "get__jobs_{id}", "get__jobs"]
    assert [block["type"] for block in context["blocks"]] == ["status_result", "status_result", "result_table"]
    assert "Machine M-CNC-01 is running" in summary
    assert "Job JOB-SEED-001 is queued" in summary
    assert "Found 3 low-priority jobs sorted by deadline" in summary
    assert summary != context["blocks"][-1]["summary"]
    assert set(context["fulfilled_requirement_ids"]) == {"req-001", "req-002", "req-003"}
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_phase6_mixed_operational_and_rag_reads_use_api_and_rag_evidence():
    graph, _selector, _executor = _graph()

    result = await graph.run(
        "Show M-CNC-01 status, then explain lockout tagout procedure.",
        session_context={"session_id": "phase6-mixed-rag"},
    )

    evidence = result.state.evidence_ledger.evidence
    context = _context(result)

    assert [item.source_type for item in evidence] == ["api_tool", "rag_tool"]
    assert evidence[1].tool_name == "rag_search_documents"
    assert evidence[1].citations[0].source_id == "src-loto-1"
    assert "Machine M-CNC-01 is running" in context["summary"]
    assert "Follow the lockout tagout procedure" in context["summary"]
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_phase6_empty_result_list_query_creates_no_record_evidence_without_stale_context():
    graph, _selector, _executor = _graph(http_executor=Phase6HttpExecutor(empty_jobs=True))

    result = await graph.run(
        "List low priority jobs sorted by deadline with fields job id and deadline.",
        session_context={"session_id": "phase6-empty-list"},
    )

    evidence = result.state.evidence_ledger.evidence[0]
    requirement = result.state.requirement_ledger.requirements[0]
    context = _context(result)

    assert evidence.normalized_result["rows"] == []
    assert evidence.normalized_result["no_match"] is True
    assert evidence.normalized_result["match_status"] == "no_match"
    assert evidence.normalized_result["summary"] == "No matching records were found."
    assert requirement.status == "impossible"
    assert context["blocks"] == [
        {
            "type": "no_record",
            "requirement_id": "req-001",
            "evidence_ref": evidence.id,
            "entity_type": "job",
            "summary": "No matching records were found.",
            "source_type": "api_tool",
        }
    ]
    assert context["no_record_evidence_refs"] == [evidence.id]
    assert "no matching records were found" in context["summary"].lower()
    assert context["preview_blocks"] == 0
    assert context["approval_blocks"] == 0
    assert context["stale_response_context_reused"] is False
    assert result.state.response_document_context.pending_approval_id is None
    assert result.state.pending_approval.status == "none"
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
