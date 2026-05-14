from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from ..schemas import ToolInfo
from ..observability.telemetry import log_event


_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")
_PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {
        "default",
        "none",
        "n/a",
        "na",
        "null",
        "unknown",
        "undefined",
        "any",
        "all",
        "placeholder",
        "example",
        "sample",
        "test",
        "",
    }
)
_SAFE_CONTROL_FIELDS: frozenset[str] = frozenset(
    {
        "limit",
        "offset",
        "page",
        "page_size",
        "sort_by",
        "sort_dir",
        "order_by",
        "order_dir",
        "fields",
        "ids_only",
    }
)


@dataclass
class GuardrailResult:
    args: dict[str, Any]
    dropped_fields: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    clarification: str | None = None
    provenance: dict[str, dict[str, Any]] = field(default_factory=dict)


def path_param_names(endpoint: str) -> list[str]:
    return [match.group(1) for match in _PATH_PARAM_RE.finditer(endpoint or "")]


def coerce_field_value(*, value: Any, field_type: str | None) -> Any:
    if field_type == "string":
        return str(value)
    if field_type == "integer":
        return int(value)
    if field_type == "number":
        return float(value)
    return value


def is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _PLACEHOLDER_VALUES


def same_arg_value(left: Any, right: Any) -> bool:
    if left == right:
        return True
    left_text = re.sub(r"\s+", " ", str(left).strip()).lower()
    right_text = re.sub(r"\s+", " ", str(right).strip()).lower()
    return bool(left_text) and left_text == right_text


def value_found_in_text(value: Any, *texts: str) -> bool:
    needle = str(value).strip()
    if not needle:
        return False
    needle_lower = needle.lower()
    needle_compact = re.sub(r"[^a-z0-9]+", "", needle_lower)
    for text in texts:
        haystack = (text or "").lower()
        if re.search(rf"\b{re.escape(needle_lower)}\b", haystack):
            return True
        if needle_compact and needle_compact in re.sub(r"[^a-z0-9]+", "", haystack):
            return True
    return False


def field_name_found_in_text(field: str, *texts: str) -> bool:
    normalized = str(field or "").strip().lower()
    if not normalized:
        return False
    aliases = {normalized, normalized.replace("_", " ")}
    aliases.update(part for part in re.split(r"[_\W]+", normalized) if part)
    for text in texts:
        haystack = text or ""
        for alias in aliases:
            pattern = re.escape(alias).replace(r"\ ", r"[ _-]+")
            if re.search(rf"\b{pattern}\b", haystack, flags=re.IGNORECASE):
                return True
    return False


def tool_required_fields(tool: ToolInfo) -> set[str]:
    required = set((tool.input_schema or {}).get("required") or [])
    required.update(path_param_names(tool.endpoint))
    required.update(tool.path_params or [])
    return {str(field) for field in required if str(field)}


def missing_required_fields(tool: ToolInfo, args: dict[str, Any]) -> list[str]:
    return sorted(
        field
        for field in tool_required_fields(tool)
        if field not in args or args.get(field) in (None, "")
    )


def sanitize_tool_args_against_schema(
    tool: ToolInfo,
    args: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    schema = tool.input_schema or {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    if not isinstance(args, dict) or not properties:
        return ({}, sorted(args.keys())) if isinstance(args, dict) and not properties else (args or {}, [])

    sanitized: dict[str, Any] = {}
    dropped: list[str] = []
    for field, value in args.items():
        if field not in properties:
            dropped.append(str(field))
            continue
        if value is None:
            continue

        field_schema = properties.get(field)
        if not isinstance(field_schema, dict):
            sanitized[field] = value
            continue

        candidate = value
        field_type = field_schema.get("type")
        if isinstance(field_type, list):
            field_type = next((t for t in field_type if t != "null"), None)
        if field_type in {"string", "integer", "number"}:
            try:
                candidate = coerce_field_value(value=value, field_type=field_type)
            except Exception:
                dropped.append(str(field))
                continue

        if not Draft202012Validator(field_schema).is_valid(candidate):
            dropped.append(str(field))
            continue
        sanitized[field] = candidate

    return sanitized, dropped


def build_unsupported_enum_clarification(
    *,
    tool: ToolInfo,
    raw_args: dict[str, Any],
    sanitized_args: dict[str, Any],
    dropped_fields: list[str],
    intent: str,
    clause: str,
    arg_provenance: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    schema = tool.input_schema or {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    entity = (tool.endpoint or "").strip("/").split("/", 1)[0] or "record"

    for field in dropped_fields:
        field_schema = properties.get(field)
        if not isinstance(field_schema, dict):
            continue
        enum_values = field_schema.get("enum")
        if not isinstance(enum_values, list) or not enum_values:
            continue
        if field in sanitized_args:
            continue
        raw_value = raw_args.get(field)
        if raw_value in (None, ""):
            continue
        provenance = arg_provenance.get(field) if isinstance(arg_provenance, dict) else None
        source = str((provenance or {}).get("source") or "").strip().lower()
        represented_by_another_enum = False
        if source != "user" and not field_name_found_in_text(field, intent, clause):
            for kept_field, kept_value in sanitized_args.items():
                if kept_field == field or not same_arg_value(raw_value, kept_value):
                    continue
                kept_schema = properties.get(kept_field)
                if isinstance(kept_schema, dict) and isinstance(kept_schema.get("enum"), list):
                    represented_by_another_enum = value_found_in_text(raw_value, intent, clause)
                    break
        if represented_by_another_enum:
            continue
        allowed = ", ".join(str(value) for value in enum_values)
        return (
            f'I found {entity}s, but I could not safely map "{raw_value}" to a valid {field}. '
            f"Allowed {field} values are: {allowed}."
        )
    return None


def mark_user_provenance(
    *,
    provenance: dict[str, dict[str, Any]],
    field: str,
    value: Any,
    confidence: float = 1.0,
) -> None:
    provenance[field] = {"value": value, "source": "user", "confidence": confidence}


def promote_user_provenance(
    *,
    tool: ToolInfo,
    args: dict[str, Any],
    intent: str,
    evidence: dict[str, Any] | None = None,
    resolved_predicates: dict[str, Any] | None = None,
    arg_provenance: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    del tool
    promoted: dict[str, dict[str, Any]] = {}
    resolved = resolved_predicates if isinstance(resolved_predicates, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    for field, value in (args or {}).items():
        existing = arg_provenance.get(field) if isinstance(arg_provenance, dict) else None
        promoted[field] = dict(existing) if isinstance(existing, dict) else {"source": "llm"}
        promoted[field]["value"] = value
        promoted[field]["source"] = "llm"
        evidence_text = str(evidence.get(field) or "")
        if (
            not is_placeholder(value)
            and (value_found_in_text(value, intent, evidence_text) or field in resolved)
        ):
            mark_user_provenance(provenance=promoted, field=field, value=value)
    return promoted


def strip_unsupported_optional_args(
    *,
    tool: ToolInfo,
    args: dict[str, Any],
    intent: str,
    intent_memory: dict[str, Any] | None = None,
    resolved_predicates: dict[str, Any] | None = None,
    arg_provenance: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    required_fields = tool_required_fields(tool)
    memory_values: set[str] = set()
    if isinstance(intent_memory, dict):
        for binding in intent_memory.get("positive_bindings") or []:
            if isinstance(binding, dict):
                value = binding.get("value") or binding.get("term")
                if value:
                    memory_values.add(str(value).strip().lower())

    clean: dict[str, Any] = {}
    dropped: list[str] = []
    for field, value in (args or {}).items():
        if field in required_fields:
            clean[field] = value
            continue

        value_text = str(value).strip().lower()
        provenance = arg_provenance.get(field) if isinstance(arg_provenance, dict) else None
        source_is_user = str((provenance or {}).get("source") or "").strip().lower() == "user"
        supported = (
            source_is_user
            and not is_placeholder(value)
            and (
                value_found_in_text(value, intent)
                or value_text in memory_values
                or (isinstance(resolved_predicates, dict) and field in resolved_predicates)
            )
        )
        control_supported = field in _SAFE_CONTROL_FIELDS and not is_placeholder(value)
        if supported or control_supported:
            clean[field] = value
            continue

        dropped.append(field)
        log_event(
            "guardrail_optional_arg_stripped",
            level="WARNING",
            reason="no_provenance",
            field=field,
            value=str(value),
            tool_name=tool.name,
            intent=intent,
        )

    return clean, dropped


def validate_agent_tool_args(
    *,
    tool: ToolInfo,
    raw_args: dict[str, Any],
    intent: str,
    evidence: dict[str, Any] | None = None,
    intent_memory: dict[str, Any] | None = None,
    allow_partial_for_approval: bool = True,
) -> GuardrailResult:
    sanitized, dropped = sanitize_tool_args_against_schema(tool, raw_args or {})
    clarification = build_unsupported_enum_clarification(
        tool=tool,
        raw_args=raw_args or {},
        sanitized_args=sanitized,
        dropped_fields=dropped,
        intent=intent,
        clause=intent,
    )
    provenance = promote_user_provenance(
        tool=tool,
        args=sanitized,
        intent=intent,
        evidence=evidence,
    )
    clean, provenance_dropped = strip_unsupported_optional_args(
        tool=tool,
        args=sanitized,
        intent=intent,
        intent_memory=intent_memory,
        arg_provenance=provenance,
    )
    missing = missing_required_fields(tool, clean)
    if missing and tool.requires_approval and allow_partial_for_approval:
        missing = []
    return GuardrailResult(
        args=clean,
        dropped_fields=[*dropped, *provenance_dropped],
        missing_required=missing,
        clarification=clarification,
        provenance=provenance,
    )


