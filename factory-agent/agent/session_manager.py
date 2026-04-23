from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Message as MessageRow
from models import Session as SessionRow
from models import generate_uuid

from .config import Settings


@dataclass(frozen=True)
class TransitionError(Exception):
    message: str

    def __str__(self) -> str:  # pragma: no cover
        return self.message


@dataclass(frozen=True)
class VersionConflictError(Exception):
    message: str

    def __str__(self) -> str:  # pragma: no cover
        return self.message


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "IDLE": {"PLANNING", "FAILED", "COMPLETED"},
    "PLANNING": {"EXECUTING", "WAITING_APPROVAL", "FAILED"},
    "EXECUTING": {"WAITING_APPROVAL", "BLOCKED", "FAILED", "COMPLETED"},
    "WAITING_APPROVAL": {"EXECUTING", "FAILED", "BLOCKED"},
    "BLOCKED": {"EXECUTING", "FAILED"},
    "FAILED": set(),
    "COMPLETED": set(),
}


class SessionManager:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def create_session(self, db: AsyncSession, *, user_id: str) -> SessionRow:
        sess = SessionRow(
            session_id=generate_uuid(),
            user_id=user_id,
            status="IDLE",
            session_started_at=datetime.utcnow(),
        )
        db.add(sess)
        await db.commit()
        await db.refresh(sess)
        return sess

    async def get_session(self, db: AsyncSession, *, session_id: str) -> SessionRow | None:
        return (await db.execute(select(SessionRow).where(SessionRow.session_id == session_id))).scalars().first()

    async def add_message(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        role: str,
        content: str,
        step_id: str | None = None,
        tool_name: str | None = None,
    ) -> MessageRow:
        msg = MessageRow(
            message_id=generate_uuid(),
            session_id=session_id,
            role=role,
            content=content,
            step_id=step_id,
            tool_name=tool_name,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg

    async def transition_status(self, db: AsyncSession, *, session: SessionRow, new_status: str) -> SessionRow:
        allowed = ALLOWED_TRANSITIONS.get(session.status, set())
        if new_status not in allowed and new_status != session.status:
            raise TransitionError(f"Invalid session transition {session.status} -> {new_status}")
        session.status = new_status
        session.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(session)
        return session

    def enforce_limits(self, session: SessionRow) -> None:
        if session.step_count >= self._settings.max_session_steps:
            raise TransitionError("Session exceeded MAX_SESSION_STEPS")
        if session.replan_count >= self._settings.max_replans:
            raise TransitionError("Session exceeded MAX_REPLANS")
        if session.llm_call_count >= self._settings.max_llm_calls:
            raise TransitionError("Session exceeded MAX_LLM_CALLS")
        if session.session_started_at:
            deadline = session.session_started_at + timedelta(seconds=self._settings.max_session_duration_s)
            if datetime.utcnow() > deadline:
                raise TransitionError("Session exceeded MAX_SESSION_DURATION_S")

    def identify_limit_hit(self, session: SessionRow) -> str | None:
        if session.step_count >= self._settings.max_session_steps:
            return "MAX_SESSION_STEPS"
        if session.replan_count >= self._settings.max_replans:
            return "MAX_REPLANS"
        if session.llm_call_count >= self._settings.max_llm_calls:
            return "MAX_LLM_CALLS"
        if session.session_started_at:
            deadline = session.session_started_at + timedelta(seconds=self._settings.max_session_duration_s)
            if datetime.utcnow() > deadline:
                return "MAX_SESSION_DURATION_S"
        return None

    async def update_with_version(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        expected_version: int,
        values: dict,
    ) -> SessionRow:
        values = dict(values)
        values["version"] = expected_version + 1
        values["updated_at"] = datetime.utcnow()
        stmt = (
            update(SessionRow)
            .where(SessionRow.session_id == session_id)
            .where(SessionRow.version == expected_version)
            .values(**values)
        )
        result = await db.execute(stmt)
        if result.rowcount != 1:
            await db.rollback()
            raise VersionConflictError("Session version conflict")
        await db.commit()
        refreshed = await self.get_session(db, session_id=session_id)
        if not refreshed:  # pragma: no cover
            raise VersionConflictError("Session not found after versioned update")
        return refreshed
