from __future__ import annotations

from pathlib import Path

import pytest

from factory_agent.graph.v2_agent_graph import _PENDING_EXECUTION_DIAGNOSTIC_KEY
from factory_agent.planning.v2_agent_state import GraphToolCall
from factory_agent.planning.v2_graph_adapters import GraphToolExecutionResult
from tests.test_planner_owned_agent_graph_phase8_approval_resume import (
    PLAN_CREATION_SOURCE,
    RUNTIME_ADAPTER_SOURCE,
    _approval_decision,
    _graph,
)


GRAPH_SOURCE = Path("factory_agent/graph/v2_agent_graph.py")


@pytest.mark.asyncio
async def test_phase9_append_interruption_creates_new_ledger_revision():
    graph, _selector, _executor, _persister = _graph()
    session_context = {"session_id": "phase9-append", "status": "EXECUTING"}
    staged = await graph.run(
        "Set low priority jobs to high priority.",
        session_context=session_context,
    )

    interrupted = await graph.interrupt_with_user_message(
        session_context,
        "Also include medium priority jobs.",
    )

    revision_record = interrupted.state.requirement_ledger.revision_history[-1]
    pointer = session_context["replan_context"]["planner_owned_graph_interrupt"]

    assert interrupted.state.requirement_ledger.revision > staged.state.requirement_ledger.revision
    assert revision_record.change_type == "user_interrupt:append_requirement"
    assert revision_record.details["added_requirement_ids"]
    assert interrupted.state.pending_approval.status == "stale"
    assert pointer["ledger_revision"] == interrupted.state.requirement_ledger.revision
    assert pointer["session_replan_context_authoritative"] is False


@pytest.mark.asyncio
async def test_phase9_modify_interruption_revises_requirement_and_preserves_locked_constraints():
    graph, _selector, _executor, _persister = _graph()
    staged = await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase9-modify"},
    )
    original = staged.state.requirement_ledger.requirements[0]

    interrupted = await graph.interrupt_with_user_message(
        {
            "session_id": "phase9-modify",
            "status": "EXECUTING",
            "target_requirement_id": original.id,
        },
        "Actually only queued low priority jobs.",
    )

    superseded = next(req for req in interrupted.state.requirement_ledger.requirements if req.id == original.id)
    replacement = next(req for req in interrupted.state.requirement_ledger.requirements if req.id == superseded.superseded_by)

    assert interrupted.state.requirement_ledger.revision_history[-1].change_type == "user_interrupt:modify_requirement"
    assert superseded.status == "superseded"
    assert replacement.status == "open"
    assert set(original.locked_constraints).issubset(set(replacement.locked_constraints))
    for locked in original.locked_constraints:
        assert replacement.constraints.get(locked) == original.constraints.get(locked)


@pytest.mark.asyncio
async def test_phase9_replace_interruption_supersedes_old_active_requirements_and_evidence():
    graph, _selector, _executor, _persister = _graph()
    completed = await graph.run(
        "List low priority jobs.",
        session_context={"session_id": "phase9-replace"},
    )
    old_evidence_id = completed.state.evidence_ledger.evidence[0].id

    interrupted = await graph.interrupt_with_user_message(
        {"session_id": "phase9-replace", "status": "EXECUTING"},
        "Replace that with set medium priority jobs to low priority.",
    )

    old_requirement = next(req for req in interrupted.state.requirement_ledger.requirements if req.id == "req-001")
    old_evidence = next(evidence for evidence in interrupted.state.evidence_ledger.evidence if evidence.id == old_evidence_id)
    active_evidence_refs = interrupted.state.response_document_context.evidence_refs

    assert interrupted.state.requirement_ledger.revision_history[-1].change_type == "user_interrupt:replace_goal"
    assert old_requirement.status == "superseded"
    assert old_evidence.diagnostic_metadata["stale_after_graph_revision"] is True
    assert old_evidence.diagnostic_metadata["active_revision_satisfaction"] is False
    assert old_evidence_id not in active_evidence_refs


@pytest.mark.asyncio
async def test_phase9_cancel_interruption_closes_active_graph_safely():
    graph, _selector, _executor, _persister = _graph()
    await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase9-cancel"},
    )

    interrupted = await graph.interrupt_with_user_message(
        {"session_id": "phase9-cancel", "status": "EXECUTING"},
        "Cancel the current run.",
    )

    active_requirements = [
        req for req in interrupted.state.requirement_ledger.requirements if req.status != "superseded"
    ]
    cancellation_evidence = [
        evidence
        for evidence in interrupted.state.evidence_ledger.evidence
        if evidence.normalized_result.get("reason") == "user_cancelled_current_run"
    ]

    assert interrupted.state.pending_approval.status == "none"
    assert active_requirements
    assert all(req.status == "impossible" for req in active_requirements)
    assert cancellation_evidence
    assert interrupted.state.final_validation_result.status == "passed"  # type: ignore[union-attr]
    assert interrupted.state.execution_trace.diagnostics["phase9_cancel_interrupt"]["status"] == "closed"


@pytest.mark.asyncio
async def test_phase9_stale_approval_cannot_commit_after_interruption():
    graph, _selector, executor, _persister = _graph()
    staged = await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase9-stale-approval"},
    )
    stale_approval = _approval_decision(staged)

    await graph.interrupt_with_user_message(
        {"session_id": "phase9-stale-approval", "status": "EXECUTING"},
        "Also include medium priority jobs.",
    )
    resumed = await graph.resume_from_approval(
        {"session_id": "phase9-stale-approval"},
        stale_approval,
    )

    stale_evidence = next(evidence for evidence in resumed.state.evidence_ledger.evidence if evidence.source_type == "approval")

    assert executor.calls == []
    assert stale_evidence.normalized_result["approval_status"] == "stale"
    assert stale_evidence.normalized_result["committed"] is False
    assert resumed.state.pending_approval.status == "stale"


@pytest.mark.asyncio
async def test_phase9_stale_background_result_is_ignored_by_revision_and_checkpoint():
    graph, _selector, _executor, _persister = _graph()
    staged = await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase9-stale-background"},
    )
    interrupted = await graph.interrupt_with_user_message(
        {"session_id": "phase9-stale-background", "status": "EXECUTING"},
        "Also include medium priority jobs.",
    )
    state = interrupted.state.model_copy(deep=True)
    requirement = next(req for req in state.requirement_ledger.requirements if req.status == "open")
    stale_execution = GraphToolExecutionResult(
        tool_call=GraphToolCall(
            call_id="call-stale-background",
            kind="api_tool",
            tool_name="get__jobs",
            args={"priority": "low"},
            requirement_id=requirement.id,
        ),
        source_type="api_tool",
        source_of_truth="operational_state",
        ok=True,
        result_ref="old-background-result",
        normalized_result={"rows": [{"job_id": "OLD", "priority": "low"}]},
        satisfies=["operational_state_tool_result"],
        diagnostic_metadata={
            "ledger_revision": staged.state.requirement_ledger.revision,
            "checkpoint_id": staged.state.pending_approval.checkpoint_id,
        },
    )
    state.execution_trace.diagnostics[_PENDING_EXECUTION_DIAGNOSTIC_KEY] = {
        "status": "observed_by_next_node",
        "execution_results": [stale_execution.model_dump(mode="json")],
    }
    evidence_count = len(state.evidence_ledger.evidence)

    await graph._evidence_observation_node(state)

    assert len(state.evidence_ledger.evidence) == evidence_count
    ignored = state.execution_trace.diagnostics["stale_background_results_ignored"][0]
    assert ignored["reason"] in {"ledger_revision_mismatch", "checkpoint_id_mismatch"}
    assert state.execution_trace.diagnostics["evidence_observation"]["stale_background_results_ignored"] is True


@pytest.mark.asyncio
async def test_phase9_carried_forward_evidence_must_be_explicit():
    graph, _selector, _executor, _persister = _graph()
    completed = await graph.run(
        "List low priority jobs.",
        session_context={"session_id": "phase9-carry-forward"},
    )
    evidence_id = completed.state.evidence_ledger.evidence[0].id

    implicit = await graph.interrupt_with_user_message(
        {"session_id": "phase9-carry-forward", "status": "EXECUTING"},
        "Also include medium priority jobs.",
    )

    assert evidence_id not in implicit.state.response_document_context.evidence_refs
    assert implicit.state.evidence_ledger.evidence[0].diagnostic_metadata["active_revision_satisfaction"] is False

    graph2, _selector2, _executor2, _persister2 = _graph()
    completed2 = await graph2.run(
        "List low priority jobs.",
        session_context={"session_id": "phase9-carry-forward-explicit"},
    )
    evidence_id2 = completed2.state.evidence_ledger.evidence[0].id
    explicit = await graph2.interrupt_with_user_message(
        {"session_id": "phase9-carry-forward-explicit", "status": "EXECUTING"},
        "Also include medium priority jobs.",
        options={"configurable": {"carry_forward_evidence_refs": [evidence_id2]}},
    )

    carried = next(evidence for evidence in explicit.state.evidence_ledger.evidence if evidence.id == evidence_id2)
    assert evidence_id2 in explicit.state.response_document_context.evidence_refs
    assert carried.diagnostic_metadata["carried_forward_explicit"] is True
    assert carried.diagnostic_metadata["carried_forward_to_ledger_revision"] == explicit.state.requirement_ledger.revision


@pytest.mark.asyncio
async def test_phase9_new_revision_produces_new_trace_and_revision_metadata():
    graph, _selector, _executor, _persister = _graph()
    staged = await graph.run(
        "Set low priority jobs to high priority.",
        session_context={"session_id": "phase9-trace"},
    )

    interrupted = await graph.interrupt_with_user_message(
        {"session_id": "phase9-trace", "status": "EXECUTING"},
        "Also include medium priority jobs.",
    )

    trace = interrupted.state.execution_trace.diagnostics["phase9_interruption_revision"]
    metadata = interrupted.state.execution_trace.diagnostics["graph_revision_metadata"][-1]

    assert trace["native_langgraph_checkpoint_used"] is True
    assert trace["session_replan_context_authoritative"] is False
    assert trace["previous_ledger_revision"] == staged.state.requirement_ledger.revision
    assert trace["new_ledger_revision"] == interrupted.state.requirement_ledger.revision
    assert trace["new_checkpoint_identity"]["ledger_revision"] == interrupted.state.requirement_ledger.revision
    assert metadata["interrupt"]["interrupt_type"] == "append_requirement"


def test_phase9_normal_runtime_switches_to_graph_after_phase10():
    source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    runtime_source = RUNTIME_ADAPTER_SOURCE.read_text(encoding="utf-8")

    assert "PlannerOwnedGraphRuntimeAdapter" in source
    assert "PlannerOwnedAgentGraph" in runtime_source
    assert '"thread_id": sess.session_id' in runtime_source
    assert "_create_historical_direct_v2_plan" not in source
