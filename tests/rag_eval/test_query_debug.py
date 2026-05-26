from tests.rag_eval.query_debug import project_response_document_debug, summarize_loto_procedure_projection


def test_query_debug_projection_reports_step_citation_evidence():
    answer = "\n".join(
        [
            "1. Prepare for shutdown.[^1]",
            "2. Shut down the machine.[^1]",
            "3. Disconnect or isolate the machine from the energy source(s).[^1]",
            "4. Apply the lockout or tagout device(s) to the energy-isolating device(s).[^1]",
            "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy.[^1]",
            "6. Verify the isolation and deenergization of the machine.[^1]",
        ]
    )
    sources = [
        {
            "source_id": "osha#loto",
            "source_number": 1,
            "doc_id": "osha_3120_lockout_tagout",
            "chunk_id": "rse:osha:parent",
            "title": "Control of Hazardous Energy Lockout/Tagout",
            "organization": "OSHA",
            "snippet": "Before beginning service or maintenance, the following steps must be accomplished...",
            "pdf_url": "/documents/osha/pdf",
            "page": 13,
            "evidence_snippets": [
                {
                    "chunk_id": "osha_3120_lockout_tagout_c0015",
                    "doc_id": "osha_3120_lockout_tagout",
                    "page": 14,
                    "pdf_url": "/documents/osha/pdf",
                    "snippet": (
                        "Before beginning service or maintenance, the following steps must be accomplished "
                        "in sequence: (1) Prepare for shutdown; (2) Shut down the machine; "
                        "(3) Disconnect or isolate the machine from the energy source(s); "
                        "(4) Apply the lockout or tagout device(s) to the energy-isolating device(s); "
                        "(5) Release, restrain, or otherwise render safe all potential hazardous stored or residual energy; "
                        "and (6) Verify the isolation and deenergization of the machine."
                    ),
                }
            ],
        }
    ]

    projection = project_response_document_debug(answer=answer, sources=sources)
    summary = summarize_loto_procedure_projection(projection)

    assert summary["observed_segment_count"] == 6
    assert summary["missing_phrases"] == []
    assert summary["uncited_steps"] == []
    assert summary["steps_without_exact_or_context_evidence"] == []
    assert summary["steps_missing_expected_pdf_page_14"] == []
    assert summary["pages_by_step"]["6"] == [14]
    diagnostics = projection["diagnostics"]["step_diagnostics"]
    assert diagnostics[5]["citation_ids"]
    assert diagnostics[5]["evidence"][0]["page"] == 14


def test_loto_query_debug_projection_fails_when_later_steps_resolve_to_parent_page():
    answer = "\n".join(
        [
            "1. Prepare for shutdown.[^1]",
            "2. Shut down the machine.[^1]",
            "3. Disconnect or isolate the machine from the energy source(s).[^1]",
            "4. Apply the lockout or tagout device(s) to the energy-isolating device(s).[^1]",
            "5. Release, restrain, or otherwise render safe all potential hazardous stored or residual energy.[^1]",
            "6. Verify the isolation and deenergization of the machine.[^1]",
        ]
    )
    sources = [
        {
            "source_id": "osha#loto",
            "source_number": 1,
            "doc_id": "osha_3120_lockout_tagout",
            "chunk_id": "rse:osha:parent",
            "title": "Control of Hazardous Energy Lockout/Tagout",
            "organization": "OSHA",
            "snippet": "Prepare for shutdown.",
            "pdf_url": "/documents/osha/pdf",
            "page": 13,
            "text_search": "Prepare for shutdown",
            "evidence_snippets": [
                {
                    "chunk_id": "rse:osha:parent",
                    "doc_id": "osha_3120_lockout_tagout",
                    "page": 13,
                    "pdf_url": "/documents/osha/pdf",
                    "snippet": "Verify the isolation and deenergization of the machine.",
                    "text_search": "Verify the isolation and deenergization of the machine",
                }
            ],
        }
    ]

    projection = project_response_document_debug(answer=answer, sources=sources)
    summary = summarize_loto_procedure_projection(projection)

    assert summary["ok"] is False
    assert summary["steps_missing_expected_pdf_page_14"] == [1, 2, 3, 4, 5, 6]
