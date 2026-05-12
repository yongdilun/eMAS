from __future__ import annotations

from typing import Any

from ...config import Settings
from ...security.guardrails import (
    build_unsupported_enum_clarification,
    missing_required_fields,
    promote_user_provenance,
    sanitize_tool_args_against_schema,
    strip_unsupported_optional_args,
)
from ...planning.plan_validator import validate_plan
from ...schemas import PlanBinding, PlanDraft, PlanStepDraft
from ...observability.telemetry import log_event
from ..errors import LangGraphPlannerClarification, LangGraphPlannerError
from ..planner_graph_helpers import (
    _deterministic_plan_repair,
    _extract_user_supported_path_args,
    _insert_delete_preflights,
    _reference_tool_preference,
)
from ..state import AgentState, user_query_text
from ..state import replace_list

try:
    from langgraph.types import interrupt
except Exception:  # pragma: no cover - defensive for older langgraph versions
    interrupt = None  # type: ignore[assignment]


def make_validate_node(settings: Settings):
    def validate_node(state: AgentState) -> AgentState:
        plan_blueprint = state.get("plan_blueprint")
        if plan_blueprint is None:
            raise LangGraphPlannerError("LangGraph planner did not produce a plan.")
        if plan_blueprint.clarification:
            return {
                "clarification": plan_blueprint.clarification,
                "validated_plan": None,
                "status": "awaiting_clarification",
            }

        tools_by_name = {tool.name: tool for tool in state.get("scoped_tools") or []}
        repaired = _deterministic_plan_repair(
            user_query_text(state),
            state.get("scoped_tools") or [],
            context=state.get("context") or {},
        )
        repaired_tool_names = {step.tool_name for step in repaired.steps} if repaired is not None else set()
        blueprint_tool_names = {step.tool_name for step in plan_blueprint.steps or []}
        incomplete_repairable_plan = bool(repaired_tool_names and not repaired_tool_names <= blueprint_tool_names)
        if not plan_blueprint.steps or any(step.tool_name not in tools_by_name for step in plan_blueprint.steps) or incomplete_repairable_plan:
            if repaired is not None:
                log_event(
                    "langgraph_planner_deterministic_repair",
                    level="WARNING",
                    intent=user_query_text(state),
                    reason="empty_unsupported_or_incomplete_plan",
                    raw_step_count=len(plan_blueprint.steps or []),
                    raw_tool_names=[step.tool_name for step in plan_blueprint.steps or []],
                    tool_names=[step.tool_name for step in repaired.steps],
                )
                plan_blueprint = repaired
        context = state.get("context") or {}
        intent_memory = context.get("intent_memory") if isinstance(context.get("intent_memory"), dict) else {}
        step_drafts: list[PlanStepDraft] = []
        contract_steps: list[dict[str, Any]] = []

        for idx, raw_step in enumerate(plan_blueprint.steps[: settings.max_plan_steps]):
            tool = tools_by_name.get(raw_step.tool_name)
            if not tool:
                raise LangGraphPlannerClarification(f"I could not safely select a supported tool for step {idx + 1}.")
            preferred_tool = _reference_tool_preference(user_query_text(state), tool, tools_by_name)
            if preferred_tool.name != tool.name:
                log_event(
                    "langgraph_planner_tool_preference_applied",
                    level="INFO",
                    intent=user_query_text(state),
                    original_tool_name=tool.name,
                    preferred_tool_name=preferred_tool.name,
                    reason="reference_data_preference",
                )
                tool = preferred_tool

            raw_args = dict(raw_step.args or {})
            raw_evidence = dict(raw_step.evidence or {})
            supported_args, supported_evidence = _extract_user_supported_path_args(
                intent=user_query_text(state),
                tool=tool,
                existing_args=raw_args,
            )
            if supported_args:
                raw_args.update(supported_args)
                for field, proof in supported_evidence.items():
                    raw_evidence.setdefault(field, proof)

            sanitized_args, dropped_fields = sanitize_tool_args_against_schema(tool, raw_args)
            if dropped_fields:
                clarification = build_unsupported_enum_clarification(
                    tool=tool,
                    raw_args=raw_args,
                    sanitized_args=sanitized_args,
                    dropped_fields=dropped_fields,
                    intent=user_query_text(state),
                    clause=user_query_text(state),
                )
                if clarification:
                    raise LangGraphPlannerClarification(clarification)
                log_event(
                    "langgraph_planner_args_sanitized",
                    level="WARNING",
                    tool_name=tool.name,
                    dropped_fields=dropped_fields,
                    raw_args=raw_args,
                    intent=user_query_text(state),
                )

            missing = sorted(
                set(missing_required_fields(tool, sanitized_args))
                | {field for field in raw_step.missing_required if sanitized_args.get(field) in (None, "")}
            )
            if missing and not tool.requires_approval:
                raise LangGraphPlannerClarification(
                    f"Need {', '.join(missing)} before I can use `{tool.name}` for this request."
                )

            provenance = promote_user_provenance(
                tool=tool,
                args=sanitized_args,
                intent=user_query_text(state),
                evidence=raw_evidence,
            )
            clean_args, provenance_dropped = strip_unsupported_optional_args(
                tool=tool,
                args=sanitized_args,
                intent=user_query_text(state),
                intent_memory=intent_memory,
                arg_provenance=provenance,
            )

            bindings: list[PlanBinding] = []
            for binding in raw_step.bindings or []:
                bindings.append(binding)
            depends_on = [dep for dep in raw_step.depends_on if 0 <= dep < idx]
            for binding in bindings:
                if binding.from_step < idx:
                    depends_on.append(binding.from_step)
            execution_mode = raw_step.execution_mode if raw_step.execution_mode in {"single", "foreach"} else "single"
            if any(binding.mode == "foreach" for binding in bindings):
                execution_mode = "foreach"

            step_drafts.append(
                PlanStepDraft(
                    step_index=idx,
                    tool_name=tool.name,
                    args=clean_args,
                    depends_on=sorted(set(depends_on)) or ([idx - 1] if idx > 0 else []),
                    execution_mode=execution_mode,  # type: ignore[arg-type]
                    bindings=bindings,
                )
            )
            contract_steps.append(
                {
                    "step_index": idx,
                    "tool_name": tool.name,
                    "args": clean_args,
                    "evidence": raw_evidence,
                    "confidence": raw_step.confidence,
                    "missing_required": [] if tool.requires_approval else missing,
                    "provenance_dropped": provenance_dropped,
                    "arg_provenance": provenance,
                    "bindings": [binding.model_dump() for binding in bindings],
                    "execution_mode": execution_mode,
                }
            )

        if not step_drafts:
            log_event(
                "langgraph_planner_empty_plan",
                level="WARNING",
                intent=user_query_text(state),
                raw_step_count=len(plan_blueprint.steps or []),
                raw_tool_names=[s.tool_name for s in plan_blueprint.steps or [] if isinstance(getattr(s, "tool_name", None), str)],
                scoped_tool_count=len(tools_by_name),
            )
            raise LangGraphPlannerClarification("I could not map that request to a safe factory tool plan.")

        step_drafts, contract_steps, inserted_preflights = _insert_delete_preflights(
            steps=step_drafts,
            contract_steps=contract_steps,
            tools_by_name=tools_by_name,
        )
        if inserted_preflights:
            log_event(
                "langgraph_planner_delete_preflight_inserted",
                level="INFO",
                intent=user_query_text(state),
                inserted_steps=inserted_preflights,
            )

        draft = PlanDraft(
            plan_explanation=plan_blueprint.plan_explanation.strip()
            or f"Plan prepared for intent: {user_query_text(state) or 'user request'}.",
            risk_summary=plan_blueprint.risk_summary.strip() or "Review the proposed tool calls before execution.",
            steps=step_drafts,
        )
        validation = validate_plan(draft, tools_by_name, max_steps=settings.max_plan_steps)
        if not validation.ok:
            raise LangGraphPlannerError("; ".join(validation.errors))
        return {
            "validated_plan": draft,
            "intent_contract": {
                "intent": user_query_text(state),
                "backend": "langgraph",
                "steps": contract_steps,
            },
            "final_response": draft.plan_explanation,
            "status": "completed",
            "validation_results": [{"ok": True, "phase": "plan_validator"}],
        }

    return validate_node


def make_final_validator_node(settings: Settings):
    """Phase 5 final validation + controlled repair loop + approval interrupt."""

    validate_node = make_validate_node(settings)

    def _has_fatal(state: AgentState) -> bool:
        if state.get("fatal_system_error"):
            return True
        errs = state.get("errors") or []
        return any(isinstance(e, str) and e.startswith("FATAL_SYSTEM_ERROR") for e in errs)

    def _needs_approval(state: AgentState) -> bool:
        staged = state.get("staged_writes") or []
        if not staged:
            return False
        decisions = state.get("decisions") or []
        for d in reversed(decisions[-6:]):
            if not isinstance(d, dict):
                continue
            risk = str(d.get("risk_level") or "")
            if risk in {"write_commit", "high_risk"}:
                return True
        return True

    def _approval_payload(state: AgentState) -> dict[str, Any]:
        staged = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]
        return {
            "kind": "approval_required",
            "summary": "High-risk write bundle requires approval before commit.",
            "count": len(staged),
            "preview": [
                {
                    "tool_name": x.get("tool_name"),
                    "output_ref": x.get("output_ref"),
                    "args": x.get("args"),
                }
                for x in staged[:5]
            ],
        }

    def _hard_constraints_present(state: AgentState) -> bool:
        cur = state.get("current_intent")
        if not isinstance(cur, dict):
            return False
        constraints = cur.get("explicit_constraints") or []
        for c in constraints:
            if isinstance(c, dict) and str(c.get("strength") or "hard") == "hard":
                return True
        return False

    def _dry_run_failure(state: AgentState) -> dict[str, Any] | None:
        staged = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]
        if not staged:
            return None
        dry = state.get("bundle_dry_run_result")
        if not isinstance(dry, dict):
            return {"ok": False, "reason": "missing_bundle_dry_run"}
        if dry.get("skipped") and dry.get("reason") != "no_staged_writes":
            return {"ok": False, "reason": dry.get("reason") or "dry_run_skipped", "detail": dry}
        if dry.get("ok") is False:
            return {"ok": False, "reason": "bundle_dry_run_failed", "detail": dry}
        return None

    def _route_forward_for_repair(
        state: AgentState,
        *,
        phase: str,
        reason: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempts = int(state.get("repair_attempts") or 0) + 1
        if attempts > max(1, int(settings.max_repair_attempts or 3)):
            return {
                "status": "failed",
                "errors": [f"repair_limit_exceeded:{attempts}"],
                "next_route": "fatal_end",
            }
        trunc_at = len(state.get("tool_outputs") or [])
        return {
            "repair_attempts": attempts,
            "failed_strategies": [
                {
                    "phase": phase,
                    "attempt": attempts,
                    "reason": reason,
                    "detail": detail or {},
                }
            ],
            "staged_writes": replace_list(),
            "bundle_dry_run_result": None,
            "last_commit_result": None,
            "pending_relevance_batch": None,
            "pending_decision": None,
            "tool_outputs_truncated_at": trunc_at,
            "status": "planning",
            "next_route": "continue_planner",
            "completed_actions": [
                {
                    "phase": "final_validator",
                    "kind": "auto_repair",
                    "summary": f"{phase} failed; routing back to planner.",
                }
            ],
        }

    def node(state: AgentState) -> dict[str, Any]:
        if _has_fatal(state):
            return {"status": "failed", "next_route": "fatal_end"}

        staged = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]

        # Commit-time business failure: forward-only auto-repair, never state rollback.
        commit = state.get("last_commit_result")
        if isinstance(commit, dict) and commit.get("ok") is False:
            if commit.get("infrastructure") or int(commit.get("http_status") or 0) >= 500:
                msg = f"FATAL_SYSTEM_ERROR:commit:{commit}"
                return {"errors": [msg], "fatal_system_error": msg, "status": "failed", "next_route": "fatal_end"}
            if int(commit.get("http_status") or 0) == 409 and _hard_constraints_present(state):
                return {
                    "status": "awaiting_clarification",
                    "clarification": "A required user constraint conflicts with current backend state. Please clarify or relax the constraint.",
                    "failed_strategies": [
                        {
                            "phase": "commit",
                            "reason": "hard_constraint_conflict",
                            "http_status": 409,
                        }
                    ],
                    "next_route": "fatal_end",
                }

            failed_entry = {
                "phase": "commit",
                "reason": "business_validation_failed",
                "http_status": commit.get("http_status"),
                "summary": str(commit.get("body") or commit.get("error") or "commit failed"),
            }
            return _route_forward_for_repair(
                state,
                phase="commit",
                reason="business_validation_failed",
                detail=failed_entry,
            )

        if staged and not isinstance(state.get("bundle_dry_run_result"), dict):
            return {
                "next_route": "bundle_dry_run",
                "status": "validating",
                "completed_actions": [
                    {
                        "phase": "final_validator",
                        "kind": "dry_run_required",
                        "summary": "Staged writes require bundle dry-run before final validation.",
                    }
                ],
            }

        dry_failure = _dry_run_failure(state)
        if dry_failure is not None:
            if _hard_constraints_present(state):
                return {
                    "status": "awaiting_clarification",
                    "clarification": "A required user constraint failed dry-run validation. Please clarify or relax the constraint.",
                    "failed_strategies": [
                        {
                            "phase": "bundle_dry_run",
                            "reason": "hard_constraint_conflict",
                            "detail": dry_failure,
                        }
                    ],
                    "next_route": "fatal_end",
                }
            return _route_forward_for_repair(
                state,
                phase="bundle_dry_run",
                reason=str(dry_failure.get("reason") or "dry_run_failed"),
                detail=dry_failure,
            )

        out = validate_node(state)
        if out.get("status") == "awaiting_clarification":
            out["next_route"] = "fatal_end"
            return out
        if out.get("status") != "completed":
            return _route_forward_for_repair(state, phase="final_validator", reason="plan_validation_failed")

        if _needs_approval(state):
            payload = _approval_payload(state)
            approved = True
            if interrupt is not None:
                resume_value = interrupt(payload)
                if isinstance(resume_value, dict):
                    approved = bool(resume_value.get("approved"))
                elif isinstance(resume_value, bool):
                    approved = resume_value
            if not approved:
                attempts = int(state.get("repair_attempts") or 0) + 1
                return {
                    "repair_attempts": attempts,
                    "status": "failed",
                    "failed_strategies": [
                        {
                            "phase": "approval",
                            "attempt": attempts,
                            "reason": "approval_rejected",
                        }
                    ],
                    "errors": ["approval_rejected"],
                    "next_route": "fatal_end",
                }
            out["approval_requests"] = [{"status": "approved", **payload}]

        out["repair_attempts"] = 0
        out["next_route"] = "commit" if staged else "end"
        out["status"] = "completed"
        return out

    return node
