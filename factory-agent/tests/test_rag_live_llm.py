"""Pytest wrapper around the live RAG evaluation harness.

This test is opt-in. It is **skipped** unless::

    FACTORY_AGENT_LIVE_RAG = 1   # or FACTORY_AGENT_LIVE_LLM=1
    OPENAI_BASE_URL        = http://...    # or LLM_BASE_URL

When enabled, it loads ``tests/rag_eval/cases.json``, drives every case through
the current RAG evaluation harness, and writes JSON
artifacts under ``test-artifacts/rag-eval/<run_id>/`` (see
``tests/rag_eval/README.md``).

The pytest assertion is intentionally lenient: it only fails when a
**structural** check fails (e.g. the harness raised, the agent returned an
empty answer, or sources were missing on a RAG-bearing route). Routing
mismatches against the soft expectations in ``cases.json`` are recorded as
warnings inside each artifact for manual review.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _live_mode_enabled() -> bool:
    flags = ("FACTORY_AGENT_LIVE_RAG", "FACTORY_AGENT_LIVE_LLM")
    return any(os.getenv(name, "0").strip().lower() in {"1", "true", "yes"} for name in flags)


@pytest.mark.asyncio
async def test_live_rag_eval_writes_artifacts():
    if not _live_mode_enabled():
        pytest.skip(
            "FACTORY_AGENT_LIVE_RAG / FACTORY_AGENT_LIVE_LLM not set; live RAG eval is opt-in."
        )
    if not (os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL")):
        pytest.skip("OPENAI_BASE_URL / LLM_BASE_URL not configured.")

    # Imports are local so collection still works in non-live environments.
    from tests.rag_eval.run_eval import RunnerOptions, run_eval

    opts = RunnerOptions(
        cases_path=REPO_ROOT / "tests" / "rag_eval" / "cases.json",
        output_root=REPO_ROOT / "test-artifacts" / "rag-eval",
        case_filter=os.getenv("FACTORY_AGENT_RAG_EVAL_FILTER") or None,
        run_id=os.getenv("FACTORY_AGENT_RAG_EVAL_RUN_ID") or None,
    )

    summary = run_eval(opts)

    totals = summary.get("totals") or {}
    assert totals.get("cases", 0) >= 10, "expected at least 10 evaluation cases"
    # Hard fail only on structural problems; routing warnings are tolerated.
    failed = totals.get("automated_fail", 0)
    assert failed == 0, (
        f"{failed} case(s) failed structural checks; inspect "
        f"test-artifacts/rag-eval/{summary.get('run_id')}/"
    )
