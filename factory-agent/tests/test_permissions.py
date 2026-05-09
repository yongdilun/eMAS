from factory_agent.security.permissions import filter_tools_for_role, role_from_claims
from factory_agent.schemas import ToolInfo


def _tool(name: str, method: str, *, allowed_roles=None) -> ToolInfo:
    return ToolInfo(
        name=name,
        description=name,
        endpoint=f"/{name}",
        method=method,  # type: ignore[arg-type]
        input_schema={"type": "object", "x-allowed-roles": allowed_roles or []},
        is_read_only=method == "GET",
        requires_approval=method != "GET",
        side_effect_level="NONE" if method == "GET" else "HIGH",
        is_concurrency_safe=True,
        is_strongly_idempotent=False,
        capability_tags=[],
        allowed_roles=allowed_roles or [],
    )


def test_role_from_claims_prefers_highest_roles_entry():
    assert role_from_claims({"roles": ["viewer", "manager"]}) == "manager"


def test_filter_tools_for_role_blocks_viewer_writes():
    tools = {
        "get__jobs": _tool("get__jobs", "GET"),
        "patch__jobs": _tool("patch__jobs", "PATCH"),
    }
    filtered = filter_tools_for_role(tools, role="viewer")
    assert set(filtered) == {"get__jobs"}


def test_filter_tools_for_role_respects_explicit_allowed_roles():
    tools = {
        "post__jobs": _tool("post__jobs", "POST", allowed_roles=["manager", "admin"]),
    }
    assert filter_tools_for_role(tools, role="planner") == {}
    assert set(filter_tools_for_role(tools, role="manager")) == {"post__jobs"}

