import pytest

from factory_agent.config import get_settings


def _set_safe_production_auth(monkeypatch):
    monkeypatch.setenv("JWT_REQUIRED", "1")
    monkeypatch.setenv("JWT_SECRET", "prod-secret")
    monkeypatch.setenv("ADMIN_API_KEY", "prod-admin-key")


def test_production_mode_prefers_production_llm_overrides(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    _set_safe_production_auth(monkeypatch)
    monkeypatch.setenv("PLANNER_MODEL", "dev-planner")
    monkeypatch.setenv("OPENAI_API_KEY", "dev-key")
    monkeypatch.setenv("PRODUCTION_PLANNER_MODEL", "gemma-3-12b-it")
    monkeypatch.setenv("PRODUCTION_SUMMARY_MODEL", "gemma-3-4b-it")
    monkeypatch.setenv("PRODUCTION_TOOL_RESULT_SUMMARY_MODEL", "gemma-3-4b-it")
    monkeypatch.setenv("PRODUCTION_TOOL_SELECTOR_MODEL", "gemma-3-12b-it")
    monkeypatch.setenv("PRODUCTION_OPENAI_API_KEY", "prod-key")

    settings = get_settings()

    assert settings.planner_model == "gemma-3-12b-it"
    assert settings.summary_model == "gemma-3-4b-it"
    assert settings.tool_result_summary_model == "gemma-3-4b-it"
    assert settings.tool_selector_model == "gemma-3-12b-it"
    assert settings.openai_api_key == "prod-key"


def test_production_uses_production_openai_base_before_dev_role_urls(monkeypatch):
    """PLANNER_OPENAI_BASE_URL=localhost must not win over PRODUCTION_OPENAI_BASE_URL."""
    monkeypatch.setenv("APP_MODE", "production")
    _set_safe_production_auth(monkeypatch)
    monkeypatch.setenv("PLANNER_OPENAI_BASE_URL", "http://127.0.0.1:900/v1")
    monkeypatch.setenv("SUMMARY_OPENAI_BASE_URL", "http://127.0.0.1:901/v1")
    monkeypatch.setenv("PRODUCTION_OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    monkeypatch.setenv("PRODUCTION_OPENAI_API_KEY", "prod-key")

    settings = get_settings()

    assert settings.planner_openai_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert settings.summary_openai_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert settings.openai_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_development_mode_prefers_development_scoped_override(monkeypatch):
    monkeypatch.setenv("APP_MODE", "development")
    monkeypatch.setenv("PLANNER_MODEL", "shared-planner")
    monkeypatch.setenv("DEVELOPMENT_PLANNER_MODEL", "dev-scoped-planner")

    settings = get_settings()

    assert settings.planner_model == "dev-scoped-planner"


def test_production_mode_rejects_disabled_jwt(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("JWT_REQUIRED", "0")
    monkeypatch.setenv("JWT_SECRET", "prod-secret")
    monkeypatch.setenv("ADMIN_API_KEY", "prod-admin-key")

    with pytest.raises(ValueError, match="JWT_REQUIRED"):
        get_settings()


def test_production_mode_rejects_missing_jwt_secret(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("JWT_REQUIRED", "1")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("ADMIN_API_KEY", "prod-admin-key")

    with pytest.raises(ValueError, match="JWT_SECRET"):
        get_settings()


def test_production_mode_rejects_default_admin_key(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("JWT_REQUIRED", "1")
    monkeypatch.setenv("JWT_SECRET", "prod-secret")
    monkeypatch.setenv("ADMIN_API_KEY", "changeme-admin-key")

    with pytest.raises(ValueError, match="ADMIN_API_KEY"):
        get_settings()


def test_explicit_escape_hatch_allows_unsafe_production_config(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("JWT_REQUIRED", "0")
    monkeypatch.setenv("ADMIN_API_KEY", "changeme-admin-key")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("ALLOW_UNSAFE_PRODUCTION_CONFIG", "1")

    settings = get_settings()

    assert settings.jwt_required is False
