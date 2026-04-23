from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Approval as ApprovalRow
from models import DeadLetter as DeadLetterRow
from models import ExecutionSnapshot as SnapshotRow
from models import Plan as PlanRow
from models import PlanStep as PlanStepRow
from models import Session as SessionRow
from models import generate_uuid

from .config import Settings
from .events import AgentEvent, EventBus
from .memory_manager import MemoryManager
from .metrics import metrics
from .schemas import ToolInfo
from .telemetry import log_event, log_step_status_changed

FailureDecision = Literal["RETRY", "REPLAN", "FAIL_HARD", "AMBIGUOUS"]


class AmbiguousExecutionError(Exception):
    pass


class ToolHTTPError(Exception):
    def __init__(self, status_code: int, body: dict[str, Any] | None):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}")


class ToolNetworkError(Exception):
    def __init__(self, message: str, *, request_was_sent: bool):
        self.request_was_sent = request_was_sent
        super().__init__(message)


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_idempotency_key(*, session_id: str, step_index: int, plan_version: int, args: dict[str, Any]) -> str:
    payload = f"{session_id}:{step_index}:{plan_version}:{_stable_json(args)}"
    return _sha256_hex(payload)


def compute_payload_hash(*, args: dict[str, Any]) -> str:
    return _sha256_hex(_stable_json(args))


@dataclass(frozen=True)
class ExecuteResult:
    status: str
    current_step_index: int


class ExecutionEngine:
    def __init__(self, settings: Settings, event_bus: EventBus):
        self._settings = settings
        self._event_bus = event_bus
        self._memory_manager = MemoryManager(settings)

    def _session_duration_s(self, session: SessionRow) -> int:
        if not session.session_started_at:
            return 0
        return int((datetime.utcnow() - session.session_started_at).total_seconds())

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

    async def _push_dlq(
        self,
        db: AsyncSession,
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

    async def _create_approval(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        step: PlanStepRow,
        tool: ToolInfo,
    ) -> ApprovalRow:
        approval = ApprovalRow(
            approval_id=generate_uuid(),
            session_id=session_id,
            step_id=step.step_id,
            tool_name=tool.name,
            args=step.args,
            risk_summary="This operation performs a write via backend API.",
            side_effect_level=tool.side_effect_level or "HIGH",
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        db.add(approval)
        step.approval_id = approval.approval_id
        step.requires_approval = True
        session = await db.get(SessionRow, session_id)
        if session:
            session.version += 1
        await db.commit()
        await db.refresh(approval)
        log_event(
            "approval_created",
            session_id=session_id,
            step_id=step.step_id,
            tool=tool.name,
            side_effect_level=tool.side_effect_level,
        )
        return approval

    async def _record_snapshot(
        self,
        db: AsyncSession,
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

    async def _execute_tool_call(
        self,
        *,
        tool: ToolInfo,
        args: dict[str, Any],
        idempotency_key: str,
        plan_hash: str,
        plan_version: int,
        session_id: str,
        step_id: str,
        db: AsyncSession,
    ) -> tuple[dict[str, Any] | None, int]:
        url = f"{self._settings.go_api_base_url}{tool.endpoint}"
        headers = {
            "Idempotency-Key": idempotency_key,
            "X-Idempotency-Key": idempotency_key,
            "X-Plan-Hash": plan_hash,
            "X-Plan-Version": str(plan_version),
            "X-Payload-Hash": compute_payload_hash(args=args),
        }

        start = time.time()
        body: dict[str, Any] | None = None
        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_s) as client:
                if tool.method == "GET":
                    resp = await client.get(url, params=args, headers=headers)
                elif tool.method == "POST":
                    resp = await client.post(url, json=args, headers=headers)
                elif tool.method == "PUT":
                    resp = await client.put(url, json=args, headers=headers)
                elif tool.method == "PATCH":
                    resp = await client.patch(url, json=args, headers=headers)
                elif tool.method == "DELETE":
                    resp = await client.request("DELETE", url, json=args, headers=headers)
                else:
                    raise ValueError(f"Unsupported method: {tool.method}")
        except httpx.TimeoutException as e:
            await self._record_snapshot(
                db,
                step_id=step_id,
                session_id=session_id,
                tool=tool,
                args=args,
                plan_hash=plan_hash,
                plan_version=plan_version,
                idempotency_key=idempotency_key,
                http_status=None,
                response_body={"error_type": "timeout", "message": str(e)},
                latency_ms=int((time.time() - start) * 1000),
            )
            raise ToolNetworkError(str(e), request_was_sent=True) from e
        except httpx.NetworkError as e:
            await self._record_snapshot(
                db,
                step_id=step_id,
                session_id=session_id,
                tool=tool,
                args=args,
                plan_hash=plan_hash,
                plan_version=plan_version,
                idempotency_key=idempotency_key,
                http_status=None,
                response_body={"error_type": "network", "message": str(e)},
                latency_ms=int((time.time() - start) * 1000),
            )
            raise ToolNetworkError(str(e), request_was_sent=False) from e

        latency_ms = int((time.time() - start) * 1000)
        try:
            if resp.content:
                body = resp.json()
        except Exception:
            body = {"raw": resp.text}

        await self._record_snapshot(
            db,
            step_id=step_id,
            session_id=session_id,
            tool=tool,
            args=args,
            plan_hash=plan_hash,
            plan_version=plan_version,
            idempotency_key=idempotency_key,
            http_status=resp.status_code,
            response_body=body,
            latency_ms=latency_ms,
        )
        metrics.observe("step_execution_latency_ms", latency_ms, labels={"tool": tool.name})
        log_event(
            "step_http_result",
            session_id=session_id,
            step_id=step_id,
            tool=tool.name,
            method=tool.method,
            endpoint=tool.endpoint,
            status=resp.status_code,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
        )

        if resp.status_code >= 400:
            raise ToolHTTPError(resp.status_code, body)
        return body, latency_ms

    def _classify_error(self, *, err: Exception, tool: ToolInfo, step: PlanStepRow) -> FailureDecision:
        if isinstance(err, ToolNetworkError):
            if tool.is_strongly_idempotent and step.retry_count < step.max_retries:
                return "RETRY"
            if err.request_was_sent:
                return "AMBIGUOUS"
            return "REPLAN"

        if isinstance(err, ToolHTTPError):
            status_code = err.status_code
            if status_code in (400, 404, 409):
                return "REPLAN"
            if status_code in (401, 403):
                return "FAIL_HARD"
            if status_code >= 500:
                if tool.is_strongly_idempotent and step.retry_count < step.max_retries:
                    return "RETRY"
                return "REPLAN"
            return "FAIL_HARD"

        return "FAIL_HARD"

    async def _claim_step(self, db: AsyncSession, *, step_id: str) -> bool:
        stmt = (
            update(PlanStepRow)
            .where(PlanStepRow.step_id == step_id)
            .where(PlanStepRow.status.in_(["NOT_STARTED", "FAILED"]))
            .values(status="IN_PROGRESS", started_at=datetime.utcnow())
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount == 1

    def _build_replan_context(
        self,
        *,
        session: SessionRow,
        steps: list[PlanStepRow],
        failed_step: PlanStepRow | None,
        reason: str,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        completed = []
        for s in steps:
            if s.status == "DONE":
                completed.append(
                    {
                        "step_index": s.step_index,
                        "tool_name": s.tool_name,
                        "args": s.args,
                        "result": s.result,
                    }
                )
        context: dict[str, Any] = {
            "original_intent": session.current_intent,
            "plan_id": session.plan_id,
            "plan_version": session.plan_version,
            "completed_steps": completed,
            "error": reason,
            "failed_step": None,
        }
        if failed_step is not None:
            context["failed_step"] = {
                "step_id": failed_step.step_id,
                "step_index": failed_step.step_index,
                "tool_name": failed_step.tool_name,
                "args": failed_step.args,
                "last_error": failed_step.last_error,
            }
        if user_message:
            context["user_message"] = user_message
        return context

    async def _trigger_replan(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        plan: PlanRow,
        steps: list[PlanStepRow],
        failed_step: PlanStepRow | None,
        reason: str,
        user_message: str | None = None,
    ) -> ExecuteResult:
        if failed_step is not None:
            failed_step.status = "FAILED"
            failed_step.last_error = reason
            failed_step.completed_at = datetime.utcnow()
            self._log_step_status_change(
                session=session,
                plan=plan,
                step=failed_step,
                tool=None,
                status=failed_step.status,
            )

        if not plan.invalidated_at:
            plan.invalidated_at = datetime.utcnow()
            plan.invalidated_reason = reason

        session.replan_count += 1
        metrics.inc("replan_total")
        metrics.inc("replan_rate")
        session.plan_version = (session.plan_version or 0) + 1
        session.replan_context = self._build_replan_context(
            session=session,
            steps=steps,
            failed_step=failed_step,
            reason=reason,
            user_message=user_message,
        )
        session.pending_user_message = None

        if session.replan_count >= self._settings.max_replans:
            session.status = "BLOCKED"
            session.error = f"Session exceeded MAX_REPLANS ({reason})"
            session.version += 1
            await db.commit()
            await self._push_dlq(
                db,
                session_id=session.session_id,
                step_id=failed_step.step_id if failed_step else None,
                failure_type="replan_limit_reached",
                reason=reason,
                payload=session.replan_context or {},
            )
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

        session.status = "PLANNING"
        session.error = reason
        session.version += 1
        await db.commit()
        log_event(
            "session_replan_triggered",
            level="WARNING",
            session_id=session.session_id,
            plan_id=plan.plan_id,
            reason=reason,
            replan_count=session.replan_count,
            failed_step_id=failed_step.step_id if failed_step else None,
        )
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

    async def _fail_hard(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        step: PlanStepRow,
        reason: str,
        failure_type: str,
        payload: dict[str, Any],
    ) -> ExecuteResult:
        step.status = "FAILED"
        step.last_error = reason
        step.completed_at = datetime.utcnow()
        self._log_step_status_change(session=session, plan=None, step=step, tool=None, status=step.status)
        session.status = "FAILED"
        session.error = reason
        session.version += 1
        await db.commit()
        metrics.inc("session_failed_total", labels={"reason": failure_type})
        metrics.observe("steps_per_session", float(session.step_count))
        log_event(
            "session_failed",
            level="ERROR",
            session_id=session.session_id,
            step_id=step.step_id,
            tool=step.tool_name,
            failure_type=failure_type,
            reason=reason,
        )
        await self._push_dlq(
            db,
            session_id=session.session_id,
            step_id=step.step_id,
            failure_type=failure_type,
            reason=reason,
            payload=payload,
        )
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

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
        metrics.inc("limit_type_distribution", labels={"limit_type": limit_reason})
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
        metrics.inc("session_failed_total", labels={"reason": "rate_limit"})
        metrics.observe("steps_per_session", float(session.step_count))
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
            metrics.inc("session_failed_total", labels={"reason": "plan_not_found"})
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

        steps = (
            await db.execute(
                select(PlanStepRow)
                .where(PlanStepRow.plan_id == plan.plan_id)
                .order_by(PlanStepRow.step_index.asc())
            )
        ).scalars().all()

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

            if tool.requires_approval:
                if not step.approval_id:
                    await self._create_approval(db, session_id=session.session_id, step=step, tool=tool)
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
                step.status = "DONE" if existing_snapshot.http_status < 400 else "FAILED"
                step.result = existing_snapshot.response_body
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
                await db.commit()
            else:
                recovery_step_id = step.step_id
                recovery_session_id = session.session_id
                recovery_step_index = int(session.current_step_index or 0)
                while True:
                    try:
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
                        step.status = "DONE"
                        step.result = body
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
                            reason = (
                                f"HTTP {status_code}" if status_code is not None else str(e)
                            )
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

        session.status = "COMPLETED"
        session.completed_at = datetime.utcnow()
        session.version += 1
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
