from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import PlannerOwnedAgentGraph, PlannerOwnedAgentGraphAdapters
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_agent_state import GraphToolCall, PlannerDecisionRecord, PlannerOwnedAgentGraphState
from factory_agent.planning.v2_contracts import (
    CandidateTool,
    CandidateToolWindow,
    CapabilityNeed,
    EvidenceLedgerEntry,
    HydratedToolCard,
    HydratedToolCards,
    RequirementLedger,
    RequirementLedgerEntry,
    RequirementRevisionRecord,
    next_child_requirement_id,
)
from factory_agent.planning.v2_planner_decisions import (
    PlannerDecisionSubmission,
    PlannerDecisionValidationError,
    record_planner_decision,
    validate_planner_decision,
)
from factory_agent.planning.v2_planner_proposer import (
    OpenAICompatibleQwenPlannerDecisionProposer,
    PlannerDecisionProposalResult,
    PlannerDecisionProposalContext,
    PlannerDecisionProposerError,
    _build_planner_decision_prompt,
)
from factory_agent.schemas import ToolInfo


FACTORY_AGENT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_SOURCE = FACTORY_AGENT_ROOT / "factory_agent" / "graph" / "v2_agent_graph.py"


def _settings():
    return replace(
        get_settings(),
        graph_checkpoint_backend="off",
        tool_selector_backend="retrieval",
        tool_selector_top_k=5,
        tool_selector_candidate_pool=5,
        tool_selector_reranker_enabled=False,
    )


def _machine_status_tool(name: str = "get__machines_{id}") -> ToolInfo:
    return ToolInfo(
        name=name,
        description="Read machine status",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "x-ai-id-field": "machine_id", "x-ai-entity": "machine"},
                "fields": {"type": "string"},
            },
            "required": ["id"],
            "x-ai-entity": "machine",
            "x-ai-response-contracts": ["entity_status_v1"],
        },
        output_schema={
            "type": "object",
            "properties": {"machine_id": {"type": "string"}, "status": {"type": "string"}},
            "x-ai-entity": "machine",
            "x-ai-response-contracts": ["entity_status_v1"],
        },
        path_params=["id"],
        query_params=["fields"],
        param_sources={"id": "path", "fields": "query"},
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        capability_tags=["machine", "lookup", "status", "operational_state"],
    )


class RecordingSelector:
    def __init__(self, names: list[str] | None = None) -> None:
        self.names = names or ["get__machines_{id}"]

    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        return ToolSelectionResult(self.names, backend_used="retrieval", llm_calls=0)


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        settings,
        tool,
        args,
        *,
        idempotency_key: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"tool": tool.name, "args": dict(args), "idempotency_key": idempotency_key})
        return {
            "ok": True,
            "http_status": 200,
            "latency_ms": 1,
            "body": {"machine_id": args.get("id"), "status": "running"},
            "infrastructure_error": False,
        }


def _proposal(decision: PlannerDecisionRecord, *, adapter: str) -> PlannerDecisionProposalResult:
    proposer_diagnostics = {
        "proposer_seam": True,
        "adapter": adapter,
        "decision_id": decision.decision_id,
        "bounded_state_view": True,
        "full_openapi_catalog_visible": False,
    }
    decision = decision.model_copy(
        update={"diagnostics": {**decision.diagnostics, "planner_proposer": proposer_diagnostics}},
        deep=True,
    )
    return PlannerDecisionProposalResult(
        submission=PlannerDecisionSubmission(decision=decision),
        diagnostics=proposer_diagnostics,
    )


class ValidMockProposer:
    def __init__(self) -> None:
        self.contexts: list[Any] = []

    async def propose_decision(self, *, state, context):
        self.contexts.append(context)
        if context.requested_decision_kind == "retrieve_tools":
            return _proposal(
                PlannerDecisionRecord(
                    decision_id=context.decision_id,
                    decision_kind="retrieve_tools",
                    requirement_id=context.requirement_id,
                    ledger_revision=state.requirement_ledger.revision,
                    capability_need=context.capability_need,
                    reason="Mock planner requests bounded retrieval.",
                ),
                adapter="phase10_5_valid_mock_proposer",
            )
        selected = context.candidate_tool_calls[0]
        return _proposal(
            PlannerDecisionRecord(
                decision_id=context.decision_id,
                decision_kind="choose_tool",
                requirement_id=context.requirement_id,
                ledger_revision=state.requirement_ledger.revision,
                capability_need=context.capability_need,
                selected_tool_call=selected,
                reason="Mock planner selects from the hydrated window.",
            ),
            adapter="phase10_5_valid_mock_proposer",
        )


class FailingMockProposer:
    async def propose_decision(self, *, state, context):
        raise PlannerDecisionProposerError(
            "mock malformed JSON/schema from planner proposer",
            diagnostics={"invalid_json": True, "invalid_schema": True, "adapter": "phase10_5_failing_mock"},
        )


class OutsideWindowMockProposer(ValidMockProposer):
    async def propose_decision(self, *, state, context):
        if context.requested_decision_kind != "choose_tool":
            return await super().propose_decision(state=state, context=context)
        return _proposal(
            PlannerDecisionRecord(
                decision_id=context.decision_id,
                decision_kind="choose_tool",
                requirement_id=context.requirement_id,
                ledger_revision=state.requirement_ledger.revision,
                capability_need=context.capability_need,
                selected_tool_call=GraphToolCall(
                    call_id="call-outside-hydrated-window",
                    kind="api_tool",
                    tool_name="get__secret_full_catalog_tool",
                    args={},
                    requirement_id=context.requirement_id or "req-001",
                ),
                reason="Mock planner chose outside the hydrated candidate window.",
            ),
            adapter="phase10_5_outside_window_mock",
        )


class RevisingMockProposer:
    async def propose_decision(self, *, state, context):
        proposed = state.requirement_ledger.model_copy(deep=True)
        proposed.revision = state.requirement_ledger.revision + 1
        proposed.requirements[0].constraints["machine_id"] = "M-OTHER-77"
        return PlannerDecisionProposalResult(
            submission=PlannerDecisionSubmission(
                decision=PlannerDecisionRecord(
                    decision_id=context.decision_id,
                    decision_kind="revise_requirements",
                    requirement_id=context.requirement_id,
                    ledger_revision=state.requirement_ledger.revision,
                    reason="Mock planner tries to drop a locked machine id.",
                    diagnostics={
                        "planner_proposer": {
                            "proposer_seam": True,
                            "adapter": "phase10_5_revision_mock",
                            "bounded_state_view": True,
                            "full_openapi_catalog_visible": False,
                        }
                    },
                ),
                proposed_requirement_ledger=proposed,
            ),
            diagnostics={
                "proposer_seam": True,
                "adapter": "phase10_5_revision_mock",
                "bounded_state_view": True,
                "full_openapi_catalog_visible": False,
            },
        )


class EarlyFinalizeMockProposer:
    async def propose_decision(self, *, state, context):
        return _proposal(
            PlannerDecisionRecord(
                decision_id=context.decision_id,
                decision_kind="finalize",
                ledger_revision=state.requirement_ledger.revision,
                evidence_refs=[],
                reason="Mock planner tries to finalize before validation passes.",
            ),
            adapter="phase10_5_finalize_mock",
        )


class StaticPlannerModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.prompts: list[str] = []
        self.configs: list[dict[str, Any]] = []

    async def ainvoke(self, prompt: str, config: dict[str, Any] | None = None):
        self.prompts.append(prompt)
        if config is not None:
            self.configs.append(config)
        return self.content


def _child_expansion_state() -> PlannerOwnedAgentGraphState:
    state = PlannerOwnedAgentGraphState(
        original_query="Explain why machine M-LTH-77 is stopped.",
        requirement_ledger=RequirementLedger(
            user_goal="Explain why machine M-LTH-77 is stopped.",
            requirements=[
                RequirementLedgerEntry(
                    id="req-001",
                    goal="Read machine M-LTH-77 status",
                    requirement_type="single_entity_status",
                    entity="machine",
                    intent_operation="report_status",
                    source_of_truth="operational_state",
                    constraints={"machine_id": "M-LTH-77"},
                    requested_fields=["status"],
                    locked_constraints=["machine_id", "requested_fields"],
                )
            ],
        ),
    )
    state.evidence_ledger.evidence.append(
        EvidenceLedgerEntry(
            id="ev-api-machine",
            requirement_id="req-001",
            source_type="api_tool",
            source_of_truth="operational_state",
            tool_name="get__machines_{id}",
            normalized_result={
                "entity": "machine",
                "entity_id": "M-LTH-77",
                "fields": {
                    "machine_id": "M-LTH-77",
                    "status": "stopped",
                    "active_job_id": "JOB-CAUSE-17",
                },
            },
        )
    )
    state.execution_trace.diagnostics["satisfaction"] = {
        "missing_evidence_reasons": [
            {
                "requirement_id": "req-001",
                "status": "blocked",
                "reason": "needs_follow_up_entity",
                "retriable": True,
                "evidence_refs": ["ev-api-machine"],
            }
        ]
    }
    state.execution_trace.diagnostics["replan_spine"] = {
        "failed_tool_calls": [
            {
                "tool_name": "get__machines_{id}",
                "args": {"id": "M-LTH-77", "fields": "status"},
                "requirement_id": "req-001",
                "evidence_ref": "ev-api-machine",
                "reason": "tool_error",
                "attempt": 1,
            }
        ]
    }
    return state


@pytest.mark.asyncio
async def test_qwen_adapter_merges_parent_langsmith_config_into_model_call():
    state = _child_expansion_state()
    context = PlannerDecisionProposalContext(
        decision_id="dec-retrieve-parent-trace",
        requested_decision_kind="retrieve_tools",
        allowed_decision_kinds=["retrieve_tools", "fail"],
        requirement_id="req-001",
        capability_need=CapabilityNeed(
            source_of_truth="operational_state",
            entity="machine",
            action="read_one",
            constraints={"machine_id": "M-LTH-77"},
            requirement_id="req-001",
        ),
    )
    model = StaticPlannerModel(
        json.dumps(
            {
                "decision": {
                    "decision_kind": "retrieve_tools",
                    "reason": "Retrieve the machine status.",
                },
                "proposed_requirement_ledger": None,
            }
        )
    )
    proposer = OpenAICompatibleQwenPlannerDecisionProposer(_settings(), model=model)

    result = await proposer.propose_decision(
        state=state,
        context=context,
        parent_run_config={
            "configurable": {"thread_id": "trace-thread"},
            "tags": ["graph_segment:post_approval_resume", "logical_trace:trace-parent"],
            "metadata": {
                "logical_trace_id": "trace-parent",
                "graph_segment": "post_approval_resume",
                "approval_id": "approval-123",
            },
        },
    )

    assert model.configs
    config = model.configs[0]
    assert config["run_name"] == "planner_decision_proposer"
    assert config["configurable"]["thread_id"] == "trace-thread"
    assert "graph_segment:post_approval_resume" in config["tags"]
    assert "planner_decision" in config["tags"]
    assert config["metadata"]["logical_trace_id"] == "trace-parent"
    assert config["metadata"]["graph_segment"] == "post_approval_resume"
    assert config["metadata"]["approval_id"] == "approval-123"
    assert config["metadata"]["component"] == "planner_decision"
    assert config["metadata"]["raw_llm_output_executes_tools"] is False
    assert result.diagnostics["langsmith_parent_config_present"] is True


def _graph(proposer, executor: RecordingExecutor | None = None) -> tuple[PlannerOwnedAgentGraph, RecordingExecutor]:
    settings = _settings()
    executor = executor or RecordingExecutor()
    graph = PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name={"get__machines_{id}": _machine_status_tool()},
            tool_selector=RecordingSelector(),  # type: ignore[arg-type]
            http_executor=executor,
        ),
        proposer=proposer,
        checkpointer=None,
    )
    return graph, executor


@pytest.mark.asyncio
async def test_phase10_5_valid_mocked_proposer_submissions_retrieve_and_choose_tool():
    proposer = ValidMockProposer()
    graph, executor = _graph(proposer)

    result = await graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase10-5-valid"},
    )

    planner_decisions = [decision for decision in result.state.planner_decisions if decision.author == "planner"]
    assert [decision.decision_kind for decision in planner_decisions] == ["retrieve_tools", "choose_tool"]
    assert all(decision.diagnostics["planner_proposer"]["proposer_seam"] is True for decision in planner_decisions)
    assert all(
        decision.diagnostics["planner_proposer"]["full_openapi_catalog_visible"] is False
        for decision in planner_decisions
    )
    assert executor.calls and executor.calls[0]["tool"] == "get__machines_{id}"
    choose_context = next(context for context in proposer.contexts if context.requested_decision_kind == "choose_tool")
    assert [call.tool_name for call in choose_context.candidate_tool_calls] == ["get__machines_{id}"]


@pytest.mark.asyncio
async def test_phase10_5_malformed_json_or_schema_failure_closes_safely_without_tool_execution():
    executor = RecordingExecutor()
    graph, _executor = _graph(FailingMockProposer(), executor)

    result = await graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase10-5-malformed"},
    )

    rejected = result.state.execution_trace.planner.diagnostics["planner_decision_proposer"]["rejected"]
    assert rejected[0]["fail_closed"] is True
    assert rejected[0]["diagnostics"]["invalid_json"] is True
    assert executor.calls == []
    assert result.state.evidence_ledger.evidence == []


@pytest.mark.asyncio
async def test_phase10_5_tool_outside_hydrated_candidate_window_is_rejected():
    executor = RecordingExecutor()
    graph, _executor = _graph(OutsideWindowMockProposer(), executor)

    result = await graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase10-5-outside-window"},
    )

    rejected = result.state.execution_trace.planner.diagnostics["planner_decision_proposer"]["rejected"]
    assert any("selected tool is not in the hydrated candidate window" in item["reason"] for item in rejected)
    assert executor.calls == []
    assert result.state.evidence_ledger.evidence == []


@pytest.mark.asyncio
async def test_phase10_5_locked_constraint_drop_during_revise_requirements_is_rejected():
    graph, executor = _graph(RevisingMockProposer())

    result = await graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase10-5-revise-locked"},
    )

    rejected = result.state.execution_trace.planner.diagnostics["planner_decision_proposer"]["rejected"]
    assert "locked constraint value changed" in rejected[0]["reason"]
    assert executor.calls == []
    assert result.state.requirement_ledger.revision == 1


@pytest.mark.asyncio
async def test_phase10_5_finalize_before_validation_is_rejected():
    graph, executor = _graph(EarlyFinalizeMockProposer())

    result = await graph.run(
        "Show machine M-LTH-77 status.",
        session_context={"session_id": "phase10-5-early-finalize"},
    )

    rejected = result.state.execution_trace.planner.diagnostics["planner_decision_proposer"]["rejected"]
    assert "finalize decision requires passed final validation" in rejected[0]["reason"]
    assert executor.calls == []
    assert result.state.evidence_ledger.evidence == []


def test_phase10_5_qwen_prompt_is_compact_and_decision_specific_for_choose_tool():
    capability_need = CapabilityNeed(
        source_of_truth="operational_state",
        entity="job",
        action="update",
        constraints={"priority": "medium", "new_priority": "high", "requires_approval": True},
        requirement_id="req-001",
    )
    state = PlannerOwnedAgentGraphState(
        original_query="Change medium priority jobs to high.",
        requirement_ledger=RequirementLedger(
            user_goal="Change medium priority jobs to high.",
            requirements=[
                RequirementLedgerEntry(
                    id="req-001",
                    goal="change medium priority jobs to high",
                    requirement_type="mutation_request",
                    entity="job",
                    intent_operation="stage_mutation",
                    source_of_truth="operational_state",
                    constraints={"priority": "medium", "new_priority": "high", "requires_approval": True},
                    locked_constraints=["priority", "new_priority", "requires_approval"],
                )
            ],
        ),
        candidate_tool_windows=[
            CandidateToolWindow(
                requirement_id="req-001",
                capability_need=capability_need,
                candidates=[
                    CandidateTool(tool_name="get__jobs", rank=1, actions=["read"], requires_approval=False),
                    CandidateTool(tool_name="put__jobs_{id}", rank=2, actions=["update"], requires_approval=True),
                ],
            )
        ],
        hydrated_tool_cards=[
            HydratedToolCards(
                requirement_id="req-001",
                cards=[
                    HydratedToolCard(
                        tool_name="get__jobs",
                        actions=["read"],
                        is_read_only=True,
                        requires_approval=False,
                        query_params=["priority"],
                        supports_filters=True,
                        input_schema={"large_input_marker": "x" * 2000},
                        output_schema={"large_output_marker": "y" * 2000},
                    ),
                    HydratedToolCard(
                        tool_name="put__jobs_{id}",
                        actions=["update"],
                        is_read_only=False,
                        requires_approval=True,
                        required_args=["id"],
                        path_params=["id"],
                        metadata={"body_fields": ["priority"], "side_effect_level": "HIGH"},
                        input_schema={"large_write_input_marker": "z" * 2000},
                    ),
                ],
            )
        ],
    )
    context = PlannerDecisionProposalContext(
        decision_id="dec-choose-001",
        requested_decision_kind="choose_tool",
        allowed_decision_kinds=["choose_tool", "revise_requirements", "request_clarification", "fail"],
        requirement_id="req-001",
        capability_need=capability_need,
        candidate_tool_calls=[
            GraphToolCall(
                call_id="call-read",
                kind="api_tool",
                tool_name="get__jobs",
                args={"priority": "medium"},
                requirement_id="req-001",
                candidate_window_id="window-001",
            ),
            GraphToolCall(
                call_id="call-write",
                kind="api_tool",
                tool_name="put__jobs_{id}",
                args={"priority": "medium"},
                requirement_id="req-001",
                candidate_window_id="window-001",
            ),
        ],
    )

    prompt = _build_planner_decision_prompt(state=state, context=context)
    payload = json.loads(prompt)
    decision_state_text = json.dumps(payload["decision_state"], sort_keys=True)

    assert "bounded_graph_state" not in payload
    assert "candidate_tool_windows" not in prompt
    assert "input_schema" not in decision_state_text
    assert "large_input_marker" not in decision_state_text
    assert payload["response_contract"]["minimal_json"]["decision"]["selected_tool_name"]
    assert payload["decision_state"]["tool_choice_policy"]["prefer_write_tool_for_approval_required_mutation"] is True
    assert payload["decision_state"]["tool_choice_policy"]["approval_preview_reads_source_rows"] is True
    write_call = next(
        call for call in payload["decision_state"]["candidate_tool_calls"] if call["tool_name"] == "put__jobs_{id}"
    )
    assert write_call["missing_required_args"] == ["id"]
    assert len(prompt) < 6000


def test_requirement_expansion_revise_prompt_includes_child_rules_and_bounded_context():
    state = _child_expansion_state()
    context = PlannerDecisionProposalContext(
        decision_id="dec-revise-child",
        requested_decision_kind="revise_requirements",
        allowed_decision_kinds=["revise_requirements", "request_clarification", "fail"],
        requirement_id="req-001",
        reason="Consider bounded child expansion after parent evidence.",
    )

    prompt = _build_planner_decision_prompt(state=state, context=context)
    payload = json.loads(prompt)
    decision_state = payload["decision_state"]

    assert payload["response_contract"]["minimal_json"]["proposed_requirement_ledger"]["requirements"] == (
        "complete revised requirement list preserving locked constraints"
    )
    assert decision_state["child_expansion_rules"]["max_child_depth"] == 1
    assert decision_state["child_expansion_rules"]["max_children_per_parent"] == 2
    assert decision_state["child_expansion_rules"]["allowed_initial_child_actions"] == [
        "read",
        "read_one",
        "read_many",
        "list",
        "search_documents",
    ]
    assert decision_state["missing_evidence_reasons"][0]["evidence_refs"] == ["ev-api-machine"]
    assert decision_state["failed_tool_memory"][0]["requirement_id"] == "req-001"
    assert decision_state["candidate_source_of_truth_hints"]["matching_capabilities"] == []
    assert "active_job_id" in json.dumps(decision_state["active_evidence_summary"])
    assert decision_state["full_openapi_catalog_visible"] is False
    assert "input_schema" not in json.dumps(decision_state)


@pytest.mark.asyncio
async def test_requirement_expansion_qwen_adapter_normalizes_valid_child_revision_record():
    state = _child_expansion_state()
    parent = state.requirement_ledger.requirements[0]
    child_id = next_child_requirement_id(parent.id, [requirement.id for requirement in state.requirement_ledger.requirements])
    proposed = state.requirement_ledger.model_dump(mode="json")
    proposed["revision"] = state.requirement_ledger.revision + 1
    proposed["requirements"].append(
        {
            "id": child_id,
            "goal": "Read active job JOB-CAUSE-17 status",
            "requirement_type": "single_entity_status",
            "entity": "job",
            "intent_operation": "report_status",
            "source_of_truth": "operational_state",
            "constraints": {"job_id": "JOB-CAUSE-17"},
            "requested_fields": ["status"],
            "locked_constraints": ["job_id", "requested_fields"],
            "parent_requirement_id": parent.id,
            "expansion_reason": "Machine evidence exposed the active job id.",
            "derived_from_evidence_refs": ["ev-api-machine"],
            "derived_from_missing_reasons": [],
            "depends_on": ["ev-api-machine"],
        }
    )
    proposed["revision_history"] = []
    context = PlannerDecisionProposalContext(
        decision_id="dec-revise-child",
        requested_decision_kind="revise_requirements",
        allowed_decision_kinds=["revise_requirements", "request_clarification", "fail"],
        requirement_id=parent.id,
    )
    model = StaticPlannerModel(
        json.dumps(
            {
                "decision": {
                    "decision_kind": "revise_requirements",
                    "reason": "Add a bounded child requirement from parent evidence.",
                },
                "proposed_requirement_ledger": proposed,
            }
        )
    )
    proposer = OpenAICompatibleQwenPlannerDecisionProposer(_settings(), model=model)

    result = await proposer.propose_decision(state=state, context=context)
    revision = result.submission.proposed_requirement_ledger.revision_history[-1]  # type: ignore[union-attr]

    assert revision.change_type == "add_child_requirements"
    assert revision.details["parent_requirement_id"] == parent.id
    assert revision.details["added_child_requirement_ids"] == [child_id]
    assert revision.details["derived_from_evidence_refs"] == ["ev-api-machine"]
    assert validate_planner_decision(state, result.submission).accepted is True


@pytest.mark.asyncio
async def test_requirement_expansion_qwen_adapter_unjustified_child_ledger_is_rejected_by_gate():
    state = _child_expansion_state()
    parent = state.requirement_ledger.requirements[0]
    child_id = next_child_requirement_id(parent.id, [requirement.id for requirement in state.requirement_ledger.requirements])
    proposed = state.requirement_ledger.model_dump(mode="json")
    proposed["revision"] = state.requirement_ledger.revision + 1
    proposed["requirements"].append(
        {
            "id": child_id,
            "goal": "Read unrelated job status",
            "requirement_type": "single_entity_status",
            "entity": "job",
            "intent_operation": "report_status",
            "source_of_truth": "operational_state",
            "constraints": {"job_id": "JOB-UNSUPPORTED"},
            "requested_fields": ["status"],
            "locked_constraints": ["job_id"],
            "parent_requirement_id": parent.id,
            "expansion_reason": "Planner invented a follow-up.",
            "derived_from_evidence_refs": [],
            "derived_from_missing_reasons": [],
        }
    )
    context = PlannerDecisionProposalContext(
        decision_id="dec-revise-unjustified-child",
        requested_decision_kind="revise_requirements",
        allowed_decision_kinds=["revise_requirements", "request_clarification", "fail"],
        requirement_id=parent.id,
    )
    model = StaticPlannerModel(
        json.dumps(
            {
                "decision": {
                    "decision_kind": "revise_requirements",
                    "reason": "Invent a child requirement.",
                },
                "proposed_requirement_ledger": proposed,
            }
        )
    )
    proposer = OpenAICompatibleQwenPlannerDecisionProposer(_settings(), model=model)

    result = await proposer.propose_decision(state=state, context=context)

    with pytest.raises(PlannerDecisionValidationError, match="child requirement expansion requires evidence"):
        validate_planner_decision(state, result.submission)


@pytest.mark.asyncio
async def test_phase10_5_qwen_adapter_enforces_write_choice_for_approval_required_mutation():
    capability_need = CapabilityNeed(
        source_of_truth="operational_state",
        entity="job",
        action="update",
        constraints={"priority": "medium", "new_priority": "high", "requires_approval": True},
        requirement_id="req-001",
    )
    state = PlannerOwnedAgentGraphState(
        original_query="Change medium priority jobs to high priority.",
        requirement_ledger=RequirementLedger(
            user_goal="Change medium priority jobs to high priority.",
            requirements=[
                RequirementLedgerEntry(
                    id="req-001",
                    goal="change medium priority jobs to high priority",
                    requirement_type="mutation_request",
                    entity="job",
                    intent_operation="stage_mutation",
                    source_of_truth="operational_state",
                    constraints={"priority": "medium", "new_priority": "high", "requires_approval": True},
                    locked_constraints=["priority", "new_priority", "requires_approval"],
                )
            ],
        ),
        candidate_tool_windows=[
            CandidateToolWindow(
                requirement_id="req-001",
                capability_need=capability_need,
                candidates=[
                    CandidateTool(tool_name="get__jobs", rank=1, actions=["list", "read"], requires_approval=False),
                    CandidateTool(tool_name="put__jobs_{id}", rank=2, actions=["update"], requires_approval=True),
                ],
            )
        ],
        hydrated_tool_cards=[
            HydratedToolCards(
                requirement_id="req-001",
                cards=[
                    HydratedToolCard(
                        tool_name="get__jobs",
                        actions=["list", "read"],
                        is_read_only=True,
                        requires_approval=False,
                        query_params=["priority"],
                        supports_filters=True,
                    ),
                    HydratedToolCard(
                        tool_name="put__jobs_{id}",
                        actions=["update"],
                        is_read_only=False,
                        requires_approval=True,
                        required_args=["id"],
                        path_params=["id"],
                        metadata={"body_fields": ["priority"], "side_effect_level": "HIGH"},
                    ),
                ],
            )
        ],
    )
    context = PlannerDecisionProposalContext(
        decision_id="dec-choose-001",
        requested_decision_kind="choose_tool",
        allowed_decision_kinds=["choose_tool", "revise_requirements", "request_clarification", "fail"],
        requirement_id="req-001",
        capability_need=capability_need,
        candidate_tool_calls=[
            GraphToolCall(
                call_id="call-read",
                kind="api_tool",
                tool_name="get__jobs",
                args={"priority": "medium"},
                requirement_id="req-001",
                candidate_window_id="window-001",
            ),
            GraphToolCall(
                call_id="call-write",
                kind="api_tool",
                tool_name="put__jobs_{id}",
                args={"priority": "medium"},
                requirement_id="req-001",
                candidate_window_id="window-001",
            ),
        ],
    )
    model = StaticPlannerModel(
        '{"decision":{"decision_kind":"choose_tool","selected_tool_name":"get__jobs",'
        '"reason":"Use the read tool to preview affected rows."}}'
    )
    proposer = OpenAICompatibleQwenPlannerDecisionProposer(_settings(), model=model)

    result = await proposer.propose_decision(state=state, context=context)

    decision = result.submission.decision
    assert decision.selected_tool_call is not None
    assert decision.selected_tool_call.tool_name == "put__jobs_{id}"
    assert decision.diagnostics["tool_choice_policy_enforced"] == {
        "reason": "approval_required_mutation_requires_write_tool",
        "model_selected_tool_name": "get__jobs",
        "selected_tool_name": "put__jobs_{id}",
    }
    assert validate_planner_decision(state, result.submission).accepted is True


@pytest.mark.asyncio
async def test_phase10_5_qwen_adapter_accepts_compact_selected_tool_name_submission():
    capability_need = CapabilityNeed(
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        constraints={"machine_id": "M-LTH-77"},
        requested_fields=["status"],
        requirement_id="req-001",
    )
    state = PlannerOwnedAgentGraphState(
        original_query="Show machine M-LTH-77 status.",
        requirement_ledger=RequirementLedger(
            user_goal="Show machine M-LTH-77 status.",
            requirements=[
                RequirementLedgerEntry(
                    id="req-001",
                    goal="show machine status",
                    requirement_type="single_entity_status",
                    entity="machine",
                    intent_operation="report_status",
                    source_of_truth="operational_state",
                    constraints={"machine_id": "M-LTH-77"},
                    requested_fields=["status"],
                    locked_constraints=["machine_id"],
                )
            ],
        ),
        hydrated_tool_cards=[
            HydratedToolCards(
                requirement_id="req-001",
                cards=[
                    HydratedToolCard(
                        tool_name="get__machines_{id}",
                        actions=["read_one"],
                        is_read_only=True,
                        required_args=["id"],
                        path_params=["id"],
                    )
                ],
            )
        ],
    )
    context = PlannerDecisionProposalContext(
        decision_id="dec-choose-001",
        requested_decision_kind="choose_tool",
        allowed_decision_kinds=["choose_tool", "revise_requirements", "request_clarification", "fail"],
        requirement_id="req-001",
        capability_need=capability_need,
        candidate_tool_calls=[
            GraphToolCall(
                call_id="call-001",
                kind="api_tool",
                tool_name="get__machines_{id}",
                args={"id": "M-LTH-77", "fields": "status"},
                requirement_id="req-001",
                candidate_window_id="window-001",
            )
        ],
    )
    model = StaticPlannerModel(
        '{"decision":{"decision_kind":"choose_tool","selected_tool_name":"get__machines_{id}",'
        '"reason":"Use the hydrated read tool."}}'
    )
    proposer = OpenAICompatibleQwenPlannerDecisionProposer(_settings(), model=model)

    result = await proposer.propose_decision(state=state, context=context)

    assert result.submission.decision.selected_tool_call is not None
    assert result.submission.decision.selected_tool_call.tool_name == "get__machines_{id}"
    assert result.submission.decision.diagnostics["planner_proposer"]["proposer_seam"] is True
    assert "selected_tool_name" not in result.submission.decision.model_dump(mode="json")


@pytest.mark.asyncio
async def test_replan_spine_qwen_adapter_carries_filtered_candidates_for_failed_memory_gate():
    capability_need = CapabilityNeed(
        source_of_truth="operational_state",
        entity="machine",
        action="read_one",
        constraints={"machine_id": "M-LTH-77"},
        requested_fields=["status"],
        requirement_id="req-001",
    )
    state = PlannerOwnedAgentGraphState(
        original_query="Show machine M-LTH-77 status.",
        requirement_ledger=RequirementLedger(
            user_goal="Show machine M-LTH-77 status.",
            requirements=[
                RequirementLedgerEntry(
                    id="req-001",
                    goal="show machine status",
                    requirement_type="single_entity_status",
                    entity="machine",
                    intent_operation="report_status",
                    source_of_truth="operational_state",
                    constraints={"machine_id": "M-LTH-77"},
                    requested_fields=["status"],
                    locked_constraints=["machine_id"],
                )
            ],
        ),
        candidate_tool_windows=[
            CandidateToolWindow(
                requirement_id="req-001",
                capability_need=capability_need,
                candidates=[
                    CandidateTool(tool_name="get__machines_{id}", rank=1, actions=["read_one", "read"]),
                    CandidateTool(tool_name="get__machine_status_{id}", rank=2, actions=["read_one", "read"]),
                ],
            )
        ],
        hydrated_tool_cards=[
            HydratedToolCards(
                requirement_id="req-001",
                cards=[
                    HydratedToolCard(
                        tool_name="get__machines_{id}",
                        actions=["read_one"],
                        is_read_only=True,
                        required_args=["id"],
                        path_params=["id"],
                        query_params=["fields"],
                    ),
                    HydratedToolCard(
                        tool_name="get__machine_status_{id}",
                        actions=["read_one"],
                        is_read_only=True,
                        required_args=["id"],
                        path_params=["id"],
                        query_params=["fields"],
                    ),
                ],
            )
        ],
    )
    failed_call = GraphToolCall(
        call_id="call-failed-primary",
        kind="api_tool",
        tool_name="get__machines_{id}",
        args={"id": "M-LTH-77", "fields": "status"},
        requirement_id="req-001",
        candidate_window_id="window-001",
    )
    alternate_call = GraphToolCall(
        call_id="call-alternate-status",
        kind="api_tool",
        tool_name="get__machine_status_{id}",
        args={"id": "M-LTH-77", "fields": "status"},
        requirement_id="req-001",
        candidate_window_id="window-001",
    )
    state.execution_trace.diagnostics["replan_spine"] = {
        "failed_tool_calls": [
            {
                "tool_name": failed_call.tool_name,
                "args": dict(failed_call.args),
                "requirement_id": "req-001",
                "evidence_ref": "evidence-failed-primary",
                "reason": "tool_error",
                "attempt": 1,
            }
        ]
    }
    context = PlannerDecisionProposalContext(
        decision_id="dec-choose-001",
        requested_decision_kind="choose_tool",
        allowed_decision_kinds=["choose_tool", "revise_requirements", "request_clarification", "fail"],
        requirement_id="req-001",
        capability_need=capability_need,
        candidate_tool_calls=[alternate_call],
    )
    model = StaticPlannerModel(
        '{"decision":{"decision_kind":"choose_tool",'
        '"selected_tool_call":{'
        '"call_id":"call-failed-primary",'
        '"kind":"api_tool",'
        '"tool_name":"get__machines_{id}",'
        '"args":{"id":"M-LTH-77","fields":"status"},'
        '"requirement_id":"req-001",'
        '"candidate_window_id":"window-001"'
        '},'
        '"reason":"Repeat the previous full selected tool call."}}'
    )
    proposer = OpenAICompatibleQwenPlannerDecisionProposer(_settings(), model=model)

    result = await proposer.propose_decision(state=state, context=context)

    assert result.submission.decision.selected_tool_call is not None
    assert result.submission.decision.selected_tool_call.tool_name == failed_call.tool_name
    assert result.submission.candidate_tool_calls == [alternate_call]
    with pytest.raises(PlannerDecisionValidationError, match="failed-tool memory"):
        validate_planner_decision(state, result.submission)


@pytest.mark.asyncio
async def test_phase10_5_qwen_adapter_expands_compact_tool_name_to_read_batch():
    capability_need = CapabilityNeed(
        source_of_truth="operational_state",
        entity="job",
        action="list",
        constraints={"job_id": ["JOB-001", "JOB-002"]},
        requested_fields=["job_id", "status"],
        requirement_id="req-001",
    )
    state = PlannerOwnedAgentGraphState(
        original_query="Find status for job ids JOB-001 and JOB-002.",
        requirement_ledger=RequirementLedger(
            user_goal="Find status for job ids JOB-001 and JOB-002.",
            requirements=[
                RequirementLedgerEntry(
                    id="req-001",
                    goal="show job statuses",
                    requirement_type="multi_entity_status",
                    entity="job",
                    intent_operation="report_multi_status",
                    source_of_truth="operational_state",
                    constraints={"job_id": ["JOB-001", "JOB-002"]},
                    requested_fields=["job_id", "status"],
                    locked_constraints=["job_id", "requested_fields"],
                )
            ],
        ),
        candidate_tool_windows=[
            CandidateToolWindow(
                requirement_id="req-001",
                capability_need=capability_need,
                candidates=[
                    CandidateTool(
                        tool_name="get__jobs_{id}",
                        rank=1,
                        actions=["read_one", "read"],
                        source_of_truth="operational_state",
                    )
                ],
            )
        ],
        hydrated_tool_cards=[
            HydratedToolCards(
                requirement_id="req-001",
                cards=[
                    HydratedToolCard(
                        tool_name="get__jobs_{id}",
                        actions=["read_one", "read"],
                        is_read_only=True,
                        required_args=["id"],
                        path_params=["id"],
                    )
                ],
            )
        ],
    )
    context = PlannerDecisionProposalContext(
        decision_id="dec-choose-001",
        requested_decision_kind="choose_tool",
        allowed_decision_kinds=["choose_tool", "revise_requirements", "request_clarification", "fail"],
        requirement_id="req-001",
        capability_need=capability_need,
        candidate_tool_calls=[
            GraphToolCall(
                call_id="call-001",
                kind="api_tool",
                tool_name="get__jobs_{id}",
                args={"id": "JOB-001", "fields": "job_id,status"},
                requirement_id="req-001",
                candidate_window_id="window-001",
            ),
            GraphToolCall(
                call_id="call-002",
                kind="api_tool",
                tool_name="get__jobs_{id}",
                args={"id": "JOB-002", "fields": "job_id,status"},
                requirement_id="req-001",
                candidate_window_id="window-001",
            ),
        ],
    )
    model = StaticPlannerModel(
        '{"decision":{"decision_kind":"choose_tool","selected_tool_name":"get__jobs_{id}",'
        '"reason":"Use the hydrated job read tool for both requested ids."}}'
    )
    proposer = OpenAICompatibleQwenPlannerDecisionProposer(_settings(), model=model)

    result = await proposer.propose_decision(state=state, context=context)

    assert result.submission.decision.selected_tool_call is None
    assert [call.args["id"] for call in result.submission.decision.selected_tool_calls] == ["JOB-001", "JOB-002"]
    assert validate_planner_decision(state, result.submission).accepted is True


@pytest.mark.asyncio
async def test_phase10_5_parallel_read_batch_guard_authorizes_each_selected_call():
    capability_need = CapabilityNeed(
        source_of_truth="operational_state",
        entity="machine",
        action="list",
        constraints={"machine_id": ["M-UNIT-A", "M-UNIT-B"]},
        requested_fields=["machine_id", "status"],
        requirement_id="req-001",
    )
    state = PlannerOwnedAgentGraphState(
        original_query="Show machine M-UNIT-A and M-UNIT-B statuses.",
        requirement_ledger=RequirementLedger(
            user_goal="Show machine M-UNIT-A and M-UNIT-B statuses.",
            requirements=[
                RequirementLedgerEntry(
                    id="req-001",
                    goal="show machine statuses",
                    requirement_type="multi_entity_status",
                    entity="machine",
                    intent_operation="report_multi_status",
                    source_of_truth="operational_state",
                    constraints={"machine_id": ["M-UNIT-A", "M-UNIT-B"]},
                    requested_fields=["machine_id", "status"],
                    locked_constraints=["machine_id", "requested_fields"],
                )
            ],
        ),
        candidate_tool_windows=[
            CandidateToolWindow(
                requirement_id="req-001",
                capability_need=capability_need,
                candidates=[
                    CandidateTool(
                        tool_name="get__machines_{id}",
                        rank=1,
                        actions=["read_one", "read"],
                        source_of_truth="operational_state",
                    )
                ],
            )
        ],
        hydrated_tool_cards=[
            HydratedToolCards(
                requirement_id="req-001",
                cards=[
                    HydratedToolCard(
                        tool_name="get__machines_{id}",
                        actions=["read_one", "read"],
                        is_read_only=True,
                        required_args=["id"],
                        path_params=["id"],
                    )
                ],
            )
        ],
    )
    calls = [
        GraphToolCall(
            call_id="call-001",
            kind="api_tool",
            tool_name="get__machines_{id}",
            args={"id": "M-UNIT-A", "fields": "machine_id,status"},
            requirement_id="req-001",
            candidate_window_id="window-001",
        ),
        GraphToolCall(
            call_id="call-002",
            kind="api_tool",
            tool_name="get__machines_{id}",
            args={"id": "M-UNIT-B", "fields": "machine_id,status"},
            requirement_id="req-001",
            candidate_window_id="window-001",
        ),
    ]
    choose = _proposal(
        PlannerDecisionRecord(
            decision_id="dec-choose-001",
            decision_kind="choose_tool",
            requirement_id="req-001",
            ledger_revision=state.requirement_ledger.revision,
            capability_need=capability_need,
            selected_tool_calls=calls,
            reason="Planner selects both bounded read calls.",
        ),
        adapter="phase10_5_batch_mock_proposer",
    ).submission.decision
    assert record_planner_decision(
        state,
        PlannerDecisionSubmission(decision=choose, candidate_tool_calls=calls),
    ).accepted is True
    execute_batch = PlannerDecisionRecord(
        decision_id="dec-execute-002",
        decision_kind="execute_parallel_read_batch",
        author="deterministic_guard",
        requirement_id="req-001",
        ledger_revision=state.requirement_ledger.revision,
        capability_need=capability_need,
        selected_tool_calls=calls,
        reason="Execute the persisted planner-selected read batch.",
    )
    assert record_planner_decision(state, execute_batch).accepted is True
    executor = RecordingExecutor()
    adapters = PlannerOwnedAgentGraphAdapters(
        settings=_settings(),
        tools_by_name={"get__machines_{id}": _machine_status_tool()},
        http_executor=executor,
    )

    for call in calls:
        execution_decision = execute_batch.model_copy(
            update={"selected_tool_call": call, "selected_tool_calls": []}
        )
        result = await adapters.execute_tool(state, execution_decision)
        assert result.ok is True

    assert [call["args"]["id"] for call in executor.calls] == ["M-UNIT-A", "M-UNIT-B"]


def test_phase10_5_deterministic_guard_can_choose_single_bounded_document_tool():
    capability_need = CapabilityNeed(
        source_of_truth="document_knowledge",
        entity="procedure",
        action="search_documents",
        constraints={"topic": "maintenance safety"},
        requested_fields=["answer", "citations"],
        requirement_id="req-001",
    )
    state = PlannerOwnedAgentGraphState(
        original_query="Which maintenance safety procedure applies?",
        requirement_ledger=RequirementLedger(
            user_goal="Which maintenance safety procedure applies?",
            requirements=[
                RequirementLedgerEntry(
                    id="req-001",
                    goal="answer maintenance safety procedure question",
                    requirement_type="document_answer",
                    entity="procedure",
                    intent_operation="answer_document_question",
                    source_of_truth="document_knowledge",
                    constraints={"topic": "maintenance safety"},
                    requested_fields=["answer", "citations"],
                )
            ],
        ),
        candidate_tool_windows=[
            CandidateToolWindow(
                requirement_id="req-001",
                capability_need=capability_need,
                candidates=[
                    CandidateTool(
                        tool_name="rag_search_documents",
                        rank=1,
                        actions=["search_documents", "read"],
                        source_of_truth="document_knowledge",
                    )
                ],
            )
        ],
        hydrated_tool_cards=[
            HydratedToolCards(
                requirement_id="req-001",
                cards=[
                    HydratedToolCard(
                        tool_name="rag_search_documents",
                        actions=["search_documents", "read"],
                        source_of_truth="document_knowledge",
                        is_read_only=True,
                    )
                ],
            )
        ],
    )
    decision = PlannerDecisionRecord(
        decision_id="dec-choose-001",
        decision_kind="choose_tool",
        author="deterministic_guard",
        requirement_id="req-001",
        ledger_revision=state.requirement_ledger.revision,
        capability_need=capability_need,
        selected_tool_call=GraphToolCall(
            call_id="call-001",
            kind="rag_tool",
            tool_name="rag_search_documents",
            args={"query": "maintenance safety"},
            requirement_id="req-001",
            candidate_window_id="window-001",
        ),
        reason="Choose the only bounded document tool.",
    )

    assert validate_planner_decision(state, decision).accepted is True
    record_planner_decision(state, decision)
    execute = PlannerDecisionRecord(
        decision_id="dec-execute-002",
        decision_kind="execute_tool",
        author="deterministic_guard",
        requirement_id="req-001",
        ledger_revision=state.requirement_ledger.revision,
        capability_need=capability_need,
        selected_tool_call=decision.selected_tool_call,
        reason="Execute the persisted deterministic document tool choice.",
    )

    assert validate_planner_decision(state, execute).accepted is True


def test_phase10_5_static_planner_authored_graph_decisions_use_proposer_seam():
    source = GRAPH_SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    graph_record_calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PlannerDecisionRecord"
    ]

    for call in graph_record_calls:
        author_keywords = [keyword for keyword in call.keywords if keyword.arg == "author"]
        assert author_keywords, "graph-owned PlannerDecisionRecord calls must spell out non-planner authors"
        author = author_keywords[0].value
        assert not (isinstance(author, ast.Constant) and author.value == "planner")

    assert 'proposer_kwargs: dict[str, Any] = {"state": state, "context": context}' in source
    assert '"parent_run_config"' in source
    assert "self._proposer.propose_decision(**proposer_kwargs)" in source
    assert "proposal.submission.model_copy" in source
    assert '"candidate_tool_calls": list(context.candidate_tool_calls)' in source
    assert "record_planner_decision(state, submission)" in source
    assert "planner_proposer" in source
