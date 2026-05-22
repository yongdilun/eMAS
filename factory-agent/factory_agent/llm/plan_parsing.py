"""Normalize planner JSON emitted by structured LLM outputs."""

from __future__ import annotations

from typing import Any


def _coerce_non_negative_int(value: Any) -> int | None:
    """Coerce ``value`` to a non-negative int when safe. Returns None otherwise.

    Accepts native ints, integer-valued floats, and digit strings. Rejects bools
    (``True``/``False`` are subclasses of int but never represent step indices).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value.is_integer() and value >= 0:
            return int(value)
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped, 10)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
    return None


def _normalize_plan_dict(parsed: dict[str, Any]) -> dict[str, Any]:
    """Repair common LLM-output mistakes so ``AgentPlanOutput.model_validate`` can accept the dict.

    Local small models (e.g. Qwen2.5-1.5B) frequently:
    - put tool-name strings in ``depends_on`` instead of integer step indices
      (``["get__machines"]`` instead of ``[0]``);
    - use tool names in ``bindings[].from_step`` instead of integer indices;
    - return ``confidence`` as a string, send ``args``/``evidence`` as null,
      or use unknown ``execution_mode`` values.

    This normalizer:
    - builds a ``tool_name -> step_index`` map from the plan's own ``steps``
      so string entries that match a previous step's ``tool_name`` get rewritten
      to the matching index (only when the index is strictly less than the
      current step's index, preserving DAG ordering);
    - coerces every other field to its declared type, dropping unrecoverable
      values rather than failing the entire plan.

    The normalizer is purely schema-driven: it does NOT depend on any specific
    intent, tool, or request text, so it cannot bias planning decisions.
    """
    if not isinstance(parsed, dict):
        return parsed

    out = dict(parsed)
    out.setdefault("plan_explanation", "")
    out.setdefault("risk_summary", "")

    if not isinstance(out.get("plan_explanation"), str):
        out["plan_explanation"] = ""
    if not isinstance(out.get("risk_summary"), str):
        out["risk_summary"] = ""

    clarification = out.get("clarification")
    if isinstance(clarification, str):
        out["clarification"] = clarification.strip() or None
    elif clarification is not None:
        out["clarification"] = None

    raw_steps = out.get("steps")
    if not isinstance(raw_steps, list):
        out["steps"] = []
        return out

    tool_name_to_index: dict[str, int] = {}
    for idx, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            continue
        tool_name = step.get("tool_name")
        if isinstance(tool_name, str):
            stripped = tool_name.strip()
            if stripped and stripped not in tool_name_to_index:
                tool_name_to_index[stripped] = idx

    normalized_steps: list[dict[str, Any]] = []
    for idx, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            continue
        tool_name = step.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            continue

        new_step: dict[str, Any] = dict(step)
        new_step["tool_name"] = tool_name.strip()

        for container_field in ("args", "evidence"):
            value = new_step.get(container_field)
            if not isinstance(value, dict):
                new_step[container_field] = {}

        missing = new_step.get("missing_required")
        if isinstance(missing, list):
            new_step["missing_required"] = [str(item) for item in missing if isinstance(item, str)]
        else:
            new_step["missing_required"] = []

        confidence = new_step.get("confidence")
        coerced_conf: float = 0.0
        if isinstance(confidence, bool):
            coerced_conf = 1.0 if confidence else 0.0
        elif isinstance(confidence, (int, float)):
            coerced_conf = float(confidence)
        elif isinstance(confidence, str):
            try:
                coerced_conf = float(confidence.strip())
            except (TypeError, ValueError):
                coerced_conf = 0.0
        new_step["confidence"] = coerced_conf

        mode = new_step.get("execution_mode")
        new_step["execution_mode"] = mode if mode in {"single", "foreach"} else "single"

        raw_deps = new_step.get("depends_on")
        cleaned_deps: list[int] = []
        if isinstance(raw_deps, list):
            for dep in raw_deps:
                coerced = _coerce_non_negative_int(dep)
                if coerced is None and isinstance(dep, str):
                    target_idx = tool_name_to_index.get(dep.strip())
                    if target_idx is not None:
                        coerced = target_idx
                if coerced is None:
                    continue
                if 0 <= coerced < idx:
                    cleaned_deps.append(coerced)
        new_step["depends_on"] = sorted(set(cleaned_deps))

        raw_bindings = new_step.get("bindings")
        cleaned_bindings: list[dict[str, Any]] = []
        if isinstance(raw_bindings, list):
            for binding in raw_bindings:
                if not isinstance(binding, dict):
                    continue
                nb = dict(binding)
                from_step = nb.get("from_step")
                coerced_from = _coerce_non_negative_int(from_step)
                if coerced_from is None and isinstance(from_step, str):
                    target_idx = tool_name_to_index.get(from_step.strip())
                    if target_idx is not None:
                        coerced_from = target_idx
                if coerced_from is None or coerced_from < 0 or coerced_from >= idx:
                    continue
                field = nb.get("field")
                if not isinstance(field, str) or not field.strip():
                    alias = nb.get("source_field")
                    field = alias if isinstance(alias, str) else ""
                target_arg = nb.get("target_arg")
                if not isinstance(target_arg, str) or not target_arg.strip():
                    for alias_key in ("arg", "to_arg", "target", "target_field"):
                        alias = nb.get(alias_key)
                        if isinstance(alias, str) and alias.strip():
                            target_arg = alias
                            break
                if not isinstance(field, str) or not field.strip():
                    continue
                if not isinstance(target_arg, str) or not target_arg.strip():
                    continue

                result_path = nb.get("result_path")
                if not isinstance(result_path, str) or not result_path.strip():
                    result_path = "data"
                mode = nb.get("mode")
                if mode not in {"single", "foreach"}:
                    mode = "single"

                cleaned_bindings.append(
                    {
                        "from_step": coerced_from,
                        "result_path": result_path.strip(),
                        "field": field.strip(),
                        "target_arg": target_arg.strip(),
                        "mode": mode,
                    }
                )
        new_step["bindings"] = cleaned_bindings

        normalized_steps.append(new_step)

    out["steps"] = normalized_steps
    return out
