"""Shared copy for graph-native write-bundle approval (UI + API)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_UUID_TAIL = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def _staged_job_ids(staged: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for x in staged:
        if not isinstance(x, dict):
            continue
        args = x.get("args") if isinstance(x.get("args"), dict) else {}
        tid = args.get("id") or args.get("job_id")
        if isinstance(tid, str) and tid.strip():
            ids.append(tid.strip())
            continue
        tn = str(x.get("tool_name") or "")
        m = _UUID_TAIL.search(tn)
        if m:
            ids.append(m.group(1))
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _staged_uniform_arg(staged: list[dict[str, Any]], key: str) -> Any | None:
    vals: list[Any] = []
    for x in staged:
        if not isinstance(x, dict):
            continue
        args = x.get("args") if isinstance(x.get("args"), dict) else {}
        if key in args:
            vals.append(args[key])
    if not vals:
        return None
    first = vals[0]
    if all(v == first for v in vals):
        return first
    return None


def format_staged_jobs_human_hint(staged: list[dict[str, Any]], *, max_ids: int = 16) -> str | None:
    """Short, user-facing line listing job (or job-like) ids when detectable from staged writes."""
    clean = [x for x in staged if isinstance(x, dict)]
    if not clean:
        return None
    jobish = any("job" in str(x.get("tool_name") or "").lower() for x in clean)
    if not jobish:
        return None
    ids = _staged_job_ids(clean)
    if not ids:
        return None
    head = ids[:max_ids]
    id_part = ", ".join(head)
    if len(ids) > max_ids:
        id_part += f", … (+{len(ids) - max_ids} more)"
    pri = _staged_uniform_arg(clean, "priority")
    if pri is not None and str(pri).strip():
        return f"Jobs affected: {id_part}; priority set to {str(pri).strip()}"
    return f"Jobs affected: {id_part}"


def format_write_bundle_approval_summary(staged: list[dict[str, Any]], *, max_distinct: int = 12) -> str:
    """Single-line summary listing tools and counts (e.g. bulk job updates)."""
    clean = [x for x in staged if isinstance(x, dict)]
    n = len(clean)
    if n == 0:
        return "Backend write bundle requires approval before commit."

    counts = Counter(str(x.get("tool_name") or "unknown") for x in clean)
    parts: list[str] = []
    for name, cnt in counts.most_common(max_distinct):
        parts.append(f"{name} ×{cnt}" if cnt > 1 else name)
    tail = ""
    if len(counts) > max_distinct:
        tail = f" (+{len(counts) - max_distinct} more)"
    listed = ", ".join(parts) + tail
    base = f"Approve {n} backend write{'s' if n != 1 else ''}: {listed}"
    hint = format_staged_jobs_human_hint(clean)
    if hint:
        return f"{base}. {hint}"
    return base


def approval_preview_rows(staged: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": x.get("tool_name"),
            "output_ref": x.get("output_ref"),
            "args": x.get("args"),
        }
        for x in staged[:limit]
        if isinstance(x, dict)
    ]


def _tool_is_job_put(tool_name: Any) -> bool:
    if not isinstance(tool_name, str) or not tool_name.strip():
        return False
    return "put__jobs" in tool_name.lower()


def build_job_priority_bundle_uiview(
    staged: list[dict[str, Any]],
    *,
    intent_text: str = "",
) -> dict[str, Any] | None:
    """Structured UI bundle for bulk job priority updates (no LLM).

    Returned shape is stable for API/UI:
    ``{ "kind": "job_priority_bundle", "headline": str, "rows": [...], "previous_priority": str, "new_priority": str }``
    """
    from .planner_graph_helpers import _infer_bulk_job_priority_mutation

    clean = [x for x in staged if isinstance(x, dict)]
    if not clean or not all(_tool_is_job_put(x.get("tool_name")) for x in clean):
        return None

    pairs: list[tuple[str, str]] = []
    for x in clean:
        args = x.get("args") if isinstance(x.get("args"), dict) else {}
        jid = args.get("id") or args.get("job_id")
        if not isinstance(jid, str) or not jid.strip():
            return None
        pri = args.get("priority")
        if not isinstance(pri, str) or not pri.strip():
            return None
        pairs.append((jid.strip(), pri.strip().lower()))

    new_vals = [p[1] for p in pairs]
    uniform_new = len(set(new_vals)) == 1

    mut = _infer_bulk_job_priority_mutation(intent_text.strip())
    prev_from_intent: str | None = None
    if isinstance(mut, dict) and mut.get("action") == "update_priority":
        prev_from_intent = str(mut.get("source_priority") or "").strip().lower() or None

    rows_out: list[dict[str, str]] = []
    if prev_from_intent and uniform_new:
        for jid, new_p in pairs:
            rows_out.append(
                {"job_id": jid, "previous_priority": prev_from_intent, "new_priority": new_p},
            )
        n = len(rows_out)
        prev_u = prev_from_intent
        new_u = new_vals[0]
        headline = f"{n} job{'s' if n != 1 else ''} will be updated from {prev_u} to {new_u} priority."
        return {
            "kind": "job_priority_bundle",
            "headline": headline,
            "previous_priority": prev_u,
            "new_priority": new_u,
            "rows": rows_out,
        }

    if uniform_new:
        prev_arg = _staged_uniform_arg(clean, "previous_priority")
        if isinstance(prev_arg, str) and prev_arg.strip():
            prev_u = prev_arg.strip().lower()
            new_u = new_vals[0]
            for jid, new_p in pairs:
                rows_out.append({"job_id": jid, "previous_priority": prev_u, "new_priority": new_p})
            n = len(rows_out)
            headline = f"{n} job{'s' if n != 1 else ''} will be updated from {prev_u} to {new_u} priority."
            return {
                "kind": "job_priority_bundle",
                "headline": headline,
                "previous_priority": prev_u,
                "new_priority": new_u,
                "rows": rows_out,
            }

    if not uniform_new:
        if not prev_from_intent:
            return None
        for jid, new_p in pairs:
            rows_out.append({"job_id": jid, "previous_priority": prev_from_intent, "new_priority": new_p})
        n = len(rows_out)
        headline = f"{n} job{'s' if n != 1 else ''} pending approval (mixed priority changes)."
        return {
            "kind": "job_priority_bundle",
            "headline": headline,
            "previous_priority": prev_from_intent,
            "new_priority": "",
            "rows": rows_out,
        }

    return None


def build_approval_required_payload(staged: list[dict[str, Any]], *, intent_text: str = "") -> dict[str, Any]:
    """Graph interrupt / validator payload: summary + preview + optional ``bundle_ui``."""
    clean = [x for x in staged if isinstance(x, dict)]
    summary = format_write_bundle_approval_summary(clean)
    payload: dict[str, Any] = {
        "kind": "approval_required",
        "summary": summary,
        "count": len(clean),
        "preview": approval_preview_rows(clean, limit=min(50, max(len(clean), 1))),
    }
    ui = build_job_priority_bundle_uiview(clean, intent_text=intent_text)
    if ui:
        payload["bundle_ui"] = ui
    return payload
