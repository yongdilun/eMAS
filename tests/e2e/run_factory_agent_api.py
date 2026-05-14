from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx


TERMINAL_STATUSES = {"IDLE", "COMPLETED", "FAILED", "BLOCKED", "WAITING_CONFIRMATION"}
_METRIC_LINE_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+(-?[0-9]+(?:\.[0-9]+)?)$")


def load_scenarios(path: Path, ids: set[str] | None) -> list[dict[str, Any]]:
    scenarios = json.loads(path.read_text(encoding="utf-8"))
    selected = [
        s
        for s in scenarios
        if s.get("entrypoint") == "factory_agent"
        and s.get("category") in {"factory_agent", "negative"}
        and (not ids or s.get("id") in ids)
    ]
    if ids:
        found = {s["id"] for s in selected}
        missing = sorted(ids - found)
        if missing:
            raise SystemExit(f"Unknown or non-factory-agent scenario ids: {', '.join(missing)}")
    return selected


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected_status: int | None = None,
    **kwargs: Any,
) -> tuple[int, Any, str]:
    response = client.request(method, path, **kwargs)
    text = response.text
    try:
        payload: Any = response.json()
    except Exception:
        payload = text
    if expected_status is not None and response.status_code != expected_status:
        raise AssertionError(f"{method} {path}: expected {expected_status}, got {response.status_code}: {text}")
    return response.status_code, payload, text


def searchable_text(*values: Any) -> str:
    return "\n".join(json.dumps(v, default=str, sort_keys=True) for v in values)


def grouped_counts(results: list[dict[str, Any]], field: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for result in results:
        key = str(result.get(field) or "uncategorized")
        bucket = grouped.setdefault(key, {"total": 0, "passed": 0, "failed": 0})
        bucket["total"] += 1
        if result.get("status") == "passed":
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
    return dict(sorted(grouped.items()))


def parse_prometheus_metrics(payload: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for raw_line in (payload or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC_LINE_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        value = float(match.group(2))
        values[name] = values.get(name, 0.0) + value
    return values


def poll_health(base_url: str, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        try:
            with httpx.Client(base_url=base_url, timeout=2.0) as client:
                response = client.get("/health")
                if response.status_code == 200:
                    return
                last_error = response.text
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise SystemExit(f"Factory-agent API did not become healthy at {base_url}: {last_error}")


def run_scenario(
    client: httpx.Client,
    scenario: dict[str, Any],
    *,
    require_llm: bool,
    timeout_s: float,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    sid = ""
    plan: Any = None
    snapshot: Any = None
    messages: Any = None
    steps: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []

    status_code, session, _ = request_json(
        client,
        "POST",
        "/sessions",
        json={"user_id": "seed-pipeline", "name": scenario["id"]},
        expected_status=200,
    )
    events.append({"phase": "create_session", "http_status": status_code, "response": session})
    sid = session["session_id"]

    metric_baseline: dict[str, float] = {}
    required_metric_deltas = scenario.get("required_metric_deltas")
    if isinstance(required_metric_deltas, dict):
        _, metrics_payload, metrics_text = request_json(client, "GET", "/metrics")
        payload_text = metrics_text if isinstance(metrics_text, str) else str(metrics_payload)
        metric_baseline = parse_prometheus_metrics(payload_text)

    turns = [scenario["input"]]
    extra_turns = scenario.get("follow_up_inputs")
    if isinstance(extra_turns, list):
        turns.extend(str(value) for value in extra_turns if str(value).strip())

    for turn_index, turn_text in enumerate(turns):
        status_code, message, _ = request_json(
            client,
            "POST",
            f"/sessions/{sid}/messages",
            json={"role": "user", "content": turn_text, "mode": "normal"},
            expected_status=200,
        )
        events.append(
            {
                "phase": "add_message",
                "turn_index": turn_index,
                "input": turn_text,
                "http_status": status_code,
                "response": message,
            }
        )

        status_code, plan, plan_text = request_json(
            client,
            "POST",
            f"/sessions/{sid}/plans",
            json={},
        )
        events.append(
            {
                "phase": "create_plan",
                "turn_index": turn_index,
                "http_status": status_code,
                "response": plan,
            }
        )
        if status_code >= 400:
            return {
                "status": "failed",
                "reason": f"plan creation returned HTTP {status_code} on turn {turn_index}",
                "session_id": sid,
                "events": events,
                "response_body": plan_text,
            }

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status_code, execution, execution_text = request_json(
                client,
                "POST",
                f"/sessions/{sid}/execute",
            )
            events.append(
                {
                    "phase": "execute",
                    "turn_index": turn_index,
                    "http_status": status_code,
                    "response": execution,
                }
            )
            if status_code >= 400:
                return {
                    "status": "failed",
                    "reason": f"execute returned HTTP {status_code} on turn {turn_index}",
                    "session_id": sid,
                    "events": events,
                    "response_body": execution_text,
                }

            _, snapshot, _ = request_json(client, "GET", f"/sessions/{sid}/snapshot", expected_status=200)
            pending = snapshot.get("pending_approval")
            if pending:
                approvals.append(pending)
                policy = scenario.get("approval_policy", "none")
                if policy == "approve":
                    decision_path = f"/approvals/{pending['approval_id']}/approve"
                    _, decision, _ = request_json(
                        client,
                        "POST",
                        decision_path,
                        json={"decided_by": "seed-pipeline"},
                        expected_status=200,
                    )
                    events.append(
                        {
                            "phase": "approve",
                            "turn_index": turn_index,
                            "http_status": 200,
                            "response": decision,
                        }
                    )
                    continue
                if policy == "reject":
                    decision_path = f"/approvals/{pending['approval_id']}/reject"
                    _, decision, _ = request_json(
                        client,
                        "POST",
                        decision_path,
                        json={"decided_by": "seed-pipeline", "rejection_reason": "seed pipeline rejection"},
                        expected_status=200,
                    )
                    events.append(
                        {
                            "phase": "reject",
                            "turn_index": turn_index,
                            "http_status": 200,
                            "response": decision,
                        }
                    )
                    break
                break

            session_status = snapshot.get("session", {}).get("status")
            if session_status in TERMINAL_STATUSES:
                break
            time.sleep(0.5)
        else:
            return {
                "status": "failed",
                "reason": f"scenario timed out after {timeout_s}s on turn {turn_index}",
                "session_id": sid,
                "events": events,
                "snapshot": snapshot,
            }

    _, snapshot, _ = request_json(client, "GET", f"/sessions/{sid}/snapshot", expected_status=200)
    _, messages, _ = request_json(client, "GET", f"/sessions/{sid}/messages", expected_status=200)
    _, steps, _ = request_json(client, "GET", f"/sessions/{sid}/steps", expected_status=200)

    step_tools = [step.get("tool_name") for step in steps]
    seen_tools = {tool for tool in step_tools if tool}
    timeline = snapshot.get("timeline") if isinstance(snapshot, dict) else None
    if isinstance(timeline, list):
        for event in timeline:
            if not isinstance(event, dict):
                continue
            tool_name = event.get("tool_name")
            if isinstance(tool_name, str) and tool_name and tool_name not in {"__conversation__", "__plan__"}:
                if tool_name not in seen_tools:
                    step_tools.append(tool_name)
                    seen_tools.add(tool_name)
    for approval in approvals:
        payload = approval.get("args") if isinstance(approval, dict) and isinstance(approval.get("args"), dict) else {}
        preview = payload.get("preview")
        if not isinstance(preview, list):
            continue
        for item in preview:
            if not isinstance(item, dict):
                continue
            tool_name = item.get("tool_name")
            if isinstance(tool_name, str) and tool_name and tool_name not in seen_tools:
                step_tools.append(tool_name)
                seen_tools.add(tool_name)
    missing_tools = [tool for tool in scenario.get("expected_tools", []) if tool not in step_tools]

    body = searchable_text(snapshot, messages, steps, events)
    missing_contains = [
        expected
        for expected in scenario.get("expected_response_contains", [])
        if expected.lower() not in body.lower()
    ]

    session_info = snapshot.get("session", {}) if isinstance(snapshot, dict) else {}
    plan_info = snapshot.get("plan") if isinstance(snapshot, dict) else None
    llm_calls = int(session_info.get("llm_call_count") or 0)
    plan_created_by = (plan_info or {}).get("created_by") if isinstance(plan_info, dict) else None
    llm_failed = require_llm and (llm_calls <= 0 or plan_created_by in {None, "legacy", "system", "client"})
    metric_deltas: dict[str, float] = {}
    metric_failed = False

    if isinstance(required_metric_deltas, dict):
        _, metrics_payload_after, metrics_text_after = request_json(client, "GET", "/metrics")
        payload_text_after = metrics_text_after if isinstance(metrics_text_after, str) else str(metrics_payload_after)
        metric_after = parse_prometheus_metrics(payload_text_after)
        for metric_name, expected_delta in required_metric_deltas.items():
            base_val = float(metric_baseline.get(metric_name, 0.0))
            end_val = float(metric_after.get(metric_name, 0.0))
            delta_val = end_val - base_val
            metric_deltas[str(metric_name)] = delta_val
            try:
                target = float(expected_delta)
            except Exception:
                target = 0.0
            if delta_val < target:
                metric_failed = True

    non_empty_required = bool(scenario.get("assert_non_empty_memory_retrieval"))
    non_empty_failed = False
    if non_empty_required:
        retrieval = metric_deltas.get("memory_retrieval_total", 0.0)
        empty = metric_deltas.get("memory_retrieval_empty_total", 0.0)
        if retrieval <= empty:
            non_empty_failed = True

    approval_count_failed = False
    expected_approval_count = scenario.get("expected_approval_count")
    if expected_approval_count is not None:
        try:
            approval_count_failed = len(approvals) != int(expected_approval_count)
        except Exception:
            approval_count_failed = True

    bundle_count_failed = False
    expected_bundle_write_count = scenario.get("expected_bundle_write_count")
    if expected_bundle_write_count is not None:
        actual_counts = []
        for approval in approvals:
            payload = approval.get("args") if isinstance(approval, dict) and isinstance(approval.get("args"), dict) else {}
            actual_counts.append(int(payload.get("count") or 0))
        try:
            bundle_count_failed = int(expected_bundle_write_count) not in actual_counts
        except Exception:
            bundle_count_failed = True

    preview_failed: list[dict[str, Any]] = []
    expected_preview_contains = scenario.get("expected_approval_preview_contains")
    if isinstance(expected_preview_contains, list) and expected_preview_contains:
        previews: list[dict[str, Any]] = []
        for approval in approvals:
            payload = approval.get("args") if isinstance(approval, dict) and isinstance(approval.get("args"), dict) else {}
            preview = payload.get("preview")
            if isinstance(preview, list):
                previews.extend(item for item in preview if isinstance(item, dict))

        def _contains_expected_preview(expected: dict[str, Any]) -> bool:
            expected_tool = expected.get("tool_name")
            expected_args = expected.get("args") if isinstance(expected.get("args"), dict) else {}
            for item in previews:
                if expected_tool and item.get("tool_name") != expected_tool:
                    continue
                args = item.get("args") if isinstance(item.get("args"), dict) else {}
                if all(args.get(key) == value for key, value in expected_args.items()):
                    return True
            return False

        preview_failed = [
            expected
            for expected in expected_preview_contains
            if isinstance(expected, dict) and not _contains_expected_preview(expected)
        ]

    passed = (
        not missing_tools
        and not missing_contains
        and not llm_failed
        and not metric_failed
        and not non_empty_failed
        and not approval_count_failed
        and not bundle_count_failed
        and not preview_failed
    )
    reason_parts: list[str] = []
    if missing_tools:
        reason_parts.append("missing expected tools: " + ", ".join(missing_tools))
    if missing_contains:
        reason_parts.append("missing expected text: " + ", ".join(missing_contains))
    if llm_failed:
        reason_parts.append(
            f"LLM planner was required but llm_call_count={llm_calls} and plan_created_by={plan_created_by!r}"
        )
    if metric_failed:
        reason_parts.append(f"required metric delta(s) not met: {metric_deltas}")
    if non_empty_failed:
        reason_parts.append(
            "non-empty memory retrieval assertion failed "
            f"(memory_retrieval_total={metric_deltas.get('memory_retrieval_total', 0.0)}, "
            f"memory_retrieval_empty_total={metric_deltas.get('memory_retrieval_empty_total', 0.0)})"
        )
    if approval_count_failed:
        reason_parts.append(f"expected {expected_approval_count} approval(s), got {len(approvals)}")
    if bundle_count_failed:
        reason_parts.append(
            f"expected approval bundle count {expected_bundle_write_count}, "
            f"got {[((a.get('args') or {}).get('count') if isinstance(a, dict) else None) for a in approvals]}"
        )
    if preview_failed:
        reason_parts.append(f"missing approval preview item(s): {preview_failed}")

    return {
        "status": "passed" if passed else "failed",
        "reason": "; ".join(reason_parts) if reason_parts else "ok",
        "session_id": sid,
        "session_status": session_info.get("status"),
        "llm_call_count": llm_calls,
        "plan_created_by": plan_created_by,
        "expected_tools": scenario.get("expected_tools", []),
        "actual_tools": step_tools,
        "approvals": approvals,
        "metric_deltas": metric_deltas,
        "events": events,
        "snapshot": snapshot,
        "messages": messages,
        "steps": steps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run seed scenarios through the real factory-agent HTTP API.")
    parser.add_argument("--base-url", default=os.getenv("FACTORY_AGENT_BASE_URL", "http://127.0.0.1:18081"))
    parser.add_argument("--scenarios", default=os.getenv("SEED_SCENARIOS", "tests/e2e/scenarios/seed_pipeline.json"))
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--timeout-s", type=float, default=float(os.getenv("AGENT_SCENARIO_TIMEOUT_S", "90")))
    parser.add_argument("--health-timeout-s", type=float, default=30)
    parser.add_argument("--require-llm", action="store_true")
    args = parser.parse_args()

    scenario_ids = set()
    for value in args.scenario:
        scenario_ids.update(part.strip() for part in value.split(",") if part.strip())

    scenarios = load_scenarios(Path(args.scenarios), scenario_ids or None)
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    poll_health(args.base_url, args.health_timeout_s)

    results: list[dict[str, Any]] = []
    with httpx.Client(base_url=args.base_url, timeout=args.timeout_s) as client:
        for scenario in scenarios:
            started = time.time()
            try:
                result = run_scenario(client, scenario, require_llm=args.require_llm, timeout_s=args.timeout_s)
            except Exception as exc:
                result = {"status": "failed", "reason": str(exc)}
            result["duration_s"] = round(time.time() - started, 3)
            artifact = {"scenario": scenario, "result": result}
            (artifact_dir / f"{scenario['id']}.agent.json").write_text(
                json.dumps(artifact, indent=2, default=str),
                encoding="utf-8",
            )
            results.append(
                {
                    "id": scenario["id"],
                    "category": scenario.get("category"),
                    "coverage_area": scenario.get("coverage_area"),
                    "complexity": scenario.get("complexity"),
                    "difficulty": scenario.get("difficulty"),
                    **result,
                }
            )

    passed = [r for r in results if r["status"] == "passed"]
    failed = [r for r in results if r["status"] != "passed"]
    summary = {
        "total": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "require_llm": args.require_llm,
        "by_difficulty": grouped_counts(results, "difficulty"),
        "by_complexity": grouped_counts(results, "complexity"),
        "by_coverage_area": grouped_counts(results, "coverage_area"),
        "failures": [{"id": r["id"], "reason": r.get("reason")} for r in failed],
    }
    (artifact_dir / "factory-agent-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
