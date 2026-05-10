from __future__ import annotations

from typing import Any

from ...persistence.models import Session as SessionRow
from ...persistence.models import PlanStep as PlanStepRow
from ...schemas import ToolInfo
from ...observability.telemetry import log_event
from ...planning.intent_verifier import normalize_predicate_value
from .tool_caller import normalize_tool_args


class PredicateVerificationError(Exception):
    def __init__(self, message: str, *, coverage: dict[str, Any]):
        self.coverage = coverage
        super().__init__(message)


def contract_clause_for_step(*, session: SessionRow, step: PlanStepRow) -> dict[str, Any] | None:
    context = session.replan_context if isinstance(session.replan_context, dict) else {}
    contract = context.get("intent_contract") if isinstance(context.get("intent_contract"), dict) else {}
    clauses = contract.get("clauses") if isinstance(contract.get("clauses"), list) else []
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        if clause.get("tool_name") == step.tool_name and int(clause.get("step_index", step.step_index)) == int(step.step_index):
            return clause
    if 0 <= int(step.step_index or 0) < len(clauses):
        candidate = clauses[int(step.step_index or 0)]
        return candidate if isinstance(candidate, dict) else None
    return None


def verify_predicate_contract(
    *,
    session: SessionRow,
    step: PlanStepRow,
    tool: ToolInfo,
    body: dict[str, Any] | None,
    result_items_fn: Any,
) -> dict[str, Any] | None:
    if tool.method != "GET":
        return None
    clause = contract_clause_for_step(session=session, step=step)
    if not clause:
        return None
    predicates = clause.get("predicates") if isinstance(clause.get("predicates"), list) else []
    requested = [p for p in predicates if isinstance(p, dict) and p.get("requested")]
    if not requested:
        return None

    path_args, query_args, body_args = normalize_tool_args(tool, step.args or {})
    sent_args = {**body_args, **path_args, **query_args}
    items = result_items_fn(body)
    coverage_predicates: list[dict[str, Any]] = []
    errors: list[str] = []
    unknowns = 0
    verified_count = 0
    for pred in requested:
        field = pred.get("field")
        expected = pred.get("value")
        current = dict(pred)
        sent = bool(field and field in sent_args and sent_args.get(field) not in (None, ""))
        current["sent"] = sent
        if not pred.get("resolved") or not field:
            errors.append(f"predicate unresolved: {pred.get('raw_term')}")
            current["verified"] = False
        elif not sent:
            errors.append(f"predicate not sent: {field}={expected}")
            current["verified"] = False
        elif items is None:
            current["verified"] = "unknown"
            current["reason"] = "response has no comparable list/data field"
            unknowns += 1
        elif len(items) == 0:
            current["verified"] = "unknown_empty"
            current["reason"] = "empty result — filter sent but result is ambiguous; repair loop may retry"
            unknowns += 1
        else:
            comparable = [item for item in items if field in item]
            if not comparable:
                current["verified"] = "unknown"
                current["reason"] = "response rows do not include comparable field"
                unknowns += 1
            else:
                expected_norm = normalize_predicate_value(str(expected))
                mismatches = [
                    item.get(field)
                    for item in comparable
                    if normalize_predicate_value(str(item.get(field))) != expected_norm
                ]
                if mismatches:
                    current["verified"] = False
                    current["reason"] = "comparable rows did not match predicate"
                    errors.append(f"predicate mismatch: {field}={expected}")
                else:
                    current["verified"] = True
                    current["reason"] = "all comparable rows matched"
                    verified_count += 1
        coverage_predicates.append(current)

    total_checks = max(1, len(requested) * 3)
    met = 0
    for pred in coverage_predicates:
        for key in ("requested", "resolved", "sent"):
            if pred.get(key):
                met += 1
    coverage = {
        "predicates": coverage_predicates,
        "predicate_coverage_score": round(met / total_checks, 3),
        "verified_count": verified_count,
        "unknown_count": unknowns,
        "errors": errors,
    }
    if errors:
        log_event(
            "predicate_verifier_blocked",
            level="WARNING",
            session_id=session.session_id,
            step_id=step.step_id,
            tool=tool.name,
            coverage=coverage,
        )
        raise PredicateVerificationError("; ".join(errors), coverage=coverage)
    log_event(
        "predicate_verifier_passed",
        session_id=session.session_id,
        step_id=step.step_id,
        tool=tool.name,
        coverage=coverage,
    )
    return coverage
