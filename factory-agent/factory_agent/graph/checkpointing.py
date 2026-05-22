from __future__ import annotations

import base64
import asyncio
from datetime import datetime, timedelta
import json
import time
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import Settings
from ..observability.metrics import metrics
from ..observability.telemetry import log_event
from ..persistence.models import WorkflowCheckpoint as WorkflowCheckpointRow

try:
    from langgraph.checkpoint.memory import InMemorySaver
except Exception:  # pragma: no cover
    InMemorySaver = None  # type: ignore[assignment]

_MEMORY_CHECKPOINTERS: dict[str, Any] = {}
_DB_CHECKPOINTERS: dict[str, Any] = {}


def get_process_memory_checkpointer() -> Any:
    """Process-local MemorySaver shared by ``build_graph_checkpointer`` and graph compile fallback.

    Using one saver per process ensures ``generate`` and ``resume_after_approval`` see the same
    interrupt checkpoints when no DB/Postgres saver is configured.
    """
    key = "memory"
    saver = _MEMORY_CHECKPOINTERS.get(key)
    if saver is not None:
        return saver
    try:
        from langgraph.checkpoint.memory import MemorySaver
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("langgraph.checkpoint.memory.MemorySaver is unavailable.") from exc
    saver = MemorySaver()
    _MEMORY_CHECKPOINTERS[key] = saver
    return saver


def clear_graph_checkpointer_cache() -> None:
    """Drop process-local checkpointer singletons.

    Tests use this to simulate a backend restart. Production restart naturally
    clears these dictionaries while durable checkpoint rows remain in the DB.
    """
    _MEMORY_CHECKPOINTERS.clear()
    _DB_CHECKPOINTERS.clear()


def _typed_to_json(value: tuple[str, bytes]) -> dict[str, str]:
    return {"type": value[0], "data": base64.b64encode(value[1]).decode("ascii")}


def _typed_from_json(value: Any) -> tuple[str, bytes]:
    if not isinstance(value, dict):
        return ("empty", b"")
    return (str(value.get("type") or "empty"), base64.b64decode(str(value.get("data") or "")))


def _version_to_json(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": value}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "str", "value": str(value)}


def _version_from_json(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    kind = value.get("type")
    raw = value.get("value")
    if kind == "bool":
        return bool(raw)
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    return str(raw)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump())
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class SqlAlchemyLangGraphCheckpointSaver(InMemorySaver):  # type: ignore[misc]
    """Durable LangGraph saver backed by the existing workflow_checkpoints table.

    The row stores LangGraph's native checkpoint payload plus a JSON-safe
    `agent_state` projection for snapshot/history compatibility. Execution
    resume still uses the native checkpoint data.
    """

    def __init__(self, database_url: str):
        if InMemorySaver is None:  # pragma: no cover
            raise RuntimeError("LangGraph memory saver is unavailable.")
        super().__init__()
        self._engine = create_async_engine(database_url, echo=False)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)
        self._loaded_threads: set[str] = set()
        self._schema_ready = False
        self._lock = asyncio.Lock()

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._engine.begin() as conn:
            await conn.run_sync(WorkflowCheckpointRow.__table__.create, checkfirst=True)
        self._schema_ready = True

    def _thread_id(self, config: dict[str, Any]) -> str:
        return str((config.get("configurable") or {}).get("thread_id") or "")

    def _normalized_config(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(config or {})
        configurable = dict(normalized.get("configurable") or {})
        configurable.setdefault("checkpoint_ns", "")
        normalized["configurable"] = configurable
        return normalized

    async def _load_thread(self, thread_id: str) -> None:
        if not thread_id or thread_id in self._loaded_threads:
            return
        started = time.perf_counter()
        metrics.inc("checkpoint_load_total")
        await self._ensure_schema()
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(WorkflowCheckpointRow).where(WorkflowCheckpointRow.thread_id == thread_id)
                )
            ).scalars().first()
        self._loaded_threads.add(thread_id)
        try:
            if not row:
                return
            row_state = row.state
            if isinstance(row_state, str):
                try:
                    row_state = json.loads(row_state)
                except Exception:
                    row_state = {}
            if not isinstance(row_state, dict):
                return
            payload = row_state.get("langgraph_checkpoint")
            if not isinstance(payload, dict):
                return

            self.storage[thread_id].clear()
            for ns, checkpoints in (payload.get("storage") or {}).items():
                ns_key = str(ns)
                for checkpoint_id, saved in (checkpoints or {}).items():
                    if not isinstance(saved, dict):
                        continue
                    self.storage[thread_id][ns_key][str(checkpoint_id)] = (
                        _typed_from_json(saved.get("checkpoint")),
                        _typed_from_json(saved.get("metadata")),
                        saved.get("parent"),
                    )

            for key in list(self.writes.keys()):
                if key[0] == thread_id:
                    del self.writes[key]
            for saved in payload.get("writes") or []:
                if not isinstance(saved, dict):
                    continue
                outer_key = (
                    thread_id,
                    str(saved.get("checkpoint_ns") or ""),
                    str(saved.get("checkpoint_id") or ""),
                )
                inner_key = (str(saved.get("task_id") or ""), int(saved.get("idx") or 0))
                self.writes[outer_key][inner_key] = (
                    inner_key[0],
                    str(saved.get("channel") or ""),
                    _typed_from_json(saved.get("value")),
                    str(saved.get("task_path") or ""),
                )

            for key in list(self.blobs.keys()):
                if key[0] == thread_id:
                    del self.blobs[key]
            for saved in payload.get("blobs") or []:
                if not isinstance(saved, dict):
                    continue
                self.blobs[
                    (
                        thread_id,
                        str(saved.get("checkpoint_ns") or ""),
                        str(saved.get("channel") or ""),
                        _version_from_json(saved.get("version")),
                    )
                ] = _typed_from_json(saved.get("value"))
        finally:
            metrics.observe("checkpoint_load_latency_ms", (time.perf_counter() - started) * 1000.0)

    def _serialize_thread(self, thread_id: str) -> dict[str, Any]:
        storage: dict[str, dict[str, Any]] = {}
        for ns, checkpoints in self.storage.get(thread_id, {}).items():
            storage[str(ns)] = {}
            for checkpoint_id, saved in checkpoints.items():
                checkpoint, metadata, parent = saved
                storage[str(ns)][str(checkpoint_id)] = {
                    "checkpoint": _typed_to_json(checkpoint),
                    "metadata": _typed_to_json(metadata),
                    "parent": parent,
                }

        writes: list[dict[str, Any]] = []
        for (saved_thread, ns, checkpoint_id), saved_writes in self.writes.items():
            if saved_thread != thread_id:
                continue
            for (_task_id, idx), (task_id, channel, value, task_path) in saved_writes.items():
                writes.append(
                    {
                        "checkpoint_ns": ns,
                        "checkpoint_id": checkpoint_id,
                        "task_id": task_id,
                        "idx": idx,
                        "channel": channel,
                        "value": _typed_to_json(value),
                        "task_path": task_path,
                    }
                )

        blobs: list[dict[str, Any]] = []
        for (saved_thread, ns, channel, version), value in self.blobs.items():
            if saved_thread != thread_id:
                continue
            blobs.append(
                {
                    "checkpoint_ns": ns,
                    "channel": channel,
                    "version": _version_to_json(version),
                    "value": _typed_to_json(value),
                }
            )
        return {"storage": storage, "writes": writes, "blobs": blobs}

    def _latest_agent_state(self, thread_id: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        latest = super().get_tuple(config)
        if latest is None:
            return {}
        values = latest.checkpoint.get("channel_values")
        return _jsonable(values if isinstance(values, dict) else {})

    async def _save_thread(self, session: AsyncSession, thread_id: str) -> None:
        started = time.perf_counter()
        metrics.inc("checkpoint_save_total")
        now = datetime.utcnow()
        try:
            payload = {
                "kind": "langgraph_native_checkpoint",
                "agent_state": self._latest_agent_state(thread_id),
                "langgraph_checkpoint": self._serialize_thread(thread_id),
            }
            row = (
                await session.execute(
                    select(WorkflowCheckpointRow).where(WorkflowCheckpointRow.thread_id == thread_id)
                )
            ).scalars().first()
            if row is None:
                row = WorkflowCheckpointRow(
                    thread_id=thread_id,
                    session_id=thread_id,
                    state=payload,
                    version=1,
                    expires_at=now + timedelta(days=30),
                )
                session.add(row)
            else:
                row.session_id = row.session_id or thread_id
                row.state = payload
                row.version = int(row.version or 0) + 1
                row.updated_at = now
                row.expires_at = row.expires_at or (now + timedelta(days=30))
            await session.commit()
        finally:
            metrics.observe("checkpoint_save_latency_ms", (time.perf_counter() - started) * 1000.0)

    async def aget_tuple(self, config: dict[str, Any]) -> Any | None:
        normalized = self._normalized_config(config)
        async with self._lock:
            await self._load_thread(self._thread_id(normalized))
            return super().get_tuple(normalized)

    async def alist(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ):
        if config is not None:
            normalized = self._normalized_config(config)
            await self._load_thread(self._thread_id(normalized))
            async for item in super().alist(normalized, filter=filter, before=before, limit=limit):
                yield item
            return

        await self._ensure_schema()
        async with self._sessionmaker() as session:
            rows = (await session.execute(select(WorkflowCheckpointRow.thread_id))).scalars().all()
        for thread_id in rows:
            await self._load_thread(str(thread_id))
        async for item in super().alist(None, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = self._normalized_config(config)
        thread_id = self._thread_id(normalized)
        async with self._lock:
            await self._load_thread(thread_id)
            result = super().put(normalized, checkpoint, metadata, new_versions)
            async with self._sessionmaker() as session:
                await self._save_thread(session, thread_id)
            return result

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        normalized = self._normalized_config(config)
        thread_id = self._thread_id(normalized)
        async with self._lock:
            await self._load_thread(thread_id)
            super().put_writes(normalized, writes, task_id, task_path)
            async with self._sessionmaker() as session:
                await self._save_thread(session, thread_id)

    async def adelete_thread(self, thread_id: str) -> None:
        async with self._lock:
            await self._load_thread(thread_id)
            super().delete_thread(thread_id)
            await self._ensure_schema()
            async with self._sessionmaker() as session:
                await session.execute(delete(WorkflowCheckpointRow).where(WorkflowCheckpointRow.thread_id == thread_id))
                await session.commit()
            self._loaded_threads.discard(thread_id)


def build_graph_checkpointer(settings: Settings) -> Any | None:
    """Best-effort native LangGraph checkpointer factory.

    Preference:
    1) Postgres saver when explicitly configured and importable
    2) Existing database-backed saver for durable restart recovery
    3) In-memory saver as local/dev fallback
    4) None when disabled
    """
    backend = (settings.graph_checkpoint_backend or "auto").strip().lower() or "auto"
    if backend == "off":
        return None

    postgres_dsn = settings.graph_checkpoint_postgres_dsn
    if backend in {"auto", "postgres"} and postgres_dsn:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore

            return AsyncPostgresSaver.from_conn_string(postgres_dsn)
        except Exception as exc:
            log_event(
                "graph_postgres_checkpointer_unavailable",
                level="WARNING",
                backend=backend,
                fallback="database_or_memory",
                error=str(exc),
            )

    if backend in {"auto", "postgres", "db", "database", "sqlalchemy"}:
        database_url = (settings.database_url or "").strip()
        if database_url:
            if database_url.endswith(":memory:") and backend == "auto":
                pass
            else:
                saver = _DB_CHECKPOINTERS.get(database_url)
                if saver is None:
                    try:
                        saver = SqlAlchemyLangGraphCheckpointSaver(database_url)
                        _DB_CHECKPOINTERS[database_url] = saver
                    except Exception as exc:
                        log_event(
                            "graph_database_checkpointer_unavailable",
                            level="WARNING",
                            backend=backend,
                            fallback="memory" if backend in {"auto", "postgres"} else "none",
                            error=str(exc),
                        )
                        if backend not in {"auto", "postgres"}:
                            return None
                if saver is not None:
                    return saver

    if backend in {"auto", "postgres", "memory"}:
        try:
            return get_process_memory_checkpointer()
        except Exception:
            return None
    return None
