from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.persistence.models import WorkflowCheckpoint as WorkflowCheckpointRow
from factory_agent.planning.historical_direct_v2_compatibility import is_historical_direct_v2_created_by


def is_langgraph_plan(plan: PlanRow | None) -> bool:
    created_by = str(getattr(plan, "created_by", "") or "").strip().lower()
    return created_by in {"langgraph", "planner_owned_agent_graph"}


def is_planner_owned_v2_plan(plan: PlanRow | None) -> bool:
    return bool(plan and is_historical_direct_v2_created_by(getattr(plan, "created_by", None)))


def allows_persisted_step_projection(plan: PlanRow | None) -> bool:
    return is_langgraph_plan(plan) or is_planner_owned_v2_plan(plan)


def checkpoint_state_is_langgraph_native(state: object) -> bool:
    return isinstance(state, dict) and state.get("kind") == "langgraph_native_checkpoint"


async def has_langgraph_native_checkpoint(db: AsyncSession, *, session_id: str) -> bool:
    now = datetime.utcnow()
    thread_state = (
        await db.execute(
            select(WorkflowCheckpointRow.state)
            .where(WorkflowCheckpointRow.thread_id == session_id)
            .where((WorkflowCheckpointRow.expires_at.is_(None)) | (WorkflowCheckpointRow.expires_at > now))
            .limit(1)
        )
    ).scalars().first()
    if checkpoint_state_is_langgraph_native(thread_state):
        return True

    checkpoint_id = (
        await db.execute(
            select(WorkflowCheckpointRow.checkpoint_id)
            .where(WorkflowCheckpointRow.session_id == session_id)
            .where((WorkflowCheckpointRow.expires_at.is_(None)) | (WorkflowCheckpointRow.expires_at > now))
            .order_by(WorkflowCheckpointRow.updated_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if checkpoint_id is None:
        return False

    session_state = (
        await db.execute(
            select(WorkflowCheckpointRow.state).where(WorkflowCheckpointRow.checkpoint_id == checkpoint_id)
        )
    ).scalars().first()
    return checkpoint_state_is_langgraph_native(session_state)


async def is_graph_native_session(
    db: AsyncSession,
    session: SessionRow | None,
    *,
    plan: PlanRow | None = None,
) -> bool:
    """Return true for every persisted marker of LangGraph-native execution.

    This helper is intentionally shared by API, worker, and legacy execution
    guardrails so checkpoint-only graph sessions cannot fall back to relational
    plan-step execution.
    """
    if session is None:
        return False

    context = session.replan_context if isinstance(session.replan_context, dict) else {}
    if bool(context.get("langgraph_pending_approval")) or bool(context.get("langgraph_approval_resume")):
        return True

    current_plan = plan
    if current_plan is None and session.plan_id:
        current_plan = (await db.execute(select(PlanRow).where(PlanRow.plan_id == session.plan_id))).scalars().first()
    if is_langgraph_plan(current_plan):
        return True

    return await has_langgraph_native_checkpoint(db, session_id=session.session_id)
