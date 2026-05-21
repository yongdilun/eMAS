# Planner-Owned Agent Graph Migration Tracker

## Current Status

Status: Phase 3 complete. The planner-owned LangGraph shell is added behind an explicit test/debug entry point without switching normal runtime.

This tracker belongs to `PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md`. It starts after `PLANNER_OWNED_AGENT_LOOP_MIGRATION.md` Phase 15.

Primary objective:

```text
Move normal v2 runtime from service-level direct execution to a real planner-owned LangGraph agent graph.
```

## Starting Baseline

Confirmed starting facts:

- The previous planner-owned loop migration is complete through Phase 15.
- Normal legacy and shadow runtime authority was removed in the previous migration.
- Current v2 contracts, evidence satisfaction, approval safety, response documents, hardcode guardrails, and cleanup tests are valuable and must be preserved.
- `PlannerOwnedV2Loop` remains a shallow planning/contract module, not the full graph-owned execution loop.
- `plan_creation_service.py` still contains service-level direct v2 execution helpers that must be moved behind graph authority in this migration.
- The old `factory_agent.graph` concepts such as `working_intents`, `intent_cursor`, and `intent_completed` must not become execution authority again.
- Baseline note from 2026-05-21: the user reports `npm run test:e2e:seeded-oracles` and `npm run test:e2e:real-langgraph` are passing before this migration begins. Treat later failures in those lanes as migration regressions unless the tracker proves an unrelated external cause.

Previous tracker debt note:

- The previous tracker mentioned seeded-oracle HQ-9/LOTO/SSE and real-LangGraph SO-026 LOTO follow-up debt.
- Because the user reports both suites are now green, this new migration should not carry those as active waivers.
- If those failures reappear, classify them as new regression, unrelated external issue with proof, or explicitly reopened debt with owner and removal gate.

State/checkpoint decision:

- Authoritative graph state is `PlannerOwnedAgentGraphState` from `factory-agent/factory_agent/planning/v2_agent_state.py`.
- Graph checkpointing must reuse `build_graph_checkpointer(settings)` from `factory-agent/factory_agent/graph/checkpointing.py`.
- Durable resume should use LangGraph native checkpoint payloads stored through the existing checkpoint saver, not a hand-built state from `session.replan_context`.
- `session.replan_context` may carry lightweight UI/pointer metadata only.

## Progress Table

| Phase | Name | Status | Commit | Required Gate |
| --- | --- | --- | --- | --- |
| 1 | Graph state and trace contracts | Complete | `fb1d24b9cb93778ba8ab7ae93387b84ab9dbfc07` | Focused Phase 1 state tests plus existing v2 cleanup guard |
| 2 | Planner decision interface | Complete | pending final commit | Decision validation tests plus route/tool guardrails |
| 3 | LangGraph shell | Complete | pending final commit | Node transition tests plus fake tracer proof |
| 4 | Retrieval and tool choice | Not started |  | Candidate-window and no-new-retriever tests |
| 5 | Tool/RAG execution and evidence observation | Not started |  | Evidence observation tests plus satisfaction guard |
| 6 | Read-only product flows | Not started |  | Mixed read, empty-result, response-document tests and E2E |
| 7 | RAG as a graph tool | Not started |  | Citation/insufficient-context tests without legacy RAG route |
| 8 | Writes, approval pause, and resume | Not started |  | Approval resume, stale approval, and UI approval tests |
| 9 | Interruptions, revisions, and stale work | Not started |  | Interrupt/revision/stale-work tests |
| 10 | Runtime switch to graph | Not started |  | Full backend plus frontend response-document and seeded-oracle gates |
| 11 | Test cleanup and legacy quarantine | Not started |  | Full backend with no new xfail/skips and static cleanup guardrails |
| 12 | Release proof | Not started |  | Full backend, frontend, seeded-oracle, real-LangGraph/release, trace proof |

## Phase Notes

### Phase 1: Graph State And Trace Contracts

Status: complete.

Planned files:

- `factory-agent/factory_agent/planning/v2_agent_state.py`
- `factory-agent/factory_agent/planning/v2_contracts.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase1_state.py`

Completion evidence to record:

- test command and count,
- trace identity added for graph-owned runtime,
- serialization proof,
- confirmation that direct-v2 trace identity is not reused as graph proof.

Completion evidence:

- Files changed: `factory-agent/factory_agent/planning/v2_agent_state.py`, `factory-agent/factory_agent/planning/v2_contracts.py`, `factory-agent/tests/test_planner_owned_agent_graph_phase1_state.py`, and this tracker.
- Added `PlannerOwnedAgentGraphState` with serializable graph-owned fields for original query, requirement ledger, capability map, candidate tool windows, hydrated tool cards, planner decisions, evidence ledger, pending approval, satisfaction state, final validation result, response-document context, revision history, execution trace, and engine version.
- Added graph trace identity `planner_owned_agent_graph`; historical trace values including `v2_planner_loop` remain parse/read compatible through `ExecutionTrace`, but graph state rejects them as graph proof.
- Focused tests prove a hard multi-step query builds requirements and locked constraints before execution, empty evidence cannot satisfy locked constraints, graph trace identity is distinct from direct-v2, and state serialization/deserialization preserves revision, evidence, candidate-window, approval, satisfaction, response-document, and trace fields.
- Normal runtime was not switched, direct-v2 helpers were not removed, no graph nodes were built, and no new ToolSelector/RAG/approval/response-document stack was added.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py -q` reported `4 passed, 3 warnings`.
- Tests run: PowerShell-expanded equivalent of `python -m pytest tests/test_planner_owned_loop_phase*_*.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` reported `88 passed, 120 warnings`. The literal glob command did not expand under this PowerShell invocation and ran no tests, so the rerun used expanded file paths.
- `git diff --check`: passed.
- Blockers: none.

### Phase 2: Planner Decision Interface

Status: complete.

Planned files:

- `factory-agent/factory_agent/planning/v2_planner_decisions.py`
- `factory-agent/factory_agent/planning/v2_agent_state.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase2_decisions.py`

Completion evidence to record:

- invalid decision rejection coverage,
- locked-constraint preservation coverage,
- no exact-prompt or seeded-ID branches.

Completion evidence:

- Files changed: `factory-agent/factory_agent/planning/v2_planner_decisions.py`, `factory-agent/factory_agent/planning/v2_agent_state.py`, `factory-agent/tests/test_planner_owned_agent_graph_phase2_decisions.py`, and this tracker.
- Added a strict `PlannerDecisionSubmission`/`validate_planner_decision()`/`record_planner_decision()` gate that validates planner decision records against `PlannerOwnedAgentGraphState` before later graph phases can retrieve tools, choose tools, execute, request approval, revise requirements, clarify, finalize, or fail.
- Existing graph state decision/tool-call contracts are reused. `PlannerDecisionRecord` now also supports `selected_tool_calls` so `execute_parallel_read_batch` can be represented without adding a second tool-call stack.
- Locked constraints are validated against proposed requirement-ledger revisions before `revise_requirements` decisions can pass.
- `choose_tool`, `execute_tool`, `execute_parallel_read_batch`, and `request_approval` decisions require selected API/RAG tool calls from hydrated candidate windows.
- `finalize` decisions are rejected unless existing v2 final validation passes from typed evidence and terminal requirement proof.
- Deterministic guard decisions are accepted only when state already proves the transition, such as a prior persisted planner `choose_tool` decision for an `execute_tool` guard.
- Tests cover invalid locked-constraint changes, choosing a non-candidate tool, executing without a selected tool/RAG action, finalizing without required evidence, a valid `retrieve_tools` decision, deterministic guard rejection/acceptance, and serialization/deserialization of planner decision submissions.
- Normal runtime was not switched, no LangGraph nodes were added, no tools/RAG were executed, no product behavior changed, and no ToolSelector/RAG/approval/response-document stack was added.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase2_decisions.py -q` reported `12 passed, 3 warnings`.
- Tests run: `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q` reported `50 passed, 37 warnings`.
- No pytest command in this phase used `*`, so no PowerShell wildcard expansion was required.
- `git diff --check`: passed.
- Blockers: none.

Next phase recommendation:

- Proceed to Phase 3: add the LangGraph shell and node transitions behind an explicit test/debug entry point, using the Phase 2 decision gate as the authorization boundary before any retrieval, execution, approval, finalization, or failure transition.

### Phase 3: LangGraph Shell

Status: complete.

Planned files:

- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase3_shell.py`

Completion evidence to record:

- graph node transition proof,
- fake tracer or local trace proof,
- confirmation old graph state is not execution authority,
- confirmation the graph accepts an injected/configured LangGraph checkpointer and does not create a bespoke checkpoint store.

Completion evidence:

- Files changed: `factory-agent/factory_agent/graph/v2_agent_graph.py`, `factory-agent/tests/test_planner_owned_agent_graph_phase3_shell.py`, and this tracker.
- Added `PlannerOwnedAgentGraph` with the Phase 3 LangGraph shell nodes: `semantic_intake_node`, `requirement_ledger_node`, `planner_decision_node`, `tool_retrieval_node`, `planner_choose_tool_node`, `tool_execution_node`, `evidence_observation_node`, `satisfaction_node`, `approval_node`, `finalize_node`, and `response_document_node`.
- The graph uses `PlannerOwnedAgentGraphState` as the LangGraph state schema and records node order in `execution_trace.diagnostics["phase3_node_order"]`.
- Added local Phase 3 adapters and `LocalPlannerOwnedGraphTracer` for shell proof only. The adapters create bounded local candidate windows, planner-selected tool calls, fake execution observations, typed evidence, deterministic satisfaction, and response-document context without calling product APIs, RAG, approval persistence, or the response renderer.
- Phase 2 decision validation gates retrieval, tool choice, deterministic guarded execution, deterministic finalize, and fail transitions through `record_planner_decision()`/`validate_planner_decision()`.
- The graph compiles through the existing checkpoint seam with `build_graph_checkpointer(settings)` and also accepts injected checkpointers such as LangGraph `MemorySaver`. No bespoke checkpoint store was added.
- Tests prove a simple read query flows through nodes in order, planner decisions are written into state, old graph fields are ignored as execution authority, injected/configured checkpointers are accepted, direct service execution is not called, and `session.replan_context` is not used as authoritative resume state.
- Normal runtime was not switched, normal plan creation does not call this graph, direct-v2 helpers were not removed, no real API/RAG tools were executed, and no product-visible behavior changed.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase3_shell.py -q` reported `6 passed, 3 warnings`.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase2_decisions.py tests/test_planner_owned_agent_graph_phase3_shell.py -q` reported `18 passed, 3 warnings`.
- Tests run: `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` reported `5 passed, 3 warnings`.
- No pytest command in this phase used `*`, so no PowerShell wildcard expansion was required.
- `git diff --check`: passed.
- Blockers: none.

### Phase 4: Retrieval And Tool Choice

Status: not started.

Planned files:

- `factory-agent/factory_agent/planning/v2_graph_adapters.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase4_retrieval.py`

Completion evidence to record:

- candidate window max and hydration behavior,
- planner choice limited to hydrated candidates,
- confirmation `ToolSelector` is reused through the existing adapter.

### Phase 5: Tool/RAG Execution And Evidence Observation

Status: not started.

Planned files:

- `factory-agent/factory_agent/planning/v2_graph_adapters.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase5_execution_observation.py`

Completion evidence to record:

- tool execution authorization proof,
- typed evidence proof,
- failed execution does not satisfy requirements,
- RAG action creates graph evidence.

### Phase 6: Read-Only Product Flows

Status: not started.

Planned files:

- `factory-agent/tests/test_planner_owned_agent_graph_phase6_read_flows.py`
- response-document tests as needed,
- frontend E2E tests as needed.

Required behavior proof:

- Mixed machine/job/list query summary represents all fulfilled requirements.
- Empty low-priority result says no low-priority records were found.
- No duplicate or stale preview/results blocks.

Completion evidence to record:

- backend test counts,
- frontend E2E counts,
- screenshots only if the UI changed.

### Phase 7: RAG As A Graph Tool

Status: not started.

Planned files:

- `factory-agent/tests/test_planner_owned_agent_graph_phase7_rag.py`
- graph/RAG adapter files as needed.

Completion evidence to record:

- citation-backed answer proof,
- insufficient-context proof,
- no `legacy_rag_route` runtime authority,
- no source-ID runtime branches.

### Phase 8: Writes, Approval Pause, And Resume

Status: not started.

Planned files:

- `factory-agent/tests/test_planner_owned_agent_graph_phase8_approval_resume.py`
- approval/graph adapter files as needed,
- frontend approval E2E tests as needed.

Required behavior proof:

- Approval 1 UI describes approval 1.
- Approval 2 UI describes approval 2.
- No-record first operation does not show stale/future approval details.
- Commit happens only after approval.
- Resume uses the native LangGraph checkpoint; `session.replan_context` is pointer/UI metadata only.

Completion evidence to record:

- backend approval counts,
- frontend approval E2E counts,
- stale approval rejection proof.

### Phase 9: Interruptions, Revisions, And Stale Work

Status: not started.

Planned files:

- `factory-agent/tests/test_planner_owned_agent_graph_phase9_interrupts.py`
- interrupt/graph adapter files as needed.

Completion evidence to record:

- revision history proof,
- superseded evidence proof,
- stale background result ignored,
- stale approval rejected,
- stale-work checks tied to graph revision/checkpoint identity.

### Phase 10: Runtime Switch To Graph

Status: not started.

Planned files:

- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- runtime switch tests.

Completion evidence to record:

- normal runtime enters graph path,
- service-level direct execution no longer owns normal v2 runtime,
- runtime uses stable graph thread id and configured LangGraph checkpointer,
- resume does not rebuild authoritative state from `session.replan_context`,
- full backend count,
- frontend response-document and seeded-oracle counts.

### Phase 11: Test Cleanup And Legacy Quarantine

Status: not started.

Planned files:

- direct-v2 and old graph tests as classified,
- cleanup/static guard tests.

Completion evidence to record:

- deleted/rewritten tests and replacement coverage,
- static guard proving no old execution authority,
- full backend count with no new xfail/skips.

### Phase 12: Release Proof

Status: not started.

Completion evidence to record:

- focused graph-owned suite count,
- full backend count,
- frontend unit count,
- response-document Playwright count,
- seeded-oracle Playwright count,
- real-LangGraph or release Playwright count,
- trace proof summary,
- final commit hash.

## Update Rules

Every phase update must include:

- files changed,
- tests run,
- exact pass/fail/skip/xfail counts,
- whether `git diff --check` passed,
- any blocker and owner,
- whether the commit was created,
- commit hash when committed.

Do not mark a phase complete if:

- normal runtime behavior was changed outside the phase scope,
- tests were weakened without replacement coverage,
- exact-prompt or seeded-ID runtime branches were added,
- direct service-level execution is presented as graph-owned execution,
- legacy RAG or old graph cursor/scaffold authority was restored.

## Current Handoff Prompt

```text
You are implementing Phase 3 of docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md.

Read first:
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md
- docs/qa/PLANNER_OWNED_AGENT_LOOP_MIGRATION.md
- docs/qa/PLANNER_OWNED_AGENT_LOOP_MIGRATION_TRACK.md
- factory-agent/factory_agent/planning/v2_agent_state.py
- factory-agent/factory_agent/planning/v2_contracts.py
- factory-agent/factory_agent/planning/v2_planner_decisions.py

Scope:
- Implement only Phase 3: LangGraph Shell.
- Do not switch runtime.
- Do not execute the new graph from normal plan creation.
- Do not remove direct-v2 helpers.
- Update only the graph migration tracker after implementation.

Implementation requirements:
- Add the new graph shell and node transitions behind an explicit test/debug entry point.
- Use `PlannerOwnedAgentGraphState` as graph state.
- Require a planner decision or deterministic guard decision before retrieval, tool choice, execution, approval, finalization, or failure transitions.
- Compile with the existing LangGraph checkpointer seam and support injected/configured checkpointers.
- Assert local/fake trace shape without requiring live LangSmith.

Maintainability and hardcode rules:
- No exact-prompt runtime branches.
- No seeded-ID runtime branches such as M-CNC-01, JOB-SEED-*, hard query IDs, or source IDs.
- No new retriever, RAG, approval, or response-document stack.
- Keep requirement, capability need, tool call, evidence, and response document separate.
- Use the existing LangGraph checkpointer seam for checkpoint/resume work in later phases. Do not make `session.replan_context` authoritative graph state.
- If a bug reveals architecture leakage, use the improve-codebase-architecture skill before patching.

Verification:
- cd factory-agent
- python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase2_decisions.py tests/test_planner_owned_agent_graph_phase3_shell.py -q
- python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
- If a planned pytest command uses `*`, expand it in PowerShell before running and record the expanded command/count.
- git diff --check

Commit only if the required gate passes. Suggested commit message:
feat: add planner-owned agent graph shell

Final response format:
Use exactly these sections:
- Phase Result
- Files Changed
- Tracker Update
- Verification
- Guardrail Checklist
- Open Issues
- Next Step

If any field is not verified, say `not verified` and explain why.
```
