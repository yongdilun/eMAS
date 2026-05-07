from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .config import Settings
from .guardrails import promote_user_provenance, strip_unsupported_optional_args
from .schemas import PlanDraft, PlanStepDraft, ToolInfo
from .telemetry import log_event
from .tool_registry import ToolRegistry


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


def _split_compound_intent(intent: str) -> list[str]:
    normalized = (intent or "").strip()
    return [normalized] if normalized else []


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


class LangGraphPlannerBackend:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        tools_markdown: str = "",
    ) -> PlannerResult:
        del tools_markdown
        try:
            from .graph.planner_graph import LangGraphPlanner, LangGraphPlannerClarification
        except Exception as exc:
            raise PlannerBackendError("LangGraph planner backend unavailable.") from exc

        try:
            draft, contract = await LangGraphPlanner(self._settings).generate(
                intent=intent,
                scoped_tools=scoped_tools,
                context=context,
            )
        except LangGraphPlannerClarification as exc:
            raise PlannerClarificationError(str(exc)) from exc
        except Exception as exc:
            raise PlannerBackendError(str(exc)) from exc
        return PlannerResult(draft=draft, backend_used="langgraph", llm_calls=1, intent_contract=contract)


class LegacyPlannerBackend:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        tools_markdown: str = "",
    ) -> PlannerResult:
        del intent, scoped_tools, context, tools_markdown
        raise PlannerBackendError("Legacy planner backend is disabled; use langgraph.")


class LangChainPlannerBackend:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        tools_markdown: str = "",
    ) -> PlannerResult:
        del intent, scoped_tools, context, tools_markdown
        raise PlannerBackendError("LangChain planner backend is disabled; use langgraph.")


class StructuredPlannerBackend:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        tools_markdown: str = "",
    ) -> PlannerResult:
        del intent, scoped_tools, context, tools_markdown
        raise PlannerBackendError("Structured planner backend is disabled; use langgraph.")


class PlannerAdapter:
    def __init__(self, *, settings: Settings, tool_registry: ToolRegistry):
        self._settings = settings
        self._tool_registry = tool_registry
        self._langgraph = LangGraphPlannerBackend(settings)

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        force_backend: PlannerBackendName | None = None,
    ) -> PlannerResult:
        runtime = (getattr(self._settings, "agent_runtime", "langgraph_agent") or "langgraph_agent").strip().lower()
        configured_backend = (self._settings.planner_backend or "langgraph").strip().lower()
        backend = (force_backend or ("langgraph" if runtime == "langgraph_agent" else configured_backend)).strip().lower()
        self._tool_registry.load_tools_markdown()

        if backend != "langgraph":
            raise PlannerBackendError(f"Unsupported planner backend: {backend}. Only langgraph is enabled.")

        result = await self._langgraph.generate_plan(
            intent=intent,
            scoped_tools=scoped_tools,
            context=context,
        )

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
