from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from factory_agent.api.dependencies import require_session_owner
from factory_agent.observability.telemetry import log_event
from factory_agent.orchestration.session_manager import SessionManager, TransitionError
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.schemas import PlanCreateRequest
from factory_agent.services.plan_creation_service import PlanCreationService, _bump_session_revision


class ExecutionService:
    def __init__(
        self,
        *,
        session_mgr: SessionManager,
        plan_service: PlanCreationService,
        start_graph_approval_resume_task: Callable[[AsyncSession, str], None],
    ) -> None:
        self._session_mgr = session_mgr
        self._plan_service = plan_service
        self._start_graph_approval_resume_task = start_graph_approval_resume_task

    async def _run_planner_owned_session(
        self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        user: dict[str, Any],
    ) -> SessionRow:
        await self._plan_service.create_plan(
            db=db,
            session_id=sess.session_id,
            req=PlanCreateRequest(),
            user=user,
        )
        return await self._session_mgr.get_session(db, session_id=sess.session_id) or sess

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
        require_session_owner(sess, user)
        if self._plan_service._is_cancelled_session(sess):
            return sess
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
        if sess.status in {"BLOCKED", "FAILED"}:
            detail = sess.error or f"session is {sess.status.lower()}"
            raise HTTPException(status_code=400, detail={"errors": [detail]})
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
                            await self._run_planner_owned_session(db=bg_db, sess=bg_sess, user=user)
                except Exception as e:
                    log_event("background_execute_failed", session_id=session_id, error=str(e))
                    async with bg_sessionmaker() as bg_db:
                        failed_sess = await self._session_mgr.get_session(bg_db, session_id=session_id)
                        if failed_sess and failed_sess.status not in {"COMPLETED", "WAITING_APPROVAL", "BLOCKED", "FAILED"}:
                            failed_sess.status = "FAILED"
                            failed_sess.error = (
                                "unable_to_start_request: Background execution stopped before a terminal result. "
                                "Current state: failed. Next action: check diagnostics and retry if it is safe."
                            )
                            failed_sess.completed_at = None
                            _bump_session_revision(failed_sess)
                            await bg_db.commit()

            asyncio.create_task(_runner())
            sess.status = "EXECUTING"
            _bump_session_revision(sess)
            await db.commit()
            return sess

        sess = await self._run_planner_owned_session(db=db, sess=sess, user=user)
        return sess
