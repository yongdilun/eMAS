from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Literal

from .config import Settings
from .plan_validator import validate_plan
from .prompting import build_planner_prompt
from .schemas import PlanDraft, PlanStepDraft, ToolInfo
from .tool_registry import ToolRegistry


PlannerBackendName = Literal["legacy", "langchain"]


class PlannerBackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlannerResult:
    draft: PlanDraft
    backend_used: PlannerBackendName
    llm_calls: int = 0


def _default_value_for_json_type(json_type: str) -> Any:
    if json_type == "string":
        return "sample"
    if json_type == "integer":
        return 1
    if json_type == "number":
        return 1.0
    if json_type == "boolean":
        return False
    if json_type == "array":
        return []
    return {}


def _default_args_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    out: dict[str, Any] = {}
    for field in required:
        raw = properties.get(field, {})
        field_type = raw.get("type")
        if isinstance(field_type, list):
            field_type = next((t for t in field_type if t != "null"), "string")
        out[field] = _default_value_for_json_type(field_type or "string")
    return out


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
    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
        tools_markdown: str = "",
    ) -> PlannerResult:
        del context, tools_markdown
        if not scoped_tools:
            raise PlannerBackendError("No scoped tools available to generate a plan.")

        # Keep legacy deterministic behavior: one read-first step, custom validator remains the safety gate.
        sorted_tools = sorted(scoped_tools, key=lambda t: (not t.is_read_only, t.name))
        selected = sorted_tools[0]
        args = _default_args_from_schema(selected.input_schema or {})

        draft = PlanDraft(
            plan_explanation=f"Use `{selected.name}` to address intent: {intent.strip() or 'user request'}.",
            risk_summary=(
                "Read-only operation with low operational risk."
                if selected.is_read_only
                else "Write operation may change backend state and should respect approval gates."
            ),
            steps=[PlanStepDraft(step_index=0, tool_name=selected.name, args=args)],
        )
        return PlannerResult(draft=draft, backend_used="legacy", llm_calls=0)


class LangChainPlannerBackend:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._legacy = LegacyPlannerBackend()

    def _build_chat_model(self):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.planner_model,
            "temperature": 0,
            "timeout": 60,
            "max_retries": 0,
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
        return PlannerResult(draft=fallback.draft, backend_used="langchain", llm_calls=max(1, llm_calls))


class PlannerAdapter:
    def __init__(self, *, settings: Settings, tool_registry: ToolRegistry):
        self._settings = settings
        self._tool_registry = tool_registry
        self._legacy = LegacyPlannerBackend()
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
            return await self._langchain.generate_plan(
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
