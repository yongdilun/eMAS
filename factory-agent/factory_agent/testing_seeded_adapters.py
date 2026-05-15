from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from factory_agent.config import Settings
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

        if "approval" in lowered or ("low priority" in lowered and "high priority" in lowered):
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
            raise RuntimeError("Seeded Playwright planner received rejection.")
        return await self._approved_priority_update(
            intent="Approved seeded low-priority jobs to high priority.",
            scoped_tools=[],
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
