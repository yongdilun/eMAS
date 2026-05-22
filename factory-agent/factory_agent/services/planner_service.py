from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..registry.tool_registry import ToolRegistry
from ..schemas import PlanDraft, PlanStepDraft, ToolInfo

PlannerBackendName = str


class PlannerBackendError(RuntimeError):
    """Transient or infrastructure planner failure - maps to HTTP 503."""

    pass


class PlannerPlanRejected(RuntimeError):
    """Planner produced no valid plan (validation, JSON, graph outcome) - maps to HTTP 400."""

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


class PlannerApprovalRequired(PlannerBackendError):
    def __init__(self, message: str, *, approval: dict[str, Any]):
        self.approval = approval
        super().__init__(message)


@dataclass(frozen=True)
class PlannerResult:
    draft: PlanDraft
    backend_used: PlannerBackendName
    llm_calls: int = 0
    intent_contract: dict[str, Any] | None = None
    tool_outputs: list[dict[str, Any]] | None = None


def _assign_parallel_groups(
    steps: list[PlanStepDraft],
    tools_by_name: dict[str, ToolInfo],
    *,
    enabled: bool,
) -> list[list[int]]:
    if not enabled:
        return []
    independent_read_steps: list[int] = []
    for step in steps:
        tool = tools_by_name.get(step.tool_name)
        if not tool or not tool.is_read_only:
            continue
        if step.depends_on:
            continue
        if step.bindings:
            continue
        independent_read_steps.append(step.step_index)
    return [independent_read_steps] if len(independent_read_steps) > 1 else []


def _dedupe_plan_steps(draft: PlanDraft) -> tuple[PlanDraft, int]:
    def _freeze(value: Any) -> Any:
        if isinstance(value, dict):
            return tuple(sorted((str(key), _freeze(val)) for key, val in value.items()))
        if isinstance(value, list):
            return tuple(_freeze(item) for item in value)
        if isinstance(value, set):
            return tuple(sorted(_freeze(item) for item in value))
        return value

    seen: set[tuple[str, Any]] = set()
    new_steps: list[PlanStepDraft] = []
    dropped = 0
    for step in draft.steps:
        key = (step.tool_name, _freeze(step.args or {}))
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        new_steps.append(
            step.model_copy(
                update={
                    "step_index": len(new_steps),
                    "depends_on": [len(new_steps) - 1] if new_steps else [],
                }
            )
        )
    if dropped == 0:
        return draft, 0
    return (
        draft.model_copy(
            update={
                "steps": new_steps,
                "parallel_groups": None,
            }
        ),
        dropped,
    )


_ACTION_VERB_RE = re.compile(
    r"\b(?:check|show|list|get|find|view|inspect|update|set|create|delete|approve|reject|replan|assign|schedule|replenish|move|run)\b",
    re.IGNORECASE,
)

_CONNECTOR_SPLIT_RE = re.compile(
    r"(?:^|\s+)(?:"
    r"\b(?:and then|after that|afterwards|but first|before that|once done|when done|finally)\b"
    r"|\b(?:then|next)\b"
    r")\s+",
    re.IGNORECASE,
)

_PERIOD_SENTENCE_RE = re.compile(r"(?<!\d)\.\s+(?=[A-Za-z])")


def _finalize_clause(text: str) -> str:
    return text.strip().rstrip(".")


def _merge_final(parts: list[str]) -> list[str]:
    out = [_finalize_clause(p) for p in parts if p.strip()]
    return out if out else [""]


def _try_numbered_steps(normalized: str) -> list[str] | None:
    if not re.search(r"(?:^|\s)\d+[.)]\s+\S", normalized):
        return None
    raw = re.split(r"\s+(?=\d+[.)]\s)", normalized)
    out: list[str] = []
    for segment in raw:
        stripped = re.sub(r"^\d+[.)]\s*", "", segment).strip()
        if stripped:
            out.append(stripped)
    return out if len(out) >= 2 else None


def _split_compound_intent(intent: str) -> list[str]:
    raw = (intent or "").strip()
    if not raw:
        return [""]

    structural = [p.strip() for p in re.split(r"[;\n]+", raw) if p.strip()]
    if len(structural) > 1:
        merged: list[str] = []
        for part in structural:
            merged.extend(_split_compound_intent(part))
        return _merge_final(merged)

    normalized = re.sub(r"\s+", " ", raw)

    numbered = _try_numbered_steps(normalized)
    if numbered:
        return _merge_final(numbered)

    text = normalized

    conn_parts = [p.strip() for p in _CONNECTOR_SPLIT_RE.split(text) if p.strip()]
    if len(conn_parts) > 1:
        merged = []
        for part in conn_parts:
            merged.extend(_split_compound_intent(part))
        return _merge_final(merged)

    period_parts = [p.strip() for p in _PERIOD_SENTENCE_RE.split(text) if p.strip()]
    if len(period_parts) > 1:
        merged = []
        for part in period_parts:
            merged.extend(_split_compound_intent(part))
        return _merge_final(merged)

    comma_parts = [p.strip() for p in text.split(",")]
    if len(comma_parts) >= 2 and all(_ACTION_VERB_RE.search(p) for p in comma_parts):
        return _merge_final(comma_parts)

    if re.search(r"\s+(?:and|also)\s+", text, re.IGNORECASE):
        aparts = [p.strip() for p in re.split(r"\s+(?:and|also)\s+", text, flags=re.IGNORECASE) if p.strip()]
        if len(aparts) > 1 and sum(1 for p in aparts if _ACTION_VERB_RE.search(p)) >= 2:
            merged = []
            for part in aparts:
                merged.extend(_split_compound_intent(part))
            return _merge_final(merged)

    return [_finalize_clause(text)]


class PlannerService:
    """Retired planner adapter placeholder for default route wiring.

    Normal runtime is owned by PlanCreationService and PlannerOwnedAgentGraph.
    Seeded test adapters are injected explicitly and handled by
    plan_creation_compatibility.py; this service no longer exposes the old
    graph generate/resume boundary.
    """

    def __init__(self, *, settings: Settings, tool_registry: ToolRegistry):
        self._settings = settings
        self._tool_registry = tool_registry

    def handles_seeded_intent(self, intent: str) -> bool:
        del intent
        return False
