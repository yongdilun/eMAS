from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import httpx

from ...persistence.models import Approval as ApprovalRow
from ...persistence.models import Session as SessionRow
from ...persistence.models import Plan as PlanRow
from ...persistence.models import PlanStep as PlanStepRow
from ...persistence.models import generate_uuid
from ...schemas import ToolInfo
from ...observability.telemetry import log_event
from .result_summary import entity_label, compose_text, summarize_step_result, build_not_found_summary
from .tool_caller import materialize_endpoint


def approval_target_identifier(args: dict[str, Any]) -> Any | None:
    return (
        args.get("id")
        or args.get("machine_id")
        or args.get("job_id")
        or args.get("inventory_id")
        or args.get("material_id")
        or args.get("proposal_id")
        or args.get("approval_id")
    )


def is_preapproval_probe_candidate(tool: ToolInfo, args: dict[str, Any]) -> bool:
    if tool.method not in {"PUT", "PATCH", "DELETE"}:
        return False
    if "{id}" not in (tool.endpoint or ""):
        return False
    return approval_target_identifier(args) not in (None, "")


async def build_approval_risk_summary(
    engine: Any,
    *,
    tool: ToolInfo,
    args: dict[str, Any],
    target_preview: str | None = None,
) -> str:
    target = entity_label(args)
    fallback = f"This request will perform a write operation for {target}."
    if target_preview:
        fallback = f"{fallback} Target check: {target_preview}"
    prompt = (
        "Write one short approval risk summary for operators.\n"
        "Rules:\n"
        "- Mention this is a write-side effect.\n"
        "- Use only facts provided below.\n"
        "- One sentence, <= 25 words.\n\n"
        f"Tool: {tool.name}\n"
        f"Method: {tool.method}\n"
        f"Endpoint: {tool.endpoint}\n"
        f"Args: {json.dumps(args or {}, ensure_ascii=False)}\n"
        f"Target preview: {target_preview or ''}\n"
    )
    return await compose_text(
        engine,
        component="approval_risk_summary",
        prompt=prompt,
        fallback=fallback,
        metadata={"tool_name": tool.name},
    )


def bulk_risk_summary(settings: Any, tool: ToolInfo, step: PlanStepRow) -> str | None:
    state = step.bulk_state if isinstance(getattr(step, "bulk_state", None), dict) else {}
    total = int(state.get("total_items") or 0)
    if total <= 0:
        return None
    threshold = int(state.get("max_foreach_items") or settings.max_foreach_items)
    if total > threshold:
        return (
            f"This bulk write will run `{tool.name}` for {total} item(s), "
            f"which exceeds the safe threshold of {threshold}."
        )
    return f"This bulk write will run `{tool.name}` for {total} item(s)."


async def probe_entity_for_approval(
    engine: Any,
    *,
    endpoint: str,
    args: dict[str, Any],
    summary_tool_name: str,
) -> tuple[bool | None, str | None]:
    path_args = {"id": approval_target_identifier(args)}
    rendered_endpoint, leftover_path_args = materialize_endpoint(endpoint=endpoint, args=path_args)
    if leftover_path_args:
        path_args.update(leftover_path_args)
    url = f"{engine._settings.go_api_base_url}{rendered_endpoint}"
    try:
        async with httpx.AsyncClient(timeout=engine._settings.http_timeout_s) as client:
            resp = await client.get(url)
    except (httpx.TimeoutException, httpx.NetworkError):
        return None, None

    payload: dict[str, Any] | None = None
    try:
        if resp.content:
            parsed = resp.json()
            if isinstance(parsed, dict):
                payload = parsed
    except Exception:
        payload = None

    if resp.status_code == 404:
        summary = await build_not_found_summary(engine, tool_name=summary_tool_name, args=args, body=payload)
        return False, summary
    if resp.status_code >= 400:
        return None, None
    if isinstance(payload, dict):
        return True, await summarize_step_result(engine, tool_name=summary_tool_name, body=payload, args=args)
    return True, None


async def create_approval(
    engine: Any,
    db: Any,
    *,
    session_id: str,
    step: PlanStepRow,
    tool: ToolInfo,
    risk_summary_override: str | None = None,
) -> ApprovalRow:
    risk_summary = risk_summary_override
    if not risk_summary:
        risk_summary = await build_approval_risk_summary(engine, tool=tool, args=step.args or {})

    approval = ApprovalRow(
        approval_id=generate_uuid(),
        session_id=session_id,
        subject_type="step",
        plan_id=None,
        step_id=step.step_id,
        tool_name=tool.name,
        args=step.args,
        risk_summary=risk_summary,
        side_effect_level=tool.side_effect_level or "HIGH",
        status="PENDING",
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(approval)
    step.approval_id = approval.approval_id
    step.requires_approval = True
    session = await db.get(SessionRow, session_id)
    if session:
        session.version += 1
    await db.commit()
    await db.refresh(approval)
    log_event(
        "approval_created",
        session_id=session_id,
        step_id=step.step_id,
        tool=tool.name,
        side_effect_level=tool.side_effect_level,
    )
    return approval


async def preflight_approval_guard(
    engine: Any,
    *,
    session: SessionRow,
    plan: PlanRow,
    step: PlanStepRow,
    tool: ToolInfo,
    db: Any,
) -> tuple[bool, str | None]:
    args = step.args or {}
    if not is_preapproval_probe_candidate(tool=tool, args=args):
        return False, None

    exists, preview = await probe_entity_for_approval(
        engine,
        endpoint=tool.endpoint or "",
        args=args,
        summary_tool_name=tool.name,
    )
    if exists is False:
        generated = await build_not_found_summary(engine, tool_name=tool.name, args=args, body=None)
        summary = (preview or generated).strip()
        summary = f"{summary} No changes were made."
        step.status = "DONE"
        step.result = {"not_found": True, "_summary": summary, "preflight": True}
        step.result_summary = summary
        step.completed_at = datetime.utcnow()
        engine._log_step_status_change(session=session, plan=plan, step=step, tool=tool, status=step.status)
        from .result_summary import append_tool_result_message
        await append_tool_result_message(
            engine,
            db,
            session_id=session.session_id,
            step=step,
            intent=session.current_intent,
        )
        session.current_step_index += 1
        session.step_count += 1
        session.version += 1
        await db.commit()
        return True, None

    risk_summary_override = None
    if preview:
        risk_summary_override = await build_approval_risk_summary(engine, tool=tool, args=args, target_preview=preview)
    return False, risk_summary_override
