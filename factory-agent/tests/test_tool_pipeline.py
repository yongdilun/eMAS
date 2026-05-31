"""Tests for graph-owned HTTP tool client helpers."""

from __future__ import annotations

import pytest

from factory_agent.config import Settings
from factory_agent.graph.http_tool_client import (
    compute_planner_write_idempotency_key,
    execute_tool_http,
    planner_identity_headers,
)
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


def test_planner_identity_headers_trim_blank_environment(monkeypatch):
    monkeypatch.setenv("GO_API_USER_ID", "   ")
    monkeypatch.setenv("VITE_USER_ID", "   ")
    monkeypatch.setenv("GO_API_USER_ROLE", "   ")

    assert planner_identity_headers() == {
        "X-User-Id": "local-planner",
        "X-User-Role": "planner",
    }


@pytest.mark.asyncio
async def test_execute_tool_http_sends_default_planner_identity_headers(respx_mock, monkeypatch):
    monkeypatch.delenv("GO_API_USER_ID", raising=False)
    monkeypatch.delenv("GO_API_USER_ROLE", raising=False)
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
    tool = ToolInfo(
        name="post__ai_scheduling_reschedule-all",
        description="Reschedule all",
        endpoint="/ai/scheduling/reschedule-all",
        method="POST",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
    )
    route = respx_mock.post("http://testserver/ai/scheduling/reschedule-all").respond(
        200,
        json={"success": True, "data": {"proposals": []}},
    )

    result = await execute_tool_http(settings, tool, {}, idempotency_key="reschedule-all-test")

    assert result["ok"] is True
    request = route.calls[0].request
    assert request.headers["x-user-id"] == "local-planner"
    assert request.headers["x-user-role"] == "planner"
    assert request.headers["idempotency-key"] == "reschedule-all-test"
