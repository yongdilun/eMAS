from __future__ import annotations

import inspect
from typing import Any

from factory_agent.schemas import ToolInfo


def _seeded_planner_handles_intent(*, planner: Any, intent: str) -> bool:
    handles_intent = getattr(planner, "handles_seeded_intent", None)
    return callable(handles_intent) and bool(handles_intent(intent))


def seeded_planner_compatibility_matches_approval(
    *,
    planner: Any,
    intent: str,
    approval_payload: dict[str, Any],
) -> bool:
    """Return whether a graph approval row belongs to the seeded planner adapter seam."""
    if not bool(getattr(planner, "is_seeded_playwright_adapter", False)):
        return False
    if not _seeded_planner_handles_intent(planner=planner, intent=intent):
        return False
    bundle_ui = approval_payload.get("bundle_ui") if isinstance(approval_payload.get("bundle_ui"), dict) else {}
    return bool(str(bundle_ui.get("kind") or "").strip())


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def generate_seeded_planner_compatibility_plan(
    *,
    planner: Any,
    intent: str,
    scoped_tools: list[ToolInfo],
    context: dict[str, Any],
) -> Any:
    """Compatibility owner for seeded planner adapters that still expose generate_plan()."""
    if not _seeded_planner_handles_intent(planner=planner, intent=intent):
        raise RuntimeError("seeded planner compatibility requires an adapter-declared intent")

    generate_plan = getattr(planner, "generate_plan", None)
    if not callable(generate_plan):
        raise RuntimeError("seeded planner compatibility adapter does not expose generate_plan")

    return await generate_plan(
        intent=intent,
        scoped_tools=scoped_tools,
        context=context,
    )


async def resume_seeded_planner_compatibility_approval(
    *,
    planner: Any,
    session_id: str,
    intent: str,
    approval_payload: dict[str, Any],
    approved: bool,
) -> Any:
    """Compatibility owner for seeded planner adapters that still expose approval resume."""
    if not seeded_planner_compatibility_matches_approval(
        planner=planner,
        intent=intent,
        approval_payload=approval_payload,
    ):
        raise RuntimeError("seeded planner compatibility approval did not match this adapter")

    seed_resume_context = getattr(planner, "seed_resume_context", None)
    if callable(seed_resume_context):
        await _maybe_await(
            seed_resume_context(
                session_id=session_id,
                intent=intent,
                approval_payload=approval_payload,
            )
        )

    resume_after_approval = getattr(planner, "resume_after_approval", None)
    if not callable(resume_after_approval):
        raise RuntimeError("seeded planner compatibility adapter does not expose resume_after_approval")

    return await resume_after_approval(
        session_id=session_id,
        approved=approved,
    )
