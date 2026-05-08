import pytest

from agent.config import Settings
from agent.planner import (
    LangChainPlannerBackend,
    LangGraphPlannerBackend,
    LegacyPlannerBackend,
    PlannerAdapter,
    PlannerBackendError,
    PlannerClarificationError,
    PlannerConfirmationRequired,
    PlannerResult,
    StructuredPlannerBackend,
    _assign_parallel_groups,
)
from agent.reasoning_pipeline import ToolSelectionDecision
from agent.graph.planner_graph import (
    LangGraphPlanner,
    LangGraphPlannerClarification,
    _deterministic_plan_repair,
    _normalize_plan_dict,
)
from agent.graph.state import AgentPlanOutput, AgentPlanStep
from agent.schemas import PlanBinding, PlanDraft, PlanStepDraft, ToolInfo
from agent.tool_registry import ToolRegistry


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
        planner_backend="legacy",
        planner_fallback_to_legacy=True,
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
async def test_planner_adapter_langchain_backend_raises_when_unavailable(monkeypatch):
    settings = Settings(
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
        planner_backend="langchain",
        planner_fallback_to_legacy=True,
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())
    tool = ToolInfo(
        name="get__machines_{id}",
        description="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "status"],
    )

    async def failing_generate_plan(self, *, intent, scoped_tools, context=None, tools_markdown=""):
        del self, intent, scoped_tools, context, tools_markdown
        raise PlannerBackendError("LangChain backend unavailable")

    monkeypatch.setattr(LangChainPlannerBackend, "generate_plan", failing_generate_plan)

    with pytest.raises(PlannerBackendError):
        await adapter.generate_plan(
            intent="Check machine 5 status",
            scoped_tools=[tool],
            context=None,
        )


@pytest.mark.asyncio
async def test_planner_adapter_agent_runtime_routes_to_langgraph(monkeypatch):
    settings = Settings(
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
        agent_runtime="langgraph_agent",
        planner_backend="legacy",
        planner_fallback_to_legacy=False,
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())
    tool = _read_tool("get__machines", "/machines")

    async def fake_generate_plan(self, *, intent, scoped_tools, context=None, tools_markdown=""):
        del self, intent, scoped_tools, context, tools_markdown
        return PlannerResult(
            draft=PlanDraft(
                plan_explanation="Graph plan",
                risk_summary="Read-only graph plan.",
                steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={})],
            ),
            backend_used="langgraph",
            llm_calls=1,
            intent_contract={"backend": "langgraph"},
        )

    monkeypatch.setattr(LangGraphPlannerBackend, "generate_plan", fake_generate_plan)

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
    planner = LangGraphPlanner(_settings())
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

    result = planner._validate_node(state)

    draft = result["draft"]
    assert draft.steps[0].tool_name == reference_tool
    assert result["intent_contract"]["steps"][0]["tool_name"] == reference_tool


def test_langgraph_validation_inserts_delete_preflight_lookup():
    planner = LangGraphPlanner(_settings())
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

    result = planner._validate_node(state)

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
    settings = Settings(
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
        planner_backend="langgraph",
        planner_fallback_to_legacy=True,
    )
    planner = LangGraphPlanner(settings)
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
        planner._validate_node(state)


def test_validate_node_empty_plan_falls_back_to_clear_read_tool_with_supported_path_id():
    planner = LangGraphPlanner(_settings())
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

    result = planner._validate_node(state)

    draft = result["draft"]
    assert [step.tool_name for step in draft.steps] == ["get__scheduling_explosion"]
    assert draft.steps[0].args == {"id": "P-001"}
    assert result["intent_contract"]["steps"][0]["tool_name"] == "get__scheduling_explosion"


def test_langgraph_repair_expands_job_and_slots_compound_read():
    settings = _settings()
    planner = LangGraphPlanner(settings)
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

    result = planner._validate_node(state)

    draft = result["draft"]
    assert [step.tool_name for step in draft.steps] == ["get__jobs_{id}", "get__jobs_{id}_slots"]
    assert all(step.args == {"id": "JOB-SEED-001"} for step in draft.steps)
    assert draft.steps[1].depends_on == [0]


def test_langgraph_repair_expands_incomplete_job_slots_plan():
    planner = LangGraphPlanner(_settings())
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

    result = planner._validate_node(state)

    draft = result["draft"]
    assert [step.tool_name for step in draft.steps] == ["get__jobs_{id}", "get__jobs_{id}_slots"]
    assert all(step.args == {"id": "JOB-SEED-001"} for step in draft.steps)


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
        PlanStepDraft(step_index=1, tool_name="get__machines", args={}, depends_on=[0]),
        PlanStepDraft(step_index=2, tool_name="get__materials", args={}, depends_on=[1]),
    ]

    groups = _assign_parallel_groups(steps, tools, enabled=True)

    assert groups == [[0, 1, 2]]
    assert [step.parallel_group for step in steps] == [0, 0, 0]
    assert [step.depends_on for step in steps] == [[], [], []]


def test_assign_parallel_groups_skips_bound_steps():
    tools = {
        "get__jobs": _read_tool("get__jobs", "/jobs"),
        "get__machines": _read_tool("get__machines", "/machines"),
        "get__materials": _read_tool("get__materials", "/materials"),
    }
    steps = [
        PlanStepDraft(step_index=0, tool_name="get__jobs", args={}, depends_on=[]),
        PlanStepDraft(step_index=1, tool_name="get__machines", args={}, depends_on=[0]),
        PlanStepDraft(
            step_index=2,
            tool_name="get__materials",
            args={},
            depends_on=[1],
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
    assert steps[2].parallel_group is None


@pytest.mark.asyncio
async def test_legacy_planner_prefills_enum_backed_optional_filters():
    settings = Settings(
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
        agent_runtime="legacy_planner",
        tool_selector_backend="retrieval",
    )
    planner = LegacyPlannerBackend(settings)
    tool = ToolInfo(
        name="get__machines",
        description="List machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
                "machine_type": {"type": "string"},
            },
        },
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "list"],
    )

    result = await planner.generate_plan(
        intent="find all running machine",
        scoped_tools=[tool],
    )

    assert result.draft.steps[0].tool_name == "get__machines"
    assert result.draft.steps[0].args["status"] == "running"


@pytest.mark.asyncio
async def test_legacy_planner_keeps_no_arg_specialized_endpoint_terms_as_tool_evidence():
    planner = LegacyPlannerBackend(_settings())
    tools = [
        ToolInfo(
            name="get__predictive_high-risk-jobs",
            description="List high-risk jobs",
            endpoint="/predictive/high-risk-jobs",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "list"],
        ),
        ToolInfo(
            name="get__jobs",
            description="List jobs",
            endpoint="/jobs",
            method="GET",
            input_schema={"type": "object", "properties": {"priority": {"type": "string"}}},
            query_params=["priority"],
            param_sources={"priority": "query"},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "list"],
        ),
    ]

    result = await planner.generate_plan(intent="show predictive high risk jobs", scoped_tools=tools)

    assert result.draft.steps[0].tool_name == "get__predictive_high-risk-jobs"
    assert result.draft.steps[0].args == {}


@pytest.mark.asyncio
async def test_legacy_planner_keeps_requested_feature_endpoint_over_id_lookup(monkeypatch):
    planner = LegacyPlannerBackend(_settings())
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
            capability_tags=["job", "lookup"],
        ),
        ToolInfo(
            name="get__ai_scheduling_jobs_{id}_proposal",
            description="Generate a proposal",
            endpoint="/ai/scheduling/jobs/{id}/proposal",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            capability_tags=["ai", "scheduling", "job", "proposal", "lookup"],
        ),
    ]

    async def _fake_select_tool(*, intent, clause, candidates):
        del intent, clause, candidates
        return ToolSelectionDecision(
            tool_name="get__jobs_{id}",
            args={"id": "JOB-SEED-001"},
            confidence=0.9,
            missing_args=[],
            reason="id lookup overfit",
        )

    monkeypatch.setattr(planner._reasoning, "select_tool", _fake_select_tool)

    result = await planner.generate_plan(intent="show proposal for job JOB-SEED-001", scoped_tools=tools)

    assert result.draft.steps[0].tool_name == "get__ai_scheduling_jobs_{id}_proposal"
    assert result.draft.steps[0].args == {"id": "JOB-SEED-001"}


@pytest.mark.asyncio
async def test_legacy_planner_does_not_turn_endpoint_terms_into_filters():
    planner = LegacyPlannerBackend(_settings())
    tool = ToolInfo(
        name="get__reference_widget-locations",
        description="List widget locations",
        endpoint="/reference/widget-locations",
        method="GET",
        input_schema={"type": "object", "properties": {"type": {"type": "string"}}},
        query_params=["type"],
        param_sources={"type": "query"},
        is_read_only=True,
        requires_approval=False,
        capability_tags=["reference", "widget", "location", "list"],
    )

    result = await planner.generate_plan(intent="list widget locations", scoped_tools=[tool])

    assert result.draft.steps[0].tool_name == "get__reference_widget-locations"
    assert result.draft.steps[0].args == {}


@pytest.mark.asyncio
async def test_legacy_planner_expands_parent_lookup_and_child_resource_read():
    planner = LegacyPlannerBackend(_settings())
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
            capability_tags=["job", "lookup"],
        ),
        ToolInfo(
            name="get__slots_{id}",
            description="Get a slot by ID",
            endpoint="/slots/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            capability_tags=["slot", "job", "lookup"],
        ),
    ]

    result = await planner.generate_plan(intent="show JOB-SEED-001 and its slots", scoped_tools=tools)

    assert [step.tool_name for step in result.draft.steps] == ["get__jobs_{id}", "get__jobs_{id}_slots"]
    assert all(step.args == {"id": "JOB-SEED-001"} for step in result.draft.steps)


@pytest.mark.asyncio
async def test_legacy_planner_keeps_direct_slot_lookup_for_slot_id():
    planner = LegacyPlannerBackend(_settings())
    tools = [
        ToolInfo(
            name="get__jobs_{id}_slots",
            description="List slots by job ID",
            endpoint="/jobs/{id}/slots",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "slot", "lookup"],
        ),
        ToolInfo(
            name="get__slots_{id}",
            description="Get a slot by ID",
            endpoint="/slots/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            capability_tags=["slot", "job", "lookup"],
        ),
    ]

    result = await planner.generate_plan(intent="show slot SLOT-SEED-001", scoped_tools=tools)

    assert [step.tool_name for step in result.draft.steps] == ["get__slots_{id}"]
    assert result.draft.steps[0].args == {"id": "SLOT-SEED-001"}


@pytest.mark.asyncio
async def test_legacy_planner_binds_create_then_show_lookup():
    planner = LegacyPlannerBackend(_settings())
    tools = [
        ToolInfo(
            name="post__jobs",
            description="Create a job",
            endpoint="/jobs",
            method="POST",
            input_schema={
                "type": "object",
                "properties": {"product_id": {"type": "string"}, "quantity_total": {"type": "integer"}},
                "required": ["product_id", "quantity_total"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "object",
                        "properties": {"job_id": {"type": "string"}},
                    }
                },
            },
            body_fields=["product_id", "quantity_total"],
            required_body_fields=["product_id", "quantity_total"],
            is_read_only=False,
            requires_approval=True,
            capability_tags=["job", "create"],
        ),
        ToolInfo(
            name="get__jobs_{id}",
            description="Get a job by ID",
            endpoint="/jobs/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "lookup"],
        ),
    ]

    result = await planner.generate_plan(intent="create job P-005 qty 2 then show it", scoped_tools=tools)

    assert [step.tool_name for step in result.draft.steps] == ["post__jobs", "get__jobs_{id}"]
    assert result.draft.steps[1].bindings[0].from_step == 0
    assert result.draft.steps[1].bindings[0].field == "job_id"
    assert result.draft.steps[1].bindings[0].target_arg == "id"


@pytest.mark.asyncio
async def test_legacy_planner_inserts_delete_preflight_lookup():
    planner = LegacyPlannerBackend(_settings())
    tools = [
        ToolInfo(
            name="delete__jobs_{id}",
            description="Delete a job",
            endpoint="/jobs/{id}",
            method="DELETE",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=False,
            requires_approval=True,
            capability_tags=["job", "delete"],
        ),
        ToolInfo(
            name="get__jobs_{id}",
            description="Get a job by ID",
            endpoint="/jobs/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "lookup"],
        ),
    ]

    result = await planner.generate_plan(intent="delete job JOB-1", scoped_tools=tools)

    assert [step.tool_name for step in result.draft.steps] == ["get__jobs_{id}", "delete__jobs_{id}"]
    assert all(step.args == {"id": "JOB-1"} for step in result.draft.steps)


@pytest.mark.asyncio
async def test_structured_planner_generates_schema_valid_plan(monkeypatch):
    settings = Settings(
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
        planner_backend="structured",
        planner_fallback_to_legacy=False,
    )
    planner = StructuredPlannerBackend(settings)
    tool = ToolInfo(
        name="get__machines",
        description="List machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "status": {"type": "string", "enum": ["idle", "running"]},
            },
        },
        query_params=["location", "status"],
        param_sources={"location": "query", "status": "query"},
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "list"],
    )

    async def _fake_invoke_json(*, intent, scoped_tools, context):
        del intent, scoped_tools, context
        return {
            "plan_explanation": "List machines in Paint Shop.",
            "risk_summary": "Read-only lookup.",
            "steps": [
                {
                    "step_index": 0,
                    "tool_name": "get__machines",
                    "args": {"location": "Paint Shop"},
                    "depends_on": [],
                    "evidence": {"location": "Paint Shop"},
                    "confidence": 0.93,
                    "missing_required": [],
                }
            ],
            "clarification": None,
        }

    monkeypatch.setattr(planner, "_invoke_json", _fake_invoke_json)

    result = await planner.generate_plan(
        intent="show machines in Paint Shop",
        scoped_tools=[tool],
    )

    assert result.backend_used == "structured"
    assert result.llm_calls == 1
    assert result.draft.steps[0].tool_name == "get__machines"
    assert result.draft.steps[0].args == {"location": "Paint Shop"}
    assert result.intent_contract["backend"] == "structured"


@pytest.mark.asyncio
async def test_structured_planner_rejects_invalid_enum_args(monkeypatch):
    planner = StructuredPlannerBackend(_settings())
    tool = ToolInfo(
        name="get__machines",
        description="List machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
            },
        },
        query_params=["status"],
        param_sources={"status": "query"},
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "list"],
    )

    async def _fake_invoke_json(*, intent, scoped_tools, context):
        del intent, scoped_tools, context
        return {
            "plan_explanation": "List broken machines.",
            "risk_summary": "Read-only lookup.",
            "steps": [
                {
                    "step_index": 0,
                    "tool_name": "get__machines",
                    "args": {"status": "broken"},
                    "evidence": {"status": "broken"},
                    "confidence": 0.88,
                    "missing_required": [],
                }
            ],
        }

    monkeypatch.setattr(planner, "_invoke_json", _fake_invoke_json)

    with pytest.raises(PlannerClarificationError) as exc:
        await planner.generate_plan(
            intent="show broken machines",
            scoped_tools=[tool],
        )

    assert 'could not safely map "broken"' in str(exc.value)
    assert "Allowed status values are: idle, running, maintenance, offline." in str(exc.value)


@pytest.mark.asyncio
async def test_planner_adapter_structured_backend_raises_when_unavailable(monkeypatch):
    settings = Settings(
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
        planner_backend="structured",
        planner_fallback_to_legacy=True,
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())
    tool = ToolInfo(
        name="get__machines_{id}",
        description="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "status"],
    )

    async def failing_generate_plan(self, *, intent, scoped_tools, context=None, tools_markdown=""):
        del self, intent, scoped_tools, context, tools_markdown
        raise PlannerBackendError("Structured backend unavailable")

    monkeypatch.setattr(StructuredPlannerBackend, "generate_plan", failing_generate_plan)

    with pytest.raises(PlannerBackendError):
        await adapter.generate_plan(
            intent="Check machine 5 status",
            scoped_tools=[tool],
            context=None,
        )


@pytest.mark.asyncio
async def test_legacy_planner_clarifies_invalid_llm_optional_enum_args(monkeypatch):
    settings = Settings(
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
    planner = LegacyPlannerBackend(settings)
    tool = ToolInfo(
        name="get__machines",
        description="List machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
                "limit": {"type": "integer"},
            },
        },
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "list"],
    )

    async def _fake_select_tool(*, intent, clause, candidates):
        del intent, clause, candidates
        return ToolSelectionDecision(
            tool_name="get__machines",
            args={"status": "broke", "limit": 100},
            confidence=0.9,
            missing_args=[],
            reason="bad enum from llm",
        )

    monkeypatch.setattr(planner._reasoning, "select_tool", _fake_select_tool)

    with pytest.raises(PlannerClarificationError) as exc:
        await planner.generate_plan(
            intent="find all broke machine",
            scoped_tools=[tool],
        )

    message = str(exc.value)
    assert 'could not safely map "broke"' in message
    assert "Allowed status values are: idle, running, maintenance, offline." in message


@pytest.mark.asyncio
async def test_legacy_planner_clarifies_unknown_term_against_likely_enum_field(monkeypatch):
    settings = Settings(
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
    planner = LegacyPlannerBackend(settings)
    tool = ToolInfo(
        name="get__machines",
        description="List machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
            },
        },
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "list"],
    )

    async def _fake_classify_unknown_term(*, clause, term, entity, tool):
        del clause, entity, tool
        assert term == "broke"
        return {"field_name": "status", "confidence": 0.91, "reason": "likely machine status"}

    monkeypatch.setattr(planner._reasoning, "classify_unknown_term", _fake_classify_unknown_term)

    with pytest.raises(PlannerClarificationError) as exc:
        await planner.generate_plan(
            intent="find all broke machine",
            scoped_tools=[tool],
        )

    message = str(exc.value)
    assert 'could not safely map "broke"' in message
    assert "Allowed status values are: idle, running, maintenance, offline." in message


@pytest.mark.asyncio
async def test_legacy_planner_clarifies_unknown_term_without_schema_match(monkeypatch):
    settings = Settings(
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
    planner = LegacyPlannerBackend(settings)
    tool = ToolInfo(
        name="get__machines",
        description="List machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
            },
        },
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "list"],
    )

    async def _fake_classify_unknown_term(*, clause, term, entity, tool):
        del clause, entity, tool
        assert term == "bsn"
        return {"field_name": None, "confidence": 0.0, "reason": "no clear schema field"}

    monkeypatch.setattr(planner._reasoning, "classify_unknown_term", _fake_classify_unknown_term)

    with pytest.raises(PlannerClarificationError) as exc:
        await planner.generate_plan(
            intent="find all bsn machine",
            scoped_tools=[tool],
        )

    assert 'couldn\'t match "bsn" to any supported machine field or filter' in str(exc.value).lower()


@pytest.mark.asyncio
async def test_legacy_planner_negative_memory_blocks_repeated_bad_enum_mapping(monkeypatch):
    planner = LegacyPlannerBackend(_settings())
    tool = ToolInfo(
        name="get__machines",
        description="List machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
            },
        },
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "list"],
    )

    async def _fake_classify_unknown_term(*, clause, term, entity, tool):
        del clause, entity, tool
        assert term == "asasidn"
        return {"field_name": "status", "confidence": 0.91, "reason": "looks like status"}

    monkeypatch.setattr(planner._reasoning, "classify_unknown_term", _fake_classify_unknown_term)

    with pytest.raises(PlannerClarificationError) as exc:
        await planner.generate_plan(
            intent="find all asasidn machine",
            scoped_tools=[tool],
            context={
                "intent_memory": {
                    "negative_bindings": [
                        {
                            "term": "asasidn",
                            "normalized_term": "asasidn",
                            "entity": "machine",
                            "field": "status",
                        }
                    ]
                }
            },
        )

    assert 'couldn\'t match "asasidn" to any supported machine field or filter' in str(exc.value).lower()


def _machine_list_tool_with_filters() -> ToolInfo:
    return ToolInfo(
        name="get__machines",
        description="List machines",
        endpoint="/machines",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["idle", "running", "maintenance", "offline"]},
                "machine_name": {"type": "string"},
                "machine_type": {"type": "string"},
                "location": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
                "sort_by": {"type": "string"},
                "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
                "fields": {"type": "string"},
            },
        },
        query_params=["status", "machine_name", "machine_type", "location", "limit", "offset", "sort_by", "sort_dir", "fields"],
        param_sources={
            "status": "query",
            "machine_name": "query",
            "machine_type": "query",
            "location": "query",
            "limit": "query",
            "offset": "query",
            "sort_by": "query",
            "sort_dir": "query",
            "fields": "query",
        },
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=["machine", "list"],
    )


def _job_list_tool_with_filters() -> ToolInfo:
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


@pytest.mark.asyncio
async def test_legacy_planner_maps_paint_shop_location_filter():
    settings = Settings(
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
        agent_runtime="legacy_planner",
        tool_selector_backend="retrieval",
    )
    planner = LegacyPlannerBackend(settings)

    with pytest.raises(PlannerConfirmationRequired) as exc:
        await planner.generate_plan(
            intent="find all Paint Shop machine",
            scoped_tools=[_machine_list_tool_with_filters()],
        )

    assert exc.value.confirmation["kind"] == "predicate_field_confirmation"
    assert exc.value.confirmation["raw_term"] == "Paint Shop"


@pytest.mark.asyncio
async def test_legacy_planner_maps_in_paint_shop_location_filter():
    settings = Settings(
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
        agent_runtime="legacy_planner",
        tool_selector_backend="retrieval",
    )
    planner = LegacyPlannerBackend(settings)

    result = await planner.generate_plan(
        intent="machines in Paint Shop",
        scoped_tools=[_machine_list_tool_with_filters()],
    )

    assert result.draft.steps[0].args == {"location": "Paint Shop"}


@pytest.mark.asyncio
async def test_legacy_planner_keeps_paint_shop_location_and_strips_synthetic_controls(monkeypatch):
    settings = Settings(
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
        agent_runtime="legacy_planner",
        tool_selector_backend="retrieval",
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())

    async def _fake_select_tool(*, intent, clause, candidates):
        del intent, clause, candidates
        return ToolSelectionDecision(
            tool_name="get__machines",
            args={"location": "Paint Shop", "sort_by": "location", "sort_dir": "asc", "limit": 50},
            confidence=0.9,
            missing_args=[],
            reason="intent filter plus guessed controls",
        )

    monkeypatch.setattr(adapter._legacy._reasoning, "select_tool", _fake_select_tool)

    result = await adapter.generate_plan(
        intent="give me all paint shop machine",
        scoped_tools=[_machine_list_tool_with_filters()],
    )

    assert result.draft.steps[0].tool_name == "get__machines"
    assert result.draft.steps[0].args == {"location": "Paint Shop"}


@pytest.mark.asyncio
async def test_legacy_planner_strips_llm_sort_dir_without_triggering_confirmation(monkeypatch):
    settings = Settings(
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
        agent_runtime="legacy_planner",
        tool_selector_backend="retrieval",
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())

    async def _fake_select_tool(*, intent, clause, candidates):
        del intent, clause, candidates
        return ToolSelectionDecision(
            tool_name="get__machines",
            args={"status": "running", "sort_dir": "asc"},
            confidence=0.9,
            missing_args=[],
            reason="llm guessed sort order",
        )

    monkeypatch.setattr(adapter._legacy._reasoning, "select_tool", _fake_select_tool)

    result = await adapter.generate_plan(
        intent="find all running machines",
        scoped_tools=[_machine_list_tool_with_filters()],
    )

    assert result.draft.steps[0].tool_name == "get__machines"
    assert result.draft.steps[0].args == {"status": "running"}


@pytest.mark.asyncio
async def test_legacy_planner_keeps_user_grounded_priority_but_strips_llm_sort_fields(monkeypatch):
    settings = Settings(
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
        agent_runtime="legacy_planner",
        tool_selector_backend="retrieval",
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())

    async def _fake_select_tool(*, intent, clause, candidates):
        del intent, clause, candidates
        return ToolSelectionDecision(
            tool_name="get__jobs",
            args={"priority": "high", "sort_by": "priority", "sort_dir": "asc"},
            confidence=0.9,
            missing_args=[],
            reason="llm guessed sort controls",
        )

    monkeypatch.setattr(adapter._legacy._reasoning, "select_tool", _fake_select_tool)

    result = await adapter.generate_plan(
        intent="find all high priority job",
        scoped_tools=[_job_list_tool_with_filters()],
    )

    assert result.draft.steps[0].tool_name == "get__jobs"
    assert result.draft.steps[0].args == {"priority": "high"}


@pytest.mark.asyncio
async def test_legacy_planner_drops_llm_status_hallucination_when_priority_is_grounded(monkeypatch):
    settings = Settings(
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
        agent_runtime="legacy_planner",
        tool_selector_backend="retrieval",
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())

    async def _fake_select_tool(*, intent, clause, candidates):
        del intent, clause, candidates
        return ToolSelectionDecision(
            tool_name="get__jobs",
            args={"status": "low", "priority": "low", "sort_by": "priority", "sort_dir": "asc"},
            confidence=0.9,
            missing_args=[],
            reason="llm confused priority with status",
        )

    monkeypatch.setattr(adapter._legacy._reasoning, "select_tool", _fake_select_tool)

    result = await adapter.generate_plan(
        intent="find all low priority job",
        scoped_tools=[_job_list_tool_with_filters()],
    )

    assert result.draft.steps[0].tool_name == "get__jobs"
    assert result.draft.steps[0].args == {"priority": "low"}


@pytest.mark.asyncio
async def test_planner_adapter_dedupes_duplicate_steps_for_repeated_clause():
    settings = Settings(
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
        agent_runtime="legacy_planner",
        planner_backend="legacy",
        tool_selector_backend="retrieval",
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())

    result = await adapter.generate_plan(
        intent="find all low priority job and find all low priority job",
        scoped_tools=[_job_list_tool_with_filters()],
    )

    assert len(result.draft.steps) == 1
    assert result.draft.steps[0].step_index == 0
    assert result.draft.steps[0].tool_name == "get__jobs"
    assert result.draft.steps[0].args == {"priority": "low"}


@pytest.mark.asyncio
async def test_legacy_planner_clarifies_explicit_invalid_status(monkeypatch):
    settings = Settings(
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
        agent_runtime="legacy_planner",
        tool_selector_backend="retrieval",
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())

    async def _fake_select_tool(*, intent, clause, candidates):
        del intent, clause, candidates
        return ToolSelectionDecision(
            tool_name="get__jobs",
            args={"status": "low"},
            confidence=0.9,
            missing_args=[],
            reason="user asked for an unsupported status",
        )

    monkeypatch.setattr(adapter._legacy._reasoning, "select_tool", _fake_select_tool)

    with pytest.raises(PlannerClarificationError) as exc:
        await adapter.generate_plan(
            intent="find job status low",
            scoped_tools=[_job_list_tool_with_filters()],
        )

    assert "valid status" in str(exc.value).lower()
    assert "planned" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_universal_provenance_gate_respects_contract_arg_provenance(monkeypatch):
    settings = Settings(
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
        agent_runtime="legacy_planner",
        planner_backend="legacy",
    )
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())

    async def _fake_generate_plan(*, intent, scoped_tools, context=None, tools_markdown=""):
        del intent, scoped_tools, context, tools_markdown
        return PlannerResult(
            draft=PlanDraft(
                plan_explanation="list high priority jobs",
                risk_summary="read only",
                steps=[
                    PlanStepDraft(
                        step_index=0,
                        tool_name="get__jobs",
                        args={"priority": "high", "sort_by": "priority"},
                        depends_on=[],
                    )
                ],
            ),
            backend_used="legacy",
            llm_calls=0,
            intent_contract={
                "intent": "find all high priority job",
                "clauses": [
                    {
                        "step_index": 0,
                        "tool_name": "get__jobs",
                        "args": {"priority": "high", "sort_by": "priority"},
                        "resolved_predicates": {"priority": "high"},
                        "arg_provenance": {
                            "priority": {"value": "high", "source": "llm"},
                            "sort_by": {"value": "priority", "source": "llm"},
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(adapter._legacy, "generate_plan", _fake_generate_plan)

    result = await adapter.generate_plan(
        intent="find all high priority job",
        scoped_tools=[_job_list_tool_with_filters()],
    )

    assert result.draft.steps[0].args == {"priority": "high"}


@pytest.mark.asyncio
async def test_legacy_planner_rejects_vague_free_text_filter():
    settings = Settings(
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
    planner = LegacyPlannerBackend(settings)

    with pytest.raises(PlannerClarificationError) as exc:
        await planner.generate_plan(
            intent="find close machines",
            scoped_tools=[_machine_list_tool_with_filters()],
        )

    assert "couldn't match" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_legacy_planner_requests_confirmation_for_ambiguous_cnc_filter():
    settings = Settings(
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
    planner = LegacyPlannerBackend(settings)

    with pytest.raises(PlannerConfirmationRequired) as exc:
        await planner.generate_plan(
            intent="find all CNC machine",
            scoped_tools=[_machine_list_tool_with_filters()],
        )

    assert exc.value.confirmation["kind"] == "predicate_field_confirmation"
    assert {opt["field"] for opt in exc.value.confirmation["options"]} >= {"machine_type", "location"}


@pytest.mark.asyncio
async def test_legacy_planner_confirmation_includes_all_executable_machine_fields():
    settings = Settings(
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
    planner = LegacyPlannerBackend(settings)

    with pytest.raises(PlannerConfirmationRequired) as exc:
        await planner.generate_plan(
            intent="find all Coating Station Machines",
            scoped_tools=[_machine_list_tool_with_filters()],
        )

    confirmation = exc.value.confirmation
    fields = [opt["field"] for opt in confirmation["options"]]
    assert fields == [opt["field"] for opt in confirmation["all_options"]]
    assert set(fields) >= {"machine_name", "machine_type", "location"}
    assert "status" not in fields


@pytest.mark.asyncio
async def test_legacy_planner_uses_data_evidence_for_confirmation_options(respx_mock):
    settings = Settings(
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
    planner = LegacyPlannerBackend(settings)
    respx_mock.get(
        "http://testserver/machines",
        params={"machine_type": "Coating Station", "limit": "25"},
    ).respond(200, json={"success": True, "data": [
        {"machine_id": "M-CTG-01", "machine_type": "Coating Station"},
        {"machine_id": "M-CTG-02", "machine_type": "Coating Station"},
    ]})
    respx_mock.get(
        "http://testserver/machines",
        params={"machine_name": "Coating Station", "limit": "25"},
    ).respond(200, json={"success": True, "data": [
        {"machine_id": "M-CTG-01", "machine_name": "Coating Station 01"},
        {"machine_id": "M-CTG-02", "machine_name": "Coating Station 02"},
    ]})
    respx_mock.get(
        "http://testserver/machines",
        params={"location": "Coating Station", "limit": "25"},
    ).respond(200, json={"success": True, "data": []})

    with pytest.raises(PlannerConfirmationRequired) as exc:
        await planner.generate_plan(
            intent="find all Coating Station Machines",
            scoped_tools=[_machine_list_tool_with_filters()],
        )

    confirmation = exc.value.confirmation
    assert {opt["field"] for opt in confirmation["options"]} == {"machine_name", "machine_type"}
    assert {opt["field"] for opt in confirmation["other_possible_fields"]} == {"location"}
    assert all(opt["match_count"] == 2 for opt in confirmation["options"])
    assert confirmation["other_possible_fields"][0]["match_count"] == 0


@pytest.mark.asyncio
async def test_data_evidence_overrides_stale_predicate_memory(respx_mock):
    settings = Settings(
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
    planner = LegacyPlannerBackend(settings)
    respx_mock.get(
        "http://testserver/machines",
        params={"location": "Coating Station", "limit": "25"},
    ).respond(200, json={"success": True, "data": []})
    respx_mock.get(
        "http://testserver/machines",
        params={"machine_type": "Coating Station", "limit": "25"},
    ).respond(200, json={"success": True, "data": [
        {"machine_id": "M-CTG-01", "machine_type": "Coating Station"},
    ]})
    respx_mock.get(
        "http://testserver/machines",
        params={"machine_name": "Coating Station", "limit": "25"},
    ).respond(200, json={"success": True, "data": [
        {"machine_id": "M-CTG-01", "machine_name": "Coating Station 01"},
    ]})

    with pytest.raises(PlannerConfirmationRequired) as exc:
        await planner.generate_plan(
            intent="find all Coating Station Machines",
            scoped_tools=[_machine_list_tool_with_filters()],
            context={
                "intent_memory": {
                    "positive_bindings": [
                        {
                            "entity": "machine",
                            "term": "Coating Station",
                            "field": "location",
                            "value": "Coating Station",
                        }
                    ]
                }
            },
        )

    confirmation = exc.value.confirmation
    assert {opt["field"] for opt in confirmation["options"]} == {"machine_name", "machine_type"}
    assert {opt["field"] for opt in confirmation["other_possible_fields"]} == {"location"}
