from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from factory_agent.rag.context_building import (
    BudgetedRSESettings,
    RAGContextBuilder,
    normalize_compression,
    normalize_context_builder,
    rewrite_query_for_retrieval,
)
from factory_agent.rag.generation import AnswerGenerator
from factory_agent.rag.query_rewriting import build_corpus_aware_query_rewrite_for_retriever
from factory_agent.rag.reranking import LLMReranker
from factory_agent.rag.retrieval import HybridRetriever
from factory_agent.rag.schemas import AnswerResult, Chunk, ScoredChunk
from factory_agent.rag.source_metadata import is_insufficient_context_answer
from factory_agent.observability.telemetry import log_event


@dataclass(frozen=True)
class MultiQueryFusionSettings:
    original_query_weight: float = 1.0
    expanded_query_weight: float = 0.92
    rrf_constant: float = 60.0


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
    corpus_aware_query_rewrite: bool = False
    multi_query_retrieval: bool = False
    source_register_path: str | None = None
    context_builder: str = "none"
    compression: str = "none"
    document_augmentation: bool = False
    context_builder_settings: dict[str, Any] = field(default_factory=dict)
    multi_query_fusion_settings: dict[str, Any] = field(default_factory=dict)

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
        candidates, query_plan = retrieve_candidates_for_config(
            self._retriever,
            query=query,
            route=route,
            config=config,
        )
        retrieval_query = str(query_plan.get("retrieval_query") or query)
        log_event(
            "rag_query_rewrite_complete",
            session_id=session_id,
            rag_variant=config.variant_id,
            mode=query_plan.get("mode"),
            enabled=query_plan.get("enabled"),
            original_query=query_plan.get("original_query"),
            normalized_query=query_plan.get("normalized_query"),
            retrieval_query=retrieval_query,
            expansion_terms=query_plan.get("expansion_terms"),
            expansion_sources=query_plan.get("expansion_sources"),
            confidence=query_plan.get("confidence"),
            retrieval_queries=query_plan.get("retrieval_queries"),
        )

        # 1. Retrieval
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
        context_result = RAGContextBuilder(
            self._retriever,
            budgeted_rse_settings=_budgeted_rse_settings_from_config(config),
        ).build(
            query=query if config.corpus_aware_query_rewrite else retrieval_query,
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
                **query_plan,
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


def build_retrieval_query_plan(
    *,
    query: str,
    config: RAGPipelineConfig,
    retriever: HybridRetriever | Any | None = None,
) -> dict[str, Any]:
    if config.corpus_aware_query_rewrite:
        rewrite = build_corpus_aware_query_rewrite_for_retriever(
            query,
            retriever,
            source_register_path=config.source_register_path,
        )
        retrieval_queries = [rewrite.normalized_query]
        if rewrite.expanded_query and rewrite.expanded_query != rewrite.normalized_query:
            retrieval_queries.append(rewrite.expanded_query)
        return {
            "enabled": True,
            "mode": rewrite.mode,
            "original_query": rewrite.original_query,
            "normalized_query": rewrite.normalized_query,
            "retrieval_query": rewrite.expanded_query,
            "expanded_query": rewrite.expanded_query,
            "expansion_terms": rewrite.expansion_terms,
            "expansion_sources": rewrite.expansion_sources,
            "confidence": rewrite.confidence,
            "multi_query_retrieval": config.multi_query_retrieval,
            "retrieval_queries": retrieval_queries if config.multi_query_retrieval else [rewrite.expanded_query],
        }

    retrieval_query = rewrite_query_for_retrieval(query) if config.query_rewrite else query
    return {
        "enabled": config.query_rewrite,
        "mode": "deterministic" if config.query_rewrite else "none",
        "original_query": query,
        "normalized_query": query,
        "retrieval_query": retrieval_query,
        "expanded_query": retrieval_query,
        "expansion_terms": [],
        "expansion_sources": [],
        "confidence": 0.0,
        "multi_query_retrieval": False,
        "retrieval_queries": [retrieval_query],
    }


def retrieve_candidates_for_config(
    retriever: HybridRetriever | Any,
    *,
    query: str,
    route: str,
    config: RAGPipelineConfig,
) -> tuple[list[ScoredChunk], dict[str, Any]]:
    query_plan = build_retrieval_query_plan(query=query, config=config, retriever=retriever)
    retrieval_queries = list(query_plan.get("retrieval_queries") or [query_plan.get("retrieval_query") or query])
    if not config.multi_query_retrieval:
        retrieval_queries = [str(query_plan.get("retrieval_query") or query)]

    result_sets: list[list[ScoredChunk]] = []
    for retrieval_query in retrieval_queries:
        if not retrieval_query:
            continue
        result_sets.append(
            retriever.retrieve(
                query=retrieval_query,
                route=route,
                vector_top_k=config.vector_top_k,
                keyword_top_k=config.keyword_top_k,
                fusion_top_k=config.fusion_top_k,
                expand_neighbors=config.expand_neighbors,
                retrieval_mode=config.retrieval_mode,
            )
        )

    if len(result_sets) <= 1:
        return (result_sets[0] if result_sets else []), query_plan
    return (
        _fuse_multi_query_results(
            result_sets,
            top_k=config.fusion_top_k,
            settings=_multi_query_fusion_settings_from_config(config),
        ),
        query_plan,
    )


def _fuse_multi_query_results(
    result_sets: list[list[ScoredChunk]],
    *,
    top_k: int,
    settings: MultiQueryFusionSettings,
) -> list[ScoredChunk]:
    scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    vector_scores: dict[str, float] = {}
    keyword_scores: dict[str, float] = {}
    boosted_scores: dict[str, float] = {}
    for result_index, results in enumerate(result_sets):
        query_weight = settings.original_query_weight if result_index == 0 else settings.expanded_query_weight
        for rank, item in enumerate(results, start=1):
            chunk_id = item.chunk.chunk_id
            chunks[chunk_id] = item.chunk
            scores[chunk_id] = scores.get(chunk_id, 0.0) + (query_weight / (settings.rrf_constant + rank))
            if item.vector_score is not None:
                vector_scores[chunk_id] = max(vector_scores.get(chunk_id, 0.0), float(item.vector_score))
            if item.keyword_score is not None:
                keyword_scores[chunk_id] = max(keyword_scores.get(chunk_id, 0.0), float(item.keyword_score))
            if item.boosted_score is not None:
                boosted_scores[chunk_id] = max(boosted_scores.get(chunk_id, 0.0), float(item.boosted_score))

    ordered_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return [
        ScoredChunk(
            chunk=chunks[chunk_id],
            vector_score=vector_scores.get(chunk_id),
            keyword_score=keyword_scores.get(chunk_id),
            fusion_score=scores[chunk_id],
            boosted_score=boosted_scores.get(chunk_id, scores[chunk_id]),
        )
        for chunk_id in ordered_ids
    ]


def _budgeted_rse_settings_from_config(config: RAGPipelineConfig) -> BudgetedRSESettings:
    raw_settings = dict(config.context_builder_settings or {})
    nested = raw_settings.get("budgeted_rse")
    if isinstance(nested, dict):
        raw_settings = dict(nested)
    allowed = {item.name for item in fields(BudgetedRSESettings)}
    return BudgetedRSESettings(**{key: value for key, value in raw_settings.items() if key in allowed})


def _multi_query_fusion_settings_from_config(config: RAGPipelineConfig) -> MultiQueryFusionSettings:
    raw_settings = dict(config.multi_query_fusion_settings or {})
    allowed = {item.name for item in fields(MultiQueryFusionSettings)}
    return MultiQueryFusionSettings(**{key: value for key, value in raw_settings.items() if key in allowed})


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
