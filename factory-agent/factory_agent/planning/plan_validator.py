from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from ..schemas import PlanDraft, ToolInfo


@dataclass(frozen=True)
class PlanValidationResult:
    ok: bool
    errors: list[str]
    normalized_dependency_graph: dict[int, list[int]]
    normalized_parallel_groups: list[list[int]]
    plan_hash: str


def stable_json(obj: Any) -> str:
    """Canonical JSON for plan hashing and duplicate-step keys (sorted keys, compact)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def _strip_required(schema: Any) -> Any:
    """Remove `required` constraints recursively.

    We use this to allow approval-gated (write) steps to be planned with partial
    args so the UI can present a form and collect missing fields before final
    approval and execution.
    """
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for key, val in schema.items():
            if key == "required" and isinstance(val, list):
                continue
            out[key] = _strip_required(val)
        return out
    if isinstance(schema, list):
        return [_strip_required(v) for v in schema]
    return schema


def compute_plan_hash(plan: PlanDraft) -> str:
    payload = stable_json(plan.model_dump())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _has_cycle(dep_graph: dict[int, list[int]]) -> bool:
    # DFS cycle detection
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: int) -> bool:
        if node in visited:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        for dep in dep_graph.get(node, []):
            if visit(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(n) for n in dep_graph.keys())


def _extract_write_target(tool: ToolInfo, args: dict[str, Any]) -> str:
    # Best-effort heuristic for conflict detection in parallel steps.
    # Treat read-only tools as no-write. For write tools, try to extract a stable target.
    if tool.is_read_only:
        return ""
    id_like_keys = [
        key
        for key in args.keys()
        if str(key).lower() == "id" or str(key).lower().endswith("_id")
    ]
    for key in sorted(id_like_keys):
        if key in args:
            return f"{tool.endpoint}:{key}={args.get(key)}"
    return tool.endpoint


def _normalize_parallel_groups(steps: list[dict[str, Any]]) -> list[list[int]]:
    groups: dict[int, list[int]] = {}
    for s in steps:
        if s.get("parallel_group") is None:
            continue
        groups.setdefault(int(s["parallel_group"]), []).append(int(s["step_index"]))
    return [sorted(v) for _, v in sorted(groups.items(), key=lambda kv: kv[0])]


def _normalize_dependency_graph(steps: list[dict[str, Any]]) -> dict[int, list[int]]:
    graph: dict[int, list[int]] = {}
    for s in steps:
        deps = [int(x) for x in (s.get("depends_on") or [])]
        for binding in s.get("bindings") or []:
            if isinstance(binding, dict):
                try:
                    deps.append(int(binding.get("from_step")))
                except Exception:
                    continue
        graph[int(s["step_index"])] = sorted(set(deps))
    return graph


def _schema_without_required(schema: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    if not fields:
        return schema
    normalized = json.loads(json.dumps(schema))
    required = normalized.get("required")
    if isinstance(required, list):
        normalized["required"] = [field for field in required if field not in fields]
        if not normalized["required"]:
            normalized.pop("required", None)
    return normalized


def _normalize_result_path(path: str) -> list[str]:
    normalized = (path or "").strip()
    if normalized.startswith("$."):
        normalized = normalized[2:]
    if normalized.startswith("result."):
        normalized = normalized[len("result.") :]
    if normalized.endswith("[*]"):
        normalized = normalized[:-3]
    if normalized.endswith("[]"):
        normalized = normalized[:-2]
    return [part for part in normalized.split(".") if part]


def _schema_for_result_path(schema: dict[str, Any], path: str) -> dict[str, Any] | None:
    node: Any = schema
    for part in _normalize_result_path(path):
        if not isinstance(node, dict):
            return None
        if node.get("type") == "array":
            node = node.get("items")
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        node = properties.get(part)
        if node is None:
            return None
    if isinstance(node, dict) and node.get("type") == "array":
        items = node.get("items")
        return items if isinstance(items, dict) else None
    return node if isinstance(node, dict) else None


def _schema_has_field(schema: dict[str, Any] | None, field: str) -> bool:
    if not isinstance(schema, dict):
        return False
    if schema.get("type") == "array":
        schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    return field in properties or not properties


def validate_plan(
    plan: PlanDraft,
    tools_by_name: dict[str, ToolInfo],
    *,
    max_steps: int = 10,
) -> PlanValidationResult:
    errors: list[str] = []

    step_dicts = [s.model_dump() for s in plan.steps]
    dependency_graph = plan.dependency_graph or _normalize_dependency_graph(step_dicts)
    parallel_groups = plan.parallel_groups or _normalize_parallel_groups(step_dicts)

    # Rule 4 (10.2): Max 10 steps per plan
    if len(plan.steps) > max_steps:
        errors.append(f"Plan exceeds {max_steps} steps. Break into smaller tasks.")

    # Basic structural checks
    indexes = [s.step_index for s in plan.steps]
    if len(set(indexes)) != len(indexes):
        errors.append("Duplicate step_index values detected.")
    if any(i < 0 for i in indexes):
        errors.append("step_index must be >= 0.")

    # Rule 1 (10.1): No self-dependency
    for idx, deps in dependency_graph.items():
        if idx in deps:
            errors.append(f"Step {idx} depends on itself")

    # Rule 2 (10.1): No forward-only dependencies
    for idx, deps in dependency_graph.items():
        for dep in deps:
            if dep >= idx:
                errors.append(f"Step {idx} depends on future step {dep}")

    # Rule 3 (10.1): No cycles
    if _has_cycle(dependency_graph):
        errors.append("Dependency graph contains a cycle")

    # Tool exists + args schema validation
    steps_by_index = {step.step_index: step for step in plan.steps}
    tools_by_step = {s.step_index: tools_by_name.get(s.tool_name) for s in plan.steps}
    for step in plan.steps:
        tool = tools_by_name.get(step.tool_name)
        if not tool:
            errors.append(f"Unknown tool: {step.tool_name}")
            continue
        if step.execution_mode not in ("single", "foreach"):
            errors.append(f"Invalid execution_mode for step {step.step_index}: {step.execution_mode}")
        bound_targets = {binding.target_arg for binding in (step.bindings or [])}
        properties = tool.input_schema.get("properties") if isinstance(tool.input_schema.get("properties"), dict) else {}
        for target in bound_targets:
            if target not in properties:
                errors.append(f"Binding target `{target}` is not an input field for tool {tool.name}.")
        for binding in step.bindings or []:
            if binding.from_step >= step.step_index:
                errors.append(f"Step {step.step_index} binding depends on future step {binding.from_step}")
                continue
            source_step = steps_by_index.get(binding.from_step)
            source_tool = tools_by_step.get(binding.from_step)
            if source_step is None or source_tool is None:
                errors.append(f"Step {step.step_index} binding references unknown step {binding.from_step}")
                continue
            source_schema = _schema_for_result_path(source_tool.output_schema or {}, binding.result_path)
            if source_schema is None:
                errors.append(
                    f"Step {step.step_index} binding path `{binding.result_path}` is not present in response schema for {source_tool.name}."
                )
            elif not _schema_has_field(source_schema, binding.field):
                errors.append(
                    f"Step {step.step_index} binding field `{binding.field}` is not present at `{binding.result_path}` for {source_tool.name}."
                )
            if binding.mode == "foreach" and not source_tool.is_read_only:
                errors.append(f"Step {step.step_index} foreach binding source must be read-only.")
            if binding.mode == "foreach" and tool.is_read_only:
                errors.append(f"Step {step.step_index} foreach binding target should be a write/action tool.")
        if step.execution_mode == "foreach" and not step.bindings:
            errors.append(f"Step {step.step_index} uses foreach without bindings.")
        if step.execution_mode == "foreach" and not tool.requires_approval:
            errors.append(f"Step {step.step_index} foreach write requires approval gating.")
        try:
            schema = tool.input_schema
            if tool.requires_approval:
                schema = _strip_required(schema)
            schema = _schema_without_required(schema, bound_targets)
            
            # Clean None values from args to support optional parameters passed as null/None
            step.args = {k: v for k, v in step.args.items() if v is not None}
            Draft202012Validator(schema).validate(step.args)
        except Exception as e:  # jsonschema raises ValidationError, but keep robust
            errors.append(f"Invalid args for tool {step.tool_name}: {e}")


    # Rule 5 (10.2): No duplicate (tool_name + args) pairs
    seen: set[str] = set()
    for step in plan.steps:
        key = f"{step.tool_name}:{stable_json(step.args)}"
        if key in seen:
            errors.append(f"Duplicate step detected: {step.tool_name} with same args")
        seen.add(key)

    # Rule 4 (10.1): Parallel steps must not have shared write targets
    for group in parallel_groups:
        write_targets: list[str] = []
        for idx in group:
            matching = next((s for s in plan.steps if s.step_index == idx), None)
            if not matching:
                continue
            tool = tools_by_name.get(matching.tool_name)
            if not tool or tool.is_read_only:
                continue
            write_targets.append(_extract_write_target(tool, matching.args))
        duplicates = {t for t in write_targets if t and write_targets.count(t) > 1}
        if duplicates:
            errors.append(f"Parallel group {group} has conflicting write targets: {sorted(duplicates)}")

    # Tool chain safety (10.2)
    # Rule 3: Approval steps must not be in a parallel group with other steps
    approval_steps = {s.step_index for s in plan.steps if tools_by_name.get(s.tool_name, None) and tools_by_name[s.tool_name].requires_approval}
    for group in parallel_groups:
        group_set = set(group)
        if group_set & approval_steps and len(group) > 1:
            errors.append(f"Parallel group {group} contains approval-gated steps; approval must be a sync point.")

    # Rule 2: No two CRITICAL side-effect steps in same parallel group
    for group in parallel_groups:
        critical = 0
        for idx in group:
            step = next((s for s in plan.steps if s.step_index == idx), None)
            if not step:
                continue
            tool = tools_by_name.get(step.tool_name)
            if tool and tool.side_effect_level == "CRITICAL":
                critical += 1
        if critical > 1:
            errors.append(f"Parallel group {group} contains multiple CRITICAL side-effect steps.")

    # Rule 1: DELETE must never appear before a GET of same resource in same plan (best-effort by endpoint)
    for step in sorted(plan.steps, key=lambda s: s.step_index):
        tool = tools_by_step.get(step.step_index)
        if not tool:
            continue
        if tool.method == "DELETE":
            prior_reads = [
                t
                for idx, t in tools_by_step.items()
                if t and idx < step.step_index and t.method == "GET" and t.endpoint == tool.endpoint
            ]
            if not prior_reads:
                errors.append(
                    f"DELETE step {step.step_index} ({tool.name}) appears before any GET of same endpoint {tool.endpoint}."
                )

    plan_hash = compute_plan_hash(plan)
    return PlanValidationResult(
        ok=len(errors) == 0,
        errors=errors,
        normalized_dependency_graph=dependency_graph,
        normalized_parallel_groups=parallel_groups,
        plan_hash=plan_hash,
    )

