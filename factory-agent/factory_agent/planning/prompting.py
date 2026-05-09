from __future__ import annotations

import json
from typing import Any

from ..schemas import PlanDraft


PLANNER_SYSTEM_INSTRUCTIONS = """You are the Factory Operations planning agent.

Return ONLY valid JSON that matches the provided JSON Schema.

Requirements:
- Keep plans <= 10 steps unless absolutely necessary.
- Prefer read-only tools first (GET) before writes (POST/PATCH/DELETE).
- When the user asks for IDs-only or a narrow subset, prefer tools/args that return minimal fields (for example query params like `fields`, `select`, `limit`).
- For every step: choose a tool_name from the provided tool list.
  - For read-only steps (requires_approval=false): provide args that fully satisfy the tool's input schema.
  - For approval-gated steps (requires_approval=true): you may provide partial args when the user has not provided all required fields.
    The system will request missing fields from the user during approval before executing the tool.
- Include explainability fields:
  - plan_explanation: plain-English description of what the plan will do and why.
  - risk_summary: highlight irreversible actions and failure modes.
"""


def get_plan_draft_json_schema() -> dict[str, Any]:
    # Return the concrete schema for PlanDraft (stable across pydantic versions).
    return PlanDraft.model_json_schema()


def build_planner_prompt(*, user_goal: str, tools_markdown: str, scoped_tool_names: list[str]) -> str:
    schema = get_plan_draft_json_schema()
    scoped_list = "\n".join(f"- {name}" for name in scoped_tool_names)

    return "\n\n".join(
        [
            PLANNER_SYSTEM_INSTRUCTIONS.strip(),
            "User goal:",
            user_goal.strip(),
            "Allowed tools (scoped subset):",
            scoped_list or "- (none)",
            "Tool reference (tools.md):",
            tools_markdown.strip(),
            "JSON Schema for your response:",
            json.dumps(schema, indent=2, ensure_ascii=False),
        ]
    )

