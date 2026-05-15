from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.response_mappers import dead_letter_to_response
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import DeadLetter as DeadLetterRow
from factory_agent.schemas import (
    DeadLetterDismissRequest,
    DeadLetterPushRequest,
    DeadLetterReplayRequest,
    DeadLetterResponse,
)


def build_dlq_router(*, require_jwt: Callable[..., dict[str, Any]]) -> APIRouter:
    router = APIRouter()

    @router.get("/dlq", response_model=list[DeadLetterResponse])
    async def list_dlq(
        status: str | None = Query(None),
        session_id: str | None = Query(None),
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(DeadLetterRow)
        if status:
            stmt = stmt.where(DeadLetterRow.status == status)
        if session_id:
            stmt = stmt.where(DeadLetterRow.session_id == session_id)
        rows = (await db.execute(stmt.order_by(DeadLetterRow.created_at.desc()))).scalars().all()
        return [dead_letter_to_response(row) for row in rows]

    @router.post("/dlq/push", response_model=DeadLetterResponse)
    async def push_dlq(
        req: DeadLetterPushRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        raise HTTPException(
            status_code=410,
            detail="legacy step-based DLQ push is retired; graph-native failures are recorded in graph state",
        )

    @router.post("/dlq/{dlq_id}/replay")
    async def replay_dlq(
        dlq_id: str,
        req: DeadLetterReplayRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        raise HTTPException(
            status_code=410,
            detail="legacy step-based DLQ replay is retired; rerun graph-native sessions with /sessions/{session_id}/execute",
        )

    @router.post("/dlq/{dlq_id}/replay-request")
    async def request_dlq_replay(
        dlq_id: str,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        raise HTTPException(
            status_code=410,
            detail="legacy step-based DLQ replay is retired; rerun graph-native sessions with /sessions/{session_id}/execute",
        )

    @router.post("/dlq/{dlq_id}/dismiss")
    async def dismiss_dlq(
        dlq_id: str,
        req: DeadLetterDismissRequest,
        _: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        row = (await db.execute(select(DeadLetterRow).where(DeadLetterRow.dlq_id == dlq_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="dlq entry not found")
        row.status = "DISMISSED"
        row.dismissed_at = datetime.utcnow()
        who = req.dismissed_by or "ops"
        row.dismissed_reason = f"{who}: {req.dismissed_reason}"
        await db.commit()
        return {"ok": True}

    return router
