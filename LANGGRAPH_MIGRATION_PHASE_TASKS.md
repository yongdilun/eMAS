# LangGraph Migration Phase Tasks

This checklist separates the remaining LangGraph migration work into clear phases with explicit exit requirements. Use it as the operational tracker for proving the migration is complete, not just partially implemented.

## Phase 0: Audit Baseline And Safety Boundary

Status: AUDITED. Evidence baseline and reference-check pass live in `LANGGRAPH_PHASE0_AUDIT.md`.

### Tasks
- Confirm the real runtime entry points for session creation, message submission, plan creation, execution, approval, snapshot, and SSE.
- Label every active execution path as either graph-native, compatibility, or legacy.
- Keep `SessionRow`, `PlanRow`, and `PlanStepRow` only where needed for UI/history compatibility.
- Document all behavior-changing fixes that require approval before implementation.
- Remove only safe audit-blocking clutter such as unused imports, obsolete comments, and proven-dead helpers.

### Exit Requirement
- A current audit report identifies all active runtime paths and clearly marks each migration area as `DONE`, `PARTIAL`, `WRONG`, `MISSING`, `LEGACY STILL USED`, or `CLEANED UP`.
- No behavior-changing migration fix has been made without approval.
- Safe cleanup is documented with reference checks and tests.

## Phase 1: State Schema And Core Types

Status: COMPLETE. Evidence: `factory-agent/tests/test_agent_state.py` proves `AgentState` passes through a dummy LangGraph graph; reducers append messages/traces, overwrite scalar/map fields, and clear `staged_writes` via `replace_list()`. `factory-agent/factory_agent/schemas.py` now accepts graph-native approval responses with `subject_type="graph"`. Verification run on 2026-05-13: `python -m pytest tests/test_agent_state.py`, `python -m pytest tests/test_agent_state.py tests/test_planner_phase3.py tests/test_tool_pipeline.py tests/test_phase5_final_validator.py`, and `python -m compileall factory_agent`.

### Tasks
- Finalize `AgentState` as the LangGraph execution state shape.
- Ensure reducer behavior is correct for messages, append-only traces, clearable buffers, and overwrite fields.
- Keep legacy fields out of graph state unless explicitly isolated for compatibility.
- Align schemas for `Intent`, `ExplicitConstraint`, `PlannerDecision`, `ToolCall`, staged writes, approvals, validation results, and errors.
- Fix API schemas that contradict runtime graph values.

### Exit Requirement
- `AgentState` initializes and passes through a dummy LangGraph graph.
- Type checks or equivalent import/compile checks pass.
- API response models accept every graph-native value emitted at runtime, including graph approvals if still exposed through approval APIs.
- Tests prove reducers append, overwrite, and clear state exactly as intended.

## Phase 2: Intent Understanding Layer

Status: COMPLETE. Evidence: `factory-agent/factory_agent/planning/intent.py` now makes `split_user_intents` the canonical deterministic decomposition layer with stable intent IDs, dependency references, incomplete-query parsing, and structured machine/job/product/date/operator constraints with hard/soft strength preservation. `factory-agent/factory_agent/graph/nodes/intent_split.py` feeds splitter output into `intents`, `working_intents`, `intent_cursor`, and `current_intent` before planner execution. `assess_intent` remains a legacy compatibility API that delegates to `split_user_intents`, and graph-native code under `factory_agent/graph` has no `QueryRouter` or route-score dependency. Verification run on 2026-05-13: `python -m pytest tests/test_intent_splitter.py`, `python -m pytest tests/test_intent.py tests/test_intent_splitter.py tests/test_planner_phase3.py tests/test_agent_state.py`, and `python -m compileall factory_agent`.

### Tasks
- Make the intent splitter the canonical query decomposition layer.
- Ensure incomplete queries are parsed, not rejected.
- Extract hard and soft explicit constraints into structured `ExplicitConstraint` records.
- Capture multi-intent dependencies.
- Clearly isolate `assess_intent` as compatibility-only if it remains active.
- Remove or bypass legacy route scoring for graph-native execution.

### Exit Requirement
- Complex multi-part requests produce multiple structured intents with stable dependency relationships.
- Explicit user constraints such as machine, job, product, date, or operator requirements are preserved in state.
- Runtime graph entry uses `split_user_intents` output as execution state input.
- No graph-native execution decision depends on `QueryRouter` weighted route scores.

## Phase 3: Planner Loop And Graph Rewiring

Status: COMPLETE. Evidence: `factory-agent/factory_agent/graph/nodes/planner_loop.py` now records guard violations as `failed_strategies` repair signals while routing back to the planner, preserving the `completed_actions` trace. `factory-agent/tests/test_planner_phase3.py` proves a compiled LangGraph run handles `Find available machine M-001 and then list jobs` through `Planner -> DecisionGuard -> ToolExecution -> RelevanceFilter -> Planner`, blocks the first constraint-violating machine call without HTTP execution, repairs it, completes both intents, and derives the final validated plan from graph `completed_actions`. The same test module proves upstream intent failure cancels dependent intents with `cancelled_due_to_dependency_failure`. Phase 3 also fixed a discovered splitter/runtime mismatch where plural `jobs` was incorrectly parsed as `job_id="S"`; `factory-agent/tests/test_intent_splitter.py` now covers that case. Verification run on 2026-05-13: `python -m pytest tests/test_planner_phase3.py tests/test_intent_splitter.py`, `python -m pytest tests/test_agent_state.py tests/test_intent.py tests/test_intent_splitter.py tests/test_planner_phase3.py tests/test_tool_pipeline.py tests/test_phase5_final_validator.py`, and `python -m compileall factory_agent`.

### Tasks
- Use the LangGraph loop as the execution brain: `Planner -> DecisionGuard -> ToolExecution -> RelevanceFilter -> Planner`.
- Normalize model output into strict `PlannerDecision` envelopes.
- Enforce explicit constraints before tool execution.
- Support sequential multi-intent processing with dependency failure cancellation.
- Maintain execution trace in `completed_actions`.
- Route clarification, completion, failure, and halt decisions through graph state.

### Exit Requirement
- A graph run can process at least one multi-intent request through planner decisions without creating a legacy step plan as the execution truth.
- Guard violations skip tool execution and route back to the planner for repair.
- Dependent intents are cancelled when upstream intents fail.
- Tests prove planner decisions, guard behavior, dependency cancellation, and trace updates.

## Phase 4: Tool Execution, Staging, And Relevance

Status: COMPLETE. Evidence: `factory-agent/factory_agent/graph/nodes/tool_pipeline.py` now keeps write tool decisions in `staged_writes` without emitting synthetic `tool_outputs` or calling mutating backend endpoints during the planning loop; only read HTTP envelopes flow through `pending_relevance_batch` into relevance-filtered `tool_outputs` and `retrieved_info`. `factory-agent/tests/test_tool_pipeline.py` proves read execution, write staging with HTTP blocked, unknown `$ref:` validation, hard constraint blocking via Phase 3 guard coverage, semantic filtering only when `ToolInfo.requires_semantic_filter` is set, and infrastructure failure routing through `FATAL_SYSTEM_ERROR` to `fatal_end`. Verification run on 2026-05-13: `python -m pytest tests/test_tool_pipeline.py -q`, `python -m pytest tests/test_agent_state.py tests/test_intent.py tests/test_intent_splitter.py tests/test_planner_phase3.py tests/test_tool_pipeline.py tests/test_phase5_final_validator.py -q`, and `python -m compileall factory_agent`.

### Tasks
- Keep read tools as deterministic graph tool nodes.
- Ensure read outputs update only `tool_outputs` and `retrieved_info`.
- Ensure write tools stage proposed operations and never perform physical writes during the planning loop.
- Validate transaction-scoped `$ref:` dependencies before staging.
- Run relevance filtering after tool execution.
- Use semantic filtering only when tool metadata requires it.
- Distinguish logical errors from infrastructure errors.

### Exit Requirement
- Read tool calls execute through LangGraph nodes and append normalized outputs to graph state.
- Write tool calls append only `staged_writes`; they do not directly call mutating backend endpoints.
- Invalid refs and hard constraint violations are blocked before tool execution.
- Infrastructure failures set `FATAL_SYSTEM_ERROR` and halt.
- Tests prove read execution, write staging, ref validation, relevance filtering, and fatal error routing.

## Phase 5: Dry Run, Approval, Commit, And Recovery

Status: COMPLETE. Evidence: `factory-agent/factory_agent/graph/nodes/validate.py` now routes staged writes to bundle dry-run before final validation and approval, then uses native LangGraph `interrupt()` approval and resumes with `Command(resume=...)` from the checkpoint before commit. `factory-agent/factory_agent/graph/planner_graph.py` now detects interrupt payloads from native LangGraph checkpoint snapshots, and `factory-agent/factory_agent/graph/checkpointing.py` shares the in-process memory checkpointer so API approval resume can continue the interrupted thread without re-planning. `factory-agent/factory_agent/graph/nodes/tool_pipeline.py` refuses commit before successful dry-run, final validation, and approval; commit posts exactly one transaction bundle with deterministic bundle and per-write idempotency keys. `emas/internal/handler/agent_transaction_handler.go` and `emas/internal/service/agent_transaction_service.go` add backend bundle dry-run and atomic commit endpoints with backend idempotency enforcement via `Idempotency-Key` and one GORM transaction. `factory-agent/tests/test_phase5_final_validator.py` proves dry-run-before-approval routing, dry-run repair, approval interrupt/resume without re-planning, commit precondition blocking, single bundle commit success, business conflict repair routing, and infrastructure fatal halt. `emas/internal/handler/agent_transaction_handler_test.go` proves backend dry-run does not commit, commit is idempotent, and business conflicts roll back the whole transaction. Phase 5 also fixed a discovered splitter/runtime mismatch where `create a job for product P-001` was incorrectly parsed as hard `job_id="FOR"`; `factory-agent/tests/test_intent_splitter.py` now covers that case. Verification run on 2026-05-13: `python -m pytest factory-agent/tests/test_agent_state.py factory-agent/tests/test_intent.py factory-agent/tests/test_intent_splitter.py factory-agent/tests/test_planner_phase3.py factory-agent/tests/test_tool_pipeline.py factory-agent/tests/test_phase5_final_validator.py -q`, `python -m compileall factory-agent/factory_agent`, `go test ./internal/handler -run AgentTransaction -count=1`, and `go test ./internal/service -run '^$' -count=1`.

### Tasks
- Implement backend bundle dry-run endpoint for staged writes.
- Implement backend atomic transaction commit endpoint.
- Generate semantic deterministic idempotency keys for staged and committed writes.
- Enforce idempotency on the backend.
- Run final validation before approval and commit.
- Use native LangGraph interrupts for approval pauses.
- Resume approval with `Command(resume=...)`.
- Keep auto-repair forward-moving; do not erase failed strategies.
- Truncate bulky failed-attempt state while preserving concise failure summaries.

### Exit Requirement
- A write request follows this exact flow: stage writes, bundle dry-run, final validation, approval interrupt, checkpoint resume, atomic commit.
- No write operation commits before dry-run, validation, and approval.
- Commit uses one backend transaction bundle, not separate REST write calls.
- Approval resume continues from the interrupted checkpoint without re-planning the approved action.
- Business commit failures route to bounded auto-repair.
- Infrastructure commit failures halt with `FATAL_SYSTEM_ERROR`.
- Tests prove approval interrupt/resume, dry-run failure handling, commit success, commit conflict repair, and infrastructure halt.

## Phase 6: Checkpointing And Execution Truth

Status: COMPLETE. Evidence: `factory-agent/factory_agent/graph/checkpointing.py` now provides durable DB-backed native LangGraph checkpointing via the existing `workflow_checkpoints` table when `GRAPH_CHECKPOINT_BACKEND=auto|db|database|sqlalchemy`, while still preserving optional Postgres saver support and memory/off modes. `factory-agent/tests/test_planner_service_phase6.py` proves an approval interrupt can be resumed after clearing process-local checkpointer state, without re-planning and with commit continuing from the LangGraph checkpoint. `GET /sessions/{session_id}/snapshot` now suppresses legacy step execution rows for graph-native sessions unless they are LangGraph compatibility projections, and checkpoint-derived graph steps receive stable compatibility IDs. Legacy step approval rejection now returns `409` for graph-native sessions without mutating approval/session state, and `factory-agent/main.py` worker, cold-start recovery, stuck-step reconciliation, approval event, cancel event, and DLQ replay event paths skip graph-native sessions instead of mutating relational execution rows. Verification run on 2026-05-13: `python -m pytest tests/test_planner_service_phase6.py -q`, `python -m pytest tests/test_agent_state.py tests/test_intent.py tests/test_intent_splitter.py tests/test_planner_phase3.py tests/test_tool_pipeline.py tests/test_phase5_final_validator.py tests/test_planner_service_phase6.py -q`, and `python -m compileall factory_agent ../factory-agent/main.py`.

### Tasks
- Configure durable LangGraph checkpointing for production.
- Ensure compiled graph instances can resume interrupted sessions by `thread_id`.
- Stop treating relational plan/step rows as execution truth for graph-native sessions.
- Use legacy relational rows only as compatibility projections for UI/history if still needed.
- Remove or disable legacy DLQ replay for graph-native execution.

### Exit Requirement
- Killing/restarting the backend during a waiting approval state still allows approval resume from the LangGraph checkpoint.
- Graph checkpoint state is the internal execution truth.
- Snapshot data for graph sessions is derived from graph state or compatibility projections, not from legacy step execution.
- Legacy replay and step approval paths cannot mutate graph-native sessions.

## Phase 7: API And UI Alignment

### Tasks
- Provide `GET /sessions/{session_id}/snapshot` as frontend recovery truth.
- Stream semantic SSE events from graph state changes or a graph event adapter.
- Keep raw LangGraph state internal.
- Update frontend to hydrate from snapshot before opening SSE.
- On reconnect, refetch snapshot and resume semantic event consumption.
- Remove frontend assumptions that all execution is relational plan/step based.

### Exit Requirement
- Browser refresh, network reconnect, approval pause, and backend restart all recover by snapshot hydration.
- SSE emits semantic events such as `PLANNER_THINKING`, `TOOL_STARTED`, `TOOL_RESULT`, `APPROVAL_REQUIRED`, `APPROVAL_DECIDED`, `SESSION_COMPLETED`, and `SESSION_FAILED`.
- Frontend rendering does not parse raw graph blobs.
- Graph-native sessions display correctly without relying on legacy `PlanStepRow` execution state.

## Phase 8: Legacy Retirement And Contract Cleanup

### Tasks
- Identify all remaining uses of `ExecutionEngine`, `QueryRouter`, route scores, legacy approvals, DLQ replay, and relational execution state.
- Remove inactive legacy code only after reference checks.
- Keep compatibility code clearly labeled and isolated.
- Update tests to stop proving legacy behavior as the primary path.
- Add migration documentation for any intentional compatibility shims.

### Exit Requirement
- No graph-native user flow reaches `ExecutionEngine.execute_until_blocked`.
- `QueryRouter` is unused by graph-native runtime.
- Legacy-only code is either removed or clearly marked as compatibility.
- Tests prove graph-native execution end-to-end.
- Remaining legacy tests are explicitly scoped as compatibility tests.

## Phase 9: Final Verification Gate

### Tasks
- Run targeted LangGraph tests.
- Run API integration tests.
- Run frontend smoke tests for snapshot and SSE.
- Run backend transaction tests against the Go API.
- Run full test suite or document known long-running exclusions.
- Produce final migration evidence.

### Exit Requirement
- All required tests pass or have documented, approved exclusions.
- A final report states which legacy code remains and why.
- End-to-end evidence proves read flow, write flow, approval pause/resume, atomic commit, recovery, SSE, and frontend hydration.
- Migration status can be marked complete only when graph checkpoint state is the internal execution truth and legacy execution paths are no longer active for graph-native sessions.
