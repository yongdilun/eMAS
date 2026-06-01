from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest

from factory_agent.planning.v2_capability_map import (
    build_capability_needs_for_text,
    build_requirement_sketch_for_text,
)
from factory_agent.rag.corpus_routing import match_corpus_document_route
from factory_agent.rag.schemas import Chunk


FACTORY_AGENT_ROOT = Path(__file__).resolve().parents[1]


def _source_doc(
    doc_id: str,
    title: str,
    *,
    use_for: list[str],
    related_entities: list[str] | None = None,
    domain: str = "test_domain",
    subdomain: str = "test_subdomain",
) -> dict[str, object]:
    return {
        "doc_id": doc_id,
        "title": title,
        "file_path": f"{doc_id}.pdf",
        "source_type": "test_pdf",
        "organization": "Test Authority",
        "domain": domain,
        "subdomain": subdomain,
        "authority_level": "test_guidance",
        "version": "1.0",
        "use_for": use_for,
        "do_not_use_for": [],
        "related_entities": related_entities or [],
        "risk_level": "low",
        "license": "test",
        "retrieved_date": "2026-05-31",
    }


def _write_source_register(path: Path, docs: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"documents": docs}), encoding="utf-8")


@pytest.mark.parametrize(
    "prompt",
    [
        "How do GOVERN and IDENTIFY relate in CSF 2.0?",
        "In CSF 2.0, what is the difference between a Current Profile and a Target Profile?",
    ],
)
def test_csf_corpus_anchor_questions_compile_to_document_knowledge_need(prompt):
    sketch = build_requirement_sketch_for_text(prompt)
    needs = build_capability_needs_for_text(prompt)

    assert [requirement.goal for requirement in sketch.requirements] == [prompt]
    assert sketch.requirements[0].source_of_truth == "document_knowledge"
    assert sketch.requirements[0].requirement_type == "document_answer"
    assert needs[0].source_of_truth == "document_knowledge"
    assert needs[0].action == "search_documents"


def test_synthetic_source_register_terms_route_without_named_standard_branch(monkeypatch, tmp_path):
    register_path = tmp_path / "source_register.json"
    _write_source_register(
        register_path,
        [
            _source_doc(
                "widget_reliability_manual",
                "Widget Reliability Manual (WRM)",
                use_for=[
                    "explain widget reliability recovery",
                    "explain Blue Valve Reset recovery",
                ],
                related_entities=["blue_valve_reset", "wrm_recovery"],
                domain="widget_reliability",
                subdomain="blue_valve_reset",
            )
        ],
    )
    monkeypatch.setenv("RAG_SOURCE_REGISTER_PATH", str(register_path))

    prompt = "How do Blue Valve Reset and WRM recovery relate?"
    route = match_corpus_document_route(prompt, source_register_path=register_path)
    sketch = build_requirement_sketch_for_text(prompt)
    needs = build_capability_needs_for_text(prompt)

    assert route.is_match is True
    assert route.source_of_truth == "document_knowledge"
    assert route.matched_sources[0]["doc_id"] == "widget_reliability_manual"
    assert [requirement.goal for requirement in sketch.requirements] == [prompt]
    assert sketch.requirements[0].source_of_truth == "document_knowledge"
    assert needs[0].action == "search_documents"


def test_indexed_chunk_metadata_can_supply_document_route_anchor():
    route = match_corpus_document_route(
        "How does Blue Valve Reset relate to recovery?",
        source_documents=[],
        indexed_chunks=[
            Chunk(
                chunk_id="widget_reliability_manual_c0007",
                text="The body text is intentionally generic.",
                metadata={
                    "doc_id": "widget_reliability_manual",
                    "title": "Widget Reliability Manual",
                    "section_title": "Blue Valve Reset",
                    "section_path": ["Widget Reliability Manual", "Recovery", "Blue Valve Reset"],
                    "aliases": ["BVR"],
                    "related_entities": ["wrm_recovery"],
                    "use_for": ["explain Blue Valve Reset recovery"],
                    "domain": "widget_reliability",
                    "subdomain": "blue_valve_reset",
                },
            )
        ],
    )

    assert route.is_match is True
    assert route.matched_sources[0]["source_type"] == "indexed_metadata"
    assert route.matched_sources[0]["doc_id"] == "widget_reliability_manual"


def test_runtime_planner_uses_indexed_chunk_metadata_when_source_register_is_sparse(
    monkeypatch,
    tmp_path,
):
    register_path = tmp_path / "source_register.json"
    bm25_path = tmp_path / "bm25_index.pkl"
    _write_source_register(
        register_path,
        [
            _source_doc(
                "widget_manual",
                "Widget Manual",
                use_for=["explain widgets"],
                related_entities=[],
            )
        ],
    )
    chunks = [
        Chunk(
            chunk_id="widget_manual_c0007",
            text="The body text is intentionally generic.",
            metadata={
                "doc_id": "widget_manual",
                "title": "Widget Manual",
                "section_title": "Blue Valve Reset",
                "section_path": ["Widget Manual", "Recovery", "Blue Valve Reset"],
                "aliases": ["BVR"],
                "related_entities": ["recovery"],
                "use_for": ["explain Blue Valve Reset recovery"],
            },
        )
    ]
    bm25_path.write_bytes(pickle.dumps({"chunks": chunks}))
    monkeypatch.setenv("RAG_SOURCE_REGISTER_PATH", str(register_path))
    monkeypatch.setenv("RAG_ROUTING_BM25_PATH", str(bm25_path))

    prompt = "How does Blue Valve Reset relate to recovery?"
    source_register_route = match_corpus_document_route(prompt, source_register_path=register_path)
    sketch = build_requirement_sketch_for_text(prompt)
    needs = build_capability_needs_for_text(prompt)

    assert source_register_route.is_match is False
    assert [requirement.goal for requirement in sketch.requirements] == [prompt]
    assert sketch.requirements[0].source_of_truth == "document_knowledge"
    assert sketch.requirements[0].requirement_type == "document_answer"
    assert needs[0].source_of_truth == "document_knowledge"
    assert needs[0].action == "search_documents"


def test_corpus_route_question_shape_alone_is_not_enough():
    route = match_corpus_document_route(
        "How do alpha payroll codes relate?",
        source_documents=[
            _source_doc(
                "widget_reliability_manual",
                "Widget Reliability Manual (WRM)",
                use_for=["explain Blue Valve Reset recovery"],
                related_entities=["blue_valve_reset", "wrm_recovery"],
            )
        ],
    )

    assert route.is_match is False
    assert route.source_of_truth == "unknown"


def test_corpus_route_code_has_no_named_standard_table():
    source = (FACTORY_AGENT_ROOT / "factory_agent" / "rag" / "corpus_routing.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()

    for literal in (
        "csf",
        "govern",
        "identify",
        "current profile",
        "target profile",
        "mtconnect",
        "qif",
        "named_standard",
    ):
        assert literal not in lowered
