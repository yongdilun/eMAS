from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from ...schemas import ToolInfo
from .idempotency import compute_payload_hash


class ToolHTTPError(Exception):
    def __init__(self, status_code: int, body: dict[str, Any] | None):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}")


class ToolNetworkError(Exception):
    def __init__(self, message: str, *, request_was_sent: bool):
        self.request_was_sent = request_was_sent
        super().__init__(message)


class ToolInputError(Exception):
    pass


_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def normalize_tool_args(tool: ToolInfo, args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = args or {}
    if any(key in payload for key in ("path", "query", "body", "path_args", "query_args", "body_args")):
        path_args = payload.get("path") if isinstance(payload.get("path"), dict) else payload.get("path_args") if isinstance(payload.get("path_args"), dict) else {}
        query_args = payload.get("query") if isinstance(payload.get("query"), dict) else payload.get("query_args") if isinstance(payload.get("query_args"), dict) else {}
        body_args = payload.get("body") if isinstance(payload.get("body"), dict) else payload.get("body_args") if isinstance(payload.get("body_args"), dict) else {}
        return dict(path_args), dict(query_args), dict(body_args)

    path_param_names = tool.path_params or [match.group(1) for match in _PATH_PARAM_RE.finditer(tool.endpoint or "")]
    query_param_names = tool.query_params or [
        key for key, source in (tool.param_sources or {}).items() if source == "query"
    ]
    path_args = {key: payload[key] for key in path_param_names if key in payload}
    query_args = {
        key: payload[key]
        for key in query_param_names
        if key in payload
    }
    consumed = set(path_args.keys()) | set(query_args.keys())
    body_args = {key: value for key, value in payload.items() if key not in consumed}
    return path_args, query_args, body_args


def materialize_endpoint(endpoint: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
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
        raise ToolInputError(f"Missing required path args: {missing}")
    remaining_args = {key: value for key, value in args.items() if key not in used_keys}
    return rendered, remaining_args


async def execute_tool_call(
    engine: Any,
    *,
    tool: ToolInfo,
    args: dict[str, Any],
    idempotency_key: str,
    plan_hash: str,
    plan_version: int,
    session_id: str,
    step_id: str,
    db: Any,
) -> tuple[dict[str, Any] | None, int]:
    path_args, query_args, body_args = normalize_tool_args(tool, args)
    rendered_endpoint, leftover_path_args = materialize_endpoint(endpoint=tool.endpoint, args=path_args)
    if leftover_path_args:
        path_args.update(leftover_path_args)
    url = f"{engine._settings.go_api_base_url}{rendered_endpoint}"
    headers = {
        "Idempotency-Key": idempotency_key,
        "X-Idempotency-Key": idempotency_key,
        "X-Plan-Hash": plan_hash,
        "X-Plan-Version": str(plan_version),
        "X-Payload-Hash": compute_payload_hash(args=args),
    }

    start = time.time()
    body: dict[str, Any] | None = None
    try:
        async with httpx.AsyncClient(timeout=engine._settings.http_timeout_s) as client:
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
                raise ValueError(f"Unsupported method: {tool.method}")
    except httpx.TimeoutException as e:
        await engine._record_snapshot(
            db,
            step_id=step_id,
            session_id=session_id,
            tool=tool,
            args=args,
            plan_hash=plan_hash,
            plan_version=plan_version,
            idempotency_key=idempotency_key,
            http_status=None,
            response_body={"error_type": "timeout", "message": str(e)},
            latency_ms=int((time.time() - start) * 1000),
        )
        raise ToolNetworkError(str(e), request_was_sent=True) from e
    except httpx.NetworkError as e:
        await engine._record_snapshot(
            db,
            step_id=step_id,
            session_id=session_id,
            tool=tool,
            args=args,
            plan_hash=plan_hash,
            plan_version=plan_version,
            idempotency_key=idempotency_key,
            http_status=None,
            response_body={"error_type": "network", "message": str(e)},
            latency_ms=int((time.time() - start) * 1000),
        )
        raise ToolNetworkError(str(e), request_was_sent=False) from e

    latency_ms = int((time.time() - start) * 1000)
    try:
        if resp.content:
            body = resp.json()
    except Exception:
        body = {"raw": resp.text}

    await engine._record_snapshot(
        db,
        step_id=step_id,
        session_id=session_id,
        tool=tool,
        args=args,
        plan_hash=plan_hash,
        plan_version=plan_version,
        idempotency_key=idempotency_key,
        http_status=resp.status_code,
        response_body=body,
        latency_ms=latency_ms,
    )
    from ...observability.metrics import metrics
    from ...observability.telemetry import log_event
    metrics.observe("step_execution_latency_ms", latency_ms, labels={"tool": tool.name})
    log_event(
        "step_http_result",
        session_id=session_id,
        step_id=step_id,
        tool=tool.name,
        method=tool.method,
        endpoint=rendered_endpoint,
        status=resp.status_code,
        latency_ms=latency_ms,
        idempotency_key=idempotency_key,
    )

    if engine._is_soft_not_found(tool=tool, http_status=resp.status_code, body=body):
        body = dict(body)
        body["not_found"] = True
        body["_summary"] = await engine._build_not_found_summary(tool_name=tool.name, args=args, body=body)
        return body, latency_ms

    if resp.status_code >= 400:
        raise ToolHTTPError(resp.status_code, body)
    return body, latency_ms
