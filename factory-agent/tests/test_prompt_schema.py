import json

import main  # noqa: F401

from factory_agent.planning.prompting import get_plan_draft_json_schema
from factory_agent.observability.telemetry import log_llm_prompt, log_llm_prompt_skipped
from factory_agent.llm.prompt_contracts import (
    PROMPT_CONTRACTS,
    prompt_contracts_by_name,
    validate_prompt_contract,
)


def test_plan_draft_json_schema_has_expected_shape():
    schema = get_plan_draft_json_schema()
    assert isinstance(schema, dict)
    assert "properties" in schema
    assert "steps" in schema["properties"]
    assert "plan_explanation" in schema["properties"]
    assert "risk_summary" in schema["properties"]


def test_log_llm_prompt_emits_structured_log(caplog):
    with caplog.at_level("INFO"):
        log_llm_prompt(
            component="planner",
            backend="langchain",
            model="test-model",
            prompt="Prompt body here",
            metadata={"attempt": "structured_output", "session_id": "sess-1"},
        )

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload["event"] == "llm_prompt"
    assert payload["component"] == "planner"
    assert payload["backend"] == "langchain"
    assert payload["model"] == "test-model"
    assert payload["prompt"] == "Prompt body here"
    assert payload["attempt"] == "structured_output"
    assert payload["session_id"] == "sess-1"


def test_log_llm_prompt_skipped_emits_structured_log(caplog):
    with caplog.at_level("INFO"):
        log_llm_prompt_skipped(
            component="planner",
            backend="deterministic",
            reason="summary_backend=deterministic",
            metadata={"intent": "Check machine 5 status", "scoped_tool_count": 2},
        )

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload["event"] == "llm_prompt_skipped"
    assert payload["component"] == "planner"
    assert payload["backend"] == "deterministic"
    assert payload["reason"] == "summary_backend=deterministic"
    assert payload["intent"] == "Check machine 5 status"
    assert payload["scoped_tool_count"] == 2


def test_prompt_contract_registry_has_required_metadata():
    assert PROMPT_CONTRACTS
    names = [contract.name for contract in PROMPT_CONTRACTS]
    assert len(names) == len(set(names))

    for contract in PROMPT_CONTRACTS:
        validate_prompt_contract(contract)
        assert contract.version.startswith("v")
        assert contract.owner_module.startswith("factory_agent.")
        assert contract.status in {"active", "optional", "legacy", "retired"}

    contracts = prompt_contracts_by_name()
    for required in {
        "planner_decision_v2",
        "rag_answer_v1",
        "rag_answer_repair_v1",
        "tool_selector_rerank_v1",
        "semantic_intake_v1",
    }:
        assert required in contracts

