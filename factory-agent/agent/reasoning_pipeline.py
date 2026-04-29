from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .schemas import ToolInfo
from .telemetry import log_event, log_llm_prompt, log_llm_prompt_skipped


@dataclass(frozen=True)
class ToolSelectionDecision:
    tool_name: str | None
    args: dict[str, Any]
    confidence: float
    missing_args: list[str]
    reason: str = ""


@dataclass(frozen=True)
class FactExtractionResult:
    answer_type: str
    facts: list[str]
    ids: list[str]
    counts: dict[str, Any]
    warnings: list[str]
    grounding_refs: list[str]


class ReasoningPipeline:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _enabled(self) -> bool:
        return bool(self._settings.openai_base_url or self._settings.openai_api_key)

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

    def _normalize_field(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())

    def _is_id_field(self, field_name: str) -> bool:
        normalized = self._normalize_field(field_name)
        return normalized == "id" or normalized.endswith("id")

    def _parse_requested_fields(self, args: dict[str, Any]) -> set[str]:
        raw = args.get("fields") or args.get("select")
        if isinstance(raw, str):
            tokens = [part.strip() for part in re.split(r"[,\s]+", raw) if part.strip()]
            return {self._normalize_field(tok) for tok in tokens}
        if isinstance(raw, list):
            return {self._normalize_field(str(tok)) for tok in raw if str(tok).strip()}
        return set()

    def _deterministic_extract_facts(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> FactExtractionResult:
        if result.get("not_found"):
            summary = str(result.get("_summary") or result.get("detail") or "Requested resource was not found.")
            return FactExtractionResult(
                answer_type="not_found",
                facts=[summary],
                ids=[],
                counts={},
                warnings=[],
                grounding_refs=["$._summary" if "_summary" in result else "$.detail"],
            )

        data = result.get("data")
        if isinstance(data, list):
            requested = self._parse_requested_fields(args or {})
            ids: list[str] = []
            refs: list[str] = []
            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                matches: list[tuple[str, Any]] = []
                for key, value in item.items():
                    key_norm = self._normalize_field(str(key))
                    if requested:
                        if key_norm in requested and self._is_id_field(key_norm):
                            matches.append((key, value))
                    else:
                        if self._is_id_field(key_norm):
                            matches.append((key, value))
                if len(matches) == 1:
                    key, value = matches[0]
                    if value not in (None, ""):
                        ids.append(str(value))
                        refs.append(f"$.data[{idx}].{key}")
            if ids:
                ids = list(dict.fromkeys(ids))
                return FactExtractionResult(
                    answer_type="id_list",
                    facts=[f"Found {len(ids)} IDs in tool result."],
                    ids=ids,
                    counts={"total": len(ids)},
                    warnings=[],
                    grounding_refs=refs[:25],
                )
            return FactExtractionResult(
                answer_type="summary",
                facts=[f"Retrieved {len(data)} records."],
                ids=[],
                counts={"records": len(data)},
                warnings=[],
                grounding_refs=["$.data"],
            )

        for key in ("message", "detail", "status", "summary"):
            if isinstance(result.get(key), str) and str(result.get(key)).strip():
                return FactExtractionResult(
                    answer_type="summary",
                    facts=[str(result.get(key)).strip()],
                    ids=[],
                    counts={},
                    warnings=[],
                    grounding_refs=[f"$.{key}"],
                )

        return FactExtractionResult(
            answer_type="summary",
            facts=[f"{tool_name} completed."],
            ids=[],
            counts={},
            warnings=[],
            grounding_refs=[],
        )

    def _build_model(self):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.tool_result_summary_model,
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

    async def _invoke_json(self, *, component: str, prompt: str, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self._enabled():
            log_llm_prompt_skipped(
                component=component,
                backend="disabled",
                reason="llm_not_configured",
                metadata=metadata or {},
            )
            return None

        try:
            from langchain_openai import ChatOpenAI  # noqa: F401
        except Exception:
            log_llm_prompt_skipped(
                component=component,
                backend="disabled",
                reason="langchain_openai_unavailable",
                metadata=metadata or {},
            )
            return None

        log_llm_prompt(
            component=component,
            backend="langchain",
            model=self._settings.tool_result_summary_model,
            prompt=prompt,
            metadata=metadata or {},
        )
        try:
            model = self._build_model()
            resp = await model.ainvoke(prompt)
            content = (getattr(resp, "content", "") or "").strip()
            return self._extract_json_obj(content)
        except Exception as exc:
            log_event(
                f"{component}_failed",
                level="WARNING",
                error=str(exc),
                **(metadata or {}),
            )
            return None

    async def select_tool(
        self,
        *,
        intent: str,
        clause: str,
        candidates: list[dict[str, Any]],
    ) -> ToolSelectionDecision | None:
        try:
            prompt = (
                "Select one best tool for this user clause and return STRICT JSON.\n"
                "JSON shape:\n"
                '{"tool_name":"string","args":{},"confidence":0.0,"missing_args":[],"reason":"string"}\n'
                "Rules:\n"
                "- Choose tool_name from candidates only.\n"
                "- Prefer tools with fewer missing required args for read operations.\n"
                "- Use candidate prefilled_args as args baseline.\n"
                "- Do not invent unsupported args.\n\n"
                f"Intent: {intent}\n"
                f"Clause: {clause}\n"
                f"Candidates: {json.dumps(candidates, ensure_ascii=False)}\n"
            )
            parsed = await self._invoke_json(
                component="reasoning_tool_selection",
                prompt=prompt,
                metadata={"candidate_count": len(candidates)},
            )
            if not isinstance(parsed, dict):
                return None
            tool_name = parsed.get("tool_name")
            args = parsed.get("args")
            confidence = parsed.get("confidence", 0.0)
            missing_args = parsed.get("missing_args")
            reason = parsed.get("reason", "")
            if not isinstance(tool_name, str):
                return None
            if not isinstance(args, dict):
                args = {}
            if not isinstance(missing_args, list):
                missing_args = []
            try:
                conf = float(confidence)
            except Exception:
                conf = 0.0
            return ToolSelectionDecision(
                tool_name=tool_name,
                args=args,
                confidence=conf,
                missing_args=[str(x) for x in missing_args],
                reason=str(reason or ""),
            )
        except Exception as exc:
            log_event(
                "reasoning_tool_selection_guarded_fallback",
                level="WARNING",
                error=str(exc),
            )
            return None

    async def extract_facts(
        self,
        *,
        intent: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> FactExtractionResult | None:
        deterministic = self._deterministic_extract_facts(tool_name=tool_name, args=args or {}, result=result or {})
        try:
            prompt = (
                "Extract grounded facts from the tool result and return STRICT JSON.\n"
                "JSON shape:\n"
                '{"answer_type":"id_list|record|not_found|error|summary","facts":[],"ids":[],"counts":{},"warnings":[],"grounding_refs":[]}\n'
                "Rules:\n"
                "- Facts must be atomic and grounded in result JSON.\n"
                "- grounding_refs must use JSONPath-like pointers (e.g. $.data[0].id).\n"
                "- Do not write final user prose.\n\n"
                f"Intent: {intent}\n"
                f"Tool: {tool_name}\n"
                f"Args: {json.dumps(args or {}, ensure_ascii=False)}\n"
                f"Result: {json.dumps(result or {}, ensure_ascii=False)}\n"
            )
            parsed = await self._invoke_json(
                component="reasoning_fact_extraction",
                prompt=prompt,
                metadata={"tool_name": tool_name},
            )
            if not isinstance(parsed, dict):
                return deterministic
            answer_type = str(parsed.get("answer_type") or "summary")
            facts = parsed.get("facts") if isinstance(parsed.get("facts"), list) else []
            ids = parsed.get("ids") if isinstance(parsed.get("ids"), list) else []
            counts = parsed.get("counts") if isinstance(parsed.get("counts"), dict) else {}
            warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
            refs = parsed.get("grounding_refs") if isinstance(parsed.get("grounding_refs"), list) else []
            return FactExtractionResult(
                answer_type=answer_type,
                facts=[str(x) for x in facts],
                ids=[str(x) for x in ids],
                counts=counts,
                warnings=[str(x) for x in warnings],
                grounding_refs=[str(x) for x in refs],
            )
        except Exception as exc:
            log_event(
                "reasoning_fact_extraction_guarded_fallback",
                level="WARNING",
                error=str(exc),
                tool_name=tool_name,
            )
            return deterministic

    async def generate_response(self, *, intent: str, facts: FactExtractionResult) -> str | None:
        prompt = (
            "Write a concise user-facing response using ONLY the provided facts JSON.\n"
            "Rules:\n"
            "- One short sentence.\n"
            "- No claims outside facts.\n"
            "- Prefer IDs/counts when answer_type=id_list.\n\n"
            f"Intent: {intent}\n"
            f"Facts JSON: {json.dumps(facts.__dict__, ensure_ascii=False)}\n"
            "Return JSON only: {\"message\":\"...\"}\n"
        )
        parsed = await self._invoke_json(
            component="reasoning_response_generation",
            prompt=prompt,
            metadata={"answer_type": facts.answer_type},
        )
        if not isinstance(parsed, dict):
            return None
        message = parsed.get("message")
        if not isinstance(message, str) or not message.strip():
            return None
        return message.strip()

    async def verify_grounding(self, *, response_text: str, facts: FactExtractionResult) -> bool:
        prompt = (
            "Verify whether the response is fully grounded in the facts JSON.\n"
            "Return JSON only: {\"grounded\": true|false, \"issues\": []}\n\n"
            f"Response: {response_text}\n"
            f"Facts JSON: {json.dumps(facts.__dict__, ensure_ascii=False)}\n"
        )
        parsed = await self._invoke_json(
            component="reasoning_grounding_verifier",
            prompt=prompt,
            metadata={"answer_type": facts.answer_type},
        )
        if not isinstance(parsed, dict):
            return False
        grounded = parsed.get("grounded")
        return bool(grounded is True)

    def fallback_response_from_facts(self, *, facts: FactExtractionResult) -> str:
        if facts.answer_type == "id_list":
            ids = facts.ids[:10]
            suffix = f", +{len(facts.ids) - len(ids)} more" if len(facts.ids) > len(ids) else ""
            if ids:
                return f"Found {len(facts.ids)} ID(s): {', '.join(ids)}{suffix}."
        if facts.facts:
            return facts.facts[0]
        if facts.warnings:
            return facts.warnings[0]
        return "Tool execution completed."

    def build_selection_candidates(
        self,
        *,
        tools: list[ToolInfo],
        prefilled_by_tool: dict[str, dict[str, Any]],
        missing_by_tool: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for tool in tools:
            out.append(
                {
                    "name": tool.name,
                    "method": tool.method,
                    "endpoint": tool.endpoint,
                    "read_only": tool.is_read_only,
                    "requires_approval": tool.requires_approval,
                    "required_fields": list((tool.input_schema or {}).get("required", [])),
                    "prefilled_args": prefilled_by_tool.get(tool.name, {}),
                    "missing_required": missing_by_tool.get(tool.name, []),
                    "capability_tags": tool.capability_tags,
                }
            )
        return out
