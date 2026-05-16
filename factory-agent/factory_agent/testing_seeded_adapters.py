from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from factory_agent.config import Settings
from factory_agent.observability.telemetry import log_event
from factory_agent.planner import PlannerApprovalRequired
from factory_agent.schemas import PlanDraft, PlanStepDraft, ToolInfo
from factory_agent.services.planner_service import PlannerResult


@dataclass(frozen=True)
class _FakeRagResult:
    answer: str
    sources: list[dict[str, Any]]
    safety_content: str | None = None


class SeededPlaywrightRAGPipeline:
    async def run(self, *, query: str, session_id: str | None = None, route: str = "RAG_ONLY", api_data: Any = None):
        del session_id, route, api_data
        lowered = query.lower()
        if "no-source" in lowered or "no source" in lowered or "unavailable source" in lowered:
            return _FakeRagResult(
                answer=(
                    "Controlled seeded RAG fallback: I do not have an available cited source for this question, "
                    "so I can only give a cautious general answer. Verify the site procedure before acting."
                ),
                sources=[],
                safety_content="No retrievable seeded source was available for this Playwright hard-scenario answer.",
            )
        return _FakeRagResult(
            answer=(
                "Controlled seeded RAG answer: LOTO means isolating hazardous energy, locking and tagging "
                "energy-isolating devices, verifying zero energy, and following the site procedure before work begins. [1]"
            ),
            sources=[
                {
                    "source_number": 1,
                    "doc_id": "seeded-loto-procedure",
                    "title": "Seeded LOTO Procedure",
                    "organization": "eMas Safety",
                    "authority_level": "controlled_test_fixture",
                    "license": "internal-test",
                }
            ],
            safety_content="Controlled fake RAG output for Playwright L3; do not treat as live safety guidance.",
        )


class SeededPlaywrightPlanner:
    """Deterministic L3 planner that calls the seeded Go API but never calls an LLM."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._calls_by_session: dict[str, int] = {}
        self._scenario_by_session: dict[str, str] = {}
        self._approval_counts_by_session: dict[str, int] = {}

    def _scenario_for_resume(self, session_id: str) -> str | None:
        scenario = self._scenario_by_session.get(session_id)
        if scenario:
            return scenario
        # Focused seeded runs can miss session_id on the interrupted planner
        # call. Transfer that orphaned marker to the concrete approval session.
        scenario = self._scenario_by_session.get("")
        if scenario:
            self._scenario_by_session[session_id] = scenario
            return scenario
        return None

    def seed_resume_context(
        self,
        *,
        session_id: str,
        intent: str,
        approval_payload: dict[str, Any] | None = None,
    ) -> None:
        payload = approval_payload if isinstance(approval_payload, dict) else {}
        bundle_ui = payload.get("bundle_ui") if isinstance(payload.get("bundle_ui"), dict) else {}
        if "phase 9 multi approval chain" in intent.lower() or bundle_ui.get("kind") == "phase9_approval_chain":
            self._scenario_by_session[session_id] = "multi_approval_chain"
            self._approval_counts_by_session.setdefault(session_id, 0)
            log_event(
                "playwright_seeded_multi_approval_seeded",
                session_id=session_id,
                scenario=self._scenario_by_session.get(session_id),
                count=self._approval_counts_by_session.get(session_id),
            )

    async def generate_plan(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        context: dict[str, Any] | None = None,
    ) -> PlannerResult:
        lowered = intent.lower()
        session_id = str((context or {}).get("session_id") or "")
        call_index = self._calls_by_session.get(session_id, 0) + 1
        if session_id:
            self._calls_by_session[session_id] = call_index

        if "phase 9 multi-step ordered" in lowered:
            self._scenario_by_session[session_id] = "multi_step_ordered"
            return await self._multi_step_ordered(intent=intent, scoped_tools=scoped_tools)

        if "phase 9 multi approval chain" in lowered:
            self._scenario_by_session[session_id] = "multi_approval_chain"
            self._approval_counts_by_session[session_id] = 0
            log_event(
                "playwright_seeded_multi_approval_started",
                session_id=session_id,
                scenario=self._scenario_by_session.get(session_id),
            )
            raise PlannerApprovalRequired(
                "Seeded first approval required.",
                approval={
                    "summary": "Phase 9 multi-approval chain: first approval is required before supervisor review.",
                    "count": 1,
                    "preview": [
                        {
                            "tool_name": "phase9_first_approval_gate",
                            "args": {"stage": "operator_review", "next_stage": "supervisor_review"},
                        }
                    ],
                    "bundle_ui": {
                        "kind": "phase9_approval_chain",
                        "headline": "First approval required before the seeded chain can continue.",
                        "rows": [
                            {
                                "approval_stage": "operator_review",
                                "status": "pending",
                                "next_stage": "supervisor_review",
                            }
                        ],
                    },
                },
            )

        if "phase 9 approval timeout" in lowered:
            self._scenario_by_session[session_id] = "approval_timeout"
            raise PlannerApprovalRequired(
                "Seeded approval timeout fixture.",
                approval={
                    "summary": "Phase 9 approval timeout: the job is waiting safely and must not continue without a decision.",
                    "count": 1,
                    "preview": [
                        {
                            "tool_name": "phase9_timeout_gate",
                            "args": {"timeout_state": "expired_visible_safe"},
                        }
                    ],
                    "bundle_ui": {
                        "kind": "phase9_timeout_gate",
                        "headline": "Approval timed out; execution remains paused and visible.",
                        "rows": [
                            {
                                "approval_stage": "operator_timeout",
                                "status": "timed_out",
                                "hidden_continuation": "no",
                            }
                        ],
                    },
                    "expires_in_seconds": -1,
                },
            )

        if "phase 9 partial failure" in lowered:
            self._scenario_by_session[session_id] = "partial_failure"
            return await self._partial_failure(intent=intent, scoped_tools=scoped_tools)

        if "phase 9 schema mismatch" in lowered:
            self._scenario_by_session[session_id] = "schema_mismatch"
            return self._schema_mismatch(intent=intent, scoped_tools=scoped_tools)

        if "phase 9 duplicate submit" in lowered:
            self._scenario_by_session[session_id] = "duplicate_submit"
            if call_index == 1:
                return self._draft_only(
                    intent=intent,
                    scoped_tools=scoped_tools,
                    tool_name="get__machines_{id}",
                    args={"id": "M-CNC-01"},
                    summary="Phase 9 duplicate-submit run is staged and ready to execute.",
                )
            await asyncio.sleep(0.8)
            return await self._machine_status(intent=intent, scoped_tools=scoped_tools)

        if "phase 9 out-of-order duplicate sse" in lowered:
            self._scenario_by_session[session_id] = "out_of_order_sse"
            if call_index == 1:
                return self._draft_only(
                    intent=intent,
                    scoped_tools=scoped_tools,
                    tool_name="get__jobs",
                    args={"priority": "low", "limit": 2},
                    summary="Phase 9 out-of-order SSE run is staged.",
                )
            await asyncio.sleep(1.2)
            return await self._multi_step_ordered(intent=intent, scoped_tools=scoped_tools)

        if "phase 9 last-event-id reconnect" in lowered:
            self._scenario_by_session[session_id] = "last_event_id_reconnect"
            if call_index == 1:
                return self._draft_only(
                    intent=intent,
                    scoped_tools=scoped_tools,
                    tool_name="get__machines_{id}",
                    args={"id": "M-CNC-01"},
                    summary="Phase 9 reconnect run is staged.",
                )
            await asyncio.sleep(5.0)
            return await self._machine_status(intent=intent, scoped_tools=scoped_tools)

        if "phase 9 stream drop recovery" in lowered:
            self._scenario_by_session[session_id] = "stream_drop_recovery"
            if call_index == 1:
                return self._draft_only(
                    intent=intent,
                    scoped_tools=scoped_tools,
                    tool_name="get__machines_{id}",
                    args={"id": "M-CNC-01"},
                    summary="Phase 9 stream-drop recovery run is staged.",
                )
            await asyncio.sleep(4.5)
            return await self._completed_with_summary(
                intent=intent,
                scoped_tools=scoped_tools,
                tool_name="get__machines_{id}",
                args={"id": "M-CNC-01"},
                result={"data": {"machine_id": "M-CNC-01", "status": "RUNNING"}},
                summary="Phase 9 stream drop recovered by snapshot polling.",
                risk="Read-only seeded stream-drop recovery fixture.",
            )

        if "phase 9 large structured result" in lowered:
            self._scenario_by_session[session_id] = "large_structured_result"
            return await self._large_structured_result(intent=intent, scoped_tools=scoped_tools)

        if "phase 9 isolation alpha" in lowered:
            self._scenario_by_session[session_id] = "isolation_alpha"
            return await self._completed_with_summary(
                intent=intent,
                scoped_tools=scoped_tools,
                tool_name="get__machines_{id}",
                args={"id": "M-CNC-01"},
                result={"data": {"machine_id": "M-CNC-01", "status": "RUNNING", "isolation": "alpha"}},
                summary="Phase 9 isolation alpha session completed without beta data.",
                risk="Read-only seeded isolation fixture.",
            )

        if "phase 9 isolation beta" in lowered:
            self._scenario_by_session[session_id] = "isolation_beta"
            return await self._completed_with_summary(
                intent=intent,
                scoped_tools=scoped_tools,
                tool_name="get__machines_{id}",
                args={"id": "M-CNC-02"},
                result={"data": {"machine_id": "M-CNC-02", "status": "IDLE", "isolation": "beta"}},
                summary="Phase 9 isolation beta session completed without alpha data.",
                risk="Read-only seeded isolation fixture.",
            )

        if "approval" in lowered or ("low priority" in lowered and "high priority" in lowered):
            self._scenario_by_session[session_id] = "priority_approval"
            if call_index == 1:
                jobs = await self._get_json("/jobs", params={"priority": "low", "fields": "job_id,priority,product_id,status,deadline", "limit": 2})
                rows = self._rows(jobs)[:2]
                if not rows:
                    rows = [{"job_id": "JOB-SEED-005", "priority": "low", "product_id": "P-005", "status": "planned"}]
                preview = [
                    {
                        "tool_name": "put__jobs_{id}",
                        "args": {"id": row.get("job_id"), "priority": "high"},
                    }
                    for row in rows
                ]
                raise PlannerApprovalRequired(
                    "Seeded approval required.",
                    approval={
                        "summary": f"{len(preview)} seeded low-priority job(s) require approval before priority changes.",
                        "count": len(preview),
                        "preview": preview,
                        "bundle_ui": {
                            "kind": "job_priority_bundle",
                            "headline": f"{len(preview)} job(s) will be updated from LOW to HIGH priority.",
                            "rows": [
                                {
                                    "job_id": row.get("job_id"),
                                    "previous_priority": row.get("priority"),
                                    "new_priority": "high",
                                }
                                for row in rows
                            ],
                            "previous_priority": "low",
                            "new_priority": "high",
                        },
                    },
                )
            return await self._approved_priority_update(intent=intent, scoped_tools=scoped_tools)

        if "cancel" in lowered:
            if call_index == 1:
                return self._draft_only(
                    intent=intent,
                    scoped_tools=scoped_tools,
                    tool_name="get__jobs",
                    args={"priority": "low", "limit": 1},
                    summary="Seeded cancellable run is staged and ready to execute.",
                )
            await asyncio.sleep(30)
            return await self._low_priority_jobs(intent=intent, scoped_tools=scoped_tools)

        if "sse" in lowered or "activity" in lowered or "stream" in lowered:
            if call_index == 1:
                return self._draft_only(
                    intent=intent,
                    scoped_tools=scoped_tools,
                    tool_name="get__machines_{id}",
                    args={"id": "M-CNC-01"},
                    summary="Seeded SSE run is staged and ready to execute.",
                )
            await asyncio.sleep(1.2)
            return await self._machine_status(intent=intent, scoped_tools=scoped_tools)

        if "low priority" in lowered or ("priority" in lowered and "jobs" in lowered):
            return await self._low_priority_jobs(intent=intent, scoped_tools=scoped_tools)

        return await self._machine_status(intent=intent, scoped_tools=scoped_tools)

    async def resume_after_approval(self, *, session_id: str, approved: bool) -> PlannerResult:
        if not approved:
            return self._rejected_noop_result()
        scenario = self._scenario_for_resume(session_id)
        log_event(
            "playwright_seeded_resume_after_approval",
            session_id=session_id,
            approved=approved,
            scenario=scenario,
            count=self._approval_counts_by_session.get(session_id),
        )
        if scenario == "multi_approval_chain":
            count = self._approval_counts_by_session.get(session_id, 0) + 1
            self._approval_counts_by_session[session_id] = count
            if count == 1:
                raise PlannerApprovalRequired(
                    "Seeded second approval required.",
                    approval={
                        "summary": "Phase 9 multi-approval chain: second supervisor approval is required before final execution.",
                        "count": 1,
                        "preview": [
                            {
                                "tool_name": "phase9_second_approval_gate",
                                "args": {"stage": "supervisor_review", "next_stage": "final_execution"},
                            }
                        ],
                        "bundle_ui": {
                            "kind": "phase9_approval_chain",
                            "headline": "Second approval required before final execution.",
                            "rows": [
                                {
                                    "approval_stage": "supervisor_review",
                                    "status": "pending",
                                    "next_stage": "final_execution",
                                }
                            ],
                        },
                    },
                )
            return await self._multi_approval_completed()
        return await self._approved_priority_update(
            intent="Approved seeded low-priority jobs to high priority.",
            scoped_tools=[],
        )

    def _pick_tool(self, scoped_tools: list[ToolInfo], preferred: str) -> str:
        names = {tool.name for tool in scoped_tools}
        if preferred in names or not scoped_tools:
            return preferred
        return scoped_tools[0].name

    def _read_tool(self, scoped_tools: list[ToolInfo], preferred: str = "get__jobs") -> str:
        for tool in scoped_tools:
            if tool.name == preferred:
                return tool.name
        for tool in scoped_tools:
            if str(getattr(tool, "method", "")).upper() == "GET":
                return tool.name
        return preferred

    def _plan_result(
        self,
        *,
        explanation: str,
        risk: str,
        steps: list[PlanStepDraft],
        tool_outputs: list[dict[str, Any]] | None = None,
    ) -> PlannerResult:
        return PlannerResult(
            draft=PlanDraft(plan_explanation=explanation, risk_summary=risk, steps=steps),
            backend_used="langgraph",
            llm_calls=0,
            tool_outputs=tool_outputs or [],
        )

    async def _machine_status(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        body = await self._get_json("/machines/M-CNC-01")
        data = self._data(body)
        status = data.get("status") or data.get("Status") or "unknown"
        name = data.get("machine_name") or data.get("MachineName") or "CNC Mill 01"
        summary = f"Machine M-CNC-01 ({name}) is {status} in the seeded Go API data."
        return self._completed(
            intent=intent,
            tool_name=self._tool_name(scoped_tools, "get__machines_{id}"),
            args={"id": "M-CNC-01"},
            result=body,
            summary=summary,
            explanation=summary,
            risk="Read-only seeded machine lookup.",
        )

    async def _low_priority_jobs(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        body = await self._get_json(
            "/jobs",
            params={
                "priority": "low",
                "fields": "job_id,priority,product_id,status,deadline",
                "sort_by": "deadline",
                "sort_dir": "asc",
                "limit": 5,
            },
        )
        rows = self._rows(body)
        ids = [str(row.get("job_id") or row.get("id")) for row in rows if row.get("job_id") or row.get("id")]
        summary = f"Found {len(rows)} low-priority seeded jobs: {', '.join(ids[:5])}. Details are shown in the table below."
        return self._completed(
            intent=intent,
            tool_name=self._tool_name(scoped_tools, "get__jobs"),
            args={"priority": "low", "fields": "job_id,priority,product_id,status,deadline", "sort_by": "deadline", "sort_dir": "asc", "limit": 5},
            result=body,
            summary=summary,
            explanation=summary,
            risk="Read-only seeded job list lookup.",
        )

    async def _multi_step_ordered(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        tool_name = self._read_tool(scoped_tools, "get__jobs")
        jobs = await self._get_json(
            "/jobs",
            params={"priority": "low", "fields": "job_id,priority,product_id,status,deadline", "limit": 3},
        )
        rows = self._rows(jobs)[:3]
        if not rows:
            rows = [{"job_id": "JOB-SEED-005", "priority": "low", "status": "planned"}]
        overdue = [row for row in rows if str(row.get("status") or "").lower() in {"delayed", "planned"}]
        summary_rows = [
            {
                "job_id": row.get("job_id") or row.get("id"),
                "priority": row.get("priority"),
                "rule": "expedite" if row in overdue else "monitor",
            }
            for row in rows
        ]
        steps = [
            PlanStepDraft(step_index=0, tool_name=tool_name, args={"priority": "low", "limit": 3}),
            PlanStepDraft(step_index=1, tool_name=tool_name, args={"priority": "low", "status": "planned", "limit": 3}, depends_on=[0]),
            PlanStepDraft(step_index=2, tool_name=tool_name, args={"priority": "low", "fields": "job_id,priority,status", "limit": 3}, depends_on=[1]),
        ]
        return self._plan_result(
            explanation="Phase 9 plan: plan, read seeded data, apply business rule, summarize.",
            risk="Read-only seeded multi-step orchestration fixture.",
            steps=steps,
            tool_outputs=[
                {
                    "tool_name": tool_name,
                    "args": steps[0].args,
                    "result": {"data": rows},
                    "http_status": 200,
                    "summary": "Phase 9 step 2 read seeded data: low-priority jobs loaded from the seeded Go API.",
                    "status": "DONE",
                },
                {
                    "tool_name": tool_name,
                    "args": steps[1].args,
                    "result": {"data": summary_rows},
                    "http_status": 200,
                    "summary": "Phase 9 step 3 apply business rule: overdue or planned low-priority jobs were marked for expedite review.",
                    "status": "DONE",
                },
                {
                    "tool_name": tool_name,
                    "args": steps[2].args,
                    "result": {"data": summary_rows, "rule_applied": True},
                    "http_status": 200,
                    "summary": f"Phase 9 step 4 summarize: {len(summary_rows)} seeded job(s) evaluated in ordered sequence.",
                    "status": "DONE",
                },
            ],
        )

    async def _partial_failure(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        tool_name = self._pick_tool(scoped_tools, "get__machines_{id}")
        jobs = await self._get_json("/jobs", params={"priority": "low", "limit": 1})
        rows = self._rows(jobs)[:1] or [{"job_id": "JOB-SEED-005", "priority": "low"}]
        steps = [
            PlanStepDraft(step_index=0, tool_name=tool_name, args={"id": "M-CNC-01"}),
            PlanStepDraft(step_index=1, tool_name=tool_name, args={"id": "M-CNC-02"}, depends_on=[0]),
            PlanStepDraft(step_index=2, tool_name=tool_name, args={"id": "M-CNC-03"}, depends_on=[1]),
        ]
        return self._plan_result(
            explanation="Phase 9 partial failure plan: step 1 succeeds, step 2 fails, step 3 must not run.",
            risk="Read-only seeded partial failure fixture.",
            steps=steps,
            tool_outputs=[
                {
                    "tool_name": tool_name,
                    "args": steps[0].args,
                    "result": {"data": rows},
                    "http_status": 200,
                    "summary": "Phase 9 partial failure step 1 succeeded.",
                    "status": "DONE",
                },
                {
                    "tool_name": tool_name,
                    "args": steps[1].args,
                    "result": {"error": "phase9_forced_partial_failure"},
                    "http_status": 422,
                    "summary": "Phase 9 partial failure step 2 failed safely.",
                    "status": "FAILED",
                    "last_error": "Phase 9 forced failure at step 2; step 3 must not run.",
                },
            ],
        )

    def _schema_mismatch(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        tool_name = self._pick_tool(scoped_tools, "get__machines_{id}")
        return self._plan_result(
            explanation="Phase 9 schema mismatch plan: intentionally malformed tool payload.",
            risk="Seeded schema mismatch fixture should return a safe validation error.",
            steps=[
                PlanStepDraft(
                    step_index=0,
                    tool_name=tool_name,
                    args={"id": {"malformed": True}},
                )
            ],
        )

    async def _large_structured_result(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        del intent
        tool_name = self._read_tool(scoped_tools, "get__jobs")
        rows = [
            {
                "job_id": f"JOB-SEED-LARGE-{idx:03d}",
                "priority": "low" if idx % 2 else "medium",
                "status": "planned" if idx % 3 else "ready",
                "deadline": f"2026-05-{(idx % 28) + 1:02d}",
                "rule": "expedite" if idx % 5 == 0 else "monitor",
            }
            for idx in range(1, 81)
        ]
        return await self._completed_with_summary(
            intent="Phase 9 large structured result",
            scoped_tools=scoped_tools,
            tool_name=tool_name,
            args={"priority": "low", "limit": 80},
            result={"data": rows, "total": len(rows)},
            summary="Phase 9 large structured result rendered 80 seeded rows without losing completion state.",
            risk="Read-only seeded large-result fixture.",
        )

    async def _approved_priority_update(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        jobs = await self._get_json("/jobs", params={"priority": "low", "fields": "job_id,priority,product_id,status,deadline", "limit": 1})
        rows = self._rows(jobs)
        job_id = str((rows[0] if rows else {}).get("job_id") or "JOB-SEED-005")
        updated = await self._put_json(f"/jobs/{job_id}", json={"priority": "high"})
        summary = f"Approved seeded change completed: {job_id} is now high priority."
        return self._completed(
            intent=intent,
            tool_name=self._tool_name(scoped_tools, "put__jobs_{id}"),
            args={"id": job_id, "priority": "high"},
            result=updated,
            summary=summary,
            explanation=summary,
            risk="Approved seeded write performed by deterministic fake provider.",
        )

    async def _multi_approval_completed(self) -> PlannerResult:
        updated = await self._put_json("/jobs/JOB-SEED-005", json={"priority": "high"})
        return self._completed(
            intent="Phase 9 multi approval final execution",
            tool_name="put__jobs_{id}",
            args={"id": "JOB-SEED-005", "priority": "high"},
            result=updated,
            summary="Phase 9 multi-approval final execution completed after two approvals.",
            explanation="Phase 9 multi-approval chain completed only after both approvals.",
            risk="Approved seeded write performed after two deterministic approval gates.",
        )

    def _rejected_noop_result(self) -> PlannerResult:
        return PlannerResult(
            draft=PlanDraft(
                plan_explanation="Approval was rejected; no later seeded steps were executed.",
                risk_summary="Rejected seeded approval stopped the chain safely.",
                steps=[],
            ),
            backend_used="langgraph",
            llm_calls=0,
            tool_outputs=[],
        )

    async def _completed_with_summary(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        summary: str,
        risk: str,
    ) -> PlannerResult:
        return self._completed(
            intent=intent,
            tool_name=self._tool_name(scoped_tools, tool_name),
            args=args,
            result=result,
            summary=summary,
            explanation=summary,
            risk=risk,
        )

    def _draft_only(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        tool_name: str,
        args: dict[str, Any],
        summary: str,
    ) -> PlannerResult:
        resolved_tool_name = self._tool_name(scoped_tools, tool_name)
        draft = PlanDraft(
            plan_explanation=summary,
            risk_summary="Seeded L3 test draft; execution is intentionally backgrounded.",
            steps=[PlanStepDraft(step_index=0, tool_name=resolved_tool_name, args=args)],
        )
        return PlannerResult(draft=draft, backend_used="seeded-fake", llm_calls=0, tool_outputs=[])

    def _completed(
        self,
        *,
        intent: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        summary: str,
        explanation: str,
        risk: str,
    ) -> PlannerResult:
        draft = PlanDraft(
            plan_explanation=explanation,
            risk_summary=risk,
            steps=[PlanStepDraft(step_index=0, tool_name=tool_name, args=args)],
        )
        return PlannerResult(
            draft=draft,
            backend_used="langgraph",
            llm_calls=0,
            tool_outputs=[
                {
                    "tool_name": tool_name,
                    "args": args,
                    "result": result,
                    "http_status": 200,
                    "summary": summary,
                    "status": "DONE",
                }
            ],
        )

    def _tool_name(self, scoped_tools: list[ToolInfo], preferred: str) -> str:
        names = {tool.name for tool in scoped_tools}
        if preferred in names or not scoped_tools:
            return preferred
        return scoped_tools[0].name

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._settings.http_timeout_s) as client:
            resp = await client.get(f"{self._settings.go_api_base_url}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def _put_json(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._settings.http_timeout_s) as client:
            resp = await client.put(f"{self._settings.go_api_base_url}{path}", json=json)
            resp.raise_for_status()
            return resp.json()

    def _data(self, body: dict[str, Any]) -> dict[str, Any]:
        data = body.get("data") if isinstance(body, dict) else None
        return data if isinstance(data, dict) else body

    def _rows(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(body.get("items"), list):
            return [row for row in body["items"] if isinstance(row, dict)]
        return []
