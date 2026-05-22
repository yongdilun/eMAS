# Planner-Owned Agent Legacy Cleanup Tracker

Status: Phase 2.4 complete. Active direct-v2 trace/context compatibility is separated from the historical direct loop, historical direct executor entrypoints are deleted, remaining `PlanCreationService` direct-v2 helper islands are retired or moved to explicit compatibility owners, `PlannerOwnedV2Loop` / `PlannerOwnedV2LoopRun` are deleted, the active graph runtime entry is renamed to `_create_planner_owned_graph_plan()`, and normal runtime still enters `PlannerOwnedAgentGraph`. Old graph scaffold deletion, frontend fixture rewrites, and broad migration-test consolidation remain out of scope.

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

## Current Handoff Prompt

```text
You are implementing the next narrow cleanup phase after Phase 2.4 of docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md.

Goal:
Continue cleanup without changing product behavior. Phase 2.4 renamed the active normal runtime service entry from `_create_direct_v2_plan()` to `_create_planner_owned_graph_plan()`. Direct-v2 trace/draft compatibility remains in `v2_trace_compatibility.py`; normal runtime remains `PlannerOwnedAgentGraph`.

Read first:
- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md
- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md
- factory-agent/factory_agent/services/plan_creation_service.py
- factory-agent/factory_agent/services/approval_resume_service.py
- factory-agent/factory_agent/services/planner_owned_graph_runtime.py
- factory-agent/factory_agent/planning/v2_trace_compatibility.py
- factory-agent/factory_agent/planning/v2_contracts.py
- factory-agent/factory_agent/planning/v2_interrupts.py
- factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py
- factory-agent/tests/test_planner_owned_loop_phase9_hard_query_release.py
- factory-agent/tests/test_planner_owned_agent_graph_phase8_approval_resume.py

Scope:
- Keep `PlannerOwnedV2Loop`, `PlannerOwnedV2LoopRun`, and `planning/v2_planner_loop.py` deleted unless an explicit public compatibility requirement is newly proven.
- Keep `_create_direct_v2_plan()` deleted; normal service runtime should enter `_create_planner_owned_graph_plan()` and delegate to graph runtime.
- Treat `_context_with_engine_trace()` and `v2_trace_compatibility.py` as active trace/context compatibility.
- Keep `PlanCreationService` free of `_direct_v2_*`, `_execute_direct_v2_*`, and `_maybe_create_direct_v2_*` helper islands.
- `_create_historical_direct_v2_plan()`, `_execute_direct_v2_steps()`, `_execute_direct_v2_api_step()`, and `_execute_direct_v2_rag_step()` must remain absent.
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
