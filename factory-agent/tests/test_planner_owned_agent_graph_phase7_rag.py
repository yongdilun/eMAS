from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import PlannerOwnedAgentGraph, PlannerOwnedAgentGraphAdapters
from factory_agent.planning.tool_selector import ToolSelectionResult


FACTORY_AGENT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "graph" / "v2_agent_graph.py"
GRAPH_ADAPTER_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "planning" / "v2_graph_adapters.py"
PLAN_CREATION_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "services" / "plan_creation_service.py"
RUNTIME_ADAPTER_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "services" / "planner_owned_graph_runtime.py"

LOTO_REENERGIZE_QUESTION = (
    "According to OSHA lockout/tagout guidance, what notification is required before reenergizing "
    "a machine after lockout devices are removed?"
)


def _settings():
    return replace(
        get_settings(),
        graph_checkpoint_backend="off",
        tool_selector_backend="retrieval",
        tool_selector_top_k=10,
        tool_selector_candidate_pool=20,
        tool_selector_reranker_enabled=False,
    )


class Phase7Selector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        self.calls.append(kwargs)
        return ToolSelectionResult(["rag_search_documents"], backend_used="retrieval", llm_calls=0)


class Phase7RAGPipeline:
    def __init__(
        self,
        *,
        answer: str,
        sources: list[dict[str, Any]],
        safety_content: str | None = None,
    ) -> None:
        self.answer = answer
        self.sources = sources
        self.safety_content = safety_content
        self.calls: list[dict[str, Any]] = []

    async def run(self, *, query: str, session_id: str | None = None, route: str = "RAG_ONLY", api_data=None):
        self.calls.append({"query": query, "session_id": session_id, "route": route, "api_data": api_data})

        class Result:
            pass

        result = Result()
        result.answer = self.answer
        result.sources = self.sources
        result.safety_content = self.safety_content
        return result


def _graph(rag_pipeline: Phase7RAGPipeline) -> tuple[PlannerOwnedAgentGraph, Phase7Selector]:
    settings = _settings()
    selector = Phase7Selector()
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name={},
            tool_selector=selector,  # type: ignore[arg-type]
            rag_pipeline=rag_pipeline,
        ),
        checkpointer=None,
    )
    return graph, selector


def _proving_source() -> dict[str, Any]:
    return {
        "source_id": "loto-guide#reenergize-notification",
        "source_number": 1,
        "doc_id": "loto-guide",
        "chunk_id": "reenergize-notification",
        "title": "Control of Hazardous Energy Guidance",
        "organization": "OSHA",
        "snippet": (
            "Before lockout or tagout devices are removed and before machines are reenergized, "
            "the employer must notify affected employees that the devices have been removed."
        ),
        "page": 9,
        "text_search": "notify affected employees",
    }


def _non_proving_source() -> dict[str, Any]:
    return {
        "source_id": "loto-guide#unrelated-housekeeping",
        "source_number": 1,
        "doc_id": "loto-guide",
        "chunk_id": "unrelated-housekeeping",
        "title": "Control of Hazardous Energy Guidance",
        "organization": "OSHA",
        "snippet": "This section discusses inspection schedules and housekeeping records.",
        "page": 12,
    }


@pytest.mark.asyncio
async def test_phase7_document_requirement_uses_graph_rag_tool_with_citation_evidence():
    rag = Phase7RAGPipeline(
        answer=(
            "Before reenergizing, the employer must notify affected employees that lockout or tagout "
            "devices were removed. [1]"
        ),
        sources=[_proving_source()],
        safety_content="Follow the site energy-control procedure.",
    )
    graph, selector = _graph(rag)

    result = await graph.run(
        LOTO_REENERGIZE_QUESTION,
        session_context={"session_id": "phase7-rag-citation"},
    )

    evidence = result.state.evidence_ledger.evidence[0]
    requirement = result.state.requirement_ledger.requirements[0]
    choose_decision = next(
        decision for decision in result.state.planner_decisions if decision.decision_kind == "choose_tool"
    )
    graph_action = result.state.execution_trace.diagnostics["graph_tool_actions"][0]
    graph_evidence = result.state.execution_trace.diagnostics["evidence_observation"]["graph_evidence"][0]

    assert selector.calls
    assert rag.calls[0]["route"] == "RAG_ONLY"
    assert result.state.candidate_tool_windows[0].max_candidates == 5
    assert choose_decision.selected_tool_call is not None
    assert choose_decision.selected_tool_call.kind == "rag_tool"
    assert evidence.source_type == "rag_tool"
    assert evidence.source_of_truth == "document_knowledge"
    assert evidence.tool_name == "rag_search_documents"
    assert evidence.citations[0].source_id == "loto-guide#reenergize-notification"
    assert evidence.citations[0].doc_id == "loto-guide"
    assert evidence.citations[0].chunk_id == "reenergize-notification"
    assert evidence.citations[0].locator["text_search"] == "notify affected employees"
    assert evidence.normalized_result["sources"][0]["organization"] == "OSHA"
    assert evidence.diagnostic_metadata["graph_tool_action"] == "rag_tool"
    assert evidence.diagnostic_metadata["retrieved_content_proved_claim"] is True
    assert evidence.diagnostic_metadata["safety_content_present"] is True
    assert evidence.diagnostic_metadata["safety_content_used_as_evidence"] is False
    assert requirement.status == "satisfied"
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert graph_action["graph_tool_action"] == "rag_tool"
    assert graph_action["legacy_shortcut_used"] is False
    assert graph_evidence["source_type"] == "rag_tool"
    assert graph_evidence["legacy_shortcut_used"] is False


@pytest.mark.asyncio
async def test_phase7_non_proving_retrieval_creates_insufficient_context_evidence():
    rag = Phase7RAGPipeline(
        answer="Before reenergizing, affected employees must be notified. [1]",
        sources=[_non_proving_source()],
        safety_content="Follow the site energy-control procedure.",
    )
    graph, _selector = _graph(rag)

    result = await graph.run(
        LOTO_REENERGIZE_QUESTION,
        session_context={"session_id": "phase7-rag-insufficient"},
    )

    evidence = result.state.evidence_ledger.evidence[0]
    requirement = result.state.requirement_ledger.requirements[0]
    context = result.state.response_document_context.diagnostics
    block = context["blocks"][0]

    assert evidence.source_type == "system_guard"
    assert evidence.source_of_truth == "document_knowledge"
    assert evidence.tool_name == "rag_search_documents"
    assert evidence.citations == []
    assert evidence.normalized_result["match_status"] == "no_match"
    assert evidence.normalized_result["no_match"] is True
    assert evidence.normalized_result["sources_checked"][0]["chunk_id"] == "unrelated-housekeeping"
    assert "do not prove the requested claim" in evidence.normalized_result["answer"]
    assert evidence.diagnostic_metadata["reason"] == "insufficient_context"
    assert evidence.diagnostic_metadata["retrieved_content_proved_claim"] is False
    assert evidence.diagnostic_metadata["safety_content_present"] is True
    assert evidence.diagnostic_metadata["safety_content_used_as_evidence"] is False
    assert requirement.status == "impossible"
    assert result.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert block["type"] == "document_insufficient_context"
    assert block["sources_checked_count"] == 1
    assert context["insufficient_context_evidence_refs"] == [evidence.id]
    assert context["no_record_evidence_refs"] == []


@pytest.mark.asyncio
async def test_phase7_trace_and_evidence_do_not_use_legacy_rag_route():
    rag = Phase7RAGPipeline(
        answer=(
            "Before reenergizing, the employer must notify affected employees that lockout or tagout "
            "devices were removed. [1]"
        ),
        sources=[_proving_source()],
    )
    graph, _selector = _graph(rag)

    result = await graph.run(
        LOTO_REENERGIZE_QUESTION,
        session_context={"session_id": "phase7-no-legacy-rag"},
    )
    payload = result.state.model_dump(mode="json")

    assert result.state.execution_trace.generated_by == "planner_owned_agent_graph"
    assert result.state.execution_trace.detectors.legacy_rag_shortcut.used is False
    assert all(evidence.source_type != "legacy_rag_route" for evidence in result.state.evidence_ledger.evidence)
    assert payload["execution_trace"]["diagnostics"]["graph_tool_actions"][0]["tool_call_kind"] == "rag_tool"


def test_phase7_graph_runtime_has_no_prompt_seed_or_source_id_branches():
    graph_source = GRAPH_SOURCE.read_text(encoding="utf-8")
    adapter_source = GRAPH_ADAPTER_SOURCE.read_text(encoding="utf-8")
    runtime_source = f"{graph_source}\n{adapter_source}"

    banned_literals = [
        "M-CNC-01",
        "JOB-SEED",
        "osha_3120_lockout_tagout",
        "src-loto-1",
        "According to OSHA lockout/tagout guidance",
        "legacy_rag_route",
    ]
    for literal in banned_literals:
        assert literal not in runtime_source

    assert "default_knowledge_policy_registry" in adapter_source
    assert "RAGPipeline" in adapter_source


def test_phase7_normal_runtime_switches_to_graph_after_phase10():
    source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    runtime_source = RUNTIME_ADAPTER_SOURCE.read_text(encoding="utf-8")

    assert "PlannerOwnedGraphRuntimeAdapter" in source
    assert "PlannerOwnedAgentGraph" in runtime_source
    assert '"thread_id": sess.session_id' in runtime_source
    assert "_create_historical_direct_v2_plan" in source
