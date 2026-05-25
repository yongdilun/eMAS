from __future__ import annotations

import asyncio
import time
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

    variant_id: str = "default"
    operating_mode: str = "advisory"
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
        started = time.perf_counter()
        log_event(
            "rag_pipeline_start",
            session_id=session_id,
            query=query,
            route=route,
            rag_variant=config.variant_id,
            operating_mode=config.operating_mode,
            rag_config=config.to_dict(),
            retrieval_mode=config.retrieval_mode,
            use_rerank=config.use_rerank,
            query_rewrite=config.query_rewrite,
            context_builder=config.context_builder,
            compression=config.compression,
            document_augmentation=config.document_augmentation,
        )
        try:
            result = await asyncio.to_thread(
                self._run_sync,
                query=query,
                route=route,
                api_data=api_data,
                session_id=session_id,
                config=config,
            )
        except Exception as exc:
            latency_ms = int(round((time.perf_counter() - started) * 1000.0))
            rerank_trace = dict(getattr(self._reranker, "last_trace", {}) or {})
            log_event(
                "rag_pipeline_failed",
                level="WARNING",
                session_id=session_id,
                route=route,
                rag_variant=config.variant_id,
                operating_mode=config.operating_mode,
                rag_config=config.to_dict(),
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
                rerank_attempted=rerank_trace.get("attempted"),
                rerank_succeeded=rerank_trace.get("succeeded"),
                rerank_fallback_used=rerank_trace.get("fallback_used"),
            )
            raise
        latency_ms = int(round((time.perf_counter() - started) * 1000.0))
        result.metadata = {
            **(result.metadata or {}),
            "runtime": {
                **((result.metadata or {}).get("runtime") or {}),
                "latency_ms": latency_ms,
            },
        }
        no_evidence_fallback = is_insufficient_context_answer(result.answer)
        boundary_refusal = _is_boundary_refusal_result(result)
        citation_details = _citation_details(result.sources)
        context_token_estimate = _context_token_estimate(result.metadata)
        log_event(
            "rag_pipeline_complete",
            session_id=session_id,
            route=route,
            rag_variant=config.variant_id,
            operating_mode=config.operating_mode,
            retrieval_mode=config.retrieval_mode,
            context_builder=config.context_builder,
            compression=config.compression,
            document_augmentation=config.document_augmentation,
            latency_ms=latency_ms,
            success=not no_evidence_fallback,
            no_evidence_fallback=no_evidence_fallback,
            boundary_refusal=boundary_refusal,
            citation_count=len(result.sources),
            citation_source_ids=[item.get("source_id") for item in citation_details],
            citation_doc_ids=[item.get("doc_id") for item in citation_details],
            citation_pages=[item.get("page") for item in citation_details if item.get("page") is not None],
            citation_details=citation_details,
            context_token_estimate=context_token_estimate,
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
            rag_variant=config.variant_id,
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
            rag_variant=config.variant_id,
            selected_count=len(selected_chunks),
            use_rerank=config.use_rerank,
            rerank_attempted=rerank_trace.get("attempted"),
            rerank_succeeded=rerank_trace.get("succeeded"),
            rerank_fallback_used=rerank_trace.get("fallback_used"),
            rerank_fallback_allowed=rerank_trace.get("fallback_allowed"),
            rerank_backend=rerank_trace.get("backend"),
            rerank_duration_s=rerank_trace.get("duration_s"),
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
            rag_variant=config.variant_id,
            context_builder=config.context_builder,
            compression=config.compression,
            segment_count=len(context_result.chunks),
            compression_ran=context_result.metadata.get("compression_ran"),
            token_estimates=context_result.metadata.get("token_estimates"),
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
            "runtime_config": config.to_dict(),
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


def _citation_details(sources: list[Any]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for source in sources or []:
        data = source.model_dump() if hasattr(source, "model_dump") else dict(source or {})
        details.append(
            {
                "source_id": data.get("source_id"),
                "doc_id": data.get("doc_id"),
                "chunk_id": data.get("chunk_id"),
                "page": data.get("page"),
                "page_start": data.get("page_start"),
                "page_end": data.get("page_end"),
                "supporting_pages": data.get("supporting_pages"),
                "section_title": data.get("section_title"),
                "section_path": data.get("section_path"),
            }
        )
    return details


def _context_token_estimate(metadata: dict[str, Any]) -> int | None:
    context = metadata.get("context_building") if isinstance(metadata, dict) else None
    if not isinstance(context, dict):
        return None
    estimates = context.get("token_estimates")
    if not isinstance(estimates, dict):
        return None
    value = estimates.get("after_compression") or estimates.get("after_expansion")
    return int(value) if isinstance(value, int) else None


def _is_boundary_refusal_result(result: AnswerResult) -> bool:
    metadata = result.metadata or {}
    generation = metadata.get("generation_validation") if isinstance(metadata, dict) else None
    if isinstance(generation, dict) and generation.get("initial_reason") == "certification_boundary_enforced":
        return True
    answer = (result.answer or "").lower()
    return (
        "cannot certify" in answer
        or "cannot certify, attest, approve" in answer
        or "do not start, operate, energize, or reenergize" in answer
    )
