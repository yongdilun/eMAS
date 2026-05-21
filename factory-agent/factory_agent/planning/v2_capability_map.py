from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..schemas import Intent, ToolInfo
from .intent import SemanticFrame, semantic_frame_for_text, split_user_intents
from .tool_intent_profile import build_tool_intent_profile, normalize_token
from .v2_contracts import (
    CapabilityAction,
    CapabilityMap,
    CapabilityMapEntry,
    CapabilityNeed,
    FieldAlias,
    FieldAliases,
    IntentOperation,
    RequirementLedger,
    RequirementLedgerEntry,
    RequirementOrigin,
    RequirementRevisionRecord,
    RequirementSketch,
    RequirementSketchItem,
    RequirementType,
    SourceOfTruth,
    ToolRetrievalSlice,
)


_CONTROL_QUERY_FIELDS = {"fields", "limit", "offset", "page", "page_size", "sort", "sort_by", "sort_dir"}
_READ_METHODS = {"GET"}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_DOC_HINT_RE = re.compile(
    r"\b(?:loto|lock\s*out|tag\s*out|lockout|tagout|procedure|procedures|sop|policy|policies|"
    r"safety|ppe|osha|manual|standard|guidance|instructions?|hazard(?:ous)?)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\b(?:limit|top|first|next)\s+(\d{1,3})\b", re.IGNORECASE)
_SORT_HINT_RE = re.compile(r"\b(?:sort(?:ed)?|order(?:ed)?|rank(?:ed)?)\s+by\b", re.IGNORECASE)
_DESC_RE = re.compile(r"\b(?:desc(?:ending)?|latest|last|furthest|highest)\b", re.IGNORECASE)
_ASC_RE = re.compile(r"\b(?:asc(?:ending)?|earliest|soonest|nearest|lowest|next|first)\b", re.IGNORECASE)
_FIELD_SEGMENT_RE = re.compile(
    r"\b(?:only|fields?|columns?|include|return|select)\b\s+"
    r"(?P<fields>.+?)(?:\s+\b(?:sorted|ordered|ranked|limit|top|next|where|for|with)\b|[.;]|$)",
    re.IGNORECASE | re.DOTALL,
)
_NEGATIVE_SAFETY_RE = re.compile(
    r"\b(?:do\s+not|don't|never|without|exclude|except)\b[^.;\n]*",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


_COMMON_FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "id": ("id", "record id"),
    "status": ("status", "state", "condition"),
    "deadline": ("deadline", "due date", "due", "due by", "required by"),
    "due_date": ("due date", "deadline", "due", "due by"),
    "priority": ("priority", "urgency"),
    "quantity": ("quantity", "qty", "amount", "count"),
    "job_id": ("job id", "work order id", "wo id", "job number", "id"),
    "machine_id": ("machine id", "equipment id", "asset id", "machine", "id"),
    "name": ("name", "label"),
    "type": ("type", "kind"),
}


def build_v2_capability_map(
    tools: Mapping[str, ToolInfo] | Iterable[ToolInfo],
    *,
    include_document_knowledge: bool = True,
) -> CapabilityMap:
    """Build the Phase 3 compact capability map from tool metadata only.

    The map intentionally carries endpoint and contract hints, not full input or
    output schemas. Hydrated schemas belong to the later candidate-window phase.
    """

    tool_list = _tool_list(tools)
    aliases = field_aliases_from_tools(tool_list)
    capabilities = [_capability_entry_for_tool(tool) for tool in tool_list]
    if include_document_knowledge:
        capabilities.extend(_document_knowledge_capabilities())
    capabilities.sort(key=lambda item: item.capability_id)
    return CapabilityMap(capabilities=capabilities, field_aliases=aliases)


def field_aliases_from_tools(tools: Mapping[str, ToolInfo] | Iterable[ToolInfo]) -> FieldAliases:
    tool_list = _tool_list(tools)
    aliases_by_key: dict[tuple[str, str | None], set[str]] = {}
    source_by_key: dict[tuple[str, str | None], str] = {}

    for tool in tool_list:
        entity = _tool_entity(tool)
        for field_name, field_schema in _tool_fields(tool).items():
            canonical = _canonical_field_name(field_name, field_schema, entity=entity)
            key = (canonical, entity)
            aliases_by_key.setdefault(key, set()).update(
                _aliases_for_field(field_name, field_schema, entity=entity, canonical=canonical)
            )
            source_by_key.setdefault(key, "tool_metadata")

    for entity in sorted({_tool_entity(tool) for tool in tool_list if _tool_entity(tool)}):
        canonical = f"{entity}_id"
        key = (canonical, entity)
        aliases_by_key.setdefault(key, set()).update(_COMMON_FIELD_TERMS.get(canonical, ()))
        aliases_by_key[key].update({f"{entity} id", "id"})
        source_by_key.setdefault(key, "derived_entity_id")

    return FieldAliases(
        aliases=[
            FieldAlias(
                canonical_field=canonical,
                entity=entity,
                user_terms=sorted(terms, key=lambda value: (len(value), value)),
                source=source_by_key.get((canonical, entity)),
            )
            for (canonical, entity), terms in sorted(aliases_by_key.items())
            if canonical and terms
        ]
    )


def resolve_field_alias(term: str, aliases: FieldAliases, *, entity: str | None = None) -> str | None:
    normalized = _normalize_phrase(term)
    if not normalized:
        return None

    candidates = _alias_candidates(aliases, entity=entity)
    for alias in candidates:
        terms = {_normalize_phrase(alias.canonical_field), *(_normalize_phrase(item) for item in alias.user_terms)}
        if normalized in terms:
            return alias.canonical_field
    return None


def normalize_requested_fields(
    terms: Iterable[str],
    aliases: FieldAliases,
    *,
    entity: str | None = None,
) -> list[str]:
    fields: list[str] = []
    seen: set[str] = set()
    for term in terms:
        canonical = resolve_field_alias(term, aliases, entity=entity)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        fields.append(canonical)
    return fields


def classify_source_of_truth(text: str, *, capability_map: CapabilityMap | None = None) -> SourceOfTruth:
    needs = build_capability_needs_for_text(text, capability_map=capability_map)
    sources = {need.source_of_truth for need in needs if need.source_of_truth != "unknown"}
    if len(sources) > 1:
        return "mixed"
    if len(sources) == 1:
        return next(iter(sources))
    return "unknown"


def build_capability_needs_for_text(
    text: str,
    *,
    capability_map: CapabilityMap | None = None,
) -> list[CapabilityNeed]:
    sketch = build_requirement_sketch_for_text(text, capability_map=capability_map)
    needs: list[CapabilityNeed] = []
    for requirement in sketch.requirements:
        action = _capability_action_for_requirement(requirement.requirement_type, requirement.source_of_truth)
        id_args = {
            key: value
            for key, value in requirement.constraints.items()
            if key.endswith("_id") or key in {"id", "machine_ref"}
        }
        needs.append(
            CapabilityNeed(
                requirement_id=requirement.id,
                source_of_truth=requirement.source_of_truth,
                entity=requirement.entity,
                action=action,
                known_args=id_args,
                constraints=dict(requirement.constraints),
                requested_fields=list(requirement.requested_fields),
                reason=f"deterministic_source_hint:{requirement.source_of_truth}",
            )
        )
    return needs


def build_requirement_sketch_for_text(
    text: str,
    *,
    capability_map: CapabilityMap | None = None,
) -> RequirementSketch:
    capability_map = capability_map or CapabilityMap()
    aliases = capability_map.field_aliases
    intents = _prepare_requirement_intents(split_user_intents(text), aliases)
    requirements: list[RequirementSketchItem] = []
    slices: list[ToolRetrievalSlice] = []

    for index, intent in enumerate(intents, start=1):
        clause = intent.description
        frame = semantic_frame_for_text(clause)
        source = _source_for_frame(frame, clause)
        entity = _entity_for_hint(frame, clause, source)

        previous_modifier = _previous_requirement_modifier_for_clause(clause)
        if previous_modifier and requirements:
            previous = requirements[-1]
            for key, value in previous_modifier.items():
                previous.constraints[key] = value
                if key not in previous.locked_constraints:
                    previous.locked_constraints.append(key)
            if slices:
                slices[-1].constraints.update(previous_modifier)
            continue

        conditional_branch = _conditional_branch_for_clause(
            clause,
            capability_map=capability_map,
            entity=entity,
        )
        if conditional_branch and requirements:
            previous = requirements[-1]
            previous.constraints.setdefault("conditional_branches", []).append(conditional_branch)
            if "conditional_branches" not in previous.locked_constraints:
                previous.locked_constraints.append("conditional_branches")
            if slices:
                slices[-1].constraints.setdefault("conditional_branches", []).append(conditional_branch)
            continue

        constraints = _constraints_for_clause(
            clause,
            intent=intent,
            frame=frame,
            source_of_truth=source,
            entity=entity,
            capability_map=capability_map,
        )
        requested_fields = _requested_fields_for_clause(
            clause,
            aliases,
            entity=entity,
            source_of_truth=source,
        )
        for field in ("sort_by",):
            value = constraints.get(field)
            if isinstance(value, str) and value not in requested_fields:
                requested_fields.append(value)
        requirement_type, intent_operation = _requirement_shape_for(frame, source, entity, constraints)
        requested_fields = _requested_fields_with_row_identity(
            requested_fields,
            entity=entity,
            requirement_type=requirement_type,
            source_of_truth=source,
        )
        locked_constraints = _locked_constraints_for(constraints, requested_fields)
        requirement_id = f"req-{index:03d}"

        requirement = RequirementSketchItem(
            id=requirement_id,
            goal=clause,
            requirement_type=requirement_type,
            entity=entity,
            intent_operation=intent_operation,
            source_of_truth=source,
            constraints=constraints,
            requested_fields=requested_fields,
            locked_constraints=locked_constraints,
            origin=RequirementOrigin(
                goal="deterministic_requirement_sketch",
                constraints="deterministic_extraction",
                fields="metadata_field_aliases",
                source_of_truth="capability_map_hint",
            ),
        )
        requirements.append(requirement)
        slices.append(
            ToolRetrievalSlice(
                slice_id=f"slice-{index:03d}",
                text=clause,
                source_of_truth_hint=source,
                entity=entity,
                actions=[_capability_action_for_requirement(requirement_type, source)],
                constraints=constraints,
                requested_fields=requested_fields,
            )
        )

    return RequirementSketch(
        user_goal=text,
        requirements=requirements,
        field_aliases=aliases,
        tool_retrieval_slices=slices,
    )


def _prepare_requirement_intents(intents: list[Intent], aliases: FieldAliases) -> list[Intent]:
    coalesced = _coalesce_field_continuation_intents(intents, aliases)
    prepared: list[Intent] = []
    for intent in coalesced:
        prepared.extend(_expand_mixed_entity_intent(intent))
    return prepared


def _coalesce_field_continuation_intents(intents: list[Intent], aliases: FieldAliases) -> list[Intent]:
    coalesced: list[Intent] = []
    for intent in intents:
        if coalesced and _is_field_continuation_clause(
            intent.description,
            previous_clause=coalesced[-1].description,
            aliases=aliases,
        ):
            merged_clause = f"{coalesced[-1].description}, {intent.description}"
            merged = split_user_intents(merged_clause)[0]
            coalesced[-1] = merged.model_copy(
                update={
                    "intent_id": coalesced[-1].intent_id,
                    "depends_on": coalesced[-1].depends_on,
                }
            )
            continue
        coalesced.append(intent)
    return coalesced


def _is_field_continuation_clause(
    clause: str,
    *,
    previous_clause: str,
    aliases: FieldAliases,
) -> bool:
    if not _FIELD_SEGMENT_RE.search(previous_clause):
        return False
    if split_user_intents(clause)[0].explicit_constraints:
        return False
    frame = semantic_frame_for_text(clause)
    if frame.route != "unknown" or frame.entity:
        return False
    fields = _requested_fields_for_clause(
        clause,
        aliases,
        entity=None,
        source_of_truth="operational_state",
    )
    return bool(fields)


def _expand_mixed_entity_intent(intent: Intent) -> list[Intent]:
    grouped: dict[str, list[Any]] = {}
    for constraint in intent.explicit_constraints:
        entity = _entity_from_constraint_field(constraint.field)
        if entity is None:
            continue
        grouped.setdefault(entity, []).append(constraint.value)
    if len(grouped) <= 1:
        return [intent]

    field_suffix = _field_context_suffix(intent.description)
    expanded: list[Intent] = []
    index = 0
    for entity, values in grouped.items():
        for value in _unique_values(values):
            index += 1
            clause = f"show {entity} id {value}{field_suffix}"
            generated = split_user_intents(clause)[0]
            expanded.append(
                generated.model_copy(
                    update={
                        "intent_id": f"{intent.intent_id}:entity-{index}",
                        "depends_on": list(intent.depends_on),
                    }
                )
            )
    return expanded


def _entity_from_constraint_field(field: str | None) -> str | None:
    if not field:
        return None
    if field == "machine_ref":
        return "machine"
    if field.endswith("_id"):
        entity = field[:-3]
        return entity or None
    return None


def _field_context_suffix(clause: str) -> str:
    fields: list[str] = []
    lowered = clause.lower()
    for field in ("status", "details"):
        if _contains_term(lowered, field):
            fields.append(field)
    return f" {' '.join(fields)}" if fields else ""


def _unique_values(values: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for value in values:
        if isinstance(value, list):
            nested = value
        else:
            nested = [value]
        for item in nested:
            key = str(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
    return unique


def build_requirement_ledger_from_sketch(sketch: RequirementSketch) -> RequirementLedger:
    return RequirementLedger(
        user_goal=sketch.user_goal,
        requirements=[
            RequirementLedgerEntry(
                id=item.id,
                goal=item.goal,
                requirement_type=item.requirement_type,
                entity=item.entity,
                intent_operation=item.intent_operation,
                source_of_truth=item.source_of_truth,
                constraints=dict(item.constraints),
                requested_fields=list(item.requested_fields),
                locked_constraints=list(item.locked_constraints),
                status="open",
                origin=item.origin,
            )
            for item in sketch.requirements
        ],
        revision=1,
        revision_history=[
            RequirementRevisionRecord(
                revision=1,
                actor="deterministic_guard",
                change_type="initial_requirement_sketch",
                reason="Phase 3 locked hard constraints before planner execution.",
                locked_constraints_preserved=True,
            )
        ],
    )


def _tool_list(tools: Mapping[str, ToolInfo] | Iterable[ToolInfo]) -> list[ToolInfo]:
    if isinstance(tools, Mapping):
        return [tools[name] for name in sorted(tools)]
    return sorted(list(tools), key=lambda tool: tool.name)


def _document_knowledge_capabilities() -> list[CapabilityMapEntry]:
    return [
        CapabilityMapEntry(
            capability_id="knowledge.rag.loto_procedure",
            source_of_truth="document_knowledge",
            entity="procedure",
            actions=["search_documents", "read"],
            supports=["citations", "document_search", "procedure"],
            output_contract="knowledge_answer_v1",
            metadata={
                "capability_family": "document_knowledge",
                "knowledge_family": "loto_procedure",
                "rag_tool_contract": "knowledge_answer_v1",
            },
        ),
        CapabilityMapEntry(
            capability_id="knowledge.rag.procedure",
            source_of_truth="document_knowledge",
            entity="procedure",
            actions=["search_documents", "read"],
            supports=["citations", "document_search", "procedure"],
            output_contract="knowledge_answer_v1",
            metadata={
                "capability_family": "document_knowledge",
                "knowledge_family": "procedure",
                "rag_tool_contract": "knowledge_answer_v1",
            },
        ),
        CapabilityMapEntry(
            capability_id="knowledge.rag.safety_policy",
            source_of_truth="document_knowledge",
            entity="policy",
            actions=["search_documents", "read"],
            supports=["citations", "document_search", "policy"],
            output_contract="knowledge_answer_v1",
            metadata={
                "capability_family": "document_knowledge",
                "knowledge_family": "safety_policy",
                "rag_tool_contract": "knowledge_answer_v1",
            },
        ),
    ]


def _capability_entry_for_tool(tool: ToolInfo) -> CapabilityMapEntry:
    entity = _tool_entity(tool)
    actions = _actions_for_tool(tool)
    output_contract = _output_contract_for_tool(tool, actions=actions)
    metadata = _compact_tool_metadata(tool, entity=entity)
    return CapabilityMapEntry(
        capability_id=_capability_id(tool, entity=entity, actions=actions, output_contract=output_contract),
        source_of_truth="operational_state",
        entity=entity,
        actions=actions,
        supports=_supports_for_tool(tool),
        output_contract=output_contract,
        requires_approval=bool(tool.requires_approval),
        metadata=metadata,
    )


def _compact_tool_metadata(tool: ToolInfo, *, entity: str | None) -> dict[str, Any]:
    fields = _tool_fields(tool)
    query_fields = set(tool.query_params or [])
    query_fields.update(key for key, source in (tool.param_sources or {}).items() if source == "query")
    filter_fields = sorted(field for field in query_fields if field not in _CONTROL_QUERY_FIELDS)
    sort_values = _enum_values(fields.get("sort_by", {})) or _enum_values(fields.get("sort", {}))
    filter_enums = {
        field: _enum_values(fields[field])
        for field in filter_fields
        if field in fields and _enum_values(fields[field])
    }
    required_args = [str(value) for value in (tool.input_schema or {}).get("required", []) if str(value)]
    if not required_args:
        required_args = list(tool.path_params or [])

    return {
        "tool_name": tool.name,
        "method": tool.method,
        "endpoint_root": _endpoint_root(tool),
        "endpoint_shape": build_tool_intent_profile(tool).endpoint_shape,
        "entity": entity,
        "path_params": list(tool.path_params or []),
        "query_params": list(tool.query_params or []),
        "body_fields": list(tool.body_fields or []),
        "required_args": required_args,
        "filter_fields": filter_fields,
        "filter_enums": filter_enums,
        "sort_fields": sort_values,
        "limit_fields": sorted(field for field in query_fields if field in {"limit", "page_size"}),
        "field_selector": "fields" in query_fields,
        "read_only": bool(tool.is_read_only),
        "requires_approval": bool(tool.requires_approval),
        "side_effect_level": tool.side_effect_level,
        "capability_tags": list(tool.capability_tags or []),
    }


def _tool_entity(tool: ToolInfo) -> str | None:
    for schema in (tool.input_schema, tool.output_schema, tool.body_schema):
        entity = _schema_ai_entity(schema)
        if entity:
            return normalize_token(entity)

    ignored = {
        "read",
        "lookup",
        "list",
        "status",
        "create",
        "update",
        "delete",
        "approve",
        "reject",
        "cancel",
        "collection",
        "result",
        "entity",
    }
    for tag in tool.capability_tags or []:
        normalized = normalize_token(str(tag))
        if normalized and normalized not in ignored:
            return normalized

    root = _endpoint_root(tool)
    return normalize_token(root) if root else None


def _schema_ai_entity(schema: dict[str, Any] | None) -> str | None:
    if not isinstance(schema, dict):
        return None
    entity = schema.get("x-ai-entity")
    if isinstance(entity, str) and entity.strip():
        return entity
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for child in properties.values():
            found = _schema_ai_entity(child if isinstance(child, dict) else None)
            if found:
                return found
    items = schema.get("items")
    if isinstance(items, dict):
        return _schema_ai_entity(items)
    return None


def _endpoint_root(tool: ToolInfo) -> str | None:
    for part in (tool.endpoint or "").strip("/").split("/"):
        if not part or (part.startswith("{") and part.endswith("}")):
            continue
        return part[:-1] if part.endswith("s") and len(part) > 3 else part
    return None


def _actions_for_tool(tool: ToolInfo) -> list[CapabilityAction]:
    profile = build_tool_intent_profile(tool)
    method = (tool.method or "").upper()
    tags = {normalize_token(tag) for tag in tool.capability_tags or []}

    if method in _READ_METHODS:
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
    if method in _WRITE_METHODS:
        return ["update"]
    return ["read"]


def _supports_for_tool(tool: ToolInfo) -> list[str]:
    fields = set(tool.query_params or [])
    fields.update(key for key, source in (tool.param_sources or {}).items() if source == "query")
    supports: set[str] = set()
    if tool.path_params:
        supports.add("path_params")
    if fields - _CONTROL_QUERY_FIELDS:
        supports.add("filters")
    if "fields" in fields:
        supports.add("fields")
    if {"sort", "sort_by", "sort_dir"} & fields:
        supports.add("sort")
    if {"limit", "page_size"} & fields:
        supports.add("limit")
    if tool.body_fields:
        supports.add("body")
    if tool.requires_approval:
        supports.add("approval_required")
    return sorted(supports)


def _output_contract_for_tool(tool: ToolInfo, *, actions: list[CapabilityAction]) -> str | None:
    for schema in (tool.input_schema, tool.output_schema):
        contracts = schema.get("x-ai-response-contracts") if isinstance(schema, dict) else None
        if isinstance(contracts, list):
            for contract in contracts:
                if isinstance(contract, str) and contract.strip():
                    return contract
        if isinstance(contracts, str) and contracts.strip():
            return contracts

    tags = {normalize_token(tag) for tag in tool.capability_tags or []}
    if "status" in tags and "read_one" in actions:
        return "entity_status_v1"
    if "list" in actions or "read_many" in actions:
        return "result_collection_v1"
    if any(action in actions for action in ("create", "update", "approve", "reject", "cancel")):
        return "business_change_v1"
    return None


def _capability_id(
    tool: ToolInfo,
    *,
    entity: str | None,
    actions: list[CapabilityAction],
    output_contract: str | None,
) -> str:
    entity_part = entity or "tool"
    tags = {normalize_token(tag) for tag in tool.capability_tags or []}
    if "status" in tags or output_contract == "entity_status_v1":
        feature = "status"
    elif "list" in actions:
        feature = "collection"
    elif output_contract:
        feature = output_contract.replace("_v1", "")
    else:
        feature = _endpoint_root(tool) or "capability"
    action_part = "read" if any(action in actions for action in ("read", "read_one", "read_many", "list")) else actions[0]
    return ".".join(_slug(part) for part in (entity_part, action_part, feature) if part)


def _tool_fields(tool: ToolInfo) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for schema in (tool.input_schema, tool.output_schema, tool.body_schema):
        for name, field_schema in _iter_schema_properties(schema):
            fields.setdefault(name, field_schema)
    for name in [*(tool.path_params or []), *(tool.query_params or []), *(tool.body_fields or [])]:
        fields.setdefault(str(name), {})
    return fields


def _iter_schema_properties(schema: dict[str, Any] | None, *, depth: int = 0) -> Iterable[tuple[str, dict[str, Any]]]:
    if not isinstance(schema, dict) or depth > 4:
        return
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, child in properties.items():
            child_schema = child if isinstance(child, dict) else {}
            yield str(name), child_schema
            yield from _iter_schema_properties(child_schema, depth=depth + 1)
    items = schema.get("items")
    if isinstance(items, dict):
        yield from _iter_schema_properties(items, depth=depth + 1)


def _canonical_field_name(field_name: str, field_schema: dict[str, Any], *, entity: str | None) -> str:
    explicit = field_schema.get("x-ai-id-field") if isinstance(field_schema, dict) else None
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    normalized = str(field_name or "").strip()
    if normalized == "id" and entity:
        return f"{entity}_id"
    return normalized


def _aliases_for_field(
    field_name: str,
    field_schema: dict[str, Any],
    *,
    entity: str | None,
    canonical: str,
) -> set[str]:
    terms: set[str] = {canonical, canonical.replace("_", " "), field_name, str(field_name).replace("_", " ")}
    for part in re.split(r"[_\W]+", str(canonical)):
        if part:
            terms.add(part)
    terms.update(_COMMON_FIELD_TERMS.get(canonical, ()))
    if canonical.endswith("_id"):
        entity_term = canonical[:-3].replace("_", " ")
        terms.update({"id", f"{entity_term} id"})
    if field_name == "id" and entity:
        terms.update({"id", f"{entity} id"})

    if isinstance(field_schema, dict):
        for key in ("x-ai-aliases", "x-ai-field-aliases", "x-ai-user-terms"):
            raw_aliases = field_schema.get(key)
            if isinstance(raw_aliases, list):
                terms.update(str(value).strip() for value in raw_aliases if str(value).strip())
        title = field_schema.get("title")
        if isinstance(title, str) and title.strip():
            terms.add(title.strip())
    return {_normalize_phrase(term) for term in terms if _normalize_phrase(term)}


def _enum_values(field_schema: dict[str, Any]) -> list[str]:
    values = field_schema.get("enum") if isinstance(field_schema, dict) else None
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value)]


def _source_for_frame(frame: SemanticFrame, clause: str) -> SourceOfTruth:
    if frame.route.startswith("rag.") or frame.domain_intent in {"loto_procedure", "document_procedure", "safety_policy"}:
        return "document_knowledge"
    if frame.route.startswith("tool.") or frame.route in {"approval_action", "cancel_run"}:
        return "operational_state"
    if frame.route.startswith("clarification.") and _DOC_HINT_RE.search(clause):
        return "document_knowledge"
    if frame.entity in {"machine", "job", "inventory", "product", "approval", "session"}:
        return "operational_state"
    if _DOC_HINT_RE.search(clause):
        return "document_knowledge"
    return "unknown"


def _entity_for_hint(frame: SemanticFrame, clause: str, source: SourceOfTruth) -> str | None:
    if source == "document_knowledge":
        lowered = clause.lower()
        if "policy" in lowered or "osha" in lowered or "ppe" in lowered or "safety" in lowered:
            return "policy"
        return "procedure"
    if frame.entity:
        return frame.entity
    if "job" in clause.lower() or "work order" in clause.lower():
        return "job"
    if "machine" in clause.lower() or "equipment" in clause.lower():
        return "machine"
    return None


def _constraints_for_clause(
    clause: str,
    *,
    intent: Intent,
    frame: SemanticFrame,
    source_of_truth: SourceOfTruth,
    entity: str | None,
    capability_map: CapabilityMap,
) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    for constraint in intent.explicit_constraints:
        if constraint.strength != "hard" or not constraint.field:
            continue
        _merge_constraint_value(constraints, constraint.field, constraint.value)
    source_priority = frame.normalized_entities.get("from_priority") or []
    target_priority = frame.normalized_entities.get("to_priority") or []
    if source_priority:
        constraints["priority"] = source_priority[0] if len(source_priority) == 1 else list(source_priority)
    if target_priority:
        constraints["new_priority"] = target_priority[0] if len(target_priority) == 1 else list(target_priority)
    for field, values in frame.normalized_entities.items():
        if not values:
            continue
        if field in {"topic"}:
            continue
        target_field = "priority" if field == "from_priority" else field
        if field == "to_priority":
            target_field = "new_priority"
        if target_field not in constraints:
            constraints[target_field] = values[0] if len(values) == 1 else list(values)

    metadata = _metadata_for_entity(capability_map, entity=entity, source=source_of_truth)
    filter_enums = _filter_enums(metadata)
    for field, enum_values in filter_enums.items():
        if field in constraints:
            continue
        matched = _enum_filter_value(clause, field, enum_values, capability_map.field_aliases, entity=entity)
        if matched is not None:
            constraints[field] = matched

    sort_by = _sort_field_for_clause(clause, metadata, capability_map.field_aliases, entity=entity)
    if sort_by:
        constraints["sort_by"] = sort_by
        constraints["sort_dir"] = "desc" if _DESC_RE.search(clause) else "asc"
    limit = _limit_for_clause(clause, metadata)
    if limit is not None:
        constraints["limit"] = limit

    safety_constraints = _safety_constraints_for_clause(clause)
    if safety_constraints:
        constraints["safety_constraints"] = safety_constraints

    if frame.requires_approval or re.search(r"\b(?:approval|approve|ask\s+approval|before\s+applying)\b", clause, re.I):
        constraints["requires_approval"] = True

    return constraints


def _merge_constraint_value(constraints: dict[str, Any], field: str, value: Any) -> None:
    if field not in constraints:
        constraints[field] = value
        return
    existing = constraints[field]
    values = existing if isinstance(existing, list) else [existing]
    incoming = value if isinstance(value, list) else [value]
    for item in incoming:
        if item not in values:
            values.append(item)
    constraints[field] = values


def _conditional_branch_for_clause(
    clause: str,
    *,
    capability_map: CapabilityMap,
    entity: str | None,
) -> dict[str, Any] | None:
    if not re.search(r"\bif\s+any\b", clause, re.IGNORECASE):
        return None
    if not re.search(r"\bexplain\b", clause, re.IGNORECASE):
        return None

    metadata = _metadata_for_entity(capability_map, entity=entity, source="operational_state")
    status_values = _filter_enums(metadata).get("status", [])
    condition_value = next(
        (value for value in status_values if _contains_term(clause, value)),
        None,
    )
    if condition_value is None:
        return None

    branch: dict[str, Any] = {
        "branch_type": "conditional_explanation",
        "condition_field": "status",
        "condition_value": condition_value,
        "required_evidence": "typed_explanation",
        "planner_action": "continue_for_explanation_before_update_suggestion",
    }
    if re.search(r"\bbefore\b.*\b(?:suggest|recommend)", clause, re.IGNORECASE):
        branch["ordering"] = "explain_before_suggestion"
    return branch


def _previous_requirement_modifier_for_clause(clause: str) -> dict[str, Any] | None:
    modifiers: dict[str, Any] = {}
    if re.match(r"\s*(?:do\s+not|don't|never|without|exclude|except)\b", clause, re.IGNORECASE):
        negative_safety = [
            match.group(0).strip(" .;")
            for match in _NEGATIVE_SAFETY_RE.finditer(clause)
            if match.group(0).strip(" .;")
        ]
        if negative_safety:
            modifiers["safety_constraints"] = negative_safety
    if re.search(r"\b(?:show|preview|summari[sz]e)\b.*\b(?:would\s+change|changes?)\b", clause, re.IGNORECASE):
        modifiers["preview_before_apply"] = True
    if re.search(r"\b(?:ask|request|require)\b.*\bapproval\b", clause, re.IGNORECASE):
        modifiers["requires_approval"] = True
    if not modifiers:
        return None
    return modifiers


def _metadata_for_entity(
    capability_map: CapabilityMap,
    *,
    entity: str | None,
    source: SourceOfTruth,
) -> list[dict[str, Any]]:
    return [
        entry.metadata
        for entry in capability_map.capabilities
        if entry.source_of_truth == source and (entity is None or entry.entity == entity)
    ]


def _filter_enums(metadata_entries: list[dict[str, Any]]) -> dict[str, list[str]]:
    enums: dict[str, list[str]] = {}
    for metadata in metadata_entries:
        raw = metadata.get("filter_enums")
        if not isinstance(raw, dict):
            continue
        for field, values in raw.items():
            if isinstance(values, list):
                enums[str(field)] = [str(value) for value in values if str(value)]
    return enums


def _enum_filter_value(
    text: str,
    field: str,
    enum_values: list[str],
    aliases: FieldAliases,
    *,
    entity: str | None,
) -> str | None:
    alias_terms = _terms_for_field(field, aliases, entity=entity)
    for value in enum_values:
        value_pattern = re.escape(value).replace(r"\ ", r"[ _-]+")
        for alias in alias_terms:
            alias_pattern = re.escape(alias).replace(r"\ ", r"[ _-]+")
            if re.search(rf"\b{value_pattern}\b[\s-]+{alias_pattern}\b", text, re.I):
                return value
            if re.search(rf"\b{alias_pattern}\b\s*(?:=|:|is|are|to|as)?\s*\b{value_pattern}\b", text, re.I):
                return value
    return None


def _sort_field_for_clause(
    text: str,
    metadata_entries: list[dict[str, Any]],
    aliases: FieldAliases,
    *,
    entity: str | None,
) -> str | None:
    if not _SORT_HINT_RE.search(text):
        return None
    sort_fields: list[str] = []
    for metadata in metadata_entries:
        values = metadata.get("sort_fields")
        if isinstance(values, list):
            sort_fields.extend(str(value) for value in values if str(value))
    for field in sort_fields:
        for term in _terms_for_field(field, aliases, entity=entity):
            if _contains_term(text, term):
                return field
    return None


def _limit_for_clause(text: str, metadata_entries: list[dict[str, Any]]) -> int | None:
    supports_limit = any(metadata.get("limit_fields") for metadata in metadata_entries)
    if not supports_limit:
        return None
    match = _LIMIT_RE.search(text)
    if not match:
        return None
    return max(1, min(int(match.group(1)), 500))


def _safety_constraints_for_clause(text: str) -> list[str]:
    constraints: list[str] = []
    for match in _NEGATIVE_SAFETY_RE.finditer(text):
        value = re.sub(r"\s+", " ", match.group(0)).strip(" ,")
        if value:
            constraints.append(value)
    if re.search(r"\b(?:safety|hazard(?:ous)?|loto|lockout|tagout|ppe)\b", text, re.I):
        constraints.append("preserve safety requirements")
    return list(dict.fromkeys(constraints))


def _requested_fields_for_clause(
    clause: str,
    aliases: FieldAliases,
    *,
    entity: str | None,
    source_of_truth: SourceOfTruth,
) -> list[str]:
    if source_of_truth == "document_knowledge":
        return []

    fields: list[str] = []
    seen: set[str] = set()

    def add(field: str | None) -> None:
        if not field or field in seen:
            return
        seen.add(field)
        fields.append(field)

    for segment_match in _FIELD_SEGMENT_RE.finditer(clause):
        segment = segment_match.group("fields")
        for field in _fields_mentioned(segment, aliases, entity=entity):
            add(field)

    if fields:
        return fields

    for alias in _alias_candidates(aliases, entity=entity):
        if alias.canonical_field in _CONTROL_QUERY_FIELDS:
            continue
        if alias.canonical_field.endswith("_id"):
            continue
        if alias.canonical_field not in {"status", "deadline", "due_date", "quantity"}:
            continue
        if any(_contains_term(clause, term) for term in [alias.canonical_field, *alias.user_terms]):
            add(alias.canonical_field)

    return fields


def _requested_fields_with_row_identity(
    requested_fields: list[str],
    *,
    entity: str | None,
    requirement_type: RequirementType,
    source_of_truth: SourceOfTruth,
) -> list[str]:
    if (
        source_of_truth != "operational_state"
        or not entity
        or requirement_type not in {"filtered_collection", "multi_entity_status"}
        or not requested_fields
    ):
        return requested_fields
    identity_field = f"{entity}_id"
    return list(dict.fromkeys([identity_field, *requested_fields]))


def _fields_mentioned(text: str, aliases: FieldAliases, *, entity: str | None) -> list[str]:
    positions: dict[str, int] = {}
    for alias in _alias_candidates(aliases, entity=entity):
        if alias.canonical_field in _CONTROL_QUERY_FIELDS:
            continue
        matches = [
            _term_position(text, term)
            for term in _field_selector_terms(alias, entity=entity)
        ]
        matches = [position for position in matches if position is not None]
        if matches:
            positions[alias.canonical_field] = min(matches)
    return [
        field
        for field, _position in sorted(positions.items(), key=lambda item: (item[1], item[0]))
    ]


def _field_selector_terms(alias: FieldAlias, *, entity: str | None) -> list[str]:
    canonical = str(alias.canonical_field or "")
    canonical_terms = {_normalize_phrase(canonical), _normalize_phrase(canonical.replace("_", " "))}
    common_terms = {_normalize_phrase(term) for term in _COMMON_FIELD_TERMS.get(canonical, ())}
    primary_id_terms: set[str] = set()
    if entity and canonical == f"{entity}_id":
        primary_id_terms.update({_normalize_phrase("id"), _normalize_phrase(f"{entity} id")})

    allowed: list[str] = []
    compound_parts = {_normalize_phrase(part) for part in canonical.split("_") if part}
    for term in [canonical, *alias.user_terms]:
        normalized = _normalize_phrase(term)
        if not normalized:
            continue
        if (
            canonical.endswith("_id")
            and entity
            and canonical != f"{entity}_id"
            and normalized == "id"
        ):
            continue
        if (
            normalized in canonical_terms
            or normalized in common_terms
            or normalized in primary_id_terms
            or normalized not in compound_parts
        ):
            allowed.append(normalized)
    return list(dict.fromkeys(allowed))


def _terms_for_field(field: str, aliases: FieldAliases, *, entity: str | None) -> list[str]:
    terms: list[str] = []
    for alias in _alias_candidates(aliases, entity=entity):
        if alias.canonical_field == field:
            terms.extend([alias.canonical_field, *alias.user_terms])
    if not terms:
        terms.extend([field, field.replace("_", " ")])
        terms.extend(_COMMON_FIELD_TERMS.get(field, ()))
    return sorted({_normalize_phrase(term) for term in terms if _normalize_phrase(term)}, key=len, reverse=True)


def _alias_candidates(aliases: FieldAliases, *, entity: str | None) -> list[FieldAlias]:
    return [
        alias
        for alias in aliases.aliases
        if alias.entity in {entity, None} or entity is None
    ]


def _contains_term(text: str, term: str) -> bool:
    return _term_position(text, term) is not None


def _term_position(text: str, term: str) -> int | None:
    normalized = _normalize_phrase(term)
    if not normalized:
        return None
    pattern = re.escape(normalized).replace(r"\ ", r"[ _-]+")
    match = re.search(rf"\b{pattern}\b", _normalize_phrase(text), re.I)
    return match.start() if match else None


def _locked_constraints_for(constraints: dict[str, Any], requested_fields: list[str]) -> list[str]:
    locked = [key for key, value in constraints.items() if value not in (None, "", [], {})]
    if requested_fields:
        locked.append("requested_fields")
    return list(dict.fromkeys(locked))


def _requirement_shape_for(
    frame: SemanticFrame,
    source: SourceOfTruth,
    entity: str | None,
    constraints: dict[str, Any],
) -> tuple[RequirementType, IntentOperation]:
    if source == "document_knowledge":
        return "document_answer", "answer_document_question"
    if source == "unknown":
        return "clarification_request", "request_clarification"
    if frame.route == "approval_action":
        return "approval_request", "request_approval"
    if frame.route == "unsupported_dangerous_action":
        return "safety_refusal", "refuse_for_safety"
    if frame.requires_approval or constraints.get("requires_approval") or frame.action in {"create", "update", "delete"}:
        return "mutation_request", "stage_mutation"
    if entity and _has_multiple_entity_ids(constraints):
        return "multi_entity_status", "report_multi_status"
    if entity and any(key.endswith("_id") or key in {"id", "machine_ref"} for key in constraints):
        return "single_entity_status", "report_status"
    if entity and ({"limit", "sort_by"} & constraints.keys() or any(key in constraints for key in ("priority", "status"))):
        return "filtered_collection", "report_filtered_collection"
    if entity:
        return "multi_entity_status", "report_multi_status"
    return "diagnostic", "report_diagnostic"


def _has_multiple_entity_ids(constraints: Mapping[str, Any]) -> bool:
    count = 0
    for key, value in constraints.items():
        if not (key.endswith("_id") or key in {"id", "machine_ref"}):
            continue
        if isinstance(value, list):
            count += len([item for item in value if item not in (None, "", [], {})])
        elif value not in (None, "", [], {}):
            count += 1
    return count > 1


def _capability_action_for_requirement(
    requirement_type: RequirementType,
    source: SourceOfTruth,
) -> CapabilityAction:
    if source == "document_knowledge" or requirement_type == "document_answer":
        return "search_documents"
    if requirement_type == "single_entity_status":
        return "read_one"
    if requirement_type in {"filtered_collection", "multi_entity_status"}:
        return "list"
    if requirement_type == "approval_request":
        return "approve"
    if requirement_type == "mutation_request":
        return "update"
    return "read"


def _normalize_phrase(value: str) -> str:
    tokens = [normalize_token(match.group(0)) for match in _WORD_RE.finditer(value or "")]
    return " ".join(token for token in tokens if token)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _normalize_phrase(value)).strip("_") or "unknown"
