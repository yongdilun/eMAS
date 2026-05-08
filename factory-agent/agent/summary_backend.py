from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Literal

from .config import Settings
from .schemas import PlanDraft
from .telemetry import log_llm_prompt, log_llm_prompt_skipped


SummaryBackendName = Literal["legacy", "langchain"]


@dataclass(frozen=True)
class SummaryResult:
    text: str
    backend_used: SummaryBackendName
    llm_calls: int = 0


class SummaryBackendError(RuntimeError):
    pass


class SummaryAdapter:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _build_chat_model(self):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.summary_model,
            "temperature": 0,
            "timeout": self._settings.summary_timeout_s,
            "max_retries": 0,
            "max_tokens": self._settings.summary_max_tokens,
        }
        if self._settings.summary_openai_base_url:
            kwargs["base_url"] = self._settings.summary_openai_base_url
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    async def summarize_plan(self, *, intent: str, draft: PlanDraft) -> SummaryResult:
        backend = (self._settings.summary_backend or "auto").strip().lower()
        if backend == "auto":
            backend = "langchain" if (self._settings.summary_openai_base_url or self._settings.openai_api_key) else "legacy"
        if backend == "langchain":
            return await self._summarize_langchain(intent=intent, draft=draft)
        return self._summarize_legacy(intent=intent, draft=draft)

    def _summarize_legacy(self, *, intent: str, draft: PlanDraft) -> SummaryResult:
        log_llm_prompt_skipped(
            component="summary",
            backend="legacy",
            reason="summary_backend=legacy",
            metadata={"intent": intent, "step_count": len(draft.steps)},
        )
        text = (
            f"Intent: {intent.strip() or 'n/a'}. "
            f"Plan has {len(draft.steps)} step(s). Risk summary: {draft.risk_summary.strip()}."
        )
        return SummaryResult(text=text, backend_used="legacy", llm_calls=0)

    async def _summarize_langchain(self, *, intent: str, draft: PlanDraft) -> SummaryResult:
        try:
            from langchain_openai import ChatOpenAI
        except Exception as e:
            raise SummaryBackendError(
                "LangChain summary backend unavailable; install langchain-openai and configure API credentials."
            ) from e
        model = self._build_chat_model()
        prompt = (
            "Summarize this execution plan for operators in <=120 words.\n\n"
            f"Intent:\n{intent}\n\n"
            f"Plan explanation:\n{draft.plan_explanation}\n\n"
            f"Risk summary:\n{draft.risk_summary}\n"
        )
        log_llm_prompt(
            component="summary",
            backend="langchain",
            model=self._settings.summary_model,
            prompt=prompt,
            metadata={
                "intent": intent,
                "step_count": len(draft.steps),
            },
        )
        try:
            resp = await model.ainvoke(prompt)
        except Exception as e:
            raise SummaryBackendError(f"Summary backend call failed: {e}") from e
        content = (getattr(resp, "content", "") or "").strip()
        if not content:
            raise SummaryBackendError("Summary backend returned empty content.")
        return SummaryResult(text=content, backend_used="langchain", llm_calls=1)
