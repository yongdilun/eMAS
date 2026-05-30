"""RAG evaluation variant registry.

The registry is intentionally eval-scoped. It translates named benchmark
variants into :class:`factory_agent.rag.pipeline.RAGPipelineConfig` without
changing default production RAG behavior.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORY_AGENT_DIR = REPO_ROOT / "factory-agent"
if str(FACTORY_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_AGENT_DIR))

from factory_agent.rag.document_augmentation import (  # noqa: E402
    AUGMENTED_BM25_PATH,
    AUGMENTED_VECTOR_DB_PATH,
    DEFAULT_BM25_PATH,
    DEFAULT_VECTOR_DB_PATH,
)
from factory_agent.rag.context_building import BudgetedRSESettings  # noqa: E402
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
    "V8",
    "V9",
    "V10",
    "V11",
    "V12",
    "V13",
    "V14",
    "V15",
    "V15A",
    "V15B",
    "V15C",
)

V14_BUDGETED_RSE_SETTINGS = {
    **asdict(BudgetedRSESettings()),
    "max_segment_tokens": 1500,
    "max_context_tokens": 3200,
    "max_neighbor_window": 2,
}
V15_BUDGETED_RSE_SETTINGS = {
    **V14_BUDGETED_RSE_SETTINGS,
    "use_evidence_cards": True,
    "max_evidence_cards": 8,
    "max_card_tokens": 180,
    "evidence_card_token_budget": 2200,
}
V15A_BUDGETED_RSE_SETTINGS = {
    **V14_BUDGETED_RSE_SETTINGS,
    "use_evidence_cards": False,
}
V15B_BUDGETED_RSE_SETTINGS = {
    **V14_BUDGETED_RSE_SETTINGS,
    "use_evidence_cards": True,
    "evidence_card_context_mode": "metadata_only",
    "max_evidence_cards": 8,
    "max_card_tokens": 180,
    "evidence_card_token_budget": 2200,
}
V15C_BUDGETED_RSE_SETTINGS = {
    **V15B_BUDGETED_RSE_SETTINGS,
    "evidence_card_context_mode": "mode_aware",
}


@dataclass(frozen=True)
class RAGVariantConfig:
    variant_id: str
    name: str
    retrieval_mode: str
    use_rerank: bool
    expand_neighbors: bool
    query_rewrite: bool = False
    corpus_aware_query_rewrite: bool = False
    multi_query_retrieval: bool = False
    context_builder: str = "none"
    compression: str = "none"
    document_augmentation: bool = False
    vector_top_k: int = 10
    keyword_top_k: int = 10
    fusion_top_k: int = 10
    rerank_top_k: int | None = None
    allow_rerank_fallback: bool = False
    phase2_status: str = "executable"
    notes: str = ""
    context_builder_settings: dict[str, Any] = field(default_factory=dict)

    @property
    def phase2_executable(self) -> bool:
        return self.phase2_status == "executable"

    def to_pipeline_config(self) -> RAGPipelineConfig:
        return RAGPipelineConfig(
            variant_id=self.variant_id,
            operating_mode="eval",
            retrieval_mode=self.retrieval_mode,
            use_rerank=self.use_rerank,
            expand_neighbors=self.expand_neighbors,
            vector_top_k=self.vector_top_k,
            keyword_top_k=self.keyword_top_k,
            fusion_top_k=self.fusion_top_k,
            rerank_top_k=self.rerank_top_k,
            allow_rerank_fallback=self.allow_rerank_fallback,
            query_rewrite=self.query_rewrite,
            corpus_aware_query_rewrite=self.corpus_aware_query_rewrite,
            multi_query_retrieval=self.multi_query_retrieval,
            context_builder=self.context_builder,
            compression=self.compression,
            document_augmentation=self.document_augmentation,
            context_builder_settings=self.context_builder_settings,
        )

    def index_paths(self) -> dict[str, str]:
        if self.document_augmentation:
            return {
                "vector_db_path": AUGMENTED_VECTOR_DB_PATH,
                "bm25_path": AUGMENTED_BM25_PATH,
            }
        return {
            "vector_db_path": DEFAULT_VECTOR_DB_PATH,
            "bm25_path": DEFAULT_BM25_PATH,
        }

    def retrieval_settings(self) -> dict[str, Any]:
        config = self.to_pipeline_config()
        return {
            "retrieval_mode": config.retrieval_mode,
            "vector_top_k": config.vector_top_k,
            "keyword_top_k": config.keyword_top_k,
            "fusion_top_k": config.fusion_top_k,
            "expand_neighbors": config.expand_neighbors,
            "query_rewrite": config.query_rewrite,
            "corpus_aware_query_rewrite": config.corpus_aware_query_rewrite,
            "multi_query_retrieval": config.multi_query_retrieval,
            "context_builder": config.context_builder,
            "compression": config.compression,
            "allow_rerank_fallback": config.allow_rerank_fallback,
            "document_augmentation": config.document_augmentation,
            "context_builder_settings": config.context_builder_settings,
            "index_paths": self.index_paths(),
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
    "V8": RAGVariantConfig(
        variant_id="V8",
        name="Document Augmentation + Hybrid Search + Small-to-Big + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        context_builder="small_to_big",
        document_augmentation=True,
        notes="Document-augmented retrieval index, chunk rerank, and Small-to-Big expansion.",
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
    "V13": RAGVariantConfig(
        variant_id="V13",
        name="Document Augmentation + Hybrid Search + RSE + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        context_builder="rse",
        document_augmentation=True,
        notes="Document-augmented retrieval index, chunk rerank, and RSE segment building.",
    ),
    "V14": RAGVariantConfig(
        variant_id="V14",
        name="Query Rewrite + Hybrid Search + Budgeted Evidence-Aware RSE + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        query_rewrite=True,
        context_builder="budgeted_rse",
        context_builder_settings={"budgeted_rse": V14_BUDGETED_RSE_SETTINGS},
        notes=(
            "Deterministic retrieval query rewrite, chunk rerank, and budgeted evidence-aware "
            "RSE with per-segment and global context budgets."
        ),
    ),
    "V15": RAGVariantConfig(
        variant_id="V15",
        name="Corpus-Aware Multi-Query Rewrite + Evidence Cards + Budgeted RSE + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        query_rewrite=False,
        corpus_aware_query_rewrite=True,
        multi_query_retrieval=True,
        context_builder="budgeted_rse",
        context_builder_settings={"budgeted_rse": V15_BUDGETED_RSE_SETTINGS},
        notes=(
            "Corpus-derived retrieval vocabulary, separate original and expanded retrieval, "
            "chunk rerank, compact evidence cards, and budgeted evidence-aware RSE."
        ),
    ),
    "V15A": RAGVariantConfig(
        variant_id="V15A",
        name="Corpus-Aware Multi-Query Rewrite + Budgeted RSE + Rerank",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        query_rewrite=False,
        corpus_aware_query_rewrite=True,
        multi_query_retrieval=True,
        context_builder="budgeted_rse",
        context_builder_settings={"budgeted_rse": V15A_BUDGETED_RSE_SETTINGS},
        notes=(
            "V14 budgeted RSE with corpus-aware multi-query retrieval and no legacy named-standard "
            "rewrite or evidence-card context replacement."
        ),
    ),
    "V15B": RAGVariantConfig(
        variant_id="V15B",
        name="V15A + Evidence Cards As Metadata",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        query_rewrite=False,
        corpus_aware_query_rewrite=True,
        multi_query_retrieval=True,
        context_builder="budgeted_rse",
        context_builder_settings={"budgeted_rse": V15B_BUDGETED_RSE_SETTINGS},
        notes=(
            "V15A with evidence-card citation, facet, and debug metadata only; generation remains "
            "on budgeted RSE context."
        ),
    ),
    "V15C": RAGVariantConfig(
        variant_id="V15C",
        name="V15B + Mode-Aware Evidence Card Context",
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        query_rewrite=False,
        corpus_aware_query_rewrite=True,
        multi_query_retrieval=True,
        context_builder="budgeted_rse",
        context_builder_settings={"budgeted_rse": V15C_BUDGETED_RSE_SETTINGS},
        notes=(
            "V15B with compact evidence-card context for direct/procedure answers and broader "
            "RSE context for summaries, relationships, comparisons, and checklist reviews."
        ),
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
