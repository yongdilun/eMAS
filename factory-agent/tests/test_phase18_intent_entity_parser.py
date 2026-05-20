import pytest

from factory_agent.planning.intent import (
    assess_intent,
    intent_constraint_values,
    should_clarify_loto_machine,
    should_route_loto_to_rag,
    split_user_intents,
)


@pytest.mark.parametrize(
    "prompt",
    [
        "What LOTO procedure applies before working on M-CNC-01?",
        "what loto procedure applies before working on m-cnc-01",
        "LOTO for M-CNC-01",
        "loto m-cnc-01",
        "Before service:\nLOTO for \"m-cnc-01\".",
        "What LOTO applies before working on **m-cnc-01**",
        "Apply LOTO before touching (M-CNC-01), please.",
    ],
)
def test_phase18_loto_variants_extract_machine_id_and_route_rag(prompt):
    assert intent_constraint_values(prompt, "machine_id") == ["M-CNC-01"]
    assert should_clarify_loto_machine(prompt) is False
    assert should_route_loto_to_rag(prompt) is True


@pytest.mark.parametrize(
    ("prompt", "expected_entity", "field", "expected_value"),
    [
        ("equipment M-CNC-01 status", "machine", "machine_id", "M-CNC-01"),
        ("asset m-cnc-01 condition", "machine", "machine_id", "M-CNC-01"),
        ("status for work order JOB-SEED-001", "job", "job_id", "JOB-SEED-001"),
        ("urgent tasks due soon", "job", None, None),
        ("overdue work orders", "job", None, None),
    ],
)
def test_phase18_machine_job_status_synonyms_map_to_entities(prompt, expected_entity, field, expected_value):
    assessment = assess_intent(prompt)
    assert assessment.kind == "operations"
    assert assessment.entity == expected_entity
    if field:
        assert intent_constraint_values(prompt, field) == [expected_value]


def test_phase18_missing_loto_machine_asks_clarification_but_present_id_does_not():
    missing = "What LOTO procedure applies before working on the machine?"
    present = "What LOTO procedure applies before working on M-CNC-01?"

    assert should_clarify_loto_machine(missing) is True
    assert should_route_loto_to_rag(missing) is False
    assert should_clarify_loto_machine(present) is False
    assert should_route_loto_to_rag(present) is True


def test_phase18_multi_entity_loto_prompt_preserves_machine_and_job_ids():
    prompt = "What LOTO procedure applies before working on M-CNC-01 for job JOB-SEED-001?"

    assert intent_constraint_values(prompt, "machine_id") == ["M-CNC-01"]
    assert intent_constraint_values(prompt, "job_id") == ["JOB-SEED-001"]
    assert should_route_loto_to_rag(prompt) is True


def test_phase18_parser_matrix_handles_markdown_quotes_newlines_and_mixed_case():
    prompt = "### Check\n'work order' **job-seed-001** before LOTO on `m-cnc-01`."
    intents = split_user_intents(prompt)
    flattened = [
        (constraint.field, constraint.value)
        for intent in intents
        for constraint in intent.explicit_constraints
    ]

    assert ("machine_id", "M-CNC-01") in flattened
    assert ("job_id", "JOB-SEED-001") in flattened
    assert should_route_loto_to_rag(prompt) is True


def test_phase18_compound_loto_status_prompt_keeps_status_as_tool_route():
    prompt = "Use OSHA LOTO guidance and show machine M-CNC-01 status"

    assert should_route_loto_to_rag(prompt) is False
    assessment = assess_intent(prompt)
    assert assessment.kind == "operations"
    assert assessment.entity == "machine"
