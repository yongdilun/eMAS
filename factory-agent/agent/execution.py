from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
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
from .schemas import ToolInfo


class AmbiguousExecutionError(Exception):
    pass


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
        await db.commit()
        await db.refresh(approval)
        return approval

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
    ) -> tuple[int, dict[str, Any] | None, int]:
        url = f"{self._settings.go_api_base_url}{tool.endpoint}"
        headers = {
            "Idempotency-Key": idempotency_key,
            "X-Idempotency-Key": idempotency_key,
            "X-Plan-Hash": plan_hash,
            "X-Plan-Version": str(plan_version),
            "X-Payload-Hash": compute_payload_hash(args=args),
        }

        start = time.time()
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

        latency_ms = int((time.time() - start) * 1000)
        body: dict[str, Any] | None = None
        try:
            if resp.content:
                body = resp.json()
        except Exception:
            body = {"raw": resp.text}

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
            http_status=resp.status_code,
            response_body=body,
            latency_ms=latency_ms,
            executed_at=datetime.utcnow(),
        )
        db.add(snapshot)
        await db.commit()

        return resp.status_code, body, latency_ms

    async def execute_until_blocked(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        tools_by_name: dict[str, ToolInfo],
    ) -> ExecuteResult:
        # Require a plan
        if not session.plan_id:
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

        plan: PlanRow | None = (
            await db.execute(select(PlanRow).where(PlanRow.plan_id == session.plan_id))
        ).scalars().first()
        if not plan:
            session.status = "FAILED"
            session.error = "Plan not found"
            await db.commit()
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

        steps = (
            await db.execute(
                select(PlanStepRow)
                .where(PlanStepRow.plan_id == plan.plan_id)
                .order_by(PlanStepRow.step_index.asc())
            )
        ).scalars().all()

        while session.current_step_index < len(steps):
            step = steps[session.current_step_index]
            tool = tools_by_name.get(step.tool_name)
            if not tool:
                step.status = "FAILED"
                step.last_error = f"Unknown tool: {step.tool_name}"
                session.status = "FAILED"
                session.error = step.last_error
                await db.commit()
                return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

            # Skip already completed steps
            if step.status in ("DONE", "SKIPPED"):
                session.current_step_index += 1
                await db.commit()
                continue

            # Approval gate
            if tool.requires_approval:
                if not step.approval_id:
                    await self._create_approval(db, session_id=session.session_id, step=step, tool=tool)
                session.status = "WAITING_APPROVAL"
                await db.commit()
                return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

            # Execute
            session.status = "EXECUTING"
            step.status = "IN_PROGRESS"
            step.started_at = datetime.utcnow()
            await db.commit()

            # Exactly-once: if a snapshot exists, use it
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
                await db.commit()
            else:
                try:
                    status_code, body, _ = await self._execute_tool_call(
                        tool=tool,
                        args=step.args,
                        idempotency_key=step.idempotency_key,
                        plan_hash=plan.plan_hash,
                        plan_version=plan.version,
                        session_id=session.session_id,
                        step_id=step.step_id,
                        db=db,
                    )
                    if status_code >= 400:
                        step.status = "FAILED"
                        step.last_error = f"HTTP {status_code}"
                        session.status = "FAILED"
                        session.error = step.last_error
                        await self._push_dlq(
                            db,
                            session_id=session.session_id,
                            step_id=step.step_id,
                            failure_type="TOOL_HTTP_ERROR",
                            reason=step.last_error,
                            payload={"tool": tool.name, "endpoint": tool.endpoint, "args": step.args, "status": status_code, "body": body},
                        )
                        await db.commit()
                        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

                    step.status = "DONE"
                    step.result = body
                    step.completed_at = datetime.utcnow()
                    await db.commit()
                except httpx.TimeoutException as e:
                    if not tool.is_strongly_idempotent:
                        step.status = "AMBIGUOUS"
                        step.last_error = f"Timeout executing non-strongly-idempotent tool {tool.name}"
                        session.status = "BLOCKED"
                        session.error = step.last_error
                        dlq = await self._push_dlq(
                            db,
                            session_id=session.session_id,
                            step_id=step.step_id,
                            failure_type="AMBIGUOUS",
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
                        await db.commit()
                        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)
                    # Strongly idempotent: treat as retryable failure (Phase 1: stop execution)
                    step.status = "FAILED"
                    step.last_error = f"Timeout executing tool {tool.name}"
                    session.status = "FAILED"
                    session.error = step.last_error
                    await db.commit()
                    return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

            # Advance
            session.current_step_index += 1
            session.step_count += 1
            await db.commit()

        session.status = "COMPLETED"
        session.completed_at = datetime.utcnow()
        await db.commit()
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

