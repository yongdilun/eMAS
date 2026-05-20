from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

ID_PATTERNS: dict[str, dict[str, str]] = {
    "proposal_id": {"entity": "proposal", "prefix": "AIPROP-", "pattern": r"^AIPROP-[A-Za-z0-9-]+$"},
    "approval_id": {"entity": "approval", "prefix": "CHAPPR-", "pattern": r"^CHAPPR-[A-Za-z0-9-]+$"},
    "arrival_id": {"entity": "arrival", "prefix": "ARR-", "pattern": r"^ARR-[A-Za-z0-9-]+$"},
    "formula_id": {"entity": "formula", "prefix": "F-", "pattern": r"^F-[A-Za-z0-9-]+$"},
    "material_id": {"entity": "inventory", "prefix": "MAT-", "pattern": r"^MAT-[A-Za-z0-9-]+$"},
    "job_id": {"entity": "job", "prefix": "JOB-", "pattern": r"^JOB-[A-Za-z0-9-]+$"},
    "job_step_id": {"entity": "step", "prefix": "JS-", "pattern": r"^JS-[A-Za-z0-9-]+$"},
    "machine_id": {"entity": "machine", "prefix": "M-", "pattern": r"^M-[A-Za-z0-9-]+$"},
    "process_id": {"entity": "process", "prefix": "PRC-", "pattern": r"^PRC-[A-Za-z0-9-]+$"},
    "step_id": {"entity": "step", "prefix": "STP-", "pattern": r"^STP-[A-Za-z0-9-]+$"},
    "product_id": {"entity": "product", "prefix": "P-", "pattern": r"^P-[A-Za-z0-9-]+$"},
    "slot_id": {"entity": "slot", "prefix": "SLOT-", "pattern": r"^SLOT-[A-Za-z0-9-]+$"},
}

ID_FIELD_ALIASES = {
    "arrivalID": "arrival_id",
    "formulaID": "formula_id",
    "jobID": "job_id",
    "jobStepID": "job_step_id",
    "machineID": "machine_id",
    "materialID": "material_id",
    "processID": "process_id",
    "productID": "product_id",
    "proposalID": "proposal_id",
    "slotID": "slot_id",
}

ENTITY_TO_FIELD = {meta["entity"]: field for field, meta in ID_PATTERNS.items() if field != "step_id"}

CREATE_ID_FIELDS = {
    "dto.CreateFormulaRequest": "formula_id",
    "dto.CreateMachineRequest": "machine_id",
    "dto.CreateMaterialRequest": "material_id",
    "dto.CreateProcessRequest": "process_id",
    "dto.CreateProductRequest": "product_id",
}

ENTITY_STATUS_OPERATIONS: dict[tuple[str, str], dict[str, Any]] = {
    ("/machines/{id}", "get"): {
        "entity": "machine",
        "entity_id_field": "machine_id",
        "display_id_field": "machineID",
        "display_name_field": "machineName",
        "status_fields": [
            "status",
            "machineName",
            "machineType",
            "location",
            "capacityPerHour",
            "utilizationRate",
            "lastMaintenanceDate",
        ],
    },
    ("/jobs/{id}", "get"): {
        "entity": "job",
        "entity_id_field": "job_id",
        "display_id_field": "job_id",
        "display_name_field": "product_id",
        "status_fields": [
            "status",
            "priority",
            "deadline",
            "deadline_status",
            "quantity_total",
            "quantity_completed",
            "product_id",
        ],
    },
    ("/products/{id}", "get"): {
        "entity": "product",
        "entity_id_field": "product_id",
        "display_id_field": "productID",
        "display_name_field": "productName",
        "status_fields": [
            "status",
            "productName",
            "productType",
            "unitOfMeasure",
            "formulaID",
            "processID",
        ],
    },
    ("/inventory/materials/{id}", "get"): {
        "entity": "inventory",
        "entity_id_field": "material_id",
        "display_id_field": "materialID",
        "display_name_field": "materialName",
        "status_fields": [
            "status",
            "materialName",
            "currentStock",
            "minStock",
            "reorderLevel",
            "unit",
            "storageLocation",
            "lastUpdated",
        ],
    },
}

NO_MATCH_COLLECTION_OPERATIONS: dict[tuple[str, str], dict[str, str]] = {
    ("/machines", "get"): {"entity": "machine", "entity_id_field": "machine_id"},
    ("/jobs", "get"): {"entity": "job", "entity_id_field": "job_id"},
    ("/products", "get"): {"entity": "product", "entity_id_field": "product_id"},
    ("/inventory/materials", "get"): {"entity": "inventory", "entity_id_field": "material_id"},
}

BUSINESS_CHANGE_OPERATIONS: dict[tuple[str, str], dict[str, Any]] = {
    ("/jobs/{id}", "put"): {
        "entity": "job",
        "entity_id_field": "job_id",
        "display_id_field": "job_id",
        "changed_fields": ["deadline", "notes", "priority", "quantity_total", "status"],
        "selector_fields": ["id", "job_id", "status", "priority", "product_id", "machine_id"],
        "source_state_basis": ["read_collection_before_mutation", "read_entity_before_mutation"],
    },
}

AGENT_TRANSACTION_OPERATIONS: dict[tuple[str, str], dict[str, str]] = {
    ("/agent/transaction/bundle-dry-run", "post"): {"action": "validate", "commit_mode": "dry_run"},
    ("/agent/transaction/commit", "post"): {"action": "commit", "commit_mode": "commit"},
}


def _canonical_id_field(field_name: str) -> str:
    return ID_FIELD_ALIASES.get(field_name, field_name)


def _apply_id_metadata(schema: dict[str, Any], field_name: str) -> None:
    canonical = _canonical_id_field(field_name)
    meta = ID_PATTERNS.get(canonical)
    if not meta:
        return
    schema.setdefault("type", "string")
    schema["pattern"] = meta["pattern"]
    schema["x-ai-entity"] = meta["entity"]
    schema["x-ai-id-prefix"] = meta["prefix"]
    schema["x-ai-id-field"] = canonical


def _merge_unique_list(node: dict[str, Any], key: str, values: list[Any]) -> None:
    existing = node.get(key)
    merged: list[Any] = list(existing) if isinstance(existing, list) else []
    for value in values:
        if value not in merged:
            merged.append(value)
    node[key] = merged


def _apply_entity_status_metadata(operation: dict[str, Any], meta: dict[str, Any]) -> None:
    entity = meta["entity"]
    operation["x-ai-entity"] = entity
    operation["x-ai-action"] = "read"
    operation["x-ai-entity-id-field"] = meta["entity_id_field"]
    operation["x-ai-display-id-field"] = meta["display_id_field"]
    operation["x-ai-display-name-field"] = meta["display_name_field"]
    operation["x-ai-primary-status-field"] = "status"
    operation["x-ai-status-fields"] = meta["status_fields"]
    _merge_unique_list(operation, "x-ai-response-contracts", ["entity_status_v1"])
    _merge_unique_list(
        operation,
        "x-ai-capability-tags",
        [
            entity,
            "read",
            "lookup",
            "status",
            "entity_status",
            "entity_status_v1",
            "single_entity",
        ],
    )


def _apply_no_match_metadata(operation: dict[str, Any], meta: dict[str, str]) -> None:
    entity = meta["entity"]
    operation["x-ai-entity"] = entity
    operation["x-ai-action"] = "read"
    operation["x-ai-entity-id-field"] = meta["entity_id_field"]
    operation["x-ai-no-match-contract"] = {
        "contract": "entity_agnostic_no_matching_records_v1",
        "data_path": "data",
        "empty_when": "array length is zero",
        "approval_required": False,
    }
    _merge_unique_list(operation, "x-ai-response-contracts", ["entity_agnostic_no_matching_records_v1"])
    _merge_unique_list(
        operation,
        "x-ai-capability-tags",
        [
            entity,
            "read",
            "list",
            "filter",
            "no_match",
            "no_matching_records",
            "entity_agnostic_no_matching_records_v1",
        ],
    )


def _apply_business_change_metadata(operation: dict[str, Any], meta: dict[str, Any]) -> None:
    entity = meta["entity"]
    operation["x-ai-entity"] = entity
    operation["x-ai-action"] = "update"
    operation["x-ai-business-change-fields"] = {
        "contract": "business_change_v1",
        "entity_type": entity,
        "entity_id_field": meta["entity_id_field"],
        "display_id_field": meta["display_id_field"],
        "changed_fields": meta["changed_fields"],
        "selector_fields": meta["selector_fields"],
        "source_state_basis": meta["source_state_basis"],
        "row_outcome_fields": ["status", "primary_id", "data"],
    }
    _merge_unique_list(operation, "x-ai-response-contracts", ["business_change_v1"])
    _merge_unique_list(
        operation,
        "x-ai-capability-tags",
        [
            entity,
            "update",
            "write",
            "mutation",
            "approval_required",
            "business_change",
            "business_change_v1",
            "field_change",
            "row_outcome",
        ],
    )


def _apply_agent_transaction_metadata(operation: dict[str, Any], meta: dict[str, str]) -> None:
    operation["x-ai-entity"] = "agent_transaction"
    operation["x-ai-action"] = meta["action"]
    operation["x-ai-commit-mode"] = meta["commit_mode"]
    operation["x-ai-business-change-fields"] = {
        "contract": "business_change_v1",
        "staged_writes_path": "staged_writes",
        "operation_results_path": "data.operations",
        "tool_name_field": "tool_name",
        "record_id_field": "primary_id",
        "row_status_field": "status",
        "row_data_field": "data",
        "idempotency_field": "idempotency_key",
        "source_state_basis": ["staged_write_args", "tool_output_ref"],
    }
    operation["x-ai-no-match-contract"] = {
        "contract": "entity_agnostic_no_matching_records_v1",
        "source": "planner no-op groups before staged writes",
        "approval_required": False,
    }
    _merge_unique_list(operation, "x-ai-response-contracts", ["business_change_v1", "entity_agnostic_no_matching_records_v1"])
    _merge_unique_list(
        operation,
        "x-ai-capability-tags",
        [
            "agent_transaction",
            "staged_write",
            "business_change",
            "business_change_v1",
            "no_match",
            "no_matching_records",
            "entity_agnostic_no_matching_records_v1",
            meta["action"],
            meta["commit_mode"],
            "approval_required",
            "row_outcome",
        ],
    )


def _apply_operation_metadata(path: str, method: str, operation: dict[str, Any]) -> None:
    key = (path, method.lower())
    if key in ENTITY_STATUS_OPERATIONS:
        _apply_entity_status_metadata(operation, ENTITY_STATUS_OPERATIONS[key])
    if key in NO_MATCH_COLLECTION_OPERATIONS:
        _apply_no_match_metadata(operation, NO_MATCH_COLLECTION_OPERATIONS[key])
    if key in BUSINESS_CHANGE_OPERATIONS:
        _apply_business_change_metadata(operation, BUSINESS_CHANGE_OPERATIONS[key])
    if key in AGENT_TRANSACTION_OPERATIONS:
        _apply_agent_transaction_metadata(operation, AGENT_TRANSACTION_OPERATIONS[key])


def _walk_schema(node: Any, *, field_name: str | None = None) -> None:
    if isinstance(node, dict):
        if field_name:
            _apply_id_metadata(node, field_name)
        props = node.get("properties")
        if isinstance(props, dict):
            for name, child in props.items():
                _walk_schema(child, field_name=str(name))
        items = node.get("items")
        if isinstance(items, dict):
            _walk_schema(items)
        for key in ("allOf", "oneOf", "anyOf"):
            parts = node.get(key)
            if isinstance(parts, list):
                for part in parts:
                    _walk_schema(part)
    elif isinstance(node, list):
        for child in node:
            _walk_schema(child)


def _infer_path_id_field(path: str, param: dict[str, Any]) -> str | None:
    name = str(param.get("name") or "")
    if name != "id":
        return name if name in ID_PATTERNS else None
    description = str(param.get("description") or "").lower()
    for entity, field in ENTITY_TO_FIELD.items():
        if entity in description:
            return field
    path_lower = path.lower()
    if "expected-arrivals" in path_lower:
        return "arrival_id"
    if "proposals" in path_lower:
        return "proposal_id"
    if "approvals" in path_lower:
        return "approval_id"
    for segment, field in [
        ("jobs", "job_id"),
        ("machines", "machine_id"),
        ("products", "product_id"),
        ("materials", "material_id"),
        ("processes", "process_id"),
        ("formulas", "formula_id"),
        ("job-steps", "job_step_id"),
        ("slots", "slot_id"),
    ]:
        if f"/{segment}/" in path_lower or path_lower.endswith(f"/{segment}/{{id}}"):
            return field
    return None


def enrich(spec: dict[str, Any]) -> dict[str, Any]:
    definitions = spec.get("definitions")
    if isinstance(definitions, dict):
        for schema in definitions.values():
            _walk_schema(schema)
    components = spec.get("components")
    if isinstance(components, dict):
        for group in components.values():
            if isinstance(group, dict):
                for schema in group.values():
                    _walk_schema(schema)

    if isinstance(definitions, dict):
        for definition, id_field in CREATE_ID_FIELDS.items():
            schema = definitions.get(definition)
            if not isinstance(schema, dict):
                continue
            required = schema.get("required")
            if isinstance(required, list) and id_field in required:
                schema["required"] = [field for field in required if field != id_field]
            prop = (schema.get("properties") or {}).get(id_field)
            if isinstance(prop, dict):
                prop["description"] = (prop.get("description") or "Generated when omitted.").strip()
                prop["x-ai-generated"] = True

    paths = spec.get("paths")
    if isinstance(paths, dict):
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if not isinstance(operation, dict):
                    continue
                _apply_operation_metadata(str(path), str(method), operation)
                for param in operation.get("parameters") or []:
                    if not isinstance(param, dict):
                        continue
                    if param.get("in") not in {"path", "query"}:
                        continue
                    field = _infer_path_id_field(str(path), param)
                    if field:
                        _apply_id_metadata(param, field)
                    schema = param.get("schema")
                    if isinstance(schema, dict):
                        _walk_schema(schema, field_name=field)
    return spec


def update_json_and_yaml() -> dict[str, Any]:
    json_path = DOCS / "swagger.json"
    yaml_path = DOCS / "swagger.yaml"
    spec = enrich(json.loads(json_path.read_text(encoding="utf-8")))
    json_path.write_text(json.dumps(spec, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    yaml_path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return spec


def update_docs_go(spec: dict[str, Any]) -> None:
    docs_go = DOCS / "docs.go"
    text = docs_go.read_text(encoding="utf-8")
    match = re.search(r"const docTemplate = `(?P<body>.*)`\s*(?://[^\n]*\n\s*)*var SwaggerInfo", text, flags=re.S)
    if not match:
        return
    body = match.group("body")
    parseable = body.replace('"schemes": {{ marshal .Schemes }}', '"schemes": []')
    try:
        parsed = json.loads(parseable)
    except json.JSONDecodeError:
        return
    enriched = enrich(parsed)
    rendered = json.dumps(enriched, indent=4, ensure_ascii=False)
    rendered = rendered.replace('"schemes": []', '"schemes": {{ marshal .Schemes }}')
    updated = text[: match.start("body")] + rendered + text[match.end("body") :]
    docs_go.write_text(updated, encoding="utf-8")


def main() -> None:
    spec = update_json_and_yaml()
    update_docs_go(spec)


if __name__ == "__main__":
    main()
