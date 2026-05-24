import os
import shutil
import pytest
import json
import fitz
from factory_agent.rag.ingestion import IngestionEngine, _find_text_range
from factory_agent.rag.document_registry import resolve_source_pdf_path, source_pdf_url
from factory_agent.rag.schemas import DocumentEntry

TEST_DB_PATH = "factory_agent/rag/test_vector_db"
TEST_BM25_PATH = "factory_agent/rag/test_bm25_index.pkl"


def _write_test_register(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    doc_path = sources / "loto.md"
    doc_path.write_text(
        "# LOTO SOP\n\n## Lockout\n\nThe LOTO procedure requires locking out all energy sources before maintenance.\n",
        encoding="utf-8",
    )
    register_path = tmp_path / "source_register.json"
    register_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "doc_id": "SOP-LOTO-001",
                        "title": "LOTO SOP",
                        "file_path": str(doc_path),
                        "source_type": "markdown",
                        "organization": "eMAS Safety",
                        "domain": "safety",
                        "subdomain": "loto",
                        "authority_level": "mandatory_procedure",
                        "use_for": ["loto"],
                        "do_not_use_for": ["live factory status lookup"],
                        "related_entities": ["machine"],
                        "risk_level": "high",
                        "license": "internal",
                        "version": "1.0",
                        "retrieved_date": "2026-05-10",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return register_path


def _write_pdf_test_register(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    doc_path = sources / "loto.pdf"
    pdf = fitz.open()
    page_1 = pdf.new_page()
    page_1.insert_text((72, 72), "LOTO preparation. Notify affected employees before lockout starts.")
    page_2 = pdf.new_page()
    page_2.insert_text((72, 72), "LOTO verification. Verify zero energy after isolation and before maintenance.")
    pdf.save(doc_path)
    pdf.close()
    register_path = tmp_path / "source_register.json"
    register_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "doc_id": "PDF-LOTO",
                        "title": "PDF LOTO Procedure",
                        "file_path": str(doc_path),
                        "source_type": "official_public_pdf",
                        "organization": "Factory Safety",
                        "domain": "safety",
                        "subdomain": "loto",
                        "authority_level": "mandatory_procedure",
                        "use_for": ["loto"],
                        "do_not_use_for": ["live factory status lookup"],
                        "related_entities": ["machine"],
                        "risk_level": "high",
                        "license": "internal",
                        "version": "1.0",
                        "retrieved_date": "2026-05-10",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return register_path, doc_path


def _write_structured_pdf_test_register(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    doc_path = sources / "structured_loto.pdf"
    pdf = fitz.open()
    page_1 = pdf.new_page()
    page_1.insert_text(
        (72, 72),
        "\n".join(
            [
                "Factory Safety SOP",
                "Preparation",
                "The control docu-",
                "ment explains the preparation step.",
                "What must workers do before they begin service",
                "or maintenance activities?",
                "1. Notify affected employees before shutdown.",
                "Is the lockout device ready?",
                "1",
            ]
        ),
    )
    page_2 = pdf.new_page()
    page_2.insert_text(
        (72, 72),
        "\n".join(
            [
                "Factory Safety SOP",
                "Verification",
                "Verify zero energy after isolation.",
                "Record the verification result before maintenance starts.",
                "2",
            ]
        ),
    )
    pdf.set_toc(
        [
            [1, "Preparation", 1],
            [2, "What must workers do before they begin service or maintenance activities?", 1],
            [1, "Verification", 2],
        ]
    )
    pdf.save(doc_path)
    pdf.close()
    register_path = tmp_path / "source_register.json"
    register_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "doc_id": "PDF-STRUCTURED-LOTO",
                        "title": "Structured LOTO Procedure",
                        "file_path": str(doc_path),
                        "source_type": "official_public_pdf",
                        "organization": "Factory Safety",
                        "domain": "safety",
                        "subdomain": "loto",
                        "authority_level": "mandatory_procedure",
                        "use_for": ["loto"],
                        "do_not_use_for": ["live factory status lookup"],
                        "related_entities": ["machine"],
                        "risk_level": "high",
                        "license": "internal",
                        "version": "1.0",
                        "retrieved_date": "2026-05-10",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return register_path, doc_path


def _write_long_pdf_test_register(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    doc_path = sources / "long_loto.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text(
        (72, 72),
        "Procedure\n"
        + "\n".join(
            [
                f"Step {i} confirms isolation before work starts."
                for i in range(1, 25)
            ]
        ),
    )
    pdf.set_toc([[1, "Procedure", 1]])
    pdf.save(doc_path)
    pdf.close()
    register_path = tmp_path / "source_register.json"
    register_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "doc_id": "PDF-LONG-LOTO",
                        "title": "Long LOTO Procedure",
                        "file_path": str(doc_path),
                        "source_type": "official_public_pdf",
                        "organization": "Factory Safety",
                        "domain": "safety",
                        "subdomain": "loto",
                        "authority_level": "mandatory_procedure",
                        "use_for": ["loto"],
                        "do_not_use_for": ["live factory status lookup"],
                        "related_entities": ["machine"],
                        "risk_level": "high",
                        "license": "internal",
                        "version": "1.0",
                        "retrieved_date": "2026-05-10",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return register_path, doc_path


def test_pdf_text_range_tolerates_extracted_whitespace():
    page_text = "Control of \nHazardous Energy \nLockout/Tagout \n"
    chunk_text = "Control of\nHazardous Energy\nLockout/Tagout"

    expected_end = page_text.index("Lockout/Tagout") + len("Lockout/Tagout")
    assert _find_text_range(page_text, chunk_text) == (0, expected_end)


@pytest.fixture
def engine(tmp_path):
    # Cleanup before test
    if os.path.exists(TEST_DB_PATH):
        shutil.rmtree(TEST_DB_PATH, ignore_errors=True)
    if os.path.exists(TEST_BM25_PATH):
        try:
            os.remove(TEST_BM25_PATH)
        except:
            pass
        
    engine = IngestionEngine(db_path=TEST_DB_PATH, bm25_path=TEST_BM25_PATH)
    engine.test_register = str(_write_test_register(tmp_path))
    yield engine
    
    # Cleanup after test
    # Attempt cleanup but don't fail if files are locked
    if os.path.exists(TEST_DB_PATH):
        shutil.rmtree(TEST_DB_PATH, ignore_errors=True)
    if os.path.exists(TEST_BM25_PATH):
        try:
            os.remove(TEST_BM25_PATH)
        except:
            pass

def test_full_ingestion(engine):
    # Requirement I1: Ingest from register
    engine.run_full_ingestion(engine.test_register)
    
    # Requirement I2: Vector DB chunk count
    count = engine.collection.count()
    assert count > 0
    print(f"Total chunks ingested: {count}")
    
    # Requirement I3: BM25 index file exists
    assert os.path.exists(TEST_BM25_PATH)
    
    # Requirement I4 & I9: Metadata and Section Prefixing
    results = engine.collection.get(limit=5)
    for i in range(len(results['ids'])):
        meta = results['metadatas'][i]
        text = results['documents'][i]
        
        # I4: Required metadata fields
        assert "doc_id" in meta
        assert "source_id" in meta
        assert "chunk_id" in meta
        assert "snippet" in meta
        assert "section_title" in meta
        assert "section_path" in meta
        assert "authority_level" in meta
        assert "risk_level" in meta
        
        # I5: List types
        assert isinstance(json.loads(meta["use_for"]), list)
        assert isinstance(json.loads(meta["do_not_use_for"]), list)
        
        # I9: Section prefixing
        assert text.startswith("[Section:")


def test_pdf_ingestion_preserves_page_locator_metadata(engine, tmp_path):
    register_path, doc_path = _write_pdf_test_register(tmp_path)

    engine.run_full_ingestion(str(register_path))

    results = engine.collection.get(where={"doc_id": "PDF-LOTO"}, include=["documents", "metadatas"])
    assert results["ids"]
    assert min(meta.get("page_start") for meta in results["metadatas"]) == 1
    assert max(meta.get("page_end") for meta in results["metadatas"]) == 2
    assert resolve_source_pdf_path("PDF-LOTO", register_path=register_path) == doc_path.resolve()
    for meta, text in zip(results["metadatas"], results["documents"]):
        assert meta["pdf_url"] == source_pdf_url("PDF-LOTO")
        assert meta["pdf_url"] == "/documents/PDF-LOTO/pdf"
        assert "file_path" not in meta
        assert meta["source_id"] == f"PDF-LOTO#{meta['chunk_id']}"
        assert meta["chunk_id"]
        assert meta["snippet"]
        assert meta["page"] == meta["page_start"]
        assert meta["page_start"] <= meta["page_end"]
        assert meta["chunk_strategy_version"] == "pdf_struct_sentence_v1"
        assert "paragraph_start" in meta
        assert "sentence_start" in meta
        if "char_range" in meta:
            assert isinstance(json.loads(meta["char_range"]), list)
        assert meta["text_search"]
        assert text.startswith("[Section:")


def test_pdf_ingestion_uses_real_sections_and_cleans_paragraphs(engine, tmp_path):
    register_path, _ = _write_structured_pdf_test_register(tmp_path)

    engine.run_full_ingestion(str(register_path))

    results = engine.collection.get(
        where={"doc_id": "PDF-STRUCTURED-LOTO"},
        include=["documents", "metadatas"],
    )
    assert results["ids"]
    section_titles = {meta["section_title"] for meta in results["metadatas"]}
    assert "Preparation" in section_titles
    assert "What must workers do before they begin service or maintenance activities?" in section_titles
    assert "Verification" in section_titles
    assert section_titles != {"General"}

    combined_text = " ".join(results["documents"])
    combined_body_text = " ".join(text.split("] ", 1)[1] for text in results["documents"])
    assert "Factory Safety SOP" not in combined_text
    assert "docu- ment" not in combined_text
    assert "document explains the preparation step." in combined_text
    assert "What must workers do before they begin service or maintenance activities?" not in combined_body_text
    assert "1. Notify affected employees before shutdown." in combined_text
    assert "Is the lockout device ready?" in combined_text

    for meta in results["metadatas"]:
        assert meta["section_title"] in {
            "Preparation",
            "What must workers do before they begin service or maintenance activities?",
            "Verification",
        }
        assert meta["split_reason"]


def test_pdf_token_budget_packs_sentence_chunks(engine, tmp_path):
    register_path, _ = _write_long_pdf_test_register(tmp_path)
    engine.PDF_TARGET_TOKENS = 18
    engine.PDF_MAX_TOKENS = 24
    engine.PDF_MIN_TOKENS = 5

    engine.run_full_ingestion(str(register_path))

    results = engine.collection.get(
        where={"doc_id": "PDF-LONG-LOTO"},
        include=["documents", "metadatas"],
    )
    assert len(results["ids"]) >= 3
    for meta, text in zip(results["metadatas"], results["documents"]):
        assert meta["chunk_token_estimate"] <= 24
        body = text.split("] ", 1)[1]
        assert body[0].isupper() or body[0].isdigit()
        assert body[-1] in ".?!"


def test_pdf_reingests_when_chunk_strategy_version_changes(engine, tmp_path):
    register_path, _ = _write_pdf_test_register(tmp_path)
    engine.PDF_CHUNK_STRATEGY_VERSION = "legacy_pdf_chunks"
    engine.run_full_ingestion(str(register_path))

    first = engine.collection.get(where={"doc_id": "PDF-LOTO"}, limit=1)
    assert first["metadatas"][0]["chunk_strategy_version"] == "legacy_pdf_chunks"

    engine.PDF_CHUNK_STRATEGY_VERSION = "pdf_struct_sentence_v1"
    engine.run_full_ingestion(str(register_path))

    second = engine.collection.get(where={"doc_id": "PDF-LOTO"}, limit=1)
    assert second["metadatas"][0]["chunk_strategy_version"] == "pdf_struct_sentence_v1"

def test_reingestion_logic(engine):
    # First ingestion
    engine.run_full_ingestion(engine.test_register)
    initial_count = engine.collection.count()
    
    # Requirement I6: Re-ingest unchanged doc (should skip)
    engine.run_full_ingestion(engine.test_register)
    assert engine.collection.count() == initial_count
    
    # Requirement I7: Re-ingest with changed version
    with open(engine.test_register, 'r') as f:
        data = json.load(f)
        data['documents'][0]['version'] = "2.0"
        
    temp_register = os.path.join(os.path.dirname(engine.test_register), "temp_register.json")
    with open(temp_register, 'w') as f:
        json.dump(data, f)
        
    engine.run_full_ingestion(temp_register)
    # Count should still be same as it replaces
    assert engine.collection.count() == initial_count
    
    # Verify version updated in metadata
    res = engine.collection.get(where={"doc_id": "SOP-LOTO-001"}, limit=1)
    assert res['metadatas'][0]['version'] == "2.0"
    
    os.remove(temp_register)

def test_failed_ingestion_logging(engine):
    # Requirement I8: Missing file doesn't crash and logs error
    bad_doc = DocumentEntry(
        doc_id="MISSING-001",
        title="Missing Doc",
        file_path="non_existent.md",
        source_type="test",
        organization="test",
        domain="test",
        subdomain="test",
        authority_level="test",
        use_for=[],
        do_not_use_for=[],
        related_entities=[],
        risk_level="low",
        license="test",
        version="1.0",
        retrieved_date="2026-05-10"
    )
    
    if os.path.exists("failed_ingestion.log"):
        os.remove("failed_ingestion.log")
        
    success = engine.ingest_document(bad_doc)
    assert success is False
    assert os.path.exists("failed_ingestion.log")
