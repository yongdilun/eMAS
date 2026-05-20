from __future__ import annotations

import re
from typing import Any

from factory_agent.schemas import ToolInfo


CONTROL_QUERY_FIELDS = {"fields", "limit", "offset", "page", "page_size", "sort", "sort_by", "sort_dir"}
ASCENDING_WORD_RE = re.compile(r"\b(?:asc|ascending|earliest|oldest|soonest|due\s+soon)\b", re.IGNORECASE)
DESCENDING_WORD_RE = re.compile(r"\b(?:desc|descending|latest|newest|most\s+recent)\b", re.IGNORECASE)
LIMIT_RE = re.compile(r"\b(?:limit|first|next|top)\s+(\d{1,4})\b", re.IGNORECASE)
STATUS_WORD_RE = re.compile(r"\b(?:status|state|health|condition|running|availability|available)\b", re.IGNORECASE)
ONLY_AFTER_RE = re.compile(
    r"\bonly\s+(?P<fields>[^.;\n]+?)(?=(?:,?\s+\b(?:sorted?|sort|order(?:ed)?|limit|first|next|top|where|for)\b)|[.;\n]|$)",
    re.IGNORECASE,
)
ONLY_BEFORE_RE = re.compile(
    r"\b(?:show|include|return|list)\s+(?P<fields>[^.;\n]+?)\s+only\b",
    re.IGNORECASE,
)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "record id"),
    "job_id": ("job id", "job ids", "job", "work order id", "work order"),
    "machine_id": ("machine id", "machine ids", "machine"),
    "product_id": ("product id", "product ids", "product"),
    "material_id": ("material id", "material ids", "material"),
    "status": ("status", "state", "condition"),
    "priority": ("priority",),
    "deadline": ("deadline", "due date", "due"),
    "created_at": ("created at", "created date", "creation date", "created"),
    "updated_at": ("updated at", "updated date", "modified date"),
}


def _schema_properties(tool: ToolInfo) -> dict[str, Any]:
    properties = (tool.input_schema or {}).get("properties")
    return properties if isinstance(properties, dict) else {}


def _schema_query_params(tool: ToolInfo) -> set[str]:
    params = set(str(item) for item in (tool.query_params or []) if item)
    schema_params = (tool.input_schema or {}).get("x-query-params")
    if isinstance(schema_params, list):
        params.update(str(item) for item in schema_params if item)
    return params


def _supports_arg(tool: ToolInfo, name: str) -> bool:
    return name in _schema_query_params(tool) or name in _schema_properties(tool)


def _singular(value: str) -> str:
    lowered = value.strip().lower().replace("-", "_")
    if lowered.endswith("ies") and len(lowered) > 3:
        return lowered[:-3] + "y"
    if lowered.endswith("s") and not lowered.endswith("ss") and len(lowered) > 1:
        return lowered[:-1]
    return lowered


def _tool_entity(tool: ToolInfo) -> str | None:
    schema_entity = (tool.input_schema or {}).get("x-ai-entity")
    if isinstance(schema_entity, str) and schema_entity.strip():
        return _singular(schema_entity)
    match = re.match(r"^[a-z]+__([a-z][a-z0-9_-]*?)(?:_\{|$|__)", tool.name or "", re.IGNORECASE)
    if match:
        return _singular(match.group(1))
    segments = [part for part in (tool.endpoint or "").split("/") if part and not part.startswith("{")]
    return _singular(segments[0]) if segments else None


def _field_label(value: str) -> str:
    return re.sub(r"[_-]+", " ", value).strip().lower()


def _canonical_field_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _output_field_candidates(tool: ToolInfo) -> list[str]:
    schema = tool.input_schema or {}
    out: list[str] = []

    def add(value: Any) -> None:
        key = _canonical_field_key(value)
        if key and key not in out:
            out.append(key)

    for key in ("x-ai-entity-id-field", "x-ai-display-id-field", "x-ai-display-name-field", "x-ai-primary-status-field"):
        add(schema.get(key))
    for item in schema.get("x-ai-status-fields") or []:
        add(item)

    sort_schema = _schema_properties(tool).get("sort_by")
    if isinstance(sort_schema, dict):
        for item in sort_schema.get("enum") or []:
            add(item)

    entity = _tool_entity(tool)
    if entity:
        add(f"{entity}_id")
    return out


def _field_aliases(field: str, *, entity: str | None) -> list[str]:
    aliases = {_field_label(field), field.lower()}
    aliases.update(FIELD_ALIASES.get(field, ()))
    if field == "id" and entity:
        aliases.add(f"{entity} id")
    if field.endswith("_id"):
        aliases.add(_field_label(field))
    if field == "created_at":
        aliases.add("created")
    return sorted(aliases, key=len, reverse=True)


def _field_from_phrase(phrase: str, *, candidates: list[str], entity: str | None) -> str | None:
    normalized = _field_label(phrase)
    normalized = re.sub(r"\b(?:and|or|the|a|an|field|fields|columns?|values?)\b", " ", normalized)
    normalized = " ".join(normalized.split())
    if not normalized:
        return None
    for field in candidates:
        for alias in _field_aliases(field, entity=entity):
            if normalized == alias or re.search(rf"\b{re.escape(alias)}\b", normalized):
                return field
    return None


def _split_field_phrase(value: str) -> list[str]:
    cleaned = re.sub(r"\b(?:sorted?|sort|order(?:ed)?|limit|first|next|top)\b.*$", "", value, flags=re.IGNORECASE)
    return [
        item.strip(" ,")
        for item in re.split(r"\s*,\s*|\s+\band\b\s+|\s*&\s*", cleaned)
        if item.strip(" ,")
    ]


def infer_requested_fields(intent: str, tool: ToolInfo) -> list[str]:
    if not _supports_arg(tool, "fields"):
        return []

    text = intent or ""
    entity = _tool_entity(tool)
    candidates = _output_field_candidates(tool)
    explicit_segments = [
        *(match.group("fields") for match in ONLY_AFTER_RE.finditer(text)),
        *(match.group("fields") for match in ONLY_BEFORE_RE.finditer(text)),
    ]
    best_fields: list[str] = []
    for segment in explicit_segments:
        fields: list[str] = []
        for phrase in _split_field_phrase(segment):
            field = _field_from_phrase(phrase, candidates=candidates, entity=entity)
            if field and field not in fields:
                fields.append(field)
        if len(fields) > len(best_fields):
            best_fields = fields
    if best_fields:
        identity = next((field for field in candidates if field.endswith("_id")), None)
        if STATUS_WORD_RE.search(text) and "status" in best_fields and identity and identity not in best_fields:
            best_fields.insert(0, identity)
        if STATUS_WORD_RE.search(text) and "status" in candidates and "status" not in best_fields:
            best_fields.append("status")
        return best_fields

    if STATUS_WORD_RE.search(text):
        identity = next((field for field in candidates if field.endswith("_id")), None)
        if identity:
            return [identity, "status"]
        if "status" in candidates:
            return ["status"]
    return []


def _sort_by_from_intent(intent: str, tool: ToolInfo) -> str | None:
    if not _supports_arg(tool, "sort_by"):
        return None
    schema = _schema_properties(tool).get("sort_by")
    enum_values = schema.get("enum") if isinstance(schema, dict) else None
    candidates = [str(item) for item in enum_values] if isinstance(enum_values, list) else []
    if not candidates:
        return None
    text = intent or ""
    sort_match = re.search(r"\b(?:sorted?|order(?:ed)?)\s+by\s+([a-zA-Z0-9_ -]+)", text, re.IGNORECASE)
    if sort_match:
        probe = sort_match.group(1)
        for value in candidates:
            label = _field_label(value)
            if re.search(rf"\b{re.escape(label)}\b", _field_label(probe)):
                return value
    if re.search(r"\b(?:due\s+soon|deadline)\b", text, re.IGNORECASE) and "deadline" in candidates:
        return "deadline"
    if DESCENDING_WORD_RE.search(text) and "created_at" in candidates:
        return "created_at"
    return None


def _sort_dir_from_intent(intent: str, *, sort_by: str | None) -> str | None:
    text = intent or ""
    if ASCENDING_WORD_RE.search(text):
        return "asc"
    if DESCENDING_WORD_RE.search(text):
        return "desc"
    if sort_by == "deadline" and re.search(r"\b(?:next|due\s+soon|deadline)\b", text, re.IGNORECASE):
        return "asc"
    return None


def _limit_from_intent(intent: str, tool: ToolInfo) -> int | None:
    if not _supports_arg(tool, "limit"):
        return None
    match = LIMIT_RE.search(intent or "")
    if not match:
        return None
    value = int(match.group(1))
    return max(1, min(value, 1000))


def _enum_filter_args(intent: str, tool: ToolInfo) -> dict[str, Any]:
    args: dict[str, Any] = {}
    properties = _schema_properties(tool)
    query_params = _schema_query_params(tool)
    lowered = f" {_field_label(intent or '')} "
    for field, schema in properties.items():
        if field not in query_params or field in CONTROL_QUERY_FIELDS:
            continue
        enum_values = schema.get("enum") if isinstance(schema, dict) else None
        if not isinstance(enum_values, list):
            continue
        for value in enum_values:
            label = _field_label(str(value))
            if re.search(rf"\b{re.escape(label)}\b", lowered):
                args[str(field)] = value
                break
    return args


def infer_collection_query_args(intent: str, tool: ToolInfo) -> dict[str, Any]:
    args = _enum_filter_args(intent, tool)
    sort_by = _sort_by_from_intent(intent, tool)
    sort_dir = _sort_dir_from_intent(intent, sort_by=sort_by)
    limit = _limit_from_intent(intent, tool)
    fields = infer_requested_fields(intent, tool)

    if sort_by is not None:
        args["sort_by"] = sort_by
    if sort_dir is not None and _supports_arg(tool, "sort_dir"):
        args["sort_dir"] = sort_dir
    if limit is not None:
        args["limit"] = limit
    if fields:
        args["fields"] = ",".join(fields)
    return args


def infer_lookup_query_args(intent: str, tool: ToolInfo) -> dict[str, Any]:
    fields = infer_requested_fields(intent, tool)
    return {"fields": ",".join(fields)} if fields else {}


def merge_inferred_read_args(intent: str, tool: ToolInfo, args: dict[str, Any]) -> dict[str, Any]:
    merged = dict(args or {})
    inferred = (
        infer_collection_query_args(intent, tool)
        if not (tool.path_params or (tool.input_schema or {}).get("required"))
        else infer_lookup_query_args(intent, tool)
    )
    for key, value in inferred.items():
        if _supports_arg(tool, key) and merged.get(key) in (None, ""):
            merged[key] = value
    return merged


def parse_fields_arg(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_canonical_field_key(item) for item in value if _canonical_field_key(item)]
    return [_canonical_field_key(item) for item in str(value or "").split(",") if _canonical_field_key(item)]
