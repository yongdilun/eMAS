from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter

from .dependencies import build_require_admin, build_require_jwt
from .response_mappers import step_to_response
from .routers.admin import build_admin_router
from .routers.approvals import build_approvals_router
from .routers.dlq import build_dlq_router
from .routers.documents import build_documents_router
from .routers.events import build_events_router
from .routers.execution import build_execution_router
from .routers.messages import build_messages_router
from .routers.plans import build_plans_router
from .routers.session_controls import build_session_controls_router
from .routers.sessions import build_sessions_router
from .routers.snapshots import build_snapshots_router
from .routers.tools import build_tools_router
from ..analysis.summary_backend import SummaryAdapter
from ..config import Settings
from ..observability.events import EventBus
from ..observability.telemetry import log_step_status_changed
from ..orchestration.memory_manager import MemoryManager
from ..orchestration.session_manager import SessionManager
from ..planning.tool_selector import ToolSelector
from ..registry.tool_registry import ToolRegistry
from ..services.approval_resume_service import ApprovalResumeService
from ..services.execution_service import ExecutionService
from ..services.plan_creation_service import PlanCreationService
from ..services.planner_service import PlannerService
from ..services.session_snapshot_service import (
    SessionSnapshotService,
    _activity_steps_for_snapshot,
    _semantic_payload_for_timeline_event,
    _should_skip_semantic_timeline_event,
)
from factory_agent.persistence.models import generate_uuid as _generate_uuid
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow

generate_uuid = _generate_uuid


def build_router(
    *,
    settings: Settings,
    tool_registry: ToolRegistry,
    event_bus: EventBus,
    enqueue_session: Any | None = None,
    planner_adapter: PlannerService | None = None,
    rag_pipeline_adapter: Any | None = None,
) -> APIRouter:
    del enqueue_session

    router = APIRouter()
    session_mgr = SessionManager(settings)
    memory_manager = MemoryManager(settings)
    planner = planner_adapter or PlannerService(settings=settings, tool_registry=tool_registry)
    tool_selector = ToolSelector(settings)
    summary_adapter = SummaryAdapter(settings)
    require_admin = build_require_admin(settings)
    require_jwt = build_require_jwt(settings)

    plan_creation_service = PlanCreationService(
        settings=settings,
        session_mgr=session_mgr,
        memory_manager=memory_manager,
        planner=planner,
        tool_selector=tool_selector,
        summary_adapter=summary_adapter,
        tool_registry=tool_registry,
        rag_pipeline=rag_pipeline_adapter,
        uuid_factory=lambda: generate_uuid(),
    )
    snapshot_service = SessionSnapshotService(
        session_mgr=session_mgr,
        memory_manager=memory_manager,
        tool_registry=tool_registry,
    )
    approval_resume_service = ApprovalResumeService(
        settings=settings,
        session_mgr=session_mgr,
        plan_service=plan_creation_service,
        event_bus=event_bus,
        planner_adapter_is_none=planner_adapter is None,
    )
    execution_service = ExecutionService(
        session_mgr=session_mgr,
        plan_service=plan_creation_service,
        start_graph_approval_resume_task=approval_resume_service.start_graph_approval_resume_task,
    )

    def _session_duration_s(sess: SessionRow) -> int:
        if not sess.session_started_at:
            return 0
        return int((datetime.utcnow() - sess.session_started_at).total_seconds())

    def _log_step_status(sess: SessionRow, step: PlanStepRow, status: str) -> None:
        log_step_status_changed(
            session_id=sess.session_id,
            plan_id=sess.plan_id,
            plan_version=sess.plan_version,
            step_id=step.step_id,
            step_index=step.step_index,
            tool=step.tool_name,
            status=status,
            idempotency_key=step.idempotency_key,
            required_approval=bool(step.requires_approval),
            session_step_count=sess.step_count,
            session_llm_call_count=sess.llm_call_count,
            session_replan_count=sess.replan_count,
            session_duration_s=_session_duration_s(sess),
            user_id=sess.user_id,
        )

    router.include_router(build_admin_router(tool_registry=tool_registry, event_bus=event_bus, require_admin=require_admin))
    router.include_router(build_dlq_router(require_jwt=require_jwt))
    router.include_router(build_documents_router(require_jwt=require_jwt))
    router.include_router(build_sessions_router(session_mgr=session_mgr, require_jwt=require_jwt))
    router.include_router(
        build_messages_router(
            session_mgr=session_mgr,
            memory_manager=memory_manager,
            event_bus=event_bus,
            require_jwt=require_jwt,
        )
    )
    router.include_router(
        build_tools_router(
            tool_registry=tool_registry,
            tool_selector=tool_selector,
            require_jwt=require_jwt,
        )
    )
    router.include_router(
        build_snapshots_router(
            load_session_snapshot=snapshot_service.load_session_snapshot,
            require_jwt=require_jwt,
        )
    )
    router.include_router(
        build_events_router(
            load_session_snapshot=snapshot_service.load_session_snapshot,
            activity_steps_for_snapshot=snapshot_service.activity_steps_for_snapshot,
            semantic_payload_for_timeline_event=snapshot_service.semantic_payload_for_timeline_event,
            should_skip_semantic_timeline_event=snapshot_service.should_skip_semantic_timeline_event,
            require_jwt=require_jwt,
        )
    )
    router.include_router(
        build_session_controls_router(
            session_mgr=session_mgr,
            event_bus=event_bus,
            require_jwt=require_jwt,
            log_step_status=_log_step_status,
            step_to_response=step_to_response,
        )
    )
    router.include_router(build_plans_router(plan_creation_service=plan_creation_service, require_jwt=require_jwt))
    router.include_router(build_execution_router(execution_service=execution_service, require_jwt=require_jwt))
    router.include_router(
        build_approvals_router(
            session_mgr=session_mgr,
            planner=planner,
            require_jwt=require_jwt,
            publish_agent_event=approval_resume_service.publish_agent_event,
            start_graph_approval_resume_task=approval_resume_service.start_graph_approval_resume_task,
            should_resume_graph_approval_inline=approval_resume_service.should_resume_graph_approval_inline,
            resume_approved_graph_approval=approval_resume_service.resume_approved_graph_approval,
        )
    )

    return router
