import asyncio

from factory_agent.rag.pipeline import RAGPipeline, RAGPipelineConfig
from factory_agent.rag.schemas import AnswerResult, Chunk, ScoredChunk


class FakeRetriever:
    def __init__(self) -> None:
        self.calls = []
        self.chunks = [
            Chunk(chunk_id="c1", text="alpha", metadata={"doc_id": "doc"}),
            Chunk(chunk_id="c2", text="bravo", metadata={"doc_id": "doc"}),
        ]

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return [
            ScoredChunk(chunk=self.chunks[0], vector_score=0.9, fusion_score=0.9),
            ScoredChunk(chunk=self.chunks[1], vector_score=0.8, fusion_score=0.8),
        ]


class FakeReranker:
    def __init__(self) -> None:
        self.calls = []

    def rerank(self, **kwargs):
        self.calls.append(kwargs)
        return [kwargs["candidates"][1].chunk]


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
    assert [chunk.chunk_id for chunk in generator.calls[0]["chunks"]] == ["c1", "c2"]


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
    assert [chunk.chunk_id for chunk in generator.calls[0]["chunks"]] == ["c2"]
