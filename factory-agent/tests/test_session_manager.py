import pytest
from datetime import datetime, timedelta

from agent.config import Settings
from agent.session_manager import SessionManager, TransitionError, VersionConflictError


@pytest.mark.asyncio
async def test_invalid_transition_raises(db_session):
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
        max_session_duration_s=60,
        http_timeout_s=1.0,
    )
    mgr = SessionManager(settings)
    sess = await mgr.create_session(db_session, user_id="u1")
    sess.status = "COMPLETED"
    await db_session.commit()

    with pytest.raises(TransitionError):
        await mgr.transition_status(db_session, session=sess, new_status="EXECUTING")


def test_enforce_limits_raises_on_duration():
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=2,
        max_replans=1,
        max_llm_calls=1,
        max_session_duration_s=1,
        http_timeout_s=1.0,
    )
    mgr = SessionManager(settings)
    # Use a lightweight fake session row-like object for enforce_limits.
    class S:
        step_count = 0
        replan_count = 0
        llm_call_count = 0
        session_started_at = datetime.utcnow() - timedelta(seconds=10)

    with pytest.raises(TransitionError):
        mgr.enforce_limits(S())


@pytest.mark.asyncio
async def test_update_with_version_rejects_second_concurrent_update(db_session):
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
        max_session_duration_s=60,
        http_timeout_s=1.0,
    )
    mgr = SessionManager(settings)
    sess = await mgr.create_session(db_session, user_id="u1")
    session_id = sess.session_id
    expected = sess.version

    first = await mgr.update_with_version(
        db_session,
        session_id=sess.session_id,
        expected_version=expected,
        values={"status": "EXECUTING"},
    )
    assert first.status == "EXECUTING"

    with pytest.raises(VersionConflictError):
        await mgr.update_with_version(
            db_session,
            session_id=session_id,
            expected_version=expected,
            values={"status": "FAILED"},
        )

    latest = await mgr.get_session(db_session, session_id=session_id)
    assert latest is not None
    assert latest.status == "EXECUTING"
