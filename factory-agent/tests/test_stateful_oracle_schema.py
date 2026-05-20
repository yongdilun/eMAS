import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ORACLE_DIR = REPO_ROOT / "tests" / "e2e" / "scenarios" / "stateful_oracles"

REQUIRED_FIELDS = {
    "id",
    "title",
    "risk",
    "prompt",
    "initial_state",
    "expected_approvals",
    "expected_intermediate_states",
    "expected_final_state",
    "expected_audit_rows",
    "expected_timeline",
    "expected_sse_or_snapshot",
    "expected_final_response",
    "expected_ui",
    "expected_unchanged_rows",
    "invariants",
    "required_layers",
    "weakness_from_phase0",
}

ID_PATTERN = re.compile(r"^SO-\d{3}$")
OPTIONALLY_EMPTY_FIELDS = {
    "expected_approvals",
    "expected_audit_rows",
    "expected_unchanged_rows",
}


def _oracle_files() -> list[Path]:
    return sorted(ORACLE_DIR.glob("*.json"))


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_stateful_oracle_bank_exists_and_has_initial_phase_1_entries():
    files = _oracle_files()

    assert ORACLE_DIR.is_dir(), f"Missing oracle directory: {ORACLE_DIR}"
    assert len(files) >= 5


def test_stateful_oracles_have_required_contract_fields_and_stable_ids():
    seen_ids: set[str] = set()

    for path in _oracle_files():
        oracle = _load_json(path)
        missing = REQUIRED_FIELDS - set(oracle)
        assert not missing, f"{path.name} missing required fields: {sorted(missing)}"

        oracle_id = oracle["id"]
        assert ID_PATTERN.match(oracle_id), f"{path.name} has unstable id {oracle_id!r}"
        assert oracle_id not in seen_ids, f"Duplicate oracle id {oracle_id}"
        seen_ids.add(oracle_id)

        expected_prefix = oracle_id.lower()
        assert path.stem.startswith(expected_prefix), (
            f"{path.name} must start with stable id prefix {expected_prefix}"
        )

        assert "expected_intents" in oracle or "expected_route" in oracle, (
            f"{path.name} must define expected_intents or expected_route"
        )

        for field in REQUIRED_FIELDS:
            value = oracle[field]
            assert value is not None, f"{path.name} field {field} cannot be null"
            if isinstance(value, str):
                assert value.strip(), f"{path.name} field {field} cannot be blank"
            if isinstance(value, (list, dict)) and field not in OPTIONALLY_EMPTY_FIELDS:
                assert value, f"{path.name} field {field} cannot be empty"


def test_stateful_oracle_transition_contracts_are_actionable():
    for path in _oracle_files():
        oracle = _load_json(path)
        timeline_events = [entry.get("event") for entry in oracle["expected_timeline"]]
        approval_required = oracle["expected_sse_or_snapshot"].get(
            "approval_required", True
        )

        assert "operation_started" in timeline_events, f"{path.name} lacks operation start"
        assert oracle["invariants"], f"{path.name} lacks invariant names"
        assert oracle["required_layers"], f"{path.name} lacks required layers"

        if approval_required:
            assert "approval_requested" in timeline_events, (
                f"{path.name} lacks approval request"
            )
            assert oracle["expected_approvals"], (
                f"{path.name} lacks approval expectations"
            )
        else:
            assert not oracle["expected_approvals"], (
                f"{path.name} marks approval not required but defines approvals"
            )
            assert "no_approval_required" in oracle["invariants"], (
                f"{path.name} must include no_approval_required invariant"
            )

        approval_ids = [
            approval.get("approval_id")
            for approval in oracle["expected_approvals"]
            if approval.get("approval_id")
        ]
        assert len(approval_ids) == len(set(approval_ids)), (
            f"{path.name} reuses an approval id inside one scenario"
        )
