from factory_agent.rag.context_building import (
    BudgetedRSESettings,
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


def _chunk(doc_id, index, text, *, section="Parent Section", section_path=None, page=1, extra_metadata=None):
    metadata = {
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
    }
    metadata.update(extra_metadata or {})
    return Chunk(
        chunk_id=f"{doc_id}_c{index:04d}",
        text=f"[Section: {section}] {text}",
        metadata=metadata,
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


def test_rse_preserves_top_retrieved_related_candidate_skipped_by_rerank():
    chunks = [
        _chunk(
            "csf",
            10,
            "DETECT finds and analyzes adverse cybersecurity events and supports response and recovery.",
            section="DE",
            page=9,
        ),
        _chunk(
            "csf",
            11,
            "The Functions should be addressed concurrently; RESPOND and RECOVER should be ready at all times.",
            section="Functions",
            page=10,
        ),
        _chunk(
            "csf",
            40,
            "RECOVER restores assets and operations affected by a cybersecurity incident and communicates recovery progress.",
            section="RC",
            page=27,
        ),
        _chunk(
            "csf",
            50,
            "There are six CSF Functions: Govern, Identify, Protect, Detect, Respond, and Recover.",
            section="Glossary",
            page=31,
        ),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks), rse_max_window=0)

    result = builder.build(
        query="How do the CSF Functions DETECT, RESPOND, and RECOVER fit together during cybersecurity incidents?",
        selected_chunks=[chunks[0], chunks[1], chunks[3]],
        candidates=[_scored(chunks[0]), _scored(chunks[2]), _scored(chunks[1]), _scored(chunks[3])],
        context_builder="rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "RECOVER restores assets and operations" in text
    assert "cybersecurity incident" in text


def test_rse_preserves_rank_four_related_candidate_for_checklist_review():
    chunks = [
        _chunk(
            "guide",
            1,
            "Maintenance checklist items mention preparation before repairs.",
            section="Maintenance and Repair",
            page=2,
        ),
        _chunk(
            "guide",
            2,
            "Checklist items mention equipment isolation before removal.",
            section="Requirements",
            page=1,
        ),
        _chunk(
            "guide",
            3,
            "Checklist heading filler.",
            section="Checklist",
            page=1,
        ),
        _chunk(
            "guide",
            4,
            "Training checklist items mention maintenance workers knowing how the controls work.",
            section="Training",
            page=2,
        ),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks), rse_max_window=0)

    result = builder.build(
        query="For a maintenance review, which checklist areas should be checked?",
        selected_chunks=[chunks[0], chunks[1], chunks[2]],
        candidates=[
            _scored(chunks[0]),
            _scored(chunks[1]),
            _scored(chunks[2]),
            _scored(chunks[3]),
        ],
        context_builder="rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "Training checklist items" in text
    assert "maintenance workers" in text


def test_legacy_rse_preserves_top_related_candidate_without_budgeted_cross_doc_gate():
    primary = _chunk(
        "primary",
        1,
        "The section summarizes calibration readiness checks and release review responsibilities.",
        section="Readiness",
    )
    related = _chunk(
        "related",
        1,
        "The related appendix summarizes calibration readiness checks and release review responsibilities.",
        section="Related Appendix",
    )
    builder = RAGContextBuilder(FakeRetriever([primary, related]), rse_max_window=0)

    result = builder.build(
        query="Summarize calibration readiness checks and release review responsibilities.",
        selected_chunks=[primary],
        candidates=[_scored(primary), _scored(related)],
        context_builder="rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "related appendix summarizes calibration readiness" in text


def test_budgeted_rse_keeps_cross_doc_preservation_gate_when_candidate_adds_no_query_terms():
    primary = _chunk(
        "primary",
        1,
        "The section summarizes calibration readiness checks and release review responsibilities.",
        section="Readiness",
    )
    related = _chunk(
        "related",
        1,
        "The related appendix summarizes calibration readiness checks and release review responsibilities.",
        section="Related Appendix",
    )
    builder = RAGContextBuilder(FakeRetriever([primary, related]))

    result = builder.build(
        query="Summarize calibration readiness checks and release review responsibilities.",
        selected_chunks=[primary],
        candidates=[_scored(primary), _scored(related)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "related appendix summarizes calibration readiness" not in text


def test_budgeted_rse_prioritizes_top_source_whose_title_matches_checklist_recall():
    procedure = _chunk(
        "procedure",
        10,
        (
            "Before beginning a release, complete these steps in sequence: "
            "open the change record, notify reviewers, freeze the deployment window, and apply the approval marker."
        ),
        section="Release Procedure",
        extra_metadata={"title": "Release Control Procedure"},
    )
    checklist = _chunk(
        "checklist",
        8,
        (
            "Deployment inspection checklist items ask whether owners confirmed rollback contacts before rollout "
            "and whether multiple approvals are present when several teams share a release."
        ),
        section="Deployment Readiness",
        extra_metadata={"title": "Deployment Inspection Checklist"},
    )
    builder = RAGContextBuilder(FakeRetriever([procedure, checklist]))

    result = builder.build(
        query="What release-readiness checks are listed in the deployment inspection checklist?",
        selected_chunks=[procedure, checklist],
        candidates=[_scored(checklist, score=0.8), _scored(procedure, score=1.4)],
        context_builder="budgeted_rse",
        compression="none",
    )

    assert result.chunks[0].metadata["title"] == "Deployment Inspection Checklist"


def test_budgeted_rse_prioritizes_top_source_whose_title_matches_adjacent_item_recall():
    procedure = _chunk(
        "procedure",
        10,
        "The onboarding procedure explains how to request access, approve accounts, and close tickets in order.",
        section="Access Procedure",
        extra_metadata={"title": "Onboarding Procedure"},
    )
    checklist = _chunk(
        "checklist",
        8,
        "Readiness checklist items ask whether staff completed access training and received escalation contacts.",
        section="Readiness Items",
        extra_metadata={"title": "Access Readiness Checklist"},
    )
    builder = RAGContextBuilder(FakeRetriever([procedure, checklist]))

    result = builder.build(
        query="Which access readiness items are listed in the onboarding checklist?",
        selected_chunks=[procedure, checklist],
        candidates=[_scored(checklist, score=0.75), _scored(procedure, score=1.25)],
        context_builder="budgeted_rse",
        compression="none",
    )

    assert result.chunks[0].metadata["title"] == "Access Readiness Checklist"


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


def test_budgeted_rse_includes_relevant_neighbor_and_records_offtopic_exclusion():
    chunks = [
        _chunk("doc", 1, "Release-gate verification confirms that approval remains effective."),
        _chunk("doc", 2, "The seed readiness step identifies the service before rollout starts."),
        _chunk("doc", 3, "Payroll approval and cafeteria scheduling are unrelated administrative topics."),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks))

    result = builder.build(
        query="readiness verification before rollout",
        selected_chunks=[chunks[1]],
        candidates=[_scored(chunks[1]), _scored(chunks[0]), _scored(chunks[2])],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = result.chunks[0].text
    assert "Release-gate verification" in text
    assert "seed readiness step" in text
    assert "Payroll approval" not in text

    segment = result.metadata["segments"][0]
    assert segment["context_builder"] == "budgeted_rse"
    assert segment["included_child_chunk_ids"] == ["doc_c0001", "doc_c0002"]
    decisions = segment["neighbor_decisions"]
    assert any(
        decision["chunk_id"] == "doc_c0001" and decision["decision"] == "include"
        for decision in decisions
    )
    assert any(
        decision["chunk_id"] == "doc_c0003"
        and decision["decision"] == "exclude"
        and decision["reason"] in {"low_marginal_gain", "low_relevance"}
        for decision in decisions
    )


def test_budgeted_rse_global_budget_keeps_higher_value_segments_first():
    high_value = _chunk("doc", 1, "Critical readiness verification evidence for rollout work.", page=4)
    low_value = _chunk("doc", 10, "General background about routine recordkeeping and administrative review.", page=12)
    builder = RAGContextBuilder(
        FakeRetriever([high_value, low_value]),
        budgeted_rse_settings=BudgetedRSESettings(max_context_tokens=28),
    )

    result = builder.build(
        query="readiness verification before rollout",
        selected_chunks=[low_value, high_value],
        candidates=[_scored(low_value, score=0.2), _scored(high_value, score=0.95)],
        context_builder="budgeted_rse",
        compression="none",
    )

    assert len(result.chunks) == 1
    assert "Critical readiness verification" in result.chunks[0].text
    assert "routine recordkeeping" not in result.chunks[0].text
    budget = result.metadata["global_budget"]
    assert budget["max_context_tokens"] == 28
    assert budget["dropped_segments"][0]["seed_chunk_id"] == "doc_c0010"
    assert budget["dropped_segments"][0]["reason"] == "global_context_budget"


def test_budgeted_rse_preserves_exact_child_locator_metadata_for_procedure_evidence():
    chunks = [
        _chunk(
            "procedure",
            8,
            "(1) Prepare for shutdown.",
            page=14,
            extra_metadata={"text_search": "Prepare for shutdown", "char_range": [120, 142]},
        ),
        _chunk(
            "procedure",
            9,
            "(2) Shut down the machine before service or maintenance.",
            page=14,
            extra_metadata={"text_search": "Shut down the machine", "char_range": [150, 171]},
        ),
        _chunk(
            "procedure",
            10,
            "(1) Inspect tools after work is complete; this is a later removal procedure.",
            page=15,
        ),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks))

    result = builder.build(
        query="procedure steps before service maintenance prepare shutdown",
        selected_chunks=[chunks[1]],
        candidates=[_scored(chunks[1]), _scored(chunks[0]), _scored(chunks[2])],
        context_builder="budgeted_rse",
        compression="none",
    )

    evidence = result.chunks[0].metadata["source_chunk_evidence"]
    assert evidence[0]["chunk_id"] == "procedure_c0008"
    assert evidence[0]["page"] == 14
    assert evidence[0]["text_search"] == "Prepare for shutdown"
    assert evidence[0]["char_range"] == [120, 142]
    assert "later removal procedure" not in result.chunks[0].text


def test_budgeted_rse_rejects_adjacent_restarted_numbered_sequence_generically():
    chunks = [
        _chunk("manual", 4, "1. Confirm calibration scope."),
        _chunk("manual", 5, "2. Verify calibration records before releasing the instrument."),
        _chunk("manual", 6, "1. File travel expenses for the same department."),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks))

    result = builder.build(
        query="calibration checklist verify records before release",
        selected_chunks=[chunks[1]],
        candidates=[_scored(chunks[1]), _scored(chunks[0]), _scored(chunks[2])],
        context_builder="budgeted_rse",
        compression="none",
    )

    assert "Confirm calibration scope" in result.chunks[0].text
    assert "Verify calibration records" in result.chunks[0].text
    assert "travel expenses" not in result.chunks[0].text
    assert any(
        decision["chunk_id"] == "manual_c0006"
        and decision["reason"] == "ordered_sequence_restart"
        for decision in result.metadata["segments"][0]["neighbor_decisions"]
    )


def test_budgeted_rse_expands_across_sibling_sections_for_missing_facets():
    chunks = [
        _chunk(
            "framework",
            20,
            "DETECT finds and analyzes adverse events during cybersecurity incidents.",
            section="DETECT",
            section_path=["Framework", "Core", "Functions", "DETECT"],
        ),
        _chunk(
            "framework",
            21,
            "RESPOND contains actions regarding a detected cybersecurity incident.",
            section="RESPOND",
            section_path=["Framework", "Core", "Functions", "RESPOND"],
        ),
        _chunk(
            "framework",
            22,
            "RECOVER restores assets and operations affected by a cybersecurity incident.",
            section="RECOVER",
            section_path=["Framework", "Core", "Functions", "RECOVER"],
        ),
        _chunk(
            "framework",
            23,
            "GOVERN establishes organizational risk strategy and oversight.",
            section="GOVERN",
            section_path=["Framework", "Core", "Functions", "GOVERN"],
        ),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks), budgeted_rse_settings=BudgetedRSESettings(max_neighbor_window=3))

    result = builder.build(
        query="How do the DETECT, RESPOND, and RECOVER Functions fit together during cybersecurity incidents?",
        selected_chunks=[chunks[0]],
        candidates=[_scored(chunks[0]), _scored(chunks[1]), _scored(chunks[2]), _scored(chunks[3])],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = result.chunks[0].text
    assert "DETECT finds" in text
    assert "RESPOND contains" in text
    assert "RECOVER restores" in text
    assert "GOVERN establishes" not in text
    included = [
        decision
        for decision in result.metadata["segments"][0]["neighbor_decisions"]
        if decision["decision"] == "include"
    ]
    assert [decision["chunk_id"] for decision in included] == ["framework_c0021", "framework_c0022"]
    assert "respond" in included[0]["missing_query_terms"]
    assert "recover" in included[1]["missing_query_terms"]


def test_budgeted_rse_keeps_short_same_section_list_continuation_for_related_query():
    chunks = [
        _chunk(
            "standards",
            20,
            "AlphaExchange defines a common model for live equipment data.",
            section="Operational uses",
            section_path=["Standards", "Operational uses"],
        ),
        _chunk(
            "standards",
            21,
            "The agent returns structured equipment readings for client applications.",
            section="Operational uses",
            section_path=["Standards", "Operational uses"],
        ),
        _chunk(
            "standards",
            22,
            "- Overall effectiveness and utilization",
            section="Operational uses",
            section_path=["Standards", "Operational uses"],
        ),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks))

    result = builder.build(
        query="Compare AlphaExchange with BetaInspect for reusable manufacturing data context.",
        selected_chunks=[chunks[1]],
        candidates=[_scored(chunks[1]), _scored(chunks[2])],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = result.chunks[0].text
    assert "structured equipment readings" in text
    assert "Overall effectiveness" in text
    assert any(
        decision["chunk_id"] == "standards_c0022" and decision["decision"] == "include"
        for decision in result.metadata["segments"][0]["neighbor_decisions"]
    )


def test_budgeted_rse_prioritizes_uncovered_named_facets_over_higher_score_noise():
    alpha = _chunk("doc", 1, "AlphaExchange creates contextualized equipment data for applications.")
    noise = _chunk("doc", 10, "Administrative data-retention background mentions context and applications.")
    beta = _chunk("doc", 20, "BetaInspect creates quality inspection context from measurement results.")
    builder = RAGContextBuilder(
        FakeRetriever([alpha, noise, beta]),
        budgeted_rse_settings=BudgetedRSESettings(max_context_tokens=42),
    )

    result = builder.build(
        query="Compare AlphaExchange and BetaInspect for reusable manufacturing data context.",
        selected_chunks=[alpha, noise, beta],
        candidates=[_scored(alpha, 0.75), _scored(noise, 0.95), _scored(beta, 0.55)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "AlphaExchange creates contextualized equipment data" in text
    assert "BetaInspect creates quality inspection context" in text
    assert "Administrative data-retention background" not in text


def test_budgeted_rse_drops_extra_segments_after_named_facets_are_covered():
    alpha = _chunk("doc", 1, "AlphaExchange provides structured equipment data for client applications.")
    beta = _chunk("doc", 5, "BetaInspect provides XML quality data for inspection planning and results.")
    reference_noise = _chunk("doc", 9, "Reference entries repeat data, standard, context, and application terms.")
    generic_noise = _chunk("doc", 13, "General background says data context can support many decisions.")
    builder = RAGContextBuilder(
        FakeRetriever([alpha, beta, reference_noise, generic_noise]),
        budgeted_rse_settings=BudgetedRSESettings(max_context_tokens=500),
    )

    result = builder.build(
        query="Compare AlphaExchange and BetaInspect for reusable manufacturing data context.",
        selected_chunks=[alpha, beta, reference_noise, generic_noise],
        candidates=[
            _scored(alpha, 0.92),
            _scored(beta, 0.9),
            _scored(reference_noise, 0.88),
            _scored(generic_noise, 0.86),
        ],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "AlphaExchange provides structured equipment data" in text
    assert "BetaInspect provides XML quality data" in text
    assert "Reference entries repeat" not in text
    assert "General background says" not in text
    assert {
        dropped["reason"] for dropped in result.metadata["global_budget"]["dropped_segments"]
    } == {"support_sufficient"}


def test_budgeted_rse_preservation_does_not_add_cross_doc_generic_overlap_without_query_gain():
    exact = _chunk(
        "equipment_audit",
        4,
        "The equipment safety checklist electric hazard checks cover code installation, loose fittings, grounding, fused supply, and minor shocks.",
        section="Electric Hazards",
    )
    generic = _chunk(
        "maintenance_guide",
        6,
        "The maintenance guide mentions equipment safety hazard checks before service work.",
        section="Maintenance Coverage",
    )
    builder = RAGContextBuilder(
        FakeRetriever([exact, generic]),
        budgeted_rse_settings=BudgetedRSESettings(max_neighbor_window=0),
    )

    result = builder.build(
        query="Which electric hazard checks appear on the equipment safety checklist?",
        selected_chunks=[exact],
        candidates=[_scored(exact, 0.94), _scored(generic, 0.92)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "code installation" in text
    assert "maintenance guide mentions" not in text


def test_budgeted_rse_preservation_keeps_cross_doc_candidate_with_new_query_term_support():
    alpha = _chunk(
        "alpha_review",
        1,
        "AlphaControl access checks cover administrator approval.",
        section="Access Controls",
    )
    beta = _chunk(
        "beta_review",
        2,
        "BetaRecovery recovery checks cover restoration evidence.",
        section="Recovery Checks",
    )
    builder = RAGContextBuilder(
        FakeRetriever([alpha, beta]),
        budgeted_rse_settings=BudgetedRSESettings(max_neighbor_window=0),
    )

    result = builder.build(
        query="Compare AlphaControl and BetaRecovery access and recovery checks.",
        selected_chunks=[alpha],
        candidates=[_scored(alpha, 0.94), _scored(beta, 0.90)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "AlphaControl access checks" in text
    assert "BetaRecovery recovery checks" in text


def test_evidence_cards_prefer_checklist_card_while_keeping_supporting_procedure_card():
    chunks = [
        _chunk(
            "guide",
            1,
            "- Guard condition\n- Worker training\n- Lockout readiness",
            section="Inspection Checklist",
        ),
        _chunk(
            "guide",
            2,
            "1. Stop equipment before maintenance. 2. Isolate stored energy before servicing.",
            section="Maintenance Procedure",
        ),
    ]
    builder = RAGContextBuilder(
        FakeRetriever(chunks),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True),
    )

    result = builder.build(
        query="Which checklist areas should maintenance review before service?",
        selected_chunks=chunks,
        candidates=[_scored(chunks[0]), _scored(chunks[1])],
        context_builder="budgeted_rse",
        compression="none",
    )

    cards = result.metadata["evidence_cards"]["selected_cards"]
    assert result.metadata["evidence_cards"]["query_intent_scores"]["checklist"] > 0
    assert result.metadata["evidence_cards"]["query_intent_scores"]["procedure"] > 0
    assert cards[0]["chunk_id"] == "guide_c0001"
    assert "checklist areas" in cards[0]["facets_covered"]
    assert any(card["chunk_id"] == "guide_c0002" for card in cards)
    assert "Worker training" in "\n".join(chunk.text for chunk in result.chunks)


def test_evidence_cards_preserve_ordered_steps_for_procedure_query():
    chunks = [
        _chunk(
            "procedure",
            3,
            "1. Prepare the work area. 2. Shut down the equipment. 3. Verify isolation.",
            section="Procedure",
            page=5,
        )
    ]
    builder = RAGContextBuilder(
        FakeRetriever(chunks),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True),
    )

    result = builder.build(
        query="What procedure steps should be followed before service?",
        selected_chunks=chunks,
        candidates=[_scored(chunks[0])],
        context_builder="budgeted_rse",
        compression="none",
    )

    assert len(result.chunks) == 1
    assert "1. Prepare" in result.chunks[0].text
    assert "2. Shut down" in result.chunks[0].text
    assert "3. Verify" in result.chunks[0].text
    assert "steps" in result.metadata["evidence_cards"]["selected_cards"][0]["facets_covered"]


def test_evidence_cards_summary_query_covers_scope_purpose_and_limitations():
    chunks = [
        _chunk("manual", 1, "The purpose is to provide reusable source guidance.", section="Purpose"),
        _chunk("manual", 2, "The scope includes static documentation and excludes live approval.", section="Scope"),
        _chunk("manual", 3, "Limitations include that the source is not current-state proof.", section="Limitations"),
    ]
    builder = RAGContextBuilder(
        FakeRetriever(chunks),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=3),
    )

    result = builder.build(
        query="Summarize the source purpose, scope, and limitations.",
        selected_chunks=chunks,
        candidates=[_scored(chunks[0]), _scored(chunks[1]), _scored(chunks[2])],
        context_builder="budgeted_rse",
        compression="none",
    )

    facets = set()
    for card in result.metadata["evidence_cards"]["selected_cards"]:
        facets.update(card["facets_covered"])
    assert {"purpose", "scope", "limitations"} <= facets


def test_evidence_cards_comparison_query_keeps_evidence_for_both_anchors():
    alpha = _chunk("doc", 1, "AlphaExchange supports equipment data streams.", section="AlphaExchange")
    beta = _chunk("doc", 2, "BetaInspect supports quality inspection results.", section="BetaInspect")
    filler = _chunk("doc", 3, "General reusable data background repeats data context.", section="Background")
    builder = RAGContextBuilder(
        FakeRetriever([alpha, beta, filler]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=2),
    )

    result = builder.build(
        query="Compare AlphaExchange and BetaInspect for reusable data.",
        selected_chunks=[filler, alpha, beta],
        candidates=[_scored(filler, 0.9), _scored(alpha, 0.7), _scored(beta, 0.6)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "AlphaExchange supports equipment data" in text
    assert "BetaInspect supports quality inspection" in text
    assert "General reusable data background" not in text


def test_evidence_cards_keep_mixed_intent_scores_instead_of_one_label():
    chunk = _chunk(
        "guide",
        1,
        "- Check guards before work. 1. Stop the machine before maintenance.",
        section="Checklist Procedure",
    )
    builder = RAGContextBuilder(
        FakeRetriever([chunk]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True),
    )

    result = builder.build(
        query="Summarize checklist steps for maintenance review.",
        selected_chunks=[chunk],
        candidates=[_scored(chunk)],
        context_builder="budgeted_rse",
        compression="none",
    )

    scores = result.metadata["evidence_cards"]["query_intent_scores"]
    assert scores["summary"] > 0
    assert scores["checklist"] > 0
    assert scores["procedure"] > 0


def test_evidence_cards_preserve_exact_child_evidence_from_parent_context():
    parent = Chunk(
        chunk_id="rse:manual:01:manual_c0001",
        text="[Section: Parent] Broad parent context around the exact child evidence.",
        metadata={
            "doc_id": "manual",
            "chunk_index": 1,
            "title": "Manual",
            "organization": "Test Org",
            "authority_level": "official_public_guidance",
            "section_title": "Parent",
            "section_path": ["Manual", "Parent"],
            "page": 10,
            "source_chunk_evidence": [
                {
                    "chunk_id": "manual_c0007",
                    "doc_id": "manual",
                    "page": 12,
                    "section_title": "Exact Child",
                    "section_path": ["Manual", "Exact Child"],
                    "snippet": "Exact child evidence states the verification requirement.",
                    "text_search": "verification requirement",
                    "char_range": [200, 226],
                }
            ],
        },
    )
    builder = RAGContextBuilder(
        FakeRetriever([parent]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True),
    )

    result = builder.build(
        query="What verification requirement is stated?",
        selected_chunks=[parent],
        candidates=[_scored(parent)],
        context_builder="budgeted_rse",
        compression="none",
    )

    card = result.metadata["evidence_cards"]["selected_cards"][0]
    assert card["chunk_id"] == "manual_c0007"
    assert card["page"] == 12
    assert card["text_search"] == "verification requirement"
    assert card["char_range"] == [200, 226]
    assert result.chunks[0].metadata["source_chunk_evidence"][0]["chunk_id"] == "manual_c0007"


def test_evidence_cards_preserve_top_candidate_with_exact_section_match_when_rerank_misses_it():
    exact = _chunk(
        "manual",
        4,
        "The procedure must include the scope, responsible roles, required records, and verification.",
        section="What must the procedure include?",
        page=4,
    )
    reranked = _chunk(
        "manual",
        8,
        "Annual review checks whether people followed an existing procedure.",
        section="Review checklist",
        page=8,
    )
    builder = RAGContextBuilder(
        FakeRetriever([exact, reranked]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True),
    )

    result = builder.build(
        query="What must the procedure include?",
        selected_chunks=[reranked],
        candidates=[_scored(exact, 0.95), _scored(reranked, 0.80)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "scope, responsible roles" in text
    assert result.metadata["evidence_cards"]["selected_cards"][0]["chunk_id"] == "manual_c0004"


def test_evidence_cards_preserve_adjacent_top_candidate_with_direct_heading_overlap():
    exact = _chunk(
        "quality",
        11,
        "Shift handoff records include open work, owner, status, and next verification.",
        section="What if a shift changes during work?",
        page=11,
    )
    nearby = _chunk(
        "quality",
        12,
        "Before release, workers verify the tool state and notify the owner.",
        section="Before release",
        page=12,
    )
    builder = RAGContextBuilder(
        FakeRetriever([exact, nearby]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True),
    )

    result = builder.build(
        query="How should shift changes during work be handled?",
        selected_chunks=[nearby],
        candidates=[_scored(exact, 0.93), _scored(nearby, 0.82)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "Shift handoff records include" in text
    assert any(
        card["chunk_id"] == "quality_c0011"
        for card in result.metadata["evidence_cards"]["selected_cards"]
    )


def test_evidence_cards_do_not_stop_when_key_query_terms_remain_uncovered():
    generic = _chunk(
        "manual",
        1,
        "Before release, workers follow the standard verification steps.",
        section="General procedure",
    )
    contractor = _chunk(
        "manual",
        2,
        "Contractor work requires coordination between the site employer and outside employer.",
        section="Contractor coordination",
    )
    group = _chunk(
        "manual",
        3,
        "Group work assigns primary responsibility and keeps each worker protected.",
        section="Group work",
    )
    shift = _chunk(
        "manual",
        4,
        "Shift changes require handoff records before work continues.",
        section="Shift changes",
    )
    builder = RAGContextBuilder(
        FakeRetriever([generic, contractor, group, shift]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=4),
    )

    result = builder.build(
        query="How should contractor work, group work, and shift changes be handled?",
        selected_chunks=[generic],
        candidates=[
            _scored(shift, 0.95),
            _scored(contractor, 0.90),
            _scored(group, 0.88),
            _scored(generic, 0.80),
        ],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "Contractor work requires coordination" in text
    assert "Group work assigns primary responsibility" in text
    assert "Shift changes require handoff" in text


def test_evidence_cards_adjacent_query_term_coverage_keeps_limitations_with_summary():
    overview = _chunk("manual", 1, "The purpose is to guide static source review.", section="Purpose")
    limitation = _chunk("manual", 2, "The source cannot prove current approval.", section="Limitations")
    builder = RAGContextBuilder(
        FakeRetriever([overview, limitation]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=2),
    )

    result = builder.build(
        query="Summarize the purpose and current approval limitations.",
        selected_chunks=[overview],
        candidates=[_scored(overview, 0.90), _scored(limitation, 0.86)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "purpose is to guide" in text
    assert "cannot prove current approval" in text


def test_evidence_cards_summary_does_not_pull_unasked_generic_facets_over_direct_topic_evidence():
    roles = _chunk(
        "manual",
        11,
        "Authorized workers need to know safe application and removal duties. Affected workers need to recognize procedure restrictions.",
        section="What do workers need to know?",
    )
    retraining = _chunk(
        "manual",
        12,
        "Retraining is required when assignments, equipment hazards, or procedures change.",
        section="When is retraining necessary?",
    )
    review = _chunk(
        "manual",
        30,
        "The review purpose is to confirm the scope, included items, and limitations of the program.",
        section="Annual review scope",
    )
    builder = RAGContextBuilder(
        FakeRetriever([roles, retraining, review]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=3),
    )

    result = builder.build(
        query="Summarize what workers need to know and when retraining is required.",
        selected_chunks=[review],
        candidates=[_scored(roles, 0.95), _scored(retraining, 0.92), _scored(review, 0.80)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "Authorized workers need to know" in text
    assert "Retraining is required when assignments" in text
    assert "review purpose is to confirm" not in text


def test_evidence_cards_adjacent_summary_keeps_direct_responsibility_and_trigger_evidence():
    responsibilities = _chunk(
        "manual",
        21,
        "Inspectors verify responsibility assignments and record whether corrective actions are owned.",
        section="What responsibilities are checked?",
    )
    triggers = _chunk(
        "manual",
        22,
        "Follow-up is required when inspection findings show gaps or when the process changes.",
        section="When is follow-up required?",
    )
    scope = _chunk(
        "manual",
        23,
        "Program scope includes routine oversight examples and excludes unrelated departments.",
        section="Program scope",
    )
    builder = RAGContextBuilder(
        FakeRetriever([responsibilities, triggers, scope]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=3),
    )

    result = builder.build(
        query="Summarize inspection responsibilities and when follow-up is required.",
        selected_chunks=[scope],
        candidates=[_scored(responsibilities, 0.94), _scored(triggers, 0.90), _scored(scope, 0.76)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "verify responsibility assignments" in text
    assert "Follow-up is required when inspection findings" in text
    assert "Program scope includes routine oversight" not in text


def test_evidence_cards_direct_fact_prefers_exact_query_phrase_over_broad_resource_card():
    coverage = _chunk(
        "manual",
        5,
        "The standard applies to all hazardous energy sources, including mechanical, electrical, chemical, and thermal sources.",
        section="Coverage",
    )
    resources = _chunk(
        "manual",
        30,
        "Reference guidance and website tools help users apply the standard to hazardous energy work.",
        section="Interpretive guidance and tools",
    )
    builder = RAGContextBuilder(
        FakeRetriever([coverage, resources]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=2),
    )

    result = builder.build(
        query="What hazardous energy sources does the standard apply to?",
        selected_chunks=[resources],
        candidates=[_scored(resources, 0.96), _scored(coverage, 0.82)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "all hazardous energy sources" in text
    assert "Reference guidance and website tools" not in text


def test_evidence_cards_adjacent_direct_fact_keeps_exact_object_phrase():
    coverage = _chunk(
        "manual",
        6,
        "The policy covers calibrated measurement records, inspection reports, and release evidence.",
        section="Policy coverage",
    )
    resources = _chunk(
        "manual",
        31,
        "Supplemental resources explain how teams use the policy in common workflows.",
        section="Supplemental resources",
    )
    builder = RAGContextBuilder(
        FakeRetriever([coverage, resources]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=2),
    )

    result = builder.build(
        query="What measurement records does the policy cover?",
        selected_chunks=[resources],
        candidates=[_scored(resources, 0.94), _scored(coverage, 0.80)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "calibrated measurement records" in text
    assert "Supplemental resources explain" not in text


def test_evidence_cards_can_select_resource_listing_when_query_asks_for_resources():
    coverage = _chunk(
        "manual",
        6,
        "The policy covers calibrated measurement records, inspection reports, and release evidence.",
        section="Policy coverage",
    )
    resources = _chunk(
        "manual",
        31,
        "Supplemental resources include a quick guide, examples, and a diagnostic tool.",
        section="Supplemental resources",
    )
    builder = RAGContextBuilder(
        FakeRetriever([coverage, resources]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=2),
    )

    result = builder.build(
        query="Which supplemental resources and tools are available?",
        selected_chunks=[coverage],
        candidates=[_scored(coverage, 0.90), _scored(resources, 0.84)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "Supplemental resources include" in text


def test_evidence_cards_difference_query_keeps_both_concept_definitions_not_only_gap_card():
    current = _chunk(
        "manual",
        7,
        "Alpha Mode specifies the operating state the team currently achieves and characterizes how well it is achieved.",
        section="Alpha Mode",
    )
    target = _chunk(
        "manual",
        8,
        "Beta Mode specifies the desired outcomes selected and prioritized for future process objectives.",
        section="Beta Mode",
    )
    gap = _chunk(
        "manual",
        9,
        "Teams compare Alpha Mode and Beta Mode to identify gaps and create a prioritized action plan.",
        section="Gap analysis",
    )
    builder = RAGContextBuilder(
        FakeRetriever([current, target, gap]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=3),
    )

    result = builder.build(
        query="What is the difference between Alpha Mode and Beta Mode?",
        selected_chunks=[gap],
        candidates=[_scored(gap, 0.96), _scored(current, 0.90), _scored(target, 0.88)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "currently achieves" in text
    assert "desired outcomes selected and prioritized" in text


def test_evidence_cards_purpose_query_prefers_content_over_front_matter_boilerplate():
    front_matter = _chunk(
        "report",
        0,
        "This publication is available for reference. Commercial systems are identified to describe an experimental procedure or concept adequately.",
        section="Publication notes",
    )
    abstract = _chunk(
        "report",
        1,
        "This report describes a reusable model for collecting equipment data so teams can curate and reuse production information across applications.",
        section="Abstract",
    )
    builder = RAGContextBuilder(
        FakeRetriever([front_matter, abstract]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=2),
    )

    result = builder.build(
        query="What is the purpose of this report?",
        selected_chunks=[front_matter],
        candidates=[_scored(front_matter, 0.95), _scored(abstract, 0.82)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "reusable model for collecting equipment data" in text
    assert "Commercial systems are identified" not in text


def test_evidence_cards_preserve_short_alphanumeric_activity_anchor():
    exact = _chunk(
        "manual",
        4,
        "A4 includes production scheduling, product fabrication, quality checks, and release reporting.",
        section="A4: Produce Products",
    )
    overview = _chunk(
        "manual",
        5,
        "The overview lists product activities and model background at a high level.",
        section="Overview of the Model",
    )
    builder = RAGContextBuilder(
        FakeRetriever([exact, overview]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=2),
    )

    result = builder.build(
        query="What does A4: Produce Products include?",
        selected_chunks=[overview],
        candidates=[_scored(overview, 0.92), _scored(exact, 0.86)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "A4 includes production scheduling" in text
    assert "overview lists product activities" not in text


def test_evidence_cards_preserve_adjacent_short_alphanumeric_anchor():
    exact = _chunk(
        "manual",
        7,
        "B2 defines validation inputs, execution records, and acceptance outputs.",
        section="B2 Validation Activity",
    )
    broad = _chunk(
        "manual",
        8,
        "The model overview discusses validation and activity outputs generally.",
        section="Model Overview",
    )
    builder = RAGContextBuilder(
        FakeRetriever([exact, broad]),
        budgeted_rse_settings=BudgetedRSESettings(use_evidence_cards=True, max_evidence_cards=2),
    )

    result = builder.build(
        query="What does B2 define for validation?",
        selected_chunks=[broad],
        candidates=[_scored(broad, 0.91), _scored(exact, 0.84)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "B2 defines validation inputs" in text
    assert "overview discusses validation" not in text


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
    assert result.chunks[0].metadata["source_chunk_evidence"][1]["page"] == 8
    assert "Verification support" in result.chunks[0].metadata["source_chunk_evidence"][1]["snippet"]


def test_context_builder_source_chunk_evidence_keeps_long_procedure_support():
    procedure_text = (
        "Before beginning service or maintenance, the following steps must be accomplished in sequence "
        "and according to the specific provisions of the employer's energy-control procedure: "
        "(1) Prepare for shutdown; "
        "(2) Shut down the machine; "
        "(3) Disconnect or isolate the machine from the energy source(s); "
        "(4) Apply the lockout or tagout device(s) to the energy-isolating device(s); "
        "(5) Release, restrain, or otherwise render safe all potential hazardous stored or residual energy. "
        "If a possibility exists for reaccumulation of hazardous energy, regularly verify during the service "
        "and maintenance that such energy has not reaccumulated to hazardous levels; and "
        "(6) Verify the isolation and deenergization of the machine."
    )
    chunks = [
        _chunk("doc", 15, procedure_text, section="What must workers do before they begin service?", page=14),
    ]
    builder = RAGContextBuilder(FakeRetriever(chunks))

    result = builder.build(
        query="what steps before service maintenance",
        selected_chunks=[chunks[0]],
        candidates=[_scored(chunks[0])],
        context_builder="rse",
        compression="none",
    )

    child_evidence = result.chunks[0].metadata["source_chunk_evidence"][0]
    assert child_evidence["page"] == 14
    assert "Apply the lockout or tagout device(s)" in child_evidence["snippet"]
    assert "Verify the isolation and deenergization of the machine" in child_evidence["snippet"]


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


def test_evidence_cards_can_log_metadata_without_replacing_generation_context():
    chunks = [
        _chunk("doc", 1, "Alpha calibration evidence defines the required record.", page=4),
        _chunk("doc", 2, "Calibration verification evidence explains the supporting check.", page=5),
    ]
    builder = RAGContextBuilder(
        FakeRetriever(chunks),
        budgeted_rse_settings=BudgetedRSESettings(
            use_evidence_cards=True,
            evidence_card_context_mode="metadata_only",
            max_context_tokens=200,
            max_segment_tokens=200,
        ),
    )

    result = builder.build(
        query="define alpha calibration evidence",
        selected_chunks=[chunks[0]],
        candidates=[_scored(chunks[0]), _scored(chunks[1], score=0.7)],
        context_builder="budgeted_rse",
        compression="none",
    )

    assert result.chunks
    assert all("evidence_card" not in chunk.metadata for chunk in result.chunks)
    assert result.metadata["evidence_cards"]["context_policy"]["mode"] == "metadata_only"
    assert result.metadata["evidence_cards"]["selected_cards"]
    assert result.metadata["evidence_cards"]["selected_cards"][0]["score_breakdown"]["total"] > 0
    assert result.metadata["global_budget"]["kept_segments"][0]["reason"]


def test_metadata_only_evidence_cards_do_not_expand_generation_context_with_card_candidates():
    selected = _chunk(
        "audit",
        4,
        "The electric hazard checks cover code installation, loose fittings, grounding, fused supply, and minor shocks.",
        section="Electric Hazards",
    )
    card_only_candidate = _chunk(
        "audit",
        7,
        "This card-only debug candidate repeats electric hazard words but should not enter the generation context.",
        section="Electric Hazards Details",
    )
    builder = RAGContextBuilder(
        FakeRetriever([selected, card_only_candidate]),
        budgeted_rse_settings=BudgetedRSESettings(
            use_evidence_cards=True,
            evidence_card_context_mode="metadata_only",
            max_neighbor_window=0,
        ),
    )

    result = builder.build(
        query="Explain electric hazard evidence.",
        selected_chunks=[selected],
        candidates=[_scored(selected, 0.94), _scored(card_only_candidate, 0.93)],
        context_builder="budgeted_rse",
        compression="none",
    )

    text = "\n".join(chunk.text for chunk in result.chunks)
    assert "code installation" in text
    assert "card-only debug candidate" not in text
    assert result.metadata["evidence_cards"]["context_policy"]["mode"] == "metadata_only"


def test_mode_aware_evidence_cards_use_compact_context_for_procedure_queries():
    chunks = [
        _chunk("doc", 1, "General background before the work begins.", page=4),
        _chunk("doc", 2, "(1) Inspect the record. (2) Verify the calibration evidence.", page=5),
    ]
    builder = RAGContextBuilder(
        FakeRetriever(chunks),
        budgeted_rse_settings=BudgetedRSESettings(
            use_evidence_cards=True,
            evidence_card_context_mode="mode_aware",
            max_context_tokens=200,
            max_segment_tokens=200,
        ),
    )

    result = builder.build(
        query="What steps should I follow to verify calibration evidence?",
        selected_chunks=[chunks[1]],
        candidates=[_scored(chunks[1]), _scored(chunks[0], score=0.7)],
        context_builder="budgeted_rse",
        compression="none",
    )

    assert result.metadata["evidence_cards"]["context_policy"]["mode"] == "compact_cards"
    assert result.chunks
    assert all("evidence_card" in chunk.metadata for chunk in result.chunks)


def test_mode_aware_evidence_cards_keep_broader_context_for_summary_queries():
    chunks = [
        _chunk("doc", 1, "Alpha calibration evidence defines the required record.", page=4),
        _chunk("doc", 2, "Calibration verification evidence explains the supporting check.", page=5),
    ]
    builder = RAGContextBuilder(
        FakeRetriever(chunks),
        budgeted_rse_settings=BudgetedRSESettings(
            use_evidence_cards=True,
            evidence_card_context_mode="mode_aware",
            max_context_tokens=200,
            max_segment_tokens=200,
        ),
    )

    result = builder.build(
        query="Summarize the alpha calibration evidence and verification coverage.",
        selected_chunks=[chunks[0]],
        candidates=[_scored(chunks[0]), _scored(chunks[1], score=0.7)],
        context_builder="budgeted_rse",
        compression="none",
    )

    assert result.metadata["evidence_cards"]["context_policy"]["mode"] == "broad_context"
    assert result.chunks
    assert all("evidence_card" not in chunk.metadata for chunk in result.chunks)
    assert "Calibration verification evidence" in result.chunks[0].text


def test_mode_aware_evidence_cards_keep_broader_context_when_relationship_query_looks_procedural():
    chunks = [
        _chunk("doc", 1, "Protect controls establish safeguards before monitoring begins.", page=8),
        _chunk("doc", 2, "Detect, respond, and recover activities connect monitoring to recovery.", page=9),
    ]
    builder = RAGContextBuilder(
        FakeRetriever(chunks),
        budgeted_rse_settings=BudgetedRSESettings(
            use_evidence_cards=True,
            evidence_card_context_mode="mode_aware",
            max_context_tokens=220,
            max_segment_tokens=220,
        ),
    )

    result = builder.build(
        query="How do protect and detect controls relate during a review?",
        selected_chunks=[chunks[0]],
        candidates=[_scored(chunks[0]), _scored(chunks[1], score=0.7)],
        context_builder="budgeted_rse",
        compression="none",
    )

    assert result.metadata["evidence_cards"]["context_policy"]["mode"] == "broad_context"
    assert result.chunks
    assert all("evidence_card" not in chunk.metadata for chunk in result.chunks)
    assert "Detect, respond, and recover" in result.chunks[0].text
