from __future__ import annotations

from typing import Any

from factory_agent.graph.v2_agent_graph import _evaluate_conditional_branches_from_evidence
from factory_agent.planning.semantic_intake import SemanticIntakeResult
from factory_agent.planning.v2_agent_state import build_initial_planner_owned_agent_graph_state
from factory_agent.planning.v2_capability_map import (
    build_requirement_ledger_from_sketch,
    build_requirement_sketch_for_text,
    build_v2_capability_map,
)
from factory_agent.planning.v2_contracts import EvidenceLedgerEntry

from tests.test_planner_owned_semantic_intake import (
    _job_collection_tool,
    _job_status_tool,
    _machine_status_tool,
    _product_status_tool,
)


def _intake(user_goal: str, items: list[dict[str, Any]]) -> SemanticIntakeResult:
    return SemanticIntakeResult(
        user_goal=user_goal,
        items=items,
        source="test_fake",
        proposer="compiler_contract_test",
        diagnostics={"compiler_authority": "deterministic"},
    )


def _machine_job_capability_map():
    return build_v2_capability_map(
        {
            "get__machines_{id}": _machine_status_tool(),
            "get__jobs_{id}": _job_status_tool(),
        }
    )


def _job_product_capability_map():
    return build_v2_capability_map(
        {
            "get__jobs_{id}": _job_status_tool(),
            "get__products_{id}": _product_status_tool(),
        }
    )


def _identity_values_from_sketch(sketch) -> set[str]:
    values: set[str] = set()
    for requirement in sketch.requirements:
        for key, value in requirement.constraints.items():
            if key.endswith("_id") or key == "id":
                if isinstance(value, list):
                    values.update(str(item).upper() for item in value)
                else:
                    values.add(str(value).upper())
    for retrieval_slice in sketch.tool_retrieval_slices:
        for key, value in retrieval_slice.constraints.items():
            if key.endswith("_id") or key == "id":
                if isinstance(value, list):
                    values.update(str(item).upper() for item in value)
                else:
                    values.add(str(value).upper())
    return values


def test_compiler_rejects_singular_dependent_read_without_referent():
    user_goal = "Read that job."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=_machine_job_capability_map(),
        semantic_intake=_intake(
            user_goal,
            [
                {
                    "id": "intake-001",
                    "role": "required_requirement",
                    "text": "Read that job.",
                    "reason": "llm_misclassified_dependent_read",
                }
            ],
        ),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert ledger.requirements == []
    assert len(ledger.clarification_needs) == 1
    assert ledger.clarification_needs[0].reason == "dependent_singular_read_missing_bound_entity"
    assert ledger.clarification_needs[0].blocked_entity == "job"


def test_compiler_binds_updated_jobs_read_to_previous_mutation():
    user_goal = "Change planned low-priority jobs to medium priority, then show the updated jobs."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=build_v2_capability_map(
            {
                "get__jobs": _job_collection_tool(),
                "get__jobs_{id}": _job_status_tool(),
            }
        ),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert [(requirement.id, requirement.requirement_type, requirement.entity) for requirement in ledger.requirements] == [
        ("req-001", "mutation_request", "job"),
        ("req-002", "filtered_collection", "job"),
    ]
    assert ledger.requirements[1].depends_on == ["req-001"]
    assert ledger.requirements[1].constraints == {
        "depends_on_result_binding": "updated_jobs",
        "result_binding_source_requirement": "req-001",
        "result_binding_field": "affected_entity_ids",
    }
    assert ledger.clarification_needs == []
    assert [clause.role for clause in ledger.intake_clauses] == [
        "mutation_or_approval_request",
        "required_requirement",
    ]


def test_compiler_binds_affected_jobs_read_to_previous_mutation():
    user_goal = "Change planned low-priority jobs to medium priority, then show the affected jobs."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=build_v2_capability_map(
            {
                "get__jobs": _job_collection_tool(),
                "get__jobs_{id}": _job_status_tool(),
            }
        ),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert [(requirement.id, requirement.requirement_type, requirement.entity) for requirement in ledger.requirements] == [
        ("req-001", "mutation_request", "job"),
        ("req-002", "filtered_collection", "job"),
    ]
    assert ledger.requirements[1].depends_on == ["req-001"]
    assert ledger.requirements[1].constraints["depends_on_result_binding"] == "updated_jobs"
    assert ledger.requirements[1].constraints["result_binding_source_requirement"] == "req-001"
    assert ledger.clarification_needs == []


def test_compiler_keeps_updated_jobs_clarification_without_previous_mutation():
    user_goal = "Show the updated jobs."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=build_v2_capability_map(
            {
                "get__jobs": _job_collection_tool(),
                "get__jobs_{id}": _job_status_tool(),
            }
        ),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert ledger.requirements == []
    assert len(ledger.clarification_needs) == 1
    assert ledger.clarification_needs[0].reason == "dependent_singular_read_missing_bound_entity"
    assert ledger.clarification_needs[0].blocked_entity == "updated"


def test_unbound_when_you_see_product_on_that_job_is_not_executable():
    user_goal = "When you see a product on that job, pull the product too."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=_job_product_capability_map(),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert ledger.requirements == []
    assert sketch.tool_retrieval_slices == []
    assert len(ledger.clarification_needs) == 1
    assert ledger.clarification_needs[0].reason in {
        "conditional_branch_missing_active_parent_or_referent",
        "dependent_singular_read_missing_bound_entity",
    }
    assert ledger.clarification_needs[0].blocked_entity in {"product", "job"}
    assert {"ON", "TOO"}.isdisjoint(_identity_values_from_sketch(sketch))


def test_only_check_product_if_there_is_one_is_not_executable_without_parent():
    user_goal = "Only check the product if there is one."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=_job_product_capability_map(),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert ledger.requirements == []
    assert sketch.tool_retrieval_slices == []
    assert len(ledger.clarification_needs) == 1
    assert ledger.clarification_needs[0].reason in {
        "conditional_branch_missing_active_parent_or_referent",
        "dependent_singular_read_missing_bound_entity",
    }
    assert ledger.clarification_needs[0].blocked_entity == "product"
    assert "IF" not in _identity_values_from_sketch(sketch)


def test_explain_product_if_present_after_job_read_becomes_conditional_not_fake_product_read():
    user_goal = "Check job JOB-SEED-001 then explain its product if present."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=_job_product_capability_map(),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert [(requirement.entity, requirement.constraints) for requirement in ledger.requirements] == [
        ("job", {"job_id": "JOB-SEED-001", "observation_fields": ["product_id", "active_product_id"]})
    ]
    assert sketch.tool_retrieval_slices[0].entity == "job"
    assert sketch.tool_retrieval_slices[0].constraints["job_id"] == "JOB-SEED-001"
    assert len(ledger.conditional_branches) == 1
    branch = ledger.conditional_branches[0]
    assert branch.parent_requirement_id == "req-001"
    assert branch.status == "pending"
    assert branch.condition["field_any"] == ["product_id", "active_product_id"]
    assert branch.on_true["entity"] == "product"
    assert [instruction.text for instruction in ledger.answer_instructions] == [
        "explain its product if present."
    ]
    assert "IF" not in _identity_values_from_sketch(sketch)


def test_dependent_singular_read_never_uses_stopwords_as_identity_constraints():
    examples = [
        ("if", "Only check the product if there is one."),
        ("on", "When you see a product on that job, pull it."),
        ("too", "Pull the product too when it appears."),
        ("present", "Explain the product present if applicable."),
        ("one", "Check the product one only if it exists."),
        ("applicable", "Check the product applicable only if present."),
        ("related", "Check the product related to that job."),
    ]

    for stopword, user_goal in examples:
        sketch = build_requirement_sketch_for_text(
            user_goal,
            capability_map=_job_product_capability_map(),
        )
        assert stopword.upper() not in _identity_values_from_sketch(sketch), user_goal


def test_compiler_does_not_compile_answer_instruction_to_tool_requirement():
    user_goal = "Explain what it means."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=_machine_job_capability_map(),
        semantic_intake=_intake(
            user_goal,
            [
                {
                    "id": "intake-001",
                    "role": "answer_instruction",
                    "text": "Explain what it means.",
                    "reason": "answer_composition_instruction",
                }
            ],
        ),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert ledger.requirements == []
    assert [instruction.text for instruction in ledger.answer_instructions] == [
        "Explain what it means."
    ]


def test_compiler_overrides_bad_required_role_for_answer_instruction():
    user_goal = "Show machine M-CNC-01 status and explain what it means."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=_machine_job_capability_map(),
        semantic_intake=_intake(
            user_goal,
            [
                {
                    "id": "intake-001",
                    "role": "required_requirement",
                    "text": "Show machine M-CNC-01 status",
                },
                {
                    "id": "intake-002",
                    "role": "required_requirement",
                    "text": "explain what it means.",
                    "reason": "llm_misclassified_answer_instruction",
                },
            ],
        ),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert [requirement.id for requirement in ledger.requirements] == ["req-001"]
    assert [instruction.text for instruction in ledger.answer_instructions] == [
        "explain what it means."
    ]
    assert [clause.role for clause in ledger.intake_clauses] == [
        "required_requirement",
        "answer_instruction",
    ]


def test_compiler_reclassifies_answer_instruction_with_concrete_entity_as_required():
    user_goal = "Explain why machine M-CNC-01 is stopped."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=_machine_job_capability_map(),
        semantic_intake=_intake(
            user_goal,
            [
                {
                    "id": "intake-001",
                    "role": "answer_instruction",
                    "text": "Explain why machine M-CNC-01 is stopped.",
                    "reason": "small_model_answer_alias",
                }
            ],
        ),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert [requirement.entity for requirement in ledger.requirements] == ["machine"]
    assert ledger.requirements[0].constraints["machine_id"] == "M-CNC-01"
    assert ledger.answer_instructions == []
    assert [clause.role for clause in ledger.intake_clauses] == ["required_requirement"]


def test_compiler_keeps_conditional_branch_non_executable_until_evidence():
    user_goal = "Check machine status, then conditionally read the job."
    sketch = build_requirement_sketch_for_text(
        user_goal,
        capability_map=_machine_job_capability_map(),
        semantic_intake=_intake(
            user_goal,
            [
                {
                    "id": "intake-001",
                    "role": "required_requirement",
                    "text": "Check machine M-CNC-01 status.",
                },
                {
                    "id": "intake-002",
                    "role": "conditional_branch",
                    "text": "If the machine result includes a job id, read that job.",
                    "parent_item_id": "intake-001",
                    "condition": {
                        "type": "active_parent_evidence_has_any_field",
                        "field_any": ["job_id", "active_job_id"],
                    },
                    "child_intent": {
                        "action": "read_one",
                        "entity": "job",
                        "referent": "that job",
                    },
                },
            ],
        ),
    )
    ledger = build_requirement_ledger_from_sketch(sketch)

    assert [requirement.entity for requirement in ledger.requirements] == ["machine"]
    assert len(ledger.conditional_branches) == 1
    assert ledger.conditional_branches[0].status == "pending"
    assert ledger.conditional_branches[0].activated_child_requirement_ids == []


def test_compiler_activates_child_from_active_parent_evidence_only():
    state = build_initial_planner_owned_agent_graph_state(
        "Check machine M-CNC-01 status. If the machine result includes a job id, read that job.",
        tools_by_name={
            "get__machines_{id}": _machine_status_tool(),
            "get__jobs_{id}": _job_status_tool(),
        },
    )
    evidence = EvidenceLedgerEntry(
        id="ev-parent-active",
        requirement_id="req-001",
        source_type="api_tool",
        source_of_truth="operational_state",
        tool_name="get__machines_{id}",
        args={"id": "M-CNC-01"},
        normalized_result={"fields": {"machine_id": "M-CNC-01", "active_job_id": "JOB-CAUSE-17"}},
        diagnostic_metadata={"active_revision_satisfaction": True},
    )
    state.evidence_ledger.evidence.append(evidence)

    _evaluate_conditional_branches_from_evidence(state, [evidence])

    branch = state.requirement_ledger.conditional_branches[0]
    child = state.requirement_ledger.requirements[1]
    assert branch.status == "activated"
    assert branch.activated_child_requirement_ids == [child.id]
    assert child.parent_requirement_id == "req-001"
    assert child.constraints == {"job_id": "JOB-CAUSE-17"}
    assert child.derived_from_evidence_refs == ["ev-parent-active"]


def test_compiler_skips_branch_when_parent_evidence_lacks_referent():
    state = build_initial_planner_owned_agent_graph_state(
        "Check machine M-CNC-01 status. If the machine result includes a job id, read that job.",
        tools_by_name={
            "get__machines_{id}": _machine_status_tool(),
            "get__jobs_{id}": _job_status_tool(),
        },
    )
    evidence = EvidenceLedgerEntry(
        id="ev-parent-without-job",
        requirement_id="req-001",
        source_type="api_tool",
        source_of_truth="operational_state",
        tool_name="get__machines_{id}",
        args={"id": "M-CNC-01"},
        normalized_result={"fields": {"machine_id": "M-CNC-01", "status": "running"}},
        diagnostic_metadata={"active_revision_satisfaction": True},
    )
    state.evidence_ledger.evidence.append(evidence)

    _evaluate_conditional_branches_from_evidence(state, [evidence])

    branch = state.requirement_ledger.conditional_branches[0]
    assert branch.status == "skipped"
    assert branch.skipped_reason == "conditional_branch_not_triggered"
    assert [requirement.id for requirement in state.requirement_ledger.requirements] == ["req-001"]


def test_compiler_rejects_child_from_stale_parent_evidence():
    state = build_initial_planner_owned_agent_graph_state(
        "Check machine M-CNC-01 status. If the machine result includes a job id, read that job.",
        tools_by_name={
            "get__machines_{id}": _machine_status_tool(),
            "get__jobs_{id}": _job_status_tool(),
        },
    )
    evidence = EvidenceLedgerEntry(
        id="ev-parent-stale",
        requirement_id="req-001",
        source_type="api_tool",
        source_of_truth="operational_state",
        tool_name="get__machines_{id}",
        args={"id": "M-CNC-01"},
        normalized_result={"fields": {"machine_id": "M-CNC-01", "active_job_id": "JOB-STALE-01"}},
        diagnostic_metadata={"active_revision_satisfaction": False},
    )
    state.evidence_ledger.evidence.append(evidence)

    _evaluate_conditional_branches_from_evidence(state, [evidence])

    branch = state.requirement_ledger.conditional_branches[0]
    assert branch.status == "pending"
    assert branch.activated_child_requirement_ids == []
    assert [requirement.id for requirement in state.requirement_ledger.requirements] == ["req-001"]
