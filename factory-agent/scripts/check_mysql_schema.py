import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine

import factory_agent.persistence.models as models  # noqa: F401
from factory_agent.persistence.database import Base


async def _run(url: str) -> None:
    engine = create_async_engine(url, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    mysql_url = os.getenv("MYSQL_TEST_DATABASE_URL")
    if not mysql_url:
        raise SystemExit("MYSQL_TEST_DATABASE_URL is required")
    asyncio.run(_run(mysql_url))
    print("MySQL schema create check passed.")

