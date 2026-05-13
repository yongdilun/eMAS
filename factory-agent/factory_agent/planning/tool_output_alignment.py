"""Align LangGraph tool_outputs rows to persisted plan steps for API snapshots (seed / UX)."""

from __future__ import annotations

import json
from typing import Any, Sequence


def align_tool_outputs_to_steps(
    *,
    step_tool_names: Sequence[str],
    tool_outputs: list[dict[str, Any]] | None,
) -> list[tuple[dict[str, Any] | None, str | None]]:
    """Return (result dict, short summary) per plan step, in step order."""
    if not step_tool_names:
        return []
    if not tool_outputs:
        return [(None, None)] * len(step_tool_names)

    usable: list[dict[str, Any]] = []
    for row in tool_outputs:
        if not isinstance(row, dict):
            continue
        if row.get("infrastructure_error"):
            continue
        http = row.get("http_status")
        if isinstance(http, int) and http >= 500:
            continue
        body = row.get("result")
        if not isinstance(body, dict):
            continue
        usable.append(row)

    out: list[tuple[dict[str, Any] | None, str | None]] = []
    start = 0
    for name in step_tool_names:
        target = str(name)
        idx_found: int | None = None
        for j in range(start, len(usable)):
            if str(usable[j].get("tool_name") or "") == target:
                idx_found = j
                break
        if idx_found is None:
            out.append((None, None))
            continue
        start = idx_found + 1
        row = usable[idx_found]
        res = row.get("result")
        res_dict = res if isinstance(res, dict) else None
        args = row.get("args") if isinstance(row.get("args"), dict) else {}
        out.append((res_dict, summarize_tool_result(tool_name=target, result=res_dict, args=args)))
    return out


def _entity_label(tool_name: str, *, plural: bool) -> str:
    cleaned = str(tool_name or "records").replace("__", "_")
    cleaned = cleaned.split("_", 1)[-1] if "_" in cleaned else cleaned
    cleaned = cleaned.replace("{id}", "").replace("_id", "")
    cleaned = cleaned.strip("_- /{}") or "record"
    noun = cleaned.split("_", 1)[0].replace("-", " ")
    if plural and not noun.endswith("s"):
        noun = f"{noun}s"
    if not plural and noun.endswith("s"):
        noun = noun[:-1]
    return noun


def _id_values(rows: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    ids: list[str] = []
    for row in rows:
        for key, value in row.items():
            normalized = str(key).lower().replace("-", "_")
            if (normalized == "id" or normalized.endswith("_id")) and value not in (None, ""):
                ids.append(str(value))
                break
        if len(ids) >= limit:
            break
    return ids


def _filter_phrase(args: dict[str, Any] | None, noun: str) -> str:
    payload = args if isinstance(args, dict) else {}
    parts: list[str] = []
    priority = payload.get("priority")
    status = payload.get("status")
    if priority not in (None, ""):
        parts.append(f"{priority}-priority")
    if status not in (None, ""):
        parts.append(str(status))
    parts.append(noun)
    return " ".join(str(part) for part in parts)


def _result_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("data", "items"):
        value = result.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def summarize_tool_result(*, tool_name: str, result: dict[str, Any] | None, args: dict[str, Any] | None = None) -> str | None:
    if not result:
        return None
    rows = _result_rows(result)
    if rows:
        noun = _entity_label(tool_name, plural=len(rows) != 1)
        descriptor = _filter_phrase(args, noun)
        ids = _id_values(rows)
        if ids:
            suffix = ", +{} more".format(len(rows) - len(ids)) if len(rows) > len(ids) else ""
            return f"Found {len(rows)} {descriptor}: {', '.join(ids)}{suffix}. Details are shown in the table below."
        return f"Found {len(rows)} {descriptor}. Details are shown in the table below."
    for key in ("data", "items"):
        value = result.get(key)
        if isinstance(value, list) and not value:
            return f"No {_filter_phrase(args, _entity_label(tool_name, plural=True))} matched."
    if result.get("not_found"):
        return str(result.get("_summary") or result.get("detail") or "Requested resource was not found.").strip()
    for key in ("status", "message", "detail", "summary"):
        val = result.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:800]
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        return None
    if len(text) <= 2000:
        return text
    return text[:2000] + "…"
