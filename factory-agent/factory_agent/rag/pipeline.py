from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from factory_agent.rag.context_building import (
    RAGContextBuilder,
    normalize_compression,
    normalize_context_builder,
    rewrite_query_for_retrieval,
)
from factory_agent.rag.generation import AnswerGenerator
from factory_agent.rag.reranking import LLMReranker
from factory_agent.rag.retrieval import HybridRetriever
from factory_agent.rag.schemas import AnswerResult, Chunk, ScoredChunk
from factory_agent.rag.source_metadata import is_insufficient_context_answer
from factory_agent.observability.telemetry import log_event


@dataclass(frozen=True)
class RAGPipelineConfig:
    """Runtime knobs for retrieval/rerank behavior.

    Defaults preserve the existing production behavior. The RAG eval harness
    passes explicit configs to isolate Run 1 variants.
    """

    retrieval_mode: str = "hybrid"
    use_rerank: bool = True
    expand_neighbors: bool = True
    vector_top_k: int = 8
    keyword_top_k: int = 8
    fusion_top_k: int = 8
    rerank_top_k: int | None = None
    allow_rerank_fallback: bool = False
    query_rewrite: bool = False
    context_builder: str = "none"
    compression: str = "none"
    document_augmentation: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "context_builder", normalize_context_builder(self.context_builder))
        object.__setattr__(self, "compression", normalize_compression(self.compression))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RAGPipeline:
    """Async wrapper that composes retrieval -> rerank -> generation."""

    def __init__(
        self,
        retriever: HybridRetriever | None = None,
        reranker: LLMReranker | None = None,
        generator: AnswerGenerator | None = None,
    ) -> None:
        self._retriever = retriever or HybridRetriever()
        self._reranker = reranker or LLMReranker()
        self._generator = generator or AnswerGenerator()

    async def run(
        self,
        *,
        query: str,
        session_id: str | None = None,
        route: str = "RAG_ONLY",
        api_data: dict[str, Any] | None = None,
        config: RAGPipelineConfig | None = None,
    ) -> AnswerResult:
        config = config or RAGPipelineConfig()
        log_event(
            "rag_pipeline_start",
            session_id=session_id,
            query=query,
            route=route,
            retrieval_mode=config.retrieval_mode,
            use_rerank=config.use_rerank,
            query_rewrite=config.query_rewrite,
            context_builder=config.context_builder,
            compression=config.compression,
        )
        result = await asyncio.to_thread(
            self._run_sync,
            query=query,
            route=route,
            api_data=api_data,
            session_id=session_id,
            config=config,
        )
        log_event(
            "rag_pipeline_complete",
            session_id=session_id,
            success=not is_insufficient_context_answer(result.answer),
            chunk_count=len(result.sources)
        )
        return result

    def _run_sync(
        self,
        *,
        query: str,
        route: str,
        api_data: dict[str, Any] | None,
        session_id: str | None = None,
        config: RAGPipelineConfig | None = None,
    ) -> AnswerResult:
        config = config or RAGPipelineConfig()
        retrieval_query = rewrite_query_for_retrieval(query) if config.query_rewrite else query

        # 1. Retrieval
        candidates = self._retriever.retrieve(
            query=retrieval_query,
            route=route,
            vector_top_k=config.vector_top_k,
            keyword_top_k=config.keyword_top_k,
            fusion_top_k=config.fusion_top_k,
            expand_neighbors=config.expand_neighbors,
            retrieval_mode=config.retrieval_mode,
        )
        log_event(
            "rag_retrieval_complete",
            session_id=session_id,
            candidate_count=len(candidates),
            retrieval_mode=config.retrieval_mode,
            expand_neighbors=config.expand_neighbors,
            query_rewrite=config.query_rewrite,
        )

        # 2. Reranking
        if config.use_rerank:
            selected_chunks = self._reranker.rerank(
                query=query,
                candidates=candidates,
                route=route,
                top_k=config.rerank_top_k,
                allow_fallback=config.allow_rerank_fallback,
            )
            rerank_trace = dict(getattr(self._reranker, "last_trace", {}) or {})
        else:
            selected_chunks = _chunks_from_candidates(candidates, top_k=config.rerank_top_k)
            rerank_trace = {
                "enabled": False,
                "attempted": False,
                "succeeded": False,
                "fallback_used": False,
                "fallback_allowed": config.allow_rerank_fallback,
                "candidate_count": len(candidates),
                "selected_count": len(selected_chunks),
                "input_chunk_ids": [sc.chunk.chunk_id for sc in candidates],
                "output_chunk_ids": [chunk.chunk_id for chunk in selected_chunks],
            }
        log_event(
            "rag_rerank_complete",
            session_id=session_id,
            selected_count=len(selected_chunks),
            use_rerank=config.use_rerank,
            rerank_succeeded=rerank_trace.get("succeeded"),
            rerank_fallback_used=rerank_trace.get("fallback_used"),
        )

        # 3. Context building
        context_result = RAGContextBuilder(self._retriever).build(
            query=retrieval_query,
            selected_chunks=selected_chunks,
            candidates=candidates,
            context_builder=config.context_builder,
            compression=config.compression,
        )
        log_event(
            "rag_context_build_complete",
            session_id=session_id,
            context_builder=config.context_builder,
            compression=config.compression,
            segment_count=len(context_result.chunks),
            compression_ran=context_result.metadata.get("compression_ran"),
        )

        # 4. Generation
        result = self._generator.generate(
            query=query,
            chunks=context_result.chunks,
            api_data=api_data,
            route=route,
        )
        result.metadata = {
            **(result.metadata or {}),
            "query_rewrite": {
                "enabled": config.query_rewrite,
                "original_query": query,
                "retrieval_query": retrieval_query,
            },
            "rerank": rerank_trace,
            "context_building": context_result.metadata,
            "document_augmentation": {
                "enabled": config.document_augmentation,
                "retriever_db_path": getattr(self._retriever, "db_path", None),
                "retriever_bm25_path": getattr(self._retriever, "bm25_path", None),
                "retriever_document_augmentation": bool(
                    getattr(self._retriever, "document_augmentation", False)
                ),
            },
        }
        return result


def _chunks_from_candidates(candidates: list[ScoredChunk], *, top_k: int | None = None) -> list[Chunk]:
    chunks = [sc.chunk for sc in candidates]
    if top_k is None:
        return chunks
    return chunks[:top_k]
