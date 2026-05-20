import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

import database
from factory_agent.api import build_router
from factory_agent.api.routers.messages import _CANCEL_COMMAND_RE
from factory_agent.config import Settings
from factory_agent.planning.intent import (
    assess_intent,
    intent_constraint_values,
    loto_query_with_resolved_machine_context,
    resolve_contextual_loto_machine_id,
    semantic_frame_for_text,
    should_clarify_loto_machine,
    should_route_loto_to_rag,
)
from factory_agent.planning.tool_selector import ToolSelector
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import ToolInfo
from factory_agent.testing_seeded_adapters import SeededPlaywrightPlanner, SeededPlaywrightRAGPipeline
from tests.support.stateful_oracle_harness import load_oracle


REPO_ROOT = Path(__file__).resolve().parents[2]
BANK_PATH = REPO_ROOT / "tests" / "e2e" / "scenarios" / "manual_prompt_regressions.json"
PHASE19_NOTIFICATION_PROMPTS = [
    "According to the LOTO procedure, what notification is required before starting lockout",
    "What does the LOTO procedure say about notifying affected employees?",
    "Before lockout, who needs to be notified according to LOTO?",
    "What are the notification requirements before lockout/tagout?",
    "According to OSHA LOTO guidance, what notification is required before lockout?",
]


class FakeEventBus:
    def __init__(self):
        self.published = []

    async def publish(self, event):
        self.published.append(event)

    async def listen(self, handler):
        return


def _load_bank():
    return json.loads(BANK_PATH.read_text(encoding="utf-8"))


def _settings(**overrides):
    base = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        worker_count=1,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=2.0,
        tool_selector_backend="retrieval",
        tool_selector_top_k=6,
        tool_selector_candidate_pool=10,
    )
    values = base.__dict__.copy()
    values.update(overrides)
    return Settings(**values)


async def _make_phase19_app(sessionmaker_override, *, rag_pipeline_adapter):
    settings = _settings(
        worker_count=0,
        enforce_tool_registry_health=False,
        auto_repair_tool_registry=False,
        min_healthy_tool_count=0,
    )
    app = FastAPI()
    event_bus = FakeEventBus()

    async def override_get_db():
        async with sessionmaker_override() as s:
            yield s

    app.dependency_overrides[database.get_db] = override_get_db
    app.include_router(
        build_router(
            settings=settings,
            tool_registry=ToolRegistry(),
            event_bus=event_bus,
            enqueue_session=None,
            rag_pipeline_adapter=rag_pipeline_adapter,
        )
    )
    return app


def _tool(name, description, endpoint, method, tags, *, read_only=True, approval=False):
    return ToolInfo(
        name=name,
        description=description,
        endpoint=endpoint,
        method=method,
        input_schema={"type": "object", "properties": {}},
        is_read_only=read_only,
        requires_approval=approval,
        capability_tags=tags,
    )


def _route_matrix_tools():
    return {
        "get__machines_{id}": _tool(
            "get__machines_{id}",
            "Get machine by id and status",
            "/machines/{id}",
            "GET",
            ["machine", "status", "lookup"],
        ),
        "get__jobs": _tool(
            "get__jobs",
            "List jobs by priority and status",
            "/jobs",
            "GET",
            ["job", "list", "priority"],
        ),
        "put__jobs_{id}": _tool(
            "put__jobs_{id}",
            "Update job priority by id",
            "/jobs/{id}",
            "PUT",
            ["job", "update", "priority"],
            read_only=False,
            approval=True,
        ),
        "get__chatbot_approval_pending": _tool(
            "get__chatbot_approval_pending",
            "List pending approvals",
            "/chatbot/approval/pending",
            "GET",
            ["approval", "pending", "list"],
        ),
        "post__sessions_{id}_cancel": _tool(
            "post__sessions_{id}_cancel",
            "Cancel the current session run",
            "/sessions/{id}/cancel",
            "POST",
            ["session", "cancel", "run"],
            read_only=False,
        ),
    }


def _assert_semantic_frame(prompt, *, domain_intent, route, entity=None, missing=(), negative=(), question_type=None):
    frame = semantic_frame_for_text(prompt)
    assert frame.domain_intent == domain_intent
    assert frame.route == route
    assert frame.entity == entity
    assert frame.missing_required_entities == list(missing)
    if question_type is not None:
        assert frame.question_type == question_type
    for forbidden in negative:
        assert forbidden in (frame.negative_route_assertions or [])
    return frame


@pytest.mark.parametrize(
    ("prompt", "expected_domain", "expected_route", "expected_question_type"),
    [
        *[
            (prompt, "document_procedure", "rag.procedure", "document_content_question")
            for prompt in PHASE19_NOTIFICATION_PROMPTS[:4]
        ],
        (PHASE19_NOTIFICATION_PROMPTS[4], "safety_policy", "rag.safety_policy", "safety_policy_question"),
    ],
)
def test_phase19_document_content_loto_notification_route_matrix(
    prompt,
    expected_domain,
    expected_route,
    expected_question_type,
):
    frame = _assert_semantic_frame(
        prompt,
        domain_intent=expected_domain,
        route=expected_route,
        entity=None,
        missing=[],
        negative=["tool.read.machine_status"],
        question_type=expected_question_type,
    )

    assert frame.normalized_entities == {"topic": ["loto"]}
    assert should_clarify_loto_machine(prompt) is False
    assert should_route_loto_to_rag(prompt) is True
    assert "machine_id" not in frame.entities


@pytest.mark.parametrize(
    ("prompt", "expected_entity"),
    [
        ("What does the maintenance instruction say about notifying operators before service?", None),
        ("According to the quality procedure, what notification is required before inspection?", None),
        ("What does the job instruction say about notifying the supervisor before setup?", "job"),
    ],
)
def test_phase19_document_content_contract_is_not_loto_prompt_specific(prompt, expected_entity):
    frame = _assert_semantic_frame(
        prompt,
        domain_intent="document_procedure",
        route="rag.procedure",
        entity=expected_entity,
        missing=[],
        negative=["tool.read.machine_status"],
        question_type="document_content_question",
    )

    assert frame.missing_required_entities == []
    assert "machine_id" not in frame.normalized_entities


def test_phase19_adjacent_loto_and_status_controls_keep_entity_requirements():
    specific = _assert_semantic_frame(
        "What LOTO procedure applies before working on M-CNC-01?",
        domain_intent="loto_procedure",
        route="rag.loto_procedure",
        entity="machine",
        missing=[],
        negative=["tool.read.machine_status"],
        question_type="machine_specific_procedure_selection",
    )
    generic_machine = _assert_semantic_frame(
        "What LOTO procedure applies before working on the CNC machine?",
        domain_intent="loto_procedure",
        route="clarification.machine_id_missing",
        entity="machine",
        missing=["machine_id"],
        negative=["rag.loto_procedure", "tool.read.machine_status"],
        question_type="machine_specific_procedure_selection",
    )
    status = _assert_semantic_frame(
        "What is the status of M-CNC-01?",
        domain_intent="machine_status",
        route="tool.read.machine_status",
        entity="machine",
        missing=[],
        negative=["rag.loto_procedure", "rag.procedure"],
        question_type="live_operational_status",
    )

    assert specific.normalized_entities["machine_id"] == ["M-CNC-01"]
    assert "machine_id" not in generic_machine.normalized_entities
    assert status.normalized_entities["machine_id"] == ["M-CNC-01"]


@pytest.mark.asyncio
async def test_phase19_document_content_loto_prompt_workflow_returns_clean_response_document(sessionmaker_override, db_session):
    from factory_agent.persistence.models import Session

    class FakeRAGPipeline:
        def __init__(self):
            self.calls = []

        async def run(self, *, query, session_id=None, route="RAG_ONLY", api_data=None):
            self.calls.append({"query": query, "session_id": session_id, "route": route, "api_data": api_data})
            return type(
                "Result",
                (),
                {
                    "answer": (
                        "The LOTO procedure requires notifying affected employees before lockout/tagout starts. "
                        "Tell them the equipment will be locked out, why the shutdown is needed, and when the "
                        "lockout/tagout condition begins [^1]."
                    ),
                    "sources": [
                        {
                            "source_number": 1,
                            "source_id": "osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0027",
                            "doc_id": "osha_3120_lockout_tagout",
                            "chunk_id": "osha_3120_lockout_tagout_c0027",
                            "title": "Control of Hazardous Energy Lockout/Tagout",
                            "organization": "OSHA",
                            "snippet": (
                                "Notify affected employees before lockout/tagout starts and tell them when the "
                                "lockout/tagout condition begins."
                            ),
                            "authority_level": "official_public_guidance",
                        }
                    ],
                    "safety_content": "Follow the site-approved LOTO procedure and authorized-employee controls.",
                },
            )()

    rag = FakeRAGPipeline()
    app = await _make_phase19_app(sessionmaker_override, rag_pipeline_adapter=rag)
    prompt = PHASE19_NOTIFICATION_PROMPTS[0]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session_id = (await client.post("/sessions", json={"user_id": "u1"})).json()["session_id"]
        await client.post(
            f"/sessions/{session_id}/messages",
            json={"role": "user", "content": prompt, "mode": "normal"},
        )

        created = await client.post(f"/sessions/{session_id}/plans", json={})
        assert created.status_code == 200
        body = created.json()
        snapshot = (await client.get(f"/sessions/{session_id}/snapshot")).json()
        steps = (await client.get(f"/sessions/{session_id}/steps")).json()

    assert rag.calls == [{"query": prompt, "session_id": session_id, "route": "RAG_ONLY", "api_data": None}]
    assert body["status"] == "COMPLETED"
    assert body["created_by"] == "v2_rag_tool"
    assert "notifying affected employees" in body["plan_explanation"].lower()
    assert body["sources"][0]["doc_id"] == "osha_3120_lockout_tagout"
    assert steps == []

    document = snapshot["response_document"]
    block_types = [block["type"] for block in document["blocks"]]
    serialized = json.dumps(snapshot)

    assert snapshot["session"]["status"] == "COMPLETED"
    assert snapshot["pending_approval"] is None
    assert document["state"] == "completed"
    assert "knowledge_answer" in block_types
    assert "source_list" in block_types
    assert "diagnostic" not in block_types
    assert "approval_required" not in block_types
    assert "Which machine ID" not in serialized
    assert "No results" not in serialized
    assert "completed_answer" not in serialized
    session_row = await db_session.get(Session, session_id)
    contract = (session_row.replan_context or {})["intent_contract"]
    assert contract["engine_version"] == "v2"
    assert contract["execution_trace"]["detectors"]["legacy_rag_shortcut"]["used"] is False
    assert contract["v2_state"]["evidence_ledger"]["evidence"][0]["source_type"] == "rag_tool"


def test_phase19_scenario_116_loto_wording_matrix_uses_same_rag_route():
    bank = _load_bank()
    loto_entries = [
        entry
        for entry in bank["prompts"]
        if (
            entry["id"] == "phase18-loto-m-cnc-01"
            or entry["id"].startswith("phase19-loto-")
            or entry.get("selected_oracle") == "SO-023"
        )
        and entry["expected"]["primary_route"] == "rag_loto"
    ]

    assert len(loto_entries) >= 5
    for entry in loto_entries:
        prompt = entry["source_prompt"]
        assert entry["expected"]["primary_route"] == "rag_loto"
        assert intent_constraint_values(prompt, "machine_id") == ["M-CNC-01"]
        assert intent_constraint_values(prompt, "job_id") == []
        assert should_clarify_loto_machine(prompt) is False
        assert should_route_loto_to_rag(prompt) is True
        assert entry["expected"]["required_source"] == {
            "machine_id": "M-CNC-01",
            "procedure_id": "LOTO-M-CNC-01",
        }
        frame = semantic_frame_for_text(prompt)
        assert frame.domain_intent == "loto_procedure"
        assert frame.route == "rag.loto_procedure"
        assert frame.normalized_entities["machine_id"] == ["M-CNC-01"]
        assert "tool.read.machine_status" in (frame.negative_route_assertions or [])


@pytest.mark.parametrize(
    ("prompt", "expected_domain", "expected_route", "expected_entity", "expected_entities", "missing", "negative"),
    [
        (
            "What is the LOTO procedure for M-CNC-01?",
            "loto_procedure",
            "rag.loto_procedure",
            "machine",
            {"machine_id": ["M-CNC-01"], "topic": ["loto"]},
            [],
            ["tool.read.machine_status"],
        ),
        (
            "What LOTO procedure applies before working on the CNC machine?",
            "loto_procedure",
            "clarification.machine_id_missing",
            "machine",
            {"topic": ["loto"]},
            ["machine_id"],
            ["rag.loto_procedure", "tool.read.machine_status"],
        ),
        (
            "What SOP applies before cleaning Line 2?",
            "document_procedure",
            "rag.procedure",
            "machine",
            {"line_id": ["LINE-2"]},
            [],
            ["tool.read.machine_status"],
        ),
        (
            "What does the PPE policy say?",
            "safety_policy",
            "rag.safety_policy",
            None,
            {"topic": ["ppe"]},
            [],
            ["tool.write.jobs"],
        ),
        (
            "What is the purpose of Lockout/Tagout (LOTO) procedures according to OSHA? Is there any specific OSHA regulation or standard that defines this?",
            "safety_policy",
            "rag.safety_policy",
            None,
            {"topic": ["loto"]},
            [],
            ["tool.read.machine_status"],
        ),
    ],
)
def test_phase21_document_and_loto_semantic_route_family_matrix(
    prompt,
    expected_domain,
    expected_route,
    expected_entity,
    expected_entities,
    missing,
    negative,
):
    frame = _assert_semantic_frame(
        prompt,
        domain_intent=expected_domain,
        route=expected_route,
        entity=expected_entity,
        missing=missing,
        negative=negative,
    )
    for field, expected_values in expected_entities.items():
        assert frame.normalized_entities.get(field) == expected_values
    assert "M-CNC-01" not in frame.normalized_entities.get("machine_id", []) or expected_entities.get("machine_id") == ["M-CNC-01"]


@pytest.mark.parametrize(
    ("prompt", "expected_route", "expected_entities", "missing"),
    [
        ("show status for machine M-CNC-01", "tool.read.machine_status", {"machine_id": ["M-CNC-01"]}, []),
        ("Use OSHA LOTO guidance and show machine M-CNC-01 status", "tool.read.machine_status", {"machine_id": ["M-CNC-01"]}, []),
        ("show machine status", "clarification.machine_id_missing", {}, ["machine_id"]),
    ],
)
def test_phase21_machine_status_semantic_route_matrix(prompt, expected_route, expected_entities, missing):
    frame = _assert_semantic_frame(
        prompt,
        domain_intent="machine_status",
        route=expected_route,
        entity="machine",
        missing=missing,
        negative=["rag.loto_procedure"],
    )
    for field, expected_values in expected_entities.items():
        assert frame.normalized_entities.get(field) == expected_values


@pytest.mark.parametrize(
    ("prompt", "expected_route", "expected_entities"),
    [
        ("show delayed high-priority jobs", "tool.read.jobs", {"priority": ["high"], "status": ["delayed"]}),
        ("status for work order JOB-SEED-001", "tool.read.jobs", {"job_id": ["JOB-SEED-001"]}),
    ],
)
def test_phase21_job_query_semantic_route_matrix(prompt, expected_route, expected_entities):
    frame = _assert_semantic_frame(
        prompt,
        domain_intent="job_query",
        route=expected_route,
        entity="job",
        negative=["tool.write.jobs"],
    )
    for field, expected_values in expected_entities.items():
        assert frame.normalized_entities.get(field) == expected_values
    assert frame.requires_approval is False


@pytest.mark.parametrize(
    ("prompt", "expected_entities"),
    [
        ("change high priority jobs to low", {"from_priority": ["high"], "to_priority": ["low"]}),
        ("update JOB-SEED-001 priority to medium", {"job_id": ["JOB-SEED-001"], "to_priority": ["medium"]}),
    ],
)
def test_phase21_job_mutation_semantic_route_matrix(prompt, expected_entities):
    frame = _assert_semantic_frame(
        prompt,
        domain_intent="job_mutation",
        route="tool.write.jobs",
        entity="job",
        negative=["approval_bypass"],
    )
    for field, expected_values in expected_entities.items():
        assert frame.normalized_entities.get(field) == expected_values
    assert frame.missing_required_entities == []
    assert frame.requires_approval is True


@pytest.mark.parametrize(
    ("prompt", "expected_domain", "expected_route", "expected_entity"),
    [
        ("show pending approvals", "approval_action", "approval_action", "approval"),
        ("approve the second request", "approval_action", "approval_action", "approval"),
        ("cancel the current run", "cancel_run", "cancel_run", "session"),
    ],
)
def test_phase21_approval_and_cancel_semantic_route_matrix(prompt, expected_domain, expected_route, expected_entity):
    _assert_semantic_frame(
        prompt,
        domain_intent=expected_domain,
        route=expected_route,
        entity=expected_entity,
        negative=["approval_bypass"] if expected_domain == "approval_action" else ["tool.write.jobs"],
    )


def test_phase21_unsupported_dangerous_action_semantic_route_blocks_mutation():
    oracle = load_oracle("SO-044")
    prompt = oracle["prompt"]

    frame = _assert_semantic_frame(
        prompt,
        domain_intent="unsupported_dangerous_action",
        route="unsupported_dangerous_action",
        entity="job",
        negative=["tool.write.production_jobs.delete", "approval_bypass", "fake_success"],
    )

    assert frame.missing_required_entities == []
    assert frame.requires_approval is False
    assert oracle["expected_route"]["route"] == "unsupported_dangerous_action"


@pytest.mark.parametrize(
    ("prompt", "expected_machine_ids", "expected_job_ids"),
    [
        ("Status for M-CNC-01, please; job JOB-SEED-001.", ["M-CNC-01"], ["JOB-SEED-001"]),
        ("check m-cnc-01 and job-seed-001", ["M-CNC-01"], ["JOB-SEED-001"]),
        ('Use "M-CNC-01" with "JOB-SEED-001" for this check.', ["M-CNC-01"], ["JOB-SEED-001"]),
        ("machine (M-CNC-01) for work order (JOB-SEED-001)", ["M-CNC-01"], ["JOB-SEED-001"]),
        ("### IDs\n- machine: `m-cnc-01`\n- job: **job-seed-001**", ["M-CNC-01"], ["JOB-SEED-001"]),
        ("Machine:\nM-CNC-01\nJob:\nJOB-SEED-001", ["M-CNC-01"], ["JOB-SEED-001"]),
        ("need lockout tagout for m-cnc-01 before service", ["M-CNC-01"], []),
    ],
)
def test_phase19_scenario_117_machine_and_job_id_extraction_matrix(prompt, expected_machine_ids, expected_job_ids):
    assert intent_constraint_values(prompt, "machine_id") == expected_machine_ids
    assert intent_constraint_values(prompt, "job_id") == expected_job_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "prompt", "expected_action", "expected_entity", "expected_route", "expected_tools"),
    [
        ("machine_status", "show status for machine M-CNC-01", "read", "machine", "tool.read.machine_status", ["get__machines_{id}"]),
        ("job_listing", "list high priority jobs", "read", "job", "tool.read.jobs", ["get__jobs"]),
        ("priority_mutation", "change all low priority jobs to high", "update", "job", "tool.write.jobs", ["put__jobs_{id}"]),
        ("approval", "show pending approvals", "approval", None, "approval_action", ["get__chatbot_approval_pending"]),
        ("cancel", "cancel the current run", "update", None, "cancel_run", ["post__sessions_{id}_cancel"]),
    ],
)
async def test_phase19_scenario_118_route_selection_matrix(label, prompt, expected_action, expected_entity, expected_route, expected_tools):
    del label
    assessment = assess_intent(prompt)
    assert assessment.kind == "operations"
    assert assessment.action == expected_action
    assert assessment.entity == expected_entity
    assert semantic_frame_for_text(prompt).route == expected_route

    selector = ToolSelector(_settings())
    selected = await selector.select_tools(
        intent=prompt,
        tools_by_name=_route_matrix_tools(),
        mode="normal",
        max_tools=10,
    )
    for tool_name in expected_tools:
        assert tool_name in selected.tool_names


def test_phase19_scenario_118_loto_route_selection_short_circuits_to_rag():
    prompt = "Before servicing M-CNC-01, which LOTO procedure applies?"
    assessment = assess_intent(prompt)

    assert should_route_loto_to_rag(prompt) is True
    assert should_clarify_loto_machine(prompt) is False
    assert assessment.kind == "operations"
    assert assessment.entity == "machine"


@pytest.mark.parametrize("oracle_id", ["SO-021", "SO-023", "SO-025"])
def test_so021_so023_so025_prompt_oracles_route_loto_to_rag_with_machine_id(oracle_id):
    oracle = load_oracle(oracle_id)
    prompt = oracle["prompt"]
    route = oracle["expected_route"]

    assert intent_constraint_values(prompt, "machine_id") == [route["machine_id"]]
    assert intent_constraint_values(prompt, "job_id") == []
    assert should_clarify_loto_machine(prompt) is False
    assert should_route_loto_to_rag(prompt) is True
    frame = semantic_frame_for_text(prompt)
    assert frame.domain_intent == "loto_procedure"
    assert frame.route == "rag.loto_procedure"
    assert frame.normalized_entities["machine_id"] == [route["machine_id"]]
    assert frame.missing_required_entities == []

    assessment = assess_intent(prompt)
    assert assessment.kind == "operations"
    assert assessment.entity == "machine"
    assert route["route"] == "rag.loto_procedure"
    forbidden_routes = route.get("must_not_route_to") or route.get("negative_route_assertions") or []
    assert "tool.read.machine_status" in forbidden_routes


def test_so022_prompt_oracle_clarifies_missing_loto_machine_without_default_id():
    oracle = load_oracle("SO-022")
    prompt = oracle["prompt"]

    assert intent_constraint_values(prompt, "machine_id") == []
    assert should_clarify_loto_machine(prompt) is True
    assert should_route_loto_to_rag(prompt) is False
    frame = semantic_frame_for_text(prompt)
    assert frame.domain_intent == "loto_procedure"
    assert frame.route == "clarification.machine_id_missing"
    assert frame.missing_required_entities == ["machine_id"]
    assert "M-CNC-01" not in frame.normalized_entities.get("machine_id", [])

    assessment = assess_intent(prompt)
    assert assessment.kind == "operations"
    assert assessment.entity == "machine"
    assert oracle["expected_route"]["route"] == "clarification.machine_id_missing"
    assert "M-CNC-01" in oracle["expected_route"]["must_not_invent"]
    assert "M-CNC-01" in oracle["expected_final_response"]["must_not_include"]


@pytest.mark.asyncio
async def test_so022_seeded_rag_does_not_default_missing_loto_machine_to_cnc_fixture():
    oracle = load_oracle("SO-022")
    result = await SeededPlaywrightRAGPipeline().run(query=oracle["prompt"], session_id="so022-rag-default")

    assert "M-CNC-01" not in result.answer
    assert "Seeded LOTO Procedure for M-CNC-01" not in result.answer
    assert result.sources == []


def test_so026_loto_followup_resolves_machine_id_from_immediately_previous_turn():
    oracle = load_oracle("SO-026")
    second_prompt = oracle["prompt_sequence"][1]["prompt"]
    previous_texts = [
        "Machine M-CNC-01 is RUNNING from seeded Go API data.",
        oracle["prompt_sequence"][0]["prompt"],
    ]

    resolved = resolve_contextual_loto_machine_id(second_prompt, previous_texts)
    assert resolved == "M-CNC-01"

    contextual_prompt = loto_query_with_resolved_machine_context(second_prompt, resolved)
    assert intent_constraint_values(contextual_prompt, "machine_id") == ["M-CNC-01"]
    assert should_clarify_loto_machine(contextual_prompt) is False
    assert should_route_loto_to_rag(contextual_prompt) is True
    frame = semantic_frame_for_text(second_prompt, previous_texts=previous_texts)
    assert frame.route == "rag.loto_procedure"
    assert frame.normalized_entities["machine_id"] == ["M-CNC-01"]
    assert resolve_contextual_loto_machine_id("What LOTO procedure applies before working on M-CNC-01?", previous_texts) is None
    assert "Machine ID:" not in contextual_prompt


def test_so028_seeded_cancel_fixture_prompt_is_not_a_cancel_command():
    assert _CANCEL_COMMAND_RE.match("cancel the current run")
    assert _CANCEL_COMMAND_RE.match("stop this operation")
    assert _CANCEL_COMMAND_RE.match("do not do this")
    assert not _CANCEL_COMMAND_RE.match("Start a seeded cancel jobs run and keep it executing")
    assert not _CANCEL_COMMAND_RE.match("Show cancellation history for job JOB-SEED-001")


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("change all high priority job to low then change all low priority job to medium", [("high", "low"), ("low", "medium")]),
        ("change all medium priority job to high then change all high priority job to medium", [("medium", "high"), ("high", "medium")]),
        ("change all low priority job to high then change all high priority job to low", [("low", "high"), ("high", "low")]),
        ("change all high priority job to medium then change all medium priority job to low", [("high", "medium"), ("medium", "low")]),
    ],
)
def test_phase19_scenario_119_cascade_prompt_matrix_extracts_two_write_sets(prompt, expected):
    planner = SeededPlaywrightPlanner(_settings())

    assert planner._phase14_cascade_priority_changes(prompt.lower()) == expected


def test_phase19_scenarios_122_123_regression_bank_schema_and_triage_rule():
    bank = _load_bank()
    required = set(bank["schema"]["required_fields"])
    severities = set(bank["schema"]["severity_values"])
    allowed_coverage = set(bank["schema"]["coverage_categories"])
    triage_categories = set(bank["triage_rule"]["coverage_categories"])

    assert required == {
        "source_prompt",
        "observed_failure",
        "expected_behavior",
        "artifact_link",
        "selected_oracle",
        "proposed_oracle",
        "owner",
        "severity",
        "lowest_test_layer",
        "browser_coverage",
        "regression",
    }
    assert {"parser", "route", "seeded-workflow", "browser", "accepted-gap"} <= triage_categories
    assert bank["triage_rule"]["accepted_gap_required_fields"] == [
        "owner",
        "severity",
        "risk",
        "target_date_or_phase",
        "reason",
        "temporary_workaround",
        "blocking_status",
    ]

    for entry in bank["prompts"]:
        assert required <= set(entry)
        assert entry["prompt"] == entry["source_prompt"]
        assert entry["observed_failure"]
        assert entry["expected_behavior"]
        assert entry["owner"]
        assert entry["severity"] in severities
        assert entry["lowest_test_layer"] in {
            "parser",
            "route",
            "pytest_snapshot",
            "seeded-workflow",
            "mocked-browser",
            "seeded-browser",
        }
        assert isinstance(entry["browser_coverage"], bool)
        assert set(entry["coverage"]) <= allowed_coverage
        if entry["browser_coverage"]:
            assert {"mocked-browser", "seeded-browser"} & set(entry["coverage"])
        assert "accepted-gap" not in entry["coverage"]
