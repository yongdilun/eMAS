from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

import database
from factory_agent.api import build_router
from factory_agent.config import Settings
from factory_agent.persistence import database as persistence_database
from factory_agent.persistence.models import Session, WorkflowCheckpoint
from factory_agent.registry.tool_registry import ToolRegistry


class _FakeEventBus:
    def __init__(self):
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)

    async def listen(self, handler: object) -> None:
        return None


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
        jwt_required=False,
        enforce_tool_registry_health=False,
        auto_repair_tool_registry=False,
        min_healthy_tool_count=0,
    )


async def _make_app(sessionmaker_override) -> FastAPI:
    app = FastAPI()

    async def override_get_db():
        async with sessionmaker_override() as s:
            yield s

    app.dependency_overrides[database.get_db] = override_get_db
    app.dependency_overrides[persistence_database.get_db] = override_get_db
    app.include_router(build_router(settings=_settings(), tool_registry=ToolRegistry(), event_bus=_FakeEventBus()))
    return app


def _checkpoint_row(session_id: str) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        thread_id=session_id,
        session_id=session_id,
        state={"kind": "langgraph_native_checkpoint", "agent_state": {"completed_actions": []}},
        expires_at=datetime.utcnow() + timedelta(days=1),
    )


@pytest.mark.asyncio
async def test_phase8_execute_endpoint_does_not_fall_back_to_legacy_engine_for_checkpoint_only_graph_session(
    sessionmaker_override,
    db_session,
):
    session_id = "phase8-checkpoint-only"
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="WAITING_APPROVAL",
            current_intent="create a job",
            replan_context={},
        )
    )
    db_session.add(_checkpoint_row(session_id))
    await db_session.commit()

    app = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/sessions/{session_id}/execute")

    assert response.status_code == 200
    assert response.json()["status"] == "WAITING_APPROVAL"


def test_phase8_legacy_runtime_modules_are_removed_from_production_package():
    package_root = Path(__file__).resolve().parents[1] / "factory_agent"
    removed_modules = [
        "orchestration/execution.py",
        "orchestration/execution_runtime.py",
        "orchestration/router.py",
        "orchestration/agent_integration.py",
    ]
    assert [rel for rel in removed_modules if (package_root / rel).exists()] == []

    forbidden_terms = ["ExecutionEngine", "execute_until_blocked", "QueryRouter", "Phase5Agent"]
    matches: list[str] = []
    for path in package_root.rglob("*.py"):
        rel = path.relative_to(package_root).as_posix()
        text = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            if term in text:
                matches.append(f"{rel}:{term}")

    assert matches == []
