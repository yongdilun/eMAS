from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.models import WorkflowCheckpoint as WorkflowCheckpointRow
from factory_agent.persistence.models import generate_uuid


class NoOpCheckpointStore:
    async def load(self, thread_id: str) -> dict[str, Any] | None:
        del thread_id
        return None

    async def save(self, thread_id: str, state: dict[str, Any]) -> None:
        del thread_id, state
        return None


class SqlCheckpointStore:
    """Database-backed checkpoint store keyed by logical thread id."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        retention_days: int = 30,
    ) -> None:
        self._db = db
        self._retention_days = max(1, int(retention_days))

    async def load(self, thread_id: str) -> dict[str, Any] | None:
        row = await self._load_row(thread_id=thread_id)
        if row is None:
            return None
        return {
            "checkpoint_id": row.checkpoint_id,
            "thread_id": row.thread_id,
            "session_id": row.session_id,
            "user_id": row.user_id,
            "state": row.state if isinstance(row.state, dict) else {},
            "version": int(row.version or 1),
            "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
            "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        }

    async def load_by_session(self, session_id: str) -> dict[str, Any] | None:
        now = datetime.utcnow()
        checkpoint_id = (
            await self._db.execute(
                select(WorkflowCheckpointRow.checkpoint_id)
                .where(WorkflowCheckpointRow.session_id == session_id)
                .where((WorkflowCheckpointRow.expires_at.is_(None)) | (WorkflowCheckpointRow.expires_at > now))
                .order_by(WorkflowCheckpointRow.updated_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if checkpoint_id is None:
            return None
        row = (
            await self._db.execute(
                select(WorkflowCheckpointRow).where(WorkflowCheckpointRow.checkpoint_id == checkpoint_id)
            )
        ).scalars().first()
        if row is None:
            return None
        return {
            "checkpoint_id": row.checkpoint_id,
            "thread_id": row.thread_id,
            "session_id": row.session_id,
            "user_id": row.user_id,
            "state": row.state if isinstance(row.state, dict) else {},
            "version": int(row.version or 1),
            "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
            "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        }

    async def save(
        self,
        thread_id: str,
        state: dict[str, Any],
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        now = datetime.utcnow()
        expires_at = now + timedelta(days=self._retention_days)
        existing = await self._load_row(thread_id=thread_id)
        if existing is None:
            self._db.add(
                WorkflowCheckpointRow(
                    checkpoint_id=generate_uuid(),
                    thread_id=thread_id,
                    session_id=session_id,
                    user_id=user_id,
                    state=state,
                    version=1,
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at,
                )
            )
            return
        existing.state = state
        existing.session_id = session_id or existing.session_id
        existing.user_id = user_id or existing.user_id
        existing.version = int(existing.version or 1) + 1
        existing.updated_at = now
        existing.expires_at = expires_at

    async def prune_expired(self) -> int:
        now = datetime.utcnow()
        rows = (
            await self._db.execute(
                select(WorkflowCheckpointRow).where(WorkflowCheckpointRow.expires_at.is_not(None)).where(
                    WorkflowCheckpointRow.expires_at <= now
                )
            )
        ).scalars().all()
        for row in rows:
            await self._db.delete(row)
        return len(rows)

    async def _load_row(self, *, thread_id: str) -> WorkflowCheckpointRow | None:
        now = datetime.utcnow()
        return (
            await self._db.execute(
                select(WorkflowCheckpointRow)
                .where(WorkflowCheckpointRow.thread_id == thread_id)
                .where((WorkflowCheckpointRow.expires_at.is_(None)) | (WorkflowCheckpointRow.expires_at > now))
                .limit(1)
            )
        ).scalars().first()
