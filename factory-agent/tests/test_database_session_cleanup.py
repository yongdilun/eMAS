from __future__ import annotations

import asyncio

import anyio
import pytest

from factory_agent.persistence import database


@pytest.mark.asyncio
async def test_get_db_finishes_session_close_when_dependency_cleanup_is_cancelled(monkeypatch):
    close_started = asyncio.Event()
    close_continue = asyncio.Event()

    class FakeSession:
        close_finished = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            await self.close()

        async def close(self):
            close_started.set()
            await close_continue.wait()
            self.close_finished = True

    fake_session = FakeSession()
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: fake_session)

    dependency = database.get_db()
    yielded_session = await dependency.__anext__()
    assert yielded_session is fake_session

    cleanup_task = asyncio.create_task(dependency.aclose())
    await close_started.wait()
    cleanup_task.cancel()
    await asyncio.sleep(0)
    close_continue.set()

    with pytest.raises(asyncio.CancelledError):
        await cleanup_task

    assert fake_session.close_finished is True


@pytest.mark.asyncio
async def test_get_db_finishes_session_close_when_anyio_cancel_scope_is_cancelled(monkeypatch):
    close_started = asyncio.Event()
    close_continue = asyncio.Event()

    class FakeSession:
        close_finished = False

        async def close(self):
            close_started.set()
            await close_continue.wait()
            self.close_finished = True

    fake_session = FakeSession()

    async def close_from_request_scope():
        await database.close_session_after_cancellation(fake_session)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(close_from_request_scope)
        await close_started.wait()
        task_group.cancel_scope.cancel()
        close_continue.set()

    assert fake_session.close_finished is True


def test_aiomysql_pool_termination_force_closes_when_graceful_termination_is_cancelled():
    class FakeDialect:
        driver = "aiomysql"

        def do_terminate(self, dbapi_connection):
            dbapi_connection.terminate()

    class FakeConnection:
        force_closed = False

        def terminate(self):
            raise asyncio.CancelledError

        def _terminate_force_close(self):
            self.force_closed = True

    dialect = FakeDialect()
    database.configure_aiomysql_cancel_safe_termination(dialect)
    connection = FakeConnection()

    dialect.do_terminate(connection)

    assert connection.force_closed is True
