from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from factory_agent.observability.telemetry import log_event
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.orchestration.session_manager import SessionManager, TransitionError
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.planner import PlannerApprovalRequired, PlannerBackendError, PlannerClarificationError, PlannerPlanRejected
from factory_agent.planning.tool_selector import ToolSelector
from factory_agent.security.permissions import filter_tools_for_role, role_from_claims
from factory_agent.services.plan_creation_service import PlanCreationService


class ExecutionService:
    def __init__(
        self,
        *,
        session_mgr: SessionManager,
        memory_manager: MemoryManager,
        planner: Any,
        tool_selector: ToolSelector,
        plan_service: PlanCreationService,
        start_graph_approval_resume_task: Callable[[AsyncSession, str], None],
    ) -> None:
        self._session_mgr = session_mgr
        self._memory_manager = memory_manager
        self._planner = planner
        self._tool_selector = tool_selector
        self._plan_service = plan_service
        self._start_graph_approval_resume_task = start_graph_approval_resume_task

    async def run_langgraph_session(self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        user: dict[str, Any],
    ) -> SessionRow:
        intent = sess.current_intent or ""
        latest_user = await self._plan_service._latest_user_message(db=db, session_id=sess.session_id)
        mode = latest_user.mode if latest_user else "normal"
        if not intent.strip():
            raise HTTPException(status_code=400, detail={"errors": ["Cannot run LangGraph without a current intent."]})

        tools_by_name = await self._plan_service._ensure_registry_health(db=db)
        tools_by_name = filter_tools_for_role(tools_by_name, role=role_from_claims(user))
        if not tools_by_name:
            raise HTTPException(status_code=403, detail={"errors": ["No tools are allowed for this user role."]})
        selection = await self._tool_selector.select_tools(
            intent=intent,
            tools_by_name=tools_by_name,
            mode=mode,
            context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        )
        scoped_tools = [tools_by_name[name] for name in selection.tool_names if name in tools_by_name]
        if mode == "plan":
            scoped_tools = [tool for tool in scoped_tools if tool.is_read_only]
        try:
            planner_context = await self._memory_manager.build_planner_context(
                db,
                session_id=sess.session_id,
                intent=intent,
                base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
            )
            generated = await self._planner.generate_plan(
                intent=intent,
                scoped_tools=scoped_tools,
                context=planner_context,
            )
        except PlannerApprovalRequired as e:
            return await self._plan_service._persist_graph_interrupt_approval(
                db=db,
                sess=sess,
                approval_payload=e.approval if isinstance(e.approval, dict) else {"kind": "approval_required"},
                mode=mode,
                tools_by_name=tools_by_name,
                intent=intent,
            )
        except PlannerClarificationError as e:
            sess.status = "BLOCKED"
            sess.error = str(e)
            sess.version += 1
            await db.commit()
            return sess
        except PlannerPlanRejected as e:
            sess.status = "BLOCKED"
            sess.error = str(e)
            sess.version += 1
            await db.commit()
            raise HTTPException(status_code=400, detail={"errors": [str(e)]}) from e
        except PlannerBackendError as e:
            sess.status = "FAILED"
            sess.error = str(e)
            sess.version += 1
            await db.commit()
            raise HTTPException(status_code=503, detail={"errors": [str(e)]}) from e

        context = dict(sess.replan_context or {})
        intent_contract = getattr(generated, "intent_contract", None)
        if intent_contract:
            context["intent_contract"] = intent_contract
        context.pop("langgraph_pending_approval", None)
        sess.replan_context = context
        sess.llm_call_count += selection.llm_calls + generated.llm_calls
        await self._plan_service._persist_plan(
            db=db,
            sess=sess,
            draft=generated.draft,
            tools_by_name=tools_by_name,
            backend_used=generated.backend_used,
            kind="execution",
            status="COMPLETED",
            intent=intent,
            context_to_keep=context,
            tool_outputs=getattr(generated, "tool_outputs", None),
        )
        sess = await self._session_mgr.get_session(db, session_id=sess.session_id) or sess
        sess.status = "COMPLETED"
        sess.completed_at = datetime.utcnow()
        sess.error = None
        sess.version += 1
        await db.commit()
        return sess

    async def execute(
        self,
        *,
        db: AsyncSession,
        session_id: str,
        background: bool,
        expected_version: int | None,
        user: dict[str, Any],
    ) -> SessionRow:
        sess = await self._session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        if expected_version is not None and sess.version != expected_version:
            raise HTTPException(status_code=409, detail=f"version_conflict expected={expected_version} actual={sess.version}")
        current_plan = await self._plan_service._load_current_plan(db=db, session_id=session_id)
        resume_context = sess.replan_context if isinstance(sess.replan_context, dict) else {}
        pending_resume = resume_context.get("langgraph_approval_resume") if isinstance(resume_context, dict) else None
        if sess.status == "EXECUTING" and isinstance(pending_resume, dict):
            approval_id = str(pending_resume.get("approval_id") or "").strip()
            if approval_id:
                self._start_graph_approval_resume_task(db, approval_id)
            return sess
        if sess.status == "WAITING_APPROVAL":
            return sess
        if current_plan and current_plan.status == "COMPLETED" and sess.status == "COMPLETED":
            return sess
        if sess.status == "COMPLETED":
            return sess
        try:
            self._session_mgr.enforce_limits(sess)
        except TransitionError as e:
            raise HTTPException(status_code=429, detail=str(e))

        if background:
            bind = getattr(db, "bind", None) or db.get_bind()
            bg_sessionmaker = sessionmaker(bind=bind, class_=AsyncSession, expire_on_commit=False)

            async def _runner() -> None:
                try:
                    async with bg_sessionmaker() as bg_db:
                        bg_sess = await self._session_mgr.get_session(bg_db, session_id=session_id)
                        if bg_sess:
                            await self.run_langgraph_session(db=bg_db, sess=bg_sess, user=user)
                except Exception as e:
                    log_event("background_execute_failed", session_id=session_id, error=str(e))

            asyncio.create_task(_runner())
            sess.status = "EXECUTING"
            await db.commit()
            return sess

        sess = await self.run_langgraph_session(db=db, sess=sess, user=user)
        return sess
