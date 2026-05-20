from __future__ import annotations

import ast
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from factory_agent.config import get_settings
from factory_agent.planner import PlannerApprovalRequired
from factory_agent.testing_seeded_adapters import SeededPlaywrightPlanner
from factory_agent.testing_seeded_scenarios import APPROVAL_REQUIRED_WORKFLOW
from factory_agent.testing_seeded_scenarios import EXPIRED_OR_STALE_APPROVAL
from factory_agent.testing_seeded_scenarios import LARGE_STRUCTURED_RESULT
from factory_agent.testing_seeded_scenarios import MIGRATED_SEEDED_SCENARIOS
from factory_agent.testing_seeded_scenarios import PARTIAL_FAILURE
from factory_agent.testing_seeded_scenarios import READ_ONLY_TOOL_RESULT
from factory_agent.testing_seeded_scenarios import REJECTED_APPROVAL
from factory_agent.testing_seeded_scenarios import SSE_FAULT_MARKER
from factory_agent.testing_seeded_scenarios import SUPPORTED_SCENARIO_CAPABILITIES
from factory_agent.testing_seeded_scenarios import TWO_STEP_APPROVAL_CHAIN
from factory_agent.schemas import ToolInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = REPO_ROOT / "factory-agent" / "factory_agent" / "testing_seeded_adapters.py"


def _settings():
    return replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        go_api_base_url="http://seeded-go.invalid",
    )


def _seed_job_rows() -> list[dict[str, Any]]:
    return [
        {"job_id": "JOB-SEED-HIGH-001", "priority": "high"},
        {"job_id": "JOB-SEED-HIGH-002", "priority": "high"},
        {"job_id": "JOB-SEED-MED-001", "priority": "medium"},
        {"job_id": "JOB-SEED-LOW-001", "priority": "low"},
    ]


def _phase_literals_in_if_tests(source: str) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        for child in ast.walk(node.test):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                value = child.value.lower()
                if re.search(r"\bphase\s+\d+\b", value):
                    found.add(value)
    return found


def test_seeded_scenario_schema_represents_phase5_capabilities():
    required = {
        READ_ONLY_TOOL_RESULT,
        APPROVAL_REQUIRED_WORKFLOW,
        TWO_STEP_APPROVAL_CHAIN,
        REJECTED_APPROVAL,
        EXPIRED_OR_STALE_APPROVAL,
        PARTIAL_FAILURE,
        LARGE_STRUCTURED_RESULT,
        SSE_FAULT_MARKER,
    }
    assert required <= SUPPORTED_SCENARIO_CAPABILITIES

    migrated = {capability for scenario in MIGRATED_SEEDED_SCENARIOS for capability in scenario.capabilities}
    assert {READ_ONLY_TOOL_RESULT, LARGE_STRUCTURED_RESULT} <= migrated
    assert {APPROVAL_REQUIRED_WORKFLOW, TWO_STEP_APPROVAL_CHAIN, REJECTED_APPROVAL} <= migrated


def test_seeded_planner_declares_phase_prompts_it_handles_from_catalog():
    planner = SeededPlaywrightPlanner(_settings())

    assert planner.handles_seeded_intent("Run Phase 14 stale approval seeded job update")
    assert planner.handles_seeded_intent("Run Phase 14 idempotent approval replay for one seeded job priority update")
    assert planner.handles_seeded_intent("List jobs for Phase 9 large structured result")
    assert planner.handles_seeded_intent("Start a seeded cancel jobs run and keep it executing")
    assert planner.handles_seeded_intent("Run seeded SSE activity stream for machine M-CNC-01")
    assert not planner.handles_seeded_intent("cancel the current run")
    assert not planner.handles_seeded_intent("Please update a job priority without a job id")


@pytest.mark.parametrize(
    ("prompt", "scenario_id"),
    [
        ("Run Phase 9 multi-step ordered seeded jobs workflow", "phase9_multi_step_ordered"),
        ("Run Phase 9 multi approval chain for seeded job priority update", "phase9_multi_approval_chain"),
        ("Run Phase 9 approval timeout seeded job update", "phase9_approval_timeout"),
        ("Run Phase 9 partial failure seeded jobs workflow", "phase9_partial_failure"),
        ("Run Phase 9 schema mismatch seeded machine workflow", "phase9_schema_mismatch"),
        ("Run Phase 9 duplicate submit seeded machine job", "phase9_duplicate_submit"),
        ("Run Phase 9 out-of-order duplicate SSE seeded jobs workflow", "phase9_out_of_order_duplicate_sse"),
        ("Run Phase 9 Last-Event-ID reconnect seeded machine workflow", "phase9_last_event_id_reconnect"),
        ("Run Phase 9 stream drop recovery seeded machine workflow", "phase9_stream_drop_recovery"),
        ("Run Phase 10 refresh during active job seeded machine workflow", "phase10_refresh_recovery"),
        ("Run Phase 10 long-running stream seeded machine workflow", "phase10_long_running_stream"),
        ("Run Phase 14 bulk partial failure priority update with exact row outcomes", "phase14_bulk_partial_failure"),
        (
            "Run Phase 14 idempotent approval replay for one seeded job priority update",
            "phase14_idempotent_approval_replay",
        ),
        (
            "Run Phase 14 refresh during active approval for original high jobs to medium",
            "phase14_refresh_active_approval",
        ),
        ("Run Phase 14 stream drop commit recovery for original high jobs", "phase14_stream_drop_commit"),
        ("Run Phase 14 Go API 500 commit failure for seeded job", "phase14_go_api_500"),
        ("Run Phase 14 stale approval seeded job update", "phase14_stale_approval"),
        ("Run Phase 14 expired approval seeded job update", "phase14_expired_approval"),
        ("Run Phase 14 agreement audit timeline summary for seeded job priority updates", "phase14_agreement"),
        ("Run Phase 9 isolation alpha seeded machine workflow", "phase9_isolation_alpha"),
        ("Run Phase 9 isolation beta seeded machine workflow", "phase9_isolation_beta"),
    ],
)
def test_phase_prompt_scenarios_are_catalogued(prompt, scenario_id):
    planner = SeededPlaywrightPlanner(_settings())

    matched = planner._scenario_interpreter.match(prompt)

    assert matched is not None
    assert matched.scenario_id == scenario_id


@pytest.mark.asyncio
async def test_large_structured_result_is_driven_by_scenario_data():
    planner = SeededPlaywrightPlanner(_settings())

    result = await planner.generate_plan(
        intent="List jobs for Phase 9 large structured result",
        scoped_tools=[],
        context={"session_id": "scenario-large"},
    )

    assert planner._scenario_by_session["scenario-large"] == "large_structured_result"
    assert result.llm_calls == 0
    assert result.tool_outputs
    output = result.tool_outputs[0]
    assert output["tool_name"] == "get__jobs"
    assert output["summary"] == "Phase 9 large structured result rendered 80 seeded rows without losing completion state."
    assert output["result"]["total"] == 80
    assert len(output["result"]["data"]) == 80


@pytest.mark.asyncio
async def test_draft_then_call_machine_status_uses_fixture_runtime_intent(monkeypatch):
    planner = SeededPlaywrightPlanner(_settings())
    tool = ToolInfo(
        name="get__machines_{id}",
        description="Get machine by ID",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
        path_params=["id"],
        param_sources={"id": "path"},
        is_read_only=True,
        capability_tags=["machine", "lookup"],
    )
    calls: list[str] = []

    async def fake_get_json(path: str, params: dict[str, Any] | None = None):
        calls.append(path)
        return {"data": {"machine_id": "M-CNC-01", "machine_name": "CNC Mill 01", "status": "RUNNING"}}

    monkeypatch.setattr(planner, "_get_json", fake_get_json)

    first = await planner.generate_plan(
        intent="Run Phase 9 Last-Event-ID reconnect seeded machine workflow",
        scoped_tools=[tool],
        context={"session_id": "scenario-last-event-id"},
    )
    second = await planner.generate_plan(
        intent="Run Phase 9 Last-Event-ID reconnect seeded machine workflow",
        scoped_tools=[tool],
        context={"session_id": "scenario-last-event-id"},
    )

    assert first.draft.steps[0].args == {"id": "M-CNC-01"}
    assert calls == ["/machines/M-CNC-01"]
    assert second.tool_outputs[0]["args"] == {"id": "M-CNC-01"}
    assert "Machine M-CNC-01" in second.draft.plan_explanation


@pytest.mark.asyncio
async def test_so005_cascade_approval_chain_is_driven_by_scenario_data(monkeypatch):
    planner = SeededPlaywrightPlanner(_settings())
    prompt = "change all medium priority job to high then change all high priority job to low"

    async def fake_seed_rows() -> list[dict[str, Any]]:
        return _seed_job_rows()

    apply_calls: list[dict[str, Any]] = []

    async def fake_apply_priority_updates(**kwargs: Any) -> list[dict[str, Any]]:
        apply_calls.append(kwargs)
        return [
            {
                "job_id": job_id,
                "original_priority": kwargs["original_priorities"].get(job_id),
                "requested_priority": kwargs["requested_priority"],
                "status": "succeeded",
            }
            for job_id in kwargs["job_ids"]
        ]

    def fail_legacy_cascade_parser(lowered: str) -> list[tuple[str, str]]:
        raise AssertionError(f"migrated SO-005 prompt should not hit legacy parser: {lowered}")

    monkeypatch.setattr(planner, "_seed_job_rows", fake_seed_rows)
    monkeypatch.setattr(planner, "_phase14_apply_priority_updates", fake_apply_priority_updates)
    monkeypatch.setattr(planner, "_phase14_cascade_priority_changes", fail_legacy_cascade_parser)

    with pytest.raises(PlannerApprovalRequired) as first:
        await planner.generate_plan(
            intent=prompt,
            scoped_tools=[],
            context={"session_id": "scenario-so005"},
        )

    first_approval = first.value.approval
    assert planner._scenario_by_session["scenario-so005"] == "phase14_cascade"
    assert first_approval["bundle_ui"]["write_set"] == "original_medium_to_high"
    assert [item["args"] for item in first_approval["preview"]] == [
        {"id": "JOB-SEED-MED-001", "priority": "high"}
    ]

    planner.seed_resume_context(
        session_id="scenario-so005",
        intent=prompt,
        approval_payload={
            "approval_id": "approval-so005-first",
            "bundle_ui": first_approval["bundle_ui"],
        },
    )

    with pytest.raises(PlannerApprovalRequired) as second:
        await planner.resume_after_approval(session_id="scenario-so005", approved=True)

    second_approval = second.value.approval
    assert apply_calls[0]["scenario"] == "86"
    assert apply_calls[0]["write_set"] == "original_medium_to_high"
    assert apply_calls[0]["approval_id"] == "approval-so005-first"
    assert second_approval["bundle_ui"]["write_set"] == "original_high_to_low"
    assert second_approval["bundle_ui"]["previous_approval_id"] == "approval-so005-first"
    assert [item["args"] for item in second_approval["preview"]] == [
        {"id": "JOB-SEED-HIGH-001", "priority": "low"},
        {"id": "JOB-SEED-HIGH-002", "priority": "low"},
    ]

    rejected = await planner.resume_after_approval(session_id="scenario-so005", approved=False)

    assert rejected.tool_outputs == []
    assert "rejected" in rejected.draft.plan_explanation.lower()
    assert len(apply_calls) == 1


@pytest.mark.asyncio
async def test_phase14_partial_failure_is_driven_by_scenario_data(monkeypatch):
    planner = SeededPlaywrightPlanner(_settings())

    async def fake_seed_rows() -> list[dict[str, Any]]:
        return _seed_job_rows()

    monkeypatch.setattr(planner, "_seed_job_rows", fake_seed_rows)

    with pytest.raises(PlannerApprovalRequired) as exc:
        await planner.generate_plan(
            intent="Run Phase 14 bulk partial failure priority update with exact row outcomes",
            scoped_tools=[],
            context={"session_id": "scenario-partial-failure"},
        )

    approval = exc.value.approval
    assert planner._scenario_by_session["scenario-partial-failure"] == "phase14_partial_failure"
    assert approval["bundle_ui"]["kind"] == "phase14_partial_failure"
    assert approval["bundle_ui"]["write_set"] == "bulk_partial_failure"


def test_testing_seeded_adapter_does_not_add_untracked_phase_prompt_branches():
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    found = _phase_literals_in_if_tests(source)

    assert found == set(), "Phase-prompt adapter branches belong in testing_seeded_scenarios.py data."
