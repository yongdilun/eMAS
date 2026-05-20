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
