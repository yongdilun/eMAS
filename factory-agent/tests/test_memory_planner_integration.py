from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from factory_agent.api import build_router
from factory_agent.config import Settings
from factory_agent.observability.events import EventBus
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Tool, generate_uuid
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import PlanDraft, PlanStepDraft


pytestmark = pytest.mark.legacy_compatibility(
    reason=(
        "Legacy planner-adapter memory context coverage is retained only through "
        "test_only_legacy_engine_enabled after Phase 10; normal FACTORY_AGENT_ENGINE=legacy resolves to v2."
    )
)


class _FakeEventBus(EventBus):
    def __init__(self):
        super().__init__(redis_url=None)

    async def publish(self, event):
        del event
        return None

    async def listen(self, handler):
        del handler
        return


class _CapturingPlanner:
    def __init__(self):
        self.last_context = None

    async def generate_plan(self, *, intent, scoped_tools, context=None):
        del intent, scoped_tools
        self.last_context = context
        return type(
            "PlannerResult",
            (),
            {
                "draft": PlanDraft(
                    plan_explanation="test",
                    risk_summary="none",
                    steps=[PlanStepDraft(step_index=0, tool_name="get__machines", args={})],
                ),
                "backend_used": "langgraph",
                "llm_calls": 1,
                "intent_contract": {"intent": "test", "steps": []},
            },
        )()


def _settings() -> Settings:
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
        http_timeout_s=1.0,
        memory_enabled=True,
        vector_memory_enabled=True,
        checkpoint_enabled=True,
        memory_retention_days=30,
        memory_redact_pii=True,
        factory_agent_engine="legacy",
        test_only_legacy_engine_enabled=True,
    )


async def _make_app(sessionmaker_override, planner_adapter):
    settings = _settings()
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
            planner_adapter=planner_adapter,
        )
    )
    return app


@pytest.mark.asyncio
async def test_create_plan_injects_retrieved_memory_into_planner_context(sessionmaker_override, db_session, monkeypatch):
    from factory_agent.planning.tool_selector import ToolSelector

    async def _select_tools(self, *, intent, tools_by_name, mode, max_tools=30, context=None):
        del self, intent, tools_by_name, mode, max_tools, context
        return type(
            "Sel",
            (),
            {
                "tool_names": ["get__machines"],
                "llm_calls": 0,
                "confidence": 1.0,
                "missing_fields": [],
                "reason": "forced-for-test",
            },
        )()

    monkeypatch.setattr(ToolSelector, "select_tools", _select_tools)

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

    planner = _CapturingPlanner()
    app = await _make_app(sessionmaker_override, planner)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        r_msg = await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": "Show machines and remember MEMORY-PIN-222", "mode": "normal"},
        )
        assert r_msg.status_code == 200
        r_plan = await client.post(f"/sessions/{session_id}/plans", json={})
        assert r_plan.status_code == 200

    assert isinstance(planner.last_context, dict)
    hits = planner.last_context.get("retrieved_memory") or []
    assert hits
    assert any("memory-pin-222" in (hit.get("content") or "").lower() for hit in hits)
