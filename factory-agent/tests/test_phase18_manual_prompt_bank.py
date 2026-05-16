import json
from pathlib import Path

from factory_agent.planning.intent import (
    intent_constraint_values,
    should_clarify_loto_machine,
    should_route_loto_to_rag,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BANK_PATH = REPO_ROOT / "tests" / "e2e" / "scenarios" / "manual_prompt_regressions.json"

PHASE8_REQUIRED_INTAKE_FIELDS = {
    "exact_prompt_or_user_action",
    "artifact_log_screenshot_or_trace_link",
    "observed_behavior",
    "expected_behavior",
    "selected_existing_oracle_or_proposed_new_oracle",
    "lowest_useful_test_layer",
    "owner",
    "severity",
}

PHASE8_REQUIRED_CLOSURE_FIELDS = {
    "regression_test_file",
    "failing_regression_command",
    "failing_regression_evidence",
    "passing_regression_command",
    "tracker_update",
}


def _load_bank():
    return json.loads(BANK_PATH.read_text(encoding="utf-8"))


def test_phase18_manual_prompt_bank_has_seeded_loto_miss():
    bank = _load_bank()
    prompts = {entry["prompt"] for entry in bank["prompts"]}

    assert "What LOTO procedure applies before working on M-CNC-01?" in prompts


def test_phase18_manual_prompt_bank_entries_have_deterministic_expectations():
    bank = _load_bank()
    required_fields = set(bank["schema"]["required_fields"])

    for entry in bank["prompts"]:
        missing = required_fields - set(entry)
        assert not missing, f"{entry.get('id')} missing required fields: {sorted(missing)}"
        assert entry.get("id")
        assert entry.get("prompt")
        assert entry.get("observed_failure")
        assert entry.get("owner")
        assert entry.get("severity") in {"critical", "high", "medium", "low"}
        expected = entry.get("expected") or {}
        assert expected.get("primary_route")
        assert expected.get("required_final_state")
        assert isinstance(expected.get("clarification_expected"), bool)
        assert entry.get("coverage")


def test_phase8_manual_failure_promotion_workflow_requires_reproducible_intake():
    bank = _load_bank()
    workflow = bank.get("promotion_workflow") or {}

    intake_fields = set(workflow.get("required_intake_fields") or [])
    closure_fields = set(workflow.get("closure_required_fields") or [])
    closure_rule = (workflow.get("closure_rule") or "").lower()

    assert PHASE8_REQUIRED_INTAKE_FIELDS <= intake_fields
    assert PHASE8_REQUIRED_CLOSURE_FIELDS <= closure_fields
    assert "tested manually only" in closure_rule
    assert "failing regression" in closure_rule
    assert "accepted gap" in closure_rule


def test_phase8_bank_entries_map_manual_misses_to_oracles_and_regressions():
    bank = _load_bank()

    for entry in bank["prompts"]:
        assert entry.get("source_prompt") == entry.get("prompt")
        assert entry.get("artifact_link")
        assert entry.get("selected_oracle") or entry.get("proposed_oracle")
        assert entry.get("lowest_test_layer")

        regression = entry.get("regression") or {}
        assert regression.get("test_file")
        assert regression.get("command")
        assert regression.get("failing_before_closure_required") is True
        assert regression.get("failure_evidence")
        assert regression.get("passing_evidence")


def test_phase18_bank_parser_gate_matches_expected_entities_and_clarification():
    bank = _load_bank()

    for entry in bank["prompts"]:
        prompt = entry["prompt"]
        expected = entry["expected"]
        assert intent_constraint_values(prompt, "machine_id") == expected.get("machine_ids", [])
        assert intent_constraint_values(prompt, "job_id") == expected.get("job_ids", [])
        assert should_clarify_loto_machine(prompt) is expected["clarification_expected"]
        if expected["primary_route"] == "rag_loto":
            assert should_route_loto_to_rag(prompt) is True
