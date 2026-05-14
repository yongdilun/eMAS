"""Bundle narrative (approval + completed) helpers."""

from __future__ import annotations

import json

import pytest

from factory_agent.analysis.summary_backend import (
    SummaryAdapter,
    _sanitize_completed_bundle_text,
    awaiting_approval_markdown_from_bundle_ui,
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
async def test_awaiting_approval_bundle_ui_bypasses_llm_and_matches_ui_copy() -> None:
    """Structured bundle: narrative is headline + pointer to in-app table (no job list)."""
    adapter = SummaryAdapter(_settings(summary_backend="auto", openai_api_key="test-key"))
    facts = {
        "intent": "Update medium priority jobs to high",
        "approval": {
            "kind": "approval_required",
            "summary": "Approve writes",
            "count": 2,
            "bundle_ui": {
                "kind": "job_priority_bundle",
                "headline": "2 jobs will be updated from medium to high priority.",
                "previous_priority": "medium",
                "new_priority": "high",
                "rows": [
                    {"job_id": "JOB-A", "previous_priority": "medium", "new_priority": "high"},
                    {"job_id": "JOB-B", "previous_priority": "medium", "new_priority": "high"},
                ],
            },
        },
    }
    r = await adapter.synthesize_bundle_markdown(intent=facts["intent"], kind="awaiting_approval", facts=facts)
    assert r.backend_used == "deterministic"
    assert r.llm_calls == 0
    assert "2 jobs will be updated from medium to high priority." in r.text
    assert "in-app table" in r.text.lower()
    assert "Please approve to continue." in r.text
    assert "JOB-A" not in r.text
    assert "|" not in r.text


def test_awaiting_approval_markdown_from_bundle_ui_helper() -> None:
    md = awaiting_approval_markdown_from_bundle_ui(
        {
            "approval": {
                "bundle_ui": {
                    "kind": "job_priority_bundle",
                    "headline": "1 job will be updated from low to urgent priority.",
                }
            }
        }
    )
    assert md is not None
    assert md.startswith("1 job will be updated")


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


@pytest.mark.asyncio
async def test_completed_job_recap_prefers_write_results_over_stale_read_table() -> None:
    adapter = SummaryAdapter(_settings(summary_backend="auto", openai_api_key="test-key"))
    facts = {
        "intent": "change all medium priority job to high",
        "tool_outputs": [
            {
                "tool_name": "get__jobs",
                "args": {"priority": "medium"},
                "result_excerpt": json.dumps(
                    {
                        "success": True,
                        "data": [
                            {
                                "job_id": "JOB-SEED-002",
                                "priority": "medium",
                                "notes": "seed:P-002:2026-05-27T00:00:00Z:420",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "tool_name": "put__jobs_{id}",
                "args": {"id": "JOB-SEED-002", "priority": "high"},
                "result_excerpt": json.dumps(
                    {
                        "success": True,
                        "data": {
                            "job_id": "JOB-SEED-002",
                            "priority": "high",
                            "product_id": "P-002",
                            "status": "planned",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    r = await adapter.synthesize_bundle_markdown(intent=facts["intent"], kind="completed", facts=facts)

    assert r.backend_used == "deterministic"
    assert "JOB-SEED-002" in r.text
    assert "Priority: **high**" in r.text
    assert "seed:P-002" not in r.text
    assert "| priority" not in r.text.lower()


def test_sanitize_completed_strips_approval_phrases() -> None:
    raw = (
        "Please approve to continue.\n\n"
        "**Success**\n\n"
        "Updated one job.\n"
    )
    cleaned = _sanitize_completed_bundle_text(raw)
    assert "please approve" not in cleaned.lower()
    assert "Updated one job" in cleaned
