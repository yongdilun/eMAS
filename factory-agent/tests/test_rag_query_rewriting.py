from factory_agent.rag.query_rewriting import build_corpus_aware_query_rewrite
from factory_agent.rag.schemas import Chunk


def _source_doc(
    doc_id,
    title,
    *,
    use_for=None,
    related_entities=None,
    domain="test_domain",
    subdomain="test_subdomain",
):
    return {
        "doc_id": doc_id,
        "title": title,
        "organization": "Test Authority",
        "domain": domain,
        "subdomain": subdomain,
        "authority_level": "official_public_guidance",
        "use_for": use_for or [],
        "related_entities": related_entities or [],
    }


def _chunk(doc_id, index, text, *, section="Overview", extra_metadata=None):
    metadata = {
        "doc_id": doc_id,
        "title": "Indexed Test Source",
        "section_title": section,
        "section_path": ["Indexed Test Source", section],
        "domain": "test_domain",
        "subdomain": "test_subdomain",
        "use_for": ["explain indexed test source"],
        "related_entities": [],
        "chunk_index": index,
    }
    metadata.update(extra_metadata or {})
    return Chunk(
        chunk_id=f"{doc_id}_c{index:04d}",
        text=text,
        metadata=metadata,
    )


def test_corpus_rewrite_expands_acronym_and_punctuation_variants_from_metadata():
    docs = [
        _source_doc(
            "quality_doc",
            "Quality Data Package",
            use_for=["explain quality data package", "explain inspection result archive"],
            domain="quality_records",
            subdomain="inspection_archives",
        )
    ]

    acronym = build_corpus_aware_query_rewrite("QDP basics", source_documents=docs)
    punctuated = build_corpus_aware_query_rewrite("quality-data package basics", source_documents=docs)

    assert "quality data package" in acronym.expanded_query.lower()
    assert "inspection result archive" in acronym.expanded_query.lower()
    assert "inspection result archive" in punctuated.expanded_query.lower()
    assert any(source["doc_id"] == "quality_doc" for source in punctuated.expansion_sources)
    assert acronym.expansion_terms
    assert acronym.expansion_sources
    assert acronym.confidence > 0


def test_corpus_rewrite_moves_unseen_wording_toward_metadata_vocabulary_without_answer_facts():
    docs = [
        _source_doc(
            "startup_readiness",
            "Service Startup Readiness Guide",
            use_for=[
                "explain startup readiness verification",
                "explain service restart before maintenance handoff",
                "explain cold start inspection",
            ],
            domain="operations",
            subdomain="startup_readiness",
        )
    ]

    result = build_corpus_aware_query_rewrite(
        "cold start inspection steps",
        source_documents=docs,
    )

    expanded = result.expanded_query.lower()
    assert "startup readiness verification" in expanded
    assert "service restart" in expanded
    assert "cold start inspection steps" in expanded
    assert "open ticket notify owner" not in expanded


def test_corpus_rewrite_uses_indexed_section_and_use_for_metadata():
    chunks = [
        _chunk(
            "calibration",
            3,
            "The body text is intentionally generic.",
            section="Verification Checklist",
            extra_metadata={
                "title": "Sensor Calibration Records",
                "use_for": ["explain traceable calibration evidence"],
                "related_entities": ["calibration_record", "traceable_evidence"],
            },
        )
    ]

    result = build_corpus_aware_query_rewrite(
        "traceable evidence review",
        indexed_chunks=chunks,
    )

    expanded = result.expanded_query.lower()
    assert "sensor calibration records" in expanded
    assert "verification checklist" in expanded
    assert any(source["field"] == "section_title" for source in result.expansion_sources)


def test_corpus_rewrite_keeps_specific_heading_queries_from_absorbing_sibling_metadata():
    docs = [
        _source_doc(
            "equipment_safety",
            "Equipment Safety Audit Manual",
            use_for=[
                "explain mechanical hazard checks",
                "explain operator training checks",
                "explain equipment maintenance shutdown",
            ],
            domain="safety_operations",
            subdomain="equipment_audits",
        ),
        _source_doc(
            "maintenance_planning",
            "Maintenance Planning Guide",
            use_for=[
                "explain equipment maintenance shutdown",
                "explain maintenance handoff planning",
            ],
            related_entities=["equipment"],
            domain="operations",
            subdomain="maintenance_planning",
        )
    ]
    chunks = [
        _chunk(
            "equipment_safety",
            1,
            "The section covers electrical hazards for equipment audit reviewers.",
            section="Electric Hazards",
        ),
        _chunk(
            "equipment_safety",
            2,
            "The section covers mechanical hazards for equipment audit reviewers.",
            section="Mechanical Hazards",
        ),
        _chunk(
            "equipment_safety",
            3,
            "The section covers training checks for equipment audit reviewers.",
            section="Operator Training",
        )
    ]

    result = build_corpus_aware_query_rewrite(
        "Which electrical hazard checks appear on the equipment safety checklist?",
        source_documents=docs,
        indexed_chunks=chunks,
    )

    expanded = result.expanded_query.lower()
    assert "electric hazards" in expanded
    assert "mechanical hazards" not in expanded
    assert "operator training" not in expanded
    assert "mechanical hazard checks" not in expanded
    assert "operator training checks" not in expanded
    assert "equipment maintenance shutdown" not in expanded
    assert all(source["doc_id"] != "maintenance_planning" for source in result.expansion_sources)


def test_corpus_rewrite_generalizes_specific_heading_anchor_to_unrelated_review_domains():
    docs = [
        _source_doc(
            "system_review",
            "Information System Review Guide",
            use_for=[
                "explain incident recovery reviews",
                "explain service continuity planning",
                "explain data retention schedules",
            ],
            domain="information_governance",
            subdomain="system_reviews",
        )
    ]
    chunks = [
        _chunk(
            "system_review",
            2,
            "The section covers access controls for system review records.",
            section="Access Control Checks",
        )
    ]

    result = build_corpus_aware_query_rewrite(
        "Which access control checks are listed for the system review?",
        source_documents=docs,
        indexed_chunks=chunks,
    )

    expanded = result.expanded_query.lower()
    assert "access control checks" in expanded
    assert "incident recovery reviews" not in expanded
    assert "service continuity planning" not in expanded
    assert "data retention schedules" not in expanded


def test_corpus_rewrite_rejects_unrelated_metadata():
    docs = [
        _source_doc(
            "quality_doc",
            "Quality Data Package",
            use_for=["explain quality data package", "explain inspection result archive"],
            domain="quality_records",
            subdomain="inspection_archives",
        )
    ]

    result = build_corpus_aware_query_rewrite(
        "payroll cafeteria menu",
        source_documents=docs,
    )

    assert result.expansion_terms == []
    assert result.expanded_query == "payroll cafeteria menu"
    assert result.confidence == 0


def test_corpus_rewrite_does_not_match_unrelated_docs_on_question_filler_words():
    docs = [
        _source_doc(
            "production_doc",
            "Production System Functional Model",
            use_for=["explain production activities and resource components"],
            domain="manufacturing",
            subdomain="production_model",
        ),
        _source_doc(
            "equipment_state_doc",
            "Equipment Idle-State Guide",
            use_for=["explain idle equipment safety"],
            domain="safety",
            subdomain="equipment_state",
        ),
    ]

    result = build_corpus_aware_query_rewrite(
        "press equipment is idle, can I start it if no one is around?",
        source_documents=docs,
    )

    expanded = result.expanded_query.lower()
    assert "idle equipment safety" in expanded
    assert "production activities" not in expanded
    assert all(source["doc_id"] != "production_doc" for source in result.expansion_sources)


def test_corpus_rewrite_requires_real_metadata_overlap_not_only_question_shape():
    docs = [
        _source_doc(
            "unrelated_questions",
            "Frequently Asked Questions",
            use_for=["explain what users can do with administrative reports"],
            domain="office",
            subdomain="reports",
        )
    ]

    result = build_corpus_aware_query_rewrite(
        "what does alpha calibration mean?",
        source_documents=docs,
    )

    assert result.expansion_terms == []


def test_corpus_rewrite_does_not_treat_two_letter_filler_as_acronym_match():
    docs = [
        _source_doc(
            "interface_doc",
            "Interface Standards",
            use_for=["explain interface standards"],
            domain="engineering",
            subdomain="interfaces",
        )
    ]

    result = build_corpus_aware_query_rewrite(
        "is it ready if no one objects",
        source_documents=docs,
    )

    assert result.expansion_terms == []
