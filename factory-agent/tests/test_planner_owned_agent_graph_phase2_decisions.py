from __future__ import annotations

from typing import Any

import pytest

from factory_agent.planning.v2_agent_state import (
    GraphToolCall,
    PlannerDecisionRecord,
    build_initial_planner_owned_agent_graph_state,
)
from factory_agent.planning.v2_contracts import (
    CandidateTool,
    CandidateToolWindow,
    CapabilityNeed,
    HydratedToolCard,
    HydratedToolCards,
)
from factory_agent.planning.v2_planner_decisions import (
    PlannerDecisionSubmission,
    PlannerDecisionValidationError,
    SUPPORTED_PLANNER_DECISION_KINDS,
    record_planner_decision,
    validate_planner_decision,
)
from factory_agent.schemas import ToolInfo


def _tool(
    name: str,
    *,
    endpoint: str,
    tags: list[str],
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

    return ToolInfo(
        name=name,
        description=name.replace("_", " "),
        endpoint=endpoint,
        method="GET",
        input_schema=input_schema,
        output_schema=output_schema,
        path_params=path_params,
        query_params=list(query_params or []),
        param_sources=param_sources,
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
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


def _machine_state():
    state = build_initial_planner_owned_agent_graph_state(
        "Show machine M-LTH-77 status.",
        tools_by_name=_tools(),
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
        reason="phase2_test_need",
    )
    return state, requirement, need


def _state_with_hydrated_machine_window():
    state, requirement, need = _machine_state()
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
                    is_read_only=True,
                    requires_approval=False,
                )
            ],
        )
    )
    return state, requirement, need


def _machine_call(*, call_id: str = "call-machine-status") -> GraphToolCall:
    return GraphToolCall(
        call_id=call_id,
        kind="api_tool",
        tool_name="get__machines_{id}",
        args={"id": "M-LTH-77", "fields": "status"},
        requirement_id="req-001",
    )


def _planner_diagnostics(decision_id: str, **extra: Any) -> dict[str, Any]:
    return {
        **extra,
        "planner_proposer": {
            "proposer_seam": True,
            "adapter": "phase2_test_proposer",
            "decision_id": decision_id,
            "bounded_state_view": True,
            "full_openapi_catalog_visible": False,
        },
    }


def test_phase2_supports_declared_planner_decision_kinds():
    assert SUPPORTED_PLANNER_DECISION_KINDS == (
        "retrieve_tools",
        "choose_tool",
        "execute_tool",
        "execute_parallel_read_batch",
        "request_approval",
        "revise_requirements",
        "request_clarification",
        "finalize",
        "fail",
    )


def test_phase2_rejects_planner_decision_that_changes_locked_constraints():
    state, requirement, _need = _machine_state()
    proposed_ledger = state.requirement_ledger.model_copy(deep=True)
    proposed_ledger.revision = state.requirement_ledger.revision + 1
    proposed_ledger.requirements[0].constraints["machine_id"] = "M-OTHER-77"

    decision = PlannerDecisionRecord(
        decision_id="dec-revise-locked",
        decision_kind="revise_requirements",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        reason="Planner tried to revise the requirement ledger.",
        diagnostics=_planner_diagnostics("dec-revise-locked"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="locked constraint value changed"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=proposed_ledger),
        )


def test_phase2_rejects_choosing_tool_outside_hydrated_candidate_window():
    state, requirement, _need = _state_with_hydrated_machine_window()
    non_candidate_call = GraphToolCall(
        call_id="call-wrong-tool",
        kind="api_tool",
        tool_name="get__jobs_{id}",
        args={"id": "JOB-LOCAL-77"},
        requirement_id=requirement.id,
    )
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-wrong-tool",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        selected_tool_call=non_candidate_call,
        reason="Planner selected a tool outside the hydrated window.",
        diagnostics=_planner_diagnostics("dec-choose-wrong-tool"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="selected tool is not in the hydrated candidate window"):
        validate_planner_decision(state, decision)


def test_phase2_rejects_execute_tool_without_selected_api_or_rag_action():
    state, requirement, _need = _state_with_hydrated_machine_window()
    decision = PlannerDecisionRecord(
        decision_id="dec-execute-without-call",
        decision_kind="execute_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        reason="Planner tried to execute without choosing an action.",
        diagnostics=_planner_diagnostics("dec-execute-without-call"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="requires a selected API/RAG tool call"):
        validate_planner_decision(state, decision)


def test_phase2_rejects_finalize_without_required_evidence():
    state, _requirement, _need = _machine_state()
    decision = PlannerDecisionRecord(
        decision_id="dec-finalize-without-evidence",
        decision_kind="finalize",
        ledger_revision=state.requirement_ledger.revision,
        reason="Planner tried to finalize before evidence was observed.",
        diagnostics=_planner_diagnostics("dec-finalize-without-evidence"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="required_requirement_open"):
        validate_planner_decision(state, decision)


def test_phase2_accepts_valid_retrieve_tools_decision_and_records_it():
    state, requirement, need = _machine_state()
    decision = PlannerDecisionRecord(
        decision_id="dec-retrieve-tools",
        decision_kind="retrieve_tools",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        reason="Need a bounded tool window for the machine status requirement.",
        diagnostics=_planner_diagnostics("dec-retrieve-tools"),
    )

    result = record_planner_decision(state, decision)

    assert result.accepted is True
    assert result.decision_kind == "retrieve_tools"
    assert state.planner_decisions == [decision]
    assert state.candidate_tool_windows == []
    assert state.evidence_ledger.evidence == []


def test_phase2_deterministic_execute_guard_is_accepted_only_when_state_proves_prior_choice():
    state, requirement, _need = _state_with_hydrated_machine_window()
    call = _machine_call()
    guard_decision = PlannerDecisionRecord(
        decision_id="dec-guard-execute",
        decision_kind="execute_tool",
        author="deterministic_guard",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        selected_tool_call=call,
        reason="Execute the already-selected read action.",
    )

    with pytest.raises(PlannerDecisionValidationError, match="prior persisted choose_tool decision"):
        validate_planner_decision(state, guard_decision)

    choose_decision = PlannerDecisionRecord(
        decision_id="dec-choose-machine-tool",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        selected_tool_call=call,
        reason="Planner selected the hydrated machine status reader.",
        diagnostics=_planner_diagnostics("dec-choose-machine-tool"),
    )
    record_planner_decision(state, choose_decision)

    result = validate_planner_decision(state, guard_decision)

    assert result.accepted is True
    assert result.deterministic_guard is True
    assert result.decision_kind == "execute_tool"


def test_phase2_planner_decision_submission_serializes_and_deserializes():
    state, requirement, _need = _state_with_hydrated_machine_window()
    call = _machine_call(call_id="call-machine-status-batch")
    decision = PlannerDecisionRecord(
        decision_id="dec-parallel-read-batch",
        decision_kind="execute_parallel_read_batch",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        selected_tool_calls=[call],
        evidence_refs=[],
        reason="Batch contains only already bounded read actions.",
        diagnostics=_planner_diagnostics("dec-parallel-read-batch", batch_size=1),
    )
    submission = PlannerDecisionSubmission(decision=decision)

    dumped = submission.model_dump(mode="json")
    restored = PlannerDecisionSubmission.model_validate(dumped)

    assert restored == submission
    assert dumped["decision"]["selected_tool_calls"][0]["tool_name"] == "get__machines_{id}"
    assert dumped["decision"]["selected_tool_calls"][0]["kind"] == "api_tool"
