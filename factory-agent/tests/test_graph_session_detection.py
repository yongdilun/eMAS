from __future__ import annotations

import pytest

from factory_agent.graph.session_detection import (
    allows_persisted_step_projection,
    has_langgraph_native_checkpoint,
    is_langgraph_plan,
    is_planner_owned_v2_plan,
)


class _Plan:
    def __init__(self, created_by: str) -> None:
        self.created_by = created_by


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _ExecuteResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return _ScalarResult(self._value)


class _CapturingDb:
    def __init__(self, values):
        self.values = list(values)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        value = self.values.pop(0) if self.values else None
        return _ExecuteResult(value)


def _statement_text(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": False}))


def test_planner_owned_graph_plan_is_graph_native_without_checkpoint_probe():
    assert is_langgraph_plan(_Plan("planner_owned_agent_graph"))


def test_historical_direct_v2_plan_still_allows_step_projection():
    plan = _Plan("v2_planner_loop")

    assert is_planner_owned_v2_plan(plan)
    assert allows_persisted_step_projection(plan)
    assert not is_langgraph_plan(plan)


def test_historical_direct_v2_created_by_normalizes_persisted_values():
    assert is_planner_owned_v2_plan(_Plan(" V2_Planner_Loop "))


@pytest.mark.asyncio
async def test_checkpoint_detection_orders_by_lightweight_checkpoint_id_before_state_fetch():
    db = _CapturingDb(
        [
            None,
            "checkpoint-001",
            {"kind": "langgraph_native_checkpoint"},
        ]
    )

    assert await has_langgraph_native_checkpoint(db, session_id="session-001")

    assert len(db.statements) == 3
    thread_lookup = _statement_text(db.statements[0])
    latest_id_lookup = _statement_text(db.statements[1])
    state_lookup = _statement_text(db.statements[2])

    assert "workflow_checkpoints.state" in thread_lookup
    assert "workflow_checkpoints.checkpoint_id" in latest_id_lookup
    assert "workflow_checkpoints.state" not in latest_id_lookup
    assert "workflow_checkpoints.thread_id" not in latest_id_lookup
    assert "ORDER BY workflow_checkpoints.updated_at DESC" in latest_id_lookup
    assert "workflow_checkpoints.state" in state_lookup
