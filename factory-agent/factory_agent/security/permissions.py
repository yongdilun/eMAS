from __future__ import annotations

from typing import Any

from ..schemas import ToolInfo


ROLE_ORDER = {
    "viewer": 0,
    "planner": 1,
    "manager": 2,
    "admin": 3,
}


def role_from_claims(claims: dict[str, Any] | None, *, default: str = "admin") -> str:
    if not isinstance(claims, dict):
        return default
    for key in ("role", "user_role", "x-user-role"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    roles = claims.get("roles")
    if isinstance(roles, list):
        normalized = [str(role).strip().lower() for role in roles if str(role).strip()]
        if normalized:
            return max(normalized, key=lambda role: ROLE_ORDER.get(role, -1))
    scope = claims.get("scope")
    if isinstance(scope, str):
        scopes = {part.strip().lower() for part in scope.split() if part.strip()}
        for role in ("admin", "manager", "planner", "viewer"):
            if role in scopes or f"role:{role}" in scopes:
                return role
    return default


def tool_allowed_for_role(tool: ToolInfo, role: str) -> bool:
    normalized_role = (role or "viewer").strip().lower()
    allowed = [item.strip().lower() for item in (tool.allowed_roles or []) if item.strip()]
    if allowed:
        return normalized_role in allowed
    if tool.is_read_only or tool.method == "GET":
        return normalized_role in {"viewer", "planner", "manager", "admin"}
    return normalized_role in {"planner", "manager", "admin"}


def filter_tools_for_role(tools_by_name: dict[str, ToolInfo], *, role: str) -> dict[str, ToolInfo]:
    return {
        name: tool
        for name, tool in tools_by_name.items()
        if tool_allowed_for_role(tool, role)
    }

