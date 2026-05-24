import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORY_AGENT_DIR = REPO_ROOT / "factory-agent"
if str(FACTORY_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_AGENT_DIR))

from factory_agent.rag.schemas import AnswerResult, Chunk, ScoredChunk
from tests.rag_eval.run_eval import _run_case
from tests.rag_eval.variants import get_variant


class FakePipeline:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return AnswerResult(
            answer="ok",
            sources=[],
            safety_warning=False,
            route_used="RAG_ONLY",
        )


class FakeRetriever:
    def __init__(self) -> None:
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return [
            ScoredChunk(
                chunk=Chunk(
                    chunk_id="chunk-1",
                    text="retrieved text",
                    metadata={"doc_id": "doc", "page": 2},
                ),
                vector_score=0.9,
                fusion_score=0.9,
            )
        ]


def test_run_case_uses_selected_variant_for_pipeline_and_retrieval_debug():
    variant = get_variant("V0")
    pipeline = FakePipeline()
    retriever = FakeRetriever()

    route_decision, rag_result, agent_response, retrieval_debug, error = asyncio.run(
        _run_case(
            case={"id": "case-1", "query": "query"},
            rag_pipeline=pipeline,
            retriever=retriever,
            variant=variant,
            retrieval_top_n=10,
        )
    )

    pipeline_config = pipeline.calls[0]["config"]
    assert pipeline_config.retrieval_mode == "vector"
    assert pipeline_config.use_rerank is False
    assert pipeline_config.expand_neighbors is False

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
    assert route_decision["variant_id"] == "V0"
    assert rag_result["answer"] == "ok"
    assert agent_response["answer"] == "ok"
    assert retrieval_debug["retrieval_settings"]["retrieval_mode"] == "vector"
    assert retrieval_debug["top_chunks"][0]["rank"] == 1
    assert error is None
