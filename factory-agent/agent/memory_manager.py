from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Message as MessageRow
from models import generate_uuid

from .config import Settings


class MemoryManager:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def maybe_compact(self, db: AsyncSession, *, session_id: str, step_count: int) -> bool:
        interval = max(0, int(self._settings.memory_compaction_step_interval))
        if interval <= 0:
            return False
        if step_count <= 0 or step_count % interval != 0:
            return False

        keep_recent = max(2, int(self._settings.memory_keep_recent_messages))
        messages = (
            await db.execute(
                select(MessageRow).where(MessageRow.session_id == session_id).order_by(MessageRow.created_at.asc())
            )
        ).scalars().all()

        if len(messages) <= keep_recent + 1:
            return False

        to_compact = messages[:-keep_recent]
        if not to_compact:
            return False

        summary_lines: list[str] = []
        for msg in to_compact:
            content = (msg.content or "").strip().replace("\n", " ")
            if len(content) > 200:
                content = content[:200] + "..."
            summary_lines.append(f"- [{msg.role}] {content}")
        summary_body = "\n".join(summary_lines[:25])
        summary = (
            f"Memory compaction at {datetime.utcnow().isoformat()}Z\n"
            f"Compressed {len(to_compact)} older messages.\n"
            f"{summary_body}"
        )

        compacted = MessageRow(
            message_id=generate_uuid(),
            session_id=session_id,
            role="system",
            content=summary,
            step_id=None,
            tool_name=None,
            created_at=datetime.utcnow(),
        )
        db.add(compacted)
        for msg in to_compact:
            await db.delete(msg)
        await db.commit()
        return True
