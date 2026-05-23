# Planner-Owned Graph Runtime Refactor Tracker

Status: Phase 6 graph file slimming and public interface freeze complete pending commit. This is a separate active-runtime maintainability lane for `PlannerOwnedAgentGraph`, not legacy cleanup. Runtime behavior, tests, product behavior, planner proposer policy, ToolSelector/RAG/approval/response-document/checkpoint stack, and `session.replan_context` authority remain unchanged.

Plan:

```text
docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_PLAN.md
```

Baseline commit at tracker creation:

```text
068594b16ba87e904f33680f695f03582f1257b0
```

## Progress Table

| Phase | Name | Status | Commit | Required Gate |
| --- | --- | --- | --- | --- |
| 0 | Runtime responsibility audit | Complete | `9026e3cb` | Docs/tracker only, diff check |
| 1 | Checkpoint and state utility extraction | Complete | `14f24635` | Graph run/resume/interrupt tests plus full backend |
| 2 | Approval preview and staged write module | Complete | `5a631f8d` | Approval/API tests plus full backend |
| 3 | Interrupt and revision policy module | Complete | `37ebf1eb` | Interrupt/stale-work tests plus full backend |
| 4 | Tool choice and execution helper split | Complete | `3277948d` | ToolSelector plus graph read/RAG/write tests |
| 5 | Evidence and response projection split | Complete | `0eb4c7b7` | Response-document backend and E2E gates |
| 6 | Graph file slimming and interface freeze | Complete pending commit |  | Full backend and frontend E2E release gates |
| 7 | Final runtime refactor release proof | Not started |  | Full backend, frontend unit, response-document, seeded, real-LangGraph, release |

## Current Baseline

At tracker creation:

- `factory-agent/factory_agent/graph/v2_agent_graph.py` is about `3596` LOC at Phase 0 audit time.
- Normal runtime enters `PlannerOwnedAgentGraph` through `PlannerOwnedGraphRuntimeAdapter`.
- Legacy cleanup is separate and must remain complete.
- No runtime code has been changed for this plan yet.

## Phase 0 Responsibility Map

Phase 0 audited `factory-agent/factory_agent/graph/v2_agent_graph.py` at about `3596` LOC. The file currently owns graph topology, runtime entrypoints, node orchestration, and several deep helper clusters. This map records current ownership before any runtime code is moved.

| Classification | Current Location | Current Owner | Existing Proof | Extraction Risk | Candidate Owner / Disposition |
| --- | --- | --- | --- | --- | --- |
| graph topology/orchestration | `v2_agent_graph.py:118-130` `PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER`; `:334-360` constructor; `:566-594` `_compile_graph`; node methods `:596-1296`; node visit helper `:1777-1786` | `PlannerOwnedAgentGraph` | `tests/test_planner_owned_graph_shell_contract.py:143`, `:161`, `:214`, `:285`; `tests/test_planner_owned_graph_runtime_adapter.py:133`, `:160` | High | Keep in `v2_agent_graph.py`; this is the graph file's core depth. |
| runtime entrypoints/run/resume/interrupt | `v2_agent_graph.py:365-400` `run` / `run_state`; `:402-464` `resume_from_approval`; `:466-564` `interrupt_with_user_message`; `:1621-1638` `_load_checkpoint_state`; service entry adapter in `services/planner_owned_graph_runtime.py:29-82`, `:155-173` | `PlannerOwnedAgentGraph` public runtime plus `PlannerOwnedGraphRuntimeAdapter` persistence adapter | `tests/test_planner_owned_graph_runtime_adapter.py:133`, `:160`, `:218`; `tests/test_planner_owned_graph_approval_resume.py:307`, `:369`; `tests/test_planner_owned_graph_interruptions.py:22`, `:238` | High | Public runtime symbols are frozen as `PlannerOwnedAgentGraph`, `PlannerOwnedAgentGraphAdapters`, `PlannerOwnedAgentGraphRunOptions`, and `PlannerOwnedGraphResult`. |
| planner decision/proposer flow | `v2_agent_graph.py:580-672`; proposer trace helpers `:1603-1685`; proposed ledger helper `:1688-1706`; state lookup helpers `:3128-3292`; existing proposer/validator modules `v2_planner_proposer.py`, `v2_planner_decisions.py` | Existing planning proposer/decision modules own proposer contract and validation; graph owns node timing and diagnostics | `tests/test_planner_owned_graph_llm_proposer.py:275`, `:297`, `:314`, `:330`, `:345`, `:741`, `:856`, `:944`; `tests/test_planner_owned_graph_proposer_policy.py:147`, `:169`, `:190`, `:222`; `tests/test_planner_owned_graph_decision_contract.py` | Medium | Possible future `graph/planner_decision_flow.py` only if it owns proposer context construction plus acceptance/rejection diagnostics; avoid pass-through wrappers over `record_planner_decision()`. |
| tool/RAG execution | Retrieval node `v2_agent_graph.py:674-743`; choose node `:745-839`; execution node `:841-974`; candidate/tool-call helpers `:1709-1731`, `:2661-2834`, `:3139-3328`; adapter methods `:166-246`; existing execution owner `planning/v2_graph_adapters.py` | `v2_tool_retriever.py`, `ToolSelector`, and `v2_graph_adapters.py` own retrieval/execution stacks; graph owns sequencing and selected-call construction | `tests/test_planner_owned_graph_retrieval_contract.py:189`, `:210`, `:298`, `:319`, `:344`, `:356`; `tests/test_planner_owned_graph_execution_observation.py:265`, `:294`, `:318`, `:358`, `:381`, `:401`, `:416`; `tests/test_route_to_execution_contract.py:194`, `:207`, `:218`, `:227`, `:258`, `:271`, `:332`; `tests/test_tool_selector.py` | Medium/High | Candidate `graph/tool_choice.py` can own card selection, tool-call construction, and deterministic single-document choice. Do not duplicate ToolSelector, retriever, RAG, or HTTP execution. |
| evidence observation | `v2_agent_graph.py:976-1084`; identity/stale helpers `:2035-2122`; no-record evidence helper `:3006-3042`; unique id helper `:3094-3101`; existing evidence adapter `planning/v2_graph_adapters.py:331-369` | Graph owns observation node and active-revision filtering; `v2_graph_adapters.py` owns conversion from execution result to typed evidence | `tests/test_planner_owned_graph_execution_observation.py:294`, `:318`, `:358`, `:381`; `tests/test_planner_owned_graph_rag_evidence.py:121`, `:171`, `:210`; `tests/test_planner_owned_graph_interruptions.py:157`, `:203` | Medium | Candidate `graph/evidence_observation.py` only if it owns active-revision observation policy, stale-result ignoring, aggregation, and graph evidence identity together. |
| satisfaction/finalization | `v2_agent_graph.py:1086-1129` `_satisfaction_node`; `:1143-1188` `_finalize_node`; active-revision filters `:2087-2122`; write-status helpers `:3045-3125`; existing satisfaction owner `planning/v2_satisfaction.py` and final-state wrapper `planning/v2_agent_state.py:219-225` | `v2_satisfaction.py` owns deterministic satisfaction and final validation rules; graph owns deferral/finalize decision recording and write follow-up gating | `tests/test_planner_owned_satisfaction.py`; `tests/test_planner_owned_graph_read_flows.py:265`, `:287`, `:309`, `:345`, `:388`; `tests/test_planner_owned_graph_approval_resume.py:307`, `:344`, `:369`; `tests/test_planner_owned_graph_execution_observation.py:381` | Medium/High | Keep node orchestration in graph. Consider only a focused finalization handoff helper after approval and interrupt extraction, because status updates span ledger, satisfaction state, evidence, and decision validation. |
| approval preview/staging/resume | `v2_agent_graph.py:1131-1141` approval node; `:1270-1581` staging and resume; preview helpers `:2211-2606`; approval matching/evidence helpers `:2837-3003`; no-record/update helpers `:3006-3091`; adapter methods `:255-293`; persistence/UI projection in `services/planner_owned_graph_runtime.py` | Graph owns approval pause/resume state machine; `approval_summary.py` owns approval payload summary; runtime adapter owns DB row and UI bundle persistence | `tests/test_planner_owned_graph_approval_resume.py:243`, `:276`, `:307`, `:344`, `:369`, `:391`, `:415`, `:500`, `:532`; `tests/test_api_endpoints.py:1382`, `:1517`, `:1625`, `:1758`, `:1905`, `:2256`, `:2417`, `:2554`, `:2881`; `tests/test_planner_owned_graph_runtime_adapter.py:287`, `:370` | High | Strong candidate for a deep `graph/approval_runtime.py`, but not first unless interface is approval preview + stage + resume evidence, not thin wrappers. Must not duplicate approval persistence or response-document service. |
| interrupt/revision/stale-work | `v2_agent_graph.py:428-526`; carry-forward and evidence policy helpers `:1734-1830`; stale-work/cancel/revision/UI helpers `:1833-2032`; stale execution/evidence filters `:2035-2122`; existing classifier/applicator in `planning/v2_interrupts.py` | `v2_interrupts.py` owns generic interrupt classification and ledger mutation; graph owns checkpoint-aware stale-work, approval invalidation, and UI pointer policy | `tests/test_planner_owned_graph_interruptions.py:22`, `:47`, `:76`, `:101`, `:131`, `:157`, `:203`, `:238`; `tests/test_planner_owned_interrupt_replan.py`; `tests/test_api_endpoints.py:2648` | High | Candidate `graph/interrupt_policy.py` after checkpoint helpers are extracted. Keep `session.replan_context` as pointer-only, never authoritative graph state. |
| checkpoint/state persistence | `v2_agent_graph.py:340-362`, `:364-426`, `:428-526`, `:1583-1600`; utility helpers `:2125-2202`, `:2609-2658`; checkpointer factory in `graph/checkpointing.py`; persistence projection in `services/planner_owned_graph_runtime.py:251-299` | LangGraph checkpointer is authoritative graph state; runtime adapter projects graph state to session context without authority | `tests/test_planner_owned_graph_shell_contract.py:214`, `:285`; `tests/test_planner_owned_graph_approval_resume.py:307`, `:369`, `:415`; `tests/test_planner_owned_graph_interruptions.py:238`; `tests/test_planner_owned_graph_runtime_adapter.py:160`, `:218` | Low/Medium for pure helpers; High for entrypoints | Phase 1 candidate `graph/checkpoint_state.py` for option/config/identity/session-context helpers only. Do not move run/resume/interrupt entrypoints in Phase 1. |
| response-document projection | `v2_agent_graph.py:1190-1268`; response block helpers `:3331-3596`; runtime adapter plan/output projection in `services/planner_owned_graph_runtime.py:251-941`; response-document service remains separate | Graph owns draft response-document context and compact graph blocks; `ResponseDocumentService` owns persisted/API response-document rendering | `tests/test_planner_owned_graph_read_flows.py:265`, `:287`, `:309`, `:345`, `:388`; `tests/test_planner_owned_graph_rag_evidence.py:121`, `:171`; `tests/test_planner_owned_graph_approval_resume.py:243`, `:500`; `tests/test_response_document_contract.py`; `tests/test_response_document_failures.py`; frontend `npm run test:e2e:response-document` gate | Medium | Candidate `graph/response_projection.py` after approval/evidence ownership is clearer. Must not duplicate `ResponseDocumentService`; graph projection remains diagnostics/context only. |
| generic utility | `v2_agent_graph.py:2133-2141` `_coerce_positive_int`; `:2169-2170` `_state_update`; `:2197-2208` `_session_context_value` / `_maybe_await`; mapping/row helpers `:2290-2291`, `:2364-2379`, `:3495-3522`; plural/summary helpers `:3525-3576` | No standalone owner; helpers belong with the deep cluster that uses them | Covered indirectly by the cluster tests above | Low individually, but shallow if extracted alone | Do not create a generic utility module. Move helpers only with a deep owner such as checkpoint, approval preview, tool choice, or response projection. |
| unknown owner | none identified in Phase 0 | n/a | n/a | n/a | No current cluster needs `unknown owner`; if later phases discover cross-cutting ownership, record it before moving code. |

## Low-Risk Extraction Candidates

| Candidate | Symbol Cluster | Why It Has Depth | Required Proof Before Phase Complete |
| --- | --- | --- | --- |
| Checkpoint/state helper module | `_normalize_options`, `_checkpoint_config`, `_session_context_value`, `_current_graph_checkpoint_id`, `_graph_checkpoint_identity`, `_graph_checkpoint_identity_for_current_revision`, `_checkpoint_tuple_id`, `_state_update` | The interface can hide LangGraph config shape, session context lookup, and graph checkpoint identity rules behind a small contract used by run/resume/interrupt/approval staging. | `tests/test_planner_owned_graph_shell_contract.py`; `tests/test_planner_owned_graph_approval_resume.py`; `tests/test_planner_owned_graph_interruptions.py`; `tests/test_planner_owned_graph_runtime_adapter.py`. |
| Approval preview helper module | `_normalize_approval_preview`, `_graph_write_approval_preview`, `_approval_preview_read_card`, `_approval_preview_read_args`, `_execute_approval_preview_read`, `_rows_from_projected_body`, `_approval_preview_rows_from_read`, `_prior_write_ids_moved_into_source_priority`, `_staged_write_tool_calls_from_preview`, `_commit_args_from_preview` | It owns a real sub-problem: build a safe preview, filter rows, derive staged writes, and produce commit args without exposing callers to read-tool/projected-row details. | `tests/test_planner_owned_graph_approval_resume.py`; `tests/test_api_endpoints.py` graph approval tests; `tests/test_planner_owned_graph_runtime_adapter.py:287`, `:370`. |
| Tool-choice construction module | `_deterministic_choose_tool_if_state_proves_single_document_tool`, `_tool_calls_for_card`, `_select_graph_tool_card`, `_card_supports_*`, `_batch_identity_arg`, `_identity_arg_names`, `_multi_entity_identity_values`, `_args_for_tool_call`, `_argument_value_for` | It can own graph-local executable call construction while still consuming existing `ToolSelector` and hydrated cards from the retriever. | `tests/test_planner_owned_graph_retrieval_contract.py`; `tests/test_planner_owned_graph_llm_proposer.py`; `tests/test_route_to_execution_contract.py`; `tests/test_tool_selector.py`. |
| Response projection helper module | `_phase6_response_blocks`, `_phase6_response_summary`, `_phase6_response_block_for_evidence`, `_evidence_has_no_match`, `_is_document_insufficient_context_evidence`, `_phase6_rows`, `_phase6_fields`, `_pending_approval_response_block` | It owns graph response-context projection and evidence-to-block summaries, separate from persisted/API response-document rendering. | `tests/test_planner_owned_graph_read_flows.py`; `tests/test_planner_owned_graph_rag_evidence.py`; `tests/test_planner_owned_graph_approval_resume.py`; response-document backend/frontend gates if visible output changes. |

## High-Risk Areas

| Area | Reason | Current Guard |
| --- | --- | --- |
| Public runtime entrypoints | `run`, `run_state`, `resume_from_approval`, and `interrupt_with_user_message` define external runtime behavior and checkpoint authority. | Keep in `PlannerOwnedAgentGraph` until interface freeze. |
| Approval stage/resume state machine | Staging crosses proposer authorization, preview read execution, pending approval state, checkpoint identity, persisted approval payloads, staged writes, and evidence. | Approval graph tests plus API approval tests. |
| Interrupt and stale-work policy | Interrupt flow mutates ledger/evidence/pending approvals/checkpoint identity and writes UI pointers while keeping `session.replan_context` non-authoritative. | Phase 9 interruption tests and API replan-context tests. |
| Tool execution node | The node ties planner decisions to deterministic execution guards, approval pause, parallel read batches, adapter execution, and pending result observation. | Execution-observation tests, retrieval contract tests, route-to-execution tests. |
| Satisfaction/finalization | Finalization depends on active-revision evidence filtering, deterministic satisfaction, approval/write follow-up status, and decision validation. | Read-flow, satisfaction, approval resume, and execution failure tests. |
| Response-document visible output | Graph response blocks feed persisted/API response-document projection through the runtime adapter. | Response-document backend tests and frontend response-document E2E when output changes. |

## Phase 0: Runtime Responsibility Audit

Status: complete.

Phase 0 verdict:

- Complete as a docs/tracker-only audit phase.
- No runtime code was moved.
- No symbols were renamed.
- No tests were changed.
- No product behavior changed.
- No new ToolSelector, RAG, approval, response-document, checkpoint, or proposer stack was created.
- `session.replan_context` remains pointer/projection context only, not authoritative graph state.

Files changed:

- `docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_PLAN.md`
- `docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md`

Symbols moved:

- none

Module ownership:

- `v2_agent_graph.py` remains the owner of graph topology/orchestration and public runtime entrypoints.
- Existing `planning/v2_planner_decisions.py` and `planning/v2_planner_proposer.py` remain owners of decision validation and proposer adapters.
- Existing `planning/v2_graph_adapters.py`, `planning/v2_rag_tool.py`, `planning/v2_tool_retriever.py`, and `ToolSelector` remain owners of execution, RAG, retrieval, and selection stacks.
- Existing `planning/v2_satisfaction.py` remains owner of deterministic satisfaction/final validation rules.
- Existing `planning/v2_interrupts.py` remains owner of generic interrupt classification and ledger mutation.
- Existing `graph/checkpointing.py` remains owner of checkpointer construction.
- Existing `services/planner_owned_graph_runtime.py` remains owner of graph-result persistence and API/session projection.
- Future extraction should target deeper graph-local modules only where the candidate owns a real sub-problem.

Audit commands used:

```powershell
git status --short --branch
(Get-Content factory-agent/factory_agent/graph/v2_agent_graph.py).Count
rg -n "^class |^(async )?def |^    (async )?def |^    class " factory-agent/factory_agent/graph/v2_agent_graph.py
rg -n "async def _.*_node|def _.*_edge|StateGraph|add_node|add_edge|add_conditional_edges|compile\(" factory-agent/factory_agent/graph/v2_agent_graph.py
rg -n "PlannerOwnedAgentGraph|PlannerOwnedAgentGraphAdapters|PlannerOwnedAgentGraphRunOptions|PlannerOwnedGraphResult" factory-agent/factory_agent factory-agent/tests docs/qa
rg -n "def test_|class Test" factory-agent/tests/test_planner_owned_graph_shell_contract.py factory-agent/tests/test_planner_owned_graph_runtime_adapter.py factory-agent/tests/test_planner_owned_graph_approval_resume.py factory-agent/tests/test_planner_owned_graph_execution_observation.py factory-agent/tests/test_planner_owned_graph_interruptions.py factory-agent/tests/test_planner_owned_graph_llm_proposer.py factory-agent/tests/test_planner_owned_graph_proposer_policy.py factory-agent/tests/test_planner_owned_graph_rag_evidence.py factory-agent/tests/test_planner_owned_graph_read_flows.py factory-agent/tests/test_planner_owned_graph_retrieval_contract.py factory-agent/tests/test_planner_owned_graph_state_contract.py factory-agent/tests/test_route_to_execution_contract.py
rg -n "approval|preview|staged|resume|pending_approval|WAITING_APPROVAL|bundle|checkpoint" factory-agent/tests/test_planner_owned_graph_approval_resume.py factory-agent/tests/test_api_endpoints.py factory-agent/tests/test_route_to_execution_contract.py factory-agent/tests/test_planner_owned_graph_runtime_adapter.py
rg -n "interrupt|stale|cancel|revision|carry_forward|background|session_replan_context|replan_context|checkpoint" factory-agent/tests/test_planner_owned_graph_interruptions.py factory-agent/tests/test_planner_owned_graph_approval_resume.py factory-agent/tests/test_planner_owned_graph_execution_observation.py factory-agent/tests/test_planner_owned_graph_runtime_adapter.py
```

Verification:

- `git diff --check -- docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_PLAN.md docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md` -> passed after temporary intent-to-add so untracked docs were inspected; LF/CRLF warnings only, no whitespace errors.
- `git status --short --branch`:

```text
## main...origin/main
?? docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_PLAN.md
?? docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md
```

- Runtime tests not run; not required for docs/tracker-only Phase 0.

Blockers:

- none

Open issues:

- none

Commit:

- `9026e3cb`

## Phase 1: Checkpoint And State Utility Extraction

Status: complete pending commit.

Phase 1 verdict:

- Complete as a narrow checkpoint/state utility extraction.
- Runtime entrypoints stayed in `v2_agent_graph.py`: `run`, `run_state`, `resume_from_approval`, and `interrupt_with_user_message`.
- Graph topology, node orchestration, approval preview/staged-write helpers, interrupt/revision policy helpers, response projection helpers, release harness behavior, Qwen/proposer policy, frontend fixtures, and product behavior were not changed.
- `session.replan_context` remains pointer/projection context only, not authoritative graph state.
- No exact-prompt, seeded-ID, or source-ID runtime branch was added.

Files changed:

- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/graph/v2_graph_state_utils.py`
- `docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md`

Symbols moved:

- `PlannerOwnedAgentGraphRunOptions`
- `_normalize_options`
- `_checkpoint_config`
- `_checkpoint_tuple_id`
- `_graph_checkpoint_identity`
- `_graph_checkpoint_identity_for_current_revision`
- `_current_graph_checkpoint_id`
- `_state_update`
- `_session_context_value`
- `_coerce_positive_int`

Symbols intentionally not moved:

- `_record_node_visit` remains in `v2_agent_graph.py` because Phase 0 classifies it with graph topology/orchestration and it records through `LocalPlannerOwnedGraphTracer`.
- `_maybe_await` remains in `v2_agent_graph.py` with checkpoint loading, which still belongs to the public resume/interrupt entrypoints in Phase 1.

Module ownership:

- `graph/v2_graph_state_utils.py` now owns graph run option normalization, LangGraph checkpoint config shape, graph checkpoint identity derivation, checkpoint tuple id extraction, current checkpoint id lookup, session-context field lookup, graph state update projection, and positive revision integer coercion.
- `v2_agent_graph.py` remains the owner of graph topology/orchestration, public runtime entrypoints, graph nodes, approval pause/resume flow, interrupt/revision policy, and response projection.
- `graph/checkpointing.py` remains the checkpointer construction owner.
- `services/planner_owned_graph_runtime.py` remains the graph-result persistence and API/session projection owner.

Audit commands used:

```powershell
rg -n "_normalize_options|_checkpoint_config|_checkpoint_tuple_id|_graph_checkpoint_identity|_graph_checkpoint_identity_for_current_revision|_current_graph_checkpoint_id|_state_update|_session_context_value|_coerce_positive_int|_record_node_visit" factory-agent/factory_agent/graph/v2_agent_graph.py factory-agent/tests
rg -n "PlannerOwnedAgentGraphRunOptions|PlannerOwnedGraphResult|LocalPlannerOwnedGraphTracer|_state_update|_checkpoint_config|_graph_checkpoint_identity" factory-agent/factory_agent factory-agent/tests
rg -n "def _normalize_options|def _checkpoint_config|def _checkpoint_tuple_id|def _graph_checkpoint_identity|def _graph_checkpoint_identity_for_current_revision|def _current_graph_checkpoint_id|def _state_update|def _session_context_value|def _coerce_positive_int|def _record_node_visit|class PlannerOwnedAgentGraphRunOptions" factory-agent/factory_agent/graph/v2_agent_graph.py factory-agent/factory_agent/graph/v2_graph_state_utils.py
```

Verification:

- `python -m compileall factory-agent\factory_agent\graph\v2_agent_graph.py factory-agent\factory_agent\graph\v2_graph_state_utils.py` -> compiled both files.
- `python -m pytest tests/test_planner_owned_graph_no_legacy_authority.py -q` -> `24 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `2 warnings`.
- `python -m pytest tests/test_planner_owned_graph_approval_resume.py tests/test_planner_owned_graph_interruptions.py -q` -> `19 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`. Non-blocking LangSmith ingest 429/network messages printed after the pytest summary.
- `python -m pytest tests/test_planner_owned_graph_shell_contract.py tests/test_planner_owned_graph_approval_resume.py tests/test_planner_owned_graph_interruptions.py tests/test_planner_owned_graph_runtime_adapter.py -q` -> `33 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `5 warnings`. Non-blocking LangSmith ingest 429/network messages printed after the pytest summary.
- `python -m pytest tests/test_planner_owned_graph_*.py -q` -> PowerShell passed the wildcard literally, so pytest reported `file or directory not found` before collection. Corrected with an explicit file list.
- `$files = (Get-ChildItem -LiteralPath 'tests' -Filter 'test_planner_owned_graph_*.py').FullName; python -m pytest $files -q` -> `117 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `64 warnings`. Non-blocking LangSmith ingest 429 messages printed after the pytest summary.
- `python -m pytest -q` -> `932 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1289 warnings`.
- `git diff --check` -> passed; LF/CRLF warnings only, no whitespace errors.

Blockers:

- none

Open issues:

- LangSmith ingest emitted non-blocking 429/network messages after several pytest summaries. Pytest exit codes were green.

Commit:

- pending

## Phase 2: Approval Preview And Staged Write Module

Status: complete pending commit.

Phase 2 verdict:

- Complete as a narrow approval preview and staged-write helper extraction.
- Runtime entrypoints stayed in `v2_agent_graph.py`: `run`, `run_state`, `resume_from_approval`, and `interrupt_with_user_message`.
- Graph topology, node orchestration, approval resume state machine, interrupt/revision policy helpers, release harness behavior, Qwen/proposer policy, frontend fixtures, and product behavior were not changed.
- `session.replan_context` remains pointer/projection context only, not authoritative graph state.
- No exact-prompt, seeded-ID, source-ID, legacy/direct-v2, or old-graph authority branch was added.

Files changed:

- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/graph/v2_graph_approval.py`
- `docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md`

Symbols moved:

- `PlannerOwnedGraphApprovalPreview`
- `_normalize_approval_preview`
- `_graph_write_approval_preview`
- `_approval_preview_read_card`
- `_approval_preview_read_args`
- `_execute_approval_preview_read`
- `_mapping_or_empty`
- `_rows_from_projected_body`
- `_approval_preview_rows_from_read`
- `_prior_write_ids_moved_into_source_priority`
- `_priority_pair_from_preview_rows`
- `_staged_write_tool_calls_from_preview`
- `_pending_staged_tool_calls`
- `_source_priority_constraint`
- `_target_priority_constraint`
- `_no_records_preview_message`
- `_default_approval_preview`
- `_commit_args_from_preview`
- `_pending_approval_response_block`

Symbols intentionally not moved:

- `_next_approval_index` remains in `v2_agent_graph.py` because approval numbering is tied to graph planner decisions.
- `_write_choice_finished_without_pending_approval` remains in `v2_agent_graph.py` because it gates graph node continuation after no-record/impossible approval staging.
- `_approval_decision_matches_pending` remains in `v2_agent_graph.py` because it is part of checkpoint-aware graph approval resume behavior.
- `_card_supports_collection_read` remains in `v2_agent_graph.py` for Phase 2 because tool-choice card selection also uses it. The approval module receives this predicate from the graph adapter instead of importing graph topology/helpers back and creating a circular owner.

Module ownership:

- `graph/v2_graph_approval.py` now owns graph approval preview normalization, preview read-tool selection/argument construction, preview read execution, API body projection to preview rows, prior-approved-write exclusion, priority constraint extraction, staged write-call expansion, pending staged-call recovery, commit args derived from preview rows, default/no-record preview messages, and pending approval response block projection.
- `v2_agent_graph.py` remains the owner of graph topology/orchestration, public runtime entrypoints, graph nodes, approval pause/resume state machine, graph decision recording, graph checkpoint identity during approval staging, interrupt/revision policy, and response-document context assembly.
- `graph/approval_summary.py` remains the approval payload summary owner.
- `services/planner_owned_graph_runtime.py` remains the graph-result persistence and API/session projection owner.

Audit commands used:

```powershell
rg -n "_normalize_approval_preview|_graph_write_approval_preview|_approval_preview|_staged_write|_pending_staged|_source_priority_constraint|_target_priority_constraint|_commit_args_from_preview|_pending_approval_response_block|_next_approval_index|_approval_decision_matches_pending" factory-agent/factory_agent/graph/v2_agent_graph.py factory-agent/tests
rg -n "v2_graph_state_utils|Approval Preview|approval preview|staged-write|staged write|graph approval module|Phase 2" docs factory-agent -g "*.md"
rg -n "PlannerOwnedGraphApprovalPreview|PlannerOwnedGraphRetrieval|PlannerOwnedAgentGraphRunOptions" factory-agent/factory_agent factory-agent/tests
rg -n "_commit_args_from_preview|_staged_write_tool_calls_from_preview|_pending_staged_tool_calls|_pending_approval_response_block|_source_priority_constraint|_target_priority_constraint|_no_records_preview_message|_default_approval_preview|_rows_from_projected_body" factory-agent/factory_agent factory-agent/tests
rg -n "api_row_id|project_api_body|def _normalize_approval_preview|def _graph_write_approval_preview|def _approval_preview_read_card|def _approval_preview_read_args|def _execute_approval_preview_read|def _rows_from_projected_body|def _approval_preview_rows_from_read|def _prior_write_ids_moved_into_source_priority|def _priority_pair_from_preview_rows|def _staged_write_tool_calls_from_preview|def _pending_staged_tool_calls|def _source_priority_constraint|def _target_priority_constraint|def _no_records_preview_message|def _default_approval_preview|def _commit_args_from_preview|def _pending_approval_response_block" factory-agent/factory_agent/graph/v2_agent_graph.py factory-agent/factory_agent/graph/v2_graph_approval.py
```

Verification:

- `python -m compileall factory-agent\factory_agent\graph\v2_agent_graph.py factory-agent\factory_agent\graph\v2_graph_approval.py` -> compiled both files.
- `python -m pytest tests/test_planner_owned_graph_no_legacy_authority.py -q` -> `24 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `2 warnings`.
- `python -m pytest tests/test_planner_owned_graph_approval_resume.py tests/test_planner_owned_graph_runtime_adapter.py -q` -> `17 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `4 warnings`. Non-blocking LangSmith ingest 429/network messages printed after the pytest summary.
- `python -m pytest tests/test_api_endpoints.py -q` -> `42 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `828 warnings`. Non-blocking LangSmith ingest 429/network messages printed after the pytest summary.
- `$files = (Get-ChildItem -LiteralPath 'tests' -Filter 'test_planner_owned_graph_*.py').FullName; python -m pytest $files -q` -> `117 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `64 warnings`. Non-blocking LangSmith ingest 429 messages printed after the pytest summary.
- `python -m pytest -q` -> `932 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1289 warnings`.
- `git diff --check` -> passed; LF/CRLF warnings only, no whitespace errors.

Blockers:

- none

Open issues:

- LangSmith ingest emitted non-blocking 429/network messages after several pytest summaries. Pytest exit codes were green.

Commit:

- pending

## Phase 3: Interrupt And Revision Policy Module

Status: complete pending commit.

Phase 3 verdict:

- Complete as a narrow graph interrupt/revision/stale-work policy extraction.
- Runtime entrypoints stayed in `v2_agent_graph.py`: `run`, `run_state`, `resume_from_approval`, and `interrupt_with_user_message`.
- Graph topology, graph nodes, approval preview/staged-write helpers, approval resume state machine, response projection, release harness behavior, Qwen/proposer policy, frontend fixtures, and product behavior were not changed.
- `session.replan_context` remains pointer/projection context only, not authoritative graph state.
- No exact-prompt, seeded-ID, source-ID, legacy/direct-v2, or old-graph authority branch was added.

Files changed:

- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/graph/v2_graph_interrupts.py`
- `docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md`

Symbols moved:

- `_apply_graph_revision_evidence_policy`
- `_invalidate_graph_work_after_interrupt`
- `_close_graph_after_cancel_interrupt`
- `_record_graph_interrupt_revision_trace`
- `_store_graph_interrupt_pointer_for_ui`
- `_attach_graph_work_identity`
- `_attach_graph_evidence_identity`
- `_stale_background_result_reason`
- `_evidence_can_satisfy_active_revision`
- `_planner_decision_is_active_for_graph_revision`
- `_record_graph_requirement_update`

Symbols intentionally not moved:

- `interrupt_with_user_message` remains in `v2_agent_graph.py` because it is the public graph runtime entrypoint for checkpoint-backed user revisions.
- Graph nodes remain in `v2_agent_graph.py`.
- `run`, `run_state`, and `resume_from_approval` remain in `v2_agent_graph.py`.
- Approval preview/staged-write helpers remain in `graph/v2_graph_approval.py`.
- Response projection helpers remain in `v2_agent_graph.py`.
- `_explicit_carried_forward_evidence_refs` remains in `v2_agent_graph.py` because it reads runtime option/session context immediately before interrupt policy application.

Module ownership:

- `graph/v2_graph_interrupts.py` now owns graph revision evidence policy, stale-work invalidation after interrupts, cancel-run closure policy, graph interrupt revision trace metadata, UI interrupt pointer storage, active-revision evidence/work identity, stale background result checks, active planner-decision filtering, and graph requirement update bookkeeping.
- `planning/v2_interrupts.py` remains the generic interrupt classification and ledger mutation owner.
- `v2_agent_graph.py` remains the owner of graph topology/orchestration, public runtime entrypoints, graph nodes, approval pause/resume state machine, graph checkpoint identity during approval staging, and response-document context assembly.
- `graph/v2_graph_state_utils.py` remains the graph checkpoint/session-context utility owner consumed by the interrupt policy module.
- `services/planner_owned_graph_runtime.py` remains the graph-result persistence and API/session projection owner.

Audit commands used:

```powershell
rg -n "_apply_graph_revision_evidence_policy|_invalidate_graph_work_after_interrupt|_close_graph_after_cancel_interrupt|_record_graph_interrupt_revision_trace|_store_graph_interrupt_pointer_for_ui|_attach_graph_work_identity|_attach_graph_evidence_identity|_stale_background_result_reason|_evidence_can_satisfy_active_revision|_planner_decision_is_active_for_graph_revision|_record_graph_requirement_update" factory-agent/factory_agent/graph/v2_agent_graph.py factory-agent/tests
rg -n "Phase 0|Phase 2|interrupt|revision|stale|tracker|extraction|approval preview|staged-write" .
rg -n "v2_agent_graph|interrupt|revision|approval preview|staged|Phase 0|Phase 2|Phase 3" factory-agent/phase_checklists factory-agent/docs factory-agent/runbooks
rg -n "Phase 1 extracted|Phase 2 extracted|checkpoint/state|staged-write|approval preview|Module Extraction|extraction|v2_graph_state_utils|v2_graph_approval|v2_graph_interrupts|v2_agent_graph" . -g "*.md"
rg -n "def _requirement_by_id|_requirement_by_id\(|_sync_graph_satisfaction_state\(|_unique_graph_evidence_id\(" factory-agent/factory_agent/graph/v2_agent_graph.py
rg -n "uuid4|RequirementRevisionRecord|RequirementSatisfactionState|validate_graph_state_final_state|record_planner_decision\(|PendingApprovalState|EvidenceLedgerEntry|SatisfactionCheck|UserInterrupt|GraphToolExecutionResult|_coerce_positive_int|_current_graph_checkpoint_id|_session_context_value" factory-agent/factory_agent/graph/v2_agent_graph.py
rg -n "test_planner_owned_graph_interrupts|phase9|interrupt|approval_resume|resume_from_approval|stale" factory-agent/tests -g "*.py"
```

Verification:

- `python -m compileall factory_agent/graph/v2_agent_graph.py factory_agent/graph/v2_graph_interrupts.py` -> compiled both files.
- `python -m pytest tests/test_planner_owned_graph_interruptions.py -q` -> `9 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`. Non-blocking LangSmith ingest 429/network messages printed after the pytest summary before tracing was disabled for later runs.
- `python -m pytest tests/test_planner_owned_graph_no_legacy_authority.py -q` -> `24 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `2 warnings`.
- `python -m pytest tests/test_planner_owned_graph_approval_resume.py -q` -> `10 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `$files = (Get-ChildItem -LiteralPath 'tests' -Filter 'test_planner_owned_graph_*.py').FullName; python -m pytest $files -q` -> `117 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `64 warnings`.
- `python -m pytest -q` -> `932 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1289 warnings`.
- `git diff --check` -> passed; LF/CRLF warnings only, no whitespace errors.

Blockers:

- none

Open issues:

- LangSmith ingest emitted non-blocking 429/network messages after the first interruption test run. Later pytest commands disabled LangSmith tracing and exited green.

Commit:

- pending

## Phase 5: Evidence And Response Projection Split

Phase result:

- Passed. Extracted graph evidence-to-response block projection and summary helpers from `v2_agent_graph.py` into `factory_agent/graph/v2_graph_response_projection.py`.
- `v2_agent_graph.py` still owns graph topology, public runtime entrypoints, graph nodes, runtime orchestration, approval pause/resume behavior, response-document context assembly, repeated-retrieval guard telemetry, and execution orchestration.
- `_response_document_node()` stayed in `v2_agent_graph.py`; no second response-document renderer was introduced.
- `_pending_approval_response_block` stayed in `v2_graph_approval.py` because approval response projection is already owned with graph approval preview/staging behavior.

Files changed:

- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/graph/v2_graph_response_projection.py`
- `docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md`

Symbols moved:

- `_phase6_response_blocks`
- `_phase6_response_summary`
- `_phase6_response_block_for_evidence`
- `_phase6_rows`
- `_phase6_fields`
- `_first_field_value`
- `_single_status_summary`
- `_collection_summary`
- `_mutation_summary`
- `_no_match_summary`
- `_plural_entity`
- `_evidence_has_no_match`
- `_is_document_insufficient_context_evidence`

Module ownership changed:

- `graph/v2_graph_response_projection.py` now owns graph-local evidence-to-response block projection, graph response summary construction, no-record/RAG-insufficient-context evidence classification for response diagnostics, normalized row/field extraction for graph response blocks, and compact single/collection/mutation/no-match summaries.
- `v2_agent_graph.py` remains the owner of graph topology/orchestration, public runtime entrypoints, graph nodes, approval pause/resume behavior, response-document context assembly, active/historical evidence reference assembly, repeated-retrieval guard telemetry, and execution orchestration.
- `graph/v2_graph_approval.py` remains the owner of approval preview/staged-write helpers and pending approval response block projection.
- `ResponseDocumentService` remains the persisted/API response-document renderer.

Verification:

- `python -m py_compile factory-agent\factory_agent\graph\v2_agent_graph.py factory-agent\factory_agent\graph\v2_graph_response_projection.py`: passed.
- `cd factory-agent; python -m pytest tests/test_planner_owned_graph_no_legacy_authority.py -q`: 24 passed, 2 warnings.
- `cd factory-agent; python -m pytest tests/test_planner_owned_graph_read_flows.py tests/test_planner_owned_graph_rag.py tests/test_response_document*.py -q`: no tests ran because `tests/test_planner_owned_graph_rag.py` is not present in this checkout.
- `cd factory-agent; python -m pytest tests/test_planner_owned_graph_read_flows.py tests/test_planner_owned_graph_rag_evidence.py tests/test_response_document_contract.py tests/test_response_document_failures.py -q`: 61 passed, 141 warnings.
- `cd factory-agent; $files = Get-ChildItem tests -Filter 'test_planner_owned_graph_*.py' | ForEach-Object { $_.FullName }; python -m pytest @files -q`: 117 passed, 64 warnings.
- `cd factory-agent; python -m pytest -q`: 932 passed, 3 skipped, 1289 warnings.
- `cd "eMas Front"; npm run test:e2e:response-document`: 30 passed.
- `cd "eMas Front"; npm run test:e2e:seeded-oracles`: first run had 33 passed and 2 failed hard-query checks where the backend remained in `PLANNING`; targeted rerun of the two failed hard-query checks passed 2/2; full required rerun passed 35/35.
- `cd "eMas Front"; npm run test:e2e:release`: 21 passed.
- `git diff --check`: passed with Git line-ending warnings only.

Candidate dispositions changed:

- Graph evidence/response projection helpers moved to `v2_graph_response_projection.py`.
- Approval response block projection retained in `v2_graph_approval.py`.
- Response-document context assembly retained in `_response_document_node()`.
- No graph topology, graph nodes, runtime entrypoints, adapters, ToolSelector, RAG/tool execution stack, approval pause/resume behavior, planner decision validation, frontend fixtures, release harness behavior, Qwen/proposer policy, exact-prompt branches, seeded-ID branches, or source-ID branches changed.

Blockers and owners:

- None. The initial seeded-oracle failure reproduced as a transient hard-query timing/backend-state gap and passed both targeted and full reruns.

Commit:

- `0eb4c7b7`

## Phase 6: Graph File Slimming And Interface Freeze

Phase result:

- Passed. Slimmed `v2_agent_graph.py` without changing graph runtime behavior.
- Removed two obsolete local leftovers from earlier extractions: the duplicate `_sync_graph_satisfaction_state()` helper now owned by `v2_graph_interrupts.py`, and unused `_latest_decision()`.
- Removed the now-unused `RequirementSatisfactionState` import.
- Confirmed no unused import candidates beyond `from __future__ import annotations`, and no zero-reference top-level graph helpers remain.
- Confirmed the public runtime interface remains stable: `PlannerOwnedAgentGraph`, `PlannerOwnedAgentGraphAdapters`, `PlannerOwnedAgentGraphRunOptions`, and `PlannerOwnedGraphResult`. No `PlannerOwnedAgentGraphRunResult` symbol exists in the current runtime.
- LOC check with `(Get-Content factory-agent/factory_agent/graph/v2_agent_graph.py).Count`: Phase 6 start `2110`, after slimming `2085`.

Files changed:

- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md`

Symbols moved:

- none

Symbols removed:

- `_sync_graph_satisfaction_state` duplicate in `v2_agent_graph.py`; canonical owner remains `graph/v2_graph_interrupts.py`.
- `_latest_decision`; unused local helper.

Module ownership:

- `v2_agent_graph.py` is frozen as the owner of graph topology, graph nodes, public runtime entrypoints, execution orchestration, approval pause/resume behavior, repeated-retrieval guard telemetry, and response-document node assembly.
- `graph/v2_graph_state_utils.py` owns run options and checkpoint/session-context helper utilities.
- `graph/v2_graph_approval.py` owns approval preview/staged-write helpers and pending approval response block projection.
- `graph/v2_graph_interrupts.py` owns graph interrupt/revision/stale-work policy and satisfaction sync after graph requirement updates.
- `graph/v2_graph_tool_choice.py` owns graph tool choice/card/call helper logic.
- `graph/v2_graph_response_projection.py` owns graph-local evidence-to-response block and response summary projection.
- Existing ToolSelector, RAG/tool execution, planner proposer/decision, approval persistence, response-document rendering, and checkpoint construction owners remain unchanged.

Verification:

- `python -m compileall -q factory-agent/factory_agent/graph`: passed.
- `cd factory-agent; python -m pytest tests/test_planner_owned_graph_no_legacy_authority.py -q`: 24 passed, 2 warnings.
- `cd factory-agent; $files = Get-ChildItem -LiteralPath tests -Filter 'test_planner_owned_graph_*.py' | ForEach-Object { $_.FullName }; python -m pytest @files -q`: 117 passed, 64 warnings.
- `cd factory-agent; python -m pytest -q`: 932 passed, 3 skipped, 1290 warnings.
- `cd "eMas Front"; npm run test:e2e:response-document`: 30 passed.
- `cd "eMas Front"; npm run test:e2e:seeded-oracles`: 35 passed.
- `cd "eMas Front"; npm run test:e2e:real-langgraph`: 3 passed.
- `cd "eMas Front"; npm run test:e2e:release`: first two full runs had 20 passed and 1 failed in scenario 60 because the remote planner model returned `503 Service Unavailable` before the Go API outage branch; final full rerun with LangSmith tracing disabled passed 21 passed.
- `git diff --check`: passed with Git line-ending warnings only, no whitespace errors.

Guardrails:

- No runtime behavior changed.
- No graph topology, graph nodes, public entrypoints, response-document semantics, approval behavior, interrupt behavior, tool/RAG execution behavior, release harness/frontend fixtures, or Qwen/proposer policy changed.
- No exact-prompt, seeded-ID, or source-ID runtime branch was added.
- `session.replan_context` remains pointer/projection context only, not authoritative graph state.

Blockers:

- none

Open issues:

- Earlier release retries were blocked by transient remote planner provider `503` in scenario 60. Final full release run passed after rerun.

Commit:

- pending

## Next Handoff Prompt

```text
You are implementing Phase 7 of docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_PLAN.md.

Goal:
Run the final planner-owned graph runtime refactor release proof and make the current refactor baseline explicit.

Context:
The planner-owned graph migration and legacy cleanup are separate. Phases 1 through 5 moved checkpoint/state, approval preview/staged-write, interrupt/revision policy, tool choice, and response projection helpers into focused modules. Phase 6 slimmed `v2_agent_graph.py` and froze the public runtime interface. Runtime entrypoints, graph topology, release harness behavior, Qwen/proposer policy, frontend fixtures, and product behavior remained unchanged.

Read first:
- docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_PLAN.md
- docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md
- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md
- factory-agent/factory_agent/graph/v2_agent_graph.py
- factory-agent/factory_agent/services/planner_owned_graph_runtime.py
- factory-agent/factory_agent/planning/v2_agent_state.py
- factory-agent/factory_agent/planning/v2_graph_adapters.py
- factory-agent/factory_agent/planning/v2_planner_decisions.py
- factory-agent/factory_agent/planning/v2_planner_proposer.py
- factory-agent/factory_agent/planning/v2_satisfaction.py
- factory-agent/factory_agent/planning/v2_interrupts.py

Scope:
- Implement only Phase 7.
- Treat this as release proof, not a new extraction phase.
- Confirm the public runtime interface remains `PlannerOwnedAgentGraph`, `PlannerOwnedAgentGraphAdapters`, `PlannerOwnedAgentGraphRunOptions`, and `PlannerOwnedGraphResult`.
- Do not move graph run/resume/interrupt entrypoints, graph topology, or graph nodes.
- Do not reopen approval, interrupt, tool-choice, checkpoint, or response projection extraction decisions unless a compile/test failure proves a misplaced helper.
- Do not rename symbols.
- Do not change product behavior.
- Update the tracker.

Maintainability rules:
- Increase module depth and locality.
- Do not create shallow pass-through modules.
- Keep graph runtime public interface stable.
- Do not duplicate ToolSelector, RAG, approval, response-document, checkpoint, or proposer stacks.
- Do not make session.replan_context authoritative graph state.

Guardrails:
- No product behavior changes.
- No planner-owned graph runtime behavior changes.
- No release harness changes.
- No Qwen/proposer policy changes.
- No exact-prompt, seeded-ID, or source-ID runtime branches.
- Do not reopen legacy/direct-v2/old graph authority.

Suggested audit commands:
- `rg -n "class PlannerOwnedAgentGraph|async def run|async def resume_from_approval|async def interrupt_with_user_message|PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER|_response_document_node" factory-agent/factory_agent/graph/v2_agent_graph.py`
- `rg -n "PlannerOwnedAgentGraphRunResult|exact prompt|seeded.*branch|source.*branch|session\\.replan_context.*authoritative" factory-agent/factory_agent docs/qa`

Verification:
- `cd factory-agent`
- `python -m pytest tests/test_planner_owned_graph_no_legacy_authority.py -q`
- `python -m pytest -q`
- `cd ..`
- `cd "eMas Front"`
- `npm test`
- `npm run test:e2e:response-document`
- `npm run test:e2e:seeded-oracles`
- `npm run test:e2e:real-langgraph`
- `npm run test:e2e:release`
- `cd ..`
- `git diff --check`
- `git status --short --branch`

Commit only if behavior is unchanged and all required backend/frontend gates pass.

Suggested commit:
`test: record planner-owned graph refactor release proof`

Final response sections:
Phase Result
Files Changed
Module Ownership
Tracker Update
Verification
Guardrail Checklist
Open Issues
Next Step
```

## Update Rules

Every phase update must include:

- files changed,
- symbols moved,
- module ownership changed,
- tests run,
- exact pass/fail/skip/xfail counts,
- whether `git diff --check` passed,
- blockers and owners,
- whether a commit was created,
- commit hash when committed.

Do not mark a phase complete if:

- runtime behavior changed outside scope,
- tests were weakened without replacement coverage,
- a shallow pass-through module was created,
- exact-prompt or seeded-ID runtime branches were added,
- legacy/direct-v2/old graph authority was restored,
- `session.replan_context` became authoritative graph state.
