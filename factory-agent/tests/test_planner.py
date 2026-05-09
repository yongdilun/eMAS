import pytest

from factory_agent.config import Settings
from factory_agent.graph.errors import LangGraphPlannerClarification
from factory_agent.graph.nodes.validate import make_validate_node
from factory_agent.graph.planner_graph_helpers import (
    _deterministic_plan_repair,
    _normalize_plan_dict,
)
from factory_agent.graph.state import AgentPlanOutput, AgentPlanStep
from factory_agent.planner import (
    PlannerAdapter,
    PlannerBackendError,
    PlannerService,
    _assign_parallel_groups,
)
from factory_agent.schemas import PlanBinding, PlanDraft, PlanStepDraft, ToolInfo
from factory_agent.registry.tool_registry import ToolRegistry


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )


def _run_validate(settings: Settings, state: dict) -> dict:
    return make_validate_node(settings)(state)


def _jobs_list_tool() -> ToolInfo:
    return ToolInfo(
        name="get__jobs",
        description="List jobs",
        endpoint="/jobs",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                "status": {"type": "string", "enum": ["planned", "scheduled", "running", "blocked", "paused", "completed", "cancelled"]},
                "sort_by": {"type": "string"},
                "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
            },
        },
        query_params=["priority", "status", "sort_by", "sort_dir"],
        param_sources={
            "priority": "query",
            "status": "query",
            "sort_by": "query",
            "sort_dir": "query",
        },
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["job", "list"],
    )


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


def _write_tool(name: str, endpoint: str, method: str = "DELETE") -> ToolInfo:
    return ToolInfo(
        name=name,
        description=name,
        endpoint=endpoint,
        method=method,
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        path_params=["id"],
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
        is_concurrency_safe=False,
        is_strongly_idempotent=False,
        capability_tags=["write"],
    )


@pytest.mark.asyncio
async def test_planner_service_propagates_backend_errors(monkeypatch):
    settings = _settings()
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())
    tool = _read_tool("get__machines", "/machines")

    class BoomPlanner:
        def __init__(self, settings):
            pass

        async def generate(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            raise PlannerBackendError("LangGraph planner unavailable")

    monkeypatch.setattr(PlannerService, "_langgraph_planner_cls", BoomPlanner)

    with pytest.raises(PlannerBackendError):
        await adapter.generate_plan(intent="show machines", scoped_tools=[tool])


@pytest.mark.asyncio
async def test_planner_service_returns_langgraph_plan(monkeypatch):
    settings = _settings()
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())
    tool = _read_tool("get__machines", "/machines")

    class FakeLGPlanner:
        def __init__(self, settings):
            pass

        async def generate(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            draft = PlanDraft(
                plan_explanation="Graph plan",
                risk_summary="Read-only graph plan.",
                steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={})],
            )
            return draft, {"backend": "langgraph"}

    monkeypatch.setattr(PlannerService, "_langgraph_planner_cls", FakeLGPlanner)

    result = await adapter.generate_plan(intent="show machines", scoped_tools=[tool])

    assert result.backend_used == "langgraph"
    assert result.draft.steps[0].tool_name == "get__machines"


@pytest.mark.parametrize(
    ("intent", "general_tool", "reference_tool"),
    [
        ("list machine types", "get__machines", "get__reference_machine-types"),
        ("list product types", "get__products", "get__reference_product-types"),
    ],
)
def test_langgraph_validation_prefers_reference_type_tools(intent, general_tool, reference_tool):
    settings = _settings()
    tools = [
        _read_tool(general_tool, f"/{general_tool.removeprefix('get__')}"),
        _read_tool(reference_tool, f"/reference/{reference_tool.removeprefix('get__reference_')}"),
    ]
    state = {
        "intent": intent,
        "context": {},
        "scoped_tools": tools,
        "raw_plan": AgentPlanOutput(
            plan_explanation="List requested type reference data.",
            risk_summary="Read-only lookup.",
            steps=[
                AgentPlanStep(
                    tool_name=general_tool,
                    args={},
                    evidence={},
                    confidence=0.8,
                )
            ],
        ),
    }

    result = _run_validate(settings, state)

    draft = result["draft"]
    assert draft.steps[0].tool_name == reference_tool
    assert result["intent_contract"]["steps"][0]["tool_name"] == reference_tool


def test_langgraph_validation_inserts_delete_preflight_lookup():
    settings = _settings()
    tools = [
        _write_tool("delete__jobs_{id}", "/jobs/{id}", "DELETE"),
        ToolInfo(
            name="get__jobs_{id}",
            description="Get a job by ID",
            endpoint="/jobs/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["job", "lookup"],
        ),
    ]
    state = {
        "intent": "delete test job TEST-E2E-factory-delete",
        "context": {},
        "scoped_tools": tools,
        "raw_plan": AgentPlanOutput(
            plan_explanation="Delete the requested job after checking it.",
            risk_summary="Requires approval before deletion.",
            steps=[
                AgentPlanStep(
                    tool_name="delete__jobs_{id}",
                    args={"id": "TEST-E2E-factory-delete"},
                    evidence={"id": "TEST-E2E-factory-delete"},
                    confidence=0.9,
                )
            ],
        ),
    }

    result = _run_validate(settings, state)

    draft = result["draft"]
    assert [step.tool_name for step in draft.steps] == ["get__jobs_{id}", "delete__jobs_{id}"]
    assert [step.step_index for step in draft.steps] == [0, 1]
    assert all(step.args == {"id": "TEST-E2E-factory-delete"} for step in draft.steps)
    assert draft.steps[1].depends_on == [0]
    assert [step["tool_name"] for step in result["intent_contract"]["steps"]] == ["get__jobs_{id}", "delete__jobs_{id}"]


def test_normalize_plan_dict_coerces_string_tool_name_in_depends_on():
    """LLM emits depends_on=['get__machines'] -> normalizer rewrites to integer index."""
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
    """Unknown tool-name references in depends_on get dropped, never crash validation."""
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
    """args=None, evidence=None, missing_required=non-list are coerced to safe defaults."""
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


def test_validate_node_empty_plan_returns_clarification():
    """Empty step_drafts should always preserve user-facing clarification behavior."""
    settings = _settings()
    state = {
        "intent": "list machines",
        "context": {},
        "scoped_tools": [_read_tool("get__machines", "/machines")],
        "raw_plan": AgentPlanOutput(
            plan_explanation="",
            risk_summary="",
            steps=[],
        ),
    }

    with pytest.raises(LangGraphPlannerClarification):
        _run_validate(settings, state)


def test_validate_node_empty_plan_falls_back_to_clear_read_tool_with_supported_path_id():
    settings = _settings()
    tools = [
        ToolInfo(
            name="get__scheduling_explosion",
            description="Explode demand",
            endpoint="/scheduling/products/{id}/explosion",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["scheduling", "explosion", "explode", "demand"],
        ),
        ToolInfo(
            name="post__products",
            description="Create a product",
            endpoint="/products",
            method="POST",
            input_schema={"type": "object", "properties": {"product_name": {"type": "string"}}, "required": ["product_name"]},
            is_read_only=False,
            requires_approval=True,
            side_effect_level="HIGH",
            is_concurrency_safe=False,
            is_strongly_idempotent=False,
            capability_tags=["product", "create"],
        ),
    ]
    state = {
        "intent": "explosion for product P-001",
        "context": {},
        "scoped_tools": tools,
        "raw_plan": AgentPlanOutput(
            plan_explanation="",
            risk_summary="",
            steps=[],
        ),
    }

    result = _run_validate(settings, state)

    draft = result["draft"]
    assert [step.tool_name for step in draft.steps] == ["get__scheduling_explosion"]
    assert draft.steps[0].args == {"id": "P-001"}
    assert result["intent_contract"]["steps"][0]["tool_name"] == "get__scheduling_explosion"


def test_langgraph_repair_expands_job_and_slots_compound_read():
    settings = _settings()
    tools = [
        ToolInfo(
            name="get__jobs_{id}",
            description="Get a job by ID",
            endpoint="/jobs/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["job", "lookup"],
        ),
        ToolInfo(
            name="get__jobs_{id}_slots",
            description="List slots by job ID",
            endpoint="/jobs/{id}/slots",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["job", "slot", "lookup"],
        ),
    ]
    state = {
        "intent": "show JOB-SEED-001 and its slots",
        "context": {},
        "scoped_tools": tools,
        "raw_plan": AgentPlanOutput(
            plan_explanation="bad model output",
            risk_summary="",
            steps=[
                AgentPlanStep(
                    tool_name="get__job",
                    args={},
                    evidence={},
                    confidence=0.1,
                )
            ],
        ),
    }

    result = _run_validate(settings, state)

    draft = result["draft"]
    assert [step.tool_name for step in draft.steps] == ["get__jobs_{id}_slots"]
    assert draft.steps[0].args == {"id": "JOB-SEED-001"}


def test_langgraph_repair_expands_incomplete_job_slots_plan():
    settings = _settings()
    tools = [
        ToolInfo(
            name="get__jobs_{id}",
            description="Get a job by ID",
            endpoint="/jobs/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["job", "lookup"],
        ),
        ToolInfo(
            name="get__jobs_{id}_slots",
            description="List slots by job ID",
            endpoint="/jobs/{id}/slots",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["job", "slot", "lookup"],
        ),
    ]
    state = {
        "intent": "show JOB-SEED-001 and its slots",
        "context": {},
        "scoped_tools": tools,
        "raw_plan": AgentPlanOutput(
            plan_explanation="Retrieve slots only.",
            risk_summary="Read-only.",
            steps=[
                AgentPlanStep(
                    tool_name="get__jobs_{id}_slots",
                    args={"id": "JOB-SEED-001"},
                    evidence={"id": "JOB-SEED-001"},
                    confidence=1.0,
                )
            ],
        ),
    }

    result = _run_validate(settings, state)

    draft = result["draft"]
    assert [step.tool_name for step in draft.steps] == ["get__jobs_{id}_slots"]
    assert draft.steps[0].args == {"id": "JOB-SEED-001"}


def test_langgraph_repair_maps_seed_diagnostic_not_found_read():
    tool = ToolInfo(
        name="get__jobs_{id}",
        description="Get a job by ID",
        endpoint="/jobs/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        path_params=["id"],
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["job", "lookup"],
    )

    repaired = _deterministic_plan_repair("factory read 404 soft", [tool])

    assert repaired is not None
    assert repaired.steps[0].tool_name == "get__jobs_{id}"
    assert repaired.steps[0].args == {"id": "JOB-NOT-REAL"}


def test_langgraph_repair_maps_seed_diagnostic_missing_machine_update():
    tool = ToolInfo(
        name="put__machines_{id}",
        description="Update a machine",
        endpoint="/machines/{id}",
        method="PUT",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        path_params=["id"],
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
        is_concurrency_safe=False,
        is_strongly_idempotent=False,
        capability_tags=["machine", "update"],
    )

    repaired = _deterministic_plan_repair("factory update missing machine", [tool])

    assert repaired is not None
    assert repaired.steps[0].tool_name == "put__machines_{id}"
    assert repaired.steps[0].args == {"id": "M-NOT-REAL"}


def test_langgraph_repair_infers_enum_collection_filter_over_feature_endpoint():
    tools = [
        ToolInfo(
            name="get__machines",
            description="List all machines",
            endpoint="/machines",
            method="GET",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
                },
            },
            query_params=["status"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["machine", "list"],
        ),
        ToolInfo(
            name="get__machines_maintenance-alerts",
            description="Get maintenance alerts",
            endpoint="/machines/maintenance-alerts",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["machine", "maintenance", "alert"],
        ),
    ]

    repaired = _deterministic_plan_repair("show maintenance machines", tools)

    assert repaired is not None
    assert repaired.steps[0].tool_name == "get__machines"
    assert repaired.steps[0].args == {"status": "maintenance"}


def test_langgraph_repair_keeps_alert_intent_out_of_enum_filter_repair():
    tool = ToolInfo(
        name="get__machines",
        description="List all machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]}},
        },
        query_params=["status"],
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "list"],
    )

    repaired = _deterministic_plan_repair("show maintenance alerts", [tool])

    assert repaired is None


def test_langgraph_repair_infers_enum_status_update_from_put_schema():
    tool = ToolInfo(
        name="put__machines_{id}",
        description="Update a machine",
        endpoint="/machines/{id}",
        method="PUT",
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
            },
            "required": ["id"],
        },
        path_params=["id"],
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
        is_concurrency_safe=False,
        is_strongly_idempotent=False,
        capability_tags=["machine", "update"],
    )

    repaired = _deterministic_plan_repair("set machine M-LTH-02 to maintenance", [tool])

    assert repaired is not None
    assert repaired.steps[0].tool_name == "put__machines_{id}"
    assert repaired.steps[0].args == {"id": "M-LTH-02", "status": "maintenance"}


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





@pytest.mark.asyncio
async def test_planner_service_dedupes_duplicate_steps(monkeypatch):
    settings = _settings()
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())

    class FakeLGPlanner:
        def __init__(self, settings):
            pass

        async def generate(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            draft = PlanDraft(
                plan_explanation="dup",
                risk_summary="low",
                steps=[
                    PlanStepDraft(step_index=0, tool_name="get__jobs", args={"priority": "low"}, depends_on=[]),
                    PlanStepDraft(step_index=1, tool_name="get__jobs", args={"priority": "low"}, depends_on=[]),
                ],
            )
            return draft, {"steps": []}

    monkeypatch.setattr(PlannerService, "_langgraph_planner_cls", FakeLGPlanner)

    result = await adapter.generate_plan(
        intent="find all low priority job and find all low priority job",
        scoped_tools=[_jobs_list_tool()],
    )

    assert len(result.draft.steps) == 1
    assert result.draft.steps[0].step_index == 0
    assert result.draft.steps[0].tool_name == "get__jobs"
    assert result.draft.steps[0].args == {"priority": "low"}


@pytest.mark.asyncio
async def test_planner_service_strips_ungrounded_args_via_contract(monkeypatch):
    settings = _settings()
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())

    class FakeLGPlanner:
        def __init__(self, settings):
            pass

        async def generate(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            draft = PlanDraft(
                plan_explanation="list high priority jobs",
                risk_summary="read only",
                steps=[
                    PlanStepDraft(
                        step_index=0,
                        tool_name="get__jobs",
                        args={"priority": "high", "sort_by": "deadline"},
                        depends_on=[],
                    )
                ],
            )
            contract = {
                "intent": "find all high priority job",
                "steps": [
                    {
                        "step_index": 0,
                        "tool_name": "get__jobs",
                        "args": {"priority": "high", "sort_by": "deadline"},
                        "arg_provenance": {
                            "priority": {"value": "high", "source": "llm"},
                            "sort_by": {"value": "deadline", "source": "llm"},
                        },
                    }
                ],
            }
            return draft, contract

    monkeypatch.setattr(PlannerService, "_langgraph_planner_cls", FakeLGPlanner)

    result = await adapter.generate_plan(
        intent="find all high priority job",
        scoped_tools=[_jobs_list_tool()],
    )

    assert result.draft.steps[0].args == {"priority": "high"}

