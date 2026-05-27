from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
DEFAULT_OUTPUT = REPO_ROOT / "test-artifacts" / "planner-owned-requirement-expansion" / "browser-proof.json"


def _load_graph_helpers():
    sys.path.insert(0, str(ROOT))
    helper_path = ROOT / "tests" / "test_planner_owned_graph_execution_observation.py"
    spec = importlib.util.spec_from_file_location("requirement_expansion_graph_helpers", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load graph helper module from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _selected_tool_calls(decision: Any) -> list[Any]:
    calls = []
    if getattr(decision, "selected_tool_call", None) is not None:
        calls.append(decision.selected_tool_call)
    calls.extend(list(getattr(decision, "selected_tool_calls", []) or []))
    return calls


def _active_evidence(evidence: Any) -> bool:
    metadata = dict(getattr(evidence, "diagnostic_metadata", {}) or {})
    return (
        metadata.get("active_revision_satisfaction") is not False
        and metadata.get("stale_after_graph_revision") is not True
        and metadata.get("stale_after_graph_replan") is not True
        and metadata.get("stale_after_user_interrupt") is not True
    )


async def _build_proof() -> dict[str, Any]:
    helpers = _load_graph_helpers()
    executor = helpers.JobProductThenProductExecutor()
    selector = helpers.SequentialRecordingSelector(
        [
            ["get__jobs_{id}"],
            ["get__products_{id}"],
        ]
    )

    result = await helpers._graph(
        tools_by_name={
            "get__jobs_{id}": helpers._job_status_tool(),
            "get__products_{id}": helpers._product_status_tool(),
        },
        selector=selector,
        http_executor=executor,
    ).run(
        "Read job JOB-SEED-001. If the job result includes a product id, read that product. Summarize the result.",
        session_context={"session_id": "browser-requirement-expansion-proof"},
    )

    state = result.state
    requirements = state.requirement_ledger.requirements
    child_requirements = [requirement for requirement in requirements if requirement.parent_requirement_id]
    evidence = state.evidence_ledger.evidence
    evidence_by_requirement = {item.requirement_id: item for item in evidence}
    parent_requirement_ids = list(dict.fromkeys(child.parent_requirement_id for child in child_requirements))
    child_requirement_ids = [child.id for child in child_requirements]
    conditional_branches = list(state.requirement_ledger.conditional_branches)
    active_final_refs = list(state.response_document_context.diagnostics.get("active_final_evidence_refs") or [])
    response_refs = list(state.response_document_context.evidence_refs)
    child_choose = next(
        (
            decision
            for decision in state.planner_decisions
            if decision.decision_kind == "choose_tool"
            and decision.requirement_id in set(child_requirement_ids)
        ),
        None,
    )
    parent_choose_calls = [
        call
        for decision in state.planner_decisions
        if decision.decision_kind == "choose_tool" and decision.requirement_id in set(parent_requirement_ids)
        for call in _selected_tool_calls(decision)
    ]
    child_choose_calls = _selected_tool_calls(child_choose) if child_choose is not None else []
    parent_evidence = evidence_by_requirement.get(parent_requirement_ids[0]) if parent_requirement_ids else None
    stale_or_failed_final_refs = [
        item.id
        for item in evidence
        if not _active_evidence(item) and item.id in set(response_refs + active_final_refs)
    ]

    checks = {
        "conditional_branch_activated": len(conditional_branches) == 1
        and conditional_branches[0].status == "activated"
        and conditional_branches[0].activated_child_requirement_ids == child_requirement_ids,
        "conditional_branch_not_skipped_in_true_path": all(
            branch.status != "skipped" and branch.skipped_reason is None
            for branch in conditional_branches
        ),
        "child_requirement_lineage_present": bool(child_requirements),
        "child_created_from_parent_product_id": bool(parent_evidence)
        and bool(child_requirements)
        and child_requirements[0].constraints.get("product_id")
        == parent_evidence.normalized_result.get("fields", {}).get("product_id")
        and child_requirements[0].derived_from_evidence_refs == [parent_evidence.id],
        "child_used_fresh_retrieval": bool(child_requirement_ids)
        and set(child_requirement_ids).issubset({window.requirement_id for window in state.candidate_tool_windows})
        and set(child_requirement_ids).issubset({cards.requirement_id for cards in state.hydrated_tool_cards})
        and all(call.requirement_id in set(child_requirement_ids) for call in child_choose_calls)
        and all(call.candidate_window_id for call in child_choose_calls),
        "parent_tools_not_reused_for_child_executable_state": bool(child_choose_calls)
        and not set(call.call_id for call in parent_choose_calls).intersection(call.call_id for call in child_choose_calls)
        and not set(call.tool_name for call in parent_choose_calls).intersection(call.tool_name for call in child_choose_calls),
        "parent_and_child_evidence_active": all(_active_evidence(item) for item in evidence_by_requirement.values()),
        "final_answer_has_parent_and_child_evidence": all(
            evidence_by_requirement[requirement_id].id in set(response_refs)
            for requirement_id in [*parent_requirement_ids, *child_requirement_ids]
            if requirement_id in evidence_by_requirement
        ),
        "stale_or_failed_evidence_not_final": not stale_or_failed_final_refs,
    }

    proof = {
        "browser_validation": "planner_owned_requirement_expansion",
        "reproducible_by": "python factory-agent/scripts/generate_requirement_expansion_proof.py",
        "seeded_fixture_feasibility": {
            "feasible": True,
            "reason": "canonical seeded JOB-SEED-001 returns product_id P-001, so condition-true child expansion can run against seeded data",
        },
        "final_validation_status": state.final_validation_result.status if state.final_validation_result else None,
        "lineage": helpers.requirement_child_lineage(state.requirement_ledger)
        if hasattr(helpers, "requirement_child_lineage")
        else state.response_document_context.diagnostics.get("child_requirement_lineage", []),
        "active_final_evidence_refs": active_final_refs,
        "response_evidence_refs": response_refs,
        "requirements": [requirement.model_dump(mode="json") for requirement in requirements],
        "conditional_branches": [branch.model_dump(mode="json") for branch in conditional_branches],
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "candidate_window_requirement_ids": [window.requirement_id for window in state.candidate_tool_windows],
        "hydrated_card_requirement_ids": [cards.requirement_id for cards in state.hydrated_tool_cards],
        "planner_decisions": [decision.model_dump(mode="json") for decision in state.planner_decisions],
        "executor_tool_sequence": [call["tool_name"] for call in executor.calls],
        "selector_requirement_ids": [
            call["context"]["v2_tool_selector_adapter_request"]["requirement_id"]
            for call in selector.calls
        ],
        "child_choose_tool_call": child_choose_calls[0].model_dump(mode="json") if child_choose_calls else None,
        "requirement_expansion_diagnostics": state.execution_trace.diagnostics.get("requirement_expansion", {}),
        "conditional_branch_diagnostics": state.execution_trace.diagnostics.get("conditional_branches", []),
        "stale_or_failed_final_evidence_refs": stale_or_failed_final_refs,
        "checks": checks,
    }
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"requirement expansion proof checks failed: {failed}")
    return proof


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proof = asyncio.run(_build_proof())
    output_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
