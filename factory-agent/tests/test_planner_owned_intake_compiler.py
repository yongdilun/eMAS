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
    _job_status_tool,
    _machine_status_tool,
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
