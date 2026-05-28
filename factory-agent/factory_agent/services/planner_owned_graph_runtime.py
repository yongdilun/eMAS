from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from factory_agent.config import Settings
from factory_agent.graph.v2_agent_graph import (
    LocalPlannerOwnedGraphTracer,
    PlannerOwnedAgentGraph,
    PlannerOwnedAgentGraphAdapters,
    PlannerOwnedGraphResult,
)
from factory_agent.observability.metrics import metrics
from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.planning.v2_contracts import EvidenceLedgerEntry, requirement_child_lineage
from factory_agent.planning.v2_rag_tool import ensure_v2_rag_tool
from factory_agent.schemas import PlanDraft, PlanResponse, PlanStepDraft, ToolInfo
from factory_agent.services.session_revision import bump_session_revision

PersistPlan = Callable[..., Awaitable[PlanResponse]]
SessionLookup = Callable[..., Awaitable[Any]]
UuidFactory = Callable[[], str]

_ACTIVE_SESSION_STATUSES = {"PLANNING", "EXECUTING", "WAITING_APPROVAL", "WAITING_CONFIRMATION"}
_LIVE_GRAPH_MAX_STEPS = 8


def _intent_contract_replan_spine(state: Any) -> dict[str, Any]:
    diagnostics = getattr(getattr(state, "execution_trace", None), "diagnostics", {})
    replan = diagnostics.get("replan_spine") if isinstance(diagnostics, Mapping) else None
    if not isinstance(replan, Mapping):
        return {}
    return dict(replan)


def _graph_event_is_rag(event: Mapping[str, Any]) -> bool:
    tool_names = [str(item or "").lower() for item in event.get("tool_names") or []]
    source_types = [str(item or "").lower() for item in event.get("source_types") or []]
    return any("rag" in item or "search_documents" in item for item in [*tool_names, *source_types])


def _live_activity_step_for_graph_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    if event.get("event") != "planner_owned_agent_graph_node":
        return None
    node = str(event.get("node") or "").strip()
    if not node:
        return None
    rag = _graph_event_is_rag(event)
    mapping: dict[str, tuple[str, str, str]] = {
        "semantic_intake_node": (
            "planning",
            "Understood request",
            "Reviewing your request and recent context",
        ),
        "requirement_ledger_node": (
            "planning",
            "Structuring request",
            "Structuring the request",
        ),
        "planner_decision_node": (
            "planning",
            "Choosing next action",
            "Choosing the next backend action",
        ),
        "tool_retrieval_node": (
            "planning",
            "Finding information path",
            "Finding the right information path",
        ),
        "planner_choose_tool_node": (
            "planning",
            "Selecting safe action",
            "Selecting a safe action",
        ),
        "tool_execution_node": (
            "research",
            "Searching knowledge sources" if rag else "Running selected tool",
            "Searching retrieved documents" if rag else "Checking relevant records",
        ),
        "evidence_observation_node": (
            "response",
            "Checking citations" if rag else "Checking result",
            "Checking evidence support" if rag else "Checking tool evidence",
        ),
        "satisfaction_node": (
            "response",
            "Checking result",
            "Verifying the result",
        ),
        "approval_node": (
            "planning",
            "Checking approvals",
            "Checking approval requirements",
        ),
        "finalize_node": (
            "response",
            "Preparing response",
            "Finalizing the answer",
        ),
        "response_document_node": (
            "response",
            "Preparing response",
            "Rendering the response",
        ),
    }
    spec = mapping.get(node)
    if spec is None:
        return None
    group, label, detail = spec
    return {
        "id": f"graph:{node}",
        "timestamp": int(datetime.utcnow().timestamp()),
        "group": group,
        "label": label,
        "detail": detail,
        "state": "running",
    }


class LiveGraphActivityRecorder:
    """Persists in-flight graph node progress so activity SSE can stream real stages."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession],
        session_id: str,
    ) -> None:
        self._session_factory = session_factory
        self._session_id = session_id
        self._pending: list[dict[str, Any]] = []
        self._drain_task: asyncio.Task[None] | None = None
        self._sequence = 0

    def record_graph_event(self, event: Mapping[str, Any]) -> None:
        step = _live_activity_step_for_graph_event(event)
        if step is None:
            return
        replan_spine = event.get("replan_spine")
        if isinstance(replan_spine, Mapping):
            step["_replan_spine"] = dict(replan_spine)
        self._sequence += 1
        step["order"] = self._sequence
        step["_order"] = self._sequence
        self._pending.append(step)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = loop.create_task(self._drain())

    async def flush(self) -> None:
        while True:
            task = self._drain_task
            if task is None:
                return
            await task
            if not self._pending and self._drain_task is task:
                return

    async def _drain(self) -> None:
        while self._pending:
            batch = self._pending
            self._pending = []
            await self._persist_batch(batch)

    async def _persist_batch(self, batch: list[dict[str, Any]]) -> None:
        async with self._session_factory() as db:
            row = (
                await db.execute(select(SessionRow).where(SessionRow.session_id == self._session_id))
            ).scalar_one_or_none()
            if row is None:
                return
            if str(row.status or "").upper() not in _ACTIVE_SESSION_STATUSES:
                return
            context = dict(row.replan_context or {})
            existing_rows = context.get("live_activity_steps")
            existing = [dict(item) for item in existing_rows if isinstance(item, dict)] if isinstance(existing_rows, list) else []
            by_id = {str(item.get("id") or ""): item for item in existing if item.get("id")}
            latest_replan_spine: dict[str, Any] | None = None
            for step in batch:
                replan_spine = step.pop("_replan_spine", None)
                if isinstance(replan_spine, Mapping):
                    latest_replan_spine = dict(replan_spine)
                step_id = str(step["id"])
                existing_order = by_id.get(step_id, {}).get("order") or by_id.get(step_id, {}).get("_order")
                if existing_order is not None:
                    step["order"] = existing_order
                    step["_order"] = existing_order
                by_id[step_id] = dict(step)
            live_steps = sorted(
                by_id.values(),
                key=lambda item: (
                    int(item.get("order") or item.get("_order") or 0),
                    int(item.get("timestamp") or 0),
                    str(item.get("id") or ""),
                ),
            )[-_LIVE_GRAPH_MAX_STEPS:]
            context["live_activity_steps"] = live_steps
            context["live_activity_revision"] = int(context.get("live_activity_revision") or 0) + 1
            if latest_replan_spine is not None:
                context["live_replan_spine"] = latest_replan_spine
                context["live_replan_spine_revision"] = int(context.get("live_replan_spine_revision") or 0) + 1
            row.replan_context = context
            row.updated_at = datetime.utcnow()
            bump_session_revision(row)
            await db.commit()


class PlannerOwnedGraphRuntimeAdapter:
    """Deep adapter from graph execution truth to UI/API persistence rows."""

    def __init__(
        self,
        *,
        settings: Settings,
        tool_selector: Any,
        rag_pipeline: Any | None,
        uuid_factory: UuidFactory,
        persist_plan: PersistPlan,
        session_lookup: SessionLookup,
    ) -> None:
        self._settings = settings
        self._tool_selector = tool_selector
        self._rag_pipeline = rag_pipeline
        self._uuid_factory = uuid_factory
        self._persist_plan = persist_plan
        self._session_lookup = session_lookup

    async def run_plan(
        self,
        *,
        db: AsyncSession,
        sess: Any,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        mode: str,
    ) -> PlanResponse:
        tools_by_name = ensure_v2_rag_tool(tools_by_name)
        live_activity = self._live_activity_recorder(db=db, sess=sess)
        graph = self._build_graph(
            db=db,
            sess=sess,
            tools_by_name=tools_by_name,
            mode=mode,
            live_activity=live_activity,
        )
        try:
            result = await graph.run(
                intent,
                session_context=sess,
                options={"thread_id": sess.session_id},
            )
        finally:
            if live_activity is not None:
                await live_activity.flush()
        sess.llm_call_count = (sess.llm_call_count or 0) + self.llm_call_count(result)
        return await self.persist_result(
            db=db,
            sess=sess,
            tools_by_name=tools_by_name,
            intent=intent,
            mode=mode,
            result=result,
        )

    async def resume_approval(
        self,
        *,
        db: AsyncSession,
        sess: Any,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        approval_id: str,
        approved: bool,
        ledger_revision: Any,
        checkpoint_id: Any,
        decided_by: str,
        mode: str = "normal",
    ) -> PlannerOwnedGraphResult:
        tools_by_name = ensure_v2_rag_tool(tools_by_name)
        live_activity = self._live_activity_recorder(db=db, sess=sess)
        graph = self._build_graph(
            db=db,
            sess=sess,
            tools_by_name=tools_by_name,
            mode=mode,
            live_activity=live_activity,
        )
        try:
            result = await graph.resume_from_approval(
                sess,
                {
                    "approval_id": approval_id,
                    "approved": approved,
                    "ledger_revision": ledger_revision,
                    "checkpoint_id": checkpoint_id,
                    "decided_by": decided_by,
                },
                options={"thread_id": sess.session_id},
            )
        finally:
            if live_activity is not None:
                await live_activity.flush()
        sess.llm_call_count = (sess.llm_call_count or 0) + self.llm_call_count(result)
        return result

    async def persist_result(
        self,
        *,
        db: AsyncSession,
        sess: Any,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        mode: str,
        result: PlannerOwnedGraphResult,
    ) -> PlanResponse:
        state = result.state
        context = self._graph_context(
            result=result,
            intent=intent,
            base_context=sess.replan_context if isinstance(sess.replan_context, dict) else None,
        )
        if state.pending_approval.status == "pending":
            return await self._persist_pending_approval(
                db=db,
                sess=sess,
                tools_by_name=tools_by_name,
                intent=intent,
                mode=mode,
                result=result,
                context=context,
            )

        draft, tool_outputs = self._plan_artifacts(result, tools_by_name=tools_by_name)
        failed = self._graph_failed(result, tool_outputs)
        plan_status = "FAILED" if failed and mode != "plan" else "COMPLETED" if mode != "plan" else "DRAFT"
        response = await self._persist_plan(
            db=db,
            sess=sess,
            draft=draft,
            tools_by_name=tools_by_name,
            backend_used="planner_owned_agent_graph",
            kind="discovery" if mode == "plan" else "execution",
            status=plan_status,
            intent=intent,
            context_to_keep=context,
            tool_outputs=tool_outputs,
        )
        metrics.inc("plan_backend_used_total", labels={"backend_used": "planner_owned_agent_graph"})
        return response

    def _build_graph(
        self,
        *,
        db: AsyncSession,
        sess: Any,
        tools_by_name: dict[str, ToolInfo],
        mode: str,
        live_activity: LiveGraphActivityRecorder | None = None,
    ) -> PlannerOwnedAgentGraph:
        async def _approval_persister(*, state: Any, payload: dict[str, Any]) -> dict[str, Any]:
            return await self._persist_approval_row(
                db=db,
                sess=sess,
                tools_by_name=tools_by_name,
                state=state,
                payload=payload,
            )

        return PlannerOwnedAgentGraph(
            settings=self._settings,
            adapters=PlannerOwnedAgentGraphAdapters(
                settings=self._settings,
                tools_by_name=tools_by_name,
                tool_selector=self._tool_selector,
                retrieval_mode=mode,
                session_id=sess.session_id,
                rag_pipeline=self._rag_pipeline,
                approval_persister=_approval_persister,
            ),
            tracer=(
                LocalPlannerOwnedGraphTracer(on_node_recorded=live_activity.record_graph_event)
                if live_activity is not None
                else None
            ),
        )

    def _live_activity_recorder(self, *, db: AsyncSession, sess: Any) -> LiveGraphActivityRecorder | None:
        bind = getattr(db, "bind", None)
        session_id = str(getattr(sess, "session_id", "") or "").strip()
        if bind is None or not session_id:
            return None
        factory = sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)
        return LiveGraphActivityRecorder(session_factory=factory, session_id=session_id)

    async def _persist_approval_row(
        self,
        *,
        db: AsyncSession,
        sess: Any,
        tools_by_name: Mapping[str, ToolInfo],
        state: Any,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        merged_payload = dict(payload)
        requirement_id = str(merged_payload.get("requirement_id") or "")
        requirement = self._requirement_by_id(state, requirement_id)
        if requirement is not None:
            merged_payload.setdefault("locked_constraints", dict(getattr(requirement, "constraints", {}) or {}))
            merged_payload.setdefault("entity_type", getattr(requirement, "entity", None))
        merged_payload = self._with_approval_bundle_ui(merged_payload)

        summary = str(
            merged_payload.get("summary")
            or merged_payload.get("approval_label")
            or "Approval is required before continuing."
        )
        expires_at = datetime.utcnow() + timedelta(hours=24)
        expires_in_seconds = merged_payload.get("expires_in_seconds")
        if isinstance(expires_in_seconds, (int, float)):
            expires_at = datetime.utcnow() + timedelta(seconds=float(expires_in_seconds))

        approval = ApprovalRow(
            approval_id=self._uuid_factory(),
            session_id=sess.session_id,
            subject_type="graph",
            plan_id=None,
            step_id=None,
            tool_name=self._approval_tool_name(merged_payload),
            args=merged_payload,
            risk_summary=summary,
            side_effect_level=self._approval_side_effect_level(merged_payload, tools_by_name),
            status="PENDING",
            expires_at=expires_at,
        )
        db.add(approval)
        await db.commit()
        return {
            "approval_id": approval.approval_id,
            "persisted": True,
            "subject_type": "graph",
            "native_langgraph_checkpoint_used": True,
        }

    def _with_approval_bundle_ui(self, payload: dict[str, Any]) -> dict[str, Any]:
        existing_bundle = payload.get("bundle_ui") if isinstance(payload.get("bundle_ui"), dict) else None
        rows = payload.get("preview_rows") if isinstance(payload.get("preview_rows"), list) else []
        if existing_bundle is not None and not rows:
            return payload
        selected_call = payload.get("selected_graph_tool_call")
        selected_args = selected_call.get("args") if isinstance(selected_call, dict) else {}
        selected_args = selected_args if isinstance(selected_args, dict) else {}
        locked_constraints = payload.get("locked_constraints") if isinstance(payload.get("locked_constraints"), dict) else {}
        entity_type = str(payload.get("entity_type") or locked_constraints.get("entity") or "").strip().lower()
        source_priority = (
            locked_constraints.get("priority")
            or locked_constraints.get("priority_from")
            or locked_constraints.get("source_priority")
        )
        target_priority = selected_args.get("priority") or payload.get("new_priority") or locked_constraints.get("new_priority")
        bundle_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out = dict(row)
            row_id = out.get("job_id") or out.get("id") or selected_args.get("id")
            if row_id not in (None, ""):
                out.setdefault("job_id", row_id)
            if target_priority not in (None, ""):
                out.setdefault("new_priority", target_priority)
            bundle_rows.append(out)

        headline = str(payload.get("summary") or "Approval required before applying staged changes.").rstrip(".")
        if bundle_rows and entity_type == "job" and source_priority not in (None, "") and target_priority not in (None, ""):
            noun = "job" if len(bundle_rows) == 1 else "jobs"
            headline = (
                f"{len(bundle_rows)} {noun} will be updated from "
                f"{str(source_priority).strip().lower()} to {str(target_priority).strip().lower()} priority."
            )
            payload["summary"] = headline
            payload["count"] = len(bundle_rows)
        bundle_kind = (
            "job_priority_bundle"
            if bundle_rows
            and entity_type == "job"
            and source_priority not in (None, "")
            and target_priority not in (None, "")
            else "v2_planner_owned_approval_preview"
        )

        payload["bundle_ui"] = {
            "kind": bundle_kind,
            "write_set": str(payload.get("requirement_id") or "planner_owned_graph_write"),
            "headline": headline,
            "rows": bundle_rows,
            "excluded_rows": payload.get("excluded_rows") if isinstance(payload.get("excluded_rows"), list) else [],
            "previous_priority": str(source_priority).strip().lower() if source_priority not in (None, "") else None,
            "new_priority": str(target_priority).strip().lower() if target_priority not in (None, "") else None,
            "source_priority": str(source_priority).strip().lower() if source_priority not in (None, "") else None,
            "locked_constraints": dict(locked_constraints),
            "requirement_ledger_revision": payload.get("requirement_ledger_revision") or payload.get("ledger_revision"),
            "source_intent": payload.get("source_intent"),
            "write_tool_name": (
                selected_call.get("tool_name")
                if isinstance(selected_call, dict)
                else payload.get("write_tool_name")
            ),
            "approval_label": payload.get("approval_label"),
            "graph_runtime": True,
        }
        return payload

    async def _persist_pending_approval(
        self,
        *,
        db: AsyncSession,
        sess: Any,
        tools_by_name: dict[str, ToolInfo],
        intent: str,
        mode: str,
        result: PlannerOwnedGraphResult,
        context: dict[str, Any],
    ) -> PlanResponse:
        pending = result.state.pending_approval
        payload = dict(pending.payload)
        summary = str(payload.get("narrative_markdown") or payload.get("summary") or "Approval is required before continuing.")
        context["langgraph_pending_approval"] = {
            "approval_id": pending.approval_id,
            "thread_id": sess.session_id,
            "source": "planner_owned_agent_graph",
            "checkpoint_id": pending.checkpoint_id,
            "ledger_revision": pending.ledger_revision,
        }
        draft = PlanDraft(
            plan_explanation=summary,
            risk_summary="Waiting for graph-native approval before committing staged changes.",
            steps=[],
        )
        response = await self._persist_plan(
            db=db,
            sess=sess,
            draft=draft,
            tools_by_name=tools_by_name,
            backend_used="planner_owned_agent_graph",
            kind="execution",
            status="COMPLETED",
            intent=intent,
            context_to_keep=context,
            tool_outputs=[],
        )
        refreshed = await self._session_lookup(db, session_id=sess.session_id) or sess
        refreshed.status = "WAITING_APPROVAL"
        refreshed.error = summary
        refreshed.completed_at = None
        refreshed.replan_context = context
        bump_session_revision(refreshed)
        await db.commit()
        metrics.inc("plan_backend_used_total", labels={"backend_used": "planner_owned_agent_graph"})
        return response

    def _graph_context(
        self,
        *,
        result: PlannerOwnedGraphResult,
        intent: str,
        base_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        state = result.state
        loop_state = state.as_loop_compat_state()
        graph_state = state.model_dump(mode="json")
        response_document_context = state.response_document_context.model_dump(mode="json")
        replan_spine = _intent_contract_replan_spine(state)
        dependency_plan = state.execution_trace.diagnostics.get("dependency_plan")
        dependency_plan_history = state.execution_trace.diagnostics.get("dependency_plan_history")
        child_lineage = requirement_child_lineage(state.requirement_ledger)
        conditional_branches = [
            branch.model_dump(mode="json")
            for branch in state.requirement_ledger.conditional_branches
        ]
        answer_instructions = [
            instruction.model_dump(mode="json")
            for instruction in state.requirement_ledger.answer_instructions
        ]
        context = dict(base_context or {})
        context.pop("live_activity_steps", None)
        context.pop("live_activity_revision", None)
        context.pop("live_replan_spine", None)
        context.pop("live_replan_spine_revision", None)
        context["intent_contract"] = {
            "intent": intent,
            "engine_version": "v2",
            "execution_trace": state.execution_trace.model_dump(mode="json"),
            "v2_state": loop_state.model_dump(mode="json"),
            "planner_owned_agent_graph_state": graph_state,
            "response_document_context": response_document_context,
            "dependency_plan": dependency_plan,
            "dependency_plan_history": dependency_plan_history,
            "child_requirement_lineage": child_lineage,
            "conditional_branches": conditional_branches,
            "answer_instructions": answer_instructions,
            "replan_spine": replan_spine,
        }
        context.pop("no_op_mutations", None)
        no_op_mutations = self._no_op_mutations(state)
        if no_op_mutations:
            context["intent_contract"]["no_op_mutations"] = no_op_mutations
            context["no_op_mutations"] = no_op_mutations
        context["planner_owned_agent_graph"] = {
            "runtime_adapter": "planner_owned_graph_runtime",
            "graph_execution_authority": True,
            "thread_id": result.checkpoint_config.get("configurable", {}).get("thread_id"),
            "checkpoint_config": result.checkpoint_config,
            "node_order": result.node_order,
            "planner_decision_count": len(state.planner_decisions),
            "evidence_refs": [evidence.id for evidence in state.evidence_ledger.evidence],
            "response_document_state": state.response_document_context.state,
            "response_document_context": response_document_context,
            "dependency_plan": dependency_plan,
            "dependency_plan_history": dependency_plan_history,
            "child_requirement_lineage": child_lineage,
            "conditional_branches": conditional_branches,
            "answer_instructions": answer_instructions,
            "replan_spine": replan_spine,
            "native_langgraph_checkpoint_used": True,
            "session_replan_context_authoritative": False,
        }
        context["skip_completed_narrative_adapter"] = True
        context["requirement_ledger_revision"] = state.requirement_ledger.revision
        context.pop("langgraph_approval_resume", None)
        if state.pending_approval.status != "pending":
            context.pop("langgraph_pending_approval", None)
        return context

    def _plan_artifacts(
        self,
        result: PlannerOwnedGraphResult,
        *,
        tools_by_name: Mapping[str, ToolInfo] | None = None,
    ) -> tuple[PlanDraft, list[dict[str, Any]]]:
        state = result.state
        summary = self._response_summary(result)
        document_only = self._is_document_only(result)
        tool_outputs = [] if document_only else self._tool_outputs(result)
        step_outputs = [] if document_only else [
            output
            for output in tool_outputs
            if str(output.get("tool_name") or "").strip() and not output.get("aggregated_from")
            and str(output.get("status") or "").upper() != "FAILED"
            and self._tool_output_has_valid_plan_step_args(output, tools_by_name or {})
        ]
        steps = [
            PlanStepDraft(
                step_index=index,
                tool_name=str(output.get("tool_name") or ""),
                args=dict(output.get("args") if isinstance(output.get("args"), dict) else {}),
            )
            for index, output in enumerate(step_outputs)
        ]
        draft = PlanDraft(
            plan_explanation=summary,
            risk_summary=self._risk_summary(result),
            steps=steps,
            sources=self._sources(state),
            safety_content=self._safety_content(state),
        )
        return draft, tool_outputs

    def _tool_output_has_valid_plan_step_args(
        self,
        output: Mapping[str, Any],
        tools_by_name: Mapping[str, ToolInfo],
    ) -> bool:
        tool_name = str(output.get("tool_name") or "").strip()
        tool = tools_by_name.get(tool_name)
        if tool is None:
            return False
        args = output.get("args")
        args = dict(args) if isinstance(args, Mapping) else {}
        try:
            Draft202012Validator(tool.input_schema or {"type": "object"}).validate(args)
        except Exception:
            return False
        return True

    def _tool_outputs(self, result: PlannerOwnedGraphResult) -> list[dict[str, Any]]:
        state = result.state
        blocks_by_evidence = {
            str(block.get("evidence_ref")): block
            for block in state.response_document_context.diagnostics.get("blocks", [])
            if isinstance(block, dict) and block.get("evidence_ref")
        }
        business_change_hints = self._business_change_hints_by_requirement(state)
        active_response_refs = set(state.response_document_context.evidence_refs)
        tool_output_refs = set(active_response_refs)
        if not tool_output_refs and self._response_context_replan_limit_reached(state):
            tool_output_refs = {
                evidence.id
                for evidence in state.evidence_ledger.evidence
                if not evidence.diagnostic_metadata.get("stale_after_graph_replan")
                and evidence.diagnostic_metadata.get("superseded_reason") != "replan_spine_retry"
            }
        outputs: list[dict[str, Any]] = []
        for evidence in state.evidence_ledger.evidence:
            if not evidence.tool_name:
                continue
            if tool_output_refs and evidence.id not in tool_output_refs:
                continue
            if self._is_non_actionable_preview_evidence(evidence):
                continue
            if evidence.diagnostic_metadata.get("aggregated_from"):
                continue
            block = blocks_by_evidence.get(evidence.id, {})
            row_hint = self._business_change_hint_for_evidence(evidence, business_change_hints)
            result_payload = self._step_result_payload(evidence)
            if row_hint:
                result_payload = self._with_business_change_result_payload(result_payload, row_hint)
            summary = (
                self._business_change_summary(row_hint)
                or str(block.get("summary") or evidence.normalized_result.get("summary") or "")
            )
            args = dict(evidence.args or {})
            if row_hint:
                for key in (
                    "previous_priority",
                    "original_priority",
                    "new_priority",
                    "source_state_basis",
                    "entity_type",
                    "selector_summary",
                    "business_change",
                    "business_change_id",
                ):
                    if row_hint.get(key) not in (None, "", [], {}):
                        args.setdefault(key, row_hint[key])
            status = "FAILED" if self._evidence_failed(evidence) else "DONE"
            outputs.append(
                {
                    "tool_name": evidence.tool_name,
                    "args": args,
                    "result": result_payload,
                    "http_status": evidence.diagnostic_metadata.get("http_status")
                    or evidence.normalized_result.get("status_code"),
                    "latency_ms": evidence.diagnostic_metadata.get("latency_ms"),
                    "status": status,
                    "requirement_id": evidence.requirement_id,
                    "approval_id": row_hint.get("approval_id") if row_hint else evidence.approval_id,
                    "summary": summary,
                    "evidence_ref": evidence.id,
                    "graph_authorized_execution": True,
                    "aggregated_from": evidence.diagnostic_metadata.get("aggregated_from"),
                }
            )
        return outputs

    def _response_context_replan_limit_reached(self, state: Any) -> bool:
        context = getattr(state, "response_document_context", None)
        diagnostics = getattr(context, "diagnostics", {}) if context is not None else {}
        replan = diagnostics.get("replan_spine") if isinstance(diagnostics, Mapping) else None
        return isinstance(replan, Mapping) and replan.get("replan_limit_reached") is True

    def _is_non_actionable_preview_evidence(self, evidence: EvidenceLedgerEntry) -> bool:
        metadata = evidence.diagnostic_metadata if isinstance(evidence.diagnostic_metadata, Mapping) else {}
        result = evidence.normalized_result if isinstance(evidence.normalized_result, Mapping) else {}
        if str(metadata.get("reason") or "").strip() == "approval_preview_no_records":
            return True
        return (
            str(evidence.source_type or "").strip() == "system_guard"
            and str(metadata.get("graph_tool_action") or "").strip() == "approval_preview"
            and (
                result.get("no_match") is True
                or str(result.get("match_status") or "").strip().lower() == "no_match"
                or str(result.get("status") or "").strip().lower() == "no_match"
            )
        )

    def _no_op_mutations(self, state: Any) -> list[dict[str, Any]]:
        no_ops: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for evidence in state.evidence_ledger.evidence:
            if not self._is_non_actionable_preview_evidence(evidence):
                continue
            requirement = self._requirement_by_id(state, evidence.requirement_id)
            result = evidence.normalized_result if isinstance(evidence.normalized_result, Mapping) else {}
            entity = str(
                getattr(requirement, "entity", None)
                or result.get("entity")
                or "record"
            ).strip().lower() or "record"
            selector_summary = self._no_op_selector_summary(requirement, evidence)
            change_summary = self._no_op_change_summary(requirement, evidence)
            key = (entity, selector_summary, change_summary)
            if key in seen:
                continue
            seen.add(key)
            no_ops.append(
                {
                    "entity_type": entity,
                    "selector_summary": selector_summary,
                    "change_summary": change_summary,
                    "matched_count": 0,
                    "changed_count": 0,
                    "status": "not_changed",
                    "reason": "no_matching_records",
                }
            )
        return no_ops

    def _no_op_selector_summary(self, requirement: Any | None, evidence: EvidenceLedgerEntry) -> str:
        constraints = dict(getattr(requirement, "constraints", {}) or {}) if requirement is not None else {}
        selector_parts = []
        for key, value in constraints.items():
            if value in (None, "", [], {}):
                continue
            key_text = str(key).strip()
            if not key_text or key_text.startswith("new_") or key_text in {"requires_approval"}:
                continue
            selector_parts.append(f"{key_text} = {value}")
        if selector_parts:
            return ", ".join(selector_parts)
        args = evidence.args if isinstance(evidence.args, Mapping) else {}
        arg_parts = [
            f"{key} = {value}"
            for key, value in args.items()
            if value not in (None, "", [], {}) and not str(key).strip().startswith("new_")
        ]
        return ", ".join(arg_parts) if arg_parts else "matching records"

    def _no_op_change_summary(self, requirement: Any | None, evidence: EvidenceLedgerEntry) -> str:
        constraints = dict(getattr(requirement, "constraints", {}) or {}) if requirement is not None else {}
        priority_target = constraints.get("new_priority")
        if priority_target not in (None, "", [], {}):
            return f"priority -> {priority_target}"
        for key, value in constraints.items():
            key_text = str(key).strip()
            if key_text.startswith("new_") and value not in (None, "", [], {}):
                return f"{key_text[4:]} -> {value}"
        args = evidence.args if isinstance(evidence.args, Mapping) else {}
        for key, value in args.items():
            if value not in (None, "", [], {}):
                return f"{key} -> {value}"
        return "no matching records"

    def _business_change_hints_by_requirement(self, state: Any) -> dict[str, dict[str, Any]]:
        hints: dict[str, dict[str, Any]] = {}
        for evidence in state.evidence_ledger.evidence:
            if evidence.source_type != "approval":
                continue
            status = str(
                evidence.normalized_result.get("approval_status")
                or evidence.normalized_result.get("status")
                or ""
            ).strip().lower()
            if status not in {"approved", "accepted"}:
                continue
            metadata = evidence.diagnostic_metadata if isinstance(evidence.diagnostic_metadata, Mapping) else {}
            locked = metadata.get("locked_constraints") if isinstance(metadata.get("locked_constraints"), Mapping) else {}
            rows = [dict(row) for row in (metadata.get("preview_rows") or []) if isinstance(row, Mapping)]
            staged_calls = [
                dict(call) for call in (metadata.get("staged_graph_tool_calls") or []) if isinstance(call, Mapping)
            ]
            requirement = self._requirement_by_id(state, evidence.requirement_id)
            entity = str(
                getattr(requirement, "entity", None)
                or locked.get("entity_type")
                or locked.get("entity")
                or ""
            ).strip().lower()
            source_priority = self._source_priority_value(locked)
            target_priority = self._target_priority_value(locked)
            calls_by_record = self._staged_call_args_by_record(staged_calls, entity=entity)

            rows_by_record: dict[str, dict[str, Any]] = {}
            for row in rows:
                row_id = self._record_id(row, entity=entity)
                staged_args = calls_by_record.get(row_id or "") if row_id else None
                hint = self._business_change_hint_from_row(
                    row,
                    entity=entity,
                    approval_id=evidence.approval_id or metadata.get("approval_id"),
                    source_priority=source_priority,
                    target_priority=target_priority,
                    staged_args=staged_args,
                )
                if row_id:
                    rows_by_record[row_id] = hint

            hints[evidence.requirement_id] = {
                "approval_id": evidence.approval_id or metadata.get("approval_id"),
                "entity_type": entity,
                "source_priority": source_priority,
                "target_priority": target_priority,
                "rows_by_record": rows_by_record,
                "row_count": len(rows_by_record) or len(rows),
            }
        return hints

    def _business_change_hint_for_evidence(
        self,
        evidence: EvidenceLedgerEntry,
        hints_by_requirement: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        hint_group = hints_by_requirement.get(evidence.requirement_id)
        if not hint_group:
            return None
        entity = str(hint_group.get("entity_type") or "").strip().lower()
        result_row = self._primary_result_row(evidence)
        record_id = self._record_id(result_row, entity=entity) or self._record_id(evidence.args, entity=entity)
        rows_by_record = hint_group.get("rows_by_record") if isinstance(hint_group.get("rows_by_record"), Mapping) else {}
        row_hint = dict(rows_by_record.get(record_id) or {}) if record_id else {}
        if not row_hint:
            row_hint = {
                "approval_id": hint_group.get("approval_id"),
                "entity_type": entity,
                "previous_priority": hint_group.get("source_priority"),
                "original_priority": hint_group.get("source_priority"),
                "new_priority": hint_group.get("target_priority"),
                "source_state_basis": "original" if hint_group.get("source_priority") else None,
            }
        row_hint["record_id"] = record_id or row_hint.get("record_id")
        row_hint["row_count"] = hint_group.get("row_count")
        return {key: value for key, value in row_hint.items() if value not in (None, "", [], {})}

    def _business_change_hint_from_row(
        self,
        row: Mapping[str, Any],
        *,
        entity: str,
        approval_id: Any,
        source_priority: Any,
        target_priority: Any,
        staged_args: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        staged_args = staged_args if isinstance(staged_args, Mapping) else {}
        source = (
            row.get("previous_priority")
            or row.get("original_priority")
            or row.get("source_priority")
            or row.get("priority")
            or source_priority
        )
        target = (
            row.get("new_priority")
            or row.get("target_priority")
            or staged_args.get("priority")
            or target_priority
        )
        source_text = str(source).strip().lower() if source not in (None, "", [], {}) else ""
        target_text = str(target).strip().lower() if target not in (None, "", [], {}) else ""
        hint = {
            "approval_id": approval_id,
            "_approval_id": approval_id,
            "entity_type": entity,
            "previous_priority": source_text,
            "original_priority": row.get("original_priority") or source_text,
            "new_priority": target_text,
            "source_state_basis": row.get("source_state_basis") or ("original" if source_text else None),
            "selector_summary": row.get("selector_summary") or (f"priority = {source_text}" if source_text else None),
            "business_change": row.get("business_change") or self._priority_change_label(source_text, target_text),
            "business_change_id": row.get("business_change_id"),
            "field_changes": row.get("field_changes")
            or (
                [{"field": "priority", "label": "Priority", "from": source_text, "to": target_text}]
                if source_text and target_text
                else None
            ),
        }
        return {key: value for key, value in hint.items() if value not in (None, "", [], {})}

    def _with_business_change_result_payload(
        self,
        payload: dict[str, Any],
        hint: Mapping[str, Any],
    ) -> dict[str, Any]:
        out = dict(payload)
        data = out.get("data")
        if isinstance(data, list):
            out["data"] = [
                self._with_business_change_row(row, hint)
                if isinstance(row, Mapping) and self._row_matches_hint(row, hint)
                else row
                for row in data
            ]
        elif isinstance(data, Mapping):
            out["data"] = self._with_business_change_row(data, hint)
        else:
            out["data"] = self._with_business_change_row({}, hint)
        if hint.get("approval_id"):
            out.setdefault("approval_id", hint.get("approval_id"))
            out.setdefault("_approval_id", hint.get("approval_id"))
        return out

    def _with_business_change_row(
        self,
        row: Mapping[str, Any],
        hint: Mapping[str, Any],
    ) -> dict[str, Any]:
        out = dict(row)
        if hint.get("record_id"):
            entity = str(hint.get("entity_type") or "").strip().lower()
            out.setdefault("record_id", hint["record_id"])
            out.setdefault("id", hint["record_id"])
            if entity:
                out.setdefault(f"{entity}_id", hint["record_id"])
        for key in (
            "approval_id",
            "_approval_id",
            "entity_type",
            "previous_priority",
            "original_priority",
            "new_priority",
            "source_state_basis",
            "selector_summary",
            "business_change",
            "business_change_id",
            "field_changes",
        ):
            if hint.get(key) not in (None, "", [], {}):
                out.setdefault(key, hint[key])
        return out

    def _business_change_summary(self, hint: Mapping[str, Any] | None) -> str | None:
        if not hint:
            return None
        source = str(hint.get("previous_priority") or hint.get("original_priority") or "").strip().lower()
        target = str(hint.get("new_priority") or "").strip().lower()
        try:
            count = int(hint.get("row_count") or 0)
        except (TypeError, ValueError):
            count = 0
        entity = str(hint.get("entity_type") or "record").strip().lower() or "record"
        if not (source and target and count > 0):
            return None
        noun = self._entity_noun(entity, count)
        return f"Updated {count} {source}-priority {noun} to {target}."

    def _primary_result_row(self, evidence: EvidenceLedgerEntry) -> dict[str, Any]:
        result = evidence.normalized_result if isinstance(evidence.normalized_result, dict) else {}
        fields = result.get("fields")
        if isinstance(fields, Mapping):
            return dict(fields)
        rows = result.get("rows")
        if isinstance(rows, list):
            first = next((row for row in rows if isinstance(row, Mapping)), None)
            if first is not None:
                return dict(first)
        return dict(result)

    def _record_id(self, row: Mapping[str, Any] | None, *, entity: str = "") -> str | None:
        if not isinstance(row, Mapping):
            return None
        keys = []
        if entity:
            keys.append(f"{entity}_id")
        keys.extend(["job_id", "machine_id", "product_id", "material_id", "record_id", "id", "row_id"])
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    def _row_matches_hint(self, row: Mapping[str, Any], hint: Mapping[str, Any]) -> bool:
        expected = str(hint.get("record_id") or "").strip()
        if not expected:
            return True
        entity = str(hint.get("entity_type") or "").strip().lower()
        return self._record_id(row, entity=entity) == expected

    def _staged_call_args_by_record(
        self,
        staged_calls: list[dict[str, Any]],
        *,
        entity: str,
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for call in staged_calls:
            args = call.get("args") if isinstance(call.get("args"), Mapping) else {}
            record_id = self._record_id(args, entity=entity)
            if record_id:
                out[record_id] = dict(args)
        return out

    def _source_priority_value(self, values: Mapping[str, Any]) -> str | None:
        raw = values.get("priority") or values.get("priority_from") or values.get("source_priority")
        if raw in (None, "", [], {}):
            return None
        return str(raw).strip().lower()

    def _target_priority_value(self, values: Mapping[str, Any]) -> str | None:
        raw = values.get("new_priority") or values.get("priority_to") or values.get("target_priority")
        if raw in (None, "", [], {}):
            return None
        return str(raw).strip().lower()

    def _priority_change_label(self, source: str, target: str) -> str | None:
        if not (source and target):
            return None
        return f"{source.title()} -> {target.title()}"

    def _entity_noun(self, entity: str, count: int) -> str:
        base = (entity or "record").strip().lower() or "record"
        if count == 1:
            return base
        if base.endswith("y"):
            return base[:-1] + "ies"
        if base.endswith("s"):
            return base
        return base + "s"

    def _step_result_payload(self, evidence: EvidenceLedgerEntry) -> dict[str, Any]:
        if evidence.source_of_truth == "document_knowledge":
            return {
                "answer": evidence.normalized_result.get("answer"),
                "sources": self._sources_from_evidence(evidence),
                "safety_content": evidence.normalized_result.get("safety_content"),
            }
        if "rows" in evidence.normalized_result:
            return {"data": evidence.normalized_result.get("rows")}
        if "fields" in evidence.normalized_result:
            return {"data": evidence.normalized_result.get("fields")}
        return dict(evidence.normalized_result)

    def _response_summary(self, result: PlannerOwnedGraphResult) -> str:
        diagnostics = result.state.response_document_context.diagnostics
        summary = str(diagnostics.get("summary") or "").strip()
        if summary:
            return summary
        if result.state.final_validation_result is not None and result.state.final_validation_result.status == "failed":
            return "The planner-owned graph could not produce a safe final result."
        return "Planner-owned graph execution completed."

    def _risk_summary(self, result: PlannerOwnedGraphResult) -> str:
        if result.state.pending_approval.status == "pending":
            return "Approval is required before the graph commits staged changes."
        if self._graph_failed(result, self._tool_outputs(result)):
            return "The planner-owned graph finished with a safe failure."
        return "Planner-owned graph execution used typed evidence and final validation."

    def _graph_failed(
        self,
        result: PlannerOwnedGraphResult,
        tool_outputs: list[dict[str, Any]],
    ) -> bool:
        final_validation = result.state.final_validation_result
        if final_validation is not None and final_validation.status == "failed":
            return True
        for output in tool_outputs:
            result_payload = output.get("result") if isinstance(output, dict) else {}
            result_payload = result_payload if isinstance(result_payload, dict) else {}
            if output.get("status") == "FAILED" or result_payload.get("error"):
                return True
        return False

    def _is_document_only(self, result: PlannerOwnedGraphResult) -> bool:
        evidence = list(result.state.evidence_ledger.evidence)
        return bool(evidence) and all(item.source_of_truth == "document_knowledge" for item in evidence)

    def _sources(self, state: Any) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for evidence in state.evidence_ledger.evidence:
            sources.extend(self._sources_from_evidence(evidence))
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source in sources:
            key = str(source.get("source_id") or source.get("doc_id") or source)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(source)
        return deduped

    def _sources_from_evidence(self, evidence: EvidenceLedgerEntry) -> list[dict[str, Any]]:
        raw_sources = evidence.normalized_result.get("sources") or evidence.normalized_result.get("sources_checked") or []
        if isinstance(raw_sources, list):
            return [dict(source) for source in raw_sources if isinstance(source, dict)]
        return [
            {
                "source_id": citation.source_id,
                "doc_id": citation.doc_id,
                "chunk_id": citation.chunk_id,
                "title": citation.title,
                **dict(citation.locator or {}),
            }
            for citation in evidence.citations
        ]

    def _safety_content(self, state: Any) -> str | None:
        for evidence in state.evidence_ledger.evidence:
            safety_content = evidence.normalized_result.get("safety_content")
            if isinstance(safety_content, str) and safety_content.strip():
                return safety_content.strip()
        return None

    def _evidence_failed(self, evidence: EvidenceLedgerEntry) -> bool:
        result = evidence.normalized_result if isinstance(evidence.normalized_result, dict) else {}
        return bool(result.get("error")) or str(result.get("status") or "").lower() in {"tool_failed", "failed"}

    def _requirement_by_id(self, state: Any, requirement_id: str) -> Any | None:
        ledger = getattr(state, "requirement_ledger", None)
        for requirement in list(getattr(ledger, "requirements", []) or []):
            if str(getattr(requirement, "id", "") or "") == requirement_id:
                return requirement
        return None

    def _approval_tool_name(self, payload: Mapping[str, Any]) -> str:
        selected_call = payload.get("selected_graph_tool_call")
        if isinstance(selected_call, Mapping):
            tool_name = str(selected_call.get("tool_name") or "").strip()
            if tool_name:
                return tool_name
        return "__planner_owned_agent_graph__"

    def _approval_side_effect_level(
        self,
        payload: Mapping[str, Any],
        tools_by_name: Mapping[str, ToolInfo],
    ) -> str:
        tool = tools_by_name.get(self._approval_tool_name(payload))
        if tool is not None and str(tool.side_effect_level or "").strip():
            return str(tool.side_effect_level)
        return "HIGH"

    def llm_call_count(self, result: PlannerOwnedGraphResult) -> int:
        reranker = result.state.execution_trace.tool_retrieval.reranker
        try:
            return max(0, int(getattr(reranker, "call_count", 0) or 0))
        except Exception:
            return 0
