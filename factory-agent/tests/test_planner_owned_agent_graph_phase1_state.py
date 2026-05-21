from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from factory_agent.planning.v2_agent_state import (
    PLANNER_OWNED_AGENT_GRAPH_TRACE_ID,
    GraphToolCall,
    PendingApprovalState,
    PlannerDecisionRecord,
    PlannerOwnedAgentGraphState,
    ResponseDocumentContext,
    build_initial_planner_owned_agent_graph_state,
    validate_graph_state_final_state,
)
from factory_agent.planning.v2_contracts import (
    CandidateTool,
    CandidateToolWindow,
    CapabilityNeed,
    EvidenceLedger,
    EvidenceLedgerEntry,
    ExecutionTrace,
    HydratedToolCard,
    HydratedToolCards,
    RequirementRevisionRecord,
    SatisfactionCheck,
    SatisfactionState,
)
from factory_agent.schemas import ToolInfo


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


def _base_tools() -> dict[str, ToolInfo]:
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
        "get__jobs": _tool(
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
                "job_id": {"type": "string", "x-ai-aliases": ["job id"]},
                "status": {"type": "string"},
                "priority": {"type": "string"},
                "deadline": {"type": "string", "x-ai-aliases": ["due date"]},
            },
            entity="job",
            response_contract="result_collection_v1",
        ),
    }


def _hard_multi_step_query() -> str:
    return (
        "Show machine M-LTH-77 status, then show job JOB-ALPHA-77 status, then list next 2 low priority "
        "jobs sorted by deadline with only job id, status, priority, deadline."
    )


def test_phase1_hard_multi_step_query_builds_graph_state_before_execution():
    state = build_initial_planner_owned_agent_graph_state(_hard_multi_step_query(), tools_by_name=_base_tools())
    ledger = state.requirement_ledger

    assert state.original_query == _hard_multi_step_query()
    assert state.engine_version == "v2"
    assert state.execution_trace.generated_by == PLANNER_OWNED_AGENT_GRAPH_TRACE_ID
    assert state.execution_trace.generated_by != "v2_planner_loop"
    assert state.execution_trace.tool_retrieval.call_count == 0
    assert state.execution_trace.planner.diagnostics["execution_started"] is False
    assert len(ledger.requirements) == 3
    assert [requirement.requirement_type for requirement in ledger.requirements] == [
        "single_entity_status",
        "single_entity_status",
        "filtered_collection",
    ]
    assert ledger.requirements[0].constraints == {"machine_id": "M-LTH-77"}
    assert ledger.requirements[0].locked_constraints == ["machine_id", "requested_fields"]
    assert ledger.requirements[1].constraints == {"job_id": "JOB-ALPHA-77"}
    assert ledger.requirements[2].constraints == {
        "priority": "low",
        "sort_by": "deadline",
        "sort_dir": "asc",
        "limit": 2,
    }
    assert ledger.requirements[2].requested_fields == ["job_id", "status", "priority", "deadline"]
    assert "requested_fields" in ledger.requirements[2].locked_constraints
    assert state.candidate_tool_windows == []
    assert state.hydrated_tool_cards == []
    assert state.evidence_ledger.evidence == []
    assert state.response_document_context.requirement_ids == ["req-001", "req-002", "req-003"]


def test_phase1_empty_evidence_cannot_satisfy_locked_constraints():
    state = build_initial_planner_owned_agent_graph_state(_hard_multi_step_query(), tools_by_name=_base_tools())

    result = validate_graph_state_final_state(state)

    assert result.status == "failed"
    assert state.execution_trace.final_validator_status == "failed"
    assert {issue.issue for issue in result.issues} == {"required_requirement_open"}
    assert [requirement.status for requirement in state.requirement_ledger.requirements] == ["open", "open", "open"]
    assert all(requirement.locked_constraints for requirement in state.requirement_ledger.requirements)


def test_phase1_graph_trace_identity_is_required_but_historical_values_still_parse():
    historical_loop_trace = ExecutionTrace(engine_version="v2", generated_by="v2_planner_loop")
    assert historical_loop_trace.generated_by == "v2_planner_loop"

    state = build_initial_planner_owned_agent_graph_state(_hard_multi_step_query(), tools_by_name=_base_tools())
    with pytest.raises(ValidationError, match="graph trace identity"):
        PlannerOwnedAgentGraphState(
            original_query=state.original_query,
            requirement_ledger=state.requirement_ledger,
            capability_map=state.capability_map,
            execution_trace=historical_loop_trace,
        )


def test_phase1_graph_state_serializes_and_deserializes_without_losing_contract_fields():
    state = build_initial_planner_owned_agent_graph_state(_hard_multi_step_query(), tools_by_name=_base_tools())
    requirement_id = "req-001"
    capability_need = CapabilityNeed(
        requirement_id=requirement_id,
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        known_args={"machine_id": "M-LTH-77"},
        requested_fields=["status"],
    )
    tool_call = GraphToolCall(
        call_id="call-001",
        kind="api_tool",
        tool_name="get__machines_{id}",
        args={"id": "M-LTH-77", "fields": "status"},
        requirement_id=requirement_id,
        decision_id="dec-001",
        candidate_window_id="window-001",
    )
    decision = PlannerDecisionRecord(
        decision_id="dec-001",
        decision_kind="execute_tool",
        requirement_id=requirement_id,
        ledger_revision=1,
        capability_need=capability_need,
        selected_tool_call=tool_call,
        reason="Need current machine status evidence.",
    )
    state.planner_decisions.append(decision)
    state.candidate_tool_windows.append(
        CandidateToolWindow(
            requirement_id=requirement_id,
            capability_need=capability_need,
            candidates=[
                CandidateTool(
                    tool_name="get__machines_{id}",
                    rank=1,
                    source_of_truth="operational_state",
                    actions=["read_one"],
                )
            ],
            backend_used="retrieval",
        )
    )
    state.hydrated_tool_cards.append(
        HydratedToolCards(
            requirement_id=requirement_id,
            cards=[
                HydratedToolCard(
                    tool_name="get__machines_{id}",
                    source_of_truth="operational_state",
                    actions=["read_one"],
                    required_args=["id"],
                    path_params=["id"],
                    query_params=["fields"],
                    supports_fields=True,
                    output_contract="entity_status_v1",
                )
            ],
        )
    )
    state.evidence_ledger = EvidenceLedger(
        evidence=[
            EvidenceLedgerEntry(
                id="ev-001",
                requirement_id=requirement_id,
                source_type="api_tool",
                source_of_truth="operational_state",
                tool_name="get__machines_{id}",
                args={"id": "M-LTH-77", "fields": "status"},
                result_ref="tool-result-001",
                normalized_result={
                    "entity": "machine",
                    "entity_id": "M-LTH-77",
                    "fields": {"status": "running"},
                },
                satisfies=["locked_constraints", "requested_fields"],
            )
        ]
    )
    state.pending_approval = PendingApprovalState(
        status="pending",
        approval_id="approval-001",
        requirement_id=requirement_id,
        decision_id="dec-001",
        ledger_revision=1,
        checkpoint_id="checkpoint-001",
        tool_call=tool_call,
        payload={"summary": "Approval checkpoint is represented separately from evidence."},
    )
    state.satisfaction_state = SatisfactionState(
        requirements=[
            {
                "requirement_id": requirement_id,
                "status": "satisfied",
                "evidence_refs": ["ev-001"],
                "satisfaction_checks": [
                    SatisfactionCheck(
                        check="requested_fields",
                        expected=["status"],
                        actual=["status"],
                        passed=True,
                        evidence_ref="ev-001",
                    )
                ],
            }
        ]
    )
    state.response_document_context = ResponseDocumentContext(
        state="draft",
        document_id="response-doc-001",
        revision=1,
        requirement_ids=["req-001", "req-002", "req-003"],
        evidence_refs=["ev-001"],
        pending_approval_id="approval-001",
        render_contract="response_document_v1",
    )
    state.revision_history.append(
        RequirementRevisionRecord(
            revision=2,
            actor="deterministic_guard",
            change_type="candidate_window_recorded",
            requirement_id=requirement_id,
            reason="State contract serialization proof.",
        )
    )
    state.execution_trace.tool_retrieval.call_count = 1
    state.execution_trace.tool_retrieval.selected_candidate_tool_names = ["get__machines_{id}"]

    dumped = state.model_dump(mode="json")
    restored = PlannerOwnedAgentGraphState.model_validate(dumped)

    assert restored == state
    assert dumped["planner_decisions"][0]["selected_tool_call"]["tool_name"] == "get__machines_{id}"
    assert dumped["candidate_tool_windows"][0]["candidates"][0]["tool_name"] == "get__machines_{id}"
    assert dumped["hydrated_tool_cards"][0]["cards"][0]["output_contract"] == "entity_status_v1"
    assert dumped["evidence_ledger"]["evidence"][0]["source_type"] == "api_tool"
    assert dumped["pending_approval"]["approval_id"] == "approval-001"
    assert dumped["satisfaction_state"]["requirements"][0]["satisfaction_checks"][0]["check"] == "requested_fields"
    assert dumped["response_document_context"]["document_id"] == "response-doc-001"
    assert dumped["revision_history"][1]["change_type"] == "candidate_window_recorded"
    assert dumped["execution_trace"]["generated_by"] == PLANNER_OWNED_AGENT_GRAPH_TRACE_ID
