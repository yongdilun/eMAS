from __future__ import annotations

from typing import Any

from .answer_model import AnswerField, AnswerModel


# Map common API response keys to display labels, ordered by preference
_ENTITY_FIELD_PRIORITY: dict[str, list[str]] = {
    "machine": [
        "machineID",
        "machineName",
        "machineType",
        "status",
        "location",
        "capacityPerHour",
        "utilizationRate",
        "lastMaintenanceDate",
        "maintenanceIntervalDays",
        "defaultSetupTime",
        "defaultCleaningTime",
        "defaultChangeoverTime",
    ],
    "job": [
        "job_id",
        "id",
        "product_id",
        "priority",
        "status",
        "deadline",
        "start_date",
        "end_date",
        "quantity",
    ],
    "product": [
        "product_id",
        "id",
        "product_name",
        "name",
        "sku",
        "category",
        "status",
    ],
    "inventory": [
        "inventory_id",
        "id",
        "material_id",
        "material_name",
        "name",
        "quantity",
        "location",
        "status",
    ],
    "proposal": [
        "proposal_id",
        "id",
        "title",
        "status",
        "priority",
        "created_at",
    ],
}

_STATUS_KEYS = {"status", "state", "current_status"}
_ID_KEYS = {"id", "machine_id", "job_id", "product_id", "inventory_id", "material_id", "proposal_id"}


def _normalize_key(key: str) -> str:
    return str(key).strip()


def _label_for_key(key: str) -> str:
    raw = str(key).replace("-", " ").replace("_", " ").strip()
    parts = [p for p in raw.split() if p]
    if not parts:
        return str(key)
    return " ".join(p.upper() if p.lower() == "id" else p.capitalize() for p in parts)


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _entity_type_from_tool(tool_name: str | None, endpoint: str | None) -> str:
    name = str(tool_name or "").lower()
    ep = str(endpoint or "").lower()
    for token in ("machine", "job", "product", "inventory", "material", "proposal", "process", "report"):
        if token in name or token in ep:
            return token if token != "material" else "inventory"
    # Heuristic: first noun after HTTP verb in tool name
    parts = name.split("__")
    if len(parts) >= 2:
        noun = parts[1].split("_")[0].replace("-", "")
        if noun.endswith("s"):
            noun = noun[:-1]
        return noun or "record"
    return "record"


def _pick_status(data: dict[str, Any]) -> str | None:
    for key in _STATUS_KEYS:
        val = data.get(key)
        if val not in (None, ""):
            return _coerce_string(val)
    return None


def _pick_entity_id(data: dict[str, Any], entity_type: str) -> str:
    for key in _ID_KEYS:
        val = data.get(key)
        if val not in (None, ""):
            return _coerce_string(val)
    # fallback to first non-empty value
    for key, val in data.items():
        if val not in (None, ""):
            return _coerce_string(val)
    return ""


def _ordered_fields(data: dict[str, Any], entity_type: str) -> list[AnswerField]:
    priority = _ENTITY_FIELD_PRIORITY.get(entity_type, [])
    seen: set[str] = set()
    fields: list[AnswerField] = []

    # 1. Priority fields first
    for key in priority:
        if key not in data or data[key] in (None, ""):
            continue
        if key in seen:
            continue
        seen.add(key)
        fields.append(
            AnswerField(
                label=_label_for_key(key),
                value=_coerce_string(data[key]),
                key=key,
                primary=key.lower() in _STATUS_KEYS,
            )
        )

    # 2. Remaining scalar fields
    for key, val in data.items():
        if key in seen:
            continue
        if val in (None, ""):
            continue
        if not isinstance(val, (str, int, float, bool)):
            continue
        seen.add(key)
        fields.append(
            AnswerField(
                label=_label_for_key(key),
                value=_coerce_string(val),
                key=key,
                primary=False,
            )
        )

    return fields


def normalize_tool_result(
    *,
    tool_name: str | None,
    endpoint: str | None,
    result: dict[str, Any] | None,
    intent: str | None = None,
) -> AnswerModel | None:
    """Convert a single GET-by-ID or similar tool result into a generic AnswerModel."""
    if not isinstance(result, dict):
        return None

    body = result
    # unwrap common wrappers
    for key in ("data", "item", "result"):
        wrapped = body.get(key)
        if isinstance(wrapped, dict):
            body = wrapped
            break

    if not isinstance(body, dict) or not body:
        return None

    entity_type = _entity_type_from_tool(tool_name, endpoint)
    entity_id = _pick_entity_id(body, entity_type)
    status = _pick_status(body)

    fields = _ordered_fields(body, entity_type)
    if not fields:
        return None

    title = f"{entity_type.capitalize()} status"
    if intent:
        title = str(intent).strip().rstrip(".")

    return AnswerModel(
        answer_type="entity_status",
        entity_type=entity_type,
        entity_id=entity_id or "unknown",
        title=title,
        primary_status=status,
        fields=fields,
        extra={"tool_name": tool_name, "endpoint": endpoint},
    )
