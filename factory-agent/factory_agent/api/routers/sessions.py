from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.dependencies import is_admin_claims, principal_user_id, require_session_owner
from factory_agent.api.response_mappers import normalize_session_name, session_to_response
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.schemas import SessionBulkDeleteResponse, SessionCreateRequest, SessionResponse, SessionUpdateRequest
from factory_agent.services.session_cleanup import delete_session_tree, delete_sessions_for_user


def build_sessions_router(
    *,
    session_mgr: SessionManager,
    require_jwt: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    @router.post("/sessions", response_model=SessionResponse)
    async def create_session(
        req: SessionCreateRequest,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        principal = principal_user_id(user)
        if principal and not is_admin_claims(user) and req.user_id != principal:
            raise HTTPException(status_code=403, detail="cannot create a session for another user")
        sess = await session_mgr.create_session(
            db,
            user_id=req.user_id,
            name=normalize_session_name(req.name) or "New chat",
        )
        return session_to_response(sess)

    @router.get("/sessions", response_model=list[SessionResponse])
    async def list_sessions(
        user_id: str | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(SessionRow).order_by(SessionRow.updated_at.desc()).limit(limit)
        principal = principal_user_id(user)
        if principal and not is_admin_claims(user):
            stmt = stmt.where(SessionRow.user_id == principal)
        elif user_id:
            stmt = stmt.where(SessionRow.user_id == user_id)
        rows = (await db.execute(stmt)).scalars().all()
        return [session_to_response(row) for row in rows]

    @router.delete("/sessions", response_model=SessionBulkDeleteResponse)
    async def delete_sessions(
        user_id: str | None = Query(None),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        principal = principal_user_id(user)
        if principal and not is_admin_claims(user):
            if user_id and user_id != principal:
                raise HTTPException(status_code=403, detail="cannot delete sessions for another user")
            target_user_id = principal
        else:
            target_user_id = user_id

        if not target_user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        result = await delete_sessions_for_user(db, user_id=target_user_id)
        return SessionBulkDeleteResponse(
            ok=True,
            user_id=result.user_id,
            deleted_count=result.deleted_count,
            session_ids=result.session_ids,
        )

    @router.get("/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(
        session_id: str,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(sess, user)
        return session_to_response(sess)

    @router.delete("/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(sess, user)
        result = await delete_session_tree(db, session_id=session_id)
        if not result.deleted:
            raise HTTPException(status_code=404, detail="session not found")
        return {"ok": True, "session_id": result.session_id}

    @router.patch("/sessions/{session_id}", response_model=SessionResponse)
    async def update_session(
        session_id: str,
        req: SessionUpdateRequest,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(sess, user)
        sess.name = normalize_session_name(req.name)
        sess.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(sess)
        return session_to_response(sess)

    return router
