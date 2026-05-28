from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

import main
from factory_agent.config import Settings
from factory_agent.registry.tool_registry import ToolRegistrySnapshot


def _settings(*, enforce_tool_registry_health: bool = False, min_healthy_tool_count: int = 0) -> Settings:
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
        jwt_required=False,
        enforce_tool_registry_health=enforce_tool_registry_health,
        auto_repair_tool_registry=False,
        min_healthy_tool_count=min_healthy_tool_count,
    )


@pytest.mark.asyncio
async def test_readiness_reports_ready_when_database_and_optional_checks_pass(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(main, "engine", engine)
    app = FastAPI()
    app.state.settings = _settings(enforce_tool_registry_health=False)
    app.state.event_bus = SimpleNamespace(healthy=False)
    app.state.tool_registry = SimpleNamespace(
        _snapshot=ToolRegistrySnapshot(tools_by_name={}, loaded_at=datetime.utcnow())
    )

    try:
        status_code, payload = await main._readiness_payload(app)
    finally:
        await engine.dispose()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"]["database"]["ok"] is True
    assert payload["checks"]["redis"]["skipped"] is True
    assert payload["checks"]["tool_registry"]["skipped"] is True


@pytest.mark.asyncio
async def test_readiness_reports_not_ready_when_required_tool_registry_is_not_loaded(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(main, "engine", engine)
    app = FastAPI()
    app.state.settings = _settings(enforce_tool_registry_health=True, min_healthy_tool_count=1)
    app.state.event_bus = SimpleNamespace(healthy=False)
    app.state.tool_registry = SimpleNamespace(_snapshot=None)

    try:
        status_code, payload = await main._readiness_payload(app)
    finally:
        await engine.dispose()

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["checks"]["tool_registry"]["ok"] is False


@pytest.mark.asyncio
async def test_lifespan_shutdown_helper_suppresses_task_cancelled_error():
    started = asyncio.Event()

    async def long_running_task():
        started.set()
        await asyncio.sleep(60)

    task = asyncio.create_task(long_running_task())
    await started.wait()

    await main._cancel_and_await_task(task)

    assert task.cancelled()
