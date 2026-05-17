from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Protocol

from fastapi import Request

from factory_agent.schemas import SessionSnapshotResponse


ActivityFrame = tuple[str, dict[str, Any]]


class SseFaultInjectionAdapter(Protocol):
    exposes_playwright_diagnostics: bool

    def record_connection(
        self,
        request: Request,
        *,
        stream: str,
        session_id: str,
        last_event_id: str | None,
        event: str = "open",
    ) -> None:
        ...

    def connection_rows(self, request: Request) -> list[dict[str, Any]]:
        ...

    def activity_frames(
        self,
        request: Request,
        *,
        session_id: str,
        snapshot: SessionSnapshotResponse,
        pending_frames: list[ActivityFrame],
    ) -> list[ActivityFrame]:
        ...

    def should_drop_notification_stream(
        self,
        request: Request,
        *,
        session_id: str,
        last_event_id: str | None,
        snapshot: SessionSnapshotResponse | None,
    ) -> bool:
        ...


class NoopSseFaultInjectionAdapter:
    exposes_playwright_diagnostics = False

    def record_connection(
        self,
        request: Request,
        *,
        stream: str,
        session_id: str,
        last_event_id: str | None,
        event: str = "open",
    ) -> None:
        del request, stream, session_id, last_event_id, event

    def connection_rows(self, request: Request) -> list[dict[str, Any]]:
        del request
        return []

    def activity_frames(
        self,
        request: Request,
        *,
        session_id: str,
        snapshot: SessionSnapshotResponse,
        pending_frames: list[ActivityFrame],
    ) -> list[ActivityFrame]:
        del request, session_id, snapshot
        return pending_frames

    def should_drop_notification_stream(
        self,
        request: Request,
        *,
        session_id: str,
        last_event_id: str | None,
        snapshot: SessionSnapshotResponse | None,
    ) -> bool:
        del request, session_id, last_event_id, snapshot
        return False


class SeededPlaywrightSseFaultInjectionAdapter:
    exposes_playwright_diagnostics = True

    _ACTIVITY_DUPLICATE_OUT_OF_ORDER_PROMPT = "phase 9 out-of-order duplicate sse"
    _NOTIFICATION_DROP_PROMPTS = (
        "phase 9 last-event-id reconnect",
        "phase 9 stream drop recovery",
        "phase 14 stream drop commit recovery",
    )

    def record_connection(
        self,
        request: Request,
        *,
        stream: str,
        session_id: str,
        last_event_id: str | None,
        event: str = "open",
    ) -> None:
        rows = getattr(request.app.state, "playwright_seeded_sse_connections", None)
        if rows is None:
            rows = []
            setattr(request.app.state, "playwright_seeded_sse_connections", rows)
        rows.append(
            {
                "stream": stream,
                "session_id": session_id,
                "last_event_id": last_event_id,
                "event": event,
                "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
        del rows[:-100]

    def connection_rows(self, request: Request) -> list[dict[str, Any]]:
        rows = getattr(request.app.state, "playwright_seeded_sse_connections", [])
        return list(rows)

    def activity_frames(
        self,
        request: Request,
        *,
        session_id: str,
        snapshot: SessionSnapshotResponse,
        pending_frames: list[ActivityFrame],
    ) -> list[ActivityFrame]:
        del request, session_id
        if not self._snapshot_intent_contains(snapshot, self._ACTIVITY_DUPLICATE_OUT_OF_ORDER_PROMPT):
            return pending_frames
        if len(pending_frames) < 2:
            return pending_frames
        return [pending_frames[-1], pending_frames[0], pending_frames[-1], *pending_frames[1:-1]]

    def should_drop_notification_stream(
        self,
        request: Request,
        *,
        session_id: str,
        last_event_id: str | None,
        snapshot: SessionSnapshotResponse | None,
    ) -> bool:
        if last_event_id:
            return False
        if not any(self._snapshot_intent_contains(snapshot, prompt) for prompt in self._NOTIFICATION_DROP_PROMPTS):
            return False

        faults = getattr(request.app.state, "playwright_seeded_sse_faults", None)
        if faults is None:
            faults = set()
            setattr(request.app.state, "playwright_seeded_sse_faults", faults)

        key = f"notification-drop:{session_id}"
        if key in faults:
            return False
        faults.add(key)
        self.record_connection(
            request,
            stream="notification",
            session_id=session_id,
            last_event_id=last_event_id,
            event="seeded_drop",
        )
        return True

    @staticmethod
    def _snapshot_intent_contains(snapshot: SessionSnapshotResponse | None, text: str) -> bool:
        if snapshot is None or snapshot.session is None:
            return False
        return text.lower() in str(getattr(snapshot.session, "current_intent", "") or "").lower()


def seeded_playwright_sse_faults_enabled() -> bool:
    return os.getenv("FACTORY_AGENT_PLAYWRIGHT_SEEDED_MODE", "0").strip().lower() in {"1", "true", "yes"}


def build_sse_fault_injection_adapter() -> SseFaultInjectionAdapter:
    if seeded_playwright_sse_faults_enabled():
        return SeededPlaywrightSseFaultInjectionAdapter()
    return NoopSseFaultInjectionAdapter()
