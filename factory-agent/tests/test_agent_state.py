"""Graph-neutral state and schema smoke tests."""

from __future__ import annotations

import operator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from factory_agent.schemas import ApprovalResponse


class _DummyState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    errors: Annotated[list[str], operator.add]
    tag: str


def _echo_node(state: _DummyState) -> _DummyState:
    return {"errors": ["step-a"], "messages": [AIMessage(content="ack")]}


@pytest.mark.asyncio
async def test_stategraph_reducers_append_messages_and_errors():
    graph = StateGraph(_DummyState)
    graph.add_node("n", _echo_node)
    graph.set_entry_point("n")
    graph.add_edge("n", END)
    compiled = graph.compile()

    out = await compiled.ainvoke(
        {
            "messages": [HumanMessage(content="start")],
            "errors": [],
            "tag": "t",
        }
    )

    assert [m.content for m in out["messages"]] == ["start", "ack"]
    assert out["errors"] == ["step-a"]
    assert out["tag"] == "t"


def test_approval_response_accepts_graph_native_approval_subject():
    approval = ApprovalResponse(
        approval_id="a1",
        session_id="s1",
        subject_type="graph",
        plan_id=None,
        step_id=None,
        tool_name="__langgraph_commit__",
        args={"kind": "approval_required", "preview": [{"tool_name": "post__jobs"}]},
        risk_summary="High-risk write bundle requires approval before commit.",
        side_effect_level="HIGH",
        status="PENDING",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        created_at=datetime.now(UTC),
    )

    assert approval.subject_type == "graph"
    assert approval.args["kind"] == "approval_required"
