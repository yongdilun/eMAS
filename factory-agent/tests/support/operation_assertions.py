from __future__ import annotations

from typing import Any

from tests.support.stateful_oracle_harness import StatefulOracleHarness


def assert_jobs_match(harness: StatefulOracleHarness, expected_jobs: list[dict[str, Any]]) -> None:
    actual_by_id = {str(row.get("id") or row.get("job_id")): row for row in harness.job_snapshot()}
    for expected in expected_jobs:
        job_id = str(expected.get("id") or expected.get("job_id"))
        assert job_id in actual_by_id, f"Missing expected job {job_id}"
        actual = actual_by_id[job_id]
        for key, value in expected.items():
            if key in {"id", "job_id"}:
                continue
            assert actual.get(key) == value, (
                f"Job {job_id} field {key} expected {value!r}, got {actual.get(key)!r}"
            )


def assert_final_state_matches_oracle(harness: StatefulOracleHarness, oracle: dict[str, Any]) -> None:
    expected = oracle["expected_final_state"]
    assert harness.session_phase == expected["session_phase"]
    assert harness.pending_approval_id == expected.get("pending_approval_id")
    assert_jobs_match(harness, expected.get("jobs") or [])


def assert_unchanged_rows(harness: StatefulOracleHarness, expected_rows: list[dict[str, Any]]) -> None:
    assert_jobs_match(harness, expected_rows)


def assert_audit_rows_match(harness: StatefulOracleHarness, expected_rows: list[dict[str, Any]]) -> None:
    assert len(harness.audit_rows) == len(expected_rows)
    unmatched = list(harness.audit_rows)
    for expected in expected_rows:
        match_index = next(
            (
                idx
                for idx, actual in enumerate(unmatched)
                if _audit_row_matches(actual, expected)
            ),
            None,
        )
        assert match_index is not None, f"Missing audit row matching {expected!r}; actual={harness.audit_rows!r}"
        unmatched.pop(match_index)


def assert_timeline_contains_chain(
    harness: StatefulOracleHarness,
    expected_events: list[dict[str, Any]],
) -> None:
    start = 0
    for expected in expected_events:
        match_index = next(
            (
                idx
                for idx in range(start, len(harness.timeline))
                if _event_matches(harness.timeline[idx], expected)
            ),
            None,
        )
        assert match_index is not None, (
            f"Missing timeline event after index {start}: {expected!r}; "
            f"actual={harness.timeline!r}"
        )
        start = match_index + 1


def assert_no_timeline_event(
    harness: StatefulOracleHarness,
    event: str,
    *,
    approval_id: str | None = None,
) -> None:
    for row in harness.timeline:
        if row.get("event") != event:
            continue
        if approval_id is not None and row.get("approval_id") != approval_id:
            continue
        raise AssertionError(f"Unexpected timeline event {event!r}: {row!r}")


def assert_event_count(
    harness: StatefulOracleHarness,
    event: str,
    *,
    approval_id: str | None = None,
    count: int,
) -> None:
    actual = 0
    for row in harness.timeline:
        if row.get("event") != event:
            continue
        if approval_id is not None and row.get("approval_id") != approval_id:
            continue
        actual += 1
    assert actual == count, f"Expected {count} {event} events for {approval_id}, got {actual}"


def _audit_row_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if key == "must_exist_once":
            continue
        if key == "row_ids":
            if sorted(actual.get("row_ids") or []) != sorted(value or []):
                return False
            continue
        if actual.get(key) != value:
            return False
    return True


def _event_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if key == "sequence":
            if actual.get("sequence", actual.get("sequence_number")) != value:
                return False
            continue
        if actual.get(key) != value:
            return False
    return True
