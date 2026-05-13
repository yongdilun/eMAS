from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from factory_agent.orchestration.agent_integration import Phase5Agent
from factory_agent.rag.schemas import SourceCitation

pytestmark = pytest.mark.legacy_compatibility

LEGACY_COMPATIBILITY_SCOPE = (
    "Phase5Agent is the deprecated route-score compatibility orchestrator; "
    "graph-native runtime no longer depends on QueryRouter route decisions."
)


@dataclass
class _ExecResult:
    status: str = "COMPLETED"
    current_step_index: int = 2


@dataclass
class _RagResult:
    answer: Any
    sources: list[SourceCitation]
    safety_warning: bool = False


class _FakeRouter:
    def __init__(self, route_decision: dict[str, Any]):
        self.route_decision = route_decision

    async def route(self, query: str) -> dict[str, Any]:
        del query
        return dict(self.route_decision)


class _FakeExecRunner:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    async def execute(self, *, query: str, session_id: str | None = None, guidance_context: str | None = None) -> _ExecResult:
        self.calls.append({"query": query, "session_id": session_id, "guidance_context": guidance_context, "t": time.perf_counter()})
        return _ExecResult()


class _FakeRagRunner:
    def __init__(self, answer: Any = "rag-answer", safety_warning: bool = False):
        self.calls: list[dict[str, Any]] = []
        self.answer = answer
        self.safety_warning = safety_warning
        self.sources = [
            SourceCitation(
                source_number=1,
                doc_id="doc-1",
                title="Procedure Doc",
                organization="eMAS",
                authority_level="mandatory_procedure",
                domain="safety",
                version="1.0",
                license="internal",
                retrieved_date="2026-01-01",
            )
        ]

    async def run(
        self,
        *,
        query: str,
        session_id: str | None = None,
        route: str = "RAG_ONLY",
        api_data: dict[str, Any] | None = None,
    ) -> _RagResult:
        self.calls.append(
            {"query": query, "session_id": session_id, "route": route, "api_data": api_data, "t": time.perf_counter()}
        )
        return _RagResult(answer=self.answer, sources=list(self.sources), safety_warning=self.safety_warning)


class _FakeSessionAdapter:
    def __init__(self):
        self.summary_used = False

    def build_answer_from_execution(self, execution_result: Any) -> str:
        return f"Execution {getattr(execution_result, 'status', 'COMPLETED').lower()}."

    def summarize_execution(self, execution_result: Any) -> str:
        self.summary_used = True
        return f"status={getattr(execution_result, 'status', 'COMPLETED')};step={getattr(execution_result, 'current_step_index', 0)}"

    def serialize_rag_context(self, rag_result: Any) -> str:
        return f"context:{getattr(rag_result, 'answer', '')}"


def _build_agent(route_decision: dict[str, Any], *, rag_answer: Any = "rag-answer", rag_warning: bool = False):
    router = _FakeRouter(route_decision)
    exec_runner = _FakeExecRunner()
    rag_runner = _FakeRagRunner(answer=rag_answer, safety_warning=rag_warning)
    adapter = _FakeSessionAdapter()
    agent = Phase5Agent(
        router=router,
        execution_runner=exec_runner,
        rag_pipeline=rag_runner,
        session_adapter=adapter,
    )
    return agent, exec_runner, rag_runner, adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["API_ONLY", "RAG_ONLY", "API_THEN_RAG", "RAG_THEN_API", "CLARIFY"])
async def test_ag1_all_routes_complete_without_unhandled_exceptions(route: str):
    agent, _, _, _ = _build_agent({"route": route, "route_source": "score"})
    result = await agent.run(query="test query", session_id="sess-1")
    assert result.route == route
    assert isinstance(result.answer, str)


@pytest.mark.asyncio
async def test_ag2_route_decision_metadata_preserved():
    route_decision = {"route": "API_ONLY", "route_source": "score", "confidence": 0.9, "signals": ["api_action_verb"]}
    agent, _, _, _ = _build_agent(route_decision)
    result = await agent.run(query="show machine", session_id="sess-2")
    assert result.metadata["route_decision"] == route_decision


@pytest.mark.asyncio
async def test_ag3_clarify_invokes_no_rag_or_executor():
    agent, exec_runner, rag_runner, _ = _build_agent({"route": "CLARIFY", "clarify_reason": "missing id"})
    result = await agent.run(query="fix it", session_id="sess-3")
    assert "missing id" in result.answer
    assert exec_runner.calls == []
    assert rag_runner.calls == []


@pytest.mark.asyncio
async def test_ag4_api_only_never_calls_rag():
    agent, exec_runner, rag_runner, _ = _build_agent({"route": "API_ONLY"})
    await agent.run(query="get machine", session_id="sess-4")
    assert len(exec_runner.calls) == 1
    assert rag_runner.calls == []


@pytest.mark.asyncio
async def test_ag5_rag_only_never_calls_executor():
    agent, exec_runner, rag_runner, _ = _build_agent({"route": "RAG_ONLY"})
    await agent.run(query="what is loto", session_id="sess-5")
    assert len(rag_runner.calls) == 1
    assert exec_runner.calls == []


@pytest.mark.asyncio
async def test_ag6_api_then_rag_order_is_execution_then_rag():
    agent, exec_runner, rag_runner, adapter = _build_agent({"route": "API_THEN_RAG"})
    await agent.run(query="show oee and explain", session_id="sess-6")
    assert len(exec_runner.calls) == 1
    assert len(rag_runner.calls) == 1
    assert exec_runner.calls[0]["t"] < rag_runner.calls[0]["t"]
    assert adapter.summary_used is True
    assert "Execution context:" in rag_runner.calls[0]["query"]


@pytest.mark.asyncio
async def test_ag7_rag_then_api_order_is_rag_then_execution():
    agent, exec_runner, rag_runner, _ = _build_agent({"route": "RAG_THEN_API"})
    await agent.run(query="based on sop update machine", session_id="sess-7")
    assert len(exec_runner.calls) == 1
    assert len(rag_runner.calls) == 1
    assert rag_runner.calls[0]["t"] < exec_runner.calls[0]["t"]
    assert exec_runner.calls[0]["guidance_context"] is not None


@pytest.mark.asyncio
async def test_ag9_answer_is_normalized_not_raw_object():
    agent, _, _, _ = _build_agent({"route": "RAG_ONLY"}, rag_answer={"raw": "object"})
    result = await agent.run(query="procedure", session_id="sess-8")
    assert isinstance(result.answer, str)
    assert result.answer == "Execution completed, but no readable summary was produced."


@pytest.mark.asyncio
async def test_ag10_and_ag11_async_path_and_session_propagation():
    agent, exec_runner, rag_runner, _ = _build_agent({"route": "API_THEN_RAG"})
    await agent.run(query="explain machine issue", session_id="sess-11")
    assert exec_runner.calls[0]["session_id"] == "sess-11"
    assert rag_runner.calls[0]["session_id"] == "sess-11"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["API_ONLY", "RAG_ONLY", "API_THEN_RAG", "RAG_THEN_API", "CLARIFY"])
async def test_ag12_response_route_matches_route_decision(route: str):
    agent, _, _, _ = _build_agent({"route": route})
    result = await agent.run(query="route test", session_id="sess-12")
    assert result.route == route


class _ExplodingExecRunner(_FakeExecRunner):
    async def execute(self, *, query: str, session_id: str | None = None, guidance_context: str | None = None) -> _ExecResult:
        del query, session_id, guidance_context
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_ag13_graceful_error_handling_returns_safe_response():
    router = _FakeRouter({"route": "API_ONLY"})
    rag_runner = _FakeRagRunner()
    adapter = _FakeSessionAdapter()
    agent = Phase5Agent(
        router=router,
        execution_runner=_ExplodingExecRunner(),
        rag_pipeline=rag_runner,
        session_adapter=adapter,
    )
    result = await agent.run(query="show", session_id="sess-13")
    assert result.route == "API_ONLY"
    assert "could not be completed safely" in result.answer.lower()


@pytest.mark.asyncio
async def test_ag14_latency_slos_with_fast_stubs():
    async def _sample(route: str, n: int) -> float:
        agent, _, _, _ = _build_agent({"route": route})
        samples = []
        for _ in range(n):
            started = time.perf_counter()
            await agent.run(query="latency", session_id="sess-lat")
            samples.append(time.perf_counter() - started)
        samples.sort()
        idx = max(0, int(len(samples) * 0.95) - 1)
        return samples[idx]

    clarify_p95 = await _sample("CLARIFY", 20)
    rag_only_p95 = await _sample("RAG_ONLY", 20)
    mixed_api_then_rag_p95 = await _sample("API_THEN_RAG", 20)
    mixed_rag_then_api_p95 = await _sample("RAG_THEN_API", 20)

    assert clarify_p95 < 2.0
    assert rag_only_p95 < 10.0
    assert mixed_api_then_rag_p95 < 15.0
    assert mixed_rag_then_api_p95 < 15.0
