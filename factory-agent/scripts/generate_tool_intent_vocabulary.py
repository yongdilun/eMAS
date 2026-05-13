from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


FACTORY_AGENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = FACTORY_AGENT_ROOT.parent
if str(FACTORY_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(FACTORY_AGENT_ROOT))

from factory_agent.schemas import ToolInfo  # noqa: E402
from factory_agent.planning.tool_intent_profile import build_tool_intent_vocabulary  # noqa: E402
from factory_agent.registry.toolgen import tools_from_openapi  # noqa: E402


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(value).strip().lower() for value in parsed if str(value).strip()]


def _tool_info_from_generated_tool(tool: Any) -> ToolInfo:
    schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    path_params = [str(value) for value in schema.get("x-path-params", []) if str(value)]
    query_params = [str(value) for value in schema.get("x-query-params", []) if str(value)]
    body_fields = [str(value) for value in schema.get("x-body-fields", []) if str(value)]
    if not body_fields:
        body_fields = [
            str(name)
            for name in properties
            if str(name) not in set(path_params) | set(query_params)
        ]
    return ToolInfo(
        name=str(tool.name),
        description=str(tool.description or ""),
        endpoint=str(tool.endpoint or ""),
        method=str(tool.method).upper(),
        input_schema=schema,
        output_schema=tool.output_schema if isinstance(tool.output_schema, dict) else {"type": "object"},
        path_params=path_params,
        query_params=query_params,
        body_fields=body_fields,
        required_body_fields=[str(value) for value in schema.get("x-body-required", []) if str(value)],
        body_schema=schema.get("x-body-schema") if isinstance(schema.get("x-body-schema"), dict) else None,
        param_sources={
            str(key): str(value)
            for key, value in (schema.get("x-param-sources") or {}).items()
            if str(key) and str(value)
        },
        is_read_only=bool(tool.is_read_only),
        requires_approval=bool(tool.requires_approval),
        side_effect_level=tool.side_effect_level or "NONE",
        capability_tags=_json_list(tool.capability_tags),
        allowed_roles=[str(value).strip().lower() for value in schema.get("x-allowed-roles", []) if str(value).strip()],
    )


def _default_operator_tokens() -> set[str]:
    return {
        "a",
        "about",
        "all",
        "an",
        "and",
        "any",
        "by",
        "can",
        "check",
        "create",
        "delete",
        "find",
        "for",
        "from",
        "get",
        "give",
        "help",
        "in",
        "into",
        "list",
        "lookup",
        "me",
        "new",
        "of",
        "please",
        "read",
        "remove",
        "show",
        "the",
        "to",
        "update",
        "view",
        "with",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate registry-derived tool intent vocabulary.")
    parser.add_argument(
        "--swagger",
        default=str(REPO_ROOT / "emas" / "docs" / "swagger.json"),
        help="Path to local OpenAPI/Swagger JSON.",
    )
    parser.add_argument(
        "--output",
        default=str(FACTORY_AGENT_ROOT / "factory_agent" / "generated" / "tool_intent_vocabulary.json"),
        help="Output JSON path (must match factory_agent.planning.tool_intent_profile).",
    )
    parser.add_argument(
        "--generic-threshold",
        type=float,
        default=0.60,
        help="Document-frequency threshold for generic registry tokens.",
    )
    args = parser.parse_args()

    swagger_path = Path(args.swagger)
    with swagger_path.open("r", encoding="utf-8") as handle:
        spec = json.load(handle)

    generated_tools = tools_from_openapi(spec)
    tools = [_tool_info_from_generated_tool(tool) for tool in generated_tools]
    vocabulary = build_tool_intent_vocabulary(
        tools,
        generic_threshold=args.generic_threshold,
        operator_tokens=_default_operator_tokens(),
    )

    payload = {
        "source": str(swagger_path),
        "tool_count": len(tools),
        "generic_threshold": args.generic_threshold,
        "generic_tokens": sorted(vocabulary.generic_tokens),
        "entity_tokens": sorted(vocabulary.entity_tokens),
        "operator_tokens": sorted(vocabulary.operator_tokens),
        "known_tool_tokens": sorted(vocabulary.known_tool_tokens),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output_path} ({len(tools)} tools)")
    print(
        f"generic_tokens={len(vocabulary.generic_tokens)} "
        f"entity_tokens={len(vocabulary.entity_tokens)} "
        f"operator_tokens={len(vocabulary.operator_tokens)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


