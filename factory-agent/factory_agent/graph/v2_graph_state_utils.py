from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from pydantic import Field

from ..planning.v2_agent_state import PlannerOwnedAgentGraphState
from ..planning.v2_contracts import V2ContractModel


class PlannerOwnedAgentGraphRunOptions(V2ContractModel):
    thread_id: str | None = None
    configurable: dict[str, Any] = Field(default_factory=dict)
    run_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _normalize_options(
    options: PlannerOwnedAgentGraphRunOptions | Mapping[str, Any] | None,
) -> PlannerOwnedAgentGraphRunOptions:
    if options is None:
        return PlannerOwnedAgentGraphRunOptions()
    if isinstance(options, PlannerOwnedAgentGraphRunOptions):
        return options
    return PlannerOwnedAgentGraphRunOptions.model_validate(dict(options))


def _checkpoint_config(
    options: PlannerOwnedAgentGraphRunOptions,
    *,
    session_context: Mapping[str, Any] | Any | None,
) -> dict[str, Any]:
    thread_id = options.thread_id or _session_context_value(session_context, "session_id")
    if not thread_id:
        thread_id = f"planner-owned-agent-graph-{uuid4().hex[:12]}"
    configurable = dict(options.configurable)
    configurable["thread_id"] = str(thread_id)
    configurable.setdefault("checkpoint_ns", "")
    config: dict[str, Any] = {"configurable": configurable}
    if options.run_name:
        config["run_name"] = str(options.run_name)
    if options.tags:
        config["tags"] = list(dict.fromkeys(str(tag) for tag in options.tags if str(tag).strip()))
    if options.metadata:
        config["metadata"] = dict(options.metadata)
    return config


def _checkpoint_tuple_id(checkpoint_tuple: Any) -> str | None:
    config = getattr(checkpoint_tuple, "config", None)
    if isinstance(config, Mapping):
        configurable = config.get("configurable")
        if isinstance(configurable, Mapping):
            checkpoint_id = configurable.get("checkpoint_id")
            return str(checkpoint_id) if checkpoint_id not in (None, "") else None
    checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
    if isinstance(checkpoint, Mapping):
        checkpoint_id = checkpoint.get("id")
        return str(checkpoint_id) if checkpoint_id not in (None, "") else None
    return None


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed >= 1 else None
    return None


def _current_graph_checkpoint_id(state: PlannerOwnedAgentGraphState) -> str | None:
    identity = state.execution_trace.diagnostics.get("graph_checkpoint_identity")
    if isinstance(identity, Mapping):
        checkpoint_id = identity.get("checkpoint_id")
        return str(checkpoint_id) if checkpoint_id not in (None, "") else None
    return None


def _graph_checkpoint_identity(
    checkpoint_config: Mapping[str, Any],
    *,
    ledger_revision: int,
) -> dict[str, Any]:
    configurable = checkpoint_config.get("configurable") if isinstance(checkpoint_config, Mapping) else {}
    if not isinstance(configurable, Mapping):
        configurable = {}
    thread_id = str(configurable.get("thread_id") or "planner-owned-agent-graph")
    checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
    checkpoint_id = str(configurable.get("checkpoint_id") or f"{thread_id}:ledger-{ledger_revision}:approval")
    return {
        "thread_id": thread_id,
        "checkpoint_ns": checkpoint_ns,
        "checkpoint_id": checkpoint_id,
        "ledger_revision": ledger_revision,
        "native_langgraph_checkpoint": True,
    }


def _graph_checkpoint_identity_for_current_revision(
    state: PlannerOwnedAgentGraphState,
) -> dict[str, Any]:
    existing = state.execution_trace.diagnostics.get("graph_checkpoint_identity")
    configurable: dict[str, Any] = {}
    if isinstance(existing, Mapping):
        thread_id = existing.get("thread_id")
        checkpoint_ns = existing.get("checkpoint_ns")
        if thread_id not in (None, ""):
            configurable["thread_id"] = str(thread_id)
        if checkpoint_ns is not None:
            configurable["checkpoint_ns"] = str(checkpoint_ns)
    return _graph_checkpoint_identity(
        {"configurable": configurable},
        ledger_revision=state.requirement_ledger.revision,
    )


def _session_context_value(session_context: Mapping[str, Any] | Any | None, key: str) -> Any:
    if session_context is None:
        return None
    if isinstance(session_context, Mapping):
        return session_context.get(key)
    return getattr(session_context, key, None)


def _state_update(state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
    return state.model_dump(mode="python")
