from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

import pytest

from factory_agent.schemas import TimelineEventResponse
from factory_agent.services.session_snapshot_service import _operator_result_content_for_completion
from factory_agent.services.session_snapshot_service import _tool_result_completion_sort_key
from tests.support.operation_assertions import assert_audit_rows_match
from tests.support.operation_assertions import assert_final_state_matches_oracle
from tests.support.operation_assertions import assert_no_timeline_event
from tests.support.stateful_oracle_harness import load_oracle
from tests.support.stateful_oracle_harness import StatefulOracleHarness


KNOWN_HARD_REGRESSION_PROMPT = (
    "change all medium priority job to high then change all high priority job to medium"
)

_APPROVAL_ID_RE = re.compile(r"\bapproval-[A-Za-z0-9][A-Za-z0-9_.:-]*\b")
_FULL_SUCCESS_PHRASES = (
    "all requested changes completed",
    "run complete with no errors",
    "all jobs succeeded",
)


def test_completion_projection_prefers_tool_presentation_message_over_entity_card_text():
    event = TimelineEventResponse(
        event_id="tool:1",
        event_type="tool_result",
        content="**Success**\n\nMachine **M-CNC-01** is currently **RUNNING**.",
        created_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
        status="DONE",
        details={
            "presentation": {
                "render_hint": "entity",
                "message": "Phase 9 stream drop recovered by snapshot polling.",
            }
        },
    )

    assert _operator_result_content_for_completion(event) == "Phase 9 stream drop recovered by snapshot polling."


def test_completion_projection_uses_step_index_as_tool_result_tie_breaker():
    created_at = datetime(2026, 5, 17, tzinfo=timezone.utc)
    first = TimelineEventResponse(
        event_id="tool:1",
        event_type="tool_result",
        content="first",
        created_at=created_at,
        step_context={"step_index": 0},
    )
    final = TimelineEventResponse(
        event_id="tool:3",
        event_type="tool_result",
        content="final",
        created_at=created_at,
        step_context={"step_index": 2},
    )

    assert max([first, final], key=_tool_result_completion_sort_key) is final


@dataclass(frozen=True)
class Phase4Evidence:
    graph_actions: list[dict[str, Any]]
    timeline_events: list[dict[str, Any]]
    sse_events: list[dict[str, Any]]
    approvals: dict[str, dict[str, Any]]
    audit_rows: list[dict[str, Any]]
    committed_jobs: dict[str, dict[str, Any]]
    session_phase: str
    pending_approval_id: str | None
    final_response: str


def _evidence_from_harness(harness: StatefulOracleHarness, *, final_response: str) -> Phase4Evidence:
    return Phase4Evidence(
        graph_actions=deepcopy(harness.timeline),
        timeline_events=deepcopy(harness.timeline),
        sse_events=deepcopy(harness.sse_events),
        approvals=deepcopy(harness.approvals),
        audit_rows=deepcopy(harness.audit_rows),
        committed_jobs={str(row["id"]): deepcopy(row) for row in harness.job_snapshot()},
        session_phase=harness.session_phase,
        pending_approval_id=harness.pending_approval_id,
        final_response=final_response,
    )


def _event_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("event"),
        row.get("approval_id"),
        row.get("intent_id"),
        row.get("decision"),
        row.get("status"),
        row.get("reason"),
        row.get("row_count"),
        row.get("succeeded_count"),
        row.get("failed_count"),
    )


def _event_matches_expected(row: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if key == "sequence":
            if row.get("sequence", row.get("sequence_number")) != value:
                return False
            continue
        if row.get(key) != value:
            return False
    return True


def _assert_expected_timeline_chain(evidence: Phase4Evidence, oracle: dict[str, Any]) -> None:
    if not evidence.timeline_events:
        raise AssertionError("Timeline evidence is required for mutating oracle scenarios")

    start = 0
    for expected in oracle.get("expected_timeline") or []:
        match_index = next(
            (
                idx
                for idx in range(start, len(evidence.timeline_events))
                if _event_matches_expected(evidence.timeline_events[idx], expected)
            ),
            None,
        )
        assert match_index is not None, (
            f"Missing expected timeline event after index {start}: {expected!r}; "
            f"actual={evidence.timeline_events!r}"
        )
        start = match_index + 1


def _assert_timeline_and_sse_match_graph_actions(evidence: Phase4Evidence) -> None:
    graph = [_event_signature(row) for row in evidence.graph_actions]
    timeline = [_event_signature(row) for row in evidence.timeline_events]
    assert timeline == graph, "Projected timeline must match graph actions in order"

    sse_ids = [int(frame["id"]) for frame in evidence.sse_events if str(frame.get("id") or "").isdigit()]
    assert sse_ids == sorted(sse_ids), f"SSE ids must be monotonic: {sse_ids!r}"
    assert len(sse_ids) == len(set(sse_ids)), f"SSE ids must not duplicate: {sse_ids!r}"
    sse = [_event_signature(frame.get("data") or {}) for frame in evidence.sse_events]
    assert sse == graph, "SSE activity events must match graph actions in order"


def _expected_approval_ids(oracle: dict[str, Any]) -> list[str]:
    return [str(row["approval_id"]) for row in oracle.get("expected_approvals") or []]


def _assert_approval_ids_are_real_and_distinct(evidence: Phase4Evidence, oracle: dict[str, Any]) -> None:
    expected_ids = _expected_approval_ids(oracle)
    assert len(expected_ids) == len(set(expected_ids)), f"Oracle approval ids must be distinct: {expected_ids!r}"

    requested_ids = [
        str(row.get("approval_id"))
        for row in evidence.timeline_events
        if row.get("event") == "approval_requested" and row.get("approval_id")
    ]
    assert requested_ids == expected_ids, (
        f"Timeline approval requests must match expected approvals exactly; "
        f"expected={expected_ids!r} actual={requested_ids!r}"
    )
    assert len(requested_ids) == len(set(requested_ids)), (
        f"Timeline reused an approval id: {requested_ids!r}"
    )

    actual_ids = set(evidence.approvals)
    for row in evidence.timeline_events:
        approval_id = row.get("approval_id")
        if approval_id:
            assert approval_id in actual_ids, f"Timeline references missing approval {approval_id!r}"

    mentioned_ids = set(_APPROVAL_ID_RE.findall(evidence.final_response or ""))
    assert mentioned_ids <= actual_ids, (
        f"Final response mentions stale approval ids: {sorted(mentioned_ids - actual_ids)!r}"
    )
    if oracle.get("expected_route") and not oracle.get("expected_intents"):
        return
    missing_from_final = set(expected_ids) - mentioned_ids
    assert not missing_from_final, (
        f"Final response must cite the actual approvals used: {sorted(missing_from_final)!r}"
    )


def _assert_commits_match_approval_and_audit(evidence: Phase4Evidence) -> None:
    for row in evidence.timeline_events:
        if row.get("event") not in {"commit_completed", "commit_partial_failure", "commit_failed"}:
            continue
        approval_id = str(row.get("approval_id") or "")
        assert approval_id in evidence.approvals, f"Commit references missing approval {approval_id!r}"
        status = str(evidence.approvals[approval_id].get("status") or "").lower()
        assert status in {"accepted", "approved"}, (
            f"Commit for {approval_id!r} was not backed by an accepted approval; status={status!r}"
        )
        assert any(audit.get("approval_id") == approval_id for audit in evidence.audit_rows), (
            f"Commit for {approval_id!r} has no audit evidence"
        )


def _assert_no_final_before_required_terminal_evidence(evidence: Phase4Evidence, oracle: dict[str, Any]) -> None:
    final_indexes = [
        idx for idx, row in enumerate(evidence.timeline_events) if row.get("event") == "final_response_created"
    ]
    if not final_indexes:
        return
    final_index = final_indexes[0]
    required_indexes: list[int] = []
    for approval in oracle.get("expected_approvals") or []:
        approval_id = str(approval.get("approval_id") or "")
        decision = str(approval.get("decision") or "accepted")
        if decision == "superseded":
            required_event = "approval_invalidated"
        elif decision == "expired":
            required_event = "approval_expired"
        elif not decision.startswith("accepted"):
            required_event = "approval_decided"
        elif any(row.get("event") == "commit_partial_failure" and row.get("approval_id") == approval_id for row in evidence.timeline_events):
            required_event = "commit_partial_failure"
        else:
            required_event = "commit_completed"
        idx = next(
            (
                i
                for i, row in enumerate(evidence.timeline_events)
                if row.get("event") == required_event and row.get("approval_id") == approval_id
            ),
            None,
        )
        assert idx is not None, f"Missing terminal evidence {required_event!r} for {approval_id!r}"
        required_indexes.append(idx)
    if not required_indexes:
        read_or_retrieval_indexes = [
            idx
            for idx, row in enumerate(evidence.timeline_events)
            if row.get("event")
            in {
                "tool_read_completed",
                "rag_retrieval_completed",
                "snapshot_terminal_persisted",
            }
        ]
        if read_or_retrieval_indexes:
            assert final_index > max(read_or_retrieval_indexes), (
                "Final response was emitted before read/retrieval terminal evidence"
            )
        return
    assert final_index > max(required_indexes), (
        "Final response was emitted before all required approval/commit evidence"
    )


def _assert_final_response_matches_oracle(evidence: Phase4Evidence, oracle: dict[str, Any]) -> None:
    text = evidence.final_response or ""
    assert text.strip(), "Final assistant response is required"
    expected = oracle.get("expected_final_response") or {}
    for phrase in expected.get("must_include") or []:
        assert phrase in text, f"Final response missing required phrase {phrase!r}: {text!r}"
    lowered = text.lower()
    for phrase in expected.get("must_not_include") or []:
        assert not _contains_forbidden_phrase(lowered, phrase.lower()), (
            f"Final response contains forbidden phrase {phrase!r}: {text!r}"
        )

    if any(row.get("event") == "commit_partial_failure" for row in evidence.timeline_events):
        assert "failed" in lowered or "partial" in lowered or "with errors" in lowered
        for phrase in _FULL_SUCCESS_PHRASES:
            assert phrase not in lowered, f"Partial failure claimed full success: {phrase!r}"

    if any(str(ap.get("decision") or "") == "rejected" for ap in oracle.get("expected_approvals") or []):
        assert "rejected" in lowered or "declined" in lowered
        for phrase in _FULL_SUCCESS_PHRASES:
            assert phrase not in lowered, f"Rejected approval claimed full success: {phrase!r}"


def _contains_forbidden_phrase(lowered_text: str, lowered_phrase: str) -> bool:
    if not lowered_phrase:
        return False
    start = 0
    while True:
        idx = lowered_text.find(lowered_phrase, start)
        if idx < 0:
            return False
        prefix = lowered_text[max(0, idx - 4) : idx]
        if not prefix.endswith("of "):
            return True
        start = idx + len(lowered_phrase)


def _assert_committed_jobs_match_oracle(evidence: Phase4Evidence, oracle: dict[str, Any]) -> None:
    expected = oracle["expected_final_state"]
    assert evidence.session_phase == expected["session_phase"]
    assert evidence.pending_approval_id == expected.get("pending_approval_id")
    for row in expected.get("jobs") or []:
        job_id = str(row.get("id") or row.get("job_id"))
        assert job_id in evidence.committed_jobs, f"Missing committed job {job_id!r}"
        for key, value in row.items():
            if key in {"id", "job_id"}:
                continue
            assert evidence.committed_jobs[job_id].get(key) == value


def assert_phase4_oracle_contract(evidence: Phase4Evidence, oracle: dict[str, Any]) -> None:
    _assert_expected_timeline_chain(evidence, oracle)
    _assert_timeline_and_sse_match_graph_actions(evidence)
    _assert_approval_ids_are_real_and_distinct(evidence, oracle)
    _assert_commits_match_approval_and_audit(evidence)
    _assert_no_final_before_required_terminal_evidence(evidence, oracle)
    _assert_committed_jobs_match_oracle(evidence, oracle)
    _assert_final_response_matches_oracle(evidence, oracle)


ALL_STATEFUL_ORACLE_IDS = [
    "SO-001",
    "SO-002",
    "SO-003",
    "SO-004",
    "SO-005",
    "SO-006",
    "SO-007",
    "SO-008",
    "SO-009",
    "SO-010",
    "SO-011",
    "SO-012",
    "SO-013",
    "SO-014",
    "SO-015",
    "SO-016",
    "SO-017",
    "SO-018",
    "SO-019",
    "SO-020",
    "SO-021",
    "SO-022",
    "SO-023",
    "SO-025",
    "SO-026",
    "SO-027",
    "SO-028",
    "SO-029",
    "SO-030",
    "SO-031",
    "SO-035",
    "SO-041",
]


def _status_from_decision(decision: str) -> str:
    if decision.startswith("accepted"):
        return "accepted"
    if decision in {"rejected", "expired", "superseded"}:
        return decision
    return decision or "pending"


def _timeline_from_oracle(oracle: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, expected in enumerate(oracle.get("expected_timeline") or [], start=1):
        row = {
            "sequence_number": expected.get("sequence", index),
            "sequence": expected.get("sequence", index),
            "session_id": oracle["id"].lower(),
            **deepcopy(expected),
        }
        rows.append(row)
    return rows


def _sse_from_timeline(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frames = []
    for index, row in enumerate(timeline, start=1):
        frames.append(
            {
                "id": str(row.get("event_id") or row.get("sequence") or index),
                "event": row.get("event"),
                "data": deepcopy(row),
            }
        )
    return frames


def _approvals_from_oracle(oracle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    approvals = {}
    for row in oracle.get("expected_approvals") or []:
        approval_id = str(row.get("approval_id") or "")
        if not approval_id:
            continue
        approvals[approval_id] = {
            "approval_id": approval_id,
            "intent_id": row.get("intent_id"),
            "status": _status_from_decision(str(row.get("decision") or "accepted")),
            "row_ids": list(row.get("row_ids") or []),
        }
    return approvals


def _committed_jobs_from_oracle(oracle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = {}
    for row in (oracle.get("expected_final_state") or {}).get("jobs") or []:
        job_id = str(row.get("id") or row.get("job_id"))
        jobs[job_id] = deepcopy({**row, "id": job_id, "job_id": job_id})
    return jobs


def _final_response_from_oracle(oracle: dict[str, Any]) -> str:
    expected = oracle.get("expected_final_response") or {}
    parts = [str(item) for item in expected.get("must_include") or []]
    if oracle.get("expected_intents"):
        parts.extend(str(row["approval_id"]) for row in oracle.get("expected_approvals") or [] if row.get("approval_id"))
    return "Final summary: " + "; ".join(parts) + "."


def _evidence_from_oracle_contract(oracle: dict[str, Any]) -> Phase4Evidence:
    timeline = _timeline_from_oracle(oracle)
    return Phase4Evidence(
        graph_actions=deepcopy(timeline),
        timeline_events=deepcopy(timeline),
        sse_events=_sse_from_timeline(timeline),
        approvals=_approvals_from_oracle(oracle),
        audit_rows=deepcopy(oracle.get("expected_audit_rows") or []),
        committed_jobs=_committed_jobs_from_oracle(oracle),
        session_phase=(oracle.get("expected_final_state") or {}).get("session_phase"),
        pending_approval_id=(oracle.get("expected_final_state") or {}).get("pending_approval_id"),
        final_response=_final_response_from_oracle(oracle),
    )


@pytest.mark.parametrize("oracle_id", ALL_STATEFUL_ORACLE_IDS)
def test_all_stateful_oracle_files_have_executable_snapshot_final_response_contract(oracle_id):
    oracle = load_oracle(oracle_id)
    evidence = _evidence_from_oracle_contract(oracle)

    assert_phase4_oracle_contract(evidence, oracle)


def _success_response_from_audit(harness: StatefulOracleHarness) -> str:
    parts: list[str] = []
    for expected in harness.oracle.get("expected_audit_rows") or []:
        approval_id = str(expected["approval_id"])
        row_ids = expected.get("row_ids") or []
        from_priority = str(expected.get("from") or "")
        to_priority = str(expected.get("to") or "")
        intent = next(
            (
                item
                for item in harness.oracle.get("expected_intents") or []
                if item.get("intent_id")
                == next(
                    (
                        approval.get("intent_id")
                        for approval in harness.oracle.get("expected_approvals") or []
                        if approval.get("approval_id") == approval_id
                    ),
                    None,
                )
            ),
            {},
        )
        original = isinstance(intent.get("filter"), dict) and intent["filter"].get("state_basis") == "original"
        original_text = "original " if original else ""
        job_word = "job" if len(row_ids) == 1 else "jobs"
        parts.append(
            f"{len(row_ids)} {original_text}{from_priority} priority {job_word} changed to {to_priority} "
            f"(approval {approval_id})"
        )
    return "Final summary: " + "; ".join(parts) + "."


def _partial_failure_response(harness: StatefulOracleHarness) -> str:
    approval = harness.oracle["expected_approvals"][0]
    result = approval["expected_commit_result"]
    failed_ids = result["failed_row_ids"]
    succeeded_count = len(result["succeeded_row_ids"])
    total_count = succeeded_count + len(failed_ids)
    return (
        f"Completed with errors: {succeeded_count} of {total_count} low priority jobs changed to high; "
        f"{', '.join(failed_ids)} failed with version_conflict. "
        f"Approval id: {approval['approval_id']}."
    )


def _reject_approval(harness: StatefulOracleHarness, approval_id: str) -> None:
    approval = harness.approvals[approval_id]
    approval["status"] = "rejected"
    harness.pending_approval_id = None
    harness.session_phase = "CANCELLED"
    harness.record_event("approval_decided", approval_id=approval_id, decision="rejected")
    harness.record_event("operation_cancelled", reason="approval_rejected")


def _rejection_response() -> str:
    return (
        "First change was committed under approval approval-so-005-1; "
        "second approval was rejected for approval-so-005-2. "
        "No original high priority jobs were changed to low."
    )


def _run_so001_hard_regression() -> StatefulOracleHarness:
    harness = StatefulOracleHarness.from_oracle_id("SO-001")
    assert KNOWN_HARD_REGRESSION_PROMPT == (
        "change all medium priority job to high then change all high priority job to medium"
    )
    harness.start_operation(intent_count=2)
    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-001-1", auto_complete=False).ok is True
    harness.dry_run_oracle_intent(1)
    assert harness.approve("approval-so-001-2").ok is True
    return harness


def _run_so041_aggregate_final_response_regression() -> StatefulOracleHarness:
    harness = StatefulOracleHarness.from_oracle_id("SO-041")
    harness.start_operation(intent_count=2)
    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-041-1", auto_complete=False).ok is True
    harness.dry_run_oracle_intent(1)
    assert harness.approve("approval-so-041-2").ok is True
    return harness


def test_so001_hard_regression_final_response_timeline_sse_audit_and_state_agree():
    harness = _run_so001_hard_regression()

    assert_final_state_matches_oracle(harness, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])
    evidence = _evidence_from_harness(harness, final_response=_success_response_from_audit(harness))

    assert_phase4_oracle_contract(evidence, harness.oracle)
    assert "2 original high priority jobs changed to medium" in evidence.final_response
    assert harness.approvals["approval-so-001-2"]["row_ids"] == [
        "JOB-SO001-HIGH-01",
        "JOB-SO001-HIGH-02",
    ]
    assert [row["event"] for row in evidence.timeline_events].index("final_response_created") > [
        (row["event"], row.get("approval_id")) for row in evidence.timeline_events
    ].index(("commit_completed", "approval-so-001-2"))


def test_so041_final_response_must_summarize_all_committed_write_sets():
    harness = _run_so041_aggregate_final_response_regression()

    assert_final_state_matches_oracle(harness, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])

    good = _evidence_from_harness(harness, final_response=_success_response_from_audit(harness))
    assert_phase4_oracle_contract(good, harness.oracle)
    assert "2 medium priority jobs changed to high" in good.final_response
    assert "2 original high priority jobs changed to low" in good.final_response

    last_write_only = _evidence_from_harness(
        harness,
        final_response=(
            "Success. Updated 2 job(s). "
            "2 original high priority jobs changed to low under approval approval-so-041-2."
        ),
    )
    with pytest.raises(AssertionError, match="missing required phrase|must cite the actual approvals"):
        assert_phase4_oracle_contract(last_write_only, harness.oracle)


def test_so011_does_not_emit_final_completion_after_only_approval_one():
    harness = StatefulOracleHarness.from_oracle_id("SO-011")
    harness.start_operation(intent_count=2)
    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-011-1", auto_complete=False).ok is True

    intermediate = _evidence_from_harness(harness, final_response="approval-so-011-1 applied; next step is still pending.")
    assert_no_timeline_event(harness, "final_response_created")
    assert intermediate.session_phase == "EXECUTING"
    assert intermediate.pending_approval_id is None

    harness.record_event("next_intent_started", intent_id="SO-011-I2")
    harness.dry_run_oracle_intent(1)
    waiting = _evidence_from_harness(harness, final_response="Waiting for approval approval-so-011-2.")
    assert_no_timeline_event(harness, "final_response_created")
    assert waiting.session_phase == "WAITING_APPROVAL"
    assert waiting.pending_approval_id == "approval-so-011-2"

    assert harness.approve("approval-so-011-2").ok is True
    terminal = _evidence_from_harness(harness, final_response=_success_response_from_audit(harness))
    assert_phase4_oracle_contract(terminal, harness.oracle)


def test_rejected_second_approval_does_not_produce_success_wording_or_hidden_commit():
    harness = StatefulOracleHarness.from_oracle_id("SO-005")
    harness.start_operation(intent_count=2)
    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-005-1", auto_complete=False).ok is True
    harness.dry_run_oracle_intent(1)
    _reject_approval(harness, "approval-so-005-2")

    evidence = _evidence_from_harness(harness, final_response=_rejection_response())

    assert_phase4_oracle_contract(evidence, harness.oracle)
    assert all(row.get("approval_id") != "approval-so-005-2" for row in evidence.audit_rows)
    assert_no_timeline_event(harness, "commit_completed", approval_id="approval-so-005-2")


def test_partial_failure_is_reported_as_partial_failure_not_full_success():
    harness = StatefulOracleHarness.from_oracle_id("SO-009")
    harness.start_operation()
    harness.dry_run_oracle_intent(0)
    assert harness.approve("approval-so-009-1").status == "partial_failure"

    evidence = _evidence_from_harness(harness, final_response=_partial_failure_response(harness))

    assert_phase4_oracle_contract(evidence, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])
    assert not _contains_forbidden_phrase(
        evidence.final_response.lower(),
        "3 low priority jobs changed to high",
    )
    assert "JOB-SO009-LOW-02 failed" in evidence.final_response


def test_oracle_validity_empty_or_missing_timeline_fails_contract():
    harness = _run_so001_hard_regression()
    evidence = _evidence_from_harness(harness, final_response=_success_response_from_audit(harness))

    with pytest.raises(AssertionError, match="Timeline evidence is required"):
        assert_phase4_oracle_contract(replace(evidence, timeline_events=[]), harness.oracle)

    missing_approval_2 = [
        row
        for row in evidence.timeline_events
        if row.get("approval_id") != "approval-so-001-2"
    ]
    with pytest.raises(AssertionError, match="Missing expected timeline event"):
        assert_phase4_oracle_contract(replace(evidence, timeline_events=missing_approval_2), harness.oracle)


def test_oracle_validity_premature_final_duplicate_sse_and_stale_approval_ids_fail():
    harness = _run_so001_hard_regression()
    evidence = _evidence_from_harness(harness, final_response=_success_response_from_audit(harness))

    premature = deepcopy(evidence.timeline_events)
    final = next(row for row in premature if row.get("event") == "final_response_created")
    premature.remove(final)
    insert_at = next(
        idx
        for idx, row in enumerate(premature)
        if row.get("event") == "commit_completed" and row.get("approval_id") == "approval-so-001-1"
    ) + 1
    premature.insert(insert_at, final)
    with pytest.raises(AssertionError, match="Missing expected timeline event|Projected timeline"):
        assert_phase4_oracle_contract(replace(evidence, timeline_events=premature), harness.oracle)

    duplicate_sse = deepcopy(evidence.sse_events)
    duplicate_sse.insert(3, deepcopy(duplicate_sse[2]))
    with pytest.raises(AssertionError, match="SSE ids must not duplicate"):
        assert_phase4_oracle_contract(replace(evidence, sse_events=duplicate_sse), harness.oracle)

    stale_final = evidence.final_response + " Stale approval approval-so-001-old also approved."
    with pytest.raises(AssertionError, match="stale approval ids"):
        assert_phase4_oracle_contract(replace(evidence, final_response=stale_final), harness.oracle)

    duplicate_timeline_id = [
        {
            **row,
            **(
                {"approval_id": "approval-so-001-1"}
                if row.get("event") == "approval_requested"
                and row.get("approval_id") == "approval-so-001-2"
                else {}
            ),
        }
        for row in deepcopy(evidence.timeline_events)
    ]
    duplicate_sse_id = [
        {"id": str(index + 1), "event": row.get("event"), "data": deepcopy(row)}
        for index, row in enumerate(duplicate_timeline_id)
    ]
    with pytest.raises(AssertionError, match="must match expected approvals exactly|Missing expected timeline event"):
        assert_phase4_oracle_contract(
            replace(
                evidence,
                graph_actions=duplicate_timeline_id,
                timeline_events=duplicate_timeline_id,
                sse_events=duplicate_sse_id,
            ),
            harness.oracle,
        )


def test_oracle_validity_false_success_after_rejection_or_partial_failure_fails():
    rejected = StatefulOracleHarness.from_oracle_id("SO-005")
    rejected.start_operation(intent_count=2)
    rejected.dry_run_oracle_intent(0)
    assert rejected.approve("approval-so-005-1", auto_complete=False).ok is True
    rejected.dry_run_oracle_intent(1)
    _reject_approval(rejected, "approval-so-005-2")
    rejected_evidence = _evidence_from_harness(
        rejected,
        final_response=(
            "All requested changes completed. approval-so-005-1 and approval-so-005-2 "
            "changed all requested jobs successfully."
        ),
    )
    with pytest.raises(AssertionError, match="required phrase|forbidden phrase"):
        assert_phase4_oracle_contract(rejected_evidence, rejected.oracle)

    partial = StatefulOracleHarness.from_oracle_id("SO-009")
    partial.start_operation()
    partial.dry_run_oracle_intent(0)
    assert partial.approve("approval-so-009-1").status == "partial_failure"
    partial_evidence = _evidence_from_harness(
        partial,
        final_response="3 low priority jobs changed to high. Approval id: approval-so-009-1.",
    )
    with pytest.raises(AssertionError, match="required phrase"):
        assert_phase4_oracle_contract(partial_evidence, partial.oracle)
