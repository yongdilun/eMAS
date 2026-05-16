import json
from pathlib import Path

from factory_agent.planning.intent import (
    intent_constraint_values,
    should_clarify_loto_machine,
    should_route_loto_to_rag,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BANK_PATH = REPO_ROOT / "tests" / "e2e" / "scenarios" / "manual_prompt_regressions.json"


def _load_bank():
    return json.loads(BANK_PATH.read_text(encoding="utf-8"))


def test_phase18_manual_prompt_bank_has_seeded_loto_miss():
    bank = _load_bank()
    prompts = {entry["prompt"] for entry in bank["prompts"]}

    assert "What LOTO procedure applies before working on M-CNC-01?" in prompts


def test_phase18_manual_prompt_bank_entries_have_deterministic_expectations():
    bank = _load_bank()

    for entry in bank["prompts"]:
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
