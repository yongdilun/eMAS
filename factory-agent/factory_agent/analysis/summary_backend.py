from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from ..config import Settings
from ..schemas import PlanDraft
from ..observability.telemetry import log_llm_prompt, log_llm_prompt_skipped


SummaryBackendName = Literal["deterministic", "langchain"]
BundleNarrativeKind = Literal["awaiting_approval", "completed"]


@dataclass(frozen=True)
class SummaryResult:
    text: str
    backend_used: SummaryBackendName
    llm_calls: int = 0


class SummaryBackendError(RuntimeError):
    pass


def compact_tool_outputs_for_narrative(
    tool_outputs: list[dict[str, Any]] | None,
    *,
    max_items: int = 32,
    excerpt_chars: int = 1600,
) -> list[dict[str, Any]]:
    """Shrink tool result bodies for LLM prompts (keep tool_name + args + excerpt)."""
    out: list[dict[str, Any]] = []
    if not tool_outputs:
        return out
    for row in tool_outputs[:max_items]:
        if not isinstance(row, dict):
            continue
        body = row.get("result")
        excerpt = ""
        if isinstance(body, dict):
            try:
                excerpt = json.dumps(body, ensure_ascii=False, default=str)
            except Exception:
                excerpt = str(body)
        else:
            excerpt = str(body) if body is not None else ""
        if len(excerpt) > excerpt_chars:
            excerpt = excerpt[:excerpt_chars] + "…"
        out.append(
            {
                "tool_name": row.get("tool_name"),
                "http_status": row.get("http_status"),
                "args": row.get("args"),
                "result_excerpt": excerpt,
            }
        )
    return out


_JOB_TOOL_RE = re.compile(r"(put|patch)__jobs", re.IGNORECASE)


def _parse_json_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _result_data_dict(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    if isinstance(data, dict):
        return data
    return body


def _job_recap_markdown_from_facts(facts: dict[str, Any]) -> str | None:
    """Readable post-commit recap when tool_outputs contain job PUT/PATCH bodies."""
    rows = facts.get("tool_outputs")
    if not isinstance(rows, list) or not rows:
        return None
    items: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tn = str(row.get("tool_name") or "")
        if not _JOB_TOOL_RE.search(tn):
            continue
        args = row.get("args") if isinstance(row.get("args"), dict) else {}
        job_id = str(args.get("id") or args.get("job_id") or "").strip()
        body = _parse_json_dict(row.get("result_excerpt")) or _parse_json_dict(row.get("result"))
        if not isinstance(body, dict):
            continue
        data = _result_data_dict(body)
        if not isinstance(data, dict):
            continue
        rid = str(data.get("job_id") or data.get("id") or job_id).strip()
        if not rid:
            continue
        product_id = str(data.get("product_id") or "").strip()
        status = str(data.get("status") or "").strip()
        deadline = str(data.get("deadline") or "").strip()
        priority = str(data.get("priority") or args.get("priority") or "").strip().lower()
        items.append(
            {
                "id": rid,
                "product_id": product_id,
                "status": status,
                "deadline": deadline,
                "priority": priority,
            }
        )
    if not items:
        return None
    by_id: dict[str, dict[str, str]] = {}
    for it in items:
        by_id[it["id"]] = it
    ordered = list(by_id.values())
    n = len(ordered)
    intent = str(facts.get("intent") or "").strip()
    lines: list[str] = ["**Success**", ""]
    if intent and len(intent) < 280:
        lines.append(intent)
        lines.append("")
    lines.append(f"Updated **{n}** job(s).")
    lines.append("")
    lines.append("No jobs were created or deleted.")
    lines.append("")
    for i, j in enumerate(ordered, start=1):
        dl = j["deadline"].replace("T", " ")[:19] if j["deadline"] else ""
        block = [f"{i}. **{j['id']}**"]
        if j["priority"]:
            block.append(f"   - Priority: **{j['priority']}**")
        if j["product_id"]:
            block.append(f"   - Product: **{j['product_id']}**")
        if j["status"]:
            block.append(f"   - Status: **{j['status']}**")
        if dl:
            block.append(f"   - Deadline: **{dl}**")
        lines.append("\n".join(block))
        lines.append("")
    return "\n".join(lines).strip()


def _sanitize_completed_bundle_text(text: str) -> str:
    """Strip approval-wait phrases if the model echoes them on completed bundles."""
    t = (text or "").strip()
    if not t:
        return t
    out_lines: list[str] = []
    for line in t.splitlines():
        sl = line.strip().lower()
        if sl.startswith("please approve"):
            continue
        if sl.startswith("waiting for your approval"):
            continue
        out_lines.append(line)
    cleaned = "\n".join(out_lines).strip()
    return cleaned or t


class SummaryAdapter:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _build_chat_model(self, *, max_tokens: int | None = None):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.summary_model,
            "temperature": 0,
            "timeout": self._settings.summary_timeout_s,
            "max_retries": 0,
            "max_tokens": int(max_tokens if max_tokens is not None else self._settings.summary_max_tokens),
        }
        if self._settings.summary_openai_base_url:
            kwargs["base_url"] = self._settings.summary_openai_base_url
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    async def summarize_plan(self, *, intent: str, draft: PlanDraft) -> SummaryResult:
        # If there are no steps, this is a conversational or RAG reply.
        # We skip re-summarization to preserve citations and avoid "execution plan" mentions.
        if not draft.steps:
            return SummaryResult(text=draft.plan_explanation, backend_used="deterministic", llm_calls=0)

        backend = (self._settings.summary_backend or "auto").strip().lower()
        if backend == "auto":
            backend = "langchain" if (self._settings.summary_openai_base_url or self._settings.openai_api_key) else "deterministic"
        if backend == "langchain":
            return await self._summarize_langchain(intent=intent, draft=draft)
        return self._summarize_deterministic(intent=intent, draft=draft)

    def _summarize_deterministic(self, *, intent: str, draft: PlanDraft) -> SummaryResult:
        log_llm_prompt_skipped(
            component="summary",
            backend="deterministic",
            reason="summary_backend=deterministic",
            metadata={"intent": intent, "step_count": len(draft.steps)},
        )
        text = (
            f"Intent: {intent.strip() or 'n/a'}. "
            f"Plan has {len(draft.steps)} step(s). Risk summary: {draft.risk_summary.strip()}."
        )
        return SummaryResult(text=text, backend_used="deterministic", llm_calls=0)

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

    def _facts_json(self, facts: dict[str, Any], *, max_chars: int = 18_000) -> str:
        try:
            raw = json.dumps(facts, ensure_ascii=False, default=str)
        except Exception:
            raw = "{}"
        if len(raw) <= max_chars:
            return raw
        return raw[:max_chars] + "\n…(truncated)"

    def _deterministic_bundle_narrative(self, *, intent: str, kind: BundleNarrativeKind, facts: dict[str, Any]) -> str:
        if kind == "awaiting_approval":
            ap = facts.get("approval") if isinstance(facts.get("approval"), dict) else {}
            preview = ap.get("preview") if isinstance(ap.get("preview"), list) else []
            lines: list[str] = []
            head = (intent or "").strip() or "This action needs your approval before it can run."
            lines.append(head)
            lines.append("")
            if preview:
                lines.append(f"This bundle will touch **{ap.get('count', len(preview))}** write(s). Preview:")
                lines.append("")
                for i, row in enumerate(preview, start=1):
                    if not isinstance(row, dict):
                        continue
                    tn = str(row.get("tool_name") or "tool")
                    args = row.get("args") if isinstance(row.get("args"), dict) else {}
                    lines.append(f"{i}. `{tn}` — `{args}`")
                lines.append("")
            lines.append("Please approve to continue.")
            return "\n".join(lines).strip()

        # completed
        recap = _job_recap_markdown_from_facts(facts)
        if recap:
            return recap
        steps = facts.get("steps") if isinstance(facts.get("steps"), list) else []
        lines = ["**Success**", "", (intent or "").strip() or "Execution completed."]
        if steps:
            lines.append("")
            lines.append("Plan steps:")
            for i, s in enumerate(steps[:24], start=1):
                if not isinstance(s, dict):
                    continue
                lines.append(f"{i}. {s.get('tool_name')} — args={s.get('args')}")
        return "\n".join(lines).strip()

    async def synthesize_bundle_markdown(
        self,
        *,
        intent: str,
        kind: BundleNarrativeKind,
        facts: dict[str, Any],
    ) -> SummaryResult:
        """LLM-written Markdown for approval wait copy or post-commit recap (structured facts in JSON)."""
        backend = (self._settings.summary_backend or "auto").strip().lower()
        if backend == "auto":
            backend = "langchain" if (self._settings.summary_openai_base_url or self._settings.openai_api_key) else "deterministic"
        if backend == "deterministic":
            log_llm_prompt_skipped(
                component="bundle_narrative",
                backend="deterministic",
                reason="summary_backend=deterministic",
                metadata={"intent": intent, "kind": kind},
            )
            return SummaryResult(
                text=self._deterministic_bundle_narrative(intent=intent, kind=kind, facts=facts),
                backend_used="deterministic",
                llm_calls=0,
            )
        return await self._synthesize_bundle_langchain(intent=intent, kind=kind, facts=facts)

    async def _synthesize_bundle_langchain(
        self,
        *,
        intent: str,
        kind: BundleNarrativeKind,
        facts: dict[str, Any],
    ) -> SummaryResult:
        try:
            from langchain_openai import ChatOpenAI  # noqa: F401
        except Exception as e:
            raise SummaryBackendError(
                "LangChain summary backend unavailable; install langchain-openai and configure API credentials."
            ) from e
        model = self._build_chat_model(max_tokens=max(900, int(self._settings.summary_max_tokens or 512)))
        facts_block = self._facts_json(facts)
        if kind == "awaiting_approval":
            prompt = (
                "You are writing a short, friendly Markdown message for an operator who must approve a backend write "
                "bundle in a factory scheduling assistant.\n\n"
                "Rules:\n"
                "- Use ONLY information present in the JSON facts (intent + approval payload). "
                "Never invent job IDs, priorities, products, deadlines, or counts.\n"
                "- If the approval preview lists jobs with fields like id, job_id, priority, product_id, status, "
                "deadline, mirror them in a clear numbered list. Show current vs requested priority when both exist.\n"
                "- If you cannot list entities because data is missing, summarize what is known and what will happen.\n"
                "- Do NOT include HTML or wide markdown tables.\n"
                "- End with the exact line: Please approve to continue.\n\n"
                f"User intent:\n{intent}\n\n"
                f"Facts JSON:\n{facts_block}\n"
            )
        else:
            prompt = (
                "You are writing a concise Markdown completion recap for the user after writes succeeded.\n\n"
                "Rules:\n"
                "- Start with a first line exactly: **Success** then a blank line.\n"
                "- Use ONLY the JSON facts (intent, plan fields, steps, tool output excerpts). "
                "Never invent rows or field values.\n"
                "- Prefer a numbered list per job when job records appear in tool output excerpts (id/job_id, priority, "
                "product_id, status, deadline).\n"
                "- State explicitly whether jobs were created or deleted only if facts support it; otherwise say nothing "
                "or say there were no creates/deletes if the steps are updates only.\n"
                "- Do NOT dump raw JSON; no HTML tables.\n"
                "- Do NOT write 'Please approve', 'Please approve to continue', or 'Waiting for your approval' "
                "(this run already finished).\n"
                "- Keep it readable and scannable (blank line between numbered items is fine).\n\n"
                f"User intent:\n{intent}\n\n"
                f"Facts JSON:\n{facts_block}\n"
            )
        log_llm_prompt(
            component="bundle_narrative",
            backend="langchain",
            model=self._settings.summary_model,
            prompt=prompt,
            metadata={"intent": intent, "kind": kind},
        )
        try:
            resp = await model.ainvoke(prompt)
        except Exception as e:
            raise SummaryBackendError(f"Bundle narrative call failed: {e}") from e
        content = (getattr(resp, "content", "") or "").strip()
        if not content:
            raise SummaryBackendError("Bundle narrative returned empty content.")
        if kind == "completed":
            content = _sanitize_completed_bundle_text(content)
        if not content:
            content = _job_recap_markdown_from_facts(facts) or ""
        if not content:
            raise SummaryBackendError("Bundle narrative returned empty content after sanitization.")
        return SummaryResult(text=content, backend_used="langchain", llm_calls=1)


