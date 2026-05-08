import pytest

from agent.config import Settings
from agent.schemas import ToolInfo
from agent.tool_selector import ToolSelector


def _settings(**overrides):
    base = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=1,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=2.0,
    )
    values = base.__dict__.copy()
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_selector_prefers_canonical_create_endpoint_for_generic_create_intent():
    selector = ToolSelector(_settings(tool_selector_backend="retrieval", tool_selector_top_k=5))
    tools = {
        "post__machines": ToolInfo(
            name="post__machines",
            description="Create a machine",
            endpoint="/machines",
            method="POST",
            input_schema={
                "type": "object",
                "properties": {
                    "machine_id": {"type": "string"},
                    "machine_name": {"type": "string"},
                    "machine_type": {"type": "string"},
                },
                "required": ["machine_id", "machine_name", "machine_type"],
            },
            body_fields=["machine_id", "machine_name", "machine_type"],
            required_body_fields=["machine_id", "machine_name", "machine_type"],
            is_read_only=False,
            requires_approval=True,
            capability_tags=["machine", "create"],
        ),
        "post__machines_downtime": ToolInfo(
            name="post__machines_downtime",
            description="Record downtime",
            endpoint="/machines/downtime",
            method="POST",
            input_schema={
                "type": "object",
                "properties": {"machine_id": {"type": "string"}},
                "required": ["machine_id"],
            },
            body_fields=["machine_id"],
            required_body_fields=["machine_id"],
            is_read_only=False,
            requires_approval=True,
            capability_tags=["machine", "create", "downtime"],
        ),
    }

    selected = await selector.select_tools(intent="create new machine", tools_by_name=tools, mode="normal", max_tools=10)
    assert selected.backend_used == "retrieval"
    assert selected.tool_names[0] == "post__machines"


@pytest.mark.asyncio
async def test_selector_plan_mode_keeps_read_only_candidates():
    selector = ToolSelector(_settings(tool_selector_backend="retrieval", tool_selector_top_k=5))
    tools = {
        "get__machines": ToolInfo(
            name="get__machines",
            description="List machines",
            endpoint="/machines",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "list"],
        ),
        "post__machines": ToolInfo(
            name="post__machines",
            description="Create a machine",
            endpoint="/machines",
            method="POST",
            input_schema={"type": "object", "properties": {"machine_name": {"type": "string"}}, "required": ["machine_name"]},
            body_fields=["machine_name"],
            required_body_fields=["machine_name"],
            is_read_only=False,
            requires_approval=True,
            capability_tags=["machine", "create"],
        ),
    }

    selected = await selector.select_tools(intent="create new machine", tools_by_name=tools, mode="plan", max_tools=10)
    assert selected.tool_names == ["get__machines"]


def test_selector_compact_index_contains_name_and_summary():
    selector = ToolSelector(_settings())
    tools = {
        "post__machines": ToolInfo(
            name="post__machines",
            description="Create a machine",
            endpoint="/machines",
            method="POST",
            input_schema={"type": "object", "properties": {"machine_name": {"type": "string"}}, "required": ["machine_name"]},
            body_fields=["machine_name"],
            required_body_fields=["machine_name"],
            is_read_only=False,
            requires_approval=True,
            capability_tags=["machine", "create"],
        )
    }

    compact = selector.build_compact_tool_index(tools)
    assert len(compact) == 1
    assert compact[0]["name"] == "post__machines"
    assert "required: machine_name" in compact[0]["summary"]


@pytest.mark.asyncio
async def test_selector_prefers_specialized_report_endpoint_over_entity_insight():
    selector = ToolSelector(_settings(tool_selector_backend="retrieval", tool_selector_top_k=5))
    tools = {
        "get__reports_machine-utilization": ToolInfo(
            name="get__reports_machine-utilization",
            description="Machine utilization",
            endpoint="/reports/machine-utilization",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "list", "utilization"],
        ),
        "get__machines_utilization": ToolInfo(
            name="get__machines_utilization",
            description="Get machine utilization",
            endpoint="/machines/utilization",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "list", "utilization"],
        ),
    }

    selected = await selector.select_tools(
        intent="show machine utilization report",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )

    assert selected.tool_names[0] == "get__reports_machine-utilization"


@pytest.mark.asyncio
async def test_selector_adds_delete_preflight_companion():
    selector = ToolSelector(_settings(tool_selector_backend="retrieval", tool_selector_top_k=1))
    tools = {
        "delete__jobs_{id}": ToolInfo(
            name="delete__jobs_{id}",
            description="Delete a job",
            endpoint="/jobs/{id}",
            method="DELETE",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=False,
            requires_approval=True,
            capability_tags=["job", "delete"],
        ),
        "get__jobs_{id}": ToolInfo(
            name="get__jobs_{id}",
            description="Get a job",
            endpoint="/jobs/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "lookup"],
        ),
    }

    selected = await selector.select_tools(
        intent="delete job JOB-1",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )

    assert selected.tool_names[:2] == ["delete__jobs_{id}", "get__jobs_{id}"]


@pytest.mark.asyncio
async def test_selector_routes_reference_type_requests_to_reference_tools():
    selector = ToolSelector(_settings(tool_selector_backend="retrieval", tool_selector_top_k=5))
    tools = {
        "get__machines": ToolInfo(
            name="get__machines",
            description="List machines",
            endpoint="/machines",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "list"],
        ),
        "get__reference_machine-types": ToolInfo(
            name="get__reference_machine-types",
            description="List machine types",
            endpoint="/reference/machine-types",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["reference", "machine", "type", "list"],
        ),
        "get__products": ToolInfo(
            name="get__products",
            description="List products",
            endpoint="/products",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["product", "list"],
        ),
        "get__reference_product-types": ToolInfo(
            name="get__reference_product-types",
            description="List product types",
            endpoint="/reference/product-types",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["reference", "product", "type", "list"],
        ),
    }

    machine_selected = await selector.select_tools(
        intent="list machine types",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )
    product_selected = await selector.select_tools(
        intent="list product types",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )

    assert machine_selected.tool_names == ["get__reference_machine-types"]
    assert product_selected.tool_names == ["get__reference_product-types"]


@pytest.mark.asyncio
async def test_selector_routes_direct_read_ids_to_lookup_tools():
    selector = ToolSelector(_settings(tool_selector_backend="retrieval", tool_selector_top_k=5))
    tools = {
        "get__jobs": ToolInfo(
            name="get__jobs",
            description="List jobs",
            endpoint="/jobs",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "list"],
        ),
        "post__jobs": ToolInfo(
            name="post__jobs",
            description="Create job",
            endpoint="/jobs",
            method="POST",
            input_schema={"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]},
            is_read_only=False,
            requires_approval=True,
            capability_tags=["job", "create"],
        ),
        "get__jobs_{id}": ToolInfo(
            name="get__jobs_{id}",
            description="Get job",
            endpoint="/jobs/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "lookup"],
        ),
        "get__machines": ToolInfo(
            name="get__machines",
            description="List machines",
            endpoint="/machines",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "list"],
        ),
        "get__machines_{id}": ToolInfo(
            name="get__machines_{id}",
            description="Get machine",
            endpoint="/machines/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "lookup"],
        ),
        "get__inventory_materials": ToolInfo(
            name="get__inventory_materials",
            description="List materials",
            endpoint="/inventory/materials",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["material", "list"],
        ),
        "get__inventory_materials_{id}": ToolInfo(
            name="get__inventory_materials_{id}",
            description="Get material",
            endpoint="/inventory/materials/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["material", "lookup"],
        ),
        "get__ai_scheduling_proposals_{id}": ToolInfo(
            name="get__ai_scheduling_proposals_{id}",
            description="Get proposal",
            endpoint="/ai/scheduling/proposals/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["proposal", "lookup"],
        ),
    }

    job_selected = await selector.select_tools(intent="show job JOB-NOT-REAL", tools_by_name=tools, mode="normal", max_tools=10)
    machine_selected = await selector.select_tools(intent="show machine M-CNC-01", tools_by_name=tools, mode="normal", max_tools=10)
    numeric_machine_selected = await selector.select_tools(intent="check machine 5 status", tools_by_name=tools, mode="normal", max_tools=10)
    material_selected = await selector.select_tools(intent="show material MAT-002", tools_by_name=tools, mode="normal", max_tools=10)
    proposal_selected = await selector.select_tools(intent="show proposal AIPROP-SEED-001", tools_by_name=tools, mode="normal", max_tools=10)

    assert job_selected.tool_names == ["get__jobs_{id}"]
    assert machine_selected.tool_names == ["get__machines_{id}"]
    assert numeric_machine_selected.tool_names == ["get__machines_{id}"]
    assert material_selected.tool_names == ["get__inventory_materials_{id}"]
    assert proposal_selected.tool_names == ["get__ai_scheduling_proposals_{id}"]


@pytest.mark.asyncio
async def test_path_token_boost_prefers_specific_subresource_over_root_collection():
    """Regression for factory-reroute-recommendations and similar long-tail
    sub-resources. When the user phrase contains tokens that match a tool's
    multi-segment URL path (e.g. ``"reroute recommendations"`` matches
    ``/machines/reroute-recommendations``), that tool must rank above the
    broader collection endpoint (``/machines``).
    """
    selector = ToolSelector(
        _settings(
            tool_selector_backend="retrieval",
            tool_selector_top_k=5,
            tool_selector_candidate_pool=8,
        )
    )
    tools = {
        "get__machines": ToolInfo(
            name="get__machines",
            description="List machines",
            endpoint="/machines",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "list"],
        ),
        "get__machines_reroute-recommendations": ToolInfo(
            name="get__machines_reroute-recommendations",
            description="Get reroute recommendations for machines",
            endpoint="/machines/reroute-recommendations",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "reroute", "recommendation"],
        ),
        "get__predictive_recommendations": ToolInfo(
            name="get__predictive_recommendations",
            description="Predictive maintenance recommendations",
            endpoint="/predictive/recommendations",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["predictive", "recommendation"],
        ),
        "get__scheduling_solver-preview": ToolInfo(
            name="get__scheduling_solver-preview",
            description="Preview scheduling solver result for a job",
            endpoint="/scheduling/solver-preview",
            method="GET",
            input_schema={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
            is_read_only=True,
            requires_approval=False,
            capability_tags=["scheduling", "solver", "preview"],
        ),
        "get__jobs": ToolInfo(
            name="get__jobs",
            description="List jobs",
            endpoint="/jobs",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "list"],
        ),
    }

    reroute = await selector.select_tools(
        intent="show machine reroute recommendations",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )
    predictive = await selector.select_tools(
        intent="show predictive recommendations",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )
    solver = await selector.select_tools(
        intent="solver preview for job JOB-SEED-001",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )

    assert reroute.tool_names[0] == "get__machines_reroute-recommendations"
    assert predictive.tool_names[0] == "get__predictive_recommendations"
    assert solver.tool_names[0] == "get__scheduling_solver-preview"


@pytest.mark.asyncio
async def test_path_token_boost_disabled_falls_back_to_baseline():
    """When TOOL_SELECTOR_PATH_TOKEN_WEIGHT=0 the boost is fully disabled, so
    legacy ranking behaviour is preserved (used for safe rollback).
    """
    selector = ToolSelector(
        _settings(
            tool_selector_backend="retrieval",
            tool_selector_top_k=5,
            tool_selector_candidate_pool=8,
            tool_selector_path_token_weight=0,
        )
    )
    tools = {
        "get__machines": ToolInfo(
            name="get__machines",
            description="List machines",
            endpoint="/machines",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "list"],
        ),
        "get__machines_reroute-recommendations": ToolInfo(
            name="get__machines_reroute-recommendations",
            description="Get reroute recommendations for machines",
            endpoint="/machines/reroute-recommendations",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "reroute", "recommendation"],
        ),
    }
    result = await selector.select_tools(
        intent="show machine reroute recommendations",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )
    # With the boost disabled, both tools should appear but ordering reverts
    # to the legacy heuristic; we only assert both are present.
    assert "get__machines_reroute-recommendations" in result.tool_names
    assert "get__machines" in result.tool_names


@pytest.mark.asyncio
async def test_compound_intent_bypasses_diagnostic_shortcuts():
    """Regression: ``_diagnostic_tool_names`` short-circuits used to fire on the
    first regex hit, returning a single tool and starving later clauses of
    their tools. For compound intents (``"... and then ..."``) the selector
    must skip those shortcuts and let normal retrieval score every clause's
    tools so each step of the plan can pick the right tool.
    """
    selector = ToolSelector(
        _settings(
            tool_selector_backend="retrieval",
            tool_selector_top_k=5,
            tool_selector_candidate_pool=8,
        )
    )
    tools = {
        "get__machines_{id}": ToolInfo(
            name="get__machines_{id}",
            description="Get machine by id",
            endpoint="/machines/{id}",
            method="GET",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "status"],
        ),
        "get__jobs_{id}_slots": ToolInfo(
            name="get__jobs_{id}_slots",
            description="Get available slots for a job",
            endpoint="/jobs/{id}/slots",
            method="GET",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            path_params=["id"],
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "schedule", "slot"],
        ),
    }
    result = await selector.select_tools(
        intent="Check machine M-LTH-02 status and then show slots for JOB-SEED-001",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )
    # Both clauses must contribute their tool to the selection. Without the
    # compound-intent guard, only ``get__machines_{id}`` would be returned
    # because ``_direct_lookup_tool_names`` matches "Check machine M-LTH-02"
    # before the second clause is ever considered.
    assert "get__machines_{id}" in result.tool_names
    assert "get__jobs_{id}_slots" in result.tool_names


@pytest.mark.asyncio
async def test_selector_skips_reranker_when_clear_winner_exists(monkeypatch):
    selector = ToolSelector(
        _settings(
            tool_selector_backend="langchain",
            tool_selector_top_k=5,
            tool_selector_candidate_pool=8,
            tool_selector_reranker_enabled=True,
            openai_api_key="test-key",
        )
    )
    tools = {
        "get__reports_machine-utilization": ToolInfo(
            name="get__reports_machine-utilization",
            description="Machine utilization report",
            endpoint="/reports/machine-utilization",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "utilization", "report"],
        ),
        "get__machines_utilization": ToolInfo(
            name="get__machines_utilization",
            description="Machine utilization",
            endpoint="/machines/utilization",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["machine", "utilization"],
        ),
    }

    called = {"count": 0}

    async def _fake_invoke_reranker(*, prompt: str):
        called["count"] += 1
        return {"primary_tool": "get__machines_utilization", "additional_tools": [], "confidence": 1.0, "reason": "forced"}

    monkeypatch.setattr(selector, "_invoke_reranker", _fake_invoke_reranker)

    result = await selector.select_tools(
        intent="show machine utilization report",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )

    assert called["count"] == 0
    assert result.backend_used == "retrieval"
    assert result.tool_names[0] == "get__reports_machine-utilization"


@pytest.mark.asyncio
async def test_selector_respects_disabled_reranker_even_when_trace_forced(monkeypatch):
    selector = ToolSelector(
        _settings(
            tool_selector_backend="auto",
            tool_selector_top_k=5,
            tool_selector_candidate_pool=8,
            tool_selector_reranker_enabled=False,
            force_llm_trace_all=True,
            tool_selector_openai_base_url="http://selector.test/v1",
            openai_api_key="test-key",
        )
    )
    tools = {
        "get__jobs_{id}": ToolInfo(
            name="get__jobs_{id}",
            description="Get a job by ID",
            endpoint="/jobs/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "lookup"],
        ),
        "get__ai_scheduling_jobs_{id}_explanation": ToolInfo(
            name="get__ai_scheduling_jobs_{id}_explanation",
            description="Explanation",
            endpoint="/ai/scheduling/jobs/{id}/explanation",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["ai", "scheduling", "job", "explanation"],
        ),
    }
    called = {"count": 0}

    async def _fake_invoke_reranker(*, prompt: str):
        called["count"] += 1
        return {"primary_tool": "get__jobs_{id}", "additional_tools": [], "confidence": 1.0, "reason": "forced"}

    monkeypatch.setattr(selector, "_invoke_reranker", _fake_invoke_reranker)

    result = await selector.select_tools(
        intent="explain schedule for job JOB-SEED-003",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )

    assert called["count"] == 0
    assert result.backend_used == "retrieval"
    assert result.tool_names[0] == "get__ai_scheduling_jobs_{id}_explanation"


@pytest.mark.asyncio
async def test_selector_prefers_feature_specific_job_explanation_endpoint():
    selector = ToolSelector(
        _settings(
            tool_selector_backend="retrieval",
            tool_selector_top_k=6,
            tool_selector_candidate_pool=12,
            tool_selector_path_token_weight=4,
        )
    )
    tools = {
        "get__jobs_{id}": ToolInfo(
            name="get__jobs_{id}",
            description="Get a job by ID",
            endpoint="/jobs/{id}",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "lookup"],
        ),
        "get__jobs_{id}_slots": ToolInfo(
            name="get__jobs_{id}_slots",
            description="List slots by job ID",
            endpoint="/jobs/{id}/slots",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["job", "slot", "lookup", "list"],
        ),
        "get__ai_scheduling_jobs_{id}_explanation": ToolInfo(
            name="get__ai_scheduling_jobs_{id}_explanation",
            description="Explanation",
            endpoint="/ai/scheduling/jobs/{id}/explanation",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            is_read_only=True,
            requires_approval=False,
            capability_tags=["ai", "scheduling", "job", "explanation"],
        ),
        "post__jobs": ToolInfo(
            name="post__jobs",
            description="Create a job",
            endpoint="/jobs",
            method="POST",
            input_schema={"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]},
            is_read_only=False,
            requires_approval=True,
            capability_tags=["job", "create"],
        ),
    }

    result = await selector.select_tools(
        intent="explain schedule for job JOB-SEED-003",
        tools_by_name=tools,
        mode="normal",
        max_tools=10,
    )

    assert result.tool_names[0] == "get__ai_scheduling_jobs_{id}_explanation"
