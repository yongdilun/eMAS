# Planner-Owned Agent Graph Migration Plan

## Status

Active implementation plan. This plan starts after `PLANNER_OWNED_AGENT_LOOP_MIGRATION.md` Phase 15 is complete.

The tracker is the source of truth for current phase status, commits, and verification counts:

```text
docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md
```

This is a new architecture migration. The earlier migration established v2 contracts, evidence, approval safety, response documents, hardcode guardrails, and removed legacy runtime authority. This plan moves the remaining orchestration depth into a real planner-owned LangGraph agent loop.

## North Star

LangGraph owns the agent loop. V2 owns requirements, capability needs, tool retrieval, evidence, approval, validation, and response documents.

This migration is not rollback, not fake v2, and not a trace label change. A request is complete only when the planner graph has:

1. built or revised the requirement ledger,
2. declared the next capability need,
3. retrieved a bounded tool or RAG window,
4. selected an executable action from that window,
5. executed through an authorized adapter,
6. observed evidence,
7. checked satisfaction against locked constraints,
8. continued, requested approval, asked for clarification, failed safely, or finalized.

## Current Gap

The current v2 runtime is useful but still too shallow as an agent module.

Known starting points:

- At graph-migration start, `factory-agent/factory_agent/planning/v2_planner_loop.py` defined `PlannerOwnedV2Loop` for direct-v2 requirement/capability contracts and draft response compatibility. Legacy cleanup Phase 2.3 retired that wrapper; current compatibility lives in `v2_trace_compatibility.py`.
- `factory-agent/factory_agent/services/plan_creation_service.py` still performs direct v2 execution in service-level code through `_create_direct_v2_plan()` and `_execute_direct_v2_steps()`.
- The old `factory-agent/factory_agent/graph/` package still contains historical LangGraph-style concepts such as `working_intents`, `intent_cursor`, and `intent_completed`. Those concepts must not become execution authority again.
- Phase 15 cleanup removed normal runtime authority for `FACTORY_AGENT_ENGINE=legacy`, `v2_shadow`, `test_only_legacy_engine_enabled`, legacy RAG shortcut authority, and legacy/shadow trace attachment branches. Historical values may remain parse-only.
- Baseline note from 2026-05-21: seeded-oracle and real-LangGraph E2E suites were reported green before this graph migration began. Later failures in those lanes should be treated as migration regressions unless the tracker proves an unrelated external cause.

The original gap is that the planner is not yet deciding after each observation. The graph must own planner decisions, tool/RAG execution, evidence observation, approval pauses, resumes, interruptions, final validation, and response document creation.

Post-Phase-10 gap:

- Normal runtime enters `PlannerOwnedAgentGraph`, but the planner-decision nodes still create many decisions through deterministic graph code.
- The decision gate is valuable, but `author = "planner"` must not become a fake-v2 label for decisions that were never proposed by a planner adapter.
- Before legacy cleanup, the graph needs a small, deep planner proposer seam: local Qwen/OpenAI-compatible LLM proposes a `PlannerDecisionSubmission`; deterministic validation decides whether that proposal may authorize graph progress.

Post-Phase-10.5 policy gap:

- The proposer seam exists, but offline structured proposer fallback must not silently stand in for the real planner LLM in production or release proof.
- Offline proposer mode is useful for unit tests, CI contract tests, and explicit local development, but it must be opt-in and visibly traced.
- Release proof must show the local/OpenAI-compatible Qwen planner proposer adapter, not offline contract mode.

## Target Loop

```text
semantic_intake
-> build_requirement_ledger
-> planner_decide_next_action (LLM proposal, deterministic validation)
-> retrieve_tools
-> planner_choose_tool
-> execute_tool_or_rag
-> observe_evidence
-> satisfaction_check
-> planner_continue_or_finalize
-> approval_interrupt when needed
-> response_document
```

The target implementation module is `PlannerOwnedAgentGraph`.

Recommended primary file:

```text
factory-agent/factory_agent/graph/v2_agent_graph.py
```

Supporting contracts and adapters should live near the existing v2 modules unless there is already a better local pattern:

```text
factory-agent/factory_agent/planning/v2_agent_state.py
factory-agent/factory_agent/planning/v2_planner_decisions.py
factory-agent/factory_agent/planning/v2_planner_proposer.py
factory-agent/factory_agent/planning/v2_graph_adapters.py
```

Use existing implementations as leverage:

- Requirement and evidence contracts from `v2_contracts.py`.
- Capability map helpers from `v2_capability_map.py`.
- Tool selection through `V2CapabilityToolRetriever`, which wraps the existing `ToolSelector`.
- RAG through the existing RAG tool path, represented as graph tool evidence.
- Approval staging and resume through the existing approval persistence and response contracts as adapters. The graph checkpoint remains the source of truth for resume state.
- Response documents through existing response-document rendering logic.
- LLM access through the existing OpenAI-compatible model factory in `factory_agent.llm.models`, configured for local Qwen-compatible backends.

Do not build a second ToolSelector, retriever stack, RAG stack, approval system, or response renderer.

## State And Checkpoint Store

The graph state must be a serializable Pydantic v2 contract, not a loose dict copied from the legacy graph.

Primary state contract:

```text
factory-agent/factory_agent/planning/v2_agent_state.py
PlannerOwnedAgentGraphState
```

The state should carry only graph-owned facts and contracts:

- original user query,
- requirement ledger and revision history,
- capability map and capability needs,
- candidate tool windows,
- hydrated tool cards,
- planner decisions,
- selected graph tool calls,
- evidence ledger,
- pending approval checkpoint,
- satisfaction state,
- final validation result,
- response document context,
- execution trace.

Legacy fields such as `working_intents`, `intent_cursor`, and `intent_completed` must not be added to this state as execution authority.

Checkpointing should reuse the existing LangGraph checkpoint infrastructure:

```text
factory-agent/factory_agent/graph/checkpointing.py
build_graph_checkpointer(settings)
SqlAlchemyLangGraphCheckpointSaver
```

Checkpoint backend preference:

1. `GRAPH_CHECKPOINT_BACKEND=postgres` with `GRAPH_CHECKPOINT_POSTGRES_DSN` when explicitly configured and available.
2. Existing database-backed `SqlAlchemyLangGraphCheckpointSaver` using the `workflow_checkpoints` table.
3. Process-local LangGraph `MemorySaver` for local/dev/test fallback.
4. `off` only for flows that cannot require approval/resume. It is not acceptable for graph-owned approval, interruption, or stale-work behavior.

The durable checkpoint row should store LangGraph's native checkpoint payload plus a JSON-safe `agent_state` projection for timeline/snapshot compatibility. Resume must use the native LangGraph checkpoint, not a hand-rebuilt state from `session.replan_context`.

`session.replan_context` may keep lightweight pointers and UI compatibility metadata, such as approval id, checkpoint id, ledger revision, and response-document metadata. It must not become the source of truth for graph execution.

## Architecture Vocabulary

Use this vocabulary consistently in implementation and tests:

- Requirement: what the user is owed.
- Capability need: what ability the planner needs next.
- Tool call: exact executable API or RAG invocation.
- Evidence: what has been proven by a tool, RAG result, approval, or deterministic validator.
- Response document: the user-visible rendering of proven evidence and safe failures.
- Planner decision: a persisted decision that authorizes the next transition.
- Guard decision: a deterministic transition allowed by code because the state already proves it.

The `PlannerOwnedAgentGraph` module should expose a small interface and hide a deep implementation.

Suggested public interface:

```text
run(user_message, session_context, options) -> PlannerOwnedGraphResult
resume_from_approval(session_context, approval_decision, options) -> PlannerOwnedGraphResult
interrupt_with_user_message(session_context, new_user_message, options) -> PlannerOwnedGraphResult
```

The implementation may have many nodes and adapters, but normal runtime should not need to know those details.

## No-Cheating Rules

These rules are migration blockers:

- No `working_intents`, `intent_cursor`, or `intent_completed` as execution authority.
- No legacy RAG shortcut.
- No exact-prompt, seeded-ID, source-ID, or entity-specific runtime branch.
- No branch for `M-CNC-01`, `JOB-SEED-*`, OSHA source IDs, hard query IDs, or exact user prompts.
- No broad full OpenAPI schema exposure before the planner declares a capability need.
- No direct API/RAG execution unless a persisted planner decision or deterministic guard decision authorizes it.
- No `execution_trace.generated_by = "v2_planner_loop"` as proof that the real graph loop ran.
- No product-visible behavior regression to make the graph tests pass.
- No new retriever stack when `ToolSelector` and the v2 retriever adapter can be reused.
- No deleting tests until their product guarantee is covered by a graph-owned equivalent.

The graph should get its own trace identity, for example `planner_owned_agent_graph`, added through the contract layer. Historical trace values may remain parse-only.

## LangSmith And Trace Requirements

When tracing is enabled, acceptance requires:

```text
LangSmith parent graph run
-> semantic intake node
-> planner decision node
-> tool retrieval node
-> planner choose/execute node
-> API tool or RAG child call
-> evidence observation node
-> satisfaction node
-> planner continue/finalize node
-> response document node
```

Do not require live LangSmith network access in normal tests. Add a local fake tracer or callback assertion for CI, then document the live verification command for release proof.

Trace records must distinguish:

- planner decision,
- deterministic guard decision,
- tool retrieval,
- hydrated candidate window,
- selected tool or RAG action,
- execution result,
- evidence reference,
- satisfaction result,
- approval checkpoint,
- interruption revision,
- response document result.

## Test Classification

Do not delete broadly. Classify tests first.

| Bucket | Action | Examples |
| --- | --- | --- |
| Current v2 contract tests | Keep | evidence ledger, response document, RAG citation contracts, approval safety, hardcode guardrails |
| Product behavior tests | Keep or port | machine status, job status, low-priority lists, approval previews, stale approval rejection |
| Migration-era direct-v2 tests | Rewrite | tests proving direct `_create_direct_v2_plan()` behavior instead of graph authority |
| Historical legacy tests | Quarantine or delete after replacement | tests requiring `working_intents`, `intent_cursor`, `intent_completed`, or legacy RAG shortcut authority |
| New wanted-loop tests | Add | graph state, planner decisions, node transitions, evidence observation, LangSmith trace shape |

New graph tests should use a clear naming lane:

```text
factory-agent/tests/test_planner_owned_agent_graph_phase*_*.py
```

or a marker:

```text
planner_owned_agent_graph
```

## Verification Command Notes

The verification commands in this plan are written as concise intent. On Windows PowerShell, pytest file globs such as `tests/test_planner_owned_agent_graph_phase*_*.py` may not expand. When that happens, expand them before invoking pytest and record the expanded command in the tracker.

PowerShell example:

```powershell
$phaseTests = Get-ChildItem tests -Filter "test_planner_owned_agent_graph_phase*_*.py" | ForEach-Object { $_.FullName }
python -m pytest @phaseTests -q
```

If a wildcard command reports that no tests ran, do not count it as a pass. Rerun with an explicit file list or PowerShell-expanded list and record the actual count.

## Seeded And Real-LangGraph E2E Gate Schedule

The seeded-oracle and real-LangGraph suites were reported green before this migration began. Use them as regression gates according to phase risk:

| Phase | Seeded-oracle | Real-LangGraph | Gate Meaning |
| --- | --- | --- | --- |
| 1-5 | Optional | Optional | Contract, shell, retrieval, and internal execution work. Runtime is not switched. Run only if a change looks suspicious. |
| 6 | Run targeted or full seeded when feasible | Optional | Read-only product flows and response document behavior become in scope. |
| 7 | Run seeded | Run if RAG/semantic cases changed | RAG becomes graph-owned evidence, so document-answer regressions matter. |
| 8 | Run seeded | Optional or targeted | Write approval, preview, and UI behavior become in scope. |
| 9 | Run seeded | Run real-LangGraph | Interruption, stale work, and stateful graph behavior become in scope. |
| 10 | Mandatory | Mandatory | Normal runtime switches to graph. Both suites are release blockers. |
| 10.5 | Mandatory | Mandatory | LLM planner proposer becomes the source of planner-authored decisions. Both suites are release blockers. |
| 10.6 | Mandatory | Mandatory | Offline proposer fallback policy becomes release-safe. Both suites are release blockers. |
| 11 | Mandatory | Mandatory | Test cleanup can hide wrong behavior. Both suites are release blockers. |
| 12 | Mandatory | Mandatory | Final release proof. Both suites must be green unless a failure is proven external/environmental with owner and removal gate. |

Do not treat seeded-oracle or real-LangGraph failures as inherited debt in this migration. Since they were green at the start, a later failure is a migration regression unless the tracker proves otherwise.

## Phase 1: Graph State And Trace Contracts

Goal: define the serializable state contract for the new graph without switching runtime.

Add or update contracts for:

- `original_query`
- `requirement_ledger`
- `capability_map`
- `candidate_tool_windows`
- `hydrated_tool_cards`
- `planner_decisions`
- `evidence_ledger`
- `pending_approval`
- `satisfaction_state`
- `final_validation_result`
- `response_document_context`
- `revision_history`
- `execution_trace`
- `engine_version`
- graph-generated trace identity, for example `planner_owned_agent_graph`

Likely files:

```text
factory-agent/factory_agent/planning/v2_agent_state.py
factory-agent/factory_agent/planning/v2_contracts.py
factory-agent/tests/test_planner_owned_agent_graph_phase1_state.py
docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md
```

Proof tests:

- A hard multi-step query creates state with requirements and locked constraints before any execution.
- Empty evidence cannot satisfy locked constraints.
- Graph trace identity is distinct from `v2_planner_loop`.
- State serializes and deserializes without losing revision, evidence, candidate-window, or satisfaction fields.

Stop conditions:

- If new state duplicates old `AgentState` fields as execution authority.
- If trace values make old direct-v2 execution look like the graph ran.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py -q
python -m pytest tests/test_planner_owned_loop_phase*_*.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
git diff --check
```

## Phase 2: Planner Decision Interface

Goal: add a strict planner decision schema and validator. No runtime switch.

Allowed decision types:

```text
retrieve_tools
choose_tool
execute_tool
execute_parallel_read_batch
request_approval
revise_requirements
request_clarification
finalize
fail
```

Planner input may include:

- original query,
- requirement ledger,
- locked constraints,
- current evidence summaries,
- capability map,
- current candidate windows,
- hydrated tool cards,
- approval state,
- satisfaction state.

Planner input must not include:

- full OpenAPI catalog,
- hidden seed fixtures,
- unrelated source documents,
- exact prompt matching helpers.

Likely files:

```text
factory-agent/factory_agent/planning/v2_planner_decisions.py
factory-agent/factory_agent/planning/v2_contracts.py
factory-agent/tests/test_planner_owned_agent_graph_phase2_decisions.py
```

Proof tests:

- Reject a planner decision that drops locked constraints.
- Reject choosing a tool outside hydrated candidate windows.
- Reject executing without a selected tool/RAG action.
- Reject finalizing when required evidence is missing.
- Accept a deterministic guard decision only when state proves it.

Stop conditions:

- If the planner can skip required evidence by emitting a final answer.
- If tests depend on exact user prompt text or seeded IDs.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase2_decisions.py -q
python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q
git diff --check
```

## Phase 3: LangGraph Shell

Goal: add the new graph shell and node transitions behind an explicit test/debug entry point. Do not switch normal runtime.

Add:

```text
factory-agent/factory_agent/graph/v2_agent_graph.py
```

Initial nodes:

```text
semantic_intake_node
requirement_ledger_node
planner_decision_node
tool_retrieval_node
planner_choose_tool_node
tool_execution_node
evidence_observation_node
satisfaction_node
approval_node
finalize_node
response_document_node
```

At this phase, execution nodes may be fake adapters for tests, but they must still require planner or guard authorization.

The shell must compile with the same checkpoint seam the runtime will use:

```text
build_graph_checkpointer(settings)
```

Tests may inject `MemorySaver` or a fake checkpointer, but the graph must not invent a bespoke checkpoint format. The graph state type must be `PlannerOwnedAgentGraphState`.

Proof tests:

- A simple read query flows through graph nodes in order.
- The graph writes planner decisions into state.
- The graph does not read from `working_intents`, `intent_cursor`, or `intent_completed`.
- LangSmith callback shape can be asserted with a local fake tracer.
- The compiled graph receives an injected or configured LangGraph checkpointer.

Stop conditions:

- If the new graph reuses the old graph state as execution authority.
- If direct service execution is called from the graph without a planner decision.
- If the graph stores resume state in `session.replan_context` instead of a LangGraph checkpoint.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase2_decisions.py tests/test_planner_owned_agent_graph_phase3_shell.py -q
python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
git diff --check
```

## Phase 4: Retrieval And Tool Choice

Goal: connect graph retrieval to `V2CapabilityToolRetriever` and require planner selection from bounded candidate windows.

Requirements:

- Retrieval happens after a declared capability need.
- Candidate windows stay bounded, currently max 5 per need unless existing contract says otherwise.
- Hydrated cards exist only for selected or allowed candidates.
- RAG appears as a candidate/action type, not as a legacy shortcut.
- Whole-query ToolSelector scoping must not return unrelated broad tool sets.

Likely files:

```text
factory-agent/factory_agent/graph/v2_agent_graph.py
factory-agent/factory_agent/planning/v2_graph_adapters.py
factory-agent/tests/test_planner_owned_agent_graph_phase4_retrieval.py
```

Proof tests:

- Tool retrieval receives capability needs, not exact whole-query branches.
- Planner cannot choose a non-candidate tool.
- RAG candidates are represented as RAG tool actions.
- No new retriever stack is introduced.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
python -m pytest tests/test_tool_selector.py tests/test_planner_owned_loop_phase4_tool_retriever.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
git diff --check
```

## Phase 5: Tool/RAG Execution And Evidence Observation

Goal: move execution behind graph-authorized adapters.

Requirements:

- API tools execute only after a valid planner decision or deterministic guard decision.
- RAG executes as a graph tool action.
- Execution results become typed evidence before satisfaction can pass.
- Errors become safe evidence/failure states, not hidden successful final answers.
- Direct service execution helpers remain untouched until runtime switch, but graph tests must not call them as the primary path.

Likely files:

```text
factory-agent/factory_agent/planning/v2_graph_adapters.py
factory-agent/factory_agent/graph/v2_agent_graph.py
factory-agent/tests/test_planner_owned_agent_graph_phase5_execution_observation.py
```

Proof tests:

- Tool result creates evidence with source, tool call, requirement references, and timestamps.
- RAG result creates citation evidence or explicit insufficient-context evidence.
- Failed tool execution does not satisfy the requirement.
- Repeated retrieval guard is preserved.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
python -m pytest tests/test_planner_owned_loop_phase6_satisfaction.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
git diff --check
```

## Phase 6: Read-Only Product Flows

Goal: pass read-only behavior through the graph while preserving product output.

Required scenarios:

- simple machine status,
- job status,
- multi-ID status,
- filtered jobs with sort, limit, and requested fields,
- mixed machine/job/list query,
- empty-result list query with explicit no-record summary,
- response document blocks that do not duplicate preview/results incorrectly.

Proof tests:

- The query `Show M-CNC-01 status, then show JOB-SEED-001 status, then list the next 3 low priority jobs sorted by deadline.` returns separate machine, job, and list evidence blocks and a summary that reflects all fulfilled requirements, not only the final list requirement.
- A no-low-priority result summarizes that no low-priority jobs were found and does not reuse a stale second-approval summary.
- Tests assert behavior through state/evidence/response document contracts, not exact prompt hardcoding.

Likely files:

```text
factory-agent/tests/test_planner_owned_agent_graph_phase6_read_flows.py
factory-agent/tests/test_response_document_*.py
frontend/e2e/*response-document*.spec.*
```

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
python -m pytest tests/test_response_document*.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q
cd "..\eMas Front"
npm run test:e2e:response-document
cd ..
git diff --check
```

## Phase 7: RAG As A Graph Tool

Goal: remove any remaining need for a legacy RAG shortcut by representing document search and answer drafting as graph-owned tool/evidence flow.

Requirements:

- RAG is selected from a candidate window.
- RAG execution produces citation evidence or insufficient-context evidence.
- Safety notices remain product behavior, not evidence substitutes.
- The graph can represent legacy empty-plan RAG compatibility data without pretending it went through old RAG.

Proof tests:

- LOTO/high-risk procedure query returns citation-backed guidance when evidence proves it.
- If retrieved chunks do not prove the claim, final answer is explicit insufficient context with sources checked.
- Trace says RAG graph tool action, not `legacy_rag_route`.
- No source-ID branches are added.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase7_rag.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
python -m pytest tests/test_response_document*.py tests/test_rag*.py -q
git diff --check
```

## Phase 8: Writes, Approval Pause, And Resume

Goal: make approval a real graph interrupt/checkpoint, not a hidden service restart.

Requirements:

- Write actions stage changes and pause the graph at an approval node.
- Approval payload includes ledger revision and graph checkpoint identity.
- Resume uses the native LangGraph checkpoint and continues from approval evidence.
- `session.replan_context` may store approval/checkpoint pointers for UI compatibility, but not the authoritative graph state.
- Rejection creates rejection evidence and finalizes safely.
- Stale approval cannot commit.
- Blocked jobs remain excluded.

Proof tests:

- A write query stages preview, waits for approval, commits only after approval, and finalizes with approved evidence.
- Multi-step approval query shows first approval as first approval and second approval as second approval.
- If no records match the first operation, the response says so and does not show a stale or future approval card.
- Stale approval from an earlier revision is rejected.
- Approval resume can survive process restart when the configured durable checkpoint backend is not memory-only.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase8_approval_resume.py tests/test_planner_owned_loop_phase7_interrupt_replan.py -q
python -m pytest tests/test_stateful*.py tests/test_approval*.py tests/test_response_document*.py -q
cd "..\eMas Front"
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
cd ..
git diff --check
```

## Phase 9: Interruptions, Revisions, And Stale Work

Goal: user messages during execution revise graph state and invalidate stale work.

Requirements:

- New user message during execution creates a new ledger revision.
- Old evidence can remain historical but cannot satisfy new active requirements unless explicitly carried forward.
- Old approval checkpoints become stale unless revision-compatible.
- Background results from superseded runs are ignored.
- Stale-work checks use graph revision/checkpoint identity, not only `session.replan_context` flags.

Proof tests:

- Interrupt append/modify/replace/cancel paths preserve revision history.
- Stale approval cannot commit after interrupt.
- New intent produces a new trace/revision.
- Pending user message is not left as a passive limitation.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase9_interrupts.py tests/test_planner_owned_loop_phase7_interrupt_replan.py -q
python -m pytest tests/test_stateful*.py tests/test_sse*.py -q
git diff --check
```

## Phase 10: Runtime Switch To Graph

Goal: normal runtime uses `PlannerOwnedAgentGraph` for v2 execution.

Requirements:

- `plan_creation_service.py` normal runtime calls the graph adapter.
- `_create_direct_v2_plan()` becomes a thin graph adapter, a renamed historical helper, or is removed after tests are ported.
- `_execute_direct_v2_steps()` is not used for normal runtime.
- Normal runtime passes a stable graph thread id, usually the session id, into the LangGraph checkpointer.
- Runtime resume reconstructs from the native LangGraph checkpoint, not from a hand-built state in `session.replan_context`.
- Existing frontend behavior is preserved.
- `FACTORY_AGENT_ENGINE=legacy` still resolves according to Phase 15 behavior and does not restore old paths.

Proof tests:

- API test asserts normal plan creation enters the graph path.
- Trace contains graph planner decisions, retrieval calls, evidence refs, validator status, and response document status.
- Static test rejects normal runtime calls to direct execution helpers.
- Product tests for read, RAG, write, approval, interrupt still pass.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
python -m pytest -q
cd "..\eMas Front"
npm test
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
cd ..
git diff --check
```

## Phase 10.5: LLM Planner Decision Proposer

Goal: make planner-authored decisions come from a real planner proposer seam before legacy cleanup.

This phase fixes the post-runtime-switch gap. The graph already owns execution, evidence, checkpointing, approval, and response documents, but planner decisions are still mostly produced by deterministic graph code. Phase 10.5 must introduce the planner proposer module so the graph can use local Qwen/OpenAI-compatible LLM output as a proposal, then rely on the existing deterministic decision gate to accept or reject it.

Target rule:

```text
LLM proposes PlannerDecisionSubmission.
validate_planner_decision() approves or rejects it.
Only accepted decisions can retrieve tools, choose tools, request approval, revise, fail, or finalize.
```

Requirements:

- Add a small, deep `PlannerDecisionProposer` interface near the v2 planning modules.
- Add a local/OpenAI-compatible Qwen adapter that uses existing settings and `build_planner_chat_model(..., json_mode=True)`.
- The proposer receives a bounded graph-state view only: original query, requirement ledger summary, evidence summary, capability map, candidate windows, hydrated cards, pending approval state, and final validation status.
- The proposer must not see the full OpenAPI tool catalog before retrieval has produced bounded candidate windows.
- The graph must call the proposer for judgement decisions such as `retrieve_tools`, `choose_tool`, `request_approval`, `request_clarification`, `revise_requirements`, `fail`, and `finalize` where appropriate.
- Deterministic guards may still authorize mechanical transitions such as executing a previously accepted tool choice or finalizing after passed validation.
- Do not mark a decision as planner-authored unless it came through the proposer seam and records proposer diagnostics.
- Invalid JSON, invalid schema, stale revision, dropped locked constraint, tool outside hydrated window, unsafe approval skip, or finalize-before-validation must fail closed and record diagnostics. It must not fall through into service-level direct execution.
- Keep Qwen/model-specific behavior behind the adapter and config. No exact prompt, seeded-ID, source-ID, or query-specific runtime branches.

Suggested files:

- `factory-agent/factory_agent/planning/v2_planner_proposer.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py`
- `factory-agent/factory_agent/config.py` if a small config flag or model setting is needed
- `factory-agent/tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py`
- existing Phase 10 runtime-switch tests

Proof tests:

- Mocked proposer returns valid `retrieve_tools` and `choose_tool` submissions; graph records accepted planner decisions with proposer diagnostics.
- Mocked proposer returns malformed JSON or invalid schema; graph fails closed with no tool execution.
- Mocked proposer chooses a tool outside the hydrated candidate window; `validate_planner_decision()` rejects it and execution does not run.
- Mocked proposer drops a locked constraint during `revise_requirements`; validation rejects it.
- Mocked proposer tries to finalize without passed final validation; validation rejects it.
- Static guard: `author = "planner"` decisions in graph runtime must be produced through the proposer seam, not hand-built inside graph nodes.
- Existing seeded-oracle and real-LangGraph suites remain green.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py -q
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q
cd "..\eMas Front"
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
cd ..
git diff --check
```

If a live local Qwen endpoint is configured, also run one opt-in smoke test or manual trace against the smallest hard query that requires more than one planner decision. Record the model name, base URL type, and accepted/rejected proposal diagnostics in the tracker. Do not make the phase depend on a cloud model.

## Phase 10.6: Production Planner Proposer Policy

Goal: prevent offline structured proposer fallback from pretending to be the real planner LLM.

Phase 10.5 made the proposer seam real. Phase 10.6 makes the runtime policy honest. The offline proposer may remain as a test/dev adapter, but normal production/release runtime must not silently fall back to offline decisions when local Qwen/OpenAI-compatible planner configuration is missing or broken.

Requirements:

- Add explicit configuration for offline proposer mode, for example `FACTORY_AGENT_ALLOW_OFFLINE_PLANNER_PROPOSER=1`.
- Default release/production behavior must not silently use `OfflineStructuredPlannerDecisionProposer`.
- If no planner LLM endpoint/API key is configured and offline mode is not explicitly allowed, graph planning must fail closed with a clear diagnostic and no tool execution.
- Existing unit tests may inject a proposer directly or enable explicit offline mode; they must not depend on silent runtime fallback.
- Runtime trace must record the proposer adapter and whether it is real LLM mode or offline contract mode.
- Release proof must require `OpenAICompatibleQwenPlannerDecisionProposer` or equivalent local/OpenAI-compatible LLM adapter. Offline mode cannot satisfy the release proof for "real LLM planner decisions."
- The policy belongs at the proposer factory/config seam. Do not scatter environment checks across graph nodes or services.
- Keep no-cloud-dependency tests by using fake local base URLs or injected fake models.

Suggested files:

- `factory-agent/factory_agent/config.py`
- `factory-agent/factory_agent/planning/v2_planner_proposer.py`
- `factory-agent/factory_agent/graph/v2_agent_graph.py` only if trace/fail-closed diagnostics need a small projection change
- `factory-agent/tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py`
- existing Phase 10.5 proposer tests

Proof tests:

- Missing planner LLM config with offline mode disabled fails closed before tool execution.
- Explicit offline flag enables `OfflineStructuredPlannerDecisionProposer` and traces `offline_contract_mode = true`.
- Configured local/OpenAI-compatible planner base URL selects `OpenAICompatibleQwenPlannerDecisionProposer` and traces local/model metadata.
- Release-policy test rejects offline proposer diagnostics as satisfying real LLM planner proof.
- Existing Phase 10.5 proposer tests still pass without weakening the proposer seam.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py tests/test_planner_owned_agent_graph_phase10_5_llm_proposer.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py -q
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q
cd "..\eMas Front"
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
cd ..
git diff --check
```

If a local Qwen endpoint is configured, run one opt-in smoke trace and record the adapter, model name, base URL type, prompt size, proposal validation result, and whether offline mode was disabled.

## Phase 11: Test Cleanup And Legacy Quarantine

Goal: remove or rewrite tests that reward the wrong architecture after graph runtime, planner proposer, and production proposer policy are proven.

This phase is not a product refactor and not a broad deletion pass. It is a cleanup and quarantine pass over tests/helpers that still make the old direct-v2 or legacy graph path look like valid runtime authority.

Rules:

- Start by classifying tests/helpers into keep, rewrite, quarantine, or delete. Record the classification in the tracker.
- Delete only tests whose product guarantee is already covered by graph-owned tests.
- Rewrite migration-era tests when they prove a useful product guarantee but assert the wrong architecture.
- Keep v2 contracts, evidence, response document, approval safety, stale approval, RAG citation, hardcode, and no-legacy guardrails.
- Quarantine historical tests explicitly if they are still useful for parse compatibility.
- Do not loosen tests just to reduce counts.
- Do not remove old helper code merely because it is ugly. Remove or quarantine only when normal runtime and replacement tests prove the graph-owned behavior.

Non-goals:

- no product behavior changes,
- no new planner, retriever, RAG, approval, response-document, or checkpoint stack,
- no Phase 12 release proof work beyond preserving the release gates,
- no exact-prompt, seeded-ID, source-ID, or query-specific cleanup shortcuts.

Likely cleanup targets:

- tests that require direct `_create_direct_v2_plan()` execution,
- tests that treat `PlannerOwnedV2Loop` as the whole agent loop,
- tests that accept `execution_trace.generated_by = "v2_planner_loop"` as enough proof,
- tests that require old graph `working_intents` behavior in normal runtime.
- tests that accept hand-built graph decisions as planner-authored decisions without proposer diagnostics.
- tests that count offline proposer mode as real LLM planner proof.

Proof tests:

- Static guard: normal runtime cannot call direct-v2 execution branch.
- Static guard: old graph package is historical or test-only.
- Static guard: no legacy RAG/scaffold/cursor authority.
- Static guard: no exact prompt or seeded-ID runtime branches.
- Static guard: offline proposer diagnostics cannot count as real LLM planner proof.
- Full backend has no unexpected xfail/skips added for this migration.

Verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
python -m pytest -q
cd "..\eMas Front"
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
cd ..
git diff --check
```

## Phase 12: Release Proof

Goal: prove the migration end to end with backend, frontend, seeded oracle, planner proposer, and trace evidence.

Required proof:

- Focused graph-owned suite passes.
- Full backend passes without new xfail/skips.
- Frontend unit suite passes.
- Response-document Playwright passes.
- Seeded-oracle Playwright passes. Because it was green at migration start, any failure is blocking unless the tracker proves an unrelated external/environment issue with owner and removal gate.
- Real-LangGraph/semantic oracle suite passes. Because it was green at migration start, any failure is blocking unless the tracker proves an unrelated external/environment issue with owner and removal gate.
- LangSmith or fake-tracer proof shows parent graph run plus child LLM/tool/RAG calls.
- Planner-authored decisions in trace include proposer diagnostics and deterministic validation outcome.
- Release trace uses the local/OpenAI-compatible planner proposer adapter, not offline contract mode.

Recommended commands:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
python -m pytest tests/test_route_to_execution_contract.py tests/test_intent_splitter.py tests/test_tool_selector.py tests/test_hardcode*.py -q
python -m pytest -q
cd "..\eMas Front"
npm test
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
npm run test:e2e:release
cd ..
git diff --check
```

Because seeded-oracle and real-LangGraph were reported green at the start of this migration, release cannot hide new failures in those lanes. If seeded-oracle or real-LangGraph failures appear, the tracker must state whether they are:

- fixed in this migration,
- caused by this migration and blocking,
- unrelated external or environment failures with proof,
- reopened product debt with owner and removal gate.

## Final Acceptance Criteria

The migration is complete only when a hard mixed query produces:

```text
LangSmith parent graph
-> intake
-> planner decision
-> retrieve tools
-> planner choose/execute
-> tool/RAG result
-> evidence observation
-> satisfaction
-> planner continue or finalize
-> response document
```

Normal runtime must not need:

- `working_intents`,
- `intent_cursor`,
- `intent_completed`,
- legacy RAG route,
- direct service-level v2 execution,
- exact prompt branches,
- seeded-ID branches,
- fake trace values.

## Implementation Prompt Template

Use this template for each phase.

```text
You are implementing Phase <N> of docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md.

Read first:
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md
- docs/qa/PLANNER_OWNED_AGENT_LOOP_MIGRATION.md
- docs/qa/PLANNER_OWNED_AGENT_LOOP_MIGRATION_TRACK.md

Scope:
- Implement only Phase <N>.
- Update the graph migration tracker with exact files changed, tests run, counts, and blockers.
- Do not switch runtime unless this is Phase 10.
- Do not add or replace the planner proposer seam unless this is Phase 10.5.
- Do not change offline/production proposer policy unless this is Phase 10.6.
- Do not delete legacy/direct tests unless this is Phase 11 and the product behavior is already covered by graph-owned tests.

Maintainability and hardcode rules:
- No exact-prompt runtime branches.
- No seeded-ID runtime branches such as M-CNC-01, JOB-SEED-*, hard query IDs, or source IDs.
- No new retriever, RAG, approval, or response-document stack when existing modules can be adapted.
- Prefer a small, deep interface over shallow orchestration spread across services.
- Keep requirement, capability need, tool call, evidence, and response document separate.
- Use `PlannerOwnedAgentGraphState` as graph state and the existing LangGraph checkpointer seam for checkpoint/resume. Do not make `session.replan_context` authoritative graph state.
- When a bug appears, find the root cause and use existing contracts/adapters. If the fix reveals architecture duplication or leakage, use the improve-codebase-architecture skill before patching.

Verification:
- Run the phase-specific commands from the plan.
- Preserve the green seeded-oracle and real-LangGraph baseline. If either lane fails after this migration starts, classify it in the tracker instead of treating it as inherited debt.
- Run git diff --check.
- Commit only if the required phase gates pass, or if the tracker explicitly documents an unrelated external/environment gate with proof, owner, and removal condition. Seeded-oracle and real-LangGraph failures must not be treated as inherited debt in this migration.

Expected output:
- Summary of implementation.
- Tests run with counts.
- Any blockers or unrelated external/environment failures with proof.
- Commit hash if committed.
```
