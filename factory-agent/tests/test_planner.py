import pytest

from agent.config import Settings
from agent.planner import (
    LangChainPlannerBackend,
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


@pytest.mark.asyncio
async def test_planner_adapter_langchain_backend_falls_back_to_legacy_when_unavailable(monkeypatch):
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

    result = await adapter.generate_plan(
        intent="Check machine 5 status",
        scoped_tools=[tool],
        context=None,
    )

    assert result.backend_used == "legacy"
    assert len(result.draft.steps) == 1
    assert result.draft.steps[0].tool_name == "get__machines_{id}"
    assert result.draft.steps[0].args == {"id": "5"}


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
async def test_planner_adapter_structured_backend_falls_back_to_legacy(monkeypatch):
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

    result = await adapter.generate_plan(
        intent="Check machine 5 status",
        scoped_tools=[tool],
        context=None,
    )

    assert result.backend_used == "legacy"
    assert result.draft.steps[0].tool_name == "get__machines_{id}"
    assert result.draft.steps[0].args == {"id": "5"}


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
