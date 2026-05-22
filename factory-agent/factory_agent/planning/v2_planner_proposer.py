from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import Field, ValidationError

from factory_agent.config import Settings
from factory_agent.llm.models import build_planner_chat_model
from factory_agent.observability.telemetry import log_event

from .v2_agent_state import (
    GraphToolCall,
    PlannerOwnedAgentGraphState,
    PlannerOwnedGraphDecisionKind,
)
from .v2_contracts import CapabilityNeed, HydratedToolCard, RequirementLedger, RequirementLedgerEntry, V2ContractModel
from .v2_planner_decisions import PlannerDecisionSubmission


class PlannerDecisionProposerError(RuntimeError):
    """Raised when the planner proposer cannot produce a valid submission."""

    def __init__(self, message: str, *, diagnostics: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


class PlannerDecisionProposalContext(V2ContractModel):
    """Bounded request for one planner-authored graph decision."""

    decision_id: str = Field(min_length=1)
    allowed_decision_kinds: list[PlannerOwnedGraphDecisionKind] = Field(default_factory=list)
    requested_decision_kind: PlannerOwnedGraphDecisionKind | None = None
    requirement_id: str | None = None
    capability_need: CapabilityNeed | None = None
    candidate_tool_calls: list[GraphToolCall] = Field(default_factory=list)
    prior_decision_id: str | None = None
    reason: str | None = None


class PlannerDecisionProposalResult(V2ContractModel):
    submission: PlannerDecisionSubmission
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class PlannerDecisionProposer(Protocol):
    async def propose_decision(
        self,
        *,
        state: PlannerOwnedAgentGraphState,
        context: PlannerDecisionProposalContext,
    ) -> PlannerDecisionProposalResult:
        ...


class OfflineStructuredPlannerDecisionProposer:
    """Offline adapter used when no planner LLM endpoint is configured.

    It still goes through the proposer seam and decision validator, but avoids
    requiring a live model for deterministic contract tests.
    """

    adapter_name = "offline_structured_planner_decision_proposer"

    async def propose_decision(
        self,
        *,
        state: PlannerOwnedAgentGraphState,
        context: PlannerDecisionProposalContext,
    ) -> PlannerDecisionProposalResult:
        kind = context.requested_decision_kind or (
            context.allowed_decision_kinds[0] if context.allowed_decision_kinds else "fail"
        )
        if kind not in context.allowed_decision_kinds and context.allowed_decision_kinds:
            kind = context.allowed_decision_kinds[0]

        payload: dict[str, Any] = {
            "decision": {
                "decision_id": context.decision_id,
                "decision_kind": kind,
                "author": "planner",
                "requirement_id": context.requirement_id,
                "ledger_revision": state.requirement_ledger.revision,
                "reason": context.reason or f"Offline proposer selected {kind}.",
            },
            "proposed_requirement_ledger": None,
        }
        if kind == "retrieve_tools":
            payload["decision"]["capability_need"] = _dump_model(context.capability_need)
        elif kind in {"choose_tool", "request_approval", "execute_tool"}:
            selected = _offline_selected_tool_call(state=state, context=context)
            payload["decision"]["selected_tool_call"] = _dump_model(selected)
            if context.capability_need is not None:
                payload["decision"]["capability_need"] = _dump_model(context.capability_need)
        elif kind == "finalize":
            payload["decision"]["evidence_refs"] = [
                evidence.id for evidence in state.evidence_ledger.evidence
            ]
        elif kind == "fail":
            payload["decision"]["reason"] = context.reason or "The graph could not safely continue."

        try:
            submission = PlannerDecisionSubmission.model_validate(payload)
        except ValidationError as exc:  # pragma: no cover - defensive
            raise PlannerDecisionProposerError(
                "offline planner proposer produced an invalid schema",
                diagnostics={"adapter": self.adapter_name, "error": str(exc)},
            ) from exc
        return _with_proposer_diagnostics(
            submission,
            state=state,
            context=context,
            adapter_name=self.adapter_name,
            diagnostics={
                "llm_invoked": False,
                "offline_contract_mode": True,
            },
        )


def _offline_selected_tool_call(
    *,
    state: PlannerOwnedAgentGraphState,
    context: PlannerDecisionProposalContext,
) -> GraphToolCall | None:
    if not context.candidate_tool_calls:
        return None
    need = context.capability_need
    constraints = dict(getattr(need, "constraints", {}) or {}) if need is not None else {}
    action = str(getattr(need, "action", "") or "").strip().lower()
    requires_write = bool(constraints.get("requires_approval")) or action in {
        "create",
        "update",
        "delete",
        "cancel",
        "stage_mutation",
    }
    if requires_write:
        for call in context.candidate_tool_calls:
            card = _tool_card_for_call(state, call)
            if card is not None and (card.requires_approval or not card.is_read_only):
                return call
    return context.candidate_tool_calls[0]


class OpenAICompatibleQwenPlannerDecisionProposer:
    """OpenAI-compatible local/Qwen adapter for planner decision proposals."""

    adapter_name = "openai_compatible_qwen_planner_decision_proposer"

    def __init__(self, settings: Settings, *, model: Any | None = None) -> None:
        self._settings = settings
        self._model = model

    async def propose_decision(
        self,
        *,
        state: PlannerOwnedAgentGraphState,
        context: PlannerDecisionProposalContext,
    ) -> PlannerDecisionProposalResult:
        prompt = _build_planner_decision_prompt(state=state, context=context)
        model = self._model or build_planner_chat_model(self._settings, json_mode=True)
        started = time.perf_counter()
        event_fields = _proposer_event_fields(
            state=state,
            context=context,
            adapter_name=self.adapter_name,
            settings=self._settings,
            prompt=prompt,
        )
        log_event("planner_decision_proposer_llm_start", **event_fields)
        try:
            raw_response = await model.ainvoke(prompt)
        except Exception as exc:
            duration_ms = _duration_ms(started)
            error_diagnostics = {
                "adapter": self.adapter_name,
                "model_name": self._settings.planner_model,
                "base_url_type": _base_url_type(self._settings.planner_openai_base_url),
                "duration_ms": duration_ms,
                "prompt_chars": len(prompt),
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
            log_event(
                "planner_decision_proposer_llm_error",
                level="WARNING",
                **event_fields,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                error_preview=str(exc)[:500],
            )
            raise PlannerDecisionProposerError(
                "planner proposer model call failed",
                diagnostics=error_diagnostics,
            ) from exc

        content = _message_content_text(raw_response)
        duration_ms = _duration_ms(started)
        parsed = _extract_json_object(content)
        usage_metadata = _message_usage_metadata(raw_response)
        response_metadata = _message_response_metadata(raw_response)
        diagnostics = {
            "llm_invoked": True,
            "model_name": self._settings.planner_model,
            "base_url_type": _base_url_type(self._settings.planner_openai_base_url),
            "duration_ms": duration_ms,
            "prompt_chars": len(prompt),
            "content_chars": len(content),
            "finish_reason": response_metadata.get("finish_reason"),
            "usage_metadata": usage_metadata,
            "raw_content_preview": content[:500],
        }
        log_event(
            "planner_decision_proposer_llm_complete",
            **event_fields,
            duration_ms=duration_ms,
            content_chars=len(content),
            finish_reason=response_metadata.get("finish_reason"),
            usage_metadata=usage_metadata,
        )
        if not isinstance(parsed, dict):
            log_event(
                "planner_decision_proposer_rejected",
                level="WARNING",
                **event_fields,
                duration_ms=duration_ms,
                rejection_reason="invalid_json",
                content_chars=len(content),
            )
            raise PlannerDecisionProposerError(
                "planner proposer returned invalid JSON",
                diagnostics={**diagnostics, "adapter": self.adapter_name, "invalid_json": True},
            )

        payload = _normalize_submission_payload(parsed, state=state, context=context)
        try:
            submission = PlannerDecisionSubmission.model_validate(payload)
        except ValidationError as exc:
            log_event(
                "planner_decision_proposer_rejected",
                level="WARNING",
                **event_fields,
                duration_ms=duration_ms,
                rejection_reason="invalid_schema",
                parsed_keys=sorted(parsed.keys()),
                schema_error_preview=str(exc)[:500],
            )
            raise PlannerDecisionProposerError(
                "planner proposer returned an invalid decision schema",
                diagnostics={
                    **diagnostics,
                    "adapter": self.adapter_name,
                    "invalid_schema": True,
                    "schema_error": str(exc),
                    "parsed_keys": sorted(parsed.keys()),
                },
            ) from exc

        result = _with_proposer_diagnostics(
            submission,
            state=state,
            context=context,
            adapter_name=self.adapter_name,
            diagnostics=diagnostics,
        )
        log_event(
            "planner_decision_proposer_accepted",
            **event_fields,
            duration_ms=duration_ms,
            proposed_decision_kind=result.submission.decision.decision_kind,
            has_selected_tool_call=result.submission.decision.selected_tool_call is not None,
        )
        return result


def build_planner_decision_proposer(settings: Settings) -> PlannerDecisionProposer:
    if settings.planner_openai_base_url or settings.openai_api_key:
        return OpenAICompatibleQwenPlannerDecisionProposer(settings)
    return OfflineStructuredPlannerDecisionProposer()


def _with_proposer_diagnostics(
    submission: PlannerDecisionSubmission,
    *,
    state: PlannerOwnedAgentGraphState,
    context: PlannerDecisionProposalContext,
    adapter_name: str,
    diagnostics: Mapping[str, Any],
) -> PlannerDecisionProposalResult:
    decision = submission.decision
    if decision.author != "planner":
        raise PlannerDecisionProposerError(
            "planner proposer submissions must be authored by planner",
            diagnostics={"adapter": adapter_name, "author": decision.author},
        )

    proposer_diagnostics = {
        "proposer_seam": True,
        "adapter": adapter_name,
        "decision_id": decision.decision_id,
        "requested_decision_kind": context.requested_decision_kind,
        "allowed_decision_kinds": list(context.allowed_decision_kinds),
        "ledger_revision": state.requirement_ledger.revision,
        "requirement_id": context.requirement_id,
        "prior_decision_id": context.prior_decision_id,
        "bounded_state_view": True,
        "full_openapi_catalog_visible": False,
        "candidate_tool_call_count": len(context.candidate_tool_calls),
        **dict(diagnostics),
    }
    updated_decision = decision.model_copy(
        update={
            "diagnostics": {
                **dict(decision.diagnostics),
                "planner_proposer": proposer_diagnostics,
            }
        },
        deep=True,
    )
    result = PlannerDecisionProposalResult(
        submission=PlannerDecisionSubmission(
            decision=updated_decision,
            proposed_requirement_ledger=submission.proposed_requirement_ledger,
        ),
        diagnostics=proposer_diagnostics,
    )
    return result


def _build_planner_decision_prompt(
    *,
    state: PlannerOwnedAgentGraphState,
    context: PlannerDecisionProposalContext,
) -> str:
    requested_kind = context.requested_decision_kind or (
        context.allowed_decision_kinds[0] if context.allowed_decision_kinds else "fail"
    )
    payload = {
        "task": "Return one compact PlannerDecisionSubmission JSON object. The first character must be { and the last character must be }.",
        "rules": [
            "Return JSON only: no prose, no markdown, no code fence.",
            "Return only fields named in response_contract.allowed_output_fields.",
            "Do not invent tools outside decision_state.candidate_tool_calls.",
            "For choose_tool, choose by selected_tool_name; do not copy full tool schemas.",
            "For choose_tool on approval-required mutations, choose the write/mutation tool; the graph approval preview reads source rows before execution.",
            "For non-approval choose_tool decisions, do not choose a tool call with missing_required_args unless every candidate has missing required args.",
            "Do not include proposed_requirement_ledger unless decision_kind is revise_requirements.",
            "Do not drop locked constraints in proposed_requirement_ledger.",
        ],
        "response_contract": _response_contract_for_context(
            state=state,
            context=context,
            requested_kind=requested_kind,
        ),
        "decision_state": _bounded_decision_state(
            state=state,
            context=context,
            requested_kind=requested_kind,
        ),
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _response_contract_for_context(
    *,
    state: PlannerOwnedAgentGraphState,
    context: PlannerDecisionProposalContext,
    requested_kind: str,
) -> dict[str, Any]:
    decision_base = {
        "decision_kind": requested_kind,
        "reason": "short reason",
    }
    if requested_kind == "choose_tool":
        decision_base["selected_tool_name"] = "one tool_name from decision_state.candidate_tool_calls"
    elif requested_kind in {"request_approval", "execute_tool"}:
        decision_base["selected_tool_name"] = (
            "optional; omit when decision_state.candidate_tool_calls has exactly one item"
        )
    elif requested_kind == "finalize":
        decision_base["evidence_refs"] = "optional evidence ids already present in decision_state.evidence_summary"

    contract: dict[str, Any] = {
        "allowed_output_fields": ["decision", "proposed_requirement_ledger"],
        "decision_defaults_filled_by_adapter": {
            "decision_id": context.decision_id,
            "author": "planner",
            "ledger_revision": state.requirement_ledger.revision,
            "requirement_id": context.requirement_id,
            "capability_need": "from proposal context when required",
            "selected_tool_call": "hydrated from selected_tool_name when required",
            "planner_proposer_diagnostics": "attached by adapter after parsing",
        },
        "minimal_json": {
            "decision": decision_base,
        },
        "forbidden_unless_revising": ["proposed_requirement_ledger"],
        "forbidden_always": [
            "bounded_graph_state",
            "hydrated_tool_cards",
            "input_schema",
            "output_schema",
            "selected_tool_calls",
            "full_openapi_catalog",
        ],
    }
    if requested_kind == "revise_requirements":
        contract["minimal_json"] = {
            "decision": decision_base,
            "proposed_requirement_ledger": {
                "user_goal": state.requirement_ledger.user_goal,
                "revision": state.requirement_ledger.revision + 1,
                "requirements": "complete revised requirement list preserving locked constraints",
            },
        }
        contract["forbidden_unless_revising"] = []
    return contract


def _bounded_decision_state(
    *,
    state: PlannerOwnedAgentGraphState,
    context: PlannerDecisionProposalContext,
    requested_kind: str,
) -> dict[str, Any]:
    current_requirement = _requirement_summary(state, context.requirement_id)
    base: dict[str, Any] = {
        "original_query": state.original_query,
        "decision_id": context.decision_id,
        "requested_decision_kind": requested_kind,
        "allowed_decision_kinds": list(context.allowed_decision_kinds),
        "ledger_revision": state.requirement_ledger.revision,
        "requirement_id": context.requirement_id,
        "current_requirement": current_requirement,
        "all_requirements": [
            _requirement_entry_summary(requirement)
            for requirement in state.requirement_ledger.requirements
        ],
        "capability_need": context.capability_need.model_dump(mode="json")
        if context.capability_need is not None
        else None,
        "evidence_summary": _evidence_summary(state, requirement_id=context.requirement_id),
        "pending_approval_status": state.pending_approval.status,
        "full_openapi_catalog_visible": False,
    }
    if requested_kind in {"choose_tool", "request_approval", "execute_tool"}:
        base["candidate_tool_calls"] = _tool_call_summaries(state, context)
        base["hydrated_tool_summaries"] = _tool_card_summaries(state, context)
        base["tool_choice_policy"] = {
            "approval_required": bool(
                context.capability_need is not None
                and context.capability_need.constraints.get("requires_approval") is True
            ),
            "source_state_evidence_present": bool(
                _evidence_summary(state, requirement_id=context.requirement_id)
            ),
            "prefer_write_tool_for_approval_required_mutation": True,
            "approval_preview_reads_source_rows": True,
            "reject_tools_outside_candidate_window": True,
        }
    if requested_kind == "finalize":
        base["final_validation_status"] = (
            state.final_validation_result.status if state.final_validation_result is not None else None
        )
        base["evidence_summary"] = _evidence_summary(state, requirement_id=None)
    return base


def _requirement_summary(
    state: PlannerOwnedAgentGraphState,
    requirement_id: str | None,
) -> dict[str, Any] | None:
    if requirement_id is None:
        return None
    for requirement in state.requirement_ledger.requirements:
        if requirement.id == requirement_id:
            return _requirement_entry_summary(requirement)
    return None


def _requirement_entry_summary(requirement: RequirementLedgerEntry) -> dict[str, Any]:
    return {
        "id": requirement.id,
        "goal": requirement.goal,
        "requirement_type": requirement.requirement_type,
        "entity": requirement.entity,
        "intent_operation": requirement.intent_operation,
        "source_of_truth": requirement.source_of_truth,
        "constraints": dict(requirement.constraints),
        "requested_fields": list(requirement.requested_fields),
        "locked_constraints": list(requirement.locked_constraints),
        "status": requirement.status,
        "required": requirement.required,
        "evidence_refs": list(requirement.evidence_refs),
    }


def _evidence_summary(
    state: PlannerOwnedAgentGraphState,
    *,
    requirement_id: str | None,
) -> list[dict[str, Any]]:
    evidence_items = state.evidence_ledger.evidence
    if requirement_id is not None:
        evidence_items = [
            evidence for evidence in evidence_items if evidence.requirement_id == requirement_id
        ]
    return [
        {
            "id": evidence.id,
            "requirement_id": evidence.requirement_id,
            "source_type": evidence.source_type,
            "source_of_truth": evidence.source_of_truth,
            "tool_name": evidence.tool_name,
            "satisfies": list(evidence.satisfies),
            "normalized_result": _bounded_json(dict(evidence.normalized_result), limit=900),
        }
        for evidence in evidence_items
    ]


def _tool_call_summaries(
    state: PlannerOwnedAgentGraphState,
    context: PlannerDecisionProposalContext,
) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": call.tool_name,
            "call_id": call.call_id,
            "kind": call.kind,
            "requirement_id": call.requirement_id,
            "candidate_window_id": call.candidate_window_id,
            "args": dict(call.args),
            "is_read_only": _tool_card_for_call(state, call).is_read_only
            if _tool_card_for_call(state, call) is not None
            else None,
            "requires_approval": _tool_card_for_call(state, call).requires_approval
            if _tool_card_for_call(state, call) is not None
            else None,
            "missing_required_args": _missing_required_args(state, call),
        }
        for call in context.candidate_tool_calls
    ]


def _tool_card_summaries(
    state: PlannerOwnedAgentGraphState,
    context: PlannerDecisionProposalContext,
) -> list[dict[str, Any]]:
    candidate_names = {call.tool_name for call in context.candidate_tool_calls}
    cards: list[HydratedToolCard] = []
    for group in state.hydrated_tool_cards:
        if context.requirement_id is not None and group.requirement_id != context.requirement_id:
            continue
        for card in group.cards:
            if not candidate_names or card.tool_name in candidate_names:
                cards.append(card)
    return [
        {
            "tool_name": card.tool_name,
            "description": card.description,
            "actions": list(card.actions),
            "source_of_truth": card.source_of_truth,
            "is_read_only": card.is_read_only,
            "requires_approval": card.requires_approval,
            "required_args": list(card.required_args),
            "path_params": list(card.path_params),
            "query_params": list(card.query_params),
            "body_fields": list(_metadata_list(card, "body_fields")),
            "filter_params": list(_metadata_list(card, "filter_params")),
            "supports_filters": card.supports_filters,
            "supports_sort": card.supports_sort,
            "supports_limit": card.supports_limit,
            "supports_fields": card.supports_fields,
            "output_contract": card.output_contract,
            "side_effect_level": card.metadata.get("side_effect_level"),
        }
        for card in cards
    ]


def _tool_card_for_call(
    state: PlannerOwnedAgentGraphState,
    call: GraphToolCall,
) -> HydratedToolCard | None:
    for group in state.hydrated_tool_cards:
        if group.requirement_id != call.requirement_id:
            continue
        for card in group.cards:
            if card.tool_name == call.tool_name:
                return card
    return None


def _missing_required_args(
    state: PlannerOwnedAgentGraphState,
    call: GraphToolCall,
) -> list[str]:
    card = _tool_card_for_call(state, call)
    if card is None:
        return []
    return [
        arg
        for arg in card.required_args
        if call.args.get(arg) in (None, "", [], {})
    ]


def _metadata_list(card: HydratedToolCard, key: str) -> list[Any]:
    value = card.metadata.get(key)
    return value if isinstance(value, list) else []


def _bounded_state_view(state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
    return {
        "original_query": state.original_query,
        "requirement_ledger": {
            "revision": state.requirement_ledger.revision,
            "user_goal": state.requirement_ledger.user_goal,
            "requirements": [
                {
                    "id": requirement.id,
                    "goal": requirement.goal,
                    "requirement_type": requirement.requirement_type,
                    "entity": requirement.entity,
                    "intent_operation": requirement.intent_operation,
                    "source_of_truth": requirement.source_of_truth,
                    "constraints": dict(requirement.constraints),
                    "requested_fields": list(requirement.requested_fields),
                    "locked_constraints": list(requirement.locked_constraints),
                    "status": requirement.status,
                    "required": requirement.required,
                    "evidence_refs": list(requirement.evidence_refs),
                }
                for requirement in state.requirement_ledger.requirements
            ],
        },
        "capability_map": _capability_map_summary(state),
        "candidate_tool_windows": [
            window.model_dump(mode="json") for window in state.candidate_tool_windows
        ],
        "hydrated_tool_cards": [
            cards.model_dump(mode="json") for cards in state.hydrated_tool_cards
        ],
        "evidence_summary": [
            {
                "id": evidence.id,
                "requirement_id": evidence.requirement_id,
                "source_type": evidence.source_type,
                "source_of_truth": evidence.source_of_truth,
                "tool_name": evidence.tool_name,
                "satisfies": list(evidence.satisfies),
                "normalized_result": _bounded_json(dict(evidence.normalized_result), limit=1200),
            }
            for evidence in state.evidence_ledger.evidence
        ],
        "pending_approval": state.pending_approval.model_dump(mode="json"),
        "final_validation_status": (
            state.final_validation_result.status if state.final_validation_result is not None else None
        ),
        "full_openapi_catalog_visible": False,
    }


def _capability_map_summary(state: PlannerOwnedAgentGraphState) -> dict[str, Any]:
    active_entities = {
        requirement.entity
        for requirement in state.requirement_ledger.requirements
        if requirement.status == "open" and requirement.entity
    }
    active_sources = {
        requirement.source_of_truth
        for requirement in state.requirement_ledger.requirements
        if requirement.status == "open"
    }
    matching = []
    for entry in state.capability_map.capabilities:
        if active_entities and entry.entity not in active_entities:
            continue
        if active_sources and entry.source_of_truth not in active_sources:
            continue
        matching.append(
            {
                "capability_id": entry.capability_id,
                "source_of_truth": entry.source_of_truth,
                "entity": entry.entity,
                "actions": list(entry.actions),
                "supports": list(entry.supports),
                "output_contract": entry.output_contract,
                "requires_approval": entry.requires_approval,
            }
        )
        if len(matching) >= 12:
            break
    return {
        "total_capability_count": len(state.capability_map.capabilities),
        "matching_capabilities": matching,
        "field_alias_count": len(state.capability_map.field_aliases.aliases),
        "full_openapi_catalog_visible": False,
    }


def _bounded_json(value: Any, *, limit: int) -> Any:
    try:
        text = json.dumps(value, sort_keys=True, default=str)
    except Exception:
        text = str(value)
    if len(text) <= limit:
        return value
    return {"truncated": True, "preview": text[:limit]}


def _normalize_submission_payload(
    payload: Mapping[str, Any],
    *,
    state: PlannerOwnedAgentGraphState,
    context: PlannerDecisionProposalContext,
) -> dict[str, Any]:
    if "decision" in payload and isinstance(payload["decision"], Mapping):
        decision = dict(payload["decision"])
    else:
        decision = dict(payload)

    decision.setdefault("decision_id", context.decision_id)
    decision.setdefault("author", "planner")
    decision.setdefault("ledger_revision", state.requirement_ledger.revision)
    if context.requirement_id is not None:
        decision.setdefault("requirement_id", context.requirement_id)
    if context.requested_decision_kind is not None:
        decision.setdefault("decision_kind", context.requested_decision_kind)
    if context.capability_need is not None and decision.get("decision_kind") == "retrieve_tools":
        decision.setdefault("capability_need", context.capability_need.model_dump(mode="json"))

    kind = str(decision.get("decision_kind") or "")
    if kind not in {"choose_tool", "request_approval", "execute_tool", "execute_parallel_read_batch"}:
        decision.pop("selected_tool_call", None)
        decision.pop("selected_tool_calls", None)
    if kind in {"choose_tool", "request_approval", "execute_tool"}:
        selected_name_calls = _selected_tool_name_candidate_calls(decision, context)
        if kind == "choose_tool" and len(selected_name_calls) > 1:
            decision["selected_tool_call"] = None
            decision["selected_tool_calls"] = [call.model_dump(mode="json") for call in selected_name_calls]
        else:
            decision["selected_tool_call"] = _normalized_selected_tool_call(decision, context)
            decision.pop("selected_tool_calls", None)
        decision.pop("selected_tool_name", None)
        decision.pop("tool_name", None)
        decision.pop("candidate_tool_name", None)
        if context.capability_need is not None:
            decision.setdefault("capability_need", context.capability_need.model_dump(mode="json"))

    proposed = payload.get("proposed_requirement_ledger")
    if kind != "revise_requirements":
        proposed = None
    if proposed is not None and not isinstance(proposed, RequirementLedger):
        proposed = dict(proposed) if isinstance(proposed, Mapping) else proposed
    return {
        "decision": decision,
        "proposed_requirement_ledger": proposed,
    }


def _normalized_selected_tool_call(
    decision: Mapping[str, Any],
    context: PlannerDecisionProposalContext,
) -> dict[str, Any] | None:
    selected = decision.get("selected_tool_call")
    if selected is None:
        selected_calls = decision.get("selected_tool_calls")
        if isinstance(selected_calls, list) and selected_calls:
            selected = selected_calls[0]
    if isinstance(selected, GraphToolCall):
        return selected.model_dump(mode="json")
    if isinstance(selected, Mapping):
        tool_name = str(selected.get("tool_name") or "").strip()
        candidate = _candidate_tool_call_for_name(context, tool_name)
        if candidate is not None:
            merged = candidate.model_dump(mode="json")
            merged.update({key: value for key, value in selected.items() if value not in (None, "", [], {})})
            return merged
        return dict(selected)

    tool_name = str(
        decision.get("selected_tool_name")
        or decision.get("tool_name")
        or decision.get("candidate_tool_name")
        or ""
    ).strip()
    candidate = _candidate_tool_call_for_name(context, tool_name)
    if candidate is not None:
        return candidate.model_dump(mode="json")
    if len(context.candidate_tool_calls) == 1:
        return context.candidate_tool_calls[0].model_dump(mode="json")
    return None


def _selected_tool_name_candidate_calls(
    decision: Mapping[str, Any],
    context: PlannerDecisionProposalContext,
) -> list[GraphToolCall]:
    tool_name = str(
        decision.get("selected_tool_name")
        or decision.get("tool_name")
        or decision.get("candidate_tool_name")
        or ""
    ).strip()
    if not tool_name:
        return []
    return [call for call in context.candidate_tool_calls if call.tool_name == tool_name]


def _candidate_tool_call_for_name(
    context: PlannerDecisionProposalContext,
    tool_name: str,
) -> GraphToolCall | None:
    if not tool_name:
        return None
    return next((call for call in context.candidate_tool_calls if call.tool_name == tool_name), None)


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _proposer_event_fields(
    *,
    state: PlannerOwnedAgentGraphState,
    context: PlannerDecisionProposalContext,
    adapter_name: str,
    settings: Settings,
    prompt: str,
) -> dict[str, Any]:
    return {
        "adapter": adapter_name,
        "model_name": settings.planner_model,
        "base_url_type": _base_url_type(settings.planner_openai_base_url),
        "decision_id": context.decision_id,
        "requested_decision_kind": context.requested_decision_kind,
        "allowed_decision_kinds": list(context.allowed_decision_kinds),
        "requirement_id": context.requirement_id,
        "prior_decision_id": context.prior_decision_id,
        "ledger_revision": state.requirement_ledger.revision,
        "requirement_count": len(state.requirement_ledger.requirements),
        "open_requirement_count": sum(
            1 for requirement in state.requirement_ledger.requirements if requirement.status == "open"
        ),
        "candidate_tool_call_count": len(context.candidate_tool_calls),
        "candidate_window_count": len(state.candidate_tool_windows),
        "hydrated_tool_card_count": len(state.hydrated_tool_cards),
        "evidence_count": len(state.evidence_ledger.evidence),
        "prompt_chars": len(prompt),
        "prompt_bytes": len(prompt.encode("utf-8")),
        "timeout_s": settings.planner_timeout_s,
        "max_tokens": settings.planner_max_tokens,
    }


def _message_usage_metadata(raw_response: Any) -> dict[str, Any]:
    usage = getattr(raw_response, "usage_metadata", None)
    if isinstance(usage, Mapping):
        return dict(usage)
    response_metadata = getattr(raw_response, "response_metadata", None)
    if isinstance(response_metadata, Mapping):
        token_usage = response_metadata.get("token_usage")
        if isinstance(token_usage, Mapping):
            return dict(token_usage)
    return {}


def _message_response_metadata(raw_response: Any) -> dict[str, Any]:
    metadata = getattr(raw_response, "response_metadata", None)
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return {}


def _extract_json_object(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except Exception:
            return None
    return value if isinstance(value, dict) else None


def _message_content_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text") or item.get("content")
                if text is not None:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _base_url_type(base_url: str | None) -> str:
    if not base_url:
        return "openai_default"
    lowered = base_url.lower()
    if "127.0.0.1" in lowered or "localhost" in lowered:
        return "local"
    return "remote_openai_compatible"


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


__all__ = [
    "OfflineStructuredPlannerDecisionProposer",
    "OpenAICompatibleQwenPlannerDecisionProposer",
    "PlannerDecisionProposalContext",
    "PlannerDecisionProposalResult",
    "PlannerDecisionProposer",
    "PlannerDecisionProposerError",
    "build_planner_decision_proposer",
]
