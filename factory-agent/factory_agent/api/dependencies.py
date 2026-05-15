"""FastAPI dependency factories shared across route modules."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Header, HTTPException

from factory_agent.config import Settings
from factory_agent.security import JwtValidationError, validate_bearer_token
from factory_agent.security.permissions import role_from_claims


def build_require_admin(settings: Settings) -> Callable[[str | None], None]:
    def require_admin(x_admin_key: str | None = Header(None, alias="X-Admin-Key")) -> None:
        if x_admin_key != settings.admin_api_key:
            raise HTTPException(status_code=403, detail="forbidden")

    return require_admin


def build_require_jwt(settings: Settings) -> Callable[[str | None, str | None], dict[str, Any]]:
    def require_jwt(
        authorization: str | None = Header(None, alias="Authorization"),
        x_user_role: str | None = Header(None, alias="X-User-Role"),
    ) -> dict[str, Any]:
        try:
            claims = validate_bearer_token(authorization, settings=settings)
        except JwtValidationError as e:
            raise HTTPException(status_code=401, detail=str(e))
        if x_user_role and "role" not in claims and "user_role" not in claims:
            claims["role"] = x_user_role.strip().lower()
        claims.setdefault(
            "role",
            role_from_claims(claims, default="viewer" if settings.jwt_required else "admin"),
        )
        return claims

    return require_jwt
