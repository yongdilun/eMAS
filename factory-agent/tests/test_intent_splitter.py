"""Phase 2: intent splitter structured output (no rejection of incomplete queries)."""

from __future__ import annotations

from pathlib import Path
import re

from langgraph.graph import END, StateGraph

from factory_agent.graph.nodes.intent_split import intent_splitter_node
from factory_agent.graph.state import AgentState
from factory_agent.planning.intent import split_user_intents


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
