from __future__ import annotations

from typing import Any

from ...persistence.models import DeadLetter as DeadLetterRow
from ...persistence.models import generate_uuid
from ...observability.metrics import metrics
from ...observability.telemetry import log_event


async def push_dlq(
    db: Any,
    *,
    session_id: str,
    step_id: str | None,
    failure_type: str,
    reason: str,
    payload: dict[str, Any],
) -> DeadLetterRow:
    dlq = DeadLetterRow(
        dlq_id=generate_uuid(),
        session_id=session_id,
        step_id=step_id,
        failure_type=failure_type,
        reason=reason,
        payload=payload,
        status="PENDING",
    )
    db.add(dlq)
    await db.commit()
    await db.refresh(dlq)
    metrics.inc("dlq_push_total", labels={"failure_type": failure_type})
    metrics.inc("dlq_push_rate", labels={"failure_type": failure_type})
    log_event(
        "dlq_pushed",
        level="WARNING",
        session_id=session_id,
        step_id=step_id,
        failure_type=failure_type,
        reason=reason,
        dlq_id=dlq.dlq_id,
    )
    return dlq
