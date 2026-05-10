from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...persistence.models import Session as SessionRow
from ...persistence.models import Plan as PlanRow
from ...persistence.models import PlanStep as PlanStepRow
from ...schemas import ToolInfo
from ...observability.telemetry import log_event


class AmbiguousExecutionError(Exception):
    pass


async def claim_step(db: AsyncSession, *, step_id: str) -> bool:
    stmt = (
        update(PlanStepRow)
        .where(PlanStepRow.step_id == step_id)
        .where(PlanStepRow.status.in_(["NOT_STARTED", "FAILED"]))
        .values(status="IN_PROGRESS", started_at=datetime.utcnow())
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount == 1


def parallel_groups_for_plan(settings: Any, plan: PlanRow) -> list[list[int]]:
    if not settings.enable_parallel_execution:
        return []
    groups = plan.parallel_groups if isinstance(plan.parallel_groups, list) else []
    normalized: list[list[int]] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        indexes = sorted({int(idx) for idx in group})
        if len(indexes) >= 2:
            normalized.append(indexes)
    return normalized


async def execute_parallel_group(
    engine: Any,
    db: AsyncSession,
    *,
    session: SessionRow,
    plan: PlanRow,
    group_steps: list[PlanStepRow],
    steps: list[PlanStepRow],
    tools_by_name: dict[str, ToolInfo],
) -> Any:
    from .tool_caller import ToolHTTPError
    from .predicate_guard import PredicateVerificationError
    from .engine import ExecuteResult
    from ...observability.events import AgentEvent

    bind = db.bind
    if bind is None:
        from .failure_policy import fail_hard
        return await fail_hard(
            engine,
            db,
            session=session,
            step=group_steps[0],
            reason="Database bind unavailable for parallel execution",
            failure_type="parallel_execution_unavailable",
            payload={"step_indexes": [step.step_index for step in group_steps]},
        )

    session_factory = async_sessionmaker(bind=bind, class_=AsyncSession, expire_on_commit=False)
    runnable: list[tuple[PlanStepRow, ToolInfo]] = []
    for step in group_steps:
        if step.status in ("DONE", "SKIPPED"):
            continue
        tool = tools_by_name.get(step.tool_name)
        if not tool:
            from .failure_policy import fail_hard
            return await fail_hard(
                engine,
                db,
                session=session,
                step=step,
                reason=f"Unknown tool: {step.tool_name}",
                failure_type="unrecoverable_error",
                payload={"tool_name": step.tool_name},
            )
        claimed = await claim_step(db, step_id=step.step_id)
        if not claimed:
            refreshed = await db.get(PlanStepRow, step.step_id)
            if refreshed and refreshed.status == "DONE":
                continue
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
        step.status = "IN_PROGRESS"
        step.started_at = step.started_at or datetime.utcnow()
        engine._log_step_status_change(session=session, plan=plan, step=step, tool=tool, status=step.status)
        runnable.append((step, tool))

    if len(runnable) <= 1:
        return None

    session.status = "EXECUTING"
    session.version += 1
    await db.commit()

    async def run_one(step: PlanStepRow, tool: ToolInfo) -> tuple[PlanStepRow, ToolInfo, dict[str, Any] | None, Exception | None]:
        try:
            async with session_factory() as task_db:
                body, _ = await engine._execute_tool_call(
                    tool=tool,
                    args=step.args,
                    idempotency_key=step.idempotency_key,
                    plan_hash=plan.plan_hash,
                    plan_version=plan.version,
                    session_id=session.session_id,
                    step_id=step.step_id,
                    db=task_db,
                )
            return step, tool, body, None
        except Exception as exc:
            return step, tool, None, exc

    results = await asyncio.gather(
        *[run_one(step, tool) for step, tool in runnable],
        return_exceptions=False,
    )

    failures: list[tuple[PlanStepRow, ToolInfo, Exception, str]] = []
    for step, tool, body, exc in results:
        if exc is None:
            await engine._complete_step_with_body(
                db,
                session=session,
                plan=plan,
                step=step,
                tool=tool,
                body=body,
            )
            continue
        decision = engine._classify_error(err=exc, tool=tool, step=step)
        step.status = "AMBIGUOUS" if decision == "AMBIGUOUS" else "FAILED"
        step.last_error = str(exc)
        step.completed_at = datetime.utcnow()
        engine._log_step_status_change(
            session=session,
            plan=plan,
            step=step,
            tool=tool,
            status=step.status,
        )
        failures.append((step, tool, exc, decision))

    if failures:
        failed_step, failed_tool, exc, decision = failures[0]
        if decision == "AMBIGUOUS":
            session.status = "BLOCKED"
            session.error = str(exc)
            session.version += 1
            await db.commit()
            from .dlq import push_dlq
            dlq = await push_dlq(
                db,
                session_id=session.session_id,
                step_id=failed_step.step_id,
                failure_type="ambiguous_execution",
                reason=str(exc),
                payload={"tool": failed_tool.name, "endpoint": failed_tool.endpoint, "args": failed_step.args},
            )
            await engine._event_bus.publish(
                AgentEvent(
                    event_type="session_resume",
                    session_id=session.session_id,
                    payload={"blocked_by": "AMBIGUOUS", "dlq_id": dlq.dlq_id},
                    published_at=datetime.utcnow(),
                )
            )
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
        if decision in {"RETRY", "REPLAN"}:
            status_code = exc.status_code if isinstance(exc, ToolHTTPError) else None
            reason = f"HTTP {status_code}" if status_code is not None else str(exc)
            if isinstance(exc, PredicateVerificationError):
                reason = f"predicate_mismatch: {reason}"
            from .failure_policy import trigger_replan
            return await trigger_replan(
                engine,
                db,
                session=session,
                plan=plan,
                steps=steps,
                failed_step=failed_step,
                reason=reason,
            )
        from .failure_policy import fail_hard
        return await fail_hard(
            engine,
            db,
            session=session,
            step=failed_step,
            reason=str(exc),
            failure_type="parallel_step_error",
            payload={"tool": failed_tool.name, "endpoint": failed_tool.endpoint, "args": failed_step.args},
        )

    log_event(
        "parallel_group_completed",
        session_id=session.session_id,
        plan_id=plan.plan_id,
        group_size=len(runnable),
        step_indexes=[step.step_index for step, _ in runnable],
    )
    from ...observability.metrics import metrics
    metrics.inc("parallel_group_completed_total")
    return None
