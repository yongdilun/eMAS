import asyncio
import os
import time

from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from factory_agent.observability.metrics import metrics

load_dotenv()

# Default to SQLite for local dev; override with DATABASE_URL for MySQL/Postgres.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./factory_agent.db")
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT_S = int(os.getenv("DB_POOL_TIMEOUT_S", "30"))
DB_SLOW_QUERY_MS = float(os.getenv("DB_SLOW_QUERY_MS", "250"))
SQLITE_BUSY_TIMEOUT_S = float(os.getenv("SQLITE_BUSY_TIMEOUT_S", "30"))

engine_kwargs = {"echo": False}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update({"connect_args": {"timeout": SQLITE_BUSY_TIMEOUT_S}})
else:
    engine_kwargs.update(
        {
            "pool_size": DB_POOL_SIZE,
            "max_overflow": DB_MAX_OVERFLOW,
            "pool_timeout": DB_POOL_TIMEOUT_S,
            "pool_pre_ping": True,
        }
    )


def configure_aiomysql_cancel_safe_termination(dialect) -> None:
    if getattr(dialect, "driver", None) != "aiomysql":
        return
    if getattr(dialect, "_factory_agent_cancel_safe_termination", False):
        return
    original_do_terminate = dialect.do_terminate

    def do_terminate(dbapi_connection):
        try:
            original_do_terminate(dbapi_connection)
        except asyncio.CancelledError:
            force_close = getattr(dbapi_connection, "_terminate_force_close", None)
            if callable(force_close):
                force_close()
                return
            raise

    dialect.do_terminate = do_terminate
    dialect._factory_agent_cancel_safe_termination = True


engine = create_async_engine(DATABASE_URL, **engine_kwargs)
configure_aiomysql_cancel_safe_termination(engine.sync_engine.dialect)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    if not DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout = {int(SQLITE_BUSY_TIMEOUT_S * 1000)}")
        if ":memory:" not in DATABASE_URL:
            cursor.execute("PRAGMA journal_mode = WAL")
    finally:
        cursor.close()


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
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await close_session_after_cancellation(session)


async def close_session_after_cancellation(session: AsyncSession) -> None:
    # Request cancellation can arrive while FastAPI is finalizing dependencies; let
    # the DB close finish so SQLAlchemy/aiomysql do not log interrupted cleanup.
    close_task = asyncio.create_task(session.close())
    try:
        await asyncio.shield(close_task)
    except asyncio.CancelledError:
        while not close_task.done():
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError:
                continue
        try:
            await close_task
        except (Exception, asyncio.CancelledError):
            pass
        raise

