"""Single-query live RAG debug harness.

This module is intentionally test-artifact tooling. It reuses the live RAG
evaluation stack, then adds the response-document projection that the frontend
uses for citation chips and Knowledge sources.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORY_AGENT_DIR = REPO_ROOT / "factory-agent"
if str(FACTORY_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_AGENT_DIR))

from factory_agent.config import get_settings  # noqa: E402
from factory_agent.rag.pipeline import RAGPipeline  # noqa: E402
from factory_agent.services import response_document_service  # noqa: E402
from tests.rag_eval.artifact_schema import build_env_fingerprint, now_iso  # noqa: E402
from tests.rag_eval.run_eval import (  # noqa: E402
    _build_retriever,
    _gen_run_id,
    _live_mode_enabled,
    _resolve_base_url,
    _run_case,
)
from tests.rag_eval.variants import DEFAULT_VARIANT_ID, RUN_1_VARIANT_IDS, get_variant, require_phase2_executable  # noqa: E402


DEFAULT_LOTO_QUERY = "According to the LOTO procedure, what steps must workers complete before beginning service or maintenance?"


@dataclass
class QueryDebugOptions:
    query: str = DEFAULT_LOTO_QUERY
    case_id: str = "manual-loto-procedure"
    output_root: Path = REPO_ROOT / "test-artifacts" / "rag-query-debug"
    run_id: str | None = None
    variant_id: str = DEFAULT_VARIANT_ID
    retrieval_top_n: int = 10
    require_live: bool = True


def project_response_document_debug(*, answer: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Project raw RAG output into the UI-facing knowledge/source contracts."""

    clean_answer, segments, citations = response_document_service._knowledge_answer_payload(answer, sources)
    source_list = response_document_service.normalize_source_locators(
        sources,
        fallback_snippet=clean_answer or answer,
    )
    for source in source_list:
        source.setdefault("contract", response_document_service.SOURCE_LOCATOR_CONTRACT)

    citations_by_id = {str(citation.get("citation_id")): citation for citation in citations}
    step_diagnostics = []
    for index, segment in enumerate(segments, start=1):
        citation_ids = [str(item) for item in segment.get("citation_ids") or [] if str(item or "").strip()]
        citation_payloads = [citations_by_id.get(citation_id) for citation_id in citation_ids]
        step_diagnostics.append(
            {
                "step_index": index,
                "text": segment.get("text"),
                "citation_ids": citation_ids,
                "citation_pages": _unique_values(citation.get("page") for citation in citation_payloads if citation),
                "citation_chunk_ids": _unique_values(citation.get("chunk_id") for citation in citation_payloads if citation),
                "citation_text_search": [
                    citation.get("text_search")
                    for citation in citation_payloads
                    if citation and citation.get("text_search")
                ],
                "evidence": [
                    _compact_evidence_payload(item)
                    for citation in citation_payloads
                    if citation
                    for item in citation.get("evidence") or []
                    if isinstance(item, dict)
                ],
            }
        )

    return {
        "knowledge_answer": {
            "answer": clean_answer,
            "segments": segments,
            "citations": citations,
        },
        "source_list": {
            "sources": source_list,
        },
        "diagnostics": {
            "segment_count": len(segments),
            "citation_count": len(citations),
            "source_count": len(source_list),
            "step_diagnostics": step_diagnostics,
        },
    }


def summarize_loto_procedure_projection(projection: dict[str, Any]) -> dict[str, Any]:
    """Small reusable check set for the current LOTO citation issue."""

    segments = projection.get("knowledge_answer", {}).get("segments") or []
    diagnostics = projection.get("diagnostics", {}).get("step_diagnostics") or []
    expected_phrases = [
        "Prepare for shutdown",
        "Shut down the machine",
        "Disconnect or isolate the machine",
        "Apply the lockout or tagout device",
        "Release, restrain, or otherwise render safe",
        "Verify the isolation and deenergization",
    ]
    joined_segments = "\n".join(str(segment.get("text") or "") for segment in segments)
    missing_phrases = [phrase for phrase in expected_phrases if phrase.lower() not in joined_segments.lower()]
    uncited_steps = [
        item.get("step_index")
        for item in diagnostics
        if not item.get("citation_ids")
    ]
    steps_without_exact_evidence = [
        item.get("step_index")
        for item in diagnostics
        if item.get("citation_ids") and not _step_has_exact_or_context_evidence(item)
    ]
    pages_by_step = {
        str(item.get("step_index")): _unique_values(
            [
                *(item.get("citation_pages") or []),
                *[
                    evidence.get("page")
                    for evidence in item.get("evidence") or []
                    if evidence.get("page") not in (None, "")
                ],
            ]
        )
        for item in diagnostics
    }
    steps_missing_expected_pdf_page = [
        int(step_index)
        for step_index, pages in pages_by_step.items()
        if 14 not in pages
    ]
    ok = (
        not missing_phrases
        and not uncited_steps
        and not steps_without_exact_evidence
        and not steps_missing_expected_pdf_page
    )
    return {
        "ok": ok,
        "expected_step_count": 6,
        "observed_segment_count": len(segments),
        "missing_phrases": missing_phrases,
        "uncited_steps": uncited_steps,
        "steps_without_exact_or_context_evidence": steps_without_exact_evidence,
        "steps_missing_expected_pdf_page_14": steps_missing_expected_pdf_page,
        "pages_by_step": pages_by_step,
    }


def run_query_debug(opts: QueryDebugOptions) -> dict[str, Any]:
    return asyncio.run(_run_query_debug_async(opts))


async def _run_query_debug_async(opts: QueryDebugOptions) -> dict[str, Any]:
    variant = get_variant(opts.variant_id)
    require_phase2_executable(variant)
    if opts.require_live and not _live_mode_enabled():
        raise SystemExit(
            "Live RAG query debug is opt-in. Set FACTORY_AGENT_LIVE_RAG=1 "
            "(or FACTORY_AGENT_LIVE_LLM=1) and configure OPENAI_BASE_URL / LLM_BASE_URL."
        )

    settings = get_settings()
    if opts.require_live and not _resolve_base_url(settings):
        raise SystemExit("No OpenAI-compatible base URL is configured. Set OPENAI_BASE_URL or LLM_BASE_URL.")

    run_id = opts.run_id or _gen_run_id()
    output_root = opts.output_root if opts.output_root.is_absolute() else REPO_ROOT / opts.output_root
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    retriever = _build_retriever(variant)
    rag_pipeline = RAGPipeline(retriever=retriever) if retriever is not None else RAGPipeline()
    case = {
        "id": opts.case_id,
        "query": opts.query,
        "expects_sources": True,
    }

    started_at = now_iso()
    t0 = time.perf_counter()
    route_decision, rag_result, agent_response, retrieval_debug, error = await _run_case(
        case=case,
        rag_pipeline=rag_pipeline,
        retriever=retriever,
        variant=variant,
        retrieval_top_n=opts.retrieval_top_n,
    )
    duration_s = time.perf_counter() - t0
    finished_at = now_iso()

    rag_result = rag_result or {}
    projection = project_response_document_debug(
        answer=str(rag_result.get("answer") or ""),
        sources=rag_result.get("sources") if isinstance(rag_result.get("sources"), list) else [],
    )
    loto_summary = summarize_loto_procedure_projection(projection) if "loto" in opts.query.lower() else None
    artifact = {
        "run_id": run_id,
        "case_id": opts.case_id,
        "query": opts.query,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_s": round(duration_s, 4),
        "env": build_env_fingerprint(settings),
        "variant_id": variant.variant_id,
        "variant_config": variant.to_dict(),
        "route_decision": route_decision,
        "rag": rag_result,
        "agent_response": agent_response,
        "retrieval_debug": retrieval_debug,
        "response_document_projection": projection,
        "loto_procedure_projection_summary": loto_summary,
        "error": error,
    }

    artifact_path = run_dir / f"{opts.case_id}.json"
    artifact_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "run_id": run_id,
        "case_id": opts.case_id,
        "query": opts.query,
        "variant_id": variant.variant_id,
        "artifact_path": str(artifact_path.relative_to(REPO_ROOT)),
        "duration_s": artifact["duration_s"],
        "error": error,
        "loto_procedure_projection_summary": loto_summary,
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def _compact_evidence_payload(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "locator_confidence",
        "doc_id",
        "chunk_id",
        "page",
        "page_label",
        "text_search",
        "snippet",
        "pdf_url",
    )
    return {key: item.get(key) for key in keys if item.get(key) not in (None, "", [], {})}


def _unique_values(values: Any) -> list[Any]:
    output = []
    seen = set()
    for value in values:
        if value in (None, "", [], {}):
            continue
        key = json.dumps(value, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _step_has_exact_or_context_evidence(step: dict[str, Any]) -> bool:
    if step.get("citation_text_search"):
        return True
    for evidence in step.get("evidence") or []:
        if evidence.get("locator_confidence") == "exact" or evidence.get("text_search"):
            return True
        if evidence.get("snippet") and evidence.get("page"):
            return True
    return False
