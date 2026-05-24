from pathlib import Path

from tests.rag_eval.judge import DEFAULT_JUDGE_BASE_URL, DEFAULT_JUDGE_MODEL, JudgeConfig
from tests.rag_eval.run_eval import RunnerOptions, _build_judge_config, _maybe_judge_case


def test_run_eval_judge_config_is_off_by_default(monkeypatch):
    for name in (
        "FACTORY_AGENT_RAG_EVAL_JUDGE",
        "RAG_EVAL_JUDGE",
        "RAG_EVAL_JUDGE_BASE_URL",
        "FACTORY_AGENT_RAG_EVAL_JUDGE_BASE_URL",
        "RAG_EVAL_JUDGE_MODEL",
        "FACTORY_AGENT_RAG_EVAL_JUDGE_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    config = _build_judge_config(
        RunnerOptions(cases_path=Path("cases.json"), output_root=Path("out"))
    )

    assert config.enabled is False
    assert config.base_url == DEFAULT_JUDGE_BASE_URL
    assert config.model == DEFAULT_JUDGE_MODEL


def test_maybe_judge_case_skips_when_disabled():
    calls = []

    def fake_judge(**kwargs):
        calls.append(kwargs)
        return {"correctness": 5}

    requested, result, error = _maybe_judge_case(
        case={},
        agent_response={},
        rag_result=None,
        retrieval_debug={},
        scoring={"borderline": True},
        judge_config=JudgeConfig(enabled=False),
        judge_runner=fake_judge,
    )

    assert requested is False
    assert result is None
    assert error is None
    assert calls == []


def test_maybe_judge_case_only_targets_borderline_when_enabled():
    calls = []

    def fake_judge(**kwargs):
        calls.append(kwargs)
        return {
            "correctness": 4,
            "completeness": 4,
            "faithfulness": 4,
            "citation_quality": 4,
            "safety": 5,
            "conciseness": 4,
            "serious_failure": False,
            "serious_failure_reason": None,
            "rationale": "ok",
        }

    skipped = _maybe_judge_case(
        case={},
        agent_response={},
        rag_result=None,
        retrieval_debug={},
        scoring={"borderline": False},
        judge_config=JudgeConfig(enabled=True),
        judge_runner=fake_judge,
    )
    requested, result, error = _maybe_judge_case(
        case={},
        agent_response={},
        rag_result=None,
        retrieval_debug={},
        scoring={"borderline": True},
        judge_config=JudgeConfig(enabled=True),
        judge_runner=fake_judge,
    )

    assert skipped == (False, None, None)
    assert requested is True
    assert result["correctness"] == 4
    assert error is None
    assert len(calls) == 1
