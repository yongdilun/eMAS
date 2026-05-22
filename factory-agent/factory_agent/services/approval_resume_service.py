from __future__ import annotations

import asyncio
import contextlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from factory_agent.config import Settings
from factory_agent.observability.events import AgentEvent, EventBus
from factory_agent.observability.telemetry import log_event
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.planner import PlannerApprovalRequired, PlannerBackendError, PlannerClarificationError, PlannerPlanRejected
from factory_agent.planning.v2_interrupts import execution_result_is_stale_after_interrupt
from factory_agent.graph.http_tool_client import execute_tool_http
from factory_agent.schemas import PlanDraft, PlanStepDraft
from factory_agent.services.plan_creation_service import PlanCreationService


def _bump_session_revision(sess: Any) -> None:
    sess.version = (getattr(sess, "version", None) or 0) + 1
    sess.event_seq = (getattr(sess, "event_seq", None) or 0) + 1


def stage_direct_v2_approval_compatibility_rows(
    *,
    tool_outputs: list[dict[str, Any]],
    constraints: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for output in tool_outputs:
        body = output.get("result") if isinstance(output.get("result"), dict) else {}
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, list):
            rows.extend(row for row in data if isinstance(row, dict))
    safety = " ".join(str(item) for item in constraints.get("safety_constraints", []) or []).lower()
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    priority = direct_v2_approval_compatibility_source_priority_constraint(constraints)
    date_constraint = str(constraints.get("date") or "").strip().lower()
    date_scope_rows = [
        row
        for row in rows
        if not priority or str(row.get("priority") or "").strip().lower() == priority
    ]
    production_week_window = _direct_v2_approval_compatibility_production_week_window(
        date_scope_rows,
        date_constraint,
    )
    for row in rows:
        if priority and str(row.get("priority") or "").strip().lower() != priority:
            excluded.append({**row, "exclusion_reason": "priority_constraint"})
            continue
        if date_constraint and not _direct_v2_approval_compatibility_row_matches_date_constraint(
            row,
            date_constraint,
            production_week_window=production_week_window,
        ):
            excluded.append({**row, "exclusion_reason": "date_constraint"})
            continue
        kept.append(row)
    rows = kept
    if "blocked" in safety:
        kept = []
        for row in rows:
            if str(row.get("status") or "").lower() == "blocked":
                excluded.append({**row, "exclusion_reason": "blocked_safety_constraint"})
            else:
                kept.append(row)
        rows = kept
    return rows, excluded


def direct_v2_approval_compatibility_source_priority_constraint(constraints: dict[str, Any]) -> str:
    raw = constraints.get("priority")
    if isinstance(raw, (list, tuple, set)):
        values = [str(item).strip().lower() for item in raw if str(item).strip()]
    else:
        values = [str(raw).strip().lower()] if raw not in (None, "") else []
    target = str(
        constraints.get("new_priority")
        or constraints.get("priority_to")
        or constraints.get("target_priority")
        or ""
    ).strip().lower()
    candidates = [value for value in values if value and value != target]
    return candidates[0] if candidates else (values[0] if values else "")


def _direct_v2_approval_compatibility_row_matches_date_constraint(
    row: dict[str, Any],
    date_constraint: str,
    *,
    production_week_window: tuple[date, date] | None = None,
) -> bool:
    if date_constraint != "this week":
        return True
    due_date = _direct_v2_approval_compatibility_row_due_date(row)
    if due_date is None:
        return False
    if production_week_window is None:
        production_week_window = _direct_v2_approval_compatibility_current_week_window()
    week_start, week_end = production_week_window
    return week_start <= due_date < week_end


def _direct_v2_approval_compatibility_production_week_window(
    rows: list[dict[str, Any]],
    date_constraint: str,
) -> tuple[date, date] | None:
    if date_constraint != "this week":
        return None
    current_window = _direct_v2_approval_compatibility_current_week_window()
    due_dates = [
        due_date
        for row in rows
        if (due_date := _direct_v2_approval_compatibility_row_due_date(row)) is not None
    ]
    if not due_dates:
        return current_window
    current_start, current_end = current_window
    if any(current_start <= due_date < current_end for due_date in due_dates):
        return current_window
    today = datetime.now(timezone.utc).date()
    future_due_dates = sorted(due_date for due_date in due_dates if due_date >= today)
    if not future_due_dates:
        return current_window
    production_start = future_due_dates[0]
    return production_start, production_start + timedelta(days=7)


def _direct_v2_approval_compatibility_current_week_window() -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())
    return week_start, week_start + timedelta(days=7)


def _direct_v2_approval_compatibility_row_due_date(row: dict[str, Any]) -> date | None:
    raw = row.get("deadline") or row.get("due_date") or row.get("due")
    return _direct_v2_approval_compatibility_parse_date(raw)


def _direct_v2_approval_compatibility_parse_date(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except Exception:
        return None


class ApprovalResumeService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_mgr: SessionManager,
        planner: Any,
        plan_service: PlanCreationService,
        event_bus: EventBus,
        planner_adapter_is_none: bool,
    ) -> None:
        self._settings = settings
        self._session_mgr = session_mgr
        self._planner = planner
        self._plan_service = plan_service
        self._event_bus = event_bus
        self._planner_adapter_is_none = planner_adapter_is_none
        self._active_approval_resume_tasks: set[str] = set()

    async def publish_agent_event(self, event_type: str, session_id: str, payload: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            await self._event_bus.publish(
                AgentEvent(
                    event_type=event_type,  # type: ignore[arg-type]
                    session_id=session_id,
                    payload=payload,
                    published_at=datetime.utcnow(),
                )
            )

    async def _mark_graph_approval_resume_stopped(
        self,
        *,
        db: AsyncSession,
        session_id: str,
        approval_id: str,
        status: str,
        error: str,
    ) -> None:
        await db.rollback()
        sess = await self._session_mgr.get_session(db, session_id=session_id)
        if not sess:
            return
        context = dict(sess.replan_context or {})
        context.pop("langgraph_approval_resume", None)
        context.pop("langgraph_pending_approval", None)
        sess.replan_context = context
        sess.status = status
        sess.error = error
        _bump_session_revision(sess)
        await db.commit()
        await self.publish_agent_event(
            "session_resume",
            sess.session_id,
            {"approval_id": approval_id, "status": status, "subject_type": "graph"},
        )

    async def resume_approved_graph_approval(self,
        *,
        db: AsyncSession,
        approval_id: str,
    ) -> None:
        row = (await db.execute(select(ApprovalRow).where(ApprovalRow.approval_id == approval_id))).scalars().first()
        if not row:
            return
        row_approval_id = row.approval_id
        row_session_id = row.session_id
        if (getattr(row, "subject_type", "step") or "step") != "graph":
            return
        if row.status != "APPROVED":
            return
        sess = await self._session_mgr.get_session(db, session_id=row.session_id)
        if not sess:
            return
        if sess.status == "COMPLETED":
            context_done = sess.replan_context if isinstance(sess.replan_context, dict) else {}
            if not context_done.get("langgraph_approval_resume"):
                return

        intent = str(sess.current_intent or "")
        try:
            if await self._resume_planner_owned_agent_graph_approval(db=db, row=row, sess=sess, intent=intent):
                return
            if await self._resume_direct_v2_planner_approval(db=db, row=row, sess=sess, intent=intent):
                return
            tools_by_name = await self._plan_service._ensure_registry_health(db=db)
            seed_resume_context = getattr(self._planner, "seed_resume_context", None)
            if callable(seed_resume_context):
                approval_payload = dict(row.args) if isinstance(row.args, dict) else {}
                approval_payload["_approval_id"] = row_approval_id
                seed_resume_context(
                    session_id=sess.session_id,
                    intent=intent,
                    approval_payload=approval_payload,
                )
            resumed = await self._planner.resume_after_approval(session_id=sess.session_id, approved=True)
            await db.refresh(sess)
            if execution_result_is_stale_after_interrupt(
                session_status=sess.status,
                current_intent=sess.current_intent,
                started_intent=intent,
                replan_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
            ):
                log_event(
                    "graph_approval_resume_result_ignored_after_interrupt",
                    session_id=sess.session_id,
                    approval_id=row_approval_id,
                )
                return
            draft = resumed.draft
            backend_used = resumed.backend_used
            context = dict(sess.replan_context or {})
            if resumed.intent_contract:
                context["intent_contract"] = resumed.intent_contract
            context.pop("langgraph_pending_approval", None)
            context.pop("langgraph_approval_resume", None)
            sess.replan_context = context
            sess.error = None
            await self._plan_service._persist_plan(
                db=db,
                sess=sess,
                draft=draft,
                tools_by_name=tools_by_name,
                backend_used=backend_used,
                kind="execution",
                status="COMPLETED",
                intent=intent,
                context_to_keep=context,
                tool_outputs=getattr(resumed, "tool_outputs", None),
            )
            await db.commit()
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row_approval_id, "status": "COMPLETED", "subject_type": "graph"},
            )
        except PlannerApprovalRequired as e:
            log_event(
                "graph_approval_resume_requires_followup_approval",
                session_id=row_session_id,
                approval_id=row_approval_id,
            )
            await db.rollback()
            sess = await self._session_mgr.get_session(db, session_id=row_session_id)
            if not sess:
                return
            tools_by_name = await self._plan_service._ensure_registry_health(db=db)
            latest_user = await self._plan_service._latest_user_message(db=db, session_id=sess.session_id)
            await self._plan_service._persist_graph_interrupt_approval(
                db=db,
                sess=sess,
                approval_payload=e.approval if isinstance(e.approval, dict) else {"kind": "approval_required"},
                mode=latest_user.mode if latest_user else "normal",
                tools_by_name=tools_by_name,
                intent=intent,
            )
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row_approval_id, "status": "WAITING_APPROVAL", "subject_type": "graph"},
            )
        except PlannerClarificationError as e:
            await self._mark_graph_approval_resume_stopped(
                db=db,
                session_id=row_session_id,
                approval_id=row_approval_id,
                status="BLOCKED",
                error=str(e),
            )
        except PlannerPlanRejected as e:
            await self._mark_graph_approval_resume_stopped(
                db=db,
                session_id=row_session_id,
                approval_id=row_approval_id,
                status="BLOCKED",
                error=str(e),
            )
        except PlannerBackendError as e:
            await self._mark_graph_approval_resume_stopped(
                db=db,
                session_id=row_session_id,
                approval_id=row_approval_id,
                status="FAILED",
                error=str(e),
            )
        except Exception as e:
            log_event(
                "graph_approval_resume_failed",
                level="ERROR",
                session_id=row_session_id,
                approval_id=row_approval_id,
                error=str(e),
            )
            await self._mark_graph_approval_resume_stopped(
                db=db,
                session_id=row_session_id,
                approval_id=row_approval_id,
                status="FAILED",
                error=str(e),
            )

    def start_graph_approval_resume_task(self, db: AsyncSession, approval_id: str) -> None:
        if approval_id in self._active_approval_resume_tasks:
            return
        bind = getattr(db, "bind", None) or db.get_bind()
        bg_sessionmaker = sessionmaker(bind=bind, class_=AsyncSession, expire_on_commit=False)
        self._active_approval_resume_tasks.add(approval_id)

        async def _runner() -> None:
            try:
                async with bg_sessionmaker() as bg_db:
                    await self.resume_approved_graph_approval(db=bg_db, approval_id=approval_id)
            finally:
                self._active_approval_resume_tasks.discard(approval_id)

        task = asyncio.create_task(_runner())

        def _consume_task_result(done: asyncio.Task) -> None:
            try:
                done.result()
            except Exception as exc:
                log_event(
                    "graph_approval_resume_task_failed",
                    level="ERROR",
                    approval_id=approval_id,
                    error=str(exc),
                )

        task.add_done_callback(_consume_task_result)

    def should_resume_graph_approval_inline(self, ) -> bool:
        return self._planner_adapter_is_none and self._settings.database_url.startswith("sqlite+aiosqlite:///:memory:")

    async def _resume_planner_owned_agent_graph_approval(
        self,
        *,
        db: AsyncSession,
        row: ApprovalRow,
        sess: Any,
        intent: str,
    ) -> bool:
        payload = row.args if isinstance(row.args, dict) else {}
        if payload.get("kind") != "graph_write_approval_required":
            return False

        tools_by_name = await self._plan_service._ensure_registry_health(db=db)
        result = await self._plan_service.resume_planner_owned_graph_approval(
            db=db,
            sess=sess,
            tools_by_name=tools_by_name,
            intent=intent,
            approval_id=row.approval_id,
            approved=row.status == "APPROVED",
            ledger_revision=payload.get("ledger_revision") or payload.get("requirement_ledger_revision"),
            checkpoint_id=payload.get("checkpoint_id"),
            decided_by=row.decided_by or "user",
        )
        await db.refresh(sess)
        if execution_result_is_stale_after_interrupt(
            session_status=sess.status,
            current_intent=sess.current_intent,
            started_intent=intent,
            replan_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        ):
            log_event(
                "planner_owned_graph_approval_resume_result_ignored_after_interrupt",
                session_id=sess.session_id,
                approval_id=row.approval_id,
            )
            return True

        await self._plan_service.persist_planner_owned_graph_result(
            db=db,
            sess=sess,
            tools_by_name=tools_by_name,
            intent=intent,
            mode="normal",
            result=result,
        )
        await self.publish_agent_event(
            "session_resume",
            sess.session_id,
            {
                "approval_id": row.approval_id,
                "status": "WAITING_APPROVAL" if result.state.pending_approval.status == "pending" else "COMPLETED",
                "subject_type": "graph",
                "runtime": "planner_owned_agent_graph",
            },
        )
        return True

    async def _resume_direct_v2_planner_approval(
        self,
        *,
        db: AsyncSession,
        row: ApprovalRow,
        sess: Any,
        intent: str,
    ) -> bool:
        payload = row.args if isinstance(row.args, dict) else {}
        bundle_ui = payload.get("bundle_ui") if isinstance(payload.get("bundle_ui"), dict) else {}
        if bundle_ui.get("kind") != "v2_planner_owned_approval_preview":
            return False

        tools_by_name = await self._plan_service._ensure_registry_health(db=db)
        preview = payload.get("preview") if isinstance(payload.get("preview"), list) else []
        rows = bundle_ui.get("rows") if isinstance(bundle_ui.get("rows"), list) else []
        if not rows and isinstance(payload.get("rows"), list):
            rows = payload.get("rows") or []
        preview = payload.get("preview") if isinstance(payload.get("preview"), list) else []
        if not preview and isinstance(bundle_ui.get("preview"), list):
            preview = bundle_ui.get("preview") or []
        if not preview and isinstance(payload.get("staged_writes"), list):
            preview = payload.get("staged_writes") or []
        if not rows:
            rows = self._direct_v2_rows_from_preview(preview=preview, bundle_ui=bundle_ui, payload=payload)
        if rows and not preview:
            write_tool_name = _direct_v2_write_tool_name(bundle_ui=bundle_ui, payload=payload) or "planner_owned_mutation"
            preview = [
                {
                    "tool_name": write_tool_name,
                    "args": {
                        "id": item.get("job_id") or item.get("id"),
                        "priority": item.get("new_priority") or item.get("priority_to") or item.get("priority"),
                    },
                }
                for item in rows
                if isinstance(item, dict) and (item.get("job_id") or item.get("id"))
            ]
        rows_by_id = {str(item.get("job_id") or item.get("id")): item for item in rows if isinstance(item, dict)}
        carried_steps = payload.get("completed_plan_steps") if isinstance(payload.get("completed_plan_steps"), list) else []
        carried_outputs = payload.get("completed_tool_outputs") if isinstance(payload.get("completed_tool_outputs"), list) else []
        draft_steps: list[PlanStepDraft] = [
            PlanStepDraft(
                step_index=index,
                tool_name=str(item.get("tool_name") or ""),
                args=dict(item.get("args") if isinstance(item.get("args"), dict) else {}),
            )
            for index, item in enumerate(carried_steps)
            if isinstance(item, dict) and item.get("tool_name")
        ]
        current_tool_outputs: list[dict[str, Any]] = []
        failed = False
        current_group_summary = self._direct_v2_commit_plan_summary(rows, row.approval_id)
        for offset, item in enumerate(preview):
            if not isinstance(item, dict):
                continue
            index = len(draft_steps)
            tool_name = str(item.get("tool_name") or bundle_ui.get("write_tool_name") or "").strip()
            args = item.get("args") if isinstance(item.get("args"), dict) else {
                "id": item.get("job_id") or item.get("id"),
                "priority": item.get("new_priority") or item.get("priority_to") or item.get("priority"),
            }
            args = {key: value for key, value in dict(args).items() if value not in (None, "")}
            draft_steps.append(PlanStepDraft(step_index=index, tool_name=tool_name, args=dict(args)))
            tool = tools_by_name.get(tool_name)
            row_id = str(args.get("id") or args.get("job_id") or "")
            source_row = dict(rows_by_id.get(row_id, {}))
            if tool is None:
                failed = True
                current_tool_outputs.append(
                    {
                        "tool_name": tool_name,
                        "args": dict(args),
                        "result": {
                            "data": {
                                **source_row,
                                **dict(args),
                                "status": "failed",
                                "reason": f"Tool {tool_name or '<missing>'} was not available",
                            },
                            "approval_id": row.approval_id,
                        },
                        "status": "FAILED",
                        "summary": f"Could not apply {row_id or 'record'} because the write tool was unavailable.",
                    }
                )
                continue
            env = await execute_tool_http(
                self._settings,
                tool,
                dict(args),
                idempotency_key=f"v2-approval:{sess.session_id}:{row.approval_id}:{offset}:{tool_name}",
            )
            ok = bool(env.get("ok"))
            failed = failed or not ok
            body = env.get("body") if isinstance(env.get("body"), dict) else {"value": env.get("body")}
            body_data = body.get("data") if isinstance(body.get("data"), dict) else body
            result_row = {
                **source_row,
                **(body_data if isinstance(body_data, dict) else {}),
                **dict(args),
                "job_id": source_row.get("job_id") or args.get("id") or args.get("job_id"),
                "previous_priority": source_row.get("previous_priority") or source_row.get("original_priority") or source_row.get("priority"),
                "original_priority": source_row.get("original_priority") or source_row.get("priority"),
                "new_priority": source_row.get("new_priority") or args.get("priority"),
                "source_state_basis": source_row.get("source_state_basis") or "original",
                "approval_id": row.approval_id,
                "status": "succeeded" if ok else "failed",
            }
            if not ok:
                result_row["reason"] = body.get("detail") or body.get("message") or body.get("error") or f"HTTP {env.get('http_status')}"
            summary = self._direct_v2_commit_summary(result_row, ok=ok)
            current_tool_outputs.append(
                {
                    "tool_name": tool_name,
                    "args": dict(args),
                    "result": {"data": result_row, "approval_id": row.approval_id, "summary": summary},
                    "http_status": env.get("http_status"),
                    "latency_ms": env.get("latency_ms"),
                    "approval_id": row.approval_id,
                    "status": "DONE" if ok else "FAILED",
                    "summary": summary,
                }
            )

        if current_tool_outputs and not failed:
            result_rows = [
                output.get("result", {}).get("data")
                for output in current_tool_outputs
                if isinstance(output.get("result"), dict) and isinstance(output.get("result", {}).get("data"), dict)
            ]
            current_group_summary = self._direct_v2_commit_plan_summary(
                [dict(item) for item in result_rows if isinstance(item, dict)] or rows,
                row.approval_id,
            )
            current_tool_outputs[0]["summary"] = current_group_summary
            result = current_tool_outputs[0].get("result")
            if isinstance(result, dict):
                result["summary"] = current_group_summary
        tool_outputs = [item for item in carried_outputs if isinstance(item, dict)] + current_tool_outputs
        context = dict(sess.replan_context or {})
        context.pop("langgraph_pending_approval", None)
        context.pop("langgraph_approval_resume", None)
        context["skip_completed_narrative_adapter"] = True
        draft = PlanDraft(
            plan_explanation=current_group_summary,
            risk_summary="Approved planner-owned v2 staged writes were applied through typed tool evidence.",
            steps=draft_steps,
        )
        await self._plan_service._persist_plan(
            db=db,
            sess=sess,
            draft=draft,
            tools_by_name=tools_by_name,
            backend_used="v2_planner_loop",
            kind="execution",
            status="FAILED" if failed else "COMPLETED",
            intent=intent,
            context_to_keep=context,
            tool_outputs=tool_outputs,
        )
        if failed:
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row.approval_id, "status": "FAILED", "subject_type": "graph"},
            )
            return True

        refreshed = await self._session_mgr.get_session(db, session_id=sess.session_id) or sess
        next_payload = self._next_direct_v2_approval_payload(
            payload=payload,
            previous_approval_id=row.approval_id,
            completed_plan_steps=[step.model_dump() for step in draft_steps],
            completed_tool_outputs=tool_outputs,
        )
        if next_payload is not None:
            await self._plan_service._persist_graph_interrupt_approval(
                db=db,
                sess=refreshed,
                approval_payload=next_payload,
                mode="normal",
                tools_by_name=tools_by_name,
                intent=intent,
            )
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row.approval_id, "status": "WAITING_APPROVAL", "subject_type": "graph"},
            )
            return True

        await self.publish_agent_event(
            "session_resume",
            sess.session_id,
            {"approval_id": row.approval_id, "status": "COMPLETED", "subject_type": "graph"},
        )
        return True

    def _direct_v2_rows_from_preview(
        self,
        *,
        preview: list[Any],
        bundle_ui: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        constraints = payload.get("locked_constraints") if isinstance(payload.get("locked_constraints"), dict) else {}
        if not constraints:
            constraints = bundle_ui.get("locked_constraints") if isinstance(bundle_ui.get("locked_constraints"), dict) else {}
        previous_priority = str(bundle_ui.get("previous_priority") or "").strip()
        if not previous_priority:
            previous_priority = self._direct_v2_source_priority_constraint(constraints)
        new_priority = str(
            bundle_ui.get("new_priority")
            or constraints.get("new_priority")
            or constraints.get("priority_to")
            or ""
        ).strip()
        rows: list[dict[str, Any]] = []
        for item in preview:
            if not isinstance(item, dict):
                continue
            args = item.get("args") if isinstance(item.get("args"), dict) else item
            row = dict(args)
            row_id = row.get("job_id") or row.get("id")
            if row_id:
                row["job_id"] = row_id
            if previous_priority:
                row.setdefault("previous_priority", previous_priority)
                row.setdefault("original_priority", previous_priority)
            if new_priority:
                row.setdefault("new_priority", new_priority)
            row.setdefault("source_state_basis", "original")
            rows.append(row)
        return rows

    def _direct_v2_source_priority_constraint(self, constraints: dict[str, Any]) -> str:
        return direct_v2_approval_compatibility_source_priority_constraint(constraints)

    def _next_direct_v2_approval_payload(
        self,
        *,
        payload: dict[str, Any],
        previous_approval_id: str,
        completed_plan_steps: list[dict[str, Any]],
        completed_tool_outputs: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        bundle_ui = payload.get("bundle_ui") if isinstance(payload.get("bundle_ui"), dict) else {}
        remaining_changes = payload.get("remaining_business_changes")
        if isinstance(remaining_changes, list):
            for index, item in enumerate(remaining_changes):
                if not isinstance(item, dict):
                    continue
                rows = item.get("rows")
                if not isinstance(rows, list) or not rows:
                    continue
                return self._next_direct_v2_payload_from_business_change(
                    payload=payload,
                    bundle_ui=bundle_ui,
                    business_change=item,
                    remaining_business_changes=[
                        change
                        for change in remaining_changes[index + 1 :]
                        if isinstance(change, dict) and int(change.get("count") or 0) > 0
                    ],
                    previous_approval_id=previous_approval_id,
                    completed_plan_steps=completed_plan_steps,
                    completed_tool_outputs=completed_tool_outputs,
                )
        requirements = payload.get("mutation_requirements") if isinstance(payload.get("mutation_requirements"), list) else []
        current_requirement_id = str(payload.get("current_requirement_id") or "")
        current_index = next(
            (index for index, requirement in enumerate(requirements) if str(requirement.get("id") or "") == current_requirement_id),
            -1,
        )
        next_requirement = next(
            (
                requirement
                for requirement in requirements[current_index + 1 :]
                if isinstance(requirement, dict) and requirement.get("requirement_type") == "mutation_request"
            ),
            None,
        )
        if not isinstance(next_requirement, dict):
            return None
        constraints = dict(next_requirement.get("constraints") or {})
        source_priority = self._direct_v2_source_priority_constraint(constraints)
        new_priority = constraints.get("new_priority") or constraints.get("priority_to")
        if not source_priority or not new_priority:
            return None
        candidates = []
        for key in ("excluded_rows", "rows"):
            values = bundle_ui.get(key)
            if isinstance(values, list):
                candidates.extend(item for item in values if isinstance(item, dict))
        staged_rows = []
        excluded_rows = []
        seen_ids: set[str] = set()
        for candidate in candidates:
            row_id = str(candidate.get("job_id") or candidate.get("id") or "")
            if not row_id or row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            if str(candidate.get("priority") or candidate.get("previous_priority") or candidate.get("original_priority") or "").strip().lower() != source_priority:
                excluded_rows.append({**candidate, "exclusion_reason": "priority_constraint"})
                continue
            staged_rows.append(
                {
                    **candidate,
                    "original_priority": candidate.get("original_priority") or candidate.get("priority"),
                    "previous_priority": candidate.get("previous_priority") or candidate.get("priority"),
                    "new_priority": new_priority,
                    "source_state_basis": candidate.get("source_state_basis") or "original",
                }
            )
        if not staged_rows:
            return None
        write_tool_name = _direct_v2_write_tool_name(bundle_ui=bundle_ui, payload=payload) or "planner_owned_mutation"
        return {
            "summary": "Approval required before applying the staged v2 changes.",
            "count": len(staged_rows),
            "preview": [
                {"tool_name": write_tool_name, "args": {"id": row.get("job_id") or row.get("id"), "priority": new_priority}}
                for row in staged_rows
            ],
            "bundle_ui": {
                "kind": "v2_planner_owned_approval_preview",
                "write_set": "planner_owned_preview",
                "headline": "Approval required before applying staged changes.",
                "rows": staged_rows,
                "excluded_rows": excluded_rows,
                "previous_priority": source_priority,
                "new_priority": new_priority,
                "locked_constraints": constraints,
                "requirement_ledger_revision": payload.get("requirement_ledger_revision"),
                "source_intent": bundle_ui.get("source_intent") or payload.get("source_intent"),
                "write_tool_name": write_tool_name,
                "previous_approval_id": previous_approval_id,
                "original_state_semantics": True,
            },
            "requirement_ledger_revision": payload.get("requirement_ledger_revision"),
            "current_requirement_id": next_requirement.get("id"),
            "mutation_requirements": requirements,
            "completed_plan_steps": completed_plan_steps,
            "completed_tool_outputs": completed_tool_outputs,
            "locked_constraints": constraints,
            "commit_state": "not_committed",
            "session_id": payload.get("session_id"),
        }

    def _next_direct_v2_payload_from_business_change(
        self,
        *,
        payload: dict[str, Any],
        bundle_ui: dict[str, Any],
        business_change: dict[str, Any],
        remaining_business_changes: list[dict[str, Any]],
        previous_approval_id: str,
        completed_plan_steps: list[dict[str, Any]],
        completed_tool_outputs: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        rows = business_change.get("rows") if isinstance(business_change.get("rows"), list) else []
        staged_rows = [dict(row) for row in rows if isinstance(row, dict)]
        if not staged_rows:
            return None
        constraints = business_change.get("locked_constraints")
        if not isinstance(constraints, dict):
            requirement = business_change.get("requirement") if isinstance(business_change.get("requirement"), dict) else {}
            constraints = requirement.get("constraints") if isinstance(requirement.get("constraints"), dict) else {}
        constraints = dict(constraints or {})
        source_priority = str(
            business_change.get("source_priority") or self._direct_v2_source_priority_constraint(constraints) or ""
        ).strip()
        new_priority = (
            business_change.get("new_priority")
            or constraints.get("new_priority")
            or constraints.get("priority_to")
            or constraints.get("target_priority")
        )
        if not source_priority or not new_priority:
            return None
        write_tool_name = _direct_v2_write_tool_name(bundle_ui=bundle_ui, payload=payload)
        if not write_tool_name:
            preview = business_change.get("preview") if isinstance(business_change.get("preview"), list) else []
            write_tool_name = next(
                (
                    str(item.get("tool_name") or "").strip()
                    for item in preview
                    if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
                ),
                None,
            )
        write_tool_name = write_tool_name or "planner_owned_mutation"
        entity = str(business_change.get("entity_type") or "record")
        business_change_id = str(business_change.get("business_change_id") or "planner_owned_preview")
        business_change_label = str(business_change.get("business_change") or f"{source_priority.title()} -> {str(new_priority).title()}")
        selector_summary = str(business_change.get("selector_summary") or f"priority = {source_priority}")
        summary = str(business_change.get("summary") or "").strip()
        if not summary:
            count = len(staged_rows)
            noun = "job" if count == 1 else "jobs"
            summary = f"Update {count} {source_priority}-priority {noun} to {new_priority} priority."
        preview = [
            {"tool_name": write_tool_name, "args": {"id": row.get("job_id") or row.get("id"), "priority": new_priority}}
            for row in staged_rows
        ]
        return {
            "summary": summary,
            "count": len(staged_rows),
            "preview": preview,
            "remaining_business_changes": remaining_business_changes,
            "actionable_business_change_count": payload.get("actionable_business_change_count"),
            "no_op_mutations": payload.get("no_op_mutations") if isinstance(payload.get("no_op_mutations"), list) else [],
            "bundle_ui": {
                "kind": "v2_planner_owned_approval_preview",
                "write_set": business_change_id,
                "headline": summary.rstrip("."),
                "rows": staged_rows,
                "excluded_rows": business_change.get("excluded_rows") if isinstance(business_change.get("excluded_rows"), list) else [],
                "previous_priority": business_change.get("previous_priority") or source_priority,
                "new_priority": new_priority,
                "source_priority": source_priority,
                "locked_constraints": constraints,
                "requirement_ledger_revision": payload.get("requirement_ledger_revision"),
                "source_intent": bundle_ui.get("source_intent") or payload.get("source_intent"),
                "write_tool_name": write_tool_name,
                "previous_approval_id": previous_approval_id,
                "original_state_semantics": True,
                "business_change_id": business_change_id,
                "business_change": business_change_label,
                "selector_summary": selector_summary,
                "entity_type": entity,
            },
            "requirement_ledger_revision": payload.get("requirement_ledger_revision"),
            "current_requirement_id": business_change.get("current_requirement_id"),
            "mutation_requirements": payload.get("mutation_requirements") if isinstance(payload.get("mutation_requirements"), list) else [],
            "completed_plan_steps": completed_plan_steps,
            "completed_tool_outputs": completed_tool_outputs,
            "locked_constraints": constraints,
            "commit_state": "not_committed",
            "session_id": payload.get("session_id"),
        }

    def _direct_v2_commit_summary(self, row: dict[str, Any], *, ok: bool) -> str:
        row_id = str(row.get("job_id") or row.get("id") or "record")
        previous = str(row.get("previous_priority") or row.get("original_priority") or "").strip()
        target = str(row.get("new_priority") or row.get("priority") or "").strip()
        if ok and previous and target:
            return f"Updated {row_id} from {previous} to {target} priority."
        if ok:
            return f"Updated {row_id}."
        return f"Failed to update {row_id}."

    def _direct_v2_commit_plan_summary(self, rows: list[dict[str, Any]], approval_id: str) -> str:
        count = len(rows)
        sources = {str(row.get("previous_priority") or row.get("original_priority") or row.get("priority") or "").strip() for row in rows}
        targets = {str(row.get("new_priority") or "").strip() for row in rows}
        sources.discard("")
        targets.discard("")
        if len(sources) == 1 and len(targets) == 1:
            source = next(iter(sources))
            target = next(iter(targets))
            return f"Updated {count} {source}-priority {_plural_for_direct_v2(count, 'job')} to {target} priority under approval {approval_id}."
        return f"Applied {count} approved planner-owned v2 staged {_plural_for_direct_v2(count, 'write')} under approval {approval_id}."


def _plural_for_direct_v2(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"


def _direct_v2_write_tool_name(
    *,
    bundle_ui: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> str | None:
    for candidate in (
        bundle_ui.get("write_tool_name"),
        (payload or {}).get("write_tool_name") if isinstance(payload, dict) else None,
    ):
        name = str(candidate or "").strip()
        if name:
            return name
    return None
