import pytest
from datetime import datetime

import httpx
import respx

from agent.config import Settings
from agent.events import AgentEvent
from agent.execution import ExecutionEngine, compute_idempotency_key
from agent.schemas import ToolInfo


class FakeEventBus:
    def __init__(self):
        self.published = []

    async def publish(self, event: AgentEvent):
        self.published.append(event)

    async def listen(self, handler):
        return


async def _seed_core(db_session, *, session_id: str, plan_id: str, plan_hash: str, plan_version: int):
    from models import Plan, Session, generate_uuid

    sess = Session(
        session_id=session_id,
        user_id="u1",
        status="IDLE",
        plan_id=plan_id,
        plan_version=plan_version,
        plan_hash=plan_hash,
        current_step_index=0,
        step_count=0,
        replan_count=0,
        llm_call_count=0,
        session_started_at=datetime.utcnow(),
    )
    plan = Plan(
        plan_id=plan_id,
        session_id=session_id,
        version=plan_version,
        dependency_graph={0: []},
        parallel_groups=[],
        plan_hash=plan_hash,
        plan_explanation="x",
        risk_summary="x",
        created_by="llm",
    )
    db_session.add_all([sess, plan])
    await db_session.commit()
    return sess, plan


async def _seed_step(db_session, *, plan_id: str, session_id: str, step_index: int, tool_name: str, args: dict, plan_version: int):
    from models import PlanStep, generate_uuid

    step = PlanStep(
        step_id=generate_uuid(),
        plan_id=plan_id,
        session_id=session_id,
        step_index=step_index,
        tool_name=tool_name,
        args=args,
        status="NOT_STARTED",
        idempotency_key=compute_idempotency_key(
            session_id=session_id, step_index=step_index, plan_version=plan_version, args=args
        ),
        requires_approval=False,
        retry_count=0,
        max_retries=3,
    )
    db_session.add(step)
    await db_session.commit()
    await db_session.refresh(step)
    return step


@pytest.mark.asyncio
async def test_execution_happy_path_completes(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess1"
    plan_id = "plan1"
    plan_hash = "hash1"
    plan_version = 1
    sess, _ = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)

    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="get__machines", args={}, plan_version=plan_version)

    tools = {
        "get__machines": ToolInfo(
            name="get__machines",
            description="",
            endpoint="/machines",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=["machine"],
        )
    }

    respx_mock.get("http://testserver/machines").respond(200, json={"ok": True})
    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)

    from sqlalchemy import select
    from models import PlanStep, Session
    sess2 = await db_session.get(Session, session_id)
    step = (await db_session.execute(select(PlanStep))).scalars().first()
    assert sess2.status == "COMPLETED"
    assert step.status == "DONE"


@pytest.mark.asyncio
async def test_execution_approval_gates_without_http(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess2"
    plan_id = "plan2"
    plan_hash = "hash2"
    plan_version = 1
    sess, _ = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="post__write", args={"id": 1}, plan_version=plan_version)

    tools = {
        "post__write": ToolInfo(
            name="post__write",
            description="",
            endpoint="/write",
            method="POST",
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
            is_read_only=False,
            requires_approval=True,
            side_effect_level="HIGH",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=[],
        )
    }

    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)
    assert len(respx_mock.calls) == 0

    from sqlalchemy import select
    from models import Approval, Session
    sess2 = await db_session.get(Session, session_id)
    approvals = (await db_session.execute(select(Approval))).scalars().all()
    assert sess2.status == "WAITING_APPROVAL"
    assert len(approvals) == 1


@pytest.mark.asyncio
async def test_execution_snapshot_replay_skips_http(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess3"
    plan_id = "plan3"
    plan_hash = "hash3"
    plan_version = 1
    sess, plan = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)
    step = await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="get__machines", args={}, plan_version=plan_version)

    from models import ExecutionSnapshot, generate_uuid
    snap = ExecutionSnapshot(
        snapshot_id=generate_uuid(),
        step_id=step.step_id,
        session_id=session_id,
        tool_name="get__machines",
        tool_version=1,
        schema_version=1,
        input_args={},
        plan_hash=plan.plan_hash,
        plan_version=plan.version,
        idempotency_key=step.idempotency_key,
        http_status=200,
        response_body={"cached": True},
        latency_ms=1,
    )
    db_session.add(snap)
    await db_session.commit()

    tools = {
        "get__machines": ToolInfo(
            name="get__machines",
            description="",
            endpoint="/machines",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        )
    }

    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)
    assert len(respx_mock.calls) == 0


@pytest.mark.asyncio
async def test_execution_ambiguous_timeout_creates_dlq_and_blocks(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=0.01,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess4"
    plan_id = "plan4"
    plan_hash = "hash4"
    plan_version = 1
    sess, _ = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="post__maybe", args={"id": 1}, plan_version=plan_version)

    tools = {
        "post__maybe": ToolInfo(
            name="post__maybe",
            description="",
            endpoint="/maybe",
            method="POST",
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
            is_read_only=False,
            requires_approval=False,
            side_effect_level="HIGH",
            is_concurrency_safe=True,
            is_strongly_idempotent=False,
            capability_tags=[],
        )
    }

    respx_mock.post("http://testserver/maybe").mock(side_effect=httpx.TimeoutException("timeout"))
    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)

    from sqlalchemy import select
    from models import DeadLetter, PlanStep, Session
    sess2 = await db_session.get(Session, session_id)
    step = (await db_session.execute(select(PlanStep))).scalars().first()
    dlqs = (await db_session.execute(select(DeadLetter))).scalars().all()
    assert sess2.status == "BLOCKED"
    assert step.status == "AMBIGUOUS"
    assert any(d.failure_type == "ambiguous_execution" for d in dlqs)
    assert any(e.event_type == "session_resume" for e in event_bus.published)


@pytest.mark.asyncio
async def test_execution_http_5xx_triggers_replan(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess5"
    plan_id = "plan5"
    plan_hash = "hash5"
    plan_version = 1
    sess, _ = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="get__fail", args={}, plan_version=plan_version)

    tools = {
        "get__fail": ToolInfo(
            name="get__fail",
            description="",
            endpoint="/fail",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        )
    }

    respx_mock.get("http://testserver/fail").respond(500, json={"error": "no"})
    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)

    from sqlalchemy import select
    from models import DeadLetter, Session
    sess2 = await db_session.get(Session, session_id)
    dlqs = (await db_session.execute(select(DeadLetter))).scalars().all()
    assert sess2.status == "PLANNING"
    assert sess2.replan_context is not None
    assert len(dlqs) == 0


@pytest.mark.asyncio
async def test_execution_strong_idempotent_timeout_retries_then_succeeds(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
        retry_base_delay_s=0.001,
        retry_max_delay_s=0.002,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess6"
    plan_id = "plan6"
    plan_hash = "hash6"
    plan_version = 1
    sess, _ = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="get__flaky", args={}, plan_version=plan_version)

    tools = {
        "get__flaky": ToolInfo(
            name="get__flaky",
            description="",
            endpoint="/flaky",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        )
    }

    route = respx_mock.get("http://testserver/flaky")
    route.mock(side_effect=[httpx.TimeoutException("timeout"), httpx.Response(200, json={"ok": True})])

    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)

    from sqlalchemy import select
    from models import PlanStep, Session

    sess2 = await db_session.get(Session, session_id)
    step = (await db_session.execute(select(PlanStep))).scalars().first()
    assert sess2.status == "COMPLETED"
    assert step.status == "DONE"
    assert step.retry_count == 1


@pytest.mark.asyncio
async def test_execution_rate_limit_inside_loop_pushes_dlq(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=1,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess7"
    plan_id = "plan7"
    plan_hash = "hash7"
    plan_version = 1
    sess, _ = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="get__one", args={}, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=1, tool_name="get__two", args={}, plan_version=plan_version)

    tools = {
        "get__one": ToolInfo(
            name="get__one",
            description="",
            endpoint="/one",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        ),
        "get__two": ToolInfo(
            name="get__two",
            description="",
            endpoint="/two",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        ),
    }

    respx_mock.get("http://testserver/one").respond(200, json={"ok": True})
    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)

    from sqlalchemy import select
    from models import DeadLetter, Session

    sess2 = await db_session.get(Session, session_id)
    dlqs = (await db_session.execute(select(DeadLetter))).scalars().all()
    assert sess2.status == "FAILED"
    assert any(d.failure_type == "rate_limit_exceeded" for d in dlqs)


@pytest.mark.asyncio
async def test_execution_http_401_fails_hard_without_retry_and_pushes_dlq(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess8"
    plan_id = "plan8"
    plan_hash = "hash8"
    plan_version = 1
    sess, _ = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="get__unauth", args={}, plan_version=plan_version)

    tools = {
        "get__unauth": ToolInfo(
            name="get__unauth",
            description="",
            endpoint="/unauth",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        ),
    }

    route = respx_mock.get("http://testserver/unauth")
    route.respond(401, json={"error": "unauthorized"})
    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)

    from sqlalchemy import select
    from models import DeadLetter, Session

    sess2 = await db_session.get(Session, session_id)
    dlq = (await db_session.execute(select(DeadLetter))).scalars().first()
    assert route.call_count == 1
    assert sess2.status == "FAILED"
    assert dlq is not None
    assert dlq.failure_type == "unrecoverable_error"


@pytest.mark.asyncio
async def test_execution_http_404_triggers_replan_and_preserves_done_steps(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess9"
    plan_id = "plan9"
    plan_hash = "hash9"
    plan_version = 1
    sess, _ = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="get__ok", args={}, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=1, tool_name="get__missing", args={"id": 404}, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=2, tool_name="get__unused", args={}, plan_version=plan_version)

    tools = {
        "get__ok": ToolInfo(
            name="get__ok",
            description="",
            endpoint="/ok",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        ),
        "get__missing": ToolInfo(
            name="get__missing",
            description="",
            endpoint="/missing",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        ),
        "get__unused": ToolInfo(
            name="get__unused",
            description="",
            endpoint="/unused",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        ),
    }

    respx_mock.get("http://testserver/ok").respond(200, json={"ok": True})
    respx_mock.get("http://testserver/missing").respond(404, json={"error": "missing"})
    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)

    from sqlalchemy import select
    from models import PlanStep, Session

    sess2 = await db_session.get(Session, session_id)
    steps = (
        await db_session.execute(
            select(PlanStep).where(PlanStep.plan_id == plan_id).order_by(PlanStep.step_index.asc())
        )
    ).scalars().all()
    assert sess2.status == "PLANNING"
    assert steps[0].status == "DONE"
    assert steps[1].status == "FAILED"
    assert sess2.replan_context is not None
    completed = sess2.replan_context.get("completed_steps", [])
    assert any(item.get("step_index") == 0 for item in completed)


@pytest.mark.asyncio
async def test_execution_mid_step_user_message_queued_and_processed_after_step(db_session, respx_mock):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
    )
    event_bus = FakeEventBus()
    engine = ExecutionEngine(settings, event_bus)

    session_id = "sess11"
    plan_id = "plan11"
    plan_hash = "hash11"
    plan_version = 1
    sess, plan = await _seed_core(db_session, session_id=session_id, plan_id=plan_id, plan_hash=plan_hash, plan_version=plan_version)
    await _seed_step(db_session, plan_id=plan_id, session_id=session_id, step_index=0, tool_name="get__slow", args={}, plan_version=plan_version)

    tools = {
        "get__slow": ToolInfo(
            name="get__slow",
            description="",
            endpoint="/slow",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            is_concurrency_safe=True,
            is_strongly_idempotent=True,
            capability_tags=[],
        )
    }

    async def fake_call(**kwargs):
        sess.pending_user_message = "also include maintenance schedule"
        await db_session.commit()
        return {"ok": True}, 5

    engine._execute_tool_call = fake_call  # type: ignore[method-assign]
    await engine.execute_until_blocked(db_session, session=sess, tools_by_name=tools)

    from sqlalchemy import select
    from models import PlanStep, Session

    sess2 = await db_session.get(Session, session_id)
    step = (
        await db_session.execute(
            select(PlanStep).where(PlanStep.plan_id == plan.plan_id).where(PlanStep.step_index == 0)
        )
    ).scalars().first()
    assert step is not None
    assert step.status == "DONE"
    assert sess2.status == "PLANNING"
    assert sess2.replan_context is not None
    assert sess2.replan_context.get("user_message") == "also include maintenance schedule"
