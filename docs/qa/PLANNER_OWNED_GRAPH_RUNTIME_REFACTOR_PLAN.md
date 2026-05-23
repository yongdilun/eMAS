# Planner-Owned Graph Runtime Refactor Plan

## Status

Separate active-runtime maintainability plan. This plan starts after the planner-owned graph migration and legacy cleanup release proof.

Tracker:

```text
docs/qa/PLANNER_OWNED_GRAPH_RUNTIME_REFACTOR_TRACK.md
```

Baseline commit at plan creation:

```text
068594b16ba87e904f33680f695f03582f1257b0
```

## Why This Is Separate

The legacy cleanup lane removed old authority. This plan refactors the active planner-owned graph runtime.

That distinction matters:

- Legacy cleanup removes dead or historical code.
- This refactor changes the internal shape of live runtime code.
- A failure here can affect chat execution, approvals, interruptions, evidence, response documents, or checkpoint resume.

The target is not less code at all costs. The target is more **depth** and better **locality**: a small stable graph runtime interface with focused modules behind it.

## North Star

`v2_agent_graph.py` should describe graph orchestration.

Specialized modules should own the implementation details for:

- planner decision proposal and validation flow,
- tool/RAG execution routing,
- evidence observation and identity,
- satisfaction/finalization handoff,
- approval preview/pause/resume,
- interrupt/revision/stale-work policy,
- checkpoint identity and state persistence helpers,
- response-document projection.

The public runtime interface should stay small:

```text
PlannerOwnedAgentGraph
PlannerOwnedAgentGraphAdapters
PlannerOwnedAgentGraphRunOptions
PlannerOwnedGraphResult
```

Do not split the file by line count. Split only where the new module has a real interface and improves locality.

## Current Runtime Shape

At plan creation, `factory-agent/factory_agent/graph/v2_agent_graph.py` is about 3,302 LOC and contains:

- graph construction and node routing,
- graph run/resume/interrupt entrypoints,
- planner decision proposal recording,
- tool retrieval and tool choice nodes,
- tool/RAG execution node,
- evidence observation node,
- satisfaction/finalize/response document nodes,
- approval preview and staged-write helpers,
- approval resume helpers,
- interrupt/revision/stale-work helpers,
- checkpoint identity helpers,
- response block/summary projection helpers,
- many graph state lookup helpers.

Existing nearby modules to reuse:

```text
factory-agent/factory_agent/planning/v2_agent_state.py
factory-agent/factory_agent/planning/v2_contracts.py
factory-agent/factory_agent/planning/v2_graph_adapters.py
factory-agent/factory_agent/planning/v2_planner_decisions.py
factory-agent/factory_agent/planning/v2_planner_proposer.py
factory-agent/factory_agent/planning/v2_satisfaction.py
factory-agent/factory_agent/planning/v2_interrupts.py
factory-agent/factory_agent/planning/v2_rag_tool.py
factory-agent/factory_agent/planning/v2_tool_retriever.py
factory-agent/factory_agent/graph/approval_summary.py
factory-agent/factory_agent/graph/checkpointing.py
factory-agent/factory_agent/graph/http_tool_client.py
factory-agent/factory_agent/graph/noop_mutations.py
factory-agent/factory_agent/services/planner_owned_graph_runtime.py
factory-agent/factory_agent/services/response_document_service.py
```

## Non-Negotiable Guardrails

- No product behavior changes unless a test exposes a bug and the fix is in scope.
- No broad rewrite of graph runtime.
- No new planner stack.
- No new ToolSelector/retriever/RAG/approval/response-document/checkpoint stack.
- No exact-prompt runtime branches.
- No seeded-ID or source-ID runtime branches.
- Do not weaken tests to make refactors pass.
- Do not make `session.replan_context` authoritative graph state.
- Do not count offline proposer mode as real release proof.
- Preserve current release gates.
- Keep compatibility helpers from the legacy cleanup lane owned and explicit.

## Refactor Method

Each phase should:

1. Map current responsibilities before moving code.
2. Define the target module interface.
3. Move the smallest coherent helper cluster.
4. Keep behavior identical.
5. Run focused tests and the required gate.
6. Update the tracker with moved symbols, ownership, and remaining seams.

Use the deletion test before extracting:

- If deleting the new module would scatter complexity across many callers, it has depth.
- If deleting the new module just inlines a few wrappers, it is too shallow.

## Phase 0: Runtime Responsibility Audit

Goal: build a responsibility map of `v2_agent_graph.py` before moving code.

Tasks:

- Inventory classes, graph nodes, entrypoints, and helper clusters.
- Classify each cluster as:
  - graph topology/orchestration,
  - planner decision/proposer flow,
  - tool/RAG execution,
  - evidence observation,
  - satisfaction/finalization,
  - approval preview/staging/resume,
  - interrupt/revision/stale-work,
  - checkpoint/state persistence,
  - response-document projection,
  - generic utility,
  - unknown owner.
- Identify current tests that prove each cluster.
- Identify low-risk extraction candidates and high-risk areas.
- Do not move runtime code.

Proof:

- Tracker contains a responsibility map and candidate module list.
- No runtime code changed.
- `git diff --check` passes.

## Phase 1: Checkpoint And State Utility Extraction

Goal: extract low-risk checkpoint/state utility helpers if Phase 0 confirms ownership is clear.

Candidate helpers:

- option normalization,
- checkpoint config/identity helpers,
- state update helpers,
- session context value helpers,
- current checkpoint id helpers.

Do not move graph run/resume entrypoints in this phase.

Required proof:

- Graph run/resume tests still pass.
- Approval resume and interruption tests still pass.

## Phase 2: Approval Preview And Staged Write Module

Goal: move approval preview/staged-write helper implementation behind a focused approval module.

Candidate helpers:

- approval preview normalization,
- preview read execution,
- staged write tool-call construction,
- pending approval response block helpers,
- approval commit args from preview.

Required proof:

- approval resume tests pass,
- API approval tests pass,
- response-document approval E2E passes if visible output changes.

## Phase 3: Interrupt And Revision Policy Module

Goal: move interruption/revision/stale-work helpers to a policy module.

Candidate helpers:

- evidence invalidation after interrupt,
- cancel/close graph state,
- stale background result reason,
- active revision checks,
- interrupt revision trace,
- UI pointer storage.

Required proof:

- graph phase interruption tests pass,
- stale approval/background tests pass,
- full backend passes.

## Phase 4: Tool Choice And Execution Helper Split

Goal: isolate tool choice/tool-call construction helpers while keeping execution through existing adapters.

Candidate helpers:

- deterministic single-document choice guard,
- card selection,
- tool-call construction,
- argument mapping,
- hydrated-card lookups,
- repeated retrieval guard trace.

Do not create a second ToolSelector or executor.

Required proof:

- ToolSelector tests pass,
- graph read/RAG/write tests pass,
- release E2E passes if behavior is visible.

## Phase 5: Evidence And Response Projection Split

Goal: move response block/summary projection and evidence formatting helpers behind a response/evidence projection module.

Candidate helpers:

- response blocks,
- response summary,
- evidence-to-block conversion,
- no-match summaries,
- collection/mutation summaries.

Required proof:

- response-document backend tests pass,
- frontend response-document E2E passes,
- seeded-oracle and release E2E pass if visible output changes.

## Phase 6: Graph File Slimming And Interface Freeze

Goal: make `v2_agent_graph.py` mostly graph topology, nodes, and entrypoints.

Tasks:

- Confirm exported public runtime interface.
- Confirm moved modules have stable ownership.
- Remove obsolete comments/imports.
- Update architecture notes in tracker.

Required proof:

- full backend passes,
- frontend response-document, seeded-oracle, real-LangGraph, and release E2E pass.

## Phase 7: Final Runtime Refactor Release Proof

Goal: prove refactor is behavior-preserving and ready to use as the new baseline.

Required proof:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_graph_no_legacy_authority.py -q
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

If local Qwen/OpenAI-compatible planner config is available, run one smoke trace with offline proposer disabled and record adapter/model/base URL metadata.

## Commit And Update Rules

Each phase must update the tracker with:

- phase verdict,
- files changed,
- symbols moved,
- module ownership changes,
- behavior changes, if any,
- tests run and exact counts,
- whether `git diff --check` passed,
- blockers and owners,
- commit hash when committed.

Do not mark a phase complete if:

- tests were weakened without replacement,
- a new shallow pass-through module was created,
- runtime behavior changed outside scope,
- release-visible output changed without frontend proof,
- exact-prompt/seeded-ID/source-ID branches were added,
- `session.replan_context` became authoritative graph state.

## Standard Final Response Format

Agents implementing this plan must use:

```text
Phase Result
Files Changed
Module Ownership
Tracker Update
Verification
Guardrail Checklist
Open Issues
Next Step
```

If a field is not verified, say `not verified` and explain why.
