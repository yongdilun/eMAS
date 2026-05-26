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
from factory_agent.planning.v2_graph_adapters import GraphExecutionAuthorizationError, execute_graph_api_tool_call
from factory_agent.planning.v2_planner_decisions import PlannerDecisionSubmission, record_planner_decision
from factory_agent.planning.v2_planner_proposer import (
    OfflineStructuredPlannerDecisionProposer,
    PlannerDecisionProposalResult,
)
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


def _alternate_machine_status_tool() -> ToolInfo:
    return _tool(
        "get__machine_status_{id}",
        endpoint="/machine-status/{id}",
        tags=["machine", "lookup", "status", "alternate"],
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


class SequentialRecordingSelector:
    def __init__(self, name_batches: list[list[str]]) -> None:
        self.name_batches = name_batches
        self.calls: list[dict[str, Any]] = []
        self.returned_name_batches: list[list[str]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.name_batches) - 1)
        names = self.name_batches[index]
        self.returned_name_batches.append(list(names))
        return ToolSelectionResult(names, backend_used="retrieval", llm_calls=0)


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


async def _timeout_fault_http_executor(settings, tool, args, *, idempotency_key, extra_headers=None):
    _ = settings, tool, args, idempotency_key, extra_headers
    return {
        "ok": False,
        "http_status": None,
        "latency_ms": 0,
        "body": {
            "error_type": "timeout",
            "message": "Controlled typed timeout from the seeded tool fault harness.",
        },
        "infrastructure_error": True,
    }


async def _raising_http_executor(settings, tool, args, *, idempotency_key, extra_headers=None):
    _ = settings, tool, args, idempotency_key, extra_headers
    raise ValueError("Missing required path args: id")


class SequentialMachineStatusExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, tool, idempotency_key, extra_headers
        self.calls.append({"args": dict(args)})
        if len(self.calls) == 1:
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 3,
                "body": {
                    "data": {
                        "machine_id": args.get("id"),
                        "location": "line-7",
                    }
                },
                "infrastructure_error": False,
            }
        return {
            "ok": True,
            "http_status": 200,
            "latency_ms": 4,
            "body": {
                "data": {
                    "machine_id": args.get("id"),
                    "status": "running",
                }
            },
            "infrastructure_error": False,
        }


class AlwaysMissingStatusExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, tool, idempotency_key, extra_headers
        self.calls.append({"args": dict(args)})
        return {
            "ok": True,
            "http_status": 200,
            "latency_ms": 3,
            "body": {
                "data": {
                    "machine_id": args.get("id"),
                    "location": "line-7",
                }
            },
            "infrastructure_error": False,
        }


class FailPrimaryThenSucceedAlternateExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, idempotency_key, extra_headers
        self.calls.append({"tool_name": tool.name, "args": dict(args)})
        if tool.name == "get__machines_{id}":
            return {
                "ok": False,
                "http_status": 503,
                "latency_ms": 2,
                "body": {"error": "primary upstream unavailable"},
                "infrastructure_error": True,
            }
        return {
            "ok": True,
            "http_status": 200,
            "latency_ms": 5,
            "body": {
                "data": {
                    "machine_id": args.get("id"),
                    "status": "running",
                }
            },
            "infrastructure_error": False,
        }


class AlwaysTimeoutExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, idempotency_key, extra_headers
        self.calls.append({"tool_name": tool.name, "args": dict(args)})
        return {
            "ok": False,
            "http_status": 504,
            "latency_ms": 30000,
            "body": {"error": "primary machine status lookup timed out"},
            "infrastructure_error": True,
        }


def _graph(
    *,
    tools_by_name: dict[str, ToolInfo] | None = None,
    selector: RecordingSelector | None = None,
    http_executor=_successful_http_executor,
    rag_pipeline: Any | None = None,
    max_replans: int | None = None,
    proposer: Any | None = None,
) -> PlannerOwnedAgentGraph:
    settings = _settings()
    if max_replans is not None:
        settings = replace(settings, max_replans=max_replans)
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
        proposer=proposer or OfflineStructuredPlannerDecisionProposer(),
        checkpointer=None,
    )


def _planner_proposal(decision: PlannerDecisionRecord, *, adapter: str) -> PlannerDecisionProposalResult:
    diagnostics = {
        "proposer_seam": True,
        "adapter": adapter,
        "decision_id": decision.decision_id,
        "bounded_state_view": True,
        "full_openapi_catalog_visible": False,
    }
    decision = decision.model_copy(
        update={"diagnostics": {**decision.diagnostics, "planner_proposer": diagnostics}},
        deep=True,
    )
    return PlannerDecisionProposalResult(
        submission=PlannerDecisionSubmission(decision=decision),
        diagnostics=diagnostics,
    )


class RepeatFailedFullSelectedCallProposer:
    def __init__(self) -> None:
        self.contexts: list[Any] = []
        self.first_selected_call: GraphToolCall | None = None
        self.repeated_failed_full_call = False

    async def propose_decision(self, *, state, context):
        self.contexts.append(context)
        if context.requested_decision_kind == "retrieve_tools":
            return _planner_proposal(
                PlannerDecisionRecord(
                    decision_id=context.decision_id,
                    decision_kind="retrieve_tools",
                    requirement_id=context.requirement_id,
                    ledger_revision=state.requirement_ledger.revision,
                    capability_need=context.capability_need,
                    reason="Retrieve a bounded tool window.",
                ),
                adapter="repeat_failed_full_selected_call_proposer",
            )

        if context.requested_decision_kind != "choose_tool":
            return _planner_proposal(
                PlannerDecisionRecord(
                    decision_id=context.decision_id,
                    decision_kind="fail",
                    ledger_revision=state.requirement_ledger.revision,
                    reason="Unexpected decision request in regression proposer.",
                ),
                adapter="repeat_failed_full_selected_call_proposer",
            )

        if self.first_selected_call is None:
            selected = context.candidate_tool_calls[0]
            self.first_selected_call = selected.model_copy(deep=True)
        elif not self.repeated_failed_full_call:
            selected = self.first_selected_call.model_copy(deep=True)
            self.repeated_failed_full_call = True
        else:
            selected = context.candidate_tool_calls[0]

        return _planner_proposal(
            PlannerDecisionRecord(
                decision_id=context.decision_id,
                decision_kind="choose_tool",
                requirement_id=context.requirement_id,
                ledger_revision=state.requirement_ledger.revision,
                capability_need=context.capability_need,
                selected_tool_call=selected,
                reason="Select from the bounded candidate window.",
            ),
            adapter="repeat_failed_full_selected_call_proposer",
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
async def test_replan_spine_retries_after_retriable_missing_evidence_and_then_satisfies():
    executor = SequentialMachineStatusExecutor()
    selector = RecordingSelector(["get__machines_{id}"])

    result = await _graph(selector=selector, http_executor=executor).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "replan-spine-read-recovery"},
    )

    requirement = result.state.requirement_ledger.requirements[0]
    evidence = result.state.evidence_ledger.evidence
    diagnostics = result.state.execution_trace.diagnostics

    assert len(executor.calls) == 2
    assert len(selector.calls) == 2
    assert requirement.status == "satisfied"
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert "status" not in evidence[0].normalized_result.get("fields", {})
    assert evidence[-1].normalized_result.get("fields", {}).get("status") == "running"
    assert requirement.evidence_refs == [evidence[-1].id]
    assert diagnostics["satisfaction"]["missing_evidence_reasons"][0]["retriable"] is True
    assert diagnostics["replan_spine"]["attempt_count"] == 1
    assert diagnostics["phase9_active_revision_evidence"]["historical_evidence_refs"] == [evidence[0].id]


@pytest.mark.asyncio
async def test_replan_spine_routes_unsatisfied_retriable_requirement_back_to_planner():
    executor = SequentialMachineStatusExecutor()
    result = await _graph(http_executor=executor).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "replan-spine-route"},
    )

    node_order = result.node_order
    replan = result.state.execution_trace.diagnostics["replan_spine"]
    requirement = result.state.requirement_ledger.requirements[0]

    assert node_order.count("planner_decision_node") == 2
    assert node_order.count("tool_retrieval_node") == 2
    assert node_order.count("planner_choose_tool_node") == 2
    assert node_order.count("tool_execution_node") == 2
    assert node_order.count("satisfaction_node") == 2
    assert replan["attempt_count"] == 1
    assert replan["attempts"][0]["requirement_ids"] == [requirement.id]
    assert replan["route"] == "approval_node"
    assert requirement.status == "satisfied"
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_replan_spine_marks_retriable_bad_evidence_inactive_before_retry():
    result = await _graph(http_executor=SequentialMachineStatusExecutor()).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "replan-spine-stale-evidence"},
    )

    first_evidence, final_evidence = result.state.evidence_ledger.evidence
    requirement = result.state.requirement_ledger.requirements[0]
    replan = result.state.execution_trace.diagnostics["replan_spine"]

    assert first_evidence.diagnostic_metadata["active_revision_satisfaction"] is False
    assert first_evidence.diagnostic_metadata["stale_after_graph_replan"] is True
    assert first_evidence.diagnostic_metadata["superseded_reason"] == "replan_spine_retry"
    assert final_evidence.diagnostic_metadata["active_revision_satisfaction"] is True
    assert requirement.status == "satisfied"
    assert requirement.locked_constraints == ["machine_id", "requested_fields"]
    assert requirement.evidence_refs == [final_evidence.id]
    assert result.state.response_document_context.evidence_refs == [final_evidence.id]
    assert result.state.response_document_context.diagnostics["historical_evidence_refs"] == [first_evidence.id]
    assert replan["stale_attempt_evidence_refs"] == [first_evidence.id]
    assert replan["active_final_evidence_refs"] == [final_evidence.id]


@pytest.mark.asyncio
async def test_replan_spine_passes_missing_evidence_context_to_tool_retrieval():
    selector = RecordingSelector(["get__machines_{id}"])

    result = await _graph(selector=selector, http_executor=SequentialMachineStatusExecutor()).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "replan-spine-retrieval-context"},
    )

    first_evidence = result.state.evidence_ledger.evidence[0]
    second_context = selector.calls[1]["context"]
    context_refs = second_context["context_refs"]
    adapter_request = second_context["v2_tool_selector_adapter_request"]

    assert len(selector.calls) == 2
    assert context_refs["replan_attempt"] == 1
    assert context_refs["missing_evidence_reasons"][0]["requirement_id"] == "req-001"
    assert context_refs["missing_evidence_reasons"][0]["retriable"] is True
    assert context_refs["active_evidence_refs"] == []
    assert context_refs["historical_evidence_refs"] == [first_evidence.id]
    assert adapter_request["capability_need"]["reason"].startswith("replan_spine:")


@pytest.mark.asyncio
async def test_replan_spine_avoids_repeating_failed_tool_when_alternate_candidate_exists():
    executor = FailPrimaryThenSucceedAlternateExecutor()
    selector = RecordingSelector(["get__machines_{id}", "get__machine_status_{id}"])

    result = await _graph(
        tools_by_name={
            "get__machines_{id}": _machine_status_tool(),
            "get__machine_status_{id}": _alternate_machine_status_tool(),
        },
        selector=selector,
        http_executor=executor,
    ).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "replan-spine-failed-tool-memory"},
    )

    failed_evidence, final_evidence = result.state.evidence_ledger.evidence
    failed_calls = result.state.execution_trace.diagnostics["replan_spine"]["failed_tool_calls"]
    second_context = selector.calls[1]["context"]["context_refs"]

    assert [call["tool_name"] for call in executor.calls] == [
        "get__machines_{id}",
        "get__machine_status_{id}",
    ]
    assert failed_calls == [
        {
            "tool_name": "get__machines_{id}",
            "args": {"id": "M-LTH-77", "fields": "status"},
            "requirement_id": "req-001",
            "evidence_ref": failed_evidence.id,
            "reason": "tool_error",
            "attempt": 1,
        }
    ]
    assert second_context["failed_tool_calls"] == failed_calls
    assert final_evidence.tool_name == "get__machine_status_{id}"
    assert result.state.requirement_ledger.requirements[0].status == "satisfied"
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_replan_spine_rejects_repeated_failed_full_selected_call_when_alternate_exists():
    executor = FailPrimaryThenSucceedAlternateExecutor()
    selector = SequentialRecordingSelector(
        [
            ["get__machines_{id}"],
            ["get__machines_{id}", "get__machine_status_{id}"],
        ]
    )
    proposer = RepeatFailedFullSelectedCallProposer()

    result = await _graph(
        tools_by_name={
            "get__machines_{id}": _machine_status_tool(),
            "get__machine_status_{id}": _alternate_machine_status_tool(),
        },
        selector=selector,  # type: ignore[arg-type]
        http_executor=executor,
        proposer=proposer,
    ).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "replan-spine-reject-stale-full-selected"},
    )

    replan = result.state.execution_trace.diagnostics["replan_spine"]
    failed_calls = replan["failed_tool_calls"]
    choose_contexts = [
        context for context in proposer.contexts if context.requested_decision_kind == "choose_tool"
    ]
    second_choose_context = choose_contexts[1]
    rejected = result.state.execution_trace.planner.diagnostics["planner_decision_proposer"]["rejected"]
    executed_tool_names = [call["tool_name"] for call in executor.calls]

    assert selector.returned_name_batches[0] == ["get__machines_{id}"]
    assert selector.returned_name_batches[1] == ["get__machines_{id}", "get__machine_status_{id}"]
    assert failed_calls == [
        {
            "tool_name": "get__machines_{id}",
            "args": {"id": "M-LTH-77", "fields": "status"},
            "requirement_id": "req-001",
            "evidence_ref": result.state.evidence_ledger.evidence[0].id,
            "reason": "tool_error",
            "attempt": 1,
        }
    ]
    assert proposer.repeated_failed_full_call is True
    assert [call.tool_name for call in second_choose_context.candidate_tool_calls] == ["get__machine_status_{id}"]
    assert any("failed-tool memory" in item["reason"] for item in rejected)
    assert executed_tool_names.count("get__machines_{id}") == 1
    assert "get__machine_status_{id}" in executed_tool_names or result.state.response_document_context.state == "failed"


@pytest.mark.asyncio
async def test_replan_spine_retries_read_tool_error_without_preexisting_alternate_candidate():
    executor = AlwaysTimeoutExecutor()
    selector = SequentialRecordingSelector(
        [
            ["get__machines_{id}"],
            ["get__machines_{id}"],
            ["get__machines_{id}"],
        ]
    )

    result = await _graph(
        selector=selector,  # type: ignore[arg-type]
        http_executor=executor,
        max_replans=2,
    ).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "replan-spine-tool-error-no-initial-alternate"},
    )

    replan = result.state.execution_trace.diagnostics["replan_spine"]
    failed_calls = replan["failed_tool_calls"]
    requirement = result.state.requirement_ledger.requirements[0]
    second_context = selector.calls[1]["context"]["context_refs"]

    assert selector.returned_name_batches[0] == ["get__machines_{id}"]
    assert [call["tool_name"] for call in executor.calls] == [
        "get__machines_{id}",
        "get__machines_{id}",
        "get__machines_{id}",
    ]
    assert len(selector.calls) == 3
    assert replan["attempt_count"] == 2
    assert replan["max_attempts"] == 2
    assert replan["replan_limit_reached"] is True
    assert len(failed_calls) == 3
    assert failed_calls[0]["reason"] == "tool_error"
    assert failed_calls[0]["tool_name"] == "get__machines_{id}"
    assert second_context["failed_tool_calls"][:1] == failed_calls[:1]
    assert second_context["missing_evidence_reasons"][0]["reason"] == "tool_error"
    assert requirement.status == "failed"
    assert result.state.final_validation_result.status == "failed"  # type: ignore[union-attr]
    assert result.state.response_document_context.state == "failed"


@pytest.mark.asyncio
async def test_replan_spine_discovers_alternate_after_read_tool_error_and_excludes_failed_evidence():
    executor = FailPrimaryThenSucceedAlternateExecutor()
    selector = SequentialRecordingSelector(
        [
            ["get__machines_{id}"],
            ["get__machines_{id}", "get__machine_status_{id}"],
        ]
    )

    result = await _graph(
        tools_by_name={
            "get__machines_{id}": _machine_status_tool(),
            "get__machine_status_{id}": _alternate_machine_status_tool(),
        },
        selector=selector,  # type: ignore[arg-type]
        http_executor=executor,
    ).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "replan-spine-tool-error-alternate-discovery"},
    )

    failed_evidence, final_evidence = result.state.evidence_ledger.evidence
    replan = result.state.execution_trace.diagnostics["replan_spine"]
    failed_calls = replan["failed_tool_calls"]
    requirement = result.state.requirement_ledger.requirements[0]
    second_context = selector.calls[1]["context"]["context_refs"]

    assert selector.returned_name_batches[0] == ["get__machines_{id}"]
    assert selector.returned_name_batches[1] == ["get__machines_{id}", "get__machine_status_{id}"]
    assert [call["tool_name"] for call in executor.calls] == [
        "get__machines_{id}",
        "get__machine_status_{id}",
    ]
    assert failed_calls == [
        {
            "tool_name": "get__machines_{id}",
            "args": {"id": "M-LTH-77", "fields": "status"},
            "requirement_id": "req-001",
            "evidence_ref": failed_evidence.id,
            "reason": "tool_error",
            "attempt": 1,
        }
    ]
    assert second_context["failed_tool_calls"] == failed_calls
    assert failed_evidence.diagnostic_metadata["active_revision_satisfaction"] is False
    assert failed_evidence.diagnostic_metadata["stale_after_graph_replan"] is True
    assert final_evidence.tool_name == "get__machine_status_{id}"
    assert final_evidence.diagnostic_metadata["active_revision_satisfaction"] is True
    assert requirement.status == "satisfied"
    assert requirement.evidence_refs == [final_evidence.id]
    assert result.state.response_document_context.evidence_refs == [final_evidence.id]
    assert replan["stale_attempt_evidence_refs"] == [failed_evidence.id]
    assert replan["active_final_evidence_refs"] == [final_evidence.id]
    assert failed_evidence.id not in replan["active_final_evidence_refs"]
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_replan_spine_stops_at_max_attempts_with_safe_failure_diagnostic():
    executor = AlwaysMissingStatusExecutor()

    result = await _graph(http_executor=executor, max_replans=2).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "replan-spine-limit-safe-failure"},
    )

    replan = result.state.execution_trace.diagnostics["replan_spine"]
    requirement = result.state.requirement_ledger.requirements[0]
    response_diagnostics = result.state.response_document_context.diagnostics

    assert len(executor.calls) == 3
    assert replan["attempt_count"] == 2
    assert replan["max_attempts"] == 2
    assert replan["replan_limit_reached"] is True
    assert requirement.status == "blocked"
    assert result.state.final_validation_result.status == "failed"  # type: ignore[union-attr]
    assert result.state.response_document_context.state == "failed"
    assert response_diagnostics["replan_limit_reached"] is True
    assert response_diagnostics["replan_spine"]["replan_limit_reached"] is True


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
async def test_failed_api_tool_preserves_structured_fault_type_for_retry_story():
    result = await _graph(http_executor=_timeout_fault_http_executor).run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase5-api-timeout-fault-type"},
    )

    evidence = result.state.evidence_ledger.evidence[0]

    assert evidence.normalized_result["error"]["code"] == "tool_error"
    assert evidence.normalized_result["error"]["error_type"] == "timeout"
    assert evidence.diagnostic_metadata["error_type"] == "timeout"


@pytest.mark.asyncio
async def test_phase5_tool_executor_exception_is_typed_failed_tool_evidence():
    state, _requirement, _need, call = _state_with_persisted_choice()
    decision = next(decision for decision in state.planner_decisions if decision.decision_kind == "choose_tool")

    execution = await execute_graph_api_tool_call(
        settings=_settings(),
        state=state,
        decision=decision,
        call=call,
        tool=_machine_status_tool(),
        http_executor=_raising_http_executor,
    )

    assert execution.ok is False
    assert execution.source_type == "api_tool"
    assert execution.normalized_result["status"] == "tool_failed"
    assert execution.normalized_result["error"]["code"] == "tool_error"
    assert execution.normalized_result["error"]["exception_type"] == "ValueError"
    assert execution.diagnostic_metadata["reason"] == "tool_error"
    assert execution.diagnostic_metadata["graph_authorized_execution"] is True


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
async def test_phase5_direct_v2_execution_helpers_are_not_used():
    from factory_agent.services.plan_creation_service import PlanCreationService

    assert not hasattr(PlanCreationService, "_execute_direct_v2_steps")
    assert not hasattr(PlanCreationService, "_execute_direct_v2_api_step")
    assert not hasattr(PlanCreationService, "_execute_direct_v2_rag_step")

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
    assert "_create_historical_direct_v2_plan" not in source
