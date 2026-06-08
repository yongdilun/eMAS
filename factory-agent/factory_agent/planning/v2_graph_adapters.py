from __future__ import annotations

from collections.abc import Awaitable, Mapping
from types import SimpleNamespace
from typing import Any, Protocol

from pydantic import Field

from factory_agent.config import Settings, get_settings
from factory_agent.planning.api_result_projection import api_row_id, project_api_row
from factory_agent.planning.intent import rag_query_with_required_machine_context, semantic_frame_for_text
from factory_agent.rag.knowledge_policy import default_knowledge_policy_registry
from factory_agent.rag.runtime_config import (
    advisory_rag_pipeline_config,
    run_rag_pipeline_with_optional_config,
)
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
    settings: Settings | None = None,
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
    tools_by_name: Mapping[str, ToolInfo],
    http_executor: GraphToolHttpExecutor | None = None,
    rag_pipeline: Any | None = None,
    session_id: str | None = None,
) -> GraphToolExecutionResult:
    """Execute a graph-selected API or RAG call after authorization validation."""

    persisted_decision = require_graph_execution_authorization(state, decision)
    call = persisted_decision.selected_tool_call
    if persisted_decision.decision_kind == "execute_parallel_read_batch":
        requested_call = decision.selected_tool_call
        authorized_call_ids = {selected.call_id for selected in persisted_decision.selected_tool_calls}
        if requested_call is None or requested_call.call_id not in authorized_call_ids:
            raise GraphExecutionAuthorizationError(
                "parallel read batch execution requires an authorized selected tool call"
            )
        call = requested_call
    if call is None:
        raise GraphExecutionAuthorizationError("execute_tool decision requires a selected tool call")

    tool = tools_by_name.get(call.tool_name)
    if call.kind == "rag_tool":
        return await execute_graph_rag_tool(
            settings=settings,
            state=state,
            decision=persisted_decision,
            call=call,
            rag_pipeline=rag_pipeline,
            session_id=session_id,
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
        session_id=session_id,
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
    if persisted.decision_kind not in {"execute_tool", "execute_parallel_read_batch"}:
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
    session_id: str | None = None,
) -> GraphToolExecutionResult:
    executor = http_executor or _default_http_executor
    try:
        env = await executor(
            settings,
            tool,
            dict(call.args),
            idempotency_key=_idempotency_key(state=state, decision=decision, call=call, session_id=session_id),
        )
    except Exception as exc:
        return _tool_execution_exception_result(
            state=state,
            decision=decision,
            call=call,
            exc=exc,
        )
    body = _body_mapping(env.get("body"))
    requirement = _requirement_by_id(state, call.requirement_id)
    normalized_result = _normalize_api_result(
        env=env,
        body=body,
        requirement=requirement,
        call=call,
        tool=tool,
    )
    explicit_no_match = _normalized_result_has_no_match(normalized_result)
    http_ok = bool(env.get("ok"))
    ok = http_ok or explicit_no_match
    error_type = ""
    normalized_error = normalized_result.get("error") if isinstance(normalized_result, dict) else None
    if isinstance(normalized_error, Mapping):
        error_type = str(normalized_error.get("error_type") or "").strip()
    if not error_type:
        error_type = str(body.get("error_type") or "").strip()
    diagnostic_metadata = {
        "graph_authorized_execution": True,
        "execution_adapter": "graph_http_tool_adapter",
        "decision_id": decision.decision_id,
        "tool_call_id": call.call_id,
        "http_status": env.get("http_status"),
        "latency_ms": env.get("latency_ms"),
        "ok": ok,
        "http_ok": http_ok,
        "infrastructure_error": bool(env.get("infrastructure_error")),
        "direct_v2_execution": False,
    }
    if isinstance(env.get("request_headers"), Mapping):
        diagnostic_metadata["request_headers"] = dict(env["request_headers"])
    if env.get("request_url"):
        diagnostic_metadata["request_url"] = str(env["request_url"])
    if explicit_no_match:
        diagnostic_metadata["reason"] = "not_found"
    elif not ok:
        diagnostic_metadata["reason"] = "tool_error"
    if error_type:
        diagnostic_metadata["error_type"] = error_type
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
        diagnostic_metadata=diagnostic_metadata,
    )


async def execute_graph_rag_tool(
    *,
    settings: Settings | None = None,
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
    call: GraphToolCall,
    rag_pipeline: Any | None = None,
    session_id: str | None = None,
) -> GraphToolExecutionResult:
    requirement = _requirement_by_id(state, call.requirement_id)
    query = _rag_query(call=call, requirement=requirement, state=state)
    pipeline = rag_pipeline
    if pipeline is None:
        from factory_agent.rag.pipeline import RAGPipeline

        pipeline = RAGPipeline()

    try:
        result = await run_rag_pipeline_with_optional_config(
            pipeline,
            query=query,
            session_id=session_id,
            route="RAG_ONLY",
            config=advisory_rag_pipeline_config(settings or get_settings()),
        )
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
    result_metadata = dict(getattr(result, "metadata", {}) or {})
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
        normalized_result["safety_content"] = safety_content
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
                **_rag_runtime_diagnostic_metadata(
                    result_metadata=result_metadata,
                    answer=answer,
                    sources=sources,
                ),
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
            "safety_content": safety_content,
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
            **_rag_runtime_diagnostic_metadata(
                result_metadata=result_metadata,
                answer=answer,
                sources=sources,
            ),
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
    from factory_agent.graph.http_tool_client import execute_tool_http, planner_identity_headers

    return await execute_tool_http(
        settings,
        tool,
        args,
        idempotency_key=idempotency_key,
        extra_headers=planner_identity_headers(),
    )


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


def _tool_execution_exception_result(
    *,
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
    call: GraphToolCall,
    exc: Exception,
) -> GraphToolExecutionResult:
    _ = state
    exception_type = type(exc).__name__
    detail = str(exc) or exception_type
    return GraphToolExecutionResult(
        tool_call=call,
        source_type="api_tool",
        source_of_truth="operational_state",
        ok=False,
        result_ref=f"graph-api-result-{call.call_id}",
        raw_result={
            "http_status": None,
            "body": {
                "error_type": "tool_execution_exception",
                "exception_type": exception_type,
                "message": detail,
            },
        },
        normalized_result={
            "error": {
                "code": "tool_error",
                "detail": detail,
                "exception_type": exception_type,
            },
            "status": "tool_failed",
            "status_code": None,
            "request_args": dict(call.args),
        },
        diagnostic_metadata={
            "graph_authorized_execution": True,
            "execution_adapter": "graph_http_tool_adapter",
            "decision_id": decision.decision_id,
            "tool_call_id": call.call_id,
            "http_status": None,
            "ok": False,
            "infrastructure_error": True,
            "status": "tool_failed",
            "reason": "tool_error",
            "exception_type": exception_type,
            "direct_v2_execution": False,
        },
    )


def _normalize_api_result(
    *,
    env: Mapping[str, Any],
    body: dict[str, Any],
    requirement: Any | None,
    call: GraphToolCall,
    tool: ToolInfo,
) -> dict[str, Any]:
    entity = str(getattr(requirement, "entity", "") or "").strip()
    normalized: dict[str, Any] = {
        "status_code": env.get("http_status"),
        "request_args": dict(call.args),
    }
    if entity:
        normalized["entity"] = entity

    if not bool(env.get("ok")):
        if _is_exact_single_entity_read_not_found(env=env, requirement=requirement, tool=tool):
            identifier = _single_entity_identifier(requirement=requirement, call=call, entity=entity)
            message = _not_found_message(entity=entity, identifier=identifier)
            normalized.update(
                {
                    "status": "no_match",
                    "match_status": "no_match",
                    "no_match": True,
                    "not_found": True,
                    "reason": "not_found",
                    "summary": message,
                    "message": message,
                }
            )
            if identifier:
                normalized["entity_id"] = identifier
                normalized["not_found_id"] = identifier
            return normalized

        error_type = str(body.get("error_type") or "").strip()
        error: dict[str, Any] = {
            "code": "tool_error",
            "detail": body.get("error") or body.get("message") or body,
        }
        if error_type:
            error["error_type"] = error_type
        normalized["status"] = "tool_failed"
        normalized["error"] = error
        return normalized

    rows = _rows_from_body(body)
    if rows is not None:
        rows = [project_api_row(row, requirement=requirement, entity=entity) for row in rows]
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
    fields = project_api_row(fields, requirement=requirement, entity=entity)
    normalized["fields"] = fields
    entity_id = api_row_id(fields, entity=entity)
    if entity_id not in (None, "", [], {}):
        normalized["entity_id"] = entity_id
    return normalized


def _normalized_result_has_no_match(result: Mapping[str, Any]) -> bool:
    return (
        result.get("no_match") is True
        or str(result.get("match_status") or "").lower() == "no_match"
        or str(result.get("status") or "").lower() == "no_match"
    )


def _is_exact_single_entity_read_not_found(
    *,
    env: Mapping[str, Any],
    requirement: Any | None,
    tool: ToolInfo,
) -> bool:
    return (
        env.get("http_status") == 404
        and requirement is not None
        and getattr(requirement, "requirement_type", None) == "single_entity_status"
        and str(getattr(tool, "method", "") or "").upper() == "GET"
        and _tool_endpoint_is_exact_item_read(tool)
    )


def _tool_endpoint_is_exact_item_read(tool: ToolInfo) -> bool:
    parts = [
        part
        for part in str(getattr(tool, "endpoint", "") or "").strip("/").split("/")
        if part
    ]
    if len(parts) != 2:
        return False
    return parts[1].startswith("{") and parts[1].endswith("}") and len(parts[1]) > 2


def _single_entity_identifier(
    *,
    requirement: Any | None,
    call: GraphToolCall,
    entity: str,
) -> str:
    constraints = dict(getattr(requirement, "constraints", {}) or {})
    preferred_keys = [f"{entity}_id"] if entity else []
    preferred_keys.extend(["entity_id", "id"])
    for key in preferred_keys:
        value = constraints.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    for key, value in constraints.items():
        if str(key).endswith("_id") and value not in (None, "", [], {}):
            return str(value)
    value = call.args.get("id")
    if value not in (None, "", [], {}):
        return str(value)
    return ""


def _not_found_message(*, entity: str, identifier: str) -> str:
    label = entity.replace("_", " ").strip().capitalize() if entity else "Record"
    if identifier:
        return f"{label} {identifier} was not found."
    return f"{label} was not found."


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


def _rag_query(
    *,
    call: GraphToolCall,
    requirement: Any | None,
    state: PlannerOwnedAgentGraphState,
) -> str:
    query = str(call.args.get("query") or "").strip()
    semantic_frame = semantic_frame_for_text(state.original_query)
    if query:
        return rag_query_with_required_machine_context(
            query,
            intent=state.original_query,
            semantic_frame=semantic_frame,
        )
    goal = str(getattr(requirement, "goal", "") or "").strip()
    return rag_query_with_required_machine_context(
        goal or state.original_query,
        intent=state.original_query,
        semantic_frame=semantic_frame,
    )


def _idempotency_key(
    *,
    state: PlannerOwnedAgentGraphState,
    decision: PlannerDecisionRecord,
    call: GraphToolCall,
    session_id: str | None = None,
) -> str:
    scope = str(session_id or "no-session").strip() or "no-session"
    scope = scope.replace(":", "_")
    return (
        "planner-owned-agent-graph:"
        f"{scope}:"
        f"{state.requirement_ledger.revision}:{decision.decision_id}:{call.call_id}:{call.tool_name}"
    )


def _rag_runtime_diagnostic_metadata(
    *,
    result_metadata: dict[str, Any],
    answer: str,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    runtime_config = result_metadata.get("runtime_config")
    runtime_config = runtime_config if isinstance(runtime_config, dict) else {}
    rerank = result_metadata.get("rerank")
    rerank = rerank if isinstance(rerank, dict) else {}
    context = result_metadata.get("context_building")
    context = context if isinstance(context, dict) else {}
    token_estimates = context.get("token_estimates")
    token_estimates = token_estimates if isinstance(token_estimates, dict) else {}
    generation = result_metadata.get("generation_validation")
    generation = generation if isinstance(generation, dict) else {}
    citation_details = _citation_details(sources)
    boundary_refusal = generation.get("initial_reason") == "certification_boundary_enforced" or _answer_refuses_boundary(answer)
    return {
        "rag_variant": runtime_config.get("variant_id"),
        "rag_operating_mode": runtime_config.get("operating_mode"),
        "rag_config": runtime_config,
        "rag_retrieval_mode": runtime_config.get("retrieval_mode"),
        "rag_context_builder": runtime_config.get("context_builder"),
        "rag_compression": runtime_config.get("compression"),
        "rag_document_augmentation": runtime_config.get("document_augmentation"),
        "rag_rerank_attempted": rerank.get("attempted"),
        "rag_rerank_succeeded": rerank.get("succeeded"),
        "rag_rerank_fallback_used": rerank.get("fallback_used"),
        "rag_rerank_fallback_allowed": rerank.get("fallback_allowed"),
        "rag_citation_count": len(sources),
        "rag_citation_source_ids": [item.get("source_id") for item in citation_details],
        "rag_citation_doc_ids": [item.get("doc_id") for item in citation_details],
        "rag_citation_pages": [item.get("page") for item in citation_details if item.get("page") is not None],
        "rag_citation_details": citation_details,
        "rag_no_evidence_fallback": is_insufficient_context_answer(answer),
        "rag_boundary_refusal": boundary_refusal,
        "rag_latency_ms": (result_metadata.get("runtime") or {}).get("latency_ms")
        if isinstance(result_metadata.get("runtime"), dict)
        else None,
        "rag_context_token_estimate": token_estimates.get("after_compression")
        or token_estimates.get("after_expansion"),
    }


def _citation_details(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for source in sources or []:
        details.append(
            {
                "source_id": source.get("source_id"),
                "doc_id": source.get("doc_id"),
                "chunk_id": source.get("chunk_id"),
                "page": source.get("page"),
                "page_start": source.get("page_start"),
                "page_end": source.get("page_end"),
                "supporting_pages": source.get("supporting_pages"),
                "section_title": source.get("section_title"),
                "section_path": source.get("section_path"),
            }
        )
    return details


def _answer_refuses_boundary(answer: str) -> bool:
    lowered = (answer or "").lower()
    return (
        "cannot certify" in lowered
        or "cannot certify, attest, approve" in lowered
        or "do not start, operate, energize, or reenergize" in lowered
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
