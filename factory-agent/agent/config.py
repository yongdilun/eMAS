import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str | None
    go_api_base_url: str

    # Worker pool / backpressure (Phase 0 scaffold)
    worker_count: int
    session_queue_size: int

    # Hard limits (Phase 1: tracked + enforced in SessionManager)
    max_plan_steps: int
    max_session_steps: int
    max_replans: int
    max_llm_calls: int
    max_session_duration_s: int

    # HTTP execution
    http_timeout_s: float
    admin_api_key: str = "changeme-admin-key"
    retry_base_delay_s: float = 0.25
    retry_max_delay_s: float = 5.0
    jwt_required: bool = False
    jwt_secret: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_clock_skew_s: int = 30

    # Memory compression
    memory_compaction_step_interval: int = 5
    memory_keep_recent_messages: int = 6


def get_settings() -> Settings:
    database_url = os.getenv(
        "DATABASE_URL",
        # Prefer SQLite by default for local dev; override in production.
        "sqlite+aiosqlite:///./factory_agent.db",
    )
    redis_url = os.getenv("REDIS_URL") or None
    go_api_base_url = os.getenv("GO_API_BASE_URL", "http://localhost:8080").rstrip("/")
    admin_api_key = os.getenv("ADMIN_API_KEY", "changeme-admin-key")
    max_concurrent = int(os.getenv("MAX_CONCURRENT", os.getenv("AGENT_WORKERS", "100")))
    max_queue = int(os.getenv("MAX_QUEUE", os.getenv("SESSION_QUEUE_SIZE", "500")))

    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        go_api_base_url=go_api_base_url,
        admin_api_key=admin_api_key,
        worker_count=max_concurrent,
        session_queue_size=max_queue,
        max_plan_steps=int(os.getenv("MAX_PLAN_STEPS", "10")),
        max_session_steps=int(os.getenv("MAX_SESSION_STEPS", "50")),
        max_replans=int(os.getenv("MAX_REPLANS", "5")),
        max_llm_calls=int(os.getenv("MAX_LLM_CALLS", "20")),
        max_session_duration_s=int(os.getenv("MAX_SESSION_DURATION_S", str(60 * 30))),
        http_timeout_s=float(os.getenv("HTTP_TIMEOUT_S", "20")),
        retry_base_delay_s=float(os.getenv("RETRY_BASE_DELAY_S", "0.25")),
        retry_max_delay_s=float(os.getenv("RETRY_MAX_DELAY_S", "5.0")),
        jwt_required=os.getenv("JWT_REQUIRED", "0").strip().lower() in {"1", "true", "yes"},
        jwt_secret=os.getenv("JWT_SECRET") or None,
        jwt_issuer=os.getenv("JWT_ISSUER") or None,
        jwt_audience=os.getenv("JWT_AUDIENCE") or None,
        jwt_clock_skew_s=int(os.getenv("JWT_CLOCK_SKEW_S", "30")),
        memory_compaction_step_interval=int(os.getenv("MEMORY_COMPACTION_STEP_INTERVAL", "5")),
        memory_keep_recent_messages=int(os.getenv("MEMORY_KEEP_RECENT_MESSAGES", "6")),
    )
