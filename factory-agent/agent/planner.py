from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Literal

import httpx
from jsonschema import Draft202012Validator

from .config import Settings
from .intent_verifier import verify_clause_against_tool
from .intent import assess_intent
from .plan_validator import validate_plan
from .prompting import build_planner_prompt
from .reasoning_pipeline import ReasoningPipeline
from .schemas import PlanBinding, PlanDraft, PlanStepDraft, ToolInfo
from .telemetry import log_event, log_llm_prompt, log_llm_prompt_skipped
from .tool_intent_profile import (
    ToolIntentVocabulary,
    build_tool_intent_profile,
    child_tools_for_parent,
    intent_feature_tokens,
    load_generated_vocabulary,
    profile_match_score,
    tool_covers_descriptive_terms,
    vocabulary_for_tools,
)
from .tool_registry import ToolRegistry


PlannerBackendName = Literal["legacy", "structured", "langchain"]


class PlannerBackendError(RuntimeError):
    pass


class PlannerClarificationError(PlannerBackendError):
    def __init__(
        self,
        message: str,
        *,
        predicates: list[dict[str, Any]] | None = None,
        negative_bindings: list[dict[str, Any]] | None = None,
    ):
        self.predicates = predicates or []
        self.negative_bindings = negative_bindings or []
        super().__init__(message)


class PlannerConfirmationRequired(PlannerBackendError):
    def __init__(self, message: str, *, confirmation: dict[str, Any]):
        self.confirmation = confirmation
        super().__init__(message)


@dataclass(frozen=True)
class PlannerResult:
    draft: PlanDraft
    backend_used: PlannerBackendName
    llm_calls: int = 0
    intent_contract: dict[str, Any] | None = None


_NUMBER_RE = re.compile(r"\b\d+\b")
_KEYWORD_ID_RE: re.Pattern[str] | None = None
_KEYWORD_TOKEN_ID_RE: re.Pattern[str] | None = None
_TOKEN_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\b")
_SKU_RE = re.compile(r"\bsku\s*[:#-]?\s*([a-zA-Z0-9_-]+)\b", re.IGNORECASE)
_QUANTITY_RE = re.compile(r"\b(\d+)\s*(?:units?|pcs?|pieces?)\b", re.IGNORECASE)
_QUANTITY_FOR_RE = re.compile(r"\b(?:for|of)\s+(\d+)\s*(?:units?|pcs?|pieces?)\b", re.IGNORECASE)
_QUANTITY_FIELD_RE = re.compile(r"\b(?:quantity(?:_total)?|qty)\s*(?:is|=|:)?\s*(\d+)\b", re.IGNORECASE)
_DEADLINE_RE = re.compile(
    r"\b(?:deadline|due(?:\s+date)?|by)\s*[:=]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2}(?:[ T][0-9]{1,2}:[0-9]{2})?)\b",
    re.IGNORECASE,
)
_NOTES_RE = re.compile(r"\bnotes?\s*[:=]\s*(.+)$", re.IGNORECASE)
_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")
_COMPOUND_SEPARATOR_RE = re.compile(
    r"\b(?:and then|then|next|after that|afterwards|but first|but before that"
    r"|once done|when done|once that is done|when that is done|finally)\b"
    r"|[;]+",
    re.IGNORECASE,
)
_AND_CONNECTOR_RE = re.compile(r"\b(?:and|also)\b", re.IGNORECASE)
_ACTION_VERB_RE = re.compile(
    r"\b(?:check|show|list|get|find|view|inspect|update|set|create|delete"
    r"|approve|reject|replan|assign|schedule|replenish|move|run|add|open|remove|cancel|start|stop|restart|reset|transfer)\b",
    re.IGNORECASE,
)
# Matches numbered steps like "1." or "1)" or "2." at the start of a clause.
_NUMBERED_STEP_RE = re.compile(r"(?:^|\s)\d+[.)]+\s")
# Protects decimal/version numbers (e.g. v2.1, 3.14) from period splitting.
_DECIMAL_PERIOD_PLACEHOLDER = "\x00DECPT\x00"
_DECIMAL_PERIOD_RE = re.compile(r"(\d)\.(?=\d)")
_AUXILIARY_CAPABILITY_TAGS = {
    "approve",
    "create",
    "delete",
    "list",
    "lookup",
    "pending",
    "read",
    "reject",
    "status",
    "update",
}
_FIELD_MAPPING_GROUPS = {
    "quantity": {"amount", "count", "quantity", "quantity_total", "qty", "total", "units"},
    "deadline": {"deadline", "due", "due_date", "required_by", "target_date"},
    "notes": {"comment", "comments", "description", "note", "notes", "reason"},
    "ids_only": {"ids_only", "id_only"},
    "fields": {"fields", "select"},
}
_CONFIRMATION_STOPWORDS = {
    "a",
    "all",
    "an",
    "and",
    "any",
    "check",
    "find",
    "get",
    "list",
    "show",
    "the",
    "view",
}
_INTENT_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_ID_ONLY_PHRASE_RE = re.compile(r"\b(?:ids?\s+only|only\s+ids?|only\s+id|id\s+only)\b", re.IGNORECASE)
_LIST_VERB_RE = re.compile(r"\b(?:get|show|list|find|view|fetch|give|provide)\b", re.IGNORECASE)
_ID_PATTERN_CATALOG_PATH = Path(__file__).resolve().parent / "generated" / "id_patterns.json"
_ID_PATTERN_PREFIX_CACHE: list[tuple[str, str]] | None = None


def _registry_entity_tokens(vocabulary: ToolIntentVocabulary | None = None) -> set[str]:
    vocab = vocabulary or load_generated_vocabulary()
    return {token for token in vocab.entity_tokens if token and len(token) > 1}


def _entity_keyword_regex(*, token_ids: bool) -> re.Pattern[str] | None:
    global _KEYWORD_ID_RE, _KEYWORD_TOKEN_ID_RE
    cached = _KEYWORD_TOKEN_ID_RE if token_ids else _KEYWORD_ID_RE
    if cached is not None:
        return cached
    tokens = sorted(_registry_entity_tokens(), key=len, reverse=True)
    if not tokens:
        return None
    alternation = "|".join(re.escape(token) for token in tokens)
    if token_ids:
        pattern = re.compile(
            rf"\b({alternation})\s+(?:id\s+)?([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\b",
            re.IGNORECASE,
        )
        _KEYWORD_TOKEN_ID_RE = pattern
        return pattern
    pattern = re.compile(rf"\b({alternation})\s+#?(\d+)\b", re.IGNORECASE)
    _KEYWORD_ID_RE = pattern
    return pattern


def _tool_prefers_entity_lookup(tool: ToolInfo) -> bool:
    token = f"{tool.name} {tool.endpoint}".lower()
    return "{id}" in token or "_{id}" in token


def _tool_required_arg_count(tool: ToolInfo) -> int:
    return len((tool.input_schema or {}).get("required", []))


def _tool_missing_required_args(tool: ToolInfo, args: dict[str, Any]) -> int:
    required = list((tool.input_schema or {}).get("required", []))
    return sum(1 for field in required if field not in args or args.get(field) in (None, ""))


def _tool_missing_required_path_args(tool: ToolInfo, args: dict[str, Any]) -> int:
    path_fields = set(tool.path_params or []) | set(_path_param_names(tool.endpoint))
    if not path_fields:
        return 0
    return sum(1 for field in path_fields if field not in args or args.get(field) in (None, ""))


def _tool_missing_required_fields(tool: ToolInfo, args: dict[str, Any]) -> list[str]:
    required = list((tool.input_schema or {}).get("required", []))
    return [field for field in required if field not in args or args.get(field) in (None, "")]


def _path_param_names(endpoint: str) -> list[str]:
    return [match.group(1) for match in _PATH_PARAM_RE.finditer(endpoint or "")]


def _normalize_entity_keyword(keyword: str) -> str:
    lowered = keyword.lower()
    if lowered.endswith("ies") and len(lowered) > 3:
        return lowered[:-3] + "y"
    if lowered.endswith("s") and len(lowered) > 3:
        return lowered[:-1]
    return lowered


def _id_pattern_prefixes() -> list[tuple[str, str]]:
    global _ID_PATTERN_PREFIX_CACHE
    if _ID_PATTERN_PREFIX_CACHE:
        return _ID_PATTERN_PREFIX_CACHE
    if _ID_PATTERN_PREFIX_CACHE == [] and not _ID_PATTERN_CATALOG_PATH.exists():
        return _ID_PATTERN_PREFIX_CACHE
    try:
        raw = json.loads(_ID_PATTERN_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        _ID_PATTERN_PREFIX_CACHE = []
        return _ID_PATTERN_PREFIX_CACHE

    prefixes: list[tuple[str, str]] = []
    for item in raw.get("prefixes") or []:
        if not isinstance(item, dict):
            continue
        prefix = str(item.get("prefix") or "").strip().upper()
        entity = str(item.get("entity") or "").strip().lower()
        if prefix and entity:
            prefixes.append((prefix, entity))
    _ID_PATTERN_PREFIX_CACHE = sorted(dict.fromkeys(prefixes), key=lambda pair: len(pair[0]), reverse=True)
    return _ID_PATTERN_PREFIX_CACHE


def _infer_entity_from_identifier(token: str) -> str | None:
    upper = token.upper()
    for prefix, entity in _id_pattern_prefixes():
        if upper.startswith(prefix):
            return entity
    return None


def _infer_primary_entity(tool: ToolInfo) -> str | None:
    for raw in (tool.endpoint or "").strip("/").split("/"):
        if raw and not (raw.startswith("{") and raw.endswith("}")):
            return _normalize_entity_keyword(raw)

    for tag in tool.capability_tags or []:
        normalized = str(tag).strip().lower()
        if normalized and normalized not in _AUXILIARY_CAPABILITY_TAGS:
            return _normalize_entity_keyword(normalized)
    return None


def _is_root_collection_for_entity(tool: ToolInfo, entity: str | None) -> bool:
    if not entity or tool.method != "GET" or "{" in (tool.endpoint or ""):
        return False
    endpoint = (tool.endpoint or "").strip("/").lower()
    return endpoint in {entity, f"{entity}s"}


def _tool_filter_enum_matches_intent(intent: str, tool: ToolInfo) -> bool:
    tokens = _intent_tokens(intent)
    properties = (tool.input_schema or {}).get("properties")
    if not isinstance(properties, dict):
        return False
    for schema in properties.values():
        if not isinstance(schema, dict):
            continue
        enum_values = schema.get("enum")
        if not isinstance(enum_values, list):
            continue
        if any(str(value).strip().lower() in tokens for value in enum_values):
            return True
    return False


def _tool_matches_entity(tool: ToolInfo, entity: str | None) -> bool:
    return bool(entity) and _infer_primary_entity(tool) == entity


def _tool_intent_match_score(intent: str, tool: ToolInfo, *, vocabulary: ToolIntentVocabulary | None = None) -> int:
    assessment = assess_intent(intent)
    intent_lower = intent.lower()
    token = f"{tool.name} {tool.description} {tool.endpoint} {' '.join(tool.capability_tags or [])}".lower()
    score = profile_match_score(intent, tool, vocabulary=vocabulary)
    for keyword in _registry_entity_tokens(vocabulary):
        if keyword in intent_lower and keyword in token:
            score += 1
    if assessment.entity and assessment.entity in token:
        score += 3
    for field in tool.body_fields:
        if field.lower() in intent_lower:
            score += 2
    if assessment.action == "create" and tool.method == "POST":
        score += 4
    elif assessment.action == "update" and tool.method in {"PUT", "PATCH"}:
        score += 4
    elif assessment.action == "approval" and "approval" in token:
        score += 5
    elif assessment.action == "delete" and tool.method == "DELETE":
        score += 4
    elif assessment.action == "read" and tool.method == "GET":
        score += 4
    if (
        assessment.action == "create"
        and tool.method == "POST"
        and assessment.entity
        and (tool.endpoint or "").strip("/").lower() in {assessment.entity, f"{assessment.entity}s"}
    ):
        score += 3
    score -= _tool_specialization_penalty(intent=intent, tool=tool, assessment=assessment)
    return score


def _intent_tokens(text: str) -> set[str]:
    tokens = {m.group(0).lower() for m in _INTENT_TOKEN_RE.finditer(text or "")}
    normalized: set[str] = set(tokens)
    for token in list(tokens):
        if token.endswith("ies") and len(token) > 3:
            normalized.add(token[:-3] + "y")
        elif token.endswith("s") and len(token) > 3:
            normalized.add(token[:-1])
    return normalized


def _tag_matches_intent(*, tag: str, tokens: set[str]) -> bool:
    normalized = tag.strip().lower()
    if not normalized:
        return False
    if normalized in tokens:
        return True
    if normalized.endswith("y") and (normalized[:-1] + "ies") in tokens:
        return True
    if (normalized + "s") in tokens:
        return True
    return False


def _tool_specialization_penalty(*, intent: str, tool: ToolInfo, assessment) -> int:
    tokens = _intent_tokens(intent)
    penalty = 0
    profile = build_tool_intent_profile(tool)
    for segment in profile.endpoint_segments:
        normalized = str(segment).strip().lower()
        if not normalized or normalized in _AUXILIARY_CAPABILITY_TAGS:
            continue
        if assessment.entity and normalized == assessment.entity:
            continue
        if _tag_matches_intent(tag=normalized, tokens=tokens):
            continue
        penalty += 6
    return penalty


def _endpoint_feature_matches(
    intent: str,
    tool: ToolInfo,
    *,
    vocabulary: ToolIntentVocabulary | None = None,
) -> set[str]:
    vocab = vocabulary or load_generated_vocabulary()
    profile = build_tool_intent_profile(tool, vocabulary=vocab)
    features = intent_feature_tokens(intent, vocabulary=vocab)
    return features & set(profile.endpoint_segments)


def _extract_intent_entities(intent: str) -> dict[str, Any]:
    numbers = [int(match.group(0)) for match in _NUMBER_RE.finditer(intent or "")]
    ids_by_keyword: dict[str, Any] = {}
    keyword_id_re = _entity_keyword_regex(token_ids=False)
    if keyword_id_re:
        for match in keyword_id_re.finditer(intent or ""):
            ids_by_keyword[_normalize_entity_keyword(match.group(1))] = int(match.group(2))
    explicit_ids: list[str] = []
    keyword_token_id_re = _entity_keyword_regex(token_ids=True)
    if keyword_token_id_re:
        for match in keyword_token_id_re.finditer(intent or ""):
            keyword = _normalize_entity_keyword(match.group(1))
            value = match.group(2)
            ids_by_keyword[keyword] = value
            explicit_ids.append(value)
    for match in _TOKEN_ID_RE.finditer(intent or ""):
        value = match.group(1)
        explicit_ids.append(value)
        inferred = _infer_entity_from_identifier(value)
        if inferred and inferred not in ids_by_keyword:
            ids_by_keyword[inferred] = value

    lowered = (intent or "").lower()
    for entity in _registry_entity_tokens():
        if entity in ids_by_keyword:
            continue
        plural = entity[:-1] + "ies" if entity.endswith("y") else f"{entity}s"
        if re.search(rf"\b(?:missing|nonexistent|not[- ]real|unknown)\s+(?:{re.escape(entity)}|{re.escape(plural)})\b", lowered) or re.search(
            rf"\b(?:{re.escape(entity)}|{re.escape(plural)})\s+(?:missing|nonexistent|not[- ]real|unknown)\b",
            lowered,
        ):
            ids_by_keyword[entity] = "missing"

    sku_match = _SKU_RE.search(intent or "")
    sku_value = sku_match.group(1) if sku_match else None

    return {
        "numbers": numbers,
        "ids_by_keyword": ids_by_keyword,
        "explicit_ids": list(dict.fromkeys(explicit_ids)),
        "sku": sku_value,
    }


def _coerce_field_value(*, value: Any, field_type: str | None) -> Any:
    if field_type == "string":
        return str(value)
    if field_type == "integer":
        return int(value)
    if field_type == "number":
        return float(value)
    return value


def _extract_quantity_from_intent(intent: str) -> int | None:
    for regex in (_QUANTITY_FIELD_RE, _QUANTITY_FOR_RE, _QUANTITY_RE):
        match = regex.search(intent or "")
        if match:
            try:
                return int(match.group(1))
            except Exception:
                continue
    return None


def _extract_deadline_from_intent(intent: str) -> str | None:
    match = _DEADLINE_RE.search(intent or "")
    if not match:
        return None
    raw = match.group(1).strip()
    # Keep RFC3339-compatible shape when time is present.
    if " " in raw:
        raw = raw.replace(" ", "T", 1)
    return raw


def _extract_notes_from_intent(intent: str) -> str | None:
    match = _NOTES_RE.search(intent or "")
    if not match:
        return None
    value = match.group(1).strip().strip("\"'")
    return value if value else None


def _extract_field_value_from_intent(
    *,
    intent: str,
    field_name: str,
    field_schema: dict[str, Any],
) -> Any | None:
    field_type = field_schema.get("type")
    if isinstance(field_type, list):
        field_type = next((t for t in field_type if t != "null"), "string")
    field = field_name.lower()
    intent_lower = (intent or "").lower()

    if field in _FIELD_MAPPING_GROUPS["quantity"] and field_type in {"integer", "number"}:
        qty = _extract_quantity_from_intent(intent)
        if qty is not None:
            return qty

    if field in _FIELD_MAPPING_GROUPS["deadline"] and field_type == "string":
        deadline = _extract_deadline_from_intent(intent)
        if deadline:
            return deadline

    if field in _FIELD_MAPPING_GROUPS["notes"] and field_type == "string":
        notes = _extract_notes_from_intent(intent)
        if notes:
            return notes

    if field in _FIELD_MAPPING_GROUPS["ids_only"] and field_type == "boolean":
        if _intent_requests_id_only_fields(intent):
            return True

    if field in _FIELD_MAPPING_GROUPS["fields"] and field_type == "string":
        if _intent_requests_id_only_fields(intent):
            return "product_id"

    enum_values = field_schema.get("enum")
    if isinstance(enum_values, list) and field_type == "string":
        for enum_value in enum_values:
            token = str(enum_value).strip()
            if not token:
                continue
            if re.search(rf"\b{re.escape(token.lower())}\b", intent_lower):
                return token

    field_hint = re.escape(field).replace(r"\_", "[ _-]?")
    generic_match = re.search(rf"\b{field_hint}\s*[:=]\s*([^\n,;]+)", intent or "", flags=re.IGNORECASE)
    if generic_match:
        return generic_match.group(1).strip().strip("\"'")

    return None


def _intent_requests_id_only_fields(intent: str) -> bool:
    normalized = (intent or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if _ID_ONLY_PHRASE_RE.search(lowered):
        return True
    if not _LIST_VERB_RE.search(lowered):
        return False
    entity_tokens = _registry_entity_tokens()
    if not entity_tokens or not (_intent_tokens(lowered) & entity_tokens):
        return False
    # Handles phrasing like "get all product id" / "list machine ids".
    if re.search(r"\b(?:all\s+)?[a-z_]+\s+ids?\b", lowered):
        return True
    if re.search(r"\bids?\s+for\s+(?:all\s+)?[a-z_]+\b", lowered):
        return True
    return False


def _extract_required_args(intent: str, tool: ToolInfo) -> tuple[dict[str, Any], list[str]]:
    schema = tool.input_schema or {}
    properties = schema.get("properties", {})
    required = list(dict.fromkeys(list(schema.get("required", [])) + _path_param_names(tool.endpoint)))
    entities = _extract_intent_entities(intent)
    primary_entity = _infer_primary_entity(tool)
    args: dict[str, Any] = {}
    missing: list[str] = []

    for field in required:
        raw = properties.get(field, {})
        field_type = raw.get("type")
        if isinstance(field_type, list):
            field_type = next((t for t in field_type if t != "null"), "string")
        field_name = field.lower()

        value: Any | None = None
        if field_name == "sku":
            value = entities["sku"]
        elif field_name == "id":
            value = entities["ids_by_keyword"].get(primary_entity) if primary_entity else None
        elif field_name == "job_id":
            value = entities["ids_by_keyword"].get("job")
        elif field_name in ("machine_id",):
            value = entities["ids_by_keyword"].get("machine")
        elif field_name in ("inventory_id", "item_id"):
            value = entities["ids_by_keyword"].get("inventory")
        elif field_name == "material_id":
            value = entities["ids_by_keyword"].get("inventory")
        elif field_name == "approval_id":
            value = entities["ids_by_keyword"].get("approval")
        elif field_name == "proposal_id":
            value = entities["ids_by_keyword"].get("proposal")
        elif field_name == "line_id":
            value = entities["ids_by_keyword"].get("line")

        if value is None and field_name.endswith("_id"):
            keyword = field_name[:-3]
            keyword = "inventory" if keyword == "material" else keyword
            value = entities["ids_by_keyword"].get(keyword)

        if value is None and field_name == "id" and len(entities["explicit_ids"]) == 1:
            value = entities["explicit_ids"][0]

        if value is None and field_type in ("integer", "number") and len(entities["numbers"]) == 1:
            value = entities["numbers"][0]

        if value is None and field_name in ("name", "machine_name") and "machine" in (primary_entity or ""):
            name_match = re.search(r"\b(?:named|name)\s+([A-Za-z0-9 _-]+)$", intent or "", flags=re.IGNORECASE)
            if name_match:
                value = name_match.group(1).strip()

        if value is None:
            value = _extract_field_value_from_intent(intent=intent, field_name=field, field_schema=raw)

        if value is None:
            missing.append(field)
            continue

        try:
            args[field] = _coerce_field_value(value=value, field_type=field_type)
        except Exception:
            missing.append(field)

    # Opportunistically prefill optional fields so approval forms are useful out-of-the-box.
    for field, raw in properties.items():
        if field in args:
            continue
        value = _extract_field_value_from_intent(intent=intent, field_name=field, field_schema=raw if isinstance(raw, dict) else {})
        if value is None:
            continue
        field_type = raw.get("type") if isinstance(raw, dict) else None
        if isinstance(field_type, list):
            field_type = next((t for t in field_type if t != "null"), "string")
        try:
            args[field] = _coerce_field_value(value=value, field_type=field_type)
        except Exception:
            continue

    return args, missing


def _merge_deterministic_supported_args(
    intent: str,
    tool: ToolInfo,
    args: dict[str, Any],
    *,
    provenance: dict[str, dict[str, Any]] | None = None,
    exclude_fields: set[str] | None = None,
) -> dict[str, Any]:
    del provenance
    deterministic_args, _ = _extract_required_args(intent, tool)
    if not deterministic_args:
        return args
    merged = dict(args)
    excluded = exclude_fields or set()
    for field, value in deterministic_args.items():
        if field in excluded:
            continue
        if merged.get(field) in (None, ""):
            merged[field] = value
    return merged


def _sanitize_tool_args_against_schema(tool: ToolInfo, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
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
                candidate = _coerce_field_value(value=value, field_type=field_type)
            except Exception:
                dropped.append(str(field))
                continue

        if not Draft202012Validator(field_schema).is_valid(candidate):
            dropped.append(str(field))
            continue
        sanitized[field] = candidate

    return sanitized, dropped


def _build_unsupported_enum_clarification(
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
    entity = _infer_primary_entity(tool) or "record"

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
        if source != "user" and not _field_name_found_in_text(field, intent, clause):
            for kept_field, kept_value in sanitized_args.items():
                if kept_field == field or not _same_arg_value(raw_value, kept_value):
                    continue
                kept_schema = properties.get(kept_field)
                if isinstance(kept_schema, dict) and isinstance(kept_schema.get("enum"), list):
                    represented_by_another_enum = _value_found_in_text(raw_value, intent, clause)
                    break
        if represented_by_another_enum:
            continue
        allowed = ", ".join(str(value) for value in enum_values)
        return (
            f'I found {entity}s, but I could not safely map "{raw_value}" to a valid {field}. '
            f"Allowed {field} values are: {allowed}."
        )
    return None


# ---------------------------------------------------------------------------
# Provenance validation for optional filter args
# ---------------------------------------------------------------------------

# Values that are clearly synthesised placeholders and must never be sent.
_PLACEHOLDER_VALUES: frozenset[str] = frozenset({
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
})

# Control / pagination fields are always safe — they never filter business data.
_SAFE_CONTROL_FIELDS: frozenset[str] = frozenset({
    "limit", "offset", "page", "page_size", "sort_by", "sort_dir",
    "order_by", "order_dir", "fields", "ids_only",
})
_USER_CONFIRMATION_MIN_CONFIDENCE = 0.6


def _unwrap_arg_provenance(args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    clean: dict[str, Any] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for field, value in (args or {}).items():
        if isinstance(value, dict) and "value" in value:
            source = str(value.get("source") or "llm").strip().lower()
            if source not in {"user", "llm"}:
                source = "llm"
            entry = {"value": value.get("value"), "source": source}
            if "confidence" in value:
                entry["confidence"] = value.get("confidence")
            clean[field] = value.get("value")
            provenance[field] = entry
            continue
        clean[field] = value
        provenance[field] = {"value": value, "source": "llm"}
    return clean, provenance


def _mark_user_provenance(
    *,
    provenance: dict[str, dict[str, Any]],
    field: str,
    value: Any,
    confidence: float = 1.0,
) -> None:
    provenance[field] = {"value": value, "source": "user", "confidence": confidence}


def _is_placeholder(value: Any) -> bool:
    """Return True when *value* looks like a synthesised placeholder."""
    if value is None:
        return True
    str_value = str(value).strip().lower()
    return str_value in _PLACEHOLDER_VALUES


def _value_found_in_text(value: Any, *texts: str) -> bool:
    """Return True when *value*'s string representation appears in at least one *text*."""
    needle = str(value).strip()
    if not needle:
        return False
    needle_lower = needle.lower()
    needle_compact = re.sub(r"[^a-z0-9]+", "", needle_lower)
    for text in texts:
        haystack = (text or "").lower()
        # Accept exact word-boundary match or substring match for short tokens.
        if re.search(rf"\b{re.escape(needle_lower)}\b", haystack):
            return True
        if needle_compact and needle_compact in re.sub(r"[^a-z0-9]+", "", haystack):
            return True
    return False


def _plan_step_dedupe_key(step: PlanStepDraft) -> str:
    return f"{step.tool_name}:{json.dumps(step.args or {}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)}"


def _dedupe_plan_steps(draft: PlanDraft) -> tuple[PlanDraft, int]:
    if len(draft.steps) <= 1:
        return draft, 0

    ordered = sorted(draft.steps, key=lambda s: s.step_index)
    by_old_index = {step.step_index: step for step in ordered}
    key_to_canonical_old: dict[str, int] = {}
    old_to_canonical_old: dict[int, int] = {}
    canonical_old_indexes: list[int] = []

    for step in ordered:
        old_idx = step.step_index
        key = _plan_step_dedupe_key(step)
        canonical_old = key_to_canonical_old.get(key)
        if canonical_old is None:
            key_to_canonical_old[key] = old_idx
            old_to_canonical_old[old_idx] = old_idx
            canonical_old_indexes.append(old_idx)
        else:
            old_to_canonical_old[old_idx] = canonical_old

    dropped = len(ordered) - len(canonical_old_indexes)
    if dropped <= 0:
        return draft, 0

    canonical_old_to_new: dict[int, int] = {
        old_idx: new_idx for new_idx, old_idx in enumerate(canonical_old_indexes)
    }
    old_to_new: dict[int, int] = {}
    for old_idx, canonical_old in old_to_canonical_old.items():
        mapped = canonical_old_to_new.get(canonical_old)
        if mapped is not None:
            old_to_new[old_idx] = mapped

    rebuilt_steps: list[PlanStepDraft] = []
    for canonical_old in canonical_old_indexes:
        src = by_old_index[canonical_old]
        new_idx = canonical_old_to_new[canonical_old]

        mapped_deps = []
        for dep in src.depends_on or []:
            dep_new = old_to_new.get(dep)
            if dep_new is None or dep_new == new_idx:
                continue
            mapped_deps.append(dep_new)
        mapped_deps = sorted(set(mapped_deps))

        rebuilt_bindings: list[PlanBinding] = []
        seen_binding_keys: set[tuple[int, str, str, str, str]] = set()
        for binding in src.bindings or []:
            from_new = old_to_new.get(binding.from_step)
            if from_new is None:
                continue
            binding_key = (
                from_new,
                str(binding.result_path),
                str(binding.field),
                str(binding.target_arg),
                str(binding.mode),
            )
            if binding_key in seen_binding_keys:
                continue
            seen_binding_keys.add(binding_key)
            rebuilt_bindings.append(
                PlanBinding(
                    from_step=from_new,
                    result_path=binding.result_path,
                    field=binding.field,
                    target_arg=binding.target_arg,
                    mode=binding.mode,
                )
            )

        rebuilt_steps.append(
            PlanStepDraft(
                step_index=new_idx,
                tool_name=src.tool_name,
                args=dict(src.args or {}),
                depends_on=mapped_deps,
                parallel_group=src.parallel_group,
                execution_mode=src.execution_mode,
                bindings=rebuilt_bindings,
            )
        )

    deduped = PlanDraft(
        plan_explanation=draft.plan_explanation,
        risk_summary=draft.risk_summary,
        steps=rebuilt_steps,
        dependency_graph=None,
        parallel_groups=None,
    )
    return deduped, dropped


def _assign_parallel_groups(
    steps: list[PlanStepDraft],
    tools_by_name: dict[str, ToolInfo],
    *,
    enabled: bool,
) -> list[list[int]]:
    if not enabled or len(steps) < 2:
        return []

    for step in steps:
        step.parallel_group = None

    groups: list[list[int]] = []
    i = 0
    while i < len(steps):
        candidates: list[PlanStepDraft] = []
        seen_endpoints: set[str] = set()
        j = i
        while j < len(steps):
            step = steps[j]
            tool = tools_by_name.get(step.tool_name)
            serial_dep = [step.step_index - 1] if step.step_index > 0 else []
            step_deps = sorted(set(int(dep) for dep in (step.depends_on or [])))
            if not tool or not tool.is_read_only or tool.requires_approval:
                break
            if step.bindings:
                break
            # Preserve explicit planner dependencies; only remove the default serial edge.
            if step_deps not in ([], serial_dep):
                break
            endpoint_key = f"{tool.method}:{tool.endpoint}"
            if endpoint_key in seen_endpoints:
                break
            seen_endpoints.add(endpoint_key)
            candidates.append(step)
            j += 1

        if len(candidates) >= 2:
            group_id = len(groups)
            group_indexes: list[int] = []
            for step in candidates:
                step.parallel_group = group_id
                step.depends_on = []
                group_indexes.append(step.step_index)
            groups.append(group_indexes)
            i = j
            continue

        i += 1

    return groups


def _field_name_found_in_text(field: str, *texts: str) -> bool:
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


def _same_arg_value(left: Any, right: Any) -> bool:
    if left == right:
        return True
    left_text = re.sub(r"\s+", " ", str(left).strip()).lower()
    right_text = re.sub(r"\s+", " ", str(right).strip()).lower()
    return bool(left_text) and left_text == right_text


def _tool_supports_arg_field(tool: ToolInfo, field: str) -> bool:
    schema = tool.input_schema or {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    if field in properties:
        return True
    required_fields = set(schema.get("required") or [])
    required_fields.update(_path_param_names(tool.endpoint))
    return field in required_fields


def _control_field_explicitly_requested(*, field: str, value: Any, intent: str, clause: str) -> bool:
    text = f"{intent} {clause}".lower()
    value_text = str(value).strip().lower()
    has_value = _value_found_in_text(value, intent, clause)
    field_text = field.replace("_", " ")

    if field in {"ids_only"}:
        return _intent_requests_id_only_fields(text)

    if field in {"fields"}:
        if value_text in {"id", "ids", "product_id"} and _intent_requests_id_only_fields(text):
            return True
        return bool(
            re.search(r"\b(?:fields?|select|only|ids?\s+only|only\s+ids?)\b", text)
            and (has_value or value_text in {"id", "ids", "product_id"})
        )

    if field in {"sort_by", "order_by"}:
        return bool(
            (re.search(r"\b(?:sort|order)\s+by\b", text) and has_value)
            or (
                _field_name_found_in_text(value_text, text)
                and re.search(
                    r"\b(?:earliest|soonest|latest|largest|highest|biggest|greatest|smallest|lowest|least|maximum|max|minimum|min|most)\b",
                    text,
                )
            )
        )

    if field in {"sort_dir", "order_dir"}:
        if not re.search(r"\b(?:sort|order|ascending|descending|asc|desc)\b", text):
            if value_text in {"asc", "ascending"}:
                return bool(re.search(r"\b(?:earliest|soonest|smallest|lowest|least|minimum|min)\b", text))
            if value_text in {"desc", "descending"}:
                return bool(re.search(r"\b(?:latest|largest|highest|biggest|greatest|maximum|max|most)\b", text))
            return False
        if value_text in {"asc", "ascending"}:
            return bool(re.search(r"\b(?:asc|ascending|increasing)\b", text))
        if value_text in {"desc", "descending"}:
            return bool(re.search(r"\b(?:desc|descending|decreasing)\b", text))
        return has_value

    if field in {"limit", "page_size"}:
        return bool(
            has_value
            and re.search(r"\b(?:limit|top|first|last|only|show|give|get|list)\s+\d+\b", text)
        )

    if field in {"offset", "page"}:
        return bool(has_value and re.search(rf"\b{re.escape(field_text)}\s+\d+\b", text))

    return bool(has_value and re.search(rf"\b{re.escape(field_text)}\b", text))


def _promote_user_provenance(
    *,
    tool: ToolInfo,
    args: dict[str, Any],
    intent: str,
    clause: str,
    arg_provenance: dict[str, dict[str, Any]] | None,
    resolved_predicates: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Mark only schema-valid, user-grounded args as user provenance."""
    promoted: dict[str, dict[str, Any]] = {}
    for field, value in (args or {}).items():
        existing = arg_provenance.get(field) if isinstance(arg_provenance, dict) else None
        promoted[field] = dict(existing) if isinstance(existing, dict) else {"source": "llm"}
        promoted[field]["value"] = value
        promoted[field]["source"] = "llm"

    deterministic_clause_args, _ = _extract_required_args(clause, tool)
    deterministic_intent_args, _ = _extract_required_args(intent, tool)
    resolved = resolved_predicates if isinstance(resolved_predicates, dict) else {}

    for field, value in (args or {}).items():
        if not _tool_supports_arg_field(tool, field) or _is_placeholder(value):
            continue
        if field in _SAFE_CONTROL_FIELDS and not _control_field_explicitly_requested(
            field=field,
            value=value,
            intent=intent,
            clause=clause,
        ):
            continue

        deterministic_match = (
            (field in deterministic_clause_args and _same_arg_value(deterministic_clause_args[field], value))
            or (field in deterministic_intent_args and _same_arg_value(deterministic_intent_args[field], value))
        )
        predicate_match = field in resolved and _same_arg_value(resolved[field], value)
        text_match = _value_found_in_text(value, intent, clause)
        if deterministic_match or predicate_match or text_match:
            _mark_user_provenance(provenance=promoted, field=field, value=value)

    return promoted


def _strip_unsupported_optional_args(
    *,
    tool: ToolInfo,
    args: dict[str, Any],
    intent: str,
    clause: str,
    intent_memory: dict[str, Any] | None = None,
    resolved_predicates: dict[str, Any] | None = None,
    arg_provenance: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Remove optional (non-required, non-path-param) filter args that lack provenance.

    An arg is considered *supported* when ANY of the following is true:
      1. It is a required field (from input_schema.required or path params).
      2. It is a safe control / pagination field (limit, offset, sort_by, …).
      3. Its value is NOT a known placeholder AND appears verbatim in the intent
         text or clause.
      4. Its value was positively confirmed via session memory.
      5. Its value is present in the IntentContract's resolved_predicates.

    Args that fail all checks are stripped.  A warning is logged per dropped arg.
    Returns (clean_args, list_of_dropped_field_names).
    """
    schema = tool.input_schema or {}
    required_fields: set[str] = set(schema.get("required") or [])
    required_fields.update(_path_param_names(tool.endpoint))

    # Build a quick lookup of positive memory bindings.
    memory_values: set[str] = set()
    if isinstance(intent_memory, dict):
        for binding in (intent_memory.get("positive_bindings") or []):
            if isinstance(binding, dict):
                v = binding.get("value") or binding.get("term")
                if v:
                    memory_values.add(str(v).strip().lower())

    clean: dict[str, Any] = {}
    dropped: list[str] = []

    for field, value in args.items():
        # --- 1. Always keep required / path-param fields (even if empty).
        if field in required_fields:
            clean[field] = value
            continue

        text = f"{intent} {clause}".lower()
        value_text = str(value).strip().lower()
        is_placeholder = value_text in _PLACEHOLDER_VALUES
        has_value_evidence = _value_found_in_text(value, intent, clause)
        provenance = arg_provenance.get(field) if isinstance(arg_provenance, dict) else None
        source = str((provenance or {}).get("source") or "").strip().lower()
        source_is_user = source == "user"

        # --- 2. Keep control fields only when the user asked for that value
        # or another deterministic stage marked it as supported. LLM-generated
        # sort/fields defaults can otherwise create backend 400s.
        if field in _SAFE_CONTROL_FIELDS and source_is_user and (
            has_value_evidence
            or value_text in memory_values
            or (isinstance(resolved_predicates, dict) and field in resolved_predicates)
        ):
            clean[field] = value
            continue

        if source_is_user and has_value_evidence and not is_placeholder:
            clean[field] = value
        elif source_is_user and value_text in memory_values:
            clean[field] = value
        elif source_is_user and isinstance(resolved_predicates, dict) and field in resolved_predicates:
            clean[field] = value
        else:
            dropped.append(field)
            log_event(
                "planner_optional_arg_stripped",
                level="WARNING",
                reason="no_provenance",
                field=field,
                value=str(value),
                tool_name=tool.name,
                intent=intent,
                clause=clause,
            )

    return clean, dropped


def _select_legacy_tool(intent: str, scoped_tools: list[ToolInfo], *, vocabulary: ToolIntentVocabulary | None = None) -> ToolInfo:
    assessment = assess_intent(intent)
    entities = _extract_intent_entities(intent)
    preferred_entity = assessment.entity or next(iter(entities["ids_by_keyword"]), None)
    vocab = vocabulary or load_generated_vocabulary()
    discriminating_features = intent_feature_tokens(intent, vocabulary=vocab) - ({preferred_entity} if preferred_entity else set())
    has_explicit_id = bool(entities["ids_by_keyword"]) or len(entities["numbers"]) == 1 or len(entities["explicit_ids"]) == 1

    preferred_subresource = _preferred_parent_subresource_tool(intent, scoped_tools, vocabulary=vocab)
    if preferred_subresource is not None and not re.search(
        r"\b(?:and then|then|next|after that|afterwards|finally)\b|[;\n.]+",
        intent or "",
        flags=re.IGNORECASE,
    ):
        return preferred_subresource

    ranked = sorted(
        scoped_tools,
        key=lambda t: (
            _tool_missing_required_path_args(t, _extract_required_args(intent, t)[0]),
            not (
                _is_root_collection_for_entity(t, preferred_entity)
                and _tool_filter_enum_matches_intent(intent, t)
            ),
            not tool_covers_descriptive_terms(intent, t, vocabulary=vocabulary),
            not _tool_matches_entity(t, preferred_entity),
            not (
                (assessment.action == "create" and t.method == "POST")
                or (assessment.action == "update" and t.method in {"PUT", "PATCH"})
                or (assessment.action == "approval" and "approval" in " ".join(t.capability_tags).lower())
                or (assessment.action == "delete" and t.method == "DELETE")
                or (assessment.action == "read" and t.method == "GET")
                or assessment.action is None
            ),
            not (has_explicit_id and not discriminating_features and _tool_prefers_entity_lookup(t)),
            -_tool_intent_match_score(intent, t, vocabulary=vocabulary),
            _tool_missing_required_args(t, _extract_required_args(intent, t)[0]),
            0
            if (
                (assessment.action == "create" and t.method == "POST")
                or (assessment.action == "update" and t.method in {"PUT", "PATCH"})
                or (assessment.action == "delete" and t.method == "DELETE")
                or (assessment.action == "read" and t.method == "GET")
                or assessment.action is None
            )
            else 1,
            not t.is_read_only,
            t.name,
        ),
    )
    return ranked[0]


def _diagnostic_plan_override(intent: str, scoped_tools: list[ToolInfo]) -> tuple[ToolInfo, dict[str, Any]] | None:
    lowered = (intent or "").lower()
    tools = {tool.name: tool for tool in scoped_tools}
    if "network" in lowered and "timeout" in lowered and "get__jobs" in tools:
        return tools["get__jobs"], {}
    if "404" in lowered and "read" in lowered and "get__jobs_{id}" in tools:
        return tools["get__jobs_{id}"], {"id": "JOB-NOT-REAL"}
    return None


def _clean_clause(text: str) -> str:
    """Strip leading/trailing whitespace, commas, and trailing sentence-ending punctuation."""
    cleaned = text.strip(" ,")
    # Remove trailing periods/exclamation/question marks (but not mid-clause ones)
    cleaned = re.sub(r"[.!?]+$", "", cleaned).strip()
    return cleaned


def _split_compound_intent(intent: str) -> list[str]:
    raw = (intent or "").strip()
    if not raw:
        return [""]

    # ── Pre-processing ──
    # 1. Protect decimal/version periods (e.g. v2.1, 3.14) so they survive
    #    the sentence-boundary split below.
    protected = _DECIMAL_PERIOD_RE.sub(rf"\1{_DECIMAL_PERIOD_PLACEHOLDER}", raw)

    # 2. Convert newlines to a separator the regex can see *before* collapsing
    #    whitespace, so "show jobs\ncheck machine" becomes two clauses.
    protected = protected.replace("\n", " ; ")

    # 3. Normalize whitespace
    normalized = re.sub(r"\s+", " ", protected).strip()

    # ── Tier 0: Numbered steps  ("1. do X 2. do Y 3. do Z") ──
    if _NUMBERED_STEP_RE.search(normalized):
        # Split on the numbered prefixes and discard the numbers themselves.
        step_parts = re.split(r"(?:^|\s)\d+[.)]+\s", normalized)
        step_parts = [_clean_clause(p.replace(_DECIMAL_PERIOD_PLACEHOLDER, ".")) for p in step_parts if p and p.strip()]
        if len(step_parts) >= 2:
            actionful = sum(1 for p in step_parts if _ACTION_VERB_RE.search(p))
            if actionful >= 2:
                return step_parts

    # ── Tier 1: Explicit sequencing connectors ──
    #    "and then", "then", "but first", "once done", ";"
    parts = [_clean_clause(p.replace(_DECIMAL_PERIOD_PLACEHOLDER, ".")) for p in _COMPOUND_SEPARATOR_RE.split(normalized) if p and p.strip(" ,")]
    if len(parts) > 1:
        return parts

    # ── Tier 1.5: Sentence-boundary periods ──
    #    Split on "." only when the period is a true sentence boundary
    #    (not inside a decimal/version like v2.1).
    if "." in normalized:
        dot_parts = [_clean_clause(p.replace(_DECIMAL_PERIOD_PLACEHOLDER, ".")) for p in re.split(r"\.+", normalized) if p and p.strip()]
        if len(dot_parts) > 1:
            actionful = sum(1 for p in dot_parts if _ACTION_VERB_RE.search(p))
            if actionful >= 2:
                return dot_parts

    # ── Tier 2: "and" / "also" with distinct action verbs ──
    #    Only split when BOTH halves carry their own action verb.
    #    Skip if the sentence contains a reason/causal clause ("because", "since",
    #    "so that", "in order to") — the "and" after these connects the reason,
    #    not separate actions.
    _has_reason_clause = bool(re.search(
        r"\b(?:because|since|so that|in order to|due to|as long as|given that)\b",
        normalized, re.IGNORECASE,
    ))
    if not _has_reason_clause and (" and " in normalized.lower() or " also " in normalized.lower()):
        and_parts = [_clean_clause(p.replace(_DECIMAL_PERIOD_PLACEHOLDER, ".")) for p in _AND_CONNECTOR_RE.split(normalized) if p and p.strip(" ,")]
        actionful_parts = sum(1 for part in and_parts if _ACTION_VERB_RE.search(part))
        if len(and_parts) > 1 and actionful_parts >= 2:
            return and_parts

    # ── Tier 3: Comma-separated with distinct action verbs ──
    #    "list jobs, check machine M-01" → 2 clauses
    #    "show jobs, machines, and materials" → stays 1 (only 1 verb)
    if "," in normalized:
        comma_parts = [_clean_clause(p.replace(_DECIMAL_PERIOD_PLACEHOLDER, ".")) for p in normalized.split(",") if p and p.strip()]
        # Guard: each resulting clause must have its own action verb.
        actionful_parts = sum(1 for part in comma_parts if _ACTION_VERB_RE.search(part))
        if len(comma_parts) > 1 and actionful_parts >= len(comma_parts):
            return comma_parts

    # ── No split — return as single clause ──
    result = normalized.replace(_DECIMAL_PERIOD_PLACEHOLDER, ".")
    return [_clean_clause(result) or result]


def _terminal_endpoint_tokens(tool: ToolInfo) -> set[str]:
    parts = [part for part in (tool.endpoint or "").strip("/").split("/") if part and "{" not in part]
    if not parts:
        return set()
    return _intent_tokens(parts[-1].replace("-", " "))


def _is_parent_subresource_tool(tool: ToolInfo) -> bool:
    parts = [part for part in (tool.endpoint or "").strip("/").split("/") if part]
    return (
        tool.method == "GET"
        and len(parts) >= 3
        and "{" in parts[-2]
        and "{" not in parts[-1]
    )


def _preferred_parent_subresource_tool(
    intent: str,
    scoped_tools: list[ToolInfo],
    *,
    vocabulary: ToolIntentVocabulary | None = None,
) -> ToolInfo | None:
    entities = _extract_intent_entities(intent)
    preferred_entity = next(iter(entities["ids_by_keyword"]), None)
    if not preferred_entity:
        return None

    candidates = [
        tool
        for tool in scoped_tools
        if _is_parent_subresource_tool(tool)
        and _infer_primary_entity(tool) == preferred_entity
        and _child_requested_by_clause(intent, tool)
        and _tool_missing_required_path_args(tool, _extract_required_args(intent, tool)[0]) == 0
    ]
    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda tool: (
            -_tool_intent_match_score(intent, tool, vocabulary=vocabulary),
            _tool_missing_required_args(tool, _extract_required_args(intent, tool)[0]),
            tool.name,
        ),
    )[0]


def _find_get_tool_for_endpoint(endpoint: str, scoped_tools: list[ToolInfo]) -> ToolInfo | None:
    return next(
        (
            tool
            for tool in scoped_tools
            if tool.method == "GET" and tool.endpoint == endpoint
        ),
        None,
    )


def _parent_lookup_tool(child: ToolInfo, scoped_tools: list[ToolInfo]) -> ToolInfo | None:
    parts = [part for part in (child.endpoint or "").strip("/").split("/") if part]
    if len(parts) < 3:
        return None
    if "{" not in parts[-2]:
        return None
    parent_endpoint = "/" + "/".join(parts[:-1])
    return _find_get_tool_for_endpoint(parent_endpoint, scoped_tools)


def _child_requested_by_clause(clause: str, child: ToolInfo) -> bool:
    tokens = _intent_tokens(clause)
    terminal = _terminal_endpoint_tokens(child)
    return bool(terminal and terminal <= tokens) or bool(terminal and terminal & tokens and re.search(r"\b(?:its|with|and)\b", clause or "", re.IGNORECASE))


def _requested_child_tools(clause: str, parent: ToolInfo, scoped_tools: list[ToolInfo]) -> list[ToolInfo]:
    children = child_tools_for_parent(parent, scoped_tools)
    requested = [child for child in children if _child_requested_by_clause(clause, child)]
    requested.sort(key=lambda tool: (-_tool_intent_match_score(clause, tool), tool.name))
    return requested


def _lookup_tool_for_created_resource(write_tool: ToolInfo, scoped_tools: list[ToolInfo]) -> ToolInfo | None:
    if write_tool.method != "POST":
        return None
    base = (write_tool.endpoint or "").rstrip("/")
    if not base or "{" in base:
        return None
    return _find_get_tool_for_endpoint(f"{base}/{{id}}", scoped_tools)


def _binding_field_for_lookup(source_tool: ToolInfo, target_tool: ToolInfo) -> str:
    root = (target_tool.endpoint or "").strip("/").split("/", 1)[0]
    root = root[:-1] if root.endswith("s") and len(root) > 1 else root
    preferred = [f"{root}_id", "id", "job_id", "machine_id", "product_id", "material_id", "proposal_id"]
    try:
        data = (source_tool.output_schema or {}).get("properties", {}).get("data", {})
        properties = data.get("properties") if isinstance(data, dict) else {}
        if isinstance(properties, dict):
            for field in preferred:
                if field in properties:
                    return field
    except Exception:
        pass
    return preferred[0]


def _clause_refers_to_previous_result(clause: str) -> bool:
    return bool(re.search(r"\b(?:it|that|created|newly created|result)\b", clause or "", re.IGNORECASE))


def build_planner_visible_tools(scoped_tools: list[ToolInfo]) -> list[dict[str, Any]]:
    wrappers: list[dict[str, Any]] = []
    for tool in scoped_tools:
        wrappers.append(
            {
                "name": tool.name,
                "description": tool.description,
                "method": tool.method,
                "endpoint": tool.endpoint,
                "input_schema": tool.input_schema,
                "requires_approval": tool.requires_approval,
            }
        )
    return wrappers


def _mark_contract_fields_stripped(
    *,
    intent_contract: dict[str, Any] | None,
    step_index: int,
    tool_name: str,
    dropped_fields: list[str],
) -> None:
    if not isinstance(intent_contract, dict) or not dropped_fields:
        return
    clauses = intent_contract.get("clauses") if isinstance(intent_contract.get("clauses"), list) else []
    if not clauses:
        clauses = intent_contract.get("steps") if isinstance(intent_contract.get("steps"), list) else []
    dropped = set(dropped_fields)
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        clause_step = int(clause.get("step_index", step_index))
        if clause_step != int(step_index) or clause.get("tool_name") != tool_name:
            continue
        resolved = clause.get("resolved_predicates")
        if isinstance(resolved, dict):
            clause["resolved_predicates"] = {
                field: value
                for field, value in resolved.items()
                if field not in dropped
            }
        existing_dropped = clause.get("provenance_dropped") if isinstance(clause.get("provenance_dropped"), list) else []
        clause["provenance_dropped"] = list(dict.fromkeys([*existing_dropped, *dropped_fields]))
        predicates = clause.get("predicates") if isinstance(clause.get("predicates"), list) else []
        updated_predicates: list[dict[str, Any]] = []
        for predicate in predicates:
            if not isinstance(predicate, dict):
                continue
            current = dict(predicate)
            field = str(current.get("field") or "")
            if field in dropped:
                current["requested"] = False
                current["resolved"] = False
                current["sent"] = False
                current["stripped"] = True
                current["reason"] = "stripped by provenance gate before execution"
            updated_predicates.append(current)
        if predicates:
            clause["predicates"] = updated_predicates


def _lookup_contract_clause(
    *,
    intent_contract: dict[str, Any] | None,
    step_index: int,
    tool_name: str,
) -> dict[str, Any] | None:
    if not isinstance(intent_contract, dict):
        return None
    clauses = intent_contract.get("clauses") if isinstance(intent_contract.get("clauses"), list) else []
    if not clauses:
        clauses = intent_contract.get("steps") if isinstance(intent_contract.get("steps"), list) else []
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        clause_step = int(clause.get("step_index", step_index))
        if clause_step == int(step_index) and clause.get("tool_name") == tool_name:
            return clause
    return None


def _clean_confirmation_term(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    stop = _CONFIRMATION_STOPWORDS | _AUXILIARY_CAPABILITY_TAGS
    tokens = [token for token in re.split(r"\s+", raw) if token]
    cleaned = [token for token in tokens if token.lower() not in stop]
    return " ".join(cleaned).strip() or raw


def _schema_aliases(field_schema: dict[str, Any]) -> list[str]:
    aliases = field_schema.get("x-ai-aliases")
    return [str(alias).strip().lower() for alias in aliases if str(alias).strip()] if isinstance(aliases, list) else []


def _field_confirmation_candidate(
    *,
    name: str,
    field_schema: dict[str, Any],
    selected_field: str,
    raw_term: str,
) -> dict[str, Any]:
    if name == selected_field:
        confidence = 0.7
        reason = "model selected this field, but the extracted value needed confirmation"
    elif any(alias and alias in raw_term.lower() for alias in _schema_aliases(field_schema)):
        confidence = 0.68
        reason = "term matches schema aliases for this field"
    elif isinstance(field_schema.get("enum"), list):
        confidence = 0.15
        reason = "plausible enum-backed filter field"
    else:
        confidence = 0.35
        reason = "plausible text filter field"
    return {
        "field": name,
        "value": raw_term,
        "label": f"{name}: {raw_term}",
        "confidence": confidence,
        "reason": reason,
    }


def _build_stripped_arg_confirmation(
    *,
    tool: ToolInfo,
    raw_args: dict[str, Any],
    dropped_fields: list[str],
    arg_provenance: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not dropped_fields:
        return None
    field = dropped_fields[0]
    provenance = arg_provenance.get(field) if isinstance(arg_provenance, dict) else None
    source = str((provenance or {}).get("source") or "").strip().lower()
    if source != "user":
        return None
    try:
        confidence = float((provenance or {}).get("confidence") if provenance else 0.0)
    except Exception:
        confidence = 0.0
    if confidence < _USER_CONFIRMATION_MIN_CONFIDENCE:
        return None
    raw_term = _clean_confirmation_term(raw_args.get(field))
    if not raw_term:
        return None

    schema = tool.input_schema or {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    query_names = set(tool.query_params or [])
    query_names.update(
        key for key, source in (tool.param_sources or {}).items() if source == "query"
    )
    candidates: list[dict[str, Any]] = []
    for name, field_schema in properties.items():
        if name in _SAFE_CONTROL_FIELDS:
            continue
        if query_names and name not in query_names:
            continue
        if not isinstance(field_schema, dict):
            continue
        field_type = field_schema.get("type")
        if isinstance(field_type, list):
            field_type = next((t for t in field_type if t != "null"), None)
        if field_type not in {"string", None}:
            continue
        candidates.append(
            _field_confirmation_candidate(
                name=name,
                field_schema=field_schema,
                selected_field=field,
                raw_term=raw_term,
            )
        )
    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    if not candidates:
        return None
    entity = _infer_primary_entity(tool) or "record"
    return {
        "kind": "predicate_field_confirmation",
        "entity": entity,
        "raw_term": raw_term,
        "normalized_term": re.sub(r"[^a-z0-9]+", "", raw_term.lower()),
        "message": f'I found "{raw_term}" in your {entity} request. Which field should it filter?',
        "options": candidates[:3],
        "all_options": candidates,
        "has_more": len(candidates) > 3,
    }


class LegacyPlannerBackend:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._reasoning = ReasoningPipeline(settings)

    def _explainability_backend(self) -> str:
        backend = (self._settings.summary_backend or "legacy").strip().lower()
        if backend == "auto":
            if self._settings.openai_base_url or self._settings.openai_api_key:
                return "langchain"
            return "legacy"
        return backend

    def _build_chat_model(self):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.summary_model,
            "temperature": 0,
            "timeout": self._settings.llm_json_timeout_s,
            "max_retries": 0,
            "max_tokens": self._settings.llm_json_max_tokens,
            "model_kwargs": {"response_format": {"type": "json_object"}},
        }
        if self._settings.openai_base_url:
            kwargs["base_url"] = self._settings.openai_base_url
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    async def _build_explainability(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        steps: list[PlanStepDraft],
    ) -> tuple[str, str, int]:
        tools_by_name = {tool.name: tool for tool in scoped_tools}
        write_steps = [
            step for step in steps if (tool := tools_by_name.get(step.tool_name)) and not tool.is_read_only
        ]
        fallback_explanation = f"Plan prepared for intent: {intent.strip() or 'user request'}."
        fallback_risk = (
            "This plan includes write operations and requires approval before execution."
            if write_steps
            else "This plan is read-only and only retrieves information."
        )

        backend = self._explainability_backend()
        if backend != "langchain":
            log_llm_prompt_skipped(
                component="planner_explainability",
                backend=backend,
                reason="summary_backend!=langchain",
                metadata={"step_count": len(steps)},
            )
            return fallback_explanation, fallback_risk, 0

        try:
            from langchain_openai import ChatOpenAI  # noqa: F401
        except Exception:
            log_llm_prompt_skipped(
                component="planner_explainability",
                backend=backend,
                reason="langchain_openai_unavailable",
                metadata={"step_count": len(steps)},
            )
            return fallback_explanation, fallback_risk, 0

        plan_payload = [
            {
                "step_index": step.step_index,
                "tool_name": step.tool_name,
                "args": step.args,
            }
            for step in steps
        ]
        tool_payload = [
            {
                "name": tool.name,
                "method": tool.method,
                "is_read_only": tool.is_read_only,
                "requires_approval": tool.requires_approval,
            }
            for tool in scoped_tools
        ]
        prompt = (
            "Generate plan explainability as strict JSON with keys `plan_explanation` and `risk_summary`.\n"
            "Rules:\n"
            "- Ground only on provided intent/tools/steps.\n"
            "- Keep each field concise and operator-friendly.\n"
            "- Mention approval risk if any step writes.\n"
            "- Return JSON only.\n\n"
            f"Intent: {intent}\n"
            f"Steps: {json.dumps(plan_payload, ensure_ascii=False)}\n"
            f"Tools: {json.dumps(tool_payload, ensure_ascii=False)}\n"
        )
        log_llm_prompt(
            component="planner_explainability",
            backend=backend,
            model=self._settings.summary_model,
            prompt=prompt,
            metadata={"step_count": len(steps)},
        )
        try:
            model = self._build_chat_model()
            resp = await model.ainvoke(prompt)
            content = (getattr(resp, "content", "") or "").strip()
            parsed = self._reasoning._extract_json_obj(content) if content else {}
            if isinstance(parsed, dict):
                plan_explanation = str(parsed.get("plan_explanation") or "").strip()
                risk_summary = str(parsed.get("risk_summary") or "").strip()
                if plan_explanation and risk_summary:
                    return plan_explanation, risk_summary, 1
        except Exception:
            pass

        return fallback_explanation, fallback_risk, 0

    def _predicate_match_mode(self, field: str) -> str:
        normalized = (field or "").strip().lower()
        if normalized.endswith("_name") or normalized in {"name", "q", "search"}:
            return "contains"
        return "exact"

    def _should_skip_llm_clause_tool_choice(
        self,
        *,
        clause: str,
        ranked_candidates: list[ToolInfo],
        missing_by_tool: dict[str, list[str]],
    ) -> tuple[bool, str]:
        if not ranked_candidates:
            return True, "no_candidates"

        top = ranked_candidates[0]
        top_missing = missing_by_tool.get(top.name, [])
        if len(ranked_candidates) == 1:
            return False, "single_candidate_keep_clause_llm"

        second = ranked_candidates[1]
        second_missing = missing_by_tool.get(second.name, [])
        top_score = _tool_intent_match_score(clause, top)
        second_score = _tool_intent_match_score(clause, second)
        gap = top_score - second_score

        # Skip clause-level LLM rerank when one read candidate is clearly better
        # and has all required args already inferred.
        if not top_missing and top.is_read_only:
            if second_missing and gap >= 1:
                return True, "top_candidate_has_required_args_second_missing"
            if not second_missing and gap >= 4:
                return True, "clear_score_gap"

        return False, "needs_clause_level_llm_selection"

    def _extract_result_items(self, body: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(body, dict):
            return []
        for key in ("data", "items"):
            value = body.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
        return []

    async def _lookup_predicate_evidence(
        self,
        *,
        tool: ToolInfo,
        term: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if tool.method != "GET" or not tool.is_read_only:
            return {}
        if "{" in (tool.endpoint or ""):
            return {}
        query_names = set(tool.query_params or [])
        query_names.update(
            key for key, source in (tool.param_sources or {}).items() if source == "query"
        )
        if not query_names:
            return {}

        url = f"{self._settings.go_api_base_url}{tool.endpoint}"
        evidence: dict[str, dict[str, Any]] = {}
        timeout = httpx.Timeout(
            min(float(self._settings.http_timeout_s or 1.0), 0.75),
            connect=min(float(self._settings.http_timeout_s or 1.0), 0.25),
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            async def probe(candidate: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
                field = str(candidate.get("field") or "")
                if not field or field not in query_names:
                    return "", None
                params: dict[str, Any] = {field: term}
                if "limit" in query_names:
                    params["limit"] = 25
                try:
                    resp = await client.get(url, params=params)
                except Exception as exc:
                    log_event(
                        "predicate_evidence_lookup_failed",
                        level="WARNING",
                        tool_name=tool.name,
                        field=field,
                        error=str(exc),
                    )
                    return "", None
                if resp.status_code >= 400:
                    return field, {
                        "match_count": 0,
                        "match_mode": self._predicate_match_mode(field),
                        "sample_values": [],
                    }
                try:
                    body = resp.json() if resp.content else {}
                except Exception:
                    body = {}
                items = self._extract_result_items(body if isinstance(body, dict) else {})
                samples: list[str] = []
                for item in items:
                    value = item.get(field)
                    if value not in (None, "") and str(value) not in samples:
                        samples.append(str(value))
                return field, {
                    "match_count": len(items),
                    "match_mode": self._predicate_match_mode(field),
                    "sample_values": samples[:3],
                }

            results = await asyncio.gather(*(probe(candidate) for candidate in candidates))
            for field, field_evidence in results:
                if field and field_evidence:
                    evidence[field] = field_evidence
        if evidence:
            log_event(
                "predicate_evidence_lookup_completed",
                tool_name=tool.name,
                term=term,
                evidence=evidence,
            )
        return evidence

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        tools_markdown: str = "",
    ) -> PlannerResult:
        del tools_markdown
        context = context or {}
        intent_memory = context.get("intent_memory") if isinstance(context.get("intent_memory"), dict) else {}
        log_llm_prompt_skipped(
            component="planner",
            backend="legacy",
            reason="planner_backend=legacy",
            metadata={"intent": intent, "scoped_tool_count": len(scoped_tools)},
        )
        if not scoped_tools:
            raise PlannerBackendError("No scoped tools available to generate a plan.")

        assessment = assess_intent(intent)
        if assessment.kind != "operations":
            raise PlannerClarificationError(
                assessment.reply
                or "I need an operation request before I can generate a tool plan."
            )

        clauses = _split_compound_intent(intent)
        step_drafts: list[PlanStepDraft] = []
        contract_clauses: list[dict[str, Any]] = []
        tools_by_name = {tool.name: tool for tool in scoped_tools}
        vocabulary = vocabulary_for_tools(scoped_tools)
        def append_step(
            *,
            clause_text: str,
            tool: ToolInfo,
            step_args: dict[str, Any],
            bindings: list[PlanBinding] | None = None,
            predicates: list[dict[str, Any]] | None = None,
            resolved_predicates: dict[str, Any] | None = None,
            provenance: dict[str, dict[str, Any]] | None = None,
        ) -> None:
            step_index = len(step_drafts)
            step_drafts.append(
                PlanStepDraft(
                    step_index=step_index,
                    tool_name=tool.name,
                    args=step_args,
                    depends_on=[step_index - 1] if step_index > 0 else [],
                    bindings=bindings or [],
                )
            )
            contract_clauses.append(
                {
                    "step_index": step_index,
                    "clause": clause_text,
                    "tool_name": tool.name,
                    "args": step_args,
                    "arg_provenance": provenance or {},
                    "resolved_predicates": resolved_predicates or {},
                    "unresolved_terms": [],
                    "predicates": predicates or [],
                    "predicate_coverage_score": 1.0,
                    "provenance_dropped": [],
                }
            )

        diagnostic_override = _diagnostic_plan_override(intent, scoped_tools)
        if diagnostic_override is not None:
            tool, override_args = diagnostic_override
            append_step(clause_text=intent, tool=tool, step_args=override_args)
            parallel_groups = _assign_parallel_groups(
                step_drafts,
                tools_by_name,
                enabled=self._settings.enable_parallel_execution,
            )
            plan_explanation, risk_summary, llm_calls = await self._build_explainability(
                intent=intent,
                scoped_tools=scoped_tools,
                steps=step_drafts,
            )
            return PlannerResult(
                draft=PlanDraft(
                    plan_explanation=plan_explanation,
                    risk_summary=risk_summary,
                    steps=step_drafts,
                    parallel_groups=parallel_groups or None,
                ),
                backend_used="legacy",
                llm_calls=llm_calls,
                intent_contract={"intent": intent, "clauses": contract_clauses},
            )

        for clause in clauses:
            previous_step = step_drafts[-1] if step_drafts else None
            previous_tool = tools_by_name.get(previous_step.tool_name) if previous_step else None
            if previous_tool and not previous_tool.is_read_only and _clause_refers_to_previous_result(clause):
                lookup_tool = _lookup_tool_for_created_resource(previous_tool, scoped_tools)
                if lookup_tool:
                    binding = PlanBinding(
                        from_step=previous_step.step_index,
                        result_path="data",
                        field=_binding_field_for_lookup(previous_tool, lookup_tool),
                        target_arg="id",
                        mode="single",
                    )
                    append_step(
                        clause_text=clause,
                        tool=lookup_tool,
                        step_args={},
                        bindings=[binding],
                    )
                    continue

            selected = _select_legacy_tool(clause, scoped_tools, vocabulary=vocabulary)
            args, missing = _extract_required_args(clause, selected)
            arg_provenance: dict[str, dict[str, Any]] = {}
            for field, value in args.items():
                _mark_user_provenance(provenance=arg_provenance, field=field, value=value)

            # LLM-first tool selection with deterministic guardrails.
            ranked_candidates = sorted(
                scoped_tools,
                key=lambda t: (
                    _tool_missing_required_path_args(t, _extract_required_args(clause, t)[0]),
                    not tool_covers_descriptive_terms(clause, t, vocabulary=vocabulary),
                    not _tool_matches_entity(t, assessment.entity or next(iter(_extract_intent_entities(clause)["ids_by_keyword"]), None)),
                    -_tool_intent_match_score(clause, t, vocabulary=vocabulary),
                    _tool_missing_required_args(t, _extract_required_args(clause, t)[0]),
                    t.name,
                ),
            )[:8]
            prefilled_by_tool: dict[str, dict[str, Any]] = {}
            missing_by_tool: dict[str, list[str]] = {}
            for candidate in ranked_candidates:
                cand_args, cand_missing = _extract_required_args(clause, candidate)
                prefilled_by_tool[candidate.name] = cand_args
                missing_by_tool[candidate.name] = cand_missing
            llm_candidates = self._reasoning.build_selection_candidates(
                tools=ranked_candidates,
                prefilled_by_tool=prefilled_by_tool,
                missing_by_tool=missing_by_tool,
            )
            decision = None
            skip_llm_choice, skip_reason = self._should_skip_llm_clause_tool_choice(
                clause=clause,
                ranked_candidates=ranked_candidates,
                missing_by_tool=missing_by_tool,
            )
            if skip_llm_choice:
                log_llm_prompt_skipped(
                    component="reasoning_tool_selection",
                    backend="planner_gate",
                    reason=skip_reason,
                    metadata={"intent": intent, "clause": clause, "candidate_count": len(ranked_candidates)},
                )
            else:
                try:
                    decision = await self._reasoning.select_tool(
                        intent=intent,
                        clause=clause,
                        candidates=llm_candidates,
                    )
                except Exception:
                    decision = None
            if decision and decision.tool_name in tools_by_name:
                candidate = tools_by_name[decision.tool_name]
                decision_args, decision_provenance = _unwrap_arg_provenance(decision.args or {})
                sanitized_args, dropped_fields = _sanitize_tool_args_against_schema(candidate, decision_args)
                if dropped_fields:
                    log_event(
                        "planner_llm_args_sanitized",
                        level="WARNING",
                        tool_name=candidate.name,
                        dropped_fields=dropped_fields,
                        raw_args=decision.args or {},
                        intent=intent,
                        clause=clause,
                    )
                    clarification = _build_unsupported_enum_clarification(
                        tool=candidate,
                        raw_args=decision_args,
                        sanitized_args=sanitized_args,
                        dropped_fields=dropped_fields,
                        intent=intent,
                        clause=clause,
                        arg_provenance=decision_provenance,
                    )
                    if clarification:
                        raise PlannerClarificationError(clarification)
                candidate_required_missing = _tool_missing_required_args(candidate, sanitized_args)
                candidate_score = _tool_intent_match_score(clause, candidate, vocabulary=vocabulary)
                selected_score = _tool_intent_match_score(clause, selected, vocabulary=vocabulary)
                approval_candidate_is_not_worse = candidate.requires_approval and candidate_score >= selected_score
                preserve_exact_lookup = (
                    assessment.action == "read"
                    and selected.method == "GET"
                    and selected.is_read_only
                    and _tool_prefers_entity_lookup(selected)
                    and _tool_missing_required_args(selected, args) == 0
                    and candidate.method == "GET"
                    and candidate.is_read_only
                    and not _tool_prefers_entity_lookup(candidate)
                )
                preserve_feature_endpoint = (
                    assessment.action == "read"
                    and selected.method == "GET"
                    and selected.is_read_only
                    and candidate.method == "GET"
                    and candidate.is_read_only
                    and tool_covers_descriptive_terms(clause, selected, vocabulary=vocabulary)
                    and not tool_covers_descriptive_terms(clause, candidate, vocabulary=vocabulary)
                )
                selected_endpoint_features = _endpoint_feature_matches(clause, selected, vocabulary=vocabulary)
                candidate_endpoint_features = _endpoint_feature_matches(clause, candidate, vocabulary=vocabulary)
                preserve_endpoint_feature_coverage = (
                    assessment.action == "read"
                    and selected.method == "GET"
                    and selected.is_read_only
                    and candidate.method == "GET"
                    and candidate.is_read_only
                    and bool(selected_endpoint_features)
                    and not selected_endpoint_features <= candidate_endpoint_features
                    and len(selected_endpoint_features) > len(candidate_endpoint_features)
                )
                selected_tags = {str(tag).lower() for tag in (selected.capability_tags or [])}
                candidate_tags = {str(tag).lower() for tag in (candidate.capability_tags or [])}
                preserve_user_named_slot = (
                    assessment.action == "read"
                    and re.search(r"\bslots?\b", clause or "", flags=re.IGNORECASE)
                    and "slot" in selected_tags
                    and "slot" not in candidate_tags
                )
                preserve_action_method = (
                    (assessment.action == "update" and candidate.method not in {"PUT", "PATCH"})
                    or (assessment.action == "create" and candidate.method != "POST")
                    or (assessment.action == "delete" and candidate.method != "DELETE")
                    or (assessment.action == "read" and candidate.method != "GET")
                )
                if preserve_exact_lookup:
                    log_event(
                        "planner_llm_tool_choice_ignored",
                        level="INFO",
                        reason="preserve_exact_lookup",
                        selected_tool=selected.name,
                        ignored_tool=candidate.name,
                        intent=intent,
                        clause=clause,
                    )
                elif preserve_endpoint_feature_coverage:
                    log_event(
                        "planner_llm_tool_choice_ignored",
                        level="INFO",
                        reason="preserve_endpoint_feature_coverage",
                        selected_tool=selected.name,
                        ignored_tool=candidate.name,
                        selected_endpoint_features=sorted(selected_endpoint_features),
                        candidate_endpoint_features=sorted(candidate_endpoint_features),
                        intent=intent,
                        clause=clause,
                    )
                elif preserve_user_named_slot:
                    log_event(
                        "planner_llm_tool_choice_ignored",
                        level="INFO",
                        reason="preserve_user_named_slot",
                        selected_tool=selected.name,
                        ignored_tool=candidate.name,
                        intent=intent,
                        clause=clause,
                    )
                elif preserve_feature_endpoint:
                    log_event(
                        "planner_llm_tool_choice_ignored",
                        level="INFO",
                        reason="preserve_feature_endpoint",
                        selected_tool=selected.name,
                        ignored_tool=candidate.name,
                        intent=intent,
                        clause=clause,
                    )
                elif preserve_action_method:
                    log_event(
                        "planner_llm_tool_choice_ignored",
                        level="INFO",
                        reason="preserve_action_method",
                        selected_tool=selected.name,
                        ignored_tool=candidate.name,
                        action=assessment.action,
                        intent=intent,
                        clause=clause,
                    )
                elif candidate_required_missing == 0 or approval_candidate_is_not_worse:
                    selected = candidate
                    args = sanitized_args
                    arg_provenance = {
                        field: (decision_provenance.get(field) or {"value": value, "source": "llm"})
                        for field, value in args.items()
                    }
                    arg_provenance = _promote_user_provenance(
                        tool=selected,
                        args=args,
                        intent=intent,
                        clause=clause,
                        arg_provenance=arg_provenance,
                    )
                    missing = _tool_missing_required_fields(candidate, sanitized_args)

            requested_subresource = _preferred_parent_subresource_tool(clause, scoped_tools, vocabulary=vocabulary)
            if requested_subresource:
                if selected.name != requested_subresource.name:
                    selected = requested_subresource
                    args, missing = _extract_required_args(clause, selected)
                    arg_provenance = {}
                    for field, value in args.items():
                        _mark_user_provenance(provenance=arg_provenance, field=field, value=value)
            elif re.search(r"\bslots?\b", clause or "", flags=re.IGNORECASE):
                slot_choices = [
                    tool for tool in scoped_tools
                    if tool.method == "GET"
                    and "slot" in {str(tag).lower() for tag in (tool.capability_tags or [])}
                ]
                if slot_choices:
                    slot_choice = sorted(
                        slot_choices,
                        key=lambda tool: (
                            _tool_missing_required_path_args(tool, _extract_required_args(clause, tool)[0]),
                            -_tool_intent_match_score(clause, tool, vocabulary=vocabulary),
                            tool.name,
                        ),
                    )[0]
                else:
                    slot_choice = None
                if slot_choice and selected.name != slot_choice.name:
                    selected = slot_choice
                    args, missing = _extract_required_args(clause, selected)
                    arg_provenance = {}
                    for field, value in args.items():
                        _mark_user_provenance(provenance=arg_provenance, field=field, value=value)

            preverification_raw_args = dict(args)
            args, preverification_dropped = _strip_unsupported_optional_args(
                tool=selected,
                args=args,
                intent=intent,
                clause=clause,
                intent_memory=intent_memory,
                arg_provenance=arg_provenance,
            )
            preverification_dropped_set = set(preverification_dropped)
            if preverification_dropped:
                log_event(
                    "planner_llm_optional_arg_preverification_stripped",
                    level="INFO",
                    tool_name=selected.name,
                    dropped_fields=preverification_dropped,
                    intent=intent,
                    clause=clause,
                )
                confirmation = _build_stripped_arg_confirmation(
                    tool=selected,
                    raw_args=preverification_raw_args,
                    dropped_fields=preverification_dropped,
                    arg_provenance=arg_provenance,
                )
                if confirmation:
                    raise PlannerConfirmationRequired(
                        confirmation.get("message") or "Please confirm the intended filter.",
                        confirmation=confirmation,
                    )

            # Preserve deterministic optional predicate extraction such as enum-backed
            # query filters even when the LLM reranker returns sparse args.
            args = _merge_deterministic_supported_args(
                clause,
                selected,
                args,
                provenance=arg_provenance,
                exclude_fields=preverification_dropped_set,
            )
            arg_provenance = _promote_user_provenance(
                tool=selected,
                args=args,
                intent=intent,
                clause=clause,
                arg_provenance=arg_provenance,
            )

            if missing:
                # If the clause lost an identifier during splitting, retry with
                # the full intent before asking the user for clarification.
                fallback_args, fallback_missing = _extract_required_args(intent, selected)
                if not fallback_missing:
                    args = fallback_args
                    missing = []

            args = _merge_deterministic_supported_args(
                intent,
                selected,
                args,
                provenance=arg_provenance,
                exclude_fields=preverification_dropped_set,
            )
            arg_provenance = _promote_user_provenance(
                tool=selected,
                args=args,
                intent=intent,
                clause=clause,
                arg_provenance=arg_provenance,
            )

            verification = await verify_clause_against_tool(
                clause=clause,
                tool=selected,
                args=args,
                reasoning=self._reasoning,
                memory=intent_memory,
                evidence_provider=self._lookup_predicate_evidence,
            )
            args = verification.args
            arg_provenance = _promote_user_provenance(
                tool=selected,
                args=args,
                intent=intent,
                clause=clause,
                arg_provenance=arg_provenance,
                resolved_predicates=verification.resolved_predicates,
            )
            if verification.confirmation:
                log_event(
                    "predicate_confirmation_required",
                    intent=intent,
                    clause=clause,
                    tool_name=selected.name,
                    confirmation=verification.confirmation,
                    predicates=verification.predicates,
                )
                raise PlannerConfirmationRequired(
                    verification.confirmation.get("message") or "Please confirm the intended filter.",
                    confirmation=verification.confirmation,
                )
            if verification.clarification:
                log_event(
                    "predicate_clarification_required",
                    intent=intent,
                    clause=clause,
                    tool_name=selected.name,
                    clarification=verification.clarification,
                    predicates=verification.predicates,
                )
                raise PlannerClarificationError(
                    verification.clarification,
                    predicates=verification.predicates,
                    negative_bindings=verification.negative_bindings,
                )

            if missing:
                # For approval-gated tools (typically write operations), allow
                # partial args so the UI can present a schema-driven form for the
                # user to fill/confirm at approval time.
                if not selected.requires_approval:
                    pretty = ", ".join(missing)
                    raise PlannerClarificationError(
                        f"Need {pretty} before I can use `{selected.name}` for: {clause.strip() or intent.strip() or 'user request'}."
                    )

            # ------------------------------------------------------------------
            # Provenance gate: strip optional filter args that lack support
            # from the user text, session memory, or a safe default.
            # This prevents placeholder values like "default" from reaching
            # the backend and causing HTTP 500s.
            # ------------------------------------------------------------------
            args, provenance_dropped = _strip_unsupported_optional_args(
                tool=selected,
                args=args,
                intent=intent,
                clause=clause,
                intent_memory=intent_memory,
                resolved_predicates=verification.resolved_predicates,
                arg_provenance=arg_provenance,
            )
            if provenance_dropped:
                log_event(
                    "planner_provenance_gate",
                    level="INFO",
                    tool_name=selected.name,
                    dropped_fields=provenance_dropped,
                    intent=intent,
                    clause=clause,
                    planner_backend="legacy",
                )

            contract_predicates: list[dict[str, Any]] = []
            for predicate in verification.predicates:
                if not isinstance(predicate, dict):
                    continue
                contract_predicate = dict(predicate)
                field = str(contract_predicate.get("field") or "")
                if field in provenance_dropped:
                    contract_predicate["requested"] = False
                    contract_predicate["resolved"] = False
                    contract_predicate["sent"] = False
                    contract_predicate["stripped"] = True
                    contract_predicate["reason"] = "stripped by provenance gate before execution"
                contract_predicates.append(contract_predicate)
            contract_resolved_predicates = {
                field: value
                for field, value in verification.resolved_predicates.items()
                if field not in set(provenance_dropped)
            }

            if selected.method == "DELETE":
                preflight = _find_get_tool_for_endpoint(selected.endpoint, scoped_tools)
                if preflight and not any(
                    step.tool_name == preflight.name and step.args == args
                    for step in step_drafts
                ):
                    append_step(
                        clause_text=clause,
                        tool=preflight,
                        step_args=dict(args),
                        provenance=arg_provenance,
                        resolved_predicates=contract_resolved_predicates,
                        predicates=contract_predicates,
                    )

            parent_lookup = _parent_lookup_tool(selected, scoped_tools)
            if parent_lookup and _child_requested_by_clause(clause, selected) and not any(
                step.tool_name == parent_lookup.name and step.args == args
                for step in step_drafts
            ):
                parent_args, _ = _extract_required_args(clause, parent_lookup)
                if not parent_args:
                    parent_args = dict(args)
                append_step(
                    clause_text=clause,
                    tool=parent_lookup,
                    step_args=parent_args,
                    provenance=arg_provenance,
                    resolved_predicates=contract_resolved_predicates,
                    predicates=contract_predicates,
                )

            append_step(
                clause_text=clause,
                tool=selected,
                step_args=args,
                provenance=arg_provenance,
                resolved_predicates=contract_resolved_predicates,
                predicates=contract_predicates,
            )

            for child in _requested_child_tools(clause, selected, scoped_tools):
                if any(step.tool_name == child.name and step.args == args for step in step_drafts):
                    continue
                child_args, _ = _extract_required_args(clause, child)
                if not child_args:
                    child_args = dict(args)
                append_step(
                    clause_text=clause,
                    tool=child,
                    step_args=child_args,
                    provenance=arg_provenance,
                    resolved_predicates=contract_resolved_predicates,
                    predicates=contract_predicates,
                )

        plan_explanation, risk_summary, llm_calls = await self._build_explainability(
            intent=intent,
            scoped_tools=scoped_tools,
            steps=step_drafts,
        )
        parallel_groups = _assign_parallel_groups(
            step_drafts,
            tools_by_name,
            enabled=self._settings.enable_parallel_execution,
        )
        draft = PlanDraft(
            plan_explanation=plan_explanation,
            risk_summary=risk_summary,
            steps=step_drafts,
            parallel_groups=parallel_groups or None,
        )
        return PlannerResult(
            draft=draft,
            backend_used="legacy",
            llm_calls=llm_calls,
            intent_contract={"intent": intent, "clauses": contract_clauses},
        )


class LangChainPlannerBackend:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._legacy = LegacyPlannerBackend(settings)

    def _build_chat_model(self):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.planner_model,
            "temperature": 0,
            "timeout": self._settings.llm_json_timeout_s,
            "max_retries": 0,
            "max_tokens": self._settings.llm_json_max_tokens,
        }
        if self._settings.openai_base_url:
            kwargs["base_url"] = self._settings.openai_base_url
            # llama.cpp OpenAI-compatible servers usually ignore api_key but client may require one.
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    def _extract_json_obj(self, text: str) -> dict[str, Any] | None:
        candidate = text.strip()
        if not candidate:
            return None
        if candidate.startswith("```"):
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start : end + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _is_candidate_valid(self, draft: PlanDraft, scoped_tools: list[ToolInfo]) -> bool:
        tool_map = {t.name: t for t in scoped_tools}
        result = validate_plan(draft, tool_map, max_steps=self._settings.max_plan_steps)
        return result.ok

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        tools_markdown: str = "",
    ) -> PlannerResult:
        try:
            from langchain_openai import ChatOpenAI
        except Exception as e:
            raise PlannerBackendError(
                "LangChain planner backend unavailable; install langchain-openai and configure API credentials."
            ) from e

        scoped_names = [t.name for t in scoped_tools]
        prompt = build_planner_prompt(
            user_goal=intent,
            tools_markdown=tools_markdown,
            scoped_tool_names=scoped_names,
        )
        wrappers = build_planner_visible_tools(scoped_tools)
        context_payload = context or {}
        combined_prompt = (
            f"{prompt}\n\n"
            f"Planner-visible tool wrappers (for planning only; do not execute):\n{wrappers}\n\n"
            f"Planner context:\n{context_payload}\n"
        )

        llm_calls = 0
        model = self._build_chat_model()

        # Attempt 1: provider-native structured output.
        try:
            log_llm_prompt(
                component="planner",
                backend="langchain",
                model=self._settings.planner_model,
                prompt=combined_prompt,
                metadata={
                    "attempt": "structured_output",
                    "intent": intent,
                    "scoped_tool_count": len(scoped_tools),
                    "scoped_tools": scoped_names,
                },
            )
            structured = model.with_structured_output(PlanDraft)
            raw = await structured.ainvoke(combined_prompt)
            llm_calls += 1
            draft = raw if isinstance(raw, PlanDraft) else PlanDraft.model_validate(raw)
            if self._is_candidate_valid(draft, scoped_tools):
                return PlannerResult(draft=draft, backend_used="langchain", llm_calls=llm_calls)
        except Exception:
            pass

        # Attempt 2: ask for plain JSON text and parse manually.
        repair_prompt = (
            f"{combined_prompt}\n\n"
            "Return only a JSON object matching PlanDraft. "
            "No markdown, no explanation, no surrounding text."
        )
        try:
            log_llm_prompt(
                component="planner",
                backend="langchain",
                model=self._settings.planner_model,
                prompt=repair_prompt,
                metadata={
                    "attempt": "json_repair",
                    "intent": intent,
                    "scoped_tool_count": len(scoped_tools),
                    "scoped_tools": scoped_names,
                },
            )
            raw_resp = await model.ainvoke(repair_prompt)
            llm_calls += 1
            content = (getattr(raw_resp, "content", "") or "").strip()
            parsed = self._extract_json_obj(content)
            if parsed is not None:
                draft = PlanDraft.model_validate(parsed)
                if self._is_candidate_valid(draft, scoped_tools):
                    return PlannerResult(draft=draft, backend_used="langchain", llm_calls=llm_calls)
        except Exception:
            pass

        # Last resort: deterministic safe draft so runtime can continue through existing validator and safety gates.
        fallback = await self._legacy.generate_plan(
            intent=intent,
            scoped_tools=scoped_tools,
            context=context,
            tools_markdown=tools_markdown,
        )
        return PlannerResult(draft=fallback.draft, backend_used="legacy", llm_calls=max(1, llm_calls))


class StructuredPlannerBackend:
    """LLM-first planner with deterministic schema and provenance guardrails.

    This backend is the Phase 3 path: the model extracts a structured plan from
    candidate OpenAPI tool schemas, while Python remains responsible for safety.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    def _build_chat_model(self):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.planner_model,
            "temperature": 0,
            "timeout": self._settings.llm_json_timeout_s,
            "max_retries": 0,
            "max_tokens": max(self._settings.llm_json_max_tokens, 900),
            "model_kwargs": {"response_format": {"type": "json_object"}},
        }
        if self._settings.openai_base_url:
            kwargs["base_url"] = self._settings.openai_base_url
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    def _extract_json_obj(self, text: str) -> dict[str, Any] | None:
        candidate = (text or "").strip()
        if not candidate:
            return None
        if candidate.startswith("```"):
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start : end + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _tool_cards(self, scoped_tools: list[ToolInfo]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for tool in scoped_tools:
            cards.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "method": tool.method,
                    "endpoint": tool.endpoint,
                    "input_schema": tool.input_schema,
                    "path_params": tool.path_params,
                    "query_params": tool.query_params,
                    "body_fields": tool.body_fields,
                    "required_fields": list((tool.input_schema or {}).get("required", [])),
                    "output_schema": tool.output_schema,
                    "capability_tags": tool.capability_tags,
                    "allowed_roles": tool.allowed_roles,
                    "read_only": tool.is_read_only,
                    "requires_approval": tool.requires_approval,
                }
            )
        return cards

    def _build_prompt(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None,
    ) -> str:
        return (
            "You are an operations planner. Extract the user's request into a safe tool plan.\n"
            "Return STRICT JSON only with this shape:\n"
            "{"
            '"plan_explanation":"string",'
            '"risk_summary":"string",'
            '"steps":[{"step_index":0,"tool_name":"string","args":{},"depends_on":[],"execution_mode":"single","bindings":[],"evidence":{},"confidence":0.0,"missing_required":[]}],'
            '"clarification":null'
            "}\n"
            "Rules:\n"
            "- Choose tool_name only from the provided tools.\n"
            "- Args must exactly match the selected tool input_schema properties.\n"
            "- Do not invent placeholder values such as default, any, unknown, sample, or test.\n"
            "- For every arg, include evidence[field] as the exact user text span or context source that supports it.\n"
            "- If a required value is missing, list it in missing_required instead of inventing it.\n"
            "- For values from previous tool results, use bindings, not invented args.\n"
            "- Binding shape: {\"from_step\":0,\"result_path\":\"data\",\"field\":\"job_id\",\"target_arg\":\"job_id\",\"mode\":\"single\"}.\n"
            "- Use execution_mode=\"foreach\" only for bounded bulk write/action steps fed by a previous read step.\n"
            "- If the request is ambiguous, set clarification to a short operator question and keep steps empty.\n"
            "- Preserve execution order; use depends_on for sequential compound requests.\n\n"
            f"User request: {intent}\n"
            f"Session context: {json.dumps(context or {}, ensure_ascii=False)}\n"
            f"Candidate tools: {json.dumps(self._tool_cards(scoped_tools), ensure_ascii=False)}\n"
        )

    async def _invoke_json(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            from langchain_openai import ChatOpenAI  # noqa: F401
        except Exception as exc:
            raise PlannerBackendError(
                "Structured planner unavailable; install langchain-openai and configure API credentials."
            ) from exc
        if not (self._settings.openai_base_url or self._settings.openai_api_key):
            raise PlannerBackendError("Structured planner requires OPENAI_BASE_URL or OPENAI_API_KEY.")

        prompt = self._build_prompt(intent=intent, scoped_tools=scoped_tools, context=context)
        log_llm_prompt(
            component="planner",
            backend="structured",
            model=self._settings.planner_model,
            prompt=prompt,
            metadata={"intent": intent, "scoped_tool_count": len(scoped_tools)},
        )
        model = self._build_chat_model()
        try:
            raw_resp = await model.ainvoke(prompt)
        except Exception as exc:
            raise PlannerBackendError(str(exc)) from exc
        parsed = self._extract_json_obj((getattr(raw_resp, "content", "") or "").strip())
        if not isinstance(parsed, dict):
            raise PlannerBackendError("Structured planner returned invalid JSON.")
        return parsed

    def _supported_predicates(
        self,
        *,
        intent: str,
        args: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        supported: dict[str, Any] = {}
        for field, value in args.items():
            if _is_placeholder(value):
                continue
            evidence_text = str(evidence.get(field) or "")
            if _value_found_in_text(value, intent, evidence_text):
                supported[field] = value
        return supported

    def _draft_from_payload(
        self,
        *,
        payload: dict[str, Any],
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None,
    ) -> tuple[PlanDraft, dict[str, Any]]:
        clarification = payload.get("clarification")
        if isinstance(clarification, str) and clarification.strip():
            raise PlannerClarificationError(clarification.strip())

        tools_by_name = {tool.name: tool for tool in scoped_tools}
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise PlannerClarificationError("I could not map that request to a safe factory tool plan.")

        intent_memory = context.get("intent_memory") if isinstance(context, dict) and isinstance(context.get("intent_memory"), dict) else {}
        step_drafts: list[PlanStepDraft] = []
        contract_steps: list[dict[str, Any]] = []

        for idx, raw_step in enumerate(raw_steps[: self._settings.max_plan_steps]):
            if not isinstance(raw_step, dict):
                continue
            tool_name = str(raw_step.get("tool_name") or "").strip()
            tool = tools_by_name.get(tool_name)
            if not tool:
                raise PlannerClarificationError(f"I could not safely select a supported tool for step {idx + 1}.")

            raw_args = raw_step.get("args") if isinstance(raw_step.get("args"), dict) else {}
            sanitized_args, dropped_fields = _sanitize_tool_args_against_schema(tool, raw_args)
            if dropped_fields:
                clarification_text = _build_unsupported_enum_clarification(
                    tool=tool,
                    raw_args=raw_args,
                    sanitized_args=sanitized_args,
                    dropped_fields=dropped_fields,
                    intent=intent,
                    clause=intent,
                )
                if clarification_text:
                    raise PlannerClarificationError(clarification_text)
                log_event(
                    "structured_planner_args_sanitized",
                    level="WARNING",
                    tool_name=tool.name,
                    dropped_fields=dropped_fields,
                    raw_args=raw_args,
                    intent=intent,
                )

            missing = _tool_missing_required_fields(tool, sanitized_args)
            model_missing = raw_step.get("missing_required") if isinstance(raw_step.get("missing_required"), list) else []
            missing = sorted(set(missing) | {str(x) for x in model_missing if str(x)})
            if missing and not tool.requires_approval:
                raise PlannerClarificationError(
                    f"Need {', '.join(missing)} before I can use `{tool.name}` for this request."
                )

            evidence = raw_step.get("evidence") if isinstance(raw_step.get("evidence"), dict) else {}
            arg_provenance: dict[str, dict[str, Any]] = {}
            for field, value in sanitized_args.items():
                evidence_text = str(evidence.get(field) or "")
                if _value_found_in_text(value, intent, evidence_text):
                    _mark_user_provenance(provenance=arg_provenance, field=field, value=value)
                else:
                    arg_provenance[field] = {"value": value, "source": "llm"}
            supported_predicates = self._supported_predicates(
                intent=intent,
                args=sanitized_args,
                evidence=evidence,
            )
            arg_provenance = _promote_user_provenance(
                tool=tool,
                args=sanitized_args,
                intent=intent,
                clause=intent,
                arg_provenance=arg_provenance,
                resolved_predicates=supported_predicates,
            )
            clean_args, provenance_dropped = _strip_unsupported_optional_args(
                tool=tool,
                args=sanitized_args,
                intent=intent,
                clause=intent,
                intent_memory=intent_memory,
                resolved_predicates=supported_predicates,
                arg_provenance=arg_provenance,
            )

            depends_on_raw = raw_step.get("depends_on") if isinstance(raw_step.get("depends_on"), list) else []
            depends_on: list[int] = []
            for dep in depends_on_raw:
                try:
                    dep_i = int(dep)
                except Exception:
                    continue
                if 0 <= dep_i < idx:
                    depends_on.append(dep_i)
            bindings: list[PlanBinding] = []
            raw_bindings = raw_step.get("bindings") if isinstance(raw_step.get("bindings"), list) else []
            for raw_binding in raw_bindings:
                if not isinstance(raw_binding, dict):
                    continue
                try:
                    binding = PlanBinding.model_validate(raw_binding)
                except Exception:
                    raise PlannerClarificationError(f"I could not safely validate a dependency binding for step {idx + 1}.")
                bindings.append(binding)
                if binding.from_step < idx:
                    depends_on.append(binding.from_step)
            execution_mode = str(raw_step.get("execution_mode") or "single").strip().lower()
            if execution_mode not in {"single", "foreach"}:
                execution_mode = "single"
            if any(binding.mode == "foreach" for binding in bindings):
                execution_mode = "foreach"

            step_drafts.append(
                PlanStepDraft(
                    step_index=idx,
                    tool_name=tool.name,
                    args=clean_args,
                    depends_on=sorted(set(depends_on)) or ([idx - 1] if idx > 0 else []),
                    execution_mode=execution_mode,  # type: ignore[arg-type]
                    bindings=bindings,
                )
            )
            contract_steps.append(
                {
                    "step_index": idx,
                    "tool_name": tool.name,
                    "args": clean_args,
                    "bindings": [binding.model_dump() for binding in bindings],
                    "execution_mode": execution_mode,
                    "evidence": evidence,
                    "confidence": raw_step.get("confidence"),
                    "missing_required": missing,
                    "provenance_dropped": provenance_dropped,
                    "arg_provenance": arg_provenance,
                    "resolved_predicates": {
                        field: value
                        for field, value in supported_predicates.items()
                        if field not in set(provenance_dropped)
                    },
                }
            )

        if not step_drafts:
            raise PlannerClarificationError("I could not map that request to a safe factory tool plan.")

        plan_explanation = str(payload.get("plan_explanation") or "").strip() or f"Plan prepared for intent: {intent.strip()}."
        has_write = any((tool := tools_by_name.get(step.tool_name)) and not tool.is_read_only for step in step_drafts)
        risk_summary = str(payload.get("risk_summary") or "").strip() or (
            "This plan includes write operations and requires approval before execution."
            if has_write
            else "This plan is read-only and only retrieves information."
        )
        draft = PlanDraft(
            plan_explanation=plan_explanation,
            risk_summary=risk_summary,
            steps=step_drafts,
        )
        validation = validate_plan(draft, tools_by_name, max_steps=self._settings.max_plan_steps)
        if not validation.ok:
            raise PlannerBackendError("; ".join(validation.errors))
        return draft, {"intent": intent, "backend": "structured", "steps": contract_steps}

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        tools_markdown: str = "",
    ) -> PlannerResult:
        del tools_markdown
        if not scoped_tools:
            raise PlannerBackendError("No scoped tools available to generate a structured plan.")
        payload = await self._invoke_json(intent=intent, scoped_tools=scoped_tools, context=context)
        draft, contract = self._draft_from_payload(
            payload=payload,
            intent=intent,
            scoped_tools=scoped_tools,
            context=context,
        )
        return PlannerResult(draft=draft, backend_used="structured", llm_calls=1, intent_contract=contract)


class PlannerAdapter:
    def __init__(self, *, settings: Settings, tool_registry: ToolRegistry):
        self._settings = settings
        self._tool_registry = tool_registry
        self._legacy = LegacyPlannerBackend(settings)
        self._langchain = LangChainPlannerBackend(settings)
        self._structured = StructuredPlannerBackend(settings)

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        force_backend: PlannerBackendName | None = None,
    ) -> PlannerResult:
        backend = (force_backend or self._settings.planner_backend or "legacy").strip().lower()
        tools_markdown = self._tool_registry.load_tools_markdown()
        result: PlannerResult | None = None
        if backend == "structured":
            try:
                result = await self._structured.generate_plan(
                    intent=intent,
                    scoped_tools=scoped_tools,
                    context=context,
                    tools_markdown=tools_markdown,
                )
            except PlannerBackendError as exc:
                if not self._settings.planner_fallback_to_legacy:
                    raise
                log_event(
                    "planner_backend_fallback",
                    level="WARNING",
                    requested_backend="structured",
                    fallback_backend="legacy",
                    intent=intent,
                    scoped_tool_count=len(scoped_tools),
                    error=str(exc),
                )
        elif backend == "langchain":
            try:
                result = await self._langchain.generate_plan(
                    intent=intent,
                    scoped_tools=scoped_tools,
                    context=context,
                    tools_markdown=tools_markdown,
                )
            except PlannerBackendError as exc:
                if not self._settings.planner_fallback_to_legacy:
                    raise
                log_event(
                    "planner_backend_fallback",
                    level="WARNING",
                    requested_backend="langchain",
                    fallback_backend="legacy",
                    intent=intent,
                    scoped_tool_count=len(scoped_tools),
                    error=str(exc),
                )
        
        if result is None:
            result = await self._legacy.generate_plan(
                intent=intent,
                scoped_tools=scoped_tools,
                context=context,
                tools_markdown=tools_markdown,
            )
            tools_by_name = {tool.name: tool for tool in scoped_tools}
            has_write_step = any(
                (tool := tools_by_name.get(step.tool_name)) is not None and not tool.is_read_only
                for step in result.draft.steps
            )
            if backend in {"structured", "langchain"} and len(result.draft.steps) > 1 and has_write_step:
                raise PlannerBackendError(
                    "Structured planner was unavailable and legacy fallback produced a multi-step write plan; "
                    "refusing unsafe hardcoded compound write planning."
                )

        if result and result.draft and result.draft.steps:
            deduped_draft, dropped_steps = _dedupe_plan_steps(result.draft)
            if dropped_steps > 0:
                result = PlannerResult(
                    draft=deduped_draft,
                    backend_used=result.backend_used,
                    llm_calls=result.llm_calls,
                    intent_contract=result.intent_contract,
                )
                log_event(
                    "planner_duplicate_steps_deduped",
                    level="INFO",
                    intent=intent,
                    dropped_steps=dropped_steps,
                    remaining_steps=len(deduped_draft.steps),
                    backend_used=result.backend_used,
                )

        if result and result.draft and result.draft.steps:
            tools_by_name = {t.name: t for t in scoped_tools}
            intent_memory = None
            if isinstance(context, dict) and "memory" in context:
                intent_memory = context["memory"]
            elif isinstance(context, dict):
                intent_memory = context

            for step in result.draft.steps:
                tool = tools_by_name.get(step.tool_name)
                if not tool:
                    continue
                contract_clause = _lookup_contract_clause(
                    intent_contract=result.intent_contract,
                    step_index=step.step_index,
                    tool_name=tool.name,
                )
                contract_resolved_predicates = (
                    contract_clause.get("resolved_predicates")
                    if isinstance(contract_clause, dict) and isinstance(contract_clause.get("resolved_predicates"), dict)
                    else None
                )
                contract_arg_provenance = (
                    contract_clause.get("arg_provenance")
                    if isinstance(contract_clause, dict) and isinstance(contract_clause.get("arg_provenance"), dict)
                    else None
                )
                contract_arg_provenance = _promote_user_provenance(
                    tool=tool,
                    args=step.args or {},
                    intent=intent,
                    clause=str((contract_clause or {}).get("clause") or intent),
                    arg_provenance=contract_arg_provenance,
                    resolved_predicates=contract_resolved_predicates,
                )
                if isinstance(contract_clause, dict):
                    contract_clause["arg_provenance"] = contract_arg_provenance
                
                clean_args, dropped = _strip_unsupported_optional_args(
                    tool=tool,
                    args=step.args or {},
                    intent=intent,
                    clause=intent,
                    intent_memory=intent_memory,
                    resolved_predicates=contract_resolved_predicates,
                    arg_provenance=contract_arg_provenance,
                )
                if dropped:
                    step.args = clean_args
                    _mark_contract_fields_stripped(
                        intent_contract=result.intent_contract,
                        step_index=step.step_index,
                        tool_name=tool.name,
                        dropped_fields=dropped,
                    )
                    log_event(
                        "planner_universal_provenance_gate",
                        level="INFO",
                        tool_name=tool.name,
                        dropped_fields=dropped,
                        intent=intent,
                    )
        
        return result
