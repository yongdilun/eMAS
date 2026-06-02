from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from factory_agent.api.dependencies import require_session_owner
from factory_agent.observability.metrics import metrics
from factory_agent.persistence.database import close_session_after_cancellation, get_db
from factory_agent.schemas import ActivityStepResponse, SessionSnapshotResponse, TimelineEventResponse
from factory_agent.testing.fault_injection import SseFaultInjectionAdapter, build_sse_fault_injection_adapter


LoadSessionSnapshot = Callable[..., Awaitable[SessionSnapshotResponse | None]]


def build_events_router(
    *,
    load_session_snapshot: LoadSessionSnapshot,
    activity_steps_for_snapshot: Callable[[SessionSnapshotResponse], list[ActivityStepResponse]],
    semantic_payload_for_timeline_event: Callable[..., dict[str, Any]],
    should_skip_semantic_timeline_event: Callable[[TimelineEventResponse], bool],
    require_jwt: Callable[..., dict[str, Any]],
    sse_fault_injection: SseFaultInjectionAdapter | None = None,
) -> APIRouter:
    router = APIRouter()
    fault_injection = sse_fault_injection or build_sse_fault_injection_adapter()

    if fault_injection.exposes_playwright_diagnostics:

        @router.get("/_playwright/sse-connections")
        async def seeded_sse_connections(request: Request):
            return {"connections": fault_injection.connection_rows(request)}

    @router.get("/sessions/{session_id}/events/semantic")
    async def stream_semantic_events(
        request: Request,
        session_id: str,
        last_event_id: str | None = Header(None, alias="Last-Event-ID"),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        """
        Phase 7 semantic SSE adapter.

        Frontend hydrates from snapshot first, then this stream emits semantic
        events derived from snapshot timeline diffs. EventSource reconnects can
        resume after Last-Event-ID.
        """
        fault_injection.record_connection(
            request,
            stream="semantic",
            session_id=session_id,
            last_event_id=last_event_id,
        )
        initial_for_auth = await load_session_snapshot(db=db, session_id=session_id)
        if initial_for_auth is not None:
            require_session_owner(initial_for_auth.session, user)
        session_factory = sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
        await close_session_after_cancellation(db)

        async def _event_gen():
            heartbeat_s = 12
            poll_s = 1.0
            seen_event_ids: set[str] = set()
            emitted_resume_markers: set[str] = set()
            idle_heartbeats = 0

            async def _fresh_snapshot() -> SessionSnapshotResponse | None:
                metrics.inc("stream_snapshot_poll_total", labels={"stream": "semantic"})
                async with session_factory() as poll_db:
                    return await load_session_snapshot(db=poll_db, session_id=session_id)

            if last_event_id:
                initial_snapshot = await _fresh_snapshot()
                if initial_snapshot is not None:
                    resume_seen_event_ids: list[str] = []
                    found_resume_event = False
                    for ev in initial_snapshot.timeline:
                        resume_seen_event_ids.append(ev.event_id)
                        if ev.event_id == last_event_id:
                            found_resume_event = True
                            break
                    if found_resume_event:
                        seen_event_ids.update(resume_seen_event_ids)
            init_payload = {"type": "STREAM_READY", "session_id": session_id}
            yield f"event: semantic\ndata: {json.dumps(init_payload, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    metrics.inc("stream_disconnect_total", labels={"stream": "semantic"})
                    return
                snapshot = await _fresh_snapshot()
                if snapshot is None:
                    gone = {"type": "SESSION_NOT_FOUND", "session_id": session_id}
                    yield f"event: semantic\ndata: {json.dumps(gone, ensure_ascii=False)}\n\n"
                    return
                emitted = False
                for ev in snapshot.timeline:
                    if ev.event_id in seen_event_ids:
                        continue
                    seen_event_ids.add(ev.event_id)
                    if should_skip_semantic_timeline_event(ev):
                        continue
                    payload = semantic_payload_for_timeline_event(ev, session_id=session_id)
                    emitted = True
                    yield f"id: {ev.event_id}\nevent: semantic\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

                resume_ctx = None
                sess_payload = snapshot.session
                rc = getattr(sess_payload, "replan_context", None) if sess_payload is not None else None
                if isinstance(rc, dict):
                    resume_ctx = rc.get("langgraph_approval_resume")
                sess_status = str(getattr(sess_payload, "status", "") or "").upper()
                if (
                    isinstance(resume_ctx, dict)
                    and str(resume_ctx.get("status") or "").lower() == "approved"
                    and sess_status == "EXECUTING"
                ):
                    aid = str(resume_ctx.get("approval_id") or "").strip()
                    decided_at = str(resume_ctx.get("decided_at") or "").strip()
                    marker = f"{aid}:{decided_at}" if aid else ""
                    if marker and marker not in emitted_resume_markers:
                        emitted_resume_markers.add(marker)
                        resume_payload = {
                            "type": "SESSION_WILL_RESUME",
                            "session_id": session_id,
                            "approval_id": aid,
                            "decided_at": decided_at or None,
                        }
                        emitted = True
                        yield "event: semantic\ndata: " + json.dumps(resume_payload, ensure_ascii=False) + "\n\n"

                if emitted:
                    idle_heartbeats = 0
                else:
                    idle_heartbeats += 1
                    if idle_heartbeats * poll_s >= heartbeat_s:
                        pending_id = (
                            snapshot.pending_approval.approval_id
                            if snapshot.pending_approval is not None
                            else None
                        )
                        hb = {
                            "type": "HEARTBEAT",
                            "session_id": session_id,
                            "pending_approval_id": pending_id,
                            "ts": datetime.utcnow().isoformat() + "Z",
                        }
                        yield f"event: semantic\ndata: {json.dumps(hb, ensure_ascii=False)}\n\n"
                        idle_heartbeats = 0
                await asyncio.sleep(poll_s)

        return StreamingResponse(
            _event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/sessions/{session_id}/events/activity")
    async def stream_activity_events(
        request: Request,
        session_id: str,
        last_event_id: str | None = Header(None, alias="Last-Event-ID"),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        """
        User-facing activity SSE adapter.

        This stream exposes only stable, sanitized activity steps suitable for
        the chat UI. Intra-poll changes are emitted together, then paced before
        the next poll cycle.
        """
        fault_injection.record_connection(
            request,
            stream="activity",
            session_id=session_id,
            last_event_id=last_event_id,
        )
        initial_for_auth = await load_session_snapshot(db=db, session_id=session_id)
        if initial_for_auth is not None:
            require_session_owner(initial_for_auth.session, user)
        session_factory = sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
        await close_session_after_cancellation(db)

        async def _event_gen():
            heartbeat_s = 12
            poll_s = 1.0
            activity_emit_min_s = 1.0
            last_seen_revision = -1
            try:
                client_revision = int(str(last_event_id or "").removeprefix("activity:"))
            except (TypeError, ValueError):
                client_revision = -1
            idle_heartbeats = 0

            async def _fresh_snapshot() -> SessionSnapshotResponse | None:
                metrics.inc("stream_snapshot_poll_total", labels={"stream": "activity"})
                async with session_factory() as poll_db:
                    return await load_session_snapshot(db=poll_db, session_id=session_id)

            ready = {"type": "STREAM_READY", "session_id": session_id}
            yield f"event: control\ndata: {json.dumps(ready, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    metrics.inc("stream_disconnect_total", labels={"stream": "activity"})
                    return
                snapshot = await _fresh_snapshot()
                if snapshot is None:
                    gone = {"type": "SESSION_NOT_FOUND", "session_id": session_id}
                    yield f"event: control\ndata: {json.dumps(gone, ensure_ascii=False)}\n\n"
                    return

                activity_steps = [step.model_dump(exclude_none=True) for step in activity_steps_for_snapshot(snapshot)]
                activity_revision = int(getattr(snapshot, "activity_revision", None) or snapshot.cursor or 0)
                emitted = activity_revision > max(last_seen_revision, client_revision)
                pending_frames: list[tuple[str, dict[str, Any]]] = []
                if emitted:
                    last_seen_revision = activity_revision
                    pending_frames.append(
                        (
                            str(activity_revision),
                            {
                                "type": "ACTIVITY_SNAPSHOT",
                                "session_id": session_id,
                                "activity_revision": activity_revision,
                                "activity_steps": activity_steps,
                            },
                        )
                    )
                frames_to_emit = fault_injection.activity_frames(
                    request,
                    session_id=session_id,
                    snapshot=snapshot,
                    pending_frames=pending_frames,
                )
                for frame_id, payload in frames_to_emit:
                    yield f"id: {frame_id}\nevent: activity_snapshot\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if emitted:
                    idle_heartbeats = 0
                    await asyncio.sleep(activity_emit_min_s)
                else:
                    idle_heartbeats += 1
                    if idle_heartbeats * poll_s >= heartbeat_s:
                        hb = {"type": "HEARTBEAT", "session_id": session_id, "ts": datetime.utcnow().isoformat() + "Z"}
                        yield f"event: control\ndata: {json.dumps(hb, ensure_ascii=False)}\n\n"
                        idle_heartbeats = 0
                await asyncio.sleep(poll_s)

        return StreamingResponse(
            _event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/sessions/{session_id}/events")
    async def stream_session_events(
        request: Request,
        session_id: str,
        last_event_id: str | None = Header(None, alias="Last-Event-ID"),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        """
        Notification-only SSE stream.

        Emits lightweight frames: hello, snapshot_invalidated, phase_changed,
        and heartbeat. Clients re-fetch snapshots when invalidated.
        """
        fault_injection.record_connection(
            request,
            stream="notification",
            session_id=session_id,
            last_event_id=last_event_id,
        )
        initial_for_auth = await load_session_snapshot(db=db, session_id=session_id)
        if initial_for_auth is not None:
            require_session_owner(initial_for_auth.session, user)
        session_factory = sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
        await close_session_after_cancellation(db)

        async def _event_gen():
            heartbeat_s = 15
            poll_s = 0.5
            idle_ticks = 0

            try:
                client_cursor = int(last_event_id or 0)
            except (ValueError, TypeError):
                client_cursor = 0

            last_seen_cursor: int | None = None
            last_seen_phase: str | None = None

            async def _fresh_snapshot() -> SessionSnapshotResponse | None:
                metrics.inc("stream_snapshot_poll_total", labels={"stream": "notification"})
                async with session_factory() as poll_db:
                    return await load_session_snapshot(db=poll_db, session_id=session_id)

            initial = await _fresh_snapshot()
            if initial is None:
                gone = {"type": "SESSION_NOT_FOUND", "session_id": session_id}
                yield f"event: notification\ndata: {json.dumps(gone, ensure_ascii=False)}\n\n"
                return

            last_seen_cursor = initial.cursor
            last_seen_phase = initial.phase
            hello = {
                "type": "hello",
                "session_id": session_id,
                "cursor": initial.cursor,
                "phase": initial.phase,
            }
            yield f"id: {initial.cursor}\nretry: 500\nevent: notification\ndata: {json.dumps(hello, ensure_ascii=False)}\n\n"

            if fault_injection.should_drop_notification_stream(
                request,
                session_id=session_id,
                last_event_id=last_event_id,
                snapshot=initial,
            ):
                return

            if client_cursor < initial.cursor:
                inv = {
                    "type": "snapshot_invalidated",
                    "cursor": initial.cursor,
                    "reason": "reconnect",
                }
                yield f"id: {initial.cursor}\nevent: notification\ndata: {json.dumps(inv, ensure_ascii=False)}\n\n"

            while True:
                await asyncio.sleep(poll_s)
                if await request.is_disconnected():
                    metrics.inc("stream_disconnect_total", labels={"stream": "notification"})
                    return
                snapshot = await _fresh_snapshot()
                if snapshot is None:
                    gone = {"type": "SESSION_NOT_FOUND", "session_id": session_id}
                    yield f"event: notification\ndata: {json.dumps(gone, ensure_ascii=False)}\n\n"
                    return

                if fault_injection.should_drop_notification_stream(
                    request,
                    session_id=session_id,
                    last_event_id=last_event_id,
                    snapshot=snapshot,
                ):
                    return

                emitted = False

                if snapshot.cursor != last_seen_cursor:
                    reason = "phase_change" if snapshot.phase != last_seen_phase else "update"
                    inv = {
                        "type": "snapshot_invalidated",
                        "cursor": snapshot.cursor,
                        "reason": reason,
                    }
                    yield f"id: {snapshot.cursor}\nevent: notification\ndata: {json.dumps(inv, ensure_ascii=False)}\n\n"
                    emitted = True
                    last_seen_cursor = snapshot.cursor

                if snapshot.phase != last_seen_phase:
                    pc = {
                        "type": "phase_changed",
                        "cursor": snapshot.cursor,
                        "phase": snapshot.phase,
                    }
                    yield f"id: {snapshot.cursor}\nevent: notification\ndata: {json.dumps(pc, ensure_ascii=False)}\n\n"
                    emitted = True
                    last_seen_phase = snapshot.phase

                if emitted:
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    if idle_ticks * poll_s >= heartbeat_s:
                        hb = {
                            "type": "heartbeat",
                            "cursor": snapshot.cursor,
                            "ts": datetime.utcnow().isoformat() + "Z",
                        }
                        yield f"event: notification\ndata: {json.dumps(hb, ensure_ascii=False)}\n\n"
                        idle_ticks = 0

        return StreamingResponse(
            _event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
