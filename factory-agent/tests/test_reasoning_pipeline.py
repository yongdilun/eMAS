import pytest

from factory_agent.config import Settings
from factory_agent.planning.reasoning_pipeline import ReasoningPipeline


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
        openai_base_url="http://127.0.0.1:900/v1",
        openai_api_key="local",
    )
    values = base.__dict__.copy()
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_select_tool_respects_retrieval_backend(monkeypatch):
    pipeline = ReasoningPipeline(_settings(tool_selector_backend="retrieval"))

    def _unexpected_build_model(*, component: str):
        raise AssertionError(f"LLM should not be built for {component}")

    monkeypatch.setattr(pipeline, "_build_model", _unexpected_build_model)

    result = await pipeline.select_tool(
        intent="check machine status",
        clause="check machine status",
        candidates=[
            {
                "tool_name": "get__machines_{id}",
                "description": "Get machine by id",
                "prefilled_args": {"id": "5"},
                "missing_args": [],
            }
        ],
    )

    assert result is None


@pytest.mark.asyncio
async def test_extract_facts_respects_deterministic_summary_backend(monkeypatch):
    pipeline = ReasoningPipeline(_settings(tool_result_summary_backend="deterministic"))

    def _unexpected_build_model(*, component: str):
        raise AssertionError(f"LLM should not be built for {component}")

    monkeypatch.setattr(pipeline, "_build_model", _unexpected_build_model)

    result = await pipeline.extract_facts(
        intent="tool_result_summary",
        tool_name="get__products",
        args={},
        result={"data": [{"product_id": "P-100"}, {"product_id": "P-200"}]},
    )

    assert result is not None
    assert result.answer_type == "id_list"
    assert result.ids == ["P-100", "P-200"]


@pytest.mark.asyncio
async def test_extract_facts_uses_llm_for_multi_record_summaries(monkeypatch):
    pipeline = ReasoningPipeline(_settings(tool_result_summary_backend="auto"))
    prompts: list[str] = []

    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeModel:
        async def ainvoke(self, prompt: str):
            prompts.append(prompt)
            return _FakeResponse(
                '{"answer_type":"summary","facts":["Retrieved 4 job records with mixed statuses."],"ids":[],"counts":{"records":4},"warnings":[],"grounding_refs":["$.data[0].job_id"]}'
            )

    monkeypatch.setattr(pipeline, "_build_model", lambda *, component: _FakeModel())

    result = await pipeline.extract_facts(
        intent="tool_result_summary",
        tool_name="get__jobs",
        args={},
        result={
            "data": [
                {"job_id": "JOB-001", "product_id": "P-001", "status": "planned"},
                {"job_id": "JOB-002", "product_id": "P-002", "status": "scheduled"},
                {"job_id": "JOB-003", "product_id": "P-003", "status": "done"},
                {"job_id": "JOB-004", "product_id": "P-004", "status": "planned"},
            ]
        },
    )

    assert result is not None
    assert result.answer_type == "summary"
    assert result.facts == ["Retrieved 4 job records with mixed statuses."]
    assert prompts
    assert "Deterministic baseline" in prompts[0]


@pytest.mark.asyncio
async def test_extract_facts_truncates_large_result_for_llm(monkeypatch):
    pipeline = ReasoningPipeline(_settings(tool_result_summary_backend="auto"))
    prompts: list[str] = []

    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeModel:
        async def ainvoke(self, prompt: str):
            prompts.append(prompt)
            return _FakeResponse(
                '{"answer_type":"summary","facts":["Retrieved many records."],"ids":[],"counts":{"records":12},"warnings":[],"grounding_refs":["$.data[0].id"]}'
            )

    monkeypatch.setattr(pipeline, "_build_model", lambda *, component: _FakeModel())

    large_result = {
        "data": [
            {
                "id": f"REC-{idx:03d}",
                "external_id": f"EXT-{idx:03d}",
                "description": "X" * 500,
                "nested": {"a": 1, "b": 2, "c": 3},
            }
            for idx in range(12)
        ]
    }

    result = await pipeline.extract_facts(
        intent="tool_result_summary",
        tool_name="get__records",
        args={},
        result=large_result,
    )

    assert result is not None
    assert result.facts == ["Retrieved many records."]
    assert prompts
    assert '"truncated": true' in prompts[0].lower()
    assert '"data_count": 12' in prompts[0].lower()


def test_fallback_response_humanizes_structured_fact_text():
    pipeline = ReasoningPipeline(_settings(tool_result_summary_backend="auto"))

    message = pipeline.fallback_response_from_facts(
        facts=type("Facts", (), {
            "answer_type": "summary",
            "facts": ["{'job_id': 'JOB-SEED-001', 'product_id': 'P-001', 'quantity_total': 320, 'quantity_completed': 0, 'priority': 'high', 'deadline': '2026-05-12T08:00:00+08:00', 'status': 'planned'}"],
            "ids": [],
            "counts": {},
            "warnings": [],
            "grounding_refs": [],
        })()
    )

    assert "JOB-SEED-001" in message
    assert "status planned" in message.lower()
    assert "product P-001".lower() in message.lower()
    assert "qty 320" in message.lower()


def test_fallback_response_for_multi_record_summary_mentions_table():
    pipeline = ReasoningPipeline(_settings(tool_result_summary_backend="auto"))

    message = pipeline.fallback_response_from_facts(
        facts=type("Facts", (), {
            "answer_type": "summary",
            "facts": ["JOB-SEED-001 (status planned)"],
            "ids": [],
            "counts": {"records": 26},
            "warnings": [],
            "grounding_refs": [],
        })()
    )

    assert "26 records" in message.lower()
    assert "table below" in message.lower()


@pytest.mark.asyncio
async def test_extract_facts_deterministically_analyzes_deadline_and_quantity_without_llm(monkeypatch):
    pipeline = ReasoningPipeline(_settings(tool_result_summary_backend="deterministic"))

    def _unexpected_build_model(*, component: str):
        raise AssertionError(f"LLM should not be built for {component}")

    monkeypatch.setattr(pipeline, "_build_model", _unexpected_build_model)

    result = await pipeline.extract_facts(
        intent="Show low-priority planned jobs and highlight the earliest deadline and largest quantity.",
        tool_name="get__jobs",
        args={"priority": "low", "status": "planned"},
        result={
            "data": [
                {"job_id": "JOB-SEED-005", "product_id": "P-005", "quantity_total": 520, "deadline": "2026-05-19T08:00:00+08:00"},
                {"job_id": "JOB-SEED-009", "product_id": "P-003", "quantity_total": 140, "deadline": "2026-05-19T08:00:00+08:00"},
                {"job_id": "JOB-SEED-012", "product_id": "P-009", "quantity_total": 240, "deadline": "2026-05-19T08:00:00+08:00"},
                {"job_id": "JOB-SEED-017", "product_id": "P-004", "quantity_total": 180, "deadline": "2026-05-19T08:00:00+08:00"},
                {"job_id": "JOB-SEED-024", "product_id": "P-002", "quantity_total": 480, "deadline": "2026-05-07T08:00:00+08:00"},
            ]
        },
    )

    assert result is not None
    message = pipeline.fallback_response_from_facts(facts=result).lower()
    assert "retrieved 5 records" in message
    assert "earliest deadline: job-seed-024" in message
    assert "largest quantity: job-seed-005" in message
    assert result.counts["analysis"]["dataset"]["row_count"] == 5


@pytest.mark.asyncio
async def test_extract_facts_sanitizes_structured_fact_dump(monkeypatch):
    pipeline = ReasoningPipeline(_settings(tool_result_summary_backend="auto"))

    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeModel:
        async def ainvoke(self, prompt: str):
            del prompt
            return _FakeResponse(
                '{"answer_type":"summary","facts":["{\\"job_id\\": \\"JOB-SEED-001\\", \\"product_id\\": \\"P-001\\", \\"quantity_total\\": 320, \\"quantity_completed\\": 0, \\"priority\\": \\"high\\", \\"deadline\\": \\"2026-05-12T08:00:00+08:00\\", \\"status\\": \\"planned\\"}"],"ids":[],"counts":{"records":26},"warnings":[],"grounding_refs":["$.data[0].job_id"]}'
            )

    monkeypatch.setattr(pipeline, "_build_model", lambda *, component: _FakeModel())

    result = await pipeline.extract_facts(
        intent="tool_result_summary",
        tool_name="get__jobs",
        args={},
        result={"data": [{"job_id": "JOB-SEED-001", "product_id": "P-001"}, {"job_id": "JOB-SEED-002", "product_id": "P-002"}]},
    )

    assert result is not None
    assert result.facts
    assert "JOB-SEED-001" in result.facts[0]
    assert "status planned" in result.facts[0].lower()

