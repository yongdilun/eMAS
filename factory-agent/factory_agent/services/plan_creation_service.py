from __future__ import annotations

import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from factory_agent.analysis.summary_backend import SummaryAdapter, SummaryBackendError, compact_tool_outputs_for_narrative
from factory_agent.api.dependencies import require_session_owner
from factory_agent.api.response_mappers import plan_to_response
from factory_agent.config import Settings, resolve_factory_agent_engine_for_runtime
from factory_agent.graph.http_tool_client import execute_tool_http
from factory_agent.graph.noop_mutations import no_op_mutation_for_selector
from factory_agent.observability.metrics import metrics
from factory_agent.observability.telemetry import log_event
from factory_agent.orchestration.memory_manager import MemoryManager
from factory_agent.orchestration.session_manager import SessionManager
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import DeadLetter as DeadLetterRow
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.planner import (
    PlannerApprovalRequired,
    PlannerBackendError,
    PlannerClarificationError,
    PlannerConfirmationRequired,
    PlannerPlanRejected,
)
from factory_agent.planning.intent import (
    assess_intent,
    intent_constraint_values,
    loto_query_with_resolved_machine_context,
    resolve_contextual_loto_machine_id,
    semantic_frame_for_text,
)
from factory_agent.planning.plan_validator import validate_plan
from factory_agent.planning.tool_output_alignment import align_tool_outputs_to_steps
from factory_agent.planning.tool_selector import ToolSelector
from factory_agent.planning.v2_planner_loop import (
    LegacyExecutionSignals,
    PlannerOwnedV2Loop,
    attach_direct_v2_trace_to_intent_contract,
    attach_legacy_trace_to_intent_contract,
    attach_v2_shadow_trace_to_intent_contract,
    legacy_graph_signals,
    legacy_rag_signals,
)
from factory_agent.planning.v2_contracts import EvidenceLedgerEntry, ExecutionTrace, PlannerOwnedLoopV2State
from factory_agent.planning.v2_rag_tool import (
    build_v2_rag_evidence,
    ensure_v2_rag_tool,
    open_document_requirements,
)
from factory_agent.planning.v2_satisfaction import (
    apply_deterministic_evidence_satisfaction,
    validate_v2_final_state,
)
from factory_agent.rag.knowledge_policy import default_knowledge_policy_registry
from factory_agent.rag.source_metadata import normalize_source_locators, sanitize_rag_answer_text
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import PlanCreateRequest, PlanResponse, ToolInfo
from factory_agent.security.permissions import filter_tools_for_role, role_from_claims
from factory_agent.session_state import is_user_cancelled_session
from factory_agent.tools.arguments import compute_idempotency_key


def _bump_session_revision(sess: SessionRow) -> None:
    """Advance both DB and response-document revisions for state-changing writes."""
    sess.version = (getattr(sess, "version", None) or 0) + 1
    sess.event_seq = (getattr(sess, "event_seq", None) or 0) + 1


PLANNER_NO_ACTION_REASON = "planner_no_action"
PLANNER_NO_ACTION_MESSAGE = (
    "planner_no_action: The planner did not produce a safe plan, approval, or final result for this actionable "
    "request. Current state: blocked before execution. Next action: refine the request or check tool availability, "
    "then retry."
)
EMPTY_PLAN_COMPLETION_BACKENDS = {"system", "v2_planner_loop", "v2_rag_tool"}


class PlanCreationService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_mgr: SessionManager,
        memory_manager: MemoryManager,
        planner: Any,
        tool_selector: ToolSelector,
        summary_adapter: SummaryAdapter,
        tool_registry: ToolRegistry,
        rag_pipeline: Any | None = None,
        uuid_factory: Callable[[], str],
    ) -> None:
        self._settings = settings
        self._session_mgr = session_mgr
        self._memory_manager = memory_manager
        self._planner = planner
        self._tool_selector = tool_selector
        self._summary_adapter = summary_adapter
        self._tool_registry = tool_registry
        self._rag_pipeline = rag_pipeline
        self._generate_uuid = uuid_factory
        self._knowledge_policy_registry = default_knowledge_policy_registry()

    def _should_enforce_registry_health(self) -> bool:
        if not self._settings.enforce_tool_registry_health:
            return False
        return not self._settings.database_url.startswith("sqlite+aiosqlite:///:memory:")

    async def _latest_user_message(self, *, db: AsyncSession, session_id: str) -> MessageRow | None:
        return (
            await db.execute(
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .where(MessageRow.role == "user")
                .order_by(MessageRow.created_at.desc())
            )
        ).scalars().first()

    async def _previous_turn_message_context(
        self,
        *,
        db: AsyncSession,
        session_id: str,
        latest_user: MessageRow | None,
    ) -> list[str]:
        stmt = (
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .where(MessageRow.role.in_(["user", "assistant"]))
            .order_by(MessageRow.created_at.asc(), MessageRow.message_id.asc())
        )
        if latest_user:
            stmt = stmt.where(MessageRow.message_id != latest_user.message_id)
            stmt = stmt.where(MessageRow.created_at <= latest_user.created_at)
        rows = (await db.execute(stmt)).scalars().all()
        if not rows:
            return []

        previous_user_idx = next(
            (idx for idx in range(len(rows) - 1, -1, -1) if rows[idx].role == "user"),
            None,
        )
        if previous_user_idx is None:
            return []
        previous_turn = rows[previous_user_idx:]
        return [str(row.content or "") for row in previous_turn if str(row.content or "").strip()]

    def _loto_query_with_resolved_machine(self, intent: str, machine_id: str | None) -> str:
        return loto_query_with_resolved_machine_context(intent, machine_id)

    def _rag_query_with_required_machine_context(
        self,
        query: str,
        *,
        intent: str,
        semantic_frame: Any | None,
    ) -> str:
        frame_entities = getattr(semantic_frame, "normalized_entities", None)
        machine_ids = []
        if isinstance(frame_entities, dict):
            raw_values = frame_entities.get("machine_id") or []
            if isinstance(raw_values, str):
                raw_values = [raw_values]
            machine_ids = [str(value).strip().upper() for value in raw_values if str(value or "").strip()]
        if not machine_ids:
            machine_ids = intent_constraint_values(intent, "machine_id")
        if not machine_ids:
            return query
        query_text = str(query or intent or "")
        upper_query = query_text.upper()
        if any(machine_id in upper_query for machine_id in machine_ids):
            return query_text
        return (
            f"{query_text.rstrip()}\n\n"
            f"Required machine context from the routed request: machine {machine_ids[0]}."
        )

    async def _resolve_loto_machine_context(
        self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        latest_user: MessageRow | None,
        intent: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        previous_texts = await self._previous_turn_message_context(
            db=db,
            session_id=sess.session_id,
            latest_user=latest_user,
        )
        machine_id = resolve_contextual_loto_machine_id(intent, previous_texts)
        if not machine_id:
            return None, sess.replan_context if isinstance(sess.replan_context, dict) else None
        rag_query = self._loto_query_with_resolved_machine(intent, machine_id)
        context = dict(sess.replan_context or {})
        context["contextual_resolution"] = {
            "entity_type": "machine",
            "machine_id": machine_id,
            "source": "previous_turn",
            "original_intent": intent,
            "rag_query": rag_query,
        }
        sess.replan_context = context
        log_event(
            "loto_contextual_machine_resolved",
            session_id=sess.session_id,
            machine_id=machine_id,
        )
        return machine_id, context

    async def _load_current_plan(self, *, db: AsyncSession, session_id: str) -> PlanRow | None:
        sess = await self._session_mgr.get_session(db, session_id=session_id)
        if not sess or not sess.plan_id:
            return None
        return (await db.execute(select(PlanRow).where(PlanRow.plan_id == sess.plan_id))).scalars().first()

    def _is_cancelled_session(self, sess: SessionRow) -> bool:
        return is_user_cancelled_session(sess)

    async def _cancelled_plan_response_if_needed(
        self,
        *,
        db: AsyncSession,
        sess: SessionRow,
    ) -> PlanResponse | None:
        await db.refresh(sess)
        if not self._is_cancelled_session(sess):
            return None
        current = await self._load_current_plan(db=db, session_id=sess.session_id)
        if current:
            log_event(
                "plan_generation_result_ignored_after_cancel",
                session_id=sess.session_id,
                plan_id=current.plan_id,
            )
            response = plan_to_response(current)
            response.status = "COMPLETED"
            return response
        raise HTTPException(status_code=409, detail="session was cancelled")

    def _plan_validation_step_limit(
        self,
        draft: Any,
        *,
        backend_used: str,
        kind: str,
        status: str,
        tool_outputs: list[dict[str, Any]] | None,
    ) -> int:
        limit = int(self._settings.max_plan_steps)
        steps = getattr(draft, "steps", []) or []
        if (
            backend_used in {"langgraph", "v2_planner_loop"}
            and kind == "execution"
            and status == "COMPLETED"
            and tool_outputs
            and len(steps) > limit
        ):
            step_tool_counts = Counter(str(getattr(step, "tool_name", "") or "") for step in steps)
            output_tool_counts = Counter(
                str(row.get("tool_name") or "") for row in tool_outputs if isinstance(row, dict)
            )
            if not all(output_tool_counts[name] >= count for name, count in step_tool_counts.items() if name):
                return limit
            # Completed planner-owned bulk-write plans are an audit projection of
            # already committed row-level operations; preserving every row is
            # safer than hiding committed writes behind the interactive draft cap.
            return len(steps)
        return limit

    async def _persist_conversation_reply_as_empty_plan(self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        reply: str,
        mode: str,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        context_to_keep: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> PlanResponse:
        from ..schemas import PlanDraft

        reply = sanitize_rag_answer_text(reply)
        db.add(
            MessageRow(
                message_id=self._generate_uuid(),
                session_id=sess.session_id,
                role="assistant",
                content=reply,
                mode=mode,
                tool_name="__conversation__",
            )
        )
        await db.commit()
        sources = kwargs.get("sources", [])
        sources_dict = normalize_source_locators(sources, fallback_snippet=reply)
        backend_used = str(kwargs.get("backend_used") or "system")

        empty_draft = PlanDraft(
            plan_explanation=reply,
            risk_summary="No tool execution required.",
            steps=[],
            sources=sources_dict,
            safety_content=kwargs.get("safety_content"),
        )
        return await self._persist_plan(
            db=db,
            sess=sess,
            draft=empty_draft,
            tools_by_name=tools_by_name,
            backend_used=backend_used,
            kind="execution",
            status="COMPLETED",
            intent=intent,
            context_to_keep=context_to_keep,
        )

    def _loto_machine_clarification_reply(self) -> str:
        return (
            "Which machine ID should I use for the LOTO procedure? "
            "Please provide the exact machine ID from the equipment label or work order."
        )

    def _semantic_clarification_reply(self, frame: Any) -> str:
        if frame.domain_intent == "loto_procedure" and "machine_id" in frame.missing_required_entities:
            return self._loto_machine_clarification_reply()
        if frame.domain_intent == "machine_status" and "machine_id" in frame.missing_required_entities:
            return (
                "Which machine ID should I use for the live status lookup? "
                "Please provide the exact machine ID from the equipment label or work order."
            )
        return "I need one more detail before I can route this safely. Please provide the missing required field."

    def _seeded_planner_handles_intent(self, intent: str) -> bool:
        handles = getattr(self._planner, "handles_seeded_intent", None)
        return bool(handles(intent)) if callable(handles) else False

    async def _answer_knowledge_question_as_plan(self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        mode: str,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        context_to_keep: dict[str, Any] | None = None,
        semantic_frame: Any | None = None,
    ) -> PlanResponse:
        answer = ""
        sources: list[Any] = []
        safety_content: str | None = None
        try:
            if self._rag_pipeline is None:
                from ..rag.pipeline import RAGPipeline

                self._rag_pipeline = RAGPipeline()
            result = await self._rag_pipeline.run(query=intent, session_id=sess.session_id, route="RAG_ONLY")
            answer = str(getattr(result, "answer", "") or "").strip()
            sources = list(getattr(result, "sources", []) or [])
            safety_content = getattr(result, "safety_content", None)
        except Exception as exc:
            log_event(
                "rag_knowledge_answer_failed",
                level="WARNING",
                session_id=sess.session_id,
                error=str(exc),
            )

        semantic_frame = semantic_frame or semantic_frame_for_text(intent)
        route_family = str(getattr(semantic_frame, "route", "") or "unknown")
        policy_application = self._knowledge_policy_registry.apply(
            route_family=route_family,
            query=intent,
            answer=answer,
            sources=sources,
            safety_content=safety_content,
            semantic_frame=semantic_frame,
        )
        answer = sanitize_rag_answer_text(policy_application.answer or "")
        sources = normalize_source_locators(policy_application.sources, fallback_snippet=answer)
        safety_content = policy_application.safety_content

        if not answer:
            answer = "I could not find enough relevant knowledge-base material to answer that safely."

        return await self._persist_conversation_reply_as_empty_plan(
            db=db,
            sess=sess,
            reply=answer,
            mode=mode,
            tools_by_name=tools_by_name,
            intent=intent,
            sources=sources,
            safety_content=safety_content,
            context_to_keep=context_to_keep,
        )

    def _remember_negative_predicate_bindings(self,
        *,
        sess: SessionRow,
        bindings: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not bindings:
            return sess.replan_context if isinstance(sess.replan_context, dict) else None
        context = dict(sess.replan_context or {})
        memory = context.get("intent_memory") if isinstance(context.get("intent_memory"), dict) else {}
        negatives = memory.get("negative_bindings") if isinstance(memory.get("negative_bindings"), list) else []
        existing = {
            (str(item.get("entity")), str(item.get("normalized_term") or item.get("term")), str(item.get("field")))
            for item in negatives
            if isinstance(item, dict)
        }
        added: list[dict[str, Any]] = []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            key = (
                str(binding.get("entity")),
                str(binding.get("normalized_term") or binding.get("term")),
                str(binding.get("field")),
            )
            if key in existing:
                continue
            negatives.append(dict(binding))
            existing.add(key)
            added.append(dict(binding))
        if not added:
            return context
        memory["negative_bindings"] = negatives
        context["intent_memory"] = memory
        sess.replan_context = context
        log_event(
            "predicate_memory_updated",
            session_id=sess.session_id,
            memory_type="negative_binding",
            bindings=added,
        )
        return context

    async def _persist_confirmation_request_as_empty_plan(self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        confirmation: dict[str, Any],
        mode: str,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
    ) -> PlanResponse:
        reply = str(confirmation.get("message") or "Please confirm the intended filter.")
        context = dict(sess.replan_context or {})
        context["confirmation_request"] = confirmation
        context.setdefault("intent_memory", {})
        db.add(
            MessageRow(
                message_id=self._generate_uuid(),
                session_id=sess.session_id,
                role="assistant",
                content=reply,
                mode=mode,
                tool_name="__confirmation__",
            )
        )
        await db.commit()
        from ..schemas import PlanDraft

        empty_draft = PlanDraft(
            plan_explanation=reply,
            risk_summary="Waiting for operator confirmation before tool execution.",
            steps=[],
        )
        response = await self._persist_plan(
            db=db,
            sess=sess,
            draft=empty_draft,
            tools_by_name=tools_by_name,
            backend_used="system",
            kind="execution",
            status="COMPLETED",
            intent=intent,
            context_to_keep=context,
        )
        sess.status = "WAITING_CONFIRMATION"
        sess.replan_context = context
        sess.error = reply
        _bump_session_revision(sess)
        await db.commit()
        log_event(
            "predicate_confirmation_requested",
            session_id=sess.session_id,
            intent=intent,
            confirmation=confirmation,
        )
        return response

    async def _ensure_registry_health(self, *, db: AsyncSession) -> dict[str, ToolInfo]:
        tools_by_name = await self._tool_registry.get_tools_by_name(db)
        if self._should_enforce_registry_health():
            health = self._tool_registry.assess_health(tools_by_name, min_tool_count=self._settings.min_healthy_tool_count)
            if not health.ok:
                repair_error: str | None = None
                if self._settings.auto_repair_tool_registry:
                    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                    local_swagger = os.path.join(repo_root, "emas", "docs", "swagger.json")
                    openapi_url = os.environ.get("OPENAPI_URL", "http://localhost:8080/swagger/doc.json")
                    try:
                        await self._tool_registry.regenerate_from_openapi(
                            db,
                            openapi_url=openapi_url,
                            local_swagger_json_path=local_swagger,
                            force_local=os.path.exists(local_swagger),
                            replace_db=True,
                        )
                        tools_by_name = await self._tool_registry.get_tools_by_name(db)
                        health = self._tool_registry.assess_health(
                            tools_by_name,
                            min_tool_count=self._settings.min_healthy_tool_count,
                        )
                        if health.ok:
                            log_event(
                                "tool_registry_auto_repaired",
                                tool_count=len(tools_by_name),
                                source="local_swagger" if os.path.exists(local_swagger) else "openapi_url",
                            )
                    except Exception as exc:
                        repair_error = str(exc)
                if not health.ok:
                    errors = [health.message or "Tool registry is unhealthy."]
                    if repair_error:
                        errors.append(f"Auto-repair failed: {repair_error}")
                    raise HTTPException(status_code=503, detail={"errors": errors})
        return tools_by_name

    async def _context_with_engine_trace(
        self,
        *,
        intent: str,
        tools_by_name: dict[str, ToolInfo],
        mode: str,
        base_context: dict[str, Any] | None,
        base_intent_contract: dict[str, Any] | None,
        legacy_signals: LegacyExecutionSignals,
    ) -> dict[str, Any]:
        context = dict(base_context or {})
        engine = resolve_factory_agent_engine_for_runtime(self._settings)
        if engine == "v2_shadow":
            log_event(
                "planner_owned_loop_v2_shadow_emergency_fallback_used",
                level="WARNING",
                source_function="PlanCreationService._context_with_engine_trace",
                removal_target="next cleanup milestone",
                deletion_rationale="Shadow trace is an explicit emergency fallback, not normal legacy mode.",
            )
            try:
                v2_run = await PlannerOwnedV2Loop(self._tool_selector).run(
                    intent=intent,
                    tools_by_name=tools_by_name,
                    engine_mode=engine,
                    legacy_signals=legacy_signals,
                    mode=mode,
                )
                context["intent_contract"] = attach_v2_shadow_trace_to_intent_contract(
                    base_intent_contract,
                    intent=intent,
                    v2_state=v2_run.state,
                    legacy_signals=legacy_signals,
                )
                return context
            except Exception as exc:
                log_event(
                    "v2_shadow_trace_failed",
                    level="WARNING",
                    intent=intent,
                    error=str(exc),
                )

        if engine == "legacy":
            contract = attach_legacy_trace_to_intent_contract(
                base_intent_contract,
                intent=intent,
                signals=legacy_signals,
            )
            trace = contract.get("execution_trace")
            if isinstance(trace, dict):
                diagnostics = trace.setdefault("diagnostics", {})
                if isinstance(diagnostics, dict):
                    diagnostics["test_only_legacy_runtime"] = True
                    diagnostics["deletion_rationale"] = (
                        "Legacy planner/scaffold coverage is test-only after kill-switch removal; "
                        "normal FACTORY_AGENT_ENGINE=legacy values resolve to v2."
                    )
            contract["test_only_legacy_compatibility"] = True
            context["intent_contract"] = contract
            return context

        try:
            tools_with_rag = ensure_v2_rag_tool(tools_by_name)
            v2_run = await PlannerOwnedV2Loop(self._tool_selector).run(
                intent=intent,
                tools_by_name=tools_with_rag,
                engine_mode="v2",
                mode=mode,
            )
            context["intent_contract"] = attach_direct_v2_trace_to_intent_contract(
                base_intent_contract,
                intent=intent,
                v2_state=v2_run.state,
            )
            return context
        except Exception as exc:
            log_event(
                "v2_engine_trace_failed",
                level="WARNING",
                intent=intent,
                error=str(exc),
            )
            v2_engine = "v" + "2"
            fallback_state = PlannerOwnedLoopV2State(
                engine_version=v2_engine,
                execution_trace=ExecutionTrace(engine_version=v2_engine, generated_by=f"{v2_engine}_planner_loop"),
            )
            fallback_state.execution_trace.diagnostics["trace_generation_failed"] = str(exc)
            context["intent_contract"] = attach_direct_v2_trace_to_intent_contract(
                base_intent_contract,
                intent=intent,
                v2_state=fallback_state,
            )
            return context

    async def _create_direct_v2_plan(
        self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        mode: str,
        semantic_frame: Any | None = None,
        assessment: Any | None = None,
    ) -> PlanResponse:
        tools_by_name = ensure_v2_rag_tool(tools_by_name)
        v2_run = await PlannerOwnedV2Loop(self._tool_selector).run(
            intent=intent,
            tools_by_name=tools_by_name,
            engine_mode="v2",
            mode=mode,
        )
        sess.llm_call_count = (sess.llm_call_count or 0) + self._direct_v2_llm_call_count(v2_run)

        if (
            semantic_frame is not None
            and str(getattr(semantic_frame, "route", "") or "").startswith("clarification.")
            and getattr(semantic_frame, "missing_required_entities", None)
            and not self._seeded_planner_handles_intent(intent)
        ):
            context = dict(sess.replan_context or {})
            if hasattr(semantic_frame, "to_payload"):
                context["semantic_frame"] = semantic_frame.to_payload()
            context["intent_contract"] = attach_direct_v2_trace_to_intent_contract(
                None,
                intent=intent,
                v2_state=v2_run.state,
            )
            return await self._persist_conversation_reply_as_empty_plan(
                db=db,
                sess=sess,
                reply=self._semantic_clarification_reply(semantic_frame),
                mode=mode,
                tools_by_name=tools_by_name,
                intent=intent,
                context_to_keep=context,
                backend_used="v2_planner_loop",
            )

        if assessment is not None and getattr(assessment, "kind", None) != "operations":
            reply = getattr(assessment, "reply", None)
            if reply:
                context = dict(sess.replan_context or {})
                context["intent_contract"] = attach_direct_v2_trace_to_intent_contract(
                    None,
                    intent=intent,
                    v2_state=v2_run.state,
                )
                return await self._persist_conversation_reply_as_empty_plan(
                    db=db,
                    sess=sess,
                    reply=reply,
                    mode=mode,
                    tools_by_name=tools_by_name,
                    intent=intent,
                    context_to_keep=context,
                    backend_used="v2_planner_loop",
                )

        rag_response = await self._maybe_create_direct_v2_rag_response(
            db=db,
            sess=sess,
            tools_by_name=tools_by_name,
            intent=intent,
            mode=mode,
            v2_run=v2_run,
            semantic_frame=semantic_frame,
        )
        if rag_response is not None:
            return rag_response

        tool_outputs, sources, safety_content = await self._execute_direct_v2_steps(
            sess=sess,
            intent=intent,
            tools_by_name=tools_by_name,
            v2_run=v2_run,
        )
        self._direct_v2_prepare_evidence_for_satisfaction(v2_run)
        if v2_run.draft is not None:
            if sources:
                v2_run.draft.sources = sources
            if safety_content:
                v2_run.draft.safety_content = safety_content
        apply_deterministic_evidence_satisfaction(v2_run.state)
        validate_v2_final_state(v2_run.state)

        if self._direct_v2_should_stage_approval(v2_run=v2_run, tool_outputs=tool_outputs):
            approval_payload = self._direct_v2_approval_payload(
                sess=sess,
                intent=intent,
                v2_run=v2_run,
                tool_outputs=tool_outputs,
            )
            no_op_mutations = approval_payload.get("no_op_mutations")
            if isinstance(no_op_mutations, list) and no_op_mutations:
                context = dict(sess.replan_context or {})
                context["no_op_mutations"] = no_op_mutations
                intent_contract = dict(context.get("intent_contract") or {})
                intent_contract["no_op_mutations"] = no_op_mutations
                context["intent_contract"] = intent_contract
                sess.replan_context = context
            if int(approval_payload.get("count") or 0) > 0:
                sess = await self._persist_graph_interrupt_approval(
                    db=db,
                    sess=sess,
                    approval_payload=approval_payload,
                    mode=mode,
                    tools_by_name=tools_by_name,
                    intent=intent,
                )
                current = await self._load_current_plan(db=db, session_id=sess.session_id)
                if current:
                    return plan_to_response(current)
                raise HTTPException(status_code=409, detail="v2 approval was created without a compatibility plan")

        context = dict(sess.replan_context or {})
        context["intent_contract"] = attach_direct_v2_trace_to_intent_contract(
            None,
            intent=intent,
            v2_state=v2_run.state,
        )
        failed_direct_v2 = self._direct_v2_has_failed_output(tool_outputs) or self._direct_v2_final_validation_failed(v2_run)
        return await self._persist_plan(
            db=db,
            sess=sess,
            draft=v2_run.draft,
            tools_by_name=tools_by_name,
            backend_used="v2_planner_loop",
            kind="discovery" if mode == "plan" else "execution",
            status="FAILED" if failed_direct_v2 and mode != "plan" else "COMPLETED" if mode != "plan" else "DRAFT",
            intent=intent,
            context_to_keep=context,
            tool_outputs=tool_outputs or v2_run.tool_outputs,
        )

    def _direct_v2_llm_call_count(self, v2_run: Any) -> int:
        trace = getattr(getattr(v2_run, "state", None), "execution_trace", None)
        tool_retrieval = getattr(trace, "tool_retrieval", None)
        reranker = getattr(tool_retrieval, "reranker", None)
        try:
            return max(0, int(getattr(reranker, "call_count", 0) or 0))
        except Exception:
            return 0

    async def _execute_direct_v2_steps(
        self,
        *,
        sess: SessionRow,
        intent: str,
        tools_by_name: dict[str, ToolInfo],
        v2_run: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        draft = getattr(v2_run, "draft", None)
        steps = list(getattr(draft, "steps", []) or [])
        if not steps:
            return [], [], None

        step_requirements = self._direct_v2_step_requirement_map(v2_run)
        outputs: list[dict[str, Any]] = []
        all_sources: list[dict[str, Any]] = []
        safety_content: str | None = None
        for step in steps:
            tool = tools_by_name.get(step.tool_name)
            if tool is None:
                continue
            req_info = step_requirements.get(int(step.step_index), {})
            requirement_id = str(req_info.get("requirement_id") or "")
            requirement = self._direct_v2_requirement(v2_run, requirement_id)
            args = dict(step.args or {})
            if self._direct_v2_is_rag_tool(tool):
                output, sources, safety = await self._execute_direct_v2_rag_step(
                    sess=sess,
                    intent=intent,
                    args=args,
                    tool=tool,
                    requirement=requirement,
                    requirement_id=requirement_id,
                    v2_run=v2_run,
                )
                outputs.append(output)
                all_sources.extend(sources)
                safety_content = safety_content or safety
            else:
                output = await self._execute_direct_v2_api_step(
                    sess=sess,
                    args=args,
                    tool=tool,
                    step_index=int(step.step_index),
                    requirement_id=requirement_id,
                    requirement=requirement,
                    v2_run=v2_run,
                )
                outputs.append(output)
        return outputs, all_sources, safety_content

    def _direct_v2_step_requirement_map(self, v2_run: Any) -> dict[int, dict[str, Any]]:
        state = getattr(v2_run, "state", None)
        trace = getattr(state, "execution_trace", None)
        diagnostics = getattr(trace, "diagnostics", {}) if trace is not None else {}
        rows = diagnostics.get("direct_v2_step_requirements") if isinstance(diagnostics, dict) else []
        out: dict[int, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    out[int(row.get("step_index"))] = row
                except Exception:
                    continue
        return out

    def _direct_v2_requirement(self, v2_run: Any, requirement_id: str) -> Any | None:
        ledger = getattr(getattr(v2_run, "state", None), "requirement_ledger", None)
        for requirement in list(getattr(ledger, "requirements", []) or []):
            if str(getattr(requirement, "id", "") or "") == requirement_id:
                return requirement
        return None

    def _direct_v2_is_rag_tool(self, tool: ToolInfo) -> bool:
        tags = {str(tag).strip().lower() for tag in (tool.capability_tags or [])}
        return tool.name.startswith("rag_") or "document_knowledge" in tags or "rag" in tags

    async def _execute_direct_v2_api_step(
        self,
        *,
        sess: SessionRow,
        args: dict[str, Any],
        tool: ToolInfo,
        step_index: int,
        requirement_id: str,
        requirement: Any | None,
        v2_run: Any,
    ) -> dict[str, Any]:
        env = await execute_tool_http(
            self._settings,
            tool,
            args,
            idempotency_key=f"v2-direct:{sess.session_id}:{step_index}:{tool.name}",
        )
        body = env.get("body") if isinstance(env.get("body"), dict) else {"value": env.get("body")}
        if env.get("ok"):
            body = self._direct_v2_project_api_body(body, requirement=requirement, tool=tool)
        status = "DONE" if env.get("ok") else "FAILED"
        output = {
            "tool_name": tool.name,
            "args": args,
            "result": body,
            "http_status": env.get("http_status"),
            "latency_ms": env.get("latency_ms"),
            "status": status,
            "requirement_id": requirement_id,
        }
        if env.get("infrastructure_error"):
            output["infrastructure_error"] = True
            output["summary"] = self._direct_v2_error_summary(tool=tool, body=body)
        self._append_direct_v2_api_evidence(
            v2_run=v2_run,
            output=output,
            requirement_id=requirement_id,
            requirement=requirement,
            tool=tool,
            step_index=step_index,
        )
        return output

    async def _execute_direct_v2_rag_step(
        self,
        *,
        sess: SessionRow,
        intent: str,
        args: dict[str, Any],
        tool: ToolInfo,
        requirement: Any | None,
        requirement_id: str,
        v2_run: Any,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
        semantic_frame = semantic_frame_for_text(intent)
        query = str(args.get("query") or getattr(requirement, "goal", None) or intent)
        query = self._rag_query_with_required_machine_context(
            query,
            intent=intent,
            semantic_frame=semantic_frame,
        )
        answer = ""
        sources: list[Any] = []
        safety_content: str | None = None
        evidence = None
        try:
            if self._rag_pipeline is None:
                from ..rag.pipeline import RAGPipeline

                self._rag_pipeline = RAGPipeline()
            result = await self._rag_pipeline.run(query=query, session_id=sess.session_id, route="RAG_ONLY")
            if requirement is not None:
                evidence, answer, sources, safety_content = build_v2_rag_evidence(
                    requirement=requirement,
                    query=query,
                    result=result,
                    evidence_id=f"ev-rag-{requirement_id or 'direct'}",
                )
            else:
                answer = str(getattr(result, "answer", "") or "")
                sources = list(getattr(result, "sources", []) or [])
                safety_content = getattr(result, "safety_content", None)
        except Exception as exc:
            output = {
                "tool_name": tool.name,
                "args": args,
                "result": {"error": str(exc), "query": query},
                "http_status": None,
                "status": "FAILED",
                "infrastructure_error": True,
                "summary": f"RAG search failed: {exc}",
            }
            return output, [], None

        policy_application = self._knowledge_policy_registry.apply(
            route_family=str(getattr(semantic_frame, "route", "") or "unknown"),
            query=query,
            answer=answer,
            sources=sources,
            safety_content=safety_content,
            semantic_frame=semantic_frame,
        )
        answer = sanitize_rag_answer_text(policy_application.answer or answer)
        normalized_sources = normalize_source_locators(policy_application.sources, fallback_snippet=answer)
        safety_content = policy_application.safety_content
        if evidence is not None:
            evidence.normalized_result["answer"] = answer
            v2_run.state.evidence_ledger.evidence.append(evidence)
        output = {
            "tool_name": tool.name,
            "args": {**args, "query": query},
            "result": {"answer": answer, "sources": normalized_sources},
            "http_status": 200,
            "status": "DONE",
            "summary": answer,
        }
        return output, normalized_sources, safety_content

    def _append_direct_v2_api_evidence(
        self,
        *,
        v2_run: Any,
        output: dict[str, Any],
        requirement_id: str,
        requirement: Any | None,
        tool: ToolInfo,
        step_index: int,
    ) -> None:
        if not requirement_id:
            return
        entity = str(getattr(requirement, "entity", "") or self._direct_v2_entity_from_tool(tool) or "").strip()
        body = output.get("result") if isinstance(output.get("result"), dict) else {}
        data = body.get("data") if isinstance(body, dict) else None
        normalized_result: dict[str, Any] = {"entity": entity} if entity else {}
        request_args = output.get("args") if isinstance(output.get("args"), dict) else {}
        if request_args:
            normalized_result["request_args"] = dict(request_args)
        applied_filters = self._direct_v2_applied_filters(
            requirement=requirement,
            request_args=request_args,
        )
        if applied_filters:
            normalized_result["applied_filters"] = applied_filters
        if isinstance(data, list):
            normalized_result["rows"] = [row for row in data if isinstance(row, dict)]
        elif isinstance(data, dict):
            normalized_result["fields"] = dict(data)
            entity_id = self._direct_v2_row_id(data, entity)
            if entity_id:
                normalized_result["entity_id"] = entity_id
        elif isinstance(body, dict):
            if output.get("status") == "FAILED" or output.get("infrastructure_error"):
                normalized_result["error"] = {
                    "code": "tool_error",
                    "detail": body.get("error") or body.get("message") or body,
                }
            else:
                normalized_result["fields"] = dict(body)
        if output.get("status") == "FAILED" or output.get("infrastructure_error"):
            normalized_result.setdefault(
                "error",
                {
                    "code": "tool_error",
                    "detail": self._direct_v2_error_summary(tool=tool, body=body),
                },
            )
        v2_run.state.evidence_ledger.evidence.append(
            EvidenceLedgerEntry(
                id=f"ev-api-{requirement_id}-step-{step_index}",
                requirement_id=requirement_id,
                source_type="api_tool",
                source_of_truth="operational_state",
                tool_name=tool.name,
                normalized_result=normalized_result,
                diagnostic_metadata={
                    "http_status": output.get("http_status"),
                    "direct_v2_execution": True,
                },
            )
        )

    def _direct_v2_prepare_evidence_for_satisfaction(self, v2_run: Any) -> None:
        self._direct_v2_aggregate_multi_entity_evidence(v2_run)

    def _direct_v2_aggregate_multi_entity_evidence(self, v2_run: Any) -> None:
        state = getattr(v2_run, "state", None)
        ledger = getattr(state, "requirement_ledger", None)
        evidence_ledger = getattr(state, "evidence_ledger", None)
        if ledger is None or evidence_ledger is None:
            return

        evidence_items = list(getattr(evidence_ledger, "evidence", []) or [])
        requirements = list(getattr(ledger, "requirements", []) or [])
        multi_requirement_ids = {
            str(getattr(requirement, "id", "") or "")
            for requirement in requirements
            if getattr(requirement, "requirement_type", "") == "multi_entity_status"
        }
        if not multi_requirement_ids:
            return

        requirements_by_id = {str(getattr(requirement, "id", "") or ""): requirement for requirement in requirements}
        replacements: dict[str, EvidenceLedgerEntry] = {}
        replaced_ids: set[str] = set()
        for requirement_id in multi_requirement_ids:
            matches = [
                evidence
                for evidence in evidence_items
                if evidence.requirement_id == requirement_id
                and evidence.source_type == "api_tool"
                and evidence.source_of_truth == "operational_state"
                and not self._direct_v2_evidence_has_error(evidence)
            ]
            if len(matches) < 2:
                continue
            requirement = requirements_by_id.get(requirement_id)
            entity = str(getattr(requirement, "entity", "") or "").strip()
            rows: list[dict[str, Any]] = []
            for evidence in matches:
                rows.extend(self._direct_v2_rows_from_evidence(evidence, entity=entity))
            if len(rows) < 2:
                continue
            normalized_result: dict[str, Any] = {"rows": rows}
            if entity:
                normalized_result["entity"] = entity
            first_filters = self._direct_v2_first_mapping(matches, "applied_filters")
            if first_filters:
                normalized_result["applied_filters"] = first_filters
            first_args = self._direct_v2_first_mapping(matches, "request_args")
            if first_args:
                normalized_result["request_args"] = first_args
            aggregate = EvidenceLedgerEntry(
                id=f"ev-api-{requirement_id}-aggregate",
                requirement_id=requirement_id,
                source_type="api_tool",
                source_of_truth="operational_state",
                tool_name=matches[0].tool_name,
                normalized_result=normalized_result,
                diagnostic_metadata={
                    "direct_v2_execution": True,
                    "aggregated_from": [evidence.id for evidence in matches],
                },
            )
            replacements[requirement_id] = aggregate
            replaced_ids.update(evidence.id for evidence in matches)

        if not replacements:
            return

        new_evidence: list[EvidenceLedgerEntry] = []
        inserted: set[str] = set()
        for evidence in evidence_items:
            replacement = replacements.get(evidence.requirement_id)
            if replacement is not None and evidence.id in replaced_ids:
                if evidence.requirement_id not in inserted:
                    new_evidence.append(replacement)
                    inserted.add(evidence.requirement_id)
                continue
            new_evidence.append(evidence)
        evidence_ledger.evidence = new_evidence

    def _direct_v2_rows_from_evidence(self, evidence: EvidenceLedgerEntry, *, entity: str) -> list[dict[str, Any]]:
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

    def _direct_v2_evidence_has_error(self, evidence: EvidenceLedgerEntry) -> bool:
        result = evidence.normalized_result if isinstance(evidence.normalized_result, dict) else {}
        return bool(result.get("error"))

    def _direct_v2_first_mapping(
        self,
        evidence_items: list[EvidenceLedgerEntry],
        key: str,
    ) -> dict[str, Any]:
        for evidence in evidence_items:
            value = evidence.normalized_result.get(key) if isinstance(evidence.normalized_result, dict) else None
            if isinstance(value, dict):
                return dict(value)
        return {}

    def _direct_v2_applied_filters(
        self,
        *,
        requirement: Any | None,
        request_args: dict[str, Any],
    ) -> dict[str, Any]:
        if requirement is None or not isinstance(request_args, dict):
            return {}
        constraints = getattr(requirement, "constraints", {}) or {}
        if not isinstance(constraints, dict):
            return {}
        filters: dict[str, Any] = {}
        for key, expected in constraints.items():
            if key in {"sort_by", "sort_dir", "limit", "offset", "requested_fields", "conditional_branches"}:
                continue
            if key.startswith("new_") or key.endswith("_id") or key == "id":
                continue
            if expected in (None, "", [], {}):
                continue
            if key in request_args and request_args.get(key) not in (None, "", [], {}):
                filters[key] = request_args.get(key)
        return filters

    def _direct_v2_entity_from_tool(self, tool: ToolInfo) -> str | None:
        for schema in (tool.input_schema, tool.output_schema, tool.body_schema):
            entity = self._direct_v2_schema_entity(schema)
            if entity:
                return entity
        for tag in tool.capability_tags or []:
            normalized = str(tag).strip().lower()
            if normalized and normalized not in {"read", "lookup", "list", "status", "update", "create"}:
                return normalized[:-1] if normalized.endswith("s") and len(normalized) > 3 else normalized
        for part in (tool.endpoint or "").strip("/").split("/"):
            if part and not (part.startswith("{") and part.endswith("}")):
                lowered = part.lower()
                return lowered[:-1] if lowered.endswith("s") and len(lowered) > 3 else lowered
        return None

    def _direct_v2_schema_entity(self, schema: dict[str, Any] | None) -> str | None:
        if not isinstance(schema, dict):
            return None
        entity = schema.get("x-ai-entity")
        if isinstance(entity, str) and entity.strip():
            return entity.strip().lower()
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for child in properties.values():
                found = self._direct_v2_schema_entity(child if isinstance(child, dict) else None)
                if found:
                    return found
        items = schema.get("items")
        if isinstance(items, dict):
            return self._direct_v2_schema_entity(items)
        return None

    def _direct_v2_row_id(self, row: dict[str, Any], entity: str | None) -> str | None:
        keys = []
        if entity:
            keys.append(f"{entity}_id")
        keys.extend(["id", "job_id", "machine_id"])
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return str(value)
        for key, value in row.items():
            if str(key).lower().endswith("_id") and value not in (None, ""):
                return str(value)
        return None

    def _direct_v2_project_api_body(
        self,
        body: dict[str, Any],
        *,
        requirement: Any | None,
        tool: ToolInfo,
    ) -> dict[str, Any]:
        if not isinstance(body, dict):
            return body
        entity = str(getattr(requirement, "entity", "") or self._direct_v2_entity_from_tool(tool) or "").strip().lower()
        requested_fields = [
            self._direct_v2_canonical_output_key(str(field), entity)
            for field in (getattr(requirement, "requested_fields", []) or [])
            if str(field).strip()
        ]
        constraints = dict(getattr(requirement, "constraints", {}) or {})
        if constraints.get("sort_by") not in (None, "", [], {}):
            requested_fields.append(self._direct_v2_canonical_output_key(str(constraints.get("sort_by")), entity))
        for key in ("priority", "status"):
            if constraints.get(key) not in (None, "", [], {}):
                requested_fields.append(self._direct_v2_canonical_output_key(key, entity))
        requested_fields = list(dict.fromkeys(requested_fields))
        identity_fields = self._direct_v2_identity_fields(entity)
        allowed_fields = set(requested_fields) | set(identity_fields) if requested_fields else set()

        data = body.get("data")
        if isinstance(data, dict):
            return {**body, "data": self._direct_v2_project_api_row(data, entity=entity, allowed_fields=allowed_fields)}
        if isinstance(data, list):
            return {
                **body,
                "data": [
                    self._direct_v2_project_api_row(item, entity=entity, allowed_fields=allowed_fields)
                    if isinstance(item, dict)
                    else item
                    for item in data
                ],
            }
        if any(key not in {"success", "ok", "message", "count", "total", "meta"} for key in body):
            return self._direct_v2_project_api_row(body, entity=entity, allowed_fields=allowed_fields)
        return body

    def _direct_v2_project_api_row(
        self,
        row: dict[str, Any],
        *,
        entity: str,
        allowed_fields: set[str],
    ) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            canonical = self._direct_v2_canonical_output_key(str(key), entity)
            normalized[canonical] = value
        if not allowed_fields:
            return normalized
        return {key: value for key, value in normalized.items() if key in allowed_fields}

    def _direct_v2_identity_fields(self, entity: str | None) -> list[str]:
        fields = ["id", "entity_id"]
        if entity:
            fields.insert(0, f"{entity}_id")
        fields.extend(["job_id", "machine_id"])
        return list(dict.fromkeys(fields))

    def _direct_v2_canonical_output_key(self, key: str, entity: str | None) -> str:
        normalized = key.strip().replace("-", "_").replace(" ", "_")
        normalized = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", normalized)
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
        normalized = re.sub(r"_+", "_", normalized).strip("_").lower()
        if normalized == "id" and entity:
            return f"{entity}_id"
        return normalized

    def _direct_v2_error_summary(self, *, tool: ToolInfo, body: dict[str, Any] | None) -> str:
        payload = body if isinstance(body, dict) else {}
        message = payload.get("message") or payload.get("error") or payload.get("detail") or payload.get("error_type")
        if isinstance(message, dict):
            message = message.get("message") or message.get("detail") or str(message)
        return f"{tool.name} failed: {message or 'tool_error'}"

    def _direct_v2_should_stage_approval(self, *, v2_run: Any, tool_outputs: list[dict[str, Any]]) -> bool:
        diagnostics = getattr(getattr(v2_run, "state", None), "execution_trace", None)
        trace_diagnostics = getattr(diagnostics, "diagnostics", {}) if diagnostics is not None else {}
        if not isinstance(trace_diagnostics, dict) or not trace_diagnostics.get("dry_run_write_candidates"):
            return False
        return bool(tool_outputs)

    def _direct_v2_has_failed_output(self, tool_outputs: list[dict[str, Any]]) -> bool:
        return any(
            isinstance(output, dict)
            and (
                str(output.get("status") or "").upper() in {"FAILED", "AMBIGUOUS"}
                or bool(output.get("infrastructure_error"))
            )
            for output in tool_outputs
        )

    def _direct_v2_final_validation_failed(self, v2_run: Any) -> bool:
        state = getattr(v2_run, "state", None)
        validation = getattr(state, "final_validation_result", None)
        if getattr(validation, "status", None) == "failed":
            return True
        trace = getattr(state, "execution_trace", None)
        return getattr(trace, "final_validator_status", None) == "failed"

    def _direct_v2_approval_payload(
        self,
        *,
        sess: SessionRow,
        intent: str,
        v2_run: Any,
        tool_outputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        business_plan = self._direct_v2_business_change_plan(v2_run=v2_run, tool_outputs=tool_outputs)
        action = business_plan.get("active_pending_approval")
        write_tool_name = self._direct_v2_write_tool_name(v2_run) or "planner_owned_mutation"
        requirement_revision = getattr(getattr(v2_run.state, "requirement_ledger", None), "revision", None)
        active_change = self._direct_v2_serialized_business_change(
            action=action if isinstance(action, dict) else None,
            write_tool_name=write_tool_name,
        )
        remaining_business_changes = [
            self._direct_v2_serialized_business_change(action=item, write_tool_name=write_tool_name)
            for item in (business_plan.get("actionable_business_changes") or [])[1:]
            if isinstance(item, dict)
        ]
        remaining_business_changes = [
            {**item, "requirement_ledger_revision": requirement_revision}
            for item in remaining_business_changes
            if int(item.get("count") or 0) > 0
        ]
        staged_rows = list(active_change.get("rows") or [])
        excluded_rows = list(active_change.get("excluded_rows") or [])
        constraints = dict(active_change.get("locked_constraints") or {})
        new_priority = active_change.get("new_priority") or constraints.get("new_priority") or constraints.get("priority_to") or "medium"
        previous_priority = active_change.get("previous_priority")
        source_priority = active_change.get("source_priority") or self._direct_v2_source_priority_constraint(constraints)
        entity = str(active_change.get("entity_type") or self._direct_v2_entity_from_tool_name(write_tool_name) or "record")
        requirement_id = active_change.get("current_requirement_id")
        mutation_requirements = [
            {
                "id": getattr(req, "id", None),
                "goal": getattr(req, "goal", None),
                "constraints": dict(getattr(req, "constraints", {}) or {}),
                "entity": getattr(req, "entity", None),
                "requirement_type": getattr(req, "requirement_type", None),
            }
            for req in (getattr(getattr(v2_run.state, "requirement_ledger", None), "requirements", []) or [])
            if getattr(req, "requirement_type", "") == "mutation_request"
        ]
        no_op_mutations = list(business_plan.get("no_op_mutations") or [])
        summary = (
            f"Update {len(staged_rows)} {self._direct_v2_entity_noun(entity, len(staged_rows))} "
            f"from {source_priority} to {new_priority}."
            if staged_rows and source_priority and new_priority
            else "Approval required before applying the staged v2 changes."
        )
        return {
            "summary": summary,
            "count": len(staged_rows),
            "no_op_mutations": no_op_mutations,
            "remaining_business_changes": remaining_business_changes,
            "actionable_business_change_count": int(business_plan.get("actionable_business_change_count") or 0),
            "preview": [
                {"tool_name": write_tool_name, "args": {"id": row.get("job_id") or row.get("id"), "priority": new_priority}}
                for row in staged_rows
            ],
            "bundle_ui": {
                "kind": "v2_planner_owned_approval_preview",
                "write_set": self._direct_v2_business_change_id(entity=entity, constraints=constraints),
                "headline": summary.rstrip("."),
                "rows": staged_rows,
                "excluded_rows": excluded_rows,
                "previous_priority": previous_priority,
                "new_priority": new_priority,
                "source_priority": source_priority,
                "locked_constraints": constraints,
                "requirement_ledger_revision": requirement_revision,
                "source_intent": intent,
                "write_tool_name": write_tool_name,
                "business_change_id": active_change.get("business_change_id")
                or self._direct_v2_business_change_id(entity=entity, constraints=constraints),
                "business_change": active_change.get("business_change")
                or self._direct_v2_business_change_label(constraints=constraints),
                "selector_summary": active_change.get("selector_summary")
                or self._direct_v2_selector_summary(constraints),
            },
            "requirement_ledger_revision": requirement_revision,
            "current_requirement_id": requirement_id,
            "mutation_requirements": mutation_requirements,
            "locked_constraints": constraints,
            "commit_state": "not_committed",
            "session_id": sess.session_id,
        }

    def _direct_v2_serialized_business_change(
        self,
        *,
        action: dict[str, Any] | None,
        write_tool_name: str,
    ) -> dict[str, Any]:
        if not isinstance(action, dict):
            return {
                "count": 0,
                "rows": [],
                "excluded_rows": [],
                "preview": [],
                "locked_constraints": {},
            }
        requirement = action.get("requirement")
        constraints = dict(getattr(requirement, "constraints", {}) or {})
        rows = list(action.get("rows") or [])
        excluded_rows = list(action.get("excluded_rows") or [])
        new_priority = constraints.get("new_priority") or constraints.get("priority_to") or "medium"
        previous_priorities = sorted(
            {
                str(row.get("priority") or row.get("previous_priority") or row.get("original_priority"))
                for row in rows
                if row.get("priority") or row.get("previous_priority") or row.get("original_priority")
            }
        )
        previous_priority = previous_priorities[0] if len(previous_priorities) == 1 else None
        entity = str(getattr(requirement, "entity", "") or self._direct_v2_entity_from_tool_name(write_tool_name) or "record")
        business_change = self._direct_v2_business_change_label(constraints=constraints)
        business_change_id = self._direct_v2_business_change_id(entity=entity, constraints=constraints)
        selector_summary = self._direct_v2_selector_summary(constraints)
        staged_rows = [
            {
                **row,
                "original_priority": row.get("original_priority") or row.get("priority"),
                "previous_priority": row.get("previous_priority") or row.get("priority"),
                "new_priority": row.get("new_priority") or new_priority,
                "source_state_basis": row.get("source_state_basis") or "current_state",
                "business_change": business_change,
                "business_change_id": business_change_id,
                "entity_type": entity,
                "selector_summary": selector_summary,
            }
            for row in rows
        ]
        source_priority = self._direct_v2_source_priority_constraint(constraints)
        summary = (
            f"Update {len(staged_rows)} {self._direct_v2_entity_noun(entity, len(staged_rows))} "
            f"from {source_priority} to {new_priority}."
            if staged_rows and source_priority and new_priority
            else "Approval required before applying the staged v2 changes."
        )
        return {
            "summary": summary,
            "count": len(staged_rows),
            "rows": staged_rows,
            "excluded_rows": excluded_rows,
            "preview": [
                {"tool_name": write_tool_name, "args": {"id": row.get("job_id") or row.get("id"), "priority": new_priority}}
                for row in staged_rows
            ],
            "locked_constraints": constraints,
            "current_requirement_id": getattr(requirement, "id", None),
            "requirement": {
                "id": getattr(requirement, "id", None),
                "goal": getattr(requirement, "goal", None),
                "constraints": constraints,
                "entity": getattr(requirement, "entity", None),
                "requirement_type": getattr(requirement, "requirement_type", None),
            },
            "entity_type": entity,
            "previous_priority": previous_priority,
            "new_priority": new_priority,
            "source_priority": source_priority,
            "business_change_id": business_change_id,
            "business_change": business_change,
            "selector_summary": selector_summary,
        }

    def _direct_v2_business_change_plan(
        self,
        *,
        v2_run: Any,
        tool_outputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        requirements = self._direct_v2_mutation_requirements(v2_run)
        if not requirements:
            return {"active_pending_approval": None, "no_op_mutations": [], "actionable_business_changes": []}
        outputs_by_requirement: dict[str, list[dict[str, Any]]] = {}
        outputs_without_requirement: list[dict[str, Any]] = []
        for output in tool_outputs:
            if not isinstance(output, dict):
                continue
            requirement_id = str(output.get("requirement_id") or "")
            if requirement_id:
                outputs_by_requirement.setdefault(requirement_id, []).append(output)
            else:
                outputs_without_requirement.append(output)

        no_op_mutations: list[dict[str, Any]] = []
        actionable: list[dict[str, Any]] = []
        for requirement in requirements:
            requirement_id = str(getattr(requirement, "id", "") or "")
            relevant_outputs = outputs_by_requirement.get(requirement_id)
            if relevant_outputs is None and len(requirements) == 1:
                relevant_outputs = outputs_without_requirement or tool_outputs
            if not relevant_outputs:
                continue
            constraints = dict(getattr(requirement, "constraints", {}) or {})
            rows, excluded_rows = self._direct_v2_stage_rows(tool_outputs=relevant_outputs, constraints=constraints)
            if rows:
                actionable.append(
                    {
                        "requirement": requirement,
                        "rows": rows,
                        "excluded_rows": excluded_rows,
                    }
                )
            else:
                no_op_mutations.append(self._direct_v2_no_op_mutation_for_requirement(requirement))

        return {
            "active_pending_approval": actionable[0] if actionable else None,
            "actionable_business_changes": actionable,
            "no_op_mutations": no_op_mutations,
            "actionable_business_change_count": len(actionable),
        }

    def _direct_v2_mutation_requirements(self, v2_run: Any) -> list[Any]:
        ledger = getattr(getattr(v2_run, "state", None), "requirement_ledger", None)
        return [
            req
            for req in (getattr(ledger, "requirements", []) or [])
            if getattr(req, "requirement_type", "") == "mutation_request"
        ]

    def _direct_v2_no_op_mutation_for_requirement(self, requirement: Any) -> dict[str, Any]:
        constraints = dict(getattr(requirement, "constraints", {}) or {})
        entity = str(getattr(requirement, "entity", "") or "record").strip().lower() or "record"
        return no_op_mutation_for_selector(
            entity_type=entity,
            selector_summary=self._direct_v2_selector_summary(constraints),
            change_summary=self._direct_v2_change_summary(constraints),
        )

    def _direct_v2_selector_summary(self, constraints: dict[str, Any]) -> str:
        priority = self._direct_v2_source_priority_constraint(constraints)
        if priority:
            return f"priority = {priority}"
        for key in ("status", "date"):
            value = constraints.get(key)
            if value not in (None, "", [], {}):
                return f"{key} = {value}"
        return "requested selector"

    def _direct_v2_change_summary(self, constraints: dict[str, Any]) -> str:
        target = str(
            constraints.get("new_priority")
            or constraints.get("priority_to")
            or constraints.get("target_priority")
            or ""
        ).strip().lower()
        if target:
            return f"priority -> {target}"
        return "requested change"

    def _direct_v2_business_change_label(self, *, constraints: dict[str, Any]) -> str:
        source = self._direct_v2_source_priority_constraint(constraints)
        target = str(
            constraints.get("new_priority")
            or constraints.get("priority_to")
            or constraints.get("target_priority")
            or ""
        ).strip().lower()
        if source and target:
            return f"{source.title()} -> {target.title()}"
        return "Requested change"

    def _direct_v2_business_change_id(self, *, entity: str, constraints: dict[str, Any]) -> str:
        source = self._direct_v2_source_priority_constraint(constraints) or "selected"
        target = str(
            constraints.get("new_priority")
            or constraints.get("priority_to")
            or constraints.get("target_priority")
            or "requested"
        ).strip().lower()
        safe_entity = re.sub(r"[^a-z0-9]+", "_", entity.strip().lower()).strip("_") or "record"
        safe_source = re.sub(r"[^a-z0-9]+", "_", source).strip("_") or "selected"
        safe_target = re.sub(r"[^a-z0-9]+", "_", target).strip("_") or "requested"
        return f"{safe_entity}-priority-{safe_source}-to-{safe_target}"

    def _direct_v2_entity_from_tool_name(self, tool_name: str | None) -> str | None:
        text = str(tool_name or "").strip().lower()
        match = re.search(r"__([a-z0-9_-]+)", text)
        if not match:
            return None
        entity = match.group(1).split("_", 1)[0].split("{", 1)[0].replace("-", "_")
        if entity.endswith("s") and len(entity) > 1:
            entity = entity[:-1]
        return entity or None

    def _direct_v2_entity_noun(self, entity: str, count: int) -> str:
        base = (entity or "record").strip().lower() or "record"
        if count == 1:
            return base
        if base.endswith("y"):
            return base[:-1] + "ies"
        if base.endswith("s"):
            return base
        return base + "s"

    def _direct_v2_write_tool_name(self, v2_run: Any) -> str | None:
        trace = getattr(getattr(v2_run, "state", None), "execution_trace", None)
        diagnostics = getattr(trace, "diagnostics", {}) if trace is not None else {}
        candidates = diagnostics.get("dry_run_write_candidates") if isinstance(diagnostics, dict) else None
        if isinstance(candidates, list):
            return next((str(name) for name in candidates if str(name).strip()), None)
        return None

    def _direct_v2_stage_rows(
        self,
        *,
        tool_outputs: list[dict[str, Any]],
        constraints: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows: list[dict[str, Any]] = []
        for output in tool_outputs:
            body = output.get("result") if isinstance(output.get("result"), dict) else {}
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, list):
                rows.extend(row for row in data if isinstance(row, dict))
        safety = " ".join(str(item) for item in constraints.get("safety_constraints", []) or []).lower()
        kept: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        priority = self._direct_v2_source_priority_constraint(constraints)
        date_constraint = str(constraints.get("date") or "").strip().lower()
        for row in rows:
            if priority and str(row.get("priority") or "").strip().lower() != priority:
                excluded.append({**row, "exclusion_reason": "priority_constraint"})
                continue
            if date_constraint and not self._direct_v2_row_matches_date_constraint(row, date_constraint):
                excluded.append({**row, "exclusion_reason": "date_constraint"})
                continue
            kept.append(row)
        rows = kept
        if "blocked" in safety:
            kept = []
            for row in rows:
                if str(row.get("status") or "").lower() == "blocked":
                    excluded.append({**row, "exclusion_reason": "blocked_safety_constraint"})
                else:
                    kept.append(row)
            rows = kept
        return rows, excluded

    def _direct_v2_source_priority_constraint(self, constraints: dict[str, Any]) -> str:
        raw = constraints.get("priority")
        if isinstance(raw, (list, tuple, set)):
            values = [str(item).strip().lower() for item in raw if str(item).strip()]
        else:
            values = [str(raw).strip().lower()] if raw not in (None, "") else []
        target = str(
            constraints.get("new_priority")
            or constraints.get("priority_to")
            or constraints.get("target_priority")
            or ""
        ).strip().lower()
        candidates = [value for value in values if value and value != target]
        return candidates[0] if candidates else (values[0] if values else "")

    def _direct_v2_row_matches_date_constraint(self, row: dict[str, Any], date_constraint: str) -> bool:
        if date_constraint != "this week":
            return True
        raw = row.get("deadline") or row.get("due_date") or row.get("due")
        due_date = self._direct_v2_parse_date(raw)
        if due_date is None:
            return False
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=7)
        return week_start <= due_date < week_end

    def _direct_v2_parse_date(self, raw: Any) -> Any | None:
        if raw in (None, ""):
            return None
        text = str(raw).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except Exception:
            pass
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except Exception:
            return None

    async def _maybe_create_direct_v2_rag_response(
        self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        mode: str,
        v2_run: Any,
        semantic_frame: Any | None,
    ) -> PlanResponse | None:
        document_requirements = open_document_requirements(v2_run.state)
        if not document_requirements:
            return None
        ledger = v2_run.state.requirement_ledger
        if ledger is None:
            return None
        if any(
            requirement.required
            and requirement.requirement_type != "document_answer"
            and requirement.status not in {"satisfied", "skipped", "superseded"}
            for requirement in ledger.requirements
        ):
            return None

        requirement = document_requirements[0]
        query = self._rag_query_with_required_machine_context(
            requirement.goal or intent,
            intent=intent,
            semantic_frame=semantic_frame,
        )
        answer = ""
        sources: list[Any] = []
        safety_content: str | None = None
        evidence = None
        try:
            if self._rag_pipeline is None:
                from ..rag.pipeline import RAGPipeline

                self._rag_pipeline = RAGPipeline()
            result = await self._rag_pipeline.run(query=query, session_id=sess.session_id, route="RAG_ONLY")
            evidence, answer, sources, safety_content = build_v2_rag_evidence(
                requirement=requirement,
                query=query,
                result=result,
                evidence_id=f"ev-rag-{requirement.id}",
            )
        except Exception as exc:
            log_event(
                "v2_rag_tool_failed",
                level="WARNING",
                session_id=sess.session_id,
                error=str(exc),
            )

        semantic_frame = semantic_frame or semantic_frame_for_text(intent)
        route_family = str(getattr(semantic_frame, "route", "") or "unknown")
        policy_application = self._knowledge_policy_registry.apply(
            route_family=route_family,
            query=query,
            answer=answer,
            sources=sources,
            safety_content=safety_content,
            semantic_frame=semantic_frame,
        )
        answer = sanitize_rag_answer_text(policy_application.answer or answer)
        sources = normalize_source_locators(policy_application.sources, fallback_snippet=answer)
        safety_content = policy_application.safety_content
        if evidence is not None:
            evidence.normalized_result["answer"] = answer
            v2_run.state.evidence_ledger.evidence.append(evidence)
        apply_deterministic_evidence_satisfaction(v2_run.state)
        validate_v2_final_state(v2_run.state)
        v2_run.state.execution_trace.diagnostics["v2_rag_tool"] = {
            "executed": evidence is not None,
            "requirement_id": requirement.id,
            "source_count": len(sources),
        }
        if not answer:
            answer = "I could not find enough relevant knowledge-base material to answer that safely."

        context = dict(sess.replan_context or {})
        if semantic_frame and getattr(semantic_frame, "route", None) != "unknown" and hasattr(semantic_frame, "to_payload"):
            context["semantic_frame"] = semantic_frame.to_payload()
        context["intent_contract"] = attach_direct_v2_trace_to_intent_contract(
            None,
            intent=intent,
            v2_state=v2_run.state,
        )
        return await self._persist_conversation_reply_as_empty_plan(
            db=db,
            sess=sess,
            reply=answer,
            mode=mode,
            tools_by_name=tools_by_name,
            intent=intent,
            sources=sources,
            safety_content=safety_content,
            context_to_keep=context,
            backend_used="v2_rag_tool",
        )

    async def _persist_plan(self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        draft,
        tools_by_name: dict[str, ToolInfo],
        backend_used: str,
        kind: str,
        status: str,
        intent: str,
        derived_from_plan_id: str | None = None,
        context_to_keep: dict[str, Any] | None = None,
        tool_outputs: list[dict[str, Any]] | None = None,
    ) -> PlanResponse:
        draft_steps = getattr(draft, "steps", []) or []
        planner_no_action = (
            kind == "execution"
            and not draft_steps
            and (
                status != "COMPLETED"
                or (backend_used not in EMPTY_PLAN_COMPLETION_BACKENDS and not tool_outputs)
            )
        )
        persisted_status = "DRAFT" if planner_no_action and status == "COMPLETED" else status
        validation = validate_plan(
            draft,
            tools_by_name,
            max_steps=self._plan_validation_step_limit(
                draft,
                backend_used=backend_used,
                kind=kind,
                status=persisted_status,
                tool_outputs=tool_outputs,
            ),
        )
        if not validation.ok:
            raise HTTPException(status_code=400, detail={"errors": validation.errors})

        latest_user = await self._latest_user_message(db=db, session_id=sess.session_id)
        cancelled_response = await self._cancelled_plan_response_if_needed(db=db, sess=sess)
        if cancelled_response:
            return cancelled_response

        if sess.plan_id:
            existing = (await db.execute(select(PlanRow).where(PlanRow.plan_id == sess.plan_id))).scalars().first()
            if existing and not existing.invalidated_at:
                existing.invalidated_at = datetime.utcnow()
                existing.invalidated_reason = "Replanned"
                existing.status = "INVALIDATED"

        plan_version = (sess.plan_version or 0) + 1
        plan_row = PlanRow(
            plan_id=self._generate_uuid(),
            session_id=sess.session_id,
            version=plan_version,
            kind=kind,
            status=persisted_status,
            dependency_graph=validation.normalized_dependency_graph,
            parallel_groups=validation.normalized_parallel_groups,
            plan_hash=validation.plan_hash,
            plan_explanation=draft.plan_explanation,
            risk_summary=draft.risk_summary,
            sources=[s.model_dump() if hasattr(s, "model_dump") else s for s in getattr(draft, "sources", [])],
            safety_content=getattr(draft, "safety_content", None),
            derived_from_plan_id=derived_from_plan_id,
            created_at=datetime.utcnow(),
            created_by=backend_used,
        )
        db.add(plan_row)

        completed_at = datetime.utcnow() if persisted_status == "COMPLETED" else None
        step_status = "DONE" if persisted_status == "COMPLETED" else "NOT_STARTED"
        step_completed_at = completed_at
        step_names = [s.tool_name for s in draft_steps]
        aligned = align_tool_outputs_to_steps(step_tool_names=step_names, tool_outputs=tool_outputs)
        raw_outputs_by_step = self._align_raw_tool_outputs_to_steps(step_tool_names=step_names, tool_outputs=tool_outputs)
        first_failed_summary: str | None = None
        blocked_by_failed_step = False
        for i, step in enumerate(draft_steps):
            tool = tools_by_name.get(step.tool_name)
            pair = aligned[i] if i < len(aligned) else (None, None)
            step_result, step_summary = pair
            raw_output = raw_outputs_by_step[i] if i < len(raw_outputs_by_step) else None
            output_status = self._tool_output_step_status(raw_output)
            output_error = self._tool_output_error(raw_output)
            resolved_step_status = step_status
            resolved_completed_at = step_completed_at
            if persisted_status in {"COMPLETED", "FAILED"} and blocked_by_failed_step:
                resolved_step_status = "NOT_STARTED"
                resolved_completed_at = None
            elif persisted_status in {"COMPLETED", "FAILED"} and output_status in {"FAILED", "AMBIGUOUS"}:
                resolved_step_status = output_status
                resolved_completed_at = completed_at or datetime.utcnow()
                blocked_by_failed_step = True
                first_failed_summary = first_failed_summary or output_error or step_summary or f"{step.tool_name} failed"
            step_row = PlanStepRow(
                step_id=self._generate_uuid(),
                plan_id=plan_row.plan_id,
                session_id=sess.session_id,
                step_index=step.step_index,
                tool_name=step.tool_name,
                args=step.args,
                bindings=[binding.model_dump() for binding in (getattr(step, "bindings", []) or [])],
                execution_mode=getattr(step, "execution_mode", "single") or "single",
                bulk_state=None,
                status=resolved_step_status,
                idempotency_key=compute_idempotency_key(
                    session_id=sess.session_id,
                    step_index=step.step_index,
                    plan_version=plan_version,
                    args=step.args,
                ),
                requires_approval=bool(tool.requires_approval) if tool else False,
                retry_count=0,
                max_retries=3,
                completed_at=resolved_completed_at,
                last_error=output_error if resolved_step_status in {"FAILED", "AMBIGUOUS"} else None,
                result=step_result,
                result_summary=step_summary,
            )
            db.add(step_row)

        sess.plan_id = plan_row.plan_id
        sess.plan_version = plan_version
        sess.plan_hash = plan_row.plan_hash
        sess.current_step_index = 0
        sess.pending_user_message = None
        context_for_session = dict(context_to_keep or {}) if isinstance(context_to_keep, dict) else None
        skip_completed_narrative = False
        if context_for_session is not None:
            skip_completed_narrative = bool(context_for_session.pop("skip_completed_narrative_adapter", False))
        if planner_no_action:
            blocked_context = dict(context_for_session or {})
            blocked_context["blocked_reason"] = PLANNER_NO_ACTION_REASON
            blocked_context["planner_no_action"] = {
                "backend_used": backend_used,
                "requested_status": status,
                "persisted_status": persisted_status,
                "step_count": 0,
            }
            sess.replan_context = blocked_context
            sess.error = PLANNER_NO_ACTION_MESSAGE
        else:
            sess.replan_context = context_for_session if context_for_session else None
            sess.error = None
        _bump_session_revision(sess)
        if planner_no_action:
            sess.status = "BLOCKED"
            sess.completed_at = None
        elif persisted_status == "COMPLETED":
            if first_failed_summary:
                sess.status = "FAILED"
                sess.error = first_failed_summary
                sess.completed_at = None
            else:
                sess.status = "COMPLETED"
                sess.completed_at = sess.completed_at or completed_at or datetime.utcnow()
        elif persisted_status == "PENDING_APPROVAL":
            sess.status = "WAITING_APPROVAL"
        elif persisted_status == "FAILED":
            sess.status = "FAILED"
            sess.error = first_failed_summary or sess.error or "Execution failed before a safe final answer could be produced."
            sess.completed_at = None
        else:
            sess.status = "PLANNING" if draft_steps else "IDLE"
        if not sess.name:
            sess.name = "New chat"

        result_summaries = [
            summary
            for _result, summary in aligned
            if isinstance(summary, str) and summary.strip()
        ]
        result_summary = " ".join(dict.fromkeys(result_summaries))
        quick_summary = result_summary or (PLANNER_NO_ACTION_MESSAGE if planner_no_action else draft.plan_explanation) or "Execution plan created."
        plan_message = MessageRow(
            message_id=self._generate_uuid(),
            session_id=sess.session_id,
            role="assistant",
            content=quick_summary,
            mode=(latest_user.mode if latest_user else "normal"),
            step_id=plan_row.plan_id,
            tool_name="__plan__",
        )
        db.add(plan_message)
        await db.commit()

        bundle_markdown = ""
        if (
            str(persisted_status) == "COMPLETED"
            and str(kind) == "execution"
            and tool_outputs
            and not first_failed_summary
            and not skip_completed_narrative
        ):
            try:
                tool_outputs_compact = compact_tool_outputs_for_narrative(tool_outputs)
                bundle = await self._summary_adapter.synthesize_bundle_markdown(
                    intent=intent,
                    kind="completed",
                    facts={
                        "intent": intent,
                        "plan_explanation": draft.plan_explanation,
                        "risk_summary": draft.risk_summary,
                        "steps": [
                            {
                                "step_index": s.step_index,
                                "tool_name": s.tool_name,
                                "args": s.args,
                            }
                            for s in (draft.steps or [])
                        ],
                        "tool_outputs": tool_outputs_compact,
                    },
                )
                if bundle.text.strip():
                    bundle_markdown = bundle.text.strip()
                    if bundle_markdown != (plan_message.content or "").strip():
                        plan_message.content = bundle_markdown
                    sess.llm_call_count = (sess.llm_call_count or 0) + bundle.llm_calls
                    _bump_session_revision(sess)
                    await db.commit()
            except SummaryBackendError:
                bundle_markdown = ""

        if not planner_no_action and not result_summary and not bundle_markdown:
            # Two-phase response for better UX:
            # 1) quick summary appears immediately
            # 2) richer summary replaces it when ready
            try:
                summary = await self._summary_adapter.summarize_plan(intent=intent, draft=draft)
                summary_text = (summary.text or "").strip()
                if summary_text and summary_text != (plan_message.content or "").strip():
                    plan_message.content = summary_text
                sess.llm_call_count += summary.llm_calls
                _bump_session_revision(sess)
                await db.commit()
            except SummaryBackendError:
                pass
        return plan_to_response(plan_row)

    def _align_raw_tool_outputs_to_steps(
        self,
        *,
        step_tool_names: list[str],
        tool_outputs: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any] | None]:
        if not step_tool_names:
            return []
        if not tool_outputs:
            return [None] * len(step_tool_names)
        rows = [row for row in tool_outputs if isinstance(row, dict)]
        out: list[dict[str, Any] | None] = []
        start = 0
        for name in step_tool_names:
            found: int | None = None
            for idx in range(start, len(rows)):
                if str(rows[idx].get("tool_name") or "") == str(name):
                    found = idx
                    break
            if found is None:
                out.append(None)
                continue
            start = found + 1
            out.append(rows[found])
        return out

    def _tool_output_step_status(self, row: dict[str, Any] | None) -> str:
        if not isinstance(row, dict):
            return ""
        status = str(row.get("status") or "").strip().upper()
        if status in {"FAILED", "ERROR"}:
            return "FAILED"
        if status == "AMBIGUOUS":
            return "AMBIGUOUS"
        if row.get("infrastructure_error"):
            return "FAILED"
        http_status = row.get("http_status")
        if isinstance(http_status, int) and http_status >= 400:
            return "FAILED"
        if row.get("error") or row.get("last_error"):
            return "FAILED"
        return status

    def _tool_output_error(self, row: dict[str, Any] | None) -> str | None:
        if not isinstance(row, dict):
            return None
        for key in ("last_error", "error", "summary", "result_summary"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        result = row.get("result")
        if isinstance(result, dict):
            for key in ("error", "detail", "message", "summary"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    async def _create_plan_approval(self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        plan_row: PlanRow,
        tools_by_name: dict[str, ToolInfo],
    ) -> ApprovalRow:
        side_effect_level = "HIGH"
        for step in (
            await db.execute(
                select(PlanStepRow).where(PlanStepRow.plan_id == plan_row.plan_id).order_by(PlanStepRow.step_index.asc())
            )
        ).scalars().all():
            tool = tools_by_name.get(step.tool_name)
            if tool and tool.side_effect_level == "CRITICAL":
                side_effect_level = "CRITICAL"
                break
        approval = ApprovalRow(
            approval_id=self._generate_uuid(),
            session_id=sess.session_id,
            subject_type="plan",
            plan_id=plan_row.plan_id,
            step_id="",
            tool_name="__plan__",
            args={"plan_id": plan_row.plan_id, "plan_hash": plan_row.plan_hash},
            risk_summary=plan_row.risk_summary or "Approve this plan before execution.",
            side_effect_level=side_effect_level,
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        db.add(approval)
        plan_row.status = "PENDING_APPROVAL"
        sess.status = "WAITING_APPROVAL"
        sess.error = None
        _bump_session_revision(sess)
        await db.commit()
        return approval

    async def _promote_discovery_to_execution(self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        discovery_plan: PlanRow,
        tools_by_name: dict[str, ToolInfo],
    ) -> PlanRow | None:
        intent = sess.current_intent or ""
        selection = await self._tool_selector.select_tools(
            intent=intent,
            tools_by_name=tools_by_name,
            mode="normal",
            context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        )
        scoped_tools = [tools_by_name[name] for name in selection.tool_names if name in tools_by_name]
        planner_context = await self._memory_manager.build_planner_context(
            db,
            session_id=sess.session_id,
            intent=intent,
            base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        )
        try:
            generated = await self._planner.generate_plan(
                intent=intent,
                scoped_tools=scoped_tools,
                context=planner_context,
            )
        except (PlannerClarificationError, PlannerBackendError, PlannerPlanRejected):
            return None

        sess.llm_call_count += selection.llm_calls
        sess.llm_call_count += generated.llm_calls
        context_to_keep = None
        intent_contract = getattr(generated, "intent_contract", None)
        if intent_contract:
            context_to_keep = dict(sess.replan_context or {})
            context_to_keep["intent_contract"] = intent_contract
        response = await self._persist_plan(
            db=db,
            sess=sess,
            draft=generated.draft,
            tools_by_name=tools_by_name,
            backend_used=generated.backend_used,
            kind="execution",
            status="PENDING_APPROVAL",
            intent=intent,
            derived_from_plan_id=discovery_plan.plan_id,
            context_to_keep=context_to_keep,
            tool_outputs=getattr(generated, "tool_outputs", None),
        )
        plan_row = (await db.execute(select(PlanRow).where(PlanRow.plan_id == response.plan_id))).scalars().first()
        if not plan_row:
            return None
        await self._create_plan_approval(db=db, sess=sess, plan_row=plan_row, tools_by_name=tools_by_name)
        discovery_plan.status = "COMPLETED"
        sess.completed_at = None
        sess.error = None
        await db.commit()
        return plan_row

    async def create_plan(
        self,
        *,
        db: AsyncSession,
        session_id: str,
        req: PlanCreateRequest,
        user: dict[str, Any],
    ) -> PlanResponse:
        started = time.perf_counter()
        sess = await self._session_mgr.get_session(db, session_id=session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        require_session_owner(sess, user)
        cancelled_response = await self._cancelled_plan_response_if_needed(db=db, sess=sess)
        if cancelled_response:
            metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
            return cancelled_response

        intent = sess.current_intent or ""
        latest_user = await self._latest_user_message(db=db, session_id=session_id)
        mode = latest_user.mode if latest_user else "normal"
        semantic_frame = semantic_frame_for_text(intent)
        resolved_loto_machine_id, resolved_loto_context = await self._resolve_loto_machine_context(
            db=db,
            sess=sess,
            latest_user=latest_user,
            intent=intent,
        )
        loto_rag_intent = self._loto_query_with_resolved_machine(intent, resolved_loto_machine_id)
        if resolved_loto_machine_id:
            semantic_frame = semantic_frame_for_text(loto_rag_intent)
        assessment = assess_intent(loto_rag_intent if resolved_loto_machine_id else intent)

        tools_by_name = await self._tool_registry.get_tools_by_name(db)
        tools_by_name = filter_tools_for_role(tools_by_name, role=role_from_claims(user))
        backend_used = "langgraph" if req.draft is None else "client"
        draft = req.draft
        seeded_planner_handles_intent = self._seeded_planner_handles_intent(intent)
        engine = resolve_factory_agent_engine_for_runtime(self._settings)

        if (
            engine == "v2"
            and draft is None
            and not seeded_planner_handles_intent
        ):
            tools_by_name = ensure_v2_rag_tool(tools_by_name)
            if not tools_by_name:
                raise HTTPException(status_code=403, detail={"errors": ["No tools are allowed for this user role."]})
            plan_resp = await self._create_direct_v2_plan(
                db=db,
                sess=sess,
                tools_by_name=tools_by_name,
                intent=intent,
                mode=mode,
                semantic_frame=semantic_frame,
                assessment=assessment,
            )
            metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
            return plan_resp

        if (
            semantic_frame.route.startswith("clarification.")
            and semantic_frame.missing_required_entities
            and not seeded_planner_handles_intent
        ):
            context_to_keep = await self._context_with_engine_trace(
                intent=intent,
                tools_by_name=tools_by_name,
                mode=mode,
                base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
                base_intent_contract=None,
                legacy_signals=LegacyExecutionSignals(generated_by="legacy_graph_loop"),
            )
            plan_resp = await self._persist_conversation_reply_as_empty_plan(
                db=db,
                sess=sess,
                reply=self._semantic_clarification_reply(semantic_frame),
                mode=mode,
                tools_by_name=tools_by_name,
                intent=intent,
                context_to_keep=context_to_keep,
            )
            metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
            return plan_resp

        if semantic_frame.route in {"rag.loto_procedure", "rag.procedure", "rag.safety_policy"}:
            context_to_keep = resolved_loto_context
            if semantic_frame.route != "unknown":
                context_to_keep = dict(context_to_keep or sess.replan_context or {})
                context_to_keep["semantic_frame"] = semantic_frame.to_payload()
            context_to_keep = await self._context_with_engine_trace(
                intent=loto_rag_intent if resolved_loto_machine_id else intent,
                tools_by_name=tools_by_name,
                mode=mode,
                base_context=context_to_keep,
                base_intent_contract=None,
                legacy_signals=legacy_rag_signals(
                    route=str(semantic_frame.route or "unknown"),
                    source_function="PlanCreationService.create_plan",
                    policy_id=str(semantic_frame.route or "unknown"),
                ),
            )
            plan_resp = await self._answer_knowledge_question_as_plan(
                db=db,
                sess=sess,
                mode=mode,
                tools_by_name=tools_by_name,
                intent=loto_rag_intent if resolved_loto_machine_id else intent,
                context_to_keep=context_to_keep,
                semantic_frame=semantic_frame,
            )
            metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
            return plan_resp

        if assessment.kind != "operations":
            if assessment.reply is None:
                context_to_keep = await self._context_with_engine_trace(
                    intent=intent,
                    tools_by_name=tools_by_name,
                    mode=mode,
                    base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
                    base_intent_contract=None,
                    legacy_signals=legacy_rag_signals(
                        route=str(semantic_frame.route or "assessment.non_operations_rag"),
                        source_function="PlanCreationService.create_plan",
                        policy_id=str(semantic_frame.route or "unknown"),
                    ),
                )
                plan_resp = await self._answer_knowledge_question_as_plan(
                    db=db,
                    sess=sess,
                    mode=mode,
                    tools_by_name=tools_by_name,
                    intent=intent,
                    context_to_keep=context_to_keep,
                    semantic_frame=semantic_frame,
                )
                metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
                return plan_resp
            reply = assessment.reply or "I need an operation request before I can create a plan."
            context_to_keep = await self._context_with_engine_trace(
                intent=intent,
                tools_by_name=tools_by_name,
                mode=mode,
                base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
                base_intent_contract=None,
                legacy_signals=LegacyExecutionSignals(generated_by="legacy_graph_loop"),
            )
            plan_resp = await self._persist_conversation_reply_as_empty_plan(
                db=db,
                sess=sess,
                reply=reply,
                mode=mode,
                tools_by_name=tools_by_name,
                intent=intent,
                context_to_keep=context_to_keep,
            )
            metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
            return plan_resp

        tools_by_name = await self._ensure_registry_health(db=db)
        tools_by_name = filter_tools_for_role(tools_by_name, role=role_from_claims(user))
        if not tools_by_name:
            raise HTTPException(status_code=403, detail={"errors": ["No tools are allowed for this user role."]})

        selection = await self._tool_selector.select_tools(
            intent=intent,
            tools_by_name=tools_by_name,
            mode=mode,
            context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        )
        scoped_names = set(selection.tool_names)
        tool_outputs_for_plan: list[dict[str, Any]] | None = None

        if draft is None:
            if not intent.strip():
                raise HTTPException(status_code=400, detail={"errors": ["Cannot auto-generate plan without a current intent."]})
            scoped_tools = [tools_by_name[name] for name in selection.tool_names if name in tools_by_name]
            if mode == "plan":
                if not seeded_planner_handles_intent:
                    scoped_tools = [tool for tool in scoped_tools if tool.is_read_only]
            if seeded_planner_handles_intent:
                scoped_tools = list(tools_by_name.values())
                scoped_names = {tool.name for tool in scoped_tools}
            context_to_keep: dict[str, Any] | None = None
            try:
                if scoped_tools:
                    planner_context = await self._memory_manager.build_planner_context(
                        db,
                        session_id=sess.session_id,
                        intent=intent,
                        base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
                    )
                    generated = await self._planner.generate_plan(
                        intent=intent,
                        scoped_tools=scoped_tools,
                        context=planner_context,
                    )
                    draft = generated.draft
                    backend_used = generated.backend_used
                    tool_outputs_for_plan = getattr(generated, "tool_outputs", None)
                    intent_contract = getattr(generated, "intent_contract", None)
                    context = await self._context_with_engine_trace(
                        intent=intent,
                        tools_by_name=tools_by_name,
                        mode=mode,
                        base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
                        base_intent_contract=intent_contract if isinstance(intent_contract, dict) else None,
                        legacy_signals=legacy_graph_signals(
                            intent=intent,
                            selected_candidate_tool_names=selection.tool_names,
                            planner_call_count=getattr(generated, "llm_calls", 0),
                            reranker_call_count=selection.llm_calls,
                            backend_used=getattr(selection, "backend_used", None),
                            source_function="PlanCreationService.create_plan",
                        ),
                    )
                    sess.replan_context = context
                    context_to_keep = context
                    sess.llm_call_count += selection.llm_calls
                    sess.llm_call_count += generated.llm_calls
                else:
                    from ..schemas import PlanDraft

                    draft = PlanDraft(
                        plan_explanation="No safe discovery steps are required before preparing an execution proposal.",
                        risk_summary="This stage is read-only and performs no writes.",
                        steps=[],
                    )
                    backend_used = "system"
                    context_to_keep = await self._context_with_engine_trace(
                        intent=intent,
                        tools_by_name=tools_by_name,
                        mode=mode,
                        base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
                        base_intent_contract=None,
                        legacy_signals=LegacyExecutionSignals(generated_by="legacy_graph_loop"),
                    )
            except PlannerConfirmationRequired as e:
                plan_resp = await self._persist_confirmation_request_as_empty_plan(
                    db=db,
                    sess=sess,
                    confirmation=e.confirmation,
                    mode=mode,
                    tools_by_name=tools_by_name,
                    intent=intent,
                )
                metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
                return plan_resp
            except PlannerApprovalRequired as e:
                sess = await self._persist_graph_interrupt_approval(
                    db=db,
                    sess=sess,
                    approval_payload=e.approval if isinstance(e.approval, dict) else {"kind": "approval_required"},
                    mode=mode,
                    tools_by_name=tools_by_name,
                    intent=intent,
                )
                metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
                current = await self._load_current_plan(db=db, session_id=sess.session_id)
                if current:
                    return plan_to_response(current)
                raise HTTPException(status_code=409, detail="graph approval was created without a compatibility plan")
            except PlannerClarificationError as e:
                reply = str(e)
                if ('could not safely map "' in reply and "Allowed " in reply) or (
                    'couldn\'t match "' in reply and "supported " in reply
                ) or ("not found" in reply.lower() or "does not exist" in reply.lower()):
                    context_to_keep = self._remember_negative_predicate_bindings(
                        sess=sess,
                        bindings=getattr(e, "negative_bindings", []) or [],
                    )
                    plan_resp = await self._persist_conversation_reply_as_empty_plan(
                        db=db,
                        sess=sess,
                        reply=reply,
                        mode=mode,
                        tools_by_name=tools_by_name,
                        intent=intent,
                        context_to_keep=context_to_keep,
                    )
                    metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
                    return plan_resp
                raise HTTPException(status_code=400, detail={"errors": [reply]}) from e
            except PlannerPlanRejected as e:
                raise HTTPException(status_code=400, detail={"errors": [str(e)]}) from e
            except PlannerBackendError as e:
                raise HTTPException(status_code=503, detail={"errors": [str(e)]}) from e
            except Exception as e:
                log_event(
                    "planner_unexpected_exception",
                    level="ERROR",
                    session_id=session_id,
                    error=str(e),
                )
                raise HTTPException(status_code=503, detail={"errors": ["Planner failed unexpectedly. Please retry."]}) from e
            _bump_session_revision(sess)
            await db.commit()
            metrics.inc("plan_backend_used_total", labels={"backend_used": backend_used})

        invalid_scoped = [s.tool_name for s in draft.steps if s.tool_name not in scoped_names]
        if invalid_scoped:
            raise HTTPException(status_code=400, detail={"errors": [f"Tool not allowed by scope: {t}" for t in invalid_scoped]})

        plan_kind = "discovery" if mode == "plan" else "execution"
        plan_status = "COMPLETED" if (backend_used == "langgraph" and plan_kind == "execution") else "DRAFT"
        cancelled_response = await self._cancelled_plan_response_if_needed(db=db, sess=sess)
        if cancelled_response:
            metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
            return cancelled_response
        validation = validate_plan(
            draft,
            tools_by_name,
            max_steps=self._plan_validation_step_limit(
                draft,
                backend_used=backend_used,
                kind=plan_kind,
                status=plan_status,
                tool_outputs=tool_outputs_for_plan,
            ),
        )
        if not validation.ok:
            metrics.inc("plan_validation_failure_total")
            metrics.inc("plan_validation_failure_rate")
            context = dict(sess.replan_context or {})
            failures = int(context.get("validation_failure_count", 0)) + 1
            context["validation_failure_count"] = failures
            context["last_validation_errors"] = validation.errors
            sess.replan_context = context
            sess.error = "Plan validation failed"
            sess.status = "BLOCKED"
            sess.completed_at = None
            _bump_session_revision(sess)
            if failures >= 3:
                existing_dlq = (
                    await db.execute(
                        select(DeadLetterRow)
                        .where(DeadLetterRow.session_id == session_id)
                        .where(DeadLetterRow.failure_type == "replan_limit_reached")
                    )
                ).scalars().first()
                if existing_dlq is None:
                    db.add(
                        DeadLetterRow(
                            dlq_id=self._generate_uuid(),
                            session_id=session_id,
                            step_id=None,
                            failure_type="replan_limit_reached",
                            reason="Plan validation failed 3 consecutive times",
                            payload={"errors": validation.errors, "validation_failure_count": failures},
                            status="PENDING",
                        )
                    )
            await db.commit()
            raise HTTPException(status_code=400, detail={"errors": validation.errors})

        response = await self._persist_plan(
            db=db,
            sess=sess,
            draft=draft,
            tools_by_name=tools_by_name,
            backend_used=backend_used,
            kind=plan_kind,
            status=plan_status,
            intent=intent,
            context_to_keep=sess.replan_context if isinstance(sess.replan_context, dict) else None,
            tool_outputs=tool_outputs_for_plan,
        )
        await self._memory_manager.save_checkpoint(
            db,
            session_id=sess.session_id,
            thread_id=sess.session_id,
            state={
                "status": sess.status,
                "plan_id": sess.plan_id,
                "plan_version": sess.plan_version,
                "current_step_index": sess.current_step_index,
                "step_count": sess.step_count,
                "replan_count": sess.replan_count,
                "llm_call_count": sess.llm_call_count,
            },
        )
        metrics.observe("plan_generation_latency_ms", (time.perf_counter() - started) * 1000.0)
        return response

    async def _persist_graph_interrupt_approval(self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        approval_payload: dict[str, Any],
        mode: str,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
    ) -> SessionRow:
        summary = str(approval_payload.get("summary") or "Approval is required before continuing.")
        narrative_markdown = summary
        try:
            bundle = await self._summary_adapter.synthesize_bundle_markdown(
                intent=intent,
                kind="awaiting_approval",
                facts={"intent": intent, "approval": dict(approval_payload)},
            )
            if bundle.text.strip():
                narrative_markdown = bundle.text.strip()
                sess.llm_call_count = (sess.llm_call_count or 0) + bundle.llm_calls
        except SummaryBackendError:
            pass
        merged_payload = dict(approval_payload)
        merged_payload["narrative_markdown"] = narrative_markdown
        expires_at = datetime.utcnow() + timedelta(hours=24)
        expires_in_seconds = approval_payload.get("expires_in_seconds")
        if isinstance(expires_in_seconds, (int, float)):
            expires_at = datetime.utcnow() + timedelta(seconds=float(expires_in_seconds))
        approval = ApprovalRow(
            approval_id=self._generate_uuid(),
            session_id=sess.session_id,
            subject_type="graph",
            plan_id=None,
            step_id=None,
            tool_name="__langgraph_commit__",
            args=merged_payload,
            risk_summary=narrative_markdown,
            side_effect_level="HIGH",
            status="PENDING",
            expires_at=expires_at,
        )
        db.add(approval)
        context = dict(sess.replan_context or {})
        context["langgraph_pending_approval"] = {
            "approval_id": approval.approval_id,
            "thread_id": sess.session_id,
            "source": "langgraph_interrupt",
        }
        sess.replan_context = context
        sess.status = "WAITING_APPROVAL"
        sess.error = narrative_markdown
        sess.completed_at = None
        _bump_session_revision(sess)
        await db.commit()
        await self._persist_conversation_reply_as_empty_plan(
            db=db,
            sess=sess,
            reply=narrative_markdown,
            mode=mode,
            tools_by_name=tools_by_name,
            intent=intent,
            context_to_keep=context,
        )
        sess = await self._session_mgr.get_session(db, session_id=sess.session_id) or sess
        sess.replan_context = context
        sess.status = "WAITING_APPROVAL"
        sess.error = narrative_markdown
        sess.completed_at = None
        _bump_session_revision(sess)
        await db.commit()
        return await self._session_mgr.get_session(db, session_id=sess.session_id) or sess
