from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.response_mappers import session_to_response
from factory_agent.persistence.database import get_db
from factory_agent.schemas import SessionResponse
from factory_agent.services.execution_service import ExecutionService


def build_execution_router(
    *,
    execution_service: ExecutionService,
    require_jwt: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    @router.post("/sessions/{session_id}/execute", response_model=SessionResponse)
    async def execute(
        session_id: str,
        background: bool = Query(False, description="If true, enqueue execution to the worker pool (when enabled)."),
        expected_version: int | None = Query(None, ge=1, description="Optional optimistic-lock expected session version."),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        sess = await execution_service.execute(
            db=db,
            session_id=session_id,
            background=background,
            expected_version=expected_version,
            user=user,
        )
        return session_to_response(sess)

    return router
