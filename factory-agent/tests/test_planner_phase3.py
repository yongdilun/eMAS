"""Phase 3: planner loop guard and reducers."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage

from factory_agent.config import get_settings
from factory_agent.graph.builder import compile_planner_graph
from factory_agent.graph.nodes.planner_loop import make_planner_node
from factory_agent.graph.nodes.planner_loop import decision_guard_node
from factory_agent.graph.planner_graph import _initial_planner_state
from factory_agent.graph.state import AgentState
from factory_agent.schemas import ToolInfo


def _settings():
    return replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        enable_parallel_execution=False,
        graph_checkpoint_backend="off",
        max_plan_steps=8,
    )


def _tool(name: str, endpoint: str = "/test") -> ToolInfo:
    return ToolInfo(
        name=name,
        description=name,
        endpoint=endpoint,
        method="GET",
        input_schema={"type": "object"},
        is_read_only=True,
    )


def test_decision_guard_blocks_hard_constraint_mismatch():
    state: AgentState = {
        "original_query": "Use machine M-001",
        "intent": "Use machine M-001",
        "messages": [],
        "scoped_tools": [],
        "context": {},
        "current_intent": {
            "intent_id": "i1",
            "description": "check machine",
            "explicit_constraints": [
                {"field": "machine_id", "operator": "=", "value": "M-001", "strength": "hard"},
            ],
            "status": "in_progress",
        },
        "pending_decision": {
            "intent_id": "i1",
            "kind": "domain_tool",
            "tool_calls": [{"tool_name": "get__machines", "args": {"machine_id": "M-002"}}],
            "decision_summary": "wrong id",
        },
    }
    out = decision_guard_node(state)
    assert out["next_route"] == "continue_planner"
    pd = out.get("pending_decision")
    assert isinstance(pd, dict)
    assert pd.get("violates_constraints") is True
    assert pd.get("tool_calls") == []
    assert out["failed_strategies"][0]["reason"] == "constraint_violation"


def test_decision_guard_passes_matching_constraint():
    state: AgentState = {
        "original_query": "Use machine M-001",
        "intent": "Use machine M-001",
        "messages": [],
        "scoped_tools": [],
        "context": {},
        "current_intent": {
            "intent_id": "i1",
            "description": "check machine",
            "explicit_constraints": [
                {"field": "machine_id", "operator": "=", "value": "M-001", "strength": "hard"},
            ],
            "status": "in_progress",
        },
        "pending_decision": {
            "intent_id": "i1",
            "kind": "domain_tool",
            "tool_calls": [{"tool_name": "get__machines", "args": {"machine_id": "M-001"}}],
            "decision_summary": "ok",
        },
    }
    out = decision_guard_node(state)
    assert out["next_route"] == "tool_execution"


def test_decision_guard_passes_machine_ref_constraint_for_machine_id_path_arg():
    state: AgentState = {
        "original_query": "Check machine 5 status",
        "intent": "Check machine 5 status",
        "messages": [],
        "scoped_tools": [
            ToolInfo(
                name="get__machines_{id}",
                description="Get machine by ID",
                endpoint="/machines/{id}",
                method="GET",
                input_schema={
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                },
                path_params=["id"],
                param_sources={"id": "path"},
                is_read_only=True,
            )
        ],
        "context": {},
        "current_intent": {
            "intent_id": "i1",
            "description": "Check machine 5 status",
            "explicit_constraints": [
                {"field": "machine_ref", "operator": "=", "value": "5", "strength": "hard"},
            ],
            "status": "in_progress",
        },
        "pending_decision": {
            "intent_id": "i1",
            "kind": "domain_tool",
            "tool_calls": [{"tool_name": "get__machines_{id}", "args": {"id": "5"}}],
            "decision_summary": "lookup machine",
        },
    }

    out = decision_guard_node(state)

    assert out["next_route"] == "tool_execution"


def test_decision_guard_blocks_wrong_machine_ref_for_machine_id_path_arg():
    state: AgentState = {
        "original_query": "Check machine 5 status",
        "intent": "Check machine 5 status",
        "messages": [],
        "scoped_tools": [
            ToolInfo(
                name="get__machines_{id}",
                description="Get machine by ID",
                endpoint="/machines/{id}",
                method="GET",
                input_schema={
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                },
                path_params=["id"],
                param_sources={"id": "path"},
                is_read_only=True,
            )
        ],
        "context": {},
        "current_intent": {
            "intent_id": "i1",
            "description": "Check machine 5 status",
            "explicit_constraints": [
                {"field": "machine_ref", "operator": "=", "value": "5", "strength": "hard"},
            ],
            "status": "in_progress",
        },
        "pending_decision": {
            "intent_id": "i1",
            "kind": "domain_tool",
            "tool_calls": [{"tool_name": "get__machines_{id}", "args": {"id": "6"}}],
            "decision_summary": "lookup wrong machine",
        },
    }

    out = decision_guard_node(state)

    assert out["next_route"] == "continue_planner"
    assert out["failed_strategies"][0]["reason"] == "constraint_violation"


def test_decision_guard_does_not_apply_machine_ref_alias_to_other_entity_id_path():
    state: AgentState = {
        "original_query": "Check machine 5 status",
        "intent": "Check machine 5 status",
        "messages": [],
        "scoped_tools": [
            ToolInfo(
                name="get__jobs_{id}",
                description="Get job by ID",
                endpoint="/jobs/{id}",
                method="GET",
                input_schema={
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                },
                path_params=["id"],
                param_sources={"id": "path"},
                is_read_only=True,
            )
        ],
        "context": {},
        "current_intent": {
            "intent_id": "i1",
            "description": "Check machine 5 status",
            "explicit_constraints": [
                {"field": "machine_ref", "operator": "=", "value": "5", "strength": "hard"},
            ],
            "status": "in_progress",
        },
        "pending_decision": {
            "intent_id": "i1",
            "kind": "domain_tool",
            "tool_calls": [{"tool_name": "get__jobs_{id}", "args": {"id": "5"}}],
            "decision_summary": "wrong entity lookup",
        },
    }

    out = decision_guard_node(state)

    assert out["next_route"] == "continue_planner"
    assert out["failed_strategies"][0]["reason"] == "constraint_violation"


@pytest.mark.asyncio
async def test_read_only_not_found_result_completes_intent_without_clarification(monkeypatch):
    tool = ToolInfo(
        name="get__machines_{id}",
        description="Get machine by ID",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
        },
        path_params=["id"],
        param_sources={"id": "path"},
        is_read_only=True,
    )
    model_calls = 0

    class FakeModel:
        async def ainvoke(self, prompt: str):
            nonlocal model_calls
            model_calls += 1
            if model_calls > 1:
                raise AssertionError("planner should not ask the model to repair a completed not-found lookup")
            marker = "Current intent JSON: "
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\nUser query:", start)
            intent_id = json.loads(prompt[start:end])["intent_id"]
            return AIMessage(
                content=json.dumps(
                    {
                        "intent_id": intent_id,
                        "kind": "domain_tool",
                        "tool_calls": [{"tool_name": "get__machines_{id}", "args": {"id": "5"}}],
                        "control_action": None,
                        "decision_summary": "Lookup machine 5.",
                        "risk_level": "read",
                    }
                )
            )

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key):
        return {
            "ok": False,
            "http_status": 404,
            "body": {"detail": "machine not found"},
            "latency_ms": 1,
            "infrastructure_error": False,
        }

    monkeypatch.setattr(
        "factory_agent.graph.nodes.planner_loop.build_planner_chat_model",
        lambda settings, json_mode=True: FakeModel(),
    )
    monkeypatch.setattr(
        "factory_agent.graph.nodes.tool_pipeline.execute_tool_http",
        fake_execute_tool_http,
    )

    graph = compile_planner_graph(_settings())
    result = await graph.ainvoke(
        _initial_planner_state(
            intent="Check machine 5 status",
            scoped_tools=[tool],
            context={},
        ),
        config={"recursion_limit": 64, "configurable": {"thread_id": "not-found-test"}},
    )

    assert result.get("clarification") in (None, "")
    assert result.get("status") == "completed"
    assert model_calls == 1
    assert result["validated_plan"].steps[0].tool_name == "get__machines_{id}"
    assert result["validated_plan"].steps[0].args == {"id": "5"}


@pytest.mark.asyncio
async def test_graph_processes_multi_intent_through_planner_loop(monkeypatch):
    tools = [_tool("get__machines", "/machines"), _tool("get__jobs", "/jobs")]
    calls: list[dict[str, object]] = []
    responses = [
        {
            "kind": "domain_tool",
            "tool_calls": [{"tool_name": "get__machines", "args": {"machine_id": "M-002"}}],
            "decision_summary": "Try the wrong machine first.",
        },
        {
            "kind": "domain_tool",
            "tool_calls": [{"tool_name": "get__machines", "args": {"machine_id": "M-001"}}],
            "decision_summary": "Use the constrained machine.",
        },
        {
            "kind": "intent_completed",
            "tool_calls": [],
            "decision_summary": "Machine check complete.",
        },
        {
            "kind": "domain_tool",
            "tool_calls": [{"tool_name": "get__jobs", "args": {}}],
            "decision_summary": "List jobs after the machine check.",
        },
        {
            "kind": "intent_completed",
            "tool_calls": [],
            "decision_summary": "Job list complete.",
        },
    ]

    class FakeModel:
        async def ainvoke(self, prompt: str):
            marker = "Current intent JSON: "
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\nUser query:", start)
            intent_id = json.loads(prompt[start:end])["intent_id"]
            payload = dict(responses.pop(0))
            payload["intent_id"] = intent_id
            return AIMessage(content=json.dumps(payload))

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key):
        calls.append({"tool_name": tool.name, "args": dict(args)})
        return {
            "ok": True,
            "http_status": 200,
            "body": {"data": [{"tool": tool.name, "args": args}]},
            "latency_ms": 1,
        }

    monkeypatch.setattr(
        "factory_agent.graph.nodes.planner_loop.build_planner_chat_model",
        lambda settings, json_mode=True: FakeModel(),
    )
    monkeypatch.setattr(
        "factory_agent.graph.nodes.tool_pipeline.execute_tool_http",
        fake_execute_tool_http,
    )

    state = _initial_planner_state(
        intent="Find available machine M-001 and then list jobs",
        scoped_tools=tools,
        context={"session_id": "phase3-multi-intent"},
    )
    graph = compile_planner_graph(_settings())
    result = await graph.ainvoke(
        state,
        config={"recursion_limit": 64, "configurable": {"thread_id": "phase3-multi-intent"}},
    )

    assert result["status"] == "completed"
    assert [c["tool_name"] for c in calls] == ["get__machines", "get__jobs"]
    assert calls[0]["args"] == {"machine_id": "M-001"}
    assert all(c["args"] != {"machine_id": "M-002"} for c in calls)
    assert result["validated_plan"].steps[0].tool_name == "get__machines"
    assert result["validated_plan"].steps[1].tool_name == "get__jobs"
    guard_entries = [a for a in result["completed_actions"] if a.get("phase") == "decision_guard"]
    assert guard_entries and guard_entries[0]["kind"] == "constraint_violation"
    assert any(d["kind"] == "intent_completed" for d in result["decisions"])
    assert all(it["status"] == "completed" for it in result["working_intents"])


@pytest.mark.asyncio
async def test_planner_cancels_dependent_intents_when_upstream_fails(monkeypatch):
    class FakeModel:
        async def ainvoke(self, prompt: str):
            marker = "Current intent JSON: "
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\nUser query:", start)
            intent_id = json.loads(prompt[start:end])["intent_id"]
            return AIMessage(
                content=json.dumps(
                    {
                        "intent_id": intent_id,
                        "kind": "intent_failed",
                        "tool_calls": [],
                        "decision_summary": "Upstream intent cannot be completed.",
                    }
                )
            )

    monkeypatch.setattr(
        "factory_agent.graph.nodes.planner_loop.build_planner_chat_model",
        lambda settings, json_mode=True: FakeModel(),
    )
    node = make_planner_node(_settings())
    state: AgentState = {
        "original_query": "Find available machine M-001 and then list jobs",
        "intent": "Find available machine M-001 and then list jobs",
        "messages": [],
        "scoped_tools": [_tool("get__machines"), _tool("get__jobs")],
        "context": {},
        "working_intents": [
            {
                "intent_id": "intent-a",
                "description": "Find available machine M-001",
                "depends_on": [],
                "explicit_constraints": [],
                "status": "pending",
                "category": "machine",
            },
            {
                "intent_id": "intent-b",
                "description": "list jobs",
                "depends_on": ["intent-a"],
                "explicit_constraints": [],
                "status": "pending",
                "category": "job",
            },
        ],
        "intent_cursor": 0,
        "planner_iteration": 0,
        "tool_outputs": [],
        "completed_actions": [],
        "failed_strategies": [],
        "decisions": [],
    }

    out = await node(state)

    assert out["next_route"] == "synthesize_plan"
    assert out["working_intents"][0]["status"] == "failed"
    assert out["working_intents"][1]["status"] == "cancelled_due_to_dependency_failure"
    assert out["working_intents"][1]["failure_reason"] == "Upstream intent cannot be completed."
    assert out["completed_actions"][0]["kind"] == "intent_failed"
