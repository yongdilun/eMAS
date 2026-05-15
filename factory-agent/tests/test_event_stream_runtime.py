from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from factory_agent.api.routers.events import build_events_router
from factory_agent.persistence import database as persistence_database


def _events_app(sessionmaker_override, poll_sessions: list[Any], dependency_sessions: list[Any]) -> FastAPI:
    app = FastAPI()

    async def override_get_db():
        async with sessionmaker_override() as session:
            dependency_sessions.append(session)
            yield session

    async def load_session_snapshot(*, db, session_id):
        del session_id
        poll_sessions.append(db)
        return None

    app.dependency_overrides[persistence_database.get_db] = override_get_db
    app.include_router(
        build_events_router(
            load_session_snapshot=load_session_snapshot,
            activity_steps_for_snapshot=lambda snapshot: [],
            semantic_payload_for_timeline_event=lambda *args, **kwargs: {},
            should_skip_semantic_timeline_event=lambda event: False,
            require_jwt=lambda: {"sub": "u1"},
        )
    )
    return app


@pytest.mark.asyncio
async def test_notification_stream_uses_short_lived_poll_session(sessionmaker_override):
    poll_sessions: list[Any] = []
    dependency_sessions: list[Any] = []
    app = _events_app(sessionmaker_override, poll_sessions, dependency_sessions)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("GET", "/sessions/s1/events") as response:
            body = await response.aread()

    assert response.status_code == 200
    assert b"SESSION_NOT_FOUND" in body
    assert len(dependency_sessions) == 1
    assert len(poll_sessions) == 1
    assert poll_sessions[0] is not dependency_sessions[0]


@pytest.mark.asyncio
async def test_concurrent_notification_streams_use_independent_poll_sessions(sessionmaker_override):
    poll_sessions: list[Any] = []
    dependency_sessions: list[Any] = []
    app = _events_app(sessionmaker_override, poll_sessions, dependency_sessions)

    async def read_stream() -> bytes:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream("GET", "/sessions/s1/events") as response:
                assert response.status_code == 200
                return await response.aread()

    bodies = await asyncio.gather(read_stream(), read_stream())

    assert all(b"SESSION_NOT_FOUND" in body for body in bodies)
    assert len(dependency_sessions) == 2
    assert len(poll_sessions) == 2
    assert poll_sessions[0] is not poll_sessions[1]
    assert all(poll is not dep for poll, dep in zip(poll_sessions, dependency_sessions))
