from __future__ import annotations

import os
import re
from typing import Any

from factory_agent.schemas import ToolInfo


_RULES: list[dict[str, Any]] = []


def seeded_tool_faults_enabled() -> bool:
    return os.getenv("FACTORY_AGENT_PLAYWRIGHT_SEEDED_MODE", "0").strip().lower() in {"1", "true", "yes"}


def configure_tool_faults(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not seeded_tool_faults_enabled():
        clear_tool_faults()
        return []
    _RULES.clear()
    for rule in rules:
        normalized = _normalize_rule(rule)
        if normalized is not None:
            _RULES.append(normalized)
    return list_tool_faults()


def clear_tool_faults() -> None:
    _RULES.clear()


def list_tool_faults() -> list[dict[str, Any]]:
    return [dict(rule, hits=int(rule.get("hits") or 0)) for rule in _RULES]


def maybe_inject_tool_fault(*, tool: ToolInfo, args: dict[str, Any]) -> dict[str, Any] | None:
    if not seeded_tool_faults_enabled() or not _RULES:
        return None

    for index, rule in enumerate(list(_RULES)):
        if not _matches_rule(rule=rule, tool=tool, args=args):
            continue
        rule["hits"] = int(rule.get("hits") or 0) + 1
        if rule.get("once", True):
            del _RULES[index]
        return _fault_envelope(rule=rule, tool=tool)
    return None


def _normalize_rule(rule: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(rule, dict):
        return None
    fault = str(rule.get("fault") or "timeout").strip().lower()
    if fault not in {"timeout", "network", "http_500", "http_error", "empty_data"}:
        fault = "timeout"
    normalized = {
        "fault": fault,
        "once": bool(rule.get("once", True)),
        "reason": str(rule.get("reason") or f"Controlled seeded tool fault: {fault}"),
        "tool_name": _optional_str(rule.get("tool_name")),
        "method": _optional_str(rule.get("method")).upper() if _optional_str(rule.get("method")) else None,
        "endpoint": _optional_str(rule.get("endpoint")),
        "endpoint_pattern": _optional_str(rule.get("endpoint_pattern")),
        "capability_tags_any": [
            str(tag).strip().lower()
            for tag in (rule.get("capability_tags_any") or [])
            if str(tag).strip()
        ],
        "hits": 0,
    }
    if not any(
        normalized.get(key)
        for key in ("tool_name", "method", "endpoint", "endpoint_pattern", "capability_tags_any")
    ):
        return None
    return normalized


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _matches_rule(*, rule: dict[str, Any], tool: ToolInfo, args: dict[str, Any]) -> bool:
    del args
    if rule.get("tool_name") and str(tool.name) != str(rule["tool_name"]):
        return False
    if rule.get("method") and str(tool.method).upper() != str(rule["method"]).upper():
        return False
    if rule.get("endpoint") and str(tool.endpoint) != str(rule["endpoint"]):
        return False
    endpoint_pattern = rule.get("endpoint_pattern")
    if endpoint_pattern:
        try:
            if not re.search(str(endpoint_pattern), str(tool.endpoint)):
                return False
        except re.error:
            return False
    tags = {str(tag).strip().lower() for tag in (tool.capability_tags or [])}
    expected_tags = set(rule.get("capability_tags_any") or [])
    if expected_tags and tags.isdisjoint(expected_tags):
        return False
    return True


def _fault_envelope(*, rule: dict[str, Any], tool: ToolInfo) -> dict[str, Any]:
    fault = str(rule.get("fault") or "timeout")
    reason = str(rule.get("reason") or f"Controlled seeded tool fault: {fault}")
    base_body = {
        "error_type": fault,
        "message": reason,
        "fault_injected": True,
        "tool_name": tool.name,
        "no_fake_completion": True,
    }
    if fault == "network":
        base_body["error_type"] = "network"
        return {
            "ok": False,
            "http_status": None,
            "body": base_body,
            "latency_ms": 0,
            "infrastructure_error": True,
        }
    if fault in {"http_500", "http_error"}:
        base_body["error_type"] = "http_error"
        return {
            "ok": False,
            "http_status": 503,
            "body": base_body,
            "latency_ms": 0,
            "infrastructure_error": True,
        }
    if fault == "empty_data":
        return {
            "ok": True,
            "http_status": 200,
            "body": {
                "data": {},
                "fault_injected": True,
                "message": reason,
                "tool_name": tool.name,
                "no_fake_completion": True,
            },
            "latency_ms": 0,
            "infrastructure_error": False,
        }
    base_body["error_type"] = "timeout"
    return {
        "ok": False,
        "http_status": None,
        "body": base_body,
        "latency_ms": 0,
        "infrastructure_error": True,
    }


__all__ = [
    "clear_tool_faults",
    "configure_tool_faults",
    "list_tool_faults",
    "maybe_inject_tool_fault",
    "seeded_tool_faults_enabled",
]
