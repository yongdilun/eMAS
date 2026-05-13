from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.persistence.models import generate_uuid

from ..config import Settings
from ..memory.checkpoint import SqlCheckpointStore
from ..memory.vector_store import SqlVectorStore
from ..observability.metrics import metrics
from ..observability.telemetry import log_event


_ENTITY_RE = re.compile(r"\b(?:JOB|AIPROP|MAT|M|P|JS|STP)-[A-Z0-9-]+\b")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")


class MemoryManager:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def maybe_compact(self, db: AsyncSession, *, session_id: str, step_count: int) -> bool:
        if not self._settings.memory_enabled:
            return False
        interval = max(0, int(self._settings.memory_compaction_step_interval))
        if interval <= 0:
            return False
        if step_count <= 0 or step_count % interval != 0:
            return False

        try:
            await self._prune_expired(db)
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

            summary_payload = self._build_structured_summary(to_compact)
            compacted = MessageRow(
                message_id=generate_uuid(),
                session_id=session_id,
                role="system",
                content=json.dumps(summary_payload, ensure_ascii=True),
                step_id=None,
                tool_name="__memory_compaction__",
                created_at=datetime.utcnow(),
            )
            db.add(compacted)
            for msg in to_compact:
                await db.delete(msg)

            session_row = await self._session_row(db, session_id=session_id)
            await self._index_compaction_memory(
                db,
                session_id=session_id,
                user_id=session_row.user_id if session_row else None,
                source_message_id=compacted.message_id,
                summary_payload=summary_payload,
            )
            await db.commit()
            metrics.inc("memory_compaction_total", labels={"status": "success"})
            return True
        except Exception as exc:
            await db.rollback()
            metrics.inc("memory_compaction_total", labels={"status": "error"})
            log_event(
                "memory_compaction_failed",
                level="WARNING",
                session_id=session_id,
                step_count=step_count,
                error=str(exc),
            )
            return False

    async def build_planner_context(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        intent: str,
        base_context: dict[str, Any] | None = None,
        k: int = 8,
    ) -> dict[str, Any]:
        context = dict(base_context or {})
        context["session_id"] = session_id
        # LangGraph needs prior user/assistant/tool turns for follow-ups ("now show its slots");
        # this is independent of vector memory / checkpointing.
        history = await self._recent_session_messages(db, session_id=session_id, limit=max(k, 24))
        if history:
            context["messages"] = self._rows_to_planner_message_dicts(history)

        if not self._settings.memory_enabled:
            return context
        if not (intent or "").strip():
            return context

        session_row = await self._session_row(db, session_id=session_id)
        user_id = session_row.user_id if session_row else None

        metrics.inc("memory_retrieval_total")
        retrieved: list[dict[str, Any]] = []
        if self._settings.vector_memory_enabled:
            store = self._vector_store(db)
            retrieved = await store.similarity_search(
                intent,
                k=k,
                session_id=session_id,
                user_id=user_id,
            )
        if not retrieved:
            metrics.inc("memory_retrieval_empty_total")
        else:
            context["retrieved_memory"] = retrieved

        if self._settings.checkpoint_enabled:
            checkpoint = await self.load_checkpoint(db, session_id=session_id)
            if checkpoint:
                state = checkpoint.get("state") if isinstance(checkpoint.get("state"), dict) else {}
                context["checkpoint_state"] = {
                    "thread_id": checkpoint.get("thread_id"),
                    "status": state.get("status"),
                    "current_step_index": state.get("current_step_index"),
                    "step_count": state.get("step_count"),
                    "updated_at": checkpoint.get("updated_at"),
                }

        return context

    async def _recent_session_messages(
        self, db: AsyncSession, *, session_id: str | None, limit: int
    ) -> list[MessageRow]:
        sid = (session_id or "").strip()
        if not sid:
            return []
        lim = max(1, min(int(limit), 100))
        rows = (
            await db.execute(
                select(MessageRow)
                .where(MessageRow.session_id == sid)
                .order_by(MessageRow.created_at.desc())
                .limit(lim)
            )
        ).scalars().all()
        return list(reversed(rows))

    def _rows_to_planner_message_dicts(self, rows: list[MessageRow]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            if row.tool_name == "__memory_compaction__":
                continue
            role = (row.role or "user").strip().lower()
            if role == "system":
                continue
            text = (row.content or "").strip()
            if self._settings.memory_redact_pii:
                text = self._redact_pii(text).strip()
            if not text:
                continue
            item: dict[str, Any] = {"role": role, "content": text}
            if role == "tool_result":
                item["tool_call_id"] = str(row.step_id or row.message_id or "context")
            out.append(item)
        return out

    async def save_checkpoint(
        self,
        db: AsyncSession,
        *,
        session_id: str | None = None,
        thread_id: str | None = None,
        state: dict[str, Any],
    ) -> None:
        if not self._settings.checkpoint_enabled:
            return
        target_thread_id = (thread_id or session_id or "").strip()
        if not target_thread_id:
            return
        session_row = await self._session_row(db, session_id=session_id) if session_id else None
        store = self._checkpoint_store(db)
        try:
            metrics.inc("checkpoint_save_total")
            await store.save(
                target_thread_id,
                state,
                session_id=session_id,
                user_id=session_row.user_id if session_row else None,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            metrics.inc("checkpoint_error_total")
            raise

    async def load_checkpoint(
        self,
        db: AsyncSession,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not self._settings.checkpoint_enabled:
            return None
        store = self._checkpoint_store(db)
        metrics.inc("checkpoint_load_total")
        try:
            if thread_id:
                return await store.load(thread_id)
            if session_id:
                return await store.load_by_session(session_id)
            return None
        except Exception:
            metrics.inc("checkpoint_error_total")
            return None

    async def index_message(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        message_id: str,
        role: str,
        content: str,
        tool_name: str | None = None,
        reusable_scope: str = "session",
        commit: bool = True,
    ) -> bool:
        if not self._settings.memory_enabled or not self._settings.vector_memory_enabled:
            return False
        if role not in {"user", "assistant", "tool_result", "system"}:
            return False

        session_row = await self._session_row(db, session_id=session_id)
        user_id = session_row.user_id if session_row else None
        redacted = self._redact_pii(content)
        if not redacted.strip():
            return False
        store = self._vector_store(db)
        await store.add(
            session_id=session_id,
            user_id=user_id,
            text=redacted[:4000],
            memory_type="message",
            source_message_id=message_id,
            metadata={"role": role, "tool_name": tool_name},
            reusable_scope=reusable_scope,
            pii_redacted=(redacted != content),
        )
        if commit:
            await db.commit()
        return True

    def _checkpoint_store(self, db: AsyncSession) -> SqlCheckpointStore:
        return SqlCheckpointStore(db, retention_days=self._settings.memory_retention_days)

    def _vector_store(self, db: AsyncSession) -> SqlVectorStore:
        return SqlVectorStore(db, retention_days=self._settings.memory_retention_days)

    async def _session_row(self, db: AsyncSession, *, session_id: str | None) -> SessionRow | None:
        if not session_id:
            return None
        return (await db.execute(select(SessionRow).where(SessionRow.session_id == session_id))).scalars().first()

    async def _prune_expired(self, db: AsyncSession) -> None:
        removed_checkpoints = 0
        removed_vectors = 0
        if self._settings.checkpoint_enabled:
            removed_checkpoints = await self._checkpoint_store(db).prune_expired()
        if self._settings.vector_memory_enabled:
            removed_vectors = await self._vector_store(db).prune_expired()
        if removed_checkpoints or removed_vectors:
            log_event(
                "memory_retention_pruned",
                removed_checkpoints=removed_checkpoints,
                removed_vectors=removed_vectors,
            )

    async def _index_compaction_memory(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: str | None,
        source_message_id: str,
        summary_payload: dict[str, Any],
    ) -> None:
        if not self._settings.vector_memory_enabled:
            return
        summary_text = str(summary_payload.get("summary") or "").strip()
        if not summary_text:
            return
        store = self._vector_store(db)
        memory_text = "\n".join(
            [
                summary_text,
                "Entities: " + ", ".join(summary_payload.get("important_entities") or []),
                "Decisions: " + " | ".join(summary_payload.get("decisions") or []),
                "Open questions: " + " | ".join(summary_payload.get("open_questions") or []),
            ]
        )
        await store.add(
            session_id=session_id,
            user_id=user_id,
            text=memory_text[:4000],
            memory_type="compaction",
            source_message_id=source_message_id,
            metadata={
                "source_message_ids": summary_payload.get("source_message_ids") or [],
                "failed_tool_calls": summary_payload.get("failed_tool_calls") or [],
                "approvals": summary_payload.get("approvals") or [],
            },
            reusable_scope="session",
            pii_redacted=False,
        )

    def _redact_pii(self, text: str) -> str:
        if not self._settings.memory_redact_pii:
            return text
        out = _EMAIL_RE.sub("[REDACTED_EMAIL]", text or "")
        out = _PHONE_RE.sub("[REDACTED_PHONE]", out)
        return out

    def _build_structured_summary(self, messages: list[MessageRow]) -> dict[str, Any]:
        important_entities: list[str] = []
        decisions: list[str] = []
        failed_tool_calls: list[dict[str, Any]] = []
        approvals: list[str] = []
        open_questions: list[str] = []
        source_ids: list[str] = []

        for msg in messages:
            source_ids.append(msg.message_id)
            text = self._redact_pii((msg.content or "").strip()).replace("\n", " ").strip()
            if not text:
                continue

            for entity in _ENTITY_RE.findall(text):
                if entity not in important_entities:
                    important_entities.append(entity)

            lower = text.lower()
            if msg.tool_name and msg.tool_name not in important_entities:
                important_entities.append(msg.tool_name)

            if msg.role in {"assistant", "system"} and any(
                token in lower for token in ("decide", "decision", "will ", "plan", "next step", "should")
            ):
                decisions.append(text[:200])

            if any(token in lower for token in ("error", "failed", "exception", "timeout", "traceback")):
                failed_tool_calls.append(
                    {
                        "message_id": msg.message_id,
                        "tool_name": msg.tool_name,
                        "detail": text[:200],
                    }
                )

            if "approval" in lower or "approved" in lower or "rejected" in lower:
                approvals.append(text[:160])

            if "?" in text:
                open_questions.append(text[:180])

        compacted_count = len(messages)
        summary = (
            f"Compaction at {datetime.utcnow().isoformat()}Z. "
            f"Compressed {compacted_count} messages. "
            f"Entities={len(important_entities)}, decisions={len(decisions)}, "
            f"failed_tool_calls={len(failed_tool_calls)}, approvals={len(approvals)}, "
            f"open_questions={len(open_questions)}."
        )

        return {
            "memory_compaction_version": 1,
            "summary": summary,
            "important_entities": important_entities[:50],
            "decisions": decisions[:25],
            "failed_tool_calls": failed_tool_calls[:25],
            "approvals": approvals[:25],
            "open_questions": open_questions[:25],
            "source_message_ids": source_ids,
        }
