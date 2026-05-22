# Planner-Owned Agent Legacy Cleanup Tracker

Status: Phase 4.2 backend direct-v2 compatibility isolation complete. Backend `v2_planner_loop` generated-by / created-by compatibility is now owned by `historical_direct_v2_compatibility.py`; service and graph call sites use named helper functions instead of service-local literals. Persisted old plan/session projection and historical direct-v2 approval payload resume behavior are preserved. Phase 4.1 classified remaining legacy/shadow/direct-v2 trace values as active compatibility schema, persisted historical parse compatibility, frontend fixture/release vocabulary, static guard vocabulary, historical docs only, or later deletion/rewrite candidates with owners. No schema/control values, frontend fixtures, release harness behavior, Qwen/proposer policy, planner-owned graph behavior, old graph authority, or direct-v2 execution authority changed.

Plan:

```text
docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md
```

Baseline release-proof commit:

```text
90123304e66282a79c55b62361d4636359a2162a test: align release harness with planner-owned graph
```

## Progress Table

| Phase | Name | Status | Commit | Required Gate |
| --- | --- | --- | --- | --- |
| 0 | Baseline and cleanup manifest | Complete | `511755adcdd8def8ff4585276b65e9823f3c9a4d` | Docs diff check and recorded baseline |
| 1 | Full legacy and v2 usage audit | Complete | pending final commit hash | Audit table complete, no runtime change |
| 2 | Direct-v2 runtime deletion | Complete | pending final commit hash | Full backend, response-document, seeded, real-LangGraph, release |
| 3 | Old graph scaffold deletion | Phase 3.8 complete; old scaffold deleted and active seams retained | pending final commit hash | Full backend, frontend release |
| 4 | Engine and trace compatibility cleanup | Phase 4.2 complete; backend direct-v2 compatibility literals isolated behind named helper, schema/control values retained | pending final commit hash | Full backend, response-document, seeded, release |
| 5 | Legacy RAG shortcut compatibility cleanup | Not started |  | RAG suites, full backend, response-document, release |
| 6 | Frontend legacy expectation cleanup | Not started |  | Frontend unit, response-document, seeded, real-LangGraph, release |
| 7 | Migration test suite consolidation | Not started |  | Full backend plus all frontend E2E release gates |
| 8 | Static cleanup enforcement | Not started |  | Static guard and full backend |
| 9 | Final cleanup release proof | Not started |  | Full backend, frontend unit, response-document, seeded, real-LangGraph, release |

## Current Baseline

Phase 0 baseline recorded on 2026-05-22:

- Current `HEAD` before Phase 0 doc edits: `90123304e66282a79c55b62361d4636359a2162a`.
- Baseline release-proof commit: `90123304e66282a79c55b62361d4636359a2162a test: align release harness with planner-owned graph`.
- Cleanup plan exists: yes, `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md`.
- Cleanup tracker exists: yes, `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`.
- Pre-edit working tree status:

```text
## main...origin/main [ahead 23]
?? docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md
?? docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md
```

- Baseline verdict: safe to create the documentation lane. The only pre-edit working tree entries were the two cleanup docs; no runtime, test, frontend, backend, release-harness, Qwen/proposer-policy, or graph-runtime changes were present.
- Phase 0 scope verdict: documentation/tracking only. No code, runtime, test behavior, frontend behavior, PlannerOwnedAgentGraph runtime, Qwen/proposer policy, or release harness behavior changed.

Last recorded verification from planner-owned graph Phase 12.1:

- `npm run test:e2e:release -- --grep "scenario 60|scenario 66|scenario 67|SO-017"` -> `4 passed`.
- `npm run test:e2e:release` -> `21 passed`.
- `npm run test:e2e:response-document` -> `30 passed`.
- `npm run test:e2e:seeded-oracles` -> `35 passed`.
- `npm run test:e2e:real-langgraph` -> `3 passed`.
- Planner-owned graph phase pytest glob -> `88 passed`.
- Focused backend guardrails -> `56 passed`.
- Full Factory Agent pytest -> `1025 passed`, `3 skipped`.
- `git diff --check` -> passed with CRLF conversion warnings only.

## Candidate Manifest

Phase 0 candidate manifest present: yes. This starter manifest intentionally classifies every family as audit-before-delete; no item is deletion-approved until Phase 1 proves usage, ownership, and replacement coverage.

Required cleanup families covered:

- direct-v2 loop/runtime helpers,
- old graph scaffold,
- `working_intents` / `intent_cursor` / `intent_completed`,
- `legacy_rag_route`,
- `v2_shadow` / legacy engine trace compatibility,
- migration-era tests,
- `legacy_architecture_quarantine` tests,
- frontend hard-query `generatedBy` and legacy expectation fixtures.

Phase 1 audited table below superseded this starter list for cleanup ownership and deletion blockers. Phase 4.0 retains this starter manifest as historical audit context only; rows that name deleted files are not current deletion blockers.

| Candidate | Starting Evidence | Initial Disposition | Owner Needed |
| --- | --- | --- | --- |
| `factory-agent/factory_agent/planning/v2_planner_loop.py` | Historical `PlannerOwnedV2Loop` direct loop; deleted in Phase 2.3. Remaining mentions are historical docs, static guards, or compatibility trace vocabulary. | Deleted; historical references OK | None |
| `PlanCreationService._create_direct_v2_plan` | Phase 10 static guards prove it should not call historical direct execution as normal runtime. | Audit before delete | Runtime adapter owner |
| `PlanCreationService._execute_direct_v2_steps` | Historical direct execution helper should not own normal runtime. | Audit before delete | Runtime adapter owner |
| `attach_direct_v2_trace_to_intent_contract` | Historical trace adapter for direct-v2. | Audit before delete or move to compatibility | Persisted trace owner |
| `factory-agent/factory_agent/graph/planner_graph.py` | Old graph scaffold with `working_intents` and `intent_cursor`; deleted in Phase 3.8. | Deleted; historical references OK | None |
| `factory-agent/factory_agent/graph/nodes/intent_split.py` | Old intent split node that wrote `working_intents`; deleted in Phase 3.8. | Deleted; historical references OK | None |
| `factory-agent/factory_agent/graph/nodes/planner_loop.py` | Old planner loop that used `intent_completed` and cursor authority; deleted in Phase 3.8. | Deleted; historical references OK | None |
| `factory-agent/factory_agent/graph/state.py` legacy fields | Old `working_intents` and `intent_cursor` state fields; deleted with the old graph scaffold in Phase 3.8. | Deleted; historical references OK | None |
| `EngineVersion` legacy/shadow values | `legacy`, `v2_shadow`, and old generated_by values may still be parse compatibility. | Audit before edit | Trace compatibility owner |
| `legacy_rag_route` contracts | Still appears in contracts/tests as historical insufficient-evidence proof. | Audit before edit | RAG compatibility owner |
| `v2_shadow_state` handling | Old v2 shadow state appears in interruption compatibility helpers. | Audit before edit | Persisted state owner |
| `test_planner_owned_loop_phase*_*.py` | Migration-era tests may duplicate graph-owned coverage or assert old architecture. | Audit, rewrite, or delete | Test coverage owner |
| `legacy_architecture_quarantine` marker uses | Quarantined tests should shrink over cleanup. | Audit and reduce | Test coverage owner |
| Frontend hard-query `generatedBy` fixtures | Hard-query scenarios still contain historical `generatedBy` / `generated_by` values such as `v2_planner_loop`. | Frontend release-harness vocabulary; Phase 4.0 does not rewrite | Frontend oracle owner |
| Frontend legacy expectation fixtures | Response-document hard-query oracle and fallback paths may still encode legacy presentation/source/safety expectations. | Audit before delete | Frontend compatibility owner |

## Unowned Cleanup Candidates

Phase 1 found no candidate that must be classified as `unknown owner`.

```text
none
```

## Allowlist Policy

Allowed retained references after cleanup must be one of:

- docs/archive references,
- persisted historical data parser,
- explicit compatibility test,
- static guard denylist/allowlist,
- user-facing release artifact history.

Every allowlist entry must have:

- owner,
- reason,
- deletion blocker,
- removal gate.

## Phase 0: Baseline And Cleanup Manifest

Status: complete.

Phase 0 verdict:

- Complete as a documentation/tracking baseline only.
- Candidate manifest is present and includes the required cleanup families.
- No candidate is deletion-approved.
- Phase 1 is the first audit phase and must run the full usage/ownership audit before any deletion, rewrite, or behavior change.
- Parse/read compatibility remains separate from runtime authority.

Files changed:

- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition:

- At Phase 0, all manifest entries remained `Audit before delete`, `Audit before edit`, `Audit and replace`, `Audit, rewrite, or delete`, or `Audit and reduce`; later phase sections supersede that starter disposition.
- Unknown or unclear ownership must be recorded as `unknown owner` in Phase 1 instead of guessed.
- No runtime code, tests, frontend fixtures, backend behavior, release harness behavior, PlannerOwnedAgentGraph runtime, or Qwen/proposer policy changed in Phase 0.

Verification:

- `git status --short --branch`:

```text
## main...origin/main [ahead 23]
?? docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md
?? docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md
```

- `git diff --check -- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md` -> passed, no output.
- `git diff --cached --check -- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md` -> passed after staging the two new docs, no output.
- `rg -n "Phase 1|Direct-V2|direct-v2|legacy_rag_route|working_intents|legacy_architecture_quarantine|Definition Of Done" docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md` -> passed, matched the Phase 1 handoff, direct-v2, legacy RAG, old graph state, quarantine, and Definition Of Done entries.

Blockers:

- none

Commit:

- `511755adcdd8def8ff4585276b65e9823f3c9a4d` (`docs: add planner-owned legacy cleanup lane`)

## Phase 1: Full Legacy And V2 Usage Audit

Status: complete.

Phase 1 verdict:

- Complete as an audit/tracker-only phase.
- Current git `HEAD` at Phase 1 start: `511755adcdd8def8ff4585276b65e9823f3c9a4d`.
- Starting working tree status: `## main...origin/main [ahead 24]`.
- No code, tests, frontend fixtures, runtime behavior, release harness behavior, PlannerOwnedAgentGraph runtime, Qwen/proposer policy, or product behavior changed.
- Normal create-plan runtime still enters `_create_direct_v2_plan()` by name, but that method is an active graph adapter that delegates to `_create_planner_owned_graph_v2_plan()` and then `PlannerOwnedGraphRuntimeAdapter.run_plan()`.
- `PlannerOwnedV2Loop` and `attach_direct_v2_trace_to_intent_contract()` are still referenced by active service code through `_context_with_engine_trace()` and historical direct-v2 compatibility code. They are not deletion-approved.
- The old `factory_agent.graph` scaffold is still reachable through active `PlannerService`, `ExecutionService.run_langgraph_session()`, and approval fallback paths. It is not deletion-approved.
- Historical trace/evidence values such as `legacy_rag_route`, `v2_shadow`, `working_intents`, `intent_cursor`, and `intent_completed` still have compatibility/test owners and must remain isolated from graph runtime authority.
- Frontend hard-query fixtures still expect `generatedBy: 'v2_planner_loop'` and legacy detector flags. They are frontend release-harness rewrite candidates, not Phase 1 deletion candidates.
- Phase 1 did not find an `unknown owner` candidate; active owners and blockers are named below.

Files changed:

- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Exact audit commands used:

```powershell
git status --short --branch
git rev-parse HEAD
rg -n "PlannerOwnedV2Loop|_create_direct_v2_plan|_execute_direct_v2_steps|attach_direct_v2_trace_to_intent_contract|v2_planner_loop|working_intents|intent_cursor|intent_completed|legacy_rag_route|v2_shadow|test_only_legacy_engine_enabled|legacy_architecture_quarantine|FACTORY_AGENT_ENGINE|legacyIntentCompletionLoopUsed|legacyRagShortcutUsed" factory-agent docs/qa "eMas Front/e2e"
rg -n "generatedBy: 'v2_planner_loop'|generated_by=.*v2_planner_loop|generated_by=.*legacy_rag_route" factory-agent "eMas Front/e2e"
rg -n "pytestmark = pytest.mark.legacy_architecture_quarantine|@pytest.mark.legacy_architecture_quarantine" factory-agent/tests
rg -n -C 4 "PlannerOwnedV2Loop|attach_direct_v2_trace_to_intent_contract|def _create_direct_v2_plan|def _execute_direct_v2_steps|_create_planner_owned_graph_v2_plan|backend_used=\"v2_planner_loop\"" factory-agent/factory_agent/services/plan_creation_service.py factory-agent/factory_agent/planning/v2_planner_loop.py
rg -n -C 3 "PlannerOwnedGraphRuntimeAdapter|PlannerOwnedAgentGraph|PlannerOwnedV2Loop|_execute_direct_v2_steps|working_intents|intent_cursor|intent_completed|legacy_rag_route|generated_by" factory-agent/factory_agent/services/planner_owned_graph_runtime.py factory-agent/factory_agent/graph/v2_agent_graph.py
rg -n -C 3 "working_intents|intent_cursor|intent_completed|legacy_rag_route|PlannerOwnedV2Loop|_execute_direct_v2_steps|legacy_architecture_quarantine|generated_by" factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py factory-agent/tests/conftest.py
rg -n -C 3 "working_intents|intent_cursor|intent_completed" factory-agent/factory_agent/graph/planner_graph.py factory-agent/factory_agent/graph/nodes/intent_split.py factory-agent/factory_agent/graph/nodes/planner_loop.py factory-agent/factory_agent/graph/state.py
rg -n -C 3 "resolve_factory_agent_engine_for_runtime|FACTORY_AGENT_ENGINE|test_only_legacy_engine_enabled|v2_shadow|legacy" factory-agent/factory_agent factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py factory-agent/tests/test_planner_owned_loop_phase10_legacy_removal.py
rg -n -C 4 "ExecutionGeneratedBy|ExecutionTrace|legacy_rag_route|v2_shadow|v2_planner_loop|working_intents_count|intent_cursor_start|intent_completed_count|LegacyRagRouteMetadata" factory-agent/factory_agent/planning/v2_contracts.py factory-agent/factory_agent/planning/v2_interrupts.py factory-agent/factory_agent/planning/v2_satisfaction.py
rg -n -C 4 "generatedBy: 'v2_planner_loop'|legacyIntentCompletionLoopUsed|legacyRagShortcutUsed|generatedBy|legacy" "eMas Front/e2e/support/hardQueryScenarios.js" "eMas Front/e2e/specs/response-document-hard-query-oracle.spec.js"
rg -n -C 3 "pytestmark = pytest.mark.legacy_architecture_quarantine|@pytest.mark.legacy_architecture_quarantine|PlannerOwnedV2Loop|v2_planner_loop|legacy_rag_route|working_intents|intent_cursor|intent_completed" factory-agent/tests/test_planner_owned_loop_phase5_shadow_engine.py factory-agent/tests/test_planner_owned_loop_phase9_hard_query_release.py factory-agent/tests/test_api_endpoints.py factory-agent/tests/test_planner_owned_loop_phase6_satisfaction.py factory-agent/tests/test_planner_owned_loop_phase7_interrupt_replan.py factory-agent/tests/test_planner_owned_loop_phase2_contracts.py
rg -n "PlannerService|from factory_agent.services.planner_service|services.planner_service|LangGraphPlanner" factory-agent/factory_agent factory-agent/tests docs/qa
rg -n -C 3 "compile_planner_graph|LangGraphPlanner|planner_service|graph.planner_graph|graph.builder" factory-agent/factory_agent/api factory-agent/factory_agent/main.py factory-agent/factory_agent/app.py factory-agent/factory_agent/dependencies.py factory-agent/factory_agent/services factory-agent/tests
rg -n -C 3 "self\._planner|generate_plan|resume_after_approval" factory-agent/factory_agent/services/plan_creation_service.py factory-agent/factory_agent/services/execution_service.py factory-agent/factory_agent/services/approval_resume_service.py
rg -n "_create_historical_direct_v2_plan|_execute_direct_v2_steps\(" factory-agent/factory_agent factory-agent/tests docs/qa
rg -n "_context_with_engine_trace\(" factory-agent/factory_agent factory-agent/tests docs/qa
rg -n "PlannerOwnedV2Loop" factory-agent/factory_agent factory-agent/tests docs/qa "eMas Front/e2e"
rg -n "v2_shadow_state|v2_shadow|test_only_legacy_engine_enabled|FACTORY_AGENT_ENGINE" factory-agent/factory_agent factory-agent/tests docs/qa "eMas Front/e2e"
```

AST/import inspection command used:

```powershell
@'
from __future__ import annotations
import ast
from pathlib import Path

root = Path('factory-agent')
exclude_parts = {'.venv', '__pycache__'}
symbols = {
    'PlannerOwnedV2Loop',
    'attach_direct_v2_trace_to_intent_contract',
    '_create_direct_v2_plan',
    '_create_historical_direct_v2_plan',
    '_execute_direct_v2_steps',
    '_create_planner_owned_graph_v2_plan',
    'compile_planner_graph',
    'LangGraphPlanner',
}
import_hits = []
def_hits = []
call_hits = []
attr_hits = []
parse_errors = []

for path in sorted(root.rglob('*.py')):
    if any(part in exclude_parts for part in path.parts):
        continue
    text = path.read_text(encoding='utf-8-sig')
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        parse_errors.append((str(path), exc.lineno, exc.msg))
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            matched = [name for name in names if name in symbols or (node.module or '').endswith(('v2_planner_loop','planner_graph'))]
            if matched:
                import_hits.append((str(path), node.lineno, node.module, ','.join(names)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in symbols:
            def_hits.append((str(path), node.lineno, type(node).__name__, node.name))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in symbols:
                call_hits.append((str(path), node.lineno, func.id))
            elif isinstance(func, ast.Attribute) and func.attr in symbols:
                attr_hits.append((str(path), node.lineno, func.attr))

print('AST_IMPORT_HITS')
for row in import_hits:
    print(':'.join(map(str, row)))
print('AST_DEFINITION_HITS')
for row in def_hits:
    print(':'.join(map(str, row)))
print('AST_CALL_HITS')
for row in call_hits:
    print(':'.join(map(str, row)))
print('AST_ATTRIBUTE_CALL_HITS')
for row in attr_hits:
    print(':'.join(map(str, row)))
print('AST_PARSE_ERRORS')
for row in parse_errors:
    print(':'.join(map(str, row)))
'@ | python -
```

Audit table:

| Candidate family | Files/symbols found | Classification | Owner | Replacement graph-owned coverage, if known | Recommended disposition | Blocker before deletion |
| --- | --- | --- | --- | --- | --- | --- |
| Normal v2 create-plan entry name | `factory-agent/factory_agent/services/plan_creation_service.py:576` `_create_direct_v2_plan`; `:594` delegates to `_create_planner_owned_graph_v2_plan`; `:661` calls `PlannerOwnedGraphRuntimeAdapter.run_plan`; `:2289` active `create_plan()` call site | active runtime | `PlanCreationService` plus `PlannerOwnedGraphRuntimeAdapter` | `tests/test_planner_owned_agent_graph_phase10_runtime_switch.py`; `tests/test_planner_owned_loop_phase15_legacy_cleanup.py` AST guards | Keep as the compatibility entry name for normal graph runtime in Phase 1. Rename only in a later behavior-preserving phase. | All service/API call sites and tests must be migrated to an explicitly graph-owned name without reintroducing direct-v2 execution. |
| Direct-v2 trace/context adapter | `factory-agent/factory_agent/planning/v2_planner_loop.py:39` `attach_direct_v2_trace_to_intent_contract`; `:53` `PlannerOwnedV2Loop`; `plan_creation_service.py:532` `_context_with_engine_trace`; `:544` `PlannerOwnedV2Loop`; `:550`, `:569` trace attach; active callers include `execution_service.py:110` and `plan_creation_service.py:2306`, `:2333`, `:2354`, `:2373`, `:2434`, `:2454` | active runtime | `PlanCreationService` trace/context compatibility | Graph trace identity in `PlannerOwnedAgentGraphState`; Phase 1 graph-state test rejects `v2_planner_loop` as graph proof; Phase 15 cleanup guard keeps old trace values parse-only | Keep. Later isolate as an explicit compatibility/trace module or replace active call sites with graph trace generation. | Active service call sites must stop requiring `PlannerOwnedV2Loop` for context trace generation, and persisted old traces must remain readable. |
| Historical direct-v2 executor body | `plan_creation_service.py:669` `_create_historical_direct_v2_plan`; `:746` calls `_execute_direct_v2_steps`; `:873` `_execute_direct_v2_steps`; AST found no external call to `_create_historical_direct_v2_plan`; graph tests assert the historical symbol still exists | deletion candidate | `PlanCreationService` historical direct-v2 compatibility | Graph execution/evidence/RAG/approval/interrupt coverage in graph phases 5, 7, 8, 9, 10; Phase 15 AST guard proves normal runtime cannot call it | Phase 2 can investigate removal or quarantine tightening. Do not delete in Phase 1. | Remove or rewrite tests that assert only symbol presence; prove direct-v2 approval/session repair does not require this executor; preserve any needed persisted compatibility. |
| Old graph scaffold runtime | `factory-agent/factory_agent/graph/planner_graph.py:168` `LangGraphPlanner`; `:251`, `:298` `compile_planner_graph`; `factory-agent/factory_agent/graph/state.py:99` `working_intents`; `:100` `intent_cursor`; `graph/nodes/intent_split.py:26` writes `working_intents`; `graph/nodes/planner_loop.py` uses `working_intents`, `intent_cursor`, and `intent_completed`; `planner_service.py:317`, `:451` imports `LangGraphPlanner`; `api/routes.py:61` builds `PlannerService`; `execution_service.py:76` calls `generate_plan`; `approval_resume_service.py:124` fallback calls `resume_after_approval` | active runtime | `PlannerService`, `ExecutionService`, `ApprovalResumeService`, and old `factory_agent.graph` | `PlannerOwnedAgentGraph` graph phases 3 through 12.1 cover graph-owned runtime, but these active service paths are not fully migrated away from the old scaffold | Must not delete yet. Treat old scaffold as active until all live `PlannerService`/execution/approval fallback paths are retired or moved to `PlannerOwnedGraphRuntimeAdapter`. | Migrate `PlannerService.generate_plan()`, `PlannerService.resume_after_approval()`, `ExecutionService.run_langgraph_session()`, and fallback approval resume off `LangGraphPlanner`; prove old graph tests are no longer active product coverage. |
| Old graph scaffold tests and guards | `tests/test_planner_phase3.py`; `tests/test_route_to_execution_contract.py`; `tests/test_planner_service_phase6.py`; `tests/test_langgraph_state_machine_oracles.py`; `tests/test_phase5_final_validator.py`; `tests/test_planner_owned_loop_phase15_legacy_cleanup.py:266` runtime-source denylist | test-only graph guard | Old graph test suite plus Phase 15 static guard | Replacement coverage exists across `test_planner_owned_agent_graph_phase3_shell.py`, phase5 execution observation, phase8 approval resume, phase9 interrupts, phase10 runtime switch | Keep while old scaffold is active. Later rewrite/merge into graph-owned stable guards. | Old graph runtime owner above must be removed first; then each old graph assertion needs a graph-owned equivalent or deletion proof. |
| Legacy/shadow engine normalization | `factory-agent/factory_agent/config.py:399` reads `FACTORY_AGENT_ENGINE` and normalizes; `tests/test_planner_owned_loop_phase10_legacy_removal.py:73`; `tests/test_planner_owned_loop_phase15_legacy_cleanup.py:155` proves `legacy`, `v2_shadow`, and unknown normalize to `v2`; `test_only_legacy_engine_enabled` appears only in guard/doc references | active runtime | Runtime config normalization and Phase 15 guard | Phase 10/15 tests prove legacy/shadow values cannot restore legacy runtime authority | Keep normalization and guards. Later docs/config cleanup may remove old env vocabulary only with release proof. | No legacy/shadow env value may become runtime authority; any removal must preserve clear handling for existing deployments. |
| `v2_contracts` historical trace/evidence values | `factory-agent/factory_agent/planning/v2_contracts.py:8` `EngineVersion = Literal["legacy", "v2_shadow", "v2"]`; `:9-15` historical `ExecutionTraceGeneratedBy`; `:67` `legacy_rag_route`; `:131-159` legacy detector models; `:432` `LegacyRagRouteMetadata`; `:454-465` legacy RAG evidence validation | persisted-data compatibility | V2 trace/evidence contract owner | Phase 1 graph-state tests and Phase 15 cleanup tests prove old traces parse but cannot satisfy graph/v2 proof | Keep as explicit compatibility for historical sessions/traces. Later move to a compatibility parser only if that reduces runtime contract surface safely. | Need persisted-data migration or compatibility adapter; old values must stay rejected as runtime authority and satisfaction proof. |
| `v2_interrupts` shadow-state handling | `factory-agent/factory_agent/planning/v2_interrupts.py:150`, `:203`, `:564` handle `v2_shadow_state` alongside `v2_state` | persisted-data compatibility | V2 interrupt/revision compatibility | Graph approval/resume and interruption coverage in phases 8 and 9 | Keep until old persisted `v2_shadow_state` sessions are migrated or declared unsupported with proof. | Must prove no persisted sessions still need `v2_shadow_state` read/update compatibility. |
| `legacy_rag_route` final-validation guard | `factory-agent/factory_agent/planning/v2_satisfaction.py:1311` rejects satisfied requirements backed by `legacy_rag_route`; `tests/test_planner_owned_loop_phase15_legacy_cleanup.py:338`; `tests/test_planner_owned_loop_phase6_satisfaction.py:447`; `tests/test_planner_owned_loop_phase2_contracts.py:91`, `:443` | persisted-data compatibility | V2 final validator and contract tests | Graph RAG coverage in `tests/test_planner_owned_agent_graph_phase7_rag.py` and phase10 runtime switch | Keep. It prevents old persisted RAG shortcut evidence from becoming current satisfaction proof. | Only remove after old trace/evidence migration and replacement graph RAG evidence checks prove the same rejection. |
| Quarantined direct-v2/historical tests | `tests/test_planner_owned_loop_phase5_shadow_engine.py:14`; `tests/test_planner_owned_loop_phase9_hard_query_release.py:22`; `tests/test_api_endpoints.py:510`; quarantine marker registered in `tests/conftest.py:30`; marker guard in `tests/test_planner_owned_loop_phase15_legacy_cleanup.py:85`, `:202-238` | quarantined historical test | Compatibility quarantine owner | Graph phases 5, 6, 7, 8, 9, 10, 10.5, 10.6 plus release-harness proof | Keep quarantined in Phase 1. Phase 2/7 may rewrite or delete only after assertion-level mapping. | Every retained product guarantee needs graph-owned coverage; old direct-loop existence assertions must be removed or replaced. |
| Non-quarantined direct-loop contract tests | `tests/test_planner_owned_loop_phase6_satisfaction.py` imports/calls `PlannerOwnedV2Loop`; `tests/test_planner_owned_loop_phase7_interrupt_replan.py` imports/calls `PlannerOwnedV2Loop` | rewrite candidate | V2 satisfaction and interrupt contract test owner | Graph phases 6, 8, 9 cover many runtime behaviors; v2 contract/helper unit coverage may still be useful below the graph interface | Rewrite later toward contract helpers or graph-owned state tests. Do not delete yet. | Identify which assertions are pure contract/helper proof versus old direct-loop runtime proof; preserve final-validator and interrupt compatibility coverage. |
| Frontend hard-query old generated-by expectations | `eMas Front/e2e/support/hardQueryScenarios.js:255`, `:332`, `:373`, `:438`; `eMas Front/e2e/specs/response-document-hard-query-oracle.spec.js:67`; legacy detector flags at support `:258`, `:333`, `:375` and spec `:70`, `:96`, `:103` | frontend release harness | Frontend hard-query oracle/release harness owner | Planner-owned graph release proof in graph tracker Phase 12.1; backend graph trace identity is `planner_owned_agent_graph` | Rewrite in frontend cleanup phase to graph-owned trace/response-document assertions. Do not delete fixture coverage. | Response-document, seeded-oracle, real-LangGraph, and release E2E must pass after rewriting expected generatedBy/legacy flags. |
| Fixture-only frontend/backend historical strings | Frontend expected objects contain old `generatedBy`; test fixtures and direct assertions contain `legacyRagShortcutUsed`, `legacyIntentCompletionLoopUsed`, and historical generated_by values | fixture-only | Fixture/test-data owners | Replacement depends on graph-owned runtime and frontend oracle rewrites | Keep until rewritten. Do not count fixture strings as runtime authority. | Fixture updates need release-harness proof and must not weaken semantic oracle checks. |
| Docs and archive references | `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION*.md`, `docs/qa/PLANNER_OWNED_AGENT_LOOP_MIGRATION*.md`, cleanup plan/tracker references | docs/archive only | QA/migration documentation | Not applicable | Keep as historical record. Later docs cleanup can move stale claims to archive wording. | Avoid deleting docs evidence needed to explain compatibility decisions until cleanup is complete. |

Unknown-owner candidates:

```text
none
```

Safe Phase 2 candidates:

- No Phase 1 candidate is deletion-approved.
- Safe Phase 2 investigation/rewrite candidates are `_create_historical_direct_v2_plan`, `_execute_direct_v2_steps`, and quarantined direct-v2 tests, but only after proving direct-v2 approval/session repair and persisted trace compatibility do not depend on them.
- Safe Phase 2 tracker work should first split active trace compatibility from historical direct execution so active service call sites no longer depend on `PlannerOwnedV2Loop`.

Candidates that must not be deleted yet:

- `_create_direct_v2_plan()` while it remains the active graph-runtime entry name.
- `_context_with_engine_trace()`, `PlannerOwnedV2Loop`, and `attach_direct_v2_trace_to_intent_contract()` while active services call them for trace/context compatibility.
- `factory_agent.graph.planner_graph`, `graph/builder.py`, `graph/state.py`, `graph/nodes/intent_split.py`, and `graph/nodes/planner_loop.py` while `PlannerService`, `ExecutionService`, or approval fallback paths can reach `LangGraphPlanner`.
- `v2_contracts.py` historical enum/evidence/detector values and `v2_interrupts.py` `v2_shadow_state` compatibility handling.
- `legacy_rag_route` rejection logic in `v2_satisfaction.py`.
- Frontend hard-query fixtures until the frontend release harness is rewritten and proven green.
- Non-quarantined direct-loop contract tests until their contract/helper coverage is rewritten or mapped to graph-owned coverage.

Verification:

- `git diff --check -- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md` -> passed; Git printed the existing LF/CRLF conversion warning for this file, with no whitespace errors.
- `cd factory-agent; python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q` -> `23 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `10 warnings`.

Blockers:

- Old graph scaffold is active runtime through `PlannerService`/`ExecutionService`/approval fallback paths.
- Direct-v2 trace/context generation remains active through `_context_with_engine_trace()`.
- Frontend release-harness fixtures still encode `generatedBy: 'v2_planner_loop'`.
- Non-quarantined direct-loop contract tests still instantiate `PlannerOwnedV2Loop`.

Next phase recommendation:

- Proceed to Phase 2 only as a narrow direct-v2 separation phase: first isolate/replace active trace-context compatibility, then remove or rewrite tests that assert historical direct executor presence, then delete direct executor code only after static guards and persisted compatibility proof pass. Do not start old graph scaffold deletion until its active `PlannerService`/execution/approval fallback owners are migrated.

## Phase 2: Direct-V2 Runtime Deletion

Status: complete.

Phase 2 verdict:

- Complete as a narrow direct-v2 separation cleanup.
- Active trace/context compatibility no longer requires `PlanCreationService` to import `PlannerOwnedV2Loop`.
- Normal create-plan runtime still enters `_create_direct_v2_plan()` by name, and that method still delegates to `_create_planner_owned_graph_v2_plan()` and `PlannerOwnedGraphRuntimeAdapter.run_plan()`.
- `_create_historical_direct_v2_plan()` and `_execute_direct_v2_steps()` were deleted after reference and test proof showed normal runtime, graph runtime, approval/session repair, and persisted trace parsing do not call them.
- Persisted historical trace compatibility remains: `attach_direct_v2_trace_to_intent_contract()` moved to explicit compatibility code and old trace values still parse through `v2_contracts.py`.
- `PlannerOwnedV2Loop` remains for retained direct-loop contract/quarantined tests, but it now delegates trace-state construction to the compatibility helper instead of owning the active service trace seam.
- Old graph scaffold deletion was not touched.
- Frontend hard-query fixtures were not edited.
- Qwen/proposer policy and release harness behavior were not changed.

Files changed:

- `factory-agent/factory_agent/planning/v2_trace_compatibility.py`
- `factory-agent/factory_agent/planning/v2_planner_loop.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase10_runtime_switch.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase3_shell.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase4_retrieval.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase5_execution_observation.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase7_rag.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase8_approval_resume.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase9_interrupts.py`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition:

| Candidate | Phase 2 disposition | Replacement coverage / proof | Remaining blocker |
| --- | --- | --- | --- |
| `_create_direct_v2_plan()` | Kept as active normal-runtime compatibility entry name | Phase 10 runtime switch test and Phase 15 cleanup guard prove it delegates to graph runtime and does not call historical execution | Later behavior-preserving API/name migration only |
| Active trace/context compatibility | Separated into `planning/v2_trace_compatibility.py` | Phase 15 guard proves `plan_creation_service.py` imports the compatibility helper and not `PlannerOwnedV2Loop`; full backend and frontend gates passed | Persisted old trace compatibility still required |
| `attach_direct_v2_trace_to_intent_contract()` | Moved to explicit compatibility module and re-exported from `v2_planner_loop.py` for compatibility | Historical trace parse tests still pass; full backend passed | Later phase may move more historical parse surface out of active contracts |
| `PlannerOwnedV2Loop` | Kept, with smaller implementation delegating compatibility state construction | Retained Phase 5/6/7/9 direct-loop contract tests pass | Non-quarantined contract tests still instantiate it; rewrite later toward helper/graph-owned coverage |
| `_create_historical_direct_v2_plan()` | Deleted | AST guards prove absence from service definitions; graph phase 5/7/8/9 tests now assert absence instead of existence; approval resume uses graph-native resume first and separate direct-v2 approval payload compatibility only | Lower `_direct_v2_*` helper support remains because retained compatibility tests still exercise helper behavior |
| `_execute_direct_v2_steps()` | Deleted | Phase 10 and Phase 15 guards prove normal graph adapter cannot call it; graph phase 3/4/5 tests assert the service method is absent | Lower API/RAG helper methods remain blocked by retained compatibility tests |
| Approval/session repair | Kept separate from deleted executor | `approval_resume_service.py` direct-v2 approval payload compatibility does not call `_create_historical_direct_v2_plan()` or `_execute_direct_v2_steps()`; full backend and release gates passed | Historical approval payload compatibility still active |
| Old graph scaffold | Not touched | Phase 15 guard still excludes graph runtime sources from old scaffold authority; old graph active-owner blocker remains from Phase 1 | Migrate `PlannerService` / `ExecutionService` / approval fallback owners in a later phase |
| Frontend hard-query fixtures | Not touched | Response-document, seeded-oracle, real-LangGraph, and release E2E passed without fixture changes | Rewrite in frontend cleanup phase, not Phase 2 |

Verification:

- `python -m compileall -q factory-agent/factory_agent/planning/v2_trace_compatibility.py factory-agent/factory_agent/planning/v2_planner_loop.py factory-agent/factory_agent/services/plan_creation_service.py` -> passed, no output.
- `cd factory-agent; python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q` -> `24 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `10 warnings`.
- `cd factory-agent; $phaseTests = Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }; python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `cd factory-agent; python -m pytest tests/test_planner_owned_loop_phase5_shadow_engine.py tests/test_planner_owned_loop_phase9_hard_query_release.py tests/test_planner_owned_loop_phase6_satisfaction.py tests/test_planner_owned_loop_phase7_interrupt_replan.py -q` -> `35 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `9 warnings`.
- `cd factory-agent; python -m pytest -q` -> `1026 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1417 warnings`.
- `cd "eMas Front"; npm run test:e2e:response-document` -> `30 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:seeded-oracles` -> `35 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:real-langgraph` -> `3 passed`, `0 failed`.
- `cd "eMas Front"; npm run test:e2e:release` -> `21 passed`, `0 failed`.
- `git diff --check` -> passed with existing LF/CRLF conversion warnings only; no whitespace errors.

Blockers:

- `PlannerOwnedV2Loop` is still used by retained direct-loop contract/quarantined tests.
- Lower `PlanCreationService._direct_v2_*` helper support remains for retained historical helper tests and compatibility proof.
- Historical direct-v2 approval payload resume remains active in `ApprovalResumeService`.
- Old graph scaffold remains active through Phase 1 owners and is not deletion-approved by Phase 2.
- Frontend hard-query `generatedBy: 'v2_planner_loop'` fixture cleanup remains a later frontend/release-harness phase.

Commit:

- Pending in this changeset; final response records whether a commit was created.

Next phase recommendation:

- Do not proceed directly into old graph scaffold deletion without first resolving the Phase 1 active owners. The safest next cleanup is to rewrite retained `PlannerOwnedV2Loop` contract tests toward `v2_trace_compatibility.py`, `v2_satisfaction.py`, and graph-owned state tests, then delete the remaining lower `_direct_v2_*` service helpers only after those tests no longer need them.

## Phase 2 Follow-Up: Direct-Loop Test Dependency Retirement

Status: complete.

Phase result:

- Retained direct-loop contract tests no longer import or instantiate `PlannerOwnedV2Loop`.
- Direct-v2 trace/context and read-draft compatibility now live behind `planning/v2_trace_compatibility.py`.
- `PlannerOwnedV2Loop` remains as a small compatibility wrapper only; visible tests and service runtime no longer depend on it.
- Normal runtime still enters `_create_direct_v2_plan()` by name and still delegates to `PlannerOwnedGraphRuntimeAdapter.run_plan()`.
- Historical direct service execution remains absent: `_create_historical_direct_v2_plan()`, `_execute_direct_v2_steps()`, `_execute_direct_v2_api_step()`, and `_execute_direct_v2_rag_step()` are not defined on `PlanCreationService`.
- No frontend hard-query fixtures, release harness behavior, Qwen/proposer policy, or old graph scaffold code was changed.

Files changed:

- `factory-agent/factory_agent/planning/v2_trace_compatibility.py`
- `factory-agent/factory_agent/planning/v2_planner_loop.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/tests/test_planner_owned_loop_phase5_shadow_engine.py`
- `factory-agent/tests/test_planner_owned_loop_phase6_satisfaction.py`
- `factory-agent/tests/test_planner_owned_loop_phase7_interrupt_replan.py`
- `factory-agent/tests/test_planner_owned_loop_phase9_hard_query_release.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase4_retrieval.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase5_execution_observation.py`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Assertion-level test disposition:

| Test | Assertion owner after follow-up | Disposition |
| --- | --- | --- |
| `test_phase5_v2_mode_does_not_create_executable_write_steps` | `v2_trace_compatibility.py` compatibility run/draft | Rewritten from `PlannerOwnedV2Loop` to `build_direct_v2_compatibility_run()`; kept write-dry-run and hydrated-card assertions. |
| `test_phase5_historical_v2_loop_contract_records_v2_generated_by_and_read_draft` | Trace/draft compatibility | Rewritten to compatibility run; retained persisted `generated_by="v2_planner_loop"` trace compatibility and read-draft projection. |
| `test_phase5_v2_path_uses_v2_retriever_and_records_candidate_windows_and_detectors` | Trace/context compatibility | Rewritten to compatibility run; retained v2 retriever, detector, and repeated-retrieval guard assertions. |
| `test_phase5_planner_trace_does_not_receive_full_catalog_before_capability_need` | Trace/context compatibility | Rewritten to compatibility run; retained full-catalog privacy assertion. |
| `test_phase6_v2_contract_three_read_satisfies_typed_evidence_without_completion_calls` | `v2_satisfaction.py` plus compatibility state builder | Rewritten to compatibility run; deterministic satisfaction and final validation assertions preserved. |
| `test_phase6_requested_fields_reject_unrelated_full_object_fields` | Satisfaction/final-validation contract | Rewritten to compatibility run; requested-field blocking preserved. |
| `test_phase6_list_filter_sort_limit_and_fields_produce_proof_records` | Satisfaction contract | Rewritten to compatibility run; filter/sort/limit/requested-fields proof assertions preserved. |
| `test_phase6_missing_evidence_leaves_requirement_open_and_final_validator_fails` | Final-validation contract | Rewritten to compatibility run; missing typed evidence failure preserved. |
| `test_phase6_ambiguous_evidence_blocks_and_returns_to_planner_state` | Satisfaction contract | Rewritten to compatibility run; conflicting deterministic evidence behavior preserved. |
| `test_phase6_write_and_approval_requirements_never_fast_path_to_final_answer` | Satisfaction/approval-state contract | Rewritten to compatibility run; mutation guard and final-validator failure preserved. |
| `test_phase6_rag_satisfaction_requires_v2_typed_source_evidence` | RAG evidence contract | Rewritten to compatibility run; typed source/citation proof preserved. |
| `test_phase6_legacy_rag_shortcut_does_not_satisfy_v2_document_answer` | Persisted compatibility/final-validation contract | Rewritten to compatibility run; legacy RAG shortcut remains parse-only and non-satisfying. |
| `test_phase6_repeated_retrieval_guard_blocks_same_unchanged_capability_need` | Trace/context compatibility | Rewritten to compatibility run; repeated retrieval guard assertion preserved. |
| `test_phase6_final_validator_blocks_dropped_locked_constraints_and_missing_typed_evidence` | Final-validation contract | Rewritten to compatibility run; mutation of state still exercises `validate_v2_final_state()`. |
| `test_phase7_append_interrupt_adds_requirement_ledger_revision` | Interrupt/revision contract | Rewritten to compatibility run; ledger revision assertions preserved. |
| `test_phase7_modify_interrupt_supersedes_old_requirement_and_marks_stale_evidence` | Interrupt/revision contract | Rewritten to compatibility run; stale-evidence marking preserved. |
| `test_phase7_replace_interrupt_preserves_old_state_in_revision_history` | Interrupt/revision contract | Rewritten to compatibility run; prior-ledger snapshot assertion preserved. |
| `test_phase7_cancel_interrupt_invalidates_active_v2_finalization` | Interrupt/final-validation contract | Rewritten to compatibility run; invalidation assertion preserved. |
| `test_phase7_approval_payload_revision_gate_rejects_stale_and_allows_newest` | Approval payload compatibility | Rewritten to compatibility run; revision-gate compatibility preserved. |
| `test_phase7_v2_interrupt_state_revision_preserves_current_draft` | Trace/draft compatibility plus interrupt contract | Rewritten to compatibility run; draft/tool-output compatibility and interrupt actor assertion preserved. |
| `test_phase9_hard_read_query_proves_v2_retrieval_satisfaction_and_conditional_branch` | Trace/draft compatibility plus satisfaction contract | Rewritten to compatibility run; hard-query satisfaction and read-draft projection preserved. |
| `test_phase13_mixed_read_query_keeps_typed_status_and_collection_evidence_without_legacy_completion` | Satisfaction contract plus draft compatibility | Rewritten to compatibility run; typed evidence and projection assertions preserved. |
| `test_phase9_multi_id_status_read_satisfies_typed_rows_without_completion_loop` | Satisfaction contract plus draft compatibility | Rewritten to compatibility run; multi-id row proof and expanded draft args preserved. |
| `test_phase9_historical_direct_v2_aggregates_item_read_evidence_for_multi_id_status` | `v2_evidence_aggregation.py` | Rewritten away from `PlanCreationService._direct_v2_prepare_evidence_for_satisfaction()` to `aggregate_multi_entity_status_evidence()`. |
| `test_phase9_projected_collection_uses_structured_filter_evidence_without_exposing_filtered_field` | Satisfaction/final-validation contract | Rewritten to compatibility run; structured filter proof preserved. |
| `test_phase9_mixed_api_rag_uses_rag_only_for_document_requirement_and_requires_typed_sources` | RAG evidence contract | Rewritten to compatibility run; typed RAG evidence assertions preserved. |
| `test_phase9_write_approval_stages_preview_without_commit_and_interrupt_invalidates_stale_payload` | Draft compatibility plus interrupt/approval compatibility | Rewritten to compatibility run; dry-run write candidate, preview draft, and stale approval invalidation preserved. |
| `test_phase9_tool_failure_fallback_is_typed_and_cannot_finalize_success` | Satisfaction/final-validation contract | Rewritten to compatibility run; typed failure state preserved. |

Tests deleted:

- None. Direct-loop runtime proof was narrowed by changing ownership, not by weakening coverage.

Helper disposition:

| Helper group | Disposition | Replacement coverage / proof |
| --- | --- | --- |
| Direct-v2 compatibility run/draft | Moved to `v2_trace_compatibility.py` | Phase 5/6/7/9 tests now import `build_direct_v2_compatibility_run()`; Phase 15 guard proves `v2_planner_loop.py` no longer owns `_direct_v2_draft`. |
| `PlannerOwnedV2Loop` | Kept as compatibility wrapper | Phase 15 guard proves no visible tests import/instantiate it and `PlanCreationService` still does not import it. Hidden/public API compatibility is the remaining reason not to delete in this phase. |
| Service direct API/RAG executors | Deleted | Graph phase 4/5 tests assert `_execute_direct_v2_api_step()` and `_execute_direct_v2_rag_step()` are absent; Phase 15 guard blocks their return. |
| Service evidence aggregation wrapper | Deleted | Phase 9 test now calls `aggregate_multi_entity_status_evidence()` directly. |
| Service approval payload builder cluster | Deleted | Historical approval payload resume remains owned by `approval_resume_service.py`; Phase 15 guard blocks this cluster from returning to `PlanCreationService`. |
| Service direct RAG response helper | Deleted | No active reference remained; graph-owned RAG tests cover current runtime behavior. |
| Remaining `PlanCreationService` lower helpers | Kept and tracker-blocked | Used only by retained Phase 9 historical helper tests for RAG source-hint query fallback and calendar-week staged row behavior. |

Deleted `PlanCreationService` helpers:

```text
_append_direct_v2_api_evidence
_direct_v2_aggregate_multi_entity_evidence
_direct_v2_approval_payload
_direct_v2_business_change_id
_direct_v2_business_change_label
_direct_v2_business_change_plan
_direct_v2_canonical_output_key
_direct_v2_change_summary
_direct_v2_entity_from_tool
_direct_v2_entity_from_tool_name
_direct_v2_entity_noun
_direct_v2_error_summary
_direct_v2_evidence_has_error
_direct_v2_final_validation_failed
_direct_v2_first_mapping
_direct_v2_has_failed_output
_direct_v2_identity_fields
_direct_v2_is_rag_tool
_direct_v2_llm_call_count
_direct_v2_mutation_requirements
_direct_v2_no_op_mutation_for_requirement
_direct_v2_prepare_evidence_for_satisfaction
_direct_v2_project_api_body
_direct_v2_project_api_row
_direct_v2_requirement
_direct_v2_rows_from_evidence
_direct_v2_schema_entity
_direct_v2_selector_summary
_direct_v2_serialized_business_change
_direct_v2_should_stage_approval
_direct_v2_step_requirement_map
_direct_v2_write_tool_name
_execute_direct_v2_api_step
_execute_direct_v2_rag_step
_maybe_create_direct_v2_rag_response
```

Remaining tracker-blocked `PlanCreationService` direct-v2 helpers:

```text
_direct_v2_current_week_window
_direct_v2_is_source_hint_query
_direct_v2_parse_date
_direct_v2_production_week_window
_direct_v2_rag_execution_query
_direct_v2_row_due_date
_direct_v2_row_matches_date_constraint
_direct_v2_source_priority_constraint
_direct_v2_stage_rows
```

Verification:

- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q` -> `26 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `10 warnings`.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest tests/test_planner_owned_loop_phase5_shadow_engine.py tests/test_planner_owned_loop_phase9_hard_query_release.py tests/test_planner_owned_loop_phase6_satisfaction.py tests/test_planner_owned_loop_phase7_interrupt_replan.py -q` -> `35 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `9 warnings`.
- `python -m pytest -q` -> `1028 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1417 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.
- Frontend release safety commands were not run because this phase did not change active response, trace, release harness, or frontend-visible runtime behavior.

Commit:

- Pending in this changeset; final response records whether a commit was created.

Remaining blockers:

- `PlannerOwnedV2Loop` cannot be deleted yet without an explicit public-compatibility decision; it is no longer a visible test or runtime dependency.
- `PlanCreationService._direct_v2_rag_execution_query()` and `_direct_v2_stage_rows()` remain only for retained historical helper tests. They should move to explicit compatibility ownership or be deleted after replacement coverage is recorded.
- `ApprovalResumeService` still owns historical direct-v2 approval payload resume compatibility.
- Old graph scaffold remains active through the Phase 1 `PlannerService` / `ExecutionService` / approval fallback blockers and was not touched.
- Frontend hard-query `generatedBy: 'v2_planner_loop'` fixtures remain intentionally unchanged.

Next recommended phase:

- Resolve the two remaining `PlanCreationService` helper islands: move RAG source-hint query fallback and staged-row calendar filtering into an explicitly named compatibility owner only if the behavior still matters, otherwise delete them with graph/approval-resume replacement proof. After that, make a deliberate public-compatibility call on deleting `PlannerOwnedV2Loop`.

## Phase 2.2: Remaining Direct-V2 Helper Island Retirement

Status: complete.

Phase result:

- `PlanCreationService._direct_v2_rag_execution_query()` and `_direct_v2_stage_rows()` were removed from service runtime code.
- Historical direct-v2 source-hint query fallback now lives in `planning/v2_trace_compatibility.py` as `resolve_direct_v2_rag_compatibility_query()`.
- Historical approval preview row staging now lives in `approval_resume_service.py` as `stage_direct_v2_approval_compatibility_rows()`, beside the active direct-v2 approval payload compatibility owner.
- `PlannerOwnedV2Loop` is intentionally retained as a documented public compatibility wrapper. Reference inspection found no in-repo service runtime or visible test imports/constructors; hidden/out-of-tree import compatibility is the removal blocker.
- Normal runtime still enters `_create_direct_v2_plan()` by name and delegates to `PlannerOwnedGraphRuntimeAdapter.run_plan()`.
- Historical direct service execution remains absent: `_create_historical_direct_v2_plan()`, `_execute_direct_v2_steps()`, `_execute_direct_v2_api_step()`, and `_execute_direct_v2_rag_step()` are not defined on `PlanCreationService`.
- No old graph scaffold, frontend fixture, release harness, Qwen/proposer policy, or product behavior was changed.

Files changed:

- `factory-agent/factory_agent/planning/v2_trace_compatibility.py`
- `factory-agent/factory_agent/planning/v2_planner_loop.py`
- `factory-agent/factory_agent/services/approval_resume_service.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/tests/test_planner_owned_loop_phase9_hard_query_release.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition:

| Candidate | Disposition | Replacement coverage / proof | Remaining blocker |
| --- | --- | --- | --- |
| `PlanCreationService._direct_v2_rag_execution_query()` | Deleted from `PlanCreationService`; moved behavior to `resolve_direct_v2_rag_compatibility_query()` | Phase 9 historical RAG compatibility test now imports the compatibility helper directly; graph phase 7 owns active RAG runtime behavior | Persisted/source-hint compatibility remains, but not in service runtime |
| `PlanCreationService._direct_v2_is_source_hint_query()` | Deleted from `PlanCreationService`; moved behavior to `is_direct_v2_source_hint_query()` | Phase 9 source-hint fallback test covers the public compatibility resolver | None for service runtime |
| `PlanCreationService._direct_v2_stage_rows()` | Deleted from `PlanCreationService`; moved behavior to `stage_direct_v2_approval_compatibility_rows()` | Phase 9 historical approval preview tests now import the approval compatibility helper directly; graph phase 8 owns active approval resume runtime behavior | Historical direct-v2 approval payload compatibility remains in `ApprovalResumeService` |
| `PlanCreationService._direct_v2_current_week_window()` / `_direct_v2_production_week_window()` / `_direct_v2_row_due_date()` / `_direct_v2_parse_date()` / `_direct_v2_row_matches_date_constraint()` / `_direct_v2_source_priority_constraint()` | Deleted from `PlanCreationService`; useful approval staging behavior moved under approval compatibility helper names | Phase 15 guard proves no `_direct_v2_*` helpers remain on `PlanCreationService` | None for service runtime |
| `PlannerOwnedV2Loop` | Kept intentionally as public compatibility wrapper | Phase 15 guard proves no in-repo runtime imports it and visible tests do not import/instantiate it; wrapper delegates to `build_direct_v2_compatibility_run()` | Hidden/out-of-tree public import compatibility; remove only after explicit public API removal decision |

Static cleanup guards:

- `test_phase11_normal_runtime_cannot_call_historical_direct_v2_execution()` keeps `_create_direct_v2_plan()` and graph adapter calls from importing or calling `PlannerOwnedV2Loop`, `_create_historical_direct_v2_plan()`, or `_execute_direct_v2_steps()`.
- `test_phase2_2_plan_creation_direct_v2_helpers_are_retired()` proves there are no remaining `_direct_v2_*`, `_execute_direct_v2_*`, or `_maybe_create_direct_v2_*` helpers on `PlanCreationService`.
- `test_phase2_2_planner_owned_v2_loop_is_public_compatibility_only()` proves no runtime module outside `v2_planner_loop.py` references `PlannerOwnedV2Loop` and that the wrapper documents its public-compatibility purpose.

Verification:

- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q` -> `27 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `10 warnings`.
- Post-tracker update smoke check: `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `15 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- Post-tracker update smoke check: `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `15 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q` -> PowerShell passed the glob literally, so pytest reported `ERROR: file or directory not found` and `no tests ran`; rerun with an expanded file list below.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest tests/test_planner_owned_loop_phase5_shadow_engine.py tests/test_planner_owned_loop_phase6_satisfaction.py tests/test_planner_owned_loop_phase7_interrupt_replan.py tests/test_planner_owned_loop_phase9_hard_query_release.py -q` -> `35 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `9 warnings`.
- `python -m pytest -q` -> `1029 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1417 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.
- Frontend release safety commands were not run because this phase did not change active response, trace, release harness, or frontend-visible runtime behavior.

Commit:

- Pending in this changeset; final response records whether a commit was created.

Remaining blockers:

- `PlannerOwnedV2Loop` remains only for public compatibility risk. Owner: planning compatibility (`v2_trace_compatibility.py` and `v2_planner_loop.py`). Removal gate: explicit public API removal decision plus static proof that no in-repo runtime, tests, or documented external compatibility lane requires the import.
- `ApprovalResumeService` still owns historical direct-v2 approval payload resume compatibility.
- Old graph scaffold remains active through the Phase 1 `PlannerService` / `ExecutionService` / approval fallback blockers and was not touched.
- Frontend hard-query `generatedBy: 'v2_planner_loop'` fixtures remain intentionally unchanged.

Next recommended phase:

- Keep direct-v2 cleanup focused on the public compatibility decision for `PlannerOwnedV2Loop` and any remaining persisted trace naming policy. Do not start old graph scaffold deletion until the Phase 1 active `PlannerService`, `ExecutionService`, and approval fallback owners are resolved.

## Phase 2.3: PlannerOwnedV2Loop Public Compatibility Decision

Status: complete.

Phase result:

- Reference/export inspection found no real public owner for `PlannerOwnedV2Loop` or `PlannerOwnedV2LoopRun`.
- The historical wrapper module `planning/v2_planner_loop.py` was deleted.
- Direct-v2 trace/context compatibility remains explicitly owned by `planning/v2_trace_compatibility.py`.
- Normal runtime still enters `_create_direct_v2_plan()` by name and delegates to `PlannerOwnedGraphRuntimeAdapter.run_plan()`.
- Historical direct service execution remains absent: `_create_historical_direct_v2_plan()`, `_execute_direct_v2_steps()`, `_execute_direct_v2_api_step()`, and `_execute_direct_v2_rag_step()` are not defined on `PlanCreationService`.
- No old graph scaffold, frontend fixture, release harness, Qwen/proposer policy, or product behavior was changed.

Files changed:

- `factory-agent/factory_agent/planning/v2_planner_loop.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md`
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Reference/export audit:

- `rg -n "PlannerOwnedV2Loop|PlannerOwnedV2LoopRun" factory-agent docs/qa "eMas Front/e2e"` found live code references only in `planning/v2_planner_loop.py` and static cleanup guards before deletion; remaining references are historical docs/tracker records and guard strings.
- `factory-agent/factory_agent/planning/__init__.py` did not export `PlannerOwnedV2Loop` or `PlannerOwnedV2LoopRun`.
- No in-repo runtime module imports `factory_agent.planning.v2_planner_loop`.
- No visible test imports or instantiates `PlannerOwnedV2Loop`; Phase 15 keeps this as a static guard.
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md` and `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md` were updated so current graph-migration docs no longer describe the retired wrapper as present.

Candidate disposition:

| Candidate | Disposition | Replacement coverage / proof | Remaining blocker |
| --- | --- | --- | --- |
| `PlannerOwnedV2Loop` | Deleted | `v2_trace_compatibility.py` owns compatibility state/draft construction; Phase 15 guard proves no runtime or visible test dependency | None found in repo/export/docs audit |
| `PlannerOwnedV2LoopRun` | Deleted | `DirectV2CompatibilityRun` remains the compatibility return object | None found in repo/export/docs audit |
| `planning/v2_planner_loop.py` | Deleted | Static guards now assert the file is absent and that active compatibility helpers are in `v2_trace_compatibility.py` | Historical docs may mention the old name as migration history only |

Static cleanup guards:

- `test_phase2_active_trace_context_compatibility_is_separated_from_direct_loop()` now asserts `planning/v2_planner_loop.py` is absent and compatibility helpers live in `v2_trace_compatibility.py`.
- `test_phase2_3_planner_owned_v2_loop_public_wrapper_is_retired()` proves runtime modules do not reference `PlannerOwnedV2Loop` and the wrapper file remains deleted.
- `test_phase2_followup_tests_use_trace_compatibility_seam_not_planner_owned_loop()` continues to reject visible test imports/constructors.
- `test_phase11_normal_runtime_cannot_call_historical_direct_v2_execution()` continues to reject runtime calls to `PlannerOwnedV2Loop`, `_create_historical_direct_v2_plan()`, and `_execute_direct_v2_steps()`.

Verification:

- `rg -n "PlannerOwnedV2Loop|PlannerOwnedV2LoopRun" factory-agent docs/qa "eMas Front/e2e"` -> passed. No runtime definition, runtime import, package export, visible test import, or visible test instantiation remains; remaining hits are historical docs/tracker records and Phase 15 static guard strings.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q` -> `27 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `10 warnings`.
- `python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q` -> PowerShell passed the glob literally, so pytest reported `ERROR: file or directory not found` and `no tests ran`; rerun with an expanded file list below.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest -q` -> `1029 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1417 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.
- Frontend release safety commands were not run because this phase did not change active response, trace, release harness, or frontend-visible runtime behavior.

Commit:

- Pending in this changeset; final response records whether a commit was created.

Remaining blockers:

- No direct-v2 loop wrapper blocker remains after this phase.
- `_create_direct_v2_plan()` remains the active compatibility entry name for graph runtime and should be renamed only in a separate behavior-preserving API/service phase.
- `ApprovalResumeService` still owns historical direct-v2 approval payload resume compatibility.
- Old graph scaffold remains active through the Phase 1 `PlannerService` / `ExecutionService` / approval fallback blockers and was not touched.
- Frontend hard-query `generatedBy: 'v2_planner_loop'` fixtures remain intentionally unchanged.

Next recommended phase:

- Do not start old graph scaffold deletion until the Phase 1 active `PlannerService`, `ExecutionService`, and approval fallback owners are resolved. The next narrow cleanup can either rename the `_create_direct_v2_plan()` graph-adapter entry name with full caller coverage or begin the old graph scaffold audit/migration lane.

## Phase 2.4: Active Graph Runtime Entry Rename

Status: complete.

Phase result:

- The misleading active runtime entry `PlanCreationService._create_direct_v2_plan()` was removed.
- The active graph runtime implementation is now named `PlanCreationService._create_planner_owned_graph_plan()`.
- The shallow `_create_direct_v2_plan()` -> `_create_planner_owned_graph_v2_plan()` pass-through was removed; callers now enter the graph-owned implementation directly.
- Normal runtime still delegates to `PlannerOwnedGraphRuntimeAdapter.run_plan()`.
- Historical direct service execution remains absent: `_create_historical_direct_v2_plan()`, `_execute_direct_v2_steps()`, `_execute_direct_v2_api_step()`, and `_execute_direct_v2_rag_step()` are not defined on `PlanCreationService`.
- No old graph scaffold, frontend fixture, release harness, Qwen/proposer policy, graph runtime behavior, or product behavior was changed.

Files changed:

- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/tests/test_planner_owned_agent_graph_phase10_runtime_switch.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md`
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition:

| Candidate | Disposition | Replacement coverage / proof | Remaining blocker |
| --- | --- | --- | --- |
| `PlanCreationService._create_direct_v2_plan()` | Deleted | `create_plan()` now calls `_create_planner_owned_graph_plan()` directly; Phase 10 and Phase 15 static guards prove the old method is absent | None |
| `PlanCreationService._create_planner_owned_graph_v2_plan()` | Renamed to `_create_planner_owned_graph_plan()` | Phase 10 behavior test calls the graph-owned entry and still observes `planner_owned_agent_graph` output | None |
| Direct-v2 trace/context compatibility | Kept in `v2_trace_compatibility.py` | Existing trace compatibility tests and Phase 15 guards continue to cover it | Persisted trace compatibility still active |
| Historical direct-v2 approval payload compatibility | Kept in `ApprovalResumeService` | Existing approval resume compatibility remains explicitly owned there | Later phase only if persisted payload compatibility is replaced |

Static cleanup guards:

- `test_phase10_static_normal_runtime_adapter_uses_graph_not_direct_execution()` now asserts `_create_direct_v2_plan()` and `_create_planner_owned_graph_v2_plan()` are absent and `_create_planner_owned_graph_plan()` enters graph runtime.
- `test_phase11_normal_runtime_cannot_call_historical_direct_v2_execution()` now asserts the graph-owned entry exists, calls `run_plan()`, and the old direct-v2 entry names remain absent.
- The Phase 15 helper-retirement guard still proves no `_direct_v2_*`, `_execute_direct_v2_*`, or `_maybe_create_direct_v2_*` helpers exist on `PlanCreationService`.

Verification:

- `rg -n "_create_direct_v2_plan|_create_planner_owned_graph_plan|direct_v2_plan" factory-agent docs/qa "eMas Front/e2e"` -> passed. Active runtime references use `_create_planner_owned_graph_plan()`; remaining `_create_direct_v2_plan` hits are historical docs/tracker records and static guard strings. `direct_v2_plan` still appears in explicitly retained `ApprovalResumeService._resume_direct_v2_planner_approval()` compatibility.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q` -> `27 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `10 warnings`.
- `python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q` -> PowerShell passed the glob literally, so pytest reported `ERROR: file or directory not found` and `no tests ran`; rerun with an expanded file list below.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest -q` -> `1029 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1417 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.
- Frontend release safety commands were not run because this phase did not change active response, trace, release harness, graph runtime behavior, or frontend-visible runtime behavior.

Commit:

- Pending in this changeset; final response records whether a commit was created.

Remaining blockers:

- Direct-v2 normal runtime cleanup lane is closed except for explicitly retained trace/context and approval-payload compatibility.
- `ApprovalResumeService` still owns historical direct-v2 approval payload resume compatibility.
- Old graph scaffold remains active through the Phase 1 `PlannerService` / `ExecutionService` / approval fallback blockers and was not touched.
- Frontend hard-query `generatedBy: 'v2_planner_loop'` fixtures remain intentionally unchanged.

Next recommended phase:

- Begin the old graph scaffold audit/migration lane only after resolving the active `PlannerService`, `ExecutionService`, and approval fallback owners. Do not delete old graph scaffold opportunistically from the direct-v2 cleanup lane.

## Phase 3.0: Old Graph Scaffold Owner Audit

Status: complete; deletion blocked.

Phase result:

- The old graph scaffold was audited after direct-v2 cleanup closed.
- No old graph scaffold runtime code was deleted.
- Normal plan creation still enters `_create_planner_owned_graph_plan()` for non-seeded v2 runtime and delegates to `PlannerOwnedGraphRuntimeAdapter.run_plan()`.
- The old graph scaffold remains active through named owner paths and is not deletion-ready.
- A previously under-recorded helper blocker was captured: `llm/structured_output.py` imports `_normalize_plan_dict()` from `graph/planner_graph_helpers.py`, so that helper module cannot be removed with the state-machine scaffold until structured-output parsing has its own owner.
- No frontend fixtures, release harness behavior, Qwen/proposer policy, or product behavior changed.

Files changed:

- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition:

| Candidate | Disposition | Replacement coverage / proof | Remaining blocker |
| --- | --- | --- | --- |
| `graph/planner_graph.py` / `LangGraphPlanner` | Still blocked | Graph-owned runtime suites cover `PlannerOwnedAgentGraph`, but old service paths still import and adapt `LangGraphPlanner` | `PlannerService.generate_plan()` and `PlannerService.resume_after_approval()` still lazily import `LangGraphPlanner` |
| `graph/builder.py` / `compile_planner_graph()` | Still blocked | Phase 15 guard keeps `compile_planner_graph()` out of graph-owned runtime sources | Still called by `LangGraphPlanner.generate()` and `LangGraphPlanner.resume_after_approval()` |
| `graph/state.py` plus `working_intents` / `intent_cursor` / `intent_completed` | Still blocked | Phase 15 guard proves these do not appear in `PlannerOwnedGraphRuntimeAdapter` or `PlannerOwnedAgentGraph` | Old `LangGraphPlanner` state-machine tests and service owners still use the state scaffold |
| `graph/nodes/intent_split.py`, `graph/nodes/planner_loop.py`, `graph/nodes/validate.py` | Still blocked | Existing quarantine guard keeps them explicitly historical | Reachable through `compile_planner_graph()` while `LangGraphPlanner` remains reachable |
| `graph/planner_graph_helpers.py` | Still blocked, parser split complete | Active helper imports remain inside the old graph scaffold only | structured-output parsing owner resolved; remaining helper users are graph scaffold/runtime quarantine paths |
| `PlanCreationService legacy planner fallback paths` | Still blocked | Normal v2 create-plan runtime uses `_create_planner_owned_graph_plan()` first | Seeded/draft/discovery fallback branches still call `self._planner.generate_plan()` |
| `ExecutionService.run_langgraph_session()` | Still blocked | Normal create-plan runtime is graph-owned, but this execution path remains present | Calls `self._planner.generate_plan()` and persists `backend_used="langgraph"` results |
| `ApprovalResumeService graph approval fallback` | Still blocked | Planner-owned graph approval resume is attempted first | Fallback still calls `self._planner.resume_after_approval()` after direct-v2 compatibility resume declines |

Static cleanup guards:

- `test_phase3_old_graph_scaffold_deletion_blockers_are_explicitly_owned()` records the active blocker owners in both source and tracker so old scaffold deletion cannot proceed by omission.
- `test_phase11_graph_runtime_sources_do_not_use_old_graph_or_legacy_rag_authority()` continues to prove `PlannerOwnedGraphRuntimeAdapter` and `PlannerOwnedAgentGraph` do not import or use `working_intents`, `intent_cursor`, `intent_completed`, `legacy_rag_route`, `compile_planner_graph()`, or `LangGraphPlanner`.
- `test_phase11_normal_runtime_cannot_call_historical_direct_v2_execution()` continues to prove direct-v2 execution remains absent from the graph-owned service entry.

Verification:

- `rg -n "PlannerService\.generate_plan\(\)|PlannerService\.resume_after_approval\(\)|ExecutionService\.run_langgraph_session\(\)|ApprovalResumeService graph approval fallback|PlanCreationService legacy planner fallback paths|llm/structured_output.py parse helper dependency|_normalize_plan_dict|LangGraphPlanner|compile_planner_graph" factory-agent/factory_agent factory-agent/tests docs/qa` -> passed and confirmed the old graph owner/blocker inventory.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `16 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q` -> `28 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `10 warnings`.
- `python -m pytest tests/test_planner_owned_loop_phase5_shadow_engine.py tests/test_planner_owned_loop_phase9_hard_query_release.py tests/test_planner_owned_loop_phase6_satisfaction.py tests/test_planner_owned_loop_phase7_interrupt_replan.py -q` -> `35 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `9 warnings`.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest -q` -> `1030 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1417 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.
- Frontend release safety commands were not run because this phase did not change active response, trace, release harness, graph runtime behavior, or frontend-visible runtime behavior.

Commit:

- Pending in this changeset; final response records whether a commit was created.

Remaining blockers:

- `PlannerService.generate_plan()` and `PlannerService.resume_after_approval()` still own the lazy old graph adapter.
- `ExecutionService.run_langgraph_session()` still calls the injected planner adapter and persists langgraph execution results.
- `ApprovalResumeService graph approval fallback` still calls `resume_after_approval()` after planner-owned graph and direct-v2 compatibility resume paths decline.
- `PlanCreationService legacy planner fallback paths` still call `self._planner.generate_plan()` in seeded/draft/discovery fallback flows.
- `llm/structured_output.py parse helper dependency` is resolved: `_normalize_plan_dict()` now lives in `llm/plan_parsing.py`, and `llm/structured_output.py` no longer imports `graph/planner_graph_helpers.py`.

Next recommended phase:

- Migrate or retire `PlannerService` / `ExecutionService` / approval fallback owners before attempting old graph scaffold deletion.

## Phase 3.1 Structured Output Plan Parsing Isolation

Status: Complete in this changeset. Structured-output plan parsing now has a concrete LLM-adjacent owner in `factory-agent/factory_agent/llm/plan_parsing.py`.

Files changed:

- `factory-agent/factory_agent/llm/plan_parsing.py`
- `factory-agent/factory_agent/llm/structured_output.py`
- `factory-agent/factory_agent/graph/nodes/reason.py`
- `factory-agent/factory_agent/graph/planner_graph_helpers.py`
- `factory-agent/tests/test_planner.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition changes:

| Candidate | Current disposition | Evidence | Next owner/blocker |
| --- | --- | --- | --- |
| `llm/structured_output.py parse helper dependency` | Resolved | `structured_output.py` imports `_normalize_plan_dict()` from `llm/plan_parsing.py`; the old graph helper no longer defines it | None |
| `graph/planner_graph_helpers.py` | Still blocked, parser split complete | Remaining imports are old graph scaffold/helper users such as graph nodes and approval summary | Retire or migrate remaining old graph scaffold owners before deletion |
| `PlannerService.generate_plan()` / `resume_after_approval()` | Still blocked | Lazy old graph adapter remains in service boundary | Planner service owner |
| `ExecutionService.run_langgraph_session()` | Still blocked | Execution service still calls injected planner adapter | Execution service owner |
| `ApprovalResumeService graph approval fallback` | Still blocked | Fallback still calls `resume_after_approval()` after planner-owned graph/direct compatibility paths decline | Approval resume owner |
| `PlanCreationService legacy planner fallback paths` | Still blocked | Seeded/draft/discovery fallback branches still call `self._planner.generate_plan()` | Plan creation owner |

Behavior notes:

- `_normalize_plan_dict()` was moved without logic changes.
- `factory_agent.llm.structured_output` no longer imports from `factory_agent.graph.planner_graph_helpers`.
- The graph reason node now imports the same parsing owner directly for schema-failure logging and salvage.
- No old graph scaffold was deleted.
- No PlannerService, ExecutionService, approval fallback, frontend fixture, release harness, Qwen/proposer policy, graph runtime, seeded-ID, source-ID, or exact-prompt behavior was changed.

Verification:

- `rg -n "_normalize_plan_dict|planner_graph_helpers" factory-agent/factory_agent factory-agent/tests docs/qa` -> passed; live `_normalize_plan_dict()` owner is `factory_agent/llm/plan_parsing.py`, `structured_output.py` imports that owner, and remaining `planner_graph_helpers` hits are old graph helper users or historical docs.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `16 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `python -m pytest tests/test_planner.py -k normalize_plan_dict -q` -> `5 passed`, `0 failed`, `37 deselected`, `0 skipped`, `0 xfailed`, `1 warning`.
- `python -m pytest -q` -> `1030 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1417 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.
- Frontend E2E was not run because this phase changed only structured-output parsing locality and did not change response, trace, release-visible, graph runtime, or frontend behavior.

Remaining blockers:

- `PlannerService.generate_plan()` and `PlannerService.resume_after_approval()` still own the lazy old graph adapter.
- `ExecutionService.run_langgraph_session()` still calls the injected planner adapter and persists langgraph execution results.
- `ApprovalResumeService graph approval fallback` still calls `resume_after_approval()` after planner-owned graph and direct-v2 compatibility resume paths decline.
- `PlanCreationService legacy planner fallback paths` still call `self._planner.generate_plan()` in seeded/draft/discovery fallback flows.

Next recommended phase:

- Pick one active old graph owner at a time, starting with the narrowest service fallback that can be retired or rehomed with preserved trace/session compatibility.

## Phase 3.2: PlanCreationService Old Graph Fallback Audit/Retirement

Status: Complete in this changeset. PlanCreationService no longer owns an old graph scaffold fallback path.

Phase result:

- Removed the dead `_promote_discovery_to_execution()` branch from `PlanCreationService`; repository search found no callers outside its definition.
- Removed the now-dead `_create_plan_approval()` support helper that only served the retired discovery-promotion path.
- Moved the remaining seeded planner `generate_plan()` call behind `services/plan_creation_compatibility.py`, an explicit compatibility owner that requires `handles_seeded_intent()` before invoking a seeded adapter.
- Normal v2 create-plan runtime remains `_create_planner_owned_graph_plan()` -> `PlannerOwnedGraphRuntimeAdapter.run_plan()` -> `PlannerOwnedAgentGraph`.
- No `LangGraphPlanner`, old graph nodes, PlannerService, ExecutionService, approval resume fallback, frontend fixture, release harness, Qwen/proposer policy, graph runtime behavior, exact-prompt branch, seeded-ID branch, or source-ID branch changed.

Files changed:

- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/services/plan_creation_compatibility.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition changes:

| Candidate | Current disposition | Evidence | Next owner/blocker |
| --- | --- | --- | --- |
| `PlanCreationService._promote_discovery_to_execution()` | Deleted | Private method had no callers and was the only PlanCreationService discovery-promotion old planner call | None |
| `PlanCreationService._create_plan_approval()` | Deleted | Private helper became unreachable after discovery-promotion deletion | None |
| PlanCreationService seeded planner compatibility adapter | Rehomed | `PlanCreationService` calls `generate_seeded_planner_compatibility_plan()` and no longer calls `self._planner.generate_plan()` directly | Seeded Playwright compatibility adapter only; not an old graph scaffold blocker |
| `PlanCreationService legacy planner fallback paths` | Resolved for old graph scaffold deletion | Phase 15 guard now proves `await self._planner.generate_plan(` is absent from `PlanCreationService` | None |
| `PlannerService.generate_plan()` / `resume_after_approval()` | Still blocked | Lazy old graph adapter remains in service boundary | Planner service owner |
| `ExecutionService.run_langgraph_session()` | Still blocked | Execution service still calls injected planner adapter | Execution service owner |
| `ApprovalResumeService graph approval fallback` | Still blocked | Fallback still calls `resume_after_approval()` after planner-owned graph/direct compatibility paths decline | Approval resume owner |

Static cleanup guards:

- `test_phase3_old_graph_scaffold_deletion_blockers_are_explicitly_owned()` now requires `PlanCreationService` to be free of direct `self._planner.generate_plan()` calls and records the seeded compatibility adapter separately.
- `test_phase2_2_plan_creation_direct_v2_helpers_are_retired()` still proves no `_direct_v2_*`, `_execute_direct_v2_*`, or `_maybe_create_direct_v2_*` helpers remain on `PlanCreationService`.
- Graph-runtime source guards remain unchanged and continue to block `LangGraphPlanner`, `compile_planner_graph()`, `working_intents`, `intent_cursor`, and `intent_completed` from entering `PlannerOwnedGraphRuntimeAdapter` / `PlannerOwnedAgentGraph`.

Verification:

- `python -m py_compile factory-agent/factory_agent/services/plan_creation_service.py factory-agent/factory_agent/services/plan_creation_compatibility.py` -> passed, no output.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `16 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `python -m pytest tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_seeded_scenario_engine.py -q` -> `35 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `5 warnings`.
- `python -m pytest tests/test_api_endpoints.py -q` -> `40 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `814 warnings`.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest -q` -> `1030 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1414 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.

Remaining blockers:

- `PlannerService.generate_plan()` and `PlannerService.resume_after_approval()` still own the lazy old graph adapter.
- `ExecutionService.run_langgraph_session()` still calls the injected planner adapter and persists langgraph execution results.
- `ApprovalResumeService graph approval fallback` still calls `resume_after_approval()` after planner-owned graph and direct-v2 compatibility resume paths decline.

Next recommended phase:

- Pick one of the remaining active service owners, preferably `ExecutionService.run_langgraph_session()` or the PlannerService boundary, and migrate or retire it without changing normal planner-owned graph runtime behavior.

## Phase 3.3: ExecutionService Old Graph Session Owner Audit/Retirement

Phase result:

- `ExecutionService.run_langgraph_session()` retired.
- `/sessions/{session_id}/execute` no longer owns `PlannerService`, `MemoryManager`, `ToolSelector`, or direct old graph planner generation.
- Foreground and background execution triggers now call `PlanCreationService.create_plan()` with an empty server-side `PlanCreateRequest`, preserving the existing planner-owned graph runtime entry and persistence path.
- Normal runtime remains `PlannerOwnedAgentGraph` through `PlanCreationService._create_planner_owned_graph_plan()` and `PlannerOwnedGraphRuntimeAdapter`.
- No `LangGraphPlanner`, old graph nodes, PlannerService boundary, ApprovalResumeService fallback, frontend fixture, release harness, Qwen/proposer policy, graph runtime behavior, exact-prompt branch, seeded-ID branch, or source-ID branch changed.

Files changed:

- `factory-agent/factory_agent/services/execution_service.py`
- `factory-agent/factory_agent/api/routes.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition changes:

| Candidate | Current disposition | Evidence | Next owner/blocker |
| --- | --- | --- | --- |
| ExecutionService.run_langgraph_session() retired | Resolved for old graph scaffold deletion | Method deleted; Phase 15 guard proves `run_langgraph_session` and `await self._planner.generate_plan(` are absent from `execution_service.py` | None |
| `ExecutionService execution trigger` | Rehomed | `ExecutionService._run_planner_owned_session()` delegates to `PlanCreationService.create_plan()` and reloads the session row | Planner-owned graph creation path; not an old graph scaffold blocker |
| `ExecutionService` constructor planner ownership | Removed | `api/routes.py` no longer passes `planner`, `memory_manager`, or `tool_selector` into `ExecutionService` | None |
| `PlannerService.generate_plan()` / `resume_after_approval()` | Still blocked | Lazy old graph adapter remains in service boundary | Planner service owner |
| `ApprovalResumeService graph approval fallback` | Still blocked | Fallback still calls `resume_after_approval()` after planner-owned graph/direct compatibility paths decline | Approval resume owner |

Static cleanup guards:

- `test_phase3_old_graph_scaffold_deletion_blockers_are_explicitly_owned()` now requires `ExecutionService` to be free of `run_langgraph_session` and direct `self._planner.generate_plan()` calls.
- The same guard requires `ExecutionService` to delegate execution generation through `self._plan_service.create_plan()`.
- Graph-runtime source guards remain unchanged and continue to block `LangGraphPlanner`, `compile_planner_graph()`, `working_intents`, `intent_cursor`, and `intent_completed` from entering `PlannerOwnedGraphRuntimeAdapter` / `PlannerOwnedAgentGraph`.

Verification:

- `python -m py_compile factory_agent\services\execution_service.py factory_agent\api\routes.py` -> passed, no output.
- `python -m pytest tests/test_api_endpoints.py::test_write_machine_not_found_skips_approval_without_read_tool_registered tests/test_api_endpoints.py::test_create_plan_persists_plan_and_steps tests/test_api_endpoints.py::test_late_plan_or_execute_after_cancel_does_not_revive_session tests/test_api_endpoints.py::test_execute_expected_version_conflict_returns_409 tests/test_phase8_legacy_retirement.py::test_phase8_execute_endpoint_does_not_fall_back_to_legacy_engine_for_checkpoint_only_graph_session -q` -> `5 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `65 warnings`.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `16 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `python -m pytest tests/test_api_endpoints.py -q` -> `40 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `807 warnings`.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest -q` -> `1030 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1410 warnings`.
- `rg -n "run_langgraph_session|generate_plan|resume_after_approval|LangGraphPlanner|PlannerService|planner_graph|working_intents|intent_cursor|intent_completed" factory-agent/factory_agent/services factory-agent/tests docs/qa` -> passed and confirmed `ExecutionService.run_langgraph_session()` is now tracker/test-only text; remaining active service hits are `PlannerService` and `ApprovalResumeService`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.

Remaining blockers:

- `PlannerService.generate_plan()` and `PlannerService.resume_after_approval()` still own the lazy old graph adapter.
- `ApprovalResumeService graph approval fallback` still calls `resume_after_approval()` after planner-owned graph and direct-v2 compatibility resume paths decline.

Next recommended phase:

- Resolve the PlannerService old graph adapter boundary or ApprovalResumeService graph approval fallback without changing normal planner-owned graph runtime behavior.

## Phase 3.4: ApprovalResumeService Old Graph Fallback Retirement

Phase result:

- `ApprovalResumeService graph approval fallback retired`.
- `ApprovalResumeService` no longer stores or calls the injected planner adapter and no longer calls `PlannerService.resume_after_approval()` after planner-owned/direct-v2 resume handlers decline.
- Planner-owned graph approval resume remains first-class through `_resume_planner_owned_agent_graph_approval()` and `PlanCreationService.resume_planner_owned_graph_approval()`.
- Historical direct-v2 approval payload compatibility remains in `_resume_direct_v2_planner_approval()`.
- Unsupported graph approval payloads now fail closed with session `FAILED`, pending approval context cleared, and a `graph_approval_resume_unsupported_payload` event, rather than silently entering the old graph scaffold.
- No `LangGraphPlanner`, old graph nodes, PlannerService boundary, frontend fixture, release harness, Qwen/proposer policy, graph runtime behavior, exact-prompt branch, seeded-ID branch, or source-ID branch changed.

Files changed:

- `factory-agent/factory_agent/services/approval_resume_service.py`
- `factory-agent/factory_agent/api/routes.py`
- `factory-agent/tests/test_api_endpoints.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition changes:

| Candidate | Current disposition | Evidence | Next owner/blocker |
| --- | --- | --- | --- |
| Planner-owned graph approval resume | Preserved | `ApprovalResumeService._resume_planner_owned_agent_graph_approval()` still handles `kind=graph_write_approval_required` and calls `PlanCreationService.resume_planner_owned_graph_approval()` | Planner-owned graph runtime |
| Historical direct-v2 approval payload compatibility | Preserved | `ApprovalResumeService._resume_direct_v2_planner_approval()` still handles `bundle_ui.kind=v2_planner_owned_approval_preview` and queues follow-up approvals | ApprovalResumeService compatibility owner |
| ApprovalResumeService graph approval fallback retired | Resolved for old graph scaffold deletion | `ApprovalResumeService` has no `self._planner` reference and unsupported graph payloads fail closed instead of calling `resume_after_approval()` | None |
| Unsupported old graph approval payloads | Fail-closed compatibility boundary | API regression proves injected planner `resume_after_approval()` is not called and the session is marked `FAILED` with approval context cleared | None |
| `PlannerService.generate_plan()` / `resume_after_approval()` | Still blocked | Lazy old graph adapter remains in service boundary | Planner service owner |

Static cleanup guards:

- `test_phase3_old_graph_scaffold_deletion_blockers_are_explicitly_owned()` now requires `ApprovalResumeService` to be free of `self._planner`.
- The same guard requires the retired fallback marker, planner-owned graph approval resume handler, and direct-v2 approval compatibility handler to remain explicit.

Verification:

- `python -m py_compile factory_agent\services\approval_resume_service.py factory_agent\api\routes.py` -> passed, no output.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `16 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `python -m pytest tests/test_api_endpoints.py::test_graph_approval_old_graph_fallback_is_retired_and_fails_closed tests/test_api_endpoints.py::test_phase14_historical_approval_payload_resume_queues_second_actionable_approval tests/test_api_endpoints.py::test_planner_owned_graph_background_resume_failure_marks_session_failed -q` -> `3 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `75 warnings`.
- `python -m pytest tests/test_planner_owned_agent_graph_phase8_approval_resume.py tests/test_planner_owned_agent_graph_phase9_interrupts.py -q` -> `19 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `python -m pytest tests/test_api_endpoints.py -q` -> `40 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `798 warnings`.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest -q` -> `1030 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1401 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.

Remaining blockers:

- `PlannerService.generate_plan()` and `PlannerService.resume_after_approval()` still own the lazy old graph adapter.

Next recommended phase:

- Resolve the PlannerService old graph adapter boundary without changing normal planner-owned graph runtime behavior.

## Phase 3.5: PlannerService Old Graph Adapter Boundary Retirement

Phase result:

- `PlannerService old graph adapter boundary retired`.
- Deleted `PlannerService.generate_plan()` and `PlannerService.resume_after_approval()`, including the lazy `_langgraph_planner_cls` / `LangGraphPlanner` construction boundary and retry/error-mapping adapter logic.
- Default API router wiring now passes only an explicitly injected `planner_adapter` into `PlanCreationService`; it no longer constructs `PlannerService` as a live old graph adapter.
- `/approvals/{approval_id}/reject` no longer calls `planner.resume_after_approval(... approved=False)` and instead keeps the existing fail-closed graph approval rejection bookkeeping without entering old graph runtime.
- Seeded planner compatibility remains explicitly owned by `services/plan_creation_compatibility.py`, gated by `handles_seeded_intent()`, and still cannot route through default `PlannerService`.
- Removed the unused test-only `offline_langgraph_planner.py` adapter and PlannerService old-boundary unit tests.
- No `planner_graph.py`, old graph nodes, planner-owned graph runtime behavior, frontend fixtures, release harness, Qwen/proposer policy, approval direct-v2 payload compatibility, exact-prompt branch, seeded-ID branch, or source-ID branch changed.

Files changed:

- `factory-agent/factory_agent/services/planner_service.py`
- `factory-agent/factory_agent/planner.py`
- `factory-agent/factory_agent/api/routes.py`
- `factory-agent/factory_agent/api/routers/approvals.py`
- `factory-agent/tests/conftest.py`
- `factory-agent/tests/test_api_endpoints.py`
- `factory-agent/tests/test_memory_live_llm.py`
- `factory-agent/tests/test_planner.py`
- `factory-agent/tests/test_planner_service_phase6.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`
- `factory-agent/tests/offline_langgraph_planner.py`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`

Candidate disposition changes:

| Candidate | Current disposition | Evidence | Next owner/blocker |
| --- | --- | --- | --- |
| `PlannerService.generate_plan()` | Deleted | Phase 15 guard proves `async def generate_plan(`, `_langgraph_planner_cls`, and `LangGraphPlanner` are absent from `planner_service.py` | None |
| `PlannerService.resume_after_approval()` | Deleted | Phase 15 guard proves `async def resume_after_approval(` is absent from `planner_service.py` | None |
| API default PlannerService construction | Retired | `api/routes.py` passes `planner_adapter` directly into `PlanCreationService` and no longer imports or constructs `PlannerService` | None |
| Route-level graph approval rejection old adapter call | Retired | `api/routers/approvals.py` no longer accepts `planner` and no longer calls `planner.resume_after_approval()` | None |
| PlanCreationService seeded planner compatibility adapter | Preserved | `PlanCreationService` still calls `generate_seeded_planner_compatibility_plan()` only after `handles_seeded_intent()` matches | Seeded Playwright compatibility adapter only |
| Old graph scaffold modules | Product-runtime owner removed; scaffold not deleted | `LangGraphPlanner` and `compile_planner_graph()` remain only in old graph modules and historical tests, not PlannerService/API service owners | Separate old graph scaffold deletion phase |

Static cleanup guards:

- `test_phase3_old_graph_scaffold_deletion_blockers_are_explicitly_owned()` now requires `PlannerService` to be free of `LangGraphPlanner`, `_langgraph_planner_cls`, `generate_plan()`, and `resume_after_approval()`.
- The same guard requires `api/routers/approvals.py` to be free of route-level planner resume calls.
- Graph-runtime source guards remain unchanged and continue to block `LangGraphPlanner`, `compile_planner_graph()`, `working_intents`, `intent_cursor`, and `intent_completed` from entering `PlannerOwnedGraphRuntimeAdapter` / `PlannerOwnedAgentGraph`.

Verification:

- `python -m py_compile factory_agent\services\planner_service.py factory_agent\api\routes.py factory_agent\api\routers\approvals.py` -> passed, no output.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `16 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `2 warnings`.
- `python -m pytest tests/test_api_endpoints.py::test_graph_approval_reject_does_not_call_retired_planner_adapter -q` -> `1 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `7 warnings`.
- `python -m pytest tests/test_planner.py tests/test_planner_service_phase6.py tests/test_seeded_scenario_engine.py -q` -> `67 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `77 warnings`.
- `python -m pytest tests/test_route_to_execution_contract.py tests/test_api_endpoints.py -q` -> `59 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `825 warnings`.
- `python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q` -> did not run because PowerShell passed the wildcard literally (`file or directory not found`).
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest -q` -> `1023 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1400 warnings`.
- `rg -n "class PlannerService|generate_plan|resume_after_approval|LangGraphPlanner|compile_planner_graph|PlannerService\(" factory-agent/factory_agent factory-agent/tests docs/qa` -> passed and confirmed product service hits are limited to `PlannerService` class/export, seeded compatibility, old graph scaffold modules, historical tests, and tracker text; no PlannerService old graph import/construction remains.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.

Remaining blockers:

- Old graph scaffold files are still present and covered by historical old graph tests; deletion is now a separate, explicit scaffold cleanup decision rather than a PlannerService runtime blocker.

Next recommended phase:

- Decide whether to quarantine, migrate, or delete the remaining old `factory_agent.graph` scaffold/tests now that no product service owner imports or constructs `LangGraphPlanner`.

## Phase 3.6: Old Graph Scaffold Classification Before Deletion

Phase result:

- `Phase 3.6 old graph scaffold classification complete`.
- No scaffold file was deleted. The phase classified remaining old `factory_agent.graph` files/tests before deletion and added a static guard proving active runtime does not import old graph scaffold authority.
- Normal runtime remains `PlannerOwnedAgentGraph`; no planner-owned graph runtime behavior, frontend fixtures, release harness, Qwen/proposer policy, exact-prompt branch, seeded-ID branch, or source-ID branch changed.

Active runtime import proof:

- AST import/call inspection found no active runtime construction or call of `LangGraphPlanner` or `compile_planner_graph()` outside the old scaffold itself.
- AST import/call inspection found no active runtime import of old graph nodes (`factory_agent.graph.nodes.*`) outside the old scaffold itself.
- Two non-node compatibility seams still touch old graph scaffold modules:
  - `factory-agent/factory_agent/graph/approval_summary.py` imports `_infer_bulk_job_priority_mutation` from `planner_graph_helpers.py`; this is active approval UI compatibility used by `factory-agent/factory_agent/graph/v2_agent_graph.py`.
  - `factory-agent/factory_agent/llm/structured_output.py` imports `AgentPlanOutput` from `graph/state.py`; this remains a structured planner-output schema migration target.
- Static guard added: `test_phase3_6_active_runtime_does_not_import_old_graph_scaffold_authority()`.

Old Graph Scaffold Classification:

| File/symbol | Classification | Evidence | Next owner/blocker |
| --- | --- | --- | --- |
| `factory-agent/factory_agent/graph/planner_graph.py` | Historical quarantine; deletion candidate after tests migrate | Defines `LangGraphPlanner`, `_initial_planner_state()`, approval/not-found fallback helpers, and calls `compile_planner_graph()` internally; active service owners no longer import or construct it | Historical old graph tests still instantiate `LangGraphPlanner` and call `_initial_planner_state()` |
| `factory-agent/factory_agent/graph/planner_graph_helpers.py` | Compatibility owner for `_infer_bulk_job_priority_mutation`; migration target for helper extraction; remainder historical quarantine | Active `approval_summary.py` imports `_infer_bulk_job_priority_mutation`; old graph nodes/tests import `_deterministic_plan_repair()`, `_tool_cards()`, `_message_content_text()`, `_insert_delete_preflights()`, and related helpers | Move active approval-summary helper to an active owner before deleting the helper module; migrate/delete old helper tests |
| `factory-agent/factory_agent/graph/nodes/intent_split.py` | Historical quarantine; small deletion candidate after tests migrate | Writes `working_intents` and `intent_cursor`; active intent parsing lives in `factory_agent.planning.intent` | Keep `split_user_intents()` coverage; delete or migrate the two node/state smoke assertions |
| `factory-agent/factory_agent/graph/nodes/planner_loop.py` | Historical quarantine; migration target where guard behavior is still useful | Owns old planner prompt, decision guard, `intent_completed`, `working_intents`, and `intent_cursor` loop authority; active graph runtime guard forbids these concepts | Migrate still-valuable guard/repair assertions to planner-owned graph or planning helpers, then delete old loop tests |
| `factory-agent/factory_agent/graph/nodes/validate.py` | Historical quarantine; migration target for approval/finalization invariants | Old final validator still mutates `working_intents`/`intent_cursor` and builds old approval payloads; tests cover finalization, approval, commit, and repair contracts | Migrate relevant approval/finalization coverage to `PlannerOwnedAgentGraph` before deleting |
| `factory-agent/factory_agent/graph/state.py` `AgentState`, `working_intents`, `intent_cursor` | Historical quarantine; deletion candidate after old graph tests migrate | `AgentState` owns old LangGraph mutable state and legacy cursor fields; active graph runtime does not read these fields | Remove with old graph state-machine tests |
| `factory-agent/factory_agent/graph/state.py` `AgentPlanOutput` / `AgentPlanStep` | Migration target / compatibility owner | `llm/structured_output.py`, old nodes, and tests still use these planner-output models | Move to a non-graph schema owner if structured-output parsing must remain after old graph deletion |
| `factory-agent/factory_agent/graph/builder.py` / `compile_planner_graph()` | Historical quarantine; deletion candidate after tests migrate | Only old scaffold and historical tests compile this graph | Delete once old graph tests are migrated/deleted |

Related test classification:

| Test file | Classification | Evidence | Next owner/blocker |
| --- | --- | --- | --- |
| `factory-agent/tests/test_planner_phase3.py` | Historical quarantine with migration-target guard cases | Imports `compile_planner_graph`, `decision_guard_node`, `_initial_planner_state`, and asserts `intent_completed` / `working_intents` behavior | Migrate still-useful guard/constraint repair cases to active planner-owned graph tests |
| `factory-agent/tests/test_route_to_execution_contract.py` | Migration target | Compiles old graph to prove route-to-execution and constraint repair behavior; this is still a release-relevant contract but not active graph runtime proof | Rebuild against `PlannerOwnedAgentGraph` / active runtime before deleting |
| `factory-agent/tests/test_planner.py` | Mixed migration target and deletion candidate | Tests old validate/reason/decision guard helpers plus active `llm.plan_parsing` normalization | Split active plan-parsing tests from old graph helper tests |
| `factory-agent/tests/test_phase5_final_validator.py` | Historical quarantine with migration-target approval invariants | Instantiates `LangGraphPlanner` and old final validator; covers approval pause/resume and commit safety | Migrate approval/finalization invariants to graph-owned tests, then delete old graph portions |
| `factory-agent/tests/test_langgraph_state_machine_oracles.py` | Historical quarantine; migration target where oracle scenarios remain valuable | Instantiates `LangGraphPlanner`, `make_final_validator_node()`, and old state-machine cursor fields | Keep only if converted to active graph oracle coverage |
| `factory-agent/tests/test_planner_service_phase6.py` | Mixed compatibility owner and historical quarantine | First test directly exercises `LangGraphPlanner` durable checkpoint resume; later tests prove graph-native snapshot/reject behavior | Split active graph-native snapshot tests from old checkpoint test |
| `factory-agent/tests/test_tool_pipeline.py` | Mixed compatibility owner and historical quarantine | `http_tool_client` idempotency helper is still shared; old tool pipeline and decision guard tests are historical | Split active helper tests from old node tests |
| `factory-agent/tests/test_intent_splitter.py` | Mixed active intent parser coverage and historical node smoke | Most tests target `planning.intent`; final node tests assert `working_intents` graph-state projection | Keep parser tests; delete/migrate node projection smoke after old scaffold removal |
| `factory-agent/tests/test_agent_state.py` | Historical quarantine with small graph-native subject compatibility assertion | Tests old `AgentState` reducers and includes `working_intents` / `intent_cursor`; also asserts graph-native approval subject parsing | Split approval subject assertion if old state tests are deleted |
| `factory-agent/tests/graph_state_fixtures.py` | Deletion candidate after old graph tests migrate | Fixture only builds old graph `AgentPlanOutput` state for old validate/reason tests | Delete after dependent tests are migrated/deleted |

Candidate disposition:

- Active runtime: `PlannerOwnedAgentGraph`, `PlannerOwnedGraphRuntimeAdapter`, graph-native approvals, seeded compatibility, direct-v2 trace/context compatibility.
- Compatibility owner: `approval_summary.py` for `_infer_bulk_job_priority_mutation` until moved out of `planner_graph_helpers.py`; graph-native snapshot/reject tests in `test_planner_service_phase6.py`; `http_tool_client` idempotency helper tests.
- Historical quarantine: `LangGraphPlanner`, `compile_planner_graph()`, old graph nodes, `AgentState` cursor fields, old graph checkpoint/resume and state-machine tests.
- Migration target: old route-to-execution contract tests, final validator approval/commit invariants, useful decision-guard/constraint repair tests, `AgentPlanOutput` / `AgentPlanStep` schema ownership.
- Deletion candidate: `planner_graph.py`, `builder.py`, old node files, old state fields, old graph-only fixtures/tests after migration/compatibility seams are resolved.
- Unknown owner: none found.

Static cleanup guards:

- `test_phase3_6_active_runtime_does_not_import_old_graph_scaffold_authority()` scans runtime AST and fails if active runtime imports old graph nodes, imports old graph scaffold modules outside the two recorded compatibility seams, or calls `LangGraphPlanner` / `compile_planner_graph()`.
- `test_phase3_6_old_graph_scaffold_classification_is_tracked()` requires the tracker to keep the Phase 3.6 classification entries visible.

Verification:

- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `18 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `2 warnings`.
- `python -m pytest tests/test_agent_state.py tests/test_intent_splitter.py tests/test_planner.py tests/test_planner_phase3.py tests/test_phase5_final_validator.py tests/test_planner_service_phase6.py tests/test_route_to_execution_contract.py tests/test_tool_pipeline.py tests/test_langgraph_state_machine_oracles.py -q` -> `173 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `118 warnings`.
- `python -m pytest tests/test_route_to_execution_contract.py tests/test_api_endpoints.py -q` -> `59 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `825 warnings`.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest -q` -> `1025 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1397 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.

Remaining blockers:

- `planner_graph_helpers.py` cannot be deleted until `_infer_bulk_job_priority_mutation` is moved to an active approval-summary/planning owner.
- `graph/state.py` cannot be deleted until `AgentPlanOutput` / `AgentPlanStep` ownership is moved or `llm/structured_output.py` is retired with the old graph.
- Old graph test files still execute historical LangGraph scaffold behavior and need migration/deletion decisions before source deletion.

Next recommended phase:

- Migrate or split the active compatibility seams (`approval_summary.py` helper use, `AgentPlanOutput` schema ownership, graph-native snapshot/helper tests) so a later deletion phase can remove the old graph scaffold without losing current coverage.

## Phase 3.7: Split Remaining Old Graph Compatibility Seams

Phase result:

- `Phase 3.7 compatibility seams split`.
- No old graph scaffold file was deleted. `LangGraphPlanner`, `planner_graph.py`, old graph nodes, planner-owned graph runtime, frontend fixtures, release harness, Qwen/proposer policy, exact-prompt branches, seeded-ID branches, and source-ID branches were left unchanged.
- Active runtime no longer imports old graph scaffold modules through the two Phase 3.6 compatibility allowlist entries.

Candidate disposition:

| Candidate | Disposition | Evidence | Next owner/blocker |
| --- | --- | --- | --- |
| `planner_graph_helpers.py::_infer_bulk_job_priority_mutation` | Moved to graph-native approval summary owner | `factory-agent/factory_agent/graph/approval_summary.py` now defines the inference helper used by bundle UI approval summaries; old graph helpers/nodes import it from that owner for unchanged historical behavior | No active approval-summary dependency blocks helper-module deletion |
| `graph/state.py::AgentPlanOutput` / `AgentPlanStep` | Moved to central schema owner | `factory-agent/factory_agent/schemas.py` now defines both planner-output models; `llm/structured_output.py`, old graph helpers/nodes, and tests import the schema owner | `graph/state.py` can be removed with old graph state once old graph tests migrate/delete |

Tracker update:

- `ACTIVE_RUNTIME_OLD_GRAPH_COMPATIBILITY_IMPORTS` in `test_planner_owned_loop_phase15_legacy_cleanup.py` is now empty.
- Static cleanup guards now prove `structured_output.py` imports `AgentPlanOutput` from `schemas.py`, `approval_summary.py` owns `_infer_bulk_job_priority_mutation()`, `planner_graph_helpers.py` no longer defines that helper, and `graph/state.py` no longer defines `AgentPlanOutput` / `AgentPlanStep`.
- Old graph scaffold deletion remains intentionally deferred; remaining old graph files/tests are historical quarantine, migration targets, or deletion candidates as classified in Phase 3.6.

Verification:

- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `18 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `2 warnings`.
- `python -m pytest tests/test_approval_bundle_ui.py tests/test_planner.py tests/test_phase5_final_validator.py tests/test_agent_state.py -q` -> `63 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `24 warnings`.
- `python -m pytest tests/test_planner_phase3.py tests/test_tool_pipeline.py tests/test_langgraph_state_machine_oracles.py tests/test_intent_splitter.py -q` -> `92 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `17 warnings`.
- `python -m pytest tests/test_route_to_execution_contract.py tests/test_api_endpoints.py -q` -> `59 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `826 warnings`.
- `Get-ChildItem -Path tests -Filter 'test_planner_owned_agent_graph_phase*_*.py' | ForEach-Object { $_.FullName }` then `python -m pytest $phaseTests -q` -> `88 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `22 warnings`.
- `python -m pytest -q` -> `1025 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1400 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.
- Several pytest runs emitted post-success LangSmith telemetry upload 429/connection errors; pytest exit codes were zero and test summaries were already green.

Remaining blockers:

- Old graph scaffold/tests still exist and still need the Phase 3 deletion decision/migration pass.
- No active old graph compatibility seam remains for the two Phase 3.6 blockers.

Next recommended phase:

- Delete or migrate the classified old graph scaffold/tests now that the active approval-summary and planner-output schema blockers are split out.

## Phase 3.8: Delete Old Graph Scaffold

Phase result:

- `Phase 3.8 old graph scaffold deleted`.
- Deleted the old `LangGraphPlanner` state-machine scaffold, old graph nodes, old graph helper module, old graph state, old graph errors, and old graph-only tests/fixtures.
- Normal runtime remains `PlannerOwnedAgentGraph`; graph-owned runtime, checkpointing, approval summary, HTTP tool client, no-op compatibility, session detection, direct-v2 trace/context compatibility, frontend fixtures, release harness behavior, and Qwen/proposer policy were not changed.
- The frontend seeded-oracles gate exposed one missed active compatibility owner: seeded Playwright graph approval resume payloads with seeded `bundle_ui.kind` values and no top-level graph/direct-v2 `kind`. That owner is now explicit in `plan_creation_compatibility.py`; it does not revive the retired old graph fallback.

Files changed:

- Deleted old scaffold runtime: `factory-agent/factory_agent/graph/builder.py`, `factory-agent/factory_agent/graph/errors.py`, `factory-agent/factory_agent/graph/planner_graph.py`, `factory-agent/factory_agent/graph/planner_graph_helpers.py`, `factory-agent/factory_agent/graph/state.py`, and `factory-agent/factory_agent/graph/nodes/*`.
- Retained active graph-owned modules: `v2_agent_graph.py`, `checkpointing.py`, `approval_summary.py`, `http_tool_client.py`, `noop_mutations.py`, and `session_detection.py`.
- Deleted old graph-only tests/fixtures: `factory-agent/tests/test_planner_phase3.py`, `factory-agent/tests/test_phase5_final_validator.py`, `factory-agent/tests/test_langgraph_state_machine_oracles.py`, and `factory-agent/tests/graph_state_fixtures.py`.
- Retained and migrated mixed tests: `test_route_to_execution_contract.py` now exercises `PlannerOwnedAgentGraph`; `test_planner.py` keeps central parser/planner helper coverage; `test_agent_state.py` keeps graph-neutral reducer and graph-native approval subject smoke coverage; `test_tool_pipeline.py` keeps HTTP tool client idempotency coverage; `test_intent_splitter.py` keeps active intent parser/semantic routing coverage; `test_planner_service_phase6.py` keeps graph-native snapshot/reject coverage.
- Rehomed seeded Playwright approval resume compatibility through `services/plan_creation_compatibility.py`, with `PlanCreationService` as the owner and `ApprovalResumeService` delegating through that owner after graph-native and direct-v2 handlers decline the payload.
- Added `test_seeded_graph_approval_resumes_without_old_graph_fallback()` to prove seeded graph approval payloads resume through the explicit seeded compatibility seam while unsupported old graph payloads still fail closed.
- Adjusted only the backend seeded long-stream fixture evidence shape so release scenario 70 renders the terminal release summary instead of being projected as a generic machine-status result.
- Updated `test_planner_owned_loop_phase15_legacy_cleanup.py` so static guards assert old scaffold files are absent and no retained tests import deleted old graph modules.

Candidate disposition:

| Candidate | Disposition | Evidence | Owner after Phase 3.8 |
| --- | --- | --- | --- |
| `graph/planner_graph.py` / `LangGraphPlanner` | Deleted | Active service owners no longer import or construct it; old instantiation tests were deleted | None |
| `graph/builder.py` / `compile_planner_graph()` | Deleted | Only old scaffold/tests compiled it | None |
| `graph/planner_graph_helpers.py` | Deleted | `_infer_bulk_job_priority_mutation()` is owned by `graph/approval_summary.py`; `_normalize_plan_dict()` is owned by `llm/plan_parsing.py`; remaining users were old graph modules/tests | None |
| `graph/state.py` / `AgentState` / `working_intents` / `intent_cursor` | Deleted | `AgentPlanOutput` / `AgentPlanStep` are owned by `schemas.py`; active graph state is `planning/v2_agent_state.py` | None |
| `graph/nodes/*` old state-machine nodes | Deleted | No active runtime/test import remains; planner-owned graph tests cover active runtime behavior | None |
| `graph/errors.py` old `LangGraphPlanner*` exceptions | Deleted | Only old graph modules/tests imported them | None |
| `test_route_to_execution_contract.py` | Migrated | Retained route-to-execution proof now runs active `PlannerOwnedAgentGraph` and `ToolSelector` | Active graph/runtime contract |
| `test_planner_service_phase6.py` | Split | Deleted old `LangGraphPlanner` durable-checkpoint test; kept graph-native snapshot/reject tests | Graph-native session compatibility |
| `test_tool_pipeline.py` | Split | Deleted old node pipeline tests; kept shared HTTP tool client idempotency helper test | `graph/http_tool_client.py` |
| `test_planner.py` | Split | Deleted old node/helper tests; kept central parser and planner helper tests | `llm/plan_parsing.py`, `planner_service.py` helpers |
| `test_agent_state.py` / `test_intent_splitter.py` | Split | Deleted old `AgentState`/node projection assertions; kept active parser/schema smoke coverage | Active parser/schema owners |
| Seeded Playwright graph approval resume | Rehomed compatibility owner | Seeded-oracles initially failed with `graph_approval_resume_unsupported_payload` for seeded `bundle_ui.kind` payloads; new compatibility seam is adapter-marked and tested | `services/plan_creation_compatibility.py` |
| Release long-stream seeded evidence | Fixture evidence corrected | Release scenario 70 initially completed but rendered status-only copy; fixture result no longer masquerades as a machine status row | `testing_seeded_scenarios.py` seeded test fixture |

Tracker update:

- Static guards now require `Phase 3.8 old graph scaffold deleted` to remain recorded.
- `test_phase11_historical_graph_authority_modules_are_deleted()` asserts the deleted scaffold files are absent.
- `test_phase3_8_tests_do_not_import_deleted_old_graph_scaffold()` scans retained tests for deleted old graph imports.
- `test_phase3_old_graph_scaffold_deletion_blockers_are_explicitly_owned()` now verifies old compatibility seams are owned by `approval_summary.py`, `schemas.py`, `llm/plan_parsing.py`, and the explicit seeded planner compatibility owner, and that old scaffold paths no longer exist.

Verification:

- `rg -n "LangGraphPlanner|compile_planner_graph|planner_graph_helpers|factory_agent.graph.nodes|working_intents|intent_cursor|intent_completed|from factory_agent.graph.planner_graph|from factory_agent.graph.state" factory-agent/factory_agent factory-agent/tests docs/qa` -> passed; remaining hits are historical docs/tracker text and static guard strings, not active runtime imports.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `19 passed, 2 warnings`.
- `python -m pytest tests/test_planner.py tests/test_agent_state.py tests/test_intent_splitter.py tests/test_tool_pipeline.py tests/test_planner_service_phase6.py -q --disable-warnings` -> `59 passed, 23 warnings`.
- `python -m pytest tests/test_route_to_execution_contract.py tests/test_api_endpoints.py -q --disable-warnings` -> `59 passed, 825 warnings`.
- `python -m pytest tests/test_planner_owned_agent_graph_phase*_*.py -q` with PowerShell-expanded file list -> `88 passed, 22 warnings`.
- `python -m pytest -q` -> `930 passed, 3 skipped, 1331 warnings`.
- `npm run test:e2e:response-document` -> `30 passed`.
- `npm run test:e2e:seeded-oracles` -> first run exposed the seeded approval resume owner (`20 passed, 15 failed`); after the explicit seeded compatibility seam, rerun passed with `35 passed`.
- `npm run test:e2e:real-langgraph` -> `3 passed`.
- `npm run test:e2e:release` -> first run exposed the seeded long-stream evidence-shape issue (`20 passed, 1 failed`); after the seeded fixture evidence correction, rerun passed with `21 passed`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.

Remaining cleanup candidates:

- Historical documentation still references old graph concepts as migration history; no active runtime/test import owner remains.
- Frontend fixture/release-harness naming cleanup remains out of scope unless a later phase explicitly rewrites historical trace labels.

## Phase 4.0: Historical Documentation And Guard Vocabulary Cleanup

Status: complete.

Phase 4.0 historical documentation and guard vocabulary cleanup complete.

Remaining old graph/direct-v2 terms were classified as historical documentation, static guard vocabulary, compatibility schema values, frontend release-harness vocabulary, or deletion candidates already completed.

Goal:

- Clean or quarantine historical old graph/direct-v2 documentation and test vocabulary after Phase 3.8 deleted the old graph scaffold.
- Preserve compatibility schema values, static guard denylist strings, frontend release-harness vocabulary, and migration history without presenting old graph/direct-v2 terms as current runtime authority.

Reference audit:

```powershell
rg -n "LangGraphPlanner|compile_planner_graph|planner_graph|planner_graph_helpers|working_intents|intent_cursor|intent_completed|v2_planner_loop|legacy graph scaffold|direct-v2 loop" docs factory-agent "eMas Front/e2e"
```

Disposition:

| Candidate | Phase 4.0 classification | Evidence | Follow-up |
| --- | --- | --- | --- |
| `LangGraphPlanner` | Historical docs OK and static guard OK | Deleted with `graph/planner_graph.py` in Phase 3.8; remaining code hits are cleanup guard strings that prevent reintroduction. | None unless old graph terms reappear in runtime imports/calls. |
| `compile_planner_graph` | Historical docs OK and static guard OK | Deleted with `graph/builder.py` in Phase 3.8; remaining code hits are cleanup guard strings. | None. |
| `planner_graph.py` | Historical docs OK and deletion candidate already completed | Deleted in Phase 3.8; old QA/tracker docs keep migration chronology. | Leave historical docs intact unless a later archive pass moves old QA plans. |
| `planner_graph_helpers.py` | Historical docs OK and deletion candidate already completed | Deleted in Phase 3.8 after parser and approval-summary ownership moved to active owners. | None. |
| `working_intents` | Historical docs OK, static guard OK, compatibility schema OK | Old state field deleted with `graph/state.py`; retained in `v2_contracts.py` as historical trace schema vocabulary and in tests as denylist/compatibility vocabulary. | Do not remove schema value without persisted-trace compatibility proof. |
| `intent_cursor` | Historical docs OK, static guard OK, compatibility schema OK | Old state field deleted with `graph/state.py`; retained in compatibility trace fields and static guards. | Do not remove schema field without persisted-trace compatibility proof. |
| `intent_completed` | Historical docs OK, static guard OK, compatibility schema OK | Old loop action deleted with old graph nodes; `schemas.py` keeps compatibility/control vocabulary and guards keep it out of graph runtime authority. | Do not remove schema/control value without API compatibility proof. |
| `v2_planner_loop` | Compatibility schema OK, historical docs OK, frontend release-harness vocabulary | `planning/v2_planner_loop.py` is deleted; `v2_trace_compatibility.py`, `v2_contracts.py`, approval payload compatibility, and selected frontend fixtures retain the value as historical trace vocabulary. | Engine/trace cleanup or frontend fixture rewrite phase must decide any removal. |
| `legacy graph scaffold` | Historical docs OK | Tracker and migration docs now describe it as deleted Phase 3.8 history. | None. |
| direct-v2 loop as current runtime | Misleading/current wording fixed | Updated cleanup plan/tracker and graph migration docs so direct-v2 names are historical/compatibility vocabulary, not current runtime proof. | Future Phase 4.x may rewrite active trace/fixture expectations. |

Files changed:

- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md`
- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION.md`
- `docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md`

Guardrail outcome:

- No runtime behavior changed.
- No planner-owned graph behavior changed.
- No frontend fixtures or release harness changed.
- No Qwen/proposer policy changed.
- No compatibility schema values removed.
- No exact-prompt, seeded-ID, or source-ID branches added.

Verification:

- `rg -n "LangGraphPlanner|compile_planner_graph|planner_graph|planner_graph_helpers|working_intents|intent_cursor|intent_completed|v2_planner_loop|legacy graph scaffold|direct-v2 loop" docs factory-agent "eMas Front/e2e"` -> passed; remaining hits are classified as historical docs, static guards, compatibility schema/control vocabulary, approval/session compatibility, or frontend release-harness vocabulary.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `20 passed, 2 warnings`.
- `python -m pytest -q` -> `931 passed, 3 skipped, 1330 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.

Remaining cleanup candidates:

- Frontend hard-query `generatedBy: 'v2_planner_loop'` fixtures remain intentionally unchanged as release-harness vocabulary until a frontend/release-harness phase owns the rewrite.
- Compatibility schema values for old trace fields remain intentionally unchanged until persisted-session compatibility is explicitly migrated or removed.

## Phase 4.1: Engine And Trace Compatibility Audit

Status: complete.

Goal:

- Audit every remaining legacy/shadow/direct-v2 trace value before deleting anything.
- Classify the remaining references as active compatibility schema, persisted historical parse compatibility, frontend fixture/release vocabulary, static guard vocabulary, historical docs only, deletion candidate, or unknown owner.
- Preserve persisted trace/session compatibility, frontend fixtures, release harness behavior, planner-owned graph runtime behavior, and Qwen/proposer policy.

Reference audit commands:

```powershell
git status --short --branch
git rev-parse HEAD
rg -n "EngineVersion|v2_shadow|v2_planner_loop|legacy_rag_route|legacy_rag_shortcut|legacyIntentCompletionLoopUsed|legacyRagShortcutUsed|generatedBy|generated_by|v2_shadow_state" factory-agent docs/qa "eMas Front/e2e"
rg -n "legacy|v2_shadow|legacy_rag_route" factory-agent/factory_agent/planning factory-agent/tests docs/qa "eMas Front/e2e"
rg -n "generatedBy|generated_by|legacyIntentCompletionLoopUsed|legacyRagShortcutUsed|engineVersion|legacy_rag_shortcut|legacy_intent_completion_loop" "eMas Front/e2e"
rg -n "generatedBy|generated_by|legacyIntentCompletionLoopUsed|legacyRagShortcutUsed|engineVersion|legacy_rag_shortcut|legacy_intent_completion_loop" "eMas Front/src"
rg -n "v2_planner_loop|legacy_rag_route|legacy_rag_shortcut|v2_shadow_state|v2_shadow|generated_by|created_by" factory-agent/factory_agent -g "*.py"
Select-String -Path "factory-agent/factory_agent/config.py" -Pattern "normalize_factory_agent_engine|FACTORY_AGENT_ENGINE|legacy|v2_shadow" -Context 4,8
Select-String -Path "factory-agent/factory_agent/services/plan_creation_service.py" -Pattern "v2_planner_loop|legacy_rag_route|generated_by|EMPTY_PLAN_COMPLETION_BACKENDS" -Context 4,6
Select-String -Path "factory-agent/factory_agent/services/approval_resume_service.py" -Pattern "v2_planner_loop|legacy_rag_route|backend_used|generated_by" -Context 4,8
Select-String -Path "factory-agent/factory_agent/graph/session_detection.py" -Pattern "v2_planner_loop|legacy|created_by" -Context 4,8
```

Disposition:

| Reference family | Primary classification | Owner | Evidence | Phase 4.1 decision | Removal or rewrite gate |
| --- | --- | --- | --- | --- | --- |
| `EngineVersion = Literal["legacy", "v2_shadow", "v2"]` | active compatibility schema | `planning/v2_contracts.py` plus graph state schema reuse in `planning/v2_agent_state.py` | `PlannerOwnedLoopV2State`, `ExecutionTrace`, and graph state still deserialize old engine labels while graph state enforces `planner_owned_agent_graph` trace identity. | Keep. Do not remove schema/control values in audit phase. | Persisted trace/session migration or a split compatibility parser with graph-state tests proving old values parse but cannot become runtime authority. |
| `FACTORY_AGENT_ENGINE=legacy` / `FACTORY_AGENT_ENGINE=v2_shadow` normalization | static guard vocabulary | `config.py` and Phase 10/15 cleanup tests | `normalize_factory_agent_engine()` maps any input to `v2`; tests prove legacy/shadow env values do not restore authority. | Keep normalization and guard strings. | Only remove env vocabulary after deployment/release proof that old env values no longer need graceful normalization. |
| `ExecutionTraceGeneratedBy` old values: `legacy_graph_loop`, `legacy_rag_route`, `legacy_working_intents`, `v2_shadow_planner_loop`, `v2_planner_loop` | active compatibility schema | `planning/v2_contracts.py` | The enum accepts historical trace values; graph state rejects non-graph trace identity as graph proof. | Keep as compatibility contract. | Move to explicit historical trace parser or archive contract after persisted-data audit; keep graph rejection tests. |
| `ExecutionTrace` defaults `engine_version="legacy"` and `generated_by="legacy_graph_loop"` | persisted historical parse compatibility | `planning/v2_contracts.py` | Defaults preserve old trace construction and phase contract tests. | Keep for now; flag as Phase 4.2 review candidate. | Change only if all callers construct explicit current graph trace identity and old traces still parse through a compatibility adapter. |
| `generated_by="v2_planner_loop"` in `v2_trace_compatibility.py` | persisted historical parse compatibility | `planning/v2_trace_compatibility.py` | Direct-v2 compatibility builder still emits the historical value for old trace/context tests; `planning/v2_planner_loop.py` remains deleted. | Keep behind explicit compatibility module. | Remove or rewrite only after tests no longer need direct-v2 trace replay and persisted direct-v2 sessions have a migration/reader. |
| Failed direct-v2 compatibility fallback `generated_by=f"{v2_engine}_planner_loop"` | persisted historical parse compatibility | `planning/v2_trace_compatibility.py` | Failure-state builder uses the same historical generated-by value without reintroducing `PlannerOwnedV2Loop`. | Keep; no runtime authority. | Same as direct-v2 compatibility builder removal gate. |
| `attach_direct_v2_trace_to_intent_contract()` | persisted historical parse compatibility | `planning/v2_trace_compatibility.py` | Still attaches `engine_version="v2"`, `execution_trace`, and `v2_state` for historical context compatibility. | Keep. | Remove only after persisted intent-contract readers no longer require old direct-v2 fields. |
| `legacy_rag_route` generated-by validator and `legacy_rag_shortcut` detector | active compatibility schema | `planning/v2_contracts.py` | Validator requires `legacy_rag_shortcut.used` when `generated_by="legacy_rag_route"`. | Keep as compatibility validation. | Phase 5 may move this into a historical RAG parser if persisted legacy RAG route traces can still be read. |
| `EvidenceSourceType = "legacy_rag_route"` and `LegacyRagRouteMetadata` | active compatibility schema | `planning/v2_contracts.py` | Evidence validation prevents legacy RAG route evidence from masquerading as a v2 tool call and requires route metadata. | Keep. | Phase 5 removal or extraction requires persisted evidence migration plus RAG/source rendering proof. |
| `legacy_rag_route_cannot_satisfy_v2` in final validation | static guard vocabulary | `planning/v2_satisfaction.py` | Historical RAG route evidence is explicitly failed for satisfied current v2 requirements. | Keep; this is a guard, not legacy authority. | Remove only if `legacy_rag_route` evidence type is removed or moved and equivalent rejection remains covered. |
| `v2_shadow_state` in interrupt/revision helpers | persisted historical parse compatibility | `planning/v2_interrupts.py` | Interrupt context reads both `v2_state` and `v2_shadow_state`, writes updated execution trace back to the matched key, and extracts ledger revisions from either key. | Keep. | Remove only after old shadow-state sessions are migrated or declared unsupported with an explicit compatibility decision. |
| Legacy detector model fields: `legacy_working_intent_execution`, `legacy_whole_query_tool_scope`, `legacy_intent_completion_loop`, `legacy_rag_shortcut` | active compatibility schema | `planning/v2_contracts.py` | Current graph/runtime tests assert these flags remain false while old traces can still deserialize detector payloads. | Keep as schema/control vocabulary. | Extract or remove after frontend/release fixtures and persisted trace readers stop referencing the detector names. |
| `v2_planner_loop` in `PlanCreationService` empty-plan and max-step completion allowlists | persisted historical parse compatibility | `services/plan_creation_service.py` | `EMPTY_PLAN_COMPLETION_BACKENDS` and completion guard include `v2_planner_loop` to preserve historical plan `created_by` handling. | Keep during audit. | Phase 4.2 should decide whether to move this literal behind a named compatibility helper before any deletion. |
| `backend_used="v2_planner_loop"` in direct-v2 approval resume compatibility | persisted historical parse compatibility | `services/approval_resume_service.py` | Historical direct-v2 approval resume path persists the compatibility backend while graph-native and seeded compatibility paths remain separate. | Keep during audit. | Remove only after old direct-v2 approval payload compatibility is retired or migrated. |
| `is_planner_owned_v2_plan()` checks `created_by == "v2_planner_loop"` | persisted historical parse compatibility | `graph/session_detection.py` | Persisted step projection still recognizes old direct-v2 plans without treating them as graph-native authority. | Keep during audit. | Remove after persisted `created_by="v2_planner_loop"` plans no longer need projection compatibility. |
| `generated_by="planner_owned_agent_graph"` | active compatibility schema | `planning/v2_agent_state.py`, graph runtime tests, API tests | This is the current graph trace identity and must remain distinct from `v2_planner_loop`. | Keep as active graph identity. | Not a cleanup candidate. |
| Graph tests that mention `v2_planner_loop` or `legacy_rag_route` as rejected values | static guard vocabulary | `tests/test_planner_owned_agent_graph_phase1_state.py`, phase7 RAG tests, phase10 runtime-switch tests, phase15 cleanup tests | Tests prove historical values parse when appropriate but cannot satisfy graph proof or runtime authority. | Keep. | Consolidate in Phase 7/8 only after stable static guard suite exists. |
| Quarantined direct-v2 compatibility tests asserting `generated_by="v2_planner_loop"` and legacy detector flags are false | persisted historical parse compatibility | `tests/test_planner_owned_loop_phase5_shadow_engine.py`, `tests/test_planner_owned_loop_phase9_hard_query_release.py` | These tests are marked `legacy_architecture_quarantine` and exercise `v2_trace_compatibility.py`, not the deleted loop. | Keep until migration-test consolidation. | Phase 7 may rewrite/delete after graph-owned coverage and persisted compatibility decisions are recorded. |
| Phase 2 contract tests for `legacy_graph_loop`, `legacy_rag_route`, legacy RAG metadata, and legacy detector payloads | persisted historical parse compatibility | `tests/test_planner_owned_loop_phase2_contracts.py` | Contract tests assert old trace/evidence payloads serialize and enforce legacy RAG constraints. | Keep. | Move to a compatibility-parser suite if `v2_contracts.py` is narrowed later. |
| API and graph release tests asserting `legacy_rag_shortcut.used is False` | static guard vocabulary | `tests/test_api_endpoints.py`, `tests/test_planner_owned_agent_graph_phase7_rag.py`, phase8/10 tests | Current runtime emits graph trace identity and keeps legacy detector flags false. | Keep. | Consolidate later, but do not drop until graph-owned no-legacy authority guards are stable. |
| Frontend `generatedBy: "v2_planner_loop"` hard-query expectations | frontend fixture/release vocabulary | `eMas Front/e2e/support/hardQueryScenarios.js`, `eMas Front/e2e/specs/response-document-hard-query-oracle.spec.js` | Four hard-query scenarios and the oracle spec still encode historical generated-by expectations. | Keep unchanged in Phase 4.1. | Phase 6 should rewrite to graph-owned trace/release evidence with frontend E2E proof. |
| Frontend `legacyIntentCompletionLoopUsed` / `legacyRagShortcutUsed` fixture fields | frontend fixture/release vocabulary | `eMas Front/e2e/support/hardQueryScenarios.js`, oracle spec | Fixture vocabulary asserts legacy detectors are absent in release scenarios. | Keep unchanged in Phase 4.1. | Phase 6 should replace with graph-owned semantic checks if backend guards already own legacy absence. |
| Generic `legacy` text in hardcode docs, response-document probe labels, and unrelated tests/comments | historical docs only | Existing hardcode/frontend compatibility docs and test owners | These hits are not engine/trace authority and mostly describe typed-presentation fallback history or markdown-cleanup behavior. | Leave for separate docs/frontend cleanup; not Phase 4.1 deletion. | Archive or rewrite only in a dedicated frontend/docs wording phase. |
| Historical QA/migration docs that name old values | historical docs only | `docs/qa/*` | Remaining doc hits preserve migration chronology and prior verification commands. | Keep. | Optional archive pass may shorten history after final cleanup proof. |

Unknown owner result:

```text
none
```

Deletion candidates found but not approved in Phase 4.1:

| Candidate | Classification | Why not deleted now | Recommended owner |
| --- | --- | --- | --- |
| Frontend `generatedBy: "v2_planner_loop"` expectations | frontend fixture/release vocabulary | Release fixture behavior is explicitly out of scope for this audit. | Phase 6 frontend/release oracle cleanup |
| Frontend legacy detector camelCase fields | frontend fixture/release vocabulary | Backend static guards already cover some absence checks, but release oracle rewrite needs E2E proof. | Phase 6 frontend/release oracle cleanup |
| Service-local `v2_planner_loop` backend allowlist literals | persisted historical parse compatibility | Persisted plan/session compatibility still needs an owner; moving/removing requires tests around old `created_by` plans and direct-v2 approval payloads. | Phase 4.2 backend compatibility isolation |
| `legacy_rag_route` evidence/source schema | active compatibility schema | Persisted historical RAG route traces still parse, and current validation rejects them as v2 satisfaction proof. | Phase 5 legacy RAG shortcut compatibility cleanup |
| Quarantined direct-v2 compatibility tests | persisted historical parse compatibility | They still prove compatibility helpers and detector defaults, not old runtime authority. | Phase 7 migration test suite consolidation |

Recommended next cleanup phase:

- Run a narrow Phase 4.2 backend compatibility isolation pass before deleting any value. The pass should decide whether `v2_planner_loop` backend/created-by handling belongs in one named compatibility helper instead of service-local literals, and should add focused tests for old `created_by="v2_planner_loop"` plan projection plus direct-v2 approval payload compatibility if the helper moves.
- Leave frontend hard-query `generatedBy` and camelCase legacy-detector vocabulary to Phase 6, where response-document and release E2E can prove the fixture rewrite.
- Leave `legacy_rag_route` evidence/source cleanup to Phase 5, with persisted historical trace parsing and RAG citation/source rendering proof.

Guardrail outcome:

- No runtime behavior changed.
- No planner-owned graph behavior changed.
- No frontend fixtures or release harness changed.
- No Qwen/proposer policy changed.
- No compatibility schema or control values removed.
- No exact-prompt, seeded-ID, source-ID, or source-specific runtime branches added.
- No old graph or direct-v2 authority reintroduced.

Verification:

- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> first run caught a moved Phase 4.0 tracker marker: `19 passed`, `1 failed`, `2 warnings`; tracker marker restored.
- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `20 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `2 warnings`.
- `python -m pytest -q` -> `931 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1331 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warning only; no whitespace errors.

Commit:

- pending.

Remaining cleanup candidates:

- Backend compatibility literals for old direct-v2 `generated_by` / `created_by` values remain owned but should be isolated in Phase 4.2 before deletion is considered.
- Frontend hard-query generated-by and legacy-detector vocabulary remains a Phase 6 release-harness rewrite candidate.
- `legacy_rag_route` schema/evidence/source compatibility remains a Phase 5 cleanup candidate.
- Migration-era direct-v2 compatibility tests remain a Phase 7 consolidation candidate.

## Phase 4.2: Backend Direct-V2 Compatibility Isolation

Status: complete.

Phase result:

- Backend historical direct-v2 `created_by` and `generated_by` handling now has one explicit owner: `factory-agent/factory_agent/planning/historical_direct_v2_compatibility.py`.
- `PlanCreationService` completion handling, `ApprovalResumeService` historical approval payload detection and resume persistence, `graph/session_detection.py` persisted step projection, and `v2_trace_compatibility.py` trace construction now call named helpers instead of embedding service-local compatibility literals/checks.
- Persisted old plans with `created_by="v2_planner_loop"` still allow step projection.
- Historical direct-v2 approval payload resume still persists the same old backend marker through the helper.
- Historical direct-v2 trace compatibility still emits the same generated-by marker through the helper.
- `v2_contracts.py` schema/control values were intentionally retained.
- No frontend fixtures, release harness behavior, planner-owned graph runtime, Qwen/proposer policy, exact-prompt branches, seeded-ID branches, source-ID branches, old graph authority, or direct-v2 execution authority changed.

Files changed:

- `docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md`
- `factory-agent/factory_agent/planning/historical_direct_v2_compatibility.py`
- `factory-agent/factory_agent/planning/v2_trace_compatibility.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/services/approval_resume_service.py`
- `factory-agent/factory_agent/graph/session_detection.py`
- `factory-agent/tests/test_graph_session_detection.py`
- `factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py`

Candidate disposition:

| Candidate | Phase 4.2 disposition | Owner | Evidence | Removal gate |
| --- | --- | --- | --- | --- |
| `v2_planner_loop` generated-by construction in trace compatibility | Isolated behind `historical_direct_v2_generated_by()` | `planning/historical_direct_v2_compatibility.py` plus `planning/v2_trace_compatibility.py` | Phase 15 helper-ownership guard and quarantined direct-v2 trace tests still pass | Persisted direct-v2 trace migration or explicit retirement of direct-v2 trace replay compatibility |
| `created_by == "v2_planner_loop"` persisted plan/session projection | Isolated behind `is_historical_direct_v2_created_by()` | `planning/historical_direct_v2_compatibility.py` plus `graph/session_detection.py` | `test_graph_session_detection.py` proves old created-by values still allow step projection | Persisted old plan/session migration or explicit unsupported-data decision |
| Direct-v2 approval payload compatibility | Isolated behind `is_historical_direct_v2_approval_payload()` and `historical_direct_v2_created_by()` | `planning/historical_direct_v2_compatibility.py` plus `services/approval_resume_service.py` | Focused historical approval payload resume test passed | Historical direct-v2 approval payload compatibility retirement |
| `PlanCreationService` empty-plan and max-step compatibility allowlists | Routed through `is_historical_direct_v2_created_by()` | `planning/historical_direct_v2_compatibility.py` plus `services/plan_creation_service.py` | Full backend passed; Phase 15 guard proves no service-local literal remains | Same persisted plan/session migration gate |

Tracker update:

- Phase 4 table row updated from Phase 4.1 audit-only status to Phase 4.2 complete.
- Top-level status now records backend helper ownership.
- Remaining cleanup candidates were narrowed: backend direct-v2 `created_by` / `generated_by` literals are no longer scattered cleanup candidates, but the historical compatibility value itself remains intentionally retained.

Verification:

- `python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q` -> `21 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `2 warnings`.
- `python -m pytest tests/test_graph_session_detection.py -q` -> `4 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `1 warning`.
- `python -m pytest tests/test_api_endpoints.py::test_phase14_historical_approval_payload_resume_queues_second_actionable_approval -q` -> `1 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `47 warnings`.
- `python -m pytest tests/test_planner_owned_agent_graph_phase10_runtime_switch.py::test_phase10_static_approval_resume_uses_native_graph_checkpoint_before_historical_direct_resume -q` -> `1 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `python -m pytest tests/test_planner_owned_loop_phase9_hard_query_release.py::test_phase9_historical_approval_compatibility_rows_use_next_production_week_when_calendar_week_has_no_rows tests/test_planner_owned_loop_phase9_hard_query_release.py::test_phase9_historical_approval_compatibility_rows_keep_literal_calendar_week_when_matching_rows_exist -q` -> `2 passed`, `0 failed`, `0 skipped`, `0 xfailed`, `3 warnings`.
- `python -m pytest -q` -> `934 passed`, `0 failed`, `3 skipped`, `0 xfailed`, `1331 warnings`.
- `git diff --check` -> passed with LF/CRLF conversion warnings only; no whitespace errors.

Guardrail outcome:

- No persisted old plan/session behavior changed.
- No direct-v2 approval resume behavior changed except helper routing.
- No `v2_planner_loop` schema/control values removed.
- No planner-owned graph runtime behavior changed.
- No frontend fixtures or release harness behavior changed.
- No Qwen/proposer policy changed.
- No exact-prompt, seeded-ID, source-ID, or source-specific runtime branches added.
- No old graph or direct-v2 authority reintroduced.

Remaining cleanup candidates:

- Frontend hard-query generated-by and legacy-detector vocabulary remains a Phase 6 release-harness rewrite candidate.
- `legacy_rag_route` schema/evidence/source compatibility remains a Phase 5 cleanup candidate.
- Migration-era direct-v2 compatibility tests remain a Phase 7 consolidation candidate.
- The retained historical direct-v2 compatibility marker remains until persisted-data migration or an explicit retirement decision.

Commit:

- pending.

## Current Handoff Prompt

```text
You are implementing the next narrow cleanup phase after Phase 4.2 of docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md.

Goal:
Continue cleanup without changing product behavior. Phase 4.2 isolated backend historical direct-v2 `v2_planner_loop` generated-by / created-by compatibility behind `planning/historical_direct_v2_compatibility.py`. Persisted old plan/session projection and historical direct-v2 approval payload resume behavior stayed compatible. Normal runtime remains `PlannerOwnedAgentGraph`.

Read first:
- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md
- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md
- factory-agent/factory_agent/planning/historical_direct_v2_compatibility.py
- factory-agent/factory_agent/planning/v2_contracts.py
- factory-agent/factory_agent/planning/v2_trace_compatibility.py
- factory-agent/factory_agent/planning/v2_interrupts.py
- factory-agent/factory_agent/planning/v2_satisfaction.py
- factory-agent/factory_agent/planning/v2_agent_state.py
- factory-agent/factory_agent/services/plan_creation_service.py
- factory-agent/factory_agent/services/approval_resume_service.py
- factory-agent/factory_agent/graph/session_detection.py
- factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py
- factory-agent/tests/test_planner_owned_loop_phase2_contracts.py
- factory-agent/tests/test_planner_owned_loop_phase5_shadow_engine.py
- factory-agent/tests/test_planner_owned_loop_phase9_hard_query_release.py
- factory-agent/tests/test_planner_owned_agent_graph_phase1_state.py
- factory-agent/tests/test_planner_owned_agent_graph_phase7_rag.py

Scope:
- Recommended next narrow move: Phase 5 legacy RAG shortcut compatibility cleanup. Audit `legacy_rag_route`, `legacy_rag_shortcut`, and related evidence/source schema before deleting or moving anything.
- Preserve persisted historical RAG route trace/evidence parsing unless a compatibility-parser replacement or explicit persisted-data migration is included.
- Keep frontend hard-query release fixtures unchanged unless the phase is explicitly expanded with frontend E2E gates.
- Keep `PlannerOwnedV2Loop`, `PlannerOwnedV2LoopRun`, and `planning/v2_planner_loop.py` deleted.
- Keep `_create_direct_v2_plan()`, `_create_historical_direct_v2_plan()`, `_execute_direct_v2_steps()`, `_execute_direct_v2_api_step()`, and `_execute_direct_v2_rag_step()` absent.
- Preserve persisted-data compatibility for old traces/sessions.

Guardrails:
- Normal runtime must remain PlannerOwnedAgentGraph.
- No legacy/direct-v2/old graph authority may be restored.
- No exact-prompt, seeded-ID, source-ID, or scenario-specific runtime branches.
- No new ToolSelector, retriever, RAG, approval, interrupt, response-document, checkpoint, or planner-runtime stack.
- Offline proposer mode must not count as release proof.
- Keep parse/read compatibility separate from runtime authority.
- Treat unused as something to prove with references, tests, and compatibility ownership.

Verification:
- git status --short --branch
- cd factory-agent
- python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py -q
- Run focused legacy RAG shortcut / satisfaction / source rendering tests if touched.
- python -m pytest -q
- cd ..
- git diff --check

Commit only if cleanup stays within the recorded post-scaffold scope and verification passes.

Suggested commit:
refactor: isolate legacy rag route compatibility

Final response format:
Phase Result
Files Changed
Candidate Disposition
Tracker Update
Verification
Guardrail Checklist
Open Issues
Next Step
```

## Update Rules

Every phase update must include:

- files changed,
- candidate dispositions changed,
- tests run,
- exact pass/fail/skip/xfail counts,
- whether `git diff --check` passed,
- remaining cleanup candidates,
- blockers and owners,
- whether a commit was created,
- commit hash when committed.

Do not mark a phase complete if:

- normal runtime behavior was changed outside phase scope,
- tests were weakened without replacement coverage,
- exact-prompt or seeded-ID runtime branches were added,
- legacy/direct-v2/old graph authority was restored,
- offline proposer mode was counted as release proof,
- a compatibility need was removed without replacement proof.
