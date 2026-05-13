"""Tests for graph.nodes.tool_pipeline: refs, idempotency, relevance, staging."""

from __future__ import annotations

import pytest

from factory_agent.config import get_settings
from factory_agent.graph.http_tool_client import compute_planner_write_idempotency_key
from factory_agent.graph.nodes.tool_pipeline import (
    fatal_end_node,
    make_relevance_filter_node,
    make_tool_execution_node,
    route_after_tool,
)
from factory_agent.graph.nodes.planner_loop import decision_guard_node
from factory_agent.graph.state import AgentState
from factory_agent.schemas import ToolInfo


def test_compute_planner_write_idempotency_key_stable():
    k1 = compute_planner_write_idempotency_key(
        session_id="s1",
        intent_id="i1",
        action_id="a1",
        tool_name="post__jobs",
        args={"title": "x"},
        write_generation=2,
    )
    k2 = compute_planner_write_idempotency_key(
        session_id="s1",
        intent_id="i1",
        action_id="a1",
        tool_name="post__jobs",
        args={"title": "x"},
        write_generation=2,
    )
    k3 = compute_planner_write_idempotency_key(
        session_id="s1",
        intent_id="i1",
        action_id="a1",
        tool_name="post__jobs",
        args={"title": "y"},
        write_generation=2,
    )
    assert k1 == k2
    assert k1 != k3


def test_decision_guard_rejects_forward_ref():
    write_tool = ToolInfo(
        name="post__x",
        description="w",
        endpoint="/x",
        method="POST",
        input_schema={"type": "object"},
        is_read_only=False,
    )
    state: AgentState = {
        "original_query": "q",
        "intent": "q",
        "messages": [],
        "scoped_tools": [write_tool],
        "context": {},
        "current_intent": {"intent_id": "i1", "explicit_constraints": [], "status": "in_progress"},
        "pending_decision": {
            "intent_id": "i1",
            "decision_id": "d1",
            "kind": "domain_tool",
            "tool_calls": [
                {"tool_name": "post__x", "args": {"job_id": "$ref:post__x_0"}},
            ],
        },
    }
    out = decision_guard_node(state)
    assert out["next_route"] == "continue_planner"
    pd = out.get("pending_decision")
    assert isinstance(pd, dict)
    assert pd.get("tool_calls") == []


def test_decision_guard_same_batch_read_chain_empty_tail():
    """M2: With empty tail, $ref:0 is the first read's output; second read may reference it."""
    jobs_tool = ToolInfo(
        name="get__jobs",
        description="jobs",
        endpoint="/jobs",
        method="GET",
        input_schema={"type": "object"},
        is_read_only=True,
    )
    slots_tool = ToolInfo(
        name="get__jobs_{id}_slots",
        description="slots",
        endpoint="/jobs/{id}/slots",
        method="GET",
        input_schema={"type": "object"},
        path_params=["id"],
        is_read_only=True,
    )
    state: AgentState = {
        "original_query": "q",
        "intent": "q",
        "messages": [],
        "scoped_tools": [jobs_tool, slots_tool],
        "context": {},
        "tool_outputs": [],
        "current_intent": {"intent_id": "i1", "explicit_constraints": [], "status": "in_progress"},
        "pending_decision": {
            "intent_id": "i1",
            "decision_id": "d1",
            "kind": "domain_tool",
            "tool_calls": [
                {"tool_name": "get__jobs", "args": {"status": "scheduled"}},
                {"tool_name": "get__jobs_{id}_slots", "args": {"id": "$ref:0"}},
            ],
        },
    }
    out = decision_guard_node(state)
    assert out["next_route"] == "tool_execution"
    pd = out.get("pending_decision")
    assert isinstance(pd, dict)
    assert pd.get("tool_calls")


def test_decision_guard_accepts_historical_tail_ref():
    """M2: $ref:0 resolves against planner_tool_output_tail (cross-turn memory follow-up)."""
    read_tool = ToolInfo(
        name="get__jobs_{id}_slots",
        description="slots",
        endpoint="/jobs/{id}/slots",
        method="GET",
        input_schema={"type": "object"},
        path_params=["id"],
        is_read_only=True,
    )
    state: AgentState = {
        "original_query": "q",
        "intent": "q",
        "messages": [],
        "scoped_tools": [read_tool],
        "context": {},
        "tool_outputs": [
            {
                "tool_name": "get__jobs_{id}",
                "args": {"id": "JOB-SEED-001"},
                "result": {"job_id": "JOB-SEED-001", "status": "scheduled"},
                "http_status": 200,
            }
        ],
        "tool_outputs_truncated_at": 0,
        "current_intent": {"intent_id": "i1", "explicit_constraints": [], "status": "in_progress"},
        "pending_decision": {
            "intent_id": "i1",
            "decision_id": "d1",
            "kind": "domain_tool",
            "tool_calls": [
                {"tool_name": "get__jobs_{id}_slots", "args": {"id": "$ref:0"}},
            ],
        },
    }
    out = decision_guard_node(state)
    assert out["next_route"] == "tool_execution"
    pd = out.get("pending_decision")
    assert isinstance(pd, dict)
    assert pd.get("tool_calls")


def test_decision_guard_rejects_unknown_read_ref():
    read_tool = ToolInfo(
        name="get__jobs",
        description="jobs",
        endpoint="/jobs/{id}",
        method="GET",
        input_schema={"type": "object"},
        path_params=["id"],
        is_read_only=True,
    )
    state: AgentState = {
        "original_query": "q",
        "intent": "q",
        "messages": [],
        "scoped_tools": [read_tool],
        "context": {},
        "current_intent": {"intent_id": "i1", "explicit_constraints": [], "status": "in_progress"},
        "pending_decision": {
            "intent_id": "i1",
            "decision_id": "d1",
            "kind": "domain_tool",
            "tool_calls": [
                {"tool_name": "get__jobs", "args": {"id": "$ref:missing_job"}},
            ],
        },
    }
    out = decision_guard_node(state)
    assert out["next_route"] == "continue_planner"
    assert out["failed_strategies"][0]["reason"] == "transaction_ref_violation"
    assert out["failed_strategies"][0]["detail"] == "unknown_ref:$ref:missing_job"
    assert out["pending_decision"]["tool_calls"] == []


@pytest.mark.asyncio
async def test_tool_execution_runs_read_and_relevance_appends_normalized_output(monkeypatch):
    settings = get_settings()
    read_tool = ToolInfo(
        name="get__machines",
        description="machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object"},
        is_read_only=True,
    )
    calls: list[dict[str, object]] = []

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key):
        calls.append({"tool_name": tool.name, "args": dict(args), "idempotency_key": idempotency_key})
        return {
            "ok": True,
            "http_status": 200,
            "body": {"data": [{"machine_id": "M-001", "status": "available"}]},
            "latency_ms": 3,
            "infrastructure_error": False,
        }

    monkeypatch.setattr(
        "factory_agent.graph.nodes.tool_pipeline.execute_tool_http",
        fake_execute_tool_http,
    )

    execute = make_tool_execution_node(settings)
    state: AgentState = {
        "session_id": "sess-read",
        "original_query": "find available machines",
        "intent": "find available machines",
        "messages": [],
        "scoped_tools": [read_tool],
        "context": {},
        "write_generation": 0,
        "retrieved_info": {},
        "pending_decision": {
            "intent_id": "i1",
            "decision_id": "d1",
            "kind": "domain_tool",
            "tool_calls": [
                {"tool_name": "get__machines", "args": {"status": "available"}, "tool_call_id": "tc-read"}
            ],
        },
    }
    after_execute = await execute(state)

    assert len(calls) == 1
    assert calls[0]["tool_name"] == "get__machines"
    assert calls[0]["args"] == {"status": "available"}
    assert calls[0]["idempotency_key"]
    assert after_execute["staged_writes"] == []
    assert after_execute["next_route"] == "relevance_filter"
    assert "read:get__machines:tc-read" in after_execute["retrieved_info"]

    relevance = make_relevance_filter_node(settings)
    after_relevance = await relevance(
        {
            **state,
            "pending_relevance_batch": after_execute["pending_relevance_batch"],
            "retrieved_info": after_execute["retrieved_info"],
        }
    )
    outputs = after_relevance["tool_outputs"]
    assert len(outputs) == 1
    assert outputs[0]["tool_name"] == "get__machines"
    assert outputs[0]["result"]["data"][0]["machine_id"] == "M-001"
    assert outputs[0]["useful"] is True
    assert after_relevance["retrieved_info"]["relevance_trace"][0]["tool_name"] == "get__machines"


@pytest.mark.asyncio
async def test_tool_execution_resolves_historical_ref_placeholder(monkeypatch):
    settings = get_settings()
    slots_tool = ToolInfo(
        name="get__jobs_{id}_slots",
        description="slots",
        endpoint="/jobs/{id}/slots",
        method="GET",
        input_schema={"type": "object"},
        path_params=["id"],
        is_read_only=True,
    )
    captured: list[dict[str, object]] = []

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key):
        captured.append(dict(args))
        return {
            "ok": True,
            "http_status": 200,
            "body": {"data": []},
            "latency_ms": 1,
            "infrastructure_error": False,
        }

    monkeypatch.setattr(
        "factory_agent.graph.nodes.tool_pipeline.execute_tool_http",
        fake_execute_tool_http,
    )

    execute = make_tool_execution_node(settings)
    state: AgentState = {
        "session_id": "sess-m2",
        "original_query": "slots",
        "intent": "slots",
        "messages": [],
        "scoped_tools": [slots_tool],
        "context": {},
        "write_generation": 0,
        "retrieved_info": {},
        "tool_outputs": [
            {
                "tool_name": "get__jobs_{id}",
                "args": {"id": "JOB-SEED-001"},
                "result": {"job_id": "JOB-SEED-001"},
                "http_status": 200,
            }
        ],
        "tool_outputs_truncated_at": 0,
        "pending_decision": {
            "intent_id": "i1",
            "decision_id": "d1",
            "kind": "domain_tool",
            "tool_calls": [
                {"tool_name": "get__jobs_{id}_slots", "args": {"id": "$ref:0"}, "tool_call_id": "tc-slots"}
            ],
        },
    }
    await execute(state)
    assert len(captured) == 1
    assert captured[0]["id"] == "JOB-SEED-001"


@pytest.mark.asyncio
async def test_tool_execution_stages_writes_without_http(monkeypatch):
    settings = get_settings()
    write_tool = ToolInfo(
        name="post__jobs",
        description="create",
        endpoint="/jobs",
        method="POST",
        input_schema={"type": "object"},
        is_read_only=False,
    )

    async def fail_if_http_called(settings, tool, args, *, idempotency_key):
        raise AssertionError("write tools must not call backend HTTP during graph planning")

    monkeypatch.setattr(
        "factory_agent.graph.nodes.tool_pipeline.execute_tool_http",
        fail_if_http_called,
    )

    node = make_tool_execution_node(settings)
    state: AgentState = {
        "session_id": "sess-1",
        "original_query": "create job",
        "intent": "create job",
        "messages": [],
        "scoped_tools": [write_tool],
        "context": {},
        "write_generation": 0,
        "retrieved_info": {},
        "pending_decision": {
            "intent_id": "i1",
            "decision_id": "d1",
            "kind": "domain_tool",
            "tool_calls": [{"tool_name": "post__jobs", "args": {"title": "J1"}, "tool_call_id": "tc-aaa"}],
        },
    }
    out = await node(state)
    assert out.get("next_route") == "relevance_filter"
    assert out.get("fatal_system_error") is None
    staged = out.get("staged_writes") or []
    assert len(staged) == 1
    assert staged[0].get("tool_name") == "post__jobs"
    assert staged[0].get("idempotency_key")
    assert staged[0].get("output_ref", "").startswith("$ref:")
    assert out.get("pending_relevance_batch") == []


@pytest.mark.asyncio
async def test_relevance_filter_empty_and_404():
    settings = get_settings()
    rf = make_relevance_filter_node(settings)
    empty = await rf({"pending_relevance_batch": [], "retrieved_info": {}})
    assert empty["next_route"] == "continue_planner"

    state = {
        "original_query": "find machine",
        "intent": "find machine",
        "pending_relevance_batch": [
            {
                "tool_name": "get__machines",
                "tool_call_id": "t1",
                "args": {"id": "x"},
                "result": {"error": "nf"},
                "http_status": 404,
            }
        ],
        "scoped_tools": [
            ToolInfo(
                name="get__machines",
                description="m",
                endpoint="/machines/{id}",
                method="GET",
                input_schema={"type": "object"},
                path_params=["id"],
                is_read_only=True,
            )
        ],
        "retrieved_info": {},
    }
    out = await rf(state)
    assert out["next_route"] == "continue_planner"
    to = out.get("tool_outputs") or []
    assert to and to[0].get("useful") is False


@pytest.mark.asyncio
async def test_relevance_filter_uses_semantic_only_when_tool_requires_it(monkeypatch):
    settings = get_settings()
    calls: list[str] = []

    async def fake_semantic(settings, *, tool_name: str, user_query: str, body: dict):
        calls.append(tool_name)
        return True, "semantic_pass"

    monkeypatch.setattr(
        "factory_agent.graph.nodes.tool_pipeline._semantic_useful",
        fake_semantic,
    )

    normal = ToolInfo(
        name="get__machines",
        description="machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object"},
        is_read_only=True,
    )
    semantic = ToolInfo(
        name="get__reports",
        description="report",
        endpoint="/reports",
        method="GET",
        input_schema={"type": "object"},
        is_read_only=True,
        requires_semantic_filter=True,
    )
    rf = make_relevance_filter_node(settings)
    out = await rf(
        {
            "original_query": "which report matters",
            "intent": "which report matters",
            "scoped_tools": [normal, semantic],
            "retrieved_info": {},
            "pending_relevance_batch": [
                {
                    "tool_name": "get__machines",
                    "tool_call_id": "t1",
                    "args": {},
                    "result": {"data": [{"machine_id": "M-001"}]},
                    "http_status": 200,
                },
                {
                    "tool_name": "get__reports",
                    "tool_call_id": "t2",
                    "args": {},
                    "result": {"data": [{"report_id": "R-001"}]},
                    "http_status": 200,
                },
            ],
        }
    )
    assert calls == ["get__reports"]
    assert [row["relevance_reason"] for row in out["tool_outputs"]] == [
        "direct_lookup_pass_through",
        "semantic_pass",
    ]


@pytest.mark.asyncio
async def test_tool_execution_infrastructure_failure_sets_fatal_and_routes_to_halt(monkeypatch):
    settings = get_settings()
    read_tool = ToolInfo(
        name="get__machines",
        description="machines",
        endpoint="/machines",
        method="GET",
        input_schema={"type": "object"},
        is_read_only=True,
    )

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key):
        return {
            "ok": False,
            "http_status": None,
            "body": {"error_type": "network", "message": "connection refused"},
            "latency_ms": 1,
            "infrastructure_error": True,
        }

    monkeypatch.setattr(
        "factory_agent.graph.nodes.tool_pipeline.execute_tool_http",
        fake_execute_tool_http,
    )

    node = make_tool_execution_node(settings)
    out = await node(
        {
            "session_id": "sess-fatal",
            "original_query": "find machines",
            "intent": "find machines",
            "messages": [],
            "scoped_tools": [read_tool],
            "context": {},
            "write_generation": 0,
            "retrieved_info": {},
            "pending_decision": {
                "intent_id": "i1",
                "decision_id": "d1",
                "kind": "domain_tool",
                "tool_calls": [{"tool_name": "get__machines", "args": {}, "tool_call_id": "tc-fatal"}],
            },
        }
    )

    assert str(out["fatal_system_error"]).startswith("FATAL_SYSTEM_ERROR:get__machines")
    assert out["next_route"] == "fatal_end"
    assert route_after_tool(out) == "fatal_end"
    assert fatal_end_node(out)["status"] == "failed"
