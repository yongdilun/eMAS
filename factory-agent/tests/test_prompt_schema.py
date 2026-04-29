import json

import main  # noqa: F401

from agent.prompting import get_plan_draft_json_schema
from agent.telemetry import log_llm_prompt, log_llm_prompt_skipped


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
            backend="legacy",
            reason="planner_backend=legacy",
            metadata={"intent": "Check machine 5 status", "scoped_tool_count": 2},
        )

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload["event"] == "llm_prompt_skipped"
    assert payload["component"] == "planner"
    assert payload["backend"] == "legacy"
    assert payload["reason"] == "planner_backend=legacy"
    assert payload["intent"] == "Check machine 5 status"
    assert payload["scoped_tool_count"] == 2
