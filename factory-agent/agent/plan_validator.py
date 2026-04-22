from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from .schemas import PlanDraft, ToolInfo


@dataclass(frozen=True)
class PlanValidationResult:
    ok: bool
    errors: list[str]
    normalized_dependency_graph: dict[int, list[int]]
    normalized_parallel_groups: list[list[int]]
    plan_hash: str


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_plan_hash(plan: PlanDraft) -> str:
    payload = _stable_json(plan.model_dump())
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
    for key in ("id", "machine_id", "job_id", "inventory_id", "resource_id"):
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
        graph[int(s["step_index"])] = [int(x) for x in (s.get("depends_on") or [])]
    return graph


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
    for step in plan.steps:
        tool = tools_by_name.get(step.tool_name)
        if not tool:
            errors.append(f"Unknown tool: {step.tool_name}")
            continue
        try:
            Draft202012Validator(tool.input_schema).validate(step.args)
        except Exception as e:  # jsonschema raises ValidationError, but keep robust
            errors.append(f"Invalid args for tool {step.tool_name}: {e}")

    # Rule 5 (10.2): No duplicate (tool_name + args) pairs
    seen: set[str] = set()
    for step in plan.steps:
        key = f"{step.tool_name}:{_stable_json(step.args)}"
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
    tool_by_step = {s.step_index: tools_by_name.get(s.tool_name) for s in plan.steps}
    for step in sorted(plan.steps, key=lambda s: s.step_index):
        tool = tool_by_step.get(step.step_index)
        if not tool:
            continue
        if tool.method == "DELETE":
            prior_reads = [
                t
                for idx, t in tool_by_step.items()
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

