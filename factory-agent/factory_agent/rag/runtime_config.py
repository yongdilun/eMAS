from __future__ import annotations

import inspect
from dataclasses import asdict
from typing import Any

from factory_agent.config import DEFAULT_RAG_ADVISORY_VARIANT, Settings
from factory_agent.rag.context_building import BudgetedRSESettings
from factory_agent.rag.pipeline import RAGPipelineConfig


SUPPORTED_ADVISORY_VARIANTS = ("default", "current", "previous", "V3", "V7", "V12", "V15", "V15A", "V15B", "V15C")


def _budgeted_rse_settings(**overrides: Any) -> dict[str, Any]:
    return {**asdict(BudgetedRSESettings()), **overrides}


def _v15_advisory_config(variant: str, budgeted_rse_settings: dict[str, Any]) -> RAGPipelineConfig:
    return RAGPipelineConfig(
        variant_id=variant,
        operating_mode="advisory",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        vector_top_k=10,
        keyword_top_k=10,
        fusion_top_k=10,
        query_rewrite=False,
        corpus_aware_query_rewrite=True,
        multi_query_retrieval=True,
        context_builder="budgeted_rse",
        context_builder_settings={"budgeted_rse": budgeted_rse_settings},
        compression="none",
        document_augmentation=False,
        allow_rerank_fallback=False,
    )


def advisory_rag_pipeline_config(settings: Settings) -> RAGPipelineConfig:
    """Resolve the production advisory RAG config from runtime settings."""

    return advisory_rag_pipeline_config_for_variant(
        getattr(settings, "rag_advisory_variant", DEFAULT_RAG_ADVISORY_VARIANT)
    )


def advisory_rag_pipeline_config_for_variant(variant_id: str | None) -> RAGPipelineConfig:
    variant = (variant_id or DEFAULT_RAG_ADVISORY_VARIANT).strip().upper() or DEFAULT_RAG_ADVISORY_VARIANT
    if variant in {"DEFAULT", "CURRENT", "LEGACY", "PREVIOUS"}:
        return RAGPipelineConfig(variant_id="default", operating_mode="advisory")
    if variant == "V3":
        return RAGPipelineConfig(
            variant_id="V3",
            operating_mode="advisory",
            retrieval_mode="hybrid",
            use_rerank=True,
            expand_neighbors=False,
            vector_top_k=10,
            keyword_top_k=10,
            fusion_top_k=10,
        )
    if variant == "V7":
        return RAGPipelineConfig(
            variant_id="V7",
            operating_mode="advisory",
            retrieval_mode="hybrid",
            use_rerank=True,
            expand_neighbors=False,
            vector_top_k=10,
            keyword_top_k=10,
            fusion_top_k=10,
            query_rewrite=True,
            context_builder="small_to_big",
            compression="none",
            document_augmentation=False,
            allow_rerank_fallback=False,
        )
    if variant == "V12":
        return RAGPipelineConfig(
            variant_id="V12",
            operating_mode="advisory",
            retrieval_mode="hybrid",
            use_rerank=True,
            expand_neighbors=False,
            vector_top_k=10,
            keyword_top_k=10,
            fusion_top_k=10,
            query_rewrite=True,
            context_builder="rse",
            compression="none",
            document_augmentation=False,
            allow_rerank_fallback=False,
        )
    if variant == "V15":
        return _v15_advisory_config(variant, _budgeted_rse_settings(use_evidence_cards=True))
    if variant == "V15A":
        return _v15_advisory_config(variant, _budgeted_rse_settings(use_evidence_cards=False))
    if variant == "V15B":
        return _v15_advisory_config(
            variant,
            _budgeted_rse_settings(use_evidence_cards=True, evidence_card_context_mode="metadata_only"),
        )
    if variant == "V15C":
        return _v15_advisory_config(
            variant,
            _budgeted_rse_settings(use_evidence_cards=True, evidence_card_context_mode="mode_aware"),
        )
    raise ValueError(
        "Unsupported RAG advisory variant "
        f"{variant_id!r}; expected one of: {', '.join(SUPPORTED_ADVISORY_VARIANTS)}"
    )


async def run_rag_pipeline_with_optional_config(
    pipeline: Any,
    *,
    query: str,
    session_id: str | None,
    route: str,
    api_data: dict[str, Any] | None = None,
    config: RAGPipelineConfig,
) -> Any:
    """Call production and test RAG pipeline adapters without breaking older fakes."""

    kwargs: dict[str, Any] = {
        "query": query,
        "session_id": session_id,
        "route": route,
    }
    if api_data is not None:
        kwargs["api_data"] = api_data
    if _accepts_config(pipeline.run):
        kwargs["config"] = config
    return await pipeline.run(**kwargs)


def _accepts_config(callable_obj: Any) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return True
    return "config" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
