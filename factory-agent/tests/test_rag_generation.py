import pytest
import json
from unittest.mock import MagicMock, patch
from factory_agent.rag.schemas import Chunk, ScoredChunk, AnswerResult
from factory_agent.rag.generation import AnswerGenerator, SAFETY_WARNING_BLOCK
from factory_agent.rag.source_metadata import insufficient_context_answer, normalize_source_locators

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
            "Before beginning service or maintenance, the following steps must be accomplished in sequence: "
            "(1) Prepare for shutdown; (2) Shut down the machine; (3) Disconnect or isolate the machine "
            "from the energy sources."
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

    assert result.answer == response.content
    assert mock_llm.invoke.call_count == 1
    prompt = mock_llm.invoke.call_args.args[0][1].content
    assert "Cite coherent answer groups, not every sentence" in prompt
    assert "Group adjacent sentences or related procedure steps under one citation marker" in prompt
    assert "cite the whole lead-in plus list as one grouped procedure block" in prompt
    assert "Do not scatter the same citation after every sentence" in prompt
    assert "If no supported answer remains, output exactly the insufficient-context sentence" in prompt
    assert "If relevant evidence is split across multiple source chunks" in prompt
    assert "For section summaries or multi-part questions" in prompt
    assert "For safety procedures, answer from the retrieved procedure evidence" in prompt
    assert result.sources[0].source_number == 1
    assert result.sources[0].doc_id == "osha_3120_lockout_tagout"


@patch("factory_agent.rag.generation.build_rag_answer_chat_model")
def test_generate_answer_preserves_grouped_loto_procedure_with_long_intro(mock_build_llm, mock_settings):
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

    assert result.answer == answer
    assert result.answer != insufficient_context_answer(has_sources=True)
    assert result.sources[0].source_number == 1


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
