from __future__ import annotations

import asyncio
from typing import Any

from factory_agent.rag.generation import AnswerGenerator
from factory_agent.rag.reranking import LLMReranker
from factory_agent.rag.retrieval import HybridRetriever
from factory_agent.rag.schemas import AnswerResult
from factory_agent.rag.source_metadata import is_insufficient_context_answer
from factory_agent.observability.telemetry import log_event


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
    ) -> AnswerResult:
        log_event(
            "rag_pipeline_start",
            session_id=session_id,
            query=query,
            route=route
        )
        result = await asyncio.to_thread(
            self._run_sync,
            query=query,
            route=route,
            api_data=api_data,
            session_id=session_id
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
    ) -> AnswerResult:
        # 1. Retrieval
        candidates = self._retriever.retrieve(query=query, route=route)
        log_event(
            "rag_retrieval_complete",
            session_id=session_id,
            candidate_count=len(candidates)
        )
        
        # 2. Reranking
        selected_chunks = self._reranker.rerank(query=query, candidates=candidates, route=route)
        log_event(
            "rag_rerank_complete",
            session_id=session_id,
            selected_count=len(selected_chunks)
        )
        
        # 3. Generation
        return self._generator.generate(
            query=query,
            chunks=selected_chunks,
            api_data=api_data,
            route=route,
        )
