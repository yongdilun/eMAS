import builtins
from pathlib import Path
from unittest.mock import MagicMock, patch

from factory_agent.rag.document_augmentation import build_document_augmentation
from factory_agent.rag.generation import AnswerGenerator
from factory_agent.rag.ingestion import IngestionEngine
from factory_agent.rag.retrieval import HybridRetriever
from factory_agent.rag.schemas import Chunk


def _chunk() -> Chunk:
    return Chunk(
        chunk_id="nist_csf_2_0_c0001",
        text=(
            "[Section: Govern] The CSF Core provides a taxonomy of high-level "
            "cybersecurity outcomes that can help an organization manage risk."
        ),
        metadata={
            "doc_id": "nist_csf_2_0",
            "title": "The NIST Cybersecurity Framework 2.0",
            "organization": "NIST",
            "domain": "cybersecurity",
            "subdomain": "cybersecurity framework",
            "authority_level": "official_public_guidance",
            "risk_level": "medium",
            "section_title": "Govern",
            "section_path": "CSF 2.0 > Govern",
            "use_for": ["cybersecurity framework guidance"],
            "related_entities": ["CSF Core", "Profiles", "Tiers"],
        },
    )


def test_document_augmentation_does_not_read_eval_cases_or_question_bank(monkeypatch):
    blocked = (
        "tests/rag_eval/cases.json",
        "docs/qa/rag_eval_question_bank.md",
    )
    original_open = builtins.open
    original_read_text = Path.read_text

    def guarded_open(file, *args, **kwargs):
        normalized = str(file).replace("\\", "/")
        assert all(marker not in normalized for marker in blocked)
        return original_open(file, *args, **kwargs)

    def guarded_read_text(self, *args, **kwargs):
        normalized = str(self).replace("\\", "/")
        assert all(marker not in normalized for marker in blocked)
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    augmentation = build_document_augmentation(_chunk())

    assert augmentation.synthetic_text
    assert "expected answer" not in augmentation.synthetic_text.lower()
    assert "nist-csf-2-df-01" not in augmentation.synthetic_text


def test_augmented_ingestion_keeps_synthetic_text_separate_from_original_evidence():
    engine = object.__new__(IngestionEngine)
    engine.document_augmentation = True

    store_chunks, evidence_chunks = IngestionEngine._prepare_chunks_for_index(engine, [_chunk()])

    assert len(store_chunks) == 1
    assert len(evidence_chunks) == 1
    assert "Retrieval augmentation - synthetic" in store_chunks[0].text
    assert "Retrieval augmentation - synthetic" not in evidence_chunks[0].text
    assert evidence_chunks[0].text == _chunk().text
    assert evidence_chunks[0].metadata["original_evidence_text"] == _chunk().text
    assert evidence_chunks[0].metadata["synthetic_augmentation_text"]


def test_augmented_vector_search_returns_original_evidence_text_not_synthetic_text():
    original = _chunk().text
    augmentation = build_document_augmentation(_chunk())
    metadata = {
        **_chunk().metadata,
        "document_augmentation_enabled": True,
        "document_augmentation_strategy_version": "document_augmentation_v1",
        "synthetic_augmentation_text": augmentation.synthetic_text,
        "original_evidence_text": original,
    }

    with patch("chromadb.PersistentClient"), patch(
        "chromadb.utils.embedding_functions.DefaultEmbeddingFunction"
    ):
        retriever = HybridRetriever(
            db_path="mock_augmented_db",
            bm25_path="missing_augmented_bm25.pkl",
            document_augmentation=True,
        )

    retriever.collection.query = MagicMock(
        return_value={
            "ids": [["nist_csf_2_0_c0001"]],
            "documents": [[augmentation.retrieval_text]],
            "metadatas": [[metadata]],
            "distances": [[0.1]],
        }
    )

    result = retriever.vector_search("What does Govern say about taxonomy?")

    assert result[0].chunk.text == original
    assert "Retrieval augmentation - synthetic" not in result[0].chunk.text
    assert result[0].chunk.metadata["synthetic_augmentation_text"] == augmentation.synthetic_text


def test_synthetic_augmentation_text_is_not_used_as_final_citation_evidence():
    chunk = _chunk()
    augmentation = build_document_augmentation(chunk)
    chunk.metadata = {
        **chunk.metadata,
        "synthetic_augmentation_text": augmentation.synthetic_text,
        "original_evidence_text": chunk.text,
        "document_augmentation_enabled": True,
    }
    generator = object.__new__(AnswerGenerator)

    citation = generator.build_source_citation(
        chunk,
        1,
        query="What does the CSF Core provide?",
        answer="The CSF Core provides a taxonomy of high-level cybersecurity outcomes.",
        support_chunks=[chunk],
    )

    assert "taxonomy of high-level cybersecurity outcomes" in citation.snippet
    assert "Generated retrieval questions" not in citation.snippet
    assert "Retrieval augmentation" not in citation.snippet
