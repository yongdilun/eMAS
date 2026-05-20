from __future__ import annotations

import json
from typing import Any

NO_OP_MUTATION_STATUS = "not_changed"
NO_OP_MUTATION_REASON = "no_matching_records"


def _clean_text(value: Any, *, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _clean_count(value: Any, *, fallback: int = 0) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, count)


def normalize_no_op_mutation(value: Any) -> dict[str, Any] | None:
    """Normalize entity-specific no-op metadata into the response-document contract."""
    if not isinstance(value, dict):
        return None
    entity_type = _clean_text(
        value.get("entity_type") or value.get("entity") or value.get("record_type"),
        fallback="record",
    )
    selector_summary = _clean_text(
        value.get("selector_summary") or value.get("selector") or value.get("filter_summary"),
        fallback="requested selector",
    )
    change_summary = _clean_text(
        value.get("change_summary") or value.get("change") or value.get("requested_change"),
        fallback="requested change",
    )
    return {
        "entity_type": entity_type,
        "selector_summary": selector_summary,
        "change_summary": change_summary,
        "matched_count": _clean_count(value.get("matched_count"), fallback=0),
        "changed_count": _clean_count(value.get("changed_count"), fallback=0),
        "status": NO_OP_MUTATION_STATUS,
        "reason": NO_OP_MUTATION_REASON,
    }


def no_op_mutation_for_selector(
    *,
    entity_type: str,
    selector_summary: str,
    change_summary: str,
    matched_count: int = 0,
    changed_count: int = 0,
) -> dict[str, Any]:
    normalized = normalize_no_op_mutation(
        {
            "entity_type": entity_type,
            "selector_summary": selector_summary,
            "change_summary": change_summary,
            "matched_count": matched_count,
            "changed_count": changed_count,
        }
    )
    assert normalized is not None
    return normalized


def no_op_mutations_from_actions(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        candidates: list[Any] = []
        if "no_op_mutation" in action:
            candidates.append(action.get("no_op_mutation"))
        payload = action.get("payload")
        if isinstance(payload, dict) and "no_op_mutation" in payload:
            candidates.append(payload.get("no_op_mutation"))
        control = action.get("control_action")
        if isinstance(control, dict):
            control_payload = control.get("payload")
            if isinstance(control_payload, dict) and "no_op_mutation" in control_payload:
                candidates.append(control_payload.get("no_op_mutation"))
        for candidate in candidates:
            normalized = normalize_no_op_mutation(candidate)
            if normalized is None:
                continue
            key = json.dumps(normalized, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized)
    return out


def no_op_mutations_from_state(state: Any) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    out = no_op_mutations_from_actions(state.get("completed_actions"))
    if out:
        return out
    return no_op_mutations_from_actions(state.get("decisions"))


def add_no_op_mutations_to_payload(payload: dict[str, Any], state: Any) -> dict[str, Any]:
    no_ops = no_op_mutations_from_state(state)
    if not no_ops:
        return payload
    updated = dict(payload)
    updated["no_op_mutations"] = no_ops
    return updated


def add_no_op_mutations_to_contract(contract: dict[str, Any], state: Any) -> dict[str, Any]:
    no_ops = no_op_mutations_from_state(state)
    if not no_ops:
        return contract
    updated = dict(contract)
    updated["no_op_mutations"] = no_ops
    return updated
