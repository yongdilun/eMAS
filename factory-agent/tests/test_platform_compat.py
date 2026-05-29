from __future__ import annotations

import platform
import sys

from factory_agent.platform_compat import guard_blocking_windows_platform_queries


def test_windows_platform_guard_disables_wmi_queries_by_default(monkeypatch):
    sentinel = object()
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(platform, "_wmi", sentinel, raising=False)
    monkeypatch.delenv("FACTORY_AGENT_ALLOW_WINDOWS_WMI_PLATFORM_QUERIES", raising=False)

    assert guard_blocking_windows_platform_queries() is True
    assert platform._wmi is None


def test_windows_platform_guard_can_be_opted_out(monkeypatch):
    sentinel = object()
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(platform, "_wmi", sentinel, raising=False)
    monkeypatch.setenv("FACTORY_AGENT_ALLOW_WINDOWS_WMI_PLATFORM_QUERIES", "1")

    assert guard_blocking_windows_platform_queries() is False
    assert platform._wmi is sentinel


def test_document_registry_import_does_not_load_heavy_rag_ingestion():
    for module_name in (
        "factory_agent.rag",
        "factory_agent.rag.document_registry",
        "factory_agent.rag.ingestion",
        "sentence_transformers",
        "transformers",
    ):
        sys.modules.pop(module_name, None)

    import factory_agent.rag.document_registry  # noqa: F401

    assert "factory_agent.rag.ingestion" not in sys.modules
    assert "sentence_transformers" not in sys.modules
    assert "transformers" not in sys.modules
