from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from factory_agent.persistence.models import Session
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_contracts import EvidenceLedgerEntry, UserInterrupt
from factory_agent.planning.v2_interrupts import (
    apply_user_interrupt_to_v2_state,
    approval_payload_matches_newest_ledger_revision,
    classify_user_interrupt,
)
from factory_agent.planning.v2_planner_loop import PlannerOwnedV2Loop
from factory_agent.schemas import ToolInfo
from tests.test_api_endpoints import _make_app


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
        query_params=["priority", "status", "fields", "sort_by", "sort_dir", "limit"],
        input_properties={
            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
            "status": {"type": "string", "enum": ["queued", "blocked", "done"]},
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
    }


def _api_evidence(
    evidence_id: str,
    requirement_id: str,
    *,
    entity: str,
    entity_id: str | None = None,
    fields: dict[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
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
        tool_name="get__jobs" if rows is not None else f"get__{entity}s_{{id}}",
        normalized_result=normalized_result,
    )


@pytest.mark.asyncio
async def test_phase7_executing_user_message_creates_replan_checkpoint_not_pending_storage(
    sessionmaker_override,
    db_session,
):
    session_id = "phase7-executing-interrupt"
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="EXECUTING",
            current_intent="Show machine status.",
            plan_version=1,
            version=1,
            event_seq=0,
            session_started_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            replan_context={},
        )
    )
    await db_session.commit()

    app, _event_bus = await _make_app(
        sessionmaker_override,
        enforce_tool_registry_health=False,
        min_healthy_tool_count=0,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Also include the current job status."},
        )
        assert res.status_code == 200
        session = (await client.get(f"/sessions/{session_id}")).json()

    assert session["status"] == "PLANNING"
    assert session["pending_user_message"] is None
    assert session["replan_context"]["planner_owned_loop_interrupt"]["interrupt_type"] == "append_requirement"
    assert session["replan_context"]["planner_owned_loop_interrupt"]["replaces_pending_user_message"] is True
    assert session["replan_context"]["mid_execution_replan"]["checkpoint"] == "interrupt_replan"


@pytest.mark.asyncio
async def test_phase7_append_interrupt_adds_requirement_ledger_revision():
    selector = RecordingSelector(["get__machines_{id}", "get__jobs_{id}"])
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-LTH-77 status.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
    )
    ledger = run.state.requirement_ledger
    assert ledger is not None
    base_revision = ledger.revision

    interrupt = classify_user_interrupt(
        "Also show job JOB-ALPHA-77 status.",
        previous_goal=ledger.user_goal,
        created_from_revision=base_revision,
    )
    apply_user_interrupt_to_v2_state(run.state, interrupt)

    assert ledger.revision == base_revision + 1
    assert len([requirement for requirement in ledger.requirements if requirement.status == "open"]) == 2
    assert ledger.revision_history[-1].change_type == "user_interrupt:append_requirement"
    assert ledger.revision_history[-1].details["added_requirement_ids"]


@pytest.mark.asyncio
async def test_phase7_modify_interrupt_supersedes_old_requirement_and_marks_stale_evidence():
    selector = RecordingSelector(["get__jobs"])
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
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
                        "status": "blocked",
                        "priority": "low",
                        "deadline": "2026-06-02",
                    },
                ],
            )
        ],
    )
    ledger = run.state.requirement_ledger
    assert ledger is not None
    assert ledger.requirements[0].status == "satisfied"

    interrupt = UserInterrupt(
        interrupt_id="interrupt-modify",
        interrupt_type="modify_requirement",
        user_message="Do not include blocked jobs.",
        previous_goal=ledger.user_goal,
        target_requirement_id="req-001",
        created_from_revision=ledger.revision,
    )
    apply_user_interrupt_to_v2_state(run.state, interrupt)

    superseded = next(requirement for requirement in ledger.requirements if requirement.id == "req-001")
    replacement = next(requirement for requirement in ledger.requirements if requirement.id == superseded.superseded_by)
    evidence = run.state.evidence_ledger.evidence[0]

    assert superseded.status == "superseded"
    assert replacement.status == "open"
    assert replacement.evidence_refs == []
    assert "safety_constraints" in replacement.constraints
    assert evidence.diagnostic_metadata["stale_after_user_interrupt"] is True
    assert evidence.diagnostic_metadata["superseded_reason"] == "modify_requirement"


@pytest.mark.asyncio
async def test_phase7_replace_interrupt_preserves_old_state_in_revision_history():
    selector = RecordingSelector(["get__machines_{id}"])
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-LTH-77 status.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
        direct_test_evidence=[
            _api_evidence(
                "ev-machine",
                "req-001",
                entity="machine",
                entity_id="M-LTH-77",
                fields={"status": "running"},
            )
        ],
    )
    ledger = run.state.requirement_ledger
    assert ledger is not None

    interrupt = classify_user_interrupt(
        "Replace that with job JOB-ALPHA-77 status.",
        previous_goal=ledger.user_goal,
        created_from_revision=ledger.revision,
    )
    apply_user_interrupt_to_v2_state(run.state, interrupt)

    record = ledger.revision_history[-1]
    assert record.change_type == "user_interrupt:replace_goal"
    assert record.details["previous_ledger"]["requirements"][0]["id"] == "req-001"
    assert record.details["previous_ledger"]["requirements"][0]["evidence_refs"] == ["ev-machine"]
    assert ledger.requirements[0].status == "superseded"
    assert run.state.evidence_ledger.evidence[0].diagnostic_metadata["superseded_reason"] == "replace_goal"


@pytest.mark.asyncio
async def test_phase7_cancel_interrupt_invalidates_active_v2_finalization():
    selector = RecordingSelector(["get__machines_{id}"])
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-LTH-77 status.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
    )
    ledger = run.state.requirement_ledger
    assert ledger is not None

    interrupt = classify_user_interrupt("Cancel the current run.", previous_goal=ledger.user_goal)
    apply_user_interrupt_to_v2_state(run.state, interrupt)

    assert ledger.revision_history[-1].change_type == "user_interrupt:cancel_current_run"
    assert ledger.requirements[0].status == "skipped"
    assert run.state.execution_trace.final_validator_status == "invalidated_by_user_interrupt"


@pytest.mark.asyncio
async def test_phase7_approval_payload_revision_gate_rejects_stale_and_allows_newest():
    selector = RecordingSelector(["patch__jobs_{id}"])
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Change job JOB-ALPHA-77 priority to low and ask approval.",
        tools_by_name=_base_tools(),
        engine_mode="v2",
    )
    ledger = run.state.requirement_ledger
    assert ledger is not None
    interrupt = classify_user_interrupt(
        "Also exclude blocked jobs.",
        previous_goal=ledger.user_goal,
        created_from_revision=ledger.revision,
    )
    apply_user_interrupt_to_v2_state(run.state, interrupt)
    context = {"intent_contract": {"v2_state": run.state.model_dump(mode="json")}}

    assert approval_payload_matches_newest_ledger_revision({"requirement_ledger_revision": 1}, context) is False
    assert approval_payload_matches_newest_ledger_revision(
        {"planner_owned_loop": {"requirement_ledger_revision": ledger.revision}},
        context,
    ) is True
    assert approval_payload_matches_newest_ledger_revision({"legacy_payload": True}, context) is True


@pytest.mark.asyncio
async def test_phase7_shadow_mode_stays_trace_only_when_interrupt_state_is_revised():
    selector = RecordingSelector(["get__machines_{id}", "get__jobs_{id}"])
    run = await PlannerOwnedV2Loop(selector).run(  # type: ignore[arg-type]
        intent="Show machine M-LTH-77 status.",
        tools_by_name=_base_tools(),
        engine_mode="v2_shadow",
    )
    ledger = run.state.requirement_ledger
    assert ledger is not None

    interrupt = classify_user_interrupt("Also show job JOB-ALPHA-77 status.", previous_goal=ledger.user_goal)
    apply_user_interrupt_to_v2_state(run.state, interrupt)

    assert run.draft is None
    assert run.tool_outputs == []
    assert run.state.execution_trace.diagnostics["shadow_only"] is True
    assert ledger.revision_history[-1].actor == "user"


def test_phase7_interrupt_runtime_has_no_seeded_or_exact_prompt_branches():
    source = Path("factory_agent/planning/v2_interrupts.py").read_text(encoding="utf-8")

    forbidden_fragments = [
        "M-CNC-01",
        "JOB-SEED-",
        "phase7-executing-interrupt",
        "Also show job JOB-ALPHA-77 status.",
    ]
    assert not any(fragment in source for fragment in forbidden_fragments)
