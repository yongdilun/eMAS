from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_contracts import EvidenceCitation, EvidenceLedgerEntry, UserInterrupt
from factory_agent.planning.v2_interrupts import (
    apply_user_interrupt_to_v2_state,
    approval_payload_matches_newest_ledger_revision,
)
from factory_agent.planning.v2_planner_loop import PlannerOwnedV2Loop
from factory_agent.planning.v2_rag_tool import build_v2_rag_evidence
from factory_agent.planning.v2_satisfaction import apply_deterministic_evidence_satisfaction, validate_v2_final_state
from factory_agent.schemas import ToolInfo
from factory_agent.services.plan_creation_service import PlanCreationService
from factory_agent.testing.tool_faults import clear_tool_faults, configure_tool_faults, maybe_inject_tool_fault


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
        requires_approval=(not read_only) if requires_approval is None else requires_approval,
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


def _job_lookup_tool() -> ToolInfo:
    return _tool(
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
    )


def _job_list_tool() -> ToolInfo:
    return _tool(
        "get__jobs",
        endpoint="/jobs",
        tags=["job", "list", "status"],
        query_params=["priority", "status", "deadline", "fields", "sort_by", "sort_dir", "limit"],
        input_properties={
            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
            "status": {"type": "string", "enum": ["queued", "blocked", "done"]},
            "deadline": {"type": "string", "x-ai-aliases": ["due date"]},
            "fields": {"type": "string"},
            "sort_by": {"type": "string", "enum": ["deadline", "created_at", "priority"]},
            "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer"},
        },
        output_properties={
            "job_id": {"type": "string", "x-ai-aliases": ["job id"]},
            "status": {"type": "string", "enum": ["queued", "blocked", "done"]},
            "priority": {"type": "string"},
            "deadline": {"type": "string", "x-ai-aliases": ["due date"]},
        },
        entity="job",
        response_contract="result_collection_v1",
    )


def _job_update_tool() -> ToolInfo:
    return _tool(
        "patch__jobs_{id}",
        endpoint="/jobs/{id}",
        tags=["job", "update", "priority"],
        method="PATCH",
        required=["id"],
        input_properties={
            "id": {"type": "string", "x-ai-id-field": "job_id", "x-ai-entity": "job"},
            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        output_properties={"job_id": {"type": "string"}, "priority": {"type": "string"}},
        entity="job",
        response_contract="business_change_v1",
        requires_approval=True,
    )


def _rag_tool() -> ToolInfo:
    return _tool(
        "rag_search_documents",
        endpoint="/rag/documents/search",
        tags=["rag", "document", "document_knowledge", "knowledge", "search", "citation", "policy"],
        required=["query"],
        query_params=["query", "limit"],
        input_properties={"query": {"type": "string"}, "limit": {"type": "integer"}},
        output_properties={"answer": {"type": "string"}, "citations": {"type": "array"}},
        response_contract="knowledge_answer_v1",
    )


def _base_tools() -> dict[str, ToolInfo]:
    return {
        "get__machines_{id}": _machine_status_tool(),
        "get__jobs_{id}": _job_lookup_tool(),
        "get__jobs": _job_list_tool(),
        "patch__jobs_{id}": _job_update_tool(),
        "rag_search_documents": _rag_tool(),
    }


class NeedAwareSelector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        phrase = str(kwargs.get("intent") or "").lower()
        if "document" in phrase or "knowledge" in phrase or "rag" in phrase:
            names = ["rag_search_documents"]
        elif "machine" in phrase:
            names = ["get__machines_{id}"]
        elif "job" in phrase and "update" in phrase:
            names = ["patch__jobs_{id}", "get__jobs"]
        elif "job" in phrase and any(token in phrase for token in ("collection", "list", "limit", "sort")):
            names = ["get__jobs", "get__jobs_{id}"]
        elif "job" in phrase:
            names = ["get__jobs_{id}", "get__jobs"]
        else:
            names = []
        return ToolSelectionResult(names, backend_used="retrieval", llm_calls=0)


def _api_evidence(
    evidence_id: str,
    requirement_id: str,
    *,
    entity: str,
    entity_id: str | None = None,
    fields: dict[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
    tool_name: str | None = None,
    normalized_extra: dict[str, Any] | None = None,
    diagnostic_metadata: dict[str, Any] | None = None,
) -> EvidenceLedgerEntry:
    normalized_result: dict[str, Any] = {"entity": entity}
    if entity_id is not None:
        normalized_result["entity_id"] = entity_id
    if fields is not None:
        normalized_result["fields"] = fields
    if rows is not None:
        normalized_result["rows"] = rows
    if normalized_extra:
        normalized_result.update(normalized_extra)
    return EvidenceLedgerEntry(
        id=evidence_id,
        requirement_id=requirement_id,
        source_type="api_tool",
        source_of_truth="operational_state",
        tool_name=tool_name or ("get__jobs" if rows is not None else f"get__{entity}s_{{id}}"),
        normalized_result=normalized_result,
        diagnostic_metadata=dict(diagnostic_metadata or {}),
    )


@pytest.mark.asyncio
async def test_phase9_hard_read_query_proves_v2_retrieval_satisfaction_and_conditional_branch():
    prompt = (
        "Show M-CNC-01 status, show JOB-SEED-001 and JOB-SEED-002 status, then list the next 3 "
        "low-priority jobs sorted by deadline with only job id, status, priority, and deadline. "
        "If any listed job is blocked, explain why before suggesting any update."
    )
    selector = NeedAwareSelector()

    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent=prompt,
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence("ev-machine", "req-001", entity="machine", entity_id="M-CNC-01", fields={"status": "running"}),
            _api_evidence("ev-job-1", "req-002", entity="job", entity_id="JOB-SEED-001", fields={"status": "queued"}),
            _api_evidence("ev-job-2", "req-003", entity="job", entity_id="JOB-SEED-002", fields={"status": "done"}),
            _api_evidence(
                "ev-low-jobs",
                "req-004",
                entity="job",
                rows=[
                    {"job_id": "JOB-SEED-010", "status": "queued", "priority": "low", "deadline": "2026-05-21"},
                    {"job_id": "JOB-SEED-011", "status": "blocked", "priority": "low", "deadline": "2026-05-22"},
                    {"job_id": "JOB-SEED-012", "status": "done", "priority": "low", "deadline": "2026-05-23"},
                ],
                normalized_extra={
                    "supporting_evidence": {
                        "conditional_branches": [
                            {
                                "entity_id": "JOB-SEED-011",
                                "reason": "Blocked by a missing fixture allocation.",
                            }
                        ]
                    }
                },
            ),
        ],
    )

    ledger = run.state.requirement_ledger
    assert ledger is not None
    assert [requirement.requirement_type for requirement in ledger.requirements] == [
        "single_entity_status",
        "single_entity_status",
        "single_entity_status",
        "filtered_collection",
    ]
    assert [requirement.status for requirement in ledger.requirements] == ["satisfied"] * 4
    assert run.state.execution_trace.generated_by == "v2_planner_loop"
    assert run.state.execution_trace.diagnostics["used_v2_capability_tool_retriever"] is True
    assert run.state.execution_trace.detectors.legacy_whole_query_tool_scope.used is False
    assert run.state.execution_trace.detectors.legacy_intent_completion_loop.planner_completion_only_call_count == 0
    assert run.state.execution_trace.final_validator_status == "passed"
    assert run.state.execution_trace.tool_retrieval.call_count == 4
    assert all(call["intent"] != prompt for call in selector.calls)
    assert all(len(window.candidates) <= 5 for window in run.state.candidate_tool_windows)
    assert all(len(cards.cards) <= 5 for cards in run.state.hydrated_tool_cards)

    list_requirement = ledger.requirements[3]
    assert list_requirement.constraints["priority"] == "low"
    assert list_requirement.constraints["sort_by"] == "deadline"
    assert list_requirement.constraints["sort_dir"] == "asc"
    assert list_requirement.constraints["limit"] == 3
    assert list_requirement.requested_fields == ["job_id", "status", "priority", "deadline"]
    assert list_requirement.constraints["conditional_branches"][0]["condition_value"] == "blocked"
    checks = {check.check: check for check in list_requirement.satisfaction_checks}
    assert checks["requested_fields"].actual == ["deadline", "job_id", "priority", "status"]
    assert checks["conditional_branch:typed_explanation"].actual["planner_continuation_required"] is True
    assert checks["conditional_branch:typed_explanation"].passed is True
    assert "blocked_reason" not in run.state.evidence_ledger.evidence[-1].normalized_result["rows"][1]

    assert run.draft is not None
    assert [step.tool_name for step in run.draft.steps] == [
        "get__machines_{id}",
        "get__jobs_{id}",
        "get__jobs_{id}",
        "get__jobs",
    ]
    assert run.draft.steps[0].args == {"id": "M-CNC-01", "fields": "status"}
    assert run.draft.steps[1].args == {"id": "JOB-SEED-001", "fields": "status"}
    assert run.draft.steps[2].args == {"id": "JOB-SEED-002", "fields": "status"}
    assert run.draft.steps[3].args == {
        "priority": "low",
        "sort_by": "deadline",
        "sort_dir": "asc",
        "limit": 3,
        "fields": "job_id,status,priority,deadline",
    }


@pytest.mark.asyncio
async def test_phase13_mixed_read_query_keeps_typed_status_and_collection_evidence_without_legacy_completion():
    prompt = (
        "Show M-CNC-01 status, then show JOB-SEED-001 status, then list the next 3 low priority jobs sorted by deadline."
    )
    selector = NeedAwareSelector()

    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent=prompt,
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence("ev-machine", "req-001", entity="machine", entity_id="M-CNC-01", fields={"status": "running"}),
            _api_evidence("ev-job", "req-002", entity="job", entity_id="JOB-SEED-001", fields={"status": "queued"}),
            _api_evidence(
                "ev-low-jobs",
                "req-003",
                entity="job",
                rows=[
                    {"job_id": "JOB-SEED-010", "priority": "low", "deadline": "2026-05-21"},
                    {"job_id": "JOB-SEED-011", "priority": "low", "deadline": "2026-05-22"},
                    {"job_id": "JOB-SEED-012", "priority": "low", "deadline": "2026-05-23"},
                ],
            ),
        ],
    )

    ledger = run.state.requirement_ledger
    assert ledger is not None
    assert [requirement.requirement_type for requirement in ledger.requirements] == [
        "single_entity_status",
        "single_entity_status",
        "filtered_collection",
    ]
    assert [requirement.status for requirement in ledger.requirements] == ["satisfied", "satisfied", "satisfied"]
    evidence_by_requirement = {
        evidence.requirement_id: evidence.normalized_result
        for evidence in run.state.evidence_ledger.evidence
    }
    assert evidence_by_requirement["req-001"]["entity"] == "machine"
    assert evidence_by_requirement["req-001"]["fields"] == {"status": "running"}
    assert evidence_by_requirement["req-002"]["entity"] == "job"
    assert evidence_by_requirement["req-002"]["fields"] == {"status": "queued"}
    assert [row["job_id"] for row in evidence_by_requirement["req-003"]["rows"]] == [
        "JOB-SEED-010",
        "JOB-SEED-011",
        "JOB-SEED-012",
    ]
    assert [row["deadline"] for row in evidence_by_requirement["req-003"]["rows"]] == [
        "2026-05-21",
        "2026-05-22",
        "2026-05-23",
    ]
    assert run.state.execution_trace.generated_by == "v2_planner_loop"
    assert run.state.execution_trace.detectors.legacy_intent_completion_loop.planner_completion_only_call_count == 0
    assert run.state.execution_trace.detectors.legacy_intent_completion_loop.used is False
    assert run.state.execution_trace.detectors.legacy_whole_query_tool_scope.used is False
    assert run.draft is not None
    assert run.draft.steps[2].args["fields"] == "job_id,deadline"


@pytest.mark.asyncio
async def test_phase9_multi_id_status_read_satisfies_typed_rows_without_completion_loop():
    selector = NeedAwareSelector()
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Find status for job with job id JOB-SEED-001 and JOB-SEED-002.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence(
                "ev-job-statuses",
                "req-001",
                entity="job",
                rows=[
                    {"job_id": "JOB-SEED-001", "status": "queued"},
                    {"job_id": "JOB-SEED-002", "status": "blocked"},
                ],
                tool_name="get__jobs_{id}",
            )
        ],
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    checks = {check.check: check for check in requirement.satisfaction_checks}
    assert requirement.requirement_type == "multi_entity_status"
    assert requirement.constraints["job_id"] == ["JOB-SEED-001", "JOB-SEED-002"]
    assert requirement.status == "satisfied"
    assert checks["entity_match"].expected == ["JOB-SEED-001", "JOB-SEED-002"]
    assert checks["requested_fields"].actual == ["status"]
    assert run.state.execution_trace.detectors.legacy_intent_completion_loop.used is False
    assert run.state.execution_trace.final_validator_status == "passed"
    assert run.draft is not None
    assert [step.args for step in run.draft.steps] == [
        {"id": "JOB-SEED-001", "fields": "status"},
        {"id": "JOB-SEED-002", "fields": "status"},
    ]


@pytest.mark.asyncio
async def test_phase9_direct_v2_aggregates_item_read_evidence_for_multi_id_status():
    selector = NeedAwareSelector()
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Find status for job with job id JOB-ALPHA-001 and JOB-ALPHA-002.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    assert requirement.requirement_type == "multi_entity_status"
    run.state.evidence_ledger.evidence.extend(
        [
            _api_evidence(
                "ev-api-req-001-step-0",
                requirement.id,
                entity="job",
                entity_id="JOB-ALPHA-001",
                fields={"job_id": "JOB-ALPHA-001", "status": "queued"},
                tool_name="get__jobs_{id}",
            ),
            _api_evidence(
                "ev-api-req-001-step-1",
                requirement.id,
                entity="job",
                entity_id="JOB-ALPHA-002",
                fields={"job_id": "JOB-ALPHA-002", "status": "blocked"},
                tool_name="get__jobs_{id}",
            ),
        ]
    )

    service = PlanCreationService.__new__(PlanCreationService)
    service._direct_v2_prepare_evidence_for_satisfaction(run)
    apply_deterministic_evidence_satisfaction(run.state)
    validate_v2_final_state(run.state)

    aggregate = run.state.evidence_ledger.evidence[0]
    assert aggregate.id == f"ev-api-{requirement.id}-aggregate"
    assert aggregate.diagnostic_metadata["aggregated_from"] == ["ev-api-req-001-step-0", "ev-api-req-001-step-1"]
    assert aggregate.normalized_result["rows"] == [
        {"job_id": "JOB-ALPHA-001", "status": "queued"},
        {"job_id": "JOB-ALPHA-002", "status": "blocked"},
    ]
    assert requirement.status == "satisfied"
    assert run.state.execution_trace.final_validator_status == "passed"


@pytest.mark.asyncio
async def test_phase9_projected_collection_uses_structured_filter_evidence_without_exposing_filtered_field():
    selector = NeedAwareSelector()
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="List low priority jobs, only job id and deadline, sorted by deadline ascending, limit 2.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence(
                "ev-low-jobs",
                "req-001",
                entity="job",
                rows=[
                    {"job_id": "JOB-ALPHA-010", "deadline": "2026-05-21"},
                    {"job_id": "JOB-ALPHA-011", "deadline": "2026-05-22"},
                ],
                normalized_extra={
                    "applied_filters": {"priority": "low"},
                    "request_args": {
                        "priority": "low",
                        "sort_by": "deadline",
                        "sort_dir": "asc",
                        "limit": 2,
                        "fields": "job_id,deadline",
                    },
                },
            )
        ],
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    checks = {check.check: check for check in requirement.satisfaction_checks}
    assert requirement.status == "satisfied"
    assert checks["locked_constraint:priority"].actual == "low"
    assert checks["filter_match:priority"].actual == "low"
    assert checks["requested_fields"].actual == ["deadline", "job_id"]
    assert "priority" not in run.state.evidence_ledger.evidence[0].normalized_result["rows"][0]
    assert run.state.execution_trace.final_validator_status == "passed"


@pytest.mark.asyncio
async def test_phase9_mixed_api_rag_uses_rag_only_for_document_requirement_and_requires_typed_sources():
    selector = NeedAwareSelector()
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-CNC-01 status and OSHA lockout/tagout reenergizing notification guidance as separate sections.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence("ev-machine", "req-001", entity="machine", entity_id="M-CNC-01", fields={"status": "running"}),
            EvidenceLedgerEntry(
                id="ev-rag",
                requirement_id="req-002",
                source_type="rag_tool",
                source_of_truth="document_knowledge",
                tool_name="rag_search_documents",
                normalized_result={"answer": "Notify affected employees before reenergizing."},
                citations=[
                    EvidenceCitation(
                        source_id="src-osha-reenergizing",
                        doc_id="osha_3120_lockout_tagout",
                        chunk_id="chunk-reenergizing",
                        title="Control of Hazardous Energy Lockout/Tagout",
                        page=15,
                    )
                ],
            ),
        ],
    )

    ledger = run.state.requirement_ledger
    assert ledger is not None
    assert [requirement.source_of_truth for requirement in ledger.requirements] == [
        "operational_state",
        "document_knowledge",
    ]
    assert [requirement.status for requirement in ledger.requirements] == ["satisfied", "satisfied"]
    assert [window.capability_need.source_of_truth for window in run.state.candidate_tool_windows] == [
        "operational_state",
        "document_knowledge",
    ]
    assert run.state.candidate_tool_windows[1].candidates[0].tool_name == "rag_search_documents"
    assert run.state.execution_trace.detectors.legacy_rag_shortcut.used is False

    class NoSourceResult:
        answer = "I do not have enough retrieved evidence to answer that safely."
        sources: list[Any] = []
        safety_content = None

    evidence, answer, sources, _safety = build_v2_rag_evidence(
        requirement=ledger.requirements[1],
        query="According to OSHA, what notification is required before starting lockout?",
        result=NoSourceResult(),
        evidence_id="ev-rag-insufficient",
    )
    assert evidence is None
    assert answer.startswith("I do not have enough retrieved evidence")
    assert sources == []


def test_phase9_direct_v2_rag_execution_query_uses_requirement_goal_for_source_hint():
    service = PlanCreationService.__new__(PlanCreationService)
    requirement = type(
        "Requirement",
        (),
        {"goal": "Find the approved reenergizing notification guidance."},
    )()

    query = service._direct_v2_rag_execution_query(
        args={"query": "deterministic_source_hint:document_knowledge"},
        requirement=requirement,
        intent="Show the relevant guidance.",
    )

    assert query == "Find the approved reenergizing notification guidance."
    assert service._direct_v2_rag_execution_query(
        args={"query": "Use the documented restart procedure."},
        requirement=requirement,
        intent="Show the relevant guidance.",
    ) == "Use the documented restart procedure."


def test_phase9_direct_v2_stage_rows_uses_next_production_week_when_calendar_week_has_no_rows():
    service = PlanCreationService.__new__(PlanCreationService)
    today = datetime.now(timezone.utc).date()
    rows = [
        {"job_id": "job-low-current", "priority": "low", "deadline": today.isoformat()},
        {"job_id": "job-alpha", "priority": "high", "deadline": (today + timedelta(days=9)).isoformat()},
        {"job_id": "job-beta", "priority": "high", "deadline": (today + timedelta(days=14)).isoformat()},
        {"job_id": "job-gamma", "priority": "high", "deadline": (today + timedelta(days=17)).isoformat()},
    ]

    kept, excluded = service._direct_v2_stage_rows(
        tool_outputs=[{"result": {"data": rows}}],
        constraints={"priority": "high", "date": "this week"},
    )

    assert [row["job_id"] for row in kept] == ["job-alpha", "job-beta"]
    assert [row["job_id"] for row in excluded] == ["job-low-current", "job-gamma"]
    assert excluded[0]["exclusion_reason"] == "priority_constraint"
    assert excluded[1]["exclusion_reason"] == "date_constraint"


def test_phase9_direct_v2_stage_rows_keeps_literal_calendar_week_when_matching_rows_exist():
    service = PlanCreationService.__new__(PlanCreationService)
    today = datetime.now(timezone.utc).date()
    rows = [
        {"job_id": "job-current", "priority": "high", "deadline": today.isoformat()},
        {"job_id": "job-future", "priority": "high", "deadline": (today + timedelta(days=9)).isoformat()},
    ]

    kept, excluded = service._direct_v2_stage_rows(
        tool_outputs=[{"result": {"data": rows}}],
        constraints={"priority": "high", "date": "this week"},
    )

    assert [row["job_id"] for row in kept] == ["job-current"]
    assert [row["job_id"] for row in excluded] == ["job-future"]
    assert excluded[0]["exclusion_reason"] == "date_constraint"


@pytest.mark.asyncio
async def test_phase9_write_approval_stages_preview_without_commit_and_interrupt_invalidates_stale_payload():
    selector = NeedAwareSelector()
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent=(
            "Change all high-priority jobs due this week to medium, but do not update blocked jobs. "
            "Show what would change and ask approval before applying."
        ),
        tools_by_name=_base_tools(),
        engine_mode="v2",
    )

    ledger = run.state.requirement_ledger
    assert ledger is not None
    requirement = ledger.requirements[0]
    assert len(ledger.requirements) == 1
    assert requirement.requirement_type == "mutation_request"
    assert requirement.status == "blocked"
    assert requirement.constraints == {
        "date": "this week",
        "priority": "high",
        "new_priority": "medium",
        "safety_constraints": ["do not update blocked jobs"],
        "requires_approval": True,
        "preview_before_apply": True,
    }
    assert run.draft is not None
    assert [step.tool_name for step in run.draft.steps] == ["get__jobs"]
    assert run.draft.steps[0].args == {"priority": "high", "fields": "deadline,job_id,priority,status"}
    assert run.state.execution_trace.diagnostics["dry_run_write_candidates"] == ["patch__jobs_{id}"]

    approval_evidence = EvidenceLedgerEntry(
        id="ev-staged-approval",
        requirement_id=requirement.id,
        source_type="approval",
        source_of_truth="operational_state",
        approval_id="approval-phase9",
        normalized_result={
            "approval_state": "waiting_approval",
            "commit_state": "not_committed",
            "locked_constraints": dict(requirement.constraints),
            "staged_changes": [
                {
                    "job_id": "JOB-SEED-020",
                    "current_priority": "high",
                    "new_priority": "medium",
                    "status": "queued",
                    "deadline": "2026-05-22",
                }
            ],
            "excluded_rows": [
                {
                    "job_id": "JOB-SEED-021",
                    "status": "blocked",
                    "reason": "blocked rows are excluded by locked safety constraint",
                }
            ],
        },
    )
    run.state.evidence_ledger.evidence.append(approval_evidence)
    assert approval_evidence.normalized_result["commit_state"] == "not_committed"
    assert approval_evidence.normalized_result["staged_changes"][0]["status"] != "blocked"
    assert approval_evidence.normalized_result["excluded_rows"][0]["status"] == "blocked"

    interrupt = UserInterrupt(
        interrupt_id="interrupt-phase9",
        interrupt_type="modify_requirement",
        user_message="Actually also exclude jobs missing a due date.",
        previous_goal=ledger.user_goal,
        target_requirement_id=requirement.id,
        approval_id="approval-phase9",
        created_from_revision=ledger.revision,
    )
    old_revision = ledger.revision
    apply_user_interrupt_to_v2_state(run.state, interrupt)
    context = {"intent_contract": {"v2_state": run.state.model_dump(mode="json")}}

    assert ledger.revision > old_revision
    assert approval_evidence.diagnostic_metadata["stale_after_user_interrupt"] is True
    assert approval_payload_matches_newest_ledger_revision({"requirement_ledger_revision": old_revision}, context) is False
    assert run.state.execution_trace.final_validator_status == "invalidated_by_user_interrupt"


@pytest.mark.asyncio
async def test_phase9_tool_failure_fallback_is_typed_and_cannot_finalize_success():
    selector = NeedAwareSelector()
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-CNC-01 status.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence(
                "ev-machine-failed",
                "req-001",
                entity="machine",
                entity_id="M-CNC-01",
                fields={"status": "unknown"},
                normalized_extra={"error": {"code": "upstream_timeout"}},
            )
        ],
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    assert requirement.status == "failed"
    assert requirement.satisfaction_checks[0].check == "failure_state"
    assert requirement.satisfaction_checks[0].actual == "tool_error"
    assert run.state.execution_trace.final_validator_status == "failed"
    assert run.state.final_validation_result is not None
    assert "required_requirement_not_finalizable" in {
        issue.issue for issue in run.state.final_validation_result.issues
    }


def test_phase9_seeded_tool_faults_are_metadata_controlled_one_shot_envelopes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FACTORY_AGENT_PLAYWRIGHT_SEEDED_MODE", "1")
    clear_tool_faults()

    rules = configure_tool_faults(
        [
            {
                "method": "GET",
                "endpoint": "/machines/{id}",
                "fault": "timeout",
                "once": True,
                "reason": "Controlled test timeout.",
            }
        ]
    )
    assert rules[0]["endpoint"] == "/machines/{id}"

    injected = maybe_inject_tool_fault(tool=_machine_status_tool(), args={"id": "ANY-MACHINE"})

    assert injected is not None
    assert injected["ok"] is False
    assert injected["http_status"] is None
    assert injected["infrastructure_error"] is True
    assert injected["body"]["error_type"] == "timeout"
    assert injected["body"]["fault_injected"] is True
    assert maybe_inject_tool_fault(tool=_machine_status_tool(), args={"id": "ANY-MACHINE"}) is None
    clear_tool_faults()
