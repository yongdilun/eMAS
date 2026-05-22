from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import database
from factory_agent.api import build_router
from factory_agent.config import (
    Settings,
    get_settings,
    normalize_factory_agent_engine,
    resolve_factory_agent_engine_for_runtime,
)
from factory_agent.registry.tool_registry import ToolRegistry
from tests.test_api_endpoints import FakeEventBus
from tests.test_planner_owned_graph_api_contract import FakeRAGPipeline, _create_prompt


REPO_ROOT = Path(__file__).resolve().parents[2]


def _settings(*, factory_agent_engine: str = "v2") -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        admin_api_key="test-admin-key",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
        enforce_tool_registry_health=False,
        auto_repair_tool_registry=False,
        min_healthy_tool_count=0,
        factory_agent_engine=factory_agent_engine,  # type: ignore[arg-type]
        allow_offline_planner_proposer=True,
    )


async def _make_app(
    sessionmaker_override: Any,
    *,
    factory_agent_engine: str = "v2",
    rag_pipeline_adapter: Any | None = None,
) -> FastAPI:
    app = FastAPI()

    async def override_get_db():
        async with sessionmaker_override() as s:
            yield s

    app.dependency_overrides[database.get_db] = override_get_db
    app.include_router(
        build_router(
            settings=_settings(factory_agent_engine=factory_agent_engine),
            tool_registry=ToolRegistry(),
            event_bus=FakeEventBus(),
            rag_pipeline_adapter=rag_pipeline_adapter,
        )
    )
    return app


def test_phase10_legacy_engine_value_normalizes_to_v2(monkeypatch):
    monkeypatch.setenv("FACTORY_AGENT_ENGINE", "legacy")

    assert normalize_factory_agent_engine("legacy") == "v2"
    assert get_settings().factory_agent_engine == "v2"
    assert resolve_factory_agent_engine_for_runtime(_settings(factory_agent_engine="legacy")) == "v2"


@pytest.mark.asyncio
async def test_phase10_legacy_env_value_still_runs_normal_rag_through_graph(sessionmaker_override):
    rag = FakeRAGPipeline()
    app = await _make_app(
        sessionmaker_override,
        factory_agent_engine="legacy",
        rag_pipeline_adapter=rag,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = await _create_prompt(
            client,
            "According to the OSHA lockout/tagout guide, what notification is required before reenergizing?",
        )
        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        session = (await client.get(f"/sessions/{session_id}")).json()

    contract = session["replan_context"]["intent_contract"]
    trace = contract["execution_trace"]
    evidence = contract["v2_state"]["evidence_ledger"]["evidence"]
    assert contract["engine_version"] == "v2"
    assert trace["generated_by"] == "planner_owned_agent_graph"
    assert trace["detectors"]["legacy_rag_shortcut"]["used"] is False
    assert evidence[0]["source_type"] == "system_guard"
    assert evidence[0]["tool_name"] == "rag_search_documents"
    assert evidence[0]["diagnostic_metadata"]["graph_tool_action"] == "rag_tool"


def test_phase10_legacy_xfails_are_removed_from_normal_backend_suite():
    tests_root = REPO_ROOT / "factory-agent" / "tests"
    xfail_marker = "pytest.mark." + "xfail"
    matches = []
    for path in tests_root.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        if xfail_marker in text:
            matches.append(path.relative_to(tests_root).as_posix())

    assert matches == []


def test_phase10_generated_vocabulary_names_planner_owned_v2_architecture():
    vocab_path = REPO_ROOT / "factory-agent" / "factory_agent" / "generated" / "tool_intent_vocabulary.json"
    payload = json.loads(vocab_path.read_text(encoding="utf-8"))

    assert payload["architecture"] == "planner_owned_v2"
    assert payload["retrieval_contract"] == "capability_need_to_tool_selector_adapter"
    assert "machine" in payload["entity_tokens"]
    assert "job" in payload["entity_tokens"]
