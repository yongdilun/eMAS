"""Stateless HTTP tool execution for LangGraph planning loop (Phase 4)."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from ..config import Settings
from ..schemas import ToolInfo
from ..tools.arguments import normalize_tool_args

_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def materialize_tool_endpoint(*, endpoint: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    used_keys: set[str] = set()
    unresolved_keys: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = args.get(key)
        if value is None:
            unresolved_keys.add(key)
            return match.group(0)
        used_keys.add(key)
        return quote(str(value), safe="")

    rendered = _PATH_PARAM_RE.sub(replace, endpoint)
    if unresolved_keys:
        missing = ", ".join(sorted(unresolved_keys))
        raise ValueError(f"Missing required path args: {missing}")
    remaining_args = {key: value for key, value in args.items() if key not in used_keys}
    return rendered, remaining_args


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_planner_write_idempotency_key(
    *,
    session_id: str,
    intent_id: str,
    action_id: str,
    tool_name: str,
    args: dict[str, Any],
    write_generation: int,
) -> str:
    """Semantic idempotency hash for staged / committed writes (Phase 4)."""
    import hashlib

    payload = f"{session_id}|{intent_id}|{action_id}|{tool_name}|{stable_json(args)}|{write_generation}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def execute_tool_http(
    settings: Settings,
    tool: ToolInfo,
    args: dict[str, Any],
    *,
    idempotency_key: str,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Execute a single registry tool against ``go_api_base_url``.

    Returns a normalized envelope (never raises for HTTP 4xx — caller uses ``http_status``).
    """
    path_args, query_args, body_args = normalize_tool_args(tool, args)
    rendered_endpoint, leftover_path = materialize_tool_endpoint(endpoint=tool.endpoint, args=path_args)
    if leftover_path:
        path_args.update(leftover_path)
    url = f"{settings.go_api_base_url}{rendered_endpoint}"
    headers = {
        "Idempotency-Key": idempotency_key,
        "X-Idempotency-Key": idempotency_key,
        **(extra_headers or {}),
    }
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            if tool.method == "GET":
                params = query_args or body_args
                resp = await client.get(url, params=params, headers=headers)
            elif tool.method == "POST":
                resp = await client.post(url, params=query_args or None, json=body_args, headers=headers)
            elif tool.method == "PUT":
                resp = await client.put(url, params=query_args or None, json=body_args, headers=headers)
            elif tool.method == "PATCH":
                resp = await client.patch(url, params=query_args or None, json=body_args, headers=headers)
            elif tool.method == "DELETE":
                resp = await client.request("DELETE", url, params=query_args or None, json=body_args or None, headers=headers)
            else:
                return {
                    "ok": False,
                    "http_status": None,
                    "body": {"error": f"Unsupported method: {tool.method}"},
                    "latency_ms": 0,
                    "infrastructure_error": True,
                }
    except httpx.TimeoutException as e:
        return {
            "ok": False,
            "http_status": None,
            "body": {"error_type": "timeout", "message": str(e)},
            "latency_ms": int((time.time() - start) * 1000),
            "infrastructure_error": True,
        }
    except httpx.NetworkError as e:
        return {
            "ok": False,
            "http_status": None,
            "body": {"error_type": "network", "message": str(e)},
            "latency_ms": int((time.time() - start) * 1000),
            "infrastructure_error": True,
        }

    latency_ms = int((time.time() - start) * 1000)
    body: dict[str, Any] | None = None
    try:
        if resp.content:
            body = resp.json()
    except Exception:
        body = {"raw": resp.text}

    return {
        "ok": resp.status_code < 400,
        "http_status": resp.status_code,
        "body": body,
        "latency_ms": latency_ms,
        "infrastructure_error": resp.status_code >= 500,
    }


__all__ = [
    "compute_planner_write_idempotency_key",
    "execute_tool_http",
    "materialize_tool_endpoint",
    "stable_json",
]
