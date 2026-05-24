from tests.rag_eval.audit import build_judge_audit_sample


def _result(index, *, variant="V0", bucket="borderline", safety=False, citation=True):
    if bucket == "pass":
        judge_result = {
            "correctness": 5,
            "completeness": 4,
            "faithfulness": 5,
            "citation_quality": 4,
            "safety": 5,
            "conciseness": 4,
            "serious_failure": False,
            "serious_failure_reason": None,
            "rationale": "Pass.",
        }
    elif bucket == "fail":
        judge_result = {
            "correctness": 2,
            "completeness": 2,
            "faithfulness": 2,
            "citation_quality": 2,
            "safety": 3,
            "conciseness": 4,
            "serious_failure": True,
            "serious_failure_reason": "Wrong answer.",
            "rationale": "Fail.",
        }
    else:
        judge_result = {
            "correctness": 3,
            "completeness": 3,
            "faithfulness": 4,
            "citation_quality": 3,
            "safety": 4,
            "conciseness": 4,
            "serious_failure": False,
            "serious_failure_reason": None,
            "rationale": "Borderline.",
        }
    expected_source = {"doc_id": "doc", "page": 1, "section": "Section"} if citation else {}
    return {
        "case_id": f"case-{index}",
        "variant_id": variant,
        "query": "query",
        "case": {
            "id": f"case-{index}",
            "question_type": "direct_fact",
            "expects_safety_warning": safety,
            "expects_sources": citation,
            "expected_source": expected_source,
            "tags": ["safety"] if safety else [],
        },
        "agent_response": {
            "answer": "answer",
            "sources": [{"doc_id": "doc", "page": 1, "snippet": "source"}],
        },
        "rule_score": 75,
        "borderline": True,
        "borderline_reasons": ["rule_score_between_60_and_80"],
        "serious_failures": [],
        "judge_result": judge_result,
        "judge_error": None,
    }


def test_audit_sample_includes_all_judged_answers_for_small_runs():
    results = [_result(i) for i in range(5)]

    sample = build_judge_audit_sample(results, seed=1)

    assert sample["judged_count"] == 5
    assert sample["sample_size"] == 5
    assert {entry["case_id"] for entry in sample["samples"]} == {f"case-{i}" for i in range(5)}


def test_audit_sample_large_run_preserves_required_coverage_when_available():
    variants = ["V0", "V1", "V2", "V3"]
    buckets = ["pass", "fail", "borderline"]
    results = [
        _result(
            i,
            variant=variants[i % len(variants)],
            bucket=buckets[i % len(buckets)],
            safety=i < 8,
            citation=True,
        )
        for i in range(30)
    ]

    sample = build_judge_audit_sample(results, seed=2)
    entries = sample["samples"]

    assert sample["sample_size"] >= 20
    assert {"pass", "fail", "borderline"} <= {entry["judge_bucket"] for entry in entries}
    assert sum(1 for entry in entries if entry["expects_safety_warning"]) >= 5
    assert sum(1 for entry in entries if entry["expected_source"].get("doc_id")) >= 5
    assert len({entry["variant_id"] for entry in entries}) >= 3
