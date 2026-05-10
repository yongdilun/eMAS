from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from ...persistence.models import Session as SessionRow
from ...persistence.models import Plan as PlanRow
from ...persistence.models import PlanStep as PlanStepRow
from ...persistence.models import ExecutionSnapshot as SnapshotRow
from ...schemas import ToolInfo
from .idempotency import compute_idempotency_key
from .tool_caller import ToolInputError


def result_items(body: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not isinstance(body, dict):
        return None
    for key in ("data", "items"):
        value = body.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
    return None


def result_path_parts(path: str) -> list[str]:
    normalized = (path or "data").strip()
    if normalized.startswith("$."):
        normalized = normalized[2:]
    if normalized.startswith("result."):
        normalized = normalized[len("result.") :]
    if normalized.endswith("[*]"):
        normalized = normalized[:-3]
    if normalized.endswith("[]"):
        normalized = normalized[:-2]
    return [part for part in normalized.split(".") if part]


def items_at_path(body: dict[str, Any] | None, path: str) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    node: Any = body
    for part in result_path_parts(path):
        if not isinstance(node, dict):
            return []
        node = node.get(part)
    if isinstance(node, list):
        return [item for item in node if isinstance(item, dict)]
    if isinstance(node, dict):
        return [node]
    return []


async def auto_page_items(
    engine: Any,
    *,
    source_tool: ToolInfo,
    source_step: PlanStepRow,
    initial_items: list[dict[str, Any]],
    result_path: str,
    plan: PlanRow,
    session: SessionRow,
    db: Any,
) -> list[dict[str, Any]]:
    if "limit" not in set(source_tool.query_params or []) or "offset" not in set(source_tool.query_params or []):
        return initial_items
    if "limit" in (source_step.args or {}) or "offset" in (source_step.args or {}):
        return initial_items
    if not initial_items or engine._settings.max_auto_pages <= 1:
        return initial_items

    items = list(initial_items)
    for page_index in range(1, max(1, engine._settings.max_auto_pages)):
        page_args = dict(source_step.args or {})
        page_args["limit"] = engine._settings.foreach_page_size
        page_args["offset"] = len(items)
        page_key = compute_idempotency_key(
            session_id=session.session_id,
            step_index=source_step.step_index,
            plan_version=plan.version,
            args={**page_args, "__auto_page": page_index},
        )
        body, _ = await engine._execute_tool_call(
            tool=source_tool,
            args=page_args,
            idempotency_key=page_key,
            plan_hash=plan.plan_hash,
            plan_version=plan.version,
            session_id=session.session_id,
            step_id=source_step.step_id,
            db=db,
        )
        page_items = items_at_path(body, result_path)
        if not page_items:
            break
        items.extend(page_items)
        if len(page_items) < engine._settings.foreach_page_size:
            break
    return items


async def prepare_bound_step(
    engine: Any,
    *,
    db: Any,
    session: SessionRow,
    plan: PlanRow,
    step: PlanStepRow,
    tool: ToolInfo,
    steps_by_index: dict[int, PlanStepRow],
    tools_by_name: dict[str, ToolInfo],
) -> None:
    from .parallel import AmbiguousExecutionError
    bindings = [binding for binding in (step.bindings or []) if isinstance(binding, dict)]
    if not bindings:
        return
    foreach_bindings = [binding for binding in bindings if binding.get("mode") == "foreach"]
    args = dict(step.args or {})

    if not foreach_bindings:
        for binding in bindings:
            source_step = steps_by_index.get(int(binding.get("from_step")))
            if not source_step or source_step.status != "DONE":
                raise ToolInputError(f"Binding source step {binding.get('from_step')} has not completed.")
            items = items_at_path(source_step.result if isinstance(source_step.result, dict) else None, str(binding.get("result_path") or "data"))
            if not items:
                raise AmbiguousExecutionError(f"Binding source step {source_step.step_index} returned no usable items.")
            value = items[0].get(str(binding.get("field")))
            if value in (None, ""):
                raise AmbiguousExecutionError(f"Binding field {binding.get('field')} was missing from source result.")
            args[str(binding.get("target_arg"))] = value
        if args != (step.args or {}):
            step.args = args
            step.idempotency_key = compute_idempotency_key(
                session_id=session.session_id,
                step_index=step.step_index,
                plan_version=plan.version,
                args=args,
            )
            await db.commit()
        return

    source_index = int(foreach_bindings[0].get("from_step"))
    source_step = steps_by_index.get(source_index)
    source_tool = tools_by_name.get(source_step.tool_name) if source_step else None
    if not source_step or not source_tool or source_step.status != "DONE":
        raise ToolInputError(f"Foreach source step {source_index} has not completed.")
    result_path = str(foreach_bindings[0].get("result_path") or "data")
    items = items_at_path(source_step.result if isinstance(source_step.result, dict) else None, result_path)
    items = await auto_page_items(
        engine,
        source_tool=source_tool,
        source_step=source_step,
        initial_items=items,
        result_path=result_path,
        plan=plan,
        session=session,
        db=db,
    )
    prepared_args: list[dict[str, Any]] = []
    for item in items:
        item_args = dict(args)
        skip = False
        for binding in foreach_bindings:
            value = item.get(str(binding.get("field")))
            if value in (None, ""):
                skip = True
                break
            item_args[str(binding.get("target_arg"))] = value
        if not skip:
            prepared_args.append(item_args)
    if not prepared_args:
        raise AmbiguousExecutionError("Foreach binding resolved zero executable items.")
    existing_state = step.bulk_state if isinstance(step.bulk_state, dict) else {}
    step.bulk_state = {
        **existing_state,
        "total_items": len(prepared_args),
        "max_foreach_items": engine._settings.max_foreach_items,
        "max_auto_pages": engine._settings.max_auto_pages,
        "prepared_args": prepared_args,
        "requires_bulk_approval": len(prepared_args) > engine._settings.max_foreach_items,
    }
    flag_modified(step, "bulk_state")
    await db.commit()


async def execute_foreach_step(
    engine: Any,
    *,
    tool: ToolInfo,
    step: PlanStepRow,
    plan: PlanRow,
    session: SessionRow,
    db: Any,
) -> dict[str, Any]:
    from .parallel import AmbiguousExecutionError
    state = step.bulk_state if isinstance(step.bulk_state, dict) else {}
    prepared_args = state.get("prepared_args") if isinstance(state.get("prepared_args"), list) else []
    if not prepared_args:
        raise ToolInputError("Foreach step has no prepared item args.")

    succeeded = list(state.get("succeeded") or [])
    failed = list(state.get("failed") or [])
    succeeded_indexes = {int(item.get("index")) for item in succeeded if isinstance(item, dict) and "index" in item}

    for index, item_args in enumerate(prepared_args):
        if index in succeeded_indexes:
            continue
        if not isinstance(item_args, dict):
            continue
        item_key = compute_idempotency_key(
            session_id=session.session_id,
            step_index=step.step_index,
            plan_version=plan.version,
            args={**item_args, "__foreach_index": index},
        )
        existing_snapshot = (
            await db.execute(
                select(SnapshotRow)
                .where(SnapshotRow.idempotency_key == item_key)
                .where(SnapshotRow.plan_hash == plan.plan_hash)
                .order_by(SnapshotRow.executed_at.desc())
            )
        ).scalars().first()
        if existing_snapshot and existing_snapshot.http_status and existing_snapshot.http_status < 400:
            succeeded.append({"index": index, "idempotency_key": item_key, "replayed": True})
            step.bulk_state = {**state, "succeeded": succeeded, "failed": failed}
            flag_modified(step, "bulk_state")
            await db.commit()
            continue
        try:
            body, _ = await engine._execute_tool_call(
                tool=tool,
                args=item_args,
                idempotency_key=item_key,
                plan_hash=plan.plan_hash,
                plan_version=plan.version,
                session_id=session.session_id,
                step_id=step.step_id,
                db=db,
            )
            succeeded.append({"index": index, "idempotency_key": item_key, "result": body})
            state = {**state, "succeeded": succeeded, "failed": failed}
            step.bulk_state = state
            flag_modified(step, "bulk_state")
            await db.commit()
        except Exception as exc:
            decision = engine._classify_error(err=exc, tool=tool, step=step)
            failed.append({"index": index, "args": item_args, "error": str(exc), "decision": decision})
            step.bulk_state = {**state, "succeeded": succeeded, "failed": failed}
            flag_modified(step, "bulk_state")
            await db.commit()
            if decision == "RETRY":
                raise
            raise AmbiguousExecutionError(
                f"Bulk step stopped after {len(succeeded)} success(es) and {len(failed)} failure(s): {exc}"
            ) from exc

    return {
        "bulk": True,
        "total": len(prepared_args),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "items": succeeded[:20],
    }
