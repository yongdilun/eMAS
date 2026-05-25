import sys
from pathlib import Path

from tests.rag_eval.artifact_schema import (
    AutomatedReport,
    build_case_artifact,
    build_summary,
    serialize_retrieval_debug,
)
from tests.rag_eval.variants import get_variant

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORY_AGENT_DIR = REPO_ROOT / "factory-agent"
if str(FACTORY_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_AGENT_DIR))

from factory_agent.rag.schemas import Chunk, ScoredChunk  # noqa: E402


def test_retrieval_debug_serializes_rank_metadata_and_scores():
    chunk = Chunk(
        chunk_id="doc_c0001",
        text="A useful source snippet.",
        metadata={
            "doc_id": "doc",
            "title": "Doc",
            "page": 4,
            "page_start": 4,
            "page_end": 5,
            "section_title": "Section",
            "section_path": ["Chapter", "Section"],
        },
    )
    scored = ScoredChunk(
        chunk=chunk,
        vector_score=0.9,
        keyword_score=0.7,
        fusion_score=0.5,
        boosted_score=0.6,
    )

    debug = serialize_retrieval_debug(
        [scored],
        retrieval_settings={"retrieval_mode": "hybrid", "expand_neighbors": False},
    )

    top = debug["top_chunks"][0]
    assert debug["retrieval_settings"]["retrieval_mode"] == "hybrid"
    assert debug["retrieval_settings"]["expand_neighbors"] is False
    assert top["rank"] == 1
    assert top["doc_id"] == "doc"
    assert top["page"] == 4
    assert top["page_start"] == 4
    assert top["page_end"] == 5
    assert top["section_title"] == "Section"
    assert top["section_path"] == ["Chapter", "Section"]
    assert top["scores"] == {
        "vector": 0.9,
        "keyword": 0.7,
        "fusion": 0.5,
        "boosted": 0.6,
    }
    assert top["snippet"] == "A useful source snippet."


def test_case_artifact_and_summary_include_variant_config():
    variant = get_variant("V0")
    variant_config = variant.to_dict()
    artifact = build_case_artifact(
        run_id="run",
        variant_id=variant.variant_id,
        variant_config=variant_config,
        case={"id": "case-1"},
        query="query",
        started_at="start",
        finished_at="finish",
        duration_s=0.12345,
        env={},
        route_decision={"route": "RAG_ONLY"},
        rag_result={
            "answer": "ok",
            "metadata": {
                "rerank": {
                    "enabled": True,
                    "attempted": True,
                    "succeeded": True,
                    "fallback_used": False,
                }
            },
        },
        agent_response={"answer": "ok"},
        retrieval_debug={"queried": True, "top_chunks": [], "error": None},
        automated=AutomatedReport(),
        scoring={
            "rule_score": 88.0,
            "rule_dimensions": {"answer_non_empty": {"score": 1}},
            "retrieval_metrics": {"doc_hit@3": True},
            "borderline": False,
            "serious_failures": [],
            "serious_failure": False,
        },
        error=None,
    )
    artifact["_artifact_path"] = "artifact.json"

    summary = build_summary(
        run_id="run",
        variant_id=variant.variant_id,
        variant_config=variant_config,
        started_at="start",
        finished_at="finish",
        env={},
        case_results=[artifact],
    )

    assert artifact["variant_id"] == "V0"
    assert artifact["variant_config"]["pipeline_config"]["retrieval_mode"] == "vector"
    assert artifact["rule_score"] == 88.0
    assert artifact["retrieval_metrics"]["doc_hit@3"] is True
    assert summary["variant_id"] == "V0"
    assert summary["variant_config"]["pipeline_config"]["use_rerank"] is False
    assert summary["scoring"]["average_rule_score"] == 88.0
    assert summary["scoring"]["rerank_counts"]["enabled"] == 1
    assert summary["scoring"]["rerank_counts"]["fallback_used"] == 0
    assert summary["variant_aggregates"]["V0"]["retrieval_metric_rates"]["doc_hit@3"]["rate"] == 1.0
    assert summary["cases"][0]["variant_id"] == "V0"
