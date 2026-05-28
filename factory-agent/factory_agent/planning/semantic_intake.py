from __future__ import annotations

import json
import re
import time
from typing import Any, Literal, Protocol

from pydantic import Field, ValidationError

from ..config import Settings
from ..llm.models import build_semantic_intake_chat_model
from ..observability.telemetry import log_event
from .intent import semantic_frame_for_text, split_user_intents
from .v2_contracts import RequirementClauseRole, V2ContractModel


SemanticIntakeSource = Literal["llm", "deterministic_fallback", "test_fake"]


class SemanticIntakeItem(V2ContractModel):
    id: str = Field(min_length=1)
    role: RequirementClauseRole
    text: str = Field(min_length=1)
    parent_item_id: str | None = None
    condition: dict[str, Any] = Field(default_factory=dict)
    child_intent: dict[str, Any] = Field(default_factory=dict)
    applies_to_item_ids: list[str] = Field(default_factory=list)
    reason: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class SemanticIntakeResult(V2ContractModel):
    user_goal: str = Field(min_length=1)
    items: list[SemanticIntakeItem] = Field(default_factory=list)
    source: SemanticIntakeSource
    proposer: str = Field(min_length=1)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class SemanticIntakeProposer(Protocol):
    proposer_name: str

    def propose(
        self,
        text: str,
        *,
        prepared_clauses: list[str] | None = None,
    ) -> SemanticIntakeResult:
        ...


class StaticSemanticIntakeProposer:
    proposer_name = "static_semantic_intake_proposer"

    def __init__(self, result: SemanticIntakeResult | dict[str, Any]) -> None:
        self._result = (
            result
            if isinstance(result, SemanticIntakeResult)
            else SemanticIntakeResult.model_validate(result)
        )

    def propose(
        self,
        text: str,
        *,
        prepared_clauses: list[str] | None = None,
    ) -> SemanticIntakeResult:
        _ = prepared_clauses
        return self._result.model_copy(
            update={
                "user_goal": text,
                "source": "test_fake",
                "proposer": self.proposer_name,
            },
            deep=True,
        )


class DeterministicFallbackSemanticIntakeProposer:
    proposer_name = "deterministic_fallback_semantic_intake_proposer"

    def propose(
        self,
        text: str,
        *,
        prepared_clauses: list[str] | None = None,
    ) -> SemanticIntakeResult:
        raw_clauses = prepared_clauses or [item.description for item in split_user_intents(text)]
        items: list[SemanticIntakeItem] = []
        previous_work_item_id: str | None = None

        for clause in raw_clauses:
            clause = str(clause or "").strip()
            if not clause:
                continue

            required_text, formatting_text = _split_formatting_suffix(clause)
            if required_text != clause:
                work_item = _semantic_item(
                    items,
                    role="required_requirement",
                    text=required_text,
                    reason="required_clause_with_trailing_formatting_instruction",
                )
                items.append(work_item)
                previous_work_item_id = work_item.id
                items.append(
                    _semantic_item(
                        items,
                        role="formatting_instruction",
                        text=formatting_text,
                        applies_to_item_ids=[work_item.id],
                        reason="formatting_instruction",
                    )
                )
                continue

            conditional = _conditional_item_payload(clause, parent_item_id=previous_work_item_id)
            if conditional is not None:
                item = _semantic_item(
                    items,
                    role="conditional_branch",
                    text=clause,
                    parent_item_id=previous_work_item_id,
                    reason="conditional_branch_waits_for_parent_evidence",
                    **conditional,
                )
                items.append(item)
                previous_work_item_id = item.id
                continue

            frame = semantic_frame_for_text(clause)
            if _is_answer_instruction(clause, frame=frame, has_context=bool(previous_work_item_id)):
                items.append(
                    _semantic_item(
                        items,
                        role="answer_instruction",
                        text=clause,
                        applies_to_item_ids=[previous_work_item_id] if previous_work_item_id else [],
                        reason="answer_composition_instruction",
                    )
                )
                continue

            formatting = _formatting_instruction_reason(clause, frame=frame)
            if formatting:
                items.append(
                    _semantic_item(
                        items,
                        role="formatting_instruction",
                        text=clause,
                        applies_to_item_ids=[previous_work_item_id] if previous_work_item_id else [],
                        reason=formatting,
                    )
                )
                continue

            clarification = _clarification_need_payload(clause, frame=frame)
            if clarification is not None:
                items.append(
                    _semantic_item(
                        items,
                        role="clarification_need",
                        text=clause,
                        reason=clarification["reason"],
                        diagnostics={"blocked_entity": clarification.get("entity")},
                    )
                )
                continue

            role: RequirementClauseRole = (
                "mutation_or_approval_request"
                if _is_mutation_or_approval_request(clause, frame=frame)
                else "required_requirement"
            )
            item = _semantic_item(
                items,
                role=role,
                text=clause,
                reason="semantic_role_proposed_by_deterministic_fallback",
            )
            items.append(item)
            previous_work_item_id = item.id

        return SemanticIntakeResult(
            user_goal=text,
            items=items,
            source="deterministic_fallback",
            proposer=self.proposer_name,
            diagnostics={
                "prepared_clause_count": len(raw_clauses),
                "role_counts": _role_counts(items),
            },
        )


class OpenAICompatibleSemanticIntakeProposer:
    proposer_name = "openai_compatible_semantic_intake_proposer"

    def __init__(self, settings: Settings, *, model: Any | None = None) -> None:
        self._settings = settings
        self._model = model

    def propose(
        self,
        text: str,
        *,
        prepared_clauses: list[str] | None = None,
    ) -> SemanticIntakeResult:
        effective_clauses = prepared_clauses
        if effective_clauses is None:
            effective_clauses = [item.description for item in split_user_intents(text)]
        prompt = _build_semantic_intake_prompt(text, prepared_clauses=effective_clauses)
        model = self._model or build_semantic_intake_chat_model(self._settings, json_mode=True)
        started = time.perf_counter()
        log_event(
            "semantic_intake_proposer_llm_start",
            adapter=self.proposer_name,
            model_name=self._settings.semantic_intake_model,
            prompt_chars=len(prompt),
            prepared_clause_count=len(effective_clauses),
        )
        raw_response = model.invoke(prompt)
        content = _message_content_text(raw_response)
        parsed = _extract_json_object(content)
        diagnostics = {
            "llm_invoked": True,
            "real_llm_mode": True,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "prompt_chars": len(prompt),
            "content_chars": len(content),
            "raw_content_preview": content[:500],
        }
        if not isinstance(parsed, dict):
            raise ValueError("semantic intake proposer returned invalid JSON")
        try:
            result = SemanticIntakeResult.model_validate(
                {
                    "user_goal": text,
                    "items": _normalize_llm_items(_llm_items_payload(parsed)),
                    "source": "llm",
                    "proposer": self.proposer_name,
                    "diagnostics": {
                        **diagnostics,
                        **(parsed.get("diagnostics") if isinstance(parsed.get("diagnostics"), dict) else {}),
                    },
                }
            )
        except ValidationError as exc:
            raise ValueError("semantic intake proposer returned an invalid schema") from exc
        log_event(
            "semantic_intake_proposer_llm_complete",
            adapter=self.proposer_name,
            model_name=self._settings.semantic_intake_model,
            duration_ms=diagnostics["duration_ms"],
            content_chars=len(content),
            role_counts=_role_counts(result.items),
        )
        return result


def build_semantic_intake_proposer(settings: Settings) -> SemanticIntakeProposer:
    if settings.planner_openai_base_url or settings.openai_api_key:
        return OpenAICompatibleSemanticIntakeProposer(settings)
    return DeterministicFallbackSemanticIntakeProposer()


def propose_semantic_intake_for_text(
    text: str,
    *,
    proposer: SemanticIntakeProposer | None = None,
    prepared_clauses: list[str] | None = None,
) -> SemanticIntakeResult:
    adapter = proposer or DeterministicFallbackSemanticIntakeProposer()
    fallback_reason: dict[str, Any] = {}
    try:
        result = adapter.propose(text, prepared_clauses=prepared_clauses)
    except Exception as exc:
        fallback_reason = {
            "primary_proposer": getattr(adapter, "proposer_name", type(adapter).__name__),
            "primary_proposer_error_type": type(exc).__name__,
            "primary_proposer_error": str(exc)[:500],
        }
        result = DeterministicFallbackSemanticIntakeProposer().propose(
            text,
            prepared_clauses=prepared_clauses,
        )
    return result.model_copy(
        update={
            "diagnostics": {
                **dict(result.diagnostics),
                **fallback_reason,
                "compiler_authority": "deterministic",
                "raw_llm_output_executes_tools": False,
                "active_executable_roles": ["required_requirement"],
            }
        },
        deep=True,
    )


def _semantic_item(
    existing: list[SemanticIntakeItem],
    *,
    role: RequirementClauseRole,
    text: str,
    parent_item_id: str | None = None,
    condition: dict[str, Any] | None = None,
    child_intent: dict[str, Any] | None = None,
    applies_to_item_ids: list[str] | None = None,
    reason: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> SemanticIntakeItem:
    return SemanticIntakeItem(
        id=f"intake-{len(existing) + 1:03d}",
        role=role,
        text=text.strip(),
        parent_item_id=parent_item_id,
        condition=dict(condition or {}),
        child_intent=dict(child_intent or {}),
        applies_to_item_ids=list(applies_to_item_ids or []),
        reason=reason,
        diagnostics=dict(diagnostics or {}),
    )


def _conditional_item_payload(
    clause: str,
    *,
    parent_item_id: str | None,
) -> dict[str, Any] | None:
    if not re.search(r"\b(?:if|when|whenever|for\s+(?:each|every))\b", clause, re.IGNORECASE):
        return None
    referent_entity = _conditional_referent_entity(clause)
    if not referent_entity:
        return None
    fan_out = (
        "all_unique_values"
        if re.search(r"\bfor\s+(?:each|every)\b", clause, re.IGNORECASE)
        else "first_value"
    )
    field_any = [f"{referent_entity}_id", f"active_{referent_entity}_id"]
    return {
        "condition": {
            "type": "active_parent_evidence_has_any_field",
            "field_any": field_any,
            "source": "active_parent_evidence",
        },
        "child_intent": {
            "action": "read_one",
            "entity": referent_entity,
            "referent": f"that {referent_entity}",
            "constraint_field": f"{referent_entity}_id",
            "value_from_field_any": field_any,
            "fan_out": fan_out,
        },
        "diagnostics": {
            "parent_item_id": parent_item_id,
            "dependent_singular_read": fan_out != "all_unique_values",
            "fan_out": fan_out,
        },
    }


def _conditional_referent_entity(clause: str) -> str | None:
    patterns = [
        r"\b(?:includes?|has|contains)\s+(?:a|an|the)?\s*(?P<entity>[a-z][a-z0-9_-]*)\s+id\b.+?\bread\s+that\s+(?P=entity)\b",
        r"\b(?:includes?|has|contains)\s+(?:a|an|the)?\s*(?P<entity>[a-z][a-z0-9_-]*)\b.+?\bread\s+that\s+(?P=entity)\b",
        r"\bread\s+that\s+(?P<entity>[a-z][a-z0-9_-]*)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, clause, re.IGNORECASE | re.DOTALL)
        if match:
            entity = _normalize_entity(match.group("entity"))
            if entity not in {"id", "it", "that", "this", "the"}:
                return entity
    return None


def _split_formatting_suffix(clause: str) -> tuple[str, str]:
    match = re.search(
        r"\s+(?P<format>(?:in|as)\s+(?:a\s+)?(?:short\s+|brief\s+|compact\s+)?"
        r"(?:table|bullet\s+list|bullets|list))\.?\s*$",
        clause,
        re.IGNORECASE,
    )
    if not match:
        return clause, clause
    required = clause[: match.start()].rstrip(" ,.;")
    formatting = match.group("format").strip()
    if not required:
        return clause, clause
    return required, formatting if formatting.endswith(".") else f"{formatting}."


def _is_answer_instruction(clause: str, *, frame: Any, has_context: bool) -> bool:
    if not has_context:
        return False
    if _has_hard_entity(frame) or _looks_like_document_question(clause):
        return False
    return bool(
        re.search(
            r"^\s*(?:summari[sz]e|explain|describe)\b|\b(?:what\s+it\s+means|cause|reason|why)\b",
            clause,
            re.IGNORECASE,
        )
    )


def _formatting_instruction_reason(clause: str, *, frame: Any) -> str | None:
    if _has_hard_entity(frame):
        return None
    normalized = _normalize_space(clause)
    if re.fullmatch(
        r"(?:briefly|short answer|concise|one sentence|bullet points?|"
        r"(?:in|as)\s+(?:a\s+)?(?:short\s+|brief\s+|compact\s+)?(?:table|bullet\s+list|bullets|list))\.?",
        normalized,
        re.IGNORECASE,
    ):
        return "formatting_instruction"
    return None


def _clarification_need_payload(clause: str, *, frame: Any) -> dict[str, str] | None:
    if _has_hard_entity(frame):
        return None
    match = re.search(
        r"\b(?:read|show|check|get|look\s+up)\s+(?:that|this|it|the)\s+"
        r"(?P<entity>[a-z][a-z0-9_-]*)?\b",
        clause,
        re.IGNORECASE,
    )
    if not match:
        return None
    entity = _normalize_entity(match.group("entity") or "")
    return {
        "reason": "dependent_singular_read_missing_bound_entity",
        "entity": entity or "unknown",
    }


def _is_mutation_or_approval_request(clause: str, *, frame: Any) -> bool:
    action = str(getattr(frame, "action", "") or "")
    route = str(getattr(frame, "route", "") or "")
    if bool(getattr(frame, "requires_approval", False)):
        return True
    if action in {"create", "update", "delete"} or route == "approval_action":
        return True
    return bool(re.search(r"\b(?:approve|approval|change|update|create|delete|cancel)\b", clause, re.IGNORECASE))


def _has_hard_entity(frame: Any) -> bool:
    normalized_entities = getattr(frame, "normalized_entities", {}) or {}
    return any(values for values in normalized_entities.values())


def _looks_like_document_question(clause: str) -> bool:
    return bool(
        re.search(
            r"\b(?:loto|lock\s*out|tag\s*out|lockout|tagout|procedure|sop|policy|"
            r"safety|ppe|osha|manual|standard|guidance|instructions?|hazard)\b",
            clause,
            re.IGNORECASE,
        )
    )


def _role_counts(items: list[SemanticIntakeItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.role] = counts.get(item.role, 0) + 1
    return counts


def _build_semantic_intake_prompt(text: str, *, prepared_clauses: list[str] | None) -> str:
    effective_clauses = prepared_clauses
    if effective_clauses is None:
        effective_clauses = [item.description for item in split_user_intents(text)]
    payload = {"clauses": effective_clauses}
    return (
        "You are only a clause labeler. Do not answer the factory request. "
        'Input clauses are already split; return one JSON object {"items":[...]} with one item per clause, same order. '
        "Each item: id, role, text, parent_item_id, condition, child_intent, applies_to_item_ids, reason, diagnostics. "
        "Use {} for condition/child_intent/diagnostics and [] for applies_to_item_ids when empty. "
        "Roles: read/show/check/get/list/status with an entity or id => required_requirement. "
        "if/when clause that says read that/this/the referenced entity => conditional_branch. "
        "explain/summarize/what it means/cause/reason only => answer_instruction. "
        "table/bullets/brief only => formatting_instruction. "
        "change/update/delete/cancel/approve => mutation_or_approval_request. "
        'For conditional_branch set condition.field_any to ["<entity>_id","active_<entity>_id"] and child_intent.entity. '
        "No tool names. "
        f"{json.dumps(payload, ensure_ascii=True)}"
    )


def _normalize_llm_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        payload["id"] = str(payload.get("id") or f"intake-{index:03d}")
        payload["role"] = _normalize_llm_role(payload.get("role"), text=str(payload.get("text") or ""))
        payload["text"] = str(payload.get("text") or payload.get("description") or payload["role"]).strip()
        if payload["role"] == "required_requirement":
            clarification = _clarification_need_payload(
                payload["text"],
                frame=semantic_frame_for_text(payload["text"]),
            )
            if clarification is not None:
                payload["role"] = "clarification_need"
                payload["reason"] = clarification["reason"]
                payload["diagnostics"] = {"blocked_entity": clarification.get("entity")}
        recovered_answer_text = None
        if payload["role"] != "answer_instruction":
            recovered_answer_text = _answer_instruction_text_from_value(payload.get("child_intent"))
            recovered_answer_text = recovered_answer_text or _answer_instruction_text_from_value(payload.get("reason"))
            recovered_answer_text = recovered_answer_text or _answer_instruction_text_from_value(payload["text"])
        if not isinstance(payload.get("condition"), dict):
            payload["condition"] = {}
        if not isinstance(payload.get("child_intent"), dict):
            payload["child_intent"] = {}
        if not isinstance(payload.get("applies_to_item_ids"), list):
            payload["applies_to_item_ids"] = []
        else:
            payload["applies_to_item_ids"] = [str(item_id) for item_id in payload["applies_to_item_ids"] if item_id]
        if not isinstance(payload.get("diagnostics"), dict):
            payload["diagnostics"] = {}
        required_text, formatting_text = _split_formatting_suffix(payload["text"])
        if payload["role"] == "required_requirement" and required_text != payload["text"]:
            payload["text"] = required_text
            normalized.append(payload)
            normalized.append(
                {
                    "id": f"{payload['id']}.format",
                    "role": "formatting_instruction",
                    "text": formatting_text,
                    "parent_item_id": payload["id"],
                    "condition": {},
                    "child_intent": {},
                    "applies_to_item_ids": [payload["id"]],
                    "reason": "formatting_instruction",
                    "diagnostics": {},
                }
            )
        else:
            normalized.append(payload)
        if recovered_answer_text:
            normalized.append(
                {
                    "id": f"{payload['id']}.answer",
                    "role": "answer_instruction",
                    "text": recovered_answer_text,
                    "parent_item_id": payload["id"],
                    "condition": {},
                    "child_intent": {},
                    "applies_to_item_ids": [payload["id"]],
                    "reason": "answer_composition_instruction",
                    "diagnostics": {},
                }
            )
    return normalized


def _answer_instruction_text_from_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _normalize_space(value).strip(" .")
    match = re.search(
        r"\b(?P<answer>(?:and\s+)?(?:summari[sz]e|explain|describe)\b.+)$",
        normalized,
        re.IGNORECASE,
    )
    if not match and re.search(r"\b(?:what\s+it\s+means|cause|reason)\b", normalized, re.IGNORECASE):
        match = re.search(r"(?P<answer>.+)$", normalized, re.IGNORECASE)
    if not match:
        return None
    answer = re.sub(r"^\s*and\s+", "", match.group("answer").strip(), flags=re.IGNORECASE)
    return answer if answer.endswith(".") else f"{answer}."


def _normalize_llm_role(value: Any, *, text: str) -> RequirementClauseRole:
    raw = _normalize_space(str(value or "")).lower()
    text_normalized = _normalize_space(text).lower()
    haystack = f"{raw} {text_normalized}"
    allowed: set[RequirementClauseRole] = {
        "required_requirement",
        "conditional_branch",
        "answer_instruction",
        "formatting_instruction",
        "clarification_need",
        "mutation_or_approval_request",
    }
    if raw in allowed:
        return raw  # type: ignore[return-value]
    if re.search(r"\b(?:conditional|if|when|whenever)\b", haystack):
        return "conditional_branch"
    if re.search(r"\b(?:change|update|delete|cancel|approve|approval|mutat(?:e|ion))\b", haystack):
        return "mutation_or_approval_request"
    if re.search(r"\b(?:summari[sz]e|explain|answer|cause|reason|what\s+it\s+means)\b", haystack):
        return "answer_instruction"
    if re.search(r"\b(?:read|show|check|get|lookup|look\s+up|status|list)\b", haystack):
        return "required_requirement"
    if re.search(r"\b(?:format|table|bullet|brief|concise|list)\b", raw):
        return "formatting_instruction"
    return "clarification_need"


def _llm_items_payload(parsed: dict[str, Any]) -> Any:
    items = parsed.get("items") or parsed.get("roles")
    if items is not None:
        return items
    if parsed.get("role") and (parsed.get("text") or parsed.get("description")):
        return [parsed]
    return []


def _message_content_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if value:
                    parts.append(str(value))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_entity(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


__all__ = [
    "DeterministicFallbackSemanticIntakeProposer",
    "OpenAICompatibleSemanticIntakeProposer",
    "SemanticIntakeItem",
    "SemanticIntakeProposer",
    "SemanticIntakeResult",
    "StaticSemanticIntakeProposer",
    "build_semantic_intake_proposer",
    "propose_semantic_intake_for_text",
]
