from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models import Approval as ApprovalRow
from models import ExecutionSnapshot as SnapshotRow
from models import Message as MessageRow
from models import Plan as PlanRow
from models import PlanStep as PlanStepRow
from models import Session as SessionRow
from models import generate_uuid

from .events import AgentEvent
from .metrics import metrics
from .schemas import ToolInfo
from .telemetry import log_event


async def _repair_empty_predicate_result(
    self,
    *,
    session: SessionRow,
    plan: PlanRow,
    step: PlanStepRow,
    tool: ToolInfo,
    original_args: dict[str, Any],
    original_body: dict[str, Any] | None,
    live_coverage: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Try alternative schema fields when a filtered GET returns empty.

    Iterates through candidate_fields (ranked by confidence) that were
    produced by the intent verifier.  The first alternative that returns
    a non-empty result is adopted.  If all alternatives are also empty,
    returns a synthesised body with a user-friendly explanation.

    Returns the repaired body (ready to assign to step.result), or None
    if the result should be kept as-is (e.g. repair disabled / no candidates).
    """
    from . import execution as execution_module

    del original_body
    tried_args = dict(original_args or {})
    repair_candidates = self._get_repair_candidates(
        session=session, step=step, tool=tool, live_coverage=live_coverage, tried_args=tried_args
    )
    if not repair_candidates:
        return None

    # Record the originally tried field(s) from the live coverage.
    tried_fields: list[str] = []
    for p in live_coverage.get("predicates") or []:
        if isinstance(p, dict) and p.get("verified") == "unknown_empty":
            f = p.get("field")
            if f and f not in tried_fields:
                tried_fields.append(f)

    for candidate in repair_candidates:
        alt_field: str = candidate["field"]
        alt_value: Any = candidate["value"]
        repaired_args = dict(original_args)
        # Remove the original field binding and apply the alternative.
        orig_field = candidate.get("tried_field")
        if orig_field and orig_field in repaired_args:
            del repaired_args[orig_field]
        repaired_args[alt_field] = alt_value

        log_event(
            "predicate_repair_attempt",
            session_id=session.session_id,
            step_id=step.step_id,
            tool=tool.name,
            alt_field=alt_field,
            alt_value=alt_value,
            confidence=candidate["confidence"],
        )

        # Compute a fresh idempotency key for the repair attempt so it
        # does not collide with the original step snapshot.
        repair_idem_key = execution_module.compute_idempotency_key(
            session_id=session.session_id,
            step_index=int(step.step_index or 0),
            plan_version=plan.version,
            args=repaired_args,
        )
        try:
            repair_body, _ = await self._execute_tool_call(
                tool=tool,
                args=repaired_args,
                idempotency_key=repair_idem_key,
                plan_hash=plan.plan_hash,
                plan_version=plan.version,
                session_id=session.session_id,
                step_id=step.step_id,
                db=db,
            )
        except Exception as exc:
            log_event(
                "predicate_repair_attempt_failed",
                level="WARNING",
                session_id=session.session_id,
                step_id=step.step_id,
                tool=tool.name,
                alt_field=alt_field,
                error=str(exc),
            )
            tried_fields.append(alt_field)
            continue

        items = execution_module._result_items(repair_body)
        tried_fields.append(alt_field)

        if items is not None and len(items) > 0:
            # Success - annotate the body so callers can see what happened.
            if isinstance(repair_body, dict):
                repair_body = dict(repair_body)
                repair_body["_repair_meta"] = {
                    "repaired": True,
                    "original_field": orig_field,
                    "repaired_field": alt_field,
                    "repaired_value": alt_value,
                    "tried_fields": tried_fields,
                }
                # Carry the new args forward so summaries reference the right field.
                step.args = repaired_args
            log_event(
                "predicate_repair_success",
                session_id=session.session_id,
                step_id=step.step_id,
                tool=tool.name,
                repaired_field=alt_field,
                items_found=len(items),
            )
            return repair_body

    # All candidates exhausted - build a helpful terminal message.
    tried_label = " and ".join(tried_fields) if tried_fields else "available fields"
    raw_term = (
        repair_candidates[0]["value"]
        if repair_candidates
        else str(next(iter(original_args.values()), "the given filter"))
    )
    entity = tool.endpoint.strip("/").split("/")[0] if tool.endpoint else "records"
    exhausted_body: dict[str, Any] = {
        "success": True,
        "data": [],
        "_repair_meta": {
            "repaired": False,
            "exhausted": True,
            "tried_fields": tried_fields,
            "raw_term": raw_term,
        },
        "_summary": (
            f'No {entity} found for "{raw_term}" after checking '
            f"likely fields: {tried_label}."
        ),
    }
    log_event(
        "predicate_repair_exhausted",
        level="WARNING",
        session_id=session.session_id,
        step_id=step.step_id,
        tool=tool.name,
        tried_fields=tried_fields,
        raw_term=raw_term,
    )
    return exhausted_body


async def _execute_parallel_group(
    self,
    db: AsyncSession,
    *,
    session: SessionRow,
    plan: PlanRow,
    group_steps: list[PlanStepRow],
    steps: list[PlanStepRow],
    tools_by_name: dict[str, ToolInfo],
):
    from . import execution as execution_module

    ToolHTTPError = execution_module.ToolHTTPError
    PredicateVerificationError = execution_module.PredicateVerificationError
    ExecuteResult = execution_module.ExecuteResult

    bind = db.bind
    if bind is None:
        return await self._fail_hard(
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
            return await self._fail_hard(
                db,
                session=session,
                step=step,
                reason=f"Unknown tool: {step.tool_name}",
                failure_type="unrecoverable_error",
                payload={"tool_name": step.tool_name},
            )
        claimed = await self._claim_step(db, step_id=step.step_id)
        if not claimed:
            refreshed = await db.get(PlanStepRow, step.step_id)
            if refreshed and refreshed.status == "DONE":
                continue
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
        step.status = "IN_PROGRESS"
        step.started_at = step.started_at or datetime.utcnow()
        self._log_step_status_change(session=session, plan=plan, step=step, tool=tool, status=step.status)
        runnable.append((step, tool))

    if len(runnable) <= 1:
        return None

    session.status = "EXECUTING"
    session.version += 1
    await db.commit()

    async def run_one(step: PlanStepRow, tool: ToolInfo) -> tuple[PlanStepRow, ToolInfo, dict[str, Any] | None, Exception | None]:
        try:
            async with session_factory() as task_db:
                body, _ = await self._execute_tool_call(
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
            await self._complete_step_with_body(
                db,
                session=session,
                plan=plan,
                step=step,
                tool=tool,
                body=body,
            )
            continue
        decision = self._classify_error(err=exc, tool=tool, step=step)
        step.status = "AMBIGUOUS" if decision == "AMBIGUOUS" else "FAILED"
        step.last_error = str(exc)
        step.completed_at = datetime.utcnow()
        self._log_step_status_change(
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
            dlq = await self._push_dlq(
                db,
                session_id=session.session_id,
                step_id=failed_step.step_id,
                failure_type="ambiguous_execution",
                reason=str(exc),
                payload={"tool": failed_tool.name, "endpoint": failed_tool.endpoint, "args": failed_step.args},
            )
            await self._event_bus.publish(
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
            return await self._trigger_replan(
                db,
                session=session,
                plan=plan,
                steps=steps,
                failed_step=failed_step,
                reason=reason,
            )
        return await self._fail_hard(
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
    metrics.inc("parallel_group_completed_total")
    return None


async def execute_until_blocked(
    self,
    db: AsyncSession,
    *,
    session: SessionRow,
    tools_by_name: dict[str, ToolInfo],
):
    from . import execution as execution_module

    ToolHTTPError = execution_module.ToolHTTPError
    PredicateVerificationError = execution_module.PredicateVerificationError
    ExecuteResult = execution_module.ExecuteResult

    if not session.plan_id:
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

    plan: PlanRow | None = (
        await db.execute(select(PlanRow).where(PlanRow.plan_id == session.plan_id))
    ).scalars().first()
    if not plan:
        session.status = "FAILED"
        session.error = "Plan not found"
        session.version += 1
        await db.commit()
        metrics.inc("session_failed_total", labels={"reason": "plan_not_found"})
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

    steps = (
        await db.execute(
            select(PlanStepRow)
            .where(PlanStepRow.plan_id == plan.plan_id)
            .order_by(PlanStepRow.step_index.asc())
        )
    ).scalars().all()
    steps_by_index = {int(step.step_index): step for step in steps}
    parallel_groups = self._parallel_groups_for_plan(plan)
    step_to_group: dict[int, list[int]] = {}
    for group in parallel_groups:
        for step_index in group:
            step_to_group[step_index] = group

    limit_result = await self._check_limits_and_fail_if_needed(db, session=session)
    if limit_result is not None:
        return limit_result

    while session.current_step_index < len(steps):
        limit_result = await self._check_limits_and_fail_if_needed(db, session=session)
        if limit_result is not None:
            return limit_result
        if self._settings.redis_url and hasattr(self._event_bus, "healthy") and not self._event_bus.healthy:
            session.status = "BLOCKED"
            session.error = "Redis unavailable - execution paused"
            session.version += 1
            await db.commit()
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

        current_idx = int(session.current_step_index)
        parallel_group = step_to_group.get(current_idx)
        if parallel_group:
            group_steps = [
                steps_by_index[idx]
                for idx in parallel_group
                if idx in steps_by_index and steps_by_index[idx].status not in ("DONE", "SKIPPED")
            ]
            if len(group_steps) > 1:
                result = await self._execute_parallel_group(
                    db,
                    session=session,
                    plan=plan,
                    group_steps=group_steps,
                    steps=steps,
                    tools_by_name=tools_by_name,
                )
                if result is not None:
                    return result
                session.current_step_index = max(parallel_group) + 1
                session.version += 1
                await db.commit()
                compacted = await self._memory_manager.maybe_compact(
                    db,
                    session_id=session.session_id,
                    step_count=session.step_count,
                )
                if compacted:
                    log_event(
                        "memory_compacted",
                        session_id=session.session_id,
                        step_count=session.step_count,
                    )
                if session.pending_user_message:
                    return await self._trigger_replan(
                        db,
                        session=session,
                        plan=plan,
                        steps=steps,
                        failed_step=None,
                        reason="mid_execution_user_message",
                        user_message=session.pending_user_message,
                    )
                continue

        step = steps[session.current_step_index]
        tool = tools_by_name.get(step.tool_name)
        if not tool:
            return await self._fail_hard(
                db,
                session=session,
                step=step,
                reason=f"Unknown tool: {step.tool_name}",
                failure_type="unrecoverable_error",
                payload={"tool_name": step.tool_name},
            )

        if session.pending_user_message:
            return await self._trigger_replan(
                db,
                session=session,
                plan=plan,
                steps=steps,
                failed_step=None,
                reason="mid_execution_user_message",
                user_message=session.pending_user_message,
            )

        if step.status in ("DONE", "SKIPPED"):
            session.current_step_index += 1
            session.version += 1
            await db.commit()
            continue

        try:
            await self._prepare_bound_step(
                db=db,
                session=session,
                plan=plan,
                step=step,
                tool=tool,
                steps_by_index=steps_by_index,
                tools_by_name=tools_by_name,
            )
        except Exception as e:
            decision = self._classify_error(err=e, tool=tool, step=step)
            if decision == "AMBIGUOUS":
                step.status = "AMBIGUOUS"
                step.last_error = str(e)
                session.status = "BLOCKED"
                session.error = str(e)
                session.version += 1
                await db.commit()
                await self._push_dlq(
                    db,
                    session_id=session.session_id,
                    step_id=step.step_id,
                    failure_type="ambiguous_binding",
                    reason=str(e),
                    payload={"tool": tool.name, "bindings": step.bindings or []},
                )
                return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
            return await self._trigger_replan(
                db,
                session=session,
                plan=plan,
                steps=steps,
                failed_step=step,
                reason=f"binding_resolution_failed: {e}",
            )

        if tool.requires_approval:
            if not step.approval_id:
                skipped, risk_override = await self._preflight_approval_guard(
                    session=session,
                    plan=plan,
                    step=step,
                    tool=tool,
                    db=db,
                )
                if skipped:
                    continue
                await self._create_approval(
                    db,
                    session_id=session.session_id,
                    step=step,
                    tool=tool,
                    risk_summary_override=risk_override or self._bulk_risk_summary(tool=tool, step=step),
                )
            approval = (
                await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == step.approval_id))
            ).scalars().first()
            if not approval or approval.status != "APPROVED":
                if approval and approval.status == "REJECTED":
                    metrics.inc("approval_rejected_total", labels={"tool": tool.name})
                    metrics.inc("approval_rejection_rate", labels={"tool": tool.name})
                    step.status = "SKIPPED"
                    step.last_error = approval.rejection_reason or f"Approval {approval.approval_id} rejected"
                    step.completed_at = datetime.utcnow()
                    self._log_step_status_change(
                        session=session,
                        plan=plan,
                        step=step,
                        tool=tool,
                        status=step.status,
                        approval_latency_ms=(
                            int((approval.decided_at - approval.created_at).total_seconds() * 1000)
                            if approval.decided_at and approval.created_at
                            else None
                        ),
                    )
                    session.status = "IDLE"
                    session.error = step.last_error
                    session.version += 1
                    await db.commit()
                    return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
                session.status = "WAITING_APPROVAL"
                session.version += 1
                await db.commit()
                return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
            if approval.decided_at and approval.created_at:
                wait_ms = int((approval.decided_at - approval.created_at).total_seconds() * 1000)
                metrics.observe("approval_wait_time_ms", float(max(wait_ms, 0)), labels={"tool": tool.name})

        claimed = await self._claim_step(db, step_id=step.step_id)
        if not claimed:
            refreshed = await db.get(PlanStepRow, step.step_id)
            if refreshed and refreshed.status == "DONE":
                session.current_step_index += 1
                session.version += 1
                await db.commit()
                continue
            return await self._trigger_replan(
                db,
                session=session,
                plan=plan,
                steps=steps,
                failed_step=refreshed or step,
                reason="step_lock_conflict",
            )
        step.status = "IN_PROGRESS"
        step.started_at = step.started_at or datetime.utcnow()
        self._log_step_status_change(session=session, plan=plan, step=step, tool=tool, status=step.status)

        session.status = "EXECUTING"
        session.version += 1
        await db.commit()

        existing_snapshot = (
            await db.execute(
                select(SnapshotRow)
                .where(SnapshotRow.idempotency_key == step.idempotency_key)
                .where(SnapshotRow.plan_hash == plan.plan_hash)
                .order_by(SnapshotRow.executed_at.desc())
            )
        ).scalars().first()
        if existing_snapshot and existing_snapshot.http_status and step.status != "DONE":
            snapshot_body = existing_snapshot.response_body if isinstance(existing_snapshot.response_body, dict) else None
            if self._is_soft_not_found(tool=tool, http_status=existing_snapshot.http_status, body=snapshot_body):
                step.status = "DONE"
                replay_body = dict(snapshot_body or {})
                replay_body["not_found"] = True
                replay_body["_summary"] = await self._build_not_found_summary(
                    tool_name=tool.name,
                    args=step.args or {},
                    body=snapshot_body,
                )
                step.result = replay_body
            else:
                step.status = "DONE" if existing_snapshot.http_status < 400 else "FAILED"
                step.result = existing_snapshot.response_body
            if step.status == "DONE":
                step.result = self._attach_result_analysis(
                    body=step.result if isinstance(step.result, dict) else None,
                    intent=session.current_intent,
                )
                coverage = self._verify_predicate_contract(
                    session=session,
                    step=step,
                    tool=tool,
                    body=step.result if isinstance(step.result, dict) else None,
                )
                if coverage and isinstance(step.result, dict):
                    step.result["_predicate_coverage"] = coverage
                step.result_summary = await self._summarize_step_result(
                    tool_name=tool.name,
                    body=step.result,
                    args=step.args,
                    intent=session.current_intent,
                )
            step.completed_at = datetime.utcnow()
            self._log_step_status_change(
                session=session,
                plan=plan,
                step=step,
                tool=tool,
                status=step.status,
                latency_ms=existing_snapshot.latency_ms,
                http_status=existing_snapshot.http_status,
                idempotent_replay=True,
            )
            metrics.inc("idempotent_replay_total", labels={"tool": tool.name})
            metrics.inc("idempotent_replay_rate", labels={"tool": tool.name})
            log_event(
                "idempotent_replay_hit",
                session_id=session.session_id,
                step_id=step.step_id,
                tool=tool.name,
                http_status=existing_snapshot.http_status,
                idempotency_key=step.idempotency_key,
            )
            session.version += 1
            if step.status == "DONE":
                await self._append_tool_result_message(
                    db,
                    session_id=session.session_id,
                    step=step,
                    intent=session.current_intent,
                )
            await db.commit()
        else:
            recovery_step_id = step.step_id
            recovery_session_id = session.session_id
            recovery_step_index = int(session.current_step_index or 0)
            while True:
                try:
                    if (getattr(step, "execution_mode", None) or "single") == "foreach":
                        body = await self._execute_foreach_step(
                            tool=tool,
                            step=step,
                            plan=plan,
                            session=session,
                            db=db,
                        )
                    else:
                        body, _ = await self._execute_tool_call(
                            tool=tool,
                            args=step.args,
                            idempotency_key=step.idempotency_key,
                            plan_hash=plan.plan_hash,
                            plan_version=plan.version,
                            session_id=session.session_id,
                            step_id=step.step_id,
                            db=db,
                        )
                    coverage = self._verify_predicate_contract(
                        session=session,
                        step=step,
                        tool=tool,
                        body=body,
                    )
                    # --- Schema-field repair loop ---
                    # If any predicate came back unknown_empty, the filter was
                    # sent but the result was empty - ambiguous.  Try alternative
                    # candidate fields before surfacing the empty result.
                    if (
                        coverage is not None
                        and coverage.get("unknown_count", 0) > 0
                        and tool.method == "GET"
                    ):
                        repaired = await self._repair_empty_predicate_result(
                            session=session,
                            plan=plan,
                            step=step,
                            tool=tool,
                            original_args=step.args or {},
                            original_body=body,
                            live_coverage=coverage,
                            db=db,
                        )
                        if repaired is not None:
                            body = repaired
                            # Re-run predicate verification on the repaired result.
                            coverage = self._verify_predicate_contract(
                                session=session,
                                step=step,
                                tool=tool,
                                body=body,
                            )
                    # --------------------------------
                    if coverage and isinstance(body, dict):
                        body["_predicate_coverage"] = coverage
                    body = self._attach_result_analysis(body=body, intent=session.current_intent) or body
                    step.status = "DONE"
                    step.result = body
                    step.result_summary = await self._summarize_step_result(
                        tool_name=tool.name,
                        body=body,
                        args=step.args,
                        intent=session.current_intent,
                    )
                    step.completed_at = datetime.utcnow()
                    self._log_step_status_change(
                        session=session,
                        plan=plan,
                        step=step,
                        tool=tool,
                        status=step.status,
                    )
                    log_event(
                        "step_completed",
                        session_id=session.session_id,
                        plan_id=plan.plan_id,
                        plan_version=plan.version,
                        step_id=step.step_id,
                        step_index=step.step_index,
                        tool=tool.name,
                        status=step.status,
                        session_step_count=session.step_count,
                        session_llm_call_count=session.llm_call_count,
                        session_replan_count=session.replan_count,
                    )
                    session.version += 1
                    await self._append_tool_result_message(
                        db,
                        session_id=session.session_id,
                        step=step,
                        intent=session.current_intent,
                    )
                    await db.commit()
                    break
                except Exception as e:
                    if isinstance(e, SQLAlchemyError):
                        await db.rollback()
                        # Database outage mid-step: release the claim so the step can be retried safely.
                        await db.execute(
                            update(PlanStepRow)
                            .where(PlanStepRow.step_id == recovery_step_id)
                            .values(
                                status="NOT_STARTED",
                                started_at=None,
                                last_error=f"Transient DB failure: {e}",
                            )
                        )
                        await db.execute(
                            update(SessionRow)
                            .where(SessionRow.session_id == recovery_session_id)
                            .values(
                                status="EXECUTING",
                                error="Transient DB failure; step reset for retry",
                                version=(SessionRow.version + 1),
                            )
                        )
                        await db.commit()
                        return ExecuteResult(status="EXECUTING", current_step_index=recovery_step_index)
                    decision = self._classify_error(err=e, tool=tool, step=step)
                    error_type = type(e).__name__
                    metrics.inc("tool_error_total", labels={"tool": tool.name, "error_type": error_type})
                    metrics.inc("tool_error_rate", labels={"tool": tool.name, "error_type": error_type})
                    log_event(
                        "step_error",
                        level="WARNING",
                        session_id=session.session_id,
                        step_id=step.step_id,
                        tool=tool.name,
                        decision=decision,
                        error_type=error_type,
                        error=str(e),
                        retry_count=step.retry_count,
                    )
                    if decision == "RETRY":
                        step.retry_count += 1
                        session.retry_count += 1
                        metrics.inc("retry_total", labels={"tool": tool.name})
                        metrics.inc("retry_rate", labels={"tool": tool.name})
                        session.version += 1
                        await db.commit()
                        delay = min(
                            self._settings.retry_base_delay_s * (2 ** (step.retry_count - 1)),
                            self._settings.retry_max_delay_s,
                        )
                        await asyncio.sleep(delay)
                        continue
                    if decision == "AMBIGUOUS":
                        step.status = "AMBIGUOUS"
                        step.last_error = str(e)
                        self._log_step_status_change(
                            session=session,
                            plan=plan,
                            step=step,
                            tool=tool,
                            status=step.status,
                        )
                        session.status = "BLOCKED"
                        session.error = str(e)
                        session.version += 1
                        await db.commit()
                        dlq = await self._push_dlq(
                            db,
                            session_id=session.session_id,
                            step_id=step.step_id,
                            failure_type="ambiguous_execution",
                            reason=str(e),
                            payload={"tool": tool.name, "endpoint": tool.endpoint, "args": step.args},
                        )
                        await self._event_bus.publish(
                            AgentEvent(
                                event_type="session_resume",
                                session_id=session.session_id,
                                payload={"blocked_by": "AMBIGUOUS", "dlq_id": dlq.dlq_id},
                                published_at=datetime.utcnow(),
                            )
                        )
                        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
                    if decision == "REPLAN":
                        status_code = e.status_code if isinstance(e, ToolHTTPError) else None
                        if status_code == 409:
                            metrics.inc("payload_mismatch_409_total", labels={"tool": tool.name})
                            metrics.inc("payload_mismatch_409_rate", labels={"tool": tool.name})
                        reason = f"HTTP {status_code}" if status_code is not None else str(e)
                        if isinstance(e, PredicateVerificationError):
                            reason = f"predicate_mismatch: {reason}"
                        return await self._trigger_replan(
                            db,
                            session=session,
                            plan=plan,
                            steps=steps,
                            failed_step=step,
                            reason=reason,
                        )
                    failure_type = "unrecoverable_error"
                    return await self._fail_hard(
                        db,
                        session=session,
                        step=step,
                        reason=str(e),
                        failure_type=failure_type,
                        payload={"tool": tool.name, "endpoint": tool.endpoint, "args": step.args},
                    )

        session.current_step_index += 1
        session.step_count += 1
        session.version += 1
        await db.commit()
        compacted = await self._memory_manager.maybe_compact(
            db,
            session_id=session.session_id,
            step_count=session.step_count,
        )
        if compacted:
            log_event(
                "memory_compacted",
                session_id=session.session_id,
                step_count=session.step_count,
            )

        if session.pending_user_message:
            return await self._trigger_replan(
                db,
                session=session,
                plan=plan,
                steps=steps,
                failed_step=None,
                reason="mid_execution_user_message",
                user_message=session.pending_user_message,
            )

    plan.status = "COMPLETED"
    session.status = "COMPLETED"
    session.completed_at = datetime.utcnow()
    session.version += 1
    last_step_result_has_data = False
    if steps:
        last_step = steps[-1]
        last_step_result_has_data = self._result_has_records(
            last_step.result if isinstance(last_step.result, dict) else None
        )
    if not last_step_result_has_data:
        completion_text = await self._build_completion_text(
            plan_kind=(getattr(plan, "kind", None) or "execution"),
            step_count=session.step_count,
        )
        db.add(
            MessageRow(
                message_id=generate_uuid(),
                session_id=session.session_id,
                role="assistant",
                content=completion_text,
                tool_name="__session__",
            )
        )
    await db.commit()
    metrics.inc("session_completed_total")
    metrics.inc("session_completion_rate")
    metrics.observe("steps_per_session", float(session.step_count))
    log_event(
        "session_completed",
        session_id=session.session_id,
        plan_id=plan.plan_id,
        step_count=session.step_count,
        replan_count=session.replan_count,
        llm_call_count=session.llm_call_count,
    )
    return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
