from __future__ import annotations

import asyncio
from typing import Any

from factory_agent.rag.generation import AnswerGenerator
from factory_agent.rag.reranking import LLMReranker
from factory_agent.rag.retrieval import HybridRetriever
from factory_agent.rag.schemas import AnswerResult


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
        del session_id  # Reserved for tracing / future contextual retrieval.
        return await asyncio.to_thread(
            self._run_sync,
            query=query,
            route=route,
            api_data=api_data,
        )

    def _run_sync(
        self,
        *,
        query: str,
        route: str,
        api_data: dict[str, Any] | None,
    ) -> AnswerResult:
        candidates = self._retriever.retrieve(query=query, route=route)
        selected_chunks = self._reranker.rerank(query=query, candidates=candidates, route=route)
        return self._generator.generate(
            query=query,
            chunks=selected_chunks,
            api_data=api_data,
            route=route,
        )
