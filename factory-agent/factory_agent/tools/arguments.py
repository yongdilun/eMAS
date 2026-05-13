from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..schemas import ToolInfo


_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compute_idempotency_key(*, session_id: str, step_index: int, plan_version: int, args: dict[str, Any]) -> str:
    payload = f"{session_id}:{step_index}:{plan_version}:{stable_json(args)}"
    return sha256_hex(payload)


def normalize_tool_args(tool: ToolInfo, args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = args or {}
    if any(key in payload for key in ("path", "query", "body", "path_args", "query_args", "body_args")):
        path_args = (
            payload.get("path")
            if isinstance(payload.get("path"), dict)
            else payload.get("path_args")
            if isinstance(payload.get("path_args"), dict)
            else {}
        )
        query_args = (
            payload.get("query")
            if isinstance(payload.get("query"), dict)
            else payload.get("query_args")
            if isinstance(payload.get("query_args"), dict)
            else {}
        )
        body_args = (
            payload.get("body")
            if isinstance(payload.get("body"), dict)
            else payload.get("body_args")
            if isinstance(payload.get("body_args"), dict)
            else {}
        )
        return dict(path_args), dict(query_args), dict(body_args)

    path_param_names = tool.path_params or [match.group(1) for match in _PATH_PARAM_RE.finditer(tool.endpoint or "")]
    query_param_names = tool.query_params or [
        key for key, source in (tool.param_sources or {}).items() if source == "query"
    ]
    path_args = {key: payload[key] for key in path_param_names if key in payload}
    query_args = {key: payload[key] for key in query_param_names if key in payload}
    consumed = set(path_args.keys()) | set(query_args.keys())
    body_args = {key: value for key, value in payload.items() if key not in consumed}
    return path_args, query_args, body_args
