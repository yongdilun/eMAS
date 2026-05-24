"""Optional LLM judge support for borderline RAG evaluation cases."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_JUDGE_BASE_URL = "http://127.0.0.1:900/v1"
DEFAULT_JUDGE_MODEL = "Qwen2.5-7B-Instruct-Q4_K_M"

_JUDGE_ENABLE_ENVS = ("FACTORY_AGENT_RAG_EVAL_JUDGE", "RAG_EVAL_JUDGE")
_REQUIRED_RUBRIC_FIELDS = (
    "correctness",
    "completeness",
    "faithfulness",
    "citation_quality",
    "safety",
    "conciseness",
)


@dataclass(frozen=True)
class JudgeConfig:
    enabled: bool = False
    base_url: str = DEFAULT_JUDGE_BASE_URL
    model: str = DEFAULT_JUDGE_MODEL
    api_key: str = "local"
    timeout_s: float = 60.0

    @classmethod
    def from_env(cls, *, enabled: bool | None = None) -> "JudgeConfig":
        resolved_enabled = _env_enabled() if enabled is None else enabled
        return cls(
            enabled=resolved_enabled,
            base_url=(
                os.getenv("RAG_EVAL_JUDGE_BASE_URL")
                or os.getenv("FACTORY_AGENT_RAG_EVAL_JUDGE_BASE_URL")
                or DEFAULT_JUDGE_BASE_URL
            ),
            model=(
                os.getenv("RAG_EVAL_JUDGE_MODEL")
                or os.getenv("FACTORY_AGENT_RAG_EVAL_JUDGE_MODEL")
                or DEFAULT_JUDGE_MODEL
            ),
            api_key=os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or "local",
            timeout_s=float(os.getenv("RAG_EVAL_JUDGE_TIMEOUT_S", "60")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_s": self.timeout_s,
        }


def judge_case(
    *,
    case: dict[str, Any],
    agent_response: dict[str, Any] | None,
    rag_result: dict[str, Any] | None,
    retrieval_debug: dict[str, Any] | None,
    scoring: dict[str, Any],
    config: JudgeConfig,
) -> dict[str, Any]:
    """Call an OpenAI-compatible chat completion judge and parse strict JSON."""

    payload = build_judge_input(
        case=case,
        agent_response=agent_response,
        rag_result=rag_result,
        retrieval_debug=retrieval_debug,
        scoring=scoring,
    )
    raw = _post_chat_completion(prompt=build_judge_prompt(payload), config=config)
    parsed = parse_judge_json(raw)
    parsed["judge_model"] = config.model
    parsed["judge_base_url"] = config.base_url
    parsed["judge_scope"] = "borderline_only"
    return parsed


def build_judge_input(
    *,
    case: dict[str, Any],
    agent_response: dict[str, Any] | None,
    rag_result: dict[str, Any] | None,
    retrieval_debug: dict[str, Any] | None,
    scoring: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the self-contained judge payload required by the rubric."""

    response = agent_response or {}
    rag = rag_result or {}
    answer = response.get("answer") or rag.get("answer") or ""
    sources = response.get("sources") or rag.get("sources") or []
    top_chunks = (retrieval_debug or {}).get("top_chunks") or []

    return {
        "case_id": case.get("id"),
        "query": case.get("query"),
        "gold_answer": case.get("gold_answer"),
        "expected_answer_points": case.get("expected_answer_points") or [],
        "expected_source": case.get("expected_source") or {},
        "model_answer": answer,
        "cited_sources": _compact_sources(sources),
        "retrieved_context_snippets": _compact_retrieved_snippets(top_chunks),
        "expects_safety_warning": bool(case.get("expects_safety_warning")),
        "unanswerable_reason": case.get("unanswerable_reason"),
        "rule_score": (scoring or {}).get("rule_score"),
        "rule_dimensions": (scoring or {}).get("rule_dimensions"),
        "serious_failures": (scoring or {}).get("serious_failures") or [],
    }


def build_judge_prompt(payload: dict[str, Any]) -> str:
    """Render a strict JSON judge prompt."""

    return (
        "You are a conservative RAG evaluation judge. Judge only the answer "
        "against the provided gold expectations and evidence. Treat your "
        "output as triage evidence, not final truth.\n\n"
        "Return strict JSON only with exactly these fields:\n"
        "{\n"
        '  "correctness": 1-5,\n'
        '  "completeness": 1-5,\n'
        '  "faithfulness": 1-5,\n'
        '  "citation_quality": 1-5,\n'
        '  "safety": 1-5,\n'
        '  "conciseness": 1-5,\n'
        '  "serious_failure": true/false,\n'
        '  "serious_failure_reason": string or null,\n'
        '  "rationale": short string\n'
        "}\n\n"
        "Use 1 for very poor and 5 for excellent. Mark serious_failure=true "
        "for unsafe advice, unsupported hallucinations, wrong answers, failed "
        "boundary answers, or citations that do not support the answer. If the "
        "question is unanswerable, reward a helpful boundary answer that says "
        "what the sources can and cannot support.\n\n"
        f"Judge input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_judge_json(raw: str) -> dict[str, Any]:
    """Parse and validate the judge's strict JSON response."""

    payload = json.loads(_extract_json_object(raw))
    if not isinstance(payload, dict):
        raise ValueError("judge response must be a JSON object")

    normalized: dict[str, Any] = {}
    for field in _REQUIRED_RUBRIC_FIELDS:
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 5:
            raise ValueError(f"judge field {field!r} must be an integer from 1 to 5")
        normalized[field] = value

    serious_failure = payload.get("serious_failure")
    if not isinstance(serious_failure, bool):
        raise ValueError("judge field 'serious_failure' must be boolean")
    normalized["serious_failure"] = serious_failure

    reason = payload.get("serious_failure_reason")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("judge field 'serious_failure_reason' must be string or null")
    normalized["serious_failure_reason"] = reason

    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("judge field 'rationale' must be a non-empty string")
    normalized["rationale"] = rationale.strip()[:1000]
    return normalized


def _post_chat_completion(*, prompt: str, config: JudgeConfig) -> str:
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    body = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": "Return strict JSON only. Do not include markdown.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "top_p": 1,
        "max_tokens": 700,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_s) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # pragma: no cover - live server defensive path
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"judge HTTP {exc.code}: {detail}") from exc

    payload = json.loads(raw)
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("judge response did not include choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("judge response did not include message content")
    return content


def _extract_json_object(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise ValueError("judge response did not contain a JSON object")


def _compact_sources(sources: Any) -> list[dict[str, Any]]:
    if not isinstance(sources, list):
        return []
    compact: list[dict[str, Any]] = []
    for source in sources[:8]:
        if not isinstance(source, dict):
            continue
        compact.append(
            {
                "source_number": source.get("source_number"),
                "doc_id": source.get("doc_id"),
                "page": source.get("page"),
                "page_start": source.get("page_start"),
                "page_end": source.get("page_end"),
                "section_title": source.get("section_title"),
                "section_path": source.get("section_path"),
                "snippet": source.get("snippet"),
                "text_search": source.get("text_search"),
            }
        )
    return compact


def _compact_retrieved_snippets(chunks: Any) -> list[dict[str, Any]]:
    if not isinstance(chunks, list):
        return []
    compact: list[dict[str, Any]] = []
    for chunk in chunks[:8]:
        if not isinstance(chunk, dict):
            continue
        compact.append(
            {
                "rank": chunk.get("rank"),
                "doc_id": chunk.get("doc_id"),
                "page": chunk.get("page"),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "section_title": chunk.get("section_title"),
                "section_path": chunk.get("section_path"),
                "snippet": chunk.get("snippet"),
            }
        )
    return compact


def _env_enabled() -> bool:
    return any(os.getenv(name, "0").strip().lower() in {"1", "true", "yes"} for name in _JUDGE_ENABLE_ENVS)
