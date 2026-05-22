from __future__ import annotations

import os

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from factory_agent.api import build_router
from factory_agent.config import Settings
from factory_agent.observability.events import EventBus
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Session, Tool, VectorMemory, generate_uuid
from factory_agent.registry.tool_registry import ToolRegistry


class _FakeEventBus(EventBus):
    def __init__(self):
        super().__init__(redis_url=None)

    async def publish(self, event):
        del event
        return None

    async def listen(self, handler):
        del handler
        return


def _settings(openai_base_url: str) -> Settings:
    return Settings(
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
        http_timeout_s=2.0,
        memory_enabled=True,
        vector_memory_enabled=True,
        checkpoint_enabled=True,
        memory_retention_days=30,
        memory_redact_pii=True,
        tool_selector_backend="langchain",
        openai_base_url=openai_base_url,
        openai_api_key=os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or "local",
        planner_openai_base_url=openai_base_url,
        summary_openai_base_url=openai_base_url,
        tool_result_summary_openai_base_url=openai_base_url,
        tool_selector_openai_base_url=openai_base_url,
    )


async def _make_app(sessionmaker_override, *, openai_base_url: str):
    settings = _settings(openai_base_url)
    tool_registry = ToolRegistry()
    app = FastAPI()

    async def override_get_db():
        async with sessionmaker_override() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(
        build_router(
            settings=settings,
            tool_registry=tool_registry,
            event_bus=_FakeEventBus(),
            enqueue_session=None,
            planner_adapter=None,
        )
    )
    app.state.settings = settings
    return app


@pytest.mark.asyncio
async def test_live_llm_memory_retrieval_across_turns(sessionmaker_override, db_session):
    if os.getenv("FACTORY_AGENT_LIVE_LLM", "0").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("FACTORY_AGENT_LIVE_LLM not set")
    openai_base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL")
    if not openai_base_url:
        pytest.skip("OPENAI_BASE_URL or LLM_BASE_URL not set")

    db_session.add(
        Tool(
            tool_id=generate_uuid(),
            name="get__machines",
            description="List machines",
            endpoint="/machines",
            method="GET",
            version=1,
            schema_version=1,
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object"},
            capability_tags='["machine","list"]',
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
        )
    )
    await db_session.commit()

    app = await _make_app(sessionmaker_override, openai_base_url=openai_base_url)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "live-memory"})).json()["session_id"]

        r1 = await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Remember the memory token alphamemory and list machines.", "mode": "normal"},
        )
        assert r1.status_code == 200

        r2 = await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Use alphamemory again and list machines.", "mode": "normal"},
        )
        assert r2.status_code == 200

    session_row = (await db_session.execute(select(Session).where(Session.session_id == session_id))).scalars().first()
    assert session_row is not None

    vectors = (await db_session.execute(select(VectorMemory).where(VectorMemory.session_id == session_id))).scalars().all()
    assert len(vectors) >= 2

    manager = MemoryManager(app.state.settings)
    ctx = await manager.build_planner_context(
        db_session,
        session_id=session_id,
        intent="Use alphamemory again.",
        base_context={},
    )
    hits = ctx.get("retrieved_memory") or []
    assert hits
    assert any("alphamemory" in (hit.get("content") or "").lower() for hit in hits)

