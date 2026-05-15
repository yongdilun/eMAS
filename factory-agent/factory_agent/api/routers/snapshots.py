from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.database import get_db
from factory_agent.schemas import SessionSnapshotResponse


LoadSessionSnapshot = Callable[..., Awaitable[SessionSnapshotResponse | None]]


def build_snapshots_router(
    *,
    load_session_snapshot: LoadSessionSnapshot,
    require_jwt: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/sessions/{session_id}/snapshot", response_model=SessionSnapshotResponse)
    async def get_session_snapshot(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        snapshot = await load_session_snapshot(db=db, session_id=session_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="session not found")
        return snapshot

    return router
