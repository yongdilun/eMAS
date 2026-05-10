import os
import shutil
import pytest
import json
from factory_agent.rag.ingestion import IngestionEngine
from factory_agent.rag.schemas import DocumentEntry

TEST_DB_PATH = "factory_agent/rag/test_vector_db"
TEST_BM25_PATH = "factory_agent/rag/test_bm25_index.pkl"
TEST_REGISTER = "../rag_sources/source_register.json"

@pytest.fixture
def engine():
    # Cleanup before test
    if os.path.exists(TEST_DB_PATH):
        shutil.rmtree(TEST_DB_PATH, ignore_errors=True)
    if os.path.exists(TEST_BM25_PATH):
        try:
            os.remove(TEST_BM25_PATH)
        except:
            pass
        
    engine = IngestionEngine(db_path=TEST_DB_PATH, bm25_path=TEST_BM25_PATH)
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
    engine.run_full_ingestion(TEST_REGISTER)
    
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
        assert "section_title" in meta
        assert "section_path" in meta
        assert "authority_level" in meta
        assert "risk_level" in meta
        
        # I5: List types
        assert isinstance(meta["use_for"], list)
        assert isinstance(meta["do_not_use_for"], list)
        
        # I9: Section prefixing
        assert text.startswith("[Section:")

def test_reingestion_logic(engine):
    # First ingestion
    engine.run_full_ingestion(TEST_REGISTER)
    initial_count = engine.collection.count()
    
    # Requirement I6: Re-ingest unchanged doc (should skip)
    engine.run_full_ingestion(TEST_REGISTER)
    assert engine.collection.count() == initial_count
    
    # Requirement I7: Re-ingest with changed version
    with open(TEST_REGISTER, 'r') as f:
        data = json.load(f)
        data['documents'][0]['version'] = "2.0"
        
    temp_register = "../rag_sources/temp_register.json"
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
