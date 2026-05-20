"""FastAPI dependency factories shared across route modules."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Header, HTTPException

from factory_agent.config import Settings
from factory_agent.security import JwtValidationError, validate_bearer_token
from factory_agent.security.permissions import role_from_claims


def principal_user_id(claims: dict[str, Any] | None) -> str | None:
    if not isinstance(claims, dict):
        return None
    for key in ("sub", "user_id", "uid"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def is_admin_claims(claims: dict[str, Any] | None) -> bool:
    return role_from_claims(claims, default="viewer") == "admin"


def require_session_owner(session: Any, claims: dict[str, Any] | None) -> None:
    user_id = principal_user_id(claims)
    if not user_id or is_admin_claims(claims):
        return
    if str(getattr(session, "user_id", "") or "") != user_id:
        raise HTTPException(status_code=404, detail="session not found")


def build_require_admin(settings: Settings) -> Callable[[str | None], None]:
    def require_admin(x_admin_key: str | None = Header(None, alias="X-Admin-Key")) -> None:
        if x_admin_key != settings.admin_api_key:
            raise HTTPException(status_code=403, detail="forbidden")

    return require_admin


def build_require_jwt(settings: Settings) -> Callable[[str | None, str | None], dict[str, Any]]:
    def require_jwt(
        authorization: str | None = Header(None, alias="Authorization"),
        x_user_role: str | None = Header(None, alias="X-User-Role"),
        x_user_id: str | None = Header(None, alias="X-User-Id"),
    ) -> dict[str, Any]:
        try:
            claims = validate_bearer_token(authorization, settings=settings)
        except JwtValidationError as e:
            raise HTTPException(status_code=401, detail=str(e))
        if (not settings.jwt_required) and x_user_id and "sub" not in claims and "user_id" not in claims:
            claims["sub"] = x_user_id.strip()
        if x_user_role and "role" not in claims and "user_role" not in claims:
            claims["role"] = x_user_role.strip().lower()
        default_role = "viewer" if settings.jwt_required else "manager" if principal_user_id(claims) else "admin"
        claims.setdefault(
            "role",
            role_from_claims(claims, default=default_role),
        )
        return claims

    return require_jwt
