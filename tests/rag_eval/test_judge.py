import pytest

from tests.rag_eval.judge import build_judge_input, parse_judge_json


def test_parse_judge_json_accepts_strict_rubric_output():
    parsed = parse_judge_json(
        """
        {
          "correctness": 4,
          "completeness": 3,
          "faithfulness": 5,
          "citation_quality": 4,
          "safety": 5,
          "conciseness": 4,
          "serious_failure": false,
          "serious_failure_reason": null,
          "rationale": "Mostly correct with one missing detail."
        }
        """
    )

    assert parsed["correctness"] == 4
    assert parsed["serious_failure"] is False
    assert parsed["serious_failure_reason"] is None
    assert parsed["rationale"] == "Mostly correct with one missing detail."


def test_parse_judge_json_rejects_invalid_scores():
    with pytest.raises(ValueError, match="correctness"):
        parse_judge_json(
            """
            {
              "correctness": 6,
              "completeness": 3,
              "faithfulness": 5,
              "citation_quality": 4,
              "safety": 5,
              "conciseness": 4,
              "serious_failure": false,
              "serious_failure_reason": null,
              "rationale": "Bad score."
            }
            """
        )


def test_build_judge_input_contains_required_eval_context():
    payload = build_judge_input(
        case={
            "id": "case-1",
            "query": "query",
            "gold_answer": "gold",
            "expected_answer_points": ["point"],
            "expected_source": {"doc_id": "doc"},
            "expects_safety_warning": True,
            "unanswerable_reason": "not live data",
        },
        agent_response={
            "answer": "answer",
            "sources": [{"doc_id": "doc", "page": 1, "snippet": "source"}],
        },
        rag_result=None,
        retrieval_debug={
            "top_chunks": [{"rank": 1, "doc_id": "doc", "page": 1, "snippet": "retrieved"}]
        },
        scoring={"rule_score": 72.5, "serious_failures": []},
    )

    assert payload["query"] == "query"
    assert payload["gold_answer"] == "gold"
    assert payload["expected_answer_points"] == ["point"]
    assert payload["expected_source"] == {"doc_id": "doc"}
    assert payload["model_answer"] == "answer"
    assert payload["cited_sources"][0]["doc_id"] == "doc"
    assert payload["retrieved_context_snippets"][0]["rank"] == 1
    assert payload["expects_safety_warning"] is True
    assert payload["unanswerable_reason"] == "not live data"
