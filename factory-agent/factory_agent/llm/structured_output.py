"""Validate and coerce planner JSON into structured plan output."""

from __future__ import annotations

from typing import Any

from ..schemas import AgentPlanOutput
from .plan_parsing import _normalize_plan_dict


def parse_agent_plan_output(parsed: dict[str, Any]) -> AgentPlanOutput:
    normalized = _normalize_plan_dict(parsed)
    return AgentPlanOutput.model_validate(normalized)
