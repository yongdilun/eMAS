from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import (
    PlannerOwnedAgentGraph,
    PlannerOwnedAgentGraphAdapters,
)
from factory_agent.graph.v2_graph_tool_choice import _capability_need_for_requirement
from factory_agent.planning.v2_agent_state import GraphToolCall, PlannerDecisionRecord
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_tool_retriever import V2CapabilityToolRetriever
from factory_agent.planning.v2_planner_proposer import OfflineStructuredPlannerDecisionProposer
from factory_agent.graph.v2_graph_state_utils import _state_update
from factory_agent.schemas import ToolInfo


FACTORY_AGENT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "graph" / "v2_agent_graph.py"
GRAPH_ADAPTER_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "planning" / "v2_graph_adapters.py"
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


def _tools() -> dict[str, ToolInfo]:
    priority_schema = {"type": "string", "enum": ["low", "medium", "high"]}
    status_schema = {"type": "string", "enum": ["queued", "planned", "blocked", "done"]}
    return {
        "get__jobs": _tool(
            "get__jobs",
            endpoint="/jobs",
            tags=["job", "list", "priority", "status"],
            query_params=["priority", "status", "fields", "sort_by", "sort_dir", "limit"],
            input_properties={
                "priority": priority_schema,
                "status": status_schema,
                "fields": {"type": "string"},
                "sort_by": {"type": "string", "enum": ["deadline", "priority"]},
                "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer"},
            },
            output_properties={
                "job_id": {"type": "string", "x-ai-aliases": ["job id"]},
                "priority": priority_schema,
                "status": status_schema,
                "deadline": {"type": "string"},
            },
            entity="job",
            response_contract="result_collection_v1",
        ),
        "get__jobs_{id}": _tool(
            "get__jobs_{id}",
            endpoint="/jobs/{id}",
            tags=["job", "lookup", "status", "priority"],
            required=["id"],
            query_params=["fields"],
            input_properties={
                "id": {"type": "string", "x-ai-id-field": "job_id", "x-ai-entity": "job"},
                "fields": {"type": "string"},
            },
            output_properties={
                "job_id": {"type": "string"},
                "priority": priority_schema,
                "status": status_schema,
            },
            entity="job",
            response_contract="entity_status_v1",
        ),
        "get__processes_{id}_steps": _tool(
            "get__processes_{id}_steps",
            endpoint="/processes/{id}/steps",
            tags=["process", "step", "lookup", "status"],
            required=["id"],
            input_properties={
                "id": {"type": "string", "x-ai-id-field": "process_id", "x-ai-entity": "process"},
                "fields": {"type": "string"},
            },
            output_properties={
                "process_id": {"type": "string"},
                "step_id": {"type": "string"},
                "status": status_schema,
            },
            entity="process",
            response_contract="result_collection_v1",
        ),
        "patch__jobs_{id}": _tool(
            "patch__jobs_{id}",
            endpoint="/jobs/{id}",
            tags=["job", "update", "priority"],
            method="PATCH",
            required=["id"],
            input_properties={
                "id": {"type": "string", "x-ai-id-field": "job_id", "x-ai-entity": "job"},
                "priority": priority_schema,
            },
            output_properties={"job_id": {"type": "string"}, "priority": priority_schema},
            entity="job",
            response_contract="business_change_v1",
        ),
        "put__jobs_{id}": _tool(
            "put__jobs_{id}",
            endpoint="/jobs/{id}",
            tags=["job", "update", "priority"],
            method="PUT",
            required=["id"],
            input_properties={
                "id": {"type": "string", "x-ai-id-field": "job_id", "x-ai-entity": "job"},
                "priority": priority_schema,
                "status": status_schema,
            },
            output_properties={"job_id": {"type": "string"}, "priority": priority_schema},
            entity="job",
            response_contract="business_change_v1",
        ),
    }


def _create_job_tool() -> ToolInfo:
    return _tool(
        "post__jobs",
        endpoint="/jobs",
        tags=["job", "create"],
        method="POST",
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
        entity="job",
        response_contract="business_change_v1",
    )


class Phase8Selector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        request = kwargs["context"]["v2_tool_selector_adapter_request"]
        if request["safety"] == "write_requires_approval":
            names = ["patch__jobs_{id}"]
        else:
            names = ["get__jobs", "get__jobs_{id}"]
        return ToolSelectionResult(names, backend_used="retrieval", llm_calls=0)


class Phase8PreviewProvider:
    def __init__(self, *, no_records_for: set[str] | None = None) -> None:
        self.no_records_for = set(no_records_for or set())
        self.calls: list[dict[str, Any]] = []
        self.rows = [
            {"job_id": "JOB-LOW-001", "priority": "low", "status": "queued"},
            {"job_id": "JOB-LOW-BLOCKED", "priority": "low", "status": "blocked"},
            {"job_id": "JOB-MED-001", "priority": "medium", "status": "queued"},
        ]

    async def __call__(self, *, state, tool_call, requirement, card):
        _ = state, card
        self.calls.append({"requirement_id": requirement.id, "tool_name": tool_call.tool_name})
        if requirement.id in self.no_records_for:
            return {
                "rows": [],
                "details": {"filter": dict(requirement.constraints)},
                "no_records_message": "No matching records were found for the first operation.",
            }

        priority = requirement.constraints.get("priority")
        target_priority = requirement.constraints.get("new_priority")
        matching = [row for row in self.rows if row["priority"] == priority]
        allowed = [row for row in matching if row["status"] != "blocked"]
        blocked = [row for row in matching if row["status"] == "blocked"]
        commit_args = {}
        if allowed:
            commit_args = {"id": allowed[0]["job_id"], "priority": target_priority}
        preview_rows = [
            {**row, "new_priority": target_priority}
            for row in allowed
        ]
        return {
            "rows": preview_rows,
            "excluded_rows": blocked,
            "details": {"filter": {"priority": priority}, "new_priority": target_priority},
            "commit_args": commit_args,
        }


class Phase8ApprovalPersister:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def __call__(self, *, state, payload):
        _ = state
        self.payloads.append(dict(payload))
        return {"approval_id": f"phase8-approval-{len(self.payloads)}", "persisted": True}


class Phase8HttpExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, extra_headers
        assert idempotency_key.startswith("planner-owned-agent-graph:")
        self.calls.append({"tool_name": tool.name, "args": dict(args), "idempotency_key": idempotency_key})
        return {
            "ok": True,
            "http_status": 200,
            "latency_ms": 4,
            "body": {"data": {"job_id": args.get("id"), "priority": args.get("priority")}},
            "infrastructure_error": False,
        }


class CreateJobSelector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        return ToolSelectionResult(["post__jobs"], backend_used="retrieval", llm_calls=0)


class CreateJobHttpExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, extra_headers
        assert idempotency_key.startswith("planner-owned-agent-graph:")
        self.calls.append({"tool_name": tool.name, "args": dict(args), "idempotency_key": idempotency_key})
        return {
            "ok": True,
            "http_status": 201,
            "latency_ms": 4,
            "body": {
                "data": {
                    "job_id": "JOB-CREATED-001",
                    "product_id": args.get("product_id"),
                    "quantity_total": args.get("quantity_total"),
                }
            },
            "infrastructure_error": False,
        }


def _graph(*, preview: Phase8PreviewProvider | None = None):
    settings = _settings()
    selector = Phase8Selector()
    executor = Phase8HttpExecutor()
    persister = Phase8ApprovalPersister()
    checkpointer = MemorySaver()
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=_tools(),
            tool_selector=selector,  # type: ignore[arg-type]
            http_executor=executor,
            approval_preview_provider=preview or Phase8PreviewProvider(),
            approval_persister=persister,
        ),
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=checkpointer,
    )
    return graph, selector, executor, persister


def _create_job_graph():
    settings = _settings()
    selector = CreateJobSelector()
    executor = CreateJobHttpExecutor()
    persister = Phase8ApprovalPersister()
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name={"post__jobs": _create_job_tool()},
            tool_selector=selector,  # type: ignore[arg-type]
            http_executor=executor,
            approval_persister=persister,
        ),
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=MemorySaver(),
    )
    return graph, selector, executor, persister


def _approval_decision(result, *, approved: bool = True, **extra: Any) -> dict[str, Any]:
    pending = result.state.pending_approval
    return {
        "approval_id": pending.approval_id,
        "approved": approved,
        "ledger_revision": pending.ledger_revision,
        "checkpoint_id": pending.checkpoint_id,
        **extra,
    }


def _contains_ordered_nodes(node_order: list[str], expected: list[str]) -> bool:
    cursor = 0
    for node in node_order:
        if cursor < len(expected) and node == expected[cursor]:
            cursor += 1
    return cursor == len(expected)


class CapturingParentConfigPlannerProposer(OfflineStructuredPlannerDecisionProposer):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def propose_decision(self, *, state, context, parent_run_config=None):
        self.calls.append(
            {
                "requested_decision_kind": context.requested_decision_kind,
                "requirement_id": context.requirement_id,
                "parent_run_config": parent_run_config,
            }
        )
        return await super().propose_decision(
            state=state,
            context=context,
            parent_run_config=parent_run_config,
        )


@pytest.mark.asyncio
async def test_phase8_write_query_stages_preview_and_pauses_at_approval_node():
    graph, _selector, executor, persister = _graph()

    result = await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase8-stage"},
    )

    pending = result.state.pending_approval
    payload = pending.payload
    context = result.state.response_document_context.diagnostics

    assert pending.status == "pending"
    assert pending.approval_id == "phase8-approval-1"
    assert executor.calls == []
    assert persister.payloads
    assert payload["ledger_revision"] == result.state.requirement_ledger.revision
    assert payload["graph_checkpoint_identity"]["thread_id"] == "phase8-stage"
    assert payload["checkpoint_id"] == pending.checkpoint_id
    assert payload["selected_graph_tool_call"]["tool_name"] == "patch__jobs_{id}"
    assert payload["selected_graph_tool_call"]["args"] == {"priority": "high", "id": "JOB-LOW-001"}
    assert payload["requirement_id"] == "req-001"
    assert [row["job_id"] for row in payload["preview_rows"]] == ["JOB-LOW-001"]
    assert [row["job_id"] for row in payload["excluded_rows"]] == ["JOB-LOW-BLOCKED"]
    assert payload["blocked_rows_excluded"] is True
    assert payload["legacy_shortcut_used"] is False
    assert payload["graph_tool_action"] == "approval_gate_node"
    assert result.state.execution_trace.diagnostics["phase8_approval_staging"]["lifecycle_nodes"] == [
        "write_staging_node",
        "approval_gate_node",
    ]
    assert _contains_ordered_nodes(
        result.node_order,
        [
            "planner_choose_tool_node",
            "tool_execution_node",
            "write_staging_node",
            "approval_gate_node",
            "approval_node",
        ],
    )
    assert result.node_order[-3:] == ["approval_node", "finalize_node", "response_document_node"]
    assert context["approval_blocks"] == 1
    assert context["blocks"][-1]["type"] == "approval_required"
    assert context["blocks"][-1]["approval_label"] == "Approval 1"


@pytest.mark.asyncio
async def test_phase8_incomplete_create_job_stages_approval_form_without_direct_fill():
    graph, selector, executor, persister = _create_job_graph()

    result = await graph.run(
        "help me to create a job",
        session_context={"session_id": "phase8-create-job-form"},
    )

    pending = result.state.pending_approval
    payload = pending.payload

    assert pending.status == "pending"
    assert executor.calls == []
    assert persister.payloads
    assert selector.calls[0]["context"]["v2_tool_selector_adapter_request"]["actions"] == ["create"]
    assert payload["selected_graph_tool_call"]["tool_name"] == "post__jobs"
    assert payload["selected_graph_tool_call"]["args"] == {}
    assert payload["staged_graph_tool_calls"][0]["args"] == {}
    assert payload["preview_rows"] == [{}]
    assert payload["preview_details"]["manual_input_required"] is True
    assert payload["preview_details"]["missing_required_args"] == ["product_id", "quantity_total"]
    assert payload["legacy_shortcut_used"] is False


@pytest.mark.asyncio
async def test_manual_regression_create_job_query_renders_manual_input_approval_contract():
    graph, selector, executor, _persister = _create_job_graph()

    result = await graph.run(
        "help me to create a job",
        session_context={"session_id": "manual-regression-create-job-form"},
    )

    pending = result.state.pending_approval
    payload = pending.payload
    context = result.state.response_document_context.diagnostics
    approval_block = context["blocks"][-1]

    assert pending.status == "pending"
    assert result.state.response_document_context.state == "draft"
    assert result.state.response_document_context.pending_approval_id == pending.approval_id
    assert result.node_order[-3:] == ["approval_node", "finalize_node", "response_document_node"]
    assert executor.calls == []
    assert selector.calls[0]["context"]["v2_tool_selector_adapter_request"]["actions"] == ["create"]
    assert payload["selected_graph_tool_call"]["tool_name"] == "post__jobs"
    assert payload["selected_graph_tool_call"]["args"] == {}
    assert payload["preview_details"]["manual_input_required"] is True
    assert payload["preview_details"]["missing_required_args"] == ["product_id", "quantity_total"]
    assert approval_block["type"] == "approval_required"
    assert approval_block["selected_graph_tool_call"]["tool_name"] == "post__jobs"
    assert approval_block["selected_graph_tool_call"]["args"] == {}
    assert approval_block["details"]["manual_input_required"] is True
    assert approval_block["details"]["missing_required_args"] == ["product_id", "quantity_total"]
    assert approval_block["rows"] == [{}]


@pytest.mark.asyncio
async def test_phase8_create_job_resume_executes_with_approval_form_args():
    graph, _selector, executor, _persister = _create_job_graph()
    staged = await graph.run(
        "help me to create a job",
        session_context={"session_id": "phase8-create-job-commit"},
    )

    resumed = await graph.resume_from_approval(
        {"session_id": "phase8-create-job-commit"},
        _approval_decision(
            staged,
            decided_by="qa-user",
            approved_args={"product_id": "P-001", "quantity_total": 10},
        ),
    )

    requirement = resumed.state.requirement_ledger.requirements[0]

    assert len(executor.calls) == 1
    assert executor.calls[0]["tool_name"] == "post__jobs"
    assert executor.calls[0]["args"] == {"product_id": "P-001", "quantity_total": 10}
    assert requirement.status == "satisfied"
    assert resumed.state.pending_approval.status == "none"


@pytest.mark.asyncio
async def test_phase8_no_records_for_first_write_continues_to_second_approval():
    preview = Phase8PreviewProvider(no_records_for={"req-001"})
    graph, _selector, executor, persister = _graph(preview=preview)

    result = await graph.run(
        "Change all low priority job to medium, then change all medium priority job to high",
        session_context={"session_id": "phase8-no-records-then-approval"},
    )

    requirements = {requirement.id: requirement for requirement in result.state.requirement_ledger.requirements}
    pending = result.state.pending_approval
    payload = pending.payload

    assert requirements["req-001"].status == "impossible"
    assert requirements["req-001"].blockers == ["approval_preview_no_records"]
    assert requirements["req-002"].status == "open"
    assert pending.status == "pending"
    assert pending.requirement_id == "req-002"
    assert payload["approval_label"] == "Approval 1"
    assert payload["requirement_id"] == "req-002"
    assert payload["locked_constraints"]["priority"] == "medium"
    assert payload["locked_constraints"]["new_priority"] == "high"
    assert payload["preview_rows"][0]["job_id"] == "JOB-MED-001"
    assert payload["preview_rows"][0]["new_priority"] == "high"
    assert executor.calls == []
    assert len(persister.payloads) == 1
    assert [call["requirement_id"] for call in preview.calls] == ["req-001", "req-002"]
    assert result.state.execution_trace.planner.diagnostics["finalize_node"]["decision_kind"] == "deferred"


@pytest.mark.asyncio
async def test_phase8_commit_happens_only_after_matching_approval_and_native_checkpoint_resume():
    graph, _selector, executor, _persister = _graph()

    staged = await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase8-commit"},
    )

    assert executor.calls == []

    resumed = await graph.resume_from_approval(
        {
            "session_id": "phase8-commit",
            "replan_context": {"planner_owned_graph_state": {"pending_approval": "stale-shadow"}},
        },
        _approval_decision(staged, decided_by="qa-user"),
    )

    requirement = resumed.state.requirement_ledger.requirements[0]
    approval_evidence = next(e for e in resumed.state.evidence_ledger.evidence if e.source_type == "approval")
    api_evidence = next(e for e in resumed.state.evidence_ledger.evidence if e.source_type == "api_tool")
    resume_diag = resumed.state.execution_trace.diagnostics["phase8_resume_checkpoint"]

    assert len(executor.calls) == 1
    assert executor.calls[0]["tool_name"] == "patch__jobs_{id}"
    assert executor.calls[0]["args"] == {"priority": "high", "id": "JOB-LOW-001"}
    assert approval_evidence.normalized_result["approval_status"] == "approved"
    assert api_evidence.normalized_result["entity_id"] == "JOB-LOW-001"
    assert requirement.status == "satisfied"
    assert set(requirement.evidence_refs) == {approval_evidence.id, api_evidence.id}
    assert resumed.state.pending_approval.status == "none"
    assert resumed.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert resume_diag["native_langgraph_checkpoint_used"] is True
    assert resume_diag["session_replan_context_authoritative"] is False
    assert _contains_ordered_nodes(
        resumed.node_order,
        [
            "approval_node",
            "approval_gate_node",
            "commit_write_node",
            "evidence_observation_node",
            "satisfaction_node",
        ],
    )
    assert resumed.state.execution_trace.diagnostics["phase8_write_commit"] == {
        "status": "committed",
        "approval_id": staged.state.pending_approval.approval_id,
        "requirement_id": "req-001",
        "staged_graph_tool_call_count": 1,
        "api_evidence_count": 1,
    }


@pytest.mark.asyncio
async def test_phase8_langsmith_trace_metadata_links_initial_and_resume_segments():
    graph, _selector, _executor, _persister = _graph()

    staged = await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase8-langsmith-link"},
        options={
            "thread_id": "phase8-langsmith-link",
            "run_name": "planner_owned_agent_graph.initial",
            "tags": ["factory_agent", "graph_segment:initial", "logical_trace:trace-phase8"],
            "metadata": {
                "logical_trace_id": "trace-phase8",
                "graph_segment": "initial",
                "session_id": "phase8-langsmith-link",
            },
        },
    )

    staged_trace = staged.state.execution_trace.diagnostics["langsmith_trace"]
    assert staged.checkpoint_config["run_name"] == "planner_owned_agent_graph.initial"
    assert staged_trace["metadata"]["logical_trace_id"] == "trace-phase8"
    assert staged_trace["metadata"]["graph_segment"] == "initial"
    assert "graph_segment:initial" in staged_trace["tags"]

    resumed = await graph.resume_from_approval(
        {"session_id": "phase8-langsmith-link"},
        _approval_decision(staged, decided_by="qa-user"),
        options={
            "thread_id": "phase8-langsmith-link",
            "run_name": "planner_owned_agent_graph.post_approval_resume",
            "tags": [
                "factory_agent",
                "graph_segment:post_approval_resume",
                "logical_trace:trace-phase8",
            ],
            "metadata": {
                "logical_trace_id": "trace-phase8",
                "graph_segment": "post_approval_resume",
                "session_id": "phase8-langsmith-link",
                "approval_id": staged.state.pending_approval.approval_id,
                "approval_checkpoint_id": staged.state.pending_approval.checkpoint_id,
            },
        },
    )

    resume_trace = resumed.state.execution_trace.diagnostics["phase8_resume_checkpoint"]["langsmith_trace"]
    assert resume_trace["run_name"] == "planner_owned_agent_graph.post_approval_resume"
    assert resume_trace["metadata"]["logical_trace_id"] == "trace-phase8"
    assert resume_trace["metadata"]["graph_segment"] == "post_approval_resume"
    assert resume_trace["metadata"]["approval_id"] == staged.state.pending_approval.approval_id
    assert resume_trace["metadata"]["approval_checkpoint_id"] == staged.state.pending_approval.checkpoint_id
    assert "graph_segment:post_approval_resume" in resume_trace["tags"]


@pytest.mark.asyncio
async def test_phase8_bulk_approval_preserves_each_staged_row_id_when_approved_args_include_id():
    preview = Phase8PreviewProvider()
    preview.rows = [
        {"job_id": "JOB-LOW-001", "priority": "low", "status": "queued"},
        {"job_id": "JOB-LOW-002", "priority": "low", "status": "queued"},
    ]
    graph, _selector, executor, _persister = _graph(preview=preview)

    staged = await graph.run(
        "Set low priority jobs to medium priority.",
        session_context={"session_id": "phase8-bulk-preserve-row-id"},
    )
    staged_args = [
        call["args"]
        for call in staged.state.pending_approval.payload["staged_graph_tool_calls"]
    ]
    assert staged_args == [
        {"id": "JOB-LOW-001", "priority": "medium"},
        {"id": "JOB-LOW-002", "priority": "medium"},
    ]

    await graph.resume_from_approval(
        {"session_id": "phase8-bulk-preserve-row-id"},
        _approval_decision(
            staged,
            decided_by="qa-user",
            approved_args={"id": "JOB-LOW-001", "priority": "medium"},
        ),
    )

    assert [call["args"] for call in executor.calls] == [
        {"id": "JOB-LOW-001", "priority": "medium"},
        {"id": "JOB-LOW-002", "priority": "medium"},
    ]


@pytest.mark.asyncio
async def test_phase8_approved_write_runs_dependent_updated_jobs_read_before_finalizing():
    class ReadAfterWriteExecutor:
        def __init__(self) -> None:
            self.rows = {
                "JOB-LOW-001": {"job_id": "JOB-LOW-001", "priority": "low", "status": "planned"},
                "JOB-LOW-002": {"job_id": "JOB-LOW-002", "priority": "low", "status": "planned"},
            }
            self.calls: list[dict[str, Any]] = []

        async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
            _ = settings, idempotency_key, extra_headers
            self.calls.append({"method": tool.method, "tool_name": tool.name, "args": dict(args)})
            job_id = str(args.get("id") or "")
            if tool.method == "GET":
                row = dict(self.rows[job_id])
                return {
                    "ok": True,
                    "http_status": 200,
                    "latency_ms": 4,
                    "body": {"data": row},
                    "infrastructure_error": False,
                }
            priority = str(args.get("priority") or "")
            self.rows[job_id]["priority"] = priority
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 4,
                "body": {"data": dict(self.rows[job_id])},
                "infrastructure_error": False,
            }

    settings = _settings()
    selector = Phase8Selector()
    executor = ReadAfterWriteExecutor()
    persister = Phase8ApprovalPersister()
    preview = Phase8PreviewProvider()
    proposer = CapturingParentConfigPlannerProposer()
    preview.rows = list(executor.rows.values())
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=_tools(),
            tool_selector=selector,  # type: ignore[arg-type]
            http_executor=executor,
            approval_preview_provider=preview,
            approval_persister=persister,
        ),
        proposer=proposer,
        checkpointer=MemorySaver(),
    )

    staged = await graph.run(
        "Change planned low-priority jobs to medium priority, then show the updated jobs.",
        session_context={"session_id": "phase8-read-after-write"},
        options={
            "thread_id": "phase8-read-after-write",
            "run_name": "planner_owned_agent_graph.initial",
            "tags": ["factory_agent", "graph_segment:initial", "logical_trace:trace-read-after-write"],
            "metadata": {
                "logical_trace_id": "trace-read-after-write",
                "graph_segment": "initial",
                "session_id": "phase8-read-after-write",
            },
        },
    )
    resumed = await graph.resume_from_approval(
        {"session_id": "phase8-read-after-write"},
        _approval_decision(staged, decided_by="qa-user"),
        options={
            "thread_id": "phase8-read-after-write",
            "run_name": "planner_owned_agent_graph.post_approval_resume",
            "tags": [
                "factory_agent",
                "graph_segment:post_approval_resume",
                "logical_trace:trace-read-after-write",
            ],
            "metadata": {
                "logical_trace_id": "trace-read-after-write",
                "graph_segment": "post_approval_resume",
                "session_id": "phase8-read-after-write",
                "approval_id": staged.state.pending_approval.approval_id,
                "approval_checkpoint_id": staged.state.pending_approval.checkpoint_id,
            },
        },
    )

    requirements = {requirement.id: requirement for requirement in resumed.state.requirement_ledger.requirements}
    req_002_evidence = [
        evidence
        for evidence in resumed.state.evidence_ledger.evidence
        if evidence.requirement_id == "req-002"
    ]

    assert requirements["req-001"].status == "satisfied"
    assert requirements["req-002"].status == "satisfied"
    assert requirements["req-002"].requirement_type == "multi_entity_status"
    assert requirements["req-002"].constraints["job_id"] == ["JOB-LOW-001", "JOB-LOW-002"]
    assert resumed.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert [call["args"] for call in executor.calls if call["method"] == "PATCH"] == [
        {"id": "JOB-LOW-001", "priority": "medium"},
        {"id": "JOB-LOW-002", "priority": "medium"},
    ]
    assert [call["args"] for call in executor.calls if call["method"] == "GET"] == [
        {"id": "JOB-LOW-001"},
        {"id": "JOB-LOW-002"},
    ]
    observed_read_ids = []
    for evidence in req_002_evidence:
        result = evidence.normalized_result
        fields = result.get("fields") if isinstance(result.get("fields"), dict) else {}
        rows = result.get("rows") if isinstance(result.get("rows"), list) else []
        for candidate in [result.get("entity_id"), fields.get("job_id")]:
            if candidate:
                observed_read_ids.append(candidate)
        observed_read_ids.extend(row.get("job_id") for row in rows if isinstance(row, dict) and row.get("job_id"))
    assert sorted(set(observed_read_ids)) == ["JOB-LOW-001", "JOB-LOW-002"]

    followup_retrieve = next(
        call
        for call in proposer.calls
        if call["requested_decision_kind"] == "retrieve_tools"
        and call["requirement_id"] == "req-002"
    )
    parent_config = followup_retrieve["parent_run_config"]
    assert parent_config["run_name"] == "planner_owned_agent_graph.post_approval_resume"
    assert parent_config["configurable"]["thread_id"] == "phase8-read-after-write"
    assert "graph_segment:post_approval_resume" in parent_config["tags"]
    assert parent_config["metadata"]["logical_trace_id"] == "trace-read-after-write"
    assert parent_config["metadata"]["approval_id"] == staged.state.pending_approval.approval_id


@pytest.mark.asyncio
async def test_phase8_resume_executes_preselected_unexecuted_followup_read():
    class ReadAfterWriteExecutor:
        def __init__(self) -> None:
            self.rows = {
                "JOB-LOW-001": {"job_id": "JOB-LOW-001", "priority": "low", "status": "planned"},
                "JOB-LOW-002": {"job_id": "JOB-LOW-002", "priority": "low", "status": "planned"},
            }
            self.calls: list[dict[str, Any]] = []

        async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
            _ = settings, idempotency_key, extra_headers
            self.calls.append({"method": tool.method, "tool_name": tool.name, "args": dict(args)})
            if tool.method == "GET":
                job_id = str(args.get("id") or "")
                if job_id:
                    return {
                        "ok": True,
                        "http_status": 200,
                        "latency_ms": 4,
                        "body": {"data": dict(self.rows[job_id])},
                        "infrastructure_error": False,
                    }
                return {
                    "ok": True,
                    "http_status": 200,
                    "latency_ms": 4,
                    "body": {"data": [dict(row) for row in self.rows.values()]},
                    "infrastructure_error": False,
                }
            job_id = str(args.get("id") or "")
            self.rows[job_id]["priority"] = str(args.get("priority") or "")
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 4,
                "body": {"data": dict(self.rows[job_id])},
                "infrastructure_error": False,
            }

    settings = _settings()
    executor = ReadAfterWriteExecutor()
    preview = Phase8PreviewProvider()
    preview.rows = list(executor.rows.values())
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=_tools(),
            tool_selector=Phase8Selector(),  # type: ignore[arg-type]
            http_executor=executor,
            approval_preview_provider=preview,
            approval_persister=Phase8ApprovalPersister(),
        ),
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=MemorySaver(),
    )

    staged = await graph.run(
        "Change planned low-priority jobs to medium priority, then show the id and status of the updated jobs.",
        session_context={"session_id": "phase8-preselected-followup-read"},
    )
    requirement_ids = {requirement.id for requirement in staged.state.requirement_ledger.requirements}
    assert {"req-001", "req-002"}.issubset(requirement_ids)
    assert staged.state.pending_approval.status == "pending"

    read_need = _capability_need_for_requirement(staged.state, "req-002")
    staged.state.planner_decisions.append(
        PlannerDecisionRecord(
            decision_id="dec-preselected-retrieve-req-002",
            decision_kind="retrieve_tools",
            author="planner",
            requirement_id="req-002",
            ledger_revision=staged.state.requirement_ledger.revision,
            capability_need=read_need,
            reason="Pre-approval planner retrieval for the follow-up read.",
        )
    )
    staged.state.planner_decisions.append(
        PlannerDecisionRecord(
            decision_id="dec-preselected-choose-req-002",
            decision_kind="choose_tool",
            author="planner",
            requirement_id="req-002",
            ledger_revision=staged.state.requirement_ledger.revision,
            capability_need=read_need,
            selected_tool_call=GraphToolCall(
                call_id="call-preselected-read-req-002",
                kind="api_tool",
                tool_name="get__jobs",
                args={"fields": "job_id,status"},
                requirement_id="req-002",
                decision_id="dec-preselected-choose-req-002",
            ),
            reason="Pre-approval planner choice for the follow-up read.",
        )
    )

    await graph._compiled_graph.aupdate_state(  # type: ignore[union-attr]
        staged.checkpoint_config,
        _state_update(staged.state),
        as_node="response_document_node",
    )

    resumed = await graph.resume_from_approval(
        {"session_id": "phase8-preselected-followup-read"},
        _approval_decision(staged, decided_by="qa-user"),
    )

    requirements = {requirement.id: requirement for requirement in resumed.state.requirement_ledger.requirements}
    assert requirements["req-001"].status == "satisfied"
    assert requirements["req-002"].status == "satisfied"
    assert resumed.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert [call["tool_name"] for call in executor.calls if call["method"] == "GET"] == [
        "get__jobs_{id}",
        "get__jobs_{id}",
    ]
    assert [call["args"] for call in executor.calls if call["method"] == "GET"] == [
        {"fields": "job_id,status", "id": "JOB-LOW-001"},
        {"fields": "job_id,status", "id": "JOB-LOW-002"},
    ]


@pytest.mark.asyncio
async def test_phase8_dependent_updated_jobs_read_completes_when_selector_returns_collection_only():
    class CollectionOnlyReadSelector(Phase8Selector):
        async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
            self.calls.append(kwargs)
            request = kwargs["context"]["v2_tool_selector_adapter_request"]
            if request["safety"] == "write_requires_approval":
                return ToolSelectionResult(["patch__jobs_{id}"], backend_used="retrieval", llm_calls=0)
            return ToolSelectionResult(["get__jobs"], backend_used="retrieval", llm_calls=0)

    class ReadAfterWriteExecutor:
        def __init__(self) -> None:
            self.rows = {
                "JOB-LOW-001": {"job_id": "JOB-LOW-001", "priority": "low", "status": "planned"},
                "JOB-LOW-002": {"job_id": "JOB-LOW-002", "priority": "low", "status": "planned"},
            }
            self.calls: list[dict[str, Any]] = []

        async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
            _ = settings, idempotency_key, extra_headers
            self.calls.append({"method": tool.method, "tool_name": tool.name, "args": dict(args)})
            if tool.method == "GET" and tool.name == "get__jobs":
                return {
                    "ok": True,
                    "http_status": 200,
                    "latency_ms": 4,
                    "body": {"data": [dict(row) for row in self.rows.values()]},
                    "infrastructure_error": False,
                }
            job_id = str(args.get("id") or "")
            if tool.method == "GET":
                return {
                    "ok": True,
                    "http_status": 200,
                    "latency_ms": 4,
                    "body": {"data": dict(self.rows[job_id])},
                    "infrastructure_error": False,
                }
            self.rows[job_id]["priority"] = str(args.get("priority") or "")
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 4,
                "body": {"data": dict(self.rows[job_id])},
                "infrastructure_error": False,
            }

    settings = _settings()
    selector = CollectionOnlyReadSelector()
    executor = ReadAfterWriteExecutor()
    preview = Phase8PreviewProvider()
    preview.rows = list(executor.rows.values())
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=_tools(),
            tool_selector=selector,  # type: ignore[arg-type]
            http_executor=executor,
            approval_preview_provider=preview,
            approval_persister=Phase8ApprovalPersister(),
        ),
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=MemorySaver(),
    )

    staged = await graph.run(
        "Change planned low-priority jobs to medium priority, then show the updated jobs.",
        session_context={"session_id": "phase8-read-after-write-collection-only"},
    )
    resumed = await graph.resume_from_approval(
        {"session_id": "phase8-read-after-write-collection-only"},
        _approval_decision(staged, decided_by="qa-user"),
    )

    assert resumed.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert [call["tool_name"] for call in executor.calls if call["method"] == "GET"] == [
        "get__jobs_{id}",
        "get__jobs_{id}",
    ]
    assert [call["args"] for call in executor.calls if call["method"] == "GET"] == [
        {"id": "JOB-LOW-001"},
        {"id": "JOB-LOW-002"},
    ]


@pytest.mark.asyncio
async def test_phase8_dependent_updated_jobs_read_rejects_cross_entity_id_tools():
    class ProcessFirstSelector(Phase8Selector):
        async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
            self.calls.append(kwargs)
            request = kwargs["context"]["v2_tool_selector_adapter_request"]
            if request["safety"] == "write_requires_approval":
                names = ["patch__jobs_{id}"]
            else:
                names = ["get__processes_{id}_steps", "get__jobs_{id}"]
            return ToolSelectionResult(names, backend_used="retrieval", llm_calls=0)

    class ReadAfterWriteExecutor:
        def __init__(self) -> None:
            self.rows = {
                "JOB-LOW-001": {"job_id": "JOB-LOW-001", "priority": "low", "status": "planned"},
                "JOB-LOW-002": {"job_id": "JOB-LOW-002", "priority": "low", "status": "planned"},
            }
            self.calls: list[dict[str, Any]] = []

        async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
            _ = settings, idempotency_key, extra_headers
            self.calls.append({"method": tool.method, "tool_name": tool.name, "args": dict(args)})
            job_id = str(args.get("id") or "")
            if tool.name == "get__processes_{id}_steps":
                return {
                    "ok": True,
                    "http_status": 200,
                    "latency_ms": 4,
                    "body": {"data": []},
                    "infrastructure_error": False,
                }
            if tool.method == "GET":
                return {
                    "ok": True,
                    "http_status": 200,
                    "latency_ms": 4,
                    "body": {"data": dict(self.rows[job_id])},
                    "infrastructure_error": False,
                }
            self.rows[job_id]["priority"] = str(args.get("priority") or "")
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 4,
                "body": {"data": dict(self.rows[job_id])},
                "infrastructure_error": False,
            }

    settings = _settings()
    selector = ProcessFirstSelector()
    executor = ReadAfterWriteExecutor()
    preview = Phase8PreviewProvider()
    preview.rows = list(executor.rows.values())
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=_tools(),
            tool_selector=selector,  # type: ignore[arg-type]
            http_executor=executor,
            approval_preview_provider=preview,
            approval_persister=Phase8ApprovalPersister(),
        ),
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=MemorySaver(),
    )

    staged = await graph.run(
        "Change planned low-priority jobs to medium priority, then show the updated jobs.",
        session_context={"session_id": "phase8-cross-entity-read-tool"},
    )
    resumed = await graph.resume_from_approval(
        {"session_id": "phase8-cross-entity-read-tool"},
        _approval_decision(staged, decided_by="qa-user"),
    )

    assert resumed.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert [call["tool_name"] for call in executor.calls if call["method"] == "GET"] == [
        "get__jobs_{id}",
        "get__jobs_{id}",
    ]
    assert all(call["tool_name"] != "get__processes_{id}_steps" for call in executor.calls)


@pytest.mark.asyncio
async def test_phase8_live_approval_preview_stages_row_ids_when_write_window_is_tiny():
    class PutOnlySelector(Phase8Selector):
        async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
            self.calls.append(kwargs)
            request = kwargs["context"]["v2_tool_selector_adapter_request"]
            if request["safety"] == "write_requires_approval":
                return ToolSelectionResult(["put__jobs_{id}"], backend_used="retrieval", llm_calls=0)
            return ToolSelectionResult(["get__jobs_{id}"], backend_used="retrieval", llm_calls=0)

    class LivePreviewExecutor:
        def __init__(self) -> None:
            self.rows = {
                "JOB-LOW-001": {"job_id": "JOB-LOW-001", "priority": "low", "status": "planned"},
                "JOB-LOW-002": {"job_id": "JOB-LOW-002", "priority": "low", "status": "planned"},
            }
            self.calls: list[dict[str, Any]] = []

        async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
            _ = settings, idempotency_key, extra_headers
            self.calls.append({"method": tool.method, "tool_name": tool.name, "args": dict(args)})
            if tool.method == "GET" and tool.name == "get__jobs":
                priority = args.get("priority")
                status = args.get("status")
                rows = [
                    dict(row)
                    for row in self.rows.values()
                    if (priority in (None, "", [], {}) or row.get("priority") == priority)
                    and (status in (None, "", [], {}) or row.get("status") == status)
                ]
                return {
                    "ok": True,
                    "http_status": 200,
                    "latency_ms": 4,
                    "body": {"data": rows},
                    "infrastructure_error": False,
                }
            job_id = str(args.get("id") or "")
            if tool.method == "GET":
                return {
                    "ok": True,
                    "http_status": 200,
                    "latency_ms": 4,
                    "body": {"data": dict(self.rows[job_id])},
                    "infrastructure_error": False,
                }
            if not job_id:
                return {
                    "ok": False,
                    "http_status": 400,
                    "latency_ms": 4,
                    "body": {"error_type": "invalid_payload", "message": "Missing required id."},
                    "infrastructure_error": False,
                }
            self.rows[job_id]["priority"] = str(args.get("priority") or "")
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 4,
                "body": {"data": dict(self.rows[job_id])},
                "infrastructure_error": False,
            }

    settings = _settings()
    selector = PutOnlySelector()
    executor = LivePreviewExecutor()
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=_tools(),
            tool_selector=selector,  # type: ignore[arg-type]
            tool_retriever=V2CapabilityToolRetriever(selector, max_candidates=1),  # type: ignore[arg-type]
            http_executor=executor,
            approval_persister=Phase8ApprovalPersister(),
        ),
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=MemorySaver(),
    )

    staged = await graph.run(
        "Change planned low-priority jobs to medium priority, then show the updated jobs.",
        session_context={"session_id": "phase8-live-preview-tiny-window"},
    )
    staged_args = [
        call["args"]
        for call in staged.state.pending_approval.payload["staged_graph_tool_calls"]
    ]

    assert staged_args == [
        {"id": "JOB-LOW-001", "priority": "medium", "status": "planned"},
        {"id": "JOB-LOW-002", "priority": "medium", "status": "planned"},
    ]

    resumed = await graph.resume_from_approval(
        {"session_id": "phase8-live-preview-tiny-window"},
        _approval_decision(staged, decided_by="qa-user"),
    )

    assert resumed.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert [call for call in executor.calls if call["method"] == "PUT"] == [
        {
            "method": "PUT",
            "tool_name": "put__jobs_{id}",
            "args": {"id": "JOB-LOW-001", "priority": "medium", "status": "planned"},
        },
        {
            "method": "PUT",
            "tool_name": "put__jobs_{id}",
            "args": {"id": "JOB-LOW-002", "priority": "medium", "status": "planned"},
        },
    ]


@pytest.mark.asyncio
async def test_phase8_rejection_creates_rejection_evidence_and_finalizes_safely():
    graph, _selector, executor, _persister = _graph()
    staged = await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase8-reject"},
    )

    resumed = await graph.resume_from_approval(
        {"session_id": "phase8-reject"},
        _approval_decision(staged, approved=False, rejection_reason="Operator declined the change."),
    )

    requirement = resumed.state.requirement_ledger.requirements[0]
    evidence = resumed.state.evidence_ledger.evidence[0]

    assert executor.calls == []
    assert evidence.source_type == "approval"
    assert evidence.normalized_result["approval_status"] == "rejected"
    assert evidence.normalized_result["rejection_reason"] == "Operator declined the change."
    assert requirement.status == "impossible"
    assert resumed.state.pending_approval.status == "rejected"
    assert resumed.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_phase8_stale_approval_is_rejected_without_commit():
    graph, _selector, executor, _persister = _graph()
    staged = await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase8-stale"},
    )

    stale = _approval_decision(staged, ledger_revision=999)
    resumed = await graph.resume_from_approval({"session_id": "phase8-stale"}, stale)

    evidence = resumed.state.evidence_ledger.evidence[0]

    assert executor.calls == []
    assert evidence.source_type == "approval"
    assert evidence.normalized_result["approval_status"] == "stale"
    assert evidence.normalized_result["reason"] == "stale_approval_rejected"
    assert resumed.state.pending_approval.status == "stale"
    assert resumed.state.requirement_ledger.requirements[0].status == "impossible"
    assert resumed.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_phase8_multi_step_approval_labels_approval_one_and_two():
    graph, _selector, executor, _persister = _graph()

    first = await graph.run(
        "Set low priority jobs to high priority, then set medium priority jobs to low priority.",
        session_context={"session_id": "phase8-multi"},
    )
    second = await graph.resume_from_approval(
        {"session_id": "phase8-multi"},
        _approval_decision(first),
    )

    assert first.state.pending_approval.payload["approval_label"] == "Approval 1"
    assert second.state.pending_approval.status == "pending"
    assert second.state.pending_approval.payload["approval_label"] == "Approval 2"
    assert second.state.pending_approval.payload["selected_graph_tool_call"]["args"] == {
        "priority": "low",
        "id": "JOB-MED-001",
    }
    assert len(executor.calls) == 1
    assert executor.calls[0]["args"] == {"priority": "high", "id": "JOB-LOW-001"}


@pytest.mark.asyncio
async def test_phase8_low_to_medium_then_medium_to_high_stages_second_approval_without_llm():
    class StatefulPriorityExecutor:
        def __init__(self) -> None:
            self.rows = [
                {"job_id": "JOB-LOW-001", "priority": "low", "status": "queued"},
                {"job_id": "JOB-MED-001", "priority": "medium", "status": "queued"},
            ]
            self.calls: list[dict[str, Any]] = []

        async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
            _ = settings, idempotency_key, extra_headers
            self.calls.append({"tool_name": tool.name, "method": tool.method, "args": dict(args)})
            if tool.method == "GET":
                priority = args.get("priority")
                return {
                    "ok": True,
                    "http_status": 200,
                    "latency_ms": 4,
                    "body": {
                        "data": [
                            dict(row)
                            for row in self.rows
                            if priority in (None, "", [], {}) or row.get("priority") == priority
                        ]
                    },
                    "infrastructure_error": False,
                }

            job_id = str(args.get("id") or "")
            priority = args.get("priority")
            for row in self.rows:
                if row.get("job_id") == job_id:
                    row["priority"] = priority
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 4,
                "body": {"data": {"job_id": job_id, "priority": priority}},
                "infrastructure_error": False,
            }

    settings = _settings()
    selector = Phase8Selector()
    executor = StatefulPriorityExecutor()
    persister = Phase8ApprovalPersister()
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name=_tools(),
            tool_selector=selector,  # type: ignore[arg-type]
            http_executor=executor,
            approval_persister=persister,
        ),
        proposer=OfflineStructuredPlannerDecisionProposer(),
        checkpointer=MemorySaver(),
    )

    first = await graph.run(
        "Change all low priority job to medium, then change all medium priority job to high",
        session_context={"session_id": "phase8-low-medium-high"},
    )
    second = await graph.resume_from_approval(
        {"session_id": "phase8-low-medium-high"},
        _approval_decision(first),
    )

    assert first.state.pending_approval.payload["approval_label"] == "Approval 1"
    assert first.state.pending_approval.payload["ledger_revision"] == 1
    assert first.state.pending_approval.payload["checkpoint_id"] == "phase8-low-medium-high:ledger-1:approval"
    assert {row["previous_priority"] for row in first.state.pending_approval.payload["preview_rows"]} == {"low"}
    assert {row["new_priority"] for row in first.state.pending_approval.payload["preview_rows"]} == {"medium"}
    assert second.state.pending_approval.status == "pending"
    assert second.state.pending_approval.payload["approval_label"] == "Approval 2"
    assert second.state.pending_approval.payload["ledger_revision"] == 2
    assert second.state.pending_approval.payload["checkpoint_id"] == "phase8-low-medium-high:ledger-2:approval"
    assert {row["previous_priority"] for row in second.state.pending_approval.payload["preview_rows"]} == {"medium"}
    assert {row["new_priority"] for row in second.state.pending_approval.payload["preview_rows"]} == {"high"}
    assert [call["args"] for call in executor.calls if call["method"] == "PATCH"] == [
        {"id": "JOB-LOW-001", "priority": "medium"}
    ]
    assert second.state.execution_trace.tool_retrieval.reranker.call_count == 0


@pytest.mark.asyncio
async def test_phase8_no_record_first_operation_does_not_show_stale_or_future_approval_details():
    preview = Phase8PreviewProvider(no_records_for={"req-001"})
    graph, _selector, executor, _persister = _graph(preview=preview)

    result = await graph.run(
        "Set low priority jobs to high priority, then set medium priority jobs to low priority.",
        session_context={"session_id": "phase8-no-record-first"},
    )

    context = result.state.response_document_context.diagnostics

    assert executor.calls == []
    assert result.state.pending_approval.status == "pending"
    assert result.state.pending_approval.requirement_id == "req-002"
    assert result.state.response_document_context.pending_approval_id == "phase8-approval-1"
    assert context["approval_blocks"] == 1
    assert context["no_record_evidence_refs"] == [result.state.evidence_ledger.evidence[0].id]
    assert context["blocks"][0] == {
        "type": "no_record",
        "requirement_id": "req-001",
        "evidence_ref": result.state.evidence_ledger.evidence[0].id,
        "entity_type": "job",
        "summary": "No matching records were found for the first operation.",
        "source_type": "system_guard",
    }
    assert context["blocks"][1]["type"] == "approval_required"
    assert context["blocks"][1]["approval_label"] == "Approval 1"
    assert context["blocks"][1]["requirement_id"] == "req-002"
    assert context["blocks"][1]["rows"][0]["job_id"] == "JOB-MED-001"
    assert context["pending_approval"]["requirement_id"] == "req-002"


def test_phase8_runtime_has_no_prompt_seed_or_source_id_branches():
    runtime_source = (
        GRAPH_SOURCE.read_text(encoding="utf-8")
        + "\n"
        + GRAPH_ADAPTER_SOURCE.read_text(encoding="utf-8")
    )

    banned_literals = [
        "JOB-LOW-001",
        "phase8-stage",
        "Set low priority jobs to high priority",
        "JOB-SEED",
        "src-loto-1",
        "legacy_rag_route",
    ]
    for literal in banned_literals:
        assert literal not in runtime_source


def test_phase8_normal_runtime_switches_to_graph_after_phase10():
    source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    runtime_source = RUNTIME_ADAPTER_SOURCE.read_text(encoding="utf-8")

    assert "PlannerOwnedGraphRuntimeAdapter" in source
    assert "PlannerOwnedAgentGraph" in runtime_source
    assert '"thread_id": sess.session_id' in runtime_source
    assert "_create_historical_direct_v2_plan" not in source
