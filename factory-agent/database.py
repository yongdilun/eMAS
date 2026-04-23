import os
import time

from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from agent.metrics import metrics

load_dotenv()

# Default to SQLite for local dev; override with DATABASE_URL for MySQL/Postgres.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./factory_agent.db")
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT_S = int(os.getenv("DB_POOL_TIMEOUT_S", "30"))
DB_SLOW_QUERY_MS = float(os.getenv("DB_SLOW_QUERY_MS", "250"))

engine_kwargs = {"echo": False}
if not DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update(
        {
            "pool_size": DB_POOL_SIZE,
            "max_overflow": DB_MAX_OVERFLOW,
            "pool_timeout": DB_POOL_TIMEOUT_S,
            "pool_pre_ping": True,
        }
    )

engine = create_async_engine(DATABASE_URL, **engine_kwargs)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    metrics.inc("db_query_total")
    start = getattr(context, "_query_start_time", None)
    if start is None:
        return
    duration_ms = (time.perf_counter() - start) * 1000.0
    if duration_ms >= DB_SLOW_QUERY_MS:
        metrics.inc("db_slow_query_total")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
