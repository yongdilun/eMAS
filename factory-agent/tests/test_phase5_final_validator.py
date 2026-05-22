from __future__ import annotations

from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage

from factory_agent.config import get_settings
from factory_agent.graph.checkpointing import clear_graph_checkpointer_cache
from factory_agent.graph.errors import LangGraphPlannerApprovalRequired
from factory_agent.graph.nodes.tool_pipeline import commit_node_impl
from factory_agent.graph.nodes.validate import make_final_validator_node, make_validate_node
from factory_agent.graph.nodes.tool_pipeline import route_after_bundle, route_after_commit, route_after_validate
from factory_agent.graph.planner_graph import LangGraphPlanner
from factory_agent.schemas import AgentPlanOutput, AgentPlanStep, PlanDraft, PlanStepDraft
from factory_agent.schemas import ToolInfo
from tests.support.operation_assertions import assert_audit_rows_match
from tests.support.operation_assertions import assert_final_state_matches_oracle
from tests.support.operation_assertions import assert_timeline_contains_chain
from tests.support.stateful_oracle_harness import StatefulOracleHarness

import json
import uuid


def _validated_state(**overrides):
    state = {
        "plan_blueprint": None,
        "validated_plan": PlanDraft(
            plan_explanation="Ready.",
            risk_summary="Review writes.",
            steps=[
                PlanStepDraft(
                    step_index=0,
                    tool_name="post__jobs",
                    args={"machine_id": "M-001"},
                    depends_on=[],
                )
            ],
        ),
        "status": "completed",
        "staged_writes": [
            {
                "intent_id": "i1",
                "decision_id": "d1",
                "tool_call_id": "tc1",
                "tool_name": "post__jobs",
                "args": {"machine_id": "M-001"},
                "output_ref": "$ref:job",
                "idempotency_key": "idem",
                "status": "staged",
            }
        ],
        "decisions": [{"risk_level": "high_risk"}],
        "validation_results": [],
        "tool_outputs": [],
        "repair_attempts": 0,
    }
    state.update(overrides)
    return state


def _jobs_list_tool() -> ToolInfo:
    return ToolInfo(
        name="get__jobs",
        description="List jobs",
        endpoint="/jobs",
        method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "job_id": {"type": "string"},
                            "priority": {"type": "string"},
                        },
                    },
                }
            },
        },
        query_params=["priority"],
        param_sources={"priority": "query"},
        is_read_only=True,
    )


def _job_update_tool() -> ToolInfo:
    return ToolInfo(
        name="put__jobs_{id}",
        description="Update a job",
        endpoint="/jobs/{id}",
        method="PUT",
        input_schema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            },
        },
        path_params=["id"],
        body_fields=["priority"],
        param_sources={"id": "path", "priority": "body"},
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
    )


def _job_create_tool() -> ToolInfo:
    return ToolInfo(
        name="post__jobs",
        description="Create a job",
        endpoint="/jobs",
        method="POST",
        input_schema={
            "type": "object",
            "required": ["product_id", "quantity_total"],
            "properties": {
                "product_id": {"type": "string"},
                "quantity_total": {"type": "integer"},
            },
        },
        body_fields=["product_id", "quantity_total"],
        required_body_fields=["product_id", "quantity_total"],
        param_sources={"product_id": "body", "quantity_total": "body"},
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
    )


def _job_delete_tool() -> ToolInfo:
    return ToolInfo(
        name="delete__jobs_{id}",
        description="Delete a job",
        endpoint="/jobs/{id}",
        method="DELETE",
        input_schema={
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string"},
            },
        },
        path_params=["id"],
        param_sources={"id": "path"},
        is_read_only=False,
        requires_approval=True,
        side_effect_level="HIGH",
    )


def test_validate_node_preserves_bulk_staged_steps_beyond_default_limit():
    settings = replace(get_settings(), max_plan_steps=3)
    node = make_validate_node(settings)
    steps = [
        AgentPlanStep(tool_name="put__jobs_{id}", args={"id": f"JOB-{i:03d}", "priority": "high"})
        for i in range(5)
    ]

    out = node(
        {
            "plan_blueprint": AgentPlanOutput(
                plan_explanation="Stage every selected row-level write.",
                risk_summary="Bulk job priority update requires approval.",
                steps=steps,
            ),
            "staged_writes": [
                {
                    "tool_name": "put__jobs_{id}",
                    "args": {"id": f"JOB-{i:03d}", "priority": "high"},
                    "status": "staged",
                }
                for i in range(5)
            ],
            "scoped_tools": [_job_update_tool()],
            "context": {},
            "original_query": "change all medium priority jobs to high",
        }
    )

    assert out["status"] == "completed"
    assert len(out["validated_plan"].steps) == 5
    assert [step.args["id"] for step in out["validated_plan"].steps] == [f"JOB-{i:03d}" for i in range(5)]


def test_final_validator_appends_commit_operation_outputs_for_final_summary():
    settings = get_settings()
    node = make_final_validator_node(settings)

    out = node(
        {
            "working_intents": [{"intent_id": "i1", "status": "in_progress"}],
            "intent_cursor": 0,
            "staged_writes": [
                {
                    "tool_name": "put__jobs_{id}",
                    "tool_call_id": "tc-1",
                    "args": {"id": "JOB-1", "priority": "high"},
                    "idempotency_key": "idem-1",
                    "output_ref": "$ref:job-1",
                    "status": "staged",
                },
                {
                    "tool_name": "put__jobs_{id}",
                    "tool_call_id": "tc-2",
                    "args": {"id": "JOB-2", "priority": "high"},
                    "idempotency_key": "idem-2",
                    "output_ref": "$ref:job-2",
                    "status": "staged",
                },
            ],
            "last_commit_result": {
                "ok": True,
                "http_status": 200,
                "body": {
                    "success": True,
                    "data": {
                        "committed": True,
                        "operations": [
                            {
                                "index": 1,
                                "tool_name": "put__jobs_{id}",
                                "status": "committed",
                                "primary_id": "JOB-2",
                                "data": {"job_id": "JOB-2"},
                            },
                            {
                                "index": 0,
                                "tool_name": "put__jobs_{id}",
                                "status": "committed",
                                "primary_id": "JOB-1",
                                "data": {"job_id": "JOB-1"},
                            },
                        ],
                    },
                },
            },
            "repair_attempts": 0,
        }
    )

    assert out["status"] == "completed"
    assert out["next_route"] == "end"
    rows = out["tool_outputs"]
    assert [row["args"]["id"] for row in rows] == ["JOB-1", "JOB-2"]
    assert all(row["tool_name"] == "put__jobs_{id}" for row in rows)
    assert all(row["status"] == "DONE" for row in rows)
    assert [row["result"]["data"]["job_id"] for row in rows] == ["JOB-1", "JOB-2"]
    assert [row["result"]["data"]["priority"] for row in rows] == ["high", "high"]


def test_final_validator_commit_409_with_hard_constraint_requests_clarification():
    settings = get_settings()
    node = make_final_validator_node(settings)
    out = node(
        {
            "current_intent": {
                "intent_id": "i1",
                "explicit_constraints": [{"field": "machine_id", "value": "M-001", "strength": "hard"}],
            },
            "last_commit_result": {"ok": False, "http_status": 409, "body": {"error": "conflict"}},
            "tool_outputs": [{"x": 1}],
            "repair_attempts": 0,
        }
    )
    assert out["status"] == "awaiting_clarification"
    assert out.get("clarification")


def test_final_validator_commit_business_failure_routes_repair_with_truncation_cursor():
    settings = get_settings()
    node = make_final_validator_node(settings)
    out = node(
        {
            "current_intent": {"intent_id": "i1", "explicit_constraints": []},
            "last_commit_result": {"ok": False, "http_status": 409, "body": {"error": "conflict"}},
            "tool_outputs": [{"a": 1}, {"a": 2}, {"a": 3}],
            "repair_attempts": 0,
        }
    )
    assert out["next_route"] == "continue_planner"
    assert out["repair_attempts"] == 1
    assert out["tool_outputs_truncated_at"] == 3
    assert out["staged_writes"] == [{"__replace__": True, "value": []}]


def test_final_validator_commit_infra_failure_is_fatal():
    settings = get_settings()
    node = make_final_validator_node(settings)
    out = node(
        {
            "current_intent": {"intent_id": "i1", "explicit_constraints": []},
            "last_commit_result": {"ok": False, "infrastructure": True, "error": "timeout"},
            "repair_attempts": 0,
        }
    )
    assert out["next_route"] == "fatal_end"
    assert str(out.get("fatal_system_error") or "").startswith("FATAL_SYSTEM_ERROR")


def test_write_flow_routes_dry_run_before_commit_or_approval(monkeypatch):
    settings = get_settings()
    node = make_final_validator_node(settings)

    def fake_validate(state):
        return {
            "validated_plan": state["validated_plan"],
            "intent_contract": {"backend": "langgraph", "steps": []},
            "status": "completed",
            "validation_results": [{"ok": True}],
        }

    monkeypatch.setattr("factory_agent.graph.nodes.validate.make_validate_node", lambda settings: fake_validate)
    node = make_final_validator_node(settings)

    out = node(_validated_state(bundle_dry_run_result=None))
    assert out["next_route"] == "bundle_dry_run"
    assert "approval_requests" not in out
    assert route_after_validate(out) == "bundle_dry_run"
    assert route_after_bundle({"bundle_dry_run_result": {"ok": True}}) == "final_validator"


def test_dry_run_business_failure_routes_to_repair_without_approval(monkeypatch):
    settings = get_settings()
    node = make_final_validator_node(settings)

    out = node(
        _validated_state(
            bundle_dry_run_result={
                "ok": False,
                "http_status": 409,
                "body": {"error": "machine conflict"},
            }
        )
    )

    assert out["next_route"] == "continue_planner"
    assert out["failed_strategies"][0]["phase"] == "bundle_dry_run"
    assert out["staged_writes"] == [{"__replace__": True, "value": []}]
    assert "approval_requests" not in out


def test_write_flow_approves_only_after_successful_dry_run(monkeypatch):
    settings = get_settings()

    def fake_validate(state):
        return {
            "validated_plan": state["validated_plan"],
            "intent_contract": {"backend": "langgraph", "steps": []},
            "status": "completed",
            "validation_results": [{"ok": True}],
        }

    monkeypatch.setattr("factory_agent.graph.nodes.validate.make_validate_node", lambda settings: fake_validate)
    monkeypatch.setattr("factory_agent.graph.nodes.validate.interrupt", lambda payload: {"approved": True})
    node = make_final_validator_node(settings)

    out = node(_validated_state(bundle_dry_run_result={"ok": True, "http_status": 200, "body": {}}))
    assert out["next_route"] == "commit"
    assert out["approval_requests"][0]["status"] == "approved"
    assert route_after_validate(out) == "commit"


def test_commit_business_failure_routes_back_to_final_validator():
    assert route_after_commit({"last_commit_result": {"ok": False, "http_status": 409}}) == "final_validator"


@pytest.mark.asyncio
async def test_commit_node_uses_single_bundle_endpoint_after_preconditions(monkeypatch):
    settings = get_settings()
    calls = []

    class FakeResponse:
        status_code = 200
        content = b'{"success":true}'
        text = '{"success":true}'

        def json(self):
            return {"success": True}

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json=None, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.httpx.AsyncClient", FakeClient)

    out = await commit_node_impl(
        _validated_state(
            bundle_dry_run_result={"ok": True, "http_status": 200},
            validation_results=[{"ok": True, "phase": "plan_validator"}],
            approval_requests=[{"status": "approved"}],
        ),
        settings=settings,
    )

    assert out["last_commit_result"]["ok"] is True
    assert len(calls) == 1
    assert calls[0]["url"].endswith(settings.agent_transaction_commit_path)
    assert len(calls[0]["json"]["staged_writes"]) == 1
    assert calls[0]["json"]["bundle_idempotency_key"]
    assert calls[0]["headers"]["Idempotency-Key"] == calls[0]["json"]["bundle_idempotency_key"]


@pytest.mark.asyncio
async def test_commit_node_refuses_to_call_backend_before_dry_run_validation_and_approval(monkeypatch):
    settings = get_settings()

    class FailClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            raise AssertionError("commit backend must not be called before preconditions")

    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.httpx.AsyncClient", FailClient)

    base = _validated_state()
    out = await commit_node_impl(base, settings=settings)
    assert out["last_commit_result"]["http_status"] == 428
    assert "bundle_dry_run_required" in out["last_commit_result"]["error"]

    out = await commit_node_impl(
        _validated_state(bundle_dry_run_result={"ok": True}),
        settings=settings,
    )
    assert out["last_commit_result"]["http_status"] == 428
    assert "final_validation_required" in out["last_commit_result"]["error"]

    out = await commit_node_impl(
        _validated_state(
            bundle_dry_run_result={"ok": True},
            validation_results=[{"ok": True}],
        ),
        settings=settings,
    )
    assert out["last_commit_result"]["http_status"] == 428
    assert "approval_required" in out["last_commit_result"]["error"]


@pytest.mark.asyncio
async def test_approval_interrupt_resume_commits_from_checkpoint_without_replanning(monkeypatch):
    session_id = f"phase5-{uuid.uuid4()}"
    settings = replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        graph_checkpoint_backend="memory",
        go_api_base_url="http://testserver",
        max_plan_steps=8,
    )
    write_tool = ToolInfo(
        name="post__jobs",
        description="create job",
        endpoint="/jobs",
        method="POST",
        input_schema={"type": "object"},
        is_read_only=False,
        requires_approval=True,
    )
    planner_prompts: list[str] = []
    events: list[str] = []

    class FakeModel:
        async def ainvoke(self, prompt: str):
            planner_prompts.append(prompt)
            marker = "Current intent JSON: "
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\nUser query:", start)
            intent_id = json.loads(prompt[start:end])["intent_id"]
            if len(planner_prompts) == 1:
                payload = {
                    "intent_id": intent_id,
                    "kind": "domain_tool",
                    "tool_calls": [
                        {
                            "tool_name": "post__jobs",
                            "args": {"product_id": "P-001", "quantity_total": 10},
                            "output_ref": "$ref:job",
                        }
                    ],
                    "decision_summary": "Stage the requested job.",
                    "risk_level": "write_dry_run",
                }
            else:
                payload = {
                    "intent_id": intent_id,
                    "kind": "intent_completed",
                    "tool_calls": [],
                    "decision_summary": "The staged job satisfies the request.",
                    "risk_level": "write_commit",
                }
            return AIMessage(content=json.dumps(payload))

    async def fake_dry_run(state, *, settings):
        events.append("bundle_dry_run")
        assert state["staged_writes"][0]["tool_name"] == "post__jobs"
        return {
            "bundle_dry_run_result": {"ok": True, "http_status": 200, "body": {"validated": True}},
            "completed_actions": [{"phase": "bundle_dry_run", "status": "ok"}],
        }

    async def fake_commit(state, *, settings):
        events.append("commit")
        assert state["approval_requests"][0]["status"] == "approved"
        return {
            "last_commit_result": {"ok": True, "http_status": 200, "body": {"committed": True}},
            "completed_actions": [{"phase": "commit", "status": "ok"}],
        }

    monkeypatch.setattr(
        "factory_agent.graph.nodes.planner_loop.build_planner_chat_model",
        lambda settings, json_mode=True: FakeModel(),
    )
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.bundle_dry_run_node", fake_dry_run)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.commit_node_impl", fake_commit)

    planner = LangGraphPlanner(settings)
    with pytest.raises(LangGraphPlannerApprovalRequired) as exc:
        await planner.generate(
            intent="Create the requested test job",
            scoped_tools=[write_tool],
            context={"session_id": session_id},
        )

    assert exc.value.payload["kind"] == "approval_required"
    assert events == ["bundle_dry_run"]
    assert len(planner_prompts) == 1

    draft, contract, _outputs = await planner.resume_after_approval(session_id=session_id, approved=True)

    assert events == ["bundle_dry_run", "commit"]
    assert len(planner_prompts) == 1
    assert draft.steps[0].tool_name == "post__jobs"
    assert contract["backend"] == "langgraph"


@pytest.mark.asyncio
async def test_bulk_low_priority_jobs_are_selected_by_filter_and_staged_as_one_approval_bundle(monkeypatch):
    session_id = f"bulk-priority-{uuid.uuid4()}"
    settings = replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        graph_checkpoint_backend="memory",
        max_foreach_items=50,
    )
    read_calls: list[dict[str, object]] = []
    dry_run_counts: list[int] = []

    def fail_model(*args, **kwargs):
        raise AssertionError("bulk priority repair should not call the planner model")

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key):
        read_calls.append({"tool_name": tool.name, "args": dict(args)})
        return {
            "ok": True,
            "http_status": 200,
            "body": {
                "data": [
                    {"job_id": "JOB-SEED-005", "priority": "low"},
                    {"job_id": "JOB-SEED-009", "priority": "low"},
                    {"job_id": "JOB-SEED-012", "priority": "low"},
                ]
            },
            "latency_ms": 1,
            "infrastructure_error": False,
        }

    async def fake_dry_run(state, *, settings):
        staged = state["staged_writes"]
        dry_run_counts.append(len(staged))
        assert [item["args"]["id"] for item in staged] == [
            "JOB-SEED-005",
            "JOB-SEED-009",
            "JOB-SEED-012",
        ]
        assert all(item["tool_name"] == "put__jobs_{id}" for item in staged)
        assert all(item["args"]["priority"] == "high" for item in staged)
        return {"bundle_dry_run_result": {"ok": True, "http_status": 200, "body": {"validated": True}}}

    monkeypatch.setattr("factory_agent.graph.nodes.planner_loop.build_planner_chat_model", fail_model)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.execute_tool_http", fake_execute_tool_http)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.bundle_dry_run_node", fake_dry_run)

    planner = LangGraphPlanner(settings)
    with pytest.raises(LangGraphPlannerApprovalRequired) as exc:
        await planner.generate(
            intent="change all low priority jobs to high priority",
            scoped_tools=[_jobs_list_tool(), _job_update_tool()],
            context={"session_id": session_id},
        )

    assert read_calls == [{"tool_name": "get__jobs", "args": {"priority": "low"}}]
    assert dry_run_counts == [3]
    payload = exc.value.payload
    assert payload["count"] == 3
    assert "JOB-SEED-005" in payload["summary"] and "priority" in payload["summary"].lower()
    assert [item["args"] for item in payload["preview"]] == [
        {"id": "JOB-SEED-005", "priority": "high"},
        {"id": "JOB-SEED-009", "priority": "high"},
        {"id": "JOB-SEED-012", "priority": "high"},
    ]


@pytest.mark.asyncio
async def test_complete_create_intents_are_collected_into_one_bundle_approval(monkeypatch):
    session_id = f"multi-create-{uuid.uuid4()}"
    settings = replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        graph_checkpoint_backend="memory",
    )
    dry_run_staged: list[list[dict[str, object]]] = []

    def fail_model(*args, **kwargs):
        raise AssertionError("complete create repairs should not call the planner model")

    async def fake_dry_run(state, *, settings):
        staged = list(state["staged_writes"])
        dry_run_staged.append(staged)
        return {"bundle_dry_run_result": {"ok": True, "http_status": 200, "body": {"validated": True}}}

    monkeypatch.setattr("factory_agent.graph.nodes.planner_loop.build_planner_chat_model", fail_model)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.bundle_dry_run_node", fake_dry_run)

    planner = LangGraphPlanner(settings)
    with pytest.raises(LangGraphPlannerApprovalRequired) as exc:
        await planner.generate(
            intent="create job for product P-005 quantity 2 and create job for product P-006 quantity 3",
            scoped_tools=[_job_create_tool()],
            context={"session_id": session_id},
        )

    assert len(dry_run_staged) == 1
    staged = dry_run_staged[0]
    assert len(staged) == 2
    assert [item["args"] for item in staged] == [
        {"product_id": "P-005", "quantity_total": 2},
        {"product_id": "P-006", "quantity_total": 3},
    ]
    assert exc.value.payload["count"] == 2


@pytest.mark.asyncio
async def test_bulk_low_priority_jobs_are_deleted_as_one_approval_bundle(monkeypatch):
    session_id = f"bulk-delete-{uuid.uuid4()}"
    settings = replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        graph_checkpoint_backend="memory",
        max_foreach_items=50,
    )
    read_calls: list[dict[str, object]] = []
    dry_run_staged: list[list[dict[str, object]]] = []

    def fail_model(*args, **kwargs):
        raise AssertionError("bulk delete repair should not call the planner model")

    async def fake_execute_tool_http(settings, tool, args, *, idempotency_key):
        read_calls.append({"tool_name": tool.name, "args": dict(args)})
        return {
            "ok": True,
            "http_status": 200,
            "body": {
                "data": [
                    {"job_id": "JOB-SEED-005", "priority": "low"},
                    {"job_id": "JOB-SEED-009", "priority": "low"},
                ]
            },
            "latency_ms": 1,
            "infrastructure_error": False,
        }

    async def fake_dry_run(state, *, settings):
        dry_run_staged.append(list(state["staged_writes"]))
        return {"bundle_dry_run_result": {"ok": True, "http_status": 200, "body": {"validated": True}}}

    monkeypatch.setattr("factory_agent.graph.nodes.planner_loop.build_planner_chat_model", fail_model)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.execute_tool_http", fake_execute_tool_http)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.bundle_dry_run_node", fake_dry_run)

    planner = LangGraphPlanner(settings)
    with pytest.raises(LangGraphPlannerApprovalRequired) as exc:
        await planner.generate(
            intent="delete all low priority jobs",
            scoped_tools=[_jobs_list_tool(), _job_delete_tool()],
            context={"session_id": session_id},
        )

    assert read_calls == [{"tool_name": "get__jobs", "args": {"priority": "low"}}]
    assert len(dry_run_staged) == 1
    assert [item["tool_name"] for item in dry_run_staged[0]] == ["delete__jobs_{id}", "delete__jobs_{id}"]
    assert [item["args"] for item in dry_run_staged[0]] == [{"id": "JOB-SEED-005"}, {"id": "JOB-SEED-009"}]
    assert exc.value.payload["count"] == 2


@pytest.mark.asyncio
async def test_two_step_priority_cascade_requires_second_langgraph_approval(monkeypatch):
    session_id = f"real-graph-cascade-{uuid.uuid4()}"
    settings = replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        graph_checkpoint_backend="memory",
        max_foreach_items=50,
    )
    harness = StatefulOracleHarness.from_oracle_id("SO-001", session_id=session_id)
    harness.start_operation(intent_count=2)

    def fail_model(*args, **kwargs):
        raise AssertionError("priority cascade regression must use deterministic LangGraph mechanics, not an LLM")

    clear_graph_checkpointer_cache()
    monkeypatch.setattr("factory_agent.graph.nodes.planner_loop.build_planner_chat_model", fail_model)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.execute_tool_http", harness.execute_tool_http)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.bundle_dry_run_node", harness.bundle_dry_run_node)
    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.commit_node_impl", harness.commit_node)

    planner = LangGraphPlanner(settings)
    prompt = "change all medium priority job to high then change all high priority job to medium"
    with pytest.raises(LangGraphPlannerApprovalRequired) as first:
        await planner.generate(
            intent=prompt,
            scoped_tools=[_jobs_list_tool(), _job_update_tool()],
            context={"session_id": session_id},
        )

    assert first.value.payload["bundle_ui"]["previous_priority"] == "medium"
    assert first.value.payload["bundle_ui"]["new_priority"] == "high"
    assert [item["args"] for item in harness.dry_runs[0]["staged_writes"]] == [
        {"id": "JOB-SO001-MED-01", "priority": "high"},
        {"id": "JOB-SO001-MED-02", "priority": "high"},
    ]

    with pytest.raises(LangGraphPlannerApprovalRequired) as second:
        await planner.resume_after_approval(session_id=session_id, approved=True)

    assert harness.commit_count_by_approval["approval-so-001-1"] == 1
    assert second.value.payload["bundle_ui"]["previous_priority"] == "high"
    assert second.value.payload["bundle_ui"]["new_priority"] == "medium"
    assert [item["args"] for item in harness.dry_runs[1]["staged_writes"]] == [
        {"id": "JOB-SO001-HIGH-01", "priority": "medium"},
        {"id": "JOB-SO001-HIGH-02", "priority": "medium"},
    ]

    draft, contract, _outputs = await planner.resume_after_approval(session_id=session_id, approved=True)

    assert harness.commit_count_by_approval["approval-so-001-2"] == 1
    assert [call["args"] for call in harness.read_requests if call["tool_name"] == "get__jobs"] == [
        {"priority": "medium"},
        {"priority": "high"},
    ]
    assert draft.steps[-1].tool_name == "put__jobs_{id}"
    assert contract["backend"] == "langgraph"
    assert_final_state_matches_oracle(harness, harness.oracle)
    assert_audit_rows_match(harness, harness.oracle["expected_audit_rows"])
    assert_timeline_contains_chain(harness, harness.oracle["expected_timeline"])


@pytest.mark.asyncio
async def test_incomplete_create_intent_is_not_added_to_bundle(monkeypatch):
    session_id = f"incomplete-create-{uuid.uuid4()}"
    settings = replace(
        get_settings(),
        openai_api_key="test-key",
        planner_openai_base_url=None,
        graph_checkpoint_backend="memory",
    )
    dry_run_counts: list[int] = []

    async def fake_dry_run(state, *, settings):
        dry_run_counts.append(len(state["staged_writes"]))
        return {"bundle_dry_run_result": {"ok": True, "http_status": 200, "body": {"validated": True}}}

    monkeypatch.setattr("factory_agent.graph.nodes.tool_pipeline.bundle_dry_run_node", fake_dry_run)

    planner = LangGraphPlanner(settings)
    with pytest.raises(LangGraphPlannerApprovalRequired) as exc:
        await planner.generate(
            intent="create job for product P-005 quantity 2 and create job for product P-006",
            scoped_tools=[_job_create_tool()],
            context={"session_id": session_id},
        )

    assert dry_run_counts == [1]
    assert exc.value.payload["count"] == 1
    assert exc.value.payload["preview"][0]["args"] == {"product_id": "P-005", "quantity_total": 2}
