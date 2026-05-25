import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


FactoryAgentEngine = Literal["v2"]
ResolvedFactoryAgentEngine = Literal["v2"]


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
    planner_max_retries: int = 2
    max_foreach_items: int = 50
    max_auto_pages: int = 5
    foreach_page_size: int = 50
    jwt_required: bool = False
    jwt_secret: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_clock_skew_s: int = 30

    # Memory compression
    memory_enabled: bool = True
    vector_memory_enabled: bool = False
    checkpoint_enabled: bool = True
    memory_retention_days: int = 30
    memory_redact_pii: bool = True
    memory_compaction_step_interval: int = 5
    memory_keep_recent_messages: int = 6

    # Summary / tool-result backends (planning is always LangGraph)
    summary_backend: str = "auto"  # auto|deterministic|langchain (legacy alias -> deterministic)
    tool_result_summary_backend: str = "auto"  # auto|deterministic|langchain (legacy alias -> deterministic)
    tool_selector_backend: str = "auto"  # auto|retrieval|langchain
    planner_model: str = "Qwen3.5-9B"
    summary_model: str = "Qwen3.5-9B"
    tool_result_summary_model: str = "Qwen3.5-9B"
    tool_selector_model: str = "Qwen3.5-9B"
    rag_reranker_model: str = "Qwen3.5-9B"
    rag_answer_model: str = "Qwen3.5-9B"
    bge_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    enforce_tool_registry_health: bool = True
    auto_repair_tool_registry: bool = True
    min_healthy_tool_count: int = 20
    tool_selector_top_k: int = 8
    tool_selector_candidate_pool: int = 24
    tool_selector_max_score_gap: int = 8
    tool_selector_min_confidence: float = 0.35
    # Multiplier (per overlapping path token) that boosts a tool's retrieval
    # score when user intent shares whole-word tokens with the tool's URL path
    # segments. Set to 0 to disable. Higher values make specific multi-segment
    # endpoints (e.g. /machines/reroute-recommendations) outrank broader
    # collection endpoints (e.g. /machines) when the user phrase mentions the
    # specific path tokens.
    tool_selector_path_token_weight: int = 4
    tool_selector_reranker_enabled: bool = True
    tool_selector_reranker_timeout_s: float = 3.0
    tool_selector_reranker_max_tokens: int = 220
    rag_reranker_timeout_s: float = 3.0
    rag_reranker_max_tokens: int = 256
    rag_reranker_top_k: int = 3
    rag_answer_timeout_s: float = 20.0
    rag_answer_max_tokens: int = 600
    rag_advisory_variant: str = "default"
    embedding_backend: str = "disabled"  # sentence-transformers|disabled
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    llm_default_timeout_s: float = 60.0
    llm_default_max_tokens: int = 4096
    planner_timeout_s: float = 60.0
    planner_max_tokens: int = 2048
    summary_timeout_s: float = 20.0
    summary_max_tokens: int = 512
    tool_selector_timeout_s: float = 8.0
    tool_selector_max_tokens: int = 256
    llm_json_timeout_s: float = 12.0
    llm_json_max_tokens: int = 320
    allow_offline_planner_proposer: bool = False
    tool_result_summary_timeout_s: float = 12.0
    tool_result_summary_max_tokens: int = 320
    force_llm_trace_all: bool = False
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    planner_openai_base_url: str | None = None
    summary_openai_base_url: str | None = None
    tool_result_summary_openai_base_url: str | None = None
    tool_selector_openai_base_url: str | None = None
    rag_reranker_openai_base_url: str | None = None
    rag_answer_openai_base_url: str | None = None
    # Phase 4: unified transaction bundle API (backend contract; paths may 404 until implemented).
    agent_transaction_bundle_dry_run_path: str = "/agent/transaction/bundle-dry-run"
    agent_transaction_commit_path: str = "/agent/transaction/commit"
    # Phase 5: checkpointing + controlled repair loop
    graph_checkpoint_backend: str = "auto"  # auto|memory|postgres|off
    graph_checkpoint_postgres_dsn: str | None = None
    max_repair_attempts: int = 3
    # Production deploys should create schema through migrations. Local
    # development keeps create_all enabled unless explicitly disabled.
    enable_startup_create_all: bool = True
    # Phase 5 / FA-004 rollback flag. Prefer explicit migrations; enable only
    # as a temporary compatibility bridge.
    enable_startup_schema_compat: bool = False
    # Planner-owned loop runtime. Retired migration values normalize back to v2.
    factory_agent_engine: FactoryAgentEngine = "v2"


def _normalize_summary_backend(value: str) -> str:
    v = (value or "auto").strip().lower()
    return "deterministic" if v == "legacy" else v


def _normalize_app_mode(value: str | None) -> str:
    v = (value or "development").strip().lower()
    if v in {"prod", "production"}:
        return "production"
    return "development"


def _normalize_graph_checkpoint_backend(raw: str | None) -> str:
    """Avoid empty/typo env values skipping all savers and breaking Command(resume)."""
    v = (raw or "auto").strip().lower() or "auto"
    allowed = {"auto", "memory", "postgres", "off", "db", "database", "sqlalchemy"}
    return v if v in allowed else "auto"


def normalize_factory_agent_engine(raw: str | None) -> FactoryAgentEngine:
    _ = raw
    return "v2"


def resolve_factory_agent_engine_for_runtime(settings: Settings) -> ResolvedFactoryAgentEngine:
    return normalize_factory_agent_engine(getattr(settings, "factory_agent_engine", "v2"))


def _env_truthy(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes"}


def _validate_production_security(
    *,
    app_mode: str,
    jwt_required: bool,
    jwt_secret: str | None,
    admin_api_key: str,
) -> None:
    if app_mode != "production" or _env_truthy("ALLOW_UNSAFE_PRODUCTION_CONFIG"):
        return
    errors: list[str] = []
    if not jwt_required:
        errors.append("JWT_REQUIRED must be enabled in production")
    if not jwt_secret:
        errors.append("JWT_SECRET must be set in production")
    if not admin_api_key or admin_api_key == "changeme-admin-key":
        errors.append("ADMIN_API_KEY must be changed from the development default in production")
    if errors:
        raise ValueError("Unsafe production configuration: " + "; ".join(errors))


def _env_for_mode(app_mode: str, key: str, default: str | None = None) -> str | None:
    prefix = "PRODUCTION" if app_mode == "production" else "DEVELOPMENT"
    scoped_key = f"{prefix}_{key}"
    scoped_value = os.getenv(scoped_key)
    if scoped_value is not None and scoped_value.strip() != "":
        return scoped_value
    # In production, per-role URLs (PLANNER_OPENAI_BASE_URL, etc.) must not override
    # PRODUCTION_OPENAI_BASE_URL when PRODUCTION_PLANNER_OPENAI_BASE_URL is unset —
    # otherwise a leftover localhost URL keeps routing the planner to local Llama.
    if (
        app_mode == "production"
        and key != "OPENAI_BASE_URL"
        and key.endswith("_OPENAI_BASE_URL")
    ):
        prod_generic = os.getenv("PRODUCTION_OPENAI_BASE_URL")
        if prod_generic is not None and prod_generic.strip() != "":
            return prod_generic
    shared_value = os.getenv(key)
    if shared_value is not None and shared_value.strip() != "":
        return shared_value
    return default


def get_settings() -> Settings:
    app_mode = _normalize_app_mode(os.getenv("APP_MODE", os.getenv("ENVIRONMENT", "development")))
    env = lambda key, default=None: _env_for_mode(app_mode, key, default)
    database_url = os.getenv(
        "DATABASE_URL",
        # Prefer SQLite by default for local dev; override in production.
        "sqlite+aiosqlite:///./factory_agent.db",
    )
    redis_url = os.getenv("REDIS_URL") or None
    go_api_base_url = os.getenv("GO_API_BASE_URL", "http://localhost:8080").rstrip("/")
    admin_api_key = os.getenv("ADMIN_API_KEY", "changeme-admin-key")
    jwt_required = _env_truthy("JWT_REQUIRED")
    jwt_secret = os.getenv("JWT_SECRET") or None
    _validate_production_security(
        app_mode=app_mode,
        jwt_required=jwt_required,
        jwt_secret=jwt_secret,
        admin_api_key=admin_api_key,
    )
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
        planner_max_retries=int(os.getenv("PLANNER_MAX_RETRIES", "2")),
        max_foreach_items=int(os.getenv("MAX_FOREACH_ITEMS", "50")),
        max_auto_pages=int(os.getenv("MAX_AUTO_PAGES", "5")),
        foreach_page_size=int(os.getenv("FOREACH_PAGE_SIZE", "50")),
        jwt_required=jwt_required,
        jwt_secret=jwt_secret,
        jwt_issuer=os.getenv("JWT_ISSUER") or None,
        jwt_audience=os.getenv("JWT_AUDIENCE") or None,
        jwt_clock_skew_s=int(os.getenv("JWT_CLOCK_SKEW_S", "30")),
        memory_enabled=os.getenv("MEMORY_ENABLED", "1").strip().lower() in {"1", "true", "yes"},
        vector_memory_enabled=os.getenv("VECTOR_MEMORY_ENABLED", "0").strip().lower() in {"1", "true", "yes"},
        checkpoint_enabled=os.getenv("CHECKPOINT_ENABLED", "1").strip().lower() in {"1", "true", "yes"},
        memory_retention_days=int(os.getenv("MEMORY_RETENTION_DAYS", "30")),
        memory_redact_pii=os.getenv("MEMORY_REDACT_PII", "1").strip().lower() in {"1", "true", "yes"},
        memory_compaction_step_interval=int(os.getenv("MEMORY_COMPACTION_STEP_INTERVAL", "5")),
        memory_keep_recent_messages=int(os.getenv("MEMORY_KEEP_RECENT_MESSAGES", "6")),
        summary_backend=_normalize_summary_backend(os.getenv("SUMMARY_BACKEND", "auto")),
        tool_result_summary_backend=_normalize_summary_backend(os.getenv("TOOL_RESULT_SUMMARY_BACKEND", "auto")),
        tool_selector_backend=os.getenv("TOOL_SELECTOR_BACKEND", "auto").strip().lower(),
        planner_model=env("PLANNER_MODEL", env("LLM_MODEL", "Qwen3.5-9B")).strip(),
        summary_model=env("SUMMARY_MODEL", env("LLM_MODEL", "Qwen3.5-9B")).strip(),
        tool_result_summary_model=env(
            "TOOL_RESULT_SUMMARY_MODEL",
            env("SUMMARY_MODEL", env("LLM_MODEL", "Qwen3.5-9B")),
        ).strip(),
        tool_selector_model=env(
            "TOOL_SELECTOR_MODEL",
            env("SMALL_LLM_MODEL", env("PLANNER_MODEL", env("LLM_MODEL", "Qwen3.5-9B"))),
        ).strip(),
        enforce_tool_registry_health=os.getenv("ENFORCE_TOOL_REGISTRY_HEALTH", "1").strip().lower()
        in {"1", "true", "yes"},
        auto_repair_tool_registry=os.getenv("AUTO_REPAIR_TOOL_REGISTRY", "1").strip().lower()
        in {"1", "true", "yes"},
        min_healthy_tool_count=int(os.getenv("MIN_HEALTHY_TOOL_COUNT", "20")),
        tool_selector_top_k=int(os.getenv("TOOL_SELECTOR_TOP_K", "8")),
        tool_selector_candidate_pool=int(os.getenv("TOOL_SELECTOR_CANDIDATE_POOL", "24")),
        tool_selector_max_score_gap=int(os.getenv("TOOL_SELECTOR_MAX_SCORE_GAP", "8")),
        tool_selector_min_confidence=float(os.getenv("TOOL_SELECTOR_MIN_CONFIDENCE", "0.35")),
        tool_selector_path_token_weight=int(os.getenv("TOOL_SELECTOR_PATH_TOKEN_WEIGHT", "4")),
        tool_selector_reranker_enabled=os.getenv("TOOL_SELECTOR_RERANKER_ENABLED", "1").strip().lower()
        in {"1", "true", "yes"},
        tool_selector_reranker_timeout_s=float(os.getenv("TOOL_SELECTOR_RERANKER_TIMEOUT_S", "3")),
        tool_selector_reranker_max_tokens=int(os.getenv("TOOL_SELECTOR_RERANKER_MAX_TOKENS", "220")),
        embedding_backend=os.getenv("EMBEDDING_BACKEND", "disabled").strip().lower(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip(),
        llm_default_timeout_s=float(os.getenv("LLM_DEFAULT_TIMEOUT_S", "60")),
        llm_default_max_tokens=int(os.getenv("LLM_DEFAULT_MAX_TOKENS", "4096")),
        planner_timeout_s=float(
            os.getenv("PLANNER_TIMEOUT_S", os.getenv("LLM_JSON_TIMEOUT_S", os.getenv("LLM_DEFAULT_TIMEOUT_S", "60")))
        ),
        planner_max_tokens=int(
            os.getenv("PLANNER_MAX_TOKENS", os.getenv("LLM_JSON_MAX_TOKENS", "2048"))
        ),
        summary_timeout_s=float(
            os.getenv("SUMMARY_TIMEOUT_S", os.getenv("LLM_DEFAULT_TIMEOUT_S", "20"))
        ),
        summary_max_tokens=int(
            os.getenv("SUMMARY_MAX_TOKENS", os.getenv("LLM_DEFAULT_MAX_TOKENS", "1024"))
        ),
        tool_selector_timeout_s=float(
            os.getenv(
                "TOOL_SELECTOR_TIMEOUT_S",
                os.getenv("TOOL_SELECTOR_RERANKER_TIMEOUT_S", os.getenv("LLM_DEFAULT_TIMEOUT_S", "20")),
            )
        ),
        tool_selector_max_tokens=int(
            os.getenv(
                "TOOL_SELECTOR_MAX_TOKENS",
                os.getenv("TOOL_SELECTOR_RERANKER_MAX_TOKENS", os.getenv("LLM_DEFAULT_MAX_TOKENS", "1024")),
            )
        ),
        llm_json_timeout_s=float(os.getenv("LLM_JSON_TIMEOUT_S", "12")),
        llm_json_max_tokens=int(os.getenv("LLM_JSON_MAX_TOKENS", "320")),
        allow_offline_planner_proposer=_env_truthy(
            "FACTORY_AGENT_ALLOW_OFFLINE_PLANNER_PROPOSER",
            "0",
        ),
        tool_result_summary_timeout_s=float(
            os.getenv(
                "TOOL_RESULT_SUMMARY_TIMEOUT_S",
                os.getenv("SUMMARY_TIMEOUT_S", os.getenv("LLM_JSON_TIMEOUT_S", os.getenv("LLM_DEFAULT_TIMEOUT_S", "20"))),
            )
        ),
        tool_result_summary_max_tokens=int(
            os.getenv(
                "TOOL_RESULT_SUMMARY_MAX_TOKENS",
                os.getenv("SUMMARY_MAX_TOKENS", os.getenv("LLM_JSON_MAX_TOKENS", os.getenv("LLM_DEFAULT_MAX_TOKENS", "1024"))),
            )
        ),
        force_llm_trace_all=os.getenv("FORCE_LLM_TRACE_ALL", "0").strip().lower()
        in {"1", "true", "yes"},
        openai_base_url=(env("OPENAI_BASE_URL") or env("LLM_BASE_URL") or None),
        openai_api_key=(env("OPENAI_API_KEY") or env("LLM_API_KEY") or None),
        planner_openai_base_url=(
            env("PLANNER_OPENAI_BASE_URL")
            or env("OPENAI_BASE_URL")
            or env("LLM_BASE_URL")
            or None
        ),
        summary_openai_base_url=(
            env("SUMMARY_OPENAI_BASE_URL")
            or env("OPENAI_BASE_URL")
            or env("LLM_BASE_URL")
            or None
        ),
        tool_result_summary_openai_base_url=(
            env("TOOL_RESULT_SUMMARY_OPENAI_BASE_URL")
            or env("OPENAI_BASE_URL")
            or env("LLM_BASE_URL")
            or None
        ),
        tool_selector_openai_base_url=(
            env("TOOL_SELECTOR_OPENAI_BASE_URL")
            or env("OPENAI_BASE_URL")
            or env("LLM_BASE_URL")
            or None
        ),
        rag_reranker_model=env("RAG_RERANKER_MODEL", env("PLANNER_MODEL", env("LLM_MODEL", "Qwen3.5-9B"))).strip(),
        rag_reranker_timeout_s=float(os.getenv("RAG_RERANKER_TIMEOUT_S", "3.0")),
        rag_reranker_max_tokens=int(os.getenv("RAG_RERANKER_MAX_TOKENS", "256")),
        rag_reranker_top_k=int(os.getenv("RAG_RERANKER_TOP_K", "3")),
        rag_answer_model=env("RAG_ANSWER_MODEL", env("PLANNER_MODEL", env("LLM_MODEL", "Qwen3.5-9B"))).strip(),
        rag_answer_timeout_s=float(os.getenv("RAG_ANSWER_TIMEOUT_S", "20.0")),
        rag_answer_max_tokens=int(os.getenv("RAG_ANSWER_MAX_TOKENS", "600")),
        rag_advisory_variant=os.getenv("RAG_ADVISORY_VARIANT", "default").strip() or "default",
        rag_reranker_openai_base_url=(
            env("RAG_RERANKER_OPENAI_BASE_URL")
            or env("OPENAI_BASE_URL")
            or env("LLM_BASE_URL")
            or None
        ),
        rag_answer_openai_base_url=(
            env("RAG_ANSWER_OPENAI_BASE_URL")
            or env("OPENAI_BASE_URL")
            or env("LLM_BASE_URL")
            or None
        ),
        agent_transaction_bundle_dry_run_path=os.getenv(
            "AGENT_TRANSACTION_BUNDLE_DRY_RUN_PATH", "/agent/transaction/bundle-dry-run"
        ).strip(),
        agent_transaction_commit_path=os.getenv("AGENT_TRANSACTION_COMMIT_PATH", "/agent/transaction/commit").strip(),
        graph_checkpoint_backend=_normalize_graph_checkpoint_backend(
            os.getenv("GRAPH_CHECKPOINT_BACKEND", "auto")
        ),
        graph_checkpoint_postgres_dsn=os.getenv("GRAPH_CHECKPOINT_POSTGRES_DSN") or None,
        max_repair_attempts=int(os.getenv("MAX_REPAIR_ATTEMPTS", "3")),
        enable_startup_create_all=_env_truthy(
            "ENABLE_STARTUP_CREATE_ALL",
            "0" if app_mode == "production" else "1",
        ),
        enable_startup_schema_compat=_env_truthy("ENABLE_STARTUP_SCHEMA_COMPAT", "0"),
        bge_reranker_model=os.getenv("BGE_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3").strip(),
        factory_agent_engine=normalize_factory_agent_engine(os.getenv("FACTORY_AGENT_ENGINE", "v2")),
    )
