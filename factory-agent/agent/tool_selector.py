from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from .config import Settings
from .intent import assess_intent
from .schemas import ToolInfo
from .telemetry import log_event, log_llm_prompt, log_llm_prompt_skipped
from .tool_scope import ScopedTools, filter_tools_for_intent, score_tool


ToolSelectorBackendName = Literal["retrieval", "langchain"]


@dataclass(frozen=True)
class ToolSelectionResult:
    tool_names: list[str]
    backend_used: ToolSelectorBackendName
    llm_calls: int = 0


class ToolSelector:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _backend_mode(self) -> str:
        return (self._settings.tool_selector_backend or "auto").strip().lower()

    def _can_use_llm_reranker(self) -> bool:
        if not self._settings.tool_selector_reranker_enabled:
            return False
        backend = self._backend_mode()
        if backend == "retrieval":
            return False
        if backend == "langchain":
            return True
        return bool(self._settings.openai_base_url or self._settings.openai_api_key)

    def _top_candidates(
        self,
        *,
        intent: str,
        tools_by_name: dict[str, ToolInfo],
        mode: str,
        max_tools: int,
    ) -> list[tuple[str, int]]:
        candidate_cap = max(1, min(self._settings.tool_selector_candidate_pool, max_tools))
        scoped = filter_tools_for_intent(intent=intent, tools_by_name=tools_by_name, max_tools=max(max_tools, candidate_cap))
        scoped_names = [name for name in scoped.tool_names if name in tools_by_name]
        base_names = scoped_names or sorted(tools_by_name.keys())
        retrieved = self._retrieve_candidates(intent=intent, tools_by_name=tools_by_name, candidates=base_names, limit=candidate_cap)

        if not retrieved:
            ranked = [(name, score_tool(intent, tools_by_name[name])) for name in base_names if name in tools_by_name]
        else:
            ranked = []
            for name, retrieval_score in retrieved:
                if name not in tools_by_name:
                    continue
                heuristic_score = score_tool(intent, tools_by_name[name])
                # Blend retrieval and deterministic intent scoring.
                ranked.append((name, (retrieval_score * 3) + heuristic_score))
            ranked.sort(key=lambda item: item[1], reverse=True)
        if mode == "plan":
            ranked = [(name, score) for name, score in ranked if tools_by_name[name].is_read_only]
            if not ranked:
                ranked = [
                    (name, score_tool(intent, tools_by_name[name]))
                    for name in sorted(tools_by_name.keys())
                    if name in tools_by_name and tools_by_name[name].is_read_only
                ]
                ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked[: max(1, min(self._settings.tool_selector_top_k, max_tools))]

    def _should_rerank(self, candidates: list[tuple[str, int]]) -> bool:
        if len(candidates) < 2 or not self._can_use_llm_reranker():
            return False
        top_score = candidates[0][1]
        second_score = candidates[1][1]
        return (top_score - second_score) <= self._settings.tool_selector_max_score_gap

    def _build_candidate_card(self, tool: ToolInfo) -> dict[str, Any]:
        required = [str(x) for x in (tool.input_schema or {}).get("required", []) if str(x)]
        root = self._endpoint_root(tool.endpoint)
        return {
            "name": tool.name,
            "method": tool.method,
            "endpoint": tool.endpoint,
            "endpoint_root": root,
            "summary": self._compact_summary(tool),
            "description": tool.description,
            "capability_tags": tool.capability_tags,
            "path_params": tool.path_params,
            "query_params": tool.query_params,
            "body_fields": tool.body_fields,
            "required_fields": required,
            "requires_approval": tool.requires_approval,
            "read_only": tool.is_read_only,
        }

    def _normalize_token(self, token: str) -> str:
        lowered = token.lower().strip("_- ")
        if lowered.endswith("ies") and len(lowered) > 3:
            return lowered[:-3] + "y"
        if lowered.endswith("s") and len(lowered) > 3:
            return lowered[:-1]
        return lowered

    def _tokenize(self, text: str) -> set[str]:
        raw = {self._normalize_token(match.group(0)) for match in re.finditer(r"[a-zA-Z0-9_]+", text or "")}
        return {token for token in raw if token}

    def _endpoint_root(self, endpoint: str) -> str:
        normalized = (endpoint or "").strip().strip("/")
        if not normalized:
            return ""
        root = normalized.split("/", 1)[0]
        if root.endswith("s") and len(root) > 1:
            root = root[:-1]
        return root

    def _compact_summary(self, tool: ToolInfo) -> str:
        required = [str(x) for x in (tool.input_schema or {}).get("required", []) if str(x)]
        tags = ", ".join(tool.capability_tags or []) or "-"
        req = ", ".join(required) or "-"
        return f"{tool.method} {tool.endpoint} | tags: {tags} | required: {req}"

    def build_compact_tool_index(self, tools_by_name: dict[str, ToolInfo]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name in sorted(tools_by_name.keys()):
            tool = tools_by_name[name]
            rows.append(
                {
                    "name": tool.name,
                    "summary": self._compact_summary(tool),
                    "description": tool.description,
                }
            )
        return rows

    def _tool_retrieval_tokens(self, tool: ToolInfo) -> set[str]:
        parts = [
            tool.name,
            tool.description,
            tool.endpoint,
            " ".join(tool.capability_tags or []),
            " ".join(tool.path_params or []),
            " ".join(tool.query_params or []),
            " ".join(tool.body_fields or []),
            " ".join(tool.required_body_fields or []),
        ]
        return self._tokenize(" ".join(p for p in parts if p))

    def _retrieve_candidates(
        self,
        *,
        intent: str,
        tools_by_name: dict[str, ToolInfo],
        candidates: list[str],
        limit: int,
    ) -> list[tuple[str, int]]:
        intent_tokens = self._tokenize(intent)
        if not intent_tokens:
            return []
        assessment = assess_intent(intent)
        ranked: list[tuple[str, int]] = []
        for name in candidates:
            tool = tools_by_name.get(name)
            if not tool:
                continue
            tool_tokens = self._tool_retrieval_tokens(tool)
            overlap = intent_tokens & tool_tokens
            score = len(overlap) * 2

            if assessment.action == "create" and tool.method == "POST":
                score += 6
            elif assessment.action == "update" and tool.method in {"PUT", "PATCH"}:
                score += 6
            elif assessment.action == "read" and tool.method == "GET":
                score += 6
            elif assessment.action == "delete" and tool.method == "DELETE":
                score += 6
            elif assessment.action == "approval" and "approval" in tool_tokens:
                score += 6

            if assessment.entity:
                root = self._endpoint_root(tool.endpoint)
                if root == assessment.entity:
                    score += 5
                if assessment.entity in tool_tokens:
                    score += 3

            # Prefer canonical root collection endpoints for generic create requests.
            if (
                assessment.action == "create"
                and assessment.entity
                and tool.method == "POST"
                and tool.endpoint.strip("/").lower() in {assessment.entity, f"{assessment.entity}s"}
            ):
                score += 3

            if score > 0:
                ranked.append((name, score))

        ranked.sort(key=lambda item: (item[1], score_tool(intent, tools_by_name[item[0]])), reverse=True)
        return ranked[: max(1, limit)]

    def _build_rerank_prompt(
        self,
        *,
        intent: str,
        mode: str,
        candidates: list[ToolInfo],
    ) -> str:
        cards = [self._build_candidate_card(tool) for tool in candidates]
        return (
            "You are selecting the best backend tools for a factory operations agent.\n"
            f"User intent: {intent}\n"
            f"Execution mode: {mode}\n"
            "Rules:\n"
            "- Pick tools only from the candidates below.\n"
            "- Prefer exact action + entity alignment.\n"
            "- Avoid specialized sub-resources unless intent explicitly asks for them.\n"
            "- Prefer tools whose required fields are plausibly present in the request.\n"
            "- In `plan` mode, only choose read-only GET-style discovery tools.\n"
            "- If one tool is enough, return only that tool.\n"
            "- For compound requests, you may return additional tools in execution order.\n"
            "Return only JSON with shape:\n"
            '{"primary_tool":"...", "additional_tools":["..."], "confidence":0.0, "missing_fields":["..."], "reason":"..."}\n'
            f"Candidates:\n{json.dumps(cards, ensure_ascii=False)}"
        )

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

    async def _invoke_reranker(self, *, prompt: str) -> dict[str, Any] | None:
        try:
            from langchain_openai import ChatOpenAI
        except Exception:
            return None

        kwargs: dict[str, Any] = {
            "model": self._settings.tool_selector_model,
            "temperature": 0,
            "timeout": self._settings.tool_selector_reranker_timeout_s,
            "max_retries": 0,
            "max_tokens": self._settings.tool_selector_reranker_max_tokens,
            "model_kwargs": {"response_format": {"type": "json_object"}},
        }
        if self._settings.openai_base_url:
            kwargs["base_url"] = self._settings.openai_base_url
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key

        model = ChatOpenAI(**kwargs)
        log_llm_prompt(
            component="tool_selector",
            backend="langchain",
            model=self._settings.tool_selector_model,
            prompt=prompt,
        )
        raw = await model.ainvoke(prompt)
        return self._extract_json_obj((getattr(raw, "content", "") or "").strip())

    async def select_tools(
        self,
        *,
        intent: str,
        tools_by_name: dict[str, ToolInfo],
        mode: str = "normal",
        max_tools: int = 30,
    ) -> ToolSelectionResult:
        candidates = self._top_candidates(intent=intent, tools_by_name=tools_by_name, mode=mode, max_tools=max_tools)
        candidate_names = [name for name, _ in candidates]
        if not candidates:
            return ToolSelectionResult(tool_names=[], backend_used="retrieval", llm_calls=0)

        if not self._should_rerank(candidates):
            log_llm_prompt_skipped(
                component="tool_selector",
                backend=self._backend_mode(),
                reason="retrieval_only",
                metadata={"intent": intent, "candidate_count": len(candidates)},
            )
            return ToolSelectionResult(tool_names=candidate_names, backend_used="retrieval", llm_calls=0)

        prompt = self._build_rerank_prompt(
            intent=intent,
            mode=mode,
            candidates=[tools_by_name[name] for name in candidate_names if name in tools_by_name],
        )
        try:
            parsed = await self._invoke_reranker(prompt=prompt)
        except Exception as exc:
            log_event(
                "tool_selector_rerank_fallback",
                level="WARNING",
                intent=intent,
                reason="reranker_exception",
                error=str(exc),
            )
            return ToolSelectionResult(tool_names=candidate_names, backend_used="retrieval", llm_calls=0)
        if not isinstance(parsed, dict):
            log_event("tool_selector_rerank_fallback", level="WARNING", intent=intent, reason="invalid_llm_response")
            return ToolSelectionResult(tool_names=candidate_names, backend_used="retrieval", llm_calls=0)

        primary = parsed.get("primary_tool")
        additional = parsed.get("additional_tools")
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        if not isinstance(additional, list):
            additional = []

        ordered: list[str] = []
        for name in [primary, *additional]:
            if isinstance(name, str) and name in candidate_names and name not in ordered:
                ordered.append(name)
        for name in candidate_names:
            if name not in ordered:
                ordered.append(name)

        if not ordered or confidence < self._settings.tool_selector_min_confidence:
            log_event(
                "tool_selector_rerank_fallback",
                level="WARNING",
                intent=intent,
                reason="low_confidence",
                confidence=confidence,
            )
            return ToolSelectionResult(tool_names=candidate_names, backend_used="retrieval", llm_calls=1)

        return ToolSelectionResult(tool_names=ordered, backend_used="langchain", llm_calls=1)
