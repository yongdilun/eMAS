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

PHASE13_SCREENSHOT_FIRST_TEST_LAYERS = {
    "backend_contract",
    "reducer_component",
    "mocked_playwright",
    "seeded_playwright",
    "real_langgraph",
}

VAGUE_VALUES = {
    "",
    "unknown",
    "tbd",
    "todo",
    "n/a",
    "none",
    "manual only",
    "tested manually only",
}


def _load_bank():
    return json.loads(BANK_PATH.read_text(encoding="utf-8"))


def _assert_concrete(value, label: str) -> None:
    assert value is not None, f"{label} is missing"
    if isinstance(value, str):
        normalized = value.strip().lower()
        assert normalized not in VAGUE_VALUES, f"{label} is vague: {value!r}"
        assert "tested manually only" not in normalized, f"{label} is vague: {value!r}"
        return
    if isinstance(value, list):
        assert value, f"{label} must not be empty"
        for index, item in enumerate(value):
            _assert_concrete(item, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        assert value, f"{label} must not be empty"
        for key, item in value.items():
            _assert_concrete(item, f"{label}.{key}")
        return


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


def test_phase13_manual_screenshot_entries_are_specific_and_executable():
    bank = _load_bank()
    required_fields = set(bank["schema"]["manual_screenshot_required_fields"])
    allowed_layers = set(bank["schema"]["manual_screenshot_first_test_layer_values"])
    entries = bank.get("manual_screenshot_regressions") or []

    assert entries, "Phase 13 must keep manual screenshot regressions in the structured bank"
    assert "phase13-chat514-non-terminal-snapshot-idle" in {entry.get("id") for entry in entries}
    assert PHASE13_SCREENSHOT_FIRST_TEST_LAYERS <= allowed_layers

    for entry in entries:
        missing = required_fields - set(entry)
        assert not missing, f"{entry.get('id')} missing manual screenshot fields: {sorted(missing)}"
        assert entry["severity"] in {"critical", "high", "medium", "low"}
        assert entry["first_test_layer"] in allowed_layers
        assert entry["status"] in {"open", "in_progress", "promoted_regression", "accepted_gap"}

        _assert_concrete(entry["screenshot_symptom"], f"{entry['id']}.screenshot_symptom")
        _assert_concrete(entry["user_prompt"], f"{entry['id']}.user_prompt")
        _assert_concrete(entry["observed_bad_state"], f"{entry['id']}.observed_bad_state")
        _assert_concrete(entry["forbidden_visible_text"], f"{entry['id']}.forbidden_visible_text")

        expected_backend = entry["expected_backend_session_state"]
        assert expected_backend.get("allowed_statuses") or expected_backend.get("forbidden_statuses")
        _assert_concrete(expected_backend, f"{entry['id']}.expected_backend_session_state")

        expected_document = entry["expected_response_document"]
        assert expected_document.get("allowed_states"), f"{entry['id']} must declare expected response_document states"
        assert expected_document.get("revision"), f"{entry['id']} must declare expected response_document revision behavior"
        assert expected_document.get("current_step"), f"{entry['id']} must declare expected current step behavior"
        assert (
            expected_document.get("required_block_types_any")
            or expected_document.get("required_block_types_all")
        ), f"{entry['id']} must declare expected response_document block types"
        _assert_concrete(expected_document, f"{entry['id']}.expected_response_document")

        expected_dom = entry["expected_visible_dom"]
        assert (
            expected_dom.get("required_visible_block_types_any")
            or expected_dom.get("required_text_any")
        ), f"{entry['id']} must declare expected visible DOM evidence"
        _assert_concrete(expected_dom, f"{entry['id']}.expected_visible_dom")

        repro = entry["reproducer"]
        assert (
            repro.get("minimal_backend_fixture")
            or repro.get("mocked_playwright_flow")
            or repro.get("real_flow_prompt")
        ), f"{entry['id']} must map to a backend fixture or real-flow reproducer"
        _assert_concrete(repro, f"{entry['id']}.reproducer")

        regression = entry["regression"]
        assert regression.get("test_file")
        assert regression.get("command")
        assert regression.get("failing_before_closure_required") is True
        assert regression.get("failure_evidence")
        assert regression.get("passing_evidence")

        linked = entry["linked_coverage"]
        assert linked.get("RD-001_transition_oracle")
        assert linked.get("RD-002_transition_oracle")
        assert linked.get("semantic_probe")
        _assert_concrete(linked, f"{entry['id']}.linked_coverage")


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
