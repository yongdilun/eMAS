from tests.rag_eval.scoring import compute_retrieval_metrics, score_case


def _case(**overrides):
    base = {
        "id": "case-1",
        "doc_id": "doc-a",
        "query": "What is the required lockout step?",
        "question_type": "direct_fact",
        "expected_answer_points": [
            "Notify affected employees before applying lockout.",
            "Use lockout or tagout devices according to the procedure.",
        ],
        "gold_answer": "Notify affected employees and apply lockout/tagout devices.",
        "expected_source": {
            "doc_id": "doc-a",
            "section": "Lockout Application",
            "page": 4,
            "pages": [4],
        },
        "expects_sources": True,
        "expects_safety_warning": False,
        "unanswerable_reason": None,
        "expected_doc_ids": ["doc-a"],
        "tags": ["rag"],
    }
    base.update(overrides)
    return base


def _source(**overrides):
    base = {
        "doc_id": "doc-a",
        "page": 4,
        "page_start": 4,
        "page_end": 4,
        "section_title": "Lockout Application",
        "section_path": ["Control of Hazardous Energy", "Lockout Application"],
        "snippet": "Notify affected employees before applying lockout devices.",
    }
    base.update(overrides)
    return base


def test_rule_scoring_rewards_answer_points_citations_and_safety_warning():
    case = _case(expects_safety_warning=True)
    answer = (
        "Notify affected employees before applying lockout. Use lockout or "
        "tagout devices according to the procedure. Follow the approved SOP "
        "and consult the safety officer."
    )

    result = score_case(
        case=case,
        agent_response={
            "answer": answer,
            "sources": [_source()],
            "safety_warning": True,
        },
        rag_result=None,
        retrieval_debug={"top_chunks": []},
    )

    assert result["rule_score"] >= 95
    assert result["rule_dimensions"]["expected_doc_id_cited"]["passed"] is True
    assert result["rule_dimensions"]["expected_page_hit"]["passed"] is True
    assert result["rule_dimensions"]["expected_section_hit"]["passed"] is True
    assert result["rule_dimensions"]["expected_answer_points"]["metadata"]["matched_full"] == 2
    assert result["rule_dimensions"]["safety_warning_present"]["passed"] is True
    assert result["serious_failures"] == []


def test_retrieval_metrics_compute_hit_at_3_5_and_10():
    case = _case(
        expected_source={
            "doc_id": "doc-a",
            "section": "Expected Section",
            "page": 9,
            "pages": [9],
        }
    )
    retrieval_debug = {
        "top_chunks": [
            {"rank": 1, "doc_id": "doc-b", "page": 9, "section_title": "Expected Section"},
            {"rank": 2, "doc_id": "doc-c", "page": 9, "section_title": "Expected Section"},
            {"rank": 3, "doc_id": "doc-d", "page": 9, "section_title": "Expected Section"},
            {"rank": 4, "doc_id": "doc-a", "page_start": 8, "page_end": 10, "section_title": "Other"},
            {"rank": 8, "doc_id": "doc-a", "page": 2, "section_title": "Expected Section"},
        ]
    }

    metrics = compute_retrieval_metrics(case=case, retrieval_debug=retrieval_debug)

    assert metrics["doc_hit@3"] is False
    assert metrics["doc_hit@5"] is True
    assert metrics["doc_hit@10"] is True
    assert metrics["section_or_page_hit@3"] is False
    assert metrics["section_or_page_hit@5"] is True
    assert metrics["section_or_page_hit@10"] is True


def test_borderline_when_expected_doc_cited_but_answer_points_partial():
    result = score_case(
        case=_case(),
        agent_response={
            "answer": "Notify affected employees before applying lockout.",
            "sources": [_source()],
            "safety_warning": False,
        },
        rag_result=None,
        retrieval_debug={"top_chunks": []},
    )

    assert result["borderline"] is True
    assert "expected_doc_cited_but_answer_points_partial" in result["borderline_reasons"]
    assert result["serious_failures"] == []


def test_serious_failure_classifies_unsafe_advice_as_hard_fail():
    result = score_case(
        case=_case(expects_safety_warning=True),
        agent_response={
            "answer": "You can skip lockout if the job is brief.",
            "sources": [_source()],
            "safety_warning": False,
        },
        rag_result=None,
        retrieval_debug={"top_chunks": []},
    )

    codes = {failure["code"] for failure in result["serious_failures"]}
    assert "unsafe_advice" in codes
    assert result["serious_failure"] is True
    assert result["rule_score"] <= 40


def test_serious_failure_classifies_failed_boundary_answer():
    case = _case(
        question_type="unanswerable",
        unanswerable_reason="The document is not a live compliance certificate.",
        expected_answer_points=[
            "State that the PDF does not prove live compliance.",
            "Say the source can support review concepts instead.",
        ],
    )

    result = score_case(
        case=case,
        agent_response={
            "answer": "Yes, it proves that the deployment is compliant today.",
            "sources": [_source()],
            "safety_warning": False,
        },
        rag_result=None,
        retrieval_debug={"top_chunks": []},
    )

    codes = {failure["code"] for failure in result["serious_failures"]}
    assert "failed_boundary_answer" in codes
    assert "hallucinated_unsupported_claim" in codes
