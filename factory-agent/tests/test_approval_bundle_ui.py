from __future__ import annotations

from factory_agent.graph.approval_summary import (
    build_approval_required_payload,
    build_job_priority_bundle_uiview,
)


def test_build_job_priority_bundle_uiview_bulk_medium_to_high() -> None:
    staged = [
        {"tool_name": "put__jobs_{id}", "args": {"id": "JOB-SEED-002", "priority": "high"}},
        {"tool_name": "put__jobs_{id}", "args": {"id": "JOB-SEED-004", "priority": "high"}},
    ]
    intent = "Update all medium priority jobs to high priority"
    ui = build_job_priority_bundle_uiview(staged, intent_text=intent)
    assert ui is not None
    assert ui["kind"] == "job_priority_bundle"
    assert ui["headline"] == "2 jobs will be updated from medium to high priority."
    assert len(ui["rows"]) == 2
    assert ui["rows"][0]["job_id"] == "JOB-SEED-002"
    assert ui["rows"][0]["previous_priority"] == "medium"
    assert ui["rows"][0]["new_priority"] == "high"


def test_build_approval_required_payload_includes_bundle_ui() -> None:
    staged = [
        {"tool_name": "put__jobs_{id}", "args": {"id": "JOB-A", "priority": "urgent"}},
    ]
    p = build_approval_required_payload(staged, intent_text="Change low priority jobs to urgent")
    assert p["kind"] == "approval_required"
    assert p["bundle_ui"]["headline"] == "1 job will be updated from low to urgent priority."


def test_non_job_writes_skip_bundle_ui() -> None:
    staged = [{"tool_name": "post__jobs", "args": {"machine_id": "M-1"}}]
    p = build_approval_required_payload(staged, intent_text="Create jobs")
    assert "bundle_ui" not in p
