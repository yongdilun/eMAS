from __future__ import annotations

import json
from typing import Any

from pydantic.json_schema import models_json_schema

from .schemas import PlanDraft


PLANNER_SYSTEM_INSTRUCTIONS = """You are the Factory Operations planning agent.

Return ONLY valid JSON that matches the provided JSON Schema.

Requirements:
- Keep plans <= 10 steps unless absolutely necessary.
- Prefer read-only tools first (GET) before writes (POST/PATCH/DELETE).
- For every step: choose a tool_name from the provided tool list and provide args matching the tool's input schema.
- Include explainability fields:
  - plan_explanation: plain-English description of what the plan will do and why.
  - risk_summary: highlight irreversible actions and failure modes.
"""


def get_plan_draft_json_schema() -> dict[str, Any]:
    schema, _ = models_json_schema([(PlanDraft, "validation")])
    return schema


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

