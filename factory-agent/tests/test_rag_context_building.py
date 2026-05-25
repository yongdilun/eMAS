from factory_agent.rag.context_building import (
    RAGContextBuilder,
    light_extractive_compress,
    rewrite_query_for_retrieval,
)
from factory_agent.rag.schemas import Chunk, ScoredChunk


class FakeRetriever:
    def __init__(self, chunks):
        self.chunks = chunks

    def get_chunks_for_doc(self, doc_id):
        return list(self.chunks)


def _chunk(doc_id, index, text, *, section="Parent Section", section_path=None, page=1):
    return Chunk(
        chunk_id=f"{doc_id}_c{index:04d}",
        text=f"[Section: {section}] {text}",
        metadata={
            "doc_id": doc_id,
            "chunk_index": index,
            "title": "Test Source",
            "organization": "Test Org",
            "authority_level": "official_public_guidance",
            "section_title": section,
            "section_path": section_path or f"{doc_id} > {section}",
            "page": page,
            "page_start": page,
            "page_end": page,
        },
    )


def _scored(chunk, score=0.8):
    return ScoredChunk(chunk=chunk, fusion_score=score, boosted_score=score)


def test_small_to_big_expands_selected_chunk_to_parent_section():
    chunks = [
        _chunk("doc", 0, "Opening context for the parent section."),
        _chunk("doc", 1, "The selected calibration sentence is here."),
        _chunk("doc", 2, "Verification evidence remains in the same parent section."),
        _chunk("doc", 3, "A different section should stay out.", section="Other"),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks))

    result = builder.build(
        query="calibration verification",
        selected_chunks=[chunks[1]],
        candidates=[_scored(chunks[1])],
        context_builder="small_to_big",
        compression="none",
    )

    text = result.chunks[0].text
    assert "Opening context for the parent section." in text
    assert "The selected calibration sentence is here." in text
    assert "Verification evidence remains in the same parent section." in text
    assert "A different section should stay out." not in text
    assert result.metadata["segments"][0]["child_chunk_ids"] == ["doc_c0001"]
    assert result.metadata["segments"][0]["token_estimate_after_expansion"] > result.metadata["segments"][0]["token_estimate_before_expansion"]


def test_small_to_big_long_parent_keeps_heading_and_matching_spans():
    chunks = [
        _chunk("doc", 0, "Background material that does not answer the query."),
        _chunk("doc", 1, "The selected calibration span explains the required evidence."),
        _chunk("doc", 2, "More unrelated body text fills the large section."),
        _chunk("doc", 3, "Verification records are the matching support span."),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks), small_to_big_max_tokens=35)

    result = builder.build(
        query="calibration verification evidence",
        selected_chunks=[chunks[1]],
        candidates=[_scored(chunks[1])],
        context_builder="small_to_big",
        compression="none",
    )

    text = result.chunks[0].text
    assert text.startswith("[Section: Parent Section]")
    assert "selected calibration span" in text
    assert "Verification records" in text
    assert result.metadata["segments"][0]["token_estimate_after_expansion"] <= 35


def test_rse_joins_same_doc_same_section_neighbors_with_plus_minus_two_limit():
    chunks = [
        _chunk("doc", 0, "chunk zero outside the RSE window."),
        _chunk("doc", 1, "chunk one inside the RSE window."),
        _chunk("doc", 2, "chunk two inside the RSE window."),
        _chunk("doc", 3, "seed chunk about lockout."),
        _chunk("doc", 4, "chunk four inside the RSE window."),
        _chunk("doc", 5, "chunk five inside the RSE window."),
        _chunk("doc", 6, "chunk six outside the RSE window."),
        _chunk("doc", 7, "other section neighbor excluded.", section="Other"),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks), rse_max_window=2)

    result = builder.build(
        query="lockout",
        selected_chunks=[chunks[3]],
        candidates=[_scored(chunks[3])],
        context_builder="rse",
        compression="none",
    )

    text = result.chunks[0].text
    assert "chunk zero outside" not in text
    assert "chunk one inside" in text
    assert "chunk two inside" in text
    assert "seed chunk about lockout" in text
    assert "chunk four inside" in text
    assert "chunk five inside" in text
    assert "chunk six outside" not in text
    assert "other section neighbor excluded" not in text


def test_rse_includes_sibling_sections_for_group_list_queries():
    chunks = [
        _chunk(
            "doc",
            1,
            "A2321 identifies control requirements.",
            section="A2321",
            section_path=["Doc", "A232", "A2321"],
        ),
        _chunk(
            "doc",
            2,
            "A2322 identifies instrumentation requirements.",
            section="A2322",
            section_path=["Doc", "A232", "A2322"],
        ),
        _chunk(
            "doc",
            3,
            "A2323 identifies communications requirements.",
            section="A2323",
            section_path=["Doc", "A232", "A2323"],
        ),
        _chunk(
            "doc",
            4,
            "A2324 integrates system specifications.",
            section="A2324",
            section_path=["Doc", "A232", "A2324"],
        ),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks), rse_max_window=3)

    result = builder.build(
        query="What subactivities are listed under A2321-A2324?",
        selected_chunks=[chunks[3]],
        candidates=[_scored(chunks[3])],
        context_builder="rse",
        compression="none",
    )

    text = result.chunks[0].text
    assert "A2321 identifies control requirements." in text
    assert "A2322 identifies instrumentation requirements." in text
    assert "A2323 identifies communications requirements." in text
    assert "A2324 integrates system specifications." in text


def test_rse_does_not_cross_doc_id():
    chunks = [
        _chunk("doc-a", 0, "same doc previous chunk."),
        _chunk("doc-a", 1, "same doc seed chunk."),
        _chunk("doc-b", 2, "different doc chunk must not join."),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks), rse_max_window=2)

    result = builder.build(
        query="seed",
        selected_chunks=[chunks[1]],
        candidates=[_scored(chunks[1])],
        context_builder="rse",
        compression="none",
    )

    text = result.chunks[0].text
    assert "same doc previous chunk" in text
    assert "same doc seed chunk" in text
    assert "different doc chunk must not join" not in text


def test_rewrite_query_preserves_original_key_terms_when_adding_resource_cues():
    rewritten = rewrite_query_for_retrieval(
        "How do CSF web reference materials differ from a fixed PDF publication?"
    )

    focus = rewritten.split("Retrieval focus:", 1)[1].lower()
    assert "cybersecurity framework" in focus
    assert "web" in focus
    assert "reference" in focus
    assert "material" in focus
    assert "fix" in focus
    assert "pdf" in focus
    assert "references" in focus
    assert "implementation guides" in focus


def test_rewrite_query_adds_resource_cues_for_adjacent_wording():
    rewritten = rewrite_query_for_retrieval("What supporting web material supplements the CSF?")

    focus = rewritten.split("Retrieval focus:", 1)[1].lower()
    assert "support" in focus
    assert "web" in focus
    assert "material" in focus
    assert "supplemental resources" in focus
    assert "machine-readable" in focus


def test_rewrite_query_adds_standards_and_scope_cues_from_intent_terms():
    rewritten = rewrite_query_for_retrieval(
        "Which manufacturing processes and data formats are included or excluded by the recommendations?"
    )

    focus = rewritten.split("Retrieval focus:", 1)[1].lower()
    assert "process" in focus
    assert "format" in focus
    assert "recommendation" in focus
    assert "in scope out of scope" in focus
    assert "standards open consensus" in focus


def test_light_compression_is_extractive_and_preserves_sentence_order():
    text = (
        "[Section: Lockout]\n"
        "Background sentence remains optional. "
        "Lockout devices isolate hazardous energy. "
        "Verification confirms the equipment is isolated. "
        "Unrelated filler sentence is not important. "
        "Employees must be notified before reenergizing."
    )

    result = light_extractive_compress(
        text,
        query="lockout verification employees",
        max_tokens=28,
        target_ratio=0.5,
    )

    assert result.compression_ran is True
    assert result.text.startswith("[Section: Lockout]")

    original_body = text.split("\n", 1)[1]
    compressed_body = result.text.split("\n", 1)[1]
    compressed_sentences = [part.strip() for part in compressed_body.split(".") if part.strip()]
    positions = []
    for sentence in compressed_sentences:
        sentence_text = f"{sentence}."
        assert sentence_text in original_body
        positions.append(original_body.index(sentence_text))
    assert positions == sorted(positions)


def test_context_builder_metadata_preserves_source_chunk_evidence_for_audit():
    chunks = [
        _chunk("doc", 1, "The selected lockout sentence is here.", page=7),
        _chunk("doc", 2, "Verification support remains nearby.", page=8),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks))

    result = builder.build(
        query="lockout verification",
        selected_chunks=[chunks[0]],
        candidates=[_scored(chunks[0])],
        context_builder="small_to_big",
        compression="none",
    )

    segment = result.metadata["segments"][0]
    assert segment["page_start"] == 7
    assert segment["page_end"] == 8
    assert segment["source_chunk_evidence"][0]["chunk_id"] == "doc_c0001"
    assert segment["source_chunk_evidence"][1]["page"] == 8
    assert "Verification support" in segment["source_chunk_evidence"][1]["snippet"]


def test_light_compression_preserves_required_child_evidence_from_extra_text():
    text = (
        "[Section: Lockout]\n"
        "General background about machines. "
        "This query-matching sentence talks about lockout. "
        "The required permit evidence must be retained. "
        "More filler about unrelated administration. "
        "Final filler sentence."
    )

    result = light_extractive_compress(
        text,
        query="lockout",
        max_tokens=35,
        target_ratio=0.35,
        extra_text="required permit evidence",
    )

    assert result.compression_ran is True
    assert "query-matching sentence talks about lockout" in result.text
    assert "required permit evidence must be retained" in result.text
