import copy

from factory_agent.planning.plan_validator import validate_plan
from factory_agent.schemas import PlanDraft, PlanStepDraft, ToolInfo


def _tool(
    *,
    name: str,
    method: str,
    endpoint: str,
    input_schema: dict,
    requires_approval: bool = False,
    side_effect_level: str = "NONE",
    is_read_only: bool = False,
):
    return ToolInfo(
        name=name,
        description=name,
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        input_schema=input_schema,
        requires_approval=requires_approval,
        side_effect_level=side_effect_level,  # type: ignore[arg-type]
        is_read_only=is_read_only,
        is_strongly_idempotent=False,
        is_concurrency_safe=True,
        capability_tags=[],
    )


def test_rejects_self_dependency():
    tools = {"get__x": _tool(name="get__x", method="GET", endpoint="/x", input_schema={"type": "object"})}
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[PlanStepDraft(step_index=0, tool_name="get__x", args={}, depends_on=[0])],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("depends on itself" in e for e in res.errors)


def test_rejects_forward_dependency():
    tools = {"get__x": _tool(name="get__x", method="GET", endpoint="/x", input_schema={"type": "object"})}
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[
            PlanStepDraft(step_index=0, tool_name="get__x", args={}, depends_on=[]),
            PlanStepDraft(step_index=1, tool_name="get__x", args={}, depends_on=[1]),
        ],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("future step" in e or "depends on itself" in e for e in res.errors)


def test_rejects_cycles():
    tools = {"get__x": _tool(name="get__x", method="GET", endpoint="/x", input_schema={"type": "object"})}
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[
            PlanStepDraft(step_index=0, tool_name="get__x", args={}, depends_on=[1]),
            PlanStepDraft(step_index=1, tool_name="get__x", args={}, depends_on=[0]),
        ],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("cycle" in e.lower() for e in res.errors)


def test_rejects_duplicate_tool_args_pairs():
    tools = {"get__x": _tool(name="get__x", method="GET", endpoint="/x", input_schema={"type": "object"})}
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[
            PlanStepDraft(step_index=0, tool_name="get__x", args={"a": 1}),
            PlanStepDraft(step_index=1, tool_name="get__x", args={"a": 1}),
        ],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("Duplicate step detected" in e for e in res.errors)


def test_rejects_approval_step_in_parallel_group():
    tools = {
        "post__x": _tool(
            name="post__x",
            method="POST",
            endpoint="/x",
            input_schema={"type": "object"},
            requires_approval=True,
            side_effect_level="HIGH",
        ),
        "get__y": _tool(name="get__y", method="GET", endpoint="/y", input_schema={"type": "object"}, is_read_only=True),
    }
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[
            PlanStepDraft(step_index=0, tool_name="post__x", args={}, parallel_group=1),
            PlanStepDraft(step_index=1, tool_name="get__y", args={}, parallel_group=1),
        ],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("approval-gated" in e for e in res.errors)


def test_rejects_multiple_critical_in_parallel_group():
    tools = {
        "post__a": _tool(name="post__a", method="POST", endpoint="/a", input_schema={"type": "object"}, side_effect_level="CRITICAL"),
        "post__b": _tool(name="post__b", method="POST", endpoint="/b", input_schema={"type": "object"}, side_effect_level="CRITICAL"),
    }
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[
            PlanStepDraft(step_index=0, tool_name="post__a", args={}, parallel_group=1),
            PlanStepDraft(step_index=1, tool_name="post__b", args={}, parallel_group=1),
        ],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("multiple CRITICAL" in e for e in res.errors)


def test_rejects_delete_before_get_same_endpoint():
    tools = {
        "delete__x": _tool(name="delete__x", method="DELETE", endpoint="/x", input_schema={"type": "object"}),
        "get__x": _tool(name="get__x", method="GET", endpoint="/x", input_schema={"type": "object"}, is_read_only=True),
    }
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[
            PlanStepDraft(step_index=0, tool_name="delete__x", args={}),
            PlanStepDraft(step_index=1, tool_name="get__x", args={}),
        ],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("DELETE step 0" in e for e in res.errors)


def test_rejects_parallel_write_conflicts():
    write_schema = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    tools = {
        "patch__x": _tool(name="patch__x", method="PATCH", endpoint="/x", input_schema=write_schema, side_effect_level="HIGH"),
    }
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[
            PlanStepDraft(step_index=0, tool_name="patch__x", args={"id": 1}, parallel_group=1),
            PlanStepDraft(step_index=1, tool_name="patch__x", args={"id": 1}, parallel_group=1),
        ],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("conflicting write targets" in e for e in res.errors)


def test_rejects_args_schema_mismatch():
    schema = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    tools = {"get__x": _tool(name="get__x", method="GET", endpoint="/x", input_schema=schema, is_read_only=True)}
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[PlanStepDraft(step_index=0, tool_name="get__x", args={"id": "not-int"})],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("Invalid args" in e for e in res.errors)


def test_validates_binding_against_response_schema():
    tools = {
        "get__jobs": _tool(
            name="get__jobs",
            method="GET",
            endpoint="/jobs",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
        ).model_copy(
            update={
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "array",
                            "items": {"type": "object", "properties": {"job_id": {"type": "string"}}},
                        }
                    },
                }
            }
        ),
        "patch__jobs_{id}": _tool(
            name="patch__jobs_{id}",
            method="PATCH",
            endpoint="/jobs/{id}",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            requires_approval=True,
            side_effect_level="HIGH",
        ),
    }
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[
            PlanStepDraft(step_index=0, tool_name="get__jobs", args={}),
            PlanStepDraft(
                step_index=1,
                tool_name="patch__jobs_{id}",
                args={},
                execution_mode="foreach",
                bindings=[
                    {
                        "from_step": 0,
                        "result_path": "data",
                        "field": "job_id",
                        "target_arg": "id",
                        "mode": "foreach",
                    }
                ],
            ),
        ],
    )
    res = validate_plan(plan, tools)
    assert res.ok
    assert res.normalized_dependency_graph[1] == [0]


def test_rejects_binding_unknown_response_field():
    tools = {
        "get__jobs": _tool(
            name="get__jobs",
            method="GET",
            endpoint="/jobs",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
        ).model_copy(
            update={
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "array",
                            "items": {"type": "object", "properties": {"job_id": {"type": "string"}}},
                        }
                    },
                }
            }
        ),
        "patch__jobs_{id}": _tool(
            name="patch__jobs_{id}",
            method="PATCH",
            endpoint="/jobs/{id}",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            requires_approval=True,
            side_effect_level="HIGH",
        ),
    }
    plan = PlanDraft(
        plan_explanation="x",
        risk_summary="x",
        steps=[
            PlanStepDraft(step_index=0, tool_name="get__jobs", args={}),
            PlanStepDraft(
                step_index=1,
                tool_name="patch__jobs_{id}",
                args={},
                execution_mode="foreach",
                bindings=[
                    {
                        "from_step": 0,
                        "result_path": "data",
                        "field": "missing_id",
                        "target_arg": "id",
                        "mode": "foreach",
                    }
                ],
            ),
        ],
    )
    res = validate_plan(plan, tools)
    assert not res.ok
    assert any("missing_id" in error for error in res.errors)

