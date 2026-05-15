from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.database import get_db
from factory_agent.schemas import PlanCreateRequest, PlanResponse, ValidationErrorResponse
from factory_agent.services.plan_creation_service import PlanCreationService


def build_plans_router(
    *,
    plan_creation_service: PlanCreationService,
    require_jwt: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/sessions/{session_id}/plans",
        response_model=PlanResponse,
        responses={400: {"model": ValidationErrorResponse}},
    )
    async def create_plan(
        session_id: str,
        req: PlanCreateRequest,
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        return await plan_creation_service.create_plan(
            db=db,
            session_id=session_id,
            req=req,
            user=user,
        )

    return router
