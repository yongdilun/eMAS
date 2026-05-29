from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from factory_agent.config import Settings
from factory_agent.graph.v2_agent_graph import PlannerOwnedGraphResult
from factory_agent.persistence.models import Session
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_contracts import CapabilityNeed, EvidenceLedgerEntry, RequirementLedgerEntry
from factory_agent.planning.v2_agent_state import build_initial_planner_owned_agent_graph_state
from factory_agent.planning.v2_tool_retriever import V2CapabilityToolRetriever
from factory_agent.schemas import PlanResponse, ToolInfo
from factory_agent.services.plan_creation_service import PlanCreationService
from factory_agent.services import planner_owned_graph_runtime as runtime_module
from factory_agent.services.planner_owned_graph_runtime import LiveGraphActivityRecorder, PlannerOwnedGraphRuntimeAdapter


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_CREATION_SOURCE = REPO_ROOT / "factory_agent" / "services" / "plan_creation_service.py"
APPROVAL_RESUME_SOURCE = REPO_ROOT / "factory_agent" / "services" / "approval_resume_service.py"
RUNTIME_ADAPTER_SOURCE = REPO_ROOT / "factory_agent" / "services" / "planner_owned_graph_runtime.py"


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
        enforce_tool_registry_health=False,
        min_healthy_tool_count=0,
        tool_selector_backend="retrieval",
    )


def _tool() -> ToolInfo:
    return ToolInfo(
        name="get__machines_{id}",
        description="Read machine status",
        endpoint="/machines/{id}",
        method="GET",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        output_schema={"type": "object"},
        path_params=["id"],
        is_read_only=True,
        capability_tags=["machine", "status", "operational_state"],
    )


def _job_tool(
    name: str,
    *,
    endpoint: str,
    required: list[str] | None = None,
    query_params: list[str] | None = None,
) -> ToolInfo:
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "x-ai-id-field": "job_id", "x-ai-entity": "job"},
            "job_id": {"type": "array", "items": {"type": "string"}, "x-ai-entity": "job"},
            "fields": {"type": "string"},
        },
    }
    if required:
        input_schema["required"] = list(required)
    return ToolInfo(
        name=name,
        description=name.replace("_", " "),
        endpoint=endpoint,
        method="GET",
        input_schema=input_schema,
        output_schema={
            "type": "object",
            "properties": {"job_id": {"type": "string"}, "status": {"type": "string"}},
            "x-ai-entity": "job",
            "x-ai-response-contracts": ["entity_status_v1"],
        },
        path_params=[field for field in required or [] if f"{{{field}}}" in endpoint],
        query_params=list(query_params or []),
        param_sources={field: "path" for field in required or [] if f"{{{field}}}" in endpoint}
        | {field: "query" for field in query_params or []},
        is_read_only=True,
        capability_tags=["job", "status", "operational_state"],
    )


def _service() -> PlanCreationService:
    return PlanCreationService(
        settings=_settings(),
        session_mgr=SimpleNamespace(),
        memory_manager=SimpleNamespace(),
        planner=SimpleNamespace(),
        tool_selector=SimpleNamespace(),
        summary_adapter=SimpleNamespace(),
        tool_registry=SimpleNamespace(),
        uuid_factory=lambda: "uuid",
    )


def _function_node(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    module = ast.parse(source)
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_phase10_static_normal_runtime_adapter_uses_graph_not_direct_execution():
    source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    runtime_source = RUNTIME_ADAPTER_SOURCE.read_text(encoding="utf-8")

    graph_adapter = _function_node(source, "_create_planner_owned_graph_plan")
    runtime_run = _function_node(runtime_source, "run_plan")

    graph_calls = _called_names(graph_adapter)
    runtime_calls = _called_names(runtime_run)
    defined_functions = {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_create_direct_v2_plan" not in defined_functions
    assert "_create_planner_owned_graph_v2_plan" not in defined_functions
    assert "_execute_direct_v2_steps" not in graph_calls
    assert "_create_historical_direct_v2_plan" not in graph_calls
    assert "_planner_owned_graph_runtime" in graph_calls
    assert "run_plan" in graph_calls
    assert "_build_graph" in runtime_calls
    assert "run" in runtime_calls
    assert '"thread_id": sess.session_id' in runtime_source


@pytest.mark.asyncio
async def test_phase10_behavior_normal_v2_plan_creation_enters_graph_path(monkeypatch):
    service = _service()
    calls: list[dict[str, Any]] = []

    class FakeRuntime:
        async def run_plan(self, *, db, sess, tools_by_name, intent, mode):
            calls.append(
                {
                    "user_message": intent,
                    "session_context": sess,
                    "options": {"thread_id": sess.session_id},
                    "mode": mode,
                }
            )
            state = build_initial_planner_owned_agent_graph_state(intent, tools_by_name={"get__machines_{id}": _tool()})
            result = PlannerOwnedGraphResult(
                state=state,
                node_order=["semantic_intake_node"],
                checkpoint_config={"configurable": {"thread_id": sess.session_id}},
            )
            assert result.state.execution_trace.generated_by == "planner_owned_agent_graph"
            assert result.checkpoint_config["configurable"]["thread_id"] == "phase10-session"
            return PlanResponse(
                plan_id="plan-graph",
                session_id="phase10-session",
                version=1,
                kind="execution",
                status="COMPLETED",
                plan_hash="hash",
                plan_explanation="graph path",
                risk_summary="graph runtime",
                created_at=datetime.utcnow(),
                created_by="planner_owned_agent_graph",
            )

    monkeypatch.setattr(service, "_planner_owned_graph_runtime", lambda: FakeRuntime())

    sess = SimpleNamespace(session_id="phase10-session", replan_context={}, llm_call_count=0)
    assert not hasattr(service, "_execute_direct_v2_steps")
    response = await service._create_planner_owned_graph_plan(
        db=SimpleNamespace(),
        sess=sess,
        tools_by_name={"get__machines_{id}": _tool()},
        intent="Show machine M-100 status.",
        mode="normal",
    )

    assert response.created_by == "planner_owned_agent_graph"
    assert calls == [
        {
            "user_message": "Show machine M-100 status.",
            "session_context": sess,
            "options": {"thread_id": "phase10-session"},
            "mode": "normal",
        }
    ]


@pytest.mark.asyncio
async def test_phase10_graph_runtime_records_live_activity_for_activity_sse(sessionmaker_override, db_session):
    created_at = datetime(2026, 5, 13, 9, 0, 0)
    db_session.add(
        Session(
            session_id="phase10-live-activity",
            user_id="u1",
            status="EXECUTING",
            current_intent="Answer from LOTO sources",
            session_started_at=created_at,
            created_at=created_at,
            updated_at=created_at,
            replan_context={},
            event_seq=3,
        )
    )
    await db_session.commit()

    recorder = LiveGraphActivityRecorder(
        session_factory=sessionmaker_override,
        session_id="phase10-live-activity",
    )
    recorder.record_graph_event(
        {
            "event": "planner_owned_agent_graph_node",
            "node": "semantic_intake_node",
            "ledger_revision": 1,
        }
    )
    recorder.record_graph_event(
        {
            "event": "planner_owned_agent_graph_node",
            "node": "tool_execution_node",
            "ledger_revision": 1,
            "source_types": ["rag_tool"],
            "tool_names": ["rag_search_documents"],
        }
    )
    await recorder.flush()

    async with sessionmaker_override() as verify:
        row = (
            await verify.execute(
                select(Session).where(Session.session_id == "phase10-live-activity")
            )
        ).scalar_one()

    live_steps = row.replan_context["live_activity_steps"]
    assert [step["label"] for step in live_steps] == [
        "Understood request",
        "Searching knowledge sources",
    ]
    assert live_steps[1]["detail"] == "Searching retrieved documents"
    assert row.event_seq > 3


@pytest.mark.asyncio
async def test_graph_runtime_refreshes_session_context_after_live_activity_flush(sessionmaker_override, db_session):
    created_at = datetime(2026, 5, 13, 9, 0, 0)
    sess = Session(
        session_id="phase10-live-activity-refresh",
        user_id="u1",
        status="EXECUTING",
        current_intent="Read jobs and products",
        session_started_at=created_at,
        created_at=created_at,
        updated_at=created_at,
        replan_context={},
        event_seq=3,
    )
    db_session.add(sess)
    await db_session.commit()

    recorder = LiveGraphActivityRecorder(
        session_factory=sessionmaker_override,
        session_id="phase10-live-activity-refresh",
    )
    recorder.record_graph_event(
        {
            "event": "planner_owned_agent_graph_node",
            "node": "semantic_intake_node",
            "ledger_revision": 1,
        }
    )
    await recorder.flush()

    adapter = PlannerOwnedGraphRuntimeAdapter(
        settings=_settings(),
        tool_selector=SimpleNamespace(),
        rag_pipeline=None,
        uuid_factory=lambda: "uuid",
        persist_plan=SimpleNamespace(),
        session_lookup=SimpleNamespace(),
    )

    assert sess.replan_context == {}
    await adapter._refresh_session_live_activity_context(db=db_session, sess=sess)

    assert sess.replan_context["live_activity_steps"][0]["label"] == "Understood request"


@pytest.mark.asyncio
async def test_live_activity_preserves_graph_progress_order_when_nodes_share_timestamp(
    sessionmaker_override,
    db_session,
    monkeypatch,
):
    created_at = datetime(2026, 5, 13, 9, 0, 0)

    class FrozenDateTime:
        @staticmethod
        def utcnow():
            return created_at

    monkeypatch.setattr(runtime_module, "datetime", FrozenDateTime)
    db_session.add(
        Session(
            session_id="phase10-live-activity-order",
            user_id="u1",
            status="EXECUTING",
            current_intent="Find low priority jobs",
            session_started_at=created_at,
            created_at=created_at,
            updated_at=created_at,
            replan_context={},
            event_seq=3,
        )
    )
    await db_session.commit()

    recorder = LiveGraphActivityRecorder(
        session_factory=sessionmaker_override,
        session_id="phase10-live-activity-order",
    )
    for node in [
        "requirement_ledger_node",
        "planner_decision_node",
        "tool_execution_node",
        "evidence_observation_node",
    ]:
        recorder.record_graph_event(
            {
                "event": "planner_owned_agent_graph_node",
                "node": node,
                "ledger_revision": 1,
            }
        )
    await recorder.flush()

    async with sessionmaker_override() as verify:
        row = (
            await verify.execute(
                select(Session).where(Session.session_id == "phase10-live-activity-order")
            )
        ).scalar_one()

    assert [step["detail"] for step in row.replan_context["live_activity_steps"]] == [
        "Structuring the request",
        "Choosing the next backend action",
        "Checking relevant records",
        "Checking tool evidence",
    ]
    assert [step["label"] for step in row.replan_context["live_activity_steps"]] == [
        "Structuring request",
        "Choosing next action",
        "Running selected tool",
        "Checking result",
    ]
    assert [step["order"] for step in row.replan_context["live_activity_steps"]] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_live_activity_labels_do_not_duplicate_distinct_result_and_response_nodes(
    sessionmaker_override,
    db_session,
):
    created_at = datetime(2026, 5, 13, 9, 0, 0)
    db_session.add(
        Session(
            session_id="phase10-live-activity-distinct-labels",
            user_id="u1",
            status="EXECUTING",
            current_intent="Summarize two jobs and products",
            session_started_at=created_at,
            created_at=created_at,
            updated_at=created_at,
            replan_context={},
            event_seq=3,
        )
    )
    await db_session.commit()

    recorder = LiveGraphActivityRecorder(
        session_factory=sessionmaker_override,
        session_id="phase10-live-activity-distinct-labels",
    )
    for node in [
        "evidence_observation_node",
        "satisfaction_node",
        "finalize_node",
        "response_document_node",
    ]:
        recorder.record_graph_event(
            {
                "event": "planner_owned_agent_graph_node",
                "node": node,
                "ledger_revision": 1,
            }
        )
    await recorder.flush()

    async with sessionmaker_override() as verify:
        row = (
            await verify.execute(
                select(Session).where(Session.session_id == "phase10-live-activity-distinct-labels")
            )
        ).scalar_one()

    labels = [step["label"] for step in row.replan_context["live_activity_steps"]]

    assert labels == [
        "Checking result",
        "Verifying result",
        "Preparing response",
        "Rendering response",
    ]


@pytest.mark.asyncio
async def test_live_activity_persists_active_replan_spine_for_retry_story(
    sessionmaker_override,
    db_session,
):
    created_at = datetime(2026, 5, 13, 9, 0, 0)
    db_session.add(
        Session(
            session_id="phase10-live-replan-spine",
            user_id="u1",
            status="EXECUTING",
            current_intent="Find low priority jobs",
            session_started_at=created_at,
            created_at=created_at,
            updated_at=created_at,
            replan_context={},
            event_seq=3,
        )
    )
    await db_session.commit()

    replan_spine = {
        "attempt_count": 1,
        "max_attempts": 5,
        "attempts": [
            {
                "attempt": 1,
                "missing_evidence_reasons": [{"reason": "tool_error", "evidence_refs": ["ev-1"]}],
                "failed_tool_calls": [
                    {
                        "tool_name": "get__jobs",
                        "args": {"priority": "low"},
                        "reason": "tool_error",
                        "error_type": "timeout",
                        "attempt": 1,
                    }
                ],
            }
        ],
        "failed_tool_calls": [
            {
                "tool_name": "get__jobs",
                "args": {"priority": "low"},
                "reason": "tool_error",
                "error_type": "timeout",
                "attempt": 1,
            }
        ],
    }
    recorder = LiveGraphActivityRecorder(
        session_factory=sessionmaker_override,
        session_id="phase10-live-replan-spine",
    )
    recorder.record_graph_event(
        {
            "event": "planner_owned_agent_graph_node",
            "node": "planner_decision_node",
            "ledger_revision": 2,
            "replan_spine": replan_spine,
        }
    )
    await recorder.flush()

    async with sessionmaker_override() as verify:
        row = (
            await verify.execute(
                select(Session).where(Session.session_id == "phase10-live-replan-spine")
            )
        ).scalar_one()

    assert row.replan_context["live_replan_spine"] == replan_spine
    assert row.replan_context["live_replan_spine_revision"] == 1
    assert "_replan_spine" not in row.replan_context["live_activity_steps"][0]


def test_phase10_static_approval_resume_uses_native_graph_checkpoint_before_historical_direct_resume():
    source = APPROVAL_RESUME_SOURCE.read_text(encoding="utf-8")
    resume = _function_node(source, "resume_approved_graph_approval")
    calls = _called_names(resume)

    assert "_resume_planner_owned_agent_graph_approval" in calls
    assert source.index("_resume_planner_owned_agent_graph_approval") < source.index("_resume_direct_v2_planner_approval")
    graph_resume = _function_node(source, "_resume_planner_owned_agent_graph_approval")
    graph_calls = _called_names(graph_resume)
    assert "resume_planner_owned_graph_approval" in graph_calls
    assert "persist_planner_owned_graph_result" in graph_calls
    assert "session_replan_context_authoritative" not in ast.get_source_segment(source, graph_resume)


@pytest.mark.asyncio
async def test_phase10_multi_id_graph_retrieval_completes_collection_reader_when_selector_returns_item_only():
    class ItemOnlySelector:
        async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
            request = kwargs["context"]["v2_tool_selector_adapter_request"]
            assert request["endpoint_shape"] == "collection"
            return ToolSelectionResult(["get__jobs_{id}"], backend_used="retrieval", llm_calls=0)

    retriever = V2CapabilityToolRetriever(ItemOnlySelector())  # type: ignore[arg-type]
    result = await retriever.retrieve_tools_for_need(
        CapabilityNeed(
            requirement_id="req-jobs",
            source_of_truth="operational_state",
            entity="job",
            action="read_many",
            constraints={"job_id": ["JOB-1", "JOB-2"]},
            requested_fields=["job_id", "status"],
        ),
        tools_by_name={
            "get__jobs_{id}": _job_tool("get__jobs_{id}", endpoint="/jobs/{id}", required=["id"], query_params=["fields"]),
            "get__jobs": _job_tool("get__jobs", endpoint="/jobs", query_params=["job_id", "fields"]),
        },
    )

    assert result.status == "ok"
    assert [candidate.tool_name for candidate in result.candidate_window.candidates] == [
        "get__jobs_{id}",
        "get__jobs",
    ]
    assert result.trace.diagnostics["metadata_read_completion_used"] is True
    collection_card = next(card for card in result.hydrated_tool_cards.cards if card.tool_name == "get__jobs")
    assert collection_card.path_params == []
    assert collection_card.query_params == ["job_id", "fields"]


def test_phase10_static_no_legacy_or_seed_runtime_branches_added():
    source = PLAN_CREATION_SOURCE.read_text(encoding="utf-8")
    runtime_source = RUNTIME_ADAPTER_SOURCE.read_text(encoding="utf-8")
    runtime = ast.get_source_segment(source, _function_node(source, "_create_planner_owned_graph_plan")) or ""
    runtime_adapter = ast.get_source_segment(runtime_source, _function_node(runtime_source, "run_plan")) or ""

    banned = [
        "legacy_rag_route",
        "working_intents",
        "intent_cursor",
        "intent_completed",
        "JOB-SEED",
        "M-CNC-01",
        "src-loto",
    ]
    for literal in banned:
        assert literal not in runtime
        assert literal not in runtime_adapter


def test_phase10_graph_runtime_projects_approval_business_change_metadata_into_tool_outputs():
    state = build_initial_planner_owned_agent_graph_state(
        "Change medium-priority jobs to high priority.",
        tools_by_name={},
    )
    state.requirement_ledger.requirements = [
        RequirementLedgerEntry(
            id="req-job-priority",
            goal="Change medium-priority jobs to high priority.",
            requirement_type="mutation_request",
            entity="job",
            intent_operation="stage_mutation",
            source_of_truth="operational_state",
            constraints={"priority": "medium", "new_priority": "high"},
        )
    ]
    state.evidence_ledger.evidence.extend(
        [
            EvidenceLedgerEntry(
                id="ev-approval-approved",
                requirement_id="req-job-priority",
                source_type="approval",
                source_of_truth="operational_state",
                approval_id="approval-graph-1",
                normalized_result={"approval_status": "approved", "status": "approved"},
                diagnostic_metadata={
                    "approval_id": "approval-graph-1",
                    "locked_constraints": {"priority": "medium", "new_priority": "high"},
                    "preview_rows": [
                        {"job_id": "JOB-A", "priority": "medium", "previous_priority": "medium", "new_priority": "high"},
                        {"job_id": "JOB-B", "priority": "medium", "previous_priority": "medium", "new_priority": "high"},
                    ],
                    "staged_graph_tool_calls": [
                        {"tool_name": "put__jobs_{id}", "args": {"id": "JOB-A", "priority": "high"}},
                        {"tool_name": "put__jobs_{id}", "args": {"id": "JOB-B", "priority": "high"}},
                    ],
                },
            ),
            EvidenceLedgerEntry(
                id="ev-api-write",
                requirement_id="req-job-priority",
                source_type="api_tool",
                source_of_truth="operational_state",
                tool_name="put__jobs_{id}",
                args={"id": "JOB-A", "priority": "high"},
                normalized_result={"status_code": 200, "fields": {"job_id": "JOB-A", "priority": "high"}},
                satisfies=["operational_state_tool_result"],
                diagnostic_metadata={"graph_authorized_execution": True},
            ),
        ]
    )
    adapter = PlannerOwnedGraphRuntimeAdapter(
        settings=_settings(),
        tool_selector=SimpleNamespace(),
        rag_pipeline=None,
        uuid_factory=lambda: "uuid",
        persist_plan=SimpleNamespace(),
        session_lookup=SimpleNamespace(),
    )

    outputs = adapter._tool_outputs(
        PlannerOwnedGraphResult(
            state=state,
            node_order=["tool_execution_node", "response_document_node"],
            checkpoint_config={"configurable": {"thread_id": "phase10-session"}},
        )
    )

    assert len(outputs) == 1
    output = outputs[0]
    assert output["approval_id"] == "approval-graph-1"
    assert output["summary"] == "Updated 2 medium-priority jobs to high."
    assert output["args"]["previous_priority"] == "medium"
    assert output["args"]["new_priority"] == "high"
    data = output["result"]["data"]
    assert data["approval_id"] == "approval-graph-1"
    assert data["entity_type"] == "job"
    assert data["previous_priority"] == "medium"
    assert data["new_priority"] == "high"
    assert data["selector_summary"] == "priority = medium"
    assert data["field_changes"] == [{"field": "priority", "label": "Priority", "from": "medium", "to": "high"}]


def test_phase10_graph_runtime_keeps_no_record_preview_out_of_executable_tool_outputs():
    state = build_initial_planner_owned_agent_graph_state(
        "Change low-priority jobs to medium, then medium-priority jobs to high.",
        tools_by_name={},
    )
    state.requirement_ledger.requirements = [
        RequirementLedgerEntry(
            id="req-low-medium",
            goal="Change low-priority jobs to medium.",
            requirement_type="mutation_request",
            entity="job",
            intent_operation="stage_mutation",
            source_of_truth="operational_state",
            constraints={"priority": "low", "new_priority": "medium"},
        ),
        RequirementLedgerEntry(
            id="req-medium-high",
            goal="Change medium-priority jobs to high.",
            requirement_type="mutation_request",
            entity="job",
            intent_operation="stage_mutation",
            source_of_truth="operational_state",
            constraints={"priority": "medium", "new_priority": "high"},
        ),
    ]
    state.evidence_ledger.evidence.extend(
        [
            EvidenceLedgerEntry(
                id="ev-low-no-records",
                requirement_id="req-low-medium",
                source_type="system_guard",
                source_of_truth="operational_state",
                tool_name="patch__jobs_{id}",
                args={"priority": "medium"},
                normalized_result={
                    "match_status": "no_match",
                    "no_match": True,
                    "summary": "No matching records were found for low-priority jobs.",
                    "entity": "job",
                    "preview_rows": [],
                },
                diagnostic_metadata={
                    "graph_tool_action": "approval_preview",
                    "reason": "approval_preview_no_records",
                },
            ),
            EvidenceLedgerEntry(
                id="ev-approval-medium-high",
                requirement_id="req-medium-high",
                source_type="approval",
                source_of_truth="operational_state",
                approval_id="approval-medium-high",
                normalized_result={"approval_status": "approved", "status": "approved"},
                diagnostic_metadata={
                    "approval_id": "approval-medium-high",
                    "locked_constraints": {"priority": "medium", "new_priority": "high"},
                    "preview_rows": [
                        {"job_id": "JOB-MED-A", "priority": "medium", "new_priority": "high"},
                    ],
                    "staged_graph_tool_calls": [
                        {"tool_name": "patch__jobs_{id}", "args": {"id": "JOB-MED-A", "priority": "high"}},
                    ],
                },
            ),
            EvidenceLedgerEntry(
                id="ev-api-medium-high",
                requirement_id="req-medium-high",
                source_type="api_tool",
                source_of_truth="operational_state",
                tool_name="patch__jobs_{id}",
                args={"id": "JOB-MED-A", "priority": "high"},
                normalized_result={"status_code": 200, "fields": {"job_id": "JOB-MED-A", "priority": "high"}},
                satisfies=["operational_state_tool_result"],
                diagnostic_metadata={"graph_authorized_execution": True},
            ),
        ]
    )
    adapter = PlannerOwnedGraphRuntimeAdapter(
        settings=_settings(),
        tool_selector=SimpleNamespace(),
        rag_pipeline=None,
        uuid_factory=lambda: "uuid",
        persist_plan=SimpleNamespace(),
        session_lookup=SimpleNamespace(),
    )
    result = PlannerOwnedGraphResult(
        state=state,
        node_order=["tool_execution_node", "response_document_node"],
        checkpoint_config={"configurable": {"thread_id": "phase10-session"}},
    )

    outputs = adapter._tool_outputs(result)
    context = adapter._graph_context(result=result, intent="update priorities", base_context=None)

    assert [output["evidence_ref"] for output in outputs] == ["ev-api-medium-high"]
    assert outputs[0]["approval_id"] == "approval-medium-high"
    assert context["no_op_mutations"] == [
        {
            "entity_type": "job",
            "selector_summary": "priority = low",
            "change_summary": "priority -> medium",
            "matched_count": 0,
            "changed_count": 0,
            "status": "not_changed",
            "reason": "no_matching_records",
        }
    ]


def test_graph_runtime_preserves_live_activity_history_before_clearing_transient_rows():
    state = build_initial_planner_owned_agent_graph_state(
        "Read jobs and their products.",
        tools_by_name={"get__machines_{id}": _tool()},
    )
    adapter = PlannerOwnedGraphRuntimeAdapter(
        settings=_settings(),
        tool_selector=SimpleNamespace(),
        rag_pipeline=None,
        uuid_factory=lambda: "uuid",
        persist_plan=SimpleNamespace(),
        session_lookup=SimpleNamespace(),
    )
    result = PlannerOwnedGraphResult(
        state=state,
        node_order=["semantic_intake_node", "response_document_node"],
        checkpoint_config={"configurable": {"thread_id": "phase10-session"}},
    )
    base_context = {
        "live_activity_steps": [
            {
                "id": "graph:000001:semantic_intake_node",
                "timestamp": 1770000001,
                "order": 1,
                "group": "planning",
                "label": "Understood request",
                "detail": "Reviewing your request and recent context",
                "state": "success",
                "unsafe_extra": {"tool_name": "get__jobs_{id}"},
            },
            {
                "id": "graph:000002:response_document_node",
                "timestamp": 1770000002,
                "order": 2,
                "group": "response",
                "label": "Rendering response",
                "detail": "Rendering the response",
                "state": "running",
            },
        ],
        "live_activity_revision": 12,
    }

    context = adapter._graph_context(result=result, intent="Read jobs and their products.", base_context=base_context)

    assert "live_activity_steps" not in context
    assert "live_activity_revision" not in context
    assert context["activity_graph_steps"] == [
        {
            "id": "graph:000001:semantic_intake_node",
            "timestamp": 1770000001,
            "order": 1,
            "group": "planning",
            "label": "Understood request",
            "detail": "Reviewing your request and recent context",
            "state": "success",
        },
        {
            "id": "graph:000002:response_document_node",
            "timestamp": 1770000002,
            "order": 2,
            "group": "response",
            "label": "Rendering response",
            "detail": "Rendering the response",
            "state": "running",
        },
    ]
    assert context["intent_contract"]["activity_graph_steps"] == context["activity_graph_steps"]
    assert context["planner_owned_agent_graph"]["activity_graph_steps"] == context["activity_graph_steps"]
    assert context["intent_contract"]["activity_caption_context"]["activity_graph_steps"] == context["activity_graph_steps"]


def test_graph_runtime_keeps_failed_tool_evidence_out_of_plan_steps_but_in_tool_outputs():
    state = build_initial_planner_owned_agent_graph_state(
        "Show machine status.",
        tools_by_name={},
    )
    state.evidence_ledger.evidence.append(
        EvidenceLedgerEntry(
            id="ev-failed-read",
            requirement_id=state.requirement_ledger.requirements[0].id,
            source_type="api_tool",
            source_of_truth="operational_state",
            tool_name="get__processes_{id}_steps",
            args={"id": "M-CNC-01", "fields": "status"},
            normalized_result={
                "status": "tool_failed",
                "error": {"code": "tool_error", "detail": "controlled timeout"},
            },
            diagnostic_metadata={"graph_authorized_execution": True, "reason": "tool_error"},
        )
    )
    state.response_document_context.evidence_refs = ["ev-failed-read"]
    adapter = PlannerOwnedGraphRuntimeAdapter(
        settings=_settings(),
        tool_selector=SimpleNamespace(),
        rag_pipeline=None,
        uuid_factory=lambda: "uuid",
        persist_plan=SimpleNamespace(),
        session_lookup=SimpleNamespace(),
    )
    result = PlannerOwnedGraphResult(
        state=state,
        node_order=["tool_execution_node", "response_document_node"],
        checkpoint_config={"configurable": {"thread_id": "failed-tool-session"}},
    )

    draft, tool_outputs = adapter._plan_artifacts(
        result,
        tools_by_name={
            "get__processes_{id}_steps": ToolInfo(
                name="get__processes_{id}_steps",
                description="Read process steps",
                endpoint="/processes/{id}/steps",
                method="GET",
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string", "pattern": "^PRC-[A-Za-z0-9-]+$"}},
                    "required": ["id"],
                },
                output_schema={"type": "object"},
                path_params=["id"],
                is_read_only=True,
                capability_tags=["process", "step", "read"],
            )
        },
    )

    assert tool_outputs[0]["status"] == "FAILED"
    assert tool_outputs[0]["tool_name"] == "get__processes_{id}_steps"
    assert draft.steps == []


def test_graph_runtime_keeps_invalid_successful_tool_args_out_of_plan_steps():
    state = build_initial_planner_owned_agent_graph_state(
        "Show machine status.",
        tools_by_name={},
    )
    state.evidence_ledger.evidence.append(
        EvidenceLedgerEntry(
            id="ev-invalid-read",
            requirement_id=state.requirement_ledger.requirements[0].id,
            source_type="api_tool",
            source_of_truth="operational_state",
            tool_name="get__job-steps_{id}_slots",
            args={"id": "M-CNC-01"},
            normalized_result={"rows": [{"slot_id": "slot-1"}]},
            satisfies=["operational_state_tool_result"],
            diagnostic_metadata={"graph_authorized_execution": True},
        )
    )
    state.response_document_context.evidence_refs = ["ev-invalid-read"]
    adapter = PlannerOwnedGraphRuntimeAdapter(
        settings=_settings(),
        tool_selector=SimpleNamespace(),
        rag_pipeline=None,
        uuid_factory=lambda: "uuid",
        persist_plan=SimpleNamespace(),
        session_lookup=SimpleNamespace(),
    )
    result = PlannerOwnedGraphResult(
        state=state,
        node_order=["tool_execution_node", "response_document_node"],
        checkpoint_config={"configurable": {"thread_id": "invalid-tool-session"}},
    )

    draft, tool_outputs = adapter._plan_artifacts(
        result,
        tools_by_name={
            "get__job-steps_{id}_slots": ToolInfo(
                name="get__job-steps_{id}_slots",
                description="Read job step slots",
                endpoint="/job-steps/{id}/slots",
                method="GET",
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string", "pattern": "^JOB-[A-Za-z0-9-]+$"}},
                    "required": ["id"],
                },
                output_schema={"type": "object"},
                path_params=["id"],
                is_read_only=True,
                capability_tags=["job", "slots", "read"],
            )
        },
    )

    assert tool_outputs[0]["status"] == "DONE"
    assert tool_outputs[0]["tool_name"] == "get__job-steps_{id}_slots"
    assert draft.steps == []
