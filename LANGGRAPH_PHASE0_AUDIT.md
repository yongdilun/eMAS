# LangGraph Migration Phase 0 Audit Baseline

Date: 2026-05-12

Updated: 2026-05-13 reference-check pass; 2026-05-13 Phase 1 schema evidence update; 2026-05-13 Phase 2 intent evidence update; 2026-05-13 Phase 3 planner-loop evidence update; 2026-05-13 Phase 4 tool execution evidence update; 2026-05-13 Phase 5 dry-run/approval/commit evidence update; 2026-05-13 Phase 6 checkpoint/execution-truth evidence update

Scope: evidence-only audit of active runtime paths for session creation, message submission, plan creation, execution, approval, snapshot, SSE, checkpointing, and legacy replay. No behavior-changing fixes were made in this pass.

## Executive Status

| Area | Status | Evidence |
| --- | --- | --- |
| Session CRUD | PARTIAL | `SessionRow` is still the public session record and is used by API/UI compatibility paths in `factory-agent/factory_agent/api/routes.py:1307`, `factory-agent/factory_agent/api/routes.py:1320`, `factory-agent/factory_agent/api/routes.py:1332`, and `factory-agent/factory_agent/orchestration/session_manager.py:49`. |
| Message submission | PARTIAL | Messages are persisted as relational `MessageRow` records at `factory-agent/factory_agent/api/routes.py:1472`; user messages can mutate legacy step state or graph approval rows depending on current plan classification. |
| Plan creation | LEGACY STILL USED | `/sessions/{session_id}/plans` calls LangGraph through `PlannerService`, but persists the result as `PlanRow` and `PlanStepRow` compatibility records in `_persist_plan` at `factory-agent/factory_agent/api/routes.py:489`. It also still gates non-operation requests through `assess_intent` at `factory-agent/factory_agent/api/routes.py:1715`. |
| Execution | PARTIAL | `/sessions/{session_id}/execute` routes graph-native sessions to `_run_langgraph_session` at `factory-agent/factory_agent/api/routes.py:2047`, but falls back to `ExecutionEngine.execute_until_blocked` at `factory-agent/factory_agent/api/routes.py:2113` for legacy/current-plan sessions. |
| Approval | PARTIAL | Graph approvals use `subject_type="graph"` and resume via `Command(resume=...)` through `PlannerService.resume_after_approval`; Phase 6 proves resume survives process-local checkpointer reset. Plan/step approval paths remain for compatibility/legacy sessions, and legacy step approval now returns `409` without mutation for graph-native sessions. |
| Snapshot | PARTIAL | `GET /sessions/{session_id}/snapshot` exists at `factory-agent/factory_agent/api/routes.py:1382`. For graph-native sessions, Phase 6 now derives steps from LangGraph checkpoint state or LangGraph compatibility projections and suppresses legacy step execution rows; non-graph snapshot/SSE compatibility paths remain relational. |
| SSE | PARTIAL | Semantic SSE exists at `factory-agent/factory_agent/api/routes.py:1393`, but it polls snapshot timeline diffs rather than streaming directly from graph state changes. |
| Native LangGraph graph | PARTIAL | The compiled graph includes `input_layer -> intent_splitter -> prepare -> planner -> decision_guard -> tool_execution -> relevance_filter -> planner`, plus validation, dry-run, commit, fatal, and clarification nodes in `factory-agent/factory_agent/graph/builder.py:39`. Runtime entry is `graph.ainvoke` at `factory-agent/factory_agent/graph/planner_graph.py:72`; Phase 5 now detects native interrupt payloads from checkpoint snapshots and resumes with `Command(resume=...)`. |
| Checkpointing | DONE for graph-native | Native LangGraph checkpointer is wired in `factory-agent/factory_agent/graph/builder.py:123`, and resume uses `thread_id=session_id` in `factory-agent/factory_agent/graph/planner_graph.py:103`. Phase 6 adds DB-backed durable LangGraph checkpoints in `factory-agent/factory_agent/graph/checkpointing.py` using `workflow_checkpoints`, with JSON-safe `agent_state` projection for snapshots and native checkpoint payload for resume. Legacy memory checkpoints remain only in legacy execution paths. |
| Backend transaction bundle API | DONE | Go API now exposes `POST /api/v1/agent/transaction/bundle-dry-run` and `POST /api/v1/agent/transaction/commit` through `emas/internal/handler/agent_transaction_handler.go` and `emas/internal/router/router.go`; `emas/internal/service/agent_transaction_service.go` applies commit bundles inside one GORM transaction and requires backend idempotency on commit. |
| DLQ replay | LEGACY STILL USED | `/dlq/{dlq_id}/replay` is still present at `factory-agent/factory_agent/api/routes.py:2536`; it blocks graph-native sessions and remains able to mutate legacy step sessions. Phase 6 also makes the `main.py` DLQ replay event listener skip graph-native sessions. |
| Worker/cold-start recovery | LEGACY STILL USED | `main.py` worker execution still calls `executor.execute_until_blocked` for legacy sessions, and cold-start recovery/event listeners still mutate `PlanStepRow`/`SessionRow` for legacy sessions. Phase 6 adds graph-native guards so worker execution, cold-start recovery, stuck-step reconciliation, approval events, cancel events, and DLQ replay events skip graph-native sessions. |
| Frontend chat recovery | PARTIAL | Frontend hydrates from snapshot and opens semantic SSE in `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js:169` and `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js:233`; it still calls create-plan then execute in `runIntent` at `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js:360`. |

## Reference-Check Pass

| Candidate | Reference result | Phase 0 decision |
| --- | --- | --- |
| `ExecutionEngine.execute_until_blocked` | Runtime references remain in `factory-agent/factory_agent/api/routes.py:2113` and `factory-agent/main.py:162`; tests still cover it in `factory-agent/tests/test_execution_engine.py` and `factory-agent/tests/test_approval_resume_integration.py`. | Not safe cleanup. This is active legacy execution and must be retired in a behavior-changing phase. |
| `QueryRouter` / route scores | No active production import of `QueryRouter` was found outside `factory-agent/factory_agent/orchestration/router.py`, but route-score-shaped assumptions remain in tests such as `factory-agent/tests/test_phase5_agent_integration.py:109`. | Approval-gated cleanup. The module is probably removable later, but only after compatibility tests and docs are deliberately rescaled. |
| `assess_intent` | Still used by `/sessions/{session_id}/plans` in `factory-agent/factory_agent/api/routes.py:1716`, `ToolSelector` in `factory-agent/factory_agent/planning/tool_selector.py:570`, and tool scope helpers in `factory-agent/factory_agent/planning/tool_scope.py:80`. | Not safe cleanup. It is compatibility-only by intent, but still active. |
| `SessionRow` | Used across API, session manager, memory manager, worker recovery, and frontend-facing snapshot/session responses. | Keep for UI/history compatibility. |
| `PlanRow` | Used by plan creation, graph-native detection through `created_by="langgraph"`, snapshot projection, approval paths, and legacy execution. | Keep for compatibility projection until graph checkpoint state becomes execution truth. |
| `PlanStepRow` | Used by snapshot steps, legacy execution, cold-start recovery, approval mutations, DLQ replay, and tests. | Keep for legacy and compatibility projection. Not graph-native truth. |
| DLQ replay | `/dlq/{dlq_id}/replay` remains live at `factory-agent/factory_agent/api/routes.py:2536` and event handling remains in `factory-agent/main.py:550`; it explicitly blocks graph-native sessions. | Legacy still used. Keep blocked for graph-native sessions; retire later. |
| Frontend `createPlan -> execute` flow | `useFactoryAgentChat.js` still calls `createPlan` before execute in `runIntent` at line 360 and retry flows at lines 390 and 511. | Behavior-changing to alter. Needs approval before changing UX/API flow. |
| Graph approval detection | Graph sessions are detected through `created_by="langgraph"` and `replan_context.langgraph_pending_approval` at `factory-agent/factory_agent/api/routes.py:292` and `factory-agent/factory_agent/api/routes.py:301`. | Compatibility shim. Keep until graph checkpoint/session metadata replaces it. |

## Phase 1 Evidence Update

Phase 1 confirmed a runtime API schema mismatch from the Phase 0 approval path evidence: graph-native approvals are persisted with `subject_type="graph"` in `factory-agent/factory_agent/api/routes.py:1923`, while the public `ApprovalResponse` contract only accepted `step` and `plan`. The API schema now allows `ApprovalSubjectType = Literal["step", "plan", "graph"]` in `factory-agent/factory_agent/schemas.py:116`; this is a compatibility contract fix, not a legacy behavior retirement.

Phase 1 also confirmed that `AgentState` reducer annotations can initialize and pass through a dummy `StateGraph(AgentState)`. Evidence lives in `factory-agent/tests/test_agent_state.py`, covering `add_messages`, append-only trace reducers, overwrite fields, and the `replace_list()` clear sentinel for clearable buffers.

Verification for this Phase 1 update: `python -m pytest tests/test_agent_state.py`, `python -m pytest tests/test_agent_state.py tests/test_planner_phase3.py tests/test_tool_pipeline.py tests/test_phase5_final_validator.py`, and `python -m compileall factory_agent`.

## Phase 2 Evidence Update

Phase 2 confirmed that graph-native runtime intent understanding is isolated in `factory-agent/factory_agent/graph/nodes/intent_split.py`: `intent_splitter_node` calls `split_user_intents`, then writes the serialized output to `intents`, `working_intents`, `intent_cursor`, and `current_intent` before planner execution. `split_user_intents` in `factory-agent/factory_agent/planning/intent.py` now emits deterministic intent IDs, preserves order-based dependency references for multi-part requests, parses incomplete requests into pending intents, and captures explicit machine, job, product, date, and operator constraints with hard/soft strength.

`assess_intent` remains active in compatibility call sites documented in Phase 0, but it is compatibility-only and delegates to `split_user_intents`. No Phase 0 legacy retirement behavior was changed. `QueryRouter` remains deprecated compatibility code in `factory-agent/factory_agent/orchestration/router.py`, and Phase 2 verification confirmed graph-native code under `factory_agent/graph` does not import `QueryRouter` or route-score fields.

Verification for this Phase 2 update: `python -m pytest tests/test_intent_splitter.py`, `python -m pytest tests/test_intent.py tests/test_intent_splitter.py tests/test_planner_phase3.py tests/test_agent_state.py`, and `python -m compileall factory_agent`.

## Phase 3 Evidence Update

Phase 3 confirmed the graph-native planner loop is active as the execution brain inside the compiled graph for native runs: `Planner -> DecisionGuard -> ToolExecution -> RelevanceFilter -> Planner`, ending in plan synthesis and validation from graph trace state. `factory-agent/tests/test_planner_phase3.py` runs a compiled graph for a multi-intent request and verifies the first guard-blocked tool call is not executed, the repaired call is executed, the second intent proceeds only after the first completes, planner decisions are retained, and `completed_actions` contains planner, guard, tool execution, and relevance trace entries used for final plan synthesis.

Phase 3 also confirmed dependency cancellation behavior in `make_planner_node`: when an upstream intent returns `intent_failed`, pending dependent intents are marked `cancelled_due_to_dependency_failure` with the upstream failure reason. Guard violations now append `failed_strategies` repair entries in addition to `completed_actions`, giving the next planner turn a concrete repair signal without retiring legacy API or frontend plan compatibility paths.

A runtime-path parsing fact discovered during Phase 3 testing updated the Phase 2 evidence: plural `jobs` was being parsed as a hard `job_id="S"` constraint, which caused correct guard behavior to block a normal `list jobs` read. `factory-agent/factory_agent/planning/intent.py` now requires a word boundary after singular `job` before extracting a job ID, and `factory-agent/tests/test_intent_splitter.py` covers that plural-list case. This is a graph-input correctness fix, not a Phase 0 legacy retirement.

Verification for this Phase 3 update: `python -m pytest tests/test_planner_phase3.py tests/test_intent_splitter.py`, `python -m pytest tests/test_agent_state.py tests/test_intent.py tests/test_intent_splitter.py tests/test_planner_phase3.py tests/test_tool_pipeline.py tests/test_phase5_final_validator.py`, and `python -m compileall factory_agent`.

## Phase 4 Evidence Update

Phase 4 confirmed the graph-native tool lane in `factory-agent/factory_agent/graph/nodes/tool_pipeline.py`: read tools execute through `execute_tool_http`, normalize HTTP response envelopes into a relevance batch, and only become appended `tool_outputs` after `RelevanceFilterNode` has marked usefulness. Read execution also updates `retrieved_info` with stable read keys and relevance trace metadata.

Phase 4 also tightened a runtime-path fact: graph write tool calls now append staged operations to `staged_writes` without adding synthetic staged-write rows to `tool_outputs` and without calling mutating backend endpoints during planning. Transaction-scoped `$ref:` dependencies and hard explicit constraints are blocked in `decision_guard_node` before `ToolExecutionNode`; invalid refs append repair signals to `failed_strategies` and route back to the planner. Infrastructure read failures set `fatal_system_error` with a `FATAL_SYSTEM_ERROR:...` value and route to `fatal_end`.

No Phase 0 legacy retirement behavior was changed. Legacy `ExecutionEngine`, relational plan/step compatibility projection, graph approval shims, and DLQ safeguards remain in the same active/compatibility categories documented above.

Verification for this Phase 4 update: `python -m pytest tests/test_tool_pipeline.py -q`, `python -m pytest tests/test_agent_state.py tests/test_intent.py tests/test_intent_splitter.py tests/test_planner_phase3.py tests/test_tool_pipeline.py tests/test_phase5_final_validator.py -q`, and `python -m compileall factory_agent`.

## Phase 5 Evidence Update

Phase 5 confirmed the graph-native write lane now follows the required order: write tool calls stage only, `FinalValidatorNode` routes staged writes to backend bundle dry-run before final validation, final validation runs after successful dry-run, native LangGraph `interrupt()` pauses for approval, `Command(resume=...)` resumes the interrupted checkpoint, and `CommitNode` sends one backend transaction bundle. `commit_node_impl` refuses to call the backend unless `bundle_dry_run_result.ok`, a successful validation result, and an approved graph approval request are all present.

Phase 5 also confirmed the installed LangGraph version stores interrupt payloads in checkpoint snapshot tasks rather than in a `__interrupt__` result field for this runtime. `factory-agent/factory_agent/graph/planner_graph.py` now checks both shapes, and `factory-agent/factory_agent/graph/checkpointing.py` reuses the in-process memory checkpointer so API approval resume can continue from the paused thread in the same backend process. This is not durable restart recovery; Phase 6 still owns production checkpoint durability.

The Go backend now provides graph-native transaction support at `POST /api/v1/agent/transaction/bundle-dry-run` and `POST /api/v1/agent/transaction/commit`. Dry-run executes the bundle inside a transaction and rolls it back; commit executes supported write operations inside one GORM transaction, requires a bundle idempotency key plus per-operation idempotency keys, resolves transaction-scoped refs, and rolls back the whole bundle on business conflicts.

A runtime-path parsing fact discovered during Phase 5 testing updated the Phase 2 evidence: `create a job for product P-001` was being parsed as hard `job_id="FOR"`, which caused the Phase 3 guard to block legitimate create-job writes before dry-run. `factory-agent/factory_agent/planning/intent.py` now only extracts job IDs that look like numeric or prefixed identifiers, and `factory-agent/tests/test_intent_splitter.py` covers the `job for product` case. This is a graph-input correctness fix, not Phase 0 legacy retirement.

No Phase 0 legacy retirement behavior was changed. Legacy `ExecutionEngine`, relational plan/step compatibility projection, graph approval shims, and DLQ safeguards remain in the same active/compatibility categories documented above.

Verification for this Phase 5 update: `python -m pytest factory-agent/tests/test_agent_state.py factory-agent/tests/test_intent.py factory-agent/tests/test_intent_splitter.py factory-agent/tests/test_planner_phase3.py factory-agent/tests/test_tool_pipeline.py factory-agent/tests/test_phase5_final_validator.py -q`, `python -m compileall factory-agent/factory_agent`, `go test ./internal/handler -run AgentTransaction -count=1`, and `go test ./internal/service -run '^$' -count=1`.

## Phase 6 Evidence Update

Phase 6 confirmed graph checkpoint state is now the graph-native execution truth. `factory-agent/factory_agent/graph/checkpointing.py` provides a DB-backed LangGraph saver using the existing `workflow_checkpoints` table for `GRAPH_CHECKPOINT_BACKEND=auto|db|database|sqlalchemy`, while preserving optional Postgres saver support if the LangGraph Postgres package is installed and memory/off modes for local tests. Each durable row stores the native LangGraph checkpoint payload for resume plus a JSON-safe `agent_state` projection for snapshot/history compatibility.

`factory-agent/tests/test_planner_service_phase6.py::test_durable_checkpoint_resumes_approval_after_process_restart` proves a write flow can interrupt for approval, clear process-local checkpointer state to simulate backend restart, then resume by `thread_id=session_id` from the durable LangGraph checkpoint without re-planning and continue into commit. This closes the Phase 5 same-process-only checkpoint gap.

Phase 6 also updated graph-native snapshot and legacy guardrails. `GET /sessions/{session_id}/snapshot` now suppresses legacy `PlanStepRow` execution rows for graph-native sessions unless the current plan is a LangGraph compatibility projection; checkpoint-derived graph steps receive stable compatibility idempotency keys. Legacy step approval rejection now returns `409` without mutating graph-native approval/session state. `main.py` worker execution, cold-start recovery, stuck-step reconciliation, approval events, cancel events, and DLQ replay events now skip graph-native sessions instead of mutating relational execution state.

No Phase 0 legacy retirement beyond the Phase 6 graph-native safety boundary was changed: legacy `ExecutionEngine`, legacy `PlanStepRow` execution, and DLQ replay remain active for legacy sessions.

Verification for this Phase 6 update: `python -m pytest tests/test_planner_service_phase6.py -q`, `python -m pytest tests/test_agent_state.py tests/test_intent.py tests/test_intent_splitter.py tests/test_planner_phase3.py tests/test_tool_pipeline.py tests/test_phase5_final_validator.py tests/test_planner_service_phase6.py -q`, and `python -m compileall factory_agent ../factory-agent/main.py`.

## Runtime Path Classification

| Runtime path | Classification | Notes |
| --- | --- | --- |
| `POST /sessions` | Compatibility | Creates `SessionRow` for public session identity/history. |
| `POST /sessions/{id}/messages` | Compatibility with legacy branches | Persists `MessageRow`; cancellation/replan behavior still edits `PlanStepRow` for non-LangGraph plans and graph approval rows for graph-native sessions. |
| `POST /sessions/{id}/plans` | Compatibility / legacy projection | Uses LangGraph planner when no client draft is supplied, but produces relational `PlanRow`/`PlanStepRow` as the public artifact. |
| `POST /sessions/{id}/execute` with no current plan | Graph-native | Calls `_run_langgraph_session`, which invokes LangGraph and persists compatibility rows after completion. |
| `POST /sessions/{id}/execute` with LangGraph-created plan or graph pending approval | Graph-native with compatibility projection | `_is_graph_native_session` detects `created_by="langgraph"` or `replan_context.langgraph_pending_approval`. |
| `POST /sessions/{id}/execute` with non-LangGraph plan | Legacy | Calls `ExecutionEngine.execute_until_blocked`. |
| `GET /sessions/{id}/snapshot` for graph-native sessions | Graph-native compatibility projection | Derives steps from LangGraph checkpoint `agent_state` or LangGraph-created compatibility plan rows; legacy step execution rows are suppressed for graph-native sessions. |
| `GET /sessions/{id}/snapshot` for legacy sessions | Compatibility projection | Still derives legacy session views from relational session/plan/step/message/event rows. |
| `GET /sessions/{id}/events/semantic` | Compatibility adapter | Emits semantic event names from snapshot timeline polling. |
| `POST /approvals/{id}/approve` for `subject_type="graph"` | Graph-native approval resume | Calls `planner.resume_after_approval(session_id, approved=True)`. |
| `POST /approvals/{id}/reject` for `subject_type="graph"` | Graph-native approval resume | Calls `planner.resume_after_approval(session_id, approved=False)`. |
| `POST /approvals/{id}/approve/reject` for `subject_type="plan"` | Compatibility | Plan approval rows remain supported. |
| `POST /approvals/{id}/approve/reject` for `subject_type="step"` | Legacy | Returns `409` without mutation for graph-native sessions, still active for legacy sessions. |
| `POST /api/v1/agent/transaction/bundle-dry-run` | Graph-native backend support | Validates staged write bundles inside a backend transaction and rolls back, used by graph-native Phase 5 write flow before approval. |
| `POST /api/v1/agent/transaction/commit` | Graph-native backend support | Commits approved staged write bundles inside one backend transaction with idempotency enforcement, used only after graph dry-run, final validation, and approval. |
| `POST /dlq/{id}/replay` | Legacy | Explicitly blocks graph-native sessions but mutates legacy step state. |
| Worker queue in `main.py` | Legacy | Background workers still execute relational plans through `ExecutionEngine`, but graph-native sessions are skipped. |

## Behavior-Changing Fixes Requiring Approval

1. Stop frontend `runIntent` from always creating a relational plan before execute; this changes the public workflow and should be approved before implementation.
2. Broader worker replacement remains future work, but Phase 6 disables worker queue execution for graph-native sessions; `main.py` still assumes `ExecutionEngine` for legacy sessions.
3. Replace `/plans` as execution truth with a graph-only run endpoint or make it a pure preview/projection API.
4. Make SSE derive from graph checkpoint state instead of snapshot polling; Phase 6 already makes snapshot steps for graph-native sessions checkpoint/projection-derived.
5. Retire legacy step approval and DLQ replay code entirely after legacy-session support is no longer needed; Phase 6 prevents these paths from mutating graph-native sessions.
6. Remove `QueryRouter`, route scoring, and legacy planner tests only after reference checks confirm graph-native runtime no longer imports or depends on them.

## Safe Cleanup

No safe cleanup was performed in this pass. Reference checks found no proven-dead helper/import/comment that is both migration-relevant and risk-free to remove. The obvious cleanup candidates are either active runtime paths, compatibility projections, or test-covered legacy behavior.

Validation for this pass was reference-check only:

- `rg` checks for `ExecutionEngine`, `execute_until_blocked`, `QueryRouter`, route scores, `assess_intent`, `PlanRow`, `PlanStepRow`, DLQ replay, graph approval shims, and frontend `createPlan -> execute`.
- No unit tests were run because no runtime code changed.

## Phase 0 Exit Gap

Phase 0 audit evidence is now sufficient to start Phase 1 planning. Phase 0 should not be marked fully complete until the team approves the behavior-changing retirement list or accepts that no safe cleanup is available in this phase.
