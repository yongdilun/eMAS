from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from factory_agent.planning.v2_contracts import (
    AgendaPatch,
    CapabilityAction,
    CapabilityMap,
    CapabilityMapEntry,
    CapabilityNeed,
    CandidateTool,
    CandidateToolWindow,
    EvidenceCitation,
    EvidenceLedger,
    EvidenceLedgerEntry,
    ExecutionDetectors,
    ExecutionTrace,
    FieldAlias,
    FieldAliases,
    HydratedToolCard,
    HydratedToolCards,
    IntentOperation,
    LegacyRagRouteMetadata,
    LegacyRagShortcutTrace,
    PlannerOwnedLoopV2State,
    PlannerTrace,
    RequirementLedger,
    RequirementLedgerEntry,
    RequirementRevisionRecord,
    RequirementSketch,
    RequirementSketchItem,
    RequirementStatus,
    RequirementType,
    SatisfactionCheck,
    SatisfactionState,
    ToolRetrievalSlice,
    ToolRetrievalTrace,
    ToolSelectorAdapterRequest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / "factory-agent" / "factory_agent"


def _status_requirement(**overrides: object) -> RequirementLedgerEntry:
    data: dict[str, object] = {
        "id": "req-machine-status",
        "goal": "Report machine status",
        "requirement_type": "single_entity_status",
        "entity": "machine",
        "intent_operation": "report_status",
        "source_of_truth": "operational_state",
        "constraints": {"machine_id": "machine-1"},
        "requested_fields": ["status"],
        "locked_constraints": ["machine_id", "requested_fields"],
        "status": "open",
    }
    data.update(overrides)
    return RequirementLedgerEntry.model_validate(data)


def test_phase2_state_contracts_serialize_and_round_trip_from_json_dump():
    requirement = _status_requirement()
    capability_need = CapabilityNeed(
        requirement_id=requirement.id,
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        known_args={"machine_id": "machine-1"},
        requested_fields=["status"],
    )
    adapter_request = ToolSelectorAdapterRequest(
        requirement_id=requirement.id,
        entity="machine",
        actions=["read_one"],
        safety="read_only",
        endpoint_shape="single",
        source_of_truth="operational_state",
        constraints={"machine_id": "machine-1"},
        requested_fields=["status"],
        retrieval_phrase="machine read status fields status",
        capability_need=capability_need,
    )
    state = PlannerOwnedLoopV2State(
        engine_version="legacy",
        execution_trace=ExecutionTrace(
            engine_version="legacy",
            generated_by="legacy_rag_route",
            planner=PlannerTrace(call_count=0),
            tool_retrieval=ToolRetrievalTrace(call_count=0),
            detectors=ExecutionDetectors(
                legacy_rag_shortcut=LegacyRagShortcutTrace(
                    used=True,
                    route="rag.procedure",
                    source_function="_answer_knowledge_question_as_plan",
                    policy_id="legacy-rag-shortcut",
                    persisted_empty_plan=True,
                )
            ),
        ),
        requirement_sketch=RequirementSketch(
            user_goal="Report machine status",
            requirements=[
                RequirementSketchItem(
                    id=requirement.id,
                    goal=requirement.goal,
                    requirement_type="single_entity_status",
                    entity="machine",
                    intent_operation="report_status",
                    source_of_truth="operational_state",
                    constraints={"machine_id": "machine-1"},
                    requested_fields=["status"],
                    locked_constraints=["machine_id", "requested_fields"],
                )
            ],
            field_aliases=FieldAliases(
                aliases=[FieldAlias(canonical_field="status", user_terms=["state"], entity="machine")]
            ),
            tool_retrieval_slices=[
                ToolRetrievalSlice(
                    slice_id="slice-1",
                    text="machine status",
                    source_of_truth_hint="operational_state",
                    entity="machine",
                    actions=["read_one"],
                    requested_fields=["status"],
                )
            ],
        ),
        requirement_ledger=RequirementLedger(
            user_goal="Report machine status",
            requirements=[requirement],
            revision_history=[
                RequirementRevisionRecord(
                    revision=1,
                    actor="deterministic_guard",
                    change_type="initial_ledger",
                    requirement_id=requirement.id,
                )
            ],
        ),
        capability_map=CapabilityMap(
            capabilities=[
                CapabilityMapEntry(
                    capability_id="machine.read.status",
                    source_of_truth="operational_state",
                    entity="machine",
                    actions=["read_one"],
                    supports=["fields"],
                )
            ]
        ),
        evidence_ledger=EvidenceLedger(
            evidence=[
                EvidenceLedgerEntry(
                    id="ev-machine-status",
                    requirement_id=requirement.id,
                    source_type="api_tool",
                    source_of_truth="operational_state",
                    tool_name="get__machines_{id}",
                    args={"id": "machine-1", "fields": "status"},
                    result_ref="tool-result-1",
                    normalized_result={
                        "entity": "machine",
                        "entity_id": "machine-1",
                        "fields": {"status": "running"},
                    },
                    satisfies=["locked_constraints", "requested_fields"],
                )
            ]
        ),
        satisfaction_state=SatisfactionState(
            requirements=[
                {
                    "requirement_id": requirement.id,
                    "status": "satisfied",
                    "evidence_refs": ["ev-machine-status"],
                    "satisfaction_checks": [
                        SatisfactionCheck(
                            check="requested_fields",
                            expected=["status"],
                            actual=["status"],
                            passed=True,
                            evidence_ref="ev-machine-status",
                        )
                    ],
                }
            ]
        ),
        candidate_tool_windows=[
            CandidateToolWindow(
                requirement_id=requirement.id,
                capability_need=capability_need,
                adapter_request=adapter_request,
                candidates=[
                    CandidateTool(
                        tool_name="get__machines_{id}",
                        rank=1,
                        score=0.98,
                        source_of_truth="operational_state",
                        actions=["read_one"],
                    )
                ],
                backend_used="retrieval",
            )
        ],
        hydrated_tool_cards=[
            HydratedToolCards(
                requirement_id=requirement.id,
                cards=[
                    HydratedToolCard(
                        tool_name="get__machines_{id}",
                        source_of_truth="operational_state",
                        actions=["read_one"],
                        input_schema={"type": "object"},
                        output_schema={"type": "object"},
                        required_args=["id"],
                        path_params=["id"],
                        supports_fields=True,
                        output_contract="entity_status_v1",
                    )
                ],
            )
        ],
    )

    dumped = state.model_dump(mode="json")
    round_tripped = PlannerOwnedLoopV2State.model_validate(dumped)

    assert round_tripped == state
    assert dumped["engine_version"] == "legacy"
    assert dumped["execution_trace"]["generated_by"] == "legacy_rag_route"
    assert dumped["execution_trace"]["planner"]["call_count"] == 0
    assert dumped["execution_trace"]["tool_retrieval"]["call_count"] == 0
    assert dumped["execution_trace"]["detectors"]["legacy_rag_shortcut"]["used"] is True


def test_phase2_requirement_types_and_statuses_are_fixed_literals():
    assert set(get_args(RequirementType)) == {
        "single_entity_status",
        "multi_entity_status",
        "filtered_collection",
        "document_answer",
        "mutation_request",
        "approval_request",
        "clarification_request",
        "safety_refusal",
        "diagnostic",
    }
    assert set(get_args(RequirementStatus)) == {
        "open",
        "blocked",
        "satisfied",
        "skipped",
        "impossible",
        "superseded",
        "failed",
    }

    with pytest.raises(ValidationError):
        _status_requirement(requirement_type="read_one")

    with pytest.raises(ValidationError):
        _status_requirement(status="completed")


def test_phase2_requirement_vocabulary_stays_separate_from_capability_and_tool_actions():
    assert set(get_args(RequirementType)).isdisjoint(set(get_args(CapabilityAction)))
    assert set(get_args(IntentOperation)).isdisjoint(set(get_args(CapabilityAction)))

    requirement = _status_requirement(requirement_type="single_entity_status")
    capability_need = CapabilityNeed(
        requirement_id=requirement.id,
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
    )
    adapter_request = ToolSelectorAdapterRequest(
        requirement_id=requirement.id,
        entity="machine",
        actions=["read_one"],
        endpoint_shape="single",
        source_of_truth="operational_state",
    )
    candidate = CandidateTool(tool_name="get__machines_{id}", rank=1, actions=["read_one"])

    assert requirement.requirement_type == "single_entity_status"
    assert capability_need.action == "read_one"
    assert adapter_request.actions == ["read_one"]
    assert candidate.tool_name == "get__machines_{id}"

    with pytest.raises(ValidationError):
        CapabilityNeed(source_of_truth="operational_state", entity="machine", action="single_entity_status")

    with pytest.raises(ValidationError):
        ToolSelectorAdapterRequest(
            requirement_id=requirement.id,
            entity="machine",
            actions=["single_entity_status"],
        )

def test_phase2_agenda_patch_contract_preserves_locked_constraints():
    original = _status_requirement()
    revised = _status_requirement(goal="Report current machine status")

    patch = AgendaPatch(
        patch_id="patch-1",
        operation="revise_requirement",
        reason="Clarify wording without weakening user constraints",
        requirement_id=original.id,
        locked_constraints_before=original.locked_constraints,
        proposed_requirement=revised,
    )

    dumped = patch.model_dump(mode="json")
    assert AgendaPatch.model_validate(dumped) == patch

    with pytest.raises(ValidationError, match="drops locked constraints"):
        AgendaPatch(
            patch_id="patch-2",
            operation="revise_requirement",
            reason="Invalidly drops requested fields",
            requirement_id=original.id,
            locked_constraints_before=original.locked_constraints,
            proposed_requirement=_status_requirement(locked_constraints=["machine_id"]),
        )

    with pytest.raises(ValidationError, match="needs a replacement requirement"):
        AgendaPatch(
            patch_id="patch-3",
            operation="supersede_requirement",
            reason="Invalidly removes a locked requirement with no replacement",
            requirement_id=original.id,
            locked_constraints_before=original.locked_constraints,
        )


def test_phase2_status_only_read_field_requirement_avoids_unrelated_output_fields():
    requirement = _status_requirement()
    evidence = EvidenceLedgerEntry(
        id="ev-status-only",
        requirement_id=requirement.id,
        source_type="api_tool",
        source_of_truth="operational_state",
        tool_name="get__machines_{id}",
        normalized_result={
            "entity": "machine",
            "entity_id": "machine-1",
            "fields": {"status": "running"},
        },
        satisfies=["requested_fields"],
    )

    requirement_dump = requirement.model_dump(mode="json")
    evidence_dump = evidence.model_dump(mode="json")

    assert requirement_dump["requested_fields"] == ["status"]
    assert "output_fields" not in requirement_dump
    assert evidence_dump["normalized_result"]["fields"] == {"status": "running"}
    assert "deadline" not in evidence_dump["normalized_result"]["fields"]


def test_phase2_adapter_traces_are_representable_without_running_v2():
    capability_need = CapabilityNeed(
        requirement_id="req-jobs",
        source_of_truth="operational_state",
        entity="job",
        action="list",
        constraints={"priority": "low", "limit": 3},
        requested_fields=["id", "status", "priority", "deadline"],
    )
    adapter_request = ToolSelectorAdapterRequest(
        requirement_id="req-jobs",
        entity="job",
        actions=["list", "read_many"],
        safety="read_only",
        endpoint_shape="collection",
        source_of_truth="operational_state",
        constraints={"priority": "low", "limit": 3},
        requested_fields=["id", "status", "priority", "deadline"],
        capability_need=capability_need,
    )
    trace = ExecutionTrace(
        engine_version="legacy",
        generated_by="legacy_graph_loop",
        planner=PlannerTrace(call_count=0),
        tool_retrieval=ToolRetrievalTrace(
            call_count=1,
            selected_candidate_tool_names=["get__jobs"],
            backend_used="retrieval",
        ),
    )
    window = CandidateToolWindow(
        requirement_id="req-jobs",
        capability_need=capability_need,
        adapter_request=adapter_request,
        candidates=[CandidateTool(tool_name="get__jobs", rank=1, score=0.93, actions=["list", "read_many"])],
        backend_used="retrieval",
    )

    dumped_trace = trace.model_dump(mode="json")
    dumped_window = window.model_dump(mode="json")

    assert dumped_trace["engine_version"] == "legacy"
    assert dumped_trace["generated_by"] == "legacy_graph_loop"
    assert dumped_trace["tool_retrieval"]["selected_candidate_tool_names"] == ["get__jobs"]
    assert dumped_window["adapter_request"]["capability_need"]["action"] == "list"


def test_phase2_evidence_sources_distinguish_api_rag_legacy_approval_diagnostic_and_user_input():
    entries = [
        EvidenceLedgerEntry(
            id="ev-api",
            requirement_id="req-api",
            source_type="api_tool",
            source_of_truth="operational_state",
            tool_name="get__machines_{id}",
            normalized_result={"fields": {"status": "idle"}},
        ),
        EvidenceLedgerEntry(
            id="ev-rag",
            requirement_id="req-rag",
            source_type="rag_tool",
            source_of_truth="document_knowledge",
            tool_name="rag_search_documents",
            citations=[
                EvidenceCitation(
                    source_id="source-1",
                    title="Safety Procedure",
                    doc_id="doc-1",
                    chunk_id="chunk-1",
                    page=2,
                )
            ],
            normalized_result={"answer": "Follow the cited procedure."},
        ),
        EvidenceLedgerEntry(
            id="ev-legacy-rag",
            requirement_id="req-legacy-rag",
            source_type="legacy_rag_route",
            source_of_truth="document_knowledge",
            citations=[EvidenceCitation(source_id="legacy-source-1", title="Legacy Procedure")],
            diagnostic_metadata={"route_note": "answered before graph execution"},
            legacy_rag_route=LegacyRagRouteMetadata(
                route="rag.procedure",
                source_function="_answer_knowledge_question_as_plan",
            ),
        ),
        EvidenceLedgerEntry(
            id="ev-approval",
            requirement_id="req-approval",
            source_type="approval",
            source_of_truth="operational_state",
            approval_id="approval-1",
            normalized_result={"decision": "approved"},
        ),
        EvidenceLedgerEntry(
            id="ev-diagnostic",
            requirement_id="req-diagnostic",
            source_type="diagnostic",
            source_of_truth="unknown",
            confidence="ambiguous",
            diagnostic_metadata={"reason": "missing_tool"},
        ),
        EvidenceLedgerEntry(
            id="ev-user",
            requirement_id="req-user",
            source_type="user_input",
            source_of_truth="unknown",
            normalized_result={"answer": "Use machine-1"},
        ),
    ]
    ledger = EvidenceLedger(evidence=entries)
    dumped = ledger.model_dump(mode="json")

    assert [entry["source_type"] for entry in dumped["evidence"]] == [
        "api_tool",
        "rag_tool",
        "legacy_rag_route",
        "approval",
        "diagnostic",
        "user_input",
    ]
    assert dumped["evidence"][1]["tool_name"] == "rag_search_documents"
    assert dumped["evidence"][1]["citations"][0]["doc_id"] == "doc-1"
    assert dumped["evidence"][2]["tool_name"] is None
    assert dumped["evidence"][2]["legacy_rag_route"]["persisted_empty_plan"] is True

    with pytest.raises(ValidationError, match="must not be represented as a v2 tool call"):
        EvidenceLedgerEntry(
            id="ev-bad-legacy-rag",
            requirement_id="req-legacy-rag",
            source_type="legacy_rag_route",
            source_of_truth="document_knowledge",
            tool_name="rag_search_documents",
            legacy_rag_route=LegacyRagRouteMetadata(route="rag.procedure"),
        )

    with pytest.raises(ValidationError, match="typed citations"):
        EvidenceLedgerEntry(
            id="ev-bad-rag",
            requirement_id="req-rag",
            source_type="rag_tool",
            source_of_truth="document_knowledge",
            tool_name="rag_search_documents",
        )
