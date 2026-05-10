import pytest
import json
from unittest.mock import MagicMock, patch
from factory_agent.rag.schemas import Chunk, ScoredChunk, AnswerResult
from factory_agent.rag.generation import AnswerGenerator, SAFETY_WARNING_BLOCK

@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.rag_answer_model = "test-model"
    settings.rag_answer_timeout_s = 10.0
    settings.rag_answer_max_tokens = 500
    settings.rag_answer_openai_base_url = None
    settings.openai_api_key = "test-key"
    return settings

@pytest.fixture
def sample_chunks():
    return [
        Chunk(
            chunk_id="doc1_c1",
            text="The LOTO procedure requires locking out all energy sources.",
            metadata={
                "doc_id": "doc1",
                "title": "LOTO SOP",
                "organization": "eMAS Safety",
                "authority_level": "mandatory_procedure",
                "domain": "safety",
                "subdomain": "loto",
                "risk_level": "high",
                "license": "internal",
                "version": "1.0",
                "retrieved_date": "2026-01-01",
                "file_path": "/path/to/doc1.pdf"
            }
        ),
        Chunk(
            chunk_id="doc2_c1",
            text="OEE calculation is Availability * Performance * Quality.",
            metadata={
                "doc_id": "doc2",
                "title": "OEE Standard",
                "organization": "eMAS Ops",
                "authority_level": "official_public_guidance",
                "domain": "operations",
                "subdomain": "oee",
                "risk_level": "low",
                "license": "public",
                "version": "2.0",
                "retrieved_date": "2026-01-01",
                "file_path": "/path/to/doc2.pdf"
            }
        )
    ]

@pytest.fixture
def restricted_chunk():
    return Chunk(
        chunk_id="doc3_c1",
        text="Restricted maintenance manual content.",
        metadata={
            "doc_id": "doc3",
            "title": "Confidential Manual",
            "organization": "Vendor X",
            "authority_level": "reference_only",
            "domain": "equipment",
            "subdomain": "maintenance",
            "risk_level": "medium",
            "license": "restricted",
            "version": "3.1",
            "retrieved_date": "2026-01-01",
            "file_path": "/path/to/doc3.pdf"
        }
    )

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_build_context(mock_build_llm, mock_settings, sample_chunks):
    mock_build_llm.return_value = MagicMock()
    generator = AnswerGenerator(mock_settings)
    context = generator.build_context(sample_chunks)
    
    assert "[SOURCE 1: LOTO SOP" in context
    assert "Organization: eMAS Safety" in context
    assert "Authority: mandatory_procedure" in context
    assert "Risk Level: high" in context
    assert "License: [internal]" in context
    
    assert "[SOURCE 2: OEE Standard" in context
    assert "License: [public]" in context

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_build_context_restricted(mock_build_llm, mock_settings, restricted_chunk):
    mock_build_llm.return_value = MagicMock()
    generator = AnswerGenerator(mock_settings)
    context = generator.build_context([restricted_chunk])
    
    assert "License: [restricted — internal use only]" in context

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_safety_warning(mock_build_llm, mock_settings, sample_chunks):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "To perform LOTO, follow these steps [SOURCE 1]."
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm
    
    generator = AnswerGenerator(mock_settings)
    result = generator.generate("How to do LOTO?", sample_chunks)
    
    # A1: Non-empty answer
    assert result.answer
    # A3: Safety warning present because chunk 1 has risk_level: high
    assert result.safety_warning is True
    assert SAFETY_WARNING_BLOCK.strip() in result.answer
    # A6: No file_path leakage
    assert "/path/to/doc1.pdf" not in result.answer
    for source in result.sources:
        assert not hasattr(source, "file_path") or source.file_path is None

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_no_safety_warning(mock_build_llm, mock_settings, sample_chunks):
    # Only use the low-risk chunk
    low_risk_chunks = [sample_chunks[1]]
    
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "OEE is Availability * Performance * Quality [SOURCE 1]."
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm
    
    generator = AnswerGenerator(mock_settings)
    result = generator.generate("Explain OEE?", low_risk_chunks)
    
    # A4: Safety warning absent
    assert result.safety_warning is False
    assert "⚠️ SAFETY WARNING" not in result.answer

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_api_integration(mock_build_llm, mock_settings, sample_chunks):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "The current OEE for Line 3 is 72%. According to [SOURCE 2], OEE is calculated as..."
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm
    
    api_data = {"line_id": "Line 3", "oee": 0.72}
    
    generator = AnswerGenerator(mock_settings)
    result = generator.generate("What is the OEE for Line 3?", sample_chunks, api_data=api_data, route="API_THEN_RAG")
    
    # A8: References both API data and source
    assert "72%" in result.answer
    assert "[SOURCE 2]" in result.answer
    assert result.route_used == "API_THEN_RAG"

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_citations(mock_build_llm, mock_settings, sample_chunks):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Steps: 1. Lock [SOURCE 1]. 2. Verify [SOURCE 1]. 3. Calc [SOURCE 2]."
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm
    
    generator = AnswerGenerator(mock_settings)
    result = generator.generate("How to do LOTO?", sample_chunks)
    
    # A2: Citation matching
    assert len(result.sources) == 2
    assert result.sources[0].source_number == 1
    assert result.sources[0].title == "LOTO SOP"
    assert result.sources[1].source_number == 2
    assert result.sources[1].title == "OEE Standard"
    
    # A5: Citation fields present
    for source in result.sources:
        assert source.organization
        assert source.authority_level
        assert source.license

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_llm_failure(mock_build_llm, mock_settings, sample_chunks):
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = Exception("LLM Timeout")
    mock_build_llm.return_value = mock_llm
    
    generator = AnswerGenerator(mock_settings)
    result = generator.generate("How to do LOTO?", sample_chunks)
    
    # A9: Fallback message
    assert "Unable to generate a detailed answer" in result.answer
    assert len(result.sources) == 2

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_empty_input(mock_build_llm, mock_settings):
    mock_build_llm.return_value = MagicMock()
    generator = AnswerGenerator(mock_settings)
    result = generator.generate("What is the meaning of life?", [])
    
    assert "No relevant documents" in result.answer
    assert len(result.sources) == 0
