from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..schemas import Intent, ToolInfo
from .intent import SemanticFrame, semantic_frame_for_text, split_user_intents
from .semantic_intake import (
    SemanticIntakeItem,
    SemanticIntakeProposer,
    SemanticIntakeResult,
    propose_semantic_intake_for_text,
)
from .tool_intent_profile import build_tool_intent_profile, normalize_token
from .v2_contracts import (
    AnswerInstruction,
    CapabilityAction,
    CapabilityMap,
    CapabilityMapEntry,
    CapabilityNeed,
    ClarificationNeed,
    ConditionalBranchContract,
    FieldAlias,
    FieldAliases,
    FormattingInstruction,
    IntentOperation,
    RequirementLedger,
    RequirementLedgerEntry,
    RequirementOrigin,
    RequirementIntakeClause,
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
_UNBOUND_REFERENT_ID_TOKENS = {
    "a",
    "an",
    "applicable",
    "id",
    "if",
    "it",
    "its",
    "on",
    "one",
    "present",
    "related",
    "that",
    "the",
    "this",
    "too",
}
_DEPENDENT_OR_CONDITIONAL_MARKER_RE = re.compile(
    r"\b(?:that|this|it|its|their|related|when|if|only\s+if)\b|"
    r"\bthere\s+is\s+one\b|\bif\s+(?:present|applicable)\b",
    re.IGNORECASE,
)
_DEPENDENT_ENTITY_TERM_RE = re.compile(
    r"\b(?P<entity>machines?|jobs?|products?|materials?)\b",
    re.IGNORECASE,
)


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
    return build_capability_needs_from_sketch(sketch)


def build_capability_needs_from_sketch(sketch: RequirementSketch) -> list[CapabilityNeed]:
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
    semantic_intake: SemanticIntakeResult | None = None,
    semantic_intake_proposer: SemanticIntakeProposer | None = None,
) -> RequirementSketch:
    capability_map = capability_map or CapabilityMap()
    aliases = capability_map.field_aliases
    intents = _prepare_requirement_intents(split_user_intents(text), aliases)
    semantic_intake = semantic_intake or propose_semantic_intake_for_text(
        text,
        proposer=semantic_intake_proposer,
        prepared_clauses=[intent.description for intent in intents],
    )
    intents_by_clause: dict[str, Intent] = {}
    for intent in intents:
        intents_by_clause.setdefault(intent.description, intent)
    requirements: list[RequirementSketchItem] = []
    slices: list[ToolRetrievalSlice] = []
    intake_clauses: list[RequirementIntakeClause] = []
    conditional_branches: list[ConditionalBranchContract] = []
    answer_instructions: list[AnswerInstruction] = []
    formatting_instructions: list[FormattingInstruction] = []
    clarification_needs: list[ClarificationNeed] = []
    intake_item_to_requirement_id: dict[str, str] = {}
    intake_item_to_branch_id: dict[str, str] = {}

    for index, intake_item in enumerate(semantic_intake.items, start=1):
        clause = intake_item.text
        intent = intents_by_clause.get(clause) or split_user_intents(clause)[0]
        frame = semantic_frame_for_text(clause)
        source = _source_for_frame(frame, clause)
        entity = _entity_for_hint(frame, clause, source)
        if intake_item.role == "answer_instruction" and _answer_instruction_requires_retrieval(
            frame,
            source=source,
        ):
            intake_item = intake_item.model_copy(
                update={
                    "role": "required_requirement",
                    "reason": "answer_instruction_contains_retrieval_target",
                }
            )
        clause_id = f"clause-{index:03d}"

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

        if intake_item.role == "conditional_branch":
            parent_requirement_id = _parent_requirement_id_for_intake_item(
                intake_item,
                intake_item_to_requirement_id=intake_item_to_requirement_id,
                requirements=requirements,
            )
            conditional_branch = _conditional_branch_for_intake_item(
                intake_item,
                clause=clause,
                capability_map=capability_map,
                entity=entity,
            )
            if conditional_branch is None or parent_requirement_id is None:
                need_id = f"clarification-{len(clarification_needs) + 1:03d}"
                clarification_needs.append(
                    ClarificationNeed(
                        id=need_id,
                        text=clause,
                        reason="conditional_branch_missing_active_parent_or_referent",
                        blocked_entity=entity,
                    )
                )
                intake_clauses.append(
                    RequirementIntakeClause(
                        id=clause_id,
                        text=clause,
                        role="clarification_need",
                        reason="conditional_branch_missing_active_parent_or_referent",
                    )
                )
                continue

            previous = next(
                requirement for requirement in requirements if requirement.id == parent_requirement_id
            )
            condition_fields = [
                str(field)
                for field in conditional_branch["condition"].get("field_any", [])
                if str(field)
            ]
            if condition_fields:
                previous.constraints["observation_fields"] = list(
                    dict.fromkeys(
                        [
                            *(
                                previous.constraints.get("observation_fields")
                                if isinstance(previous.constraints.get("observation_fields"), list)
                                else []
                            ),
                            *condition_fields,
                        ]
                    )
                )
                for retrieval_slice in slices:
                    if retrieval_slice.slice_id and retrieval_slice.text == previous.goal:
                        retrieval_slice.constraints["observation_fields"] = list(
                            dict.fromkeys(
                                [
                                    *(
                                        retrieval_slice.constraints.get("observation_fields")
                                        if isinstance(retrieval_slice.constraints.get("observation_fields"), list)
                                        else []
                                    ),
                                    *condition_fields,
                                ]
                            )
                        )
                        break
            branch_id = f"branch-{len(conditional_branches) + 1:03d}"
            branch = ConditionalBranchContract(
                id=branch_id,
                parent_requirement_id=parent_requirement_id,
                text=clause,
                condition=dict(conditional_branch["condition"]),
                on_true=dict(conditional_branch["on_true"]),
                diagnostics=dict(conditional_branch.get("diagnostics") or {}),
            )
            conditional_branches.append(branch)
            intake_item_to_branch_id[intake_item.id] = branch_id
            if _clause_requests_answer_composition(clause):
                answer_instructions.append(
                    AnswerInstruction(
                        id=f"answer-{len(answer_instructions) + 1:03d}",
                        text=clause,
                        applies_to_requirement_ids=[parent_requirement_id],
                        applies_to_branch_ids=[branch_id],
                        reason="answer_composition_instruction",
                    )
                )
            intake_clauses.append(
                RequirementIntakeClause(
                    id=clause_id,
                    text=clause,
                    role="conditional_branch",
                    parent_requirement_id=parent_requirement_id,
                    branch_id=branch_id,
                    reason="conditional_branch_waits_for_parent_evidence",
                )
            )
            continue

        if intake_item.role == "answer_instruction":
            instruction_id = f"answer-{len(answer_instructions) + 1:03d}"
            applies_to_requirement_ids = _applies_to_requirement_ids_for_intake_item(
                intake_item,
                intake_item_to_requirement_id=intake_item_to_requirement_id,
                requirements=requirements,
            )
            applies_to_branch_ids = _applies_to_branch_ids_for_intake_item(
                intake_item,
                intake_item_to_branch_id=intake_item_to_branch_id,
                conditional_branches=conditional_branches,
            )
            answer_instructions.append(
                AnswerInstruction(
                    id=instruction_id,
                    text=clause,
                    applies_to_requirement_ids=applies_to_requirement_ids,
                    applies_to_branch_ids=applies_to_branch_ids,
                    reason=intake_item.reason or "answer_composition_instruction",
                )
            )
            intake_clauses.append(
                RequirementIntakeClause(
                    id=clause_id,
                    text=clause,
                    role="answer_instruction",
                    reason=intake_item.reason or "answer_composition_instruction",
                )
            )
            continue

        if intake_item.role == "formatting_instruction":
            instruction_id = f"format-{len(formatting_instructions) + 1:03d}"
            formatting_instructions.append(
                FormattingInstruction(
                    id=instruction_id,
                    text=clause,
                    reason=intake_item.reason or "formatting_instruction",
                )
            )
            intake_clauses.append(
                RequirementIntakeClause(
                    id=clause_id,
                    text=clause,
                    role="formatting_instruction",
                    reason=intake_item.reason or "formatting_instruction",
                )
            )
            continue

        if intake_item.role == "clarification_need":
            need_id = f"clarification-{len(clarification_needs) + 1:03d}"
            blocked_entity = (
                str(intake_item.diagnostics.get("blocked_entity") or "").strip()
                or entity
                or _dependent_singular_read_entity(clause)
            )
            clarification_needs.append(
                ClarificationNeed(
                    id=need_id,
                    text=clause,
                    reason=intake_item.reason or "clarification_needed",
                    blocked_entity=blocked_entity or None,
                )
            )
            intake_clauses.append(
                RequirementIntakeClause(
                    id=clause_id,
                    text=clause,
                    role="clarification_need",
                    reason=intake_item.reason or "clarification_needed",
                )
            )
            continue

        if intake_item.role not in {"required_requirement", "mutation_or_approval_request"}:
            continue

        answer_instruction = _answer_instruction_for_clause(
            clause,
            frame=frame,
            source=source,
            previous_requirements=requirements,
            conditional_branches=conditional_branches,
        )
        if answer_instruction is not None:
            instruction_id = f"answer-{len(answer_instructions) + 1:03d}"
            answer_instructions.append(
                AnswerInstruction(
                    id=instruction_id,
                    text=clause,
                    applies_to_requirement_ids=[
                        requirement.id for requirement in requirements[-1:] if requirement.id
                    ],
                    applies_to_branch_ids=[
                        branch.id for branch in conditional_branches[-1:] if branch.id
                    ],
                    reason=answer_instruction,
                )
            )
            intake_clauses.append(
                RequirementIntakeClause(
                    id=clause_id,
                    text=clause,
                    role="answer_instruction",
                    reason=answer_instruction,
                )
            )
            continue

        clarification_need = _clarification_need_for_clause(clause, frame=frame)
        if clarification_need is not None:
            need_id = f"clarification-{len(clarification_needs) + 1:03d}"
            clarification_needs.append(
                ClarificationNeed(
                    id=need_id,
                    text=clause,
                    reason=clarification_need["reason"],
                    blocked_entity=clarification_need.get("entity"),
                )
            )
            intake_clauses.append(
                RequirementIntakeClause(
                    id=clause_id,
                    text=clause,
                    role="clarification_need",
                    reason=clarification_need["reason"],
                )
            )
            continue

        formatting_instruction = _formatting_instruction_for_clause(clause, frame=frame, source=source)
        if formatting_instruction is not None:
            instruction_id = f"format-{len(formatting_instructions) + 1:03d}"
            formatting_instructions.append(
                FormattingInstruction(
                    id=instruction_id,
                    text=clause,
                    reason=formatting_instruction,
                )
            )
            intake_clauses.append(
                RequirementIntakeClause(
                    id=clause_id,
                    text=clause,
                    role="formatting_instruction",
                    reason=formatting_instruction,
                )
            )
            continue

        conditional_branch = _conditional_branch_for_clause(
            clause,
            capability_map=capability_map,
            entity=entity,
        )
        if conditional_branch and requirements:
            previous = requirements[-1]
            condition_fields = [
                str(field)
                for field in conditional_branch["condition"].get("field_any", [])
                if str(field)
            ]
            if condition_fields:
                previous.constraints["observation_fields"] = list(
                    dict.fromkeys(
                        [
                            *(
                                previous.constraints.get("observation_fields")
                                if isinstance(previous.constraints.get("observation_fields"), list)
                                else []
                            ),
                            *condition_fields,
                        ]
                    )
                )
                if slices:
                    slices[-1].constraints["observation_fields"] = list(
                        dict.fromkeys(
                            [
                                *(
                                    slices[-1].constraints.get("observation_fields")
                                    if isinstance(slices[-1].constraints.get("observation_fields"), list)
                                    else []
                                ),
                                *condition_fields,
                            ]
                        )
                    )
            branch_id = f"branch-{len(conditional_branches) + 1:03d}"
            branch = ConditionalBranchContract(
                id=branch_id,
                parent_requirement_id=previous.id,
                text=clause,
                condition=dict(conditional_branch["condition"]),
                on_true=dict(conditional_branch["on_true"]),
                diagnostics=dict(conditional_branch.get("diagnostics") or {}),
            )
            conditional_branches.append(branch)
            if _clause_requests_answer_composition(clause):
                answer_instructions.append(
                    AnswerInstruction(
                        id=f"answer-{len(answer_instructions) + 1:03d}",
                        text=clause,
                        applies_to_requirement_ids=[previous.id],
                        applies_to_branch_ids=[branch_id],
                        reason="answer_composition_instruction",
                    )
                )
            intake_clauses.append(
                RequirementIntakeClause(
                    id=clause_id,
                    text=clause,
                    role="conditional_branch",
                    parent_requirement_id=previous.id,
                    branch_id=branch_id,
                    reason="conditional_branch_waits_for_parent_evidence",
                )
            )
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
        if _dependent_singular_read_entity(clause) and not _has_bounded_identity_constraints(
            constraints,
            entity=entity,
        ):
            blocked_entity = _dependent_singular_read_entity(clause) or entity
            need_id = f"clarification-{len(clarification_needs) + 1:03d}"
            clarification_needs.append(
                ClarificationNeed(
                    id=need_id,
                    text=clause,
                    reason="dependent_singular_read_missing_bound_entity",
                    blocked_entity=blocked_entity,
                )
            )
            intake_clauses.append(
                RequirementIntakeClause(
                    id=clause_id,
                    text=clause,
                    role="clarification_need",
                    reason="dependent_singular_read_missing_bound_entity",
                )
            )
            continue

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
        requirement_id = f"req-{len(requirements) + 1:03d}"

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
        intake_item_to_requirement_id[intake_item.id] = requirement_id
        intake_clauses.append(
            RequirementIntakeClause(
                id=clause_id,
                text=clause,
                role=intake_item.role,
                requirement_id=requirement_id,
                reason="executable_required_requirement",
            )
        )
        slices.append(
            ToolRetrievalSlice(
                slice_id=f"slice-{len(slices) + 1:03d}",
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
        intake_clauses=intake_clauses,
        conditional_branches=conditional_branches,
        answer_instructions=answer_instructions,
        formatting_instructions=formatting_instructions,
        clarification_needs=clarification_needs,
        intake_diagnostics={
            **dict(semantic_intake.diagnostics),
            "source": semantic_intake.source,
            "proposer": semantic_intake.proposer,
            "item_count": len(semantic_intake.items),
            "compiled_requirement_count": len(requirements),
            "compiler_authority": "deterministic",
            "active_executable_roles": ["required_requirement"],
            "raw_llm_output_executes_tools": False,
        },
    )


def _prepare_requirement_intents(intents: list[Intent], aliases: FieldAliases) -> list[Intent]:
    coalesced = _coalesce_field_continuation_intents(intents, aliases)
    prepared: list[Intent] = []
    for intent in coalesced:
        prepared.extend(_expand_mixed_entity_intent(intent))
    return prepared


def _parent_requirement_id_for_intake_item(
    intake_item: SemanticIntakeItem,
    *,
    intake_item_to_requirement_id: Mapping[str, str],
    requirements: list[RequirementSketchItem],
) -> str | None:
    if intake_item.parent_item_id:
        requirement_id = intake_item_to_requirement_id.get(intake_item.parent_item_id)
        if requirement_id:
            return requirement_id
    return requirements[-1].id if requirements else None


def _applies_to_requirement_ids_for_intake_item(
    intake_item: SemanticIntakeItem,
    *,
    intake_item_to_requirement_id: Mapping[str, str],
    requirements: list[RequirementSketchItem],
) -> list[str]:
    ids = [
        intake_item_to_requirement_id[item_id]
        for item_id in intake_item.applies_to_item_ids
        if item_id in intake_item_to_requirement_id
    ]
    if ids:
        return list(dict.fromkeys(ids))
    return [requirement.id for requirement in requirements[-1:] if requirement.id]


def _applies_to_branch_ids_for_intake_item(
    intake_item: SemanticIntakeItem,
    *,
    intake_item_to_branch_id: Mapping[str, str],
    conditional_branches: list[ConditionalBranchContract],
) -> list[str]:
    ids = [
        intake_item_to_branch_id[item_id]
        for item_id in intake_item.applies_to_item_ids
        if item_id in intake_item_to_branch_id
    ]
    if ids:
        return list(dict.fromkeys(ids))
    return [branch.id for branch in conditional_branches[-1:] if branch.id]


def _conditional_branch_for_intake_item(
    intake_item: SemanticIntakeItem,
    *,
    clause: str,
    capability_map: CapabilityMap,
    entity: str | None,
) -> dict[str, Any] | None:
    legacy = _conditional_branch_for_clause(clause, capability_map=capability_map, entity=entity)
    child_intent = dict(intake_item.child_intent or {})
    proposed_entity = str(child_intent.get("entity") or "").strip()
    if not proposed_entity and legacy:
        proposed_entity = str(dict(legacy.get("on_true") or {}).get("entity") or "").strip()
    if not proposed_entity:
        proposed_entity = _dependent_singular_read_entity(clause) or ""
    branch_entity = _conditional_branch_entity_for_phrase(proposed_entity, capability_map=capability_map)
    if not branch_entity:
        return legacy

    proposed_fields = [
        str(field)
        for field in (
            intake_item.condition.get("field_any")
            or child_intent.get("value_from_field_any")
            or []
        )
        if str(field)
    ]
    identifier_fields = _conditional_identifier_fields(capability_map, branch_entity)
    field_any = _validated_referent_fields(
        proposed_fields,
        entity=branch_entity,
        fallback_fields=identifier_fields,
    )
    fan_out = str(child_intent.get("fan_out") or "").strip()
    if fan_out not in {"all_unique_values", "first_value"}:
        fan_out = (
            "all_unique_values"
            if legacy and dict(legacy.get("on_true") or {}).get("fan_out") == "all_unique_values"
            else "first_value"
        )
    return {
        "condition": {
            "type": "active_parent_evidence_has_any_field",
            "field_any": field_any,
            "source": "active_parent_evidence",
        },
        "on_true": {
            "action": "read_one",
            "entity": branch_entity,
            "constraint_field": f"{branch_entity}_id",
            "value_from_field_any": field_any,
            "fan_out": fan_out,
            "requirement_type": "single_entity_status",
            "intent_operation": "report_status",
        },
        "diagnostics": {
            "role": "conditional_branch",
            "non_executable_until_condition_true": True,
            "compiled_from_semantic_intake": True,
            **({"fan_out": fan_out} if fan_out == "all_unique_values" else {}),
        },
    }


def _validated_referent_fields(
    fields: Iterable[str],
    *,
    entity: str,
    fallback_fields: list[str],
) -> list[str]:
    primary = f"{entity}_id"
    active = f"active_{entity}_id"
    valid: list[str] = []
    for field in fields:
        value = str(field or "").strip()
        if value == primary or value == active or value.endswith(f"_{primary}"):
            valid.append(value)
    return list(dict.fromkeys(valid or fallback_fields))


def _dependent_singular_read_entity(clause: str) -> str | None:
    lowered = clause.lower()
    if not _DEPENDENT_OR_CONDITIONAL_MARKER_RE.search(lowered):
        return None

    match = re.search(
        r"\b(?:read|show|check|get|look\s+up)\s+"
        r"(?:(?:that|this|the)\s+)?(?P<entity>[a-z][a-z0-9_-]*)?\s*(?:too)?\b",
        clause,
        re.IGNORECASE,
    )
    if match:
        entity = _normalize_phrase(match.group("entity") or "").replace(" ", "_")
        if entity and entity not in _UNBOUND_REFERENT_ID_TOKENS:
            return _singular_entity_name(entity)

    for entity_match in _DEPENDENT_ENTITY_TERM_RE.finditer(clause):
        entity = _singular_entity_name(_normalize_phrase(entity_match.group("entity")))
        if entity:
            return entity
    return None


def _has_bounded_identity_constraints(constraints: Mapping[str, Any], *, entity: str | None) -> bool:
    identity_fields = {"id", "machine_ref"}
    if entity:
        identity_fields.add(f"{entity}_id")
    for key, value in constraints.items():
        if key not in identity_fields and not key.endswith("_id"):
            continue
        for item in _iter_identity_constraint_values(value):
            if item.strip().lower() not in _UNBOUND_REFERENT_ID_TOKENS:
                return True
    return False


def _iter_identity_constraint_values(value: Any) -> Iterable[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _singular_entity_name(entity: str) -> str:
    normalized = _normalize_phrase(entity).replace(" ", "_")
    if normalized.endswith("s") and len(normalized) > 1:
        return normalized[:-1]
    return normalized


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
        intake_clauses=list(sketch.intake_clauses),
        conditional_branches=list(sketch.conditional_branches),
        answer_instructions=list(sketch.answer_instructions),
        formatting_instructions=list(sketch.formatting_instructions),
        clarification_needs=list(sketch.clarification_needs),
        intake_diagnostics=dict(sketch.intake_diagnostics),
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


def _answer_instruction_requires_retrieval(frame: SemanticFrame, *, source: SourceOfTruth) -> bool:
    if source == "unknown":
        return False
    if source == "document_knowledge":
        return True
    if frame.entity or frame.domain_intent or frame.route.startswith("tool."):
        return True
    return any(values for values in frame.normalized_entities.values())


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
    dependent_read = re.search(
        r"\bif\b.+?\bincludes?\s+(?:a|an|the)?\s*(?P<entity>[a-z][a-z0-9_-]*)\s+id\b"
        r".+?\bread\s+that\s+(?P=entity)\b",
        clause,
        re.IGNORECASE | re.DOTALL,
    )
    for_each_dependent_read = re.search(
        r"\bfor\s+(?:each|every)\b.+?\b(?:that|which|where)\s+"
        r"(?:includes?|has|contains)\s+(?:a|an|the)?\s*"
        r"(?P<entity>[a-z][a-z0-9_-]*)\s+id\b"
        r".+?\bread\s+that\s+(?P=entity)\b",
        clause,
        re.IGNORECASE | re.DOTALL,
    )
    dependent_read = dependent_read or for_each_dependent_read
    if dependent_read:
        branch_entity = _conditional_branch_entity_for_phrase(
            dependent_read.group("entity"),
            capability_map=capability_map,
        )
        if not branch_entity:
            branch_entity = entity or ""
        if not branch_entity:
            return None
        field_any = _conditional_identifier_fields(capability_map, branch_entity)
        return {
            "condition": {
                "type": "active_parent_evidence_has_any_field",
                "field_any": field_any,
                "source": "active_parent_evidence",
            },
            "on_true": {
                "action": "read_one",
                "entity": branch_entity,
                "constraint_field": f"{branch_entity}_id",
                "value_from_field_any": field_any,
                "fan_out": "all_unique_values"
                if for_each_dependent_read
                else "first_value",
                "requirement_type": "single_entity_status",
                "intent_operation": "report_status",
            },
            "diagnostics": {
                "role": "conditional_branch",
                "non_executable_until_condition_true": True,
                **(
                    {"fan_out": "all_unique_values"}
                    if for_each_dependent_read
                    else {}
                ),
            },
        }

    dependent_entity = _dependent_singular_read_entity(clause)
    if dependent_entity:
        if _dependent_clause_requires_evidence_branch(clause):
            branch_entity = _conditional_branch_entity_for_phrase(
                dependent_entity,
                capability_map=capability_map,
            )
            if not branch_entity:
                branch_entity = entity or ""
            if branch_entity:
                field_any = _conditional_identifier_fields(capability_map, branch_entity)
                return {
                    "condition": {
                        "type": "active_parent_evidence_has_any_field",
                        "field_any": field_any,
                        "source": "active_parent_evidence",
                    },
                    "on_true": {
                        "action": "read_one",
                        "entity": branch_entity,
                        "constraint_field": f"{branch_entity}_id",
                        "value_from_field_any": field_any,
                        "fan_out": "first_value",
                        "requirement_type": "single_entity_status",
                        "intent_operation": "report_status",
                    },
                    "diagnostics": {
                        "role": "conditional_branch",
                        "non_executable_until_condition_true": True,
                        "dependent_referent_guard": True,
                    },
                }

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

    return {
        "condition": {
            "type": "row_field_equals",
            "field": "status",
            "value": condition_value,
            "source": "active_parent_evidence",
        },
        "on_true": {
            "action": "continue_for_explanation_before_update_suggestion",
            "required_evidence": "typed_explanation",
        },
        "diagnostics": {
            "role": "conditional_branch",
            "legacy_collection_explanation_branch": True,
            **(
                {"ordering": "explain_before_suggestion"}
                if re.search(r"\bbefore\b.*\b(?:suggest|recommend)", clause, re.IGNORECASE)
                else {}
            ),
        },
    }


def _conditional_branch_entity_for_phrase(phrase: str, *, capability_map: CapabilityMap) -> str:
    entity = _normalize_phrase(phrase).replace(" ", "_")
    if not entity:
        return ""
    known_entities = {
        str(capability.entity or "").strip()
        for capability in capability_map.capabilities
        if str(capability.entity or "").strip()
    }
    candidates = [entity]
    if entity.endswith("s") and len(entity) > 1:
        candidates.append(entity[:-1])
    return next((candidate for candidate in candidates if candidate in known_entities), candidates[0])


def _conditional_identifier_fields(capability_map: CapabilityMap, entity: str) -> list[str]:
    primary = f"{entity}_id"
    fields: list[str] = [primary]
    suffix = f"_{primary}"
    for alias in capability_map.field_aliases.aliases:
        canonical = str(alias.canonical_field or "").strip()
        if canonical == primary or canonical.endswith(suffix):
            fields.append(canonical)
    fields.append(f"active_{primary}")
    return list(dict.fromkeys(field for field in fields if field))


def _answer_instruction_for_clause(
    clause: str,
    *,
    frame: SemanticFrame,
    source: SourceOfTruth,
    previous_requirements: list[RequirementSketchItem],
    conditional_branches: list[ConditionalBranchContract],
) -> str | None:
    if not previous_requirements and not conditional_branches:
        return None
    if _dependent_singular_read_entity(clause) and _dependent_clause_requires_evidence_branch(clause):
        return None
    if re.search(r"^\s*(?:summari[sz]e|explain|describe)\b", clause, re.IGNORECASE):
        if not any(values for values in frame.normalized_entities.values()):
            return "answer_composition_instruction"
    if frame.entity or source != "unknown":
        return None
    if re.search(r"\b(?:explain|why|cause|reason|summari[sz]e)\b", clause, re.IGNORECASE):
        return "answer_composition_instruction"
    return None


def _clause_requests_answer_composition(clause: str) -> bool:
    return bool(re.search(r"\b(?:explain|why|cause|reason|summari[sz]e|describe)\b", clause, re.IGNORECASE))


def _dependent_clause_requires_evidence_branch(clause: str) -> bool:
    return bool(
        re.search(
            r"\b(?:read|show|check|get|look\s+up|pull|fetch)\b|"
            r"\b(?:when|if|only\s+if)\b|\bthere\s+is\s+one\b|\bif\s+(?:present|applicable)\b",
            clause,
            re.IGNORECASE,
        )
    )


def _clarification_need_for_clause(clause: str, *, frame: SemanticFrame) -> dict[str, str] | None:
    if frame.normalized_entities:
        return None
    match = re.search(
        r"\b(?:read|show|check|get|look\s+up)\s+(?:that|this|the)\s+"
        r"(?P<entity>[a-z][a-z0-9_-]*)\b",
        clause,
        re.IGNORECASE,
    )
    if not match:
        return None
    entity = _normalize_phrase(match.group("entity")).replace(" ", "_")
    return {
        "reason": "dependent_singular_read_missing_bound_entity",
        "entity": entity,
    }


def _formatting_instruction_for_clause(
    clause: str,
    *,
    frame: SemanticFrame,
    source: SourceOfTruth,
) -> str | None:
    if frame.entity or source != "unknown":
        return None
    normalized = _normalize_phrase(clause)
    formatting_terms = {
        "briefly",
        "status first",
        "short answer",
        "concise",
        "one sentence",
        "bullet points",
    }
    if normalized in formatting_terms:
        return "formatting_instruction"
    return None


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
    locked = [
        key
        for key, value in constraints.items()
        if key not in {"observation_fields"} and value not in (None, "", [], {})
    ]
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
