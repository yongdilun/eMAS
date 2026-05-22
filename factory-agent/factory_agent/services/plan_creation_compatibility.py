from __future__ import annotations

from typing import Any

from factory_agent.schemas import ToolInfo


async def generate_seeded_planner_compatibility_plan(
    *,
    planner: Any,
    intent: str,
    scoped_tools: list[ToolInfo],
    context: dict[str, Any],
) -> Any:
    """Compatibility owner for seeded planner adapters that still expose generate_plan()."""
    handles_intent = getattr(planner, "handles_seeded_intent", None)
    if not callable(handles_intent) or not handles_intent(intent):
        raise RuntimeError("seeded planner compatibility requires an adapter-declared intent")

    generate_plan = getattr(planner, "generate_plan", None)
    if not callable(generate_plan):
        raise RuntimeError("seeded planner compatibility adapter does not expose generate_plan")

    return await generate_plan(
        intent=intent,
        scoped_tools=scoped_tools,
        context=context,
    )
