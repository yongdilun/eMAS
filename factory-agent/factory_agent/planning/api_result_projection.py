from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


def project_api_body(
    body: Mapping[str, Any],
    *,
    requirement: Any | None = None,
    entity: str | None = None,
) -> dict[str, Any]:
    if not isinstance(body, Mapping):
        return body
    normalized_entity = _normalized_entity(entity, requirement=requirement)
    requested_fields = requested_output_fields(requirement, entity=normalized_entity)
    allowed_fields = set(requested_fields) | set(identity_fields(normalized_entity)) if requested_fields else set()

    data = body.get("data")
    if isinstance(data, Mapping):
        return {
            **dict(body),
            "data": project_api_row(data, entity=normalized_entity, allowed_fields=allowed_fields),
        }
    if isinstance(data, list):
        return {
            **dict(body),
            "data": [
                project_api_row(item, entity=normalized_entity, allowed_fields=allowed_fields)
                if isinstance(item, Mapping)
                else item
                for item in data
            ],
        }
    if any(key not in {"success", "ok", "message", "count", "total", "meta"} for key in body):
        return project_api_row(body, entity=normalized_entity, allowed_fields=allowed_fields)
    return dict(body)


def project_api_row(
    row: Mapping[str, Any],
    *,
    requirement: Any | None = None,
    entity: str | None = None,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any]:
    normalized_entity = _normalized_entity(entity, requirement=requirement)
    if allowed_fields is None:
        requested_fields = requested_output_fields(requirement, entity=normalized_entity)
        allowed_fields = set(requested_fields) | set(identity_fields(normalized_entity)) if requested_fields else set()
    normalized = {
        canonical_output_key(str(key), normalized_entity): value
        for key, value in row.items()
    }
    if not allowed_fields:
        return normalized
    return {key: value for key, value in normalized.items() if key in allowed_fields}


def requested_output_fields(requirement: Any | None, *, entity: str | None = None) -> list[str]:
    normalized_entity = _normalized_entity(entity, requirement=requirement)
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    requested_fields = [
        canonical_output_key(str(field), normalized_entity)
        for field in (getattr(requirement, "requested_fields", []) or [])
        if str(field).strip()
    ]
    if constraints.get("sort_by") not in (None, "", [], {}):
        requested_fields.append(canonical_output_key(str(constraints.get("sort_by")), normalized_entity))
    for key in ("priority", "status"):
        if constraints.get(key) not in (None, "", [], {}):
            requested_fields.append(canonical_output_key(key, normalized_entity))
    return list(dict.fromkeys(requested_fields))


def identity_fields(entity: str | None) -> list[str]:
    fields = ["id", "entity_id"]
    normalized_entity = _normalized_entity(entity)
    if normalized_entity:
        fields.insert(0, f"{normalized_entity}_id")
    fields.extend(["job_id", "machine_id"])
    return list(dict.fromkeys(fields))


def canonical_output_key(key: str, entity: str | None) -> str:
    normalized = key.strip().replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", normalized)
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_").lower()
    normalized_entity = _normalized_entity(entity)
    if normalized == "id" and normalized_entity:
        return f"{normalized_entity}_id"
    return normalized


def api_row_id(row: Mapping[str, Any], *, entity: str | None = None) -> Any:
    normalized_entity = _normalized_entity(entity)
    candidates = []
    if normalized_entity:
        candidates.append(f"{normalized_entity}_id")
    candidates.extend(["entity_id", "id", "machine_ref", "job_id", "machine_id"])
    for key in candidates:
        value = row.get(key)
        if value not in (None, ""):
            return value
    for key, value in row.items():
        if str(key).lower().endswith("_id") and value not in (None, ""):
            return value
    return None


def _normalized_entity(entity: str | None, *, requirement: Any | None = None) -> str:
    raw = entity if entity not in (None, "") else getattr(requirement, "entity", "")
    return str(raw or "").strip().lower()
