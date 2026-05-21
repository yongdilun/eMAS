from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .v2_contracts import EvidenceLedgerEntry


def aggregate_multi_entity_status_evidence(
    *,
    requirement_ledger: Any,
    evidence_ledger: Any,
    diagnostic_metadata: Mapping[str, Any] | None = None,
    replace: bool = True,
) -> bool:
    requirements = list(getattr(requirement_ledger, "requirements", []) or [])
    evidence_items = list(getattr(evidence_ledger, "evidence", []) or [])
    multi_requirement_ids = {
        str(getattr(requirement, "id", "") or "")
        for requirement in requirements
        if getattr(requirement, "requirement_type", "") == "multi_entity_status"
    }
    if not multi_requirement_ids:
        return False

    requirements_by_id = {str(getattr(requirement, "id", "") or ""): requirement for requirement in requirements}
    replacements: dict[str, EvidenceLedgerEntry] = {}
    replaced_ids: set[str] = set()
    for requirement_id in multi_requirement_ids:
        aggregate_id = f"ev-api-{requirement_id}-aggregate"
        if any(evidence.id == aggregate_id for evidence in evidence_items):
            continue
        matches = [
            evidence
            for evidence in evidence_items
            if evidence.requirement_id == requirement_id
            and evidence.source_type == "api_tool"
            and evidence.source_of_truth == "operational_state"
            and not _evidence_has_error(evidence)
        ]
        if len(matches) < 2:
            continue
        requirement = requirements_by_id.get(requirement_id)
        entity = str(getattr(requirement, "entity", "") or "").strip()
        rows: list[dict[str, Any]] = []
        for evidence in matches:
            rows.extend(_rows_from_evidence(evidence, entity=entity))
        if len(rows) < 2:
            continue

        normalized_result: dict[str, Any] = {"rows": rows}
        if entity:
            normalized_result["entity"] = entity
        first_filters = _first_mapping(matches, "applied_filters")
        if first_filters:
            normalized_result["applied_filters"] = first_filters
        first_args = _first_mapping(matches, "request_args")
        if first_args:
            normalized_result["request_args"] = first_args
        aggregate = EvidenceLedgerEntry(
            id=aggregate_id,
            requirement_id=requirement_id,
            source_type="api_tool",
            source_of_truth="operational_state",
            tool_name=matches[0].tool_name,
            normalized_result=normalized_result,
            diagnostic_metadata={
                **dict(diagnostic_metadata or {}),
                "aggregated_from": [evidence.id for evidence in matches],
            },
        )
        replacements[requirement_id] = aggregate
        replaced_ids.update(evidence.id for evidence in matches)

    if not replacements:
        return False

    new_evidence: list[EvidenceLedgerEntry] = []
    inserted: set[str] = set()
    for evidence in evidence_items:
        replacement = replacements.get(evidence.requirement_id)
        if replacement is not None and evidence.id in replaced_ids and evidence.requirement_id not in inserted:
            new_evidence.append(replacement)
            inserted.add(evidence.requirement_id)
            if replace:
                continue
        if replacement is not None and replace and evidence.id in replaced_ids:
            continue
        new_evidence.append(evidence)
    evidence_ledger.evidence = new_evidence
    return True


def _rows_from_evidence(evidence: EvidenceLedgerEntry, *, entity: str) -> list[dict[str, Any]]:
    result = evidence.normalized_result if isinstance(evidence.normalized_result, dict) else {}
    rows = result.get("rows")
    if isinstance(rows, list):
        return [dict(row) for row in rows if isinstance(row, dict)]
    fields = result.get("fields")
    if not isinstance(fields, dict):
        return []
    row = dict(fields)
    entity_id = result.get("entity_id")
    if entity_id not in (None, ""):
        id_key = f"{entity}_id" if entity else "entity_id"
        row.setdefault(id_key, entity_id)
    return [row]


def _evidence_has_error(evidence: EvidenceLedgerEntry) -> bool:
    result = evidence.normalized_result if isinstance(evidence.normalized_result, dict) else {}
    return bool(result.get("error"))


def _first_mapping(evidence_items: list[EvidenceLedgerEntry], key: str) -> dict[str, Any]:
    for evidence in evidence_items:
        value = evidence.normalized_result.get(key) if isinstance(evidence.normalized_result, dict) else None
        if isinstance(value, dict):
            return dict(value)
    return {}
