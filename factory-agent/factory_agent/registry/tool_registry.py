from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.models import Tool as ToolRow

from ..schemas import ToolInfo


_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def default_tools_md_path() -> str:
    """Filesystem path for generated tool markdown (same default ToolRegistry loads)."""
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools.md"))


def default_id_patterns_path() -> str:
    """Filesystem path for generated id pattern catalog (from OpenAPI schemas)."""
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "generated", "id_patterns.json"))


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip().lower() for x in parsed if str(x).strip()]
    except Exception:
        pass
    normalized = str(raw).strip()
    if not normalized:
        return []
    for separator in (",", "|"):
        if separator in normalized:
            return [t.strip().lower() for t in normalized.split(separator) if t.strip()]
    return [normalized.lower()]


@dataclass(frozen=True)
class RegistryHealthResult:
    ok: bool
    message: str | None = None


def tool_row_to_info(row: ToolRow) -> ToolInfo:
    schema = row.input_schema if isinstance(row.input_schema, dict) else {}
    output_schema = row.output_schema if isinstance(row.output_schema, dict) else {"type": "object"}
    path_params = [str(x) for x in (schema.get("x-path-params") or []) if str(x)]
    if not path_params:
        path_params = [match.group(1) for match in _PATH_PARAM_RE.finditer(row.endpoint or "")]

    query_params = [str(x) for x in (schema.get("x-query-params") or []) if str(x)]
    param_sources = {
        str(key): str(val)
        for key, val in (schema.get("x-param-sources") or {}).items()
        if str(key) and str(val)
    }
    for key in path_params:
        param_sources.setdefault(key, "path")
    for key in query_params:
        param_sources.setdefault(key, "query")

    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    inferred_body_fields = [
        str(name)
        for name in properties.keys()
        if str(name) not in set(path_params) | set(query_params)
    ]
    body_fields = [str(x) for x in (schema.get("x-body-fields") or []) if str(x)] or inferred_body_fields
    required_fields = [str(x) for x in (schema.get("required") or []) if str(x)]
    required_body_fields = [str(x) for x in (schema.get("x-body-required") or []) if str(x)] or [
        name for name in required_fields if name in set(body_fields)
    ]

    return ToolInfo(
        name=row.name,
        description=row.description,
        endpoint=row.endpoint,
        method=row.method,
        input_schema=schema,
        output_schema=output_schema,
        path_params=path_params,
        query_params=query_params,
        body_fields=body_fields,
        required_body_fields=required_body_fields,
        body_schema=schema.get("x-body-schema") if isinstance(schema.get("x-body-schema"), dict) else None,
        param_sources=param_sources,
        is_read_only=bool(row.is_read_only),
        requires_approval=bool(row.requires_approval),
        side_effect_level=row.side_effect_level or "NONE",
        is_concurrency_safe=bool(row.is_concurrency_safe),
        is_strongly_idempotent=bool(row.is_strongly_idempotent),
        capability_tags=_parse_tags(row.capability_tags),
        allowed_roles=[
            str(x).strip().lower()
            for x in (schema.get("x-allowed-roles") or [])
            if str(x).strip()
        ],
    )


@dataclass
class ToolRegistrySnapshot:
    tools_by_name: dict[str, ToolInfo]
    loaded_at: datetime


class ToolRegistry:
    def __init__(self, *, tools_md_path: str | None = None):
        self._snapshot: ToolRegistrySnapshot | None = None
        self._tools_md_path = tools_md_path or default_tools_md_path()

    async def load_from_db(self, db: AsyncSession) -> ToolRegistrySnapshot:
        await self.normalize_legacy_tags(db)
        rows = (await db.execute(select(ToolRow))).scalars().all()
        tools_by_name = {r.name: tool_row_to_info(r) for r in rows}
        self._snapshot = ToolRegistrySnapshot(tools_by_name=tools_by_name, loaded_at=datetime.utcnow())
        return self._snapshot

    async def normalize_legacy_tags(self, db: AsyncSession) -> None:
        rows = (await db.execute(select(ToolRow))).scalars().all()
        dirty = False
        for row in rows:
            normalized = _parse_tags(row.capability_tags)
            normalized_json = json.dumps(normalized)
            if (row.capability_tags or "") != normalized_json:
                row.capability_tags = normalized_json
                dirty = True
        if dirty:
            await db.commit()

    async def get_tools_by_name(self, db: AsyncSession) -> dict[str, ToolInfo]:
        if not self._snapshot:
            await self.load_from_db(db)
        return dict(self._snapshot.tools_by_name) if self._snapshot else {}

    async def refresh(self, db: AsyncSession) -> dict[str, ToolInfo]:
        snapshot = await self.load_from_db(db)
        return dict(snapshot.tools_by_name)

    async def regenerate_from_openapi(
        self,
        db: AsyncSession,
        *,
        openapi_url: str,
        local_swagger_json_path: str,
        force_local: bool = False,
        replace_db: bool = True,
    ):
        from .toolgen import fetch_openapi_spec, tools_from_openapi, write_tools_md_and_meta

        spec = fetch_openapi_spec(
            openapi_url=openapi_url,
            local_swagger_json_path=local_swagger_json_path,
            force_local=force_local,
        )
        tools = tools_from_openapi(spec)
        result = await write_tools_md_and_meta(
            db,
            tools=tools,
            tools_md_path=self._tools_md_path,
            replace_db=replace_db,
        )
        await self.refresh(db)
        return result

    def load_tools_markdown(self) -> str:
        try:
            with open(self._tools_md_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return "# Available Tools\n\n(Unable to load tools.md)"

    def assess_health(self, tools_by_name: dict[str, ToolInfo], *, min_tool_count: int) -> RegistryHealthResult:
        if len(tools_by_name) < min_tool_count:
            return RegistryHealthResult(
                ok=False,
                message=f"Tool registry is incomplete: expected at least {min_tool_count} tools, found {len(tools_by_name)}.",
            )

        invalid: list[str] = []
        for name, tool in tools_by_name.items():
            if not tool.endpoint or not tool.method or not isinstance(tool.input_schema, dict):
                invalid.append(name)
                continue
            if not tool.capability_tags:
                invalid.append(name)
        if invalid:
            sample = ", ".join(invalid[:5])
            suffix = "" if len(invalid) <= 5 else f", and {len(invalid) - 5} more"
            return RegistryHealthResult(
                ok=False,
                message=f"Tool registry contains incomplete tool metadata: {sample}{suffix}.",
            )
        return RegistryHealthResult(ok=True, message=None)


