from __future__ import annotations

import inspect
from typing import Any

from factory_agent.config import Settings
from factory_agent.rag.pipeline import RAGPipelineConfig


def advisory_rag_pipeline_config(settings: Settings) -> RAGPipelineConfig:
    """Resolve the production advisory RAG config from runtime settings."""

    return advisory_rag_pipeline_config_for_variant(getattr(settings, "rag_advisory_variant", "default"))


def advisory_rag_pipeline_config_for_variant(variant_id: str | None) -> RAGPipelineConfig:
    variant = (variant_id or "default").strip().upper() or "DEFAULT"
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
    raise ValueError(
        "Unsupported RAG advisory variant "
        f"{variant_id!r}; expected default, current, previous, V3, V7, or V12"
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
