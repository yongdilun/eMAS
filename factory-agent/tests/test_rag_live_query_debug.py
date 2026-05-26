"""Opt-in live single-query RAG debug test.

Enable with:

    FACTORY_AGENT_LIVE_RAG=1
    OPENAI_BASE_URL=http://127.0.0.1:900/v1

Optional:

    FACTORY_AGENT_RAG_QUERY="..."
    FACTORY_AGENT_RAG_QUERY_RUN_ID="debug-loto"
    FACTORY_AGENT_RAG_QUERY_VARIANT="V12"
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


def test_live_rag_loto_query_debug_writes_projection_artifact():
    if not _live_mode_enabled():
        pytest.skip("FACTORY_AGENT_LIVE_RAG / FACTORY_AGENT_LIVE_LLM not set; live RAG query debug is opt-in.")
    if not (os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL")):
        pytest.skip("OPENAI_BASE_URL / LLM_BASE_URL not configured.")

    from tests.rag_eval.query_debug import DEFAULT_LOTO_QUERY, QueryDebugOptions, run_query_debug

    summary = run_query_debug(
        QueryDebugOptions(
            query=os.getenv("FACTORY_AGENT_RAG_QUERY") or DEFAULT_LOTO_QUERY,
            case_id=os.getenv("FACTORY_AGENT_RAG_QUERY_CASE_ID") or "manual-loto-procedure",
            output_root=REPO_ROOT / "test-artifacts" / "rag-query-debug",
            run_id=os.getenv("FACTORY_AGENT_RAG_QUERY_RUN_ID") or None,
            variant_id=os.getenv("FACTORY_AGENT_RAG_QUERY_VARIANT") or "V12",
        )
    )

    assert not summary.get("error"), summary.get("artifact_path")
    if (os.getenv("FACTORY_AGENT_RAG_QUERY") or DEFAULT_LOTO_QUERY) == DEFAULT_LOTO_QUERY:
        loto = summary.get("loto_procedure_projection_summary") or {}
        assert loto.get("observed_segment_count") == 6, summary.get("artifact_path")
        assert loto.get("missing_phrases") == [], summary.get("artifact_path")
        assert loto.get("uncited_steps") == [], summary.get("artifact_path")
        assert loto.get("steps_without_exact_or_context_evidence") == [], summary.get("artifact_path")
        assert loto.get("steps_missing_expected_pdf_page_14") == [], summary.get("artifact_path")
