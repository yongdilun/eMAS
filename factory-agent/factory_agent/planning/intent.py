from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Sequence
from uuid import uuid4

from ..schemas import ExplicitConstraint, Intent, IntentCategory

IntentKind = Literal["conversation", "unsupported", "operations"]
IntentAction = Literal["create", "update", "approval", "read", "delete"] | None

_GREETING_RE = re.compile(
    r"^\s*(?:hi|hello|hey|yo|good morning|good afternoon|good evening|thanks|thank you)\b",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"\b(?:what|how|why|when|where|which|who|meaning|definition|describe|explain|functions|framework|standard|policy|procedure|sop|loto|csf|ppe)\b",
    re.IGNORECASE,
)
_CLAUSE_SPLIT_RE = re.compile(
    r"\s+\band\s+|\s+;\s*|\n+|(?<=[.!?])\s+(?=[A-Z])|\b(?:and then|then|next|after that|afterwards|finally)\b",
    re.IGNORECASE,
)
_MACHINE_ID_RE = re.compile(r"\b([A-Z]{1,3}-\d{2,})\b")
_JOB_TOKEN_RE = re.compile(
    r"\bjob\s*(?:id|#)?\s*([A-Z0-9][A-Z0-9-]{0,15}|\d{2,})\b",
    re.IGNORECASE,
)
_USE_MACHINE_RE = re.compile(
    r"\b(?:use|with|for)\s+(?:machine\s+)?([A-Z]{1,3}-\d{2,})\b",
    re.IGNORECASE,
)
_MACHINE_NAME_RE = re.compile(r"\bmachine\s+([A-Z0-9][A-Z0-9-]*)\b", re.IGNORECASE)
_PRODUCT_RE = re.compile(r"\bproduct\s+([A-Z0-9][A-Z0-9-]*)\b", re.IGNORECASE)

_ACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("approval", re.compile(r"\b(?:approve|reject|approval|approvals|pending approval|pending approvals)\b", re.IGNORECASE)),
    ("create", re.compile(r"\b(?:create|new|add|open)\b", re.IGNORECASE)),
    ("update", re.compile(r"\b(?:update|set|change|assign|record|apply|run|reschedule|move|schedule)\b", re.IGNORECASE)),
    ("delete", re.compile(r"\b(?:delete|remove)\b", re.IGNORECASE)),
    (
        "read",
        re.compile(
            r"\b(?:assist|candidate|check|delay|describe|explain|explosion|forecast|get|find|inspect|list|lookup|preview|rank|read|readiness|report|reports|risk|show|shortage|slots?|status|suggestion|timeout|view|available)\b",
            re.IGNORECASE,
        ),
    ),
]

_SCHEDULING_HINT = re.compile(
    r"\b(?:schedule|scheduling|assign|book|slot|calendar|dispatch)\b",
    re.IGNORECASE,
)
_INVENTORY_HINT = re.compile(r"\b(?:inventory|stock|parts?|shortage|warehouse|sku)\b", re.IGNORECASE)
_MACHINE_HINT = re.compile(
    r"\b(?:machine|machines|cnc|equipment|line|station|unit|oee|availability|available)\b",
    re.IGNORECASE,
)
_JOB_HINT = re.compile(r"\b(?:job|work\s*order|wo\b)\b", re.IGNORECASE)
_REPORT_HINT = re.compile(r"\b(?:report|export|csv|pdf|dashboard)\b", re.IGNORECASE)


@dataclass(frozen=True)
class IntentAssessment:
    kind: IntentKind
    action: IntentAction
    entity: str | None
    confidence: float
    reply: str | None = None


def _intent_id(idx: int) -> str:
    return f"intent-{idx:03d}-{uuid4().hex[:8]}"


def _split_clauses(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = [p.strip(" \t,;") for p in _CLAUSE_SPLIT_RE.split(raw) if p and p.strip(" \t,;")]
    return parts or [raw]


def _extract_constraints(clause: str) -> list[ExplicitConstraint]:
    out: list[ExplicitConstraint] = []
    for m in _MACHINE_ID_RE.finditer(clause):
        out.append(
            ExplicitConstraint(
                field="machine_id",
                operator="=",
                value=m.group(1).upper(),
                source_text=m.group(0),
                strength="hard",
                mutable=False,
            )
        )
    for m in _USE_MACHINE_RE.finditer(clause):
        out.append(
            ExplicitConstraint(
                field="machine_id",
                operator="=",
                value=m.group(1).upper(),
                source_text=m.group(0),
                strength="hard",
                mutable=False,
            )
        )
    for m in _MACHINE_NAME_RE.finditer(clause):
        if not re.match(r"^[A-Z]-?\d", m.group(1), re.I):
            out.append(
                ExplicitConstraint(
                    field="machine_ref",
                    operator="=",
                    value=m.group(1),
                    source_text=m.group(0),
                    strength="hard",
                    mutable=False,
                )
            )
    for m in _JOB_TOKEN_RE.finditer(clause):
        out.append(
            ExplicitConstraint(
                field="job_id",
                operator="=",
                value=str(m.group(1)).upper() if m.group(1) else m.group(0),
                source_text=m.group(0),
                strength="hard",
                mutable=False,
            )
        )
    for m in _PRODUCT_RE.finditer(clause):
        out.append(
            ExplicitConstraint(
                field="product_id",
                operator="=",
                value=m.group(1).upper(),
                source_text=m.group(0),
                strength="hard",
                mutable=False,
            )
        )
    # De-dupe identical field+value
    seen: set[tuple[str, str]] = set()
    deduped: list[ExplicitConstraint] = []
    for c in out:
        key = (c.field, json.dumps(c.value, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


def _classify_clause(clause: str) -> IntentCategory:
    if not clause.strip():
        return "unknown"
    if _REPORT_HINT.search(clause):
        return "reporting"
    if _SCHEDULING_HINT.search(clause) or _JOB_HINT.search(clause):
        if _SCHEDULING_HINT.search(clause):
            return "scheduling"
        if re.search(r"\b(?:create|new|add|schedule|assign)\b", clause, re.I):
            return "scheduling"
        return "job"
    if _INVENTORY_HINT.search(clause):
        return "inventory"
    if _MACHINE_HINT.search(clause):
        return "machine"
    if _QUESTION_RE.search(clause) and not _JOB_HINT.search(clause) and not _MACHINE_HINT.search(clause):
        return "general"
    return "unknown"


def _infer_depends_on(intents: list[Intent]) -> list[Intent]:
    """Order-based heuristic: scheduling/job actions may depend on prior discovery intents."""
    out: list[Intent] = []
    for i, it in enumerate(intents):
        deps = list(it.depends_on)
        if i > 0 and it.category in ("scheduling", "job"):
            prev = intents[i - 1]
            prev_desc = prev.description.lower()
            if prev.category in ("machine", "inventory") and any(
                w in prev_desc for w in ("find", "list", "show", "available", "lookup", "search")
            ):
                if prev.intent_id not in deps:
                    deps.append(prev.intent_id)
        out.append(it.model_copy(update={"depends_on": deps}))
    return out


def split_user_intents(query: str, *, llm: Any | None = None) -> list[Intent]:
    """
    Dumb intent splitter (Phase 2): extracts structured intents without tool execution
    or completeness checks. Rule-based by default; optional LLM JSON path when ``llm`` is set.
    """
    del llm  # Reserved for Phase 2+ LLM-backed split; wire in planner settings when ready.
    raw = (query or "").strip()
    if not raw:
        return [
            Intent(
                intent_id=_intent_id(0),
                description="(empty user request)",
                category="unknown",
            )
        ]

    clauses = _split_clauses(raw)
    intents: list[Intent] = []
    for idx, clause in enumerate(clauses):
        if not clause:
            continue
        cat = _classify_clause(clause)
        intents.append(
            Intent(
                intent_id=_intent_id(idx),
                description=clause.strip(),
                explicit_constraints=_extract_constraints(clause),
                category=cat,
            )
        )

    if not intents:
        return [
            Intent(
                intent_id=_intent_id(0),
                description=raw,
                explicit_constraints=_extract_constraints(raw),
                category=_classify_clause(raw),
            )
        ]

    return _infer_depends_on(intents)


def assess_intent(text: str) -> IntentAssessment:
    """
    Legacy API for tool scoping and API gating. Delegates to :func:`split_user_intents`
    instead of standalone regex classification (Phase 2).
    """
    raw = (text or "").strip()
    lower = raw.lower()
    if not raw:
        return IntentAssessment(
            kind="conversation",
            action=None,
            entity=None,
            confidence=0.99,
            reply="Hi - tell me what factory operations request you want to run, and I will map it to the available tools.",
        )

    if _GREETING_RE.search(raw):
        return IntentAssessment(
            kind="conversation",
            action=None,
            entity=None,
            confidence=0.98,
            reply="Hi - tell me what factory operations request you want to run, and I will map it to the available tools.",
        )

    intents = split_user_intents(raw)
    if len(intents) == 1 and intents[0].category == "unknown" and len(lower.split()) <= 3 and not _QUESTION_RE.search(raw):
        return IntentAssessment(
            kind="conversation",
            action=None,
            entity=None,
            confidence=0.7,
            reply="Tell me the factory operations request you want to run, including the resource and any identifier or filter.",
        )

    matched_actions: set[str] = {c for c, p in _ACTION_PATTERNS if p.search(raw)}
    action: IntentAction = None
    if matched_actions:
        if {"create", "update", "delete"} & matched_actions:
            for candidate in ("create", "update", "delete", "read"):
                if candidate in matched_actions:
                    action = candidate  # type: ignore[assignment]
                    break
        else:
            for candidate in ("approval", "read"):
                if candidate in matched_actions:
                    action = candidate  # type: ignore[assignment]
                    break

    entity: str | None = None
    lower_raw = raw.lower()
    if re.search(r"\bjob\b", lower_raw):
        entity = "job"
    elif re.search(r"\bproduct\b", lower_raw):
        entity = "product"
    elif _MACHINE_HINT.search(raw):
        entity = "machine"
    elif _INVENTORY_HINT.search(raw):
        entity = "inventory"
    else:
        for it in intents:
            for c in it.explicit_constraints:
                if c.field == "job_id":
                    entity = "job"
                    break
                if c.field == "product_id":
                    entity = "product"
                    break
                if c.field in ("machine_id", "machine_ref"):
                    entity = "machine"
                    break
            if entity:
                break

    if action or entity or _QUESTION_RE.search(raw) or any(it.category != "unknown" for it in intents):
        confidence = 0.92 if (action and entity) else 0.78
        return IntentAssessment(kind="operations", action=action, entity=entity, confidence=confidence, reply=None)

    token_count = len([tok for tok in re.split(r"\s+", lower) if tok])
    if token_count <= 4:
        return IntentAssessment(
            kind="conversation",
            action=None,
            entity=None,
            confidence=0.7,
            reply="Tell me the factory operations request you want to run, including the resource and any identifier or filter.",
        )

    return IntentAssessment(
        kind="operations",
        action=None,
        entity=entity,
        confidence=0.55,
        reply=None,
    )


def intents_to_state_payload(intents: Sequence[Intent]) -> list[dict[str, Any]]:
    """Serialize intents for ``AgentState['intents']`` (append reducer)."""
    return [i.model_dump(mode="json") for i in intents]
