from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import asdict
from typing import Any

from .config import Settings
from .schemas import ToolInfo
from .tabular_analysis import analyze_result
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

    _MAX_INLINE_RESULT_CHARS = 3200
    _MAX_PREVIEW_LIST_ITEMS = 8
    _MAX_PREVIEW_DICT_ITEMS = 12
    _GENERIC_SUMMARY_PATTERNS = (
        re.compile(r"^retrieved \d+ records\.?$", re.IGNORECASE),
        re.compile(r"^returned \d+ record\(s\)\.?$", re.IGNORECASE),
        re.compile(r"^found \d+ ids? in tool result\.?$", re.IGNORECASE),
        re.compile(r"^tool execution completed\.?$", re.IGNORECASE),
    )
    _ALLOWED_ANSWER_TYPES = {"id_list", "record", "not_found", "error", "summary"}

    def _component_backend(self, component: str) -> str:
        if component == "reasoning_tool_selection":
            return (self._settings.tool_selector_backend or "auto").strip().lower()
        if component == "reasoning_semantic_classifier":
            return (self._settings.tool_selector_backend or "auto").strip().lower()
        if component in {"reasoning_fact_extraction", "reasoning_response_generation", "reasoning_grounding_verifier"}:
            return (self._settings.tool_result_summary_backend or "auto").strip().lower()
        return "auto"

    def _component_model(self, component: str) -> str:
        if component == "reasoning_tool_selection":
            return self._settings.tool_selector_model
        if component == "reasoning_semantic_classifier":
            return self._settings.tool_selector_model
        return self._settings.tool_result_summary_model

    def _component_base_url(self, component: str) -> str | None:
        if component in {"reasoning_tool_selection", "reasoning_semantic_classifier"}:
            return self._settings.tool_selector_openai_base_url
        return self._settings.tool_result_summary_openai_base_url

    def _component_timeout(self, component: str) -> float:
        if component in {"reasoning_tool_selection", "reasoning_semantic_classifier"}:
            return self._settings.tool_selector_timeout_s
        if component in {
            "reasoning_fact_extraction",
            "reasoning_response_generation",
            "reasoning_grounding_verifier",
        }:
            return self._settings.tool_result_summary_timeout_s
        return self._settings.llm_json_timeout_s

    def _component_max_tokens(self, component: str) -> int:
        if component in {"reasoning_tool_selection", "reasoning_semantic_classifier"}:
            return self._settings.tool_selector_max_tokens
        if component in {
            "reasoning_fact_extraction",
            "reasoning_response_generation",
            "reasoning_grounding_verifier",
        }:
            return self._settings.tool_result_summary_max_tokens
        return self._settings.llm_json_max_tokens

    def _result_json_size(self, result: dict[str, Any]) -> int:
        try:
            raw = json.dumps(result or {}, ensure_ascii=False)
        except Exception:
            return self._MAX_INLINE_RESULT_CHARS + 1
        return len(raw)

    def _enabled(self, component: str) -> bool:
        if self._settings.force_llm_trace_all:
            return bool(self._component_base_url(component) or self._settings.openai_api_key)
        backend = self._component_backend(component)
        if backend in {"legacy", "retrieval", "disabled", "off", "false", "none"}:
            return False
        if backend not in {"auto", "langchain"}:
            return False
        return bool(self._component_base_url(component) or self._settings.openai_api_key)

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

    def _is_scalar_preview_value(self, value: Any) -> bool:
        return value is None or isinstance(value, (str, int, float, bool))

    def _compact_preview_value(self, value: Any) -> Any:
        if self._is_scalar_preview_value(value):
            return value
        if isinstance(value, list):
            return f"[list:{len(value)}]"
        if isinstance(value, dict):
            return f"{{object:{len(value)}}}"
        return str(value)

    def _compact_preview_mapping(self, value: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= self._MAX_PREVIEW_DICT_ITEMS:
                break
            compact[str(key)] = self._compact_preview_value(item)
        return compact

    def _build_llm_result_payload(self, result: dict[str, Any]) -> Any:
        size = self._result_json_size(result)
        if size <= self._MAX_INLINE_RESULT_CHARS:
            return result

        preview: dict[str, Any] = {
            "truncated": True,
            "json_size_chars": size,
            "top_level_keys": list((result or {}).keys())[:20],
        }

        for key, value in (result or {}).items():
            if key in {"data", "items"} and isinstance(value, list):
                preview[f"{key}_count"] = len(value)
                sample: list[Any] = []
                for item in value[: self._MAX_PREVIEW_LIST_ITEMS]:
                    if isinstance(item, dict):
                        sample.append(self._compact_preview_mapping(item))
                    else:
                        sample.append(self._compact_preview_value(item))
                preview[f"{key}_sample"] = sample
                continue
            if isinstance(value, dict):
                preview[key] = self._compact_preview_mapping(value)
                continue
            if isinstance(value, list):
                preview[key] = [self._compact_preview_value(item) for item in value[: self._MAX_PREVIEW_LIST_ITEMS]]
                if len(value) > self._MAX_PREVIEW_LIST_ITEMS:
                    preview[f"{key}_truncated"] = True
                continue
            preview[key] = self._compact_preview_value(value)
        return preview

    def _is_generic_summary_fact(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return True
        if normalized.lower().endswith("completed."):
            return True
        return any(pattern.match(normalized) for pattern in self._GENERIC_SUMMARY_PATTERNS)

    def _looks_like_structured_text(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return False
        if (normalized.startswith("{") and normalized.endswith("}")) or (
            normalized.startswith("[") and normalized.endswith("]")
        ):
            return True
        if re.search(r"['\"]?[A-Za-z0-9_]+['\"]?\s*:\s*", normalized):
            return True
        return False

    def _summarize_structured_fact_text(self, text: str) -> str | None:
        candidate = (text or "").strip()
        if not candidate:
            return None
        parsed: Any | None = None
        try:
            parsed = json.loads(candidate)
        except Exception:
            try:
                import ast

                parsed = ast.literal_eval(candidate)
            except Exception:
                parsed = None
        if not isinstance(parsed, dict):
            return None

        identifier = None
        for key in ("job_id", "machine_id", "product_id", "inventory_id", "approval_id", "proposal_id", "id", "name"):
            value = parsed.get(key)
            if value not in (None, ""):
                identifier = str(value)
                break

        parts: list[str] = []
        if identifier:
            parts.append(identifier)
        if parsed.get("status") not in (None, ""):
            parts.append(f"status {parsed['status']}")
        if parsed.get("priority") not in (None, ""):
            parts.append(f"priority {parsed['priority']}")
        if parsed.get("product_id") not in (None, "") and str(parsed.get("product_id")) != identifier:
            parts.append(f"product {parsed['product_id']}")
        if parsed.get("quantity_total") not in (None, ""):
            parts.append(f"qty {parsed['quantity_total']}")
        if parsed.get("quantity_completed") not in (None, ""):
            parts.append(f"completed {parsed['quantity_completed']}")
        if parsed.get("deadline") not in (None, ""):
            parts.append(f"deadline {parsed['deadline']}")

        if not parts:
            return None
        head, *tail = parts
        return f"{head} ({', '.join(tail)})" if tail else head

    def _normalize_fact_text(self, text: str) -> str:
        normalized = (text or "").strip()
        if not normalized:
            return normalized
        structured_summary = self._summarize_structured_fact_text(normalized)
        if structured_summary:
            return structured_summary
        return normalized

    def _sanitize_facts(self, facts: list[Any]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in facts:
            text = self._normalize_fact_text(str(item))
            if not text or text in seen:
                continue
            cleaned.append(text)
            seen.add(text)
        return cleaned

    def _should_use_llm_for_fact_extraction(
        self,
        *,
        deterministic: FactExtractionResult,
        result: dict[str, Any],
    ) -> tuple[bool, str]:
        if not self._enabled("reasoning_fact_extraction"):
            return False, "backend_disabled_or_llm_not_configured"
        if self._settings.force_llm_trace_all:
            return True, "force_llm_trace_all"
        if deterministic.answer_type in {"id_list", "not_found", "error"}:
            return False, "deterministic_sufficient"
        if isinstance(deterministic.counts, dict) and isinstance(deterministic.counts.get("analysis"), dict):
            return False, "deterministic_analysis_sufficient"
        data = result.get("data")
        if isinstance(data, list) and len(data) > 1:
            return True, "multi_record_result"
        items = result.get("items")
        if isinstance(items, list) and len(items) > 1:
            return True, "multi_item_result"
        if self._result_json_size(result or {}) > self._MAX_INLINE_RESULT_CHARS:
            return True, "result_requires_truncation"
        if deterministic.facts and self._is_generic_summary_fact(deterministic.facts[0]):
            return True, "deterministic_summary_too_generic"
        return False, "deterministic_sufficient"

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

    def deterministic_response_contract(self, *, facts: FactExtractionResult) -> str | None:
        if not isinstance(facts.counts, dict):
            return None
        analysis = facts.counts.get("analysis")
        if isinstance(analysis, dict) and isinstance(analysis.get("facts"), list) and analysis["facts"]:
            records = facts.counts.get("records")
            prefix = ""
            try:
                n = int(records)
                prefix = f"Retrieved {n} records. "
            except Exception:
                pass
            return prefix + " ".join(str(fact) for fact in analysis["facts"][:4])
        records = facts.counts.get("records")
        try:
            n = int(records)
        except Exception:
            return None
        if n > 1:
            return f"Retrieved {n} records. Rows are shown in the table below."
        if n == 1:
            return "Retrieved 1 record."
        return None

    def response_policy(self, *, facts: FactExtractionResult) -> str:
        if facts.answer_type in {"error", "not_found"}:
            return "deterministic"
        if self.deterministic_response_contract(facts=facts):
            return "deterministic_or_grounded"
        return "llm_or_fallback"

    def _build_model(self, *, component: str):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._component_model(component),
            "temperature": 0,
            "timeout": self._component_timeout(component),
            "max_retries": 0,
            "max_tokens": self._component_max_tokens(component),
            "model_kwargs": {"response_format": {"type": "json_object"}},
        }
        base_url = self._component_base_url(component)
        if base_url:
            kwargs["base_url"] = base_url
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    async def _invoke_json(self, *, component: str, prompt: str, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        backend = self._component_backend(component)
        model_name = self._component_model(component)
        if not self._enabled(component):
            log_llm_prompt_skipped(
                component=component,
                backend=backend,
                reason="backend_disabled_or_llm_not_configured",
                metadata={"model": model_name, **(metadata or {})},
            )
            return None

        log_llm_prompt(
            component=component,
            backend="langchain",
            model=model_name,
            prompt=prompt,
            metadata={"configured_backend": backend, **(metadata or {})},
        )
        try:
            model = self._build_model(component=component)
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
                "- Do not invent unsupported args.\n"
                "- Populate optional_args into args if they match the intent.\n\n"
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

    async def classify_unknown_term(
        self,
        *,
        clause: str,
        term: str,
        entity: str,
        tool: ToolInfo,
    ) -> dict[str, Any] | None:
        properties = (tool.input_schema or {}).get("properties", {})
        candidates: list[dict[str, Any]] = []
        for field_name, field_schema in properties.items():
            if not isinstance(field_schema, dict):
                continue
            candidate: dict[str, Any] = {"field_name": field_name}
            if "type" in field_schema:
                candidate["type"] = field_schema.get("type")
            if "enum" in field_schema:
                candidate["enum"] = field_schema.get("enum")
            if "description" in field_schema:
                candidate["description"] = field_schema.get("description")
            candidates.append(candidate)

        if not candidates:
            return None

        prompt = (
            "Classify one unknown user term against a factory tool schema and return STRICT JSON.\n"
            'JSON shape: {"field_name":"string|null","confidence":0.0,"reason":"string"}\n'
            "Rules:\n"
            "- Choose field_name only from the candidates below.\n"
            "- Do not invent enum values or rewrite the term.\n"
            "- Return null when the term does not strongly suggest one schema field.\n"
            "- Prefer enum-backed fields when the unknown term looks like a state or status word.\n\n"
            f"Entity: {entity}\n"
            f"Clause: {clause}\n"
            f"Unknown term: {term}\n"
            f"Tool: {tool.name}\n"
            f"Candidate fields: {json.dumps(candidates, ensure_ascii=False)}\n"
        )
        parsed = await self._invoke_json(
            component="reasoning_semantic_classifier",
            prompt=prompt,
            metadata={"tool_name": tool.name, "entity": entity},
        )
        if not isinstance(parsed, dict):
            return None
        field_name = parsed.get("field_name")
        if field_name is not None and not isinstance(field_name, str):
            return None
        try:
            confidence = float(parsed.get("confidence", 0.0) or 0.0)
        except Exception:
            confidence = 0.0
        if field_name and confidence < 0.5:
            return None
        return {
            "field_name": field_name,
            "confidence": confidence,
            "reason": str(parsed.get("reason") or ""),
        }

    async def extract_facts(
        self,
        *,
        intent: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> FactExtractionResult | None:
        deterministic = self._deterministic_extract_facts(tool_name=tool_name, args=args or {}, result=result or {})
        if isinstance(result, dict):
            analysis = analyze_result(intent=intent or "", result=result)
            if analysis is not None and deterministic.answer_type == "summary":
                deterministic = FactExtractionResult(
                    answer_type="summary",
                    facts=[f"Retrieved {analysis.dataset.row_count} records.", *analysis.facts],
                    ids=deterministic.ids,
                    counts={
                        **(deterministic.counts or {}),
                        "records": analysis.dataset.row_count,
                        "analysis": {
                            "dataset": asdict(analysis.dataset),
                            "operations": [asdict(op) for op in analysis.operations],
                            "results": analysis.results,
                            "facts": analysis.facts,
                        },
                    },
                    warnings=deterministic.warnings,
                    grounding_refs=[*deterministic.grounding_refs, *analysis.grounding_refs],
                )
        should_use_llm, reason = self._should_use_llm_for_fact_extraction(
            deterministic=deterministic,
            result=result or {},
        )
        if not should_use_llm:
            log_llm_prompt_skipped(
                component="reasoning_fact_extraction",
                backend=self._component_backend("reasoning_fact_extraction"),
                reason=reason,
                metadata={"tool_name": tool_name},
            )
            return deterministic
        try:
            prompt_result = self._build_llm_result_payload(result or {})
            prompt = (
                "Extract grounded facts from the tool result and return STRICT JSON.\n"
                "JSON shape:\n"
                '{"answer_type":"id_list|record|not_found|error|summary","facts":[],"ids":[],"counts":{},"warnings":[],"grounding_refs":[]}\n'
                "Rules:\n"
                "- Facts must be atomic and grounded in result JSON.\n"
                "- grounding_refs must use JSONPath-like pointers (e.g. $.data[0].id).\n"
                "- Prefer concise, user-relevant facts over raw field dumps.\n"
                "- Do not output raw JSON objects, Python dicts, or key-value dumps inside facts.\n"
                "- For list results, include the total count and a few notable patterns or examples.\n"
                "- Do not write final user prose.\n\n"
                f"Intent: {intent}\n"
                f"Tool: {tool_name}\n"
                f"Args: {json.dumps(args or {}, ensure_ascii=False)}\n"
                f"Deterministic baseline: {json.dumps(deterministic.__dict__, ensure_ascii=False)}\n"
                f"Result: {json.dumps(prompt_result, ensure_ascii=False)}\n"
            )
            parsed = await self._invoke_json(
                component="reasoning_fact_extraction",
                prompt=prompt,
                metadata={"tool_name": tool_name, "selection_reason": reason},
            )
            if not isinstance(parsed, dict):
                return deterministic
            answer_type = str(parsed.get("answer_type") or "summary")
            if "|" in answer_type or answer_type not in self._ALLOWED_ANSWER_TYPES:
                return deterministic
            facts = self._sanitize_facts(parsed.get("facts") if isinstance(parsed.get("facts"), list) else [])
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

    async def generate_response(self, *, intent: str, facts: FactExtractionResult, render_context: dict[str, Any] | None = None) -> str | None:
        prompt = (
            "Write a concise user-facing response using ONLY the provided facts JSON.\n"
            "Rules:\n"
            "- Use plain human-readable language for operators.\n"
            "- Never echo JSON, Python dicts, braces, or key-value dumps.\n"
            "- Use 1-2 short sentences.\n"
            "- Mention the total count when available.\n"
            "- If counts.records > 1, tell the user the rows are shown in the table below.\n"
            "- Mention 1-3 notable examples or patterns when grounded facts support them.\n"
            "- No claims outside facts.\n"
            "- Prefer IDs/counts when answer_type=id_list.\n\n"
            f"Intent: {intent}\n"
            f"Facts JSON: {json.dumps(facts.__dict__, ensure_ascii=False)}\n"
            f"Render context JSON: {json.dumps(render_context or {}, ensure_ascii=False)}\n"
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

    def should_generate_response(self, *, facts: FactExtractionResult) -> bool:
        if not self._enabled("reasoning_response_generation"):
            return False
        if self._settings.force_llm_trace_all:
            return facts.answer_type not in {"not_found", "error"}
        if facts.answer_type in {"id_list", "not_found", "error"}:
            return False
        if isinstance(facts.counts, dict):
            records = facts.counts.get("records")
            try:
                if records is not None and int(records) > 1:
                    return True
            except Exception:
                pass
        if facts.warnings:
            return True
        if len(facts.facts) != 1:
            return True
        if self._looks_like_structured_text(facts.facts[0]):
            return True
        return len(facts.facts[0].strip()) > 140

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
        contract = self.deterministic_response_contract(facts=facts)
        if contract:
            return contract
        if facts.answer_type == "id_list":
            ids = facts.ids[:10]
            suffix = f", +{len(facts.ids) - len(ids)} more" if len(facts.ids) > len(ids) else ""
            if ids:
                return f"Found {len(facts.ids)} ID(s): {', '.join(ids)}{suffix}."
        if isinstance(facts.counts, dict):
            records = facts.counts.get("records")
            try:
                if records is not None and int(records) > 1:
                    return f"I found {int(records)} records in the system. I listed them in the table below."
            except Exception:
                pass
        if facts.facts:
            if len(facts.facts) == 1:
                return self._normalize_fact_text(facts.facts[0])
            return " ".join(self._normalize_fact_text(fact) for fact in facts.facts[:3] if str(fact).strip())
        if facts.warnings:
            return facts.warnings[0]
        return "Execution completed successfully."

    def build_selection_candidates(
        self,
        *,
        tools: list[ToolInfo],
        prefilled_by_tool: dict[str, dict[str, Any]],
        missing_by_tool: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for tool in tools:
            required_fields = list((tool.input_schema or {}).get("required", []))
            optional_args = {}
            for field, field_schema in (tool.input_schema or {}).get("properties", {}).items():
                if field not in required_fields:
                    opt_meta = {}
                    if "type" in field_schema:
                        opt_meta["type"] = field_schema["type"]
                    if "enum" in field_schema:
                        opt_meta["enum"] = field_schema["enum"]
                    if "description" in field_schema:
                        opt_meta["description"] = field_schema["description"]
                    if opt_meta:
                        optional_args[field] = opt_meta

            out.append(
                {
                    "name": tool.name,
                    "method": tool.method,
                    "endpoint": tool.endpoint,
                    "read_only": tool.is_read_only,
                    "requires_approval": tool.requires_approval,
                    "required_fields": required_fields,
                    "optional_args": optional_args,
                    "prefilled_args": prefilled_by_tool.get(tool.name, {}),
                    "missing_required": missing_by_tool.get(tool.name, []),
                    "capability_tags": tool.capability_tags,
                }
            )
        return out
