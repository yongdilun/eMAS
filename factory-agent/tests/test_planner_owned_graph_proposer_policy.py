from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from factory_agent.config import get_settings
from factory_agent.graph.v2_agent_graph import PlannerOwnedAgentGraph, PlannerOwnedAgentGraphAdapters
from factory_agent.planning.tool_selector import ToolSelectionResult
from factory_agent.planning.v2_planner_proposer import (
    OfflineStructuredPlannerDecisionProposer,
    OpenAICompatibleQwenPlannerDecisionProposer,
    PlannerLLMConfigurationRequiredProposer,
    build_planner_decision_proposer,
    planner_proposer_diagnostics_satisfy_real_llm_release_proof,
)
from factory_agent.schemas import ToolInfo


def _settings(**overrides: Any):
    base = replace(
        get_settings(),
        graph_checkpoint_backend="off",
        tool_selector_backend="retrieval",
        tool_selector_top_k=5,
        tool_selector_candidate_pool=5,
        tool_selector_reranker_enabled=False,
        planner_openai_base_url=None,
        openai_api_key=None,
        allow_offline_planner_proposer=False,
        planner_model="Qwen-policy-test",
    )
    return replace(base, **overrides)


def _machine_status_tool() -> ToolInfo:
    return ToolInfo(
        name="get__machines_{id}",
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
    async def select_tools(self, **kwargs: Any) -> ToolSelectionResult:
        return ToolSelectionResult(["get__machines_{id}"], backend_used="retrieval", llm_calls=0)


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
        _ = settings, extra_headers
        self.calls.append({"tool": tool.name, "args": dict(args), "idempotency_key": idempotency_key})
        return {
            "ok": True,
            "http_status": 200,
            "latency_ms": 1,
            "body": {"machine_id": args.get("id"), "status": "running"},
            "infrastructure_error": False,
        }


class DecisionAwareFakePlannerModel:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        payload = json.loads(prompt)
        kind = payload["decision_state"]["requested_decision_kind"]
        if kind == "retrieve_tools":
            return json.dumps(
                {
                    "decision": {
                        "decision_kind": "retrieve_tools",
                        "reason": "Use bounded retrieval for the current requirement.",
                    }
                }
            )
        return json.dumps(
            {
                "decision": {
                    "decision_kind": "choose_tool",
                    "selected_tool_name": "get__machines_{id}",
                    "reason": "Use the hydrated read tool.",
                }
            }
        )


def _graph(settings, executor: RecordingExecutor) -> PlannerOwnedAgentGraph:
    return PlannerOwnedAgentGraph(
        settings=settings,
        adapters=PlannerOwnedAgentGraphAdapters(
            settings=settings,
            tools_by_name={"get__machines_{id}": _machine_status_tool()},
            tool_selector=RecordingSelector(),  # type: ignore[arg-type]
            http_executor=executor,
        ),
        checkpointer=None,
    )


def test_phase10_6_get_settings_reads_explicit_offline_flag(monkeypatch):
    monkeypatch.setenv("FACTORY_AGENT_ALLOW_OFFLINE_PLANNER_PROPOSER", "1")

    assert get_settings().allow_offline_planner_proposer is True


@pytest.mark.asyncio
async def test_phase10_6_missing_planner_llm_config_fails_closed_before_tool_execution():
    settings = _settings()
    executor = RecordingExecutor()
    graph = _graph(settings, executor)

    result = await graph.run(
        "Show machine M-POLICY-77 status.",
        session_context={"session_id": "phase10-6-missing-config"},
    )

    rejected = result.state.execution_trace.planner.diagnostics["planner_decision_proposer"]["rejected"]
    assert isinstance(build_planner_decision_proposer(settings), PlannerLLMConfigurationRequiredProposer)
    assert rejected[0]["adapter"] == PlannerLLMConfigurationRequiredProposer.adapter_name
    assert rejected[0]["fail_closed"] is True
    assert rejected[0]["tool_execution_allowed"] is False
    assert rejected[0]["diagnostics"]["configuration_missing"] is True
    assert "FACTORY_AGENT_ALLOW_OFFLINE_PLANNER_PROPOSER" in rejected[0]["reason"]
    assert executor.calls == []
    assert result.state.evidence_ledger.evidence == []


@pytest.mark.asyncio
async def test_phase10_6_explicit_offline_flag_enables_offline_proposer_and_traces_contract_mode():
    settings = _settings(allow_offline_planner_proposer=True)
    executor = RecordingExecutor()
    graph = _graph(settings, executor)

    result = await graph.run(
        "Show machine M-POLICY-77 status.",
        session_context={"session_id": "phase10-6-offline-allowed"},
    )

    accepted = result.state.execution_trace.planner.diagnostics["planner_decision_proposer"]["accepted"]
    assert isinstance(build_planner_decision_proposer(settings), OfflineStructuredPlannerDecisionProposer)
    assert executor.calls and executor.calls[0]["tool"] == "get__machines_{id}"
    assert accepted[0]["adapter"] == OfflineStructuredPlannerDecisionProposer.adapter_name
    assert accepted[0]["offline_contract_mode"] is True
    assert accepted[0]["real_llm_mode"] is False
    assert accepted[0]["llm_invoked"] is False
    assert planner_proposer_diagnostics_satisfy_real_llm_release_proof(accepted[0]) is False


@pytest.mark.asyncio
async def test_phase10_6_configured_local_openai_base_url_selects_qwen_adapter_and_traces_metadata(monkeypatch):
    import factory_agent.planning.v2_planner_proposer as proposer_module

    settings = _settings(planner_openai_base_url="http://localhost:11434/v1")
    executor = RecordingExecutor()
    fake_model = DecisionAwareFakePlannerModel()
    monkeypatch.setattr(
        proposer_module,
        "build_planner_chat_model",
        lambda _settings, *, json_mode: fake_model,
    )
    graph = _graph(settings, executor)

    result = await graph.run(
        "Show machine M-POLICY-77 status.",
        session_context={"session_id": "phase10-6-local-qwen"},
    )

    accepted = result.state.execution_trace.planner.diagnostics["planner_decision_proposer"]["accepted"]
    assert isinstance(build_planner_decision_proposer(settings), OpenAICompatibleQwenPlannerDecisionProposer)
    assert executor.calls and executor.calls[0]["tool"] == "get__machines_{id}"
    assert fake_model.prompts
    assert accepted[0]["adapter"] == OpenAICompatibleQwenPlannerDecisionProposer.adapter_name
    assert accepted[0]["llm_invoked"] is True
    assert accepted[0]["offline_contract_mode"] is False
    assert accepted[0]["real_llm_mode"] is True
    assert accepted[0]["model_name"] == "Qwen-policy-test"
    assert accepted[0]["base_url_type"] == "local"
    assert accepted[0]["base_url_configured"] is True
    assert planner_proposer_diagnostics_satisfy_real_llm_release_proof(accepted[0]) is True


def test_phase10_6_release_policy_rejects_offline_diagnostics_as_real_llm_planner_proof():
    offline_diagnostics = {
        "adapter": OfflineStructuredPlannerDecisionProposer.adapter_name,
        "llm_invoked": False,
        "offline_contract_mode": True,
        "real_llm_mode": False,
        "model_name": None,
        "base_url_type": None,
    }
    qwen_diagnostics = {
        "adapter": OpenAICompatibleQwenPlannerDecisionProposer.adapter_name,
        "llm_invoked": True,
        "offline_contract_mode": False,
        "real_llm_mode": True,
        "openai_compatible_planner_adapter": True,
        "model_name": "Qwen-policy-test",
        "base_url_type": "local",
    }

    assert planner_proposer_diagnostics_satisfy_real_llm_release_proof(offline_diagnostics) is False
    assert (
        planner_proposer_diagnostics_satisfy_real_llm_release_proof(
            {"planner_proposer": offline_diagnostics}
        )
        is False
    )
    assert planner_proposer_diagnostics_satisfy_real_llm_release_proof(qwen_diagnostics) is True
