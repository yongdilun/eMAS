from __future__ import annotations

from collections.abc import Awaitable, Mapping
from types import SimpleNamespace
from typing import Any, Protocol

from pydantic import Field

from factory_agent.config import Settings
from factory_agent.planning.intent import semantic_frame_for_text
from factory_agent.rag.knowledge_policy import default_knowledge_policy_registry
from factory_agent.rag.source_metadata import (
    is_insufficient_context_answer,
    normalize_source_locators,
    sanitize_rag_answer_text,
)
from factory_agent.schemas import ToolInfo

from .v2_agent_state import GraphToolCall, PlannerDecisionRecord, PlannerOwnedAgentGraphState
from .v2_contracts import (
    EvidenceCitation,
    EvidenceLedgerEntry,
    EvidenceSourceType,
    SourceOfTruth,
    V2ContractModel,
)
from .v2_planner_decisions import PlannerDecisionValidationError, validate_planner_decision
from .v2_rag_tool import build_v2_rag_evidence


class GraphToolHttpExecutor(Protocol):
    def __call__(
        self,
        settings: Settings,
        tool: ToolInfo,
        args: dict[str, Any],
        *,
        idempotency_key: str,
        extra_headers: dict[str, str] | None = None,
    ) -> Awaitable[dict[str, Any]]:
        ...



class GraphExecutionAuthorizationError(PlannerDecisionValidationError):
    """Raised when execution is attempted without persisted graph authority."""


class GraphToolExecutionResult(V2ContractModel):
    tool_call: GraphToolCall
    source_type: EvidenceSourceType
    source_of_truth: SourceOfTruth
    ok: bool
    result_ref: str = Field(min_length=1)
    raw_result: dict[str, Any] = Field(default_factory=dict)
    normalized_result: dict[str, Any] = Field(default_factory=dict)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    satisfies: list[str] = Field(default_factory=list)
    diagnostic_metadata: dict[str, Any] = Field(default_factory=dict)


async def execute_graph_tool_call(
    *,
    settings: Settings,
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
    tools_by_name: Mapping[str, ToolInfo],
    http_executor: GraphToolHttpExecutor | None = None,
    rag_pipeline: Any | None = None,
) -> GraphToolExecutionResult:
    """Execute a graph-selected API or RAG call after authorization validation."""

    persisted_decision = require_graph_execution_authorization(state, decision)
    call = persisted_decision.selected_tool_call
    if call is None:
        raise GraphExecutionAuthorizationError("execute_tool decision requires a selected tool call")

    tool = tools_by_name.get(call.tool_name)
    if call.kind == "rag_tool":
        return await execute_graph_rag_tool(
            state=state,
            decision=persisted_decision,
            call=call,
            rag_pipeline=rag_pipeline,
        )
    if tool is None:
        return _tool_missing_result(state=state, decision=persisted_decision, call=call)

    return await execute_graph_api_tool_call(
        settings=settings,
        state=state,
        decision=persisted_decision,
        call=call,
        tool=tool,
        http_executor=http_executor,
    )


def require_graph_execution_authorization(
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
) -> PlannerDecisionRecord:
    """Return the persisted, validated decision that authorizes execution."""

    persisted = next(
        (
            existing
            for existing in state.planner_decisions
            if existing.decision_id == decision.decision_id
            and existing.decision_kind == decision.decision_kind
        ),
        None,
    )
    if persisted is None:
        raise GraphExecutionAuthorizationError(
            "graph execution requires a persisted validated planner or guard decision"
        )
    if persisted.decision_kind != "execute_tool":
        raise GraphExecutionAuthorizationError("graph execution requires an execute_tool decision")
    validate_planner_decision(state, persisted)
    return persisted


async def execute_graph_api_tool_call(
    *,
    settings: Settings,
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
    call: GraphToolCall,
    tool: ToolInfo,
    http_executor: GraphToolHttpExecutor | None = None,
) -> GraphToolExecutionResult:
    executor = http_executor or _default_http_executor
    env = await executor(
        settings,
        tool,
        dict(call.args),
        idempotency_key=_idempotency_key(state=state, decision=decision, call=call),
    )
    body = _body_mapping(env.get("body"))
    requirement = _requirement_by_id(state, call.requirement_id)
    normalized_result = _normalize_api_result(
        env=env,
        body=body,
        requirement=requirement,
        call=call,
    )
    ok = bool(env.get("ok"))
    return GraphToolExecutionResult(
        tool_call=call,
        source_type="api_tool",
        source_of_truth="operational_state",
        ok=ok,
        result_ref=f"graph-api-result-{call.call_id}",
        raw_result={
            "http_status": env.get("http_status"),
            "body": body,
        },
        normalized_result=normalized_result,
        satisfies=["operational_state_tool_result"] if ok else [],
        diagnostic_metadata={
            "graph_authorized_execution": True,
            "execution_adapter": "graph_http_tool_adapter",
            "decision_id": decision.decision_id,
            "tool_call_id": call.call_id,
            "http_status": env.get("http_status"),
            "latency_ms": env.get("latency_ms"),
            "ok": ok,
            "infrastructure_error": bool(env.get("infrastructure_error")),
            "direct_v2_execution": False,
        },
    )


async def execute_graph_rag_tool(
    *,
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
    call: GraphToolCall,
    rag_pipeline: Any | None = None,
) -> GraphToolExecutionResult:
    requirement = _requirement_by_id(state, call.requirement_id)
    query = _rag_query(call=call, requirement=requirement, state=state)
    pipeline = rag_pipeline
    if pipeline is None:
        from factory_agent.rag.pipeline import RAGPipeline

        pipeline = RAGPipeline()

    try:
        result = await pipeline.run(query=query, session_id=None, route="RAG_ONLY")
    except Exception as exc:
        return GraphToolExecutionResult(
            tool_call=call,
            source_type="diagnostic",
            source_of_truth="document_knowledge",
            ok=False,
            result_ref=f"graph-rag-result-{call.call_id}",
            raw_result={"error": str(exc), "query": query},
            normalized_result={
                "error": {"code": "rag_tool_error", "detail": str(exc)},
                "status": "tool_failed",
                "query": query,
            },
            diagnostic_metadata={
                "graph_authorized_execution": True,
                "execution_adapter": "graph_rag_tool_adapter",
                "decision_id": decision.decision_id,
                "tool_call_id": call.call_id,
                "status": "tool_failed",
                "reason": "rag_tool_error",
                "direct_v2_execution": False,
            },
        )

    evidence_id = f"ev-rag-preview-{call.requirement_id}"
    evidence = None
    raw_answer = str(getattr(result, "answer", "") or "")
    raw_sources = list(getattr(result, "sources", []) or [])
    safety_content = getattr(result, "safety_content", None)
    semantic_frame = semantic_frame_for_text(query)
    route_family = str(getattr(semantic_frame, "route", "") or "unknown")
    policy_application = default_knowledge_policy_registry().apply(
        route_family=route_family,
        query=query,
        answer=raw_answer,
        sources=raw_sources,
        safety_content=safety_content,
        semantic_frame=semantic_frame,
    )
    answer = sanitize_rag_answer_text(policy_application.answer or raw_answer)
    sources: list[dict[str, Any]] = normalize_source_locators(
        policy_application.sources or raw_sources,
        fallback_snippet=answer,
    )
    safety_content = policy_application.safety_content
    prepared_result = SimpleNamespace(answer=answer, sources=sources, safety_content=safety_content)
    if requirement is not None:
        evidence, answer, sources, safety_content = build_v2_rag_evidence(
            requirement=requirement,
            query=query,
            result=prepared_result,
            evidence_id=evidence_id,
        )

    if evidence is not None and not is_insufficient_context_answer(answer):
        normalized_result = dict(evidence.normalized_result)
        normalized_result.setdefault("query", query)
        normalized_result["sources"] = sources
        return GraphToolExecutionResult(
            tool_call=call,
            source_type="rag_tool",
            source_of_truth="document_knowledge",
            ok=True,
            result_ref=f"graph-rag-result-{call.call_id}",
            raw_result={"answer": answer, "sources": sources, "safety_content": safety_content},
            normalized_result=normalized_result,
            citations=list(evidence.citations),
            satisfies=["source_citation", "document_answer"],
            diagnostic_metadata={
                "graph_authorized_execution": True,
                "graph_tool_action": "rag_tool",
                "evidence_source_type": "rag_tool",
                "execution_adapter": "graph_rag_tool_adapter",
                "decision_id": decision.decision_id,
                "tool_call_id": call.call_id,
                "tool_call_kind": call.kind,
                "query": query,
                "source_count": len(sources),
                "route_family": route_family,
                "policy_id": policy_application.policy_id,
                "retrieved_content_proved_claim": True,
                "safety_content_present": bool(safety_content),
                "safety_content_used_as_evidence": False,
                "direct_v2_execution": False,
            },
        )

    return GraphToolExecutionResult(
        tool_call=call,
        source_type="system_guard",
        source_of_truth="document_knowledge",
        ok=True,
        result_ref=f"graph-rag-result-{call.call_id}",
        raw_result={"answer": answer, "sources": sources, "safety_content": safety_content},
        normalized_result={
            "answer": answer,
            "query": query,
            "match_status": "no_match",
            "no_match": True,
            "sources_checked": sources,
            "summary": answer,
        },
        satisfies=["insufficient_context"],
        diagnostic_metadata={
            "graph_authorized_execution": True,
            "graph_tool_action": "rag_tool",
            "evidence_source_type": "insufficient_context",
            "execution_adapter": "graph_rag_tool_adapter",
            "decision_id": decision.decision_id,
            "tool_call_id": call.call_id,
            "tool_call_kind": call.kind,
            "query": query,
            "source_count": len(sources),
            "route_family": route_family,
            "policy_id": policy_application.policy_id,
            "reason": "insufficient_context",
            "retrieved_content_proved_claim": False,
            "safety_content_present": bool(safety_content),
            "safety_content_used_as_evidence": False,
            "direct_v2_execution": False,
        },
    )


def observe_graph_tool_result(
    state: PlannerOwnedAgentGraphState,
    execution: GraphToolExecutionResult,
) -> EvidenceLedgerEntry:
    """Convert an authorized graph execution result into typed evidence."""

    evidence_id = _unique_evidence_id(state, _evidence_id_prefix(execution))
    metadata = dict(execution.diagnostic_metadata)
    metadata.setdefault("tool_call_id", execution.tool_call.call_id)
    metadata.setdefault("result_ref", execution.result_ref)
    metadata.setdefault("graph_observed_as_evidence", True)
    return EvidenceLedgerEntry(
        id=evidence_id,
        requirement_id=execution.tool_call.requirement_id,
        source_type=execution.source_type,
        source_of_truth=execution.source_of_truth,
        confidence="deterministic",
        tool_name=execution.tool_call.tool_name,
        args=dict(execution.tool_call.args),
        result_ref=execution.result_ref,
        normalized_result=dict(execution.normalized_result),
        citations=list(execution.citations),
        satisfies=list(execution.satisfies),
        diagnostic_metadata=metadata,
    )


async def _default_http_executor(
    settings: Settings,
    tool: ToolInfo,
    args: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    from factory_agent.graph.http_tool_client import execute_tool_http

    return await execute_tool_http(settings, tool, args, idempotency_key=idempotency_key)


def _tool_missing_result(
    *,
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
    call: GraphToolCall,
) -> GraphToolExecutionResult:
    _ = state
    return GraphToolExecutionResult(
        tool_call=call,
        source_type="api_tool",
        source_of_truth="operational_state",
        ok=False,
        result_ref=f"graph-api-result-{call.call_id}",
        raw_result={"error": f"Tool is not registered for execution: {call.tool_name}"},
        normalized_result={
            "error": {
                "code": "tool_not_registered",
                "detail": f"Tool is not registered for execution: {call.tool_name}",
            },
            "status": "tool_failed",
        },
        diagnostic_metadata={
            "graph_authorized_execution": True,
            "execution_adapter": "graph_http_tool_adapter",
            "decision_id": decision.decision_id,
            "tool_call_id": call.call_id,
            "status": "tool_failed",
            "reason": "tool_not_registered",
            "direct_v2_execution": False,
        },
    )


def _normalize_api_result(
    *,
    env: Mapping[str, Any],
    body: dict[str, Any],
    requirement: Any | None,
    call: GraphToolCall,
) -> dict[str, Any]:
    entity = str(getattr(requirement, "entity", "") or "").strip()
    normalized: dict[str, Any] = {
        "status_code": env.get("http_status"),
        "request_args": dict(call.args),
    }
    if entity:
        normalized["entity"] = entity

    if not bool(env.get("ok")):
        normalized["status"] = "tool_failed"
        normalized["error"] = {
            "code": "tool_error",
            "detail": body.get("error") or body.get("message") or body,
        }
        return normalized

    rows = _rows_from_body(body)
    if rows is not None:
        normalized["rows"] = rows
        filters = _applied_filters(requirement=requirement, request_args=call.args)
        if filters:
            normalized["applied_filters"] = filters
        if not rows:
            normalized.update(
                {
                    "match_status": "no_match",
                    "no_match": True,
                    "summary": "No matching records were found.",
                    "message": "No matching records were found.",
                    "reason": "no_matching_records",
                }
            )
        return normalized

    fields = _fields_from_body(body)
    normalized["fields"] = fields
    entity_id = _row_id(fields, entity=entity)
    if entity_id not in (None, "", [], {}):
        normalized["entity_id"] = entity_id
    return normalized


def _body_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": value}


def _rows_from_body(body: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    for key in ("data", "rows", "items", "results", "records", "value"):
        value = body.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return None


def _fields_from_body(body: Mapping[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    if isinstance(data, Mapping):
        return dict(data)
    result = body.get("result")
    if isinstance(result, Mapping):
        return dict(result)
    return {
        str(key): value
        for key, value in body.items()
        if key not in {"error", "message", "status_code"}
    }


def _applied_filters(*, requirement: Any | None, request_args: Mapping[str, Any]) -> dict[str, Any]:
    controls = {"fields", "limit", "offset", "page", "page_size", "sort", "sort_by", "sort_dir"}
    filters: dict[str, Any] = {}
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    for key, value in {**constraints, **dict(request_args)}.items():
        if key in controls or key.endswith("_id") or key == "id":
            continue
        if value not in (None, "", [], {}):
            filters[str(key)] = value
    return filters


def _row_id(row: Mapping[str, Any], *, entity: str) -> Any:
    candidates = []
    if entity:
        candidates.append(f"{entity}_id")
    candidates.extend(["entity_id", "id", "machine_ref"])
    for key in candidates:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _rag_query(
    *,
    call: GraphToolCall,
    requirement: Any | None,
    state: PlannerOwnedAgentGraphState,
) -> str:
    query = str(call.args.get("query") or "").strip()
    if query:
        return query
    goal = str(getattr(requirement, "goal", "") or "").strip()
    return goal or state.original_query


def _idempotency_key(
    *,
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
    call: GraphToolCall,
) -> str:
    return (
        "planner-owned-agent-graph:"
        f"{state.requirement_ledger.revision}:{decision.decision_id}:{call.call_id}:{call.tool_name}"
    )


def _evidence_id_prefix(execution: GraphToolExecutionResult) -> str:
    if execution.source_type == "api_tool":
        return f"ev-api-{execution.tool_call.requirement_id}"
    if execution.source_type == "rag_tool":
        return f"ev-rag-{execution.tool_call.requirement_id}"
    if execution.diagnostic_metadata.get("reason") == "insufficient_context":
        return f"ev-insufficient-context-{execution.tool_call.requirement_id}"
    return f"ev-{execution.source_type}-{execution.tool_call.requirement_id}"


def _unique_evidence_id(state: PlannerOwnedAgentGraphState, base: str) -> str:
    existing = {evidence.id for evidence in state.evidence_ledger.evidence}
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _requirement_by_id(
    state: PlannerOwnedAgentGraphState,
    requirement_id: str | None,
) -> Any | None:
    if requirement_id is None:
        return None
    return next(
        (
            requirement
            for requirement in state.requirement_ledger.requirements
            if requirement.id == requirement_id
        ),
        None,
    )


__all__ = [
    "GraphExecutionAuthorizationError",
    "GraphToolExecutionResult",
    "GraphToolHttpExecutor",
    "execute_graph_api_tool_call",
    "execute_graph_rag_tool",
    "execute_graph_tool_call",
    "observe_graph_tool_result",
    "require_graph_execution_authorization",
]
