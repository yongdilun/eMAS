from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.database import get_db
from factory_agent.planning.tool_selector import ToolSelector
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import ToolInfo
from factory_agent.security.permissions import filter_tools_for_role, role_from_claims


def build_tools_router(
    *,
    tool_registry: ToolRegistry,
    tool_selector: ToolSelector,
    require_jwt: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/tools", response_model=list[ToolInfo])
    async def list_tools(
        intent: str | None = Query(None, description="Optional user intent to scope tools."),
        max_tools: int = Query(30, ge=1, le=200, description="Maximum tools returned."),
        user: dict[str, Any] = Depends(require_jwt),
        db: AsyncSession = Depends(get_db),
    ):
        tools_by_name = await tool_registry.get_tools_by_name(db)
        tools_by_name = filter_tools_for_role(tools_by_name, role=role_from_claims(user))
        if intent:
            selection = await tool_selector.select_tools(intent=intent, tools_by_name=tools_by_name, max_tools=max_tools)
            return [tools_by_name[name] for name in selection.tool_names if name in tools_by_name]
        names = sorted(tools_by_name.keys())[:max_tools]
        return [tools_by_name[name] for name in names]

    return router
