# Planner-Owned Agent Legacy Cleanup Tracker

Status: Phase 0 complete. Cleanup lane baseline and starter candidate manifest are recorded after planner-owned graph Phase 12.1 release proof passed.

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
| 0 | Baseline and cleanup manifest | Complete | pending final commit hash | Docs diff check and recorded baseline |
| 1 | Full legacy and v2 usage audit | Not started |  | Audit table complete, no runtime change |
| 2 | Direct-v2 runtime deletion | Not started |  | Full backend, response-document, seeded, real-LangGraph, release |
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

Phase 1 must replace this starter list with an audited table containing file, symbol/term, current references, owner, disposition, replacement coverage, and blocker.

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

Not audited yet. Phase 1 must populate this with any candidate whose owner is unclear.

```text
not audited
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

- pending final commit hash

## Current Handoff Prompt

```text
You are implementing Phase 1 of docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md.

Goal:
Run the first full legacy and v2 usage audit before any deletion or rewrite. Phase 1 proves what is actually used, who owns each compatibility path, and what graph-owned coverage replaces any future cleanup candidate. Do not delete code, tests, frontend fixtures, runtime behavior, or release-harness behavior in Phase 1.

Read first:
- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_PLAN.md
- docs/qa/PLANNER_OWNED_AGENT_LEGACY_CLEANUP_TRACK.md
- docs/qa/PLANNER_OWNED_AGENT_GRAPH_MIGRATION_TRACK.md
- factory-agent/tests/test_planner_owned_loop_phase15_legacy_cleanup.py
- factory-agent/tests/conftest.py

Scope:
- Implement only Phase 1: Full Legacy And V2 Usage Audit.
- Build a reference inventory with rg and AST/import inspection for direct-v2 loop/runtime helpers, old graph scaffold, working_intents, intent_cursor, intent_completed, legacy_rag_route, v2_shadow, legacy engine trace compatibility, migration-era tests, legacy_architecture_quarantine tests, and frontend hard-query generatedBy/legacy expectation fixtures.
- Classify every hit as active runtime, graph-owned test coverage, persisted-data compatibility, frontend release harness, docs/archive only, deletion candidate, or unknown owner.
- Map each quarantined or migration-era test to replacement graph-owned coverage before proposing any future deletion.
- Record unknown owners instead of guessing.
- Do not delete runtime code.
- Do not delete or rewrite tests.
- Do not change frontend code.
- Do not change backend runtime behavior.
- Do not touch PlannerOwnedAgentGraph runtime.
- Do not modify Qwen/proposer policy.
- Do not alter release harness behavior.

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
- rg -n "PlannerOwnedV2Loop|_create_direct_v2_plan|_execute_direct_v2_steps|attach_direct_v2_trace_to_intent_contract|v2_planner_loop|working_intents|intent_cursor|intent_completed|legacy_rag_route|v2_shadow|test_only_legacy_engine_enabled|legacy_architecture_quarantine" factory-agent docs "eMas Front"
- git diff --check

Commit only if the audit tracker is coherent and diff check passes.

Suggested commit:
docs: audit planner-owned legacy cleanup candidates

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
