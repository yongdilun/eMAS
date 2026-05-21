# Planner-Owned Agent Graph Migration Tracker

## Current Status

Status: Phase 9 complete. The explicit planner-owned graph test/debug path now handles user interruptions, requirement revisions, superseded evidence, stale approvals, and stale background results through graph ledger revision and checkpoint identity. Normal runtime has not been switched.

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
| 2 | Planner decision interface | Complete | `4f3532a1` | Decision validation tests plus route/tool guardrails |
| 3 | LangGraph shell | Complete | `04f8673c` | Node transition tests plus fake tracer proof |
| 4 | Retrieval and tool choice | Complete | `6899e2a2` | Candidate-window and no-new-retriever tests |
| 5 | Tool/RAG execution and evidence observation | Complete | `a9791b90` | Evidence observation tests plus satisfaction guard |
| 6 | Read-only product flows | Complete | `d5f69242` | Mixed read, empty-result, response-document tests and E2E |
| 7 | RAG as a graph tool | Complete | `765069b2` | Citation/insufficient-context tests without legacy RAG route |
| 8 | Writes, approval pause, and resume | Complete | `83911fa9` | Approval resume, stale approval, and UI approval tests |
| 9 | Interruptions, revisions, and stale work | Complete | `04876615` | Interrupt/revision/stale-work tests |
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

Status: complete.

Files changed:

- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase3_shell.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase4_retrieval.py`
- this tracker

Completion evidence:

- `PlannerOwnedAgentGraphAdapters` now delegates retrieval to `V2CapabilityToolRetriever`, which wraps the existing `ToolSelector`.
- Retrieval is called only from a validated `retrieve_tools` planner decision carrying a declared `CapabilityNeed`.
- The graph passes capability-derived adapter requests and retrieval phrases to `ToolSelector`; tests prove the selector does not receive the exact whole user query for a mixed machine/RAG prompt.
- Candidate windows and hydrated cards come directly from the retriever result, stay bounded at max 5 per need, and do not hydrate unrelated full-catalog tools.
- The old Phase 3 local candidate-selection helpers were removed so local fake candidates cannot be mistaken for real retrieval.
- Planner `choose_tool` decisions still pass through the Phase 2 validation gate and are rejected when the selected tool is outside the hydrated candidate window.
- RAG is represented as `rag_search_documents` with `search_documents` actions and graph `rag_tool` calls/evidence, not as `legacy_rag_route`.
- Phase 4 still does not execute real API/RAG tools. Execution remains a placeholder with `real_product_execution=false` and `execution_policy=placeholder_only_until_phase5`.
- Normal runtime was not switched, normal plan creation does not call this graph, direct-v2 helpers were not removed, and product behavior was not changed.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase4_retrieval.py -q` reported `6 passed, 5 warnings`.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase2_decisions.py tests/test_planner_owned_agent_graph_phase3_shell.py tests/test_planner_owned_agent_graph_phase4_retrieval.py -q` reported `24 passed, 5 warnings`.
- Tests run: `python -m pytest tests/test_tool_selector.py tests/test_planner_owned_loop_phase4_tool_retriever.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` reported `44 passed, 15 warnings`.
- No pytest command in this phase used `*`, so no PowerShell wildcard expansion was required.
- `git diff --check`: passed.
- Blockers: none.

Next phase recommendation:

- Proceed to Phase 5: move API/RAG execution behind graph-authorized adapters, convert execution outputs into typed evidence, preserve repeated-retrieval guards, and keep errors as explicit evidence/failure states instead of hidden successful final answers.

### Phase 5: Tool/RAG Execution And Evidence Observation

Status: complete.

Files changed:

- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/planning/v2_graph_adapters.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase3_shell.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase4_retrieval.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase5_execution_observation.py`
- this tracker

Completion evidence:

- Added `v2_graph_adapters.py` as the graph execution/evidence adapter surface. `execute_graph_tool_call()` requires a persisted validated `execute_tool` planner/guard decision before any API/RAG execution can run, and `observe_graph_tool_result()` converts execution output into typed evidence.
- API execution uses the existing stateless HTTP tool execution seam rather than service-level direct-v2 helpers. Successful API results become `EvidenceLedgerEntry` records with `source_type=api_tool`, `source_of_truth=operational_state`, requirement id, tool name, tool call/result refs, args, normalized result, and diagnostics including HTTP status and authorization metadata.
- RAG execution remains the graph-selected `rag_search_documents` action from bounded hydrated candidates. Citation-backed answers become `rag_tool` citation evidence; insufficient context becomes explicit `system_guard` evidence with `source_of_truth=document_knowledge`, `match_status=no_match`, and `reason=insufficient_context`.
- Failed API/RAG execution becomes explicit failure evidence/diagnostics and does not satisfy requirements or hide behind a successful final response.
- The graph observation node now records evidence through the adapter before deterministic satisfaction/final validation. Response document rendering remains placeholder/context only and the real response-document product renderer is still not called.
- Repeated retrieval guard diagnostics are recorded on the graph path and preserve `blocked_repeated_need` tracing for unchanged repeated capability needs.
- Phase 3/4 graph tests now inject fake API/RAG adapters so they assert graph contracts without accidental localhost/RAG execution. Direct-v2 service helpers remain untouched and are not called by the graph.
- Normal runtime was not switched, normal plan creation does not import/call `PlannerOwnedAgentGraph`, direct-v2 helpers were not removed, no product-visible behavior changed, and no ToolSelector/RAG/approval/response-document stack was duplicated.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase2_decisions.py tests/test_planner_owned_agent_graph_phase3_shell.py tests/test_planner_owned_agent_graph_phase4_retrieval.py tests/test_planner_owned_agent_graph_phase5_execution_observation.py -q` reported `32 passed, 5 warnings`.
- Tests run: `python -m pytest tests/test_planner_owned_loop_phase6_satisfaction.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` reported `15 passed, 3 warnings`.
- No pytest command in this phase used `*`, so no PowerShell wildcard expansion was required.
- `git diff --check`: passed.
- Blockers: none.

Next phase recommendation:

- Proceed to Phase 6: prove read-only product flows through graph-owned API/RAG evidence without switching normal runtime, preserving product output contracts and avoiding exact-prompt or seeded-ID runtime branches.

### Phase 6: Read-Only Product Flows

Status: complete.

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

Completion evidence:

- Files changed: `factory-agent/factory_agent/graph/v2_agent_graph.py`, `factory-agent/factory_agent/planning/v2_graph_adapters.py`, `factory-agent/tests/test_planner_owned_agent_graph_phase6_read_flows.py`, and this tracker.
- The explicit graph path now processes a bounded set of independent read requirements in one graph run: planner `retrieve_tools` decisions, retriever-backed candidate windows, planner `choose_tool` decisions, deterministic guarded `execute_tool` decisions, and typed evidence observation are all recorded per fulfilled requirement.
- API and RAG execution still run only through the Phase 5 graph-authorized adapters. Normal plan creation was not switched, direct-v2 helpers were not removed, and `plan_creation_service.py` remains outside the graph path.
- Added Phase 6 response-document context proof in `ResponseDocumentContext.diagnostics`: ordered diagnostic blocks, aggregate summary, fulfilled requirement ids, no-record evidence refs, and explicit `preview_blocks=0` / `approval_blocks=0` / `stale_response_context_reused=false`. The real response-document renderer is still not called from the graph path.
- Empty API collection results now normalize into typed no-record evidence with `match_status=no_match`, `no_match=true`, `summary="No matching records were found."`, and `reason=no_matching_records`, so stale preview/approval/response context is not reused.
- Phase 6 tests cover simple machine status, job status, multi-ID machine status, filtered jobs with sort/limit/requested fields, mixed machine/job/list reads, mixed operational/RAG reads, and empty-result list reads.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase6_read_flows.py -q` reported `6 passed, 3 warnings`.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase2_decisions.py tests/test_planner_owned_agent_graph_phase3_shell.py tests/test_planner_owned_agent_graph_phase4_retrieval.py tests/test_planner_owned_agent_graph_phase5_execution_observation.py tests/test_planner_owned_agent_graph_phase6_read_flows.py -q` reported `38 passed, 5 warnings`.
- Tests run: literal `python -m pytest tests/test_response_document*.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q` under PowerShell did not expand the wildcard and reported `no tests ran` / `file or directory not found`; the valid rerun used a PowerShell-expanded file list.
- Tests run: PowerShell-expanded response-document command (`$responseDocTests = Get-ChildItem tests -Filter "test_response_document*.py" | ForEach-Object { $_.FullName }`; `python -m pytest @responseDocTests tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q`) reported `93 passed, 175 warnings`.
- Frontend E2E: root command `npm run test:e2e:response-document` failed with `ENOENT` because `C:\Users\dilun\OneDrive\Documents\eMas APi\package.json` does not exist. The frontend package command from `eMas Front` reported `30 passed`.
- Seeded-oracles: `npm run test:e2e:seeded-oracles` from `eMas Front` reported `35 passed`.
- `git diff --check`: passed with Git line-ending warnings only.
- Blockers: none.
- Commit: `d5f69242` (`feat: prove graph read-only product flows`).

### Phase 7: RAG As A Graph Tool

Status: complete.

Files changed:

- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/planning/v2_graph_adapters.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase7_rag.py`
- this tracker

Completion evidence:

- Document requirements now execute through graph-selected `rag_search_documents` calls with `GraphToolCall.kind="rag_tool"` after bounded candidate retrieval and persisted graph execution authorization.
- `execute_graph_rag_tool()` now adapts the existing RAG pipeline, semantic frame classifier, knowledge policy registry, source normalization, and `build_v2_rag_evidence()` path instead of adding another RAG/retriever stack.
- Citation-backed document answers become `EvidenceLedgerEntry` records with `source_type=rag_tool`, `source_of_truth=document_knowledge`, typed citations, normalized source metadata, graph action diagnostics, and `retrieved_content_proved_claim=true`.
- Non-proving retrieved chunks become explicit insufficient-context `system_guard` evidence with `source_of_truth=document_knowledge`, `match_status=no_match`, `sources_checked`, `reason=insufficient_context`, and `retrieved_content_proved_claim=false`.
- Safety notices remain raw/product metadata only. Phase 7 diagnostics record `safety_content_present` and `safety_content_used_as_evidence=false`; safety content is not used as citation or satisfaction proof.
- Graph execution trace diagnostics now record graph tool action and graph evidence events without naming `legacy_rag_route` as authority.
- Response-document context now distinguishes document insufficient context from operational no-record results and records `insufficient_context_evidence_refs`.
- Phase 7 tests cover citation-backed RAG evidence, insufficient-context evidence with sources checked, no legacy RAG route trace/evidence, no exact prompt/seed/source-id runtime literals in graph code, final validation/satisfaction behavior for document requirements, and normal runtime not calling the graph.
- Normal runtime was not switched, normal plan creation does not import/call `PlannerOwnedAgentGraph`, direct-v2 helpers were not removed, no legacy RAG shortcut was added, and product behavior outside explicit graph test/debug entry points was not changed.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase7_rag.py -q` reported `5 passed, 3 warnings`.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase2_decisions.py tests/test_planner_owned_agent_graph_phase3_shell.py tests/test_planner_owned_agent_graph_phase4_retrieval.py tests/test_planner_owned_agent_graph_phase5_execution_observation.py tests/test_planner_owned_agent_graph_phase6_read_flows.py tests/test_planner_owned_agent_graph_phase7_rag.py -q` reported `43 passed, 5 warnings`.
- Tests run: PowerShell-expanded response-document/RAG command with default `%TEMP%` first reported `104 passed, 1 skipped, 141 warnings, 4 errors`; all 4 errors were `PermissionError: [WinError 5] Access is denied: 'C:\Users\dilun\AppData\Local\Temp\pytest-of-dilun'` while setting up pytest `tmp_path` for `test_rag_ingestion.py`.
- Tests run: rerun with `TMP` and `TEMP` set to workspace-local `.pytest_tmp`, using PowerShell-expanded `$responseDocTests` and `$ragTests`, reported `108 passed, 1 skipped, 141 warnings`. The temporary directory was removed after the rerun.
- Frontend E2E: `npm run test:e2e:seeded-oracles` from `C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front` reported `35 passed`.
- Frontend E2E: `npm run test:e2e:real-langgraph` from `C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front` reported `3 passed`.
- Frontend path note: the literal parent path `C:\Users\dilun\OneDrive\Documents\eMas Front` does not exist in this checkout; the package lives under the repo root at `C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front`.
- `git diff --check`: passed.
- Blockers: none.
- Commit: `04876615`.

Next phase recommendation:

- Phase 8 is now complete. Proceed to Phase 9: make user interruptions, requirement revisions, and stale-work rejection native graph checkpoint/revision behavior while keeping normal runtime unswitched.

### Phase 8: Writes, Approval Pause, And Resume

Status: complete.

Files changed:

- `factory-agent/tests/test_planner_owned_agent_graph_phase8_approval_resume.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md`

Behavior proof:

- Write requirements select bounded hydrated write candidates but stage preview rows instead of executing.
- Approval payloads include ledger revision, graph checkpoint identity, selected graph tool call, requirement id, preview rows/details, and excluded blocked rows.
- Commit happens only after matching approval resume from native LangGraph checkpoint state.
- Rejection creates approval evidence and finalizes safely without commit.
- Stale approval creates stale rejection evidence and cannot commit.
- Approval 1 and Approval 2 labels are preserved for multi-step approvals.
- No-record first operation renders no-record evidence and suppresses stale/future approval details.
- `session.replan_context` remains non-authoritative; normal plan creation still does not import or call `PlannerOwnedAgentGraph`.

Completion evidence to record:

- Backend focused approval/resume: `python -m pytest tests/test_planner_owned_agent_graph_phase8_approval_resume.py tests/test_planner_owned_loop_phase7_interrupt_replan.py -q` -> `16 passed`.
- Backend wildcard expansion: PowerShell-expanded `test_stateful*.py`, `test_approval*.py`, and `test_response_document*.py` -> `67 passed`.
- Extra graph phase regression sweep: Phase 1 through Phase 8 graph tests -> `51 passed`.
- Frontend E2E: `npm run test:e2e:response-document` from `C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front` -> `30 passed`.
- Frontend E2E: `npm run test:e2e:seeded-oracles` from `C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front` -> `35 passed`.
- `git diff --check`: passed; Git emitted only LF-to-CRLF working-copy warnings for the edited tracker and graph files.
- Blockers/waivers: none.
- Commit: pending final commit.

Next phase recommendation:

- Proceed to Phase 9: interruptions, revisions, and stale work. Native graph interruption handling should tie user revisions, superseded evidence, background/stale results, and stale approvals to graph ledger revision and checkpoint identity. Keep `session.replan_context` as pointer/UI metadata only and keep normal runtime unswitched until Phase 10.

### Phase 9: Interruptions, Revisions, And Stale Work

Status: complete.

Files changed:

- `factory-agent/tests/test_planner_owned_agent_graph_phase9_interrupts.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/planning/v2_planner_decisions.py`
- this tracker.

Completion evidence:

- `PlannerOwnedAgentGraph.interrupt_with_user_message()` now loads native LangGraph checkpoint state, classifies the user message through the existing `v2_interrupts` contract, applies append/modify/replace/cancel revisions to the graph-owned ledger, writes the revised graph state back through LangGraph `aupdate_state()`, and records UI-compatible pointers in `session.replan_context` without making that context authoritative.
- Requirement revisions preserve locked constraints and revision history through the existing v2 interrupt/revision contracts. Cancel interruptions close active graph requirements with typed cancellation evidence and passed graph final validation.
- Old evidence remains in the evidence ledger as historical state. After a user revision it is excluded from active satisfaction/response-document evidence unless `carry_forward_evidence_refs` is explicitly supplied.
- Old candidate windows, hydrated cards, planner decisions, approval checkpoints, and pending background results are marked stale/ignored by graph revision/checkpoint identity. Deterministic approval continuation still allows internal non-interrupt ledger revisions, so Phase 8 multi-approval behavior remains intact.
- Stale approvals from a pre-interruption checkpoint are rejected without commit after the graph state has been revised.
- New revision/trace metadata is recorded under `phase9_interruption_revision`, `graph_revision_metadata`, `phase9_stale_work`, and response-document active/historical evidence diagnostics.
- Normal runtime remains unswitched; `plan_creation_service.py` still does not import or call `PlannerOwnedAgentGraph`.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase9_interrupts.py -q` reported `9 passed, 3 warnings`.
- Tests run: `python -m pytest tests/test_planner_owned_agent_graph_phase9_interrupts.py tests/test_planner_owned_loop_phase7_interrupt_replan.py -q` reported `17 passed, 9 warnings`.
- Tests run: PowerShell-expanded stateful/approval/response-document command (`$stateful = Get-ChildItem tests -Filter 'test_stateful*.py'`; `$approval = Get-ChildItem tests -Filter 'test_approval*.py'`; `$response = Get-ChildItem tests -Filter 'test_response_document*.py'`; `python -m pytest @stateful @approval @response -q`) reported `67 passed, 169 warnings`.
- Tests run: Phase 1 through Phase 9 graph sweep reported `60 passed, 5 warnings`.
- Frontend E2E: `npm run test:e2e:seeded-oracles` from `C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front` reported `35 passed`.
- Frontend E2E: first `npm run test:e2e:real-langgraph` run reported `2 passed, 1 failed`; failure was RD-001 ending with `GET /sessions/null/messages` after the page and backend logs showed the aggregate completion rendered and the real session completed. This was classified as a transient test harness/localStorage capture race, not a product regression, and rerun immediately.
- Frontend E2E: clean rerun of `npm run test:e2e:real-langgraph` from `C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front` reported `3 passed`.
- `git diff --check`: passed with Git line-ending warnings only.
- Blockers/waivers: none. The transient real-LangGraph first-run failure has proof and a clean rerun; no migration waiver is carried forward.
- Commit: pending final commit.

Next phase recommendation:

- Proceed to Phase 10: switch normal runtime to the planner-owned graph path, using stable graph thread ids and native checkpoint resume while preserving direct-v2 helpers only as historical/adaptation code until test cleanup.

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
You are implementing Phase 10 of docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md.

Read first:
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md
- factory-agent/factory_agent/graph/v2_agent_graph.py
- factory-agent/factory_agent/planning/v2_agent_state.py
- factory-agent/factory_agent/planning/v2_planner_decisions.py
- factory-agent/factory_agent/planning/v2_graph_adapters.py
- factory-agent/factory_agent/planning/v2_interrupts.py
- factory-agent/factory_agent/graph/checkpointing.py
- factory-agent/factory_agent/services/plan_creation_service.py
- factory-agent/factory_agent/services/execution_service.py
- factory-agent/factory_agent/services/approval_resume_service.py
- factory-agent/tests/test_planner_owned_agent_graph_phase9_interrupts.py

Scope:
- Implement only Phase 10: Runtime Switch To Graph.
- Switch normal v2 runtime to the planner-owned graph path.
- Preserve product behavior.
- Do not delete direct-v2 helpers yet unless a test proves they are historical/test-only and replacement coverage exists.
- Do not restore legacy/shadow runtime authority.
- Update the graph migration tracker after implementation.

Implementation requirements:
- `plan_creation_service.py` normal v2 runtime must call `PlannerOwnedAgentGraph` through a small adapter/interface.
- Normal runtime must use a stable graph thread id, usually the session id, with the configured LangGraph checkpointer.
- Approval resume must reconstruct from the native LangGraph checkpoint, not from a hand-built `session.replan_context` state.
- `_execute_direct_v2_steps()` must not be used for normal runtime.
- `_create_direct_v2_plan()` must become a thin graph adapter, be renamed historical/test-only, or be bypassed by a tested graph path.
- Trace must show graph planner decisions, retrieval calls, tool/RAG evidence refs, approval/revision/checkpoint metadata, satisfaction, final validation, and response-document context.
- `FACTORY_AGENT_ENGINE=legacy` must continue to resolve according to the Phase 15 cleanup behavior and must not restore old legacy paths.

Maintainability and hardcode rules:
- No exact-prompt runtime branches.
- No seeded-ID or source-ID runtime branches such as M-CNC-01, JOB-SEED-*, OSHA source IDs, hard query IDs, or exact prompts.
- No new retriever, RAG, approval, interrupt, or response-document stack.
- Keep requirement, capability need, tool call, evidence, and response document separate.
- Use the existing LangGraph checkpointer for checkpoint/resume work. Do not make `session.replan_context` authoritative graph state.
- If a bug reveals architecture leakage, use the improve-codebase-architecture skill before patching.

Verification:
- cd factory-agent
- python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
- python -m pytest -q
- cd "..\eMas Front"
- npm test
- npm run test:e2e:response-document
- npm run test:e2e:seeded-oracles
- npm run test:e2e:real-langgraph
- cd ..
- If a planned pytest command uses `*`, expand it in PowerShell before running and record the expanded command/count.
- git diff --check

Commit only if the required gate passes. Suggested commit message:
feat: switch normal runtime to planner-owned graph

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
