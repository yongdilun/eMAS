# Planner-Owned Graph Runtime Refactor Tracker

Status: Phase 0 runtime responsibility audit complete pending commit. This is a separate active-runtime maintainability lane for `PlannerOwnedAgentGraph`, not legacy cleanup. No runtime code, tests, product behavior, planner proposer policy, ToolSelector/RAG/approval/response-document/checkpoint stack, or `session.replan_context` authority changed.

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
| 0 | Runtime responsibility audit | Complete pending commit |  | Docs/tracker only, diff check |
| 1 | Checkpoint and state utility extraction | Not started |  | Graph run/resume/interrupt tests plus full backend |
| 2 | Approval preview and staged write module | Not started |  | Approval/API tests plus full backend |
| 3 | Interrupt and revision policy module | Not started |  | Interrupt/stale-work tests plus full backend |
| 4 | Tool choice and execution helper split | Not started |  | ToolSelector plus graph read/RAG/write tests |
| 5 | Evidence and response projection split | Not started |  | Response-document backend and E2E gates |
| 6 | Graph file slimming and interface freeze | Not started |  | Full backend and frontend E2E release gates |
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
| graph topology/orchestration | `v2_agent_graph.py:67-79` `PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER`; `:296-317` constructor; `:528-556` `_compile_graph`; node methods `:558-1268`; node visit helper `:2157-2166` | `PlannerOwnedAgentGraph` | `tests/test_planner_owned_graph_shell_contract.py:143`, `:161`, `:214`, `:285`; `tests/test_planner_owned_graph_runtime_adapter.py:133`, `:160` | High | Keep in `v2_agent_graph.py`; this is the graph file's core depth. |
| runtime entrypoints/run/resume/interrupt | `v2_agent_graph.py:327-362` `run` / `run_state`; `:364-426` `resume_from_approval`; `:428-526` `interrupt_with_user_message`; `:1583-1600` `_load_checkpoint_state`; service entry adapter in `services/planner_owned_graph_runtime.py:29-82`, `:155-173` | `PlannerOwnedAgentGraph` public runtime plus `PlannerOwnedGraphRuntimeAdapter` persistence adapter | `tests/test_planner_owned_graph_runtime_adapter.py:133`, `:160`, `:218`; `tests/test_planner_owned_graph_approval_resume.py:307`, `:369`; `tests/test_planner_owned_graph_interruptions.py:22`, `:238` | High | Keep entrypoints stable until Phase 6; do not move or rename public runtime symbols in early phases. |
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

Status: complete pending commit.

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

- pending

## Next Handoff Prompt

```text
You are implementing Phase 1 of docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_PLAN.md.

Goal:
Extract low-risk checkpoint/state utility helpers from `factory-agent/factory_agent/graph/v2_agent_graph.py` only if the Phase 0 responsibility map still holds.

Context:
The planner-owned graph migration and legacy cleanup are separate. This plan refactors active runtime code for maintainability. Phase 0 completed the responsibility audit and identified checkpoint/state helpers as the lowest-risk first extraction. Do not change product behavior.

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
- Implement only Phase 1.
- Move only the smallest coherent checkpoint/state helper cluster if it improves depth and locality.
- Do not move graph run/resume/interrupt entrypoints.
- Do not rename symbols.
- Do not change product behavior.
- Do not change tests except imports/references required by the extraction.
- Update the tracker.

Candidate helpers:
- `_normalize_options`
- `_checkpoint_config`
- `_session_context_value`
- `_current_graph_checkpoint_id`
- `_graph_checkpoint_identity`
- `_graph_checkpoint_identity_for_current_revision`
- `_checkpoint_tuple_id`
- `_state_update`

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
- `rg -n "_normalize_options|_checkpoint_config|_session_context_value|_current_graph_checkpoint_id|_graph_checkpoint_identity|_checkpoint_tuple_id|_state_update" factory-agent/factory_agent/graph/v2_agent_graph.py factory-agent/tests`
- `rg -n "resume_from_approval|interrupt_with_user_message|run_state|aupdate_state|aget_tuple|session_replan_context_authoritative" factory-agent/factory_agent/graph/v2_agent_graph.py factory-agent/tests`

Verification:
- `cd factory-agent`
- `python -m pytest tests/test_planner_owned_graph_shell_contract.py tests/test_planner_owned_graph_approval_resume.py tests/test_planner_owned_graph_interruptions.py tests/test_planner_owned_graph_runtime_adapter.py -q`
- `cd ..`
- `git diff --check`
- `git status --short --branch`

Commit only if behavior is unchanged and the focused tests pass.

Suggested commit:
`refactor: extract planner-owned graph checkpoint helpers`

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
