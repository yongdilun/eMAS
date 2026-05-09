from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DatasetRef:
    source: str
    path: str
    row_count: int


@dataclass(frozen=True)
class AnalysisOperation:
    op: str
    field: str | None = None
    label: str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class ResultAnalysis:
    dataset: DatasetRef
    operations: list[AnalysisOperation]
    results: list[dict[str, Any]]
    facts: list[str]
    grounding_refs: list[str]


_WORD_RE = re.compile(r"[a-z0-9]+")
_TOP_K_RE = re.compile(r"\b(?:top|first|last)\s+(\d+)\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    return "".join(_WORD_RE.findall(str(text or "").lower()))


def _result_rows(result: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    for key in ("data", "items"):
        value = result.get(key)
        if isinstance(value, list):
            return f"$.{key}", [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return f"$.{key}", [value]
    return "$", []


def _field_lookup(rows: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for row in rows:
        for key in row.keys():
            lookup.setdefault(_normalize(str(key)), str(key))
    return lookup


def _find_field(rows: list[dict[str, Any]], aliases: list[str]) -> str | None:
    lookup = _field_lookup(rows)
    for alias in aliases:
        direct = lookup.get(_normalize(alias))
        if direct:
            return direct
    alias_norms = [_normalize(alias) for alias in aliases]
    for normalized, original in lookup.items():
        if any(alias in normalized or normalized in alias for alias in alias_norms):
            return original
    return None


def _coerce_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _coerce_number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    try:
        return float(text)
    except Exception:
        return None


def _value_for_sort(value: Any) -> Any | None:
    parsed_dt = _coerce_datetime(value)
    if parsed_dt is not None:
        return parsed_dt
    parsed_num = _coerce_number(value)
    if parsed_num is not None:
        return parsed_num
    if value in (None, ""):
        return None
    return str(value)


def _identifier(row: dict[str, Any]) -> str:
    ranked_keys = sorted(
        row.keys(),
        key=lambda key: (
            0 if str(key).lower() == "id" else 1 if str(key).lower().endswith("id") else 2,
            str(key).lower(),
        ),
    )
    for key in ranked_keys:
        value = row.get(key)
        if (str(key).lower() == "id" or str(key).lower().endswith("id")) and value not in (None, ""):
            return str(value)
    return "row"


def _result_preview(row: dict[str, Any], *, primary_field: str | None) -> dict[str, Any]:
    preferred = [
        key
        for key in row.keys()
        if str(key).lower() == "id"
        or str(key).lower().endswith("id")
        or str(key).lower() in {"amount", "deadline", "due_date", "priority", "quantity", "status"}
    ]
    out: dict[str, Any] = {}
    for key in preferred:
        if key in row and key not in out:
            out[key] = row.get(key)
    if primary_field and primary_field in row:
        out[primary_field] = row.get(primary_field)
    if not out:
        for key, value in list(row.items())[:5]:
            if value is None or isinstance(value, (str, int, float, bool)):
                out[str(key)] = value
    return out


def _fact_for_result(label: str, row: dict[str, Any], field: str) -> str:
    identifier = _identifier(row)
    parts = [f"{field}={row.get(field)}"]
    extras = [
        key
        for key in row.keys()
        if key != field
        and (
            str(key).lower().endswith("id")
            or str(key).lower() in {"amount", "deadline", "due_date", "priority", "quantity", "status"}
        )
    ]
    for extra in extras:
        if extra != field and row.get(extra) not in (None, ""):
            parts.append(f"{extra}={row.get(extra)}")
        if len(parts) >= 3:
            break
    return f"{label}: {identifier} ({', '.join(parts)})."


def _infer_operations(intent: str, rows: list[dict[str, Any]]) -> list[AnalysisOperation]:
    text = (intent or "").lower()
    operations: list[AnalysisOperation] = []

    deadline_field = _find_field(rows, ["deadline", "due_date", "due", "target_date", "required_by"])
    quantity_field = _find_field(rows, ["quantity_total", "quantity", "qty", "units", "amount"])

    if deadline_field and re.search(r"\b(?:earliest|soonest|nearest|first\s+due|due\s+first)\b", text):
        operations.append(AnalysisOperation(op="argmin", field=deadline_field, label="Earliest deadline"))
    if deadline_field and re.search(r"\b(?:latest|last|furthest)\b", text) and re.search(r"\b(?:deadline|due|date)\b", text):
        operations.append(AnalysisOperation(op="argmax", field=deadline_field, label="Latest deadline"))

    if quantity_field and re.search(r"\b(?:largest|highest|biggest|greatest|maximum|max|most)\b", text):
        if re.search(r"\b(?:quantity|qty|unit|units|amount|volume)\b", text):
            operations.append(AnalysisOperation(op="argmax", field=quantity_field, label="Largest quantity"))
    if quantity_field and re.search(r"\b(?:smallest|lowest|least|minimum|min)\b", text):
        if re.search(r"\b(?:quantity|qty|unit|units|amount|volume)\b", text):
            operations.append(AnalysisOperation(op="argmin", field=quantity_field, label="Smallest quantity"))

    if re.search(r"\b(?:count|how many|number of)\b", text):
        operations.append(AnalysisOperation(op="count", label="Record count"))

    top_match = _TOP_K_RE.search(text)
    if quantity_field and top_match and re.search(r"\b(?:largest|highest|biggest|most)\b", text):
        operations.append(
            AnalysisOperation(op="topk", field=quantity_field, label=f"Top {top_match.group(1)} by quantity", limit=int(top_match.group(1)))
        )

    seen: set[tuple[str, str | None, int | None]] = set()
    deduped: list[AnalysisOperation] = []
    for op in operations:
        key = (op.op, op.field, op.limit)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(op)
    return deduped


def analyze_result(*, intent: str, result: dict[str, Any]) -> ResultAnalysis | None:
    path, rows = _result_rows(result or {})
    if not rows:
        return None

    operations = _infer_operations(intent, rows)
    if not operations:
        return None

    facts: list[str] = []
    refs: list[str] = []
    results: list[dict[str, Any]] = []

    for operation in operations:
        if operation.op == "count":
            results.append({"operation": operation.op, "label": operation.label, "value": len(rows)})
            facts.append(f"{operation.label or 'Record count'}: {len(rows)}.")
            refs.append(path)
            continue

        field = operation.field
        if not field:
            continue
        ranked: list[tuple[int, Any, dict[str, Any]]] = []
        for idx, row in enumerate(rows):
            sort_value = _value_for_sort(row.get(field))
            if sort_value is not None:
                ranked.append((idx, sort_value, row))
        if not ranked:
            continue

        reverse = operation.op in {"argmax", "topk"}
        ranked.sort(key=lambda item: item[1], reverse=reverse)
        selected = ranked[: max(1, operation.limit or 1)]
        result_rows = [
            {
                "row_index": idx,
                "identifier": _identifier(row),
                "field": field,
                "value": row.get(field),
                "row": _result_preview(row, primary_field=field),
            }
            for idx, _sort_value, row in selected
        ]
        results.append(
            {
                "operation": operation.op,
                "label": operation.label,
                "field": field,
                "rows": result_rows,
            }
        )
        for idx, _sort_value, row in selected[:3]:
            facts.append(_fact_for_result(operation.label or operation.op, row, field))
            refs.append(f"{path}[{idx}].{field}")

    if not results:
        return None
    return ResultAnalysis(
        dataset=DatasetRef(source="tool_result", path=path, row_count=len(rows)),
        operations=operations,
        results=results,
        facts=facts,
        grounding_refs=refs,
    )
