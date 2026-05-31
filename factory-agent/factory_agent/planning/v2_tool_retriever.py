from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any, Literal

from ..schemas import ToolInfo
from .tool_intent_profile import build_tool_intent_profile, normalize_token, vocabulary_for_tools
from .tool_scope import score_tool
from .tool_selector import ToolSelector
from .v2_contracts import (
    AdapterSafety,
    CandidateTool,
    CandidateToolWindow,
    CapabilityAction,
    CapabilityNeed,
    EndpointShape,
    HydratedToolCard,
    HydratedToolCards,
    RerankerTrace,
    SourceOfTruth,
    ToolRetrievalTrace,
    ToolSelectorAdapterRequest,
)


ToolRetrievalStatus = Literal["ok", "no_match", "low_confidence", "missing_required_schema"]

_MAX_TOOLS_PER_NEED = 5
_CONTROL_QUERY_FIELDS = {"fields", "limit", "offset", "page", "page_size", "sort", "sort_by", "sort_dir"}
_PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")
_DOCUMENT_KNOWLEDGE_TAGS = {
    "citation",
    "citations",
    "document",
    "document_knowledge",
    "knowledge",
    "knowledge_answer_v1",
    "rag",
}
_RESCHEDULE_ALL_TOOL_NAME = "post__ai_scheduling_reschedule-all"
_RESCHEDULE_ALL_ENDPOINT = "/ai/scheduling/reschedule-all"


@dataclass(frozen=True)
class V2ToolRetrievalResult:
    adapter_request: ToolSelectorAdapterRequest
    candidate_window: CandidateToolWindow
    hydrated_tool_cards: HydratedToolCards
    trace: ToolRetrievalTrace
    status: ToolRetrievalStatus = "ok"

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class V2CapabilityToolRetriever:
    """Phase 4 adapter from a planner capability need to a small tool window.

    This class intentionally wraps the existing ``ToolSelector``. It does not
    execute tools, run RAG, or introduce a second ranking stack.
    """

    def __init__(
        self,
        tool_selector: ToolSelector,
        *,
        max_candidates: int = _MAX_TOOLS_PER_NEED,
        min_candidate_score: int = 1,
    ) -> None:
        self._tool_selector = tool_selector
        self._max_candidates = max(1, min(int(max_candidates), _MAX_TOOLS_PER_NEED))
        self._min_candidate_score = int(min_candidate_score)

    async def retrieve_tools_for_need(
        self,
        capability_need: CapabilityNeed,
        *,
        tools_by_name: Mapping[str, ToolInfo],
        requirement_id: str | None = None,
        requirement_refs: Mapping[str, Any] | None = None,
        context_refs: Mapping[str, Any] | None = None,
        mode: str = "normal",
    ) -> V2ToolRetrievalResult:
        adapter_request = self.build_adapter_request(
            capability_need,
            requirement_id=requirement_id,
        )
        tools = dict(tools_by_name)
        selection = await self._tool_selector.select_tools(
            intent=adapter_request.retrieval_phrase or "",
            tools_by_name=tools,
            mode=mode,
            max_tools=self._max_candidates,
            context={
                "v2_tool_selector_adapter_request": adapter_request.model_dump(mode="json"),
                "requirement_refs": dict(requirement_refs or {}),
                "context_refs": dict(context_refs or {}),
            },
        )

        backend_used = getattr(selection, "backend_used", "retrieval")
        llm_calls = int(getattr(selection, "llm_calls", 0) or 0)
        selected_names = _unique_existing(selection.tool_names, tools, limit=self._max_candidates)
        selected_names, metadata_completion = _ensure_capability_candidates(
            adapter_request,
            selected_names,
            tools,
            limit=self._max_candidates,
        )
        scores = _candidate_scores(adapter_request, selected_names, tools)
        candidates = [
            CandidateTool(
                tool_name=name,
                rank=index,
                score=float(scores.get(name)) if name in scores else None,
                source_of_truth=_source_of_truth_for_tool(tools[name]),
                actions=_actions_for_tool(tools[name]),
                reason=f"tool_selector:{backend_used}",
                requires_approval=bool(tools[name].requires_approval),
            )
            for index, name in enumerate(selected_names, start=1)
        ]
        candidate_window = CandidateToolWindow(
            requirement_id=adapter_request.requirement_id,
            capability_need=capability_need,
            candidates=candidates,
            max_candidates=self._max_candidates,
            backend_used=backend_used,
            adapter_request=adapter_request,
        )

        cards = [_hydrate_tool_card(tools[name]) for name in selected_names]
        hydrated_cards = HydratedToolCards(
            requirement_id=adapter_request.requirement_id,
            cards=cards,
            max_cards=self._max_candidates,
        )

        missing_schema = [
            {
                "tool_name": card.tool_name,
                "diagnostics": card.metadata.get("schema_diagnostics", []),
            }
            for card in cards
            if card.metadata.get("schema_diagnostics")
        ]
        status: ToolRetrievalStatus = "ok"
        diagnostics: dict[str, Any] = {
            "status": status,
            "retrieval_phrase": adapter_request.retrieval_phrase,
            "adapter_request": adapter_request.model_dump(mode="json"),
            "candidate_count": len(selected_names),
            "max_candidates_per_need": self._max_candidates,
            "metadata_read_completion_used": bool(metadata_completion.get("read_preflight")),
            "metadata_candidate_completion": metadata_completion,
            "requirement_refs": dict(requirement_refs or {}),
            "context_refs": dict(context_refs or {}),
            "missing_schema": missing_schema,
        }
        if not selected_names:
            status = "no_match"
            diagnostics["reason"] = "tool_selector_returned_no_candidates"
        elif scores and max(scores.values()) < self._min_candidate_score:
            status = "low_confidence"
            diagnostics["reason"] = "candidate_scores_below_threshold"
            diagnostics["min_candidate_score"] = self._min_candidate_score
            diagnostics["candidate_scores"] = scores
        if missing_schema:
            status = "missing_required_schema"
            diagnostics["reason"] = "selected_candidate_missing_required_schema"
        diagnostics["status"] = status

        trace = ToolRetrievalTrace(
            call_count=1,
            selected_candidate_tool_names=selected_names,
            backend_used=backend_used,
            reranker=RerankerTrace(call_count=llm_calls),
            compatibility_fallback_used=_compatibility_fallback_used(adapter_request, selected_names, tools),
            diagnostics=diagnostics,
        )
        return V2ToolRetrievalResult(
            adapter_request=adapter_request,
            candidate_window=candidate_window,
            hydrated_tool_cards=hydrated_cards,
            trace=trace,
            status=status,
        )

    def build_adapter_request(
        self,
        capability_need: CapabilityNeed,
        *,
        requirement_id: str | None = None,
    ) -> ToolSelectorAdapterRequest:
        resolved_requirement_id = requirement_id or capability_need.requirement_id or "requirement-unassigned"
        constraints = dict(capability_need.constraints)
        constraints.update(capability_need.known_args)
        actions = _expanded_actions(capability_need.action)
        adapter_request = ToolSelectorAdapterRequest(
            requirement_id=resolved_requirement_id,
            entity=capability_need.entity,
            actions=actions,
            safety=_safety_for_need(capability_need),
            endpoint_shape=_endpoint_shape_for_need(capability_need),
            source_of_truth=capability_need.source_of_truth,
            constraints=constraints,
            requested_fields=list(capability_need.requested_fields),
            retrieval_phrase=_retrieval_phrase_for_need(capability_need, actions=actions, constraints=constraints),
            capability_need=capability_need,
        )
        return adapter_request


def _unique_existing(names: list[str], tools_by_name: Mapping[str, ToolInfo], *, limit: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen or name not in tools_by_name:
            continue
        selected.append(name)
        seen.add(name)
        if len(selected) >= limit:
            break
    return selected


def _ensure_capability_candidates(
    adapter_request: ToolSelectorAdapterRequest,
    selected_names: list[str],
    tools_by_name: Mapping[str, ToolInfo],
    *,
    limit: int,
) -> tuple[list[str], dict[str, Any]]:
    completion: dict[str, Any] = {
        "read_preflight": [],
        "write_candidates": [],
    }
    if adapter_request.source_of_truth != "operational_state":
        return selected_names, completion

    if adapter_request.safety == "read_only":
        completed, used = _ensure_capability_read_candidate(
            adapter_request,
            selected_names,
            tools_by_name,
            limit=limit,
        )
        if used:
            completion["read_preflight"] = [name for name in completed if name not in selected_names]
        return completed, completion

    if adapter_request.safety != "write_requires_approval":
        return selected_names, completion

    completed = list(selected_names)
    if not any(_tool_matches_read_preflight(tool, adapter_request) for name, tool in tools_by_name.items() if name in completed):
        for name in _read_preflight_candidate_names(adapter_request, tools_by_name):
            if name not in completed:
                _append_completed_candidate(completed, name, limit=limit)
                completion["read_preflight"].append(name)
                break

    if not any(_tool_matches_write_candidate(tool, adapter_request) for name, tool in tools_by_name.items() if name in completed):
        for name in _write_candidate_names(adapter_request, tools_by_name):
            if name not in completed:
                _append_completed_candidate(completed, name, limit=limit)
                completion["write_candidates"].append(name)
                break

    return completed, completion


def _ensure_capability_read_candidate(
    adapter_request: ToolSelectorAdapterRequest,
    selected_names: list[str],
    tools_by_name: Mapping[str, ToolInfo],
    *,
    limit: int,
) -> tuple[list[str], bool]:
    if adapter_request.source_of_truth != "operational_state":
        return selected_names, False
    if adapter_request.safety != "read_only":
        return selected_names, False
    if any(_tool_satisfies_adapter_request(tools_by_name[name], adapter_request) for name in selected_names):
        return selected_names, False

    additions = [
        name
        for name, tool in tools_by_name.items()
        if name not in selected_names and _tool_satisfies_adapter_request(tool, adapter_request)
    ]
    if not additions:
        return selected_names, False
    additions.sort()
    completed = [*selected_names, additions[0]]
    if len(completed) > limit:
        completed = completed[: limit - 1] + [additions[0]]
    return completed, True


def _append_completed_candidate(completed: list[str], name: str, *, limit: int) -> None:
    if name in completed:
        return
    if len(completed) < limit:
        completed.append(name)
        return
    completed[-1:] = [name]


def _read_preflight_candidate_names(
    adapter_request: ToolSelectorAdapterRequest,
    tools_by_name: Mapping[str, ToolInfo],
) -> list[str]:
    names = [
        name
        for name, tool in tools_by_name.items()
        if _tool_matches_read_preflight(tool, adapter_request)
    ]
    names.sort(key=lambda name: _read_preflight_rank(tools_by_name[name], adapter_request))
    return names


def _write_candidate_names(
    adapter_request: ToolSelectorAdapterRequest,
    tools_by_name: Mapping[str, ToolInfo],
) -> list[str]:
    names = [
        name
        for name, tool in tools_by_name.items()
        if _tool_matches_write_candidate(tool, adapter_request)
    ]
    names.sort(key=lambda name: _write_candidate_rank(tools_by_name[name], adapter_request))
    return names


def _tool_matches_read_preflight(tool: ToolInfo, adapter_request: ToolSelectorAdapterRequest) -> bool:
    if _source_of_truth_for_tool(tool) != adapter_request.source_of_truth:
        return False
    if not bool(tool.is_read_only):
        return False
    profile = build_tool_intent_profile(tool)
    if adapter_request.entity and profile.endpoint_root != adapter_request.entity:
        return False
    expected_shape = _preflight_read_shape(adapter_request)
    profile_shape = "single" if profile.endpoint_shape == "item" else profile.endpoint_shape
    if expected_shape != "unknown" and profile_shape != expected_shape:
        return False
    return bool({"read", "read_one", "read_many", "list"}.intersection(_actions_for_tool(tool)))


def _tool_matches_write_candidate(tool: ToolInfo, adapter_request: ToolSelectorAdapterRequest) -> bool:
    if _source_of_truth_for_tool(tool) != adapter_request.source_of_truth:
        return False
    if bool(tool.is_read_only):
        return False
    if _is_reschedule_all_tool(tool):
        return _adapter_requests_reschedule_all(adapter_request)
    profile = build_tool_intent_profile(tool)
    if adapter_request.entity and profile.endpoint_root != adapter_request.entity:
        return False
    return bool(set(_actions_for_tool(tool)).intersection(adapter_request.actions))


def _preflight_read_shape(adapter_request: ToolSelectorAdapterRequest) -> str:
    constraints = dict(adapter_request.constraints or {})
    entity = str(adapter_request.entity or "").strip()
    id_keys = ["id"]
    if entity:
        id_keys.extend([f"{entity}_id", f"{entity}_ref"])
    if any(constraints.get(key) not in (None, "", [], {}) for key in id_keys):
        return "single"
    return "collection"


def _read_preflight_rank(tool: ToolInfo, adapter_request: ToolSelectorAdapterRequest) -> tuple[int, int, int, str]:
    profile = build_tool_intent_profile(tool)
    expected_shape = _preflight_read_shape(adapter_request)
    profile_shape = "single" if profile.endpoint_shape == "item" else profile.endpoint_shape
    query_params = set(_query_params_for_tool(tool))
    constraints = dict(adapter_request.constraints or {})
    supported_filters = sum(1 for key in constraints if key in query_params)
    supports_fields = int("fields" in query_params)
    shape_match = int(profile_shape == expected_shape)
    return (-shape_match, -supported_filters, -supports_fields, tool.name)


def _write_candidate_rank(tool: ToolInfo, adapter_request: ToolSelectorAdapterRequest) -> tuple[int, int, str]:
    actions = set(_actions_for_tool(tool))
    action_match = int(bool(actions.intersection(adapter_request.actions)))
    approval_match = int(bool(tool.requires_approval))
    if _is_reschedule_all_tool(tool) and _adapter_requests_reschedule_all(adapter_request):
        action_match += 1
    return (-action_match, -approval_match, tool.name)


def _tool_satisfies_adapter_request(tool: ToolInfo, adapter_request: ToolSelectorAdapterRequest) -> bool:
    if _source_of_truth_for_tool(tool) != adapter_request.source_of_truth:
        return False
    if not bool(tool.is_read_only):
        return False
    profile = build_tool_intent_profile(tool)
    if adapter_request.entity and profile.endpoint_root != adapter_request.entity:
        return False
    profile_shape = "single" if profile.endpoint_shape == "item" else profile.endpoint_shape
    if adapter_request.endpoint_shape != "unknown" and profile_shape != adapter_request.endpoint_shape:
        return False
    actions = set(_actions_for_tool(tool))
    return bool(actions.intersection(adapter_request.actions))


def _need_has_multiple_entity_ids(capability_need: CapabilityNeed) -> bool:
    entity = str(capability_need.entity or "").strip()
    keys = ["id"]
    if entity:
        keys.extend([f"{entity}_id", f"{entity}_ref"])
    merged = {**dict(capability_need.constraints or {}), **dict(capability_need.known_args or {})}
    return any(isinstance(merged.get(key), list) and len(merged.get(key) or []) > 1 for key in keys)


def _candidate_scores(
    adapter_request: ToolSelectorAdapterRequest,
    selected_names: list[str],
    tools_by_name: Mapping[str, ToolInfo],
) -> dict[str, int]:
    if not selected_names:
        return {}
    vocabulary = vocabulary_for_tools([tools_by_name[name] for name in selected_names if name in tools_by_name])
    phrase = adapter_request.retrieval_phrase or ""
    return {
        name: score_tool(phrase, tools_by_name[name], vocabulary=vocabulary)
        for name in selected_names
        if name in tools_by_name
    }


def _expanded_actions(action: CapabilityAction) -> list[CapabilityAction]:
    if action == "read_one":
        return ["read_one", "read"]
    if action == "read_many":
        return ["read_many", "read"]
    if action == "list":
        return ["list", "read_many", "read"]
    if action == "search_documents":
        return ["search_documents", "read"]
    return [action]


def _safety_for_need(capability_need: CapabilityNeed) -> AdapterSafety:
    if capability_need.source_of_truth == "document_knowledge":
        return "read_only"
    if capability_need.action in {"read", "read_one", "read_many", "list", "search_documents"}:
        return "read_only"
    if capability_need.action in {"update", "create", "approve", "reject", "cancel"}:
        return "write_requires_approval"
    return "unknown"


def _endpoint_shape_for_need(capability_need: CapabilityNeed) -> EndpointShape:
    if capability_need.source_of_truth == "document_knowledge" or capability_need.action == "search_documents":
        return "document_search"
    if capability_need.action == "read_one":
        return "single"
    if capability_need.action in {"read_many", "list"}:
        return "collection"
    if capability_need.action in {"update", "create", "cancel"}:
        return "mutation"
    if capability_need.action in {"approve", "reject"}:
        return "approval"
    return "unknown"


def _retrieval_phrase_for_need(
    capability_need: CapabilityNeed,
    *,
    actions: list[CapabilityAction],
    constraints: Mapping[str, Any],
) -> str:
    if capability_need.source_of_truth == "document_knowledge":
        parts = ["document", "knowledge", "search", "citations", "source", "answer", "rag", "knowledge_answer_v1"]
        parts.extend(str(action) for action in actions)
        return _normalize_phrase_parts(parts)

    parts: list[str] = ["operational", "state"]
    if capability_need.entity:
        parts.append(capability_need.entity)
    if capability_need.action == "read_one":
        parts.extend(["check", "lookup", "read"])
    elif capability_need.action in {"read_many", "list"}:
        parts.extend(["list", "read", "collection"])
    elif capability_need.action == "read":
        parts.extend(["read", "get"])
    else:
        parts.append(str(capability_need.action))
    parts.extend(str(action) for action in actions)
    if capability_need.requested_fields:
        parts.append("fields")
        parts.extend(str(field) for field in capability_need.requested_fields)
    for key, value in sorted(constraints.items()):
        parts.extend(_constraint_phrase_parts(key, value))
    return _normalize_phrase_parts(parts)


def _constraint_phrase_parts(key: str, value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    parts = [str(key).replace("_", " ")]
    if isinstance(value, Mapping):
        for child_key, child_value in sorted(value.items()):
            parts.extend(_constraint_phrase_parts(str(child_key), child_value))
        return parts
    if isinstance(value, (list, tuple, set)):
        for item in value:
            parts.extend(_constraint_phrase_parts(key, item))
        return parts
    parts.append(str(value))
    return parts


def _normalize_phrase_parts(parts: list[str]) -> str:
    tokens: list[str] = []
    for part in parts:
        text = str(part or "").replace("_", " ")
        text = re.sub(r"[^A-Za-z0-9{}:/.-]+", " ", text)
        tokens.extend(piece for piece in text.split() if piece)
    return " ".join(tokens)


def _source_of_truth_for_tool(tool: ToolInfo) -> SourceOfTruth:
    tags = {_normalized_tag(tag) for tag in tool.capability_tags or []}
    contract = _output_contract_for_tool(tool, source_hint="unknown", actions=[])
    if tags & _DOCUMENT_KNOWLEDGE_TAGS or contract == "knowledge_answer_v1" or tool.name.startswith("rag_"):
        return "document_knowledge"
    return "operational_state"


def _actions_for_tool(tool: ToolInfo) -> list[CapabilityAction]:
    source = _source_of_truth_for_tool(tool)
    if source == "document_knowledge":
        return ["search_documents", "read"]
    if _is_reschedule_all_tool(tool):
        return ["update", "create"]
    method = (tool.method or "").upper()
    profile = build_tool_intent_profile(tool)
    tags = {_normalized_tag(tag) for tag in tool.capability_tags or []}
    if method == "GET":
        if profile.endpoint_shape == "collection":
            return ["list", "read_many", "read"]
        return ["read_one", "read"]
    if "approve" in tags:
        return ["approve"]
    if "reject" in tags:
        return ["reject"]
    if "cancel" in tags or method == "DELETE":
        return ["cancel"]
    if method == "POST":
        return ["create"]
    if method in {"PUT", "PATCH"}:
        return ["update"]
    return ["read"]


def _hydrate_tool_card(tool: ToolInfo) -> HydratedToolCard:
    source = _source_of_truth_for_tool(tool)
    actions = _actions_for_tool(tool)
    profile = build_tool_intent_profile(tool)
    path_params = _path_params_for_tool(tool)
    query_params = _query_params_for_tool(tool)
    required_args = _required_args_for_tool(tool, path_params=path_params)
    enum_values = _enum_values_by_field(tool.input_schema, tool.body_schema)
    filter_params = sorted(param for param in query_params if param not in _CONTROL_QUERY_FIELDS)
    sort_params = sorted(param for param in query_params if param in {"sort", "sort_by", "sort_dir"})
    limit_params = sorted(param for param in query_params if param in {"limit", "page_size"})
    schema_diagnostics = _schema_diagnostics(tool, path_params=path_params, required_args=required_args)
    metadata = {
        "method": tool.method,
        "endpoint": tool.endpoint,
        "endpoint_root": profile.endpoint_root,
        "endpoint_shape": profile.endpoint_shape,
        "param_sources": dict(tool.param_sources or {}),
        "body_fields": list(tool.body_fields or []),
        "required_body_fields": list(tool.required_body_fields or []),
        "body_schema": tool.body_schema or {},
        "side_effect_level": tool.side_effect_level,
        "capability_tags": list(tool.capability_tags or []),
        "enum_values": enum_values,
        "filter_params": filter_params,
        "filter_enums": {field: enum_values[field] for field in filter_params if field in enum_values},
        "sort_params": sort_params,
        "sort_fields": enum_values.get("sort_by") or enum_values.get("sort") or [],
        "limit_params": limit_params,
        "fields_param": "fields" in query_params,
        "output_fields": sorted(_schema_property_names(tool.output_schema)),
        "evidence_source_type": "rag_tool" if source == "document_knowledge" else "api_tool",
        "schema_diagnostics": schema_diagnostics,
    }
    if source == "document_knowledge":
        metadata.update(
            {
                "executes_rag": True,
                "rag_execution_policy": "planner_owned_tool_execution",
            }
        )

    return HydratedToolCard(
        tool_name=tool.name,
        description=tool.description,
        source_of_truth=source,
        actions=actions,
        input_schema=dict(tool.input_schema or {}),
        output_schema=dict(tool.output_schema or {}),
        required_args=required_args,
        path_params=path_params,
        query_params=query_params,
        supports_filters=bool(filter_params),
        supports_sort=bool(sort_params),
        supports_limit=bool(limit_params),
        supports_fields="fields" in query_params,
        output_contract=_output_contract_for_tool(tool, source_hint=source, actions=actions),
        is_read_only=bool(tool.is_read_only),
        requires_approval=bool(tool.requires_approval),
        metadata=metadata,
    )


def _path_params_for_tool(tool: ToolInfo) -> list[str]:
    params = list(tool.path_params or [])
    for match in _PATH_PARAM_RE.finditer(tool.endpoint or ""):
        name = match.group(1).strip()
        if name and name not in params:
            params.append(name)
    return params


def _query_params_for_tool(tool: ToolInfo) -> list[str]:
    params = list(tool.query_params or [])
    for name, source in (tool.param_sources or {}).items():
        if source == "query" and name not in params:
            params.append(name)
    return params


def _required_args_for_tool(tool: ToolInfo, *, path_params: list[str]) -> list[str]:
    required: list[str] = []
    schema_required = (tool.input_schema or {}).get("required", [])
    if isinstance(schema_required, list):
        required.extend(str(value) for value in schema_required if str(value))
    required.extend(str(value) for value in tool.required_body_fields or [] if str(value))
    required.extend(path_params)
    return list(dict.fromkeys(required))


def _schema_diagnostics(tool: ToolInfo, *, path_params: list[str], required_args: list[str]) -> list[str]:
    diagnostics: list[str] = []
    properties = _schema_properties(tool.input_schema)
    body_properties = _schema_properties(tool.body_schema)
    if path_params and not (tool.path_params or []):
        diagnostics.append("endpoint_path_params_missing_from_tool_metadata")
    for arg in required_args:
        if arg in path_params and arg not in properties:
            diagnostics.append(f"required_path_arg_missing_input_schema:{arg}")
        elif arg in (tool.required_body_fields or []) and arg not in properties and arg not in body_properties:
            diagnostics.append(f"required_body_arg_missing_schema:{arg}")
        elif arg not in path_params and arg not in (tool.required_body_fields or []) and arg not in properties:
            diagnostics.append(f"required_arg_missing_input_schema:{arg}")
    return diagnostics


def _schema_properties(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    return dict(properties) if isinstance(properties, dict) else {}


def _schema_property_names(schema: dict[str, Any] | None, *, depth: int = 0) -> set[str]:
    if not isinstance(schema, dict) or depth > 5:
        return set()
    names: set[str] = set()
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, child in properties.items():
            if str(name):
                names.add(str(name))
            if isinstance(child, dict):
                names.update(_schema_property_names(child, depth=depth + 1))
    items = schema.get("items")
    if isinstance(items, dict):
        names.update(_schema_property_names(items, depth=depth + 1))
    return names


def _enum_values_by_field(*schemas: dict[str, Any] | None) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for schema in schemas:
        for field, field_schema in _schema_properties(schema).items():
            enum_values = field_schema.get("enum") if isinstance(field_schema, dict) else None
            if isinstance(enum_values, list):
                values[field] = [str(value) for value in enum_values if str(value)]
    return values


def _output_contract_for_tool(
    tool: ToolInfo,
    *,
    source_hint: SourceOfTruth | Literal["unknown"],
    actions: list[CapabilityAction],
) -> str | None:
    for schema in (tool.input_schema, tool.output_schema):
        if not isinstance(schema, dict):
            continue
        contracts = schema.get("x-ai-response-contracts")
        if isinstance(contracts, str) and contracts.strip():
            return contracts.strip()
        if isinstance(contracts, list):
            for contract in contracts:
                if isinstance(contract, str) and contract.strip():
                    return contract.strip()
    tags = {_normalized_tag(tag) for tag in tool.capability_tags or []}
    if source_hint == "document_knowledge" or tags & _DOCUMENT_KNOWLEDGE_TAGS:
        return "knowledge_answer_v1"
    if "entity_status_v1" in tags or ("status" in tags and "read_one" in actions):
        return "entity_status_v1"
    if "result_collection_v1" in tags or "list" in actions or "read_many" in actions:
        return "result_collection_v1"
    if "business_change_v1" in tags or any(action in actions for action in ("create", "update", "approve", "reject", "cancel")):
        return "business_change_v1"
    return None


def _is_reschedule_all_tool(tool: ToolInfo) -> bool:
    endpoint = str(tool.endpoint or "").strip().lower()
    return tool.name == _RESCHEDULE_ALL_TOOL_NAME or endpoint == _RESCHEDULE_ALL_ENDPOINT


def _adapter_requests_reschedule_all(adapter_request: ToolSelectorAdapterRequest) -> bool:
    entity = str(adapter_request.entity or "").strip().lower()
    if entity and entity not in {"job", "scheduling"}:
        return False
    actions = {str(action).strip().lower() for action in adapter_request.actions or []}
    if not actions.intersection({"update", "create"}):
        return False
    constraints = dict(adapter_request.constraints or {})
    operation = str(constraints.get("operation") or "").strip().lower()
    scope = str(constraints.get("scope") or "").strip().lower()
    phrase = str(adapter_request.retrieval_phrase or "").strip().lower()
    return (
        operation == "reschedule_all"
        or (scope == "all" and "reschedule" in phrase)
        or ("reschedule" in phrase and "all" in phrase and "job" in phrase)
    )


def _compatibility_fallback_used(
    adapter_request: ToolSelectorAdapterRequest,
    selected_names: list[str],
    tools_by_name: Mapping[str, ToolInfo],
) -> bool:
    fallback_names = set(_compatibility_fallback_names(adapter_request))
    if not fallback_names:
        return False
    for name in selected_names:
        tool = tools_by_name.get(name)
        if tool and not (tool.capability_tags or []) and name in fallback_names:
            return True
    return False


def _compatibility_fallback_names(adapter_request: ToolSelectorAdapterRequest) -> list[str]:
    entity = (adapter_request.entity or "").strip().lower()
    if not entity:
        return []
    plural = entity if entity.endswith("s") else f"{entity}s"
    names: list[str] = []
    if adapter_request.endpoint_shape == "single":
        names.append(f"get__{plural}_{{id}}")
    elif adapter_request.endpoint_shape == "collection":
        names.append(f"get__{plural}")
    elif adapter_request.endpoint_shape == "mutation":
        if "create" in adapter_request.actions:
            names.append(f"post__{plural}")
        if "update" in adapter_request.actions:
            names.extend([f"put__{plural}_{{id}}", f"patch__{plural}_{{id}}"])
        if "cancel" in adapter_request.actions:
            names.append(f"post__{plural}_{{id}}_cancel")
    elif adapter_request.endpoint_shape == "approval":
        if "approve" in adapter_request.actions:
            names.append(f"post__{plural}_{{id}}_approve")
        if "reject" in adapter_request.actions:
            names.append(f"post__{plural}_{{id}}_reject")
    return names


def _normalized_tag(value: str) -> str:
    return normalize_token(str(value).replace("-", "_").replace(" ", "_"))
