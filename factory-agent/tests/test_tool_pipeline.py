"""Tests for graph-owned HTTP tool client helpers."""

from __future__ import annotations

from factory_agent.graph.http_tool_client import compute_planner_write_idempotency_key


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
