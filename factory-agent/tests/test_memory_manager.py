from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import select

from factory_agent.config import Settings
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.persistence.models import Message, Session, VectorMemory, generate_uuid


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://test",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
        memory_enabled=True,
        vector_memory_enabled=True,
        checkpoint_enabled=True,
        memory_retention_days=30,
        memory_redact_pii=True,
        memory_compaction_step_interval=5,
        memory_keep_recent_messages=2,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_memory_compaction_emits_structured_payload(sessionmaker_override, db_session):
    settings = _settings()
    manager = MemoryManager(settings)

    session_id = generate_uuid()
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u-memory",
            status="IDLE",
            session_started_at=datetime.utcnow(),
        )
    )
    await db_session.commit()

    messages = [
        ("user", "Please use JOB-SEED-001 and contact me at test@example.com"),
        ("assistant", "Decision: we will inspect JOB-SEED-001 first."),
        ("tool_result", "Tool failed with timeout error while fetching machine details."),
        ("assistant", "Approval required before update."),
        ("user", "Can you retry this?"),
    ]
    for role, content in messages:
        db_session.add(
            Message(
                message_id=generate_uuid(),
                session_id=session_id,
                role=role,
                content=content,
                tool_name="get__jobs_{id}" if role == "tool_result" else None,
            )
        )
    await db_session.commit()

    compacted = await manager.maybe_compact(db_session, session_id=session_id, step_count=5)
    assert compacted is True

    rows = (await db_session.execute(select(Message).where(Message.session_id == session_id))).scalars().all()
    assert len(rows) == 3  # summary + keep_recent(2)
    summary_row = next((row for row in rows if row.tool_name == "__memory_compaction__"), None)
    assert summary_row is not None
    payload = json.loads(summary_row.content)
    assert "summary" in payload
    assert "important_entities" in payload
    assert "decisions" in payload
    assert "failed_tool_calls" in payload
    assert "approvals" in payload
    assert "open_questions" in payload
    assert "source_message_ids" in payload
    assert payload["source_message_ids"]
    assert "[REDACTED_EMAIL]" not in summary_row.content  # no raw email in summary payload text


@pytest.mark.asyncio
async def test_checkpoint_save_and_load_round_trip(sessionmaker_override, db_session):
    settings = _settings()
    manager = MemoryManager(settings)
    session_id = generate_uuid()
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u-checkpoint",
            status="EXECUTING",
            current_step_index=2,
            session_started_at=datetime.utcnow(),
        )
    )
    await db_session.commit()

    await manager.save_checkpoint(
        db_session,
        session_id=session_id,
        thread_id=session_id,
        state={"status": "EXECUTING", "current_step_index": 2, "step_count": 4},
    )

    loaded = await manager.load_checkpoint(db_session, thread_id=session_id)
    assert loaded is not None
    assert loaded["thread_id"] == session_id
    assert loaded["state"]["current_step_index"] == 2

    loaded_by_session = await manager.load_checkpoint(db_session, session_id=session_id)
    assert loaded_by_session is not None
    assert loaded_by_session["session_id"] == session_id


@pytest.mark.asyncio
async def test_vector_memory_retrieval_is_session_scoped(sessionmaker_override, db_session):
    settings = _settings()
    manager = MemoryManager(settings)

    s1 = generate_uuid()
    s2 = generate_uuid()
    db_session.add_all(
        [
            Session(session_id=s1, user_id="u1", status="IDLE", session_started_at=datetime.utcnow()),
            Session(session_id=s2, user_id="u2", status="IDLE", session_started_at=datetime.utcnow()),
        ]
    )
    await db_session.commit()

    m1 = Message(message_id=generate_uuid(), session_id=s1, role="user", content="Preferred machine is M-CNC-01")
    m2 = Message(message_id=generate_uuid(), session_id=s2, role="user", content="Preferred machine is M-LTH-02")
    db_session.add_all([m1, m2])
    await db_session.commit()

    await manager.index_message(
        db_session,
        session_id=s1,
        message_id=m1.message_id,
        role="user",
        content=m1.content,
        commit=True,
    )
    await manager.index_message(
        db_session,
        session_id=s2,
        message_id=m2.message_id,
        role="user",
        content=m2.content,
        commit=True,
    )

    context = await manager.build_planner_context(
        db_session,
        session_id=s1,
        intent="Show preferred machine again",
        base_context={},
    )
    hits = context.get("retrieved_memory") or []
    assert hits
    assert all(hit.get("session_id") == s1 for hit in hits)

    total_vectors = (await db_session.execute(select(VectorMemory))).scalars().all()
    assert len(total_vectors) >= 2


@pytest.mark.asyncio
async def test_build_planner_context_loads_messages_when_memory_disabled(sessionmaker_override, db_session):
    settings = _settings(memory_enabled=False, vector_memory_enabled=False, checkpoint_enabled=False)
    manager = MemoryManager(settings)
    session_id = generate_uuid()
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u-msg",
            status="IDLE",
            session_started_at=datetime.utcnow(),
        )
    )
    db_session.add(
        Message(
            message_id=generate_uuid(),
            session_id=session_id,
            role="user",
            content="Show slots for JOB-SEED-004",
        )
    )
    await db_session.commit()

    ctx = await manager.build_planner_context(
        db_session,
        session_id=session_id,
        intent="now show its slots",
        base_context={},
    )
    msgs = ctx.get("messages") or []
    assert msgs
    assert any("JOB-SEED-004" in str(m.get("content") or "") for m in msgs if isinstance(m, dict))
