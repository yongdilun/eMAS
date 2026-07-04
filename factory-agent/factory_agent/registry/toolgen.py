from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.persistence.models import Tool, ToolRegistryMeta, generate_uuid


@dataclass(frozen=True)
class ToolgenResult:
    tool_count: int
    tools_md_hash: str


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        return {}
    node: Any = spec
    for token in ref[2:].split("/"):
        if not isinstance(node, dict):
            return {}
        node = node.get(token)
        if node is None:
            return {}
    return node if isinstance(node, dict) else {}


def _resolve_schema(spec: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
    if not schema:
        return {"type": "object", "properties": {}}
    if "$ref" in schema:
        resolved = _resolve_ref(spec, str(schema["$ref"]))
        return _resolve_schema(spec, resolved)
    normalized: dict[str, Any] = dict(schema)
    if "allOf" in normalized and isinstance(normalized["allOf"], list):
        merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for part in normalized["allOf"]:
            resolved_part = _resolve_schema(spec, part)
            if resolved_part.get("type") == "object":
                merged["properties"].update(resolved_part.get("properties", {}))
                merged["required"].extend(resolved_part.get("required", []))
        merged["required"] = sorted(set(merged["required"]))
        return merged
    if isinstance(normalized.get("properties"), dict):
        normalized["properties"] = {
            name: _resolve_schema(spec, prop_schema if isinstance(prop_schema, dict) else {})
            for name, prop_schema in normalized["properties"].items()
        }
    if isinstance(normalized.get("items"), dict):
        normalized["items"] = _resolve_schema(spec, normalized["items"])
    return normalized


def _response_content_types(spec: dict[str, Any], operation: dict[str, Any]) -> list[str]:
    content_types: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            content_types.append(value.strip().lower())
        elif isinstance(value, list):
            for item in value:
                add(item)

    add(spec.get("produces"))
    add(operation.get("produces"))
    responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
    for response in responses.values():
        if not isinstance(response, dict):
            continue
        content = response.get("content") if isinstance(response.get("content"), dict) else {}
        for media_type in content.keys():
            add(media_type)
    return list(dict.fromkeys(content_types))


def _with_response_content_types(schema: dict[str, Any], content_types: list[str]) -> dict[str, Any]:
    enriched = dict(schema or {"type": "object", "properties": {}})
    if content_types:
        enriched["x-response-content-types"] = content_types
    return enriched


def _infer_output_schema(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    content_types = _response_content_types(spec, operation)
    responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
    for status in ("200", "201", "202", "204", "default"):
        response = responses.get(status)
        if not isinstance(response, dict):
            continue
        if isinstance(response.get("schema"), dict):
            return _with_response_content_types(_resolve_schema(spec, response.get("schema")), content_types)
        content = response.get("content") if isinstance(response.get("content"), dict) else {}
        for media in ("application/json", "application/*+json", "*/*"):
            candidate = content.get(media)
            if isinstance(candidate, dict) and isinstance(candidate.get("schema"), dict):
                return _with_response_content_types(_resolve_schema(spec, candidate.get("schema")), content_types)
        for candidate in content.values():
            if isinstance(candidate, dict) and isinstance(candidate.get("schema"), dict):
                return _with_response_content_types(_resolve_schema(spec, candidate.get("schema")), content_types)
    return _with_response_content_types({"type": "object", "properties": {}}, content_types)


def _allowed_roles_for_operation(method: str, operation: dict[str, Any]) -> list[str]:
    for key in ("x-ai-allowed-roles", "x-allowed-roles", "x-rbac-roles"):
        values = operation.get(key)
        if isinstance(values, list):
            roles = [str(value).strip().lower() for value in values if str(value).strip()]
            if roles:
                return list(dict.fromkeys(roles))
    if method.lower() == "get":
        return ["viewer", "planner", "manager", "admin"]
    return ["planner", "manager", "admin"]


def _merge_object_schema(
    base: dict[str, Any],
    addition: dict[str, Any],
    *,
    prefix: str | None = None,
    mark_required: bool = True,
) -> None:
    if addition.get("type") != "object":
        if prefix:
            base.setdefault("properties", {})[prefix] = addition
            if mark_required:
                base.setdefault("required", []).append(prefix)
        return

    for name, prop_schema in (addition.get("properties") or {}).items():
        key = f"{prefix}_{name}" if prefix else name
        base.setdefault("properties", {})[key] = prop_schema
    for required_name in addition.get("required") or []:
        key = f"{prefix}_{required_name}" if prefix else required_name
        base.setdefault("required", []).append(key)


def _resolve_parameter(spec: dict[str, Any], param: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(param, dict):
        return {}
    if "$ref" in param:
        resolved = _resolve_ref(spec, str(param["$ref"]))
        return _resolve_parameter(spec, resolved)
    return dict(param)


def _copy_parameter_metadata_to_schema(param: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(schema or {})
    for key, value in param.items():
        if key.startswith("x-ai-") or key in {"pattern", "format"}:
            enriched.setdefault(key, value)
    if isinstance(param.get("enum"), list) and "enum" not in enriched:
        enriched["enum"] = list(param.get("enum") or [])
    return enriched


def _merge_body_schema(
    input_schema: dict[str, Any],
    param_sources: dict[str, str],
    body_schema: dict[str, Any] | None,
    *,
    body_required: bool,
) -> dict[str, Any] | None:
    if not body_schema:
        return None
    if body_schema.get("type") == "object":
        _merge_object_schema(input_schema, body_schema)
        for field_name in (body_schema.get("properties") or {}).keys():
            param_sources[str(field_name)] = "body"
    else:
        _merge_object_schema(
            input_schema,
            body_schema,
            prefix="body",
            mark_required=body_required,
        )
        param_sources["body"] = "body"
        if body_required:
            input_schema.setdefault("required", []).append("body")
    return body_schema


def _infer_input_schema(
    spec: dict[str, Any],
    operation: dict[str, Any],
    method: str,
    *,
    path_parameters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    input_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    path_params: list[str] = []
    query_params: list[str] = []
    param_sources: dict[str, str] = {}
    body_schema: dict[str, Any] | None = None

    all_parameters = [*(path_parameters or []), *(operation.get("parameters", []) or [])]
    for raw_param in all_parameters:
        param = _resolve_parameter(spec, raw_param)
        schema = param.get("schema")
        if not schema and "type" in param:
            schema = {"type": param.get("type", "string")}
            if isinstance(param.get("enum"), list):
                schema["enum"] = list(param.get("enum") or [])
        resolved = _resolve_schema(spec, schema)
        resolved = _copy_parameter_metadata_to_schema(param, resolved)
        param_name = str(param.get("name", "param"))
        location = str(param.get("in", "")).lower()

        if location == "body":
            body_schema = _merge_body_schema(
                input_schema,
                param_sources,
                resolved,
                body_required=bool(param.get("required")),
            ) or body_schema
            continue

        if location == "formdata":
            if not resolved:
                resolved = {"type": str(param.get("type", "string") or "string")}
            input_schema["properties"][param_name] = resolved
            param_sources[param_name] = "body"
            if bool(param.get("required")):
                input_schema["required"].append(param_name)
            continue

        input_schema["properties"][param_name] = resolved
        param_sources[param_name] = location or "query"
        if location == "path":
            path_params.append(param_name)
        elif location == "query":
            query_params.append(param_name)
        if bool(param.get("required")) or location == "path":
            input_schema["required"].append(param_name)

    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        request_body = _resolve_schema(spec, request_body)
    if isinstance(request_body, dict):
        content = request_body.get("content", {}) or {}
        for content_type in ("application/json", "application/*+json", "*/*"):
            maybe = content.get(content_type)
            if isinstance(maybe, dict):
                body_schema = _resolve_schema(spec, maybe.get("schema"))
                if body_schema:
                    break
        if not body_schema and isinstance(content, dict):
            for media in content.values():
                if isinstance(media, dict):
                    candidate = _resolve_schema(spec, media.get("schema"))
                    if candidate:
                        body_schema = candidate
                        break
        if body_schema:
            body_schema = _merge_body_schema(
                input_schema,
                param_sources,
                body_schema,
                body_required=bool(request_body.get("required")),
            ) or body_schema

    input_schema["required"] = sorted(set(input_schema.get("required", [])))
    if not input_schema["required"]:
        input_schema.pop("required", None)
    input_schema["x-path-params"] = path_params
    input_schema["x-query-params"] = query_params
    input_schema["x-param-sources"] = param_sources
    if body_schema:
        input_schema["x-body-schema"] = body_schema
        if body_schema.get("type") == "object":
            input_schema["x-body-fields"] = sorted((body_schema.get("properties") or {}).keys())
            input_schema["x-body-required"] = sorted(set(body_schema.get("required", []) or []))
        else:
            input_schema["x-body-fields"] = ["body"]
            input_schema["x-body-required"] = ["body"] if request_body.get("required") else []
    return input_schema


def _apply_known_openapi_repairs(path: str, operation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Repair documented paths that drift from the mounted router.

    The generated Swagger for the scheduling candidate-machine endpoint omits
    the step id path segment, while the live router exposes
    /scheduling/steps/:id/candidate-machines. Keeping the operationId stable
    preserves the existing tool contract while making generated tools executable.
    """
    if path == "/scheduling/candidate-machines" and str(operation.get("summary", "")).lower() == "candidate machines":
        repaired = dict(operation)
        params = list(repaired.get("parameters") or [])
        if not any(isinstance(param, dict) and param.get("name") == "id" and param.get("in") == "path" for param in params):
            params.insert(
                0,
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "type": "string",
                    "description": "Job step ID",
                },
            )
        repaired["parameters"] = params
        return "/scheduling/steps/{id}/candidate-machines", repaired
    return path, operation


_ACTION_TAGS_BY_METHOD = {
    "get": "read",
    "post": "create",
    "put": "update",
    "patch": "update",
    "delete": "delete",
}

_LOW_SIGNAL_OPERATION_TOKENS = {
    "api",
    "by",
    "for",
    "from",
    "get",
    "in",
    "of",
    "to",
    "with",
}


def _normalize_token(token: str) -> str:
    lowered = (token or "").strip().lower()
    if lowered == "status":
        return lowered
    if lowered.endswith("ies") and len(lowered) > 3:
        return lowered[:-3] + "y"
    if lowered.endswith("sses") and len(lowered) > 5:
        return lowered[:-2]
    if lowered.endswith("ss"):
        return lowered
    if lowered.endswith("s") and len(lowered) > 3:
        return lowered[:-1]
    return lowered


def _split_tokens(value: str) -> list[str]:
    return [
        token
        for token in (_normalize_token(part) for part in re.split(r"[^a-zA-Z0-9]+", value or ""))
        if token
    ]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    return [value for value in values if value and not (value in seen or seen.add(value))]


def _path_capability_tokens(path: str) -> list[str]:
    tokens: list[str] = []
    parts = [part for part in (path or "").strip("/").split("/") if part]
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            continue
        tokens.extend(_split_tokens(part))
    return tokens


def _operation_text_tokens(operation: dict[str, Any]) -> list[str]:
    raw = " ".join(
        [
            str(operation.get("summary", "") or ""),
            str(operation.get("description", "") or ""),
            str(operation.get("operationId", "") or ""),
            " ".join(str(tag) for tag in (operation.get("tags") or []) if str(tag)),
        ]
    )
    return [token for token in _split_tokens(raw) if token not in _LOW_SIGNAL_OPERATION_TOKENS]


def _schema_tokens(schema: dict[str, Any] | None) -> list[str]:
    if not isinstance(schema, dict):
        return []
    tokens: list[str] = []
    for key in ("title", "description"):
        value = schema.get(key)
        if isinstance(value, str):
            tokens.extend(_split_tokens(value))
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, subschema in properties.items():
            tokens.extend(_split_tokens(str(name)))
            tokens.extend(_schema_tokens(subschema if isinstance(subschema, dict) else {}))
    items = schema.get("items")
    if isinstance(items, dict):
        tokens.extend(_schema_tokens(items))
    return tokens


def _extension_tokens(value: Any) -> list[str]:
    if isinstance(value, str):
        return _split_tokens(value)
    if isinstance(value, (int, float, bool)):
        return _split_tokens(str(value))
    if isinstance(value, list):
        tokens: list[str] = []
        for item in value:
            tokens.extend(_extension_tokens(item))
        return tokens
    if isinstance(value, dict):
        tokens: list[str] = []
        for key, item in value.items():
            tokens.extend(_split_tokens(str(key)))
            tokens.extend(_extension_tokens(item))
        return tokens
    return []


def _ai_extension_tokens(operation: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for key, value in operation.items():
        if isinstance(key, str) and key.startswith("x-ai-"):
            tokens.extend(_extension_tokens(value))
    return tokens


def _operation_tokens(
    path: str,
    method: str,
    operation: dict[str, Any],
    *,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> list[str]:
    tags: list[str] = []
    lowered_method = method.lower()
    path_tokens = _path_capability_tokens(path)
    operation_tokens = _operation_text_tokens(operation)
    extension_tokens = _ai_extension_tokens(operation)
    schema_tokens = _schema_tokens(input_schema) + _schema_tokens(output_schema)

    tags.extend(path_tokens)
    tags.extend(str(tag_token) for tag in operation.get("tags") or [] for tag_token in _split_tokens(str(tag)))

    if lowered_method == "get":
        tags.append("lookup" if "{" in path and "}" in path else "list")
    elif lowered_method in _ACTION_TAGS_BY_METHOD:
        tags.append(_ACTION_TAGS_BY_METHOD[lowered_method])

    tags.extend(extension_tokens)
    tags.extend(operation_tokens)
    tags.extend(schema_tokens)
    return _dedupe(tags)


def _build_tool_markdown(tool: Tool) -> str:
    input_schema_str = json.dumps(tool.input_schema, indent=2, ensure_ascii=False)
    output_schema_str = json.dumps(tool.output_schema, indent=2, ensure_ascii=False) if tool.output_schema else "{}"

    return (
        f"## {tool.name}\n"
        f"**Description**: {tool.description}\n"
        f"**Method**: {tool.method}\n"
        f"**Endpoint**: {tool.endpoint}\n"
        f"**Capability Tags**: {tool.capability_tags}\n"
        f"**Requires Approval**: {str(tool.requires_approval).lower()}\n"
        f"**Side Effect Level**: {tool.side_effect_level}\n"
        f"**Read Only**: {str(tool.is_read_only).lower()}\n"
        f"**Input Schema**:\n"
        f"`json\n{input_schema_str}\n`\n"
        f"**Output Schema**:\n"
        f"`json\n{output_schema_str}\n`\n"
        f"---\n"
    )


def render_tools_md(tools: list[Tool]) -> str:
    return "# Available Tools\n\n" + "".join(_build_tool_markdown(t) for t in tools)


def _collect_id_patterns_from_schema(schema: dict[str, Any] | None, catalog: dict[str, dict[str, str]]) -> None:
    if not isinstance(schema, dict):
        return
    field_name = schema.get("x-ai-id-field")
    entity = schema.get("x-ai-entity")
    prefix = schema.get("x-ai-id-prefix")
    pattern = schema.get("pattern")
    if isinstance(field_name, str) and isinstance(entity, str) and isinstance(prefix, str):
        catalog[field_name] = {
            "entity": entity,
            "prefix": prefix,
            "pattern": str(pattern or ""),
        }
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, child in properties.items():
            if isinstance(child, dict):
                child = dict(child)
                child.setdefault("x-ai-id-field", str(name))
            _collect_id_patterns_from_schema(child, catalog)
    items = schema.get("items")
    if isinstance(items, dict):
        _collect_id_patterns_from_schema(items, catalog)
    for key in ("allOf", "oneOf", "anyOf"):
        parts = schema.get(key)
        if isinstance(parts, list):
            for part in parts:
                _collect_id_patterns_from_schema(part if isinstance(part, dict) else None, catalog)


def build_id_pattern_catalog(tools: list[Tool]) -> dict[str, Any]:
    catalog: dict[str, dict[str, str]] = {}
    for tool in tools:
        _collect_id_patterns_from_schema(tool.input_schema if isinstance(tool.input_schema, dict) else None, catalog)
        _collect_id_patterns_from_schema(tool.output_schema if isinstance(tool.output_schema, dict) else None, catalog)

    prefixes = sorted(
        (
            {
                "prefix": meta["prefix"],
                "entity": meta["entity"],
                "field": field,
                "pattern": meta.get("pattern", ""),
            }
            for field, meta in catalog.items()
            if meta.get("prefix") and meta.get("entity")
        ),
        key=lambda item: len(item["prefix"]),
        reverse=True,
    )
    return {"version": 1, "fields": catalog, "prefixes": prefixes}


def write_id_pattern_catalog(tools: list[Tool], *, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_id_pattern_catalog(tools), f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def fetch_openapi_spec(*, openapi_url: str, local_swagger_json_path: str | None = None, force_local: bool = False) -> dict[str, Any]:
    if force_local:
        if not local_swagger_json_path or not os.path.exists(local_swagger_json_path):
            raise FileNotFoundError(f"No local swagger.json found at {local_swagger_json_path}")
        with open(local_swagger_json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        resp = requests.get(openapi_url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        if local_swagger_json_path and os.path.exists(local_swagger_json_path):
            with open(local_swagger_json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        raise


def tools_from_openapi(spec: dict[str, Any]) -> list[Tool]:
    tools: list[Tool] = []
    for path, path_item in (spec.get("paths", {}) or {}).items():
        shared_parameters = [
            _resolve_parameter(spec, param)
            for param in ((path_item or {}).get("parameters", []) or [])
            if isinstance(_resolve_parameter(spec, param), dict)
        ]
        for method, operation in (path_item or {}).items():
            if method.lower() not in ["get", "post", "put", "patch", "delete"]:
                continue
            effective_path, effective_operation = _apply_known_openapi_repairs(path, operation)

            tool_name = effective_operation.get("operationId", f"{method}_{path.replace('/', '_')}").lower()
            description = effective_operation.get("summary", "") or effective_operation.get("description", "")

            input_schema = _infer_input_schema(spec, effective_operation, method, path_parameters=shared_parameters)
            for key, value in effective_operation.items():
                if isinstance(key, str) and key.startswith("x-ai-"):
                    input_schema[key] = value
            input_schema["x-allowed-roles"] = _allowed_roles_for_operation(method, operation)
            output_schema = _infer_output_schema(spec, effective_operation)

            is_read_only = method.lower() == "get"
            requires_approval = not is_read_only
            side_effect_level = "NONE" if is_read_only else "HIGH"
            capability_tags = _operation_tokens(
                effective_path,
                method,
                effective_operation,
                input_schema=input_schema,
                output_schema=output_schema,
            )

            tools.append(
                Tool(
                    tool_id=generate_uuid(),
                    name=tool_name,
                    description=description,
                    endpoint=effective_path,
                    method=method.upper(),
                    version=1,
                    schema_version=1,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    is_read_only=is_read_only,
                    requires_approval=requires_approval,
                    side_effect_level=side_effect_level,
                    capability_tags=json.dumps(capability_tags),
                )
            )
    return tools


async def write_tools_md_and_meta(
    db: AsyncSession,
    *,
    tools: list[Tool],
    tools_md_path: str,
    id_patterns_path: str | None = None,
    replace_db: bool = True,
) -> ToolgenResult:
    # DB update (best-effort; same behavior as existing script).
    if replace_db:
        await db.execute(text("DELETE FROM tools"))
        for tool in tools:
            db.add(tool)
        await db.commit()
    else:
        for tool in tools:
            db.merge(tool)
        await db.commit()

    # tools.md
    content = render_tools_md(tools)
    with open(tools_md_path, "w", encoding="utf-8") as f:
        f.write(content)
    if id_patterns_path:
        write_id_pattern_catalog(tools, path=id_patterns_path)

    tools_md_hash = _sha256_hex(content.encode("utf-8"))

    meta = (await db.execute(select(ToolRegistryMeta).where(ToolRegistryMeta.meta_id == 1))).scalars().first()
    if not meta:
        meta = ToolRegistryMeta(meta_id=1, tools_md_hash=tools_md_hash)
        db.add(meta)
    else:
        meta.tools_md_hash = tools_md_hash
    await db.commit()

    return ToolgenResult(tool_count=len(tools), tools_md_hash=tools_md_hash)

