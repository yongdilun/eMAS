from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import DeadLetter as DeadLetterRow
from factory_agent.persistence.models import ExecutionSnapshot as ExecutionSnapshotRow
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.persistence.models import VectorMemory as VectorMemoryRow
from factory_agent.persistence.models import WorkflowCheckpoint as WorkflowCheckpointRow


SESSION_OWNED_CHILD_MODELS: tuple[type[Any], ...] = (
    VectorMemoryRow,
    MessageRow,
    ApprovalRow,
    DeadLetterRow,
    ExecutionSnapshotRow,
    PlanStepRow,
    PlanRow,
    WorkflowCheckpointRow,
)


@dataclass(frozen=True)
class SessionDeletionResult:
    session_id: str
    deleted: bool


@dataclass(frozen=True)
class SessionBulkDeletionResult:
    user_id: str
    session_ids: list[str]

    @property
    def deleted_count(self) -> int:
        return len(self.session_ids)


async def delete_session_tree(db: AsyncSession, *, session_id: str) -> SessionDeletionResult:
    existing_session_id = (
        await db.execute(select(SessionRow.session_id).where(SessionRow.session_id == session_id))
    ).scalars().first()
    if existing_session_id is None:
        return SessionDeletionResult(session_id=session_id, deleted=False)

    for model in SESSION_OWNED_CHILD_MODELS:
        await db.execute(delete(model).where(model.session_id == session_id))

    await db.execute(delete(SessionRow).where(SessionRow.session_id == session_id))
    await db.commit()
    return SessionDeletionResult(session_id=session_id, deleted=True)


async def delete_sessions_for_user(db: AsyncSession, *, user_id: str) -> SessionBulkDeletionResult:
    session_ids = list(
        (
            await db.execute(select(SessionRow.session_id).where(SessionRow.user_id == user_id))
        )
        .scalars()
        .all()
    )
    if not session_ids:
        return SessionBulkDeletionResult(user_id=user_id, session_ids=[])

    for model in SESSION_OWNED_CHILD_MODELS:
        await db.execute(delete(model).where(model.session_id.in_(session_ids)))

    await db.execute(delete(SessionRow).where(SessionRow.session_id.in_(session_ids)))
    await db.commit()
    return SessionBulkDeletionResult(user_id=user_id, session_ids=session_ids)
