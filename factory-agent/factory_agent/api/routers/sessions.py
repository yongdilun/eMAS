from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.response_mappers import normalize_session_name, session_to_response
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.schemas import SessionCreateRequest, SessionResponse, SessionUpdateRequest
from factory_agent.services.session_cleanup import delete_session_tree


def build_sessions_router(
    *,
    session_mgr: SessionManager,
    require_jwt: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    @router.post("/sessions", response_model=SessionResponse)
    async def create_session(
        req: SessionCreateRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.create_session(
            db,
            user_id=req.user_id,
            name=normalize_session_name(req.name) or "New chat",
        )
        return session_to_response(sess)

    @router.get("/sessions", response_model=list[SessionResponse])
    async def list_sessions(
        user_id: str | None = Query(None),
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(SessionRow).order_by(SessionRow.updated_at.desc())
        if user_id:
            stmt = stmt.where(SessionRow.user_id == user_id)
        rows = (await db.execute(stmt)).scalars().all()
        return [session_to_response(row) for row in rows]

    @router.get("/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        return session_to_response(sess)

    @router.delete("/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        result = await delete_session_tree(db, session_id=session_id)
        if not result.deleted:
            raise HTTPException(status_code=404, detail="session not found")
        return {"ok": True, "session_id": result.session_id}

    @router.patch("/sessions/{session_id}", response_model=SessionResponse)
    async def update_session(
        session_id: str,
        req: SessionUpdateRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        sess.name = normalize_session_name(req.name)
        sess.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(sess)
        return session_to_response(sess)

    return router
