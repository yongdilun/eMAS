"""Bundle narrative (approval + completed) helpers."""

from __future__ import annotations

import json

import pytest

from factory_agent.analysis.summary_backend import (
    SummaryAdapter,
    _sanitize_completed_bundle_text,
)
from factory_agent.config import Settings


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
    )
    values = base.__dict__.copy()
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_deterministic_completed_job_recap_from_tool_outputs() -> None:
    adapter = SummaryAdapter(_settings(summary_backend="deterministic"))
    facts = {
        "intent": "change all low priority job to high",
        "tool_outputs": [
            {
                "tool_name": "put__jobs_{id}",
                "args": {"id": "JOB-SEED-005", "priority": "high"},
                "result_excerpt": json.dumps(
                    {
                        "success": True,
                        "data": {
                            "job_id": "JOB-SEED-005",
                            "priority": "high",
                            "product_id": "P-005",
                            "status": "planned",
                            "deadline": "2026-06-03T08:00:00+08:00",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "tool_name": "put__jobs_{id}",
                "args": {"id": "JOB-SEED-009", "priority": "high"},
                "result_excerpt": json.dumps(
                    {
                        "success": True,
                        "data": {
                            "job_id": "JOB-SEED-009",
                            "priority": "high",
                            "product_id": "P-003",
                            "status": "planned",
                            "deadline": "2026-06-03T08:00:00+08:00",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    r = await adapter.synthesize_bundle_markdown(intent=facts["intent"], kind="completed", facts=facts)
    assert r.backend_used == "deterministic"
    assert "**Success**" in r.text
    assert "JOB-SEED-005" in r.text and "JOB-SEED-009" in r.text
    assert "Updated **2** job(s)" in r.text
    assert "please approve" not in r.text.lower()


def test_sanitize_completed_strips_approval_phrases() -> None:
    raw = (
        "Please approve to continue.\n\n"
        "**Success**\n\n"
        "Updated one job.\n"
    )
    cleaned = _sanitize_completed_bundle_text(raw)
    assert "please approve" not in cleaned.lower()
    assert "Updated one job" in cleaned
