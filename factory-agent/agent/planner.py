from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Literal

from .config import Settings
from .intent import assess_intent
from .plan_validator import validate_plan
from .prompting import build_planner_prompt
from .reasoning_pipeline import ReasoningPipeline
from .schemas import PlanDraft, PlanStepDraft, ToolInfo
from .telemetry import log_event, log_llm_prompt, log_llm_prompt_skipped
from .tool_registry import ToolRegistry


PlannerBackendName = Literal["legacy", "langchain"]


class PlannerBackendError(RuntimeError):
    pass


class PlannerClarificationError(PlannerBackendError):
    pass


@dataclass(frozen=True)
class PlannerResult:
    draft: PlanDraft
    backend_used: PlannerBackendName
    llm_calls: int = 0


_NUMBER_RE = re.compile(r"\b\d+\b")
_KEYWORD_ID_RE = re.compile(r"\b(machine|job|inventory|approval|proposal|line|slot|schedule)\s+#?(\d+)\b", re.IGNORECASE)
_KEYWORD_TOKEN_ID_RE = re.compile(
    r"\b(machine|job|inventory|material|approval|proposal|line|slot|schedule|arrival|product)\s+(?:id\s+)?([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\b",
    re.IGNORECASE,
)
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
_SEED_ID_PREFIXES: list[tuple[str, str]] = [
    ("AIPROP-", "proposal"),
    ("JOB-", "job"),
    ("SLOT-", "slot"),
    ("MAT-", "inventory"),
    ("ARR-", "arrival"),
    ("APPROVAL-", "approval"),
    ("M-", "machine"),
    ("P-", "product"),
]
_INTENT_MATCH_KEYWORDS = (
    "slot",
    "slots",
    "schedule",
    "proposal",
    "proposals",
    "material",
    "materials",
    "inventory",
    "arrival",
    "arrivals",
    "approval",
    "machine",
    "job",
    "product",
)

_COMPOUND_SEPARATOR_RE = re.compile(
    r"\b(?:and then|then|next|after that|afterwards|finally)\b|[;\n.]+",
    re.IGNORECASE,
)
_AND_CONNECTOR_RE = re.compile(r"\b(?:and|also)\b", re.IGNORECASE)
_ACTION_VERB_RE = re.compile(
    r"\b(?:check|show|list|get|find|view|inspect|update|set|create|delete|approve|reject|replan|assign|schedule|replenish|move|run)\b",
    re.IGNORECASE,
)
_AUXILIARY_CAPABILITY_TAGS = {"list", "lookup", "status", "pending", "create", "update", "delete", "approve", "reject"}
_INTENT_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_ID_ONLY_PHRASE_RE = re.compile(r"\b(?:ids?\s+only|only\s+ids?|only\s+id|id\s+only)\b", re.IGNORECASE)
_LIST_VERB_RE = re.compile(r"\b(?:get|show|list|find|view|fetch|give|provide)\b", re.IGNORECASE)
_PLURAL_ENTITY_RE = re.compile(r"\b(?:products?|machines?|jobs?|materials?|inventories|inventory|proposals?|approvals?)\b", re.IGNORECASE)


def _tool_prefers_entity_lookup(tool: ToolInfo) -> bool:
    token = f"{tool.name} {tool.endpoint}".lower()
    return "{id}" in token or "_{id}" in token


def _tool_required_arg_count(tool: ToolInfo) -> int:
    return len((tool.input_schema or {}).get("required", []))


def _tool_missing_required_args(tool: ToolInfo, args: dict[str, Any]) -> int:
    required = list((tool.input_schema or {}).get("required", []))
    return sum(1 for field in required if field not in args or args.get(field) in (None, ""))


def _path_param_names(endpoint: str) -> list[str]:
    return [match.group(1) for match in _PATH_PARAM_RE.finditer(endpoint or "")]


def _normalize_entity_keyword(keyword: str) -> str:
    lowered = keyword.lower()
    return "inventory" if lowered == "material" else lowered


def _infer_entity_from_identifier(token: str) -> str | None:
    upper = token.upper()
    for prefix, entity in _SEED_ID_PREFIXES:
        if upper.startswith(prefix):
            return entity
    return None


def _infer_primary_entity(tool: ToolInfo) -> str | None:
    name = tool.name.lower()
    endpoint = (tool.endpoint or "").lower()
    token = f"{name} {endpoint} {' '.join(tool.capability_tags or [])}".lower()

    if endpoint.startswith("/machines") or "/machines/" in endpoint or "machines_" in name:
        return "machine"
    if endpoint.startswith("/jobs") or "/job-steps/" in endpoint or "/jobs/" in endpoint or "jobs_" in name:
        return "job"
    if endpoint.startswith("/inventory") or "/materials/" in endpoint or "materials_" in name:
        return "inventory"
    if endpoint.startswith("/chatbot/approval") or endpoint.startswith("/approvals") or "approval" in endpoint:
        return "approval"
    if endpoint.startswith("/proposals") or "/proposals/" in endpoint:
        return "proposal"

    for tag in tool.capability_tags or []:
        normalized = str(tag).strip().lower()
        if normalized and normalized not in _AUXILIARY_CAPABILITY_TAGS:
            return normalized

    if "/jobs/{id}/slots" in endpoint or "jobs_{id}_slots" in name:
        return "job"
    if "/jobs/{id}" in endpoint or "jobs_{id}" in name:
        return "job"
    if "/proposals/{id}" in endpoint or "proposals_{id}" in name:
        return "proposal"
    if "/machines/{id}" in endpoint or "machines_{id}" in name or "machine" in token:
        return "machine"
    if "/inventory/materials/{id}" in endpoint or "materials_{id}" in name or "material" in token:
        return "inventory"
    if "approval" in token:
        return "approval"
    if "arrival" in token:
        return "arrival"
    if "product" in token:
        return "product"
    if "line" in token:
        return "line"
    if "slot" in token:
        return "slot"
    return None


def _tool_matches_entity(tool: ToolInfo, entity: str | None) -> bool:
    return bool(entity) and _infer_primary_entity(tool) == entity


def _tool_intent_match_score(intent: str, tool: ToolInfo) -> int:
    assessment = assess_intent(intent)
    intent_lower = intent.lower()
    token = f"{tool.name} {tool.description} {tool.endpoint} {' '.join(tool.capability_tags or [])}".lower()
    score = 0
    for keyword in _INTENT_MATCH_KEYWORDS:
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
    for tag in tool.capability_tags or []:
        normalized = str(tag).strip().lower()
        if not normalized or normalized in _AUXILIARY_CAPABILITY_TAGS:
            continue
        if assessment.entity and normalized == assessment.entity:
            continue
        if _tag_matches_intent(tag=normalized, tokens=tokens):
            continue
        penalty += 3
    return penalty


def _extract_intent_entities(intent: str) -> dict[str, Any]:
    numbers = [int(match.group(0)) for match in _NUMBER_RE.finditer(intent or "")]
    ids_by_keyword: dict[str, Any] = {}
    for match in _KEYWORD_ID_RE.finditer(intent or ""):
        ids_by_keyword[match.group(1).lower()] = int(match.group(2))
    explicit_ids: list[str] = []
    for match in _KEYWORD_TOKEN_ID_RE.finditer(intent or ""):
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

    if field in {"quantity_total", "quantity", "qty", "units"} and field_type in {"integer", "number"}:
        qty = _extract_quantity_from_intent(intent)
        if qty is not None:
            return qty

    if field in {"deadline", "due_date", "due_at"} and field_type == "string":
        deadline = _extract_deadline_from_intent(intent)
        if deadline:
            return deadline

    if field in {"notes", "note", "comment", "description"} and field_type == "string":
        notes = _extract_notes_from_intent(intent)
        if notes:
            return notes

    if field in {"ids_only", "id_only"} and field_type == "boolean":
        if _intent_requests_id_only_fields(intent):
            return True

    if field in {"fields", "select"} and field_type == "string":
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
    if not _PLURAL_ENTITY_RE.search(lowered):
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


def _select_legacy_tool(intent: str, scoped_tools: list[ToolInfo]) -> ToolInfo:
    assessment = assess_intent(intent)
    entities = _extract_intent_entities(intent)
    preferred_entity = assessment.entity or next(iter(entities["ids_by_keyword"]), None)
    has_explicit_id = bool(entities["ids_by_keyword"]) or len(entities["numbers"]) == 1 or len(entities["explicit_ids"]) == 1

    ranked = sorted(
        scoped_tools,
        key=lambda t: (
            not _tool_matches_entity(t, preferred_entity),
            not (
                (assessment.action == "create" and t.method == "POST")
                or (assessment.action == "update" and t.method in {"PUT", "PATCH"})
                or (assessment.action == "approval" and "approval" in " ".join(t.capability_tags).lower())
                or (assessment.action == "delete" and t.method == "DELETE")
                or (assessment.action == "read" and t.method == "GET")
                or assessment.action is None
            ),
            not (has_explicit_id and _tool_prefers_entity_lookup(t)),
            _tool_missing_required_args(t, _extract_required_args(intent, t)[0]),
            -_tool_intent_match_score(intent, t),
            not t.is_read_only,
            t.name,
        ),
    )
    return ranked[0]


def _split_compound_intent(intent: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", intent or "").strip()
    if not normalized:
        return [""]

    parts = [part.strip(" ,") for part in _COMPOUND_SEPARATOR_RE.split(normalized) if part and part.strip(" ,")]
    if len(parts) > 1:
        return parts

    # Fall back to a conservative "and"/"also" split only when the request
    # looks genuinely multi-action, so we do not split ordinary noun phrases.
    if " and " in normalized.lower() or " also " in normalized.lower():
        parts = [part.strip(" ,") for part in _AND_CONNECTOR_RE.split(normalized) if part and part.strip(" ,")]
        actionful_parts = sum(1 for part in parts if _ACTION_VERB_RE.search(part))
        if len(parts) > 1 and actionful_parts >= 2:
            return parts

    return [normalized]


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

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        tools_markdown: str = "",
    ) -> PlannerResult:
        del context, tools_markdown
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
                or "I need a factory operations request before I can generate a tool plan."
            )

        clauses = _split_compound_intent(intent)
        step_drafts: list[PlanStepDraft] = []
        tools_by_name = {tool.name: tool for tool in scoped_tools}
        for idx, clause in enumerate(clauses):
            selected = _select_legacy_tool(clause, scoped_tools)
            args, missing = _extract_required_args(clause, selected)

            # LLM-first tool selection with deterministic guardrails.
            ranked_candidates = sorted(
                scoped_tools,
                key=lambda t: (
                    _tool_missing_required_args(t, _extract_required_args(clause, t)[0]),
                    -_tool_intent_match_score(clause, t),
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
                candidate_required_missing = _tool_missing_required_args(candidate, decision.args or {})
                if candidate_required_missing == 0 or candidate.requires_approval:
                    selected = candidate
                    args = decision.args or {}
                    missing = decision.missing_args or []

            if missing:
                # If the clause lost an identifier during splitting, retry with
                # the full intent before asking the user for clarification.
                fallback_args, fallback_missing = _extract_required_args(intent, selected)
                if not fallback_missing:
                    args = fallback_args
                    missing = []

            if missing:
                # For approval-gated tools (typically write operations), allow
                # partial args so the UI can present a schema-driven form for the
                # user to fill/confirm at approval time.
                if not selected.requires_approval:
                    pretty = ", ".join(missing)
                    raise PlannerClarificationError(
                        f"Need {pretty} before I can use `{selected.name}` for: {clause.strip() or intent.strip() or 'user request'}."
                    )

            step_drafts.append(
                PlanStepDraft(
                    step_index=idx,
                    tool_name=selected.name,
                    args=args,
                    depends_on=[idx - 1] if idx > 0 else [],
                )
            )

        plan_explanation, risk_summary, llm_calls = await self._build_explainability(
            intent=intent,
            scoped_tools=scoped_tools,
            steps=step_drafts,
        )
        draft = PlanDraft(
            plan_explanation=plan_explanation,
            risk_summary=risk_summary,
            steps=step_drafts,
        )
        return PlannerResult(draft=draft, backend_used="legacy", llm_calls=llm_calls)


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


class PlannerAdapter:
    def __init__(self, *, settings: Settings, tool_registry: ToolRegistry):
        self._settings = settings
        self._tool_registry = tool_registry
        self._legacy = LegacyPlannerBackend(settings)
        self._langchain = LangChainPlannerBackend(settings)

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
        if backend == "langchain":
            try:
                return await self._langchain.generate_plan(
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
                return await self._legacy.generate_plan(
                    intent=intent,
                    scoped_tools=scoped_tools,
                    context=context,
                    tools_markdown=tools_markdown,
                )
        return await self._legacy.generate_plan(
            intent=intent,
            scoped_tools=scoped_tools,
            context=context,
            tools_markdown=tools_markdown,
        )
