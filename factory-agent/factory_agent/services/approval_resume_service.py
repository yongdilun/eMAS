from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
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
        if await self._resume_direct_v2_planner_approval(db=db, row=row, sess=sess, intent=intent):
            return
        try:
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
            await db.rollback()
            context = dict(sess.replan_context or {})
            context.pop("langgraph_approval_resume", None)
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
            sess.status = "BLOCKED"
            sess.error = str(e)
            _bump_session_revision(sess)
            await db.commit()
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row_approval_id, "status": "BLOCKED", "subject_type": "graph"},
            )
        except PlannerPlanRejected as e:
            await db.rollback()
            context = dict(sess.replan_context or {})
            context.pop("langgraph_approval_resume", None)
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
            sess.status = "BLOCKED"
            sess.error = str(e)
            _bump_session_revision(sess)
            await db.commit()
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row_approval_id, "status": "BLOCKED", "subject_type": "graph"},
            )
        except PlannerBackendError as e:
            await db.rollback()
            context = dict(sess.replan_context or {})
            context.pop("langgraph_approval_resume", None)
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
            sess.status = "FAILED"
            sess.error = str(e)
            _bump_session_revision(sess)
            await db.commit()
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row_approval_id, "status": "FAILED", "subject_type": "graph"},
            )
        except Exception as e:
            log_event(
                "graph_approval_resume_failed",
                level="ERROR",
                session_id=row_session_id,
                approval_id=row_approval_id,
                error=str(e),
            )
            await db.rollback()
            context = dict(sess.replan_context or {})
            context.pop("langgraph_approval_resume", None)
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
            sess.status = "FAILED"
            sess.error = str(e)
            _bump_session_revision(sess)
            await db.commit()
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row_approval_id, "status": "FAILED", "subject_type": "graph"},
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

    def _next_direct_v2_approval_payload(
        self,
        *,
        payload: dict[str, Any],
        previous_approval_id: str,
        completed_plan_steps: list[dict[str, Any]],
        completed_tool_outputs: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        bundle_ui = payload.get("bundle_ui") if isinstance(payload.get("bundle_ui"), dict) else {}
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
