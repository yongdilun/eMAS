from __future__ import annotations

from tests.support.operation_assertions import assert_audit_rows_match
from tests.support.operation_assertions import assert_event_count
from tests.support.operation_assertions import assert_final_state_matches_oracle
from tests.support.operation_assertions import assert_no_timeline_event
from tests.support.operation_assertions import assert_timeline_contains_chain
from tests.support.operation_assertions import assert_unchanged_rows
from tests.support.stateful_oracle_harness import StatefulOracleHarness


def _dry_run_row_ids(dry_run: dict) -> list[str]:
    body = dry_run["body"]
    return [str(row["row_id"]) for row in body["row_results"]]


def test_so001_original_state_cascade_mutates_only_original_source_sets():
    harness = StatefulOracleHarness.from_oracle_id("SO-001")
    oracle = harness.oracle
    harness.start_operation(intent_count=2)

    first = harness.dry_run_oracle_intent(0)
    assert _dry_run_row_ids(first) == ["JOB-SO001-MED-01", "JOB-SO001-MED-02"]
    assert harness.pending_approval_id == "approval-so-001-1"
    assert harness.approve("approval-so-001-1", auto_complete=False).ok is True

    assert harness.select_job_ids({"priority": "high"}, state_basis="current") == [
        "JOB-SO001-HIGH-01",
        "JOB-SO001-HIGH-02",
        "JOB-SO001-MED-01",
        "JOB-SO001-MED-02",
    ]

    second = harness.dry_run_oracle_intent(1)
    assert _dry_run_row_ids(second) == ["JOB-SO001-HIGH-01", "JOB-SO001-HIGH-02"]
    assert harness.pending_approval_id == "approval-so-001-2"
    assert harness.approve("approval-so-001-2").ok is True

    assert_final_state_matches_oracle(harness, oracle)
    assert_audit_rows_match(harness, oracle["expected_audit_rows"])
    assert_unchanged_rows(harness, oracle["expected_unchanged_rows"])
    assert_timeline_contains_chain(harness, oracle["expected_timeline"])


def test_so006_expired_second_approval_rejects_late_commit_without_mutation():
    harness = StatefulOracleHarness.from_oracle_id("SO-006")
    oracle = harness.oracle
    harness.start_operation(intent_count=2)

    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-006-1").ok is True
    harness.dry_run_oracle_intent(1)
    assert harness.pending_approval_id == "approval-so-006-2"

    expired = harness.expire_approval("approval-so-006-2")
    assert expired.http_status == 409
    assert expired.error == "expired_approval"

    late = harness.approve("approval-so-006-2", source="late_approve_attempt")
    assert late.http_status == 409
    assert late.error == "expired_approval"

    assert_no_timeline_event(harness, "commit_started", approval_id="approval-so-006-2")
    assert_final_state_matches_oracle(harness, oracle)
    assert_audit_rows_match(harness, oracle["expected_audit_rows"])
    assert_unchanged_rows(harness, oracle["expected_unchanged_rows"])
    assert_timeline_contains_chain(harness, oracle["expected_timeline"])


def test_so007_approval_double_click_and_refresh_replay_are_idempotent():
    harness = StatefulOracleHarness.from_oracle_id("SO-007")
    oracle = harness.oracle
    harness.start_operation()

    harness.dry_run_oracle_intent(0)
    first = harness.approve(
        "approval-so-007-1",
        idempotency_key="idem-so-007-approve",
        auto_complete=False,
    )
    assert first.ok is True

    double_click = harness.approve(
        "approval-so-007-1",
        idempotency_key="idem-so-007-approve",
        source="double_click",
    )
    refresh = harness.approve(
        "approval-so-007-1",
        idempotency_key="idem-so-007-approve",
        source="refresh_replay",
    )
    assert double_click.replay is True
    assert refresh.replay is True
    harness.complete_operation()

    assert harness.commit_count_by_approval == {"approval-so-007-1": 1}
    assert_event_count(harness, "commit_started", approval_id="approval-so-007-1", count=1)
    assert_event_count(harness, "commit_completed", approval_id="approval-so-007-1", count=1)
    assert_final_state_matches_oracle(harness, oracle)
    assert_audit_rows_match(harness, oracle["expected_audit_rows"])
    assert_unchanged_rows(harness, oracle["expected_unchanged_rows"])
    assert_timeline_contains_chain(harness, oracle["expected_timeline"])


def test_so008_stale_approval_after_user_revision_is_rejected():
    harness = StatefulOracleHarness.from_oracle_id("SO-008")
    oracle = harness.oracle
    harness.start_operation(turn_id="SO-008-T1")

    harness.dry_run_oracle_intent(0)
    assert harness.pending_approval_id == "approval-so-008-old"
    harness.supersede_pending_approvals(
        reason="superseded_by_user_revision",
        turn_id="SO-008-T2",
    )

    harness.dry_run_oracle_intent(1)
    assert harness.pending_approval_id == "approval-so-008-new"
    stale = harness.approve("approval-so-008-old", source="revision_replay")
    assert stale.http_status == 409
    assert stale.error == "stale_approval"
    assert_no_timeline_event(harness, "commit_started", approval_id="approval-so-008-old")

    assert harness.approve("approval-so-008-new").ok is True

    assert_final_state_matches_oracle(harness, oracle)
    assert_audit_rows_match(harness, oracle["expected_audit_rows"])
    assert_unchanged_rows(harness, oracle["expected_unchanged_rows"])
    assert_timeline_contains_chain(harness, oracle["expected_timeline"])


def test_so009_partial_bulk_commit_failure_records_per_row_results():
    harness = StatefulOracleHarness.from_oracle_id("SO-009")
    oracle = harness.oracle
    harness.start_operation()

    dry_run = harness.dry_run_oracle_intent(0)
    assert _dry_run_row_ids(dry_run) == [
        "JOB-SO009-LOW-01",
        "JOB-SO009-LOW-02",
        "JOB-SO009-LOW-03",
    ]

    result = harness.approve("approval-so-009-1")
    assert result.ok is False
    assert result.status == "partial_failure"
    assert {row["row_id"]: row["status"] for row in result.per_row_results} == {
        "JOB-SO009-LOW-01": "succeeded",
        "JOB-SO009-LOW-02": "failed",
        "JOB-SO009-LOW-03": "succeeded",
    }

    assert_final_state_matches_oracle(harness, oracle)
    assert_audit_rows_match(harness, oracle["expected_audit_rows"])
    assert_unchanged_rows(harness, oracle["expected_unchanged_rows"])
    assert_timeline_contains_chain(harness, oracle["expected_timeline"])
