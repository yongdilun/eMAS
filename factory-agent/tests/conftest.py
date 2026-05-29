import sys
from pathlib import Path
import os

# Ensure `factory-agent/` is on sys.path so imports like `import main` work.
FACTORY_AGENT_DIR = Path(__file__).resolve().parents[1]
if str(FACTORY_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_AGENT_DIR))

from factory_agent.platform_compat import guard_blocking_windows_platform_queries

guard_blocking_windows_platform_queries()

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from dotenv import load_dotenv


# Load `factory-agent/.env` for optional integration tests (e.g. REDIS_URL).
load_dotenv(FACTORY_AGENT_DIR / ".env", override=False)

PYTEST_TEMP_ROOT = FACTORY_AGENT_DIR / ".pytest-codex-tmp"
PYTEST_TEMP_ROOT.mkdir(exist_ok=True)
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(PYTEST_TEMP_ROOT))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        (
            "legacy_architecture_quarantine: historical direct-v2 or old graph "
            "compatibility coverage that must not be treated as normal runtime proof"
        ),
    )


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture()
async def sessionmaker_override():
    # Per-test isolated in-memory DB (prevents cross-test snapshot / idempotency collisions).
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    import factory_agent.persistence.models as models  # noqa: F401
    from factory_agent.persistence.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(sessionmaker_override):
    async with sessionmaker_override() as session:
        yield session
