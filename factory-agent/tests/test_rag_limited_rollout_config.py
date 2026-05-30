import asyncio
from types import SimpleNamespace

import pytest

from factory_agent.config import get_settings
from factory_agent.planning.v2_graph_adapters import _rag_runtime_diagnostic_metadata
from factory_agent.rag.runtime_config import (
    advisory_rag_pipeline_config,
    advisory_rag_pipeline_config_for_variant,
    run_rag_pipeline_with_optional_config,
)


def test_v12_advisory_config_matches_limited_rollout_defaults():
    config = advisory_rag_pipeline_config_for_variant("V12")

    assert config.variant_id == "V12"
    assert config.operating_mode == "advisory"
    assert config.retrieval_mode == "hybrid"
    assert config.use_rerank is True
    assert config.expand_neighbors is False
    assert config.query_rewrite is True
    assert config.context_builder == "rse"
    assert config.compression == "none"
    assert config.document_augmentation is False
    assert config.allow_rerank_fallback is False


def test_v15b_advisory_config_matches_school_demo_defaults():
    config = advisory_rag_pipeline_config_for_variant("V15B")
    budgeted_rse = config.context_builder_settings["budgeted_rse"]

    assert config.variant_id == "V15B"
    assert config.operating_mode == "advisory"
    assert config.retrieval_mode == "hybrid"
    assert config.use_rerank is True
    assert config.expand_neighbors is False
    assert config.query_rewrite is False
    assert config.corpus_aware_query_rewrite is True
    assert config.multi_query_retrieval is True
    assert config.context_builder == "budgeted_rse"
    assert config.compression == "none"
    assert config.document_augmentation is False
    assert config.allow_rerank_fallback is False
    assert budgeted_rse["use_evidence_cards"] is True
    assert budgeted_rse["evidence_card_context_mode"] == "metadata_only"


def test_env_unset_advisory_config_defaults_to_v15b(monkeypatch):
    monkeypatch.delenv("RAG_ADVISORY_VARIANT", raising=False)

    settings = get_settings()
    config = advisory_rag_pipeline_config(settings)

    assert settings.rag_advisory_variant == "V15B"
    assert config.variant_id == "V15B"


def test_default_advisory_config_preserves_current_rag_behavior():
    config = advisory_rag_pipeline_config(SimpleNamespace(rag_advisory_variant="default"))

    assert config.variant_id == "default"
    assert config.retrieval_mode == "hybrid"
    assert config.use_rerank is True
    assert config.expand_neighbors is True
    assert config.query_rewrite is False
    assert config.context_builder == "none"
    assert config.compression == "none"
    assert config.document_augmentation is False


def test_unknown_advisory_variant_fails_closed():
    with pytest.raises(ValueError, match="Unsupported RAG advisory variant"):
        advisory_rag_pipeline_config_for_variant("V13")


def test_v15c_is_not_enabled_for_advisory_runtime():
    with pytest.raises(ValueError, match="Unsupported RAG advisory variant"):
        advisory_rag_pipeline_config_for_variant("V15C")


def test_optional_config_runner_passes_config_only_to_new_pipeline_adapters():
    class NewAdapter:
        def __init__(self):
            self.calls = []

        async def run(self, **kwargs):
            self.calls.append(kwargs)
            return "ok"

    class OldAdapter:
        def __init__(self):
            self.calls = []

        async def run(self, *, query, session_id=None, route="RAG_ONLY", api_data=None):
            self.calls.append(
                {
                    "query": query,
                    "session_id": session_id,
                    "route": route,
                    "api_data": api_data,
                }
            )
            return "ok"

    config = advisory_rag_pipeline_config_for_variant("V12")
    new_adapter = NewAdapter()
    old_adapter = OldAdapter()

    asyncio.run(
        run_rag_pipeline_with_optional_config(
            new_adapter,
            query="query",
            session_id="session-1",
            route="RAG_ONLY",
            config=config,
        )
    )
    asyncio.run(
        run_rag_pipeline_with_optional_config(
            old_adapter,
            query="query",
            session_id="session-1",
            route="RAG_ONLY",
            config=config,
        )
    )

    assert new_adapter.calls[0]["config"].variant_id == "V12"
    assert "config" not in old_adapter.calls[0]


def test_rag_runtime_diagnostic_metadata_exposes_rollout_monitoring_fields():
    metadata = {
        "runtime_config": advisory_rag_pipeline_config_for_variant("V12").to_dict(),
        "runtime": {"latency_ms": 123},
        "rerank": {
            "attempted": True,
            "succeeded": True,
            "fallback_used": False,
            "fallback_allowed": False,
        },
        "context_building": {
            "token_estimates": {
                "before_expansion": 100,
                "after_expansion": 500,
                "after_compression": 500,
            }
        },
        "generation_validation": {"initial_reason": "certification_boundary_enforced"},
    }
    sources = [
        {
            "source_id": "osha#chunk-1",
            "doc_id": "osha",
            "chunk_id": "chunk-1",
            "page": 7,
            "section_title": "Checklist",
        }
    ]

    diagnostics = _rag_runtime_diagnostic_metadata(
        result_metadata=metadata,
        answer="I cannot certify current compliance from retrieved checklist text.",
        sources=sources,
    )

    assert diagnostics["rag_variant"] == "V12"
    assert diagnostics["rag_retrieval_mode"] == "hybrid"
    assert diagnostics["rag_context_builder"] == "rse"
    assert diagnostics["rag_rerank_attempted"] is True
    assert diagnostics["rag_rerank_succeeded"] is True
    assert diagnostics["rag_rerank_fallback_used"] is False
    assert diagnostics["rag_citation_count"] == 1
    assert diagnostics["rag_citation_source_ids"] == ["osha#chunk-1"]
    assert diagnostics["rag_citation_pages"] == [7]
    assert diagnostics["rag_boundary_refusal"] is True
    assert diagnostics["rag_latency_ms"] == 123
    assert diagnostics["rag_context_token_estimate"] == 500
