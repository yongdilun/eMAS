from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from factory_agent.planning.v2_capability_map import (
    build_capability_needs_for_text,
    build_requirement_ledger_from_sketch,
    build_requirement_sketch_for_text,
    build_v2_capability_map,
    classify_source_of_truth,
    resolve_field_alias,
)
from factory_agent.planning.v2_contracts import CapabilityMap, RequirementLedger, RequirementSketch
from factory_agent.schemas import ToolInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / "factory-agent" / "factory_agent"


def _tool(
    name: str,
    *,
    endpoint: str,
    tags: list[str],
    method: str = "GET",
    input_properties: dict[str, dict[str, Any]] | None = None,
    output_properties: dict[str, dict[str, Any]] | None = None,
    required: list[str] | None = None,
    query_params: list[str] | None = None,
    entity: str | None = None,
    response_contract: str | None = None,
    requires_approval: bool | None = None,
) -> ToolInfo:
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(input_properties or {}),
    }
    if required:
        input_schema["required"] = list(required)
    if entity:
        input_schema["x-ai-entity"] = entity
    if response_contract:
        input_schema["x-ai-response-contracts"] = [response_contract]

    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(output_properties or {}),
    }
    if entity:
        output_schema["x-ai-entity"] = entity

    param_sources = {field: "query" for field in query_params or []}
    for field in required or []:
        if f"{{{field}}}" in endpoint:
            param_sources[field] = "path"

    return ToolInfo(
        name=name,
        description=name.replace("_", " "),
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        input_schema=input_schema,
        output_schema=output_schema,
        path_params=[field for field in required or [] if f"{{{field}}}" in endpoint],
        query_params=list(query_params or []),
        param_sources=param_sources,
        is_read_only=method == "GET",
        requires_approval=(method != "GET") if requires_approval is None else requires_approval,
        side_effect_level="NONE" if method == "GET" else "HIGH",
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
        output_properties={
            "machine_id": {"type": "string", "x-ai-aliases": ["machine id"]},
            "status": {"type": "string", "x-ai-aliases": ["state", "condition"]},
        },
        entity="machine",
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
            "job_id": {"type": "string", "x-ai-aliases": ["job id", "work order id"]},
            "status": {"type": "string", "x-ai-aliases": ["state"]},
            "priority": {"type": "string"},
            "deadline": {"type": "string", "x-ai-aliases": ["due date", "due"]},
            "deadline_status": {"type": "string"},
            "product_id": {"type": "string"},
            "job_step_id": {"type": "string"},
            "quantity": {"type": "integer", "x-ai-aliases": ["qty"]},
        },
        entity="job",
        response_contract="result_collection_v1",
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
        output_properties={
            "job_id": {"type": "string", "x-ai-aliases": ["job id"]},
            "status": {"type": "string"},
            "deadline": {"type": "string", "x-ai-aliases": ["due date"]},
        },
        entity="job",
        response_contract="entity_status_v1",
    )


def _job_update_tool() -> ToolInfo:
    return _tool(
        "put__jobs_{id}",
        endpoint="/jobs/{id}",
        tags=["job", "update", "priority"],
        method="PUT",
        required=["id"],
        input_properties={
            "id": {"type": "string", "x-ai-id-field": "job_id", "x-ai-entity": "job"},
            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
            "status": {"type": "string"},
        },
        output_properties={"job_id": {"type": "string"}, "priority": {"type": "string"}},
        entity="job",
        response_contract="business_change_v1",
        requires_approval=True,
    )


def _base_capability_map() -> CapabilityMap:
    return build_v2_capability_map(
        [_machine_status_tool(), _job_list_tool(), _job_lookup_tool(), _job_update_tool()]
    )


def test_phase3_machine_status_api_tool_produces_operational_capability_hint():
    capability_map = build_v2_capability_map([_machine_status_tool()], include_document_knowledge=False)

    entry = capability_map.capabilities[0]
    assert entry.source_of_truth == "operational_state"
    assert entry.entity == "machine"
    assert "read_one" in entry.actions
    assert "fields" in entry.supports
    assert entry.output_contract == "entity_status_v1"

    needs = build_capability_needs_for_text(
        "Please check machine M-LTH-77 state.",
        capability_map=capability_map,
    )

    assert needs[0].source_of_truth == "operational_state"
    assert needs[0].entity == "machine"
    assert needs[0].action == "read_one"
    assert needs[0].known_args == {"machine_id": "M-LTH-77"}
    assert needs[0].requested_fields == ["status"]


def test_phase3_job_list_api_tool_advertises_filters_sort_limit_and_fields():
    capability_map = build_v2_capability_map([_job_list_tool()], include_document_knowledge=False)
    entry = capability_map.capabilities[0]

    assert entry.source_of_truth == "operational_state"
    assert entry.entity == "job"
    assert {"filters", "sort", "limit", "fields"} <= set(entry.supports)
    assert entry.metadata["filter_enums"] == {"priority": ["high", "medium", "low"]}
    assert entry.metadata["sort_fields"] == ["deadline", "created_at", "priority"]
    assert entry.metadata["limit_fields"] == ["limit"]

    sketch = build_requirement_sketch_for_text(
        "List next 4 low priority jobs sorted by due date ascending with only job id, status, priority, due date.",
        capability_map=capability_map,
    )
    requirement = sketch.requirements[0]

    assert requirement.source_of_truth == "operational_state"
    assert requirement.requirement_type == "filtered_collection"
    assert requirement.constraints["priority"] == "low"
    assert requirement.constraints["sort_by"] == "deadline"
    assert requirement.constraints["sort_dir"] == "asc"
    assert requirement.constraints["limit"] == 4
    assert requirement.requested_fields == ["job_id", "status", "priority", "deadline"]
    assert {"priority", "sort_by", "sort_dir", "limit", "requested_fields"} <= set(requirement.locked_constraints)


def test_phase3_document_knowledge_families_hint_procedure_loto_safety_and_policy_needs():
    capability_map = build_v2_capability_map([], include_document_knowledge=True)

    doc_entries = [entry for entry in capability_map.capabilities if entry.source_of_truth == "document_knowledge"]
    assert {entry.entity for entry in doc_entries} == {"procedure", "policy"}
    assert all(entry.output_contract == "knowledge_answer_v1" for entry in doc_entries)
    assert all(entry.metadata["legacy_route_name"] == "legacy_rag_route" for entry in doc_entries)
    assert all(entry.metadata["v2_rag_tool"] == "not_implemented_phase3" for entry in doc_entries)

    needs = build_capability_needs_for_text(
        "Which LOTO procedure applies before servicing the press?",
        capability_map=capability_map,
    )

    assert needs[0].source_of_truth == "document_knowledge"
    assert needs[0].action == "search_documents"
    assert needs[0].entity == "procedure"


def test_phase3_mixed_api_and_rag_request_produces_separate_hints():
    capability_map = _base_capability_map()
    prompt = "Show machine M-DRL-88 status, then explain the LOTO procedure before maintenance."

    needs = build_capability_needs_for_text(prompt, capability_map=capability_map)

    assert classify_source_of_truth(prompt, capability_map=capability_map) == "mixed"
    assert [need.source_of_truth for need in needs] == ["operational_state", "document_knowledge"]
    assert needs[0].known_args == {"machine_id": "M-DRL-88"}
    assert needs[1].action == "search_documents"


def test_phase3_field_aliases_are_metadata_driven_not_prompt_branches():
    ship_date_tool = _tool(
        "get__shipping_jobs",
        endpoint="/shipping-jobs",
        tags=["job", "list", "shipping"],
        query_params=["fields", "sort_by", "limit"],
        input_properties={
            "fields": {"type": "string"},
            "sort_by": {"type": "string", "enum": ["promise_date"]},
            "limit": {"type": "integer"},
        },
        output_properties={
            "job_id": {"type": "string", "x-ai-aliases": ["job id"]},
            "promise_date": {"type": "string", "x-ai-aliases": ["ship date"]},
        },
        entity="job",
    )
    capability_map = build_v2_capability_map([ship_date_tool], include_document_knowledge=False)

    assert resolve_field_alias("ship date", capability_map.field_aliases, entity="job") == "promise_date"

    sketch = build_requirement_sketch_for_text(
        "List top 2 jobs sorted by ship date with only job id and ship date.",
        capability_map=capability_map,
    )
    requirement = sketch.requirements[0]

    assert requirement.constraints["sort_by"] == "promise_date"
    assert requirement.constraints["limit"] == 2
    assert requirement.requested_fields == ["job_id", "promise_date"]


def test_phase3_requirement_sketch_and_ledger_lock_constraints_before_planner_execution():
    capability_map = _base_capability_map()
    prompt = (
        "Show job JOB-ALPHA-77 status then "
        "list next 5 high priority jobs sorted by deadline descending with only job id, status, deadline then "
        "change high priority jobs to medium with approval before applying, do not update blocked jobs."
    )

    sketch = build_requirement_sketch_for_text(prompt, capability_map=capability_map)
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert isinstance(sketch, RequirementSketch)
    assert isinstance(ledger, RequirementLedger)

    status_req = sketch.requirements[0]
    assert status_req.constraints["job_id"] == "JOB-ALPHA-77"
    assert status_req.requested_fields == ["status"]
    assert {"job_id", "requested_fields"} <= set(status_req.locked_constraints)

    list_req = sketch.requirements[1]
    assert list_req.constraints["priority"] == "high"
    assert list_req.constraints["sort_by"] == "deadline"
    assert list_req.constraints["sort_dir"] == "desc"
    assert list_req.constraints["limit"] == 5
    assert list_req.requested_fields == ["job_id", "status", "deadline"]
    assert {"priority", "sort_by", "sort_dir", "limit", "requested_fields"} <= set(list_req.locked_constraints)

    mutation_req = sketch.requirements[2]
    assert mutation_req.requirement_type == "mutation_request"
    assert mutation_req.constraints["priority"] == "high"
    assert mutation_req.constraints["new_priority"] == "medium"
    assert mutation_req.constraints["requires_approval"] is True
    assert "do not update blocked jobs" in mutation_req.constraints["safety_constraints"]
    assert {"priority", "new_priority", "requires_approval", "safety_constraints"} <= set(
        mutation_req.locked_constraints
    )

    assert [entry.locked_constraints for entry in ledger.requirements] == [
        item.locked_constraints for item in sketch.requirements
    ]


def test_phase3_compact_capability_map_omits_full_tool_schemas():
    capability_map = _base_capability_map()
    dumped = capability_map.model_dump(mode="json")
    dumped_text = repr(dumped)

    assert isinstance(capability_map, CapabilityMap)
    assert "input_schema" not in dumped_text
    assert "output_schema" not in dumped_text
    assert "properties" not in dumped_text
    assert "x-ai-response-contracts" not in dumped_text
    assert "x-ai-aliases" not in dumped_text


def test_phase3_helpers_generalize_across_non_seed_paraphrased_examples():
    capability_map = _base_capability_map()
    prompts = [
        "Give equipment M-DRL-88 state.",
        "Check lathe M-LTH-77 condition.",
    ]

    for prompt in prompts:
        needs = build_capability_needs_for_text(prompt, capability_map=capability_map)
        assert needs[0].source_of_truth == "operational_state"
        assert needs[0].entity == "machine"
        assert needs[0].action == "read_one"
        assert needs[0].requested_fields == ["status"]
        assert not any(value.startswith("M-CNC-01") for value in needs[0].known_args.values())


def test_phase3_runtime_code_still_does_not_claim_v2_or_shadow_execution():
    pretend_v2_patterns = [
        re.compile(r"engine_version[\"']?\s*[:=]\s*[\"']v2(?:_shadow)?[\"']"),
        re.compile(r"generated_by[\"']?\s*[:=]\s*[\"']v2_planner_loop[\"']"),
    ]
    hits: list[str] = []
    for path in RUNTIME_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in pretend_v2_patterns:
            for match in pattern.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                hits.append(f"{path.relative_to(REPO_ROOT)}:{line}: {match.group(0)}")

    assert hits == [], "Phase 3 must not claim v2 runtime execution yet:\n" + "\n".join(hits)


def test_phase3_helper_source_has_no_seed_id_runtime_branches():
    source = (RUNTIME_ROOT / "planning" / "v2_capability_map.py").read_text(encoding="utf-8")

    assert "M-CNC-01" not in source
    assert "JOB-SEED-" not in source
