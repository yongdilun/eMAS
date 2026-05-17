from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from factory_agent.planner import PlannerApprovalRequired
from factory_agent.schemas import ToolInfo


READ_ONLY_TOOL_RESULT = "read_only_tool_result"
APPROVAL_REQUIRED_WORKFLOW = "approval_required_workflow"
TWO_STEP_APPROVAL_CHAIN = "two_step_approval_chain"
REJECTED_APPROVAL = "rejected_approval"
EXPIRED_OR_STALE_APPROVAL = "expired_or_stale_approval"
PARTIAL_FAILURE = "partial_failure"
LARGE_STRUCTURED_RESULT = "large_structured_result"
SSE_FAULT_MARKER = "sse_fault_marker"

SUPPORTED_SCENARIO_CAPABILITIES = frozenset(
    {
        READ_ONLY_TOOL_RESULT,
        APPROVAL_REQUIRED_WORKFLOW,
        TWO_STEP_APPROVAL_CHAIN,
        REJECTED_APPROVAL,
        EXPIRED_OR_STALE_APPROVAL,
        PARTIAL_FAILURE,
        LARGE_STRUCTURED_RESULT,
        SSE_FAULT_MARKER,
    }
)


@dataclass(frozen=True)
class PromptTrigger:
    any_phrases: tuple[str, ...] = ()
    all_phrases: tuple[str, ...] = ()
    regexes: tuple[str, ...] = ()
    exclude_phrases: tuple[str, ...] = ()

    def matches(self, intent: str) -> bool:
        normalized = normalize_prompt(intent)
        if any(phrase.lower() in normalized for phrase in self.exclude_phrases):
            return False
        if self.any_phrases and not any(phrase.lower() in normalized for phrase in self.any_phrases):
            return False
        if self.all_phrases and not all(phrase.lower() in normalized for phrase in self.all_phrases):
            return False
        return not self.regexes or any(re.search(pattern, normalized) for pattern in self.regexes)


@dataclass(frozen=True)
class SeededAction:
    handler: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SeededScenario:
    scenario_id: str
    oracle_ids: tuple[str, ...]
    internal_marker: str
    capabilities: tuple[str, ...]
    trigger: PromptTrigger
    generate: SeededAction
    description: str

    def __post_init__(self) -> None:
        unknown = set(self.capabilities) - SUPPORTED_SCENARIO_CAPABILITIES
        if unknown:
            raise ValueError(f"Unsupported seeded scenario capabilities for {self.scenario_id}: {sorted(unknown)}")


class SeededScenarioRuntime(Protocol):
    _scenario_by_session: dict[str, str]

    async def _large_structured_result(self, *, intent: str, scoped_tools: list[ToolInfo]) -> Any:
        ...

    async def _phase14_start_cascade(
        self,
        *,
        session_id: str,
        changes: list[tuple[str, str]] | None = None,
        audit_scenario: str = "86",
    ) -> Any:
        ...


CASCADE_CHANGE_REGEX = (
    r"\b(?:change|update|set|move)\s+(?:all\s+)?(?:original\s+)?"
    r"(?:high|medium|low)\s+(?:priority\s+)?jobs?\s+(?:to|into)\s+"
    r"(?:high|medium|low)\b.*\b(?:change|update|set|move)\s+(?:all\s+)?(?:original\s+)?"
    r"(?:high|medium|low)\s+(?:priority\s+)?jobs?\s+(?:to|into)\s+"
    r"(?:high|medium|low)\b"
)


def normalize_prompt(intent: str) -> str:
    text = intent.lower().replace("->", " to ")
    for ch in "-_/.,;:":
        text = text.replace(ch, " ")
    return " ".join(text.split())


MIGRATED_SEEDED_SCENARIOS: tuple[SeededScenario, ...] = (
    SeededScenario(
        scenario_id="so031_large_structured_result",
        oracle_ids=("SO-031",),
        internal_marker="large_structured_result",
        capabilities=(READ_ONLY_TOOL_RESULT, LARGE_STRUCTURED_RESULT),
        trigger=PromptTrigger(any_phrases=("phase 9 large structured result",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_large_structured_result"}),
        description="Read-only 80-row structured job result used by SO-031 browser layout oracles.",
    ),
    SeededScenario(
        scenario_id="phase9_multi_step_ordered",
        oracle_ids=("SO-014",),
        internal_marker="multi_step_ordered",
        capabilities=(READ_ONLY_TOOL_RESULT,),
        trigger=PromptTrigger(any_phrases=("phase 9 multi step ordered",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_multi_step_ordered"}),
        description="Ordered read-only multi-step seeded workflow.",
    ),
    SeededScenario(
        scenario_id="phase9_multi_approval_chain",
        oracle_ids=("SO-011", "SO-012"),
        internal_marker="multi_approval_chain",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, TWO_STEP_APPROVAL_CHAIN),
        trigger=PromptTrigger(any_phrases=("phase 9 multi approval chain",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_start_multi_approval_chain"}),
        description="Two-gate seeded approval chain before final execution.",
    ),
    SeededScenario(
        scenario_id="phase9_approval_timeout",
        oracle_ids=("SO-006",),
        internal_marker="approval_timeout",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, EXPIRED_OR_STALE_APPROVAL),
        trigger=PromptTrigger(any_phrases=("phase 9 approval timeout",)),
        generate=SeededAction(
            handler="approval_payload",
            params={
                "message": "Seeded approval timeout fixture.",
                "approval": {
                    "summary": (
                        "Phase 9 approval timeout: the job is waiting safely and must not continue without a decision."
                    ),
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
            },
        ),
        description="Expired approval request fixture.",
    ),
    SeededScenario(
        scenario_id="phase9_partial_failure",
        oracle_ids=("SO-020",),
        internal_marker="partial_failure",
        capabilities=(READ_ONLY_TOOL_RESULT, PARTIAL_FAILURE),
        trigger=PromptTrigger(any_phrases=("phase 9 partial failure",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_partial_failure"}),
        description="Read-only partial failure where later steps must not execute.",
    ),
    SeededScenario(
        scenario_id="phase9_schema_mismatch",
        oracle_ids=("SO-020",),
        internal_marker="schema_mismatch",
        capabilities=(PARTIAL_FAILURE,),
        trigger=PromptTrigger(any_phrases=("phase 9 schema mismatch",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_schema_mismatch"}),
        description="Malformed tool payload fixture.",
    ),
    SeededScenario(
        scenario_id="phase9_duplicate_submit",
        oracle_ids=("SO-007",),
        internal_marker="duplicate_submit",
        capabilities=(READ_ONLY_TOOL_RESULT,),
        trigger=PromptTrigger(any_phrases=("phase 9 duplicate submit",)),
        generate=SeededAction(
            handler="draft_then_call",
            params={
                "draft": {
                    "tool_name": "get__machines_{id}",
                    "args": {"id": "M-CNC-01"},
                    "summary": "Phase 9 duplicate-submit run is staged and ready to execute.",
                },
                "delay_seconds": 0.8,
                "method": "_machine_status",
            },
        ),
        description="Duplicate submit fixture with a staged first response.",
    ),
    SeededScenario(
        scenario_id="phase9_out_of_order_duplicate_sse",
        oracle_ids=("SO-014",),
        internal_marker="out_of_order_sse",
        capabilities=(READ_ONLY_TOOL_RESULT, SSE_FAULT_MARKER),
        trigger=PromptTrigger(any_phrases=("phase 9 out of order duplicate sse",)),
        generate=SeededAction(
            handler="draft_then_call",
            params={
                "draft": {
                    "tool_name": "get__jobs",
                    "args": {"priority": "low", "limit": 2},
                    "summary": "Phase 9 out-of-order SSE run is staged.",
                },
                "delay_seconds": 1.2,
                "method": "_multi_step_ordered",
            },
        ),
        description="SSE duplicate/out-of-order fixture marker.",
    ),
    SeededScenario(
        scenario_id="phase9_last_event_id_reconnect",
        oracle_ids=("SO-014",),
        internal_marker="last_event_id_reconnect",
        capabilities=(READ_ONLY_TOOL_RESULT, SSE_FAULT_MARKER),
        trigger=PromptTrigger(any_phrases=("phase 9 last event id reconnect",)),
        generate=SeededAction(
            handler="draft_then_call",
            params={
                "draft": {
                    "tool_name": "get__machines_{id}",
                    "args": {"id": "M-CNC-01"},
                    "summary": "Phase 9 reconnect run is staged.",
                },
                "delay_seconds": 5.0,
                "method": "_machine_status",
            },
        ),
        description="Last-Event-ID reconnect fixture marker.",
    ),
    SeededScenario(
        scenario_id="phase9_stream_drop_recovery",
        oracle_ids=("SO-030",),
        internal_marker="stream_drop_recovery",
        capabilities=(READ_ONLY_TOOL_RESULT, SSE_FAULT_MARKER),
        trigger=PromptTrigger(any_phrases=("phase 9 stream drop recovery",)),
        generate=SeededAction(
            handler="draft_then_completed",
            params={
                "draft": {
                    "tool_name": "get__machines_{id}",
                    "args": {"id": "M-CNC-01"},
                    "summary": "Phase 9 stream-drop recovery run is staged.",
                },
                "delay_seconds": 4.5,
                "completed": {
                    "tool_name": "get__machines_{id}",
                    "args": {"id": "M-CNC-01"},
                    "result": {"data": {"machine_id": "M-CNC-01", "status": "RUNNING"}},
                    "summary": "Phase 9 stream drop recovered by snapshot polling.",
                    "risk": "Read-only seeded stream-drop recovery fixture.",
                },
            },
        ),
        description="Read-only stream drop recovery fixture.",
    ),
    SeededScenario(
        scenario_id="phase10_refresh_recovery",
        oracle_ids=("SO-019",),
        internal_marker="phase10_refresh_recovery",
        capabilities=(READ_ONLY_TOOL_RESULT,),
        trigger=PromptTrigger(any_phrases=("phase 10 refresh during active job",)),
        generate=SeededAction(
            handler="draft_then_completed",
            params={
                "draft": {
                    "tool_name": "get__machines_{id}",
                    "args": {"id": "M-CNC-01"},
                    "summary": "Phase 10 refresh recovery run is staged and ready to execute.",
                },
                "delay_seconds": 2.5,
                "completed": {
                    "tool_name": "get__machines_{id}",
                    "args": {"id": "M-CNC-01"},
                    "result": {"data": {"machine_id": "M-CNC-01", "status": "RUNNING", "refresh_recovered": True}},
                    "summary": "Phase 10 refresh recovery completed once without duplicate execution.",
                    "risk": "Read-only release refresh recovery fixture.",
                },
            },
        ),
        description="Refresh recovery fixture.",
    ),
    SeededScenario(
        scenario_id="phase10_long_running_stream",
        oracle_ids=("SO-013",),
        internal_marker="phase10_long_running_stream",
        capabilities=(READ_ONLY_TOOL_RESULT, SSE_FAULT_MARKER),
        trigger=PromptTrigger(any_phrases=("phase 10 long running stream",)),
        generate=SeededAction(
            handler="draft_then_completed",
            params={
                "draft": {
                    "tool_name": "get__machines_{id}",
                    "args": {"id": "M-CNC-01"},
                    "summary": "Phase 10 long-running stream is staged and will complete through polling.",
                },
                "delay_seconds": 6.0,
                "completed": {
                    "tool_name": "get__machines_{id}",
                    "args": {"id": "M-CNC-01"},
                    "result": {
                        "data": {
                            "machine_id": "M-CNC-01",
                            "status": "RUNNING",
                            "long_stream_terminal": True,
                        }
                    },
                    "summary": "Phase 10 long-running stream reached a terminal state within release limits.",
                    "risk": "Read-only release long-stream fixture.",
                },
            },
        ),
        description="Long-running read fixture.",
    ),
    SeededScenario(
        scenario_id="phase10_release_machine_status",
        oracle_ids=("SO-058", "SO-065"),
        internal_marker="phase10_release_machine_status",
        capabilities=(READ_ONLY_TOOL_RESULT,),
        trigger=PromptTrigger(
            any_phrases=(
                "phase 10 slow network machine status",
                "phase 10 release latency budget machine status",
            )
        ),
        generate=SeededAction(
            handler="completed_with_summary",
            params={
                "tool_name": "get__machines_{id}",
                "args": {"id": "M-CNC-01"},
                "result": {"data": {"machine_id": "M-CNC-01", "status": "RUNNING"}},
                "summary": "Machine M-CNC-01 (CNC Mill 01) is RUNNING in the seeded Go API data.",
                "risk": "Read-only release machine-status fixture.",
            },
        ),
        description="Release latency and slow-network machine-status fixture.",
    ),
    SeededScenario(
        scenario_id="so005_so041_medium_high_original_high_low",
        oracle_ids=("SO-005", "SO-041"),
        internal_marker="phase14_cascade",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, TWO_STEP_APPROVAL_CHAIN, REJECTED_APPROVAL),
        trigger=PromptTrigger(
            regexes=(
                r"\bchange all medium priority jobs? to high then change all "
                r"(?:original )?high priority jobs? to low\b",
            ),
            exclude_phrases=("prompt regression", "phase 19"),
        ),
        generate=SeededAction(
            handler="phase14_cascade",
            params={"changes": (("medium", "high"), ("high", "low")), "audit_scenario": "86"},
        ),
        description=(
            "Two-approval original-state cascade shared by SO-005 rejection and SO-041 final-summary coverage."
        ),
    ),
    SeededScenario(
        scenario_id="phase14_cascade_default_high_low_low_medium",
        oracle_ids=("SO-002",),
        internal_marker="phase14_cascade",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, TWO_STEP_APPROVAL_CHAIN),
        trigger=PromptTrigger(any_phrases=("phase 14 cascading priority update",)),
        generate=SeededAction(
            handler="phase14_cascade",
            params={"changes": (("high", "low"), ("low", "medium")), "audit_scenario": "86"},
        ),
        description="Legacy Phase 14 cascade marker moved from adapter branch code into scenario data.",
    ),
    SeededScenario(
        scenario_id="phase19_prompt_regression_dynamic_cascade",
        oracle_ids=("SO-001", "SO-002", "SO-003", "SO-004", "SO-041"),
        internal_marker="phase14_cascade",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, TWO_STEP_APPROVAL_CHAIN),
        trigger=PromptTrigger(regexes=(CASCADE_CHANGE_REGEX,), any_phrases=("prompt regression",)),
        generate=SeededAction(handler="dynamic_phase14_cascade", params={"audit_scenario": "119"}),
        description="Prompt-regression cascade matrix uses original-state semantics with audit scenario 119.",
    ),
    SeededScenario(
        scenario_id="phase14_dynamic_cascade",
        oracle_ids=("SO-001", "SO-002", "SO-003", "SO-004"),
        internal_marker="phase14_cascade",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, TWO_STEP_APPROVAL_CHAIN),
        trigger=PromptTrigger(regexes=(CASCADE_CHANGE_REGEX,), exclude_phrases=("prompt regression", "phase 19")),
        generate=SeededAction(handler="dynamic_phase14_cascade", params={"audit_scenario": "86"}),
        description="Generic two-clause priority cascade parsed from scenario data.",
    ),
    SeededScenario(
        scenario_id="phase14_bulk_partial_failure",
        oracle_ids=("SO-009",),
        internal_marker="phase14_partial_failure",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, PARTIAL_FAILURE),
        trigger=PromptTrigger(any_phrases=("phase 14 bulk partial failure",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_phase14_start_partial_failure"}),
        description="Bulk partial commit with exact per-row outcomes.",
    ),
    SeededScenario(
        scenario_id="phase14_idempotent_approval_replay",
        oracle_ids=("SO-007",),
        internal_marker="phase14_idempotent_replay",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW,),
        trigger=PromptTrigger(any_phrases=("phase 14 idempotent approval replay",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_phase14_start_idempotent_replay"}),
        description="Idempotent approval replay fixture.",
    ),
    SeededScenario(
        scenario_id="phase14_refresh_active_approval",
        oracle_ids=("SO-018",),
        internal_marker="phase14_refresh_active_approval",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW,),
        trigger=PromptTrigger(any_phrases=("phase 14 refresh during active approval",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_phase14_start_refresh_active_approval"}),
        description="Active approval survives browser refresh.",
    ),
    SeededScenario(
        scenario_id="phase14_stream_drop_commit",
        oracle_ids=("SO-030",),
        internal_marker="phase14_stream_drop_commit",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, SSE_FAULT_MARKER),
        trigger=PromptTrigger(any_phrases=("phase 14 stream drop commit recovery",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_phase14_start_stream_drop_commit"}),
        description="Commit completion recovered through polling after stream drop.",
    ),
    SeededScenario(
        scenario_id="phase14_go_api_500",
        oracle_ids=("SO-029",),
        internal_marker="phase14_go_api_500",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, PARTIAL_FAILURE),
        trigger=PromptTrigger(any_phrases=("phase 14 go api 500 commit failure",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_phase14_start_go_api_500"}),
        description="Backend failure fixture with no mutation or audit rows.",
    ),
    SeededScenario(
        scenario_id="phase14_stale_approval",
        oracle_ids=("SO-008", "SO-027"),
        internal_marker="phase14_stale_approval",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, EXPIRED_OR_STALE_APPROVAL),
        trigger=PromptTrigger(any_phrases=("phase 14 stale approval",)),
        generate=SeededAction(
            handler="call_runtime",
            params={"method": "_phase14_start_stale_approval", "expired": False},
        ),
        description="Stale approval must not mutate after session state changes.",
    ),
    SeededScenario(
        scenario_id="phase14_expired_approval",
        oracle_ids=("SO-006",),
        internal_marker="phase14_expired_approval",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW, EXPIRED_OR_STALE_APPROVAL),
        trigger=PromptTrigger(any_phrases=("phase 14 expired approval",)),
        generate=SeededAction(
            handler="call_runtime",
            params={"method": "_phase14_start_stale_approval", "expired": True},
        ),
        description="Expired approval must not mutate.",
    ),
    SeededScenario(
        scenario_id="phase14_agreement",
        oracle_ids=("SO-010",),
        internal_marker="phase14_agreement",
        capabilities=(APPROVAL_REQUIRED_WORKFLOW,),
        trigger=PromptTrigger(any_phrases=("phase 14 agreement audit timeline summary",)),
        generate=SeededAction(handler="call_runtime", params={"method": "_phase14_start_agreement"}),
        description="Audit, DB, SSE timeline, approval id, and summary agreement fixture.",
    ),
    SeededScenario(
        scenario_id="phase9_isolation_alpha",
        oracle_ids=("SO-032",),
        internal_marker="isolation_alpha",
        capabilities=(READ_ONLY_TOOL_RESULT,),
        trigger=PromptTrigger(any_phrases=("phase 9 isolation alpha",)),
        generate=SeededAction(
            handler="completed_with_summary",
            params={
                "tool_name": "get__machines_{id}",
                "args": {"id": "M-CNC-01"},
                "result": {"data": {"machine_id": "M-CNC-01", "status": "RUNNING", "isolation": "alpha"}},
                "summary": "Phase 9 isolation alpha session completed without beta data.",
                "risk": "Read-only seeded isolation fixture.",
            },
        ),
        description="Cross-session isolation alpha fixture.",
    ),
    SeededScenario(
        scenario_id="phase9_isolation_beta",
        oracle_ids=("SO-032",),
        internal_marker="isolation_beta",
        capabilities=(READ_ONLY_TOOL_RESULT,),
        trigger=PromptTrigger(any_phrases=("phase 9 isolation beta",)),
        generate=SeededAction(
            handler="completed_with_summary",
            params={
                "tool_name": "get__machines_{id}",
                "args": {"id": "M-CNC-02"},
                "result": {"data": {"machine_id": "M-CNC-02", "status": "IDLE", "isolation": "beta"}},
                "summary": "Phase 9 isolation beta session completed without alpha data.",
                "risk": "Read-only seeded isolation fixture.",
            },
        ),
        description="Cross-session isolation beta fixture.",
    ),
)

BUNDLE_KIND_SCENARIO_MARKERS = {
    "phase14_cascade_priority": "phase14_cascade",
    "phase14_partial_failure": "phase14_partial_failure",
    "phase14_idempotent_replay": "phase14_idempotent_replay",
    "phase14_refresh_active_approval": "phase14_refresh_active_approval",
    "phase14_stream_drop_commit": "phase14_stream_drop_commit",
    "phase14_go_api_500": "phase14_go_api_500",
    "phase14_stale_approval": "phase14_stale_approval",
    "phase14_expired_approval": "phase14_expired_approval",
    "phase14_agreement": "phase14_agreement",
    "phase9_approval_chain": "multi_approval_chain",
}

class SeededScenarioInterpreter:
    def __init__(self, scenarios: tuple[SeededScenario, ...] = MIGRATED_SEEDED_SCENARIOS):
        self._scenarios = scenarios

    @property
    def scenarios(self) -> tuple[SeededScenario, ...]:
        return self._scenarios

    def match(self, intent: str) -> SeededScenario | None:
        for scenario in self._scenarios:
            if scenario.trigger.matches(intent):
                return scenario
        return None

    def handles_intent(self, intent: str) -> bool:
        return self.match(intent) is not None

    def marker_for_bundle_kind(self, bundle_kind: str) -> str | None:
        return BUNDLE_KIND_SCENARIO_MARKERS.get(bundle_kind)

    async def generate(
        self,
        runtime: SeededScenarioRuntime,
        *,
        intent: str,
        scoped_tools: list[ToolInfo],
        session_id: str,
        call_index: int,
    ) -> Any | None:
        scenario = self.match(intent)
        if scenario is None:
            return None

        runtime._scenario_by_session[session_id] = scenario.internal_marker
        action = scenario.generate
        if action.handler == "call_runtime":
            return await self._call_runtime(
                runtime,
                method_name=str(action.params["method"]),
                intent=intent,
                scoped_tools=scoped_tools,
                session_id=session_id,
                call_index=call_index,
                **{key: value for key, value in action.params.items() if key != "method"},
            )
        if action.handler == "phase14_cascade":
            raw_changes = action.params.get("changes")
            changes = [tuple(item) for item in raw_changes] if raw_changes else None
            audit_scenario = str(action.params.get("audit_scenario") or "86")
            return await runtime._phase14_start_cascade(
                session_id=session_id,
                changes=changes,
                audit_scenario=audit_scenario,
            )
        if action.handler == "dynamic_phase14_cascade":
            changes = runtime._phase14_cascade_priority_changes(normalize_prompt(intent))  # type: ignore[attr-defined]
            if not changes:
                return None
            return await runtime._phase14_start_cascade(
                session_id=session_id,
                changes=changes,
                audit_scenario=str(action.params.get("audit_scenario") or "86"),
            )
        if action.handler == "approval_payload":
            raise PlannerApprovalRequired(
                str(action.params.get("message") or "Seeded approval required."),
                approval=dict(action.params.get("approval") or {}),
            )
        if action.handler == "draft_then_call":
            if call_index == 1:
                draft = dict(action.params.get("draft") or {})
                return runtime._draft_only(intent=intent, scoped_tools=scoped_tools, **draft)  # type: ignore[attr-defined]
            await asyncio.sleep(float(action.params.get("delay_seconds") or 0))
            return await self._call_runtime(
                runtime,
                method_name=str(action.params["method"]),
                intent=intent,
                scoped_tools=scoped_tools,
                session_id=session_id,
                call_index=call_index,
            )
        if action.handler == "draft_then_completed":
            if call_index == 1:
                draft = dict(action.params.get("draft") or {})
                return runtime._draft_only(intent=intent, scoped_tools=scoped_tools, **draft)  # type: ignore[attr-defined]
            await asyncio.sleep(float(action.params.get("delay_seconds") or 0))
            completed = dict(action.params.get("completed") or {})
            return await runtime._completed_with_summary(  # type: ignore[attr-defined]
                intent=intent,
                scoped_tools=scoped_tools,
                **completed,
            )
        if action.handler == "completed_with_summary":
            return await runtime._completed_with_summary(  # type: ignore[attr-defined]
                intent=intent,
                scoped_tools=scoped_tools,
                **action.params,
            )
        raise ValueError(f"Unsupported seeded scenario generate handler: {action.handler}")

    async def _call_runtime(self, runtime: SeededScenarioRuntime, *, method_name: str, **available: Any) -> Any:
        method = getattr(runtime, method_name)
        signature = inspect.signature(method)
        kwargs = {name: available[name] for name in signature.parameters if name in available}
        result = method(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
