from __future__ import annotations

import pytest

from factory_agent.llm.plan_parsing import _normalize_plan_dict
from factory_agent.planner import _assign_parallel_groups, _dedupe_plan_steps
from factory_agent.schemas import AgentPlanOutput, PlanBinding, PlanDraft, PlanStepDraft, ToolInfo


def _read_tool(name: str, endpoint: str) -> ToolInfo:
    return ToolInfo(
        name=name,
        description=name,
        endpoint=endpoint,
        method="GET",
        input_schema={"type": "object", "properties": {}},
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["read"],
    )


def test_normalize_plan_dict_coerces_string_tool_name_in_depends_on():
    raw = {
        "plan_explanation": "ok",
        "risk_summary": "low",
        "steps": [
            {
                "tool_name": "get__machines",
                "args": {},
                "evidence": {},
                "confidence": 0.8,
                "depends_on": [],
                "execution_mode": "single",
                "bindings": [],
            },
            {
                "tool_name": "get__jobs",
                "args": {},
                "evidence": {},
                "confidence": "0.6",
                "depends_on": ["get__machines"],
                "execution_mode": "weird-mode",
                "bindings": [
                    {
                        "from_step": "get__machines",
                        "result_path": "data",
                        "field": "id",
                        "target_arg": "machine_id",
                    }
                ],
            },
        ],
        "clarification": None,
    }

    normalized = _normalize_plan_dict(raw)
    plan = AgentPlanOutput.model_validate(normalized)

    assert len(plan.steps) == 2
    assert plan.steps[1].depends_on == [0]
    assert plan.steps[1].confidence == pytest.approx(0.6)
    assert plan.steps[1].execution_mode == "single"
    assert len(plan.steps[1].bindings) == 1
    assert plan.steps[1].bindings[0].from_step == 0


def test_normalize_plan_dict_drops_unresolvable_string_dependency():
    raw = {
        "plan_explanation": "",
        "risk_summary": "",
        "steps": [
            {
                "tool_name": "get__jobs",
                "args": {},
                "evidence": {},
                "confidence": 0.9,
                "depends_on": ["nonexistent_tool", "-1", 7],
                "execution_mode": "single",
                "bindings": [
                    {
                        "from_step": "nonexistent_tool",
                        "result_path": "data",
                        "field": "id",
                        "target_arg": "x",
                    }
                ],
            }
        ],
    }

    normalized = _normalize_plan_dict(raw)
    plan = AgentPlanOutput.model_validate(normalized)

    assert plan.steps[0].depends_on == []
    assert plan.steps[0].bindings == []


def test_normalize_plan_dict_handles_non_dict_args_and_missing_required():
    raw = {
        "steps": [
            {
                "tool_name": "get__machines",
                "args": None,
                "evidence": None,
                "confidence": True,
                "depends_on": None,
                "execution_mode": None,
                "missing_required": "id",
                "bindings": None,
            }
        ]
    }

    normalized = _normalize_plan_dict(raw)
    plan = AgentPlanOutput.model_validate(normalized)

    step = plan.steps[0]
    assert step.args == {}
    assert step.evidence == {}
    assert step.confidence == pytest.approx(1.0)
    assert step.depends_on == []
    assert step.execution_mode == "single"
    assert step.missing_required == []
    assert step.bindings == []


def test_normalize_plan_dict_drops_incomplete_binding_objects():
    raw = {
        "plan_explanation": "ok",
        "risk_summary": "low",
        "steps": [
            {"tool_name": "get__jobs", "args": {}, "evidence": {}, "confidence": 0.8},
            {
                "tool_name": "get__jobs_{id}",
                "args": {"id": "JOB-SEED-001"},
                "evidence": {},
                "confidence": 0.8,
                "bindings": [
                    {"from_step": 0},
                    {
                        "from_step": 0,
                        "result_path": "data.job_id",
                        "field": "job_id",
                        "target_arg": "id",
                    },
                ],
            }
        ],
    }

    normalized = _normalize_plan_dict(raw)
    plan = AgentPlanOutput.model_validate(normalized)

    assert len(plan.steps[1].bindings) == 1
    assert plan.steps[1].bindings[0].target_arg == "id"


def test_normalize_plan_dict_repairs_binding_alias_fields():
    raw = {
        "plan_explanation": "ok",
        "risk_summary": "low",
        "steps": [
            {"tool_name": "get__machines", "args": {}, "evidence": {}, "confidence": 0.8},
            {
                "tool_name": "get__jobs",
                "args": {},
                "evidence": {},
                "confidence": 0.8,
                "bindings": [
                    {
                        "from_step": "get__machines",
                        "result_path": "data.0.machine_id",
                        "source_field": "machine_id",
                        "arg": "machine_id",
                    }
                ],
            },
        ],
    }

    normalized = _normalize_plan_dict(raw)
    plan = AgentPlanOutput.model_validate(normalized)

    assert plan.steps[1].bindings[0].from_step == 0
    assert plan.steps[1].bindings[0].result_path == "data.0.machine_id"
    assert plan.steps[1].bindings[0].target_arg == "machine_id"


def test_assign_parallel_groups_for_independent_read_steps():
    tools = {
        "get__jobs": _read_tool("get__jobs", "/jobs"),
        "get__machines": _read_tool("get__machines", "/machines"),
        "get__materials": _read_tool("get__materials", "/materials"),
    }
    steps = [
        PlanStepDraft(step_index=0, tool_name="get__jobs", args={}, depends_on=[]),
        PlanStepDraft(step_index=1, tool_name="get__machines", args={}, depends_on=[]),
        PlanStepDraft(step_index=2, tool_name="get__materials", args={}, depends_on=[]),
    ]

    groups = _assign_parallel_groups(steps, tools, enabled=True)

    assert groups == [[0, 1, 2]]


def test_assign_parallel_groups_skips_bound_steps():
    tools = {
        "get__jobs": _read_tool("get__jobs", "/jobs"),
        "get__machines": _read_tool("get__machines", "/machines"),
        "get__materials": _read_tool("get__materials", "/materials"),
    }
    steps = [
        PlanStepDraft(step_index=0, tool_name="get__jobs", args={}, depends_on=[]),
        PlanStepDraft(step_index=1, tool_name="get__machines", args={}, depends_on=[]),
        PlanStepDraft(
            step_index=2,
            tool_name="get__materials",
            args={},
            depends_on=[],
            bindings=[
                PlanBinding(
                    from_step=1,
                    result_path="data",
                    field="id",
                    target_arg="id",
                    mode="single",
                )
            ],
        ),
    ]

    groups = _assign_parallel_groups(steps, tools, enabled=True)

    assert groups == [[0, 1]]


def test_dedupe_plan_steps_handles_nested_and_list_args():
    draft = PlanDraft(
        plan_explanation="dup",
        risk_summary="low",
        steps=[
            PlanStepDraft(
                step_index=0,
                tool_name="get__jobs",
                args={"ids": ["JOB-1", "JOB-2"], "filters": {"priority": ["high"]}},
                depends_on=[],
            ),
            PlanStepDraft(
                step_index=1,
                tool_name="get__jobs",
                args={"filters": {"priority": ["high"]}, "ids": ["JOB-1", "JOB-2"]},
                depends_on=[],
            ),
        ],
    )

    deduped, dropped = _dedupe_plan_steps(draft)

    assert dropped == 1
    assert len(deduped.steps) == 1
    assert deduped.steps[0].tool_name == "get__jobs"
