import asyncio

import pytest

import factory_agent.rag.pipeline as pipeline_module
from factory_agent.rag.pipeline import RAGPipeline, RAGPipelineConfig, build_retrieval_query_plan
from factory_agent.rag.schemas import AnswerResult, Chunk, ScoredChunk
from tests.rag_eval.variants import get_variant


class FakeRetriever:
    def __init__(self) -> None:
        self.calls = []
        self.chunks = [
            Chunk(
                chunk_id="doc_c0001",
                text="[Section: Main] alpha",
                metadata={
                    "doc_id": "doc",
                    "chunk_index": 1,
                    "section_title": "Main",
                    "section_path": "Doc > Main",
                    "title": "Alpha Source",
                    "use_for": ["explain alpha bravo"],
                },
            ),
            Chunk(
                chunk_id="doc_c0002",
                text="[Section: Main] bravo",
                metadata={
                    "doc_id": "doc",
                    "chunk_index": 2,
                    "section_title": "Main",
                    "section_path": "Doc > Main",
                    "title": "Alpha Source",
                    "use_for": ["explain alpha bravo"],
                },
            ),
        ]
        self.bm25_chunks = list(self.chunks)

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        if "expanded vocabulary" in str(kwargs.get("query") or ""):
            return [
                ScoredChunk(chunk=self.chunks[1], vector_score=0.95, fusion_score=0.95),
                ScoredChunk(chunk=self.chunks[0], vector_score=0.75, fusion_score=0.75),
            ]
        return [
            ScoredChunk(chunk=self.chunks[0], vector_score=0.9, fusion_score=0.9),
            ScoredChunk(chunk=self.chunks[1], vector_score=0.8, fusion_score=0.8),
        ]

    def get_chunks_for_doc(self, doc_id):
        return list(self.chunks)


class FakeReranker:
    def __init__(self) -> None:
        self.calls = []

    def rerank(self, **kwargs):
        self.calls.append(kwargs)
        return [kwargs["candidates"][1].chunk]


class FailingReranker:
    def __init__(self) -> None:
        self.last_trace = {
            "enabled": True,
            "attempted": True,
            "succeeded": False,
            "fallback_used": False,
            "fallback_allowed": False,
            "error": "forced failure",
        }

    def rerank(self, **kwargs):
        if kwargs.get("allow_fallback"):
            self.last_trace = {
                "enabled": True,
                "attempted": True,
                "succeeded": False,
                "fallback_used": True,
                "fallback_allowed": True,
                "error": "forced failure",
                "candidate_count": len(kwargs["candidates"]),
                "selected_count": 1,
                "input_chunk_ids": [sc.chunk.chunk_id for sc in kwargs["candidates"]],
                "output_chunk_ids": [kwargs["candidates"][0].chunk.chunk_id],
            }
            return [kwargs["candidates"][0].chunk]
        raise RuntimeError("forced failure")


class FakeGenerator:
    def __init__(self) -> None:
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return AnswerResult(
            answer="ok",
            sources=[],
            safety_warning=False,
            route_used=kwargs["route"],
        )


def test_pipeline_config_can_skip_rerank_and_disable_neighbor_expansion():
    retriever = FakeRetriever()
    reranker = FakeReranker()
    generator = FakeGenerator()
    pipeline = RAGPipeline(retriever=retriever, reranker=reranker, generator=generator)

    config = RAGPipelineConfig(
        retrieval_mode="vector",
        use_rerank=False,
        expand_neighbors=False,
        vector_top_k=10,
        keyword_top_k=10,
        fusion_top_k=10,
    )

    result = asyncio.run(pipeline.run(query="query", route="RAG_ONLY", config=config))

    assert result.answer == "ok"
    assert retriever.calls == [
        {
            "query": "query",
            "route": "RAG_ONLY",
            "vector_top_k": 10,
            "keyword_top_k": 10,
            "fusion_top_k": 10,
            "expand_neighbors": False,
            "retrieval_mode": "vector",
        }
    ]
    assert reranker.calls == []
    assert [chunk.chunk_id for chunk in generator.calls[0]["chunks"]] == ["doc_c0001", "doc_c0002"]


def test_pipeline_config_uses_reranker_when_enabled():
    retriever = FakeRetriever()
    reranker = FakeReranker()
    generator = FakeGenerator()
    pipeline = RAGPipeline(retriever=retriever, reranker=reranker, generator=generator)

    config = RAGPipelineConfig(
        retrieval_mode="hybrid",
        use_rerank=True,
        expand_neighbors=False,
        rerank_top_k=1,
    )

    asyncio.run(pipeline.run(query="query", route="RAG_ONLY", config=config))

    assert len(reranker.calls) == 1
    assert reranker.calls[0]["top_k"] == 1
    assert reranker.calls[0]["allow_fallback"] is False
    assert [chunk.chunk_id for chunk in generator.calls[0]["chunks"]] == ["doc_c0002"]


def test_pipeline_applies_context_builder_before_generation():
    retriever = FakeRetriever()
    reranker = FakeReranker()
    generator = FakeGenerator()
    pipeline = RAGPipeline(retriever=retriever, reranker=reranker, generator=generator)

    config = RAGPipelineConfig(
        retrieval_mode="hybrid",
        use_rerank=False,
        expand_neighbors=False,
        context_builder="small_to_big",
    )

    result = asyncio.run(pipeline.run(query="alpha", route="RAG_ONLY", config=config))

    generated_chunks = generator.calls[0]["chunks"]
    assert len(generated_chunks) == 1
    assert generated_chunks[0].metadata["context_builder"] == "small_to_big"
    assert "alpha" in generated_chunks[0].text
    assert "bravo" in generated_chunks[0].text
    assert result.metadata["context_building"]["context_builder"] == "small_to_big"


def test_pipeline_config_rejects_combined_context_builders():
    with pytest.raises(ValueError, match="mutually exclusive"):
        RAGPipelineConfig(context_builder="small_to_big+rse")


def test_pipeline_config_does_not_silently_fallback_when_rerank_fails():
    retriever = FakeRetriever()
    generator = FakeGenerator()
    pipeline = RAGPipeline(retriever=retriever, reranker=FailingReranker(), generator=generator)

    config = RAGPipelineConfig(use_rerank=True, expand_neighbors=False)

    with pytest.raises(RuntimeError, match="forced failure"):
        asyncio.run(pipeline.run(query="query", route="RAG_ONLY", config=config))
    assert generator.calls == []


def test_pipeline_records_explicit_reranker_fallback_when_allowed():
    retriever = FakeRetriever()
    generator = FakeGenerator()
    pipeline = RAGPipeline(retriever=retriever, reranker=FailingReranker(), generator=generator)

    config = RAGPipelineConfig(
        use_rerank=True,
        expand_neighbors=False,
        allow_rerank_fallback=True,
    )

    result = asyncio.run(pipeline.run(query="query", route="RAG_ONLY", config=config))

    trace = result.metadata["rerank"]
    assert trace["fallback_used"] is True
    assert trace["fallback_allowed"] is True
    assert trace["attempted"] is True
    assert [chunk.chunk_id for chunk in generator.calls[0]["chunks"]] == ["doc_c0001"]


def test_pipeline_passes_budgeted_rse_settings_to_context_builder():
    retriever = FakeRetriever()
    reranker = FakeReranker()
    generator = FakeGenerator()
    pipeline = RAGPipeline(retriever=retriever, reranker=reranker, generator=generator)

    config = RAGPipelineConfig(
        retrieval_mode="hybrid",
        use_rerank=False,
        expand_neighbors=False,
        context_builder="budgeted_rse",
        context_builder_settings={"budgeted_rse": {"max_context_tokens": 28, "max_segment_tokens": 28}},
    )

    result = asyncio.run(pipeline.run(query="alpha bravo", route="RAG_ONLY", config=config))

    generated_chunks = generator.calls[0]["chunks"]
    assert generated_chunks[0].metadata["context_builder"] == "budgeted_rse"
    assert result.metadata["context_building"]["global_budget"]["max_context_tokens"] == 28


def test_pipeline_runs_corpus_expanded_retrieval_separately_and_keeps_generation_query_original():
    retriever = FakeRetriever()
    retriever.bm25_chunks = [
        Chunk(
            chunk_id="lexicon_c0001",
            text="Metadata carrier.",
            metadata={
                "doc_id": "lexicon",
                "title": "Expanded Vocabulary Source",
                "section_title": "Overview",
                "section_path": ["Expanded Vocabulary Source", "Overview"],
                "use_for": ["explain alpha expanded vocabulary"],
            },
        )
    ]
    reranker = FakeReranker()
    generator = FakeGenerator()
    pipeline = RAGPipeline(retriever=retriever, reranker=reranker, generator=generator)

    config = RAGPipelineConfig(
        retrieval_mode="hybrid",
        use_rerank=False,
        expand_neighbors=False,
        corpus_aware_query_rewrite=True,
        multi_query_retrieval=True,
    )

    result = asyncio.run(pipeline.run(query="alpha overview", route="RAG_ONLY", config=config))

    assert len(retriever.calls) == 2
    assert retriever.calls[0]["query"] == "alpha overview"
    assert "Corpus retrieval focus:" in retriever.calls[1]["query"]
    assert "expanded vocabulary" in retriever.calls[1]["query"].lower()
    assert generator.calls[0]["query"] == "alpha overview"
    assert result.metadata["query_rewrite"]["mode"] == "corpus_aware"
    assert result.metadata["query_rewrite"]["original_query"] == "alpha overview"
    assert result.metadata["query_rewrite"]["normalized_query"] == "alpha overview"
    assert result.metadata["query_rewrite"]["expansion_terms"]
    assert result.metadata["query_rewrite"]["expansion_sources"]
    assert result.metadata["query_rewrite"]["confidence"] > 0


def test_v15a_query_plan_uses_corpus_rewrite_without_legacy_named_table(monkeypatch):
    retriever = FakeRetriever()
    retriever.bm25_chunks = [
        Chunk(
            chunk_id="lexicon_c0001",
            text="Metadata carrier.",
            metadata={
                "doc_id": "lexicon",
                "title": "Expanded Vocabulary Source",
                "section_title": "Overview",
                "section_path": ["Expanded Vocabulary Source", "Overview"],
                "use_for": ["explain alpha expanded vocabulary"],
            },
        )
    ]

    def fail_legacy_rewrite(_query):
        raise AssertionError("legacy named-standard rewrite should not run")

    monkeypatch.setattr(pipeline_module, "rewrite_query_for_retrieval", fail_legacy_rewrite)

    config = get_variant("V15A").to_pipeline_config()
    plan = build_retrieval_query_plan(query="alpha overview", config=config, retriever=retriever)

    assert plan["mode"] == "corpus_aware"
    assert plan["original_query"] == "alpha overview"
    assert plan["retrieval_queries"][0] == "alpha overview"
    assert "Corpus retrieval focus:" in plan["retrieval_queries"][1]
    assert plan["expansion_sources"]
    assert all(source.get("reason") for source in plan["expansion_sources"])
    assert all(source.get("confidence", 0) > 0 for source in plan["expansion_sources"])
