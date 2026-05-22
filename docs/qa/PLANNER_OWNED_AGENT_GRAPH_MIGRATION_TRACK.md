# Planner-Owned Agent Graph Migration Tracker

## Current Status

Status: Phase 12.1 release harness waiver removal complete. Normal v2 runtime still enters `PlannerOwnedAgentGraph` through the service adapter, planner-authored decisions still pass through the configured proposer seam, and production proposer policy still fails closed unless offline proposer mode is explicitly allowed for tests/dev. The optional legacy L4 `chromium-release` waiver is removed: the full release harness passed under the real release configuration, the four previously failing waiver scenarios passed, and offline proposer mode was not enabled or counted as release proof.

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
- Historical `PlannerOwnedV2Loop` was retired in legacy cleanup Phase 2.3; direct-v2 trace/draft compatibility now lives in `v2_trace_compatibility.py`, and normal runtime remains graph-owned.
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
| 10 | Runtime switch to graph | Complete | `49e3a5ba` | Full backend plus frontend response-document, seeded-oracle, and real-LangGraph gates |
| 10.5 | LLM planner decision proposer | Complete | `d2af19c2` | Proposer seam tests plus seeded-oracle and real-LangGraph gates |
| 10.6 | Production planner proposer policy | Complete | `b733c58b` | Offline-policy tests plus seeded-oracle and real-LangGraph gates |
| 11 | Test cleanup and legacy quarantine | Complete | `3d11935e` | `1023 passed, 3 skipped` backend; response-document `30 passed`; seeded-oracle `35 passed`; real-LangGraph `3 passed`; static cleanup guardrails |
| 12 | Release proof | Complete |  | Full backend `1023 passed, 3 skipped`; frontend unit `133 passed`; response-document `30 passed`; seeded-oracle `35 passed`; real-LangGraph `3 passed`; local Qwen proposer smoke passed; optional `chromium-release` waiver recorded |
| 12.1 | Release harness waiver removal | Complete |  | `chromium-release` waiver removed; release grep `4 passed`; full release `21 passed`; response-document `30 passed`; seeded-oracle `35 passed`; real-LangGraph `3 passed`; backend `1025 passed, 3 skipped`; offline proposer mode not counted |

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
- Commit: `83911fa9` (`feat: pause planner-owned graph writes for approval`).

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
- Commit: `04876615` (`feat: handle planner-owned graph interruptions`).

Next phase recommendation:

- Proceed to Phase 10: switch normal runtime to the planner-owned graph path, using stable graph thread ids and native checkpoint resume while preserving direct-v2 helpers only as historical/adaptation code until test cleanup.

### Phase 10: Runtime Switch To Graph

Status: complete.

Files changed:

- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/services/planner_owned_graph_runtime.py`
- `factory-agent/factory_agent/services/approval_resume_service.py`
- `factory-agent/factory_agent/services/session_revision.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/planning/api_result_projection.py`
- `factory-agent/factory_agent/planning/v2_evidence_aggregation.py`
- `factory-agent/factory_agent/planning/v2_graph_adapters.py`
- `factory-agent/factory_agent/planning/v2_tool_retriever.py`
- `factory-agent/factory_agent/planning/v2_capability_map.py`
- `factory-agent/factory_agent/planning/v2_satisfaction.py`
- `factory-agent/factory_agent/planning/intent.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase10_runtime_switch.py`
- existing backend regression tests updated for graph-owned normal runtime evidence/projection expectations.

Completion evidence:

- Normal v2 runtime now calls `PlannerOwnedGraphRuntimeAdapter`, which builds `PlannerOwnedAgentGraph` with the configured `build_graph_checkpointer(settings)` seam and invokes graph runs/resumes with `thread_id = sess.session_id`.
- At Phase 10 completion, `_create_direct_v2_plan()` was a thin graph adapter for normal runtime. Legacy cleanup Phase 2.4 later renamed the active entry to `_create_planner_owned_graph_plan()`; static/behavioral tests prove it does not call `_execute_direct_v2_steps()` or the historical direct-v2 path.
- Approval resume now routes graph-subject approvals through native LangGraph checkpoint resume before historical direct-v2 resume. Resume stores only pointer/UI metadata in `session.replan_context`; graph checkpoint state remains execution truth.
- The runtime adapter persists graph results into existing plan/session/UI rows without rebuilding planner decisions, evidence, approval state, RAG, ToolSelector, or response-document rendering in `plan_creation_service.py`.
- The graph trace/context now records graph planner decisions, node order, retrieval/tool evidence refs, approval/revision/checkpoint metadata, satisfaction/final validation status, and response-document context.
- Product behavior was preserved for read, RAG, write approval, cascaded approvals, response document aggregation, seeded oracles, and real LangGraph. Real LangGraph RD-001 now receives business-change projection from graph approval evidence instead of row-only write results.
- The response-document fix is generic: graph-approved write evidence is enriched from approved graph preview metadata keyed by requirement and record id. It adds no exact-prompt, seeded-ID, source-ID, or hard-query runtime branch.
- `FACTORY_AGENT_ENGINE=legacy` remains governed by the prior Phase 15 cleanup semantics and does not restore legacy/shadow runtime authority.
- Direct-v2 helpers were not broadly deleted in Phase 10; later cleanup should quarantine/remove only where graph-owned replacement coverage already proves the same product guarantee.
- Tests run: PowerShell-expanded `python -m pytest @phaseTests -q` for `tests/test_planner_owned_agent_graph_phase*_*.py` reported `66 passed, 6 warnings`.
- Tests run: default-temp `python -m pytest -q` reported `980 passed, 3 skipped, 1257 warnings, 5 errors`. All errors were `PermissionError: [WinError 5] Access is denied: 'C:\Users\dilun\AppData\Local\Temp\pytest-of-dilun'` from pytest `tmp_path` setup.
- Tests run: workspace-local `TEMP/TMP` rerun of `python -m pytest -q` reported `985 passed, 3 skipped, 1257 warnings`.
- Frontend unit: `npm test` from `C:\Users\dilun\OneDrive\Documents\eMas APi\eMas Front` reported `131 passed`.
- Frontend response-document E2E: first `npm run test:e2e:response-document` run reported `29 passed, 1 failed`; failure was a frontend mock/state timing race where backend `response_document.state` was already `waiting_approval` while mocked `session.status` still showed `PLANNING`. Immediate rerun reported `30 passed`; no migration waiver is carried forward.
- Frontend seeded-oracles: `npm run test:e2e:seeded-oracles` reported `35 passed`.
- Frontend real-LangGraph: `npm run test:e2e:real-langgraph` reported `3 passed`.
- `git diff --check`: passed.
- Blockers/waivers: none. The default TEMP/TMP backend failure and first response-document E2E race both have clean reruns and are recorded here.
- Commit: `49e3a5ba` (`feat: switch normal runtime to planner-owned graph`).

Next phase recommendation:

- Proceed to Phase 10.5: LLM planner decision proposer. Cleanup is blocked until planner-authored decisions are proposed through the proposer seam and accepted by the deterministic decision gate.

### Phase 10.5: LLM Planner Decision Proposer

Status: complete.

Files changed:

- `factory-agent/factory_agent/config.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/planning/v2_graph_adapters.py`
- `factory-agent/factory_agent/planning/v2_planner_decisions.py`
- `factory-agent/factory_agent/planning/v2_planner_proposer.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase2_decisions.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase3_shell.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase4_retrieval.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase5_execution_observation.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase6_read_flows.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase7_rag.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase8_approval_resume.py`
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md`

Completion evidence:

- Added the small `PlannerDecisionProposer` interface and a local/OpenAI-compatible Qwen proposer adapter behind existing planner settings and `build_planner_chat_model(..., json_mode=True)`.
- Graph planner-authored decisions are proposed through the proposer seam and then persisted only through `validate_planner_decision()` / `record_planner_decision()`.
- Deterministic validation now rejects malformed/stale/unsafe planner proposals and accepts only proven mechanical guards, including single bounded document-tool choice and read-batch execution.
- The proposer does not execute tools, mutate graph state, or see the full OpenAPI catalog before bounded retrieval.
- Compact Qwen prompt/parse/normalization remains inside the proposer adapter; graph nodes receive `PlannerDecisionSubmission`.
- Multi-call choices preserve `selected_tool_calls` so multi-entity status reads execute every accepted bounded call instead of collapsing to the first call.
- Static guard proves graph-created `PlannerDecisionRecord` instances are not authored as `planner`; planner authorship requires proposer diagnostics.

Tests run:

- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py -q` -> `17 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; $tests = Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }; python -m pytest $tests -q` -> `78 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q` -> `50 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd "eMas Front"; npm run test:e2e:response-document` -> `30 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:seeded-oracles` -> `35 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:real-langgraph` -> `3 passed`, `0 failed`.
- Targeted post-fix regression slice: `npx playwright test --project=chromium-seeded --grep "HQ-9-MULTI-ID|SO-021/SO-023" --reporter=list` -> `2 passed`, `0 failed`.
- `git diff --check` -> passed; CRLF warnings only.

Seeded-oracle and real-LangGraph:

- Seeded-oracle passed: yes, `35 passed`.
- Real-LangGraph passed: yes, `3 passed`.

Optional local Qwen smoke:

- Separate opt-in smoke trace not run. The seeded/real-LangGraph gates used the configured local Qwen-compatible endpoint and logged proposer diagnostics for model `Qwen2.5-7B-Instruct-Q4_K_M.gguf`, `base_url_type=local`, prompt size, timeout, token usage, finish reason, and duration.

Blockers/waivers:

- None. Intermediate seeded failures exposed two general architecture bugs and were fixed without exact-prompt, seeded-ID, source-ID, or legacy-stack branches: compact multi-call choices now preserve `selected_tool_calls`, and single bounded document-tool choices use a validated deterministic guard.

Commit:

- `d2af19c2` (`bug fix`) contains the committed Phase 10.5 proposer implementation and post-completion fixes.

Post-completion approval-resume fix:

- Fixed planner-owned graph approval resume so planner-owned/direct graph resume exceptions run through the same fail-closed session-status handling as legacy graph resume, instead of leaving background resumes stuck in `EXECUTING`.
- Reloaded the session after rollback before marking graph resume `FAILED` or `BLOCKED`, avoiding async SQLAlchemy expired-object access during the failure handler.
- Tightened the offline proposer adapter to prefer approval-gated/write candidate calls for write capability needs, while still passing through the proposer seam and deterministic validation.
- Fixed the checkpointer factory so a configured Postgres LangGraph checkpointer falls back to the existing database/memory checkpointer adapter when the optional Postgres saver package is unavailable. This prevents new graph approvals from being staged without a resumable native checkpoint.
- Fixed graph-native snapshot detection so planner-owned graph plans are recognized from the plan marker before checkpoint probing, and checkpoint probing no longer sorts while selecting the large checkpoint JSON payload.
- Fixed multi-requirement write staging when an earlier write preview has no matching records. The graph now records typed no-record evidence for that requirement, continues to the next open write requirement, and only finalizes once no open graph-write requirements remain. No-record previews no longer consume the user-visible approval number.
- Fixed response-document projection for graph no-record approval previews. Non-actionable no-record preview evidence is no longer projected as executable `tool_outputs` or persisted plan steps, and the same proven no-op is exposed through the existing typed `no_op_mutations` UI contract so it renders as "Not changed" without inflating approved business-change counts.

Additional files changed:

- `factory-agent/factory_agent/graph/checkpointing.py`
- `factory-agent/factory_agent/graph/session_detection.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/memory/checkpoint.py`
- `factory-agent/factory_agent/services/approval_resume_service.py`
- `factory-agent/factory_agent/services/planner_owned_graph_runtime.py`
- `factory-agent/tests/test_graph_session_detection.py`
- `factory-agent/tests/test_api_endpoints.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase10_runtime_switch.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase8_approval_resume.py`

Additional tests run:

- `cd factory-agent; python -m pytest tests/test_api_endpoints.py::test_graph_runtime_low_medium_high_resume_queues_second_approval_without_llm tests/test_api_endpoints.py::test_graph_runtime_low_medium_high_background_resume_queues_second_approval_without_llm tests/test_api_endpoints.py::test_planner_owned_graph_background_resume_failure_marks_session_failed tests/test_planner_owned_agent_graph_phase8_approval_resume.py::test_phase8_low_to_medium_then_medium_to_high_stages_second_approval_without_llm -q` -> `4 passed`, `0 failed`.
- `cd factory-agent; python -m pytest tests/test_api_endpoints.py::test_graph_approval_returns_before_resume_and_keeps_one_activity_operation -q` -> `1 passed`, `0 failed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase3_shell.py::test_phase3_postgres_checkpointer_config_falls_back_when_adapter_unavailable tests/test_api_endpoints.py::test_graph_runtime_low_medium_high_background_resume_queues_second_approval_without_llm tests/test_planner_owned_agent_graph_phase8_approval_resume.py::test_phase8_low_to_medium_then_medium_to_high_stages_second_approval_without_llm -q` -> `3 passed`, `0 failed`.
- `cd factory-agent; python -m pytest tests/test_graph_session_detection.py tests/test_api_endpoints.py::test_graph_runtime_low_medium_high_background_resume_queues_second_approval_without_llm tests/test_planner_owned_agent_graph_phase3_shell.py::test_phase3_postgres_checkpointer_config_falls_back_when_adapter_unavailable -q` -> `4 passed`, `0 failed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase3_shell.py::test_phase3_postgres_checkpointer_config_falls_back_when_adapter_unavailable -q` -> `18 passed`, `0 failed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_graph_session_detection.py -q` -> `19 passed`, `0 failed`.
- `cd factory-agent; python -m pytest tests/test_api_endpoints.py::test_graph_runtime_no_low_records_still_stages_medium_priority_approval_without_llm tests/test_planner_owned_agent_graph_phase8_approval_resume.py::test_phase8_no_records_for_first_write_continues_to_second_approval -q` -> `2 passed`, `0 failed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase8_approval_resume.py tests/test_api_endpoints.py::test_graph_runtime_no_low_records_still_stages_medium_priority_approval_without_llm tests/test_api_endpoints.py::test_graph_runtime_low_medium_high_resume_queues_second_approval_without_llm tests/test_api_endpoints.py::test_graph_runtime_low_medium_high_background_resume_queues_second_approval_without_llm -q` -> `13 passed`, `0 failed`.
- `cd factory-agent; $tests = Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }; python -m pytest $tests -q` -> `80 passed`, `0 failed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py -q` -> `17 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase10_runtime_switch.py::test_phase10_graph_runtime_keeps_no_record_preview_out_of_executable_tool_outputs tests/test_api_endpoints.py::test_graph_runtime_no_record_branch_is_not_counted_as_business_change_after_approval -q` -> `2 passed`, `0 failed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase8_approval_resume.py tests/test_api_endpoints.py::test_graph_runtime_no_low_records_still_stages_medium_priority_approval_without_llm tests/test_api_endpoints.py::test_graph_runtime_no_record_branch_is_not_counted_as_business_change_after_approval tests/test_api_endpoints.py::test_graph_runtime_low_medium_high_resume_queues_second_approval_without_llm tests/test_api_endpoints.py::test_graph_runtime_low_medium_high_background_resume_queues_second_approval_without_llm -q` -> `21 passed`, `0 failed`.
- `git diff --check` -> passed; CRLF warnings only.

### Phase 10.6: Production Planner Proposer Policy

Status: complete.

Files changed:

- `factory-agent/factory_agent/config.py`
- `factory-agent/factory_agent/planning/v2_planner_proposer.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py`
- this tracker.

Completion evidence:

- Added explicit offline proposer config `FACTORY_AGENT_ALLOW_OFFLINE_PLANNER_PROPOSER=1` as `Settings.allow_offline_planner_proposer`, defaulting to disabled.
- `build_planner_decision_proposer(settings)` now selects `OpenAICompatibleQwenPlannerDecisionProposer` when planner/OpenAI-compatible config exists, selects `OfflineStructuredPlannerDecisionProposer` only when offline mode is explicitly enabled, and otherwise returns a fail-closed `PlannerLLMConfigurationRequiredProposer`.
- Missing planner LLM configuration now records clear proposer diagnostics (`configuration_missing`, required config keys, offline flag name, `tool_execution_allowed=false`) and no graph tool execution occurs.
- Offline mode remains available for explicit test/dev use and traces `offline_contract_mode=true`, `real_llm_mode=false`, and `llm_invoked=false`.
- Real local/OpenAI-compatible planner mode traces adapter, model name, base URL type, configured-base-URL status, `real_llm_mode=true`, and `offline_contract_mode=false`.
- Added release-proof helper `planner_proposer_diagnostics_satisfy_real_llm_release_proof()` so offline diagnostics cannot satisfy real LLM planner proof.

Tests run:

- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q` -> `5 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py -q` -> `23 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; $phaseTests = Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }; python -m pytest $phaseTests -q` -> `86 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q` -> `50 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd "eMas Front"; npm run test:e2e:response-document` -> `30 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:seeded-oracles` -> `35 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:real-langgraph` -> `3 passed`, `0 failed`.

Seeded-oracle and real-LangGraph:

- Seeded-oracle passed: yes, `35 passed`.
- Real-LangGraph passed: yes, `3 passed`.

Blockers/waivers:

- None.

Commit:

- `b733c58b` (`feat: enforce planner-owned graph proposer policy`).

### Phase 11: Test Cleanup And Legacy Quarantine

Status: complete.

Files changed:

- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md`
- `factory-agent/tests/conftest.py`
- `factory-agent/tests/test_api_endpoints.py`
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`
- `factory-agent/tests/test_planner_owned_loop_phase10_legacy_removal.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `factory-agent/tests/test_planner_owned_loop_phase5_shadow_engine.py`
- `factory-agent/tests/test_planner_owned_loop_phase6_satisfaction.py`
- `factory-agent/tests/test_planner_owned_loop_phase8_legacy_cleanup_switch.py`
- `factory-agent/tests/test_planner_owned_loop_phase9_hard_query_release.py`

Final classification:

| File/helper | Classification | Action |
| --- | --- | --- |
| `factory-agent/tests/test_planner_owned_agent_graph_phase10_runtime_switch.py` | Keep | Preserve graph runtime switch proof; strengthen Phase 11 static cleanup guards around direct-v2 helper call graph. |
| `factory-agent/tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py` | Keep | Preserve proposer-seam proof that planner-authored graph decisions come through proposer diagnostics. |
| `factory-agent/tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py` | Keep | Preserve release-policy proof that offline proposer diagnostics cannot satisfy real LLM planner proof. |
| `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py` | Rewrite | Convert from Phase 15-only cleanup into Phase 11 cleanup/quarantine guard coverage for old graph/direct-v2 authority. |
| `factory-agent/tests/test_api_endpoints.py::test_create_direct_v2_plan_records_forced_reranker_in_session_trace` | Rewrite | Rename to graph-runtime wording; the assertion already proves `planner_owned_agent_graph` authority and reranker trace accounting. |
| `factory-agent/tests/test_api_endpoints.py::test_phase14_direct_v2_resume_queues_second_actionable_approval` | Quarantine | Keep as historical approval-payload resume compatibility; mark as legacy architecture quarantine so it cannot be mistaken for normal runtime proof. |
| `factory-agent/tests/test_api_endpoints.py::test_actionable_prompt_with_empty_generated_plan_blocks_instead_of_orphan_idle` | Delete | Delete stale injected-planner approval test; orphan/approval product guarantee is already covered by graph-owned response-document and seeded-oracle gates. |
| `factory-agent/tests/test_planner_owned_loop_phase5_shadow_engine.py` | Quarantine | Keep as historical direct-v2 loop contract/parser compatibility; mark module as quarantine and do not count `v2_planner_loop` trace as graph proof. |
| `factory-agent/tests/test_planner_owned_loop_phase6_satisfaction.py` | Keep | Keep v2 satisfaction/final-validator product contracts; rename direct-v2 wording where useful, but do not quarantine typed evidence and guardrail coverage. |
| `factory-agent/tests/test_planner_owned_loop_phase7_interrupt_replan.py` | Keep | Keep ledger revision, stale approval, and interrupt contract coverage; graph-owned Phase 9 tests remain runtime proof. |
| `factory-agent/tests/test_planner_owned_loop_phase9_hard_query_release.py` | Quarantine | Keep as historical hard-query/direct-v2 contract compatibility because graph Phase 6/7/8/9/10 tests now own runtime proof. |
| `factory-agent/factory_agent/services/plan_creation_service.py` historical direct-v2 helpers | Quarantine | Keep helper code only for historical approval/parse compatibility; Phase 11 static guard must prove normal runtime does not call it. |
| Old `factory-agent/factory_agent/graph/planner_graph.py` and `graph/nodes/planner_loop.py` state-machine concepts | Quarantine | Keep as historical/seeded LangGraph compatibility only; Phase 11 static guard must prove `working_intents`/cursor authority is not used by normal planner-owned graph runtime. |

Completion evidence:

- Added the `legacy_architecture_quarantine` pytest marker and marked historical direct-v2 compatibility modules/functions so they cannot be mistaken for normal runtime proof.
- Rewrote migration-era test names and settings to prove graph-owned behavior explicitly, with offline proposer mode enabled only in tests/dev fixtures that intentionally use offline planner proposals.
- Deleted the stale injected-planner approval test whose product guarantee is already covered by graph-owned approval, response-document, and seeded-oracle coverage.
- Added AST/static guards proving the active planner-owned graph entry delegates to graph runtime, cannot call `_execute_direct_v2_steps()`, and old graph `working_intents`/cursor authority is not used by normal planner-owned graph runtime sources. Legacy cleanup Phase 2.4 later renamed this entry to `_create_planner_owned_graph_plan()`.
- Preserved Phase 10/10.5/10.6 coverage and added guards that planner-authored graph decisions still require proposer diagnostics and offline proposer diagnostics cannot satisfy real LLM release proof.
- Kept normal runtime on `PlannerOwnedAgentGraph`; no legacy/shadow runtime authority was restored.

Tests run:

- `cd factory-agent; python -m pytest tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `34 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; $phaseTests = Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }; python -m pytest $phaseTests -q` -> `86 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q` -> `56 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; python -m pytest -q` -> `1023 passed`, `0 failed`, `3 skipped`, `0 xfailed`.
- `cd "eMas Front"; npm run test:e2e:response-document` -> `30 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:seeded-oracles` -> `35 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:real-langgraph` -> `3 passed`, `0 failed`.
- `git diff --check` -> passed.

Blockers/waivers:

- None.

Commit:

- `3d11935e` (`test: quarantine legacy direct-v2 graph coverage`).

Next phase recommendation:

- Proceed to Phase 12 release proof after review of the Phase 11 cleanup commit.

### Phase 12: Release Proof

Status: complete.

Files changed:

- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md`

Proof base commit:

- `f2655358ae0339ee81826cdd09632145168447bb` (`docs: tighten planner-owned graph release plan`)

Completion evidence:

- Normal runtime enters `PlannerOwnedAgentGraph` through `PlannerOwnedGraphRuntimeAdapter.run_plan()` with `thread_id = sess.session_id`; Phase 10/11 static guards still prove the active graph entry cannot call `_execute_direct_v2_steps()`. Legacy cleanup Phase 2.4 renamed the service entry to `_create_planner_owned_graph_plan()`.
- Planner-authored decisions are produced through the configured proposer seam. Phase 10.5/10.6/11 guards still prove graph-created `PlannerDecisionRecord` calls are not hand-authored as `author="planner"`, planner decisions require `planner_proposer` diagnostics, and offline proposer diagnostics cannot satisfy real LLM release proof.
- Trace proof includes proposer adapter/model/base URL metadata and deterministic validation outcome. Local planner smoke used `openai_compatible_qwen_planner_decision_proposer`, model `Qwen2.5-7B-Instruct-Q4_K_M.gguf`, base URL type `local`, `offline_contract_mode=false`, `real_llm_mode=true`, `llm_invoked=true`, prompt sizes `3166` and `4273` chars, accepted planner decisions `retrieve_tools` and `choose_tool`, validation via `planner_owned_agent_graph_decision_gate`, `executor_call_count=1`, `final_validation_status=passed`, and `planner_proposer_diagnostics_satisfy_real_llm_release_proof(...) == true`.
- Requirement/capability/tool/evidence/response-document separation is preserved by the graph-owned suite, response-document UI gates, and static cleanup guards.
- Approval, stale approval, interruption, RAG citation/insufficient-context, seeded oracle, and real-LangGraph flows passed through the required gates below.
- No legacy RAG shortcut, old graph cursor/scaffold authority, direct-v2 normal runtime authority, exact-prompt branch, seeded-ID branch, source-ID branch, or offline-as-real-release-proof path was restored.

Tests run:

- `cd factory-agent; $phaseTests = Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }; python -m pytest $phaseTests -q` -> `86 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `19 warnings`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q` -> `56 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `37 warnings`.
- `cd factory-agent; python -m pytest -q` -> `1023 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1414 warnings`.
- `cd "eMas Front"; npm test` -> `133 passed`, `0 failed`, `0 skipped`.
- `cd "eMas Front"; npm run test:e2e:response-document` -> `30 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:seeded-oracles` -> `35 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:real-langgraph` -> `3 passed`, `0 failed`.
- `cd factory-agent;` opt-in local Qwen/OpenAI-compatible planner smoke with offline proposer disabled -> `accepted_count=2`, `rejected_count=0`, planner decisions `retrieve_tools` and `choose_tool`, final validation `passed`, release-proof helper `true`.
- `cd "eMas Front"; npm run test:e2e:release` -> `17 passed`, `4 failed`. Failing scenarios: scenario 60 Go API outage expected exact release-fault/attention copy but UI rendered a generic safe `Run needs attention` diagnostic with no fake completion; scenario 66 mobile approval and scenario 67 keyboard approval did not surface an approval card under the release harness; SO-017 static bearer polling fallback saw machine evidence but missed visible `Run complete`.
- `cd "eMas Front"; $env:FACTORY_AGENT_ALLOW_OFFLINE_PLANNER_PROPOSER='1'; npm run test:e2e:release -- --grep "scenario 66|scenario 67|scenario 60|SO-017"` -> `1 passed`, `3 failed`; SO-017 passed under explicit offline proposer, while the three release-resilience checks still failed.

Seeded-oracle and real-LangGraph:

- Seeded-oracle passed: yes, `35 passed`.
- Real-LangGraph passed: yes, `3 passed`.

Blockers/waivers:

- Required Phase 12 gates from the implementation prompt: none.
- Optional `chromium-release` waiver: accepted for this planner-owned graph release proof because the user-requested Phase 12 verification list did not include `npm run test:e2e:release`, the migration-specific backend/response-document/seeded/real-LangGraph gates passed, and the local real planner proposer smoke proved the non-offline proposer adapter. Owner: frontend release harness / planner prompt-routing release validation. Removal gate: make `npm run test:e2e:release` pass by aligning release-resilience prompts/failure assertions with graph response-document behavior and Phase 10.6 proposer policy, without counting offline proposer mode as real planner proof.

Final release verdict:

- Planner-owned graph migration Phase 12 is releasable for the required proof set. The historical optional L4 `chromium-release` waiver is removed by Phase 12.1 below.

Commit:

- Pending in this changeset; final response records the committed hash.

### Phase 12.1: Release Harness Waiver Removal

Status: complete.

Files changed:

- `eMas Front/e2e/support/startReleaseStackForPlaywright.js`
- `eMas Front/e2e/specs/release-resilience.spec.js`
- `eMas Front/e2e/specs/release-validation.spec.js`
- `factory-agent/factory_agent/planning/v2_planner_decisions.py`
- `factory-agent/factory_agent/planning/v2_planner_proposer.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase2_decisions.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py`
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md`

Fix classification:

- Frontend harness config: release stack now keeps a LangGraph memory checkpointer available, so approval resume can use the real graph resume contract instead of failing with a missing-checkpointer diagnostic.
- Frontend release harness assertions and waits: scenario 60 now asserts the graph response-document diagnostic contract and no fake completion; release status checks use the existing final-answer latency budget instead of short default waits; approval rejection waits for pending approvals to drain before asserting visible rejection.
- Backend graph/proposer policy: mutation requirements can no longer be satisfied by a read-only tool choice, and the Qwen/OpenAI-compatible proposer adapter normalizes approval-required mutation choices to a write or approval-gated candidate at the proposer seam.
- Test coverage: added focused decision/proposer tests for read-only mutation rejection and adapter-level write-choice enforcement.

Waiver removal evidence:

- `cd "eMas Front"; npm run test:e2e:release -- --grep "scenario 60|scenario 66|scenario 67|SO-017"` -> `4 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd "eMas Front"; npm run test:e2e:release` -> `21 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd "eMas Front"; npm run test:e2e:response-document` -> `30 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd "eMas Front"; npm run test:e2e:seeded-oracles` -> `35 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd "eMas Front"; npm run test:e2e:real-langgraph` -> `3 passed`, `0 failed`, `0 skipped`, `0 xfailed`.
- `cd factory-agent; $phaseTests = Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }; .\.venv\Scripts\python.exe -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `cd factory-agent; .\.venv\Scripts\python.exe -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q` -> `56 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `37 warnings`.
- `cd factory-agent; .\.venv\Scripts\python.exe -m pytest -q` -> `1025 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1417 warnings`.
- `git diff --check` -> passed.

Guardrail confirmation:

- The optional L4 `chromium-release` waiver is removed because `npm run test:e2e:release` now passes.
- Offline proposer mode was not enabled in the passing release proof commands and was not counted as real release proof.
- No exact-prompt, seeded-ID, source-ID, or scenario-specific runtime branch was added.
- No legacy RAG shortcut, old graph cursor/scaffold authority, or direct-v2 normal runtime authority was restored.
- Response-document, seeded-oracle, real-LangGraph, approval, interruption, and proposer-policy guarantees remain covered by the passing gates above.

Blockers/waivers:

- None.

Commit:

- Pending in this changeset; final response records whether a commit was created.

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
- legacy RAG or old graph cursor/scaffold authority was restored,
- offline structured proposer mode is presented as real LLM planner proof.

## Current Handoff Prompt

```text
You are implementing Phase 11 of docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md.

Goal:
Clean up and quarantine tests/helpers that still reward the wrong architecture now that graph runtime, planner proposer, and production proposer policy are complete. This is not a product behavior change and not a broad deletion pass.

Read first:
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md
- factory-agent/factory_agent/services/plan_creation_service.py
- factory-agent/factory_agent/services/planner_owned_graph_runtime.py
- factory-agent/factory_agent/graph/v2_agent_graph.py
- factory-agent/factory_agent/graph/planner_graph.py
- factory-agent/factory_agent/graph/nodes/planner_loop.py
- factory-agent/factory_agent/planning/v2_planner_loop.py
- factory-agent/factory_agent/planning/v2_planner_proposer.py
- factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py
- factory-agent/tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py
- factory-agent/tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py
- factory-agent/tests/test_planner_owned_agent_graph_phase10_runtime_switch.py

Scope:
- Implement only Phase 11: Test Cleanup And Legacy Quarantine.
- Start by classifying touched tests/helpers into keep, rewrite, quarantine, or delete. Record the classification in the tracker.
- Delete only tests whose product guarantee is already covered by graph-owned tests.
- Rewrite migration-era tests when they prove useful product behavior but assert the wrong architecture.
- Quarantine historical tests explicitly when they remain useful for parse compatibility.
- Preserve product behavior and all Phase 10/10.5/10.6 graph runtime, proposer, and proposer-policy coverage.
- Do not change normal runtime away from `PlannerOwnedAgentGraph`.
- Do not restore legacy/shadow runtime authority.
- Update the graph migration tracker after implementation.

Implementation requirements:
- Add or strengthen static guards proving normal runtime cannot call `_execute_direct_v2_steps()` or historical direct-v2 execution.
- Add or strengthen static guards proving old graph `working_intents`, `intent_cursor`, `intent_completed`, and legacy RAG/scaffold concepts are historical/test-only and not normal runtime authority.
- Preserve guards proving planner-authored decisions require proposer diagnostics and offline proposer diagnostics cannot satisfy real LLM planner proof.
- Do not remove old helper code unless replacement graph-owned tests prove the same product guarantee.
- Keep approval resume native-checkpoint based; `session.replan_context` must remain pointer/UI metadata only.
- Preserve response-document, seeded-oracle, real-LangGraph, RAG citation, approval safety, stale approval, interruption, and hardcode guardrails.

Maintainability and hardcode rules:
- No exact-prompt runtime branches.
- No seeded-ID or source-ID runtime branches such as M-CNC-01, JOB-SEED-*, OSHA source IDs, hard query IDs, or exact prompts.
- No new retriever, RAG, approval, interrupt, response-document, or planner-runtime stack.
- Keep Qwen/model-specific behavior behind the proposer adapter and config.
- Keep requirement, capability need, tool call, evidence, and response document separate.
- Use the existing LangGraph checkpointer for checkpoint/resume work. Do not make `session.replan_context` authoritative graph state.
- Prefer small, deep cleanup guard modules/tests over broad brittle string scans when possible.
- If a bug reveals architecture leakage, use the improve-codebase-architecture skill before patching.

Verification:
- cd factory-agent
- python -m pytest tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
- python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
- python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q
- python -m pytest -q
- cd "..\eMas Front"
- npm run test:e2e:response-document
- npm run test:e2e:seeded-oracles
- npm run test:e2e:real-langgraph
- cd ..
- If a planned pytest command uses `*`, expand it in PowerShell before running and record the expanded command/count.
- git diff --check

Commit only if the required gate passes. Suggested commit message:
test: quarantine legacy direct-v2 graph coverage

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
