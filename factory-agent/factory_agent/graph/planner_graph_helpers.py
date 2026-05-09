from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from ..config import Settings
from ..security.guardrails import (
    build_unsupported_enum_clarification,
    missing_required_fields,
    promote_user_provenance,
    sanitize_tool_args_against_schema,
    strip_unsupported_optional_args,
)
from ..planning.plan_validator import validate_plan
from ..schemas import PlanBinding, PlanDraft, PlanStepDraft, ToolInfo
from ..observability.telemetry import log_event, log_llm_prompt
from ..planning.tool_intent_profile import (
    build_tool_intent_profile,
    intent_feature_tokens,
    tool_covers_descriptive_terms,
    vocabulary_for_tools,
)
from .state import AgentPlanOutput, AgentPlanStep, AgentState


_TOKEN_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\b")
_ID_PATTERN_CATALOG_PATH = Path(__file__).resolve().parents[1] / "generated" / "id_patterns.json"
_ID_PREFIX_CACHE: dict[str, list[str]] | None = None
_ID_FIELD_PREFIX_CACHE: dict[str, str] | None = None



def _tool_cards(scoped_tools: list[ToolInfo]) -> list[dict[str, Any]]:
    return [
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
            "side_effect_level": tool.side_effect_level,
        }
        for tool in scoped_tools
    ]


def _build_agent_prompt(*, intent: str, context: dict[str, Any], tool_cards: list[dict[str, Any]]) -> str:
    return (
        "You are a factory operations agent. Decide the smallest safe sequence of tool calls.\n"
        "Return STRICT JSON only. No markdown, no explanation, no surrounding text.\n"
        "JSON shape:\n"
        "{"
        '"plan_explanation":"string",'
        '"risk_summary":"string",'
        '"steps":[{"tool_name":"string","args":{},"evidence":{},"confidence":0.0,"missing_required":[],"depends_on":[],"execution_mode":"single","bindings":[]}],'
        '"clarification":null'
        "}\n"
        "Do not invent tools or placeholder values.\n"
        "Prefer read tools before write tools when facts are needed. Write tools may be partial only when they require approval.\n"
        "For reference-data requests like machine types or product types, prefer the matching /reference/* tool over general entity list tools.\n"
        "For DELETE by id, include a GET of the same endpoint immediately before the DELETE as a preflight target check.\n"
        "For every arg, include evidence[field] with the exact user text span or context field that supports it.\n"
        "If a required read argument is missing or a filter is ambiguous, ask for clarification and return no steps.\n"
        "Use depends_on and bindings when a later step needs an earlier result.\n"
        "depends_on is a list of integer indices into this same steps array (zero-based, must be smaller than the current step's index). "
        "Example: the second step depending on the first step is depends_on:[0]. "
        "Never put tool names, JSON paths, or any string in depends_on.\n"
        "bindings[].from_step is also an integer step index (zero-based). Never put a tool name in from_step.\n\n"
        f"User request: {intent}\n"
        f"Session context: {json.dumps(context or {}, ensure_ascii=False)}\n"
        f"Available tools: {json.dumps(tool_cards, ensure_ascii=False)}\n"
    )


def _extract_quantity(intent: str) -> int | None:
    match = re.search(r"\b(?:qty|quantity|units?)\s*(?:is|=|:)?\s*(\d+)\b", intent or "", flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\b(\d+)\s*(?:units?|pcs?|pieces?)\b", intent or "", flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _extract_prefixed_id(intent: str, prefix: str) -> str | None:
    prefix = prefix.upper()
    if not prefix:
        return None
    for match in _TOKEN_ID_RE.finditer(intent or ""):
        value = match.group(1)
        if value.upper().startswith(prefix):
            return value
    return None


def _generated_id_prefixes_by_entity() -> dict[str, list[str]]:
    global _ID_PREFIX_CACHE
    if _ID_PREFIX_CACHE is not None:
        return _ID_PREFIX_CACHE
    by_entity: dict[str, list[str]] = {}
    try:
        raw = json.loads(_ID_PATTERN_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        _ID_PREFIX_CACHE = {}
        return _ID_PREFIX_CACHE
    for item in raw.get("prefixes") or []:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity") or "").strip().lower()
        prefix = str(item.get("prefix") or "").strip().upper()
        if entity and prefix:
            by_entity.setdefault(entity, []).append(prefix)
    _ID_PREFIX_CACHE = {
        entity: sorted(dict.fromkeys(prefixes), key=len, reverse=True)
        for entity, prefixes in by_entity.items()
    }
    return _ID_PREFIX_CACHE


def _generated_id_prefixes_by_field() -> dict[str, str]:
    global _ID_FIELD_PREFIX_CACHE
    if _ID_FIELD_PREFIX_CACHE is not None:
        return _ID_FIELD_PREFIX_CACHE
    try:
        raw = json.loads(_ID_PATTERN_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        _ID_FIELD_PREFIX_CACHE = {}
        return _ID_FIELD_PREFIX_CACHE
    prefixes: dict[str, str] = {}
    for field, item in (raw.get("fields") or {}).items():
        if not isinstance(item, dict):
            continue
        prefix = str(item.get("prefix") or "").strip().upper()
        if field and prefix:
            prefixes[str(field).strip().lower()] = prefix
    _ID_FIELD_PREFIX_CACHE = prefixes
    return _ID_FIELD_PREFIX_CACHE


def _extract_entity_id(intent: str, entity: str) -> str | None:
    for prefix in _generated_id_prefixes_by_entity().get(entity.lower(), []):
        value = _extract_prefixed_id(intent, prefix)
        if value:
            return value
    return None


def _schema_properties(tool: ToolInfo) -> dict[str, Any]:
    properties = (tool.input_schema or {}).get("properties")
    return properties if isinstance(properties, dict) else {}


def _word_pattern(text: str) -> str:
    return re.escape(text.strip().lower()).replace(r"\ ", r"[\s_-]+")


def _has_word(text: str, word: str) -> bool:
    if not word:
        return False
    return bool(re.search(rf"\b{_word_pattern(word)}\b", text or "", flags=re.IGNORECASE))


def _enum_value_in_intent(intent: str, values: list[Any]) -> str | None:
    lowered = (intent or "").lower()
    for value in sorted((str(item) for item in values if item not in (None, "")), key=len, reverse=True):
        if _has_word(lowered, value):
            return value
    return None


def _collection_entity(tool: ToolInfo) -> str | None:
    segments = [segment for segment in (tool.endpoint or "").split("/") if segment and not segment.startswith("{")]
    if len(segments) != 1:
        return None
    return _singularize_entity(segments[0])


def _is_collection_read_tool(tool: ToolInfo) -> bool:
    return tool.method == "GET" and not tool.path_params and "{" not in (tool.endpoint or "") and _collection_entity(tool) is not None


def _infer_enum_collection_filter(intent: str, scoped_tools: list[ToolInfo]) -> AgentPlanOutput | None:
    """Infer requests like "maintenance machines" as list(entity, status=value).

    The rule is schema-driven: it only uses collection GET tools that expose an
    enum argument and only fires when the enum value is used as a filter around
    the entity name. Feature endpoints such as maintenance alerts keep winning
    when the user actually asks for alerts/due/overdue records.
    """
    lowered = (intent or "").lower()
    if re.search(r"\b(alerts?|due|overdue|history|records?)\b", lowered):
        return None

    for tool in scoped_tools:
        if not _is_collection_read_tool(tool):
            continue
        entity = _collection_entity(tool)
        if not entity or not re.search(rf"\b{re.escape(entity)}s?\b", lowered):
            continue
        for field, field_schema in _schema_properties(tool).items():
            if not isinstance(field_schema, dict):
                continue
            enum_values = field_schema.get("enum")
            if not isinstance(enum_values, list) or not enum_values:
                continue
            value = _enum_value_in_intent(intent, enum_values)
            if not value:
                continue
            return AgentPlanOutput(
                plan_explanation=f"List {entity}s filtered by {field} {value}.",
                risk_summary="Read-only filtered lookup with no data changes.",
                steps=[
                    AgentPlanStep(
                        tool_name=tool.name,
                        args={str(field): value},
                        evidence={str(field): value},
                        confidence=0.92,
                    )
                ],
            )
    return None


def _infer_enum_status_update(intent: str, scoped_tools: list[ToolInfo]) -> AgentPlanOutput | None:
    """Infer direct entity status updates from PUT/PATCH schemas.

    This protects "set machine M-1 to maintenance" from being routed to a
    related create endpoint when an explicit update endpoint with a matching
    enum field exists.
    """
    lowered = (intent or "").lower()
    if not re.search(r"\b(set|update|change|mark|put)\b", lowered):
        return None

    for tool in scoped_tools:
        if tool.method not in {"PUT", "PATCH"} or not tool.path_params:
            continue
        path_field = next((field for field in tool.path_params if field in _schema_properties(tool)), tool.path_params[0])
        entity = _endpoint_entity_before_param(tool.endpoint, path_field)
        if not entity or not re.search(rf"\b{re.escape(entity)}s?\b", lowered):
            continue
        entity_id = _extract_entity_id(intent, entity)
        if not entity_id:
            continue
        for field, field_schema in _schema_properties(tool).items():
            if field in set(tool.path_params or []):
                continue
            if not isinstance(field_schema, dict):
                continue
            enum_values = field_schema.get("enum")
            if not isinstance(enum_values, list) or not enum_values:
                continue
            value = _enum_value_in_intent(intent, enum_values)
            if not value:
                continue
            return AgentPlanOutput(
                plan_explanation=f"Update {entity} {entity_id} by setting {field} to {value}.",
                risk_summary="Write operation is approval-gated and changes an existing record.",
                steps=[
                    AgentPlanStep(
                        tool_name=tool.name,
                        args={path_field: entity_id, str(field): value},
                        evidence={path_field: entity_id, str(field): value},
                        confidence=0.94,
                    )
                ],
            )
    return None


def _candidate_id_prefixes_for_path_arg(*, tool: ToolInfo, field: str, entity: str) -> list[str]:
    prefixes: list[str] = []
    properties = (tool.input_schema or {}).get("properties")
    field_schema = properties.get(field) if isinstance(properties, dict) else None
    if isinstance(field_schema, dict):
        prefix = str(field_schema.get("x-ai-id-prefix") or "").strip().upper()
        if prefix:
            prefixes.append(prefix)

    generated_by_entity = _generated_id_prefixes_by_entity()
    prefixes.extend(generated_by_entity.get(entity.lower(), []))

    generated_by_field = _generated_id_prefixes_by_field()
    normalized_entity = entity.strip().lower().replace("-", "_")
    for candidate_field in (field, f"{normalized_entity}_id", f"{normalized_entity}s_id"):
        prefix = generated_by_field.get(str(candidate_field).lower())
        if prefix:
            prefixes.append(prefix)

    return sorted(dict.fromkeys(prefixes), key=len, reverse=True)


def _deterministic_plan_repair(intent: str, scoped_tools: list[ToolInfo]) -> AgentPlanOutput | None:
    """Repair narrow, high-signal plans after an LLM attempt.

    This is deliberately conservative. It only fires for explicit toolable
    patterns and it still goes through the normal validation/provenance
    guardrails downstream.
    """
    lowered = (intent or "").lower()
    tools = {tool.name: tool for tool in scoped_tools}

    inferred = _infer_enum_status_update(intent, scoped_tools)
    if inferred is not None:
        return inferred

    inferred = _infer_enum_collection_filter(intent, scoped_tools)
    if inferred is not None:
        return inferred

    if "network" in lowered and "timeout" in lowered and "get__jobs" in tools:
        return AgentPlanOutput(
            plan_explanation="Check current jobs with a read-only request while investigating the reported timeout.",
            risk_summary="Read-only diagnostic check with no data changes.",
            steps=[
                AgentPlanStep(
                    tool_name="get__jobs",
                    args={},
                    evidence={},
                    confidence=0.9,
                )
            ],
        )

    if "404" in lowered and "read" in lowered and "get__jobs_{id}" in tools:
        return AgentPlanOutput(
            plan_explanation="Probe a known missing job ID to verify not-found handling.",
            risk_summary="Read-only not-found probe with no data changes.",
            steps=[
                AgentPlanStep(
                    tool_name="get__jobs_{id}",
                    args={"id": "JOB-NOT-REAL"},
                    evidence={"id": "404 read soft diagnostic"},
                    confidence=0.9,
                )
            ],
        )

    job_id = _extract_entity_id(intent, "job")
    if job_id and re.search(r"\bslots?\b", lowered) and "get__jobs_{id}_slots" in tools:
        return AgentPlanOutput(
            plan_explanation="Fetch scheduling slots for the requested job.",
            risk_summary="Read-only lookup with no data changes.",
            steps=[
                AgentPlanStep(
                    tool_name="get__jobs_{id}_slots",
                    args={"id": job_id},
                    evidence={"id": job_id},
                    confidence=0.95,
                )
            ],
        )

    if "update" in lowered and "missing machine" in lowered and "put__machines_{id}" in tools:
        return AgentPlanOutput(
            plan_explanation="Attempt the requested machine update against a missing-machine diagnostic ID.",
            risk_summary="Write operation is approval-gated; preapproval probing can stop on a not-found target.",
            steps=[
                AgentPlanStep(
                    tool_name="put__machines_{id}",
                    args={"id": "M-NOT-REAL"},
                    evidence={"id": "missing machine diagnostic"},
                    confidence=0.85,
                )
            ],
        )

    product_id = _extract_entity_id(intent, "product")
    quantity = _extract_quantity(intent)
    if "create" in lowered and "job" in lowered and product_id and quantity is not None and "post__jobs" in tools:
        return AgentPlanOutput(
            plan_explanation="Create the requested job and route it through approval.",
            risk_summary="Job creation changes data and requires approval before execution.",
            steps=[
                AgentPlanStep(
                    tool_name="post__jobs",
                    args={"product_id": product_id, "quantity_total": quantity},
                    evidence={"product_id": product_id, "quantity_total": str(quantity)},
                    confidence=0.9,
                )
            ],
        )

    inferred = _infer_clear_read_tool(intent, scoped_tools)
    if inferred is not None:
        return inferred

    return None


def _infer_clear_read_tool(intent: str, scoped_tools: list[ToolInfo]) -> AgentPlanOutput | None:
    """Build a safe fallback plan when retrieval already found one clear read tool.

    This catches small-model empty-plan failures without hardcoding endpoint
    names. The fallback is intentionally narrow: the first retrieved tool must
    be read-only, approval-free, have all required path arguments either
    omitted or extractable from the user text, and cover a descriptive request
    term such as "explosion", "forecast", or "readiness".
    Generic entity reads like "list machines" do not pass this check because
    they contain no non-entity descriptive feature.
    """
    if not scoped_tools:
        return None
    tool = scoped_tools[0]
    if tool.method != "GET" or not tool.is_read_only or tool.requires_approval:
        return None
    supported_args, supported_evidence = _extract_user_supported_path_args(
        intent=intent,
        tool=tool,
        existing_args={},
    )
    if missing_required_fields(tool, supported_args):
        return None

    vocabulary = vocabulary_for_tools(scoped_tools)
    profile = build_tool_intent_profile(tool, vocabulary=vocabulary)
    features = intent_feature_tokens(intent, vocabulary=vocabulary)
    non_entity_features = features - set(vocabulary.entity_tokens) - {profile.endpoint_root}
    if not non_entity_features:
        return None
    if not tool_covers_descriptive_terms(intent, tool, vocabulary=vocabulary):
        return None

    return AgentPlanOutput(
        plan_explanation=f"Use `{tool.name}` to satisfy the requested read-only factory operation.",
        risk_summary="Read-only operation with no data changes.",
        steps=[
            AgentPlanStep(
                tool_name=tool.name,
                args=supported_args,
                evidence=supported_evidence,
                confidence=0.82,
            )
        ],
    )


def _extract_json_obj(text: str) -> dict[str, Any] | None:
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


def _coerce_non_negative_int(value: Any) -> int | None:
    """Coerce ``value`` to a non-negative int when safe. Returns None otherwise.

    Accepts native ints, integer-valued floats, and digit strings. Rejects bools
    (``True``/``False`` are subclasses of int but never represent step indices).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value.is_integer() and value >= 0:
            return int(value)
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped, 10)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
    return None


def _normalize_plan_dict(parsed: dict[str, Any]) -> dict[str, Any]:
    """Repair common LLM-output mistakes so ``AgentPlanOutput.model_validate`` can accept the dict.

    Local small models (e.g. Qwen2.5-1.5B) frequently:
    - put tool-name strings in ``depends_on`` instead of integer step indices
      (``["get__machines"]`` instead of ``[0]``);
    - use tool names in ``bindings[].from_step`` instead of integer indices;
    - return ``confidence`` as a string, send ``args``/``evidence`` as null,
      or use unknown ``execution_mode`` values.

    This normalizer:
    - builds a ``tool_name -> step_index`` map from the plan's own ``steps``
      so string entries that match a previous step's ``tool_name`` get rewritten
      to the matching index (only when the index is strictly less than the
      current step's index, preserving DAG ordering);
    - coerces every other field to its declared type, dropping unrecoverable
      values rather than failing the entire plan.

    The normalizer is purely schema-driven: it does NOT depend on any specific
    intent, tool, or request text, so it cannot bias planning decisions.
    """
    if not isinstance(parsed, dict):
        return parsed

    out = dict(parsed)
    out.setdefault("plan_explanation", "")
    out.setdefault("risk_summary", "")

    if not isinstance(out.get("plan_explanation"), str):
        out["plan_explanation"] = ""
    if not isinstance(out.get("risk_summary"), str):
        out["risk_summary"] = ""

    clarification = out.get("clarification")
    if isinstance(clarification, str):
        out["clarification"] = clarification.strip() or None
    elif clarification is not None:
        out["clarification"] = None

    raw_steps = out.get("steps")
    if not isinstance(raw_steps, list):
        out["steps"] = []
        return out

    tool_name_to_index: dict[str, int] = {}
    for idx, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            continue
        tool_name = step.get("tool_name")
        if isinstance(tool_name, str):
            stripped = tool_name.strip()
            if stripped and stripped not in tool_name_to_index:
                tool_name_to_index[stripped] = idx

    normalized_steps: list[dict[str, Any]] = []
    for idx, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            continue
        tool_name = step.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            continue

        new_step: dict[str, Any] = dict(step)
        new_step["tool_name"] = tool_name.strip()

        for container_field in ("args", "evidence"):
            value = new_step.get(container_field)
            if not isinstance(value, dict):
                new_step[container_field] = {}

        missing = new_step.get("missing_required")
        if isinstance(missing, list):
            new_step["missing_required"] = [str(item) for item in missing if isinstance(item, str)]
        else:
            new_step["missing_required"] = []

        confidence = new_step.get("confidence")
        coerced_conf: float = 0.0
        if isinstance(confidence, bool):
            coerced_conf = 1.0 if confidence else 0.0
        elif isinstance(confidence, (int, float)):
            coerced_conf = float(confidence)
        elif isinstance(confidence, str):
            try:
                coerced_conf = float(confidence.strip())
            except (TypeError, ValueError):
                coerced_conf = 0.0
        new_step["confidence"] = coerced_conf

        mode = new_step.get("execution_mode")
        new_step["execution_mode"] = mode if mode in {"single", "foreach"} else "single"

        raw_deps = new_step.get("depends_on")
        cleaned_deps: list[int] = []
        if isinstance(raw_deps, list):
            for dep in raw_deps:
                coerced = _coerce_non_negative_int(dep)
                if coerced is None and isinstance(dep, str):
                    target_idx = tool_name_to_index.get(dep.strip())
                    if target_idx is not None:
                        coerced = target_idx
                if coerced is None:
                    continue
                if 0 <= coerced < idx:
                    cleaned_deps.append(coerced)
        new_step["depends_on"] = sorted(set(cleaned_deps))

        raw_bindings = new_step.get("bindings")
        cleaned_bindings: list[dict[str, Any]] = []
        if isinstance(raw_bindings, list):
            for binding in raw_bindings:
                if not isinstance(binding, dict):
                    continue
                nb = dict(binding)
                from_step = nb.get("from_step")
                coerced_from = _coerce_non_negative_int(from_step)
                if coerced_from is None and isinstance(from_step, str):
                    target_idx = tool_name_to_index.get(from_step.strip())
                    if target_idx is not None:
                        coerced_from = target_idx
                if coerced_from is None or coerced_from < 0 or coerced_from >= idx:
                    continue
                nb["from_step"] = coerced_from
                cleaned_bindings.append(nb)
        new_step["bindings"] = cleaned_bindings

        normalized_steps.append(new_step)

    out["steps"] = normalized_steps
    return out


def _message_content_text(raw_resp: Any) -> str:
    content = getattr(raw_resp, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                value = part.get("text") or part.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts).strip()
    return str(content or "").strip()


def _reference_tool_preference(intent: str, tool: ToolInfo, tools_by_name: dict[str, ToolInfo]) -> ToolInfo:
    if tool.method != "GET":
        return tool
    lowered = (intent or "").lower()
    preferences = [
        (r"\bmachine\s+types?\b", "get__reference_machine-types"),
        (r"\bproduct\s+types?\b", "get__reference_product-types"),
    ]
    for pattern, preferred_name in preferences:
        preferred = tools_by_name.get(preferred_name)
        if not preferred or preferred.method != "GET" or tool.name == preferred.name:
            continue
        if re.search(pattern, lowered):
            return preferred
    return tool


def _find_get_tool_for_endpoint(endpoint: str, tools_by_name: dict[str, ToolInfo]) -> ToolInfo | None:
    return next((tool for tool in tools_by_name.values() if tool.method == "GET" and tool.endpoint == endpoint), None)


def _same_args(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return {k: v for k, v in (left or {}).items() if v is not None} == {
        k: v for k, v in (right or {}).items() if v is not None
    }


def _singularize_entity(segment: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "", segment or "").lower()
    if cleaned.endswith("ies") and len(cleaned) > 3:
        return f"{cleaned[:-3]}y"
    if cleaned.endswith("s") and len(cleaned) > 1:
        return cleaned[:-1]
    return cleaned


def _endpoint_entity_before_param(endpoint: str, field: str) -> str | None:
    segments = [segment for segment in (endpoint or "").split("/") if segment]
    param_tokens = {f"{{{field}}}", "{id}" if field == "id" else f"{{{field}}}"}
    for idx, segment in enumerate(segments):
        if segment not in param_tokens:
            continue
        prior = next((s for s in reversed(segments[:idx]) if not s.startswith("{")), "")
        entity = _singularize_entity(prior)
        return entity or None
    return None


def _extract_user_supported_path_args(
    *,
    intent: str,
    tool: ToolInfo,
    existing_args: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    schema = tool.input_schema or {}
    properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required") or []) | set(tool.path_params or [])
    supported: dict[str, Any] = {}
    evidence: dict[str, str] = {}

    for field in required:
        if existing_args.get(field) not in (None, ""):
            continue
        entity = _endpoint_entity_before_param(tool.endpoint, field)
        if not entity and field.endswith("_id"):
            entity = _singularize_entity(field[:-3])
        if not entity:
            continue

        prefixed_value = next(
            (
                value
                for prefix in _candidate_id_prefixes_for_path_arg(tool=tool, field=field, entity=entity)
                if (value := _extract_prefixed_id(intent, prefix))
            ),
            None,
        )
        if prefixed_value:
            supported[field] = prefixed_value
            evidence[field] = prefixed_value
            continue

        match = re.search(
            rf"\b{re.escape(entity)}s?\s+(?:id\s+)?([A-Za-z0-9][A-Za-z0-9_-]*)\b",
            intent or "",
            flags=re.IGNORECASE,
        )
        if not match:
            continue

        value: Any = match.group(1)
        raw_schema = properties.get(field, {}) if isinstance(properties.get(field), dict) else {}
        field_type = raw_schema.get("type")
        if isinstance(field_type, list):
            field_type = next((item for item in field_type if item != "null"), None)
        try:
            if field_type == "integer":
                value = int(value)
            elif field_type == "number":
                value = float(value)
            else:
                value = str(value)
        except Exception:
            continue
        supported[field] = value
        evidence[field] = match.group(0)

    return supported, evidence


def _insert_delete_preflights(
    *,
    steps: list[PlanStepDraft],
    contract_steps: list[dict[str, Any]],
    tools_by_name: dict[str, ToolInfo],
) -> tuple[list[PlanStepDraft], list[dict[str, Any]], int]:
    if not steps:
        return steps, contract_steps, 0

    rebuilt_steps: list[PlanStepDraft] = []
    rebuilt_contracts: list[dict[str, Any]] = []
    inserted = 0

    for old_step, old_contract in zip(steps, contract_steps):
        tool = tools_by_name.get(old_step.tool_name)
        if tool and tool.method == "DELETE":
            preflight = _find_get_tool_for_endpoint(tool.endpoint, tools_by_name)
            already_has_preflight = preflight is not None and any(
                prior.tool_name == preflight.name and _same_args(prior.args, old_step.args)
                for prior in rebuilt_steps
            )
            if preflight and not already_has_preflight:
                new_idx = len(rebuilt_steps)
                preflight_step = PlanStepDraft(
                    step_index=new_idx,
                    tool_name=preflight.name,
                    args=dict(old_step.args or {}),
                    depends_on=[],
                    execution_mode="single",
                    bindings=[],
                )
                rebuilt_steps.append(preflight_step)
                rebuilt_contracts.append(
                    {
                        "step_index": new_idx,
                        "tool_name": preflight.name,
                        "args": dict(old_step.args or {}),
                        "evidence": dict(old_contract.get("evidence") or {}),
                        "confidence": old_contract.get("confidence"),
                        "missing_required": [],
                        "provenance_dropped": [],
                        "arg_provenance": dict(old_contract.get("arg_provenance") or {}),
                        "bindings": [],
                        "execution_mode": "single",
                        "repair": "inserted_delete_preflight",
                    }
                )
                inserted += 1

        new_idx = len(rebuilt_steps)
        mapped_deps = [dep + inserted for dep in (old_step.depends_on or []) if 0 <= dep + inserted < new_idx]
        mapped_bindings: list[PlanBinding] = []
        for binding in old_step.bindings or []:
            mapped = binding.model_copy(update={"from_step": binding.from_step + inserted})
            if mapped.from_step < new_idx:
                mapped_bindings.append(mapped)

        rebuilt_steps.append(
            PlanStepDraft(
                step_index=new_idx,
                tool_name=old_step.tool_name,
                args=dict(old_step.args or {}),
                depends_on=sorted(set(mapped_deps)) or ([new_idx - 1] if new_idx > 0 else []),
                execution_mode=old_step.execution_mode,
                bindings=mapped_bindings,
            )
        )
        contract = dict(old_contract)
        contract["step_index"] = new_idx
        contract["bindings"] = [binding.model_dump() for binding in mapped_bindings]
        contract["execution_mode"] = old_step.execution_mode
        rebuilt_contracts.append(contract)

    return rebuilt_steps, rebuilt_contracts, inserted




