from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import httpx
import pytest

from factory_agent.config import get_settings, normalize_factory_agent_engine
from factory_agent.planning.tool_selector import ToolSelector
from factory_agent.rag.schemas import AnswerResult, SourceCitation
from tests.test_api_endpoints import _make_app, _seed_tool


REPO_ROOT = Path(__file__).resolve().parents[2]


def _machine_status_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string", "x-ai-id-field": "machine_id", "x-ai-entity": "machine"},
            "fields": {"type": "string"},
        },
        "required": ["id"],
        "x-path-params": ["id"],
        "x-query-params": ["fields"],
        "x-param-sources": {"id": "path", "fields": "query"},
        "x-ai-entity": "machine",
        "x-ai-response-contracts": ["entity_status_v1"],
    }


def _job_list_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
            "sort_by": {"type": "string", "enum": ["deadline", "priority"]},
            "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer"},
            "fields": {"type": "string"},
        },
        "x-query-params": ["priority", "sort_by", "sort_dir", "limit", "fields"],
        "x-param-sources": {
            "priority": "query",
            "sort_by": "query",
            "sort_dir": "query",
            "limit": "query",
            "fields": "query",
        },
        "x-ai-entity": "job",
        "x-ai-response-contracts": ["result_collection_v1"],
    }


class FakeRAGPipeline:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, *, query: str, session_id: str | None = None, route: str = "RAG_ONLY", **_: Any) -> AnswerResult:
        self.calls.append({"query": query, "session_id": session_id, "route": route})
        return AnswerResult(
            answer="Notify affected employees before reenergizing [^1].",
            sources=[
                SourceCitation(
                    source_id="osha_3120_lockout_tagout#c0029",
                    source_number=1,
                    doc_id="osha_3120_lockout_tagout",
                    chunk_id="c0029",
                    title="Control of Hazardous Energy Lockout/Tagout",
                    organization="OSHA",
                    snippet="Notify affected employees before reenergizing.",
                    authority_level="regulatory",
                    domain="safety",
                    version="2026",
                    license="public",
                    retrieved_date="2026-05-20",
                    page=15,
                    pdf_url="/documents/osha_3120_lockout_tagout/pdf",
                    text_search="Notify affected employees before reenergizing.",
                )
            ],
            safety_warning=True,
            safety_content="Follow the site-approved SOP before acting.",
            route_used=route,
        )


async def _create_prompt(client: httpx.AsyncClient, content: str) -> str:
    created = await client.post("/sessions", json={"user_id": "u1"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    message = await client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": content})
    assert message.status_code == 200
    return session_id


def test_phase8_default_engine_is_v2_with_legacy_kill_switch_removed():
    assert normalize_factory_agent_engine(None) == "v2"
    assert normalize_factory_agent_engine("unknown") == "v2"
    assert normalize_factory_agent_engine("legacy") == "v2"
    assert get_settings().factory_agent_engine == "v2"


@pytest.mark.asyncio
async def test_phase8_normal_api_path_records_v2_engine_without_legacy_authority(sessionmaker_override, db_session):
    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema=_machine_status_schema(),
        capability_tags=json.dumps(["machine", "lookup", "status"]),
    )
    app, _event_bus = await _make_app(
        sessionmaker_override,
        min_healthy_tool_count=0,
        allow_offline_planner_proposer=True,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = await _create_prompt(client, "Show machine M-LTH-77 status.")
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        session = (await client.get(f"/sessions/{session_id}")).json()

    contract = session["replan_context"]["intent_contract"]
    trace = contract["execution_trace"]
    assert contract["engine_version"] == "v2"
    assert trace["generated_by"] == "planner_owned_agent_graph"
    assert trace["detectors"]["legacy_rag_shortcut"]["used"] is False
    assert trace["detectors"]["legacy_working_intent_execution"]["used"] is False
    assert trace["detectors"]["legacy_whole_query_tool_scope"]["used"] is False
    assert trace["detectors"]["legacy_intent_completion_loop"]["used"] is False


@pytest.mark.asyncio
async def test_phase8_v2_rag_response_uses_rag_tool_evidence_not_legacy_route(sessionmaker_override):
    rag = FakeRAGPipeline()
    app, _event_bus = await _make_app(
        sessionmaker_override,
        min_healthy_tool_count=0,
        rag_pipeline_adapter=rag,
        allow_offline_planner_proposer=True,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = await _create_prompt(
            client,
            "According to the OSHA lockout/tagout guide, what notification is required before reenergizing?",
        )
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        session = (await client.get(f"/sessions/{session_id}")).json()
        snapshot = (await client.get(f"/sessions/{session_id}/snapshot")).json()

    contract = session["replan_context"]["intent_contract"]
    trace = contract["execution_trace"]
    evidence = contract["v2_state"]["evidence_ledger"]["evidence"]
    assert rag.calls and rag.calls[0]["route"] == "RAG_ONLY"
    assert contract["engine_version"] == "v2"
    assert trace["generated_by"] == "planner_owned_agent_graph"
    assert trace["detectors"]["legacy_rag_shortcut"]["used"] is False
    assert evidence[0]["source_type"] == "system_guard"
    assert evidence[0]["tool_name"] == "rag_search_documents"
    assert evidence[0]["diagnostic_metadata"]["graph_tool_action"] == "rag_tool"
    assert evidence[0]["normalized_result"]["sources_checked"][0]["doc_id"] == "osha_3120_lockout_tagout"
    assert snapshot["response_document"]["invariants"]["knowledge_answer_contract"] == "knowledge_answer_v1"
    assert any(block["type"] == "source_list" for block in snapshot["response_document"]["blocks"])


@pytest.mark.asyncio
async def test_phase8_v2_api_retrieval_uses_capability_phrase_not_whole_query(
    sessionmaker_override,
    db_session,
    monkeypatch,
):
    calls: list[dict[str, Any]] = []
    original_select = ToolSelector.select_tools

    async def recording_select(self: ToolSelector, **kwargs: Any):
        calls.append(kwargs)
        return await original_select(self, **kwargs)

    monkeypatch.setattr(ToolSelector, "select_tools", recording_select)
    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema=_machine_status_schema(),
        capability_tags=json.dumps(["machine", "lookup", "status"]),
    )
    await _seed_tool(
        db_session,
        name="get__jobs",
        endpoint="/jobs",
        method="GET",
        input_schema=_job_list_schema(),
        capability_tags=json.dumps(["job", "list", "status"]),
    )
    app, _event_bus = await _make_app(
        sessionmaker_override,
        min_healthy_tool_count=0,
        tool_selector_backend="retrieval",
        allow_offline_planner_proposer=True,
    )
    whole_query = "Show machine M-LTH-77 status, then list next 2 low priority jobs sorted by deadline."

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = await _create_prompt(client, whole_query)
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200

    assert calls
    assert all(call["intent"] != whole_query for call in calls)
    assert all(call["max_tools"] == 5 for call in calls)
    assert any("machine" in call["intent"] and "jobs sorted" not in call["intent"] for call in calls)


@pytest.mark.asyncio
async def test_replan_spine_persists_attempts_and_active_evidence_in_intent_contract(
    sessionmaker_override,
    db_session,
    monkeypatch,
):
    executor_calls: list[dict[str, Any]] = []

    async def sequential_execute_tool_http(settings, tool, args, *, idempotency_key, extra_headers=None):
        _ = settings, tool, idempotency_key, extra_headers
        executor_calls.append({"args": dict(args)})
        if len(executor_calls) == 1:
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 2,
                "body": {
                    "data": {}
                },
                "infrastructure_error": False,
            }
        return {
            "ok": True,
            "http_status": 200,
            "latency_ms": 3,
            "body": {
                "data": {
                    "machine_id": args.get("id"),
                    "status": "running",
                }
            },
            "infrastructure_error": False,
        }

    monkeypatch.setattr(
        "factory_agent.planning.v2_graph_adapters._default_http_executor",
        sequential_execute_tool_http,
    )
    await _seed_tool(
        db_session,
        name="get__machines_{id}",
        endpoint="/machines/{id}",
        method="GET",
        input_schema=_machine_status_schema(),
        capability_tags=json.dumps(["machine", "lookup", "status"]),
    )
    app, _event_bus = await _make_app(
        sessionmaker_override,
        min_healthy_tool_count=0,
        tool_selector_backend="retrieval",
        allow_offline_planner_proposer=True,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = await _create_prompt(client, "Show machine M-LTH-77 status.")
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200, created.text
        session = (await client.get(f"/sessions/{session_id}")).json()

    contract = session["replan_context"]["intent_contract"]
    evidence = contract["v2_state"]["evidence_ledger"]["evidence"]
    replan = contract["replan_spine"]

    assert len(executor_calls) == 2
    assert replan["attempt_count"] == 1
    assert replan["stale_attempt_evidence_refs"] == [evidence[0]["id"]]
    assert replan["active_final_evidence_refs"] == [evidence[-1]["id"]]
    assert contract["response_document_context"]["evidence_refs"] == [evidence[-1]["id"]]
    assert evidence[0]["diagnostic_metadata"]["active_revision_satisfaction"] is False
    assert evidence[-1]["diagnostic_metadata"]["active_revision_satisfaction"] is True


def test_phase8_runtime_has_no_second_parallel_tool_selector_retriever():
    planning_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "factory-agent" / "factory_agent" / "planning").glob("v2_*.py")
    )
    assert "HybridRetriever" not in planning_sources
    assert "V2CapabilityToolRetriever" in planning_sources
    assert "ToolSelector" in planning_sources
