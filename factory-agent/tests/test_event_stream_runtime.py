from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import factory_agent.api.routers.events as events_router
from factory_agent.persistence import database as persistence_database
from factory_agent.schemas import ActivityStepResponse, SessionResponse, SessionSnapshotResponse, TimelineEventResponse
from factory_agent.testing.fault_injection import NoopSseFaultInjectionAdapter, SeededPlaywrightSseFaultInjectionAdapter


LoadSnapshot = Callable[..., Awaitable[SessionSnapshotResponse | None]]
BASE_TIME = datetime(2026, 5, 16, 4, 0, tzinfo=timezone.utc)


def _events_app(
    sessionmaker_override,
    poll_sessions: list[Any],
    dependency_sessions: list[Any],
    *,
    load_session_snapshot: LoadSnapshot | None = None,
    activity_steps_for_snapshot: Callable[[SessionSnapshotResponse], list[ActivityStepResponse]] | None = None,
    semantic_payload_for_timeline_event: Callable[..., dict[str, Any]] | None = None,
    should_skip_semantic_timeline_event: Callable[[TimelineEventResponse], bool] | None = None,
    sse_fault_injection=None,
) -> FastAPI:
    app = FastAPI()

    async def override_get_db():
        async with sessionmaker_override() as session:
            dependency_sessions.append(session)
            yield session

    async def default_load_session_snapshot(*, db, session_id):
        del session_id
        poll_sessions.append(db)
        return None

    app.dependency_overrides[persistence_database.get_db] = override_get_db
    app.include_router(
        events_router.build_events_router(
            load_session_snapshot=load_session_snapshot or default_load_session_snapshot,
            activity_steps_for_snapshot=activity_steps_for_snapshot or (lambda snapshot: snapshot.activity_steps),
            semantic_payload_for_timeline_event=semantic_payload_for_timeline_event
            or (lambda event, **kwargs: {"type": event.event_type, "event_id": event.event_id, **kwargs}),
            should_skip_semantic_timeline_event=should_skip_semantic_timeline_event or (lambda event: False),
            require_jwt=lambda: {"sub": "u1"},
            sse_fault_injection=sse_fault_injection,
        )
    )
    return app


def _session_response(
    session_id: str = "s1",
    status: str = "EXECUTING",
    current_intent: str = "Phase 5 SSE oracle stream",
) -> SessionResponse:
    return SessionResponse(
        session_id=session_id,
        user_id="u1",
        name="Phase 5 SSE oracle",
        status=status,
        current_intent=current_intent,
        plan_id="plan-phase5-sse",
        operation_id="plan-phase5-sse",
        plan_version=1,
        current_step_index=0,
        step_count=1,
        replan_count=0,
        llm_call_count=0,
        session_started_at=BASE_TIME,
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def _snapshot(
    *,
    session_id: str = "s1",
    status: str = "EXECUTING",
    cursor: int = 1,
    current_intent: str = "Phase 5 SSE oracle stream",
    activity_steps: list[ActivityStepResponse] | None = None,
    timeline: list[TimelineEventResponse] | None = None,
) -> SessionSnapshotResponse:
    return SessionSnapshotResponse(
        session=_session_response(session_id=session_id, status=status, current_intent=current_intent),
        cursor=cursor,
        phase=status,
        activity_steps=activity_steps or [],
        timeline=timeline or [],
    )


def _activity_step(step_id: str, timestamp: int, label: str, state: str = "success") -> ActivityStepResponse:
    return ActivityStepResponse(
        id=step_id,
        timestamp=timestamp,
        group="research",
        label=label,
        detail=f"{label} evidence",
        state=state,
    )


def _timeline_event(event_id: str, event_type: str, content: str, offset_seconds: int) -> TimelineEventResponse:
    return TimelineEventResponse(
        event_id=event_id,
        event_type=event_type,
        content=content,
        created_at=BASE_TIME + timedelta(seconds=offset_seconds),
        operation_id="plan-phase5-sse",
        status="COMPLETED" if event_type == "session_completed" else "DONE",
    )


def _snapshot_sequence(*snapshots: SessionSnapshotResponse | None) -> tuple[LoadSnapshot, list[Any]]:
    queue = deque(snapshots)
    calls: list[Any] = []

    async def load_session_snapshot(*, db, session_id):
        calls.append({"db": db, "session_id": session_id})
        if queue:
            return queue.popleft()
        return None

    return load_session_snapshot, calls


async def _fast_sleep(_seconds: float) -> None:
    return None


def _sse_frames(body: bytes) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for raw_frame in body.decode("utf-8").replace("\r\n", "\n").strip().split("\n\n"):
        if not raw_frame.strip():
            continue
        frame: dict[str, Any] = {}
        data_lines: list[str] = []
        for line in raw_frame.splitlines():
            if line.startswith("id:"):
                frame["id"] = line.removeprefix("id:").strip()
            elif line.startswith("event:"):
                frame["event"] = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        if data_lines:
            data_text = "\n".join(data_lines)
            try:
                frame["data"] = json.loads(data_text)
            except json.JSONDecodeError:
                frame["data_raw"] = data_text
        frames.append(frame)
    return frames


def _stream_id_sort_key(value: str) -> list[int | str]:
    parts: list[int | str] = []
    for token in str(value).replace(":", "-").split("-"):
        parts.append(int(token) if token.isdigit() else token)
    return parts


def _assert_activity_oracle(
    frames: list[dict[str, Any]],
    *,
    expected_ids: list[str],
    expected_labels: list[str],
) -> None:
    activity_frames = [frame for frame in frames if frame.get("event") == "activity_snapshot"]
    frame_ids = [str(frame.get("id") or "") for frame in activity_frames]
    assert frame_ids
    assert len(set(frame_ids)) == len(frame_ids)
    assert frame_ids == sorted(frame_ids, key=_stream_id_sort_key)

    latest = activity_frames[-1]
    steps = latest.get("data", {}).get("activity_steps") or []
    ids = [str(step.get("id") or "") for step in steps]
    labels = [str(step.get("label") or "") for step in steps]

    assert ids == expected_ids
    assert labels == expected_labels
    assert len(set(ids)) == len(ids)


def _assert_notification_invalidates_snapshot(frames: list[dict[str, Any]], *, expected_cursor: int) -> None:
    invalidations = [
        frame
        for frame in frames
        if frame.get("event") == "notification" and frame.get("data", {}).get("type") == "snapshot_invalidated"
    ]
    assert len(invalidations) == 1
    assert invalidations[0]["id"] == str(expected_cursor)
    assert invalidations[0]["data"]["cursor"] == expected_cursor
    assert invalidations[0]["data"]["reason"] == "reconnect"


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
    stream_poll_sessions = [session for session in poll_sessions if session is not dependency_sessions[0]]
    assert len(stream_poll_sessions) == 1
    assert stream_poll_sessions[0] is not dependency_sessions[0]


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
    stream_poll_sessions = [
        session
        for session in poll_sessions
        if all(session is not dependency_session for dependency_session in dependency_sessions)
    ]
    assert len(stream_poll_sessions) == 2
    assert stream_poll_sessions[0] is not stream_poll_sessions[1]
    assert all(
        poll is not dependency_session
        for poll in stream_poll_sessions
        for dependency_session in dependency_sessions
    )


@pytest.mark.asyncio
async def test_activity_stream_reconnect_resumes_after_last_event_id_without_duplicate_rows(
    sessionmaker_override,
    monkeypatch,
):
    monkeypatch.setattr(events_router.asyncio, "sleep", _fast_sleep)
    steps = [
        _activity_step("act:001", 1, "Understanding request"),
        _activity_step("act:002", 2, "Reading machine telemetry"),
        _activity_step("act:003", 3, "Verifying timeline agreement"),
    ]
    snap = _snapshot(cursor=3, activity_steps=steps)
    loader, calls = _snapshot_sequence(snap, snap, snap, None)
    app = _events_app(
        sessionmaker_override,
        [],
        [],
        load_session_snapshot=loader,
        activity_steps_for_snapshot=lambda snapshot: snapshot.activity_steps,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("GET", "/sessions/s1/events/activity", headers={"Last-Event-ID": "1"}) as response:
            body = await response.aread()

    assert response.status_code == 200
    frames = _sse_frames(body)
    _assert_activity_oracle(
        frames,
        expected_ids=["act:001", "act:002", "act:003"],
        expected_labels=["Understanding request", "Reading machine telemetry", "Verifying timeline agreement"],
    )
    assert len(calls) == 4

    with pytest.raises(AssertionError):
        _assert_activity_oracle(
            [
                {
                    "event": "activity_snapshot",
                    "id": "2",
                    "data": {
                        "activity_steps": [
                            {"id": "act:001", "label": "Understanding request"},
                            {"id": "act:001", "label": "Understanding request"},
                        ]
                    },
                },
            ],
            expected_ids=["act:001"],
            expected_labels=["Understanding request"],
        )

    with pytest.raises(AssertionError):
        _assert_activity_oracle(
            [
                {
                    "event": "activity_snapshot",
                    "id": "3",
                    "data": {
                        "activity_steps": [
                            {"id": "act:003", "label": "Verifying timeline agreement"},
                            {"id": "act:002", "label": "Reading machine telemetry"},
                        ]
                    },
                },
            ],
            expected_ids=["act:002", "act:003"],
            expected_labels=["Reading machine telemetry", "Verifying timeline agreement"],
        )


@pytest.mark.asyncio
async def test_activity_stream_stale_last_event_id_replays_current_snapshot_instead_of_stalling(
    sessionmaker_override,
    monkeypatch,
):
    monkeypatch.setattr(events_router.asyncio, "sleep", _fast_sleep)
    steps = [
        _activity_step("act:001", 1, "Understanding request"),
        _activity_step("act:002", 2, "Reading machine telemetry"),
    ]
    snap = _snapshot(cursor=2, activity_steps=steps)
    loader, _calls = _snapshot_sequence(snap, snap, snap, None)
    app = _events_app(
        sessionmaker_override,
        [],
        [],
        load_session_snapshot=loader,
        activity_steps_for_snapshot=lambda snapshot: snapshot.activity_steps,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream(
            "GET",
            "/sessions/s1/events/activity",
            headers={"Last-Event-ID": "act:999-stale"},
        ) as response:
            body = await response.aread()

    assert response.status_code == 200
    _assert_activity_oracle(
        _sse_frames(body),
        expected_ids=["act:001", "act:002"],
        expected_labels=["Understanding request", "Reading machine telemetry"],
    )


@pytest.mark.asyncio
async def test_noop_fault_adapter_does_not_inject_activity_faults_for_seeded_prompt(
    sessionmaker_override,
    monkeypatch,
):
    monkeypatch.setattr(events_router.asyncio, "sleep", _fast_sleep)
    steps = [
        _activity_step("act:001", 1, "Understanding request"),
        _activity_step("act:002", 2, "Reading machine telemetry"),
    ]
    snap = _snapshot(
        cursor=2,
        current_intent="Run Phase 9 out-of-order duplicate SSE seeded jobs workflow",
        activity_steps=steps,
    )
    loader, _calls = _snapshot_sequence(snap, snap, None)
    app = _events_app(
        sessionmaker_override,
        [],
        [],
        load_session_snapshot=loader,
        activity_steps_for_snapshot=lambda snapshot: snapshot.activity_steps,
        sse_fault_injection=NoopSseFaultInjectionAdapter(),
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("GET", "/sessions/s1/events/activity") as response:
            body = await response.aread()

        diagnostics = await client.get("/_playwright/sse-connections")

    assert response.status_code == 200
    assert diagnostics.status_code == 404
    _assert_activity_oracle(
        _sse_frames(body),
        expected_ids=["act:001", "act:002"],
        expected_labels=["Understanding request", "Reading machine telemetry"],
    )


@pytest.mark.asyncio
async def test_seeded_fault_adapter_keeps_activity_snapshot_atomic(
    sessionmaker_override,
    monkeypatch,
):
    monkeypatch.setattr(events_router.asyncio, "sleep", _fast_sleep)
    steps = [
        _activity_step("act:001", 1, "Understanding request"),
        _activity_step("act:002", 2, "Reading machine telemetry"),
    ]
    snap = _snapshot(
        cursor=2,
        current_intent="Run Phase 9 out-of-order duplicate SSE seeded jobs workflow",
        activity_steps=steps,
    )
    loader, _calls = _snapshot_sequence(snap, snap, None)
    app = _events_app(
        sessionmaker_override,
        [],
        [],
        load_session_snapshot=loader,
        activity_steps_for_snapshot=lambda snapshot: snapshot.activity_steps,
        sse_fault_injection=SeededPlaywrightSseFaultInjectionAdapter(),
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("GET", "/sessions/s1/events/activity") as response:
            body = await response.aread()

        diagnostics = await client.get("/_playwright/sse-connections")

    assert response.status_code == 200
    assert diagnostics.status_code == 200
    frames = [frame for frame in _sse_frames(body) if frame.get("event") == "activity_snapshot"]
    assert [frame["id"] for frame in frames] == ["2"]
    assert [step["id"] for step in frames[0]["data"]["activity_steps"]] == ["act:001", "act:002"]
    assert diagnostics.json()["connections"][0]["stream"] == "activity"


@pytest.mark.asyncio
async def test_notification_stream_reconnect_invalidates_snapshot_for_stale_cursor(
    sessionmaker_override,
    monkeypatch,
):
    monkeypatch.setattr(events_router.asyncio, "sleep", _fast_sleep)
    snap = _snapshot(cursor=4, status="EXECUTING")
    loader, _calls = _snapshot_sequence(snap, snap, snap, None)
    app = _events_app(sessionmaker_override, [], [], load_session_snapshot=loader)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("GET", "/sessions/s1/events", headers={"Last-Event-ID": "2"}) as response:
            body = await response.aread()

    assert response.status_code == 200
    frames = _sse_frames(body)
    _assert_notification_invalidates_snapshot(frames, expected_cursor=4)

    with pytest.raises(AssertionError):
        _assert_notification_invalidates_snapshot(
            [{"event": "notification", "id": "2", "data": {"type": "heartbeat", "cursor": 2}}],
            expected_cursor=4,
    )


@pytest.mark.asyncio
async def test_seeded_notification_drop_happens_once_and_last_event_id_reconnect_continues(
    sessionmaker_override,
    monkeypatch,
):
    monkeypatch.setattr(events_router.asyncio, "sleep", _fast_sleep)
    first_snap = _snapshot(cursor=1, current_intent="Run Phase 9 Last-Event-ID reconnect seeded machine workflow")
    reconnect_snap = _snapshot(cursor=2, current_intent="Run Phase 9 Last-Event-ID reconnect seeded machine workflow")
    loader, _calls = _snapshot_sequence(first_snap, first_snap, reconnect_snap, reconnect_snap, None)
    app = _events_app(
        sessionmaker_override,
        [],
        [],
        load_session_snapshot=loader,
        sse_fault_injection=SeededPlaywrightSseFaultInjectionAdapter(),
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("GET", "/sessions/s1/events") as response:
            first_body = await response.aread()

        async with client.stream("GET", "/sessions/s1/events", headers={"Last-Event-ID": "1"}) as response:
            reconnect_body = await response.aread()

        diagnostics = await client.get("/_playwright/sse-connections")

    assert response.status_code == 200
    first_frames = _sse_frames(first_body)
    assert [frame.get("data", {}).get("type") for frame in first_frames] == ["hello"]
    reconnect_frames = _sse_frames(reconnect_body)
    _assert_notification_invalidates_snapshot(reconnect_frames, expected_cursor=2)
    connections = diagnostics.json()["connections"]
    assert any(entry["event"] == "seeded_drop" for entry in connections)
    assert any(entry["stream"] == "notification" and entry["last_event_id"] == "1" for entry in connections)


@pytest.mark.asyncio
async def test_semantic_stream_reconnect_matches_snapshot_timeline_without_replay(
    sessionmaker_override,
    monkeypatch,
):
    monkeypatch.setattr(events_router.asyncio, "sleep", _fast_sleep)
    timeline = [
        _timeline_event("tl:001", "plan_created", "Plan created", 1),
        _timeline_event("tl:002", "tool_result", "Tool evidence", 2),
        _timeline_event("tl:003", "session_completed", "Run complete", 3),
    ]
    snap = _snapshot(cursor=3, status="COMPLETED", timeline=timeline)
    loader, _calls = _snapshot_sequence(snap, snap, snap, None)
    app = _events_app(
        sessionmaker_override,
        [],
        [],
        load_session_snapshot=loader,
        semantic_payload_for_timeline_event=lambda event, **kwargs: {
            "type": event.event_type,
            "event_id": event.event_id,
            "content": event.content,
            **kwargs,
        },
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream(
            "GET",
            "/sessions/s1/events/semantic",
            headers={"Last-Event-ID": "tl:001"},
        ) as response:
            body = await response.aread()

    assert response.status_code == 200
    semantic_frames = [frame for frame in _sse_frames(body) if frame.get("event") == "semantic" and frame.get("id")]
    assert [frame["id"] for frame in semantic_frames] == ["tl:002", "tl:003"]
    assert [frame["data"]["type"] for frame in semantic_frames] == ["tool_result", "session_completed"]
    assert semantic_frames[-1]["data"]["content"] == "Run complete"


def test_events_router_does_not_contain_seeded_phase_prompt_branches():
    source = Path(events_router.__file__).read_text(encoding="utf-8").lower()
    forbidden = [
        "phase 9 out-of-order duplicate sse",
        "phase 9 last-event-id reconnect",
        "phase 9 stream drop recovery",
        "phase 14 stream drop commit recovery",
    ]
    for phrase in forbidden:
        assert phrase not in source
