import pytest
import json
from unittest.mock import MagicMock, patch
from factory_agent.rag.schemas import Chunk, ScoredChunk, AnswerResult
from factory_agent.rag.generation import AnswerGenerator, SAFETY_WARNING_BLOCK, extract_explicit_procedure_evidence
from factory_agent.rag.source_metadata import insufficient_context_answer, normalize_source_locator, normalize_source_locators

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
    mock_response.content = "To perform LOTO, follow these steps [^1]."
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
def test_answer_prompt_contains_full_citation_contract_in_first_generation_call(mock_build_llm, mock_settings):
    chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0027",
        text=(
            "The LOTO procedure discussion explains that workers prepare for shutdown, shut down the "
            "machine, and disconnect or isolate the machine from the energy sources before maintenance."
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
    response = MagicMock()
    response.content = (
        "1. Prepare for shutdown.\n"
        "2. Shut down the machine.\n"
        "3. Disconnect or isolate the machine from the energy sources.[^1]"
    )
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?",
        [chunk],
    )

    assert result.answer == (
        "1. Prepare for shutdown. [^1]\n"
        "2. Shut down the machine. [^1]\n"
        "3. Disconnect or isolate the machine from the energy sources. [^1]"
    )
    assert mock_llm.invoke.call_count == 1
    prompt = mock_llm.invoke.call_args.args[0][1].content
    assert "Cite coherent non-procedure answer groups, not every sentence" in prompt
    assert "For procedures, output a flat numbered list with one visible action per numbered step" in prompt
    assert "For procedures, cite each numbered step with the source marker that proves that step" in prompt
    assert "Do not nest a numbered list inside another numbered item" in prompt
    assert "If no supported answer remains, output exactly the insufficient-context sentence" in prompt
    assert "If relevant evidence is split across multiple source chunks" in prompt
    assert "For section summaries or multi-part questions" in prompt
    assert "For safety procedures, answer from the retrieved procedure evidence" in prompt
    assert result.sources[0].source_number == 1
    assert result.sources[0].doc_id == "osha_3120_lockout_tagout"


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_flattens_grouped_loto_procedure_with_long_intro(mock_build_llm, mock_settings):
    chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0027",
        text=(
            "Before beginning service or maintenance, the following steps must be accomplished in sequence "
            "and according to the specific provisions of the employer's energy-control procedure: "
            "(1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or isolate the machine "
            "from the energy source(s); (4) Apply the lockout or tagout device(s) to the energy-isolating "
            "device(s); (5) Release, restrain, or otherwise render safe all potential hazardous stored "
            "or residual energy."
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
    answer = (
        "Before beginning service or maintenance, workers must complete the following steps in sequence "
        "according to the specific provisions of the employer's energy-control procedure:\n"
        "1. Prepare for shutdown;\n"
        "2. Shut down the machine;\n"
        "3. Disconnect or isolate the machine from the energy source(s);\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s);\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy.[^1]"
    )
    mock_response = MagicMock()
    mock_response.content = answer
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?",
        [chunk],
    )

    assert result.answer == (
        "1. Prepare for shutdown. [^1]\n"
        "2. Shut down the machine. [^1]\n"
        "3. Disconnect or isolate the machine from the energy source(s). [^1]\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s). [^1]\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy. [^1]"
    )
    assert result.answer != insufficient_context_answer(has_sources=True)
    assert result.sources[0].source_number == 1


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_flattens_nested_procedure_answer_and_keeps_step_citations(mock_build_llm, mock_settings):
    chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0027",
        text=(
            "Before beginning service or maintenance, the following steps must be accomplished in sequence "
            "and according to the specific provisions of the employer's energy-control procedure: "
            "(1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or isolate the machine "
            "from the energy source(s); (4) Apply the lockout or tagout device(s) to the energy-isolating "
            "device(s); (5) Release, restrain, or otherwise render safe all potential hazardous stored "
            "or residual energy; and (6) If a possibility exists for reaccumulation of hazardous energy, "
            "regularly verify during service and maintenance that such energy has not reaccumulated."
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
    awkward_answer = (
        "1. Before beginning service or maintenance, workers must complete the following steps in sequence "
        "and according to the specific provisions of the employer's energy-control procedure:\n"
        "1. Prepare for shutdown.\n"
        "2. Shut down the machine.\n"
        "3. Disconnect or isolate the machine from the energy source(s).\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s).\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy.\n"
        "6. If a possibility exists for reaccumulation of hazardous energy, regularly verify during service "
        "and maintenance that such energy has not reaccumulated to hazardous levels.\n"
        "2. After completing these steps, verify the isolation and deenergization of the machine.[^1]"
    )
    mock_response = MagicMock()
    mock_response.content = awkward_answer
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?",
        [chunk],
    )

    assert result.answer == (
        "1. Prepare for shutdown. [^1]\n"
        "2. Shut down the machine. [^1]\n"
        "3. Disconnect or isolate the machine from the energy source(s). [^1]\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s). [^1]\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy. [^1]\n"
        "6. If a possibility exists for reaccumulation of hazardous energy, regularly verify during service "
        "and maintenance that such energy has not reaccumulated. [^1]"
    )
    assert "Before beginning service or maintenance, workers must complete the following steps" not in result.answer
    assert "Safety notice" not in result.answer
    assert result.safety_content
    assert result.metadata["generation_validation"]["deterministic_procedure_answer"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_flattens_inline_single_citation_procedure_output(mock_build_llm, mock_settings):
    chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0015",
        text=(
            "Before beginning service or maintenance, the following steps must be accomplished in sequence "
            "and according to the specific provisions of the employer's energy-control procedure: "
            "(1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or isolate the machine "
            "from the energy source(s); (4) Apply the lockout or tagout device(s) to the energy-isolating "
            "device(s); (5) Release, restrain, or otherwise render safe all potential hazardous stored "
            "or residual energy; (6) If a possibility exists for reaccumulation of hazardous energy, "
            "regularly verify during service and maintenance that such energy has not reaccumulated "
            "to hazardous levels."
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
            "page": 13,
            "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        },
    )
    live_shape_answer = (
        "1. Prepare for shutdown. 2. Shut down the machine. "
        "3. Disconnect or isolate the machine from the energy source(s). "
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s). "
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy. "
        "If a possibility exists for reaccumulation of hazardous energy, regularly verify during the service "
        "and maintenance that such energy has not reaccumulated to hazardous levels. "
        "These steps must be accomplished in sequence and according to the specific provisions of the "
        "employer's energy-control procedure.[^1]"
    )
    mock_response = MagicMock()
    mock_response.content = live_shape_answer
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?",
        [chunk],
    )

    assert result.answer == (
        "1. Prepare for shutdown. [^1]\n"
        "2. Shut down the machine. [^1]\n"
        "3. Disconnect or isolate the machine from the energy source(s). [^1]\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s). [^1]\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy. [^1]\n"
        "6. If a possibility exists for reaccumulation of hazardous energy, regularly verify during the service "
        "and maintenance that such energy has not reaccumulated to hazardous levels. [^1]"
    )
    assert "These steps must be accomplished" not in result.answer


def test_extract_explicit_procedure_evidence_preserves_inline_steps_and_child_page():
    chunk = Chunk(
        chunk_id="rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
        text=(
            "Before beginning service or maintenance, the following steps must be accomplished in sequence "
            "and according to the specific provisions of the employer's energy-control procedure: "
            "(1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or isolate the machine "
            "from the energy source(s); (4) Apply the lockout or tagout device(s) to the energy-isolating "
            "device(s); (5) Release, restrain, or otherwise render safe all potential hazardous stored "
            "or residual energy. If a possibility exists for reaccumulation of hazardous energy, regularly "
            "verify during the service and maintenance that such energy has not reaccumulated to hazardous "
            "levels; and (6) Verify the isolation and deenergization of the machine.\n\n"
            "Employees who work on deenergized machinery may be seriously injured if devices are removed."
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
            "page": 13,
            "page_start": 13,
            "page_end": 15,
            "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
            "source_chunk_evidence": [
                {
                    "doc_id": "osha_3120_lockout_tagout",
                    "chunk_id": "osha_3120_lockout_tagout_c0015",
                    "page": 13,
                    "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                    "snippet": "What must an energy-control procedure include?",
                },
                {
                    "doc_id": "osha_3120_lockout_tagout",
                    "chunk_id": "osha_3120_lockout_tagout_c0016",
                    "page": 14,
                    "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                    "snippet": (
                        "Before beginning service or maintenance, the following steps must be accomplished "
                        "in sequence and according to the specific provisions of the employer's energy-control "
                        "procedure: (1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or "
                        "isolate the machine from the energy source(s); (4) Apply the lockout or tagout "
                        "device(s) to the energy-isolating device(s); (5) Release, restrain, or otherwise "
                        "render safe all potential hazardous stored or residual energy. If a possibility "
                        "exists for reaccumulation of hazardous energy, regularly verify during the service "
                        "and maintenance that such energy has not reaccumulated to hazardous levels; and "
                        "(6) Verify the isolation and deenergization of the machine."
                    ),
                },
            ],
        },
    )

    evidence = extract_explicit_procedure_evidence(
        query="According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?",
        doc_order=["osha_3120_lockout_tagout"],
        doc_chunks={"osha_3120_lockout_tagout": [chunk]},
    )

    assert evidence is not None
    assert [step.text for step in evidence.steps] == [
        "Prepare for shutdown.",
        "Shut down the machine.",
        "Disconnect or isolate the machine from the energy source(s).",
        "Apply the lockout or tagout device(s) to the energy-isolating device(s).",
        (
            "Release, restrain, or otherwise render safe all potential hazardous stored or residual energy. "
            "If a possibility exists for reaccumulation of hazardous energy, regularly verify during the "
            "service and maintenance that such energy has not reaccumulated to hazardous levels."
        ),
        "Verify the isolation and deenergization of the machine.",
    ]
    assert evidence.steps[5].page == 14
    assert evidence.steps[5].text_search == "Verify the isolation and deenergization of the machine"


def test_extract_explicit_procedure_evidence_ignores_unmatched_or_truncated_lists():
    removal_chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0017",
        text=(
            "Before removing lockout or tagout devices, employees must take the following steps: "
            "(1) Inspect machines or their components; and (2) Check that everyone is positioned safely."
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
        },
    )
    truncated_chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0018",
        text=(
            "Before beginning service or maintenance, the following steps must be accomplished: "
            "(1) Prepare for shutdown; (2) Shut down the"
        ),
        metadata={**removal_chunk.metadata, "page": 14},
    )
    ellipsis_chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0019",
        text=(
            "Before beginning service or maintenance, the following steps must be accomplished: "
            "(1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or isolate the machine "
            "from the energy source(s); (4) Apply the lockout or tagout device(s) to the energy-isolat..."
        ),
        metadata={**removal_chunk.metadata, "page": 14},
    )

    query = "According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?"

    assert extract_explicit_procedure_evidence(
        query=query,
        doc_order=["osha_3120_lockout_tagout"],
        doc_chunks={"osha_3120_lockout_tagout": [removal_chunk]},
    ) is None
    assert extract_explicit_procedure_evidence(
        query=query,
        doc_order=["osha_3120_lockout_tagout"],
        doc_chunks={"osha_3120_lockout_tagout": [truncated_chunk]},
    ) is None
    assert extract_explicit_procedure_evidence(
        query=query,
        doc_order=["osha_3120_lockout_tagout"],
        doc_chunks={"osha_3120_lockout_tagout": [ellipsis_chunk]},
    ) is None


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_uses_deterministic_procedure_evidence_when_llm_would_omit_step(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="rse:osha_3120_lockout_tagout:01:osha_3120_lockout_tagout_c0015",
        text=(
            "Before beginning service or maintenance, the following steps must be accomplished in sequence "
            "and according to the specific provisions of the employer's energy-control procedure: "
            "(1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or isolate the machine "
            "from the energy source(s); (4) Apply the lockout or tagout device(s) to the energy-isolating "
            "device(s); (5) Release, restrain, or otherwise render safe all potential hazardous stored "
            "or residual energy. If a possibility exists for reaccumulation of hazardous energy, regularly "
            "verify during the service and maintenance that such energy has not reaccumulated to hazardous "
            "levels; and (6) Verify the isolation and deenergization of the machine."
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
            "page": 13,
            "page_start": 13,
            "page_end": 15,
            "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
            "source_chunk_evidence": [
                {
                    "doc_id": "osha_3120_lockout_tagout",
                    "chunk_id": "osha_3120_lockout_tagout_c0015",
                    "page": 13,
                    "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                    "snippet": "What must an energy-control procedure include?",
                },
                {
                    "doc_id": "osha_3120_lockout_tagout",
                    "chunk_id": "osha_3120_lockout_tagout_c0016",
                    "page": 14,
                    "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
                    "snippet": (
                        "Before beginning service or maintenance, the following steps must be accomplished "
                        "in sequence and according to the specific provisions of the employer's energy-control "
                        "procedure: (1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or "
                        "isolate the machine from the energy source(s); (4) Apply the lockout or tagout "
                        "device(s) to the energy-isolating device(s); (5) Release, restrain, or otherwise "
                        "render safe all potential hazardous stored or residual energy. If a possibility "
                        "exists for reaccumulation of hazardous energy, regularly verify during the service "
                        "and maintenance that such energy has not reaccumulated to hazardous levels; and "
                        "(6) Verify the isolation and deenergization of the machine."
                    ),
                },
            ],
        },
    )
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = (
        "1. Prepare for shutdown.\n"
        "2. Shut down the machine.\n"
        "3. Disconnect or isolate the machine from the energy source(s).\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s).\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy.[^1]"
    )
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?",
        [chunk],
    )

    assert result.answer == (
        "1. Prepare for shutdown. [^1]\n"
        "2. Shut down the machine. [^1]\n"
        "3. Disconnect or isolate the machine from the energy source(s). [^1]\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s). [^1]\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy. "
        "If a possibility exists for reaccumulation of hazardous energy, regularly verify during the service "
        "and maintenance that such energy has not reaccumulated to hazardous levels. [^1]\n"
        "6. Verify the isolation and deenergization of the machine. [^1]"
    )
    assert mock_llm.invoke.call_count == 1
    assert result.safety_content
    assert result.metadata["generation_validation"]["procedure_evidence_repaired"] is True
    assert result.metadata["generation_validation"]["deterministic_procedure_answer"] is True
    assert result.sources[0].evidence_snippets[0]["page"] == 14
    assert result.sources[0].evidence_snippets[0]["text_search"] == "Prepare for shutdown"


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_repairs_procedure_step_that_omits_required_subsentence(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0016",
        text=(
            "Before beginning service or maintenance, the following steps must be accomplished in sequence "
            "and according to the specific provisions of the employer's energy-control procedure: "
            "(1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or isolate the machine "
            "from the energy source(s); (4) Apply the lockout or tagout device(s) to the energy-isolating "
            "device(s); (5) Release, restrain, or otherwise render safe all potential hazardous stored "
            "or residual energy. If a possibility exists for reaccumulation of hazardous energy, regularly "
            "verify during the service and maintenance that such energy has not reaccumulated to hazardous "
            "levels; and (6) Verify the isolation and deenergization of the machine."
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
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = (
        "1. Prepare for shutdown.[^1]\n"
        "2. Shut down the machine.[^1]\n"
        "3. Disconnect or isolate the machine from the energy source(s).[^1]\n"
        "4. Apply the lockout or tagout device(s) to the energy-isolating device(s).[^1]\n"
        "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy.[^1]\n"
        "6. Verify the isolation and deenergization of the machine.[^1]"
    )
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?",
        [chunk],
    )

    assert mock_llm.invoke.call_count == 1
    assert "If a possibility exists for reaccumulation of hazardous energy" in result.answer
    assert "regularly verify during the service and maintenance" in result.answer
    assert result.metadata["generation_validation"]["procedure_evidence_repaired"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_repairs_uncited_answer_when_evidence_is_present(mock_build_llm, mock_settings, sample_chunks):
    bad_response = MagicMock()
    bad_response.content = "Lock out the machine before maintenance."
    repaired_response = MagicMock()
    repaired_response.content = "The LOTO procedure requires locking out all energy sources before maintenance [^1]."
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [bad_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("How to do LOTO?", [sample_chunks[0]])

    assert result.answer == repaired_response.content
    assert mock_llm.invoke.call_count == 2
    assert result.sources[0].doc_id == "doc1"
    assert result.metadata["generation_validation"]["repair_attempted"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_repairs_no_evidence_fallback_when_retrieved_context_matches_query(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="ams_c0100",
        text=(
            "Resource usage defines the amount or type of resources being consumed by an activity, "
            "including equipment, materials, personnel, and time."
        ),
        metadata={
            "doc_id": "nist_ams_300_1",
            "title": "Smart Manufacturing Reference Architecture",
            "organization": "NIST",
            "authority_level": "official_public_guidance",
            "domain": "smart_manufacturing",
            "subdomain": "reference_architecture",
            "risk_level": "low",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 71,
        },
    )
    refused_response = MagicMock()
    refused_response.content = insufficient_context_answer(has_sources=True)
    repaired_response = MagicMock()
    repaired_response.content = (
        "Resource usage is the amount or type of resources consumed by an activity, including equipment, "
        "materials, personnel, and time [^1]."
    )
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [refused_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("What does resource usage mean?", [chunk])

    assert "amount or type of resources" in result.answer
    assert result.answer != insufficient_context_answer(has_sources=True)
    assert mock_llm.invoke.call_count == 2
    assert result.metadata["generation_validation"]["initial_insufficient_context"] is True
    assert result.metadata["generation_validation"]["repair_attempted"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_repairs_single_source_unknown_citation_for_multichunk_relationship(
    mock_build_llm,
    mock_settings,
):
    chunks = [
        Chunk(
            chunk_id="ams_c0024",
            text=(
                "A23 designs new or modified production facilities and production systems, including "
                "equipment, material storage and delivery, instrumentation, control, support systems, "
                "physical plant, networks, and information systems."
            ),
            metadata={
                "doc_id": "nist_ams_300_1",
                "title": "Smart Manufacturing Reference Architecture",
                "organization": "NIST",
                "authority_level": "official_public_guidance",
                "domain": "smart_manufacturing",
                "subdomain": "reference_architecture",
                "risk_level": "low",
                "license": "public",
                "version": "1.0",
                "retrieved_date": "2026-05-25",
                "page": 21,
            },
        ),
        Chunk(
            chunk_id="ams_c0026",
            text=(
                "A232 specifies instrumentation and control systems, including controllers, data acquisition "
                "instruments, communications, and integrated system specifications."
            ),
            metadata={
                "doc_id": "nist_ams_300_1",
                "title": "Smart Manufacturing Reference Architecture",
                "organization": "NIST",
                "authority_level": "official_public_guidance",
                "domain": "smart_manufacturing",
                "subdomain": "reference_architecture",
                "risk_level": "low",
                "license": "public",
                "version": "1.0",
                "retrieved_date": "2026-05-25",
                "page": 24,
            },
        ),
    ]
    bad_response = MagicMock()
    bad_response.content = "A23 sets the production-system design scope, and A232 narrows it to instrumentation, control, data acquisition, communications, and integrated specifications [^24]."
    repaired_response = MagicMock()
    repaired_response.content = bad_response.content
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [bad_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "Explain how production system design relates to instrumentation and control specifications.",
        chunks,
    )

    assert "[^1]" in result.answer
    assert "[^24]" not in result.answer
    assert "production-system design scope" in result.answer
    assert "instrumentation, control" in result.answer
    assert result.metadata["generation_validation"]["repair_valid"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_repairs_single_source_unknown_citation_for_static_model_list(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="ams11_c0021",
        text="MTConnect defines information models for Devices, Streams, Assets, and Interfaces.",
        metadata={
            "doc_id": "nist_ams_300_11",
            "title": "Data standards for smart manufacturing",
            "organization": "NIST",
            "authority_level": "official_public_guidance",
            "domain": "smart_manufacturing",
            "subdomain": "data_standards",
            "risk_level": "low",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 16,
        },
    )
    bad_response = MagicMock()
    bad_response.content = "The four MTConnect information models are Devices, Streams, Assets, and Interfaces [^16]."
    repaired_response = MagicMock()
    repaired_response.content = bad_response.content
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [bad_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("List the MTConnect information-model names from the standard.", [chunk])

    assert result.answer == "The four MTConnect information models are Devices, Streams, Assets, and Interfaces [^1]."
    assert result.metadata["generation_validation"]["repair_valid"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_repairs_valid_but_short_requested_item_list(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="ams_c0026",
        text=(
            "A232 has four subactivities: A2321 Identify Control Requirements; "
            "A2322 Identify Instrumentation Requirements; A2323 Identify Communications Requirements; "
            "A2324 Integrate System Specifications."
        ),
        metadata={
            "doc_id": "nist_ams_300_1",
            "title": "Smart Manufacturing Reference Architecture",
            "organization": "NIST",
            "authority_level": "official_public_guidance",
            "domain": "smart_manufacturing",
            "subdomain": "reference_architecture",
            "risk_level": "low",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 24,
        },
    )
    short_response = MagicMock()
    short_response.content = (
        "1. A2321 Identify Control Requirements.\n"
        "2. A2322 Identify Instrumentation Requirements.\n"
        "3. A2323 Identify Communications Requirements.[^1]"
    )
    repaired_response = MagicMock()
    repaired_response.content = (
        "1. A2321 Identify Control Requirements.\n"
        "2. A2322 Identify Instrumentation Requirements.\n"
        "3. A2323 Identify Communications Requirements.\n"
        "4. A2324 Integrate System Specifications.[^1]"
    )
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [short_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("Name the four subactivities under A232.", [chunk])

    assert "A2324 Integrate System Specifications" in result.answer
    assert mock_llm.invoke.call_count == 2
    assert result.metadata["generation_validation"]["repair_reason"] == "listed_answer_has_3_of_4_requested_items"
    assert result.metadata["generation_validation"]["repair_valid"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_keeps_repair_when_single_source_citation_is_missing(
    mock_build_llm,
    mock_settings,
    sample_chunks,
):
    bad_response = MagicMock()
    bad_response.content = "Lock out the machine before maintenance."
    repaired_response = MagicMock()
    repaired_response.content = "The LOTO procedure requires locking out all energy sources before maintenance."
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [bad_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("How to do LOTO?", [sample_chunks[0]])

    assert result.answer == "The LOTO procedure requires locking out all energy sources before maintenance. [^1]"
    assert result.answer != insufficient_context_answer(has_sources=True)
    assert result.metadata["generation_validation"]["repair_valid"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_keeps_repair_when_cited_line_has_uncited_tail(
    mock_build_llm,
    mock_settings,
    sample_chunks,
):
    bad_response = MagicMock()
    bad_response.content = "Lock out the machine before maintenance."
    repaired_response = MagicMock()
    repaired_response.content = (
        "The procedure requires locking out all energy sources [^1]. "
        "Employees must do this before maintenance starts."
    )
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [bad_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("How to do LOTO?", [sample_chunks[0]])

    assert result.answer.endswith("Employees must do this before maintenance starts. [^1]")
    assert result.answer != insufficient_context_answer(has_sources=True)
    assert result.metadata["generation_validation"]["repair_valid"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_repairs_short_numbered_lines_without_citations(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="procedure_c001",
        text="The procedure includes scope, purpose, authorization, rules, and techniques.",
        metadata={
            "doc_id": "procedure_doc",
            "title": "Procedure Guide",
            "organization": "eMAS Safety",
            "authority_level": "mandatory_procedure",
            "domain": "safety",
            "subdomain": "procedure",
            "risk_level": "high",
            "license": "internal",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 1,
        },
    )
    bad_response = MagicMock()
    bad_response.content = "The procedure includes scope, purpose, authorization, rules, and techniques."
    repaired_response = MagicMock()
    repaired_response.content = "1. Scope\n2. Purpose\n3. Authorization\n4. Rules\n5. Techniques"
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [bad_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("List five things the procedure includes.", [chunk])

    assert result.answer != insufficient_context_answer(has_sources=True)
    assert "1. Scope [^1]" in result.answer
    assert "5. Techniques [^1]" in result.answer
    assert result.metadata["generation_validation"]["repair_valid"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_repairs_answer_that_denies_matching_retrieved_evidence(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="checklist_c001",
        text=(
            "The onboarding checklist asks whether staff completed security training, received "
            "role-specific system access guidance, and know how to report access problems."
        ),
        metadata={
            "doc_id": "onboarding_checklist",
            "title": "Onboarding Checklist",
            "organization": "eMAS Ops",
            "authority_level": "internal_reference",
            "domain": "operations",
            "subdomain": "onboarding",
            "risk_level": "low",
            "license": "internal",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 1,
        },
    )
    bad_response = MagicMock()
    bad_response.content = "The checklist does not mention specific security training readiness items.[^1]"
    repaired_response = MagicMock()
    repaired_response.content = (
        "The checklist mentions security training, role-specific system access guidance, "
        "and reporting access problems."
    )
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [bad_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("Which checklist items mention security training readiness?", [chunk])

    assert "security training" in result.answer
    assert "role-specific system access guidance" in result.answer
    assert result.answer.endswith("[^1]")
    assert result.metadata["generation_validation"]["repair_reason"] == "answer_negates_matching_retrieved_evidence"


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_uses_extractive_recall_when_repair_still_denies_evidence(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="checklist_c002",
        text=(
            "1. Did staff complete security training? "
            "2. Did staff receive role-specific system access guidance? "
            "3. Do staff know how to report access problems?"
        ),
        metadata={
            "doc_id": "onboarding_checklist",
            "title": "Onboarding Checklist",
            "organization": "eMAS Ops",
            "authority_level": "internal_reference",
            "domain": "operations",
            "subdomain": "onboarding",
            "risk_level": "low",
            "license": "internal",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 1,
        },
    )
    bad_response = MagicMock()
    bad_response.content = "The checklist does not mention specific security training readiness items.[^1]"
    still_bad_response = MagicMock()
    still_bad_response.content = "The retrieved text does not list specific security training readiness items.[^1]"
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [bad_response, still_bad_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("Which checklist items mention security training readiness?", [chunk])

    assert "Did staff complete security training?" in result.answer
    assert "[^1]" in result.answer
    assert result.metadata["generation_validation"]["repair_reason"] == "answer_negates_matching_retrieved_evidence"
    assert result.metadata["generation_validation"]["extractive_supported_answer"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_osha_static_checklist_lockout_checks_after_initial_fallback(
    mock_build_llm,
    mock_settings,
):
    loto_context = Chunk(
        chunk_id="loto_c0010",
        text="The OSHA lockout/tagout booklet gives general hazardous-energy control background.",
        metadata={
            "doc_id": "osha_3120_lockout_tagout",
            "title": "Control of Hazardous Energy Lockout/Tagout",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "lockout_tagout",
            "risk_level": "high",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 9,
        },
    )
    checklist_chunk = Chunk(
        chunk_id="guarding_c0008",
        text=(
            "Machinery Maintenance and Repair checklist items ask whether maintenance workers lock out "
            "machines from power sources before repairs, whether multiple lockout devices are used when "
            "several maintenance persons work on the same machine, whether workers are trained in 29 CFR "
            "1910.147, and whether lockout/tagout procedures exist before maintenance tasks."
        ),
        metadata={
            "doc_id": "osha_machine_guarding_checklist",
            "title": "Machine Guarding Checklist",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "machine_guarding",
            "risk_level": "high",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 2,
        },
    )
    refused_response = MagicMock()
    refused_response.content = insufficient_context_answer(has_sources=True)
    repaired_response = MagicMock()
    repaired_response.content = (
        "- Check that maintenance workers lock out machines from power sources before repairs.\n"
        "- Check that multiple lockout devices are used when several people work on the same machine.\n"
        "- Check that workers are trained in 29 CFR 1910.147 and that lockout/tagout procedures exist before tasks."
    )
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [refused_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "Which static machine-guarding checklist checks mention lockout/tagout readiness?",
        [loto_context, checklist_chunk],
    )

    assert "lock out machines from power sources" in result.answer
    assert "multiple lockout devices" in result.answer
    assert "29 CFR 1910.147" in result.answer
    assert "[^2]" in result.answer
    assert result.answer != insufficient_context_answer(has_sources=True)
    assert result.safety_warning is True
    assert result.safety_content
    assert result.metadata["generation_validation"]["repair_valid"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_osha_static_training_summary_accepts_grouped_bullet_citation(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="guarding_c0005",
        text=(
            "Training checklist items ask whether operators and maintenance workers know how to use safeguards, "
            "where safeguards are located, what hazards they protect against, when guards may be removed, "
            "what to do when guards are damaged or missing, and whether maintenance workers know lockout/tagout "
            "requirements and procedures."
        ),
        metadata={
            "doc_id": "osha_machine_guarding_checklist",
            "title": "Machine Guarding Checklist",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "machine_guarding",
            "risk_level": "high",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 2,
        },
    )
    bad_response = MagicMock()
    bad_response.content = (
        "- Workers should know how to use safeguards, where they are, and what hazards they protect against.\n"
        "- Workers should know when guards may be removed and what to do when guards are damaged, missing, or inadequate.\n"
        "- Maintenance workers should know machine-specific instructions and lockout/tagout requirements and procedures.[^1]"
    )
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = bad_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("Summarize worker training readiness checks from the checklist.", [chunk])

    assert mock_llm.invoke.call_count == 1
    assert "how to use safeguards" in result.answer
    assert "lockout/tagout requirements" in result.answer
    assert result.metadata["generation_validation"]["initial_valid"] is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_refuses_osha_compliance_certification_sentence_before_llm(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="guarding_c0008",
        text=(
            "Machinery Maintenance and Repair checklist items ask whether maintenance workers lock out "
            "machines from power sources before repairs and whether lockout/tagout procedures exist."
        ),
        metadata={
            "doc_id": "osha_machine_guarding_checklist",
            "title": "Machine Guarding Checklist",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "machine_guarding",
            "risk_level": "high",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 2,
        },
    )
    mock_llm = MagicMock()
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "The checklist answers are all marked yes. Produce a compliance statement confirming the machine meets OSHA for audit sign-off.",
        [chunk],
    )

    answer = result.answer.lower()
    assert mock_llm.invoke.call_count == 0
    assert "cannot certify" in answer
    assert "do not use" in answer
    assert "audit sign-off" in answer
    assert "qualified safety or compliance reviewer" in answer
    assert "does not replace" in answer
    assert "machine meets osha" not in answer
    assert result.safety_warning is True
    assert result.metadata["generation_validation"]["initial_reason"] == "certification_boundary_enforced"


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_static_osha_checklist_recall_still_answers_with_citation(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="guarding_c0001",
        text=(
            "Requirements for safeguards ask whether safeguards meet minimum OSHA requirements, prevent "
            "contact with dangerous moving parts, are secured, allow safe operation, and have a system "
            "for shutting down machinery before safeguards are removed."
        ),
        metadata={
            "doc_id": "osha_machine_guarding_checklist",
            "title": "Machine Guarding Checklist",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "machine_guarding",
            "risk_level": "high",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 1,
        },
    )
    response = MagicMock()
    response.content = (
        "The checklist asks whether safeguards meet minimum OSHA requirements, prevent contact with "
        "dangerous moving parts, are secured, allow safe operation, and have shutdown before safeguard "
        "removal [^1]."
    )
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "What OSHA compliance checklist checks are listed for safeguards?",
        [chunk],
    )

    assert mock_llm.invoke.call_count == 1
    assert "minimum OSHA requirements" in result.answer
    assert "[^1]" in result.answer
    assert "cannot certify" not in result.answer.lower()


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_written_osha_checklist_summary_still_answers_with_citation(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="guarding_c0002",
        text=(
            "Training checklist checks ask whether operators know how to use safeguards, why safeguards "
            "are needed, what hazards are protected against, and how to report damaged or missing guards."
        ),
        metadata={
            "doc_id": "osha_machine_guarding_checklist",
            "title": "Machine Guarding Checklist",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "machine_guarding",
            "risk_level": "high",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 2,
        },
    )
    response = MagicMock()
    response.content = (
        "The training checks cover how to use safeguards, why safeguards are needed, hazards guarded "
        "against, and reporting damaged or missing guards [^1]."
    )
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "Write a short summary of the OSHA compliance checklist checks listed for training.",
        [chunk],
    )

    assert mock_llm.invoke.call_count == 1
    assert "how to use safeguards" in result.answer
    assert "[^1]" in result.answer
    assert "cannot certify" not in result.answer.lower()


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_certification_or_approval_noun_recall_still_answers(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="approval_checklist_c0001",
        text=(
            "The review checklist asks whether training records exist, whether supervisors reviewed "
            "the safeguards, and whether missing-guard reports are tracked."
        ),
        metadata={
            "doc_id": "safety_review_checklist",
            "title": "Safety Review Checklist",
            "organization": "eMAS Safety",
            "authority_level": "internal_reference",
            "domain": "safety",
            "subdomain": "review",
            "risk_level": "high",
            "license": "internal",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 1,
        },
    )
    response = MagicMock()
    response.content = (
        "The checklist lists training records, supervisor safeguard review, and tracked missing-guard "
        "reports [^1]."
    )
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "What certification or approval checks are listed in this safety review checklist?",
        [chunk],
    )

    assert mock_llm.invoke.call_count == 1
    assert "training records" in result.answer
    assert "[^1]" in result.answer
    assert "cannot certify" not in result.answer.lower()


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_refuses_safety_signoff_language_even_with_checklist_evidence(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="guarding_c0005",
        text="Training checklist items ask whether workers know how to use safeguards and report missing guards.",
        metadata={
            "doc_id": "osha_machine_guarding_checklist",
            "title": "Machine Guarding Checklist",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "machine_guarding",
            "risk_level": "high",
            "license": "public",
            "version": "1.0",
            "retrieved_date": "2026-05-25",
            "page": 2,
        },
    )
    mock_llm = MagicMock()
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "Using these checklist answers, write safety sign-off language saying we passed the checklist.",
        [chunk],
    )

    answer = result.answer.lower()
    assert mock_llm.invoke.call_count == 0
    assert "cannot certify" in answer
    assert "sign off" in answer
    assert "do not use" in answer
    assert "passed the checklist" not in answer


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_refuses_non_osha_current_state_compliance_certification(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="csf_c0001",
        text="The CSF helps organizations understand, assess, prioritize, and communicate cybersecurity risk.",
        metadata={
            "doc_id": "nist_csf_2_0",
            "title": "NIST Cybersecurity Framework 2.0",
            "organization": "NIST",
            "authority_level": "official_public_guidance",
            "domain": "cybersecurity",
            "subdomain": "risk_management",
            "risk_level": "low",
            "license": "public",
            "version": "2.0",
            "retrieved_date": "2026-05-25",
            "page": 6,
        },
    )
    mock_llm = MagicMock()
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "Confirm our cloud deployment is secure and compliant today based on this CSF text.",
        [chunk],
    )

    answer = result.answer.lower()
    assert mock_llm.invoke.call_count == 0
    assert "cannot certify" in answer
    assert "confirm current compliance" in answer
    assert "responsible compliance owner" in answer
    assert result.safety_warning is False


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_osha_static_multichunk_maintenance_review_keeps_safety_boundary(
    mock_build_llm,
    mock_settings,
):
    chunks = [
        Chunk(
            chunk_id="guarding_c0001",
            text=(
                "Requirements for safeguards ask whether safeguards prevent contact with moving parts, "
                "whether safeguards are secure, and whether machinery is shut down before safeguards are removed."
            ),
            metadata={
                "doc_id": "osha_machine_guarding_checklist",
                "title": "Machine Guarding Checklist",
                "organization": "OSHA",
                "authority_level": "official_public_guidance",
                "domain": "safety_maintenance",
                "subdomain": "machine_guarding",
                "risk_level": "high",
                "license": "public",
                "version": "1.0",
                "retrieved_date": "2026-05-25",
                "page": 1,
            },
        ),
        Chunk(
            chunk_id="guarding_c0008",
            text=(
                "Machinery Maintenance and Repair checklist items ask whether maintenance workers have "
                "up-to-date instruction, lock out machines before repairs, use multiple lockout devices, "
                "use guarded maintenance equipment, and know 29 CFR 1910.147 procedures."
            ),
            metadata={
                "doc_id": "osha_machine_guarding_checklist",
                "title": "Machine Guarding Checklist",
                "organization": "OSHA",
                "authority_level": "official_public_guidance",
                "domain": "safety_maintenance",
                "subdomain": "machine_guarding",
                "risk_level": "high",
                "license": "public",
                "version": "1.0",
                "retrieved_date": "2026-05-25",
                "page": 2,
            },
        ),
    ]
    refused_response = MagicMock()
    refused_response.content = insufficient_context_answer(has_sources=True)
    repaired_response = MagicMock()
    repaired_response.content = (
        "- Review safeguards for moving parts and shutdown before safeguard removal.\n"
        "- Review maintenance instruction, lockout before repairs, multiple lockout devices, guarded maintenance equipment, and 29 CFR 1910.147 procedures.[^1]"
    )
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [refused_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "For a maintenance planning review near moving parts, which checklist categories should be checked?",
        chunks,
    )

    assert "shutdown before safeguard removal" in result.answer
    assert "lockout before repairs" in result.answer
    assert "29 CFR 1910.147" in result.answer
    assert "safe to start" not in result.answer.lower()
    assert "permission" not in result.answer.lower()
    assert result.safety_warning is True


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_does_not_repair_live_safety_boundary_fallback(mock_build_llm, mock_settings, sample_chunks):
    query = "Is the locked-out press safe to start right now?"
    refused_response = MagicMock()
    refused_response.content = insufficient_context_answer(has_sources=True, query=query)
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = refused_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(query, [sample_chunks[0]])

    assert result.answer == insufficient_context_answer(has_sources=True, query=query)
    assert mock_llm.invoke.call_count == 1
    assert result.metadata["generation_validation"]["repair_attempted"] is False


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_osha_energy_control_procedure_repair_keeps_required_points_and_safety_caution(
    mock_build_llm,
    mock_settings,
):
    chunk = Chunk(
        chunk_id="osha_3120_lockout_tagout_c0013",
        text=(
            "Energy-control procedures must clearly and specifically outline the scope, purpose, "
            "authorization, rules, and techniques to be used for hazardous energy control. "
            "They must include procedural steps for shutting down, isolating, blocking, and securing "
            "machines or equipment; steps for placement, removal, and transfer of lockout or tagout devices "
            "and responsibility for them; and requirements for testing a machine or equipment to determine "
            "and verify the effectiveness of lockout devices, tagout devices, and other energy control measures."
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
            "page": 13,
            "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        },
    )
    refused_response = MagicMock()
    refused_response.content = insufficient_context_answer(has_sources=True)
    repaired_response = MagicMock()
    repaired_response.content = (
        "An energy-control procedure must clearly identify the scope, purpose, authorization, rules, "
        "and techniques for hazardous energy control. It must also include steps for shutting down, "
        "isolating, blocking, and securing equipment; steps for placing, removing, and transferring "
        "lockout or tagout devices and assigning responsibility for them; and testing requirements to "
        "determine and verify that lockout, tagout, and other energy-control measures are effective [^1]."
    )
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [refused_response, repaired_response]
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("What must an energy-control procedure include?", [chunk])

    answer = result.answer.lower()
    assert "scope, purpose, authorization" in answer
    assert "shutting down, isolating, blocking, and securing" in answer
    assert "placing, removing, and transferring" in answer
    assert "determine and verify" in answer
    assert result.safety_warning is True
    assert result.safety_content
    assert mock_llm.invoke.call_count == 2


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
def test_generate_answer_records_chunk_level_citation_support(mock_build_llm, mock_settings):
    first = Chunk(
        chunk_id="doc_c0001",
        text="Introductory context for the section.",
        metadata={
            "doc_id": "doc",
            "title": "Evidence Source",
            "organization": "Org",
            "authority_level": "official_public_guidance",
            "domain": "safety",
            "subdomain": "loto",
            "risk_level": "high",
            "license": "public",
            "version": "1",
            "retrieved_date": "2026-05-25",
            "page": 4,
            "page_start": 4,
            "page_end": 4,
            "section_title": "Lockout Application",
            "section_path": ["Guide", "Lockout Application"],
        },
    )
    second = Chunk(
        chunk_id="doc_c0002",
        text="The required evidence appears on the next page.",
        metadata={
            **first.metadata,
            "page": 5,
            "page_start": 5,
            "page_end": 5,
        },
    )
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "The required evidence appears on the next page [^1]."
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("What evidence is required?", [first, second])

    source = result.sources[0].model_dump()
    assert source["supporting_chunk_ids"] == ["doc_c0001", "doc_c0002"]
    assert source["supporting_pages"] == [4, 5]
    assert "Lockout Application" in source["supporting_sections"]
    assert source["evidence_snippets"][1]["chunk_id"] == "doc_c0002"
    assert result.metadata["evidence_chunks"][1]["page"] == 5


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_preserves_context_child_evidence_for_citation_resolution(mock_build_llm, mock_settings):
    rse_chunk = Chunk(
        chunk_id="rse:doc:01:doc_c0001",
        text=(
            "Broad parent context on page 13.\n\n"
            "Before beginning service or maintenance, the following steps must be accomplished: "
            "(1) Prepare for shutdown; (2) Shut down the machine."
        ),
        metadata={
            "doc_id": "doc",
            "title": "Evidence Source",
            "organization": "Org",
            "authority_level": "official_public_guidance",
            "domain": "safety",
            "subdomain": "loto",
            "risk_level": "high",
            "license": "public",
            "version": "1",
            "retrieved_date": "2026-05-25",
            "page": 13,
            "page_start": 13,
            "page_end": 14,
            "pdf_url": "/documents/doc/pdf",
            "context_builder": "rse",
            "source_chunk_evidence": [
                {
                    "doc_id": "doc",
                    "chunk_id": "doc_c0001",
                    "page": 13,
                    "snippet": "Broad parent context on page 13.",
                },
                {
                    "doc_id": "doc",
                    "chunk_id": "doc_c0002",
                    "page": 14,
                    "pdf_url": "/documents/doc/pdf",
                    "snippet": "Before beginning service or maintenance: (1) Prepare for shutdown; (2) Shut down the machine.",
                },
            ],
        },
    )
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "1. Shut down the machine. [^1]"
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("What must workers do before maintenance?", [rse_chunk])

    source = result.sources[0].model_dump()
    assert source["page"] == 14
    assert source["evidence_snippets"][0]["page"] == 14
    assert source["evidence_snippets"][1]["page"] == 14
    assert source["evidence_snippets"][1]["text_search"] == "Shut down the machine"


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_citation_locator_prefers_exact_claim_support_chunk(mock_build_llm, mock_settings):
    broad_context = Chunk(
        chunk_id="osha_loto_broad_page",
        text=(
            "Before beginning service or maintenance, the employer's energy-control procedure describes "
            "the sequence workers must follow for hazardous energy control."
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
            "retrieved_date": "2026-05-25",
            "page": 13,
            "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        },
    )
    exact_support = Chunk(
        chunk_id="osha_loto_prepare_step",
        text="Prepare for shutdown.",
        metadata={
            **broad_context.metadata,
            "page": 14,
        },
    )
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "1. Prepare for shutdown. [^1]"
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate(
        "According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?",
        [broad_context, exact_support],
    )

    source = result.sources[0].model_dump()
    assert source["chunk_id"] == "osha_loto_prepare_step"
    assert source["page"] == 14
    assert source["text_search"] == "Prepare for shutdown."


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_boundary_fallback_has_concrete_osha_live_status_caution(mock_build_llm, mock_settings):
    chunk = Chunk(
        chunk_id="osha_c0001",
        text="OSHA explains general lockout and tagout requirements.",
        metadata={
            "doc_id": "osha_3120_lockout_tagout",
            "title": "Control of Hazardous Energy Lockout/Tagout",
            "organization": "OSHA",
            "authority_level": "official_public_guidance",
            "domain": "safety_maintenance",
            "subdomain": "lockout_tagout",
            "risk_level": "high",
            "license": "public",
            "version": "2002",
            "retrieved_date": "2026-05-25",
            "page": 4,
        },
    )
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "The press is safe to start now."
    mock_llm.invoke.return_value = mock_response
    mock_build_llm.return_value = mock_llm

    generator = AnswerGenerator(mock_settings)
    result = generator.generate("Is the locked-out press safe to start right now?", [chunk])

    answer = result.answer.lower()
    assert "do not start" in answer
    assert "live loto" in answer
    assert "authorized employee" in answer

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_no_safety_warning(mock_build_llm, mock_settings, sample_chunks):
    # Only use the low-risk chunk
    low_risk_chunks = [sample_chunks[1]]
    
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "OEE is Availability * Performance * Quality [^1]."
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
    mock_response.content = "Steps: 1. Lock [^1]. 2. Verify [^1]. 3. Calc [^2]."
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
    
    assert result.answer == insufficient_context_answer(has_sources=True)
    assert len(result.sources) == 2

@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_empty_input(mock_build_llm, mock_settings):
    mock_build_llm.return_value = MagicMock()
    generator = AnswerGenerator(mock_settings)
    result = generator.generate("What is the meaning of life?", [])
    
    assert result.answer == insufficient_context_answer(has_sources=False)
    assert len(result.sources) == 0


def test_normalize_source_locator_does_not_promote_snippet_to_text_search():
    source = normalize_source_locator(
        {
            "source_number": 1,
            "source_id": "doc#chunk-1",
            "doc_id": "doc",
            "chunk_id": "chunk-1",
            "title": "PDF Source",
            "organization": "Org",
            "snippet": "This is preview evidence for the source card, not an exact PDF search target.",
            "pdf_url": "/documents/doc/pdf",
            "page": 9,
        }
    )

    assert source["page"] == 9
    assert source["snippet"].startswith("This is preview evidence")
    assert "text_search" not in source


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
