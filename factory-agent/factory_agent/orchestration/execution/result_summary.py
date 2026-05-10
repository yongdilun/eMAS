from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ...persistence.models import Message as MessageRow
from ...persistence.models import Session as SessionRow
from ...persistence.models import PlanStep as PlanStepRow
from ...persistence.models import generate_uuid
from ...schemas import ToolInfo
from ...observability.telemetry import log_event, log_llm_prompt, log_llm_prompt_skipped
from ...analysis.presentation import extract_table_from_result
from ...analysis.tabular_analysis import analyze_result


def entity_label(args: dict[str, Any]) -> str:
    for key in ("id", "machine_id", "job_id", "inventory_id", "approval_id", "proposal_id", "line_id"):
        value = args.get(key)
        if value not in (None, ""):
            return f"{key}={value}"
    if args:
        first_key = next(iter(args.keys()))
        return f"{first_key}={args[first_key]}"
    return "target"


def tool_result_summary_backend(settings: Any) -> str:
    backend = (settings.tool_result_summary_backend or "auto").strip().lower()
    if backend == "auto":
        if settings.tool_result_summary_openai_base_url or settings.openai_api_key:
            return "langchain"
        return "deterministic"
    return backend


def is_soft_not_found(tool: ToolInfo, http_status: int | None, body: dict[str, Any] | None) -> bool:
    return bool(tool.is_read_only and tool.method == "GET" and http_status == 404 and isinstance(body, dict))


def result_has_records(body: dict[str, Any] | None) -> bool:
    if not isinstance(body, dict):
        return False
    data = body.get("data")
    if isinstance(data, list) and len(data) > 0:
        return True
    items = body.get("items")
    if isinstance(items, list) and len(items) > 0:
        return True
    data_count = body.get("data_count")
    try:
        if data_count is not None and int(data_count) > 0:
            return True
    except Exception:
        pass
    return False


def summarize_step_result_fallback(tool_name: str, body: dict[str, Any] | None) -> str:
    if body is None:
        return f"{tool_name} completed."
    if isinstance(body, dict):
        if body.get("not_found"):
            summary = body.get("_summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
        for key in ("message", "detail", "status", "summary"):
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                return f"{tool_name}: {val.strip()}"
        if isinstance(body.get("data"), list):
            return f"{tool_name} completed. Returned {len(body['data'])} record(s)."
        if isinstance(body.get("items"), list):
            return f"{tool_name} completed. Retrieved {len(body['items'])} item(s)."
        keys = ", ".join(list(body.keys())[:4])
        return f"{tool_name} completed. Response keys: {keys or 'none'}."
    return f"{tool_name} completed."


async def compose_text(
    engine: Any,
    *,
    component: str,
    prompt: str,
    fallback: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    backend = tool_result_summary_backend(engine._settings)
    if backend != "langchain":
        log_llm_prompt_skipped(
            component=component,
            backend=backend,
            reason="text_backend!=langchain",
            metadata=metadata or {},
        )
        return fallback

    try:
        from langchain_openai import ChatOpenAI  # noqa: F401
    except Exception:
        log_llm_prompt_skipped(
            component=component,
            backend=backend,
            reason="langchain_openai_unavailable",
            metadata=metadata or {},
        )
        return fallback

    log_llm_prompt(
        component=component,
        backend=backend,
        model=engine._settings.tool_result_summary_model,
        prompt=prompt,
        metadata=metadata or {},
    )
    try:
        model = engine._build_text_model()
        resp = await model.ainvoke(prompt)
        content = (getattr(resp, "content", "") or "").strip()
        if not content:
            return fallback
        return content.replace("\n", " ").strip()
    except Exception as exc:
        log_event(
            f"{component}_failed",
            level="WARNING",
            error=str(exc),
            **(metadata or {}),
        )
        return fallback


async def build_not_found_summary(engine: Any, *, tool_name: str, args: dict[str, Any], body: dict[str, Any] | None) -> str:
    detail = (body or {}).get("detail")
    if isinstance(detail, str) and detail.strip():
        fallback = detail.strip()
    else:
        target = (
            args.get("id")
            or args.get("machine_id")
            or args.get("job_id")
            or args.get("material_id")
            or args.get("inventory_id")
            or args.get("proposal_id")
            or args.get("approval_id")
        )
        fallback = (
            f"Requested resource {target} was not found."
            if target not in (None, "")
            else "Requested resource was not found."
        )

    prompt = (
        "Write one short operator-facing sentence for a not-found tool call.\n"
        "Rules:\n"
        "- Use only the provided tool name, args, and response body.\n"
        "- Do not invent entities or IDs.\n"
        "- Keep <= 20 words.\n\n"
        f"Tool: {tool_name}\n"
        f"Args: {json.dumps(args or {}, ensure_ascii=False)}\n"
        f"Response: {json.dumps(body or {}, ensure_ascii=False)}\n"
    )
    generated = await compose_text(
        engine,
        component="not_found_summary",
        prompt=prompt,
        fallback=fallback,
        metadata={"tool_name": tool_name},
    )
    if "not found" not in generated.lower():
        return fallback
    return generated


async def build_completion_text(engine: Any, *, plan_kind: str, step_count: int) -> str:
    fallback = (
        "Safe discovery completed. Preparing execution proposal."
        if (plan_kind or "execution") == "discovery"
        else f"Execution completed successfully. {step_count} step(s) completed."
    )
    prompt = (
        "Write one short completion message for a workflow engine.\n"
        "Rules:\n"
        "- One sentence.\n"
        "- Mention completion outcome.\n"
        "- Use only the context below.\n\n"
        f"Plan kind: {plan_kind}\n"
        f"Completed steps: {step_count}\n"
    )
    return await compose_text(
        engine,
        component="session_completion_text",
        prompt=prompt,
        fallback=fallback,
        metadata={"plan_kind": plan_kind, "step_count": step_count},
    )


async def summarize_step_result(
    engine: Any,
    *,
    tool_name: str,
    body: dict[str, Any] | None,
    args: dict[str, Any] | None = None,
    intent: str | None = None,
) -> str:
    fallback = summarize_step_result_fallback(tool_name=tool_name, body=body)
    if not isinstance(body, dict):
        return fallback
    render_context = extract_table_from_result(tool_name=tool_name, result=body, intent=intent)

    facts = await engine._reasoning.extract_facts(
        intent=intent or "tool_result_summary",
        tool_name=tool_name,
        args=args or {},
        result=body,
    )
    if facts:
        policy = engine._reasoning.response_policy(facts=facts)
        deterministic_contract = engine._reasoning.deterministic_response_contract(facts=facts)
        if policy == "deterministic" and deterministic_contract:
            return deterministic_contract
        if policy == "deterministic":
            return engine._reasoning.fallback_response_from_facts(facts=facts)
        if not engine._reasoning.should_generate_response(facts=facts):
            return engine._reasoning.fallback_response_from_facts(facts=facts)
        generated = await engine._reasoning.generate_response(
            intent=intent or "tool_result_summary",
            facts=facts,
            render_context=render_context,
        )
        if generated:
            grounded = await engine._reasoning.verify_grounding(response_text=generated, facts=facts)
            if grounded:
                return generated
            return engine._reasoning.fallback_response_from_facts(facts=facts)
        return engine._reasoning.fallback_response_from_facts(facts=facts)

    prompt_payload = body
    try:
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True)
        if len(raw) > 3500:
            raw = raw[:3500] + "..."
            prompt_payload = {"truncated": True, "preview": raw}
    except Exception:
        prompt_payload = {"unserializable": True}

    prompt = (
        "You are writing a short operator-facing status message for a factory tool result.\n"
        "Rules:\n"
        "- Use only facts present in the result JSON.\n"
        "- Never invent IDs or statuses.\n"
        "- Keep it short (1 sentence, <= 25 words).\n"
        "- Use simple language.\n\n"
        f"Tool: {tool_name}\n"
        f"Tool Args: {json.dumps(args or {}, ensure_ascii=False)}\n"
        f"Result JSON: {json.dumps(prompt_payload, ensure_ascii=False)}\n"
    )
    return await compose_text(
        engine,
        component="tool_result_summary",
        prompt=prompt,
        fallback=fallback,
        metadata={"tool_name": tool_name},
    )


def attach_result_analysis(body: dict[str, Any] | None, intent: str | None) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        return body
    analysis = analyze_result(intent=intent or "", result=body)
    if analysis is None:
        return body
    from dataclasses import asdict
    enriched = dict(body)
    enriched["_analysis"] = {
        "dataset": asdict(analysis.dataset),
        "operations": [asdict(operation) for operation in analysis.operations],
        "results": analysis.results,
        "facts": analysis.facts,
        "grounding_refs": analysis.grounding_refs,
    }
    return enriched


async def append_tool_result_message(
    engine: Any,
    db: Any,
    *,
    session_id: str,
    step: PlanStepRow,
    intent: str | None = None,
) -> None:
    text = step.result_summary or await summarize_step_result(
        engine,
        tool_name=step.tool_name,
        body=step.result,
        args=step.args,
        intent=intent,
    )
    msg = MessageRow(
        message_id=generate_uuid(),
        session_id=session_id,
        role="tool_result",
        content=text,
        step_id=step.step_id,
        tool_name=step.tool_name,
    )
    db.add(msg)
    await engine._memory_manager.index_message(
        db,
        session_id=session_id,
        message_id=msg.message_id,
        role="tool_result",
        content=text,
        tool_name=step.tool_name,
        commit=False,
    )
