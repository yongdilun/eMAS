from __future__ import annotations

import json
import re
import time
from typing import Any, Literal, Protocol

from pydantic import Field, ValidationError

from ..config import Settings
from ..llm.models import build_planner_chat_model
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
        prompt = _build_semantic_intake_prompt(text, prepared_clauses=prepared_clauses)
        model = self._model or build_planner_chat_model(self._settings, json_mode=True)
        started = time.perf_counter()
        log_event(
            "semantic_intake_proposer_llm_start",
            adapter=self.proposer_name,
            model_name=self._settings.planner_model,
            prompt_chars=len(prompt),
            prepared_clause_count=len(prepared_clauses or []),
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
                    "items": parsed.get("items") or parsed.get("roles") or [],
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
            model_name=self._settings.planner_model,
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
    payload = {
        "user_query": text,
        "deterministic_clauses": prepared_clauses or [],
        "allowed_roles": [
            "required_requirement",
            "conditional_branch",
            "answer_instruction",
            "formatting_instruction",
            "clarification_need",
            "mutation_or_approval_request",
        ],
    }
    return (
        "Classify the user's factory-agent request into semantic intake items. "
        "Return JSON only with an items array. Each item needs id, role, text, and optional "
        "parent_item_id, condition, child_intent, applies_to_item_ids, reason, diagnostics. "
        "Conditional branches must stay non-executable and should describe the evidence fields "
        "needed before a child read can activate. Answer and formatting instructions must not "
        "request tools. Do not include tool names.\n\n"
        f"{json.dumps(payload, ensure_ascii=True)}"
    )


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
