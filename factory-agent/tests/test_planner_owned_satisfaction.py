from __future__ import annotations

from typing import Any

import pytest

from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_contracts import (
    EvidenceCitation,
    EvidenceLedgerEntry,
    LegacyRagRouteMetadata,
    RequirementLedgerEntry,
    SatisfactionCheck,
)
from factory_agent.planning.v2_trace_compatibility import build_direct_v2_compatibility_run
from factory_agent.planning.v2_satisfaction import validate_v2_final_state
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
            "quantity": {"type": "integer"},
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
        tags=["rag", "document", "knowledge", "search", "citation", "procedure"],
        required=["query"],
        query_params=["query", "limit"],
        input_properties={"query": {"type": "string"}, "limit": {"type": "integer"}},
        output_properties={"answer": {"type": "string"}, "citations": {"type": "array"}},
        response_contract="knowledge_answer_v1",
    )


class RecordingSelector:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        return ToolSelectionResult(self.names, backend_used="retrieval", llm_calls=0)


def _base_tools() -> dict[str, ToolInfo]:
    return {
        "get__machines_{id}": _machine_status_tool(),
        "get__jobs_{id}": _job_lookup_tool(),
        "get__jobs": _job_list_tool(),
        "patch__jobs_{id}": _job_update_tool(),
        "rag_search_documents": _rag_tool(),
    }


def _api_evidence(
    evidence_id: str,
    requirement_id: str,
    *,
    entity: str,
    entity_id: str | None = None,
    fields: dict[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
    confidence: str = "deterministic",
) -> EvidenceLedgerEntry:
    normalized_result: dict[str, Any] = {"entity": entity}
    if entity_id is not None:
        normalized_result["entity_id"] = entity_id
    if fields is not None:
        normalized_result["fields"] = fields
    if rows is not None:
        normalized_result["rows"] = rows
    return EvidenceLedgerEntry(
        id=evidence_id,
        requirement_id=requirement_id,
        source_type="api_tool",
        source_of_truth="operational_state",
        confidence=confidence,  # type: ignore[arg-type]
        tool_name="get__jobs" if rows is not None else f"get__{entity}s_{{id}}",
        normalized_result=normalized_result,
    )


@pytest.mark.asyncio
async def test_phase6_v2_contract_three_read_satisfies_typed_evidence_without_completion_calls():
    selector = RecordingSelector(["get__machines_{id}", "get__jobs_{id}", "get__jobs"])
    prompt = (
        "Show machine M-LTH-77 status, then show job JOB-ALPHA-77 status, then "
        "list next 2 low priority jobs sorted by deadline with only job id, status, priority, deadline."
    )

    run = await build_direct_v2_compatibility_run(
        tool_selector=selector,
        intent=prompt,
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence(
                "ev-machine",
                "req-001",
                entity="machine",
                entity_id="M-LTH-77",
                fields={"status": "running"},
            ),
            _api_evidence(
                "ev-job",
                "req-002",
                entity="job",
                entity_id="JOB-ALPHA-77",
                fields={"status": "queued"},
            ),
            _api_evidence(
                "ev-jobs",
                "req-003",
                entity="job",
                rows=[
                    {
                        "job_id": "JOB-ALPHA-81",
                        "status": "queued",
                        "priority": "low",
                        "deadline": "2026-06-01",
                    },
                    {
                        "job_id": "JOB-ALPHA-82",
                        "status": "blocked",
                        "priority": "low",
                        "deadline": "2026-06-02",
                    },
                ],
            ),
        ],
    )

    ledger = run.state.requirement_ledger
    assert ledger is not None
    assert [requirement.status for requirement in ledger.requirements] == ["satisfied", "satisfied", "satisfied"]
    assert run.state.execution_trace.planner.call_count == 1
    assert run.state.execution_trace.detectors.legacy_intent_completion_loop.planner_completion_only_call_count == 0
    assert run.state.execution_trace.final_validator_status == "passed"

    for requirement in ledger.requirements:
        assert requirement.evidence_refs
        assert requirement.satisfaction_checks
        assert all(check.evidence_ref in requirement.evidence_refs for check in requirement.satisfaction_checks)


@pytest.mark.asyncio
async def test_phase6_requested_fields_reject_unrelated_full_object_fields():
    selector = RecordingSelector(["get__machines_{id}"])

    run = await build_direct_v2_compatibility_run(
        tool_selector=selector,
        intent="Show machine M-LTH-77 status.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence(
                "ev-machine-full-object",
                "req-001",
                entity="machine",
                entity_id="M-LTH-77",
                fields={"status": "running", "deadline": "2026-06-01"},
            )
        ],
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    requested_fields = next(check for check in requirement.satisfaction_checks if check.check == "requested_fields")
    assert requirement.status == "blocked"
    assert requested_fields.expected == ["status"]
    assert requested_fields.actual == ["status", "deadline"]
    assert requested_fields.passed is False
    assert run.state.execution_trace.final_validator_status == "failed"


@pytest.mark.asyncio
async def test_phase6_list_filter_sort_limit_and_fields_produce_proof_records():
    selector = RecordingSelector(["get__jobs"])

    run = await build_direct_v2_compatibility_run(
        tool_selector=selector,
        intent="List next 2 low priority jobs sorted by deadline with only job id, status, priority, deadline.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence(
                "ev-jobs",
                "req-001",
                entity="job",
                rows=[
                    {
                        "job_id": "JOB-ALPHA-81",
                        "status": "queued",
                        "priority": "low",
                        "deadline": "2026-06-01",
                    },
                    {
                        "job_id": "JOB-ALPHA-82",
                        "status": "done",
                        "priority": "low",
                        "deadline": "2026-06-03",
                    },
                ],
            )
        ],
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    checks = {check.check: check for check in requirement.satisfaction_checks}
    assert requirement.status == "satisfied"
    assert checks["filter_match:priority"].passed is True
    assert checks["sort_match"].passed is True
    assert checks["limit_match"].actual_count == 2
    assert checks["requested_fields"].expected == ["job_id", "status", "priority", "deadline"]
    assert checks["requested_fields"].passed is True


@pytest.mark.asyncio
async def test_phase6_missing_evidence_leaves_requirement_open_and_final_validator_fails():
    selector = RecordingSelector(["get__machines_{id}"])

    run = await build_direct_v2_compatibility_run(
        tool_selector=selector,
        intent="Show machine M-LTH-77 status.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    issues = [issue.issue for issue in run.state.final_validation_result.issues]  # type: ignore[union-attr]
    assert requirement.status == "open"
    assert run.state.execution_trace.final_validator_status == "failed"
    assert "required_requirement_open" in issues


@pytest.mark.asyncio
async def test_phase6_ambiguous_evidence_blocks_and_returns_to_planner_state():
    selector = RecordingSelector(["get__machines_{id}"])

    run = await build_direct_v2_compatibility_run(
        tool_selector=selector,
        intent="Show machine M-LTH-77 status.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence(
                "ev-machine-a",
                "req-001",
                entity="machine",
                entity_id="M-LTH-77",
                fields={"status": "running"},
            ),
            _api_evidence(
                "ev-machine-b",
                "req-001",
                entity="machine",
                entity_id="M-LTH-77",
                fields={"status": "down"},
            ),
        ],
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    assert requirement.status == "blocked"
    assert requirement.blockers == ["conflicting_deterministic_evidence"]
    assert requirement.satisfaction_checks[0].check == "failure_state"
    assert requirement.satisfaction_checks[0].passed is False


@pytest.mark.asyncio
async def test_phase6_write_and_approval_requirements_never_fast_path_to_final_answer():
    selector = RecordingSelector(["patch__jobs_{id}"])

    run = await build_direct_v2_compatibility_run(
        tool_selector=selector,
        intent="Change job JOB-ALPHA-77 priority to low and ask approval before applying.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    evidence = run.state.evidence_ledger.evidence[0]
    assert requirement.requirement_type == "mutation_request"
    assert requirement.status == "blocked"
    assert evidence.source_type == "system_guard"
    assert requirement.satisfaction_checks[0].check == "approval_state"
    assert run.state.execution_trace.final_validator_status == "failed"


@pytest.mark.asyncio
async def test_phase6_rag_satisfaction_requires_v2_typed_source_evidence():
    selector = RecordingSelector(["rag_search_documents"])

    run = await build_direct_v2_compatibility_run(
        tool_selector=selector,
        intent="Explain the lockout tagout procedure.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            EvidenceLedgerEntry(
                id="ev-rag",
                requirement_id="req-001",
                source_type="rag_tool",
                source_of_truth="document_knowledge",
                tool_name="rag_search_documents",
                normalized_result={"answer": "Follow the cited lockout tagout procedure."},
                citations=[
                    EvidenceCitation(
                        source_id="src-procedure-1",
                        title="Lockout Procedure",
                        doc_id="doc-procedure-1",
                        chunk_id="chunk-1",
                        page=2,
                    )
                ],
            )
        ],
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    assert requirement.status == "satisfied"
    assert {check.check for check in requirement.satisfaction_checks} == {
        "source_citation",
        "document_answer",
    }
    assert run.state.execution_trace.final_validator_status == "passed"


@pytest.mark.asyncio
async def test_phase6_legacy_rag_shortcut_does_not_satisfy_v2_document_answer():
    selector = RecordingSelector(["rag_search_documents"])

    run = await build_direct_v2_compatibility_run(
        tool_selector=selector,
        intent="Explain the lockout tagout procedure.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            EvidenceLedgerEntry(
                id="historical-rag-route-001",
                requirement_id="req-001",
                source_type="legacy_rag_route",
                source_of_truth="document_knowledge",
                confidence="deterministic",
                legacy_rag_route=LegacyRagRouteMetadata(
                    route="rag.procedure",
                    source_function="PlanCreationService.create_plan",
                    policy_id="rag.procedure",
                ),
            )
        ],
    )

    requirement = run.state.requirement_ledger.requirements[0]  # type: ignore[union-attr]
    assert run.state.evidence_ledger.evidence[0].source_type == "legacy_rag_route"
    assert requirement.status == "blocked"
    assert requirement.satisfaction_checks[0].check == "source_citation"
    assert requirement.satisfaction_checks[0].passed is False
    assert not any(evidence.source_type == "rag_tool" for evidence in run.state.evidence_ledger.evidence)


@pytest.mark.asyncio
async def test_phase6_repeated_retrieval_guard_blocks_same_unchanged_capability_need():
    selector = RecordingSelector(["get__machines_{id}"])

    run = await build_direct_v2_compatibility_run(
        tool_selector=selector,
        intent="Show machine M-LTH-77 status, then show machine M-LTH-77 status.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
    )

    guard = run.state.execution_trace.diagnostics["repeated_retrieval_guard"]
    assert guard["status"] == "blocked_repeated_need"
    assert len(selector.calls) == 1
    assert guard["decisions"][1]["blocked"] is True


def test_phase6_final_validator_blocks_dropped_locked_constraints_and_missing_typed_evidence():
    requirement = RequirementLedgerEntry(
        id="req-001",
        goal="Report machine status",
        requirement_type="single_entity_status",
        entity="machine",
        intent_operation="report_status",
        source_of_truth="operational_state",
        constraints={"machine_id": "M-LTH-77"},
        requested_fields=["status"],
        locked_constraints=["machine_id", "requested_fields"],
        status="satisfied",
        evidence_refs=["ev-missing"],
        satisfaction_checks=[
            SatisfactionCheck(
                check="requested_fields",
                expected=["status"],
                actual=["status"],
                passed=True,
                evidence_ref="ev-missing",
            )
        ],
    )
    selector = RecordingSelector(["get__machines_{id}"])

    async def _run_and_mutate():
        run = await build_direct_v2_compatibility_run(
            tool_selector=selector,
            intent="Show machine M-LTH-77 status.",
            tools_by_name=_base_tools(),
            engine_mode="v2",
        )
        assert run.state.requirement_ledger is not None
        run.state.requirement_ledger.requirements[0] = requirement
        run.state.requirement_sketch.requirements[0].locked_constraints = [  # type: ignore[union-attr]
            "machine_id",
            "requested_fields",
        ]
        run.state.requirement_ledger.requirements[0].locked_constraints = ["requested_fields"]
        return run

    import asyncio

    run = asyncio.run(_run_and_mutate())
    result = validate_v2_final_state(run.state)
    issue_names = {issue.issue for issue in result.issues}

    assert result.status == "failed"
    assert "locked_constraint_dropped" in issue_names
    assert "missing_typed_evidence" in issue_names
