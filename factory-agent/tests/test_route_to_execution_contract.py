from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from factory_agent.config import get_settings
from factory_agent.graph.builder import compile_planner_graph
from factory_agent.graph.planner_graph import _initial_planner_state
from factory_agent.planning.intent import semantic_frame_for_text
from factory_agent.planning.tool_selector import ToolSelector
from factory_agent.schemas import ToolInfo


def _settings(**overrides: Any):
    return replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        enable_parallel_execution=False,
        graph_checkpoint_backend="off",
        max_plan_steps=8,
        **overrides,
    )


def _tool(
    name: str,
    *,
    endpoint: str,
    tags: list[str],
    method: str = "GET",
    required: list[str] | None = None,
    query_params: list[str] | None = None,
) -> ToolInfo:
    required = list(required or [])
    properties = {field: {"type": "string"} for field in required}
    for field in query_params or []:
        field_type = "integer" if field == "limit" else "string"
        properties.setdefault(field, {"type": field_type})
        if field == "priority":
            properties[field]["enum"] = ["high", "medium", "low"]
        elif field == "sort_by":
            properties[field]["enum"] = ["deadline", "created_at", "priority"]
        elif field == "sort_dir":
            properties[field]["enum"] = ["asc", "desc"]
    return ToolInfo(
        name=name,
        description=name.replace("_", " "),
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        input_schema={"type": "object", "required": required, "properties": properties},
        path_params=[field for field in required if f"{{{field}}}" in endpoint],
        query_params=list(query_params or []),
        param_sources={field: "path" for field in required if f"{{{field}}}" in endpoint},
        is_read_only=method == "GET",
        capability_tags=tags,
        requires_approval=method != "GET",
    )


def _machine_tool() -> ToolInfo:
    return _tool(
        "get__machines_{id}",
        endpoint="/machines/{id}",
        tags=["machine", "lookup", "status"],
        required=["id"],
    )


def _job_lookup_tool() -> ToolInfo:
    return _tool("get__jobs_{id}", endpoint="/jobs/{id}", tags=["job", "lookup"], required=["id"])


def _job_list_tool() -> ToolInfo:
    return _tool(
        "get__jobs",
        endpoint="/jobs",
        tags=["job", "list"],
        query_params=["priority", "fields", "sort_by", "sort_dir", "limit"],
    )


def _parse_current_intent_id(prompt: str) -> str:
    marker = "Current intent JSON: "
    start = prompt.index(marker) + len(marker)
    end = prompt.index("\nUser query:", start)
    return str(json.loads(prompt[start:end])["intent_id"])


async def _run_route_contract(
    monkeypatch: pytest.MonkeyPatch,
    *,
    prompt: str,
    tools: list[ToolInfo],
    first_tool_name: str,
    first_args: dict[str, Any],
    complete_summary: str = "Requested read completed.",
) -> dict[str, Any]:
    tools_by_name = {tool.name: tool for tool in tools}
    selector = ToolSelector(_settings())
    selection = await selector.select_tools(intent=prompt, tools_by_name=tools_by_name, max_tools=8)
    scoped_tools = [tools_by_name[name] for name in selection.tool_names if name in tools_by_name]

    model_payloads: list[dict[str, Any]] = []

    class FakeModel:
        async def ainvoke(self, planner_prompt: str):
            intent_id = _parse_current_intent_id(planner_prompt)
            if '"tool_name"' in planner_prompt.split("Recent tool_outputs (last up to 4):", 1)[1].split("\nfailed_strategies:", 1)[0]:
                payload = {
                    "intent_id": intent_id,
                    "kind": "intent_completed",
                    "tool_calls": [],
                    "control_action": None,
                    "decision_summary": complete_summary,
                    "risk_level": "read",
                }
            else:
                payload = {
                    "intent_id": intent_id,
                    "kind": "domain_tool",
                    "tool_calls": [{"tool_name": first_tool_name, "args": dict(first_args)}],
                    "control_action": None,
                    "decision_summary": "Querying the status of slot for machine M-CNC-01.",
                    "risk_level": "read",
                }
            model_payloads.append(payload)
            return AIMessage(content=json.dumps(payload))

    executed: list[dict[str, Any]] = []

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key):
        executed.append({"tool_name": tool.name, "args": dict(args)})
        data = {"id": args.get("id"), **dict(args)}
        if "machine" in tool.name:
            data.update({"machine_id": args.get("id") or args.get("machine_id"), "status": "RUNNING"})
        if "jobs" in tool.name:
            data.update({"job_id": args.get("id") or args.get("job_id"), "priority": args.get("priority", "high")})
        return {"ok": True, "http_status": 200, "body": {"data": data}, "latency_ms": 1}

    monkeypatch.setattr(
        "factory_agent.graph.nodes.planner_loop.build_planner_chat_model",
        lambda settings, json_mode=True: FakeModel(),
    )
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.execute_tool_http", fake_execute_tool_http)

    graph = compile_planner_graph(_settings())
    result = await graph.ainvoke(
        _initial_planner_state(intent=prompt, scoped_tools=scoped_tools, context={"session_id": "route-contract"}),
        config={"recursion_limit": 48, "configurable": {"thread_id": f"route-contract-{abs(hash(prompt))}"}},
    )
    return {
        "frame": semantic_frame_for_text(prompt),
        "selection": selection,
        "result": result,
        "executed": executed,
        "model_payloads": model_payloads,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        "What is the status of M-CNC-01?",
        "Show status for machine M-CNC-01",
        "Is M-CNC-01 running?",
        "What is the current condition of m-cnc-01?",
        "Show machine M-CNC-01 health",
    ],
)
async def test_machine_status_route_reaches_execution_with_preserved_machine_id(monkeypatch, prompt):
    contract = await _run_route_contract(
        monkeypatch,
        prompt=prompt,
        tools=[_machine_tool(), _job_lookup_tool(), _job_list_tool()],
        first_tool_name="get__machines_{id}",
        first_args={"id": "5"},
        complete_summary="Machine status read completed.",
    )

    assert contract["frame"].route == "tool.read.machine_status"
    assert contract["selection"].tool_names == ["get__machines_{id}"]
    assert contract["executed"] == [{"tool_name": "get__machines_{id}", "args": {"id": "M-CNC-01"}}]

    result = contract["result"]
    assert result["status"] == "completed"
    assert result["validated_plan"].steps[0].tool_name == "get__machines_{id}"
    assert result["validated_plan"].steps[0].args == {"id": "M-CNC-01"}
    assert any(
        action.get("phase") == "decision_guard" and action.get("kind") == "constraint_repair"
        for action in result["completed_actions"]
    )
    assert not any(
        action.get("phase") == "decision_guard" and action.get("kind") == "constraint_violation"
        for action in result["completed_actions"]
    )


@pytest.mark.asyncio
async def test_job_status_route_reaches_execution_without_machine_repair(monkeypatch):
    contract = await _run_route_contract(
        monkeypatch,
        prompt="What is the status of job JOB-SEED-001?",
        tools=[_machine_tool(), _job_lookup_tool(), _job_list_tool()],
        first_tool_name="get__jobs_{id}",
        first_args={"id": "JOB-SEED-999"},
        complete_summary="Job status read completed.",
    )

    assert contract["frame"].route == "tool.read.jobs"
    assert contract["selection"].tool_names == ["get__jobs_{id}"]
    assert contract["executed"] == [{"tool_name": "get__jobs_{id}", "args": {"id": "JOB-SEED-001"}}]
    assert contract["result"]["validated_plan"].steps[0].args == {"id": "JOB-SEED-001"}


@pytest.mark.asyncio
async def test_machine_details_route_uses_same_read_tool_without_status_word():
    prompt = "Show full details for machine with machine id M-CNC-01"
    tools = {_machine_tool().name: _machine_tool(), _job_lookup_tool().name: _job_lookup_tool()}
    selector = ToolSelector(_settings())
    selection = await selector.select_tools(intent=prompt, tools_by_name=tools, max_tools=8)
    frame = semantic_frame_for_text(prompt)

    assert frame.route == "tool.read.machine_status"
    assert frame.domain_intent == "machine_query"
    assert frame.normalized_entities["machine_id"] == ["M-CNC-01"]
    assert selection.tool_names == ["get__machines_{id}"]


@pytest.mark.asyncio
async def test_multi_job_status_route_terminates_with_typed_multi_read_repair(monkeypatch):
    prompt = "find status for job with job id JOB-SEED-001 and JOB-SEED-002"
    contract = await _run_route_contract(
        monkeypatch,
        prompt=prompt,
        tools=[_machine_tool(), _job_lookup_tool(), _job_list_tool()],
        first_tool_name="get__jobs_{id}",
        first_args={"id": "JOB-SEED-999"},
        complete_summary="Job statuses read completed.",
    )

    assert contract["frame"].route == "tool.read.jobs"
    assert contract["frame"].normalized_entities["job_id"] == ["JOB-SEED-001", "JOB-SEED-002"]
    assert contract["selection"].tool_names == ["get__jobs_{id}"]
    assert contract["executed"] == [
        {"tool_name": "get__jobs_{id}", "args": {"id": "JOB-SEED-001"}},
        {"tool_name": "get__jobs_{id}", "args": {"id": "JOB-SEED-002"}},
    ]
    assert contract["result"]["status"] == "completed"
    assert not contract["result"].get("errors")
    assert not any(
        item.get("kind") == "typed_diagnostic" and item.get("reason") == "constraint_violation_loop"
        for item in contract["result"].get("failed_strategies", [])
        if isinstance(item, dict)
    )


@pytest.mark.asyncio
async def test_job_list_route_preserves_read_filter(monkeypatch):
    contract = await _run_route_contract(
        monkeypatch,
        prompt="Show high priority jobs",
        tools=[_machine_tool(), _job_lookup_tool(), _job_list_tool()],
        first_tool_name="get__jobs",
        first_args={"priority": "high", "fields": "job_id,priority", "limit": 100},
        complete_summary="High priority jobs read completed.",
    )

    assert contract["frame"].route == "tool.read.jobs"
    assert contract["selection"].tool_names[:2] == ["get__jobs", "get__jobs_{id}"]
    assert contract["executed"] == [
        {
            "tool_name": "get__jobs",
            "args": {"priority": "high", "fields": "job_id,priority", "limit": 100},
        }
    ]


@pytest.mark.asyncio
async def test_hard_query_job_list_preserves_fields_sort_and_limit(monkeypatch):
    contract = await _run_route_contract(
        monkeypatch,
        prompt="List low priority jobs, only job id and deadline, sorted by deadline ascending, limit 3.",
        tools=[_machine_tool(), _job_lookup_tool(), _job_list_tool()],
        first_tool_name="get__jobs",
        first_args={"priority": "low"},
        complete_summary="Low priority jobs read completed.",
    )

    expected_args = {
        "priority": "low",
        "fields": "job_id,deadline",
        "sort_by": "deadline",
        "sort_dir": "asc",
        "limit": 3,
    }
    assert contract["frame"].route == "tool.read.jobs"
    assert contract["selection"].tool_names[:2] == ["get__jobs", "get__jobs_{id}"]
    assert contract["executed"] == [{"tool_name": "get__jobs", "args": expected_args}]
    assert contract["result"]["validated_plan"].steps[0].args == expected_args


@pytest.mark.asyncio
async def test_hard_query_multi_read_selection_unions_clause_tools():
    prompt = "Show M-CNC-01 status, then show JOB-SEED-001 status, then list the next 3 low priority jobs sorted by deadline."
    tools = {
        tool.name: tool
        for tool in [
            _machine_tool(),
            _job_lookup_tool(),
            _job_list_tool(),
        ]
    }
    selector = ToolSelector(_settings())

    selection = await selector.select_tools(intent=prompt, tools_by_name=tools, max_tools=8)

    assert selection.tool_names[:3] == ["get__machines_{id}", "get__jobs_{id}", "get__jobs"]


@pytest.mark.asyncio
async def test_loto_route_bypasses_live_machine_status_tools():
    prompt = "What LOTO procedure applies before working on M-CNC-01?"
    tools = {_machine_tool().name: _machine_tool(), _job_lookup_tool().name: _job_lookup_tool()}
    selector = ToolSelector(_settings())
    selection = await selector.select_tools(intent=prompt, tools_by_name=tools, max_tools=8)
    frame = semantic_frame_for_text(prompt)

    assert frame.route == "rag.loto_procedure"
    assert "tool.read.machine_status" in (frame.negative_route_assertions or [])
    assert selection.tool_names == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected_route", "expected_question_type"),
    [
        (
            "According to the LOTO procedure, what notification is required before starting lockout",
            "rag.procedure",
            "document_content_question",
        ),
        (
            "What does the LOTO procedure say about notifying affected employees?",
            "rag.procedure",
            "document_content_question",
        ),
        (
            "Before lockout, who needs to be notified according to LOTO?",
            "rag.procedure",
            "document_content_question",
        ),
        (
            "What are the notification requirements before lockout/tagout?",
            "rag.procedure",
            "document_content_question",
        ),
        (
            "According to OSHA LOTO guidance, what notification is required before lockout?",
            "rag.safety_policy",
            "safety_policy_question",
        ),
    ],
)
async def test_loto_document_content_routes_to_rag_without_machine_id_clarification(
    prompt,
    expected_route,
    expected_question_type,
):
    tools = {_machine_tool().name: _machine_tool(), _job_lookup_tool().name: _job_lookup_tool()}
    selector = ToolSelector(_settings())
    selection = await selector.select_tools(intent=prompt, tools_by_name=tools, max_tools=8)
    frame = semantic_frame_for_text(prompt)

    assert frame.route == expected_route
    assert frame.question_type == expected_question_type
    assert frame.missing_required_entities == []
    assert "machine_id" not in frame.normalized_entities
    assert "tool.read.machine_status" in (frame.negative_route_assertions or [])
    assert selection.tool_names == []


@pytest.mark.asyncio
async def test_repeated_decision_guard_failures_emit_typed_diagnostic(monkeypatch):
    job_tool = _job_lookup_tool()

    class BadModel:
        async def ainvoke(self, planner_prompt: str):
            intent_id = _parse_current_intent_id(planner_prompt)
            return AIMessage(
                content=json.dumps(
                    {
                        "intent_id": intent_id,
                        "kind": "domain_tool",
                        "tool_calls": [{"tool_name": "get__jobs_{id}", "args": {"id": "JOB-SEED-001"}}],
                        "control_action": None,
                        "decision_summary": "Wrong domain repair.",
                        "risk_level": "read",
                    }
                )
            )

    monkeypatch.setattr(
        "factory_agent.graph.nodes.planner_loop.build_planner_chat_model",
        lambda settings, json_mode=True: BadModel(),
    )

    graph = compile_planner_graph(_settings(max_repair_attempts=2))
    result = await graph.ainvoke(
        _initial_planner_state(
            intent="Use machine M-001",
            scoped_tools=[job_tool],
            context={"session_id": "bounded-guard-loop"},
        ),
        config={"recursion_limit": 24, "configurable": {"thread_id": "bounded-guard-loop"}},
    )

    assert result["status"] == "failed"
    assert "decision_guard_constraint_repair_limit" in result["errors"]
    assert any(
        item.get("kind") == "typed_diagnostic" and item.get("reason") == "constraint_violation_loop"
        for item in result["failed_strategies"]
    )
