from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import httpx

from factory_agent.config import Settings
from factory_agent.observability.telemetry import log_event
from factory_agent.planning.intent import intent_constraint_values, semantic_frame_for_text, split_user_intents
from factory_agent.planning.query_shape import infer_collection_query_args, merge_inferred_read_args, parse_fields_arg
from factory_agent.planner import PlannerApprovalRequired
from factory_agent.rag.source_metadata import insufficient_context_answer
from factory_agent.schemas import PlanDraft, PlanStepDraft, ToolInfo
from factory_agent.services.planner_service import PlannerResult
from factory_agent.testing_seeded_scenarios import SeededScenarioInterpreter

_JOB_ID_RE = re.compile(r"\bJOB-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)


@dataclass(frozen=True)
class _FakeRagResult:
    answer: str
    sources: list[dict[str, Any]]
    safety_content: str | None = None


def _is_osha_reenergizing_notification_query(lowered: str) -> bool:
    return (
        "osha" in lowered
        and "lockout" in lowered
        and "tagout" in lowered
        and "notification" in lowered
        and "reenerg" in lowered
        and "removing" in lowered
    )


def _is_osha_before_starting_lockout_notification_query(lowered: str) -> bool:
    return (
        "osha" in lowered
        and "lockout" in lowered
        and "tagout" in lowered
        and "notification" in lowered
        and "before starting lockout" in lowered
    )


def _osha_reenergizing_source() -> dict[str, Any]:
    return {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0029",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "osha_3120_lockout_tagout_c0029",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": (
            "After removing lockout or tagout devices but before reenergizing the machine, "
            "the employer must assure that employees know the devices have been removed and "
            "that the machine is capable of being reenergized."
        ),
        "authority_level": "official_public_guidance",
        "license": "public",
        "page": 15,
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "char_range": [0, 1017],
        "text_search": "After removing the lockout or tagout devices but before reenergizing the machine",
    }


def _osha_before_starting_related_source() -> dict[str, Any]:
    return {
        "source_number": 1,
        "source_id": "osha_3120_lockout_tagout#osha_3120_lockout_tagout_c0028",
        "doc_id": "osha_3120_lockout_tagout",
        "chunk_id": "osha_3120_lockout_tagout_c0028",
        "title": "Control of Hazardous Energy Lockout/Tagout",
        "organization": "OSHA",
        "snippet": (
            "Before beginning service or maintenance, OSHA lists preparation, shutdown, isolation, "
            "applying lockout or tagout devices, controlling stored energy, and verifying deenergization."
        ),
        "authority_level": "official_public_guidance",
        "license": "public",
        "page": 14,
        "pdf_url": "/documents/osha_3120_lockout_tagout/pdf",
        "text_search": "Before beginning service or maintenance, the following steps must be accomplished in sequence",
    }


class SeededPlaywrightRAGPipeline:
    async def run(self, *, query: str, session_id: str | None = None, route: str = "RAG_ONLY", api_data: Any = None):
        del session_id, route, api_data
        lowered = query.lower()
        machine_ids = intent_constraint_values(query, "machine_id")
        job_ids = intent_constraint_values(query, "job_id")
        if not job_ids:
            job_ids = [match.group(0).upper() for match in _JOB_ID_RE.finditer(query)]
        requested_machine_id = machine_ids[0] if machine_ids else None
        requested_job_id = job_ids[0] if job_ids else None
        semantic_frame = semantic_frame_for_text(query)
        no_source_requested = "no-source" in lowered or "no source" in lowered or "unavailable source" in lowered
        if no_source_requested or requested_machine_id == "M-CNC-02":
            subject = (
                f"machine {requested_machine_id} exists in seeded data, but "
                if requested_machine_id
                else ""
            )
            source_target = f"{requested_machine_id} LOTO" if requested_machine_id else "the requested maintenance procedure"
            return _FakeRagResult(
                answer=(
                    f"Controlled seeded RAG fallback: {subject}"
                    "I do not have an available cited LOTO source for that machine/procedure. "
                    f"No retrievable seeded source was available for {source_target} in this Playwright answer. "
                    "Verify the site procedure before acting."
                ),
                sources=[],
                safety_content=(
                    f"No retrievable seeded source was available for {source_target} in this Playwright answer."
                ),
            )
        if requested_machine_id is None:
            if _is_osha_reenergizing_notification_query(lowered):
                return _FakeRagResult(
                    answer=(
                        "Before reenergizing, notify affected employees who operate or work with the machine "
                        "and employees in the service area that the lockout or tagout devices have been removed "
                        "and that the machine can be reenergized [1]."
                    ),
                    sources=[_osha_reenergizing_source()],
                    safety_content=(
                        "This topic involves high-risk industrial procedures. Follow your site's approved SOP."
                    ),
                )
            if _is_osha_before_starting_lockout_notification_query(lowered):
                return _FakeRagResult(
                    answer=insufficient_context_answer(has_sources=True),
                    sources=[_osha_before_starting_related_source()],
                    safety_content="LOTO is safety-critical. Follow your site's approved energy-control procedure.",
                )
            if semantic_frame.domain_intent == "loto_procedure" and "machine_id" in semantic_frame.missing_required_entities:
                return _FakeRagResult(
                    answer=(
                        "Controlled seeded RAG cannot return a machine-specific LOTO procedure "
                        "without an exact machine ID."
                    ),
                    sources=[],
                    safety_content=(
                        "No machine ID was provided for the seeded machine-specific LOTO lookup."
                    ),
                )
            return _FakeRagResult(
                answer=(
                    "Controlled seeded RAG answer: Lockout/Tagout controls hazardous energy during "
                    "servicing or maintenance under OSHA's Control of Hazardous Energy Lockout/Tagout "
                    "standard, 29 CFR 1910.147. Use the site-approved procedure for the specific equipment. [1]"
                ),
                sources=[
                    {
                        "source_number": 1,
                        "source_id": "seeded-general-loto-guidance#seeded-general-loto-guidance_c0000",
                        "doc_id": "seeded-general-loto-guidance",
                        "chunk_id": "seeded-general-loto-guidance_c0000",
                        "title": "Seeded General LOTO Guidance",
                        "organization": "eMas Safety",
                        "snippet": (
                            "Lockout/Tagout controls hazardous energy during servicing or maintenance. "
                            "Seeded guidance references OSHA Control of Hazardous Energy Lockout/Tagout "
                            "and 29 CFR 1910.147 for release proof."
                        ),
                        "authority_level": "controlled_test_fixture",
                        "license": "internal-test",
                    }
                ],
                safety_content="Controlled fake RAG output for Playwright L3; verify the site procedure before acting.",
            )
        job_fragment = f" for {requested_job_id}" if requested_job_id else ""
        doc_id = f"seeded-loto-procedure-{requested_machine_id.lower()}"
        chunk_id = f"{doc_id}_c0000"
        return _FakeRagResult(
            answer=(
                f"Controlled seeded RAG answer: the LOTO procedure for {requested_machine_id}{job_fragment} requires "
                "isolating hazardous energy, locking and tagging energy-isolating devices, verifying zero energy, "
                "and following the site procedure before work begins. [1]"
            ),
            sources=[
                {
                    "source_number": 1,
                    "source_id": f"{doc_id}#{chunk_id}",
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "title": f"Seeded LOTO Procedure for {requested_machine_id}",
                    "organization": "eMas Safety",
                    "snippet": (
                        "The seeded LOTO procedure requires isolating hazardous energy, locking and tagging "
                        "energy-isolating devices, and verifying zero energy before work begins."
                    ),
                    "authority_level": "controlled_test_fixture",
                    "license": "internal-test",
                    "machine_id": requested_machine_id,
                    "procedure_id": f"LOTO-{requested_machine_id}",
                    **({"job_id": requested_job_id} if requested_job_id else {}),
                }
            ],
            safety_content=f"Controlled fake RAG output for Playwright L3; verify the {requested_machine_id} site procedure before acting.",
        )


class SeededPlaywrightPlanner:
    """Deterministic L3 planner that calls the seeded Go API but never calls an LLM."""

    is_seeded_playwright_adapter = True

    def __init__(self, settings: Settings):
        self._settings = settings
        self._calls_by_session: dict[str, int] = {}
        self._scenario_by_session: dict[str, str] = {}
        self._approval_counts_by_session: dict[str, int] = {}
        self._phase14_state_by_session: dict[str, dict[str, Any]] = {}
        self._data_integrity_audit: list[dict[str, Any]] = []
        self._scenario_interpreter = SeededScenarioInterpreter()

    def handles_seeded_intent(self, intent: str) -> bool:
        if self._scenario_interpreter.handles_intent(intent):
            return True
        lowered = (intent or "").lower()
        return "seeded" in lowered and any(token in lowered for token in ("cancel", "sse", "activity", "stream"))

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
        bundle_kind = str(bundle_ui.get("kind") or "")
        approval_id = str(payload.get("_approval_id") or payload.get("approval_id") or "").strip()
        scenario_marker = self._scenario_interpreter.marker_for_bundle_kind(bundle_kind)
        if scenario_marker and scenario_marker != "multi_approval_chain":
            self._scenario_by_session[session_id] = scenario_marker
            state = self._phase14_state_by_session.setdefault(session_id, {})
            if approval_id:
                state["current_approval_id"] = approval_id
                state.setdefault("approval_ids", []).append(approval_id)
            if bundle_ui.get("write_set"):
                state["current_write_set"] = bundle_ui.get("write_set")
        intent_scenario = self._scenario_interpreter.match(intent)
        if scenario_marker == "multi_approval_chain" or (
            intent_scenario is not None and intent_scenario.internal_marker == "multi_approval_chain"
        ):
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

        scenario_result = await self._scenario_interpreter.generate(
            self,
            intent=intent,
            scoped_tools=scoped_tools,
            session_id=session_id,
            call_index=call_index,
        )
        if scenario_result is not None:
            return scenario_result

        multi_read = await self._multi_read_sequence_from_intent(intent=intent, scoped_tools=scoped_tools)
        if multi_read is not None:
            return multi_read

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

        if self._is_job_lookup_request(intent):
            return await self._job_status(intent=intent, scoped_tools=scoped_tools)

        if self._is_job_collection_request(lowered):
            return await self._jobs_from_intent(intent=intent, scoped_tools=scoped_tools)

        if "low priority" in lowered or ("priority" in lowered and "jobs" in lowered):
            return await self._low_priority_jobs(intent=intent, scoped_tools=scoped_tools)

        return await self._machine_status(intent=intent, scoped_tools=scoped_tools)

    def _start_multi_approval_chain(
        self,
        *,
        session_id: str,
        intent: str,
        scoped_tools: list[ToolInfo],
    ) -> PlannerResult:
        del intent, scoped_tools
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
        if scenario == "phase14_cascade":
            return await self._phase14_resume_cascade(session_id=session_id)
        if scenario == "phase14_partial_failure":
            return await self._phase14_resume_partial_failure(session_id=session_id)
        if scenario == "phase14_idempotent_replay":
            return await self._phase14_resume_idempotent_replay(session_id=session_id)
        if scenario == "phase14_refresh_active_approval":
            return await self._phase14_resume_refresh_active_approval(session_id=session_id)
        if scenario == "phase14_stream_drop_commit":
            return await self._phase14_resume_stream_drop_commit(session_id=session_id)
        if scenario == "phase14_go_api_500":
            return await self._phase14_resume_go_api_500(session_id=session_id)
        if scenario in {"phase14_stale_approval", "phase14_expired_approval"}:
            return await self._phase14_resume_stale_or_expired(session_id=session_id, scenario=scenario)
        if scenario == "phase14_agreement":
            return await self._phase14_resume_agreement(session_id=session_id)
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

    def _phase14_cascade_priority_changes(self, lowered: str) -> list[tuple[str, str]]:
        text = lowered.replace("->", " to ")
        for ch in "-_/.,;:":
            text = text.replace(ch, " ")
        text = " ".join(text.split())

        matches = re.finditer(
            r"\b(?:change|update|set|move)\s+(?:all\s+)?(?:original\s+)?"
            r"(high|medium|low)\s+(?:priority\s+)?jobs?\s+(?:to|into)\s+"
            r"(high|medium|low)\b",
            text,
        )
        changes: list[tuple[str, str]] = []
        for match in matches:
            source, target = match.group(1), match.group(2)
            if source == target:
                continue
            changes.append((source, target))
        if len(changes) < 2:
            return []
        return changes[:2]

    def _read_tool(self, scoped_tools: list[ToolInfo], preferred: str = "get__jobs") -> str:
        for tool in scoped_tools:
            if tool.name == preferred:
                return tool.name
        for tool in scoped_tools:
            if str(getattr(tool, "method", "")).upper() == "GET":
                return tool.name
        return preferred

    def _tool_info(self, scoped_tools: list[ToolInfo], preferred: str) -> ToolInfo | None:
        for tool in scoped_tools:
            if tool.name == preferred:
                return tool
        return None

    def _is_job_lookup_request(self, intent: str) -> bool:
        return bool(intent_constraint_values(intent, "job_id"))

    def _is_job_collection_request(self, lowered: str) -> bool:
        if not re.search(r"\b(?:jobs?|work\s*orders?|tasks?)\b", lowered):
            return False
        return bool(re.search(r"\b(?:urgent|overdue|priority|priorities|delayed|late|low|medium|high)\b", lowered))

    def _job_filters_from_intent(self, intent: str, scoped_tools: list[ToolInfo]) -> dict[str, Any]:
        tool = self._tool_info(scoped_tools, "get__jobs")
        if tool is not None:
            inferred = infer_collection_query_args(intent, tool)
            if inferred:
                limit_match = re.search(r"\b(?:limit|first|next|top)\s+(\d{1,4})\b", intent or "", re.IGNORECASE)
                if limit_match and "limit" not in inferred:
                    inferred["limit"] = max(1, min(int(limit_match.group(1)), 1000))
                return inferred
        lowered = intent.lower()
        filters: dict[str, Any] = {"fields": "job_id,priority,product_id,status,deadline", "sort_by": "deadline", "sort_dir": "asc", "limit": 5}
        if re.search(r"\b(?:urgent|critical|high)\b", lowered):
            filters["priority"] = "high"
        elif "medium" in lowered:
            filters["priority"] = "medium"
        elif "low" in lowered:
            filters["priority"] = "low"
        if re.search(r"\b(?:overdue|late|delayed)\b", lowered):
            filters["status"] = "delayed"
        return filters

    def _path_params_for_tool(self, tool: ToolInfo | None) -> set[str]:
        if tool is None:
            return {"id"}
        params = set(tool.path_params or [])
        params.update(re.findall(r"\{([a-zA-Z0-9_]+)\}", tool.endpoint or ""))
        required = (tool.input_schema or {}).get("required")
        if isinstance(required, list):
            params.update(str(item) for item in required)
        return params or {"id"}

    def _query_params_from_args(self, args: dict[str, Any], tool: ToolInfo | None) -> dict[str, Any]:
        path_params = self._path_params_for_tool(tool)
        return {key: value for key, value in args.items() if key not in path_params}

    def _summary_fields_include(self, args: dict[str, Any], field: str) -> bool:
        fields = parse_fields_arg(args.get("fields"))
        return not fields or field in fields

    async def _multi_read_sequence_from_intent(
        self,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
    ) -> PlannerResult | None:
        clauses = [item.description for item in split_user_intents(intent) if item.description.strip()]
        if len(clauses) < 2:
            return None
        if any(re.search(r"\b(?:change|set|update|mark|make|delete|remove|create)\b", clause, re.IGNORECASE) for clause in clauses):
            return None

        steps: list[PlanStepDraft] = []
        outputs: list[dict[str, Any]] = []
        summaries: list[str] = []

        async def add_lookup(
            *,
            clause: str,
            preferred_tool: str,
            path: str,
            base_args: dict[str, Any],
            summary_for_body,
        ) -> bool:
            tool = self._tool_info(scoped_tools, preferred_tool)
            if tool is None:
                return False
            tool_name = tool.name
            args = merge_inferred_read_args(clause, tool, base_args)
            params = self._query_params_from_args(args, tool)
            body = await self._get_json(path, params=params or None)
            summary = summary_for_body(body, args)
            step_index = len(steps)
            steps.append(
                PlanStepDraft(
                    step_index=step_index,
                    tool_name=tool_name,
                    args=args,
                    depends_on=[step_index - 1] if step_index else [],
                )
            )
            outputs.append(
                {
                    "tool_name": tool_name,
                    "args": args,
                    "result": body,
                    "http_status": 200,
                    "summary": summary,
                    "status": "DONE",
                }
            )
            summaries.append(summary)
            return True

        async def add_job_collection(clause: str) -> bool:
            tool = self._tool_info(scoped_tools, "get__jobs")
            if tool is None:
                return False
            tool_name = tool.name
            args = self._job_filters_from_intent(clause, scoped_tools)
            body = await self._get_json("/jobs", params=args)
            rows = self._rows(body)
            ids = [str(row.get("job_id") or row.get("id")) for row in rows if row.get("job_id") or row.get("id")]
            filter_label = ", ".join(
                f"{key}={value}" for key, value in args.items() if key in {"priority", "status"}
            ) or "all"
            summary = f"Found {len(rows)} seeded jobs for {filter_label}: {', '.join(ids[:5])}."
            step_index = len(steps)
            steps.append(
                PlanStepDraft(
                    step_index=step_index,
                    tool_name=tool_name,
                    args=args,
                    depends_on=[step_index - 1] if step_index else [],
                )
            )
            outputs.append(
                {
                    "tool_name": tool_name,
                    "args": args,
                    "result": body,
                    "http_status": 200,
                    "summary": summary,
                    "status": "DONE",
                }
            )
            summaries.append(summary)
            return True

        for clause in clauses:
            machine_ids = intent_constraint_values(clause, "machine_id")
            job_ids = intent_constraint_values(clause, "job_id")
            lowered_clause = clause.lower()
            if machine_ids:
                machine_id = machine_ids[0]
                added = await add_lookup(
                    clause=clause,
                    preferred_tool="get__machines_{id}",
                    path=f"/machines/{machine_id}",
                    base_args={"id": machine_id},
                    summary_for_body=lambda body, args: (
                        f"Machine {machine_id} is {self._data(body).get('status') or self._data(body).get('Status') or 'unknown'}."
                    ),
                )
                if not added:
                    return None
            elif job_ids:
                job_id = job_ids[0]
                added = await add_lookup(
                    clause=clause,
                    preferred_tool="get__jobs_{id}",
                    path=f"/jobs/{job_id}",
                    base_args={"id": job_id},
                    summary_for_body=lambda body, args: (
                        f"Job {job_id} is {self._data(body).get('status') or self._data(body).get('Status') or 'unknown'}"
                        + (
                            f" with {self._data(body).get('priority') or self._data(body).get('Priority') or 'unknown'} priority"
                            if self._summary_fields_include(args, "priority")
                            else ""
                        )
                        + "."
                    ),
                )
                if not added:
                    return None
            elif self._is_job_collection_request(lowered_clause) or re.search(r"\bjobs?\b", lowered_clause):
                added = await add_job_collection(clause)
                if not added:
                    return None

        if len(steps) < 2:
            return None

        explanation = "Completed ordered read sequence: " + " ".join(summaries)
        return self._plan_result(
            explanation=explanation,
            risk="Read-only seeded multi-step lookup with no approval required.",
            steps=steps,
            tool_outputs=outputs,
        )

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
        machine_ids = intent_constraint_values(intent, "machine_id")
        if not machine_ids:
            summary = "Seeded machine status requires an explicit machine ID."
            return self._plan_result(
                explanation=summary,
                risk="No seeded fixture machine ID was inferred from the prompt.",
                steps=[],
            )
        machine_id = machine_ids[0]
        tool = self._tool_info(scoped_tools, "get__machines_{id}")
        args = merge_inferred_read_args(intent, tool, {"id": machine_id}) if tool is not None else {"id": machine_id}
        body = await self._get_json(f"/machines/{machine_id}", params=self._query_params_from_args(args, tool) or None)
        data = self._data(body)
        status = data.get("status") or data.get("Status") or "unknown"
        name = data.get("machine_name") or data.get("MachineName")
        summary = (
            f"Machine {machine_id} ({name}) is {status} in the seeded Go API data."
            if name and self._summary_fields_include(args, "machine_name")
            else f"Machine {machine_id} is {status} in the seeded Go API data."
        )
        return self._completed(
            intent=intent,
            tool_name=self._tool_name(scoped_tools, "get__machines_{id}"),
            args=args,
            result=body,
            summary=summary,
            explanation=summary,
            risk="Read-only seeded machine lookup.",
        )

    async def _job_status(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        job_ids = intent_constraint_values(intent, "job_id")
        if not job_ids:
            summary = "Seeded job status requires an explicit job ID."
            return self._plan_result(
                explanation=summary,
                risk="No seeded fixture job ID was inferred from the prompt.",
                steps=[],
            )
        job_id = job_ids[0]
        tool = self._tool_info(scoped_tools, "get__jobs_{id}")
        args = merge_inferred_read_args(intent, tool, {"id": job_id}) if tool is not None else {"id": job_id}
        body = await self._get_json(f"/jobs/{job_id}", params=self._query_params_from_args(args, tool) or None)
        data = self._data(body)
        priority = data.get("priority") or data.get("Priority") or "unknown"
        status = data.get("status") or data.get("Status") or "unknown"
        summary = (
            f"Job {job_id} is {status} with {priority} priority in the seeded Go API data."
            if self._summary_fields_include(args, "priority")
            else f"Job {job_id} is {status} in the seeded Go API data."
        )
        return self._completed(
            intent=intent,
            tool_name=self._tool_name(scoped_tools, "get__jobs_{id}"),
            args=args,
            result=body,
            summary=summary,
            explanation=summary,
            risk="Read-only seeded job lookup.",
        )

    async def _jobs_from_intent(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        filters = self._job_filters_from_intent(intent, scoped_tools)
        body = await self._get_json("/jobs", params=filters)
        rows = self._rows(body)
        ids = [str(row.get("job_id") or row.get("id")) for row in rows if row.get("job_id") or row.get("id")]
        filter_label = ", ".join(f"{key}={value}" for key, value in filters.items() if key in {"priority", "status"}) or "all"
        summary = f"Found {len(rows)} seeded jobs for {filter_label}: {', '.join(ids[:5])}. Details are shown in the table below."
        return self._completed(
            intent=intent,
            tool_name=self._tool_name(scoped_tools, "get__jobs"),
            args=filters,
            result=body,
            summary=summary,
            explanation=summary,
            risk="Read-only seeded job list lookup.",
        )

    async def _low_priority_jobs(self, *, intent: str, scoped_tools: list[ToolInfo]) -> PlannerResult:
        filters = self._job_filters_from_intent(intent, scoped_tools)
        filters.setdefault("priority", "low")
        filters.setdefault("fields", "job_id,priority,product_id,status,deadline")
        filters.setdefault("sort_by", "deadline")
        filters.setdefault("sort_dir", "asc")
        filters.setdefault("limit", 5)
        body = await self._get_json("/jobs", params=filters)
        rows = self._rows(body)
        ids = [str(row.get("job_id") or row.get("id")) for row in rows if row.get("job_id") or row.get("id")]
        summary = f"Found {len(rows)} low-priority seeded jobs: {', '.join(ids[:5])}. Details are shown in the table below."
        return self._completed(
            intent=intent,
            tool_name=self._tool_name(scoped_tools, "get__jobs"),
            args=filters,
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
                    "summary": f"Rule Applied: {len(summary_rows)} seeded job(s) evaluated in ordered sequence.",
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

    def data_integrity_audit(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._data_integrity_audit
        if session_id:
            rows = [row for row in rows if row.get("session_id") == session_id]
        return [dict(row) for row in rows]

    def _record_data_integrity_audit(
        self,
        *,
        session_id: str,
        scenario: str,
        write_set: str,
        approval_id: str | None,
        job_id: str,
        original_priority: str | None,
        before_priority: str | None,
        requested_priority: str,
        after_priority: str | None,
        status: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "audit_id": f"phase14-audit-{len(self._data_integrity_audit) + 1:04d}",
            "session_id": session_id,
            "scenario": scenario,
            "write_set": write_set,
            "approval_id": approval_id,
            "job_id": job_id,
            "operation": "job_priority_update",
            "original_priority": original_priority,
            "before_priority": before_priority,
            "requested_priority": requested_priority,
            "after_priority": after_priority,
            "status": status,
            "reason": reason,
        }
        self._data_integrity_audit.append(entry)
        return entry

    async def _seed_job_rows(self) -> list[dict[str, Any]]:
        body = await self._get_json(
            "/jobs",
            params={
                "fields": "job_id,priority,product_id,status,deadline",
                "sort_by": "created_at",
                "sort_dir": "asc",
                "limit": 200,
            },
        )
        return sorted(self._rows(body), key=lambda row: str(row.get("job_id") or ""))

    async def _job_row(self, job_id: str) -> dict[str, Any] | None:
        try:
            body = await self._get_json(f"/jobs/{job_id}")
        except httpx.HTTPStatusError:
            return None
        row = self._data(body)
        return row if isinstance(row, dict) else None

    async def _phase14_apply_priority_updates(
        self,
        *,
        session_id: str,
        scenario: str,
        write_set: str,
        approval_id: str | None,
        job_ids: list[str],
        requested_priority: str,
        original_priorities: dict[str, str],
    ) -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        for job_id in job_ids:
            before = await self._job_row(job_id)
            before_priority = str(before.get("priority")) if before and before.get("priority") is not None else None
            original_priority = original_priorities.get(job_id)
            try:
                updated = await self._put_json(f"/jobs/{job_id}", json={"priority": requested_priority})
                updated_row = self._data(updated)
                after_priority = str(updated_row.get("priority")) if isinstance(updated_row, dict) else None
                status = "succeeded" if after_priority == requested_priority else "failed"
                reason = None if status == "succeeded" else f"Expected {requested_priority}, got {after_priority}."
            except httpx.HTTPStatusError as exc:
                after_priority = before_priority
                status = "failed"
                reason = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            outcome = self._record_data_integrity_audit(
                session_id=session_id,
                scenario=scenario,
                write_set=write_set,
                approval_id=approval_id,
                job_id=job_id,
                original_priority=original_priority,
                before_priority=before_priority,
                requested_priority=requested_priority,
                after_priority=after_priority,
                status=status,
                reason=reason,
            )
            outcomes.append(outcome)
        return outcomes

    def _phase14_cascade_write_set(self, source: str, target: str) -> str:
        return f"original_{source}_to_{target}"

    def _phase14_cascade_semantics(self, changes: list[tuple[str, str]]) -> str:
        by_source = {source: target for source, target in changes}
        parts = []
        for priority in ("high", "medium", "low"):
            target = by_source.get(priority)
            if target:
                parts.append(f"original {priority}-priority jobs become {target}")
            else:
                parts.append(f"original {priority}-priority jobs remain unchanged")
        return "; ".join(parts).capitalize() + "."

    def _phase14_cascade_approval_payload(
        self,
        *,
        approval_number: int,
        source: str,
        target: str,
        job_ids: list[str],
        semantics: str,
        previous_approval_id: str | None = None,
    ) -> dict[str, Any]:
        write_set = self._phase14_cascade_write_set(source, target)
        bundle_ui: dict[str, Any] = {
            "kind": "phase14_cascade_priority",
            "write_set": write_set,
            "headline": f"Approval {approval_number} required: original {source.upper()}-priority jobs will become {target.upper()}.",
            "rows": [
                {"job_id": job_id, "original_priority": source, "new_priority": target}
                for job_id in job_ids
            ],
            "original_state_semantics": semantics,
        }
        if previous_approval_id:
            bundle_ui["previous_approval_id"] = previous_approval_id
        return {
            "summary": f"Phase 14 approval {approval_number}: change {len(job_ids)} original {source}-priority job(s) to {target}.",
            "count": len(job_ids),
            "preview": [
                {"tool_name": "put__jobs_{id}", "args": {"id": job_id, "priority": target}}
                for job_id in job_ids
            ],
            "bundle_ui": bundle_ui,
        }

    async def _phase14_start_cascade(
        self,
        *,
        session_id: str,
        changes: list[tuple[str, str]] | None = None,
        audit_scenario: str = "86",
    ) -> PlannerResult:
        change_sets = list(changes or [("high", "low"), ("low", "medium")])[:2]
        rows = await self._seed_job_rows()
        original = {str(row.get("job_id")): str(row.get("priority")) for row in rows if row.get("job_id")}
        ids_by_priority = {
            priority: [job_id for job_id, row_priority in original.items() if row_priority == priority]
            for priority in ("high", "medium", "low")
        }
        first_source, first_target = change_sets[0]
        first_ids = list(ids_by_priority.get(first_source) or [])
        unchanged_priorities = [priority for priority in ("high", "medium", "low") if priority not in {source for source, _ in change_sets}]
        semantics = self._phase14_cascade_semantics(change_sets)
        self._phase14_state_by_session[session_id] = {
            "scenario": "phase14_cascade",
            "stage": "awaiting_cascade_approval_1",
            "changes": [{"source": source, "target": target} for source, target in change_sets],
            "original_priorities": original,
            "ids_by_priority": ids_by_priority,
            "unchanged_priorities": unchanged_priorities,
            "original_state_semantics": semantics,
            "audit_scenario": audit_scenario,
            "approval_ids": [],
        }
        raise PlannerApprovalRequired(
            "Phase 14 cascading priority update approval 1 required.",
            approval=self._phase14_cascade_approval_payload(
                approval_number=1,
                source=first_source,
                target=first_target,
                job_ids=first_ids,
                semantics=semantics,
            ),
        )

    async def _phase14_resume_cascade(self, *, session_id: str) -> PlannerResult:
        state = self._phase14_state_by_session.setdefault(session_id, {})
        original = state.get("original_priorities") if isinstance(state.get("original_priorities"), dict) else {}
        approval_id = str(state.get("current_approval_id") or "").strip() or None
        stage = state.get("stage")
        raw_changes = state.get("changes") if isinstance(state.get("changes"), list) else []
        changes = [
            (str(row.get("source")), str(row.get("target")))
            for row in raw_changes
            if isinstance(row, dict) and row.get("source") and row.get("target")
        ][:2]
        if len(changes) < 2:
            changes = [("high", "low"), ("low", "medium")]
        ids_by_priority = state.get("ids_by_priority") if isinstance(state.get("ids_by_priority"), dict) else {}
        semantics = str(state.get("original_state_semantics") or self._phase14_cascade_semantics(changes))
        audit_scenario = str(state.get("audit_scenario") or "86")
        summary_label = "Phase 19 cascade matrix" if audit_scenario == "119" else "Phase 14 cascading priority update"

        if stage == "awaiting_cascade_approval_1":
            first_source, first_target = changes[0]
            first_ids = list(ids_by_priority.get(first_source) or [])
            await self._phase14_apply_priority_updates(
                session_id=session_id,
                scenario=audit_scenario,
                write_set=self._phase14_cascade_write_set(first_source, first_target),
                approval_id=approval_id,
                job_ids=first_ids,
                requested_priority=first_target,
                original_priorities=original,
            )
            state["first_approval_id"] = approval_id
            state["stage"] = "awaiting_cascade_approval_2"
            second_source, second_target = changes[1]
            second_ids = list(ids_by_priority.get(second_source) or [])
            raise PlannerApprovalRequired(
                "Phase 14 cascading priority update approval 2 required.",
                approval=self._phase14_cascade_approval_payload(
                    approval_number=2,
                    source=second_source,
                    target=second_target,
                    job_ids=second_ids,
                    semantics=semantics,
                    previous_approval_id=approval_id,
                ),
            )

        if stage != "awaiting_cascade_approval_2":
            return self._phase14_duplicate_resume_result(
                scenario=audit_scenario,
                summary=f"{summary_label} was already finalized; duplicate approval resume was ignored.",
            )

        second_source, second_target = changes[1]
        second_ids = list(ids_by_priority.get(second_source) or [])
        await self._phase14_apply_priority_updates(
            session_id=session_id,
            scenario=audit_scenario,
            write_set=self._phase14_cascade_write_set(second_source, second_target),
            approval_id=approval_id,
            job_ids=second_ids,
            requested_priority=second_target,
            original_priorities=original,
        )
        state["second_approval_id"] = approval_id
        state["stage"] = "complete"
        first_approval = state.get("first_approval_id")
        second_approval = state.get("second_approval_id")
        unchanged_summaries = [
            f"{priority} unchanged {len(ids_by_priority.get(priority) or [])}"
            for priority in (state.get("unchanged_priorities") or [])
        ]
        change_summaries = [
            f"{source}->{target} {len(ids_by_priority.get(source) or [])}"
            for source, target in changes
        ]
        summary = (
            f"{summary_label} complete: "
            + ", ".join([*change_summaries, *unchanged_summaries])
            + "."
        )
        steps = [
            PlanStepDraft(
                step_index=0,
                tool_name="put__jobs_{id}",
                args={"write_set": self._phase14_cascade_write_set(changes[0][0], changes[0][1]), "priority": changes[0][1]},
            ),
            PlanStepDraft(
                step_index=1,
                tool_name="put__jobs_{id}",
                args={"write_set": self._phase14_cascade_write_set(changes[1][0], changes[1][1]), "priority": changes[1][1]},
                depends_on=[0],
            ),
        ]
        return self._plan_result(
            explanation=summary,
            risk=f"{summary_label} used original-state semantics with two approval gates.",
            steps=steps,
            tool_outputs=[
                {
                    "tool_name": "put__jobs_{id}",
                    "args": steps[0].args,
                    "result": {
                        "summary": summary,
                        "approval_id": first_approval,
                        "write_set": self._phase14_cascade_write_set(changes[0][0], changes[0][1]),
                        "outcomes": [
                            {"job_id": job_id, "original_priority": changes[0][0], "priority": changes[0][1]}
                            for job_id in ids_by_priority.get(changes[0][0]) or []
                        ],
                    },
                    "http_status": 200,
                    "summary": f"Approval {first_approval} changed original {changes[0][0].upper()} jobs to {changes[0][1].upper()}.",
                    "status": "DONE",
                },
                {
                    "tool_name": "put__jobs_{id}",
                    "args": steps[1].args,
                    "result": {
                        "summary": summary,
                        "approval_id": second_approval,
                        "write_set": self._phase14_cascade_write_set(changes[1][0], changes[1][1]),
                        "outcomes": [
                            {"job_id": job_id, "original_priority": changes[1][0], "priority": changes[1][1]}
                            for job_id in ids_by_priority.get(changes[1][0]) or []
                        ],
                    },
                    "http_status": 200,
                    "summary": summary,
                    "status": "DONE",
                },
            ],
        )

    async def _phase14_start_partial_failure(self, *, session_id: str) -> PlannerResult:
        target_ids = ["JOB-SEED-005", "JOB-SEED-009", "JOB-SEED-MISSING-014"]
        rows = await self._seed_job_rows()
        original = {str(row.get("job_id")): str(row.get("priority")) for row in rows if row.get("job_id")}
        self._phase14_state_by_session[session_id] = {
            "scenario": "phase14_partial_failure",
            "stage": "awaiting_bulk_approval",
            "target_ids": target_ids,
            "original_priorities": original,
        }
        raise PlannerApprovalRequired(
            "Phase 14 bulk partial failure approval required.",
            approval={
                "summary": "Phase 14 bulk update will try three row-level priority updates; one seeded row is missing.",
                "count": len(target_ids),
                "preview": [
                    {"tool_name": "put__jobs_{id}", "args": {"id": job_id, "priority": "high"}}
                    for job_id in target_ids
                ],
                "bundle_ui": {
                    "kind": "phase14_partial_failure",
                    "write_set": "bulk_partial_failure",
                    "headline": "Approval required: bulk priority update with per-row outcome tracking.",
                    "rows": [
                        {"job_id": job_id, "new_priority": "high", "expected_outcome": "missing" if "MISSING" in job_id else "success"}
                        for job_id in target_ids
                    ],
                },
            },
        )

    async def _phase14_resume_partial_failure(self, *, session_id: str) -> PlannerResult:
        state = self._phase14_state_by_session.setdefault(session_id, {})
        approval_id = str(state.get("current_approval_id") or "").strip() or None
        original = state.get("original_priorities") if isinstance(state.get("original_priorities"), dict) else {}
        target_ids = list(state.get("target_ids") or [])
        outcomes = await self._phase14_apply_priority_updates(
            session_id=session_id,
            scenario="87",
            write_set="bulk_partial_failure",
            approval_id=approval_id,
            job_ids=target_ids,
            requested_priority="high",
            original_priorities=original,
        )
        succeeded = [row for row in outcomes if row.get("status") == "succeeded"]
        failed = [row for row in outcomes if row.get("status") != "succeeded"]
        succeeded_ids = ", ".join(str(row.get("job_id")) for row in succeeded if row.get("job_id")) or "none"
        failed_ids = ", ".join(str(row.get("job_id")) for row in failed if row.get("job_id")) or "none"
        summary = (
            f"Phase 14 partial failure recorded exact per-row outcomes: {len(succeeded)} succeeded, "
            f"{len(failed)} failed; succeeded rows: {succeeded_ids}; failed rows: {failed_ids}; "
            f"not all jobs succeeded. Approval id: {approval_id}."
        )
        steps = [PlanStepDraft(step_index=0, tool_name="put__jobs_{id}", args={"write_set": "bulk_partial_failure", "priority": "high"})]
        return self._plan_result(
            explanation=summary,
            risk="Phase 14 partial failure fixture records success and failure without claiming full success.",
            steps=steps,
            tool_outputs=[
                {
                    "tool_name": "put__jobs_{id}",
                    "args": steps[0].args,
                    "result": {"summary": summary, "approval_id": approval_id, "outcomes": outcomes},
                    "http_status": 422,
                    "summary": summary,
                    "status": "FAILED",
                    "last_error": summary,
                }
            ],
        )

    async def _phase14_start_idempotent_replay(self, *, session_id: str) -> PlannerResult:
        await self._phase14_seed_single_update_state(
            session_id=session_id,
            scenario="phase14_idempotent_replay",
            job_ids=["JOB-SEED-005"],
            requested_priority="high",
        )
        raise PlannerApprovalRequired(
            "Phase 14 idempotent approval replay approval required.",
            approval={
                "summary": "Phase 14 approval replay test: JOB-SEED-005 will be updated to high priority exactly once.",
                "count": 1,
                "preview": [{"tool_name": "put__jobs_{id}", "args": {"id": "JOB-SEED-005", "priority": "high"}}],
                "bundle_ui": {
                    "kind": "phase14_idempotent_replay",
                    "write_set": "single_idempotent_update",
                    "headline": "Approval required: JOB-SEED-005 will become HIGH once.",
                    "rows": [{"job_id": "JOB-SEED-005", "new_priority": "high"}],
                },
            },
        )

    async def _phase14_resume_idempotent_replay(self, *, session_id: str) -> PlannerResult:
        state = self._phase14_state_by_session.setdefault(session_id, {})
        if state.get("applied"):
            return self._phase14_duplicate_resume_result(
                scenario="88",
                summary="Phase 14 idempotent approval replay was ignored because the mutation already applied once.",
            )
        approval_id = str(state.get("current_approval_id") or "").strip() or None
        original = state.get("original_priorities") if isinstance(state.get("original_priorities"), dict) else {}
        outcomes = await self._phase14_apply_priority_updates(
            session_id=session_id,
            scenario="88",
            write_set="single_idempotent_update",
            approval_id=approval_id,
            job_ids=list(state.get("job_ids") or []),
            requested_priority=str(state.get("requested_priority") or "high"),
            original_priorities=original,
        )
        state["applied"] = True
        summary = f"Phase 14 idempotent approval replay applied JOB-SEED-005 exactly once. Approval id: {approval_id}."
        return self._phase14_single_step_result(
            summary=summary,
            risk="Phase 14 idempotency fixture applies a single approved mutation once.",
            approval_id=approval_id,
            outcomes=outcomes,
        )

    async def _phase14_start_refresh_active_approval(self, *, session_id: str) -> PlannerResult:
        rows = await self._seed_job_rows()
        target_ids = [
            str(row.get("job_id"))
            for row in rows
            if row.get("job_id") and str(row.get("priority") or "").lower() == "high"
        ]
        await self._phase14_seed_single_update_state(
            session_id=session_id,
            scenario="phase14_refresh_active_approval",
            job_ids=target_ids,
            requested_priority="medium",
        )
        raise PlannerApprovalRequired(
            "Phase 14 refresh-active approval required.",
            approval={
                "summary": (
                    f"Phase 14 refresh check: {len(target_ids)} original high-priority job(s) "
                    "will become medium after the browser refreshes."
                ),
                "count": len(target_ids),
                "preview": [
                    {"tool_name": "put__jobs_{id}", "args": {"id": job_id, "priority": "medium"}}
                    for job_id in target_ids
                ],
                "bundle_ui": {
                    "kind": "phase14_refresh_active_approval",
                    "write_set": "original_high_to_medium_refresh",
                    "headline": "Approval required: original HIGH-priority jobs will become MEDIUM after refresh.",
                    "rows": [
                        {
                            "job_id": job_id,
                            "original_priority": "high",
                            "new_priority": "medium",
                        }
                        for job_id in target_ids
                    ],
                },
            },
        )

    async def _phase14_resume_refresh_active_approval(self, *, session_id: str) -> PlannerResult:
        state = self._phase14_state_by_session.setdefault(session_id, {})
        if state.get("applied"):
            return self._phase14_duplicate_resume_result(
                scenario="SO-018",
                summary="Phase 14 refresh-active approval replay was ignored because the mutation already applied once.",
            )
        approval_id = str(state.get("current_approval_id") or "").strip() or None
        original = state.get("original_priorities") if isinstance(state.get("original_priorities"), dict) else {}
        target_ids = list(state.get("job_ids") or [])
        outcomes = await self._phase14_apply_priority_updates(
            session_id=session_id,
            scenario="SO-018",
            write_set="original_high_to_medium_refresh",
            approval_id=approval_id,
            job_ids=target_ids,
            requested_priority="medium",
            original_priorities=original,
        )
        state["applied"] = True
        succeeded = [row for row in outcomes if row.get("status") == "succeeded"]
        summary = (
            f"Phase 14 refresh active approval complete: {len(succeeded)} high priority jobs changed to medium "
            f"exactly once. Approval id: {approval_id}."
        )
        step = PlanStepDraft(
            step_index=0,
            tool_name="put__jobs_{id}",
            args={"write_set": "original_high_to_medium_refresh", "priority": "medium", "approval_id": approval_id},
        )
        return self._plan_result(
            explanation=summary,
            risk="Phase 14 refresh-active fixture applies the restored pending approval bundle once.",
            steps=[step],
            tool_outputs=[
                {
                    "tool_name": "put__jobs_{id}",
                    "args": step.args,
                    "result": {"summary": summary, "approval_id": approval_id, "outcomes": outcomes},
                    "http_status": 200,
                    "summary": summary,
                    "status": "DONE",
                }
            ],
        )

    async def _phase14_start_stream_drop_commit(self, *, session_id: str) -> PlannerResult:
        rows = await self._seed_job_rows()
        target_ids = [
            str(row.get("job_id"))
            for row in rows
            if row.get("job_id") and str(row.get("priority") or "").lower() == "high"
        ]
        await self._phase14_seed_single_update_state(
            session_id=session_id,
            scenario="phase14_stream_drop_commit",
            job_ids=target_ids,
            requested_priority="medium",
        )
        raise PlannerApprovalRequired(
            "Phase 14 stream-drop commit approval required.",
            approval={
                "summary": (
                    f"Phase 14 stream drop recovery: {len(target_ids)} original high-priority job(s) "
                    "will become medium after polling observes the terminal snapshot."
                ),
                "count": len(target_ids),
                "preview": [
                    {"tool_name": "put__jobs_{id}", "args": {"id": job_id, "priority": "medium"}}
                    for job_id in target_ids
                ],
                "bundle_ui": {
                    "kind": "phase14_stream_drop_commit",
                    "write_set": "stream_drop_high_to_medium",
                    "headline": "Approval required: stream-drop recovery will change original HIGH jobs to MEDIUM.",
                    "rows": [
                        {
                            "job_id": job_id,
                            "original_priority": "high",
                            "new_priority": "medium",
                        }
                        for job_id in target_ids
                    ],
                },
            },
        )

    async def _phase14_resume_stream_drop_commit(self, *, session_id: str) -> PlannerResult:
        state = self._phase14_state_by_session.setdefault(session_id, {})
        if state.get("applied"):
            return self._phase14_duplicate_resume_result(
                scenario="SO-030",
                summary="Phase 14 stream-drop commit replay was ignored because terminal evidence already existed.",
            )
        await asyncio.sleep(2.0)
        approval_id = str(state.get("current_approval_id") or "").strip() or None
        original = state.get("original_priorities") if isinstance(state.get("original_priorities"), dict) else {}
        target_ids = list(state.get("job_ids") or [])
        outcomes = await self._phase14_apply_priority_updates(
            session_id=session_id,
            scenario="SO-030",
            write_set="stream_drop_high_to_medium",
            approval_id=approval_id,
            job_ids=target_ids,
            requested_priority="medium",
            original_priorities=original,
        )
        state["applied"] = True
        succeeded = [row for row in outcomes if row.get("status") == "succeeded"]
        summary = (
            f"Phase 14 stream drop commit recovered from polling after terminal snapshot: "
            f"{len(succeeded)} high priority jobs changed to medium. Approval id: {approval_id}."
        )
        step = PlanStepDraft(
            step_index=0,
            tool_name="put__jobs_{id}",
            args={"write_set": "stream_drop_high_to_medium", "priority": "medium", "approval_id": approval_id},
        )
        return self._plan_result(
            explanation=summary,
            risk="Phase 14 stream-drop fixture requires polling terminal evidence before final UI success.",
            steps=[step],
            tool_outputs=[
                {
                    "tool_name": "put__jobs_{id}",
                    "args": step.args,
                    "result": {"summary": summary, "approval_id": approval_id, "outcomes": outcomes},
                    "http_status": 200,
                    "summary": summary,
                    "status": "DONE",
                }
            ],
        )

    async def _phase14_start_go_api_500(self, *, session_id: str) -> PlannerResult:
        await self._phase14_seed_single_update_state(
            session_id=session_id,
            scenario="phase14_go_api_500",
            job_ids=["JOB-SEED-001"],
            requested_priority="medium",
        )
        raise PlannerApprovalRequired(
            "Phase 14 Go API 500 failure approval required.",
            approval={
                "summary": "Phase 14 Go API 500 check: JOB-SEED-001 would become medium, but commit will hit a seeded backend failure.",
                "count": 1,
                "preview": [{"tool_name": "put__jobs_{id}", "args": {"id": "JOB-SEED-001", "priority": "medium"}}],
                "bundle_ui": {
                    "kind": "phase14_go_api_500",
                    "write_set": "go_api_500_high_to_medium",
                    "headline": "Approval required: seeded Go API 500 failure must not mutate JOB-SEED-001.",
                    "rows": [
                        {
                            "job_id": "JOB-SEED-001",
                            "original_priority": "high",
                            "new_priority": "medium",
                        }
                    ],
                },
            },
        )

    async def _phase14_resume_go_api_500(self, *, session_id: str) -> PlannerResult:
        state = self._phase14_state_by_session.setdefault(session_id, {})
        approval_id = str(state.get("current_approval_id") or "").strip() or None
        summary = (
            "Could not complete the requested job priority update because the Go API returned HTTP 500: "
            f"database unavailable. No job rows were changed and no audit rows were created. Please retry after "
            f"the backend recovers. Approval id: {approval_id}."
        )
        step = PlanStepDraft(
            step_index=0,
            tool_name="put__jobs_{id}",
            args={"id": "JOB-SEED-001", "priority": "medium", "approval_id": approval_id},
        )
        return self._plan_result(
            explanation=summary,
            risk="Phase 14 seeded Go API 500 fixture must fail safely without mutation or audit rows.",
            steps=[step],
            tool_outputs=[
                {
                    "tool_name": "put__jobs_{id}",
                    "args": step.args,
                    "result": {
                        "approval_id": approval_id,
                        "error": "database unavailable",
                        "summary": summary,
                    },
                    "http_status": 500,
                    "summary": summary,
                    "status": "FAILED",
                    "last_error": "HTTP 500: database unavailable",
                }
            ],
        )

    async def _phase14_start_stale_approval(self, *, session_id: str, expired: bool) -> PlannerResult:
        scenario = "phase14_expired_approval" if expired else "phase14_stale_approval"
        await self._phase14_seed_single_update_state(
            session_id=session_id,
            scenario=scenario,
            job_ids=["JOB-SEED-005"],
            requested_priority="high",
        )
        kind = "phase14_expired_approval" if expired else "phase14_stale_approval"
        headline = (
            "Expired approval fixture: JOB-SEED-005 must not change after expiry."
            if expired
            else "Stale approval fixture: JOB-SEED-005 must not change after session state changes."
        )
        approval_payload = {
            "summary": headline,
            "count": 1,
            "preview": [{"tool_name": "put__jobs_{id}", "args": {"id": "JOB-SEED-005", "priority": "high"}}],
            "bundle_ui": {
                "kind": kind,
                "write_set": "stale_or_expired_update",
                "headline": headline,
                "rows": [{"job_id": "JOB-SEED-005", "new_priority": "high"}],
            },
        }
        if expired:
            approval_payload["expires_in_seconds"] = -1
        raise PlannerApprovalRequired("Phase 14 stale or expired approval required.", approval=approval_payload)

    async def _phase14_resume_stale_or_expired(self, *, session_id: str, scenario: str) -> PlannerResult:
        state = self._phase14_state_by_session.setdefault(session_id, {})
        approval_id = str(state.get("current_approval_id") or "").strip() or None
        original = state.get("original_priorities") if isinstance(state.get("original_priorities"), dict) else {}
        outcomes = await self._phase14_apply_priority_updates(
            session_id=session_id,
            scenario="89",
            write_set="stale_or_expired_update",
            approval_id=approval_id,
            job_ids=list(state.get("job_ids") or []),
            requested_priority=str(state.get("requested_priority") or "high"),
            original_priorities=original,
        )
        summary = f"Phase 14 stale/expired approval unexpectedly applied for {scenario}; this is a blocking defect."
        return self._phase14_single_step_result(
            summary=summary,
            risk="Phase 14 stale/expired approval fixture should be blocked before this planner path runs.",
            approval_id=approval_id,
            outcomes=outcomes,
        )

    async def _phase14_start_agreement(self, *, session_id: str) -> PlannerResult:
        await self._phase14_seed_single_update_state(
            session_id=session_id,
            scenario="phase14_agreement",
            job_ids=["JOB-SEED-005", "JOB-SEED-009"],
            requested_priority="high",
        )
        raise PlannerApprovalRequired(
            "Phase 14 agreement audit timeline summary approval required.",
            approval={
                "summary": "Phase 14 agreement check: JOB-SEED-005 and JOB-SEED-009 will become high priority.",
                "count": 2,
                "preview": [
                    {"tool_name": "put__jobs_{id}", "args": {"id": job_id, "priority": "high"}}
                    for job_id in ["JOB-SEED-005", "JOB-SEED-009"]
                ],
                "bundle_ui": {
                    "kind": "phase14_agreement",
                    "write_set": "agreement_update",
                    "headline": "Approval required: audit, DB, SSE timeline, and summary must agree.",
                    "rows": [
                        {"job_id": "JOB-SEED-005", "new_priority": "high"},
                        {"job_id": "JOB-SEED-009", "new_priority": "high"},
                    ],
                },
            },
        )

    async def _phase14_resume_agreement(self, *, session_id: str) -> PlannerResult:
        state = self._phase14_state_by_session.setdefault(session_id, {})
        approval_id = str(state.get("current_approval_id") or "").strip() or None
        original = state.get("original_priorities") if isinstance(state.get("original_priorities"), dict) else {}
        outcomes = await self._phase14_apply_priority_updates(
            session_id=session_id,
            scenario="90",
            write_set="agreement_update",
            approval_id=approval_id,
            job_ids=list(state.get("job_ids") or []),
            requested_priority=str(state.get("requested_priority") or "high"),
            original_priorities=original,
        )
        summary = (
            "Phase 14 agreement complete: JOB-SEED-005 and JOB-SEED-009 are high priority; "
            f"audit log, DB state, SSE timeline, approval {approval_id}, and final summary agree."
        )
        return self._phase14_single_step_result(
            summary=summary,
            risk="Phase 14 agreement fixture ties each mutation to audit, DB, timeline, and summary evidence.",
            approval_id=approval_id,
            outcomes=outcomes,
        )

    async def _phase14_seed_single_update_state(
        self,
        *,
        session_id: str,
        scenario: str,
        job_ids: list[str],
        requested_priority: str,
    ) -> None:
        rows = await self._seed_job_rows()
        original = {str(row.get("job_id")): str(row.get("priority")) for row in rows if row.get("job_id")}
        self._phase14_state_by_session[session_id] = {
            "scenario": scenario,
            "stage": "awaiting_approval",
            "job_ids": job_ids,
            "requested_priority": requested_priority,
            "original_priorities": original,
        }

    def _phase14_single_step_result(
        self,
        *,
        summary: str,
        risk: str,
        approval_id: str | None,
        outcomes: list[dict[str, Any]],
    ) -> PlannerResult:
        step = PlanStepDraft(step_index=0, tool_name="put__jobs_{id}", args={"priority": "high", "approval_id": approval_id})
        return self._plan_result(
            explanation=summary,
            risk=risk,
            steps=[step],
            tool_outputs=[
                {
                    "tool_name": "put__jobs_{id}",
                    "args": step.args,
                    "result": {"summary": summary, "approval_id": approval_id, "outcomes": outcomes},
                    "http_status": 200,
                    "summary": summary,
                    "status": "DONE",
                }
            ],
        )

    def _phase14_duplicate_resume_result(self, *, scenario: str, summary: str) -> PlannerResult:
        return self._plan_result(
            explanation=summary,
            risk=f"Phase 14 scenario {scenario} duplicate approval replay was safely ignored.",
            steps=[PlanStepDraft(step_index=0, tool_name="put__jobs_{id}", args={"duplicate_replay": True})],
            tool_outputs=[
                {
                    "tool_name": "put__jobs_{id}",
                    "args": {"duplicate_replay": True},
                    "result": {"summary": summary, "duplicate_replay": True},
                    "http_status": 200,
                    "summary": summary,
                    "status": "DONE",
                }
            ],
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
