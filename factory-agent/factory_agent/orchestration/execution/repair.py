from __future__ import annotations

from typing import Any

from ...persistence.models import Session as SessionRow
from ...persistence.models import Plan as PlanRow
from ...persistence.models import PlanStep as PlanStepRow
from ...schemas import ToolInfo
from ...observability.telemetry import log_event
from .idempotency import compute_idempotency_key


def get_repair_candidates(
    engine: Any,
    *,
    session: SessionRow,
    step: PlanStepRow,
    tool: ToolInfo,
    live_coverage: dict[str, Any],
    tried_args: dict[str, Any],
) -> list[dict[str, Any]]:
    from .predicate_guard import contract_clause_for_step
    live_preds = live_coverage.get("predicates") if isinstance(live_coverage.get("predicates"), list) else []
    unknown_fields: dict[str, str] = {}
    for p in live_preds:
        if not isinstance(p, dict):
            continue
        if p.get("verified") == "unknown_empty":
            field = p.get("field")
            value = p.get("value") or p.get("raw_term")
            if field and value:
                unknown_fields[str(field)] = str(value)
    if not unknown_fields:
        return []

    clause = contract_clause_for_step(session=session, step=step)
    contract_preds = clause.get("predicates") if clause and isinstance(clause.get("predicates"), list) else []
    properties = (tool.input_schema or {}).get("properties", {})
    candidates: list[dict[str, Any]] = []

    for pred in contract_preds:
        if not isinstance(pred, dict):
            continue
        tried_field = pred.get("field")
        if tried_field not in unknown_fields:
            continue
        raw_term = unknown_fields[tried_field]
        for cand in pred.get("candidate_fields") or []:
            if not isinstance(cand, dict):
                continue
            alt_field = cand.get("field")
            if not isinstance(alt_field, str) or not alt_field:
                continue
            if alt_field == tried_field:
                continue
            if alt_field not in properties:
                continue
            if tried_args.get(alt_field) not in (None, ""):
                continue
            candidates.append(
                {
                    "field": alt_field,
                    "value": raw_term,
                    "confidence": float(cand.get("confidence") or 0.0),
                    "reason": str(cand.get("reason") or ""),
                    "tried_field": tried_field,
                }
            )
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for c in candidates:
        key = (c["field"], str(c["value"]).lower())
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


async def repair_empty_predicate_result(
    engine: Any,
    *,
    session: SessionRow,
    plan: PlanRow,
    step: PlanStepRow,
    tool: ToolInfo,
    original_args: dict[str, Any],
    original_body: dict[str, Any] | None,
    live_coverage: dict[str, Any],
    db: Any,
) -> dict[str, Any] | None:
    tried_args = dict(original_args or {})
    repair_candidates = get_repair_candidates(
        engine, session=session, step=step, tool=tool, live_coverage=live_coverage, tried_args=tried_args
    )
    if not repair_candidates:
        return None

    tried_fields: list[str] = []
    for p in live_coverage.get("predicates") or []:
        if isinstance(p, dict) and p.get("verified") == "unknown_empty":
            f = p.get("field")
            if f and f not in tried_fields:
                tried_fields.append(f)

    from .foreach import result_items

    for candidate in repair_candidates:
        alt_field: str = candidate["field"]
        alt_value: Any = candidate["value"]
        repaired_args = dict(original_args)
        orig_field = candidate.get("tried_field")
        if orig_field and orig_field in repaired_args:
            del repaired_args[orig_field]
        repaired_args[alt_field] = alt_value

        log_event(
            "predicate_repair_attempt",
            session_id=session.session_id,
            step_id=step.step_id,
            tool=tool.name,
            alt_field=alt_field,
            alt_value=alt_value,
            confidence=candidate["confidence"],
        )

        repair_idem_key = compute_idempotency_key(
            session_id=session.session_id,
            step_index=int(step.step_index or 0),
            plan_version=plan.version,
            args=repaired_args,
        )
        try:
            repair_body, _ = await engine._execute_tool_call(
                tool=tool,
                args=repaired_args,
                idempotency_key=repair_idem_key,
                plan_hash=plan.plan_hash,
                plan_version=plan.version,
                session_id=session.session_id,
                step_id=step.step_id,
                db=db,
            )
        except Exception as exc:
            log_event(
                "predicate_repair_attempt_failed",
                level="WARNING",
                session_id=session.session_id,
                step_id=step.step_id,
                tool=tool.name,
                alt_field=alt_field,
                error=str(exc),
            )
            tried_fields.append(alt_field)
            continue

        items = result_items(repair_body)
        tried_fields.append(alt_field)

        if items is not None and len(items) > 0:
            if isinstance(repair_body, dict):
                repair_body = dict(repair_body)
                repair_body["_repair_meta"] = {
                    "repaired": True,
                    "original_field": orig_field,
                    "repaired_field": alt_field,
                    "repaired_value": alt_value,
                    "tried_fields": tried_fields,
                }
                step.args = repaired_args
            log_event(
                "predicate_repair_success",
                session_id=session.session_id,
                step_id=step.step_id,
                tool=tool.name,
                repaired_field=alt_field,
                items_found=len(items),
            )
            return repair_body

    tried_label = " and ".join(tried_fields) if tried_fields else "available fields"
    raw_term = (
        repair_candidates[0]["value"]
        if repair_candidates
        else str(next(iter(original_args.values()), "the given filter"))
    )
    entity = tool.endpoint.strip("/").split("/")[0] if tool.endpoint else "records"
    exhausted_body: dict[str, Any] = {
        "success": True,
        "data": [],
        "_repair_meta": {
            "repaired": False,
            "exhausted": True,
            "tried_fields": tried_fields,
            "raw_term": raw_term,
        },
        "_summary": (
            f'No {entity} found for "{raw_term}" after checking '
            f"likely fields: {tried_label}."
        ),
    }
    log_event(
        "predicate_repair_exhausted",
        level="WARNING",
        session_id=session.session_id,
        step_id=step.step_id,
        tool=tool.name,
        tried_fields=tried_fields,
        raw_term=raw_term,
    )
    return exhausted_body
