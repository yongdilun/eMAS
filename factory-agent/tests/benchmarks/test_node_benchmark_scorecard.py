from __future__ import annotations

import json

from .node_benchmark_runner import (
    build_autonomy_scorecard,
    benchmark_report_dir,
    load_cases,
    live_llm_benchmark_enabled,
    scorecard_enabled,
    write_autonomy_scorecard,
)


def _case(
    case_id: str,
    node: str,
    behavior: str,
    *,
    prompt: str | None = None,
    signals: list[str] | None = None,
    safety_cap: str | None = None,
    expected_recommendation: str | None = None,
) -> dict:
    case = {
        "id": case_id,
        "node": node,
        "behavior": behavior,
        "prompt": prompt or behavior,
        "expected_evidence": ["planner_diagnostics"],
    }
    probe = {}
    if signals is not None:
        probe["signals"] = signals
    if safety_cap is not None:
        probe["safety_cap"] = safety_cap
    if expected_recommendation is not None:
        probe["expected_recommendation"] = expected_recommendation
    if probe:
        case["autonomy_probe"] = probe
    return case


def _passed_result(case: dict, *, diagnostics: dict | None = None) -> dict:
    return {
        "id": case["id"],
        "node": case["node"],
        "behavior": case["behavior"],
        "status": "passed",
        "failures": [],
        "evidence": {
            "planner_proposer_diagnostics": diagnostics or {},
            "planner_diagnostics": {"planner_decision_proposer": diagnostics or {}},
        },
    }


def test_scorecard_recommends_upgrade_candidate_for_bounded_llm_lift():
    cases = [
        _case(
            "semantic-llm-repair",
            "semantic_intake_node",
            "LLM repair/fallback",
            signals=["multi_intent", "missing_entity", "llm_repair", "conditional"],
            safety_cap="read_only",
            expected_recommendation="upgrade_candidate",
        ),
        _case(
            "semantic-pronoun",
            "semantic_intake_node",
            "pronoun follow-up",
            signals=["ambiguity", "cross_entity", "multi_step"],
            safety_cap="read_only",
        ),
    ]
    results = [_passed_result(case, diagnostics={"real_llm_mode": True, "llm_invoked": True}) for case in cases]

    scorecard = build_autonomy_scorecard(cases, results_by_node={"semantic_intake_node": results}, live_llm_enabled=True)
    node = scorecard["nodes"]["semantic_intake_node"]

    assert node["recommendation"] == "upgrade_candidate"
    assert node["score"] >= 75
    assert node["safety_cap"] == "read_only"
    assert node["llm_lift_signal"] > 0
    assert node["expectation_matched"] is True


def test_scorecard_blocks_autonomy_for_execution_authority_even_when_complex():
    cases = [
        _case(
            "execution-write",
            "tool_execution_node",
            "approval-required write staging",
            signals=["write_approval", "parallel", "failure_recovery", "llm_repair"],
        )
    ]
    results = [_passed_result(cases[0], diagnostics={"real_llm_mode": True, "llm_invoked": True})]

    scorecard = build_autonomy_scorecard(cases, results_by_node={"tool_execution_node": results}, live_llm_enabled=True)
    node = scorecard["nodes"]["tool_execution_node"]

    assert node["recommendation"] == "do_not_autonomize"
    assert node["safety_cap"] == "no_autonomous_action"
    assert "owns execution or final authority" in " ".join(node["reasons"])


def test_scorecard_reports_guarded_pilot_when_approval_required():
    cases = [
        _case(
            "choose-write",
            "planner_choose_tool_node",
            "LLM choice among candidates for approval-required mutation",
            signals=["candidate_conflict", "write_approval", "llm_choice", "schema_validation"],
            safety_cap="approval_required",
        ),
        _case(
            "choose-outside-window",
            "planner_choose_tool_node",
            "outside-window rejection",
            signals=["candidate_conflict", "validation_rejection", "fail_closed"],
            safety_cap="approval_required",
        ),
    ]
    results = [_passed_result(case, diagnostics={"llm_invoked": False, "real_llm_mode": False}) for case in cases]

    scorecard = build_autonomy_scorecard(cases, results_by_node={"planner_choose_tool_node": results})
    node = scorecard["nodes"]["planner_choose_tool_node"]

    assert node["recommendation"] == "guarded_pilot"
    assert node["safety_cap"] == "approval_required"
    assert node["guardability"] >= 18


def test_write_autonomy_scorecard_emits_json_and_markdown(tmp_path):
    cases = [
        _case(
            "retrieval-reranker",
            "tool_retrieval_node",
            "reranker on/off",
            signals=["candidate_conflict", "llm_reranker"],
            safety_cap="read_only",
        )
    ]
    results = {"tool_retrieval_node": [_passed_result(cases[0])]}

    payload = write_autonomy_scorecard(
        cases,
        results_by_node=results,
        report_dir=tmp_path,
        live_llm_enabled=False,
    )

    json_path = tmp_path / "autonomy_scorecard.latest.json"
    md_path = tmp_path / "autonomy_scorecard.md"
    assert json_path.exists()
    assert md_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["nodes"] == payload["nodes"]
    assert "| Node | Score | Recommendation | Safety Cap |" in md_path.read_text(encoding="utf-8")


def test_scorecard_env_controls_are_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("FACTORY_AGENT_NODE_BENCHMARK_SCORECARD", raising=False)
    monkeypatch.delenv("FACTORY_AGENT_NODE_BENCHMARK_LIVE_LLM", raising=False)
    monkeypatch.setenv("FACTORY_AGENT_NODE_BENCHMARK_REPORT_DIR", str(tmp_path))

    assert scorecard_enabled() is False
    assert live_llm_benchmark_enabled() is False
    assert benchmark_report_dir() == tmp_path

    monkeypatch.setenv("FACTORY_AGENT_NODE_BENCHMARK_SCORECARD", "1")
    monkeypatch.setenv("FACTORY_AGENT_NODE_BENCHMARK_LIVE_LLM", "true")

    assert scorecard_enabled() is True
    assert live_llm_benchmark_enabled() is True


def test_real_case_bank_accepts_autonomy_probe_metadata():
    cases = load_cases("semantic_intake_node")
    annotated = {case["id"]: case["autonomy_probe"] for case in cases if "autonomy_probe" in case}

    assert annotated["semantic-intake-010-llm-repair-fallback"]["expected_recommendation"] == "upgrade_candidate"
