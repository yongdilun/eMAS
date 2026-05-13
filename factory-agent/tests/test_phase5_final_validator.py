from __future__ import annotations

from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage

from factory_agent.config import get_settings
from factory_agent.graph.errors import LangGraphPlannerApprovalRequired
from factory_agent.graph.nodes.tool_pipeline import commit_node_impl
from factory_agent.graph.nodes.validate import make_final_validator_node
from factory_agent.graph.nodes.tool_pipeline import route_after_bundle, route_after_commit, route_after_validate
from factory_agent.graph.planner_graph import LangGraphPlanner
from factory_agent.schemas import PlanDraft, PlanStepDraft
from factory_agent.schemas import ToolInfo

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
            intent="Create a job for product P-001 quantity 10",
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
