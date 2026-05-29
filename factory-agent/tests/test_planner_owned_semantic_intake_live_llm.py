from __future__ import annotations

import os

import pytest

from factory_agent.config import get_settings
from factory_agent.planning.semantic_intake import OpenAICompatibleSemanticIntakeProposer


def _live_llm_enabled() -> bool:
    return (
        os.getenv("FACTORY_AGENT_LIVE_LLM", "").strip() == "1"
        and bool(os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL"))
    )


if not _live_llm_enabled():
    pytest.skip(
        "Set FACTORY_AGENT_LIVE_LLM=1 and OPENAI_BASE_URL or LLM_BASE_URL to run live semantic intake tests.",
        allow_module_level=True,
    )


@pytest.mark.parametrize(
    ("query", "expected_roles"),
    [
        (
            "Check machine M-CNC-01 status. "
            "If the machine result includes a job id, read that job and explain the cause.",
            {"required_requirement", "conditional_branch", "answer_instruction"},
        ),
        (
            "Read job JOB-SEED-001. If it has a product, read that product too and summarize both.",
            {"required_requirement", "conditional_branch", "answer_instruction"},
        ),
        (
            "Show machine M-CNC-01 status and explain what it means.",
            {"required_requirement", "answer_instruction"},
        ),
        (
            "Show job JOB-SEED-001 status in a short table.",
            {"required_requirement", "formatting_instruction"},
        ),
        (
            "Read machine M-CNC-01. If it has an active job id, read that job and summarize both.",
            {"required_requirement", "conditional_branch", "answer_instruction"},
        ),
    ],
)
def test_live_llm_semantic_intake_shapes_hard_queries(query: str, expected_roles: set[str]):
    proposer = OpenAICompatibleSemanticIntakeProposer(get_settings())

    result = proposer.propose(query)

    roles = {item.role for item in result.items}
    assert expected_roles <= roles
    assert all(item.text.strip() for item in result.items)
    assert not any("get__" in item.text for item in result.items)
