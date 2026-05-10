from __future__ import annotations

from datetime import datetime
from typing import Any

from ...persistence.models import ExecutionSnapshot as SnapshotRow
from ...persistence.models import generate_uuid
from ...schemas import ToolInfo


async def record_snapshot(
    db: Any,
    *,
    step_id: str,
    session_id: str,
    tool: ToolInfo,
    args: dict[str, Any],
    plan_hash: str,
    plan_version: int,
    idempotency_key: str,
    http_status: int | None,
    response_body: dict[str, Any] | None,
    latency_ms: int | None,
) -> None:
    snapshot = SnapshotRow(
        snapshot_id=generate_uuid(),
        step_id=step_id,
        session_id=session_id,
        tool_name=tool.name,
        tool_version=1,
        schema_version=1,
        input_args=args,
        plan_hash=plan_hash,
        plan_version=plan_version,
        idempotency_key=idempotency_key,
        http_status=http_status,
        response_body=response_body,
        latency_ms=latency_ms,
        executed_at=datetime.utcnow(),
    )
    db.add(snapshot)
    await db.commit()
