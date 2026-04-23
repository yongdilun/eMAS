from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from .config import Settings


class JwtValidationError(Exception):
    pass


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _validate_time_claims(payload: dict[str, Any], *, now: int, skew_s: int) -> None:
    exp = payload.get("exp")
    if exp is not None and now > int(exp) + skew_s:
        raise JwtValidationError("token expired")
    nbf = payload.get("nbf")
    if nbf is not None and now + skew_s < int(nbf):
        raise JwtValidationError("token not yet valid")
    iat = payload.get("iat")
    if iat is not None and now + skew_s < int(iat):
        raise JwtValidationError("token issued in the future")


def validate_bearer_token(authorization: str | None, *, settings: Settings) -> dict[str, Any]:
    if not settings.jwt_required:
        return {}

    if not settings.jwt_secret:
        raise JwtValidationError("jwt required but JWT_SECRET is missing")
    if not authorization:
        raise JwtValidationError("missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise JwtValidationError("Authorization must use Bearer token")

    token = authorization[len("Bearer ") :].strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise JwtValidationError("invalid JWT format")
    encoded_header, encoded_payload, encoded_sig = parts
    try:
        header = json.loads(_b64url_decode(encoded_header))
        payload = json.loads(_b64url_decode(encoded_payload))
    except Exception as e:
        raise JwtValidationError("invalid JWT encoding") from e

    if header.get("alg") != "HS256":
        raise JwtValidationError("unsupported JWT algorithm")

    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected_sig = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        provided_sig = _b64url_decode(encoded_sig)
    except Exception as e:
        raise JwtValidationError("invalid JWT signature encoding") from e
    if not hmac.compare_digest(expected_sig, provided_sig):
        raise JwtValidationError("invalid JWT signature")

    now = int(time.time())
    _validate_time_claims(payload, now=now, skew_s=max(0, settings.jwt_clock_skew_s))

    if settings.jwt_issuer and payload.get("iss") != settings.jwt_issuer:
        raise JwtValidationError("invalid issuer")

    if settings.jwt_audience:
        aud = payload.get("aud")
        if isinstance(aud, str):
            audiences = {aud}
        elif isinstance(aud, list):
            audiences = {str(item) for item in aud}
        else:
            audiences = set()
        if settings.jwt_audience not in audiences:
            raise JwtValidationError("invalid audience")

    return payload
