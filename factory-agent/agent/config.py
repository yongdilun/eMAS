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
    enable_parallel_execution: bool = False
    intent_repair_attempts: int = 1
    admin_api_key: str = "changeme-admin-key"
    retry_base_delay_s: float = 0.25
    retry_max_delay_s: float = 5.0
    max_foreach_items: int = 50
    max_auto_pages: int = 5
    foreach_page_size: int = 50
    jwt_required: bool = False
    jwt_secret: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_clock_skew_s: int = 30

    # Memory compression
    memory_compaction_step_interval: int = 5
    memory_keep_recent_messages: int = 6

    # Planner / summary backend selection
    planner_backend: str = "structured"  # legacy|structured|langchain
    summary_backend: str = "auto"  # auto|legacy|langchain
    tool_result_summary_backend: str = "auto"  # auto|legacy|langchain
    tool_selector_backend: str = "auto"  # auto|retrieval|langchain
    planner_model: str = "Qwen3.5-9B"
    summary_model: str = "Qwen3.5-9B"
    tool_result_summary_model: str = "Qwen3.5-9B"
    tool_selector_model: str = "Qwen3.5-9B"
    planner_fallback_to_legacy: bool = True
    enforce_tool_registry_health: bool = True
    auto_repair_tool_registry: bool = True
    min_healthy_tool_count: int = 20
    tool_selector_top_k: int = 8
    tool_selector_candidate_pool: int = 24
    tool_selector_max_score_gap: int = 8
    tool_selector_min_confidence: float = 0.35
    tool_selector_reranker_enabled: bool = True
    tool_selector_reranker_timeout_s: float = 3.0
    tool_selector_reranker_max_tokens: int = 220
    embedding_backend: str = "disabled"  # sentence-transformers|disabled
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    llm_json_timeout_s: float = 12.0
    llm_json_max_tokens: int = 320
    tool_result_summary_timeout_s: float = 12.0
    tool_result_summary_max_tokens: int = 320
    force_llm_trace_all: bool = False
    openai_base_url: str | None = None
    openai_api_key: str | None = None


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
        intent_repair_attempts=int(os.getenv("INTENT_REPAIR_ATTEMPTS", "1")),
        http_timeout_s=float(os.getenv("HTTP_TIMEOUT_S", "20")),
        enable_parallel_execution=os.getenv("ENABLE_PARALLEL_EXECUTION", "0").strip().lower()
        in {"1", "true", "yes"},
        retry_base_delay_s=float(os.getenv("RETRY_BASE_DELAY_S", "0.25")),
        retry_max_delay_s=float(os.getenv("RETRY_MAX_DELAY_S", "5.0")),
        max_foreach_items=int(os.getenv("MAX_FOREACH_ITEMS", "50")),
        max_auto_pages=int(os.getenv("MAX_AUTO_PAGES", "5")),
        foreach_page_size=int(os.getenv("FOREACH_PAGE_SIZE", "50")),
        jwt_required=os.getenv("JWT_REQUIRED", "0").strip().lower() in {"1", "true", "yes"},
        jwt_secret=os.getenv("JWT_SECRET") or None,
        jwt_issuer=os.getenv("JWT_ISSUER") or None,
        jwt_audience=os.getenv("JWT_AUDIENCE") or None,
        jwt_clock_skew_s=int(os.getenv("JWT_CLOCK_SKEW_S", "30")),
        memory_compaction_step_interval=int(os.getenv("MEMORY_COMPACTION_STEP_INTERVAL", "5")),
        memory_keep_recent_messages=int(os.getenv("MEMORY_KEEP_RECENT_MESSAGES", "6")),
        planner_backend=os.getenv("PLANNER_BACKEND", "structured").strip().lower(),
        summary_backend=os.getenv("SUMMARY_BACKEND", "auto").strip().lower(),
        tool_result_summary_backend=os.getenv("TOOL_RESULT_SUMMARY_BACKEND", "auto").strip().lower(),
        tool_selector_backend=os.getenv("TOOL_SELECTOR_BACKEND", "auto").strip().lower(),
        planner_model=os.getenv("PLANNER_MODEL", os.getenv("LLM_MODEL", "Qwen3.5-9B")).strip(),
        summary_model=os.getenv("SUMMARY_MODEL", os.getenv("LLM_MODEL", "Qwen3.5-9B")).strip(),
        tool_result_summary_model=os.getenv("TOOL_RESULT_SUMMARY_MODEL", os.getenv("SUMMARY_MODEL", os.getenv("LLM_MODEL", "Qwen3.5-9B"))).strip(),
        tool_selector_model=os.getenv("TOOL_SELECTOR_MODEL", os.getenv("SMALL_LLM_MODEL", os.getenv("PLANNER_MODEL", os.getenv("LLM_MODEL", "Qwen3.5-9B")))).strip(),
        planner_fallback_to_legacy=os.getenv("PLANNER_FALLBACK_TO_LEGACY", "1").strip().lower()
        in {"1", "true", "yes"},
        enforce_tool_registry_health=os.getenv("ENFORCE_TOOL_REGISTRY_HEALTH", "1").strip().lower()
        in {"1", "true", "yes"},
        auto_repair_tool_registry=os.getenv("AUTO_REPAIR_TOOL_REGISTRY", "1").strip().lower()
        in {"1", "true", "yes"},
        min_healthy_tool_count=int(os.getenv("MIN_HEALTHY_TOOL_COUNT", "20")),
        tool_selector_top_k=int(os.getenv("TOOL_SELECTOR_TOP_K", "8")),
        tool_selector_candidate_pool=int(os.getenv("TOOL_SELECTOR_CANDIDATE_POOL", "24")),
        tool_selector_max_score_gap=int(os.getenv("TOOL_SELECTOR_MAX_SCORE_GAP", "8")),
        tool_selector_min_confidence=float(os.getenv("TOOL_SELECTOR_MIN_CONFIDENCE", "0.35")),
        tool_selector_reranker_enabled=os.getenv("TOOL_SELECTOR_RERANKER_ENABLED", "1").strip().lower()
        in {"1", "true", "yes"},
        tool_selector_reranker_timeout_s=float(os.getenv("TOOL_SELECTOR_RERANKER_TIMEOUT_S", "3")),
        tool_selector_reranker_max_tokens=int(os.getenv("TOOL_SELECTOR_RERANKER_MAX_TOKENS", "220")),
        embedding_backend=os.getenv("EMBEDDING_BACKEND", "disabled").strip().lower(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip(),
        llm_json_timeout_s=float(os.getenv("LLM_JSON_TIMEOUT_S", "12")),
        llm_json_max_tokens=int(os.getenv("LLM_JSON_MAX_TOKENS", "320")),
        tool_result_summary_timeout_s=float(
            os.getenv("TOOL_RESULT_SUMMARY_TIMEOUT_S", os.getenv("LLM_JSON_TIMEOUT_S", "12"))
        ),
        tool_result_summary_max_tokens=int(
            os.getenv("TOOL_RESULT_SUMMARY_MAX_TOKENS", os.getenv("LLM_JSON_MAX_TOKENS", "320"))
        ),
        force_llm_trace_all=os.getenv("FORCE_LLM_TRACE_ALL", "0").strip().lower()
        in {"1", "true", "yes"},
        openai_base_url=(os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL") or None),
        openai_api_key=(os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or None),
    )
