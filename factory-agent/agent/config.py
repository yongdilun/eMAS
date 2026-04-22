import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str | None
    go_api_base_url: str

    # Hard limits (Phase 1: tracked + enforced in SessionManager)
    max_plan_steps: int
    max_session_steps: int
    max_replans: int
    max_llm_calls: int
    max_session_duration_s: int

    # HTTP execution
    http_timeout_s: float


def get_settings() -> Settings:
    database_url = os.getenv(
        "DATABASE_URL",
        # Prefer SQLite by default for local dev; override in production.
        "sqlite+aiosqlite:///./factory_agent.db",
    )
    redis_url = os.getenv("REDIS_URL") or None
    go_api_base_url = os.getenv("GO_API_BASE_URL", "http://localhost:8080").rstrip("/")

    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        go_api_base_url=go_api_base_url,
        max_plan_steps=int(os.getenv("MAX_PLAN_STEPS", "10")),
        max_session_steps=int(os.getenv("MAX_SESSION_STEPS", "50")),
        max_replans=int(os.getenv("MAX_REPLANS", "5")),
        max_llm_calls=int(os.getenv("MAX_LLM_CALLS", "20")),
        max_session_duration_s=int(os.getenv("MAX_SESSION_DURATION_S", str(60 * 30))),
        http_timeout_s=float(os.getenv("HTTP_TIMEOUT_S", "20")),
    )

