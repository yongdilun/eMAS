import pytest
import json
from unittest.mock import MagicMock, patch
from factory_agent.rag.schemas import Chunk, ScoredChunk, AnswerResult
from factory_agent.rag.generation import AnswerGenerator, SAFETY_WARNING_BLOCK
from factory_agent.rag.source_metadata import normalize_source_locators

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
                "file_path": "/path/to/doc1.pdf",
                "page": 3,
                "pdf_url": "/documents/doc1.pdf",
                "char_range": [120, 220],
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
    # A3: Safety warning data is structured because chunk 1 has risk_level: high.
    assert result.safety_warning is True
    assert result.safety_content
    assert SAFETY_WARNING_BLOCK.strip() not in result.answer
    assert ":::safety" not in result.answer
    # A6: No file_path leakage
    assert "/path/to/doc1.pdf" not in result.answer
    for source in result.sources:
        assert not hasattr(source, "file_path") or source.file_path is None
        dumped = source.model_dump()
        assert "file_path" not in dumped
        for key in ("source_id", "source_number", "doc_id", "chunk_id", "title", "organization", "snippet"):
            assert dumped[key]
    assert result.sources[0].chunk_id == "doc1_c1"
    assert result.sources[0].snippet == "The LOTO procedure requires locking out all energy sources."
    assert result.sources[0].page == 3
    assert result.sources[0].pdf_url == "/documents/doc1.pdf"
    assert result.sources[0].char_range == [120, 220]
    assert result.sources[0].text_search == "The LOTO procedure requires locking out all energy sources."


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_strips_legacy_raw_safety_markdown(mock_build_llm, mock_settings, sample_chunks):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = f"{SAFETY_WARNING_BLOCK.strip()}\n\nNotify affected employees before lockout starts [^1]."
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("What notification is required before LOTO?", sample_chunks)

    assert ":::safety" not in result.answer
    assert "SAFETY WARNING" not in result.answer
    assert "Notify affected employees" in result.answer
    assert result.safety_content


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_osha_reenergizing_answer_has_pdf_source_locator_without_policy_fallback(mock_build_llm, mock_settings):
    prompt = (
        "According to the OSHA lockout/tagout guide, what notification is required before reenergizing "
        "a machine after removing lockout or tagout devices?"
    )
    chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0029",
        text=(
            "After removing the lockout or tagout devices but before reenergizing the machine, the employer "
            "must assure that all employees who operate or work with the machine, as well as those in the area "
            "where service or maintenance is performed, know that the devices have been removed and that the "
            "machine is capable of being reenergized."
        ),
        metadata={
            "doc_id": "osha_3120_lockout_tagout",
            "title": "Control of Hazardous Energy Lockout/Tagout",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "lockout_tagout",
            "risk_level": "high",
            "license": "public",
            "version": "2002 (Revised)",
            "retrieved_date": "2026-05-10",
            "page": 15,
            "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
            "char_range": [0, 1017],
            "text_search": (
                "After removing the lockout or tagout devices but before reenergizing the machine, "
                "the employer must assure that all employees who operate or work with the machine"
            ),
        },
    )
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = (
        "Before reenergizing, notify affected employees who operate or work with the machine and employees "
        "in the service area that the lockout or tagout devices have been removed and the machine can be "
        "reenergized [^1]."
    )
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(prompt, [chunk])

    assert "notify affected employees" in result.answer.lower()
    assert result.safety_content
    assert len(result.sources) == 1
    source = result.sources[0].model_dump()
    assert source["doc_id"] == "osha_3120_lockout_tagout"
    assert source["chunk_id"] == "osha_3120_lockout_tagout_c0029"
    assert source["page"] == 15
    assert source["pdf_url"] == "/documents/osha_3120_lockout_tagout/pdf"
    assert source["char_range"] == [0, 1017]
    assert source["text_search"]
    serialized = json.dumps({"answer": result.answer, "sources": [source]})
    assert "loto_notification_requirement" not in serialized
    assert "LOTO Notification Requirements" not in serialized


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_osha_reenergizing_source_locator_uses_supporting_chunk_when_doc_chunk_order_is_noisy(
    mock_build_llm,
    mock_settings,
):
    prompt = (
        "According to the OSHA lockout/tagout guide, what notification is required before reenergizing "
        "a machine after removing lockout or tagout devices?"
    )
    appendix_chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0027",
        text=(
            "In Appendix A to 1910.147, OSHA provides a Typical Minimal Lockout Procedure. "
            "Before beginning service or maintenance, prepare for shutdown and apply lockout devices."
        ),
        metadata={
            "doc_id": "osha_3120_lockout_tagout",
            "title": "Control of Hazardous Energy Lockout/Tagout",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "lockout_tagout",
            "risk_level": "high",
            "license": "public",
            "version": "2002 (Revised)",
            "retrieved_date": "2026-05-10",
            "page": 14,
            "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        },
    )
    supporting_chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0029",
        text=(
            "After removing the lockout or tagout devices but before reenergizing the machine, the employer "
            "must assure that all employees who operate or work with the machine know that the devices have "
            "been removed and that the machine is capable of being reenergized."
        ),
        metadata={
            **appendix_chunk.metadata,
            "chunk_id": "osha_3120_lockout_tagout_c0029",
            "page": 15,
            "char_range": [0, 1017],
            "text_search": "After removing the lockout or tagout devices but before reenergizing the machine",
        },
    )
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = (
        "Before reenergizing, the employer must assure that all employees who operate or work with the machine "
        "know that the devices have been removed and that the machine is capable of being reenergized [^1]."
    )
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(prompt, [appendix_chunk, supporting_chunk])

    source = result.sources[0].model_dump()
    assert source["chunk_id"] == "osha_3120_lockout_tagout_c0029"
    assert source["page"] == 15
    assert source["snippet"].startswith("After removing the lockout or tagout devices")
    assert "capable of being reenergized" in source["snippet"]
    assert source["text_search"] == source["snippet"]

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
        assert source.source_id
        assert source.chunk_id
        assert source.snippet

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


def test_normalize_source_locators_reassigns_duplicate_final_source_numbers():
    sources = normalize_source_locators(
        [
            {
                "source_number": 1,
                "source_id": "doc-a#chunk-a",
                "doc_id": "doc-a",
                "chunk_id": "chunk-a",
                "title": "Document A",
                "organization": "Org A",
                "snippet": "Evidence A.",
            },
            {
                "source_number": 1,
                "source_id": "doc-b#chunk-b",
                "doc_id": "doc-b",
                "chunk_id": "chunk-b",
                "title": "Document B",
                "organization": "Org B",
                "snippet": "Evidence B.",
            },
            {
                "source_number": 2,
                "source_id": "doc-c#chunk-c",
                "doc_id": "doc-c",
                "chunk_id": "chunk-c",
                "title": "Document C",
                "organization": "Org C",
                "snippet": "Evidence C.",
            },
        ]
    )

    assert [source["source_number"] for source in sources] == [1, 2, 3]
    assert len({source["source_number"] for source in sources}) == len(sources)
    assert [(source["source_id"], source["doc_id"], source["title"]) for source in sources] == [
        ("doc-a#chunk-a", "doc-a", "Document A"),
        ("doc-b#chunk-b", "doc-b", "Document B"),
        ("doc-c#chunk-c", "doc-c", "Document C"),
    ]
