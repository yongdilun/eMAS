from __future__ import annotations

import json
import math
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FACTORY_AGENT_ROOT = REPO_ROOT / "factory-agent"
sys.path.insert(0, str(FACTORY_AGENT_ROOT))

from factory_agent.planning.intent import split_user_intents  # noqa: E402
from factory_agent.planning.semantic_intake import (  # noqa: E402
    DeterministicFallbackSemanticIntakeProposer,
    _extract_json_object,
    _normalize_llm_items,
)


MODEL = "bartowski/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M"
BASE_URL = "http://127.0.0.1:901/v1"
OUT_DIR = REPO_ROOT / ".tmp" / "lightweight-splitter-eval"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    prompt: str
    expected_roles: list[str]
    must_contain: list[str]
    critical_roles: list[str]


CASES = [
    EvalCase(
        "simple-machine-status",
        "Show machine M-CNC-01 status.",
        ["required_requirement"],
        ["M-CNC-01", "status"],
        ["required_requirement"],
    ),
    EvalCase(
        "filtered-job-list",
        "List low priority jobs sorted by deadline ascending, limit 3.",
        ["required_requirement"],
        ["low priority jobs", "deadline", "limit 3"],
        ["required_requirement"],
    ),
    EvalCase(
        "document-rag-loto",
        "Use LOTO procedure documents to explain lockout steps for machine M-CNC-01.",
        ["required_requirement"],
        ["LOTO", "lockout", "M-CNC-01"],
        ["required_requirement"],
    ),
    EvalCase(
        "job-priority-mutation",
        "Change job JOB-BENCH-001 priority to high.",
        ["mutation_or_approval_request"],
        ["JOB-BENCH-001", "priority", "high"],
        ["mutation_or_approval_request"],
    ),
    EvalCase(
        "machine-active-job-cascade",
        "Show machine M-CNC-01 status, then if it has an active job show that job status.",
        ["required_requirement", "conditional_branch"],
        ["M-CNC-01", "active job", "job status"],
        ["required_requirement", "conditional_branch"],
    ),
    EvalCase(
        "conditional-follow-up",
        "Check machine M-CNC-01; if it is running, show the active job details.",
        ["required_requirement", "conditional_branch"],
        ["M-CNC-01", "running", "active job"],
        ["required_requirement", "conditional_branch"],
    ),
    EvalCase(
        "formatting-table",
        "Show machine M-CNC-01 status and answer in one compact table.",
        ["required_requirement", "formatting_instruction"],
        ["M-CNC-01", "status", "table"],
        ["required_requirement", "formatting_instruction"],
    ),
    EvalCase(
        "missing-machine-id",
        "Show the machine status.",
        ["clarification_need"],
        ["machine", "status"],
        ["clarification_need"],
    ),
    EvalCase(
        "pronoun-current-job-deadline",
        "For machine M-CNC-01, show its current job and then show its deadline.",
        ["required_requirement", "conditional_branch"],
        ["M-CNC-01", "current job", "deadline"],
        ["required_requirement", "conditional_branch"],
    ),
    EvalCase(
        "read-job-product-summary",
        "Read job JOB-SEED-001. If it has a product, read that product too and summarize both.",
        ["required_requirement", "conditional_branch", "answer_instruction"],
        ["JOB-SEED-001", "product", "summarize"],
        ["required_requirement", "conditional_branch", "answer_instruction"],
    ),
    EvalCase(
        "job-status-short-table",
        "Show job JOB-SEED-001 status in a short table.",
        ["required_requirement", "formatting_instruction"],
        ["JOB-SEED-001", "status", "table"],
        ["required_requirement", "formatting_instruction"],
    ),
    EvalCase(
        "machine-status-explain",
        "Show machine M-CNC-01 status and explain what it means.",
        ["required_requirement", "answer_instruction"],
        ["M-CNC-01", "status", "explain"],
        ["required_requirement", "answer_instruction"],
    ),
    EvalCase(
        "bulk-priority-change-approval",
        "List medium priority jobs, then change those jobs to high priority. Show what would change and ask approval before applying.",
        ["required_requirement", "mutation_or_approval_request"],
        ["medium priority jobs", "high priority", "approval"],
        ["required_requirement", "mutation_or_approval_request"],
    ),
    EvalCase(
        "field-sort-limit-continuation",
        "List low priority jobs, only job id and deadline, sorted by deadline ascending, limit 3.",
        ["required_requirement"],
        ["low priority jobs", "job id", "deadline", "limit 3"],
        ["required_requirement"],
    ),
    EvalCase(
        "blocked-row-condition",
        "List the next 3 low-priority jobs sorted by deadline with only job id, status, priority, and deadline. If any listed job is blocked, explain why before suggesting any update.",
        ["required_requirement", "conditional_branch"],
        ["low-priority jobs", "blocked", "explain why"],
        ["required_requirement", "conditional_branch"],
    ),
    EvalCase(
        "machine-result-job-id",
        "Check machine M-CNC-01 status. If the machine result includes a job id, read that job.",
        ["required_requirement", "conditional_branch"],
        ["M-CNC-01", "job id", "read that job"],
        ["required_requirement", "conditional_branch"],
    ),
    EvalCase(
        "machine-result-job-cause",
        "Check machine M-CNC-01 status. If the machine result includes a job id, read that job and explain the cause.",
        ["required_requirement", "conditional_branch", "answer_instruction"],
        ["M-CNC-01", "job id", "explain the cause"],
        ["required_requirement", "conditional_branch", "answer_instruction"],
    ),
    EvalCase(
        "unsupported-destructive-action",
        "Perform an unsafe unsupported destructive factory action.",
        ["mutation_or_approval_request"],
        ["unsafe", "destructive"],
        ["mutation_or_approval_request"],
    ),
    EvalCase(
        "multi-read-with-formatting",
        "Show machine M-CNC-01 status and job JOB-BENCH-001 status, then summarize both in bullets.",
        ["required_requirement", "required_requirement", "answer_instruction", "formatting_instruction"],
        ["M-CNC-01", "JOB-BENCH-001", "summarize", "bullets"],
        ["required_requirement", "answer_instruction", "formatting_instruction"],
    ),
    EvalCase(
        "approval-preview-before-apply",
        "Find low priority jobs due this week and change them to medium priority after showing a preview for approval.",
        ["required_requirement", "mutation_or_approval_request"],
        ["low priority jobs", "medium priority", "preview", "approval"],
        ["required_requirement", "mutation_or_approval_request"],
    ),
]


def current_splitter(case: EvalCase) -> dict[str, Any]:
    started = time.perf_counter()
    prepared = [item.description for item in split_user_intents(case.prompt)]
    result = DeterministicFallbackSemanticIntakeProposer().propose(
        case.prompt,
        prepared_clauses=prepared,
    )
    duration_ms = (time.perf_counter() - started) * 1000
    return {
        "items": [item.model_dump(mode="json") for item in result.items],
        "duration_ms": duration_ms,
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "error": None,
    }


def llm_splitter(case: EvalCase) -> dict[str, Any]:
    prompt = build_llm_splitter_prompt(case.prompt)
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You split factory assistant requests into safe semantic intake items. Return JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 640,
    }
    started = time.perf_counter()
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        duration_ms = (time.perf_counter() - started) * 1000
        content = raw["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content)
        if not isinstance(parsed, dict):
            raise ValueError(f"invalid JSON content: {content[:200]}")
        items = _normalize_llm_items(parsed.get("items") or [])
        return {
            "items": items,
            "duration_ms": duration_ms,
            "usage": raw.get("usage") or estimated_usage(prompt, content),
            "error": None,
            "raw_content": content,
        }
    except Exception as exc:
        return {
            "items": [],
            "duration_ms": (time.perf_counter() - started) * 1000,
            "usage": estimated_usage(prompt, ""),
            "error": f"{type(exc).__name__}: {exc}",
        }


def build_llm_splitter_prompt(user_request: str) -> str:
    return (
        "Split the raw user request into semantic intake items for a factory agent.\n"
        "Return exactly one JSON object with key items.\n"
        "Each item must have: id, role, text, parent_item_id, condition, child_intent, applies_to_item_ids, reason, diagnostics.\n"
        "Allowed roles: required_requirement, conditional_branch, answer_instruction, formatting_instruction, clarification_need, mutation_or_approval_request.\n"
        "Rules:\n"
        "- read/show/check/get/list/status with entity/id/filter => required_requirement.\n"
        "- if/when/for each dependent follow-up => conditional_branch.\n"
        "- explain/summarize/why/what it means without a new read => answer_instruction.\n"
        "- table/bullets/brief/formatting only => formatting_instruction.\n"
        "- change/update/delete/cancel/approve/apply => mutation_or_approval_request.\n"
        "- if user asks for a singular machine/job/product status without an id or bound referent => clarification_need.\n"
        "- preserve all clauses, same order, no tool names, no execution.\n"
        f"User request: {json.dumps(user_request)}"
    )


def estimated_usage(prompt: str, content: str) -> dict[str, int]:
    prompt_tokens = math.ceil(len(prompt) / 4)
    completion_tokens = math.ceil(len(content) / 4)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def score_case(case: EvalCase, result: dict[str, Any]) -> dict[str, Any]:
    items = result["items"]
    roles = [str(item.get("role") or "") for item in items]
    role_score = lcs_len(roles, case.expected_roles) / max(len(case.expected_roles), len(roles), 1)
    count_score = max(0.0, 1.0 - abs(len(items) - len(case.expected_roles)) / max(len(case.expected_roles), 1))
    text = " ".join(str(item.get("text") or "") for item in items).lower()
    coverage_hits = [needle for needle in case.must_contain if needle.lower() in text]
    coverage_score = len(coverage_hits) / max(len(case.must_contain), 1)
    critical_hits = [role for role in case.critical_roles if role in roles]
    critical_score = len(set(critical_hits)) / max(len(set(case.critical_roles)), 1)
    invalid_penalty = 0.25 if result.get("error") else 0.0
    accuracy = max(
        0.0,
        (0.4 * role_score) + (0.2 * count_score) + (0.25 * coverage_score) + (0.15 * critical_score) - invalid_penalty,
    )
    return {
        "case_id": case.case_id,
        "expected_roles": case.expected_roles,
        "actual_roles": roles,
        "item_texts": [str(item.get("text") or "") for item in items],
        "role_score": round(role_score, 4),
        "count_score": round(count_score, 4),
        "coverage_score": round(coverage_score, 4),
        "critical_score": round(critical_score, 4),
        "accuracy": round(accuracy, 4),
        "coverage_hits": coverage_hits,
        "duration_ms": round(float(result["duration_ms"]), 2),
        "usage": result.get("usage") or {},
        "error": result.get("error"),
    }


def lcs_len(a: list[str], b: list[str]) -> int:
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, left in enumerate(a, start=1):
        for j, right in enumerate(b, start=1):
            dp[i][j] = dp[i - 1][j - 1] + 1 if left == right else max(dp[i - 1][j], dp[i][j - 1])
    return dp[-1][-1]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_tokens = sum(int(row["usage"].get("total_tokens") or 0) for row in rows)
    prompt_tokens = sum(int(row["usage"].get("prompt_tokens") or 0) for row in rows)
    completion_tokens = sum(int(row["usage"].get("completion_tokens") or 0) for row in rows)
    return {
        "cases": len(rows),
        "avg_accuracy": round(sum(row["accuracy"] for row in rows) / len(rows), 4),
        "perfect_cases": sum(1 for row in rows if row["accuracy"] >= 0.999),
        "cases_ge_0_8": sum(1 for row in rows if row["accuracy"] >= 0.8),
        "errors": sum(1 for row in rows if row["error"]),
        "avg_duration_ms": round(sum(row["duration_ms"] for row in rows) / len(rows), 2),
        "p95_duration_ms": percentile([row["duration_ms"] for row in rows], 0.95),
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "avg_tokens_per_case": round(total_tokens / len(rows), 2),
        "local_external_api_cost_usd": 0.0,
    }


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil((len(ordered) - 1) * p))
    return round(float(ordered[index]), 2)


def decision(current: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    accuracy_delta = llm["avg_accuracy"] - current["avg_accuracy"]
    latency_delta_ms = llm["avg_duration_ms"] - current["avg_duration_ms"]
    if llm["errors"] > 0:
        verdict = "do_not_upgrade"
        reason = "lightweight LLM produced invalid/error cases"
    elif accuracy_delta >= 0.03 and llm["avg_duration_ms"] <= 1500:
        verdict = "upgrade_worth_pilot"
        reason = "accuracy improved enough while latency stayed acceptable"
    elif accuracy_delta >= 0.03:
        verdict = "accuracy_better_but_latency_risk"
        reason = "accuracy improved, but latency is high for default semantic intake"
    elif abs(accuracy_delta) < 0.03:
        verdict = "not_worth_default_upgrade"
        reason = "accuracy is roughly tied, but LLM adds latency and token cost"
    else:
        verdict = "do_not_upgrade"
        reason = "lightweight LLM accuracy is lower than current splitter"
    return {
        "verdict": verdict,
        "reason": reason,
        "accuracy_delta": round(accuracy_delta, 4),
        "latency_delta_ms": round(latency_delta_ms, 2),
    }


def write_markdown(payload: dict[str, Any]) -> None:
    lines = [
        "# Lightweight LLM Splitter Evaluation",
        "",
        f"- Model: `{MODEL}`",
        f"- Endpoint: `{BASE_URL}`",
        f"- Cases: {payload['current']['cases']}",
        f"- Verdict: **{payload['decision']['verdict']}**",
        f"- Reason: {payload['decision']['reason']}",
        "",
        "| Variant | Avg Accuracy | Perfect | >=0.8 | Errors | Avg ms | P95 ms | Total Tokens | Avg Tokens |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ["current", "lightweight_llm"]:
        item = payload[name]
        lines.append(
            f"| {name} | {item['avg_accuracy']} | {item['perfect_cases']} | {item['cases_ge_0_8']} | "
            f"{item['errors']} | {item['avg_duration_ms']} | {item['p95_duration_ms']} | "
            f"{item['total_tokens']} | {item['avg_tokens_per_case']} |"
        )
    lines.extend(
        [
            "",
            "## Case Details",
            "",
            "| Case | Current | LLM | Current Roles | LLM Roles |",
            "| --- | ---: | ---: | --- | --- |",
        ]
    )
    for case_id in payload["case_ids"]:
        cur = payload["cases"][case_id]["current"]
        llm = payload["cases"][case_id]["lightweight_llm"]
        lines.append(
            f"| `{case_id}` | {cur['accuracy']} | {llm['accuracy']} | "
            f"{', '.join(cur['actual_roles'])} | {', '.join(llm['actual_roles'])} |"
        )
    (OUT_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    current_rows: list[dict[str, Any]] = []
    llm_rows: list[dict[str, Any]] = []
    cases_payload: dict[str, Any] = {}
    for case in CASES:
        current_result = current_splitter(case)
        llm_result = llm_splitter(case)
        current_score = score_case(case, current_result)
        llm_score = score_case(case, llm_result)
        current_rows.append(current_score)
        llm_rows.append(llm_score)
        cases_payload[case.case_id] = {
            "prompt": case.prompt,
            "expected_roles": case.expected_roles,
            "current": current_score,
            "lightweight_llm": llm_score,
        }
        print(
            f"{case.case_id}: current={current_score['accuracy']:.2f} "
            f"llm={llm_score['accuracy']:.2f} llm_ms={llm_score['duration_ms']:.0f}"
        )
    current_summary = summarize(current_rows)
    llm_summary = summarize(llm_rows)
    payload = {
        "model": MODEL,
        "base_url": BASE_URL,
        "current": current_summary,
        "lightweight_llm": llm_summary,
        "decision": decision(current_summary, llm_summary),
        "case_ids": [case.case_id for case in CASES],
        "cases": cases_payload,
    }
    (OUT_DIR / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(payload)
    print(json.dumps(payload["current"], indent=2))
    print(json.dumps(payload["lightweight_llm"], indent=2))
    print(json.dumps(payload["decision"], indent=2))
    print(f"wrote {OUT_DIR / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
