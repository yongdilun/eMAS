from __future__ import annotations

import os
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
    rag_query_with_required_machine_context,
    resolve_contextual_loto_machine_id,
    semantic_frame_for_text,
)
from factory_agent.planning.plan_validator import validate_plan
from factory_agent.planning.historical_direct_v2_compatibility import is_historical_direct_v2_created_by
from factory_agent.planning.tool_output_alignment import align_tool_outputs_to_steps
from factory_agent.planning.tool_selector import ToolSelector
from factory_agent.planning.v2_rag_tool import ensure_v2_rag_tool
from factory_agent.planning.v2_trace_compatibility import (
    attach_direct_v2_trace_to_intent_contract,
    build_direct_v2_compatibility_state,
    build_failed_direct_v2_compatibility_state,
)
from factory_agent.rag.knowledge_policy import default_knowledge_policy_registry
from factory_agent.rag.runtime_config import (
    advisory_rag_pipeline_config,
    run_rag_pipeline_with_optional_config,
)
from factory_agent.rag.source_metadata import normalize_source_locators, sanitize_rag_answer_text
from factory_agent.registry.tool_registry import ToolRegistry
from factory_agent.schemas import PlanCreateRequest, PlanDraft, PlanResponse, ToolInfo
from factory_agent.security.permissions import filter_tools_for_role, role_from_claims
from factory_agent.services.plan_creation_compatibility import (
    generate_seeded_planner_compatibility_plan,
    resume_seeded_planner_compatibility_approval,
    seeded_planner_compatibility_matches_approval,
)
from factory_agent.services.planner_owned_graph_runtime import PlannerOwnedGraphRuntimeAdapter
from factory_agent.services.session_revision import bump_session_revision as _bump_session_revision
from factory_agent.session_state import is_user_cancelled_session
from factory_agent.tools.arguments import compute_idempotency_key


PLANNER_NO_ACTION_REASON = "planner_no_action"
PLANNER_NO_ACTION_MESSAGE = (
    "planner_no_action: The planner did not produce a safe plan, approval, or final result for this actionable "
    "request. Current state: blocked before execution. Next action: refine the request or check tool availability, "
    "then retry."
)
EMPTY_PLAN_COMPLETION_BACKENDS = {"system", "v2_rag_tool", "planner_owned_agent_graph"}


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
        return rag_query_with_required_machine_context(
            query,
            intent=intent,
            semantic_frame=semantic_frame,
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
        await db.commit()
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
            (
                backend_used in {"langgraph", "planner_owned_agent_graph"}
                or is_historical_direct_v2_created_by(backend_used)
            )
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

    def seeded_planner_compatibility_matches_approval(
        self,
        *,
        intent: str,
        approval_payload: dict[str, Any],
    ) -> bool:
        return seeded_planner_compatibility_matches_approval(
            planner=self._planner,
            intent=intent,
            approval_payload=approval_payload,
        )

    async def resume_seeded_planner_compatibility_approval(
        self,
        *,
        session_id: str,
        intent: str,
        approval_payload: dict[str, Any],
        approved: bool,
    ) -> Any:
        return await resume_seeded_planner_compatibility_approval(
            planner=self._planner,
            session_id=session_id,
            intent=intent,
            approval_payload=approval_payload,
            approved=approved,
        )

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
            result = await run_rag_pipeline_with_optional_config(
                self._rag_pipeline,
                query=intent,
                session_id=sess.session_id,
                route="RAG_ONLY",
                config=advisory_rag_pipeline_config(self._settings),
            )
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
    ) -> dict[str, Any]:
        context = dict(base_context or {})
        try:
            tools_with_rag = ensure_v2_rag_tool(tools_by_name)
            v2_state = await build_direct_v2_compatibility_state(
                tool_selector=self._tool_selector,
                intent=intent,
                tools_by_name=tools_with_rag,
                engine_mode="v2",
                mode=mode,
            )
            context["intent_contract"] = attach_direct_v2_trace_to_intent_contract(
                base_intent_contract,
                intent=intent,
                v2_state=v2_state,
            )
            return context
        except Exception as exc:
            log_event(
                "v2_engine_trace_failed",
                level="WARNING",
                intent=intent,
                error=str(exc),
            )
            fallback_state = build_failed_direct_v2_compatibility_state(str(exc))
            context["intent_contract"] = attach_direct_v2_trace_to_intent_contract(
                base_intent_contract,
                intent=intent,
                v2_state=fallback_state,
            )
            return context

    async def _create_planner_owned_graph_plan(
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
        if (
            semantic_frame is not None
            and str(getattr(semantic_frame, "route", "") or "").startswith("clarification.")
            and getattr(semantic_frame, "missing_required_entities", None)
            and not self._seeded_planner_handles_intent(intent)
        ):
            context = dict(sess.replan_context or {})
            if hasattr(semantic_frame, "to_payload"):
                context["semantic_frame"] = semantic_frame.to_payload()
            context["planner_owned_agent_graph"] = {
                "runtime_adapter": "semantic_clarification_guard",
                "graph_execution_authority": False,
                "reason": "clarification_required_before_execution",
            }
            return await self._persist_conversation_reply_as_empty_plan(
                db=db,
                sess=sess,
                reply=self._semantic_clarification_reply(semantic_frame),
                mode=mode,
                tools_by_name=tools_by_name,
                intent=intent,
                context_to_keep=context,
                backend_used="planner_owned_agent_graph",
            )

        if assessment is not None and getattr(assessment, "kind", None) != "operations":
            reply = getattr(assessment, "reply", None)
            if reply:
                context = dict(sess.replan_context or {})
                context["planner_owned_agent_graph"] = {
                    "runtime_adapter": "non_operational_guard",
                    "graph_execution_authority": False,
                    "reason": "non_operational_request",
                }
                return await self._persist_conversation_reply_as_empty_plan(
                    db=db,
                    sess=sess,
                    reply=reply,
                    mode=mode,
                    tools_by_name=tools_by_name,
                    intent=intent,
                    context_to_keep=context,
                    backend_used="planner_owned_agent_graph",
                )

        return await self._planner_owned_graph_runtime().run_plan(
            db=db,
            sess=sess,
            tools_by_name=tools_by_name,
            intent=intent,
            mode=mode,
        )

    def _planner_owned_graph_runtime(self) -> PlannerOwnedGraphRuntimeAdapter:
        return PlannerOwnedGraphRuntimeAdapter(
            settings=self._settings,
            tool_selector=self._tool_selector,
            rag_pipeline=self._rag_pipeline,
            uuid_factory=self._generate_uuid,
            persist_plan=self._persist_plan,
            session_lookup=self._session_mgr.get_session,
        )

    async def resume_planner_owned_graph_approval(
        self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        approval_id: str,
        approved: bool,
        ledger_revision: Any,
        checkpoint_id: Any,
        decided_by: str,
    ) -> Any:
        return await self._planner_owned_graph_runtime().resume_approval(
            db=db,
            sess=sess,
            tools_by_name=tools_by_name,
            intent=intent,
            approval_id=approval_id,
            approved=approved,
            ledger_revision=ledger_revision,
            checkpoint_id=checkpoint_id,
            decided_by=decided_by,
        )

    async def persist_planner_owned_graph_result(
        self,
        *,
        db: AsyncSession,
        sess: SessionRow,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        mode: str,
        result: Any,
    ) -> PlanResponse:
        return await self._planner_owned_graph_runtime().persist_result(
            db=db,
            sess=sess,
            tools_by_name=tools_by_name,
            intent=intent,
            mode=mode,
            result=result,
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
                or (
                    backend_used not in EMPTY_PLAN_COMPLETION_BACKENDS
                    and not is_historical_direct_v2_created_by(backend_used)
                    and not tool_outputs
                )
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
        runtime_intent = loto_rag_intent if resolved_loto_machine_id else intent

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
            plan_resp = await self._create_planner_owned_graph_plan(
                db=db,
                sess=sess,
                tools_by_name=tools_by_name,
                intent=runtime_intent,
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

        if (
            semantic_frame.route in {"rag.loto_procedure", "rag.procedure", "rag.safety_policy"}
            and not seeded_planner_handles_intent
        ):
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
                    generated = await generate_seeded_planner_compatibility_plan(
                        planner=self._planner,
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
