from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import datetime
import os

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.api.response_mappers import approval_to_response, dead_letter_to_response, session_to_response
from factory_agent.observability.events import AgentEvent, EventBus
from factory_agent.observability.metrics import metrics
from factory_agent.observability.telemetry import log_event
from factory_agent.persistence.database import get_db
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import DeadLetter as DeadLetterRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import ApprovalResponse, DeadLetterResponse


def build_admin_router(
    *,
    tool_registry: ToolRegistry,
    event_bus: EventBus,
    require_admin: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    @router.post("/admin/regenerate-tools")
    async def regenerate_tools(
        _: None = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
    ):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        local_swagger = os.path.join(repo_root, "emas", "docs", "swagger.json")
        openapi_url = os.environ.get("OPENAPI_URL", "http://localhost:8080/swagger/doc.json")
        force_local = os.environ.get("OPENAPI_LOCAL", "").strip() == "1" or os.path.exists(local_swagger)

        result = await tool_registry.regenerate_from_openapi(
            db,
            openapi_url=openapi_url,
            local_swagger_json_path=local_swagger,
            force_local=force_local,
            replace_db=True,
        )
        await event_bus.publish(
            AgentEvent(
                event_type="tool_registry_updated",
                session_id="",
                payload={"tool_count": result.tool_count, "tools_md_hash": result.tools_md_hash},
                published_at=datetime.utcnow(),
            )
        )
        log_event("tool_registry_regenerated", tool_count=result.tool_count, tools_md_hash=result.tools_md_hash)
        return {"ok": True, "tool_count": result.tool_count, "tools_md_hash": result.tools_md_hash}

    @router.get("/metrics", response_class=PlainTextResponse)
    async def get_metrics(_: None = Depends(require_admin)):
        return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")

    @router.get("/admin/sessions", dependencies=[Depends(require_admin)])
    async def admin_list_sessions(
        status: str | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(SessionRow).order_by(SessionRow.updated_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(SessionRow.status == status)
        rows = (await db.execute(stmt)).scalars().all()
        return [session_to_response(row) for row in rows]

    @router.get("/admin/approvals/pending", dependencies=[Depends(require_admin)], response_model=list[ApprovalResponse])
    async def admin_pending_approvals(db: AsyncSession = Depends(get_db)):
        rows = (
            await db.execute(select(ApprovalRow).where(ApprovalRow.status == "PENDING").order_by(ApprovalRow.created_at.asc()))
        ).scalars().all()
        return [approval_to_response(row) for row in rows]

    @router.get("/admin/dlq", dependencies=[Depends(require_admin)], response_model=list[DeadLetterResponse])
    async def admin_list_dlq(
        status: str | None = Query(None),
        session_id: str | None = Query(None),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(DeadLetterRow)
        if status:
            stmt = stmt.where(DeadLetterRow.status == status)
        if session_id:
            stmt = stmt.where(DeadLetterRow.session_id == session_id)
        rows = (await db.execute(stmt.order_by(DeadLetterRow.created_at.desc()))).scalars().all()
        return [dead_letter_to_response(row) for row in rows]

    @router.get("/admin/tools", dependencies=[Depends(require_admin)])
    async def admin_list_tools(db: AsyncSession = Depends(get_db)):
        tools_by_name = await tool_registry.get_tools_by_name(db)
        return [tools_by_name[name] for name in sorted(tools_by_name.keys())]

    @router.post("/admin/faults/redis/down", dependencies=[Depends(require_admin)])
    async def admin_fault_redis_down():
        # Fault injection hook for chaos testing (E4.3).
        setattr(event_bus, "_fault_injected", True)
        setattr(event_bus, "_healthy", False)
        return {"ok": True, "redis_fault": "down"}

    @router.post("/admin/faults/redis/up", dependencies=[Depends(require_admin)])
    async def admin_fault_redis_up():
        setattr(event_bus, "_fault_injected", False)
        with contextlib.suppress(Exception):
            await event_bus.reconnect()
        return {"ok": True, "redis_fault": "up"}

    @router.get("/admin/dashboard", dependencies=[Depends(require_admin)], response_class=HTMLResponse)
    async def admin_dashboard(db: AsyncSession = Depends(get_db)):
        sessions = (
            await db.execute(select(SessionRow).order_by(SessionRow.updated_at.desc()).limit(200))
        ).scalars().all()
        approvals = (
            await db.execute(select(ApprovalRow).where(ApprovalRow.status == "PENDING").order_by(ApprovalRow.created_at.asc()))
        ).scalars().all()
        dlq_rows = (
            await db.execute(select(DeadLetterRow).where(DeadLetterRow.status == "PENDING").order_by(DeadLetterRow.created_at.desc()))
        ).scalars().all()
        tools_by_name = await tool_registry.get_tools_by_name(db)

        session_rows = "".join(
            f"<tr><td>{s.session_id}</td><td>{s.user_id}</td><td>{s.status}</td><td>{s.current_step_index}</td><td>{s.error or ''}</td></tr>"
            for s in sessions
        )
        approval_rows = "".join(
            f"<tr><td>{a.approval_id}</td><td>{a.session_id}</td><td>{a.tool_name}</td><td>{a.status}</td></tr>"
            for a in approvals
        )
        dlq_html_rows = "".join(
            f"<tr><td>{d.dlq_id}</td><td>{d.session_id}</td><td>{d.failure_type}</td><td>{d.reason}</td></tr>"
            for d in dlq_rows
        )
        tool_rows = "".join(
            f"<tr><td>{t.name}</td><td>{t.method}</td><td>{t.endpoint}</td><td>{'yes' if t.requires_approval else 'no'}</td></tr>"
            for t in sorted(tools_by_name.values(), key=lambda x: x.name)
        )

        html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Factory Agent Admin Dashboard</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, sans-serif; margin: 24px; background: #f2f7fb; color: #112; }}
    h1 {{ margin: 0 0 8px 0; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
    section {{ background: #fff; border-radius: 12px; padding: 14px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #e7edf4; }}
    th {{ background: #eef5ff; }}
  </style>
</head>
<body>
  <h1>Factory Agent Dashboard</h1>
  <p>Sessions: {len(sessions)} | Pending approvals: {len(approvals)} | Pending DLQ: {len(dlq_rows)} | Tools: {len(tools_by_name)}</p>
  <div class="grid">
    <section>
      <h2>Sessions</h2>
      <table><thead><tr><th>Session</th><th>User</th><th>Status</th><th>Step</th><th>Error</th></tr></thead><tbody>{session_rows}</tbody></table>
    </section>
    <section>
      <h2>Approval Queue</h2>
      <table><thead><tr><th>Approval</th><th>Session</th><th>Tool</th><th>Status</th></tr></thead><tbody>{approval_rows}</tbody></table>
    </section>
    <section>
      <h2>DLQ Viewer</h2>
      <table><thead><tr><th>DLQ</th><th>Session</th><th>Failure Type</th><th>Reason</th></tr></thead><tbody>{dlq_html_rows}</tbody></table>
    </section>
    <section>
      <h2>Tool Registry</h2>
      <table><thead><tr><th>Name</th><th>Method</th><th>Endpoint</th><th>Approval</th></tr></thead><tbody>{tool_rows}</tbody></table>
    </section>
  </div>
</body>
</html>
"""
        return HTMLResponse(content=html)

    return router
