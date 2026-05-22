# Planner-Owned Agent Legacy Cleanup Tracker

Status: Phase 2 complete. Active direct-v2 trace/context compatibility is separated from the historical direct loop, the historical direct executor entrypoints are deleted, and normal runtime still enters `PlannerOwnedAgentGraph`. Old graph scaffold deletion, frontend fixture rewrites, and broad migration-test consolidation remain out of scope.

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
| 3 | Old graph scaffold deletion | Not started |  | Full backend, real-LangGraph, release |
| 4 | Engine and trace compatibility cleanup | Not started |  | Full backend, response-document, seeded, release |
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

Phase 1 audited table below supersedes this starter list for cleanup ownership and deletion blockers.

| Candidate | Starting Evidence | Initial Disposition | Owner Needed |
| --- | --- | --- | --- |
| `factory-agent/factory_agent/planning/v2_planner_loop.py` | Historical `PlannerOwnedV2Loop` direct loop still referenced by quarantined tests and service historical helpers. | Audit before delete | Graph runtime owner |
| `PlanCreationService._create_direct_v2_plan` | Phase 10 static guards prove it should not call historical direct execution as normal runtime. | Audit before delete | Runtime adapter owner |
| `PlanCreationService._execute_direct_v2_steps` | Historical direct execution helper should not own normal runtime. | Audit before delete | Runtime adapter owner |
| `attach_direct_v2_trace_to_intent_contract` | Historical trace adapter for direct-v2. | Audit before delete or move to compatibility | Persisted trace owner |
| `factory-agent/factory_agent/graph/planner_graph.py` | Old graph scaffold with `working_intents` and `intent_cursor`. | Audit before delete | Legacy graph compatibility owner |
| `factory-agent/factory_agent/graph/nodes/intent_split.py` | Old intent split node writes `working_intents`. | Audit before delete | Legacy graph compatibility owner |
| `factory-agent/factory_agent/graph/nodes/planner_loop.py` | Old planner loop uses `intent_completed` and cursor authority. | Audit before delete | Legacy graph compatibility owner |
| `factory-agent/factory_agent/graph/state.py` legacy fields | `working_intents` and `intent_cursor` may still exist as old graph state fields. | Audit before edit | Persisted state owner |
| `EngineVersion` legacy/shadow values | `legacy`, `v2_shadow`, and old generated_by values may still be parse compatibility. | Audit before edit | Trace compatibility owner |
| `legacy_rag_route` contracts | Still appears in contracts/tests as historical insufficient-evidence proof. | Audit before edit | RAG compatibility owner |
| `v2_shadow_state` handling | Old v2 shadow state appears in interruption compatibility helpers. | Audit before edit | Persisted state owner |
| `test_planner_owned_loop_phase*_*.py` | Migration-era tests may duplicate graph-owned coverage or assert old architecture. | Audit, rewrite, or delete | Test coverage owner |
| `legacy_architecture_quarantine` marker uses | Quarantined tests should shrink over cleanup. | Audit and reduce | Test coverage owner |
| Frontend hard-query `generatedBy` fixtures | Hard-query scenarios still contain old `generatedBy` / `generated_by` expectations such as `v2_planner_loop`. | Audit and replace | Frontend oracle owner |
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

- All manifest entries remain `Audit before delete`, `Audit before edit`, `Audit and replace`, `Audit, rewrite, or delete`, or `Audit and reduce`.
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

## Current Handoff Prompt

```text
You are implementing the next narrow follow-up after Phase 2 of docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md.

Goal:
Reduce the remaining direct-loop test/helper dependency without changing product behavior. Phase 2 already separated active trace/context compatibility into `v2_trace_compatibility.py` and deleted `_create_historical_direct_v2_plan()` plus `_execute_direct_v2_steps()`. The remaining cleanup candidate is lower direct-v2 helper support that is still blocked by retained compatibility tests and historical approval-payload resume.

Read first:
- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md
- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md
- factory-agent/factory_agent/services/plan_creation_service.py
- factory-agent/factory_agent/services/approval_resume_service.py
- factory-agent/factory_agent/services/planner_owned_graph_runtime.py
- factory-agent/factory_agent/planning/v2_trace_compatibility.py
- factory-agent/factory_agent/planning/v2_planner_loop.py
- factory-agent/factory_agent/planning/v2_contracts.py
- factory-agent/factory_agent/planning/v2_interrupts.py
- factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py
- factory-agent/tests/test_planner_owned_loop_phase6_satisfaction.py
- factory-agent/tests/test_planner_owned_loop_phase7_interrupt_replan.py
- factory-agent/tests/test_planner_owned_loop_phase5_shadow_engine.py
- factory-agent/tests/test_planner_owned_loop_phase9_hard_query_release.py

Scope:
- Implement only retained direct-v2 helper/test cleanup unless explicitly told to start old graph scaffold deletion.
- Treat `_create_direct_v2_plan()` as active runtime until the entry name is migrated safely; it currently delegates to graph runtime.
- Treat `_context_with_engine_trace()` and `v2_trace_compatibility.py` as active trace/context compatibility.
- Treat `PlannerOwnedV2Loop` as retained test/contract compatibility, not active service runtime.
- `_create_historical_direct_v2_plan()` and `_execute_direct_v2_steps()` should remain absent.
- Do not touch old graph scaffold deletion unless the active `PlannerService`, `ExecutionService`, and approval fallback blockers are explicitly resolved.
- Do not rewrite frontend hard-query release fixtures unless the phase scope is explicitly expanded.
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
- python -m pytest tests/test_planner_owned_loop_phase15_legacy_cleanup.py tests/test_planner_owned_agent_graph_phase10_runtime_switch.py tests/test_planner_owned_agent_graph_phase10_6_proposer_policy.py -q
- python -m pytest tests/test_planner_owned_loop_phase5_shadow_engine.py tests/test_planner_owned_loop_phase9_hard_query_release.py tests/test_planner_owned_loop_phase6_satisfaction.py tests/test_planner_owned_loop_phase7_interrupt_replan.py -q
- cd ..
- git diff --check

Commit only if cleanup stays within the recorded blocker scope and verification passes.

Suggested commit:
refactor: shrink retained direct-v2 compatibility

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
