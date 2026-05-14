import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = REPO_ROOT / "tests" / "e2e" / "scenarios" / "seed_pipeline.json"


def _load_scenarios():
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


def test_seed_pipeline_manifest_is_shared_and_complete():
    scenarios = _load_scenarios()
    assert len(scenarios) >= 60

    counts = {}
    seen = set()
    for scenario in scenarios:
        assert scenario["id"] not in seen
        seen.add(scenario["id"])
        for field in ("id", "category", "input", "entrypoint", "seed_profile", "approval_policy", "expected_status"):
            assert scenario.get(field) not in (None, "")
        counts[scenario["category"]] = counts.get(scenario["category"], 0) + 1

    for category in ("intent", "backend_read", "crud", "scheduling", "approval"):
        assert counts.get(category, 0) >= 10
    assert counts.get("factory_agent", 0) >= 50
    assert counts.get("negative", 0) >= 10


@pytest.mark.parametrize(
    "scenario",
    [s for s in _load_scenarios() if s["category"] == "factory_agent"],
    ids=lambda s: s["id"],
)
def test_factory_agent_scenarios_define_executable_contracts(scenario):
    assert scenario["entrypoint"] == "factory_agent"
    allows_no_tool_plan = scenario.get("complexity") == "knowledge_only_no_tool_plan"
    if allows_no_tool_plan:
        assert scenario["expected_tools"] == []
    else:
        assert scenario["expected_tools"], "factory-agent scenarios must name expected tool calls"
    assert scenario["approval_policy"] in {"none", "approve", "reject"}
    assert scenario["expected_response_contains"], "artifact assertions need response evidence"
    assert scenario["coverage_area"], "factory-agent scenarios need a coverage_area"
    assert scenario["complexity"] in {
        "single_step",
        "filtered_read",
        "filtered_sorted_read",
        "multi_step",
        "multi_step_approval",
        "approval_write",
        "approval_write_preflight",
        "approval_rejection",
        "soft_failure",
        "knowledge_only_no_tool_plan",
    }
    assert scenario["difficulty"] in {"easy", "medium", "hard"}

    if scenario["approval_policy"] == "none":
        assert all(not name.startswith(("post__", "put__", "patch__", "delete__")) for name in scenario["expected_tools"])
    else:
        assert any(name.startswith(("post__", "put__", "patch__", "delete__")) for name in scenario["expected_tools"])


@pytest.mark.parametrize(
    "scenario",
    [s for s in _load_scenarios() if s["entrypoint"] == "factory_agent"],
    ids=lambda s: s["id"],
)
def test_live_factory_agent_scenarios_are_categorized(scenario):
    assert scenario["coverage_area"], "live factory-agent scenarios need a coverage_area"
    assert scenario["complexity"], "live factory-agent scenarios need complexity"
    assert scenario["difficulty"] in {"easy", "medium", "hard"}


def test_reliability_scenarios_cover_hard_workflow_edges():
    scenarios = _load_scenarios()
    reliability = {s.get("reliability_area"): s for s in scenarios if s.get("category") == "reliability"}

    required = {
        "pause_resume_workflow",
        "llm_failure_recovery",
        "transactional_rollback_safety",
        "rag_normal_tool_mix",
    }
    assert required <= set(reliability), "reliability manifest is missing required hard-edge scenarios"

    for area in required:
        scenario = reliability[area]
        assert scenario["difficulty"] == "hard"
        assert scenario["test_surface"], f"{scenario['id']} must point at the executable test"
        assert scenario["expected_response_contains"], f"{scenario['id']} needs observable evidence"

    assert reliability["pause_resume_workflow"]["approval_policy"] == "approve"
    assert reliability["llm_failure_recovery"]["approval_policy"] == "none"
    assert reliability["transactional_rollback_safety"]["entrypoint"] == "go_e2e"
    assert reliability["rag_normal_tool_mix"]["expected_tools"] == ["get__machines_{id}"]
