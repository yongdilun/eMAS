"""Judge reliability audit sample selection."""

from __future__ import annotations

import math
import random
from typing import Any


def build_judge_audit_sample(
    case_results: list[dict[str, Any]],
    *,
    seed: int = 13,
) -> dict[str, Any]:
    """Select a reproducible manual-audit sample from judged artifacts."""

    judged = [
        result
        for result in case_results
        if result.get("judge_result") is not None or result.get("judge_error")
    ]
    target_min = max(20, math.ceil(len(judged) * 0.10)) if judged else 0

    if len(judged) <= 20:
        selected = judged
    else:
        selected = _select_large_sample(judged, target_min=target_min, seed=seed)

    samples = [_sample_entry(result) for result in selected]
    return {
        "sample_schema_version": 1,
        "selection_seed": seed,
        "judged_count": len(judged),
        "target_min": target_min,
        "sample_size": len(samples),
        "selection_notes": [
            "Includes all judged answers for small smoke runs with fewer than 20 judged answers.",
            "For larger runs, target is at least 20 judged answers or 10 percent of judged answers, whichever is larger.",
            "Selection tries to include pass, fail, and borderline buckets, safety cases, citation-sensitive cases, and at least three variants when available.",
        ],
        "samples": samples,
    }


def _select_large_sample(
    judged: list[dict[str, Any]],
    *,
    target_min: int,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()

    def add(result: dict[str, Any]) -> None:
        key = _result_key(result)
        if key not in selected_keys:
            selected_keys.add(key)
            selected.append(result)

    buckets = {
        "pass": [r for r in judged if _judge_bucket(r) == "pass"],
        "fail": [r for r in judged if _judge_bucket(r) == "fail"],
        "borderline": [r for r in judged if _judge_bucket(r) == "borderline"],
    }
    for bucket_items in buckets.values():
        if bucket_items:
            add(rng.choice(bucket_items))

    for result in _sample_from_group(
        [r for r in judged if _is_safety_related(r)],
        count=5,
        rng=rng,
    ):
        add(result)

    for result in _sample_from_group(
        [r for r in judged if _is_citation_sensitive(r)],
        count=5,
        rng=rng,
    ):
        add(result)

    by_variant: dict[str, list[dict[str, Any]]] = {}
    for result in judged:
        by_variant.setdefault(str(result.get("variant_id") or "unknown"), []).append(result)
    for variant_id in sorted(by_variant)[:3]:
        add(rng.choice(by_variant[variant_id]))

    remaining = [r for r in judged if _result_key(r) not in selected_keys]
    rng.shuffle(remaining)
    while len(selected) < target_min and remaining:
        add(remaining.pop())
    return selected


def _sample_from_group(
    group: list[dict[str, Any]],
    *,
    count: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    if len(group) <= count:
        return list(group)
    return rng.sample(group, count)


def _sample_entry(result: dict[str, Any]) -> dict[str, Any]:
    case = result.get("case") or {}
    response = result.get("agent_response") or {}
    rag = result.get("rag") or {}
    answer = response.get("answer") or rag.get("answer") or ""
    sources = response.get("sources") or rag.get("sources") or []
    return {
        "case_id": result.get("case_id"),
        "variant_id": result.get("variant_id"),
        "query": result.get("query") or case.get("query"),
        "question_type": case.get("question_type"),
        "expects_safety_warning": bool(case.get("expects_safety_warning")),
        "expected_source": case.get("expected_source") or {},
        "rule_score": result.get("rule_score"),
        "borderline": result.get("borderline"),
        "borderline_reasons": result.get("borderline_reasons") or [],
        "serious_failures": result.get("serious_failures") or [],
        "judge_bucket": _judge_bucket(result),
        "judge_result": result.get("judge_result"),
        "judge_error": result.get("judge_error"),
        "answer": answer,
        "cited_sources": _compact_sources(sources),
    }


def _judge_bucket(result: dict[str, Any]) -> str:
    judge = result.get("judge_result") or {}
    if result.get("judge_error"):
        return "fail"
    if judge.get("serious_failure"):
        return "fail"
    numeric_scores = [
        judge.get("correctness"),
        judge.get("completeness"),
        judge.get("faithfulness"),
        judge.get("citation_quality"),
        judge.get("safety"),
    ]
    if any(isinstance(score, int) and score <= 2 for score in numeric_scores):
        return "fail"
    if all(isinstance(score, int) and score >= 4 for score in numeric_scores):
        return "pass"
    return "borderline"


def _is_safety_related(result: dict[str, Any]) -> bool:
    case = result.get("case") or {}
    tags = {str(tag).lower() for tag in case.get("tags") or []}
    return bool(case.get("expects_safety_warning")) or "safety" in tags


def _is_citation_sensitive(result: dict[str, Any]) -> bool:
    case = result.get("case") or {}
    expected_source = case.get("expected_source") or {}
    return bool(
        case.get("expects_sources")
        and (
            expected_source.get("doc_id")
            or expected_source.get("page")
            or expected_source.get("pages")
            or expected_source.get("section")
        )
    )


def _compact_sources(sources: Any) -> list[dict[str, Any]]:
    if not isinstance(sources, list):
        return []
    compact: list[dict[str, Any]] = []
    for source in sources[:6]:
        if not isinstance(source, dict):
            continue
        compact.append(
            {
                "source_number": source.get("source_number"),
                "doc_id": source.get("doc_id"),
                "page": source.get("page"),
                "page_start": source.get("page_start"),
                "page_end": source.get("page_end"),
                "section_title": source.get("section_title"),
                "section_path": source.get("section_path"),
                "snippet": source.get("snippet"),
            }
        )
    return compact


def _result_key(result: dict[str, Any]) -> str:
    return f"{result.get('variant_id')}::{result.get('case_id')}"
