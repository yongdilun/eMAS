import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import factory_agent.persistence.models as models  # noqa: F401
from factory_agent.persistence.database import Base


@pytest.mark.asyncio
async def test_mysql_schema_creates_cleanly():
    mysql_url = os.getenv("MYSQL_TEST_DATABASE_URL")
    if not mysql_url:
        pytest.skip("MYSQL_TEST_DATABASE_URL not set")

    engine = create_async_engine(mysql_url, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

