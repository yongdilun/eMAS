from __future__ import annotations

import json
from typing import Any

from factory_agent.config import get_settings
from factory_agent.planning.semantic_intake import OpenAICompatibleSemanticIntakeProposer
from factory_agent.planning.v2_agent_state import build_initial_planner_owned_agent_graph_state
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
            "machine_id": {"type": "string"},
            "status": {"type": "string"},
            "active_job_id": {"type": "string"},
        },
        entity="machine",
        response_contract="entity_status_v1",
    )


def _job_status_tool() -> ToolInfo:
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


def _product_status_tool() -> ToolInfo:
    return _tool(
        "get__products_{id}",
        endpoint="/products/{id}",
        tags=["product", "lookup", "status"],
        required=["id"],
        query_params=["fields"],
        input_properties={
            "id": {"type": "string", "x-ai-id-field": "product_id", "x-ai-entity": "product"},
            "fields": {"type": "string"},
        },
        output_properties={"product_id": {"type": "string"}, "status": {"type": "string"}},
        entity="product",
        response_contract="entity_status_v1",
    )


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.configs: list[dict[str, Any]] = []

    def invoke(self, prompt: str, *, config: dict[str, Any] | None = None) -> _FakeMessage:
        assert "JSON object" in prompt
        if config is not None:
            self.configs.append(config)
        return _FakeMessage(json.dumps(self._payload))


def test_semantic_intake_proposer_normalizes_small_model_optional_container_fields():
    proposer = OpenAICompatibleSemanticIntakeProposer(
        get_settings(),
        model=_FakeModel(
            {
                "items": [
                    {
                        "id": "intake-001",
                        "role": "required_requirement",
                        "text": "Show machine M-CNC-01 status.",
                        "condition": None,
                        "child_intent": "read the machine status",
                        "applies_to_item_ids": None,
                        "diagnostics": "small model prose",
                    }
                ]
            }
        ),
    )

    result = proposer.propose("Show machine M-CNC-01 status.")

    assert result.items[0].condition == {}
    assert result.items[0].child_intent == {}
    assert result.items[0].applies_to_item_ids == []
    assert result.items[0].diagnostics == {}


def test_semantic_intake_proposer_accepts_single_item_object_from_small_model():
    proposer = OpenAICompatibleSemanticIntakeProposer(
        get_settings(),
        model=_FakeModel(
            {
                "id": "intake-001",
                "role": "required_requirement",
                "text": "Show machine M-CNC-01 status.",
            }
        ),
    )

    result = proposer.propose("Show machine M-CNC-01 status.")

    assert [item.role for item in result.items] == ["required_requirement"]
    assert result.items[0].text == "Show machine M-CNC-01 status."


def test_semantic_intake_proposer_normalizes_small_model_role_aliases_and_formatting():
    proposer = OpenAICompatibleSemanticIntakeProposer(
        get_settings(),
        model=_FakeModel(
            {
                "items": [
                    {
                        "id": "1",
                        "role": "read/show/check/get/list/status",
                        "text": "Show job JOB-SEED-001 status in a short table.",
                    },
                    {
                        "id": "2",
                        "role": "summarize",
                        "text": "summarize both.",
                    },
                ]
            }
        ),
    )

    result = proposer.propose("Show job JOB-SEED-001 status in a short table. Summarize both.")

    assert [item.role for item in result.items] == [
        "required_requirement",
        "formatting_instruction",
        "answer_instruction",
    ]
    assert result.items[0].text == "Show job JOB-SEED-001 status"
    assert result.items[1].text == "in a short table."


def test_semantic_intake_proposer_recovers_answer_instruction_from_small_model_tail_text():
    proposer = OpenAICompatibleSemanticIntakeProposer(
        get_settings(),
        model=_FakeModel(
            {
                "items": [
                    {
                        "id": "1",
                        "role": "required_requirement",
                        "text": "Read job JOB-SEED-001.",
                    },
                    {
                        "id": "2",
                        "role": "conditional_branch",
                        "text": "If it has a product, read that product too",
                        "child_intent": "summarize both.",
                    },
                ]
            }
        ),
    )

    result = proposer.propose(
        "Read job JOB-SEED-001. If it has a product, read that product too and summarize both."
    )

    assert [item.role for item in result.items] == [
        "required_requirement",
        "conditional_branch",
        "answer_instruction",
    ]
    assert result.items[-1].text == "summarize both."


def test_semantic_intake_proposer_reclassifies_unbound_dependent_read_as_clarification():
    proposer = OpenAICompatibleSemanticIntakeProposer(
        get_settings(),
        model=_FakeModel(
            {
                "items": [
                    {
                        "id": "1",
                        "role": "read",
                        "text": "Read that job.",
                    }
                ]
            }
        ),
    )

    result = proposer.propose("Read that job.")

    assert [item.role for item in result.items] == ["clarification_need"]
    assert result.items[0].diagnostics["blocked_entity"] == "job"


def test_semantic_intake_proposer_names_langsmith_run_and_metadata():
    model = _FakeModel(
        {
            "items": [
                {
                    "id": "1",
                    "role": "required_requirement",
                    "text": "Show machine M-CNC-01 status.",
                }
            ]
        }
    )
    proposer = OpenAICompatibleSemanticIntakeProposer(
        get_settings(),
        model=model,
        parent_run_config={
            "configurable": {"thread_id": "parent-trace"},
            "tags": ["langgraph_parent"],
            "metadata": {"parent_component": "langgraph"},
        },
    )

    proposer.propose("Show machine M-CNC-01 status.")

    assert model.configs
    config = model.configs[0]
    assert config["run_name"] == "semantic_intake_proposer"
    assert config["configurable"]["thread_id"] == "parent-trace"
    assert "langgraph_parent" in config["tags"]
    assert "semantic_intake" in config["tags"]
    assert config["metadata"]["parent_component"] == "langgraph"
    assert config["metadata"]["component"] == "semantic_intake"
    assert config["metadata"]["compiler_authority"] == "deterministic"
    assert config["metadata"]["raw_llm_output_executes_tools"] is False


def test_semantic_intake_classifies_conditional_job_branch():
    state = build_initial_planner_owned_agent_graph_state(
        "Check machine M-CNC-01 status. "
        "If the machine result includes a job id, read that job and explain the cause.",
        tools_by_name={
            "get__machines_{id}": _machine_status_tool(),
            "get__jobs_{id}": _job_status_tool(),
        },
    )

    ledger = state.requirement_ledger
    requirements = ledger.requirements
    branches = ledger.conditional_branches
    intake_roles = [clause.role for clause in ledger.intake_clauses]
    semantic_intake = state.execution_trace.diagnostics["semantic_intake"]

    assert len(requirements) == 1
    assert requirements[0].entity == "machine"
    assert requirements[0].constraints["machine_id"] == "M-CNC-01"
    assert requirements[0].constraints["observation_fields"] == ["job_id", "active_job_id"]
    assert intake_roles == ["required_requirement", "conditional_branch", "answer_instruction"]
    assert len(branches) == 1
    assert branches[0].parent_requirement_id == requirements[0].id
    assert branches[0].condition["field_any"] == ["job_id", "active_job_id"]
    assert branches[0].on_true["entity"] == "job"
    assert branches[0].status == "pending"
    assert ledger.answer_instructions[0].text == "explain the cause."
    assert semantic_intake["compiler_authority"] == "deterministic"
    assert semantic_intake["active_executable_roles"] == ["required_requirement"]


def test_semantic_intake_classifies_answer_instruction_as_non_executable():
    state = build_initial_planner_owned_agent_graph_state(
        "Show machine M-CNC-01 status and explain what it means.",
        tools_by_name={"get__machines_{id}": _machine_status_tool()},
    )

    ledger = state.requirement_ledger
    capability_needs = state.execution_trace.diagnostics["capability_needs"]

    assert [requirement.entity for requirement in ledger.requirements] == ["machine"]
    assert [clause.role for clause in ledger.intake_clauses] == [
        "required_requirement",
        "answer_instruction",
    ]
    assert [instruction.text for instruction in ledger.answer_instructions] == [
        "explain what it means."
    ]
    assert [need["requirement_id"] for need in capability_needs] == ["req-001"]
    assert all("explain" not in requirement.goal.lower() for requirement in ledger.requirements)


def test_semantic_intake_classifies_formatting_instruction_as_non_executable():
    state = build_initial_planner_owned_agent_graph_state(
        "Show job JOB-SEED-001 status in a short table.",
        tools_by_name={"get__jobs_{id}": _job_status_tool()},
    )

    ledger = state.requirement_ledger
    capability_needs = state.execution_trace.diagnostics["capability_needs"]

    assert [requirement.entity for requirement in ledger.requirements] == ["job"]
    assert ledger.requirements[0].constraints["job_id"] == "JOB-SEED-001"
    assert [clause.role for clause in ledger.intake_clauses] == [
        "required_requirement",
        "formatting_instruction",
    ]
    assert [instruction.text for instruction in ledger.formatting_instructions] == [
        "in a short table."
    ]
    assert [need["requirement_id"] for need in capability_needs] == ["req-001"]
    assert all("table" not in requirement.goal.lower() for requirement in ledger.requirements)


def test_semantic_intake_preserves_sequence_and_dependency():
    state = build_initial_planner_owned_agent_graph_state(
        "Read job JOB-SEED-001. If it has a product, read that product too and summarize both.",
        tools_by_name={
            "get__jobs_{id}": _job_status_tool(),
            "get__products_{id}": _product_status_tool(),
        },
    )

    ledger = state.requirement_ledger
    branch = ledger.conditional_branches[0]

    assert [requirement.entity for requirement in ledger.requirements] == ["job"]
    assert ledger.requirements[0].constraints["job_id"] == "JOB-SEED-001"
    assert ledger.requirements[0].constraints["observation_fields"] == [
        "product_id",
        "active_product_id",
    ]
    assert [clause.role for clause in ledger.intake_clauses] == [
        "required_requirement",
        "conditional_branch",
        "answer_instruction",
    ]
    assert branch.parent_requirement_id == "req-001"
    assert branch.condition["field_any"] == ["product_id", "active_product_id"]
    assert branch.on_true["entity"] == "product"
    assert branch.status == "pending"
    assert [instruction.text for instruction in ledger.answer_instructions] == ["summarize both."]
