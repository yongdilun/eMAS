from __future__ import annotations

from typing import Any

import pytest

from factory_agent.planning.v2_agent_state import (
    GraphToolCall,
    PlannerDecisionRecord,
    build_initial_planner_owned_agent_graph_state,
)
from factory_agent.graph.v2_graph_interrupts import _planner_decision_is_active_for_graph_revision
from factory_agent.planning.v2_contracts import (
    CandidateTool,
    CandidateToolWindow,
    CapabilityNeed,
    EvidenceLedgerEntry,
    HydratedToolCard,
    HydratedToolCards,
    RequirementLedgerEntry,
    RequirementRevisionRecord,
    next_child_requirement_id,
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
    method: str = "GET",
    required: list[str] | None = None,
    query_params: list[str] | None = None,
    input_properties: dict[str, dict[str, Any]] | None = None,
    output_properties: dict[str, dict[str, Any]] | None = None,
    entity: str | None = None,
    response_contract: str | None = None,
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

    path_params = [field for field in required or [] if f"{{{field}}}" in endpoint]
    param_sources = {field: "path" for field in path_params}
    for field in query_params or []:
        param_sources[field] = "query"

    read_only = method.upper() == "GET"
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
        requires_approval=(not read_only if requires_approval is None else requires_approval),
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


def _state_with_hydrated_machine_alternates():
    state, requirement, need = _state_with_hydrated_machine_window()
    state.candidate_tool_windows[0].candidates.append(
        CandidateTool(
            tool_name="get__machine_status_{id}",
            rank=2,
            source_of_truth="operational_state",
            actions=["read_one", "read"],
        )
    )
    state.hydrated_tool_cards[0].cards.append(
        HydratedToolCard(
            tool_name="get__machine_status_{id}",
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
    )
    return state, requirement, need


def _job_mutation_tools() -> dict[str, ToolInfo]:
    priority_schema = {"type": "string", "enum": ["low", "medium", "high"]}
    return {
        "get__jobs": _tool(
            "get__jobs",
            endpoint="/jobs",
            tags=["job", "list", "priority"],
            query_params=["priority", "fields"],
            input_properties={
                "priority": priority_schema,
                "fields": {"type": "string"},
            },
            output_properties={"job_id": {"type": "string"}, "priority": priority_schema},
            entity="job",
            response_contract="result_collection_v1",
        ),
        "put__jobs_{id}": _tool(
            "put__jobs_{id}",
            endpoint="/jobs/{id}",
            tags=["job", "update", "priority", "approval"],
            method="PUT",
            required=["id"],
            input_properties={
                "id": {"type": "string", "x-ai-id-field": "job_id", "x-ai-entity": "job"},
                "priority": priority_schema,
            },
            output_properties={"job_id": {"type": "string"}, "priority": priority_schema},
            entity="job",
            response_contract="business_change_v1",
            requires_approval=True,
        ),
    }


def _state_with_mutating_job_window():
    state = build_initial_planner_owned_agent_graph_state(
        "Change medium priority jobs to high priority.",
        tools_by_name=_job_mutation_tools(),
    )
    requirement = state.requirement_ledger.requirements[0]
    need = CapabilityNeed(
        requirement_id=requirement.id,
        source_of_truth="operational_state",
        entity="job",
        action="update",
        constraints=dict(requirement.constraints),
        requested_fields=list(requirement.requested_fields),
        reason="phase2_mutation_test_need",
    )
    state.candidate_tool_windows.append(
        CandidateToolWindow(
            requirement_id=requirement.id,
            capability_need=need,
            candidates=[
                CandidateTool(
                    tool_name="get__jobs",
                    rank=1,
                    source_of_truth="operational_state",
                    actions=["list", "read"],
                ),
                CandidateTool(
                    tool_name="put__jobs_{id}",
                    rank=2,
                    source_of_truth="operational_state",
                    actions=["update"],
                    requires_approval=True,
                ),
            ],
        )
    )
    state.hydrated_tool_cards.append(
        HydratedToolCards(
            requirement_id=requirement.id,
            cards=[
                HydratedToolCard(
                    tool_name="get__jobs",
                    source_of_truth="operational_state",
                    actions=["list", "read"],
                    query_params=["priority", "fields"],
                    supports_filters=True,
                    supports_fields=True,
                    output_contract="result_collection_v1",
                    is_read_only=True,
                    requires_approval=False,
                ),
                HydratedToolCard(
                    tool_name="put__jobs_{id}",
                    source_of_truth="operational_state",
                    actions=["update"],
                    required_args=["id"],
                    path_params=["id"],
                    output_contract="business_change_v1",
                    is_read_only=False,
                    requires_approval=True,
                ),
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


def _alternate_machine_call(*, call_id: str = "call-machine-status-alternate") -> GraphToolCall:
    return GraphToolCall(
        call_id=call_id,
        kind="api_tool",
        tool_name="get__machine_status_{id}",
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


def _active_job_evidence(requirement_id: str) -> EvidenceLedgerEntry:
    return EvidenceLedgerEntry(
        id="ev-api-active-job",
        requirement_id=requirement_id,
        source_type="api_tool",
        source_of_truth="operational_state",
        tool_name="get__machines_{id}",
        normalized_result={
            "entity": "machine",
            "entity_id": "M-LTH-77",
            "fields": {
                "machine_id": "M-LTH-77",
                "status": "stopped",
                "active_job_id": "JOB-CAUSE-17",
            },
        },
    )


def _child_revision_ledger(state, child: RequirementLedgerEntry):
    proposed_ledger = state.requirement_ledger.model_copy(deep=True)
    proposed_ledger.revision = state.requirement_ledger.revision + 1
    proposed_ledger.requirements.append(child)
    proposed_ledger.revision_history.append(
        RequirementRevisionRecord(
            revision=proposed_ledger.revision,
            actor="planner",
            change_type="add_child_requirements",
            requirement_id=child.parent_requirement_id,
            locked_constraints_preserved=True,
            details={
                "parent_requirement_id": child.parent_requirement_id,
                "added_child_requirement_ids": [child.id],
                "derived_from_evidence_refs": list(child.derived_from_evidence_refs),
                "derived_from_missing_reasons": list(child.derived_from_missing_reasons),
                "locked_constraints_preserved": True,
            },
        )
    )
    return proposed_ledger


def _revise_decision(decision_id: str, requirement_id: str) -> PlannerDecisionRecord:
    return PlannerDecisionRecord(
        decision_id=decision_id,
        decision_kind="revise_requirements",
        requirement_id=requirement_id,
        ledger_revision=1,
        reason="Planner proposed a bounded requirement expansion.",
        diagnostics=_planner_diagnostics(decision_id),
    )


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


def test_requirement_expansion_rejects_child_addition_without_evidence_or_missing_reason_justification():
    state, requirement, _need = _machine_state()
    child = RequirementLedgerEntry(
        id=next_child_requirement_id(requirement.id, [item.id for item in state.requirement_ledger.requirements]),
        goal="Read active job status",
        requirement_type="single_entity_status",
        entity="job",
        intent_operation="report_status",
        source_of_truth="operational_state",
        constraints={"job_id": "JOB-UNSUPPORTED"},
        requested_fields=["status"],
        locked_constraints=["job_id", "requested_fields"],
        parent_requirement_id=requirement.id,
        expansion_reason="Planner proposed a follow-up without grounded evidence.",
    )
    proposed_ledger = state.requirement_ledger.model_copy(deep=True)
    proposed_ledger.revision = state.requirement_ledger.revision + 1
    proposed_ledger.requirements.append(child)
    proposed_ledger.revision_history.append(
        RequirementRevisionRecord(
            revision=proposed_ledger.revision,
            actor="planner",
            change_type="add_child_requirements",
            requirement_id=requirement.id,
            locked_constraints_preserved=True,
            details={
                "parent_requirement_id": requirement.id,
                "added_child_requirement_ids": [child.id],
            },
        )
    )
    decision = PlannerDecisionRecord(
        decision_id="dec-child-without-justification",
        decision_kind="revise_requirements",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        reason="Planner tried to expand the requirement ledger.",
        diagnostics=_planner_diagnostics("dec-child-without-justification"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="child requirement expansion requires evidence or missing-evidence justification"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=proposed_ledger),
        )


def test_requirement_expansion_rejects_child_addition_from_invented_missing_evidence_reason():
    state, requirement, _need = _machine_state()
    child = RequirementLedgerEntry(
        id=next_child_requirement_id(requirement.id, [item.id for item in state.requirement_ledger.requirements]),
        goal="Read active job JOB-CAUSE-17 status",
        requirement_type="single_entity_status",
        entity="job",
        intent_operation="report_status",
        source_of_truth="operational_state",
        constraints={"job_id": "JOB-CAUSE-17"},
        requested_fields=["status"],
        locked_constraints=["job_id", "requested_fields"],
        parent_requirement_id=requirement.id,
        expansion_reason="Planner invented an unobserved missing-evidence gap.",
        derived_from_missing_reasons=[
            {
                "requirement_id": requirement.id,
                "status": "open",
                "reason": "missing related job evidence",
                "job_id": "JOB-CAUSE-17",
            }
        ],
    )
    decision = _revise_decision("dec-child-invented-missing-reason", requirement.id)

    with pytest.raises(PlannerDecisionValidationError, match="missing-evidence reason is not current"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=_child_revision_ledger(state, child)),
        )


def test_requirement_expansion_accepts_current_grounded_missing_evidence_reason():
    state, requirement, _need = _machine_state()
    missing_reason = {
        "requirement_id": requirement.id,
        "status": "open",
        "reason": "missing related job evidence",
        "retriable": True,
        "constraints": {"job_id": "JOB-CAUSE-17"},
        "evidence_refs": [],
        "failed_checks": [],
    }
    state.execution_trace.diagnostics["satisfaction"] = {
        "status": "applied",
        "missing_evidence_reasons": [missing_reason],
    }
    child = RequirementLedgerEntry(
        id=next_child_requirement_id(requirement.id, [item.id for item in state.requirement_ledger.requirements]),
        goal="Read active job JOB-CAUSE-17 status",
        requirement_type="single_entity_status",
        entity="job",
        intent_operation="report_status",
        source_of_truth="operational_state",
        constraints={"job_id": "JOB-CAUSE-17"},
        requested_fields=["status"],
        locked_constraints=["job_id", "requested_fields"],
        parent_requirement_id=requirement.id,
        expansion_reason="Current diagnostics exposed a child evidence gap.",
        derived_from_missing_reasons=[missing_reason],
    )
    decision = _revise_decision("dec-child-grounded-missing-reason", requirement.id)

    result = validate_planner_decision(
        state,
        PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=_child_revision_ledger(state, child)),
    )

    assert result.accepted is True


def test_requirement_expansion_rejects_current_missing_evidence_reason_without_child_support():
    state, requirement, _need = _machine_state()
    missing_reason = {
        "requirement_id": requirement.id,
        "status": "open",
        "reason": "missing unrelated operator evidence",
        "retriable": True,
        "constraints": {"operator_id": "OP-9"},
        "evidence_refs": [],
        "failed_checks": [],
    }
    state.execution_trace.diagnostics["satisfaction"] = {
        "status": "applied",
        "missing_evidence_reasons": [missing_reason],
    }
    child = RequirementLedgerEntry(
        id=next_child_requirement_id(requirement.id, [item.id for item in state.requirement_ledger.requirements]),
        goal="Read active job JOB-CAUSE-17 status",
        requirement_type="single_entity_status",
        entity="job",
        intent_operation="report_status",
        source_of_truth="operational_state",
        constraints={"job_id": "JOB-CAUSE-17"},
        requested_fields=["status"],
        locked_constraints=["job_id", "requested_fields"],
        parent_requirement_id=requirement.id,
        expansion_reason="Current diagnostics did not expose this child evidence gap.",
        derived_from_missing_reasons=[missing_reason],
    )
    decision = _revise_decision("dec-child-unsupported-missing-reason", requirement.id)

    with pytest.raises(PlannerDecisionValidationError, match="not supported by current evidence gap"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=_child_revision_ledger(state, child)),
        )


def test_requirement_expansion_accepts_valid_child_requirement_addition():
    state, requirement, _need = _machine_state()
    state.evidence_ledger.evidence.append(_active_job_evidence(requirement.id))
    child = RequirementLedgerEntry(
        id=next_child_requirement_id(requirement.id, [item.id for item in state.requirement_ledger.requirements]),
        goal="Read active job JOB-CAUSE-17 status",
        requirement_type="single_entity_status",
        entity="job",
        intent_operation="report_status",
        source_of_truth="operational_state",
        constraints={"job_id": "JOB-CAUSE-17"},
        requested_fields=["status"],
        locked_constraints=["job_id", "requested_fields"],
        parent_requirement_id=requirement.id,
        expansion_reason="Machine evidence exposed an active job id.",
        derived_from_evidence_refs=["ev-api-active-job"],
        depends_on=["ev-api-active-job"],
    )
    decision = _revise_decision("dec-valid-child", requirement.id)

    result = validate_planner_decision(
        state,
        PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=_child_revision_ledger(state, child)),
    )

    assert result.accepted is True


def test_requirement_expansion_rejects_child_addition_from_stale_parent_evidence():
    state, requirement, _need = _machine_state()
    stale_evidence = _active_job_evidence(requirement.id)
    stale_evidence.diagnostic_metadata.update(
        {
            "active_revision_satisfaction": False,
            "stale_after_graph_replan": True,
            "superseded_reason": "replan_spine_retry",
        }
    )
    state.evidence_ledger.evidence.append(stale_evidence)
    child = RequirementLedgerEntry(
        id=next_child_requirement_id(requirement.id, [item.id for item in state.requirement_ledger.requirements]),
        goal="Read active job JOB-CAUSE-17 status",
        requirement_type="single_entity_status",
        entity="job",
        intent_operation="report_status",
        source_of_truth="operational_state",
        constraints={"job_id": "JOB-CAUSE-17"},
        requested_fields=["status"],
        locked_constraints=["job_id", "requested_fields"],
        parent_requirement_id=requirement.id,
        expansion_reason="Planner tried to branch from stale parent evidence.",
        derived_from_evidence_refs=[stale_evidence.id],
        depends_on=[stale_evidence.id],
    )
    decision = _revise_decision("dec-child-stale-parent-evidence", requirement.id)

    with pytest.raises(PlannerDecisionValidationError, match="child requirement evidence is not active"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=_child_revision_ledger(state, child)),
        )


def test_requirement_expansion_rejects_child_addition_with_missing_parent():
    state, requirement, _need = _machine_state()
    state.evidence_ledger.evidence.append(_active_job_evidence(requirement.id))
    child = RequirementLedgerEntry(
        id="req-missing.a",
        goal="Read active job JOB-CAUSE-17 status",
        requirement_type="single_entity_status",
        entity="job",
        intent_operation="report_status",
        source_of_truth="operational_state",
        constraints={"job_id": "JOB-CAUSE-17"},
        requested_fields=["status"],
        locked_constraints=["job_id"],
        parent_requirement_id="req-missing",
        expansion_reason="Machine evidence exposed an active job id.",
        derived_from_evidence_refs=["ev-api-active-job"],
    )
    decision = _revise_decision("dec-missing-parent", requirement.id)

    with pytest.raises(PlannerDecisionValidationError, match="child requirement parent is missing"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=_child_revision_ledger(state, child)),
        )


def test_requirement_expansion_rejects_child_mutation_that_bypasses_approval_safety():
    state, requirement, _need = _machine_state()
    state.evidence_ledger.evidence.append(_active_job_evidence(requirement.id))
    child = RequirementLedgerEntry(
        id=next_child_requirement_id(requirement.id, [item.id for item in state.requirement_ledger.requirements]),
        goal="Update active job JOB-CAUSE-17 priority",
        requirement_type="mutation_request",
        entity="job",
        intent_operation="stage_mutation",
        source_of_truth="operational_state",
        constraints={"job_id": "JOB-CAUSE-17"},
        requested_fields=[],
        locked_constraints=["job_id"],
        parent_requirement_id=requirement.id,
        expansion_reason="Machine evidence exposed an active job id.",
        derived_from_evidence_refs=["ev-api-active-job"],
    )
    decision = _revise_decision("dec-child-mutation-no-approval", requirement.id)

    with pytest.raises(PlannerDecisionValidationError, match="child mutation requirements must remain approval-gated"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=_child_revision_ledger(state, child)),
        )


def test_requirement_expansion_rejects_child_that_changes_parent_locked_value():
    state, requirement, _need = _machine_state()
    state.evidence_ledger.evidence.append(_active_job_evidence(requirement.id))
    child = RequirementLedgerEntry(
        id=next_child_requirement_id(requirement.id, [item.id for item in state.requirement_ledger.requirements]),
        goal="Read a different machine status",
        requirement_type="single_entity_status",
        entity="machine",
        intent_operation="report_status",
        source_of_truth="operational_state",
        constraints={"machine_id": "M-OTHER-77"},
        requested_fields=["status"],
        locked_constraints=["machine_id", "requested_fields"],
        parent_requirement_id=requirement.id,
        expansion_reason="Planner tried to branch to a conflicting machine.",
        derived_from_evidence_refs=["ev-api-active-job"],
    )
    decision = _revise_decision("dec-child-locked-conflict", requirement.id)

    with pytest.raises(PlannerDecisionValidationError, match="child requirement contradicts parent locked constraint"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, proposed_requirement_ledger=_child_revision_ledger(state, child)),
        )


def test_requirement_expansion_rejects_selected_tool_call_for_terminal_requirement():
    state, requirement, _need = _state_with_hydrated_machine_window()
    requirement.status = "satisfied"
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-terminal-requirement",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        selected_tool_call=_machine_call(),
        reason="Planner tried to execute against a terminal requirement.",
        diagnostics=_planner_diagnostics("dec-choose-terminal-requirement"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="selected tool call targets non-open requirement"):
        validate_planner_decision(state, decision)


def test_requirement_expansion_rejects_old_revision_selected_tool_call_after_expansion():
    state, requirement, _need = _state_with_hydrated_machine_window()
    old_call = _machine_call()
    old_choose = PlannerDecisionRecord(
        decision_id="dec-old-choose",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        selected_tool_call=old_call,
        reason="Planner selected the original machine reader.",
        diagnostics=_planner_diagnostics("dec-old-choose"),
    )
    record_planner_decision(state, PlannerDecisionSubmission(decision=old_choose, candidate_tool_calls=[old_call]))
    state.requirement_ledger.revision += 1
    old_call = old_call.model_copy(update={"decision_id": old_choose.decision_id}, deep=True)
    decision = PlannerDecisionRecord(
        decision_id="dec-reuse-old-call",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        selected_tool_call=old_call,
        reason="Planner tried to reuse a selected call from a previous ledger revision.",
        diagnostics=_planner_diagnostics("dec-reuse-old-call"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="selected tool call comes from a previous ledger revision"):
        validate_planner_decision(state, decision)


def test_requirement_expansion_rejects_provenance_less_selected_tool_call_with_old_args():
    state, requirement, need = _state_with_hydrated_machine_window()
    current_call = _machine_call(call_id="call-current-candidate")
    old_call = _machine_call(call_id="call-old-copied-without-decision").model_copy(
        update={"args": {"id": "M-LTH-77", "fields": "temperature"}},
        deep=True,
    )
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-provenance-less-old-call",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=old_call,
        reason="Planner copied an old selected call without carrying decision provenance.",
        diagnostics=_planner_diagnostics("dec-choose-provenance-less-old-call"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="does not match current candidate tool calls"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, candidate_tool_calls=[current_call]),
        )


def test_requirement_expansion_rejects_provenance_less_selected_tool_calls_batch_with_old_args():
    state, requirement, need = _state_with_hydrated_machine_window()
    current_call = _machine_call(call_id="call-current-candidate")
    old_call = _machine_call(call_id="call-old-batch-copied-without-decision").model_copy(
        update={"args": {"id": "M-LTH-77", "fields": "temperature"}},
        deep=True,
    )
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-provenance-less-old-batch",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_calls=[old_call, current_call],
        reason="Planner batched an old selected call with the current candidate.",
        diagnostics=_planner_diagnostics("dec-choose-provenance-less-old-batch", batch_size=2),
    )

    with pytest.raises(PlannerDecisionValidationError, match="does not match current candidate tool calls"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, candidate_tool_calls=[current_call]),
        )


def test_requirement_expansion_rejects_selected_tool_call_args_that_contradict_locked_identity():
    state, requirement, need = _state_with_hydrated_machine_window()
    wrong_identity_call = _machine_call(call_id="call-wrong-locked-identity").model_copy(
        update={"args": {"id": "M-OTHER-77", "fields": "status"}},
        deep=True,
    )
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-locked-identity-conflict",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=wrong_identity_call,
        reason="Planner selected args that contradict the locked machine identity.",
        diagnostics=_planner_diagnostics("dec-choose-locked-identity-conflict"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="contradict locked identity constraint"):
        validate_planner_decision(state, decision)


def test_requirement_expansion_rejects_unbounded_collection_tool_for_locked_identity_read():
    state = build_initial_planner_owned_agent_graph_state(
        "Show updated jobs.",
        tools_by_name=_tools(),
    )
    requirement = RequirementLedgerEntry(
        id="req-002",
        goal="Show the updated jobs.",
        requirement_type="multi_entity_status",
        entity="job",
        intent_operation="report_multi_status",
        source_of_truth="operational_state",
        constraints={
            "job_id": ["JOB-SEED-005", "JOB-SEED-009"],
            "depends_on_result_binding": "updated_jobs",
            "result_binding_source_requirement": "req-001",
            "result_binding_field": "affected_entity_ids",
        },
        requested_fields=["job_id", "priority", "status"],
        locked_constraints=["job_id", "requested_fields"],
    )
    state.requirement_ledger.requirements = [requirement]
    need = CapabilityNeed(
        requirement_id=requirement.id,
        source_of_truth="operational_state",
        entity="job",
        action="read_many",
        constraints=dict(requirement.constraints),
        requested_fields=list(requirement.requested_fields),
        reason="phase4_locked_updated_jobs_read",
    )
    state.candidate_tool_windows.append(
        CandidateToolWindow(
            requirement_id=requirement.id,
            capability_need=need,
            candidates=[
                CandidateTool(
                    tool_name="get__jobs",
                    rank=1,
                    source_of_truth="operational_state",
                    actions=["list", "read_many", "read"],
                )
            ],
        )
    )
    state.hydrated_tool_cards.append(
        HydratedToolCards(
            requirement_id=requirement.id,
            cards=[
                HydratedToolCard(
                    tool_name="get__jobs",
                    source_of_truth="operational_state",
                    actions=["list", "read_many", "read"],
                    query_params=["priority", "fields"],
                    supports_filters=True,
                    supports_fields=True,
                    output_contract="result_collection_v1",
                    is_read_only=True,
                    requires_approval=False,
                )
            ],
        )
    )
    broad_collection_call = GraphToolCall(
        call_id="call-broad-updated-jobs",
        kind="api_tool",
        tool_name="get__jobs",
        args={},
        requirement_id=requirement.id,
    )
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-broad-updated-jobs",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=broad_collection_call,
        reason="Planner selected an unbounded collection read for a locked updated-jobs requirement.",
        diagnostics=_planner_diagnostics("dec-choose-broad-updated-jobs"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="cannot satisfy locked identity constraint"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, candidate_tool_calls=[broad_collection_call]),
        )


def test_requirement_expansion_accepts_collection_tool_with_locked_identity_query_filter():
    state = build_initial_planner_owned_agent_graph_state(
        "Show updated jobs.",
        tools_by_name=_tools(),
    )
    requirement = RequirementLedgerEntry(
        id="req-002",
        goal="Show the updated jobs.",
        requirement_type="multi_entity_status",
        entity="job",
        intent_operation="report_multi_status",
        source_of_truth="operational_state",
        constraints={
            "job_id": ["JOB-SEED-005", "JOB-SEED-009"],
            "depends_on_result_binding": "updated_jobs",
            "result_binding_source_requirement": "req-001",
            "result_binding_field": "affected_entity_ids",
        },
        requested_fields=["job_id", "priority", "status"],
        locked_constraints=["job_id", "requested_fields"],
    )
    state.requirement_ledger.requirements = [requirement]
    need = CapabilityNeed(
        requirement_id=requirement.id,
        source_of_truth="operational_state",
        entity="job",
        action="read_many",
        constraints=dict(requirement.constraints),
        requested_fields=list(requirement.requested_fields),
        reason="phase4_locked_updated_jobs_read",
    )
    state.candidate_tool_windows.append(
        CandidateToolWindow(
            requirement_id=requirement.id,
            capability_need=need,
            candidates=[
                CandidateTool(
                    tool_name="get__jobs",
                    rank=1,
                    source_of_truth="operational_state",
                    actions=["list", "read_many", "read"],
                )
            ],
        )
    )
    state.hydrated_tool_cards.append(
        HydratedToolCards(
            requirement_id=requirement.id,
            cards=[
                HydratedToolCard(
                    tool_name="get__jobs",
                    source_of_truth="operational_state",
                    actions=["list", "read_many", "read"],
                    query_params=["job_id", "fields"],
                    supports_filters=True,
                    supports_fields=True,
                    output_contract="result_collection_v1",
                    is_read_only=True,
                    requires_approval=False,
                )
            ],
        )
    )
    bounded_collection_call = GraphToolCall(
        call_id="call-bounded-updated-jobs",
        kind="api_tool",
        tool_name="get__jobs",
        args={"job_id": ["JOB-SEED-005", "JOB-SEED-009"]},
        requirement_id=requirement.id,
    )
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-bounded-updated-jobs",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=bounded_collection_call,
        reason="Planner selected a bounded collection read for a locked updated-jobs requirement.",
        diagnostics=_planner_diagnostics("dec-choose-bounded-updated-jobs"),
    )

    result = validate_planner_decision(
        state,
        PlannerDecisionSubmission(decision=decision, candidate_tool_calls=[bounded_collection_call]),
    )

    assert result.accepted is True


def test_requirement_expansion_stale_planner_decisions_are_inactive_in_shared_graph_filter():
    state, requirement, need = _state_with_hydrated_machine_window()
    call = _machine_call()
    decisions = [
        PlannerDecisionRecord(
            decision_id="dec-stale-retrieve",
            decision_kind="retrieve_tools",
            requirement_id=requirement.id,
            ledger_revision=state.requirement_ledger.revision,
            capability_need=need,
            reason="Stale retrieve decision.",
            diagnostics=_planner_diagnostics("dec-stale-retrieve"),
        ),
        PlannerDecisionRecord(
            decision_id="dec-stale-choose",
            decision_kind="choose_tool",
            requirement_id=requirement.id,
            ledger_revision=state.requirement_ledger.revision,
            capability_need=need,
            selected_tool_call=call,
            reason="Stale choose decision.",
            diagnostics=_planner_diagnostics("dec-stale-choose"),
        ),
        PlannerDecisionRecord(
            decision_id="dec-stale-execute",
            decision_kind="execute_tool",
            author="deterministic_guard",
            requirement_id=requirement.id,
            ledger_revision=state.requirement_ledger.revision,
            capability_need=need,
            selected_tool_call=call,
            reason="Stale execute decision.",
        ),
        PlannerDecisionRecord(
            decision_id="dec-stale-finalize",
            decision_kind="finalize",
            author="deterministic_guard",
            ledger_revision=state.requirement_ledger.revision,
            reason="Stale finalize decision.",
        ),
    ]
    active_decision = PlannerDecisionRecord(
        decision_id="dec-active-retrieve",
        decision_kind="retrieve_tools",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        reason="Current retrieve decision.",
        diagnostics=_planner_diagnostics("dec-active-retrieve"),
    )
    state.execution_trace.diagnostics["requirement_expansion"] = {
        "stale_planner_decision_ids": [decision.decision_id for decision in decisions],
    }

    assert [
        _planner_decision_is_active_for_graph_revision(state, decision)
        for decision in decisions
    ] == [False, False, False, False]
    assert _planner_decision_is_active_for_graph_revision(state, active_decision) is True


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


def test_replan_spine_decision_gate_rejects_failed_selected_tool_call_excluded_by_memory():
    state, requirement, need = _state_with_hydrated_machine_alternates()
    failed_call = _machine_call()
    alternate_call = _alternate_machine_call()
    state.execution_trace.diagnostics["replan_spine"] = {
        "failed_tool_calls": [
            {
                "tool_name": failed_call.tool_name,
                "args": dict(failed_call.args),
                "requirement_id": requirement.id,
                "evidence_ref": "evidence-failed-primary",
                "reason": "tool_error",
                "attempt": 1,
            }
        ]
    }
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-stale-failed-tool",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=failed_call,
        reason="Planner repeated the full failed tool call after an alternate was retrieved.",
        diagnostics=_planner_diagnostics("dec-choose-stale-failed-tool"),
    )

    with pytest.raises(PlannerDecisionValidationError, match="failed-tool memory"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, candidate_tool_calls=[alternate_call]),
        )


def test_replan_spine_decision_gate_allows_bounded_retry_for_transient_timeout_memory():
    state, requirement, need = _state_with_hydrated_machine_alternates()
    failed_call = _machine_call()
    alternate_call = _alternate_machine_call()
    state.execution_trace.diagnostics["replan_spine"] = {
        "failed_tool_calls": [
            {
                "tool_name": failed_call.tool_name,
                "args": dict(failed_call.args),
                "requirement_id": requirement.id,
                "evidence_ref": "evidence-timeout-primary",
                "reason": "tool_error",
                "error_type": "timeout",
                "attempt": 1,
            }
        ]
    }
    decision = PlannerDecisionRecord(
        decision_id="dec-retry-transient-timeout-tool",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=failed_call,
        reason="Planner retried the same read after a structured transient timeout.",
        diagnostics=_planner_diagnostics("dec-retry-transient-timeout-tool"),
    )

    assert (
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, candidate_tool_calls=[failed_call, alternate_call]),
        ).accepted
        is True
    )


def test_replan_spine_decision_gate_rejects_failed_selected_tool_calls_batch_excluded_by_memory():
    state, requirement, need = _state_with_hydrated_machine_alternates()
    failed_call = _machine_call(call_id="call-failed-primary")
    alternate_call = _alternate_machine_call(call_id="call-alternate-status")
    state.execution_trace.diagnostics["replan_spine"] = {
        "failed_tool_calls": [
            {
                "tool_name": failed_call.tool_name,
                "args": dict(failed_call.args),
                "requirement_id": requirement.id,
                "evidence_ref": "evidence-failed-primary",
                "reason": "tool_error",
                "attempt": 1,
            }
        ]
    }
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-stale-failed-batch",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_calls=[failed_call, alternate_call],
        reason="Planner batched a stale failed read with the viable alternate.",
        diagnostics=_planner_diagnostics("dec-choose-stale-failed-batch", batch_size=2),
    )

    with pytest.raises(PlannerDecisionValidationError, match="failed-tool memory"):
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, candidate_tool_calls=[alternate_call]),
        )


def test_replan_spine_decision_gate_accepts_non_failed_alternate_after_failed_memory():
    state, requirement, need = _state_with_hydrated_machine_alternates()
    failed_call = _machine_call()
    alternate_call = _alternate_machine_call()
    state.execution_trace.diagnostics["replan_spine"] = {
        "failed_tool_calls": [
            {
                "tool_name": failed_call.tool_name,
                "args": dict(failed_call.args),
                "requirement_id": requirement.id,
                "evidence_ref": "evidence-failed-primary",
                "reason": "tool_error",
                "attempt": 1,
            }
        ]
    }
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-non-failed-alternate",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=alternate_call,
        reason="Planner recovered by selecting the non-failed alternate read.",
        diagnostics=_planner_diagnostics("dec-choose-non-failed-alternate"),
    )

    assert (
        validate_planner_decision(
            state,
            PlannerDecisionSubmission(decision=decision, candidate_tool_calls=[alternate_call]),
        ).accepted
        is True
    )


def test_phase2_rejects_read_only_choice_for_mutation_requirement():
    state, requirement, need = _state_with_mutating_job_window()
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-read-for-mutation",
        decision_kind="choose_tool",
        requirement_id=requirement.id,
        ledger_revision=state.requirement_ledger.revision,
        capability_need=need,
        selected_tool_call=GraphToolCall(
            call_id="call-read",
            kind="api_tool",
            tool_name="get__jobs",
            args={"priority": "medium"},
            requirement_id=requirement.id,
            candidate_window_id="window-jobs",
        ),
        reason="Planner selected the preview read as if it could satisfy a mutation.",
        diagnostics=_planner_diagnostics("dec-choose-read-for-mutation"),
    )

    with pytest.raises(
        PlannerDecisionValidationError,
        match="approval-required mutation choose_tool requires a write or approval-gated tool",
    ):
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
    record_planner_decision(state, PlannerDecisionSubmission(decision=choose_decision, candidate_tool_calls=[call]))

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
