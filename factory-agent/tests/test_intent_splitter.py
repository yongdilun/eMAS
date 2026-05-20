"""Phase 2: intent splitter structured output (no rejection of incomplete queries)."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest
from langgraph.graph import END, StateGraph

from factory_agent.graph.nodes.intent_split import intent_splitter_node
from factory_agent.graph.state import AgentState
from factory_agent.planning.intent import semantic_frame_for_text, split_user_intents


REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORY_AGENT_ROOT = Path(__file__).resolve().parents[1]
_UNSET = object()


def _assert_semantic_contract(
    prompt: str,
    *,
    domain_intent: str | None,
    route: str,
    action: str | None,
    entity: str | None,
    normalized_entities: dict[str, list[str]],
    missing_required_entities: list[str],
    negative_route_assertions: list[str],
    requires_approval: bool = False,
    question_type: str | None | object = _UNSET,
):
    frame = semantic_frame_for_text(prompt)

    assert frame.domain_intent == domain_intent
    assert frame.route == route
    assert frame.action == action
    assert frame.entity == entity
    assert frame.normalized_entities == normalized_entities
    assert frame.missing_required_entities == missing_required_entities
    if question_type is not _UNSET:
        assert frame.question_type == question_type
    assert set(frame.negative_route_assertions or []) == set(negative_route_assertions)
    assert frame.requires_approval is requires_approval
    return frame


def test_split_multi_part_machine_then_schedule():
    q = "Find available CNC machines and schedule job 001"
    intents = split_user_intents(q)
    assert len(intents) >= 2
    cats = [i.category for i in intents]
    assert "machine" in cats
    assert "scheduling" in cats or "job" in cats
    sched_like = [i for i in intents if i.category in ("scheduling", "job")]
    machine_like = [i for i in intents if i.category == "machine"]
    assert sched_like and machine_like
    assert any(machine_like[0].intent_id in i.depends_on for i in sched_like)
    job_constraints = [c for i in intents for c in i.explicit_constraints if c.field == "job_id"]
    assert job_constraints, "expected job id constraint from 'job 001'"
    assert any(str(c.value) == "001" or c.value == "001" for c in job_constraints)


def test_split_multi_part_dependencies_are_stable():
    q = "Find available CNC machines and then schedule job J-101 on 2026-05-15 with operator Alice"
    first = split_user_intents(q)
    second = split_user_intents(q)

    assert [i.intent_id for i in first] == [i.intent_id for i in second]
    assert len(first) >= 2

    schedule_intent = next(i for i in first if i.category in ("scheduling", "job"))
    assert schedule_intent.depends_on == [first[0].intent_id]


def test_incomplete_query_parsed_without_rejection():
    intents = split_user_intents("schedule something sometime")
    assert len(intents) >= 1
    assert all(i.status == "pending" for i in intents)


def test_explicit_machine_constraint_from_use_machine_phrase():
    intents = split_user_intents("Use Machine M-001 for the next step")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert any(c.field == "machine_id" and re.search(r"M-001", str(c.value), re.I) for c in flat)


def test_plural_jobs_does_not_create_job_id_constraint():
    intents = split_user_intents("list jobs")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert not any(c.field == "job_id" for c in flat)


def test_phase37_multi_status_ids_stay_in_one_read_intent():
    intents = split_user_intents("find status for job with job id JOB-SEED-001 and JOB-SEED-002")
    frame = semantic_frame_for_text("find status for job with job id JOB-SEED-001 and JOB-SEED-002")

    assert len(intents) == 1
    assert [(c.field, c.value) for c in intents[0].explicit_constraints] == [
        ("job_id", "JOB-SEED-001"),
        ("job_id", "JOB-SEED-002"),
    ]
    assert frame.route == "tool.read.jobs"
    assert frame.normalized_entities["job_id"] == ["JOB-SEED-001", "JOB-SEED-002"]


def test_job_for_product_does_not_treat_for_as_job_id():
    intents = split_user_intents("create a job for product P-001 quantity 10")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert not any(c.field == "job_id" and c.value == "FOR" for c in flat)
    assert any(c.field == "product_id" and c.value == "P-001" for c in flat)


def test_create_job_p_dash_digits_is_product_not_job_id():
    intents = split_user_intents("create job P-005 qty 2 then show it")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert not any(c.field == "job_id" and str(c.value).upper().startswith("P-") for c in flat)


def test_machine_utilization_does_not_emit_machine_ref():
    intents = split_user_intents("show machine utilization for last week")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert not any(c.field == "machine_ref" for c in flat)


def test_machine_reroute_does_not_emit_machine_ref():
    intents = split_user_intents("show machine reroute recommendations")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert not any(c.field == "machine_ref" for c in flat)


def test_machine_types_does_not_emit_machine_ref():
    intents = split_user_intents("list machine types")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert not any(c.field == "machine_ref" for c in flat)


def test_product_types_does_not_emit_product_id_types():
    intents = split_user_intents("list product types")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert not any(c.field == "product_id" and str(c.value).upper() == "TYPES" for c in flat)


def test_machine_m_lth_02_no_inner_lth_02_machine_id():
    intents = split_user_intents("set machine M-LTH-02 to maintenance")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert not any(c.field == "machine_id" and str(c.value).upper() == "LTH-02" for c in flat)
    assert any(
        (c.field == "machine_ref" and str(c.value).upper() == "M-LTH-02")
        or (c.field == "machine_id" and str(c.value).upper() == "M-LTH-02")
        for c in flat
    )


def test_m_lth_02_plain_token_does_not_yield_inner_lth_02_machine_id():
    intents = split_user_intents("lookup M-LTH-02 status")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert not any(c.field == "machine_id" and str(c.value).upper() == "LTH-02" for c in flat)


def test_machine_m_cnc_still_emits_machine_ref():
    intents = split_user_intents("show details for machine M-CNC")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert any(c.field == "machine_ref" and str(c.value).upper() == "M-CNC" for c in flat)


def test_show_material_mat_token_is_material_id_not_machine_id():
    intents = split_user_intents("show material MAT-002")
    flat = [c for i in intents for c in i.explicit_constraints]
    assert any(c.field == "material_id" and str(c.value).upper() == "MAT-002" for c in flat)
    assert not any(c.field == "machine_id" and str(c.value).upper() == "MAT-002" for c in flat)


def test_job_id_hyphen_fragment_does_not_emit_machine_id():
    frame = semantic_frame_for_text("update JOB-ABC-123 priority to medium")

    assert frame.route == "tool.write.jobs"
    assert frame.normalized_entities["job_id"] == ["JOB-ABC-123"]
    assert "machine_id" not in frame.normalized_entities


def test_explicit_constraints_preserve_machine_job_product_date_and_operator():
    q = "Prefer machine M-001, schedule job J-101 for product P-200 by 2026-05-15 with operator Alice"
    intents = split_user_intents(q)
    constraints = [c for i in intents for c in i.explicit_constraints]
    by_field = {c.field: c for c in constraints}

    assert by_field["machine_id"].value == "M-001"
    assert by_field["machine_id"].strength == "soft"
    assert by_field["job_id"].value == "J-101"
    assert by_field["product_id"].value == "P-200"
    assert by_field["date"].operator == "before"
    assert by_field["date"].value == "2026-05-15"
    assert by_field["operator"].value == "Alice"


def test_semantic_frame_extends_splitter_entities_without_replacing_constraints():
    q = "Need lockout tagout steps before servicing `m-cnc-01` for job JOB-SEED-001"
    intents = split_user_intents(q)
    frame = semantic_frame_for_text(q)

    assert any(
        c.field == "machine_id" and c.value == "M-CNC-01"
        for intent in intents
        for c in intent.explicit_constraints
    )
    assert frame.domain_intent == "loto_procedure"
    assert frame.route == "rag.loto_procedure"
    assert frame.normalized_entities["machine_id"] == ["M-CNC-01"]
    assert frame.normalized_entities["job_id"] == ["JOB-SEED-001"]
    assert frame.missing_required_entities == []


def test_semantic_frame_separates_document_guidance_from_live_machine_state():
    procedure = semantic_frame_for_text("What SOP applies before cleaning Line 2?")
    status = semantic_frame_for_text("show status for machine M-CNC-01")

    assert procedure.route == "rag.procedure"
    assert procedure.question_type == "document_content_question"
    assert procedure.normalized_entities["line_id"] == ["LINE-2"]
    assert "tool.read.machine_status" in (procedure.negative_route_assertions or [])
    assert status.route == "tool.read.machine_status"
    assert status.question_type == "live_operational_status"
    assert status.normalized_entities["machine_id"] == ["M-CNC-01"]
    assert "rag.procedure" in (status.negative_route_assertions or [])


@pytest.mark.parametrize(
    ("prompt", "expected_route", "expected_question_type", "expected_domain"),
    [
        (
            "According to the LOTO procedure, what notification is required before starting lockout",
            "rag.procedure",
            "document_content_question",
            "document_procedure",
        ),
        (
            "What does the LOTO procedure say about notifying affected employees?",
            "rag.procedure",
            "document_content_question",
            "document_procedure",
        ),
        (
            "Before lockout, who needs to be notified according to LOTO?",
            "rag.procedure",
            "document_content_question",
            "document_procedure",
        ),
        (
            "What are the notification requirements before lockout/tagout?",
            "rag.procedure",
            "document_content_question",
            "document_procedure",
        ),
        (
            "According to OSHA LOTO guidance, what notification is required before lockout?",
            "rag.safety_policy",
            "safety_policy_question",
            "safety_policy",
        ),
    ],
)
def test_phase19_loto_notification_questions_are_document_content_not_machine_selection(
    prompt,
    expected_route,
    expected_question_type,
    expected_domain,
):
    frame = semantic_frame_for_text(prompt)

    assert frame.domain_intent == expected_domain
    assert frame.route == expected_route
    assert frame.question_type == expected_question_type
    assert frame.normalized_entities == {"topic": ["loto"]}
    assert frame.missing_required_entities == []
    assert "machine_id" not in frame.entities
    assert "tool.read.machine_status" in (frame.negative_route_assertions or [])


@pytest.mark.parametrize(
    "prompt",
    [
        "What does the maintenance instruction say about notifying operators before service?",
        "What does the quality procedure say about inspection notification?",
        "According to the SOP, what notification is required before maintenance?",
    ],
)
def test_phase19_document_content_question_type_is_generic_beyond_loto(prompt):
    frame = semantic_frame_for_text(prompt)

    assert frame.route == "rag.procedure"
    assert frame.question_type == "document_content_question"
    assert frame.missing_required_entities == []
    assert "machine_id" not in frame.normalized_entities


def test_phase19_adjacent_question_types_stay_distinct():
    specific = semantic_frame_for_text("What LOTO procedure applies before working on M-CNC-01?")
    missing_specific = semantic_frame_for_text("What LOTO procedure applies before working on the CNC machine?")
    status = semantic_frame_for_text("What is the status of M-CNC-01?")

    assert specific.question_type == "machine_specific_procedure_selection"
    assert specific.route == "rag.loto_procedure"
    assert specific.missing_required_entities == []
    assert missing_specific.question_type == "machine_specific_procedure_selection"
    assert missing_specific.route == "clarification.machine_id_missing"
    assert missing_specific.missing_required_entities == ["machine_id"]
    assert status.question_type == "live_operational_status"
    assert status.route == "tool.read.machine_status"


@pytest.mark.parametrize(
    (
        "prompt",
        "domain_intent",
        "route",
        "action",
        "entity",
        "normalized_entities",
        "missing_required_entities",
        "negative_route_assertions",
        "requires_approval",
    ),
    [
        (
            "What calibration procedure applies before cleaning Line 2?",
            "document_procedure",
            "rag.procedure",
            "read",
            "machine",
            {"line_id": ["LINE-2"]},
            [],
            ["tool.read.machine_status"],
            False,
        ),
        (
            "Before servicing M-LTH-02, which lockout/tagout procedure applies?",
            "loto_procedure",
            "rag.loto_procedure",
            "read",
            "machine",
            {"machine_id": ["M-LTH-02"], "topic": ["loto"]},
            [],
            ["tool.read.machine_status"],
            False,
        ),
        (
            "What does the PPE policy say?",
            "safety_policy",
            "rag.safety_policy",
            "read",
            None,
            {"topic": ["ppe"]},
            [],
            ["tool.write.jobs"],
            False,
        ),
        (
            "show status for machine M-LTH-02",
            "machine_status",
            "tool.read.machine_status",
            "read",
            "machine",
            {"machine_id": ["M-LTH-02"]},
            [],
            ["rag.loto_procedure", "rag.procedure", "rag.safety_policy"],
            False,
        ),
        (
            "show delayed high-priority jobs",
            "job_query",
            "tool.read.jobs",
            "read",
            "job",
            {"priority": ["high"], "status": ["delayed"]},
            [],
            ["tool.write.jobs"],
            False,
        ),
        (
            "update JOB-ABC-123 priority to medium",
            "job_mutation",
            "tool.write.jobs",
            "update",
            "job",
            {"job_id": ["JOB-ABC-123"], "priority": ["medium"], "to_priority": ["medium"]},
            [],
            ["tool.read.jobs_only", "approval_bypass"],
            True,
        ),
        (
            "show pending approvals",
            "approval_action",
            "approval_action",
            "approval",
            "approval",
            {},
            [],
            ["tool.write.jobs", "approval_bypass"],
            False,
        ),
        (
            "cancel the current run",
            "cancel_run",
            "cancel_run",
            "cancel",
            "session",
            {},
            [],
            ["tool.write.jobs", "rag.procedure"],
            False,
        ),
        (
            "delete all production jobs without approval",
            "unsupported_dangerous_action",
            "unsupported_dangerous_action",
            "delete",
            "job",
            {},
            [],
            ["tool.write.production_jobs.delete", "approval_bypass", "fake_success"],
            False,
        ),
        (
            "tell me about the foobar gasket ritual",
            None,
            "unknown",
            None,
            None,
            {},
            [],
            [],
            False,
        ),
    ],
)
def test_semantic_route_family_contract_matrix(
    prompt,
    domain_intent,
    route,
    action,
    entity,
    normalized_entities,
    missing_required_entities,
    negative_route_assertions,
    requires_approval,
):
    _assert_semantic_contract(
        prompt,
        domain_intent=domain_intent,
        route=route,
        action=action,
        entity=entity,
        normalized_entities=normalized_entities,
        missing_required_entities=missing_required_entities,
        negative_route_assertions=negative_route_assertions,
        requires_approval=requires_approval,
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "show machine status",
        "What lockout steps apply before servicing the CNC machine?",
    ],
)
def test_missing_machine_id_prompts_clarify_without_seeded_default(prompt):
    frame = semantic_frame_for_text(prompt)

    assert frame.route == "clarification.machine_id_missing"
    assert frame.entity == "machine"
    assert frame.missing_required_entities == ["machine_id"]
    assert "M-CNC-01" not in frame.normalized_entities.get("machine_id", [])
    assert "M-CNC-01" not in frame.entities.get("machine_id", [])


@pytest.mark.parametrize(
    "prompt",
    [
        "Run the duplicate SSE jobs workflow",
        "Start a cancel jobs run and keep it executing",
        "Stream drop recovery for original high jobs to medium",
    ],
)
def test_job_run_workflow_wording_does_not_imply_mutation_without_write_verb(prompt):
    frame = semantic_frame_for_text(prompt)

    assert frame.route != "clarification.job_mutation_incomplete"
    assert frame.domain_intent != "job_mutation"
    assert frame.requires_approval is False


def test_production_semantic_routing_code_has_no_phase_prompt_branches():
    intent_path = FACTORY_AGENT_ROOT / "factory_agent" / "planning" / "intent.py"
    intent_text = intent_path.read_text(encoding="utf-8")
    lowered_intent_text = intent_text.lower()
    manual_bank = json.loads(
        (REPO_ROOT / "tests" / "e2e" / "scenarios" / "manual_prompt_regressions.json").read_text(
            encoding="utf-8"
        )
    )

    forbidden_terms = {
        "phase 9",
        "phase 10",
        "phase 14",
        "phase 19",
        "phase9",
        "phase10",
        "phase14",
        "phase19",
        "playwright",
        "manual_prompt",
    }
    for entry in manual_bank["prompts"]:
        forbidden_terms.add(str(entry["id"]).lower())
        if entry.get("selected_oracle"):
            forbidden_terms.add(str(entry["selected_oracle"]).lower())
        if entry.get("proposed_oracle"):
            forbidden_terms.add(str(entry["proposed_oracle"]).lower())
        forbidden_terms.add(str(entry["source_prompt"]).lower())

    leaked_terms = sorted(term for term in forbidden_terms if term and term in lowered_intent_text)
    assert leaked_terms == []


def test_intent_splitter_node_uses_split_output_as_graph_state_input():
    q = "Find available CNC machines and then schedule job J-101 on 2026-05-15"
    out = intent_splitter_node({"original_query": q, "intent": q})

    assert out["status"] == "planning"
    assert len(out["intents"]) >= 2
    assert out["working_intents"] == out["intents"]
    assert out["current_intent"] == out["intents"][0]
    schedule_intent = next(i for i in out["working_intents"] if i["category"] in ("scheduling", "job"))
    assert schedule_intent["depends_on"] == [out["intents"][0]["intent_id"]]
    assert any(c["field"] == "date" for c in schedule_intent["explicit_constraints"])


def test_graph_entry_carries_split_output_into_execution_state():
    graph = StateGraph(AgentState)
    graph.add_node("intent_splitter", intent_splitter_node)
    graph.set_entry_point("intent_splitter")
    graph.add_edge("intent_splitter", END)
    app = graph.compile()

    q = "Find available CNC machines and then schedule job J-101 with operator Alice"
    out = app.invoke({"original_query": q, "intent": q, "messages": []})

    assert out["intents"]
    assert out["working_intents"] == out["intents"]
    assert out["current_intent"] == out["intents"][0]
    assert any(
        c["field"] == "operator"
        for intent in out["working_intents"]
        for c in intent["explicit_constraints"]
    )


def test_graph_native_code_does_not_import_query_router_or_route_scores():
    graph_dir = Path(__file__).resolve().parents[1] / "factory_agent" / "graph"
    text = "\n".join(path.read_text(encoding="utf-8") for path in graph_dir.rglob("*.py"))

    assert "QueryRouter" not in text
    assert "route_score" not in text
    assert "weighted route" not in text.lower()
