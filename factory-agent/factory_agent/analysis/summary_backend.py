from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from ..config import Settings
from ..schemas import PlanDraft
from ..observability.telemetry import log_llm_prompt, log_llm_prompt_skipped
from .answer_model import render_answer_model_markdown
from .result_normalizer import normalize_tool_result


SummaryBackendName = Literal["deterministic", "langchain"]
BundleNarrativeKind = Literal["awaiting_approval", "completed"]
SUMMARY_PLAN_LANGCHAIN_PROMPT_CONTRACT = "summary_plan_langchain_v1"


def awaiting_approval_markdown_from_bundle_ui(facts: dict[str, Any]) -> str | None:
    """Fixed narrative when ``facts["approval"]["bundle_ui"]`` carries the job table.

    The client renders ``bundle_ui`` as a native table; ``risk_summary`` must not repeat
    per-job rows or markdown tables (avoids fighting the UI and saves LLM tokens).
    """
    ap = facts.get("approval") if isinstance(facts.get("approval"), dict) else {}
    bui = ap.get("bundle_ui") if isinstance(ap.get("bundle_ui"), dict) else None
    if not bui or not str(bui.get("headline") or "").strip():
        return None
    hl = str(bui["headline"]).strip()
    return "\n".join(
        [
            hl,
            "",
            "The change list is shown in the in-app table below.",
            "",
            "Please approve to continue.",
        ]
    ).strip()


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
        previous_priority = str(
            data.get("previous_priority")
            or data.get("_previous_priority")
            or args.get("previous_priority")
            or ""
        ).strip().lower()
        source_state_basis = str(
            data.get("source_state_basis")
            or data.get("_source_state_basis")
            or args.get("source_state_basis")
            or ""
        ).strip().lower()
        approval_id = str(
            data.get("approval_id")
            or data.get("_approval_id")
            or row.get("approval_id")
            or ""
        ).strip()
        items.append(
            {
                "id": rid,
                "product_id": product_id,
                "status": status,
                "deadline": deadline,
                "priority": priority,
                "previous_priority": previous_priority,
                "source_state_basis": source_state_basis,
                "approval_id": approval_id,
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

    grouped_lines = _priority_write_set_summary_lines(ordered)
    if grouped_lines:
        lines: list[str] = ["**Success**", ""]
        if intent and len(intent) < 280:
            lines.append(intent)
            lines.append("")
        group_count = len(grouped_lines)
        lines.append(f"Updated **{n}** job(s) across **{group_count}** write set(s).")
        lines.append("")
        lines.extend(f"- {line}" for line in grouped_lines)
        lines.append("")
        lines.append("No jobs were created or deleted.")
        lines.append("")
        lines.append("Affected records:")
        lines.append("")
        for i, j in enumerate(ordered, start=1):
            prev = j.get("previous_priority") or "unknown"
            new = j.get("priority") or "unknown"
            lines.append(f"{i}. **{j['id']}**")
            lines.append(f"   - Previous Priority: **{prev}**")
            lines.append(f"   - New Priority: **{new}**")
            if j["product_id"]:
                lines.append(f"   - Product: **{j['product_id']}**")
            if j["status"]:
                lines.append(f"   - Status: **{j['status']}**")
            lines.append("")
        return "\n".join(lines).strip()

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


def _priority_write_set_summary_lines(items: list[dict[str, str]]) -> list[str]:
    """Summarize multi-approval priority updates by previous/new priority."""
    if not items:
        return []
    if not all(item.get("previous_priority") and item.get("priority") for item in items):
        return []

    groups: list[dict[str, Any]] = []
    group_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (
            item.get("previous_priority") or "",
            item.get("priority") or "",
            item.get("source_state_basis") or "",
            item.get("approval_id") or "",
        )
        group = group_by_key.get(key)
        if group is None:
            group = {
                "previous_priority": key[0],
                "priority": key[1],
                "source_state_basis": key[2],
                "approval_id": key[3],
                "ids": [],
            }
            group_by_key[key] = group
            groups.append(group)
        group["ids"].append(item["id"])

    if len(groups) <= 1:
        return []

    lines: list[str] = []
    earlier_targets: set[str] = set()
    for group in groups:
        count = len(group["ids"])
        previous = str(group["previous_priority"])
        new = str(group["priority"])
        basis = str(group.get("source_state_basis") or "")
        approval_id = str(group.get("approval_id") or "")
        original = previous in earlier_targets or (basis == "original" and bool(lines))
        original_text = "original " if original else ""
        job_word = "job" if count == 1 else "jobs"
        line = f"{count} {original_text}{previous} priority {job_word} changed to {new}"
        if approval_id:
            line += f" under approval {approval_id}"
        lines.append(line)
        if new:
            earlier_targets.add(new)
    return lines


def _entity_recap_markdown_from_facts(facts: dict[str, Any]) -> str | None:
    """Readable recap for single-entity GET results using the generic AnswerModel."""
    rows = facts.get("tool_outputs")
    if not isinstance(rows, list) or not rows:
        return None

    answers: list[str] = []
    intent = str(facts.get("intent") or "").strip()
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Skip write-side tools
        tn = str(row.get("tool_name") or "")
        if re.search(r"\b(post|put|patch|delete)\b", tn, re.IGNORECASE):
            continue
        # Try raw result dict first, then parse excerpt
        result = row.get("result")
        if not isinstance(result, dict):
            excerpt = row.get("result_excerpt")
            if isinstance(excerpt, str) and excerpt.strip():
                try:
                    result = json.loads(excerpt)
                except Exception:
                    result = None
            if not isinstance(result, dict):
                continue
        answer = normalize_tool_result(
            tool_name=tn,
            endpoint=None,
            result=result,
            intent=intent,
        )
        if answer is not None:
            answers.append(render_answer_model_markdown(answer))

    if not answers:
        return None
    return "\n\n".join(answers)


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
        # Optional prompt lane: most production narratives are deterministic; this
        # branch is only used when SUMMARY_BACKEND explicitly resolves to langchain.
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

    def _deterministic_bundle_narrative(self, *, intent: str, kind: BundleNarrativeKind, facts: dict[str, Any]) -> str:
        if kind == "awaiting_approval":
            structured = awaiting_approval_markdown_from_bundle_ui(facts)
            if structured is not None:
                return structured
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
        entity_recap = _entity_recap_markdown_from_facts(facts)
        if entity_recap:
            return entity_recap
        plan_explanation = facts.get("plan_explanation")
        if isinstance(plan_explanation, str) and plan_explanation.strip():
            return f"**Success**\n\n{plan_explanation.strip()}"
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
        if kind == "completed":
            recap = _job_recap_markdown_from_facts(facts)
            if recap:
                log_llm_prompt_skipped(
                    component="bundle_narrative",
                    backend="deterministic",
                    reason="completed_job_write_recap",
                    metadata={"intent": intent, "kind": kind},
                )
                return SummaryResult(text=recap, backend_used="deterministic", llm_calls=0)
            entity_recap = _entity_recap_markdown_from_facts(facts)
            if entity_recap:
                log_llm_prompt_skipped(
                    component="bundle_narrative",
                    backend="deterministic",
                    reason="completed_entity_lookup_recap",
                    metadata={"intent": intent, "kind": kind},
                )
                return SummaryResult(text=entity_recap, backend_used="deterministic", llm_calls=0)

        if kind == "awaiting_approval":
            structured = awaiting_approval_markdown_from_bundle_ui(facts)
            if structured is not None:
                log_llm_prompt_skipped(
                    component="bundle_narrative",
                    backend="deterministic",
                    reason="awaiting_approval_bundle_ui",
                    metadata={"intent": intent, "kind": kind},
                )
                return SummaryResult(text=structured, backend_used="deterministic", llm_calls=0)

        log_llm_prompt_skipped(
            component="bundle_narrative",
            backend="deterministic",
            reason="fallback_deterministic",
            metadata={"intent": intent, "kind": kind},
        )
        return SummaryResult(
            text=self._deterministic_bundle_narrative(intent=intent, kind=kind, facts=facts),
            backend_used="deterministic",
            llm_calls=0,
        )

