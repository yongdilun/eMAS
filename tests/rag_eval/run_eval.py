"""Run the live RAG evaluation harness.

Usage (from the repo root)::

    # Opt in by setting either env var, plus a real LLM base URL:
    $env:FACTORY_AGENT_LIVE_RAG = "1"
    $env:OPENAI_BASE_URL        = "http://127.0.0.1:900/v1"
    $env:OPENAI_API_KEY         = "local"

    python -m tests.rag_eval.run_eval

    # Optional flags:
    python -m tests.rag_eval.run_eval --cases tests/rag_eval/cases.json `
                                      --output test-artifacts/rag-eval `
                                      --variant V3 `
                                      --filter loto-

This module exposes :func:`run_eval` so the pytest wrapper in
``factory-agent/tests/test_rag_live_llm.py`` can call into the same flow.

The harness:

1. Loads cases from ``tests/rag_eval/cases.json``.
2. Resolves a RAG eval variant config (default: V3).
3. Builds a real :class:`factory_agent.rag.pipeline.RAGPipeline` with the
   selected variant's retrieval/rerank settings.
4. Runs each case directly through the current RAG pipeline. The retired
   Phase5Agent/QueryRouter compatibility layer is intentionally not imported.
5. For each case, runs the pipeline **and** issues a separate
   ``HybridRetriever.retrieve`` call with the same retrieval settings for debug
   logging (top chunks).
6. Writes one JSON artifact per case plus a run-level ``summary.json``.

Failure policy: structural-only checks (answer non-empty, sources present when
a RAG-bearing route is used, hard ``do_not_use_for`` violations) flip
``automated.ok`` to false. Routing mismatches are recorded as warnings, never
hard failures, since real LLM routing is non-deterministic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORY_AGENT_DIR = REPO_ROOT / "factory-agent"
if str(FACTORY_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_AGENT_DIR))

# Imports below need ``factory-agent`` on sys.path, hence the insert above.
from factory_agent.config import get_settings  # noqa: E402
from factory_agent.rag.context_building import rewrite_query_for_retrieval  # noqa: E402
from factory_agent.rag.document_registry import default_source_register_path  # noqa: E402
from factory_agent.rag.ingestion import IngestionEngine  # noqa: E402
from factory_agent.rag.pipeline import RAGPipeline  # noqa: E402
from factory_agent.rag.retrieval import HybridRetriever  # noqa: E402

from tests.rag_eval.audit import build_judge_audit_sample  # noqa: E402
from tests.rag_eval.artifact_schema import (  # noqa: E402
    AutomatedReport,
    CheckResult,
    SEVERITY_FAIL,
    SEVERITY_WARN,
    build_case_artifact,
    build_env_fingerprint,
    build_summary,
    now_iso,
    serialize_rag_result,
    serialize_retrieval_debug,
)
from tests.rag_eval.judge import JudgeConfig, judge_case  # noqa: E402
from tests.rag_eval.scoring import score_case  # noqa: E402
from tests.rag_eval.variants import (  # noqa: E402
    DEFAULT_VARIANT_ID,
    RUN_1_VARIANT_IDS,
    RAGVariantConfig,
    get_variant,
    require_phase2_executable,
)


# ---------------------------------------------------------------------------
# Automated structural checks
# ---------------------------------------------------------------------------


_RAG_BEARING_ROUTES = {"RAG_ONLY", "API_THEN_RAG", "RAG_THEN_API"}


def _evaluate_case(*, case: dict[str, Any], route_decision: dict[str, Any] | None,
                   agent_response: dict[str, Any] | None, retrieval_debug: dict[str, Any],
                   error: str | None) -> AutomatedReport:
    """Run structural-only checks. Avoids any exact substring match on answers."""

    report = AutomatedReport()

    if error:
        report.add(
            CheckResult(
                id="harness_no_exception",
                ok=False,
                severity=SEVERITY_FAIL,
                detail=error,
            )
        )
        return report
    report.add(CheckResult(id="harness_no_exception", ok=True))

    route = (route_decision or {}).get("route")
    route_source = (route_decision or {}).get("route_source")
    answer = (agent_response or {}).get("answer") or ""
    sources = (agent_response or {}).get("sources") or []

    report.add(
        CheckResult(
            id="answer_non_empty",
            ok=isinstance(answer, str) and bool(answer.strip()),
            severity=SEVERITY_FAIL,
            detail=None if answer else "agent_response.answer is empty",
        )
    )

    expects_sources = bool(case.get("expects_sources"))
    if expects_sources and route in _RAG_BEARING_ROUTES:
        report.add(
            CheckResult(
                id="rag_sources_present",
                ok=len(sources) > 0,
                severity=SEVERITY_FAIL,
                detail=None if sources else f"route={route} but no citations returned",
            )
        )
    elif expects_sources and route not in _RAG_BEARING_ROUTES:
        report.add(
            CheckResult(
                id="rag_route_used",
                ok=False,
                severity=SEVERITY_WARN,
                detail=f"case expects RAG sources but route={route}",
            )
        )

    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    if expected_doc_ids and sources:
        seen = {str(s.get("doc_id")) for s in sources if isinstance(s, dict)}
        intersect = expected_doc_ids & seen
        report.add(
            CheckResult(
                id="expected_doc_ids_cited",
                ok=bool(intersect),
                severity=SEVERITY_WARN,
                detail=None if intersect
                else f"expected one of {sorted(expected_doc_ids)}, got {sorted(seen)}",
            )
        )

    routing_expectation = case.get("routing_expectation") or {}
    preferred = set(routing_expectation.get("preferred") or [])
    acceptable = set(routing_expectation.get("acceptable") or [])
    if preferred or acceptable:
        # ``acceptable`` is the broader bucket: route must be in it.
        # ``preferred`` is informational unless ``acceptable`` is empty.
        bucket = acceptable or preferred
        in_bucket = route in bucket if bucket else True
        report.add(
            CheckResult(
                id="routing_acceptable",
                ok=in_bucket,
                severity=SEVERITY_WARN,
                detail=None if in_bucket
                else f"route={route} not in acceptable={sorted(bucket)}; route_source={route_source}",
            )
        )
        if preferred and route not in preferred:
            report.add(
                CheckResult(
                    id="routing_preferred",
                    ok=False,
                    severity=SEVERITY_WARN,
                    detail=f"preferred={sorted(preferred)} but got {route} (route_source={route_source})",
                )
            )

    # Hard exclusion check via doc metadata + case query.
    do_not_use_violation = _detect_do_not_use_violation(case=case, retrieval_debug=retrieval_debug)
    if do_not_use_violation is not None:
        report.add(
            CheckResult(
                id="do_not_use_for_excluded",
                ok=False,
                severity=SEVERITY_FAIL,
                detail=do_not_use_violation,
            )
        )

    return report


def _detect_do_not_use_violation(*, case: dict[str, Any],
                                 retrieval_debug: dict[str, Any]) -> str | None:
    """Return a description if a top retrieved chunk's ``do_not_use_for`` matches the case tag.

    The check is conservative: it only fires when the case is explicitly tagged
    ``do_not_use_for`` AND a top chunk's metadata contains the offending phrase.
    Today the case list only tags ``router-12-realtime-lock-status`` this way.
    """

    if "do_not_use_for" not in (case.get("tags") or []):
        return None
    chunks = retrieval_debug.get("top_chunks") or []
    for ch in chunks:
        # The harness's serialize_retrieval_debug only carries metadata fields it
        # explicitly extracts. ``do_not_use_for`` lives on the original chunk
        # metadata; we surface it here via the snippet check + doc_id mapping
        # is sufficient for the current corpus, so we keep this as a soft signal.
        snippet = (ch.get("snippet") or "").lower()
        if "live machine lock status" in snippet or "real-time permit" in snippet:
            return f"top chunk {ch.get('chunk_id')} matches do_not_use_for cue"
    return None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class RunnerOptions:
    cases_path: Path
    output_root: Path
    case_filter: str | None = None
    run_id: str | None = None
    retrieval_top_n: int = 10
    variant_id: str = DEFAULT_VARIANT_ID
    judge_enabled: bool | None = None
    judge_base_url: str | None = None
    judge_model: str | None = None
    judge_audit_seed: int = 13


def _gen_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _load_cases(path: Path, *, case_filter: str | None) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    cases = raw.get("cases") or []
    if case_filter:
        cases = [c for c in cases if case_filter in str(c.get("id"))]
    if not cases:
        raise SystemExit(f"No cases matched filter={case_filter!r} in {path}")
    return cases


def _live_mode_enabled() -> bool:
    flags = ("FACTORY_AGENT_LIVE_RAG", "FACTORY_AGENT_LIVE_LLM")
    return any(os.getenv(name, "0").strip().lower() in {"1", "true", "yes"} for name in flags)


def _resolve_base_url(settings: Any) -> str | None:
    return (
        getattr(settings, "rag_answer_openai_base_url", None)
        or getattr(settings, "planner_openai_base_url", None)
        or getattr(settings, "openai_base_url", None)
    )


def _build_judge_config(opts: RunnerOptions) -> JudgeConfig:
    config = JudgeConfig.from_env(enabled=opts.judge_enabled)
    return JudgeConfig(
        enabled=config.enabled,
        base_url=opts.judge_base_url or config.base_url,
        model=opts.judge_model or config.model,
        api_key=config.api_key,
        timeout_s=config.timeout_s,
    )


async def _run_case(
    *,
    case: dict[str, Any],
    rag_pipeline: RAGPipeline,
    retriever: HybridRetriever | None,
    variant: RAGVariantConfig,
    retrieval_top_n: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None,
           dict[str, Any], str | None]:
    """Execute a single case. Returns (route_decision, rag, agent_response, retrieval_debug, error)."""

    query = str(case.get("query") or "")
    pipeline_config = variant.to_pipeline_config()
    retrieval_query = rewrite_query_for_retrieval(query) if pipeline_config.query_rewrite else query
    retrieval_settings = {
        **variant.retrieval_settings(),
        "retrieval_query": retrieval_query,
    }
    error: str | None = None
    route_decision: dict[str, Any] | None = None
    rag_result: dict[str, Any] | None = None
    agent_response: dict[str, Any] | None = None

    try:
        response = await rag_pipeline.run(
            query=query,
            session_id=case.get("id"),
            route="RAG_ONLY",
            config=pipeline_config,
        )
        rag_result = serialize_rag_result(response)
        route_decision = {
            "route": rag_result.get("route_used") or "RAG_ONLY",
            "route_source": "rag_pipeline_direct",
            "variant_id": variant.variant_id,
        }
        agent_response = {
            "answer": rag_result.get("answer"),
            "sources": rag_result.get("sources") or [],
            "route": rag_result.get("route_used") or "RAG_ONLY",
            "safety_warning": bool(rag_result.get("safety_warning")),
            "metadata": {
                "route_decision": route_decision,
                "rag_metadata": rag_result.get("metadata") or {},
            },
        }
    except Exception as exc:  # pragma: no cover - defensive harness
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

    # Retrieval debug runs regardless: it provides ground-truth for "what was
    # retrievable" even when the agent path errored or was routed away from RAG.
    retrieval_debug: dict[str, Any]
    if retriever is None:
        retrieval_debug = serialize_retrieval_debug(
            None,
            error="HybridRetriever unavailable (vector_db / bm25 not initialised)",
            retrieval_settings=retrieval_settings,
        )
    else:
        try:
            scored = retriever.retrieve(
                query=retrieval_query,
                route="RAG_ONLY",
                vector_top_k=pipeline_config.vector_top_k,
                keyword_top_k=pipeline_config.keyword_top_k,
                fusion_top_k=pipeline_config.fusion_top_k,
                expand_neighbors=pipeline_config.expand_neighbors,
                retrieval_mode=pipeline_config.retrieval_mode,
            )
            retrieval_debug = serialize_retrieval_debug(
                scored,
                top_n=retrieval_top_n,
                retrieval_settings=retrieval_settings,
            )
        except Exception as exc:
            retrieval_debug = serialize_retrieval_debug(
                None,
                error=f"{type(exc).__name__}: {exc}",
                retrieval_settings=retrieval_settings,
            )

    return route_decision, rag_result, agent_response, retrieval_debug, error


def _maybe_judge_case(
    *,
    case: dict[str, Any],
    agent_response: dict[str, Any] | None,
    rag_result: dict[str, Any] | None,
    retrieval_debug: dict[str, Any] | None,
    scoring: dict[str, Any],
    judge_config: JudgeConfig,
    judge_runner: Any = judge_case,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Run the optional judge only for borderline cases."""

    if not judge_config.enabled:
        return False, None, None
    if not scoring.get("borderline"):
        return False, None, None
    try:
        result = judge_runner(
            case=case,
            agent_response=agent_response,
            rag_result=rag_result,
            retrieval_debug=retrieval_debug,
            scoring=scoring,
            config=judge_config,
        )
    except Exception as exc:  # pragma: no cover - live judge defensive path
        return True, None, f"{type(exc).__name__}: {exc}"
    return True, result, None


def _ensure_augmented_index_ready(variant: RAGVariantConfig) -> None:
    if not variant.document_augmentation:
        return
    paths = variant.index_paths()
    print(
        "[rag-eval] ensuring augmented retrieval index "
        f"vector_db={paths['vector_db_path']} bm25={paths['bm25_path']}"
    )
    engine = IngestionEngine(
        db_path=paths["vector_db_path"],
        bm25_path=paths["bm25_path"],
        document_augmentation=True,
    )
    engine.run_full_ingestion(str(default_source_register_path()))


def _build_retriever(variant: RAGVariantConfig) -> HybridRetriever | None:
    """Instantiate ``HybridRetriever`` if the persisted indexes look usable.

    The retriever's ``__init__`` only logs warnings when the vector_db / bm25
    paths are missing; we still want to attempt construction so the artifact
    captures whatever ChromaDB returns. If construction itself raises we
    record the error in ``retrieval_debug.error`` instead.
    """

    try:
        paths = variant.index_paths()
        return HybridRetriever(
            db_path=paths["vector_db_path"],
            bm25_path=paths["bm25_path"],
            document_augmentation=variant.document_augmentation,
        )
    except Exception:
        return None


async def _run_async(opts: RunnerOptions) -> dict[str, Any]:
    try:
        variant = get_variant(opts.variant_id)
        require_phase2_executable(variant)
    except (ValueError, NotImplementedError) as exc:
        raise SystemExit(str(exc)) from exc
    variant_config = variant.to_dict()
    judge_config = _build_judge_config(opts)

    if not _live_mode_enabled():
        raise SystemExit(
            "Live RAG eval is opt-in. Set FACTORY_AGENT_LIVE_RAG=1 (or "
            "FACTORY_AGENT_LIVE_LLM=1) and provide an OpenAI-compatible "
            "base URL via OPENAI_BASE_URL / LLM_BASE_URL."
        )

    settings = get_settings()
    base_url = _resolve_base_url(settings)
    if not base_url:
        raise SystemExit(
            "No OpenAI-compatible base URL is configured. Set OPENAI_BASE_URL "
            "or LLM_BASE_URL (and the matching API key) before running the "
            "harness."
        )

    cases = _load_cases(opts.cases_path, case_filter=opts.case_filter)
    run_id = opts.run_id or _gen_run_id()
    run_dir = opts.output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    env = build_env_fingerprint(settings)

    _ensure_augmented_index_ready(variant)
    retriever = _build_retriever(variant)
    if retriever is None and variant.document_augmentation:
        raise SystemExit("Document augmentation variant could not initialize the augmented retriever")
    rag_pipeline = RAGPipeline(retriever=retriever) if retriever is not None else RAGPipeline()

    started_at = now_iso()
    case_results: list[dict[str, Any]] = []

    print(
        f"[rag-eval] run_id={run_id} variant={variant.variant_id} "
        f"cases={len(cases)} judge={'on' if judge_config.enabled else 'off'} output={run_dir}"
    )

    for idx, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or f"case-{idx}")
        print(f"[rag-eval] ({idx}/{len(cases)}) {case_id} :: {case.get('query')}")

        case_started_iso = now_iso()
        t0 = time.perf_counter()
        route_decision, rag_result, agent_response, retrieval_debug, error = await _run_case(
            case=case,
            rag_pipeline=rag_pipeline,
            retriever=retriever,
            variant=variant,
            retrieval_top_n=opts.retrieval_top_n,
        )
        duration_s = time.perf_counter() - t0
        case_finished_iso = now_iso()

        report = _evaluate_case(
            case=case,
            route_decision=route_decision,
            agent_response=agent_response,
            retrieval_debug=retrieval_debug,
            error=error,
        )
        scoring = score_case(
            case=case,
            agent_response=agent_response,
            rag_result=rag_result,
            retrieval_debug=retrieval_debug,
            automated=report.to_dict(),
        )
        judge_requested, judge_result, judge_error = _maybe_judge_case(
            case=case,
            agent_response=agent_response,
            rag_result=rag_result,
            retrieval_debug=retrieval_debug,
            scoring=scoring,
            judge_config=judge_config,
        )

        artifact = build_case_artifact(
            run_id=run_id,
            variant_id=variant.variant_id,
            variant_config=variant_config,
            case=case,
            query=str(case.get("query") or ""),
            started_at=case_started_iso,
            finished_at=case_finished_iso,
            duration_s=duration_s,
            env=env,
            route_decision=route_decision,
            rag_result=rag_result,
            agent_response=agent_response,
            retrieval_debug=retrieval_debug,
            automated=report,
            scoring=scoring,
            judge_requested=judge_requested,
            judge_result=judge_result,
            judge_error=judge_error,
            error=error,
        )

        artifact_path = run_dir / f"{case_id}.json"
        artifact_path.write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        artifact["_artifact_path"] = str(artifact_path.relative_to(REPO_ROOT))
        case_results.append(artifact)

        status = "OK" if report.ok else "FAIL"
        warn_count = len(report.warnings)
        judge_status = "judge=skipped"
        if judge_requested:
            judge_status = "judge=ok" if judge_result is not None else "judge=error"
        print(
            f"[rag-eval]    -> {status} score={scoring['rule_score']} "
            f"borderline={scoring['borderline']} {judge_status} "
            f"(warnings={warn_count}) artifact={artifact_path.name}"
        )

    finished_at = now_iso()
    judge_audit_path: str | None = None
    if judge_config.enabled:
        audit_payload = build_judge_audit_sample(
            case_results,
            seed=opts.judge_audit_seed,
        )
        audit_path = run_dir / "judge_audit_sample.json"
        audit_path.write_text(
            json.dumps(audit_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        judge_audit_path = str(audit_path.relative_to(REPO_ROOT))

    summary = build_summary(
        run_id=run_id,
        variant_id=variant.variant_id,
        variant_config=variant_config,
        started_at=started_at,
        finished_at=finished_at,
        env=env,
        case_results=case_results,
        judge_audit_path=judge_audit_path,
    )
    summary_path = run_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"[rag-eval] done. summary={summary_path} "
        f"pass={summary['totals']['automated_pass']}/{summary['totals']['cases']} "
        f"warnings={summary['totals']['warnings']}"
    )
    return summary


def run_eval(opts: RunnerOptions) -> dict[str, Any]:
    """Synchronous entrypoint used by both the CLI and the pytest wrapper."""

    return asyncio.run(_run_async(opts))


def _parse_args(argv: list[str] | None = None) -> RunnerOptions:
    parser = argparse.ArgumentParser(description="Live RAG evaluation harness")
    parser.add_argument(
        "--cases",
        type=Path,
        default=REPO_ROOT / "tests" / "rag_eval" / "cases.json",
        help="Path to cases.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "test-artifacts" / "rag-eval",
        help="Output root for artifacts (a per-run subfolder is created).",
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="Substring filter on case id (e.g. 'loto-' or 'router-').",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override the auto-generated run id (e.g. for reproducible artifacts).",
    )
    parser.add_argument(
        "--retrieval-top-n",
        type=int,
        default=10,
        help="How many top retrieved chunks to log per case (debug only).",
    )
    parser.add_argument(
        "--variant",
        default=DEFAULT_VARIANT_ID,
        choices=RUN_1_VARIANT_IDS,
        help="RAG eval variant ID to execute.",
    )
    parser.add_argument(
        "--judge",
        dest="judge_enabled",
        action="store_true",
        default=None,
        help="Enable optional LLM judge for borderline cases only.",
    )
    parser.add_argument(
        "--no-judge",
        dest="judge_enabled",
        action="store_false",
        help="Disable optional LLM judge even if judge env vars are set.",
    )
    parser.add_argument(
        "--judge-base-url",
        default=None,
        help="OpenAI-compatible judge base URL. Defaults to http://127.0.0.1:900/v1.",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Judge model name. Defaults to Qwen2.5-7B-Instruct-Q4_K_M.",
    )
    parser.add_argument(
        "--judge-audit-seed",
        type=int,
        default=13,
        help="Random seed for judge_audit_sample.json selection.",
    )
    args = parser.parse_args(argv)
    return RunnerOptions(
        cases_path=args.cases,
        output_root=args.output,
        case_filter=args.filter,
        run_id=args.run_id,
        retrieval_top_n=args.retrieval_top_n,
        variant_id=args.variant,
        judge_enabled=args.judge_enabled,
        judge_base_url=args.judge_base_url,
        judge_model=args.judge_model,
        judge_audit_seed=args.judge_audit_seed,
    )


def main(argv: list[str] | None = None) -> int:
    opts = _parse_args(argv)
    summary = run_eval(opts)
    # Exit non-zero only when a structural check fails. Routing warnings do
    # not flip the exit code so reviewers can run the harness in CI without
    # spurious failures from LLM non-determinism.
    return 0 if summary["totals"]["automated_fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
