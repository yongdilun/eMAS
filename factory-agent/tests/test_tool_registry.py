from factory_agent.schemas import ToolInfo
from factory_agent.registry.tool_registry import ToolRegistry


def _tool(name: str, endpoint: str, method: str, tags: list[str]) -> ToolInfo:
    return ToolInfo(
        name=name,
        description=name,
        endpoint=endpoint,
        method=method,
        input_schema={"type": "object", "properties": {}},
        capability_tags=tags,
        is_read_only=method == "GET",
        requires_approval=method != "GET",
    )


def test_registry_health_is_domain_agnostic():
    registry = ToolRegistry()
    result = registry.assess_health(
        {
            "get_customers": _tool("get_customers", "/customers", "GET", ["customer", "list"]),
            "post_invoices": _tool("post_invoices", "/invoices", "POST", ["invoice", "create"]),
        },
        min_tool_count=2,
    )

    assert result.ok


def test_registry_health_rejects_incomplete_generated_metadata():
    registry = ToolRegistry()
    result = registry.assess_health(
        {
            "get_customers": _tool("get_customers", "/customers", "GET", []),
        },
        min_tool_count=1,
    )

    assert not result.ok
    assert "incomplete tool metadata" in (result.message or "")

