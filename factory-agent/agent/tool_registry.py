from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Tool as ToolRow

from .schemas import ToolInfo


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except Exception:
        pass
    # Fallback: allow comma-separated text
    return [t.strip() for t in raw.split(",") if t.strip()]


def tool_row_to_info(row: ToolRow) -> ToolInfo:
    return ToolInfo(
        name=row.name,
        description=row.description,
        endpoint=row.endpoint,
        method=row.method,
        input_schema=row.input_schema,
        is_read_only=bool(row.is_read_only),
        requires_approval=bool(row.requires_approval),
        side_effect_level=row.side_effect_level or "NONE",
        is_concurrency_safe=bool(row.is_concurrency_safe),
        is_strongly_idempotent=bool(row.is_strongly_idempotent),
        capability_tags=_parse_tags(row.capability_tags),
    )


@dataclass
class ToolRegistrySnapshot:
    tools_by_name: dict[str, ToolInfo]
    loaded_at: datetime


class ToolRegistry:
    def __init__(self, *, tools_md_path: str | None = None):
        self._snapshot: ToolRegistrySnapshot | None = None
        self._tools_md_path = tools_md_path or os.path.join(os.path.dirname(__file__), "..", "tools.md")

    async def load_from_db(self, db: AsyncSession) -> ToolRegistrySnapshot:
        rows = (await db.execute(select(ToolRow))).scalars().all()
        tools_by_name = {r.name: tool_row_to_info(r) for r in rows}
        self._snapshot = ToolRegistrySnapshot(tools_by_name=tools_by_name, loaded_at=datetime.utcnow())
        return self._snapshot

    async def get_tools_by_name(self, db: AsyncSession) -> dict[str, ToolInfo]:
        if not self._snapshot:
            await self.load_from_db(db)
        return dict(self._snapshot.tools_by_name) if self._snapshot else {}

    def load_tools_markdown(self) -> str:
        try:
            with open(self._tools_md_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return "# Available Tools\n\n(Unable to load tools.md)"

