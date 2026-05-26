from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..planning.v2_agent_state import PlannerOwnedAgentGraphState
from ..planning.v2_contracts import EvidenceLedgerEntry
from ..rag.source_metadata import is_insufficient_context_answer
from .v2_graph_interrupts import _evidence_can_satisfy_active_revision


def _phase6_response_blocks(state: PlannerOwnedAgentGraphState) -> list[dict[str, Any]]:
    requirements_by_id = {requirement.id: requirement for requirement in state.requirement_ledger.requirements}
    blocks: list[dict[str, Any]] = []
    for evidence in state.evidence_ledger.evidence:
        if not _evidence_can_satisfy_active_revision(state, evidence):
            continue
        requirement = requirements_by_id.get(evidence.requirement_id)
        block = _phase6_response_block_for_evidence(requirement, evidence)
        if block:
            blocks.append(block)
    return blocks


def _phase6_response_summary(state: PlannerOwnedAgentGraphState, blocks: list[dict[str, Any]]) -> str:
    _ = state
    parts = [
        str(block.get("summary") or block.get("user_message") or "").strip()
        for block in blocks
        if str(block.get("summary") or block.get("user_message") or "").strip()
    ]
    if not parts:
        return "No fulfilled read evidence was available for response rendering."
    return " ".join(dict.fromkeys(parts))


def _replan_limit_response_block(state: PlannerOwnedAgentGraphState, replan_spine: Mapping[str, Any]) -> dict[str, Any]:
    stale_refs = [
        str(ref)
        for ref in replan_spine.get("stale_attempt_evidence_refs", replan_spine.get("stale_evidence_refs", []))
        if str(ref)
    ]
    requirement_ids = [
        requirement.id
        for requirement in state.requirement_ledger.requirements
        if requirement.status != "satisfied"
    ]
    message = (
        "I could not verify the requested evidence after bounded retries, "
        "so I did not claim a successful status."
    )
    return {
        "id": "diagnostic:replan-limit",
        "type": "diagnostic",
        "severity": "error",
        "reason": "replan_limit_reached",
        "title": "Unable to verify evidence",
        "summary": message,
        "user_message": message,
        "cause": "The graph kept receiving incomplete or stale evidence for the active read requirement.",
        "impact": {
            "changes_applied": False,
            "safe_to_retry": True,
            "unsatisfied_requirement_ids": requirement_ids,
        },
        "current_state": "No successful active evidence satisfied the request.",
        "next_action": "Retry after the upstream data source can return the requested fields.",
        "technical_details": {
            "reason": "replan_limit_reached",
            "attempt_count": int(replan_spine.get("attempt_count") or 0),
            "max_attempts": int(replan_spine.get("max_attempts") or 0),
            "stale_attempt_evidence_refs": stale_refs,
            "sanitized": True,
        },
        "details_collapsed": True,
    }


def _phase6_response_block_for_evidence(requirement: Any | None, evidence: EvidenceLedgerEntry) -> dict[str, Any]:
    if evidence.source_type == "approval":
        status = str(evidence.normalized_result.get("approval_status") or evidence.normalized_result.get("status") or "")
        if status == "approved":
            return {
                "type": "approval_decision",
                "requirement_id": evidence.requirement_id,
                "evidence_ref": evidence.id,
                "approval_id": evidence.approval_id,
                "status": "approved",
                "summary": "Approval was recorded; the graph committed the staged write after approval.",
                "source_type": evidence.source_type,
            }
        return {
            "type": "approval_decision",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "approval_id": evidence.approval_id,
            "status": status or "rejected",
            "summary": str(
                evidence.normalized_result.get("rejection_reason")
                or evidence.normalized_result.get("reason")
                or "Approval was not applied."
            ),
            "source_type": evidence.source_type,
        }

    if _is_document_insufficient_context_evidence(evidence):
        answer = str(evidence.normalized_result.get("answer") or "").strip()
        sources_checked = evidence.normalized_result.get("sources_checked")
        source_count = len(sources_checked) if isinstance(sources_checked, list) else 0
        return {
            "type": "document_insufficient_context",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "summary": answer or "I do not have enough retrieved evidence to answer that safely.",
            "sources_checked_count": source_count,
            "source_type": evidence.source_type,
            "source_of_truth": evidence.source_of_truth,
        }

    if _evidence_has_no_match(evidence):
        return {
            "type": "no_record",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "entity_type": getattr(requirement, "entity", None),
            "summary": _no_match_summary(requirement, evidence),
            "source_type": evidence.source_type,
        }

    if evidence.source_type == "rag_tool":
        answer = str(evidence.normalized_result.get("answer") or "").strip()
        return {
            "type": "document_answer",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "summary": answer or "Document evidence was retrieved.",
            "citation_count": len(evidence.citations),
            "source_type": evidence.source_type,
        }

    rows = _phase6_rows(evidence.normalized_result)
    if rows is not None:
        return {
            "type": (
                "mutation_result"
                if getattr(requirement, "requirement_type", None) == "mutation_request"
                else ("result_table" if getattr(requirement, "requirement_type", None) == "filtered_collection" else "multi_status")
            ),
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "entity_type": getattr(requirement, "entity", None),
            "summary": _collection_summary(requirement, evidence, rows),
            "row_count": len(rows),
            "rows": rows,
            "requested_fields": list(getattr(requirement, "requested_fields", []) or []),
            "source_type": evidence.source_type,
        }

    fields = _phase6_fields(evidence.normalized_result)
    if getattr(requirement, "requirement_type", None) == "mutation_request" and evidence.source_type == "api_tool":
        entity = str(getattr(requirement, "entity", "") or evidence.normalized_result.get("entity") or "record")
        entity_id = evidence.normalized_result.get("entity_id") or _first_field_value(
            fields,
            [f"{entity}_id", "entity_id", "id", "machine_ref"],
        )
        return {
            "type": "mutation_result",
            "requirement_id": evidence.requirement_id,
            "evidence_ref": evidence.id,
            "entity_type": entity,
            "entity_id": entity_id,
            "summary": _mutation_summary(entity=entity, entity_id=entity_id, fields=fields),
            "fields": fields,
            "source_type": evidence.source_type,
        }

    entity = str(getattr(requirement, "entity", "") or evidence.normalized_result.get("entity") or "record")
    entity_id = evidence.normalized_result.get("entity_id") or _first_field_value(
        fields,
        [f"{entity}_id", "entity_id", "id", "machine_ref"],
    )
    status = _first_field_value(fields, ["status", "state"])
    summary = _single_status_summary(entity=entity, entity_id=entity_id, status=status)
    requested_fields = [f"{entity}_id", *list(getattr(requirement, "requested_fields", []) or [])]
    return {
        "type": "status_result",
        "requirement_id": evidence.requirement_id,
        "evidence_ref": evidence.id,
        "entity_type": entity,
        "entity_id": entity_id,
        "summary": summary,
        "primary_status": str(status).lower() if status not in (None, "") else None,
        "requested_fields": list(dict.fromkeys(field for field in requested_fields if field)),
        "fields": fields,
        "source_type": evidence.source_type,
    }


def _evidence_has_no_match(evidence: EvidenceLedgerEntry) -> bool:
    result = evidence.normalized_result
    return (
        result.get("no_match") is True
        or str(result.get("match_status") or "").lower() == "no_match"
        or str(result.get("status") or "").lower() == "no_match"
    )


def _is_document_insufficient_context_evidence(evidence: EvidenceLedgerEntry) -> bool:
    result = evidence.normalized_result
    if evidence.source_of_truth != "document_knowledge":
        return False
    return (
        evidence.diagnostic_metadata.get("reason") == "insufficient_context"
        or is_insufficient_context_answer(result.get("answer"))
    )


def _phase6_rows(result: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    for key in ("rows", "items", "results", "records", "data"):
        value = result.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return None


def _phase6_fields(result: Mapping[str, Any]) -> dict[str, Any]:
    fields = result.get("fields")
    if isinstance(fields, Mapping):
        return dict(fields)
    data = result.get("data")
    if isinstance(data, Mapping):
        return dict(data)
    return {
        key: value
        for key, value in result.items()
        if key not in {"status_code", "request_args", "entity", "entity_id", "rows", "applied_filters"}
    }


def _first_field_value(fields: Mapping[str, Any], names: list[str]) -> Any:
    for name in names:
        value = fields.get(name)
        if value not in (None, ""):
            return value
    return None


def _single_status_summary(*, entity: str, entity_id: Any, status: Any) -> str:
    label = entity.strip().capitalize() or "Record"
    if entity_id not in (None, "") and status not in (None, ""):
        return f"{label} {entity_id} is {str(status).lower()}."
    if entity_id not in (None, ""):
        return f"{label} {entity_id} was retrieved."
    return f"{label} status was retrieved."


def _collection_summary(requirement: Any | None, evidence: EvidenceLedgerEntry, rows: list[dict[str, Any]]) -> str:
    entity = str(getattr(requirement, "entity", "") or evidence.normalized_result.get("entity") or "record")
    plural = _plural_entity(entity)
    filters = dict(evidence.normalized_result.get("applied_filters") or {})
    priority = filters.get("priority") or getattr(requirement, "constraints", {}).get("priority")
    sort_by = getattr(requirement, "constraints", {}).get("sort_by") if requirement is not None else None
    descriptor = f"{priority}-priority " if priority not in (None, "", [], {}) else ""
    sorted_by = f" sorted by {sort_by}" if sort_by not in (None, "", [], {}) else ""
    return f"Found {len(rows)} {descriptor}{plural}{sorted_by}."


def _mutation_summary(*, entity: str, entity_id: Any, fields: Mapping[str, Any]) -> str:
    label = entity.strip().capitalize() or "Record"
    changed = [
        f"{key}={value}"
        for key, value in fields.items()
        if key not in {f"{entity}_id", "entity_id", "id", "machine_ref"}
    ]
    target = f" {entity_id}" if entity_id not in (None, "") else ""
    if changed:
        return f"{label}{target} updated ({', '.join(changed)})."
    return f"{label}{target} updated."


def _no_match_summary(requirement: Any | None, evidence: EvidenceLedgerEntry) -> str:
    base = str(evidence.normalized_result.get("summary") or evidence.normalized_result.get("message") or "").strip()
    if "no matching records were found" in base.lower():
        return base
    entity = str(getattr(requirement, "entity", "") or evidence.normalized_result.get("entity") or "").strip()
    filters = dict(evidence.normalized_result.get("applied_filters") or {})
    priority = filters.get("priority") or getattr(requirement, "constraints", {}).get("priority")
    if entity and priority not in (None, "", [], {}):
        return f"No matching records were found for {priority}-priority {_plural_entity(entity)}."
    if entity:
        return f"No matching records were found for {_plural_entity(entity)}."
    return "No matching records were found."


def _plural_entity(entity: str) -> str:
    normalized = entity.strip().lower() or "record"
    if normalized.endswith("s"):
        return normalized
    return f"{normalized}s"
