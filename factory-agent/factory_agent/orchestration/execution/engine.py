from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...persistence.models import Session as SessionRow
from ...persistence.models import Plan as PlanRow
from ...persistence.models import PlanStep as PlanStepRow
from ...persistence.models import Message as MessageRow
from ...persistence.models import Approval as ApprovalRow
from ...persistence.models import ExecutionSnapshot as SnapshotRow
from ...persistence.models import generate_uuid
from ...config import Settings
from ...observability.events import AgentEvent, EventBus
from ..memory_manager import MemoryManager
from ...planning.reasoning_pipeline import ReasoningPipeline
from ...schemas import ToolInfo
from ...observability.metrics import metrics
from ...observability.telemetry import log_event, log_step_status_changed

from . import tool_caller, idempotency, approval_guard, failure_policy, predicate_guard, repair, snapshots, dlq, result_summary, foreach, parallel


@dataclass(frozen=True)
class ExecuteResult:
    status: str
    current_step_index: int


class ExecutionEngine:
    def __init__(self, settings: Settings, event_bus: EventBus):
        self._settings = settings
        self._event_bus = event_bus
        self._memory_manager = MemoryManager(settings)
        self._reasoning = ReasoningPipeline(settings)

    def _session_duration_s(self, session: SessionRow) -> int:
        if not session.session_started_at:
            return 0
        return int((datetime.utcnow() - session.session_started_at).total_seconds())

    def _checkpoint_state(self, session: SessionRow) -> dict[str, Any]:
        return {
            "status": session.status,
            "plan_id": session.plan_id,
            "plan_version": session.plan_version,
            "plan_hash": session.plan_hash,
            "current_step_index": session.current_step_index,
            "step_count": session.step_count,
            "replan_count": session.replan_count,
            "retry_count": session.retry_count,
            "llm_call_count": session.llm_call_count,
            "error": session.error,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }

    def _build_text_model(self):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.tool_result_summary_model,
            "temperature": 0,
            "timeout": self._settings.tool_result_summary_timeout_s,
            "max_retries": 0,
            "max_tokens": self._settings.tool_result_summary_max_tokens,
        }
        if self._settings.tool_result_summary_openai_base_url:
            kwargs["base_url"] = self._settings.tool_result_summary_openai_base_url
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    def _log_step_status_change(
        self,
        *,
        session: SessionRow,
        plan: PlanRow | None,
        step: PlanStepRow,
        tool: ToolInfo | None,
        status: str,
        latency_ms: int | None = None,
        http_status: int | None = None,
        idempotent_replay: bool = False,
        approval_latency_ms: int | None = None,
    ) -> None:
        log_step_status_changed(
            session_id=session.session_id,
            plan_id=plan.plan_id if plan else session.plan_id,
            plan_version=plan.version if plan else session.plan_version,
            step_id=step.step_id,
            step_index=step.step_index,
            tool=(tool.name if tool else step.tool_name or ""),
            is_strongly_idempotent=bool(tool.is_strongly_idempotent) if tool else None,
            status=status,
            latency_ms=latency_ms,
            http_status=http_status,
            idempotency_key=step.idempotency_key,
            idempotent_replay=idempotent_replay,
            required_approval=bool(step.requires_approval),
            approval_latency_ms=approval_latency_ms,
            session_step_count=session.step_count,
            session_llm_call_count=session.llm_call_count,
            session_replan_count=session.replan_count,
            session_duration_s=self._session_duration_s(session),
            user_id=session.user_id,
        )

    # Delegated methods
    async def _execute_tool_call(self, *args, **kwargs):
        return await tool_caller.execute_tool_call(self, *args, **kwargs)

    def _is_soft_not_found(self, *args, **kwargs):
        return result_summary.is_soft_not_found(*args, **kwargs)

    async def _build_not_found_summary(self, *args, **kwargs):
        return await result_summary.build_not_found_summary(self, *args, **kwargs)

    async def _record_snapshot(self, *args, **kwargs):
        return await snapshots.record_snapshot(*args, **kwargs)

    def _result_has_records(self, *args, **kwargs):
        return result_summary.result_has_records(*args, **kwargs)

    async def _build_completion_text(self, *args, **kwargs):
        return await result_summary.build_completion_text(self, *args, **kwargs)

    async def _summarize_step_result(self, *args, **kwargs):
        return await result_summary.summarize_step_result(self, *args, **kwargs)

    async def _append_tool_result_message(self, *args, **kwargs):
        return await result_summary.append_tool_result_message(self, *args, **kwargs)

    async def _preflight_approval_guard(self, *args, **kwargs):
        return await approval_guard.preflight_approval_guard(self, *args, **kwargs)

    async def _create_approval(self, *args, **kwargs):
        return await approval_guard.create_approval(self, *args, **kwargs)

    def _bulk_risk_summary(self, *args, **kwargs):
        return approval_guard.bulk_risk_summary(self._settings, *args, **kwargs)

    def _classify_error(self, *args, **kwargs):
        return failure_policy.classify_error(*args, **kwargs)

    async def _trigger_replan(self, *args, **kwargs):
        return await failure_policy.trigger_replan(self, *args, **kwargs)

    async def _fail_hard(self, *args, **kwargs):
        return await failure_policy.fail_hard(self, *args, **kwargs)

    async def _push_dlq(self, *args, **kwargs):
        return await dlq.push_dlq(*args, **kwargs)

    async def _prepare_bound_step(self, *args, **kwargs):
        return await foreach.prepare_bound_step(self, *args, **kwargs)

    async def _execute_foreach_step(self, *args, **kwargs):
        return await foreach.execute_foreach_step(self, *args, **kwargs)

    def _parallel_groups_for_plan(self, *args, **kwargs):
        return parallel.parallel_groups_for_plan(self._settings, *args, **kwargs)

    async def _execute_parallel_group(self, *args, **kwargs):
        return await parallel.execute_parallel_group(self, *args, **kwargs)

    def _verify_predicate_contract(self, *args, **kwargs):
        return predicate_guard.verify_predicate_contract(result_items_fn=foreach.result_items, *args, **kwargs)

    async def _repair_empty_predicate_result(self, *args, **kwargs):
        return await repair.repair_empty_predicate_result(self, *args, **kwargs)

    async def _check_limits_and_fail_if_needed(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
    ) -> ExecuteResult | None:
        duration_s = 0.0
        if session.session_started_at:
            duration_s = (datetime.utcnow() - session.session_started_at).total_seconds()
        limit_reason: str | None = None
        if session.step_count >= self._settings.max_session_steps:
            limit_reason = "MAX_SESSION_STEPS"
        elif session.replan_count >= self._settings.max_replans:
            limit_reason = "MAX_REPLANS"
        elif session.llm_call_count >= self._settings.max_llm_calls:
            limit_reason = "MAX_LLM_CALLS"
        elif duration_s >= self._settings.max_session_duration_s:
            limit_reason = "MAX_SESSION_DURATION_S"

        if not limit_reason:
            return None

        metrics.inc("sessions_rate_limited_total", labels={"limit_type": limit_reason})
        log_event(
            "session_rate_limit_hit",
            level="WARNING",
            session_id=session.session_id,
            limit_type=limit_reason,
            step_count=session.step_count,
            replan_count=session.replan_count,
            llm_call_count=session.llm_call_count,
            duration_s=duration_s,
        )
        session.status = "FAILED"
        session.error = f"Session limit exceeded: {limit_reason}"
        session.version += 1
        await db.commit()
        await self._push_dlq(
            db,
            session_id=session.session_id,
            step_id=None,
            failure_type="rate_limit_exceeded",
            reason=limit_reason,
            payload={
                "step_count": session.step_count,
                "replan_count": session.replan_count,
                "llm_call_count": session.llm_call_count,
                "duration_s": duration_s,
            },
        )
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

    async def _complete_step_with_body(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        plan: PlanRow,
        step: PlanStepRow,
        tool: ToolInfo,
        body: dict[str, Any] | None,
    ) -> None:
        coverage = self._verify_predicate_contract(
            session=session,
            step=step,
            tool=tool,
            body=body,
        )
        if coverage and coverage.get("unknown_count", 0) > 0 and tool.method == "GET":
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
                coverage = self._verify_predicate_contract(
                    session=session,
                    step=step,
                    tool=tool,
                    body=body,
                )
        if coverage and isinstance(body, dict):
            body["_predicate_coverage"] = coverage
        body = result_summary.attach_result_analysis(body=body, intent=session.current_intent) or body
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
        )
        await self._append_tool_result_message(
            db,
            session_id=session.session_id,
            step=step,
            intent=session.current_intent,
        )
        session.step_count += 1

    async def execute_until_blocked(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        tools_by_name: dict[str, ToolInfo],
    ) -> ExecuteResult:
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

            recovery_session_id = session.session_id
            recovery_step_index = int(session.current_step_index or 0)

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
                    await self._memory_manager.maybe_compact(db, session_id=session.session_id, step_count=session.step_count)
                    await self._memory_manager.save_checkpoint(db, session_id=session.session_id, thread_id=session.session_id, state=self._checkpoint_state(session))
                    if session.pending_user_message:
                        return await self._trigger_replan(db, session=session, plan=plan, steps=steps, failed_step=None, reason="mid_execution_user_message", user_message=session.pending_user_message)
                    continue

            step = steps[session.current_step_index]
            tool = tools_by_name.get(step.tool_name)
            if not tool:
                return await self._fail_hard(db, session=session, step=step, reason=f"Unknown tool: {step.tool_name}", failure_type="unrecoverable_error", payload={"tool_name": step.tool_name})

            if session.pending_user_message:
                return await self._trigger_replan(db, session=session, plan=plan, steps=steps, failed_step=None, reason="mid_execution_user_message", user_message=session.pending_user_message)

            if step.status in ("DONE", "SKIPPED"):
                session.current_step_index += 1
                session.version += 1
                await db.commit()
                continue

            try:
                await self._prepare_bound_step(db=db, session=session, plan=plan, step=step, tool=tool, steps_by_index=steps_by_index, tools_by_name=tools_by_name)
            except Exception as e:
                decision = self._classify_error(err=e, tool=tool, step=step)
                if decision == "AMBIGUOUS":
                    step.status = "AMBIGUOUS"
                    step.last_error = str(e)
                    session.status = "BLOCKED"
                    session.error = str(e)
                    session.version += 1
                    await db.commit()
                    await self._push_dlq(db, session_id=session.session_id, step_id=step.step_id, failure_type="ambiguous_binding", reason=str(e), payload={"tool": tool.name, "bindings": step.bindings or []})
                    return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
                return await self._trigger_replan(db, session=session, plan=plan, steps=steps, failed_step=step, reason=f"binding_resolution_failed: {e}")

            if tool.requires_approval:
                if not step.approval_id:
                    skipped, risk_override = await self._preflight_approval_guard(session=session, plan=plan, step=step, tool=tool, db=db)
                    if skipped: continue
                    await self._create_approval(db, session_id=session.session_id, step=step, tool=tool, risk_summary_override=risk_override or self._bulk_risk_summary(tool=tool, step=step))
                approval = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == step.approval_id))).scalars().first()
                if not approval or approval.status != "APPROVED":
                    if approval and approval.status == "REJECTED":
                        step.status = "SKIPPED"
                        step.last_error = approval.rejection_reason or f"Approval {approval.approval_id} rejected"
                        step.completed_at = datetime.utcnow()
                        self._log_step_status_change(session=session, plan=plan, step=step, tool=tool, status=step.status)
                        session.status = "IDLE"
                        session.error = step.last_error
                        session.version += 1
                        await db.commit()
                        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
                    session.status = "WAITING_APPROVAL"
                    session.version += 1
                    await db.commit()
                    return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

            claimed = await parallel.claim_step(db, step_id=step.step_id)
            if not claimed:
                refreshed = await db.get(PlanStepRow, step.step_id)
                if refreshed and refreshed.status == "DONE":
                    session.current_step_index += 1
                    session.version += 1
                    await db.commit()
                    continue
                return await self._trigger_replan(db, session=session, plan=plan, steps=steps, failed_step=refreshed or step, reason="step_lock_conflict")

            step.status = "IN_PROGRESS"
            step.started_at = step.started_at or datetime.utcnow()
            self._log_step_status_change(session=session, plan=plan, step=step, tool=tool, status=step.status)
            session.status = "EXECUTING"
            session.version += 1
            await db.commit()

            existing_snapshot = (await db.execute(select(SnapshotRow).where(SnapshotRow.idempotency_key == step.idempotency_key).where(SnapshotRow.plan_hash == plan.plan_hash).order_by(SnapshotRow.executed_at.desc()))).scalars().first()
            if existing_snapshot and existing_snapshot.http_status and step.status != "DONE":
                snapshot_body = existing_snapshot.response_body if isinstance(existing_snapshot.response_body, dict) else None
                if self._is_soft_not_found(tool=tool, http_status=existing_snapshot.http_status, body=snapshot_body):
                    step.status = "DONE"
                    replay_body = dict(snapshot_body or {})
                    replay_body["not_found"] = True
                    replay_body["_summary"] = await self._build_not_found_summary(tool_name=tool.name, args=step.args or {}, body=snapshot_body)
                    step.result = replay_body
                else:
                    step.status = "DONE" if existing_snapshot.http_status < 400 else "FAILED"
                    step.result = existing_snapshot.response_body
                if step.status == "DONE":
                    step.result = result_summary.attach_result_analysis(body=step.result if isinstance(step.result, dict) else None, intent=session.current_intent)
                    coverage = self._verify_predicate_contract(session=session, step=step, tool=tool, body=step.result if isinstance(step.result, dict) else None)
                    if coverage and isinstance(step.result, dict): step.result["_predicate_coverage"] = coverage
                    step.result_summary = await self._summarize_step_result(tool_name=tool.name, body=step.result, args=step.args, intent=session.current_intent)
                step.completed_at = datetime.utcnow()
                self._log_step_status_change(session=session, plan=plan, step=step, tool=tool, status=step.status, latency_ms=existing_snapshot.latency_ms, http_status=existing_snapshot.http_status, idempotent_replay=True)
                session.version += 1
                if step.status == "DONE": await self._append_tool_result_message(db, session_id=session.session_id, step=step, intent=session.current_intent)
                await db.commit()
            else:
                while True:
                    try:
                        if (getattr(step, "execution_mode", None) or "single") == "foreach":
                            body = await self._execute_foreach_step(tool=tool, step=step, plan=plan, session=session, db=db)
                        else:
                            body, _ = await self._execute_tool_call(tool=tool, args=step.args, idempotency_key=step.idempotency_key, plan_hash=plan.plan_hash, plan_version=plan.version, session_id=session.session_id, step_id=step.step_id, db=db)
                        await self._complete_step_with_body(db, session=session, plan=plan, step=step, tool=tool, body=body)
                        await db.commit()
                        break
                    except Exception as e:
                        from sqlalchemy import update
                        from sqlalchemy.exc import SQLAlchemyError
                        if isinstance(e, SQLAlchemyError):
                            # Capture for recovery before potential session invalidation
                            recovery_step_id = step.step_id if step else None
                            await db.rollback()

                            if recovery_step_id:
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
                                await db.commit()

                            return ExecuteResult(status="EXECUTING", current_step_index=recovery_step_index)

                        decision = self._classify_error(err=e, tool=tool, step=step)
                        error_type = type(e).__name__
                        metrics.inc("tool_error_total", labels={"tool": tool.name, "error_type": error_type})

                        reason = str(e)
                        if isinstance(e, predicate_guard.PredicateVerificationError):
                            reason = f"predicate_mismatch: {reason}"

                        if decision == "RETRY":
                            step.retry_count += 1
                            session.retry_count += 1
                            session.version += 1
                            await db.commit()
                            await asyncio.sleep(min(self._settings.retry_base_delay_s * (2 ** (step.retry_count - 1)), self._settings.retry_max_delay_s))
                            continue
                        if decision == "AMBIGUOUS":
                            step.status = "AMBIGUOUS"
                            step.last_error = reason
                            self._log_step_status_change(session=session, plan=plan, step=step, tool=tool, status=step.status)
                            session.status = "BLOCKED"
                            session.error = reason
                            session.version += 1
                            await db.commit()
                            dlq_row = await self._push_dlq(db, session_id=session.session_id, step_id=step.step_id, failure_type="ambiguous_execution", reason=reason, payload={"tool": tool.name, "endpoint": tool.endpoint, "args": step.args})
                            await self._event_bus.publish(
                                AgentEvent(
                                    event_type="session_resume",
                                    session_id=session.session_id,
                                    payload={"blocked_by": "AMBIGUOUS", "dlq_id": dlq_row.dlq_id},
                                    published_at=datetime.utcnow(),
                                )
                            )
                            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
                        if decision == "REPLAN":
                            return await self._trigger_replan(db, session=session, plan=plan, steps=steps, failed_step=step, reason=reason)
                        return await self._fail_hard(db, session=session, step=step, reason=reason, failure_type="unrecoverable_error", payload={"tool": tool.name, "endpoint": tool.endpoint, "args": step.args})

            session.current_step_index += 1
            session.step_count += 1
            session.version += 1
            await db.commit()
            await self._memory_manager.maybe_compact(db, session_id=session.session_id, step_count=session.step_count)
            await self._memory_manager.save_checkpoint(db, session_id=session.session_id, thread_id=session.session_id, state=self._checkpoint_state(session))
            if session.pending_user_message:
                return await self._trigger_replan(db, session=session, plan=plan, steps=steps, failed_step=None, reason="mid_execution_user_message", user_message=session.pending_user_message)

        plan.status = "COMPLETED"
        session.status = "COMPLETED"
        session.completed_at = datetime.utcnow()
        session.version += 1
        last_step_result_has_data = False
        if steps:
            last_step = steps[-1]
            last_step_result_has_data = self._result_has_records(body=last_step.result if isinstance(last_step.result, dict) else None)
        if not last_step_result_has_data:
            completion_text = await self._build_completion_text(plan_kind=(getattr(plan, "kind", None) or "execution"), step_count=session.step_count)
            db.add(MessageRow(message_id=generate_uuid(), session_id=session.session_id, role="assistant", content=completion_text, tool_name="__session__"))
        await db.commit()
        try:
            await self._memory_manager.save_checkpoint(db, session_id=session.session_id, thread_id=session.session_id, state=self._checkpoint_state(session))
        except Exception: pass
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
