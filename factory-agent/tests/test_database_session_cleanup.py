from __future__ import annotations

import asyncio

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
