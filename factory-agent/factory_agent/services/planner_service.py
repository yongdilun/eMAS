from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from ..config import Settings
from ..security.guardrails import promote_user_provenance, strip_unsupported_optional_args
from ..schemas import PlanDraft, PlanStepDraft, ToolInfo
from ..observability.telemetry import log_event
from ..registry.tool_registry import ToolRegistry

PlannerBackendName = Literal["langgraph"]


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
    seen: set[tuple[str, tuple[tuple[str, Any], ...]]] = set()
    new_steps: list[PlanStepDraft] = []
    dropped = 0
    for step in draft.steps:
        key = (step.tool_name, tuple(sorted((step.args or {}).items())))
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


def _lookup_contract_clause(
    *,
    intent_contract: dict[str, Any] | None,
    step_index: int,
    tool_name: str,
) -> dict[str, Any] | None:
    if not isinstance(intent_contract, dict):
        return None
    steps = intent_contract.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("step_index") == step_index and step.get("tool_name") == tool_name:
            return step
    return None


def _mark_contract_fields_stripped(
    *,
    intent_contract: dict[str, Any] | None,
    step_index: int,
    tool_name: str,
    dropped_fields: list[str],
) -> None:
    clause = _lookup_contract_clause(intent_contract=intent_contract, step_index=step_index, tool_name=tool_name)
    if not isinstance(clause, dict):
        return
    existing = clause.get("provenance_dropped")
    provenance_dropped = list(existing) if isinstance(existing, list) else []
    provenance_dropped.extend(dropped_fields)
    clause["provenance_dropped"] = sorted(set(str(field) for field in provenance_dropped if str(field)))


class PlannerService:
    """LangGraph-backed planning with post-processing (dedupe, provenance gates)."""

    _langgraph_planner_cls: ClassVar[type | None] = None

    def __init__(self, *, settings: Settings, tool_registry: ToolRegistry):
        self._settings = settings
        self._tool_registry = tool_registry

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
    ) -> PlannerResult:
        from ..graph.errors import LangGraphPlannerClarification

        planner_cls = PlannerService._langgraph_planner_cls
        if planner_cls is None:
            try:
                from ..graph.planner_graph import LangGraphPlanner as planner_cls  # noqa: PLC0415 â€” optional heavy deps
            except Exception as exc:
                raise PlannerBackendError("LangGraph planner unavailable.") from exc

        self._tool_registry.load_tools_markdown()

        try:
            draft, contract = await planner_cls(self._settings).generate(
                intent=intent,
                scoped_tools=scoped_tools,
                context=context,
            )
        except LangGraphPlannerClarification as exc:
            raise PlannerClarificationError(str(exc)) from exc
        except PlannerConfirmationRequired:
            raise
        except Exception as exc:
            raise PlannerBackendError(str(exc)) from exc

        result = PlannerResult(draft=draft, backend_used="langgraph", llm_calls=1, intent_contract=contract)

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

        tools_by_name = {t.name: t for t in scoped_tools}
        intent_memory = context if isinstance(context, dict) else {}
        for step in result.draft.steps:
            tool = tools_by_name.get(step.tool_name)
            if not tool:
                continue
            clause = _lookup_contract_clause(
                intent_contract=result.intent_contract,
                step_index=step.step_index,
                tool_name=tool.name,
            )
            arg_provenance = clause.get("arg_provenance") if isinstance(clause, dict) and isinstance(clause.get("arg_provenance"), dict) else None
            evidence = clause.get("evidence") if isinstance(clause, dict) and isinstance(clause.get("evidence"), dict) else {}
            arg_provenance = promote_user_provenance(
                tool=tool,
                args=step.args or {},
                intent=intent,
                evidence=evidence,
                arg_provenance=arg_provenance,
            )
            if isinstance(clause, dict):
                clause["arg_provenance"] = arg_provenance

            clean_args, dropped = strip_unsupported_optional_args(
                tool=tool,
                args=step.args or {},
                intent=intent,
                intent_memory=intent_memory if isinstance(intent_memory, dict) else {},
                arg_provenance=arg_provenance,
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


