from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, create_model

from ..security.guardrails import validate_agent_tool_args
from ..schemas import ToolInfo


class ToolCallBlocked(Exception):
    def __init__(self, message: str, *, payload: dict[str, Any] | None = None):
        self.payload = payload or {}
        super().__init__(message)


class FactoryToolExecutor:
    """Controlled execution boundary for LangChain/LangGraph tool calls.

    The adapter intentionally does not call the backend directly. Production
    graph execution should inject an executor that routes through the existing
    approval, idempotency, retry, and telemetry machinery.
    """

    async def call_tool(self, *, tool: ToolInfo, args: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        del context
        raise ToolCallBlocked(
            "Tool execution is disabled for planner-only tool wrappers.",
            payload={"tool_name": tool.name, "args": args},
        )


def _python_type_for_json_schema(schema: dict[str, Any]) -> Any:
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        raw_type = next((item for item in raw_type if item != "null"), "string")
    if raw_type == "integer":
        return int
    if raw_type == "number":
        return float
    if raw_type == "boolean":
        return bool
    if raw_type == "array":
        return list
    if raw_type == "object":
        return dict
    return str


def build_args_model(tool: ToolInfo) -> type[BaseModel]:
    properties = (tool.input_schema or {}).get("properties")
    properties = properties if isinstance(properties, dict) else {}
    required = set((tool.input_schema or {}).get("required") or [])
    fields: dict[str, tuple[Any, Any]] = {}
    for name, schema in properties.items():
        if not isinstance(schema, dict):
            schema = {}
        annotation = _python_type_for_json_schema(schema)
        description = str(schema.get("description") or "")
        default = ... if name in required else None
        fields[str(name)] = (annotation, Field(default, description=description))

    model_name = f"{tool.name.replace('-', '_').replace('{', '').replace('}', '').replace('/', '_')}Args"
    return create_model(
        model_name,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def build_langchain_tool(
    *,
    tool: ToolInfo,
    executor: FactoryToolExecutor,
    context_factory: Callable[[], dict[str, Any] | None] | None = None,
):
    try:
        from langchain_core.tools import StructuredTool
    except Exception as exc:  # pragma: no cover - import depends on optional runtime package
        raise RuntimeError("langchain-core is required to build LangChain tool wrappers") from exc

    args_schema = build_args_model(tool)

    async def _call(**kwargs: Any) -> dict[str, Any]:
        context = context_factory() if context_factory else {}
        guardrail = validate_agent_tool_args(
            tool=tool,
            raw_args=kwargs,
            intent=str((context or {}).get("intent") or ""),
            evidence={field: str(value) for field, value in kwargs.items()},
            intent_memory=(context or {}).get("intent_memory") if isinstance(context, dict) else None,
        )
        if guardrail.clarification:
            raise ToolCallBlocked(guardrail.clarification, payload={"tool_name": tool.name})
        if guardrail.missing_required:
            raise ToolCallBlocked(
                f"Missing required args for {tool.name}: {', '.join(guardrail.missing_required)}",
                payload={"tool_name": tool.name, "missing_required": guardrail.missing_required},
            )
        if tool.requires_approval:
            raise ToolCallBlocked(
                f"{tool.name} requires approval before execution.",
                payload={"tool_name": tool.name, "args": guardrail.args, "requires_approval": True},
            )
        return await executor.call_tool(tool=tool, args=guardrail.args, context=context)

    return StructuredTool.from_function(
        coroutine=_call,
        name=tool.name,
        description=tool.description or f"{tool.method} {tool.endpoint}",
        args_schema=args_schema,
    )


def build_langchain_tools(
    *,
    tools: list[ToolInfo],
    executor: FactoryToolExecutor | None = None,
    context_factory: Callable[[], dict[str, Any] | None] | None = None,
) -> list[Any]:
    active_executor = executor or FactoryToolExecutor()
    return [
        build_langchain_tool(tool=tool, executor=active_executor, context_factory=context_factory)
        for tool in tools
    ]

