"""Run 1 RAG evaluation variant registry.

The registry is intentionally eval-scoped. It translates named benchmark
variants into :class:`factory_agent.rag.pipeline.RAGPipelineConfig` without
changing default production RAG behavior.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORY_AGENT_DIR = REPO_ROOT / "factory-agent"
if str(FACTORY_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_AGENT_DIR))

from factory_agent.rag.pipeline import RAGPipelineConfig  # noqa: E402

DEFAULT_VARIANT_ID = "V3"
RUN_1_VARIANT_IDS = (
    "V0",
    "V1",
    "V2",
    "V3",
    "V4",
    "V5",
    "V6",
    "V7",
    "V9",
    "V10",
    "V11",
    "V12",
)


@dataclass(frozen=True)
class RAGVariantConfig:
    variant_id: str
    name: str
    retrieval_mode: str
    use_rerank: bool
    expand_neighbors: bool
    query_rewrite: bool = False
    context_builder: str = "none"
    compression: str = "none"
    vector_top_k: int = 10
    keyword_top_k: int = 10
    fusion_top_k: int = 10
    rerank_top_k: int | None = None
    phase2_status: str = "executable"
    notes: str = ""

    @property
    def phase2_executable(self) -> bool:
        return self.phase2_status == "executable"

    def to_pipeline_config(self) -> RAGPipelineConfig:
        return RAGPipelineConfig(
            retrieval_mode=self.retrieval_mode,
            use_rerank=self.use_rerank,
            expand_neighbors=self.expand_neighbors,
            vector_top_k=self.vector_top_k,
            keyword_top_k=self.keyword_top_k,
            fusion_top_k=self.fusion_top_k,
            rerank_top_k=self.rerank_top_k,
            query_rewrite=self.query_rewrite,
            context_builder=self.context_builder,
            compression=self.compression,
        )

    def retrieval_settings(self) -> dict[str, Any]:
        config = self.to_pipeline_config()
        return {
            "retrieval_mode": config.retrieval_mode,
            "vector_top_k": config.vector_top_k,
            "keyword_top_k": config.keyword_top_k,
            "fusion_top_k": config.fusion_top_k,
            "expand_neighbors": config.expand_neighbors,
            "query_rewrite": config.query_rewrite,
            "context_builder": config.context_builder,
            "compression": config.compression,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pipeline_config"] = self.to_pipeline_config().to_dict()
        payload["retrieval_settings"] = self.retrieval_settings()
        return payload


RUN_1_VARIANTS: dict[str, RAGVariantConfig] = {
    "V0": RAGVariantConfig(
        variant_id="V0",
        name="Basic Vector RAG",
        retrieval_mode="vector",
        use_rerank=False,
        expand_neighbors=False,
        notes="Vector retrieval only; BM25, rerank, expansion, and compression disabled.",
    ),
    "V1": RAGVariantConfig(
        variant_id="V1",
        name="Vector + Rerank",
        retrieval_mode="vector",
        use_rerank=True,
        expand_neighbors=False,
        notes="Vector retrieval followed by reranking; BM25 and expansion disabled.",
    ),
    "V2": RAGVariantConfig(
        variant_id="V2",
        name="Hybrid Search",
        retrieval_mode="hybrid",
        use_rerank=False,
        expand_neighbors=False,
        notes="Vector + BM25 hybrid retrieval; rerank and expansion disabled.",
    ),
    "V3": RAGVariantConfig(
        variant_id="V3",
        name="Hybrid Search + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        notes="Vector + BM25 hybrid retrieval followed by reranking; expansion disabled.",
    ),
    "V4": RAGVariantConfig(
        variant_id="V4",
        name="Hybrid Search + Small-to-Big",
        retrieval_mode="hybrid",
        use_rerank=False,
        expand_neighbors=False,
        context_builder="small_to_big",
        notes="Small-to-Big expands selected chunks to parent sections.",
    ),
    "V5": RAGVariantConfig(
        variant_id="V5",
        name="Hybrid Search + Small-to-Big + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        context_builder="small_to_big",
        notes="Chunk rerank followed by Small-to-Big parent section expansion.",
    ),
    "V6": RAGVariantConfig(
        variant_id="V6",
        name="Hybrid Search + Small-to-Big + Rerank + Light Compression",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        context_builder="small_to_big",
        compression="light_extractive",
        notes="Small-to-Big parent section expansion followed by extractive compression.",
    ),
    "V7": RAGVariantConfig(
        variant_id="V7",
        name="Query Rewrite + Hybrid Search + Small-to-Big + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        query_rewrite=True,
        context_builder="small_to_big",
        notes="Deterministic retrieval query rewrite, chunk rerank, and Small-to-Big expansion.",
    ),
    "V9": RAGVariantConfig(
        variant_id="V9",
        name="Hybrid Search + RSE",
        retrieval_mode="hybrid",
        use_rerank=False,
        expand_neighbors=False,
        context_builder="rse",
        notes="RSE joins same-doc, same-section nearby chunks after retrieval.",
    ),
    "V10": RAGVariantConfig(
        variant_id="V10",
        name="Hybrid Search + RSE + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        context_builder="rse",
        notes="Chunk rerank followed by RSE segment building.",
    ),
    "V11": RAGVariantConfig(
        variant_id="V11",
        name="Hybrid Search + RSE + Rerank + Light Compression",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        context_builder="rse",
        compression="light_extractive",
        notes="Chunk rerank, RSE segment building, and extractive compression.",
    ),
    "V12": RAGVariantConfig(
        variant_id="V12",
        name="Query Rewrite + Hybrid Search + RSE + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        query_rewrite=True,
        context_builder="rse",
        notes="Deterministic retrieval query rewrite, chunk rerank, and RSE segment building.",
    ),
}


def get_variant(variant_id: str | None) -> RAGVariantConfig:
    resolved = (variant_id or DEFAULT_VARIANT_ID).upper()
    try:
        return RUN_1_VARIANTS[resolved]
    except KeyError as exc:
        valid = ", ".join(RUN_1_VARIANT_IDS)
        raise ValueError(f"Unknown RAG eval variant {variant_id!r}; expected one of: {valid}") from exc


def require_phase2_executable(variant: RAGVariantConfig) -> None:
    if variant.phase2_executable:
        return
    raise NotImplementedError(
        f"{variant.variant_id} is registered for Run 1 but is not executable in the current phase "
        f"({variant.name}). {variant.notes}"
    )
