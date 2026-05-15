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
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.planner import PlannerBackendError, PlannerClarificationError, PlannerPlanRejected
from factory_agent.services.plan_creation_service import PlanCreationService


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
            resumed = await self._planner.resume_after_approval(session_id=sess.session_id, approved=True)
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
                {"approval_id": row.approval_id, "status": "COMPLETED", "subject_type": "graph"},
            )
        except PlannerClarificationError as e:
            await db.rollback()
            context = dict(sess.replan_context or {})
            context.pop("langgraph_approval_resume", None)
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
            sess.status = "BLOCKED"
            sess.error = str(e)
            sess.version += 1
            await db.commit()
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row.approval_id, "status": "BLOCKED", "subject_type": "graph"},
            )
        except PlannerPlanRejected as e:
            await db.rollback()
            context = dict(sess.replan_context or {})
            context.pop("langgraph_approval_resume", None)
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
            sess.status = "BLOCKED"
            sess.error = str(e)
            sess.version += 1
            await db.commit()
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row.approval_id, "status": "BLOCKED", "subject_type": "graph"},
            )
        except PlannerBackendError as e:
            await db.rollback()
            context = dict(sess.replan_context or {})
            context.pop("langgraph_approval_resume", None)
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
            sess.status = "FAILED"
            sess.error = str(e)
            sess.version += 1
            await db.commit()
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row.approval_id, "status": "FAILED", "subject_type": "graph"},
            )
        except Exception as e:
            await db.rollback()
            context = dict(sess.replan_context or {})
            context.pop("langgraph_approval_resume", None)
            context.pop("langgraph_pending_approval", None)
            sess.replan_context = context
            sess.status = "FAILED"
            sess.error = str(e)
            sess.version += 1
            await db.commit()
            await self.publish_agent_event(
                "session_resume",
                sess.session_id,
                {"approval_id": row.approval_id, "status": "FAILED", "subject_type": "graph"},
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
            with contextlib.suppress(Exception):
                done.result()

        task.add_done_callback(_consume_task_result)

    def should_resume_graph_approval_inline(self, ) -> bool:
        return self._planner_adapter_is_none and self._settings.database_url.startswith("sqlite+aiosqlite:///:memory:")
