import pytest
from dataclasses import replace
import json
from langchain_core.messages import AIMessage

from factory_agent.config import Settings
from factory_agent.graph.errors import LangGraphPlannerClarification
import factory_agent.graph.nodes.reason as reason_module
from factory_agent.graph.nodes.planner_loop import decision_guard_node, make_planner_node
from factory_agent.graph.nodes.reason import make_reason_node
from factory_agent.graph.nodes.validate import _dedupe_identical_readonly_steps, make_validate_node
from factory_agent.graph.planner_graph import _approval_payload_from_state, _not_found_clarification_from_state
from factory_agent.graph.planner_graph_helpers import (
    _deterministic_plan_repair,
    _normalize_plan_dict,
)
from factory_agent.graph.state import AgentPlanOutput, AgentPlanStep
from factory_agent.graph.errors import LangGraphPlannerError
from factory_agent.planner import (
    PlannerAdapter,
    PlannerBackendError,
    PlannerPlanRejected,
    PlannerService,
    _assign_parallel_groups,
    _dedupe_plan_steps,
)
from factory_agent.schemas import PlanBinding, PlanDraft, PlanStepDraft, ToolInfo
from factory_agent.registry.tool_registry import ToolRegistry

from tests.graph_state_fixtures import stub_agent_state


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
async def test_planner_service_maps_langgraph_validation_error_to_plan_rejected(monkeypatch):
    """M3: Invalid graph outcome is a client-visible 400, not a bogus 503."""
    settings = _settings()
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())
    tool = _read_tool("get__machines", "/machines")

    class BadOutcomePlanner:
        def __init__(self, settings):
            pass

        async def generate(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            raise LangGraphPlannerError("LangGraph planner did not return a validated PlanDraft.")

    monkeypatch.setattr(PlannerService, "_langgraph_planner_cls", BadOutcomePlanner)

    with pytest.raises(PlannerPlanRejected):
        await adapter.generate_plan(intent="show machines", scoped_tools=[tool])


@pytest.mark.asyncio
async def test_planner_service_maps_transient_langgraph_error_to_backend_error(monkeypatch):
    settings = _settings()
    adapter = PlannerAdapter(settings=settings, tool_registry=ToolRegistry())
    tool = _read_tool("get__machines", "/machines")

    class TimeoutPlanner:
        def __init__(self, settings):
            pass

        async def generate(self, *, intent, scoped_tools, context=None):
            del intent, scoped_tools, context
            err = LangGraphPlannerError("upstream stalled")
            err.__cause__ = TimeoutError()
            raise err

    monkeypatch.setattr(PlannerService, "_langgraph_planner_cls", TimeoutPlanner)

    with pytest.raises(PlannerBackendError):
        await adapter.generate_plan(intent="show machines", scoped_tools=[tool])


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
            return draft, {"backend": "langgraph"}, []

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
    state = stub_agent_state(
        query=intent,
        scoped_tools=tools,
        plan_blueprint=AgentPlanOutput(
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
    )

    result = _run_validate(settings, state)

    draft = result["validated_plan"]
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
    state = stub_agent_state(
        query="delete test job TEST-E2E-factory-delete",
        scoped_tools=tools,
        plan_blueprint=AgentPlanOutput(
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
    )

    result = _run_validate(settings, state)

    draft = result["validated_plan"]
    assert [step.tool_name for step in draft.steps] == ["get__jobs_{id}", "delete__jobs_{id}"]
    assert [step.step_index for step in draft.steps] == [0, 1]
    assert all(step.args == {"id": "TEST-E2E-factory-delete"} for step in draft.steps)
    assert draft.steps[1].depends_on == [0]
    assert [step["tool_name"] for step in result["intent_contract"]["steps"]] == ["get__jobs_{id}", "delete__jobs_{id}"]


def test_decision_guard_strips_unsupported_optional_defaults_before_execution():
    tool = ToolInfo(
        name="get__reference_storage-locations",
        description="List storage locations",
        endpoint="/reference/storage-locations",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "type": {"type": "string"},
                "sort_by": {"type": "string"},
                "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
                "fields": {"type": "string"},
            },
        },
        query_params=["q", "type", "sort_by", "sort_dir", "limit", "offset", "fields"],
        param_sources={
            "q": "query",
            "type": "query",
            "sort_by": "query",
            "sort_dir": "query",
            "limit": "query",
            "offset": "query",
            "fields": "query",
        },
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        capability_tags=["reference", "storage", "location"],
    )
    state = stub_agent_state(query="list storage locations", scoped_tools=[tool])
    state["pending_decision"] = {
        "intent_id": "intent-1",
        "kind": "domain_tool",
        "tool_calls": [
            {
                "tool_name": "get__reference_storage-locations",
                "args": {
                    "q": "",
                    "type": "",
                    "sort_by": "",
                    "sort_dir": "",
                    "limit": 10,
                    "offset": 0,
                    "fields": "",
                },
            }
        ],
        "decision_summary": "List storage locations.",
        "risk_level": "read",
    }

    out = decision_guard_node(state)

    assert out["next_route"] == "tool_execution"
    assert out["pending_decision"]["tool_calls"][0]["args"] == {}


def test_decision_guard_repairs_alias_constraint_violation():
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
        body_fields=["status"],
        param_sources={"id": "path", "status": "body"},
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
        capability_tags=["machine", "update"],
    )
    state = stub_agent_state(query="set machine M-LTH-02 to maintenance", scoped_tools=[tool])
    state["current_intent"] = {
        "intent_id": "intent-1",
        "description": "set machine M-LTH-02 to maintenance",
        "explicit_constraints": [
            {"field": "machine_ref", "operator": "=", "value": "M-LTH-02", "strength": "hard"}
        ],
    }
    state["pending_decision"] = {
        "intent_id": "intent-1",
        "kind": "domain_tool",
        "tool_calls": [{"tool_name": "put__machines_{id}", "args": {"machine_id": "M-LTH-02", "status": "maintenance"}}],
        "decision_summary": "Update machine.",
        "risk_level": "write_dry_run",
    }

    out = decision_guard_node(state)

    assert out["next_route"] == "tool_execution"
    assert out["pending_decision"]["tool_calls"][0]["args"] == {"id": "M-LTH-02", "status": "maintenance"}


def test_decision_guard_repairs_mixed_case_delete_id_constraint():
    tools = [
        _write_tool("delete__jobs_{id}", "/jobs/{id}", "DELETE"),
        ToolInfo(
            name="get__jobs_{id}",
            description="Get job",
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
    state = stub_agent_state(query="delete test job TEST-E2E-factory-delete", scoped_tools=tools)
    state["current_intent"] = {
        "intent_id": "intent-delete",
        "description": "delete test job TEST-E2E-factory-delete",
        "explicit_constraints": [
            {
                "field": "job_id",
                "operator": "=",
                "value": "TEST-E2E-FACTORY-DELETE",
                "strength": "hard",
            }
        ],
    }
    state["pending_decision"] = {
        "intent_id": "intent-delete",
        "kind": "domain_tool",
        "tool_calls": [{"tool_name": "delete__jobs_{id}", "args": {}}],
        "decision_summary": "Delete the job.",
        "risk_level": "write_dry_run",
    }

    out = decision_guard_node(state)

    assert out["next_route"] == "tool_execution"
    assert out["pending_decision"]["tool_calls"][0]["args"] == {"id": "TEST-E2E-FACTORY-DELETE"}


def test_langgraph_generate_fallback_detects_approval_pause_state():
    payload = _approval_payload_from_state(
        {
            "staged_writes": [
                {
                    "tool_name": "post__jobs",
                    "output_ref": "$ref:job",
                    "args": {"product_id": "P-005", "quantity_total": 2},
                }
            ],
            "bundle_dry_run_result": {"ok": True, "http_status": 200},
        }
    )

    assert payload is not None
    assert payload["kind"] == "approval_required"
    assert payload["preview"][0]["tool_name"] == "post__jobs"
    assert "post__jobs" in payload["summary"]


def test_langgraph_generate_fallback_detects_not_found_dry_run():
    clarification = _not_found_clarification_from_state(
        {
            "staged_writes": [{"tool_name": "put__machines_{id}", "args": {"id": "M-NOT-REAL"}}],
            "bundle_dry_run_result": {
                "ok": False,
                "http_status": 404,
                "body": {"error": "machine not found: M-NOT-REAL"},
            },
        }
    )

    assert clarification == "machine not found: M-NOT-REAL"


@pytest.mark.asyncio
async def test_planner_routes_staged_writes_to_synthesis_without_llm():
    planner = make_planner_node(_settings())
    state = stub_agent_state(query="create job for product P-001 quantity 2", scoped_tools=[])
    state["staged_writes"] = [{"tool_name": "post__jobs", "args": {"product_id": "P-001", "quantity_total": 2}}]

    out = await planner(state)

    assert out["next_route"] == "synthesize_plan"
    assert out["status"] == "validating"


@pytest.mark.asyncio
async def test_planner_repairs_empty_write_decision(monkeypatch):
    settings = replace(_settings(), openai_api_key="test-key")
    tool = ToolInfo(
        name="post__jobs",
        description="Create a job",
        endpoint="/jobs",
        method="POST",
        input_schema={
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "quantity_total": {"type": "integer"}},
            "required": ["product_id", "quantity_total"],
        },
        body_fields=["product_id", "quantity_total"],
        param_sources={"product_id": "body", "quantity_total": "body"},
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
        capability_tags=["job", "create"],
    )

    class EmptyWriteModel:
        async def ainvoke(self, prompt):
            marker = "Current intent JSON: "
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\nUser query:", start)
            intent_id = json.loads(prompt[start:end])["intent_id"]
            return AIMessage(
                content=json.dumps(
                    {
                        "intent_id": intent_id,
                        "kind": "request_approval",
                        "tool_calls": [],
                        "decision_summary": "Approval required.",
                        "risk_level": "write_dry_run",
                    }
                )
            )

    monkeypatch.setattr("factory_agent.graph.nodes.planner_loop.build_planner_chat_model", lambda *_args, **_kwargs: EmptyWriteModel())
    planner = make_planner_node(settings)
    state = stub_agent_state(query="create job for product P-005 quantity 2", scoped_tools=[tool])

    out = await planner(state)

    assert out["next_route"] == "decision_guard"
    calls = out["pending_decision"]["tool_calls"]
    assert calls[0]["tool_name"] == "post__jobs"
    assert calls[0]["args"] == {"product_id": "P-005", "quantity_total": 2}


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


def test_normalize_plan_dict_drops_incomplete_binding_objects():
    """Bindings with only from_step should be discarded instead of failing schema validation."""
    raw = {
        "plan_explanation": "ok",
        "risk_summary": "low",
        "steps": [
            {
                "tool_name": "get__jobs_{id}",
                "args": {"id": "JOB-SEED-001"},
                "evidence": {"id": "JOB-SEED-001"},
                "confidence": 0.9,
            },
            {
                "tool_name": "get__ai_scheduling_jobs_{id}_proposal",
                "args": {"id": "JOB-SEED-001"},
                "evidence": {"id": "JOB-SEED-001"},
                "confidence": 0.8,
                "depends_on": [0],
                "bindings": [{"from_step": 0}],
            },
        ],
    }

    normalized = _normalize_plan_dict(raw)
    plan = AgentPlanOutput.model_validate(normalized)

    assert len(plan.steps) == 2
    assert plan.steps[1].depends_on == [0]
    assert plan.steps[1].bindings == []


def test_normalize_plan_dict_repairs_binding_alias_fields():
    """Common alias keys should be normalized into a valid PlanBinding."""
    raw = {
        "plan_explanation": "ok",
        "risk_summary": "low",
        "steps": [
            {
                "tool_name": "get__jobs",
                "args": {},
                "evidence": {},
                "confidence": 0.9,
            },
            {
                "tool_name": "get__jobs_{id}",
                "args": {},
                "evidence": {},
                "confidence": 0.7,
                "bindings": [
                    {
                        "from_step": "get__jobs",
                        "result_path": "",
                        "source_field": "job_id",
                        "arg": "id",
                        "mode": "bad-mode",
                    }
                ],
            },
        ],
    }

    normalized = _normalize_plan_dict(raw)
    plan = AgentPlanOutput.model_validate(normalized)

    assert len(plan.steps[1].bindings) == 1
    binding = plan.steps[1].bindings[0]
    assert binding.from_step == 0
    assert binding.result_path == "data"
    assert binding.field == "job_id"
    assert binding.target_arg == "id"
    assert binding.mode == "single"


def test_validate_node_empty_plan_returns_clarification():
    """Empty step_drafts should always preserve user-facing clarification behavior."""
    settings = _settings()
    state = stub_agent_state(
        query="list machines",
        scoped_tools=[_read_tool("get__machines", "/machines")],
        plan_blueprint=AgentPlanOutput(
            plan_explanation="",
            risk_summary="",
            steps=[],
        ),
    )

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
    state = stub_agent_state(
        query="explosion for product P-001",
        scoped_tools=tools,
        plan_blueprint=AgentPlanOutput(
            plan_explanation="",
            risk_summary="",
            steps=[],
        ),
    )

    result = _run_validate(settings, state)

    draft = result["validated_plan"]
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
    state = stub_agent_state(
        query="show JOB-SEED-001 and its slots",
        scoped_tools=tools,
        plan_blueprint=AgentPlanOutput(
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
    )

    result = _run_validate(settings, state)

    draft = result["validated_plan"]
    assert [step.tool_name for step in draft.steps] == ["get__jobs_{id}", "get__jobs_{id}_slots"]
    assert draft.steps[0].args == {"id": "JOB-SEED-001"}
    assert draft.steps[1].args == {"id": "JOB-SEED-001"}
    assert draft.steps[1].depends_on == [0]


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
    state = stub_agent_state(
        query="show JOB-SEED-001 and its slots",
        scoped_tools=tools,
        plan_blueprint=AgentPlanOutput(
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
    )

    result = _run_validate(settings, state)

    draft = result["validated_plan"]
    assert [step.tool_name for step in draft.steps] == ["get__jobs_{id}", "get__jobs_{id}_slots"]
    assert draft.steps[0].args == {"id": "JOB-SEED-001"}
    assert draft.steps[1].args == {"id": "JOB-SEED-001"}
    assert draft.steps[1].depends_on == [0]


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
            return draft, {"steps": []}, []

    monkeypatch.setattr(PlannerService, "_langgraph_planner_cls", FakeLGPlanner)

    result = await adapter.generate_plan(
        intent="find all low priority job and find all low priority job",
        scoped_tools=[_jobs_list_tool()],
    )

    assert len(result.draft.steps) == 1
    assert result.draft.steps[0].step_index == 0
    assert result.draft.steps[0].tool_name == "get__jobs"
    assert result.draft.steps[0].args == {"priority": "low"}


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


def test_dedupe_identical_readonly_steps_uses_clean_args_key():
    """Read-only steps with identical normalized args (validator key) collapse to one."""
    tool = _read_tool("get__products", "/products")
    tools_by_name = {tool.name: tool}
    drafts = [
        PlanStepDraft(step_index=0, tool_name="get__products", args={}, depends_on=[], bindings=[]),
        PlanStepDraft(step_index=1, tool_name="get__products", args={}, depends_on=[0], bindings=[]),
    ]
    contracts: list[dict] = [
        {"step_index": 0, "tool_name": "get__products", "args": {}},
        {"step_index": 1, "tool_name": "get__products", "args": {}},
    ]
    out_d, out_c = _dedupe_identical_readonly_steps(
        drafts, contracts, tools_by_name, intent="list products"
    )
    assert len(out_d) == 1
    assert len(out_c) == 1
    assert out_d[0].step_index == 0
    assert out_d[0].tool_name == "get__products"


def test_langgraph_repair_expands_show_job_and_slots_to_two_steps():
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
            description="Get job slots",
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

    repaired = _deterministic_plan_repair("show JOB-SEED-001 and its slots", tools)

    assert repaired is not None
    assert [step.tool_name for step in repaired.steps] == ["get__jobs_{id}", "get__jobs_{id}_slots"]
    assert repaired.steps[0].args == {"id": "JOB-SEED-001"}
    assert repaired.steps[1].args == {"id": "JOB-SEED-001"}
    assert repaired.steps[1].depends_on == [0]


def test_langgraph_repair_uses_context_for_pronoun_followup_slots():
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
            description="Get job slots",
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
    context = {
        "intent_contract": {
            "intent": "show job JOB-SEED-001",
            "backend": "langgraph",
            "steps": [
                {
                    "step_index": 0,
                    "tool_name": "get__jobs_{id}",
                    "args": {"id": "JOB-SEED-001"},
                }
            ],
        }
    }

    repaired = _deterministic_plan_repair("now show its slots", tools, context=context)

    assert repaired is not None
    assert [step.tool_name for step in repaired.steps] == ["get__jobs_{id}", "get__jobs_{id}_slots"]
    assert repaired.steps[0].args == {"id": "JOB-SEED-001"}
    assert repaired.steps[1].args == {"id": "JOB-SEED-001"}
    assert repaired.steps[1].depends_on == [0]


def test_langgraph_repair_keeps_pronoun_followup_unresolved_without_context():
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
            description="Get job slots",
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

    repaired = _deterministic_plan_repair("now show its slots", tools)

    assert repaired is None


def test_langgraph_repair_expands_product_and_followup_read_via_entity_id_field():
    tools = [
        ToolInfo(
            name="get__products_{id}",
            description="Get product",
            endpoint="/products/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["product", "lookup"],
        ),
        ToolInfo(
            name="get__scheduling_explosion",
            description="Explosion for product",
            endpoint="/scheduling/explosion",
            method="GET",
            input_schema={"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]},
            query_params=["product_id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["scheduling", "explosion", "product"],
        ),
    ]

    repaired = _deterministic_plan_repair("show product P-001 and its explosion", tools)

    assert repaired is not None
    assert [step.tool_name for step in repaired.steps] == ["get__products_{id}", "get__scheduling_explosion"]
    assert repaired.steps[0].args == {"id": "P-001"}
    assert repaired.steps[1].args == {"product_id": "P-001"}
    assert repaired.steps[1].depends_on == [0]


def test_langgraph_repair_does_not_force_single_entity_followup_for_multi_entity_compound():
    tools = [
        ToolInfo(
            name="get__machines_{id}",
            description="Get machine",
            endpoint="/machines/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["machine", "lookup"],
        ),
        ToolInfo(
            name="get__jobs_{id}_slots",
            description="Get slots",
            endpoint="/jobs/{id}/slots",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["job", "slot"],
        ),
    ]

    repaired = _deterministic_plan_repair(
        "check machine M-LTH-02 status and then show slots for JOB-SEED-001",
        tools,
    )
    assert repaired is not None
    assert [step.tool_name for step in repaired.steps] == ["get__jobs_{id}_slots"]


def test_langgraph_repair_prefers_metadata_matched_child_read_before_generic_lookup():
    tools = [
        ToolInfo(
            name="work_order_reader",
            description="Read work order",
            endpoint="/work-orders/{id}",
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
            name="work_order_window_reader",
            description="Read inspection windows for a work order",
            endpoint="/work-orders/{id}/inspection-windows",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=["job", "inspection", "window", "lookup", "list"],
        ),
    ]

    repaired = _deterministic_plan_repair("show inspection windows for job JOB-SEED-001", tools)

    assert repaired is not None
    assert [step.tool_name for step in repaired.steps] == ["work_order_window_reader"]
    assert repaired.steps[0].args == {"id": "JOB-SEED-001"}


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
            return draft, contract, []

    monkeypatch.setattr(PlannerService, "_langgraph_planner_cls", FakeLGPlanner)

    result = await adapter.generate_plan(
        intent="find all high priority job",
        scoped_tools=[_jobs_list_tool()],
    )

    assert result.draft.steps[0].args == {"priority": "high"}


@pytest.mark.asyncio
async def test_reason_node_invalid_schema_uses_deterministic_repair(monkeypatch):
    settings = replace(_settings(), openai_api_key="test-key")
    reason_node = make_reason_node(settings)
    scoped_tool = _read_tool("get__jobs_{id}", "/jobs/{id}")

    class _Resp:
        def __init__(self, content: str):
            self.content = content

    class _Model:
        async def ainvoke(self, prompt: str):
            del prompt
            return _Resp('{"steps":[{"tool_name":"get__jobs_{id}","args":{"id":"JOB-SEED-001"}}]}')

    monkeypatch.setattr(reason_module, "build_planner_chat_model", lambda settings, json_mode=True: _Model())
    monkeypatch.setattr(reason_module, "parse_agent_plan_output", lambda parsed: (_ for _ in ()).throw(ValueError("bad schema")))
    monkeypatch.setattr(
        reason_module,
        "_deterministic_plan_repair",
        lambda intent, scoped_tools, context=None: AgentPlanOutput(
            plan_explanation="repair",
            risk_summary="repair-risk",
            steps=[AgentPlanStep(tool_name="get__jobs_{id}", args={"id": "JOB-SEED-001"})],
        ),
    )

    out = await reason_node(
        stub_agent_state(
            query="show job JOB-SEED-001",
            scoped_tools=[scoped_tool],
            tool_cards=[],
        )
    )

    assert out["plan_blueprint"] is not None
    assert [step.tool_name for step in out["plan_blueprint"].steps] == ["get__jobs_{id}"]
    assert out["risk_summary"] == "repair-risk"


@pytest.mark.asyncio
async def test_reason_node_invalid_schema_salvages_supported_steps_when_repair_unavailable(monkeypatch):
    settings = replace(_settings(), openai_api_key="test-key")
    reason_node = make_reason_node(settings)
    scoped_tool = _read_tool("get__jobs_{id}", "/jobs/{id}")

    class _Resp:
        def __init__(self, content: str):
            self.content = content

    class _Model:
        async def ainvoke(self, prompt: str):
            del prompt
            return _Resp(
                '{"plan_explanation":123,"risk_summary":null,"steps":['
                '{"tool_name":"get__jobs_{id}","args":{"id":"JOB-SEED-001"},"depends_on":["0","oops"],"confidence":"0.7"},'
                '{"tool_name":"get__unknown_tool","args":{"id":"X"}}]}'
            )

    monkeypatch.setattr(reason_module, "build_planner_chat_model", lambda settings, json_mode=True: _Model())
    monkeypatch.setattr(reason_module, "parse_agent_plan_output", lambda parsed: (_ for _ in ()).throw(ValueError("bad schema")))
    monkeypatch.setattr(reason_module, "_deterministic_plan_repair", lambda intent, scoped_tools, context=None: None)

    out = await reason_node(
        stub_agent_state(
            query="show job JOB-SEED-001",
            scoped_tools=[scoped_tool],
            tool_cards=[],
        )
    )

    plan = out["plan_blueprint"]
    assert plan is not None
    assert [step.tool_name for step in plan.steps] == ["get__jobs_{id}"]
    assert plan.steps[0].args == {"id": "JOB-SEED-001"}
    assert plan.steps[0].depends_on == []
    assert out["risk_summary"] == "Planner output was partially malformed; unsupported fields were dropped."
