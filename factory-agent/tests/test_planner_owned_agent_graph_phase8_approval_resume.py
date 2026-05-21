from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import PlannerOwnedAgentGraph, PlannerOwnedAgentGraphAdapters
from factory_agent.planning.tool_selector import ToolSelectionResult
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
    status_schema = {"type": "string", "enum": ["queued", "blocked", "done"]}
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
    }


class Phase8Selector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        request = kwargs["context"]["v2_tool_selector_adapter_request"]
        if request["safety"] == "write_requires_approval":
            names = ["patch__jobs_{id}"]
        else:
            names = ["get__jobs"]
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
        checkpointer=checkpointer,
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
    assert result.node_order[-3:] == ["approval_node", "finalize_node", "response_document_node"]
    assert context["approval_blocks"] == 1
    assert context["blocks"][-1]["type"] == "approval_required"
    assert context["blocks"][-1]["approval_label"] == "Approval 1"


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
    assert result.state.pending_approval.status == "none"
    assert result.state.response_document_context.pending_approval_id is None
    assert context["approval_blocks"] == 0
    assert context["no_record_evidence_refs"] == [result.state.evidence_ledger.evidence[0].id]
    assert context["blocks"] == [
        {
            "type": "no_record",
            "requirement_id": "req-001",
            "evidence_ref": result.state.evidence_ledger.evidence[0].id,
            "entity_type": "job",
            "summary": "No matching records were found for the first operation.",
            "source_type": "system_guard",
        }
    ]
    assert context["pending_approval"] is None
    assert all(block["type"] != "approval_required" for block in context["blocks"])


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
    assert "_create_historical_direct_v2_plan" in source
