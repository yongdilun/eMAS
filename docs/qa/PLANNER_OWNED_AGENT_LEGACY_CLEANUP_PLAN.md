# Planner-Owned Agent Legacy Cleanup Plan

## Status

Post-release cleanup plan. This plan starts only after the planner-owned graph migration and Phase 12.1 release-harness waiver removal are complete.

The tracker is the source of truth for phase status, commits, candidate disposition, and verification counts:

```text
docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md
```

Baseline release-proof commit at plan creation:

```text
90123304e66282a79c55b62361d4636359a2162a test: align release harness with planner-owned graph
```

## North Star

Normal Factory Agent runtime has one deep orchestration module:

```text
PlannerOwnedAgentGraph
```

The old direct-v2 loop, old graph scaffold, legacy/shadow engine paths, legacy RAG shortcut compatibility, and migration-era tests should be removed when they are no longer active product, API, persisted-data, or release-harness requirements.

The goal is broad cleanup until there are no unowned cleanup candidates left. "Unused" must be proven, not guessed.

## Definition Of Done

The cleanup is done when all of these are true:

- Normal runtime still enters `PlannerOwnedAgentGraph`.
- No normal runtime code imports or calls the historical direct-v2 loop or old graph scaffold.
- No active frontend E2E or backend release proof expects `v2_planner_loop`, `working_intents`, `intent_cursor`, `intent_completed`, `legacy_rag_route`, `v2_shadow`, or direct-v2 execution as current behavior.
- No quarantined test remains unless the tracker records a current compatibility owner and deletion blocker.
- No migration-era test remains merely to prove that an old implementation exists.
- Every deleted test has replacement graph-owned product or architecture coverage.
- Every retained compatibility contract is named as compatibility and isolated from runtime authority.
- Static guard tests fail if old authority is reintroduced.
- Full backend, response-document, seeded-oracle, real-LangGraph, and release E2E gates pass.
- The tracker has an empty "unowned cleanup candidates" list.

## Cleanup Safety Model

Every phase follows this order:

1. Audit references and ownership.
2. Classify each candidate as keep, move, rewrite, quarantine, or delete.
3. Prove replacement coverage before deleting.
4. Delete the smallest coherent candidate set.
5. Run targeted tests, then broad gates when the phase affects runtime or release harnesses.
6. Update the tracker with exact counts and remaining blockers.

Do not delete code because it looks old. Delete it because the audit proves its behavior is now owned by a smaller, deeper module or is no longer required.

## Architecture Rules

Use these terms consistently:

- **Module**: anything with an interface and implementation.
- **Interface**: everything callers must know to use the module.
- **Implementation**: the code inside the module.
- **Depth**: leverage at the interface.
- **Seam**: where an interface lives and behavior can change without editing callers.
- **Adapter**: a concrete implementation at a seam.
- **Leverage**: what callers get from depth.
- **Locality**: what maintainers get from depth.

Cleanup should increase depth and locality:

- Prefer deleting shallow pass-through modules after their behavior is absorbed by a deeper graph/runtime interface.
- Prefer one graph runtime interface over service-level orchestration fragments.
- Prefer one final guard lane over many migration-era tests proving the same guarantee.
- Keep parse/read compatibility behind explicit compatibility modules when persisted historical data still needs it.

## Non-Negotiable Guardrails

- No exact-prompt runtime branches.
- No seeded-ID or source-ID runtime branches.
- No new ToolSelector, retriever, RAG, approval, interrupt, response-document, checkpoint, or planner-runtime stack.
- Do not restore `FACTORY_AGENT_ENGINE=legacy`, `v2_shadow`, old graph cursor/scaffold authority, legacy RAG shortcut authority, or direct-v2 normal runtime authority.
- Do not count offline proposer mode as real release proof.
- Do not weaken tests without graph-owned replacement coverage.
- Do not delete compatibility code required to read persisted sessions/traces unless a migration or compatibility adapter replaces it.
- Do not remove user-visible behavior without release-gate proof.

## Starting Candidate Families

These are starting audit candidates, not pre-approved deletions:

```text
factory-agent/factory_agent/planning/v2_planner_loop.py
factory-agent/factory_agent/services/plan_creation_service.py historical direct-v2 helpers
factory-agent/factory_agent/graph/planner_graph.py
factory-agent/factory_agent/graph/nodes/intent_split.py
factory-agent/factory_agent/graph/nodes/planner_loop.py
factory-agent/factory_agent/graph/state.py working_intents / intent_cursor compatibility
factory-agent/factory_agent/planning/v2_contracts.py legacy/shadow/legacy_rag_route compatibility fields
factory-agent/factory_agent/planning/v2_interrupts.py v2_shadow compatibility handling
factory-agent/tests/test_planner_owned_loop_phase*_*.py migration-era tests
factory-agent/tests/test_phase8_legacy_retirement.py
factory-agent/tests/test_api_endpoints.py legacy_architecture_quarantine tests
eMas Front/e2e/support/hardQueryScenarios.js historical generatedBy expectations
eMas Front/e2e/specs/response-document-hard-query-oracle.spec.js historical generatedBy expectations
```

## Phase 0: Baseline And Cleanup Manifest

Goal: create the cleanup lane without changing product behavior.

Tasks:

- Record the Phase 12.1 release-proof baseline.
- Record the current `HEAD` and pre-edit working tree status.
- Create a cleanup candidate manifest in the tracker.
- Define allowlist categories:
  - active runtime,
  - graph-owned test coverage,
  - persisted-data compatibility,
  - frontend release harness,
  - docs/archive only,
  - deletion candidate,
  - unknown owner.
- Record that Phase 1 is the first audit phase and that no code, runtime, or test deletion is allowed before that audit.
- Add the first handoff prompt for Phase 1.

Proof:

- The tracker records current `HEAD`, baseline release-proof commit, and pre-edit working tree status.
- Pre-edit status has no unrelated runtime, frontend, backend, or test changes. The cleanup plan/tracker docs may be new or modified because Phase 0 creates the lane.
- `git diff --check -- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md` passes.
- Phase 0 marks no candidate as deletion-approved.

## Phase 1: Full Legacy And V2 Usage Audit

Goal: prove what is actually used before deleting anything.

Tasks:

- Build a reference inventory with `rg` and AST/import inspection for:
  - `PlannerOwnedV2Loop`,
  - `_create_direct_v2_plan`,
  - `_execute_direct_v2_steps`,
  - `attach_direct_v2_trace_to_intent_contract`,
  - `v2_planner_loop`,
  - `working_intents`,
  - `intent_cursor`,
  - `intent_completed`,
  - `legacy_rag_route`,
  - `v2_shadow`,
  - `test_only_legacy_engine_enabled`,
  - `legacy_architecture_quarantine`.
- Classify each hit as active runtime, test-only, fixture-only, docs-only, persisted compatibility, or unknown.
- Map every quarantined test to the graph-owned test that replaces its product guarantee.
- Identify any candidate whose owner is unclear and stop before deletion.

Proof:

- Tracker contains an audit table with owner/disposition for every candidate family.
- No runtime changes.
- Targeted static guard tests still pass.

Suggested verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q
cd ..
git diff --check
```

## Phase 2: Direct-V2 Runtime Deletion

Goal: remove historical direct-v2 service execution and `PlannerOwnedV2Loop` if Phase 1 proves graph coverage owns the behavior.

Candidates:

- `factory-agent/factory_agent/planning/v2_planner_loop.py`
- `PlanCreationService._create_direct_v2_plan`
- `PlanCreationService._execute_direct_v2_steps`
- `attach_direct_v2_trace_to_intent_contract`
- tests that instantiate `PlannerOwnedV2Loop` only to prove old behavior

Tasks:

- Rewrite useful remaining direct-v2 tests to call `PlannerOwnedAgentGraph` or the graph runtime adapter.
- Delete tests that only prove the direct-v2 helper exists.
- Remove direct-v2 imports from normal services.
- Delete direct-v2 helper code only after static guards prove normal runtime no longer references it.
- Keep or move only parse compatibility for old persisted traces if Phase 1 proves it is still needed.

Proof:

- No runtime import of `PlannerOwnedV2Loop`.
- No normal runtime callable named `_execute_direct_v2_steps`.
- Graph-owned tests cover read, RAG, write approval, interruption, and proposer-policy behavior.

Suggested verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q
python -m pytest -q
cd "..\eMas Front"
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
npm run test:e2e:release
cd ..
git diff --check
```

## Phase 3: Old Graph Scaffold Deletion

Goal: remove or isolate the historical graph scaffold once it has no active runtime owner.

Candidates:

- `factory-agent/factory_agent/graph/planner_graph.py`
- `factory-agent/factory_agent/graph/planner_graph_helpers.py`
- `factory-agent/factory_agent/graph/nodes/intent_split.py`
- `factory-agent/factory_agent/graph/nodes/planner_loop.py`
- `factory-agent/factory_agent/graph/nodes/validate.py` legacy cursor handling, if unowned
- `factory-agent/factory_agent/graph/state.py` legacy fields, if unowned

Tasks:

- Prove no normal runtime imports the old scaffold.
- Move any still-needed helper behind a graph-owned or compatibility interface.
- Delete old nodes whose only use is historical tests.
- Remove `working_intents`, `intent_cursor`, and `intent_completed` from active tests/fixtures unless they are parse-only compatibility.
- Keep static guard coverage against reintroduction.

Proof:

- No active Python module imports old graph scaffold as runtime authority.
- Old scaffold terms exist only in docs/archive or explicit compatibility tests, or not at all.

Suggested verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q
python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
python -m pytest -q
cd "..\eMas Front"
npm run test:e2e:real-langgraph
npm run test:e2e:release
cd ..
git diff --check
```

## Phase 4: Engine And Trace Compatibility Cleanup

Goal: remove retired engine/shadow concepts from active runtime while preserving any required historical parse compatibility.

Candidates:

- `EngineVersion = Literal["legacy", "v2_shadow", "v2"]`
- `generated_by="v2_planner_loop"` active expectations
- `generated_by="legacy_rag_route"` active expectations
- `v2_shadow_state` handling
- environment/config normalization for retired values

Tasks:

- Decide whether old trace values are still needed to read persisted sessions.
- If needed, move them to an explicit compatibility parser or archive contract.
- Remove retired values from active runtime decisions and release-harness assertions.
- Update frontend hard-query scenarios to expect graph-owned trace identity.
- Keep tests proving old values cannot become runtime authority again.

Proof:

- Active release proof uses planner-owned graph trace identity.
- Retired engine values either do not exist or live only in compatibility code with tests.

Suggested verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_agent_graph_phase1_state.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
python -m pytest -q
cd "..\eMas Front"
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:release
cd ..
git diff --check
```

## Phase 5: Legacy RAG Shortcut Compatibility Cleanup

Goal: remove `legacy_rag_route` as an active contract unless Phase 1 proves persisted historical trace parsing still needs it.

Tasks:

- Audit backend contracts, satisfaction checks, RAG tests, response-document tests, and frontend source rendering for `legacy_rag_route`.
- Replace any active proof with graph RAG tool evidence.
- Keep only explicit historical parse compatibility if needed.
- Delete tests that assert legacy RAG route structure as current behavior.
- Preserve RAG citation, insufficient-context, safety, and source metadata behavior.

Proof:

- RAG answers are represented as graph tool evidence and response-document blocks.
- `legacy_rag_route` cannot satisfy v2/graph requirements.
- Release and response-document E2E pass.

Suggested verification:

```powershell
cd factory-agent
python -m pytest tests/test_rag_*.py tests/test_planner_owned_agent_graph_phase7_rag.py tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
python -m pytest -q
cd "..\eMas Front"
npm run test:e2e:response-document
npm run test:e2e:release
cd ..
git diff --check
```

## Phase 6: Frontend Legacy Expectation Cleanup

Goal: remove frontend scenarios and assertions that still describe old engine identities or old response heuristics as current behavior.

Candidates:

- `eMas Front/e2e/support/hardQueryScenarios.js`
- `eMas Front/e2e/specs/response-document-hard-query-oracle.spec.js`
- any valid-response-document path that still relies on legacy presentation/source/safety chrome

Tasks:

- Replace historical trace labels with graph-owned trace/response-document assertions.
- Remove old flags that only prove legacy behavior is absent if backend static guards already own that proof.
- Keep release scenarios focused on user-visible response-document behavior and graph release evidence.
- Do not weaken semantic oracle coverage.

Proof:

- Frontend E2E checks graph-owned behavior and user-visible response documents, not obsolete trace labels.
- No duplicated legacy renderer assertions remain for valid response-document turns.

Suggested verification:

```powershell
cd "eMas Front"
npm test
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
npm run test:e2e:release
cd ..
git diff --check
```

## Phase 7: Migration Test Suite Consolidation

Goal: reduce test confusion by replacing phase-era scaffolding with stable product and architecture guard suites.

Tasks:

- Classify all `test_planner_owned_loop_phase*_*.py` and `test_planner_owned_agent_graph_phase*_*.py` files as:
  - keep as stable guard,
  - merge into stable guard,
  - rewrite as product behavior test,
  - delete after replacement,
  - archive/quarantine.
- Prefer stable names over phase names for long-term tests, for example:
  - `test_planner_owned_graph_runtime_contract.py`,
  - `test_planner_owned_graph_proposer_policy.py`,
  - `test_planner_owned_graph_approval_interrupts.py`,
  - `test_planner_owned_graph_rag_evidence.py`,
  - `test_planner_owned_graph_no_legacy_authority.py`.
- Remove duplicate assertions that prove the same guarantee through old phase labels.
- Keep final static guard tests compact and readable.

Proof:

- Fewer migration-era test files.
- Product guarantees remain covered.
- Full backend still has no unexpected skips or xfails from this cleanup.

Suggested verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_graph_*.py tests/test_route_to_execution_contract.py tests/test_tool_selector.py -q
python -m pytest -q
cd "..\eMas Front"
npm run test:e2e:response-document
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
npm run test:e2e:release
cd ..
git diff --check
```

## Phase 8: Static Cleanup Enforcement

Goal: prevent legacy/direct-v2 code from drifting back after deletion.

Tasks:

- Add or update static guard tests with a small allowlist file.
- The guard should fail on active-code references to retired terms unless the tracker records a compatibility owner.
- Use AST/import analysis where possible instead of brittle full-repo string scans.
- Keep docs/archive references out of active-code denylist failures.
- Record any remaining allowlist entries and owners in the tracker.

Proof:

- Static cleanup guard catches normal runtime references to retired modules and terms.
- Allowlist is short, named, and owned.

Suggested verification:

```powershell
cd factory-agent
python -m pytest tests/test_planner_owned_graph_no_legacy_authority.py -q
python -m pytest -q
cd ..
git diff --check
```

## Phase 9: Final Cleanup Release Proof

Goal: prove broad cleanup is complete and no unowned candidates remain.

Required proof:

- Cleanup candidate manifest has no unknown owners.
- Unowned cleanup candidates list is empty.
- Static guard allowlist contains only compatibility entries with owners.
- Normal runtime still enters `PlannerOwnedAgentGraph`.
- Local Qwen/OpenAI-compatible proposer proof still works with offline mode disabled.
- Backend full suite passes.
- Frontend unit/support suite passes.
- Response-document, seeded-oracle, real-LangGraph, and release E2E all pass.

Recommended verification:

```powershell
cd factory-agent
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

If local Qwen/OpenAI-compatible planner config is available, also run one opt-in smoke trace with offline proposer disabled and record proposer adapter/model/base URL metadata.

## Commit And Update Rules

Each phase must update the tracker with:

- phase verdict,
- files changed,
- candidate classifications changed,
- tests run,
- exact pass/fail/skip/xfail counts,
- whether `git diff --check` passed,
- remaining cleanup candidates,
- blockers and owners,
- commit hash when committed.

Do not mark a phase complete if:

- normal runtime leaves `PlannerOwnedAgentGraph`,
- old runtime authority is restored,
- a test is deleted without replacement coverage,
- exact-prompt/seeded-ID/source-ID runtime branches are added,
- offline proposer mode is counted as release proof,
- a compatibility need is removed without migration/proof,
- release or seeded/real-LangGraph gates are red without a documented external owner and removal gate.

## Standard Final Response Format

Agents implementing this cleanup must use these sections:

```text
Phase Result
Files Changed
Candidate Disposition
Tracker Update
Verification
Guardrail Checklist
Open Issues
Next Step
```

If a field is not verified, say `not verified` and explain why.
