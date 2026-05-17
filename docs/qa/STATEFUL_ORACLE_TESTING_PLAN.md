# Stateful Oracle Testing Plan

Created: 2026-05-16

Branch: `codex/playwright-e2e-plan`

Purpose: replace routine manual chatbot validation with tests that can catch real product bugs in LangGraph flow, approvals, final responses, SSE, timeline projection, and browser behavior.

This plan does not replace the existing Playwright/pytest stack. It hardens it. The failure pattern is not a lack of test volume. The failure pattern is weak oracles: tests can pass while the real system is still wrong.

## Critical Diagnosis

Recent bugs show these real gaps:

| Gap | Why Current Tests Missed It | Required Fix |
|---|---|---|
| Stateful backend gap | Fake tools returned fixed rows and did not mutate after commit. | Stateful fake tools must mutate, expire approvals, track audit rows, and expose exact final state. |
| Intermediate-state gap | Tests checked final `COMPLETED`, not each approval/commit boundary. | Assert every transition: prompt, approval 1, commit 1, approval 2, commit 2, final response. |
| Seeded-adapter gap | Seeded Playwright planner behaved differently from real LangGraph. | Add non-seeded LangGraph mechanic tests and at least one non-seeded browser/full-stack smoke for critical flows. |
| Projection gap | Snapshot, SSE, timeline, final response, and UI can be generated from different logic. | Introduce operation invariants and eventually a canonical operation ledger. |
| Live DOM projection gap | Backend snapshot/API evidence can be correct while the browser still renders a stale activity row, stale approval table, or stale final bubble. | Real browser proofs must assert visible DOM text and forbidden stale text, not only API final text. |
| Final-response gap | Final assistant copy can claim success while DB/audit/approval evidence disagrees. | Final response must be derived only after committed state is verified. |
| Aggregate final-response gap | A multi-approval workflow can commit more than one write set but the final assistant recap can describe only the last approval. | Final response oracles must require every committed write set, count, previous state, new state, approval id, and unchanged group to be represented. |
| SSE/timeline gap | EventSource tests can show activity while timeline/snapshot semantics are wrong. | Contract-test SSE, timeline, and snapshot against the same expected event sequence. |
| Prompt wording gap | Exact prompts passed while real operator wording routed differently. | Manual prompt misses must enter a regression bank with parser, route, workflow, and browser coverage. |
| Test-validity gap | A passing test was treated as proof without asking if it could pass while product is wrong. | Every test must answer: what real bug would this catch, and what bug could still slip through? |

## Non-Negotiable Rule

No high-risk scenario is accepted unless it has a state oracle.

For every mutating or multi-step chatbot scenario, the test must define and verify:

- Initial DB or fake-tool state.
- User prompt and mode.
- Expected intent split and route.
- Expected read source groups before writes.
- Expected approval sequence and distinct approval ids.
- Expected DB state after each approval.
- Expected audit rows and idempotency evidence.
- Expected SSE/timeline event sequence.
- Expected snapshot phase/status/pending approval state.
- Expected final assistant summary.
- Expected visible browser UI state.
- Expected unchanged rows.

If a scenario can pass while any of those are wrong, the test is too weak.

## Stop-The-Line Policy

Phase promotion stops when a reproducible defect is found.

- Fix the defect before moving to the next phase.
- Add a regression at the lowest useful layer.
- Rerun the failed phase command plus the fast PR suite.
- If a defect is deferred, record it as an accepted gap with severity, owner, risk, workaround, and target date.
- Do not mark a phase `Done` when critical/high gaps are open.

## Target Architecture

### 1. Scenario Oracle Files

Create machine-readable oracle files, not only prose.

Proposed location:

```text
tests/e2e/scenarios/stateful_oracles/
  priority_cascade_original_state.json
  multi_approval_reject_second.json
  final_response_timeline_consistency.json
  sse_disconnect_recovery.json
  loto_rag_route_machine_present.json
```

Each oracle should include:

```json
{
  "id": "SO-001",
  "title": "Medium to high then original high to medium",
  "risk": "multi-step approval cascade can complete with wrong DB state",
  "prompt": "change all medium priority job to high then change all high priority job to medium",
  "initial_state": {
    "jobs": [
      { "id": "JOB-SEED-001", "priority": "high" },
      { "id": "JOB-SEED-002", "priority": "medium" }
    ]
  },
  "expected_approvals": [
    { "previous_priority": "medium", "new_priority": "high", "row_count": 1 },
    { "previous_priority": "high", "new_priority": "medium", "row_count": 1 }
  ],
  "expected_final_state": {
    "jobs": [
      { "id": "JOB-SEED-001", "priority": "medium" },
      { "id": "JOB-SEED-002", "priority": "high" }
    ]
  },
  "invariants": [
    "no_final_response_before_second_approval",
    "timeline_contains_both_approval_ids",
    "final_summary_matches_committed_rows"
  ]
}
```

### 2. Stateful Test Harness

Add a shared harness for backend and Playwright tests.

Responsibilities:

- Seed fake or real DB state.
- Execute reads and writes through the same tool abstraction the graph uses.
- Mutate fake state after commit.
- Track audit rows.
- Track approval lifecycle.
- Track SSE/timeline emissions.
- Export debug evidence when a test fails.

Possible files:

```text
factory-agent/tests/support/stateful_oracle_harness.py
factory-agent/tests/support/operation_assertions.py
eMas Front/e2e/support/statefulOracleScenarios.js
eMas Front/e2e/support/operationOracle.js
```

### 3. Operation Ledger Contract

The long-term product fix should be a canonical operation ledger. Until then, tests should enforce the same invariants across existing tables and projections.

Canonical event types:

```text
operation_started
intent_split
tool_read_started
tool_read_completed
approval_requested
approval_decided
commit_started
commit_completed
next_intent_started
final_response_created
operation_completed
operation_failed
```

Every event should carry:

```text
session_id
operation_id
plan_id
plan_version
intent_id
step_id
approval_id
sequence_number
status
payload
created_at
```

Final response, snapshot, SSE, activity timeline, and browser UI should all be derivable from this event sequence.

### 4. Invariant Library

Create reusable assertions rather than copy-pasting fragile checks.

Required invariants:

| Invariant | Meaning |
|---|---|
| `no_final_before_terminal` | Final assistant response is not visible before all required approvals and commits finish. |
| `approval_ids_are_distinct` | Multi-approval chains use separate approval ids and do not replay stale ids. |
| `pending_approval_matches_snapshot` | DB pending approval, snapshot pending approval, and UI card agree. |
| `commit_matches_approval_bundle` | Committed rows exactly match approved bundle rows. |
| `final_summary_matches_commits` | Final assistant summary cannot claim rows that were not committed. |
| `timeline_contains_transition_chain` | Timeline includes expected approval, commit, and terminal events in order. |
| `sse_matches_snapshot` | SSE activity eventually matches snapshot timeline/progress state. |
| `original_state_semantics` | Cascading source sets are captured before any write unless explicitly marked current-state. |
| `no_generic_error_on_expected_success` | Successful routed prompts never show `Factory Agent needs attention`. |
| `no_real_llm_in_deterministic_ci` | PR, seeded, and oracle suites do not depend on live model output. |

## Phased Implementation

### Phase 0: Test Reality Audit

Goal:

Find tests that give false confidence.

Files likely touched:

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `factory-agent/tests/`
- `eMas Front/e2e/specs/`
- `eMas Front/e2e/support/`
- `tests/e2e/scenarios/manual_prompt_regressions.json`

Implementation steps:

- Classify current tests by layer: parser, graph mechanic, API, seeded full-stack, mocked browser, release, synthetic.
- Mark each high-risk test as strong, weak, duplicate, or missing oracle.
- For each weak test, record what bug could pass unnoticed.
- Identify top 20 high-risk scenarios needing state oracles.
- Mark existing `Done` claims as insufficient where only final `COMPLETED` was asserted.

Acceptance criteria:

- Tracker lists weak-oracle tests and replacement action.
- Top 20 scenarios are selected and ordered by risk.
- No product code changes yet.

Verification command:

```powershell
git status --short
rg -n "COMPLETED|WAITING_APPROVAL|approval_id|timeline|pending_approval" "factory-agent/tests" "eMas Front/e2e"
```

Risks:

- Audit may reveal many `Done` tests are shallow. That is useful, not failure.

### Phase 1: Oracle Schema and Scenario Bank

Goal:

Create the source of truth for hard scenarios.

Files likely touched:

- `tests/e2e/scenarios/stateful_oracles/*.json`
- `docs/qa/manual_prompt_regression_bank.md`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `factory-agent/tests/test_stateful_oracle_schema.py`

Implementation steps:

- Define oracle JSON schema.
- Add schema validation tests.
- Add the first 20 oracles from the scenario list below.
- Include exact manual failures and observed failure notes.
- Require each oracle to name the lowest required test layer.

Acceptance criteria:

- Oracle files validate.
- Every critical manual failure has an oracle entry.
- Each oracle states what would make the scenario fail.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_stateful_oracle_schema.py -q
```

Risks:

- Too much prose and not enough machine-readable data will recreate the current problem.

### Phase 2: Stateful Fake Tool and Commit Harness

Goal:

Make fake tests behave like a real mutable backend.

Files likely touched:

- `factory-agent/tests/support/stateful_oracle_harness.py`
- `factory-agent/tests/test_phase5_final_validator.py`
- `factory-agent/tests/test_planner_phase3.py`
- `factory-agent/factory_agent/testing_seeded_adapters.py`

Implementation steps:

- Build stateful fake jobs, machines, approvals, audit rows, and transaction commit behavior.
- Reads must reflect previous commits.
- Commits must mutate state and append audit rows.
- Replays must be idempotent.
- Partial failures must record exact per-row results.
- Replace fixed fake rows in critical graph tests.

Acceptance criteria:

- A test fails if approval 2 reads newly mutated state when original-state semantics are expected.
- The exact priority cascade bug cannot reappear without a failing test.
- The harness can simulate partial failure, stale approval, double-click, and timeout.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_phase5_final_validator.py tests/test_planner_phase3.py -q
```

Risks:

- Overbuilding the fake backend. Keep it small and oracle-driven.

### Phase 3: LangGraph State Machine Invariants

Goal:

Catch multi-step and multi-approval bugs before browser tests.

Files likely touched:

- `factory-agent/factory_agent/graph/nodes/planner_loop.py`
- `factory-agent/factory_agent/graph/nodes/tool_pipeline.py`
- `factory-agent/factory_agent/graph/nodes/validate.py`
- `factory-agent/factory_agent/graph/planner_graph.py`
- `factory-agent/tests/test_langgraph_state_machine_oracles.py`

Implementation steps:

- Add tests for intent cursor movement after commit.
- Add tests for staged write clearing after commit.
- Add tests for next active intent selection.
- Add tests for approval rejection and no hidden continuation.
- Add tests for approval expiry and stale resume.
- Add tests for no final response when another active intent remains.

Acceptance criteria:

- Multi-step workflows prove every intermediate transition.
- `COMPLETED` cannot happen while an approval, staged write, or active intent remains.
- Regressions fail in pytest before needing browser reproduction.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_langgraph_state_machine_oracles.py tests/test_phase5_final_validator.py -q
```

Risks:

- Some current code may need product fixes, not test fixes.

### Phase 4: Snapshot, Timeline, and Final Response Contract

Goal:

Stop final response, snapshot, timeline, and UI from disagreeing.

Files likely touched:

- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/analysis/summary_backend.py`
- `factory-agent/factory_agent/graph/approval_summary.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs`

Implementation steps:

- Add backend contract tests that load a snapshot after each oracle transition.
- Assert pending approval visibility matches approval table state.
- Assert final response exists only after terminal operation state.
- Assert final response text matches committed row counts and ids.
- Assert timeline contains approval ids and commit/terminal evidence.
- Add frontend turn/timeline assembly tests for the same snapshots.

Acceptance criteria:

- A completed snapshot with wrong final summary fails.
- Timeline cannot omit approval 2 for multi-approval flows.
- UI assembly cannot display a stale previous answer as the new final response.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_snapshot_timeline_final_response_contract.py -q
Set-Location "..\\eMas Front"
npm test
```

Risks:

- Existing snapshot projection may need refactoring toward a ledger model.

### Phase 5: SSE Contract and Disconnect Semantics

Goal:

Prove streaming behavior is correct, not just visually busy.

Files likely touched:

- `factory-agent/factory_agent/api/routers/events.py`
- `factory-agent/tests/test_event_stream_runtime.py`
- `eMas Front/e2e/fixtures/sseScripts.js`
- `eMas Front/e2e/specs/full-stack-sse-hard.spec.js`
- `eMas Front/e2e/specs/chat-sse-activity.spec.js`
- `eMas Front/src/components/features/chat/factory-agent/useActivityStream.js`
- `eMas Front/src/components/features/chat/factory-agent/useSessionEvents.js`

Implementation steps:

- Assert SSE event ids are monotonic per stream.
- Assert reconnect with `Last-Event-ID` does not duplicate activity.
- Assert malformed events are ignored and next valid event still updates.
- Assert stream close triggers polling or safe diagnostic.
- Assert navigation/close disconnects EventSource.
- Assert SSE progress never creates final UI before snapshot terminal state.

Acceptance criteria:

- SSE, snapshot, and timeline agree for every oracle scenario with streaming.
- Disconnect and reconnect are observable in test artifacts.
- No infinite busy UI after stream interruption.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_event_stream_runtime.py -q
Set-Location "..\\eMas Front"
npm run test:e2e -- --project=chromium --grep "@sse"
npm run test:e2e -- --project=chromium-seeded --grep "@sse|@l3-hard"
```

Risks:

- Browser EventSource and polling fallback can diverge. Both modes need coverage.

### Phase 6: Seeded Full-Stack Data and Audit Oracles

Goal:

Prove real Factory Agent plus seeded Go API commits exactly what the oracle expects.

Files likely touched:

- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js`
- `eMas Front/e2e/support/dataIntegrityScenarios.js`
- `eMas Front/e2e/support/promptRegressionScenarios.js`
- `factory-agent/factory_agent/testing_seeded_adapters.py`
- `emas/cmd/e2e_server`

Implementation steps:

- Reset seeded DB per scenario.
- Capture initial DB state before prompt.
- Drive scenario through seeded full-stack APIs.
- Assert approval rows, audit rows, DB rows, timeline, snapshot, and final summary.
- Add exact unchanged-row assertions.
- Export artifacts on failure: initial state, approval table, final state, snapshot, timeline, browser text.

Acceptance criteria:

- Data integrity scenarios cannot pass with wrong committed rows.
- Cascades use original-state semantics unless oracle explicitly says current-state.
- Partial failure cannot claim full success.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity|@prompt-regression"
```

Risks:

- Seeded adapters can drift from real LangGraph. Critical scenarios still need Phase 7.

### Phase 7: Non-Seeded LangGraph Browser Proof

Goal:

Prove the browser can surface critical real LangGraph behavior, not only seeded adapters.

Files likely touched:

- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`
- `eMas Front/e2e/support/startRealLangGraphStackForPlaywright.js`
- `factory-agent/tests/test_phase5_final_validator.py`
- `TRACK.md` or this tracker

Implementation steps:

- Start seeded Go API.
- Start Factory Agent with real LangGraph planner path and fake deterministic model disabled where deterministic graph mechanics apply.
- Prepopulate tool registry correctly.
- Drive the browser through the top 5 critical workflows.
- Assert approval card order, final UI, backend DB state, and no generic success/error mismatch.

Acceptance criteria:

- The exact cascade prompt shows approval 1, approval 2, then final completion.
- Final browser text and DB state match the oracle.
- This test is opt-in or release-gate only until runtime is stable.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-real-langgraph --grep "@critical"
```

Risks:

- Startup is heavier than seeded tests.
- This must not become the default PR gate until stable.

### Phase 8: Manual Failure Promotion Workflow

Goal:

Every manual failure becomes a permanent regression.

Files likely touched:

- `docs/qa/manual_prompt_regression_bank.md`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `tests/e2e/scenarios/stateful_oracles/*.json`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`

Implementation steps:

- Add a required bug intake template.
- Record exact prompt, observed failure, expected behavior, layer, owner, severity, and reproduction artifact.
- Add a failing test before or with the fix.
- Close only after the oracle passes at the lowest useful layer.

Acceptance criteria:

- No manual failure can be closed as "tested manually only".
- Regression bank maps each bug to a test file and command.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_phase18_manual_prompt_bank.py tests/test_stateful_oracle_schema.py -q
```

Risks:

- Bank can become noisy. Only add wording variants that expose distinct parser, route, state, SSE, or UI risks.

### Phase 9: CI Gate Restructure

Goal:

Make the right tests block the right changes.

Files likely touched:

- `.github/workflows/*.yml`
- `eMas Front/package.json`
- `eMas Front/playwright.config.js`
- `docs/operations/chatbot_release_runbook.md`

Implementation steps:

- Keep fast mocked Chromium on every PR.
- Add backend oracle pytest group on every PR.
- Add seeded full-stack oracle group on release branches or pre-merge gate.
- Keep real LangGraph browser as opt-in or release gate.
- Keep synthetic production checks safe and read-only.
- Upload oracle artifacts on every failure.

Acceptance criteria:

- A broken state-machine invariant blocks PR.
- A broken seeded data integrity oracle blocks release.
- Production synthetic does not mutate data.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_langgraph_state_machine_oracles.py tests/test_snapshot_timeline_final_response_contract.py -q
Set-Location "..\\eMas Front"
npm test
npm run test:e2e -- --project=chromium
npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity|@prompt-regression|@sse"
```

Risks:

- Too many slow gates will be skipped by developers. Separate fast PR gates from release gates.

### Phase 10: Ledger Refactor Decision

Goal:

Decide whether the product needs a real operation ledger implementation.

Files likely touched if implemented:

- `factory-agent/factory_agent/persistence/models.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/api/routers/events.py`
- `factory-agent/factory_agent/graph/nodes/*.py`
- Migration files or schema scripts

Implementation steps:

- Review Phase 3-6 failures.
- If projection mismatch remains common, implement a durable operation ledger.
- Make snapshot, SSE, timeline, and final response read from ledger-derived state.
- Keep old tables as source data only where needed.

Acceptance criteria:

- One canonical event sequence can reconstruct visible operation state.
- No duplicate business logic for final response, SSE, timeline, and snapshot terminal state.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_snapshot_timeline_final_response_contract.py tests/test_event_stream_runtime.py -q
```

Risks:

- Ledger is a product refactor. Do it only if invariant tests show projection fixes are becoming fragile.

Phase 10 decision, 2026-05-16:

Do not implement a durable operation ledger in this phase. The current projection model is acceptable for now because Phases 3-9 converted the known projection risks into invariant-backed oracle gates, and the latest focused checks still pass. Keep the ledger as a reopening option, not as immediate product work.

Evidence:

- Phase 3 found no product defect in the LangGraph state-machine invariant pass; it proved cursor advancement, staged-write cleanup, rejection/timeout boundaries, distinct approvals, and original-state cascade semantics before browser execution.
- Phase 4 found and fixed a frontend projection bug where a stale terminal event from approval 1 could outrank a newer pending approval 2; the backend contract now rejects empty/missing timeline evidence, premature final response ordering, duplicate SSE ids, stale approval ids, and false success wording.
- Phase 5 found and fixed an SSE reconnect defect where an unknown `Last-Event-ID` could suppress current evidence; runtime and browser checks now require monotonic unique activity ids, snapshot invalidation, malformed-frame recovery, stream-drop polling, and snapshot-gated final UI.
- Phase 6 found and fixed backend snapshot projection bugs: approval-wait copy was projected as `session_completed`, plan rows could be backdated before approval/commit evidence, and commit tool results lacked ordered approval-id evidence.
- Phase 7 found real LangGraph evidence bugs: truncated committed audit steps, missing commit outputs, capped completed bulk audit persistence, and raw-output final assistant text. The SO-001 real LangGraph browser proof now ties DB rows, approvals, snapshot/timeline/activity, audit-plan rows, final text, and visible UI together.
- Phase 9 moved the fast state-machine and snapshot/final-response oracles into the PR gate and kept seeded plus real LangGraph gates available for release/pre-merge or explicit dispatch.

Projection audit:

- `session_snapshot_service.py` remains the canonical server projection for snapshot, timeline, activity, pending approval, effective status, and final completion content. It derives from existing durable rows: sessions, messages, plans, plan steps, approvals, execution snapshots, and workflow checkpoints.
- `events.py` does not maintain separate business state; notification, activity, and semantic SSE streams poll the same snapshot projection and apply reconnect/duplicate filtering only.
- `summary_backend.py` and `approval_summary.py` format approval and final-response copy from structured bundle/tool facts; they do not decide terminal state.
- The frontend still has fallback timeline/activity/turn assembly logic for stale or older snapshots, but the server `activity_steps` and timeline are preferred, and frontend tests assert that final UI stays terminal-gated.

Remaining risks:

- The projection is still synthesized from several durable tables plus LangGraph checkpoint data, so a new workflow shape can introduce another mapping edge case.
- Frontend fallback projection can drift from the server projection if new event types are added without paired unit fixtures.
- Real LangGraph browser coverage currently proves SO-001 only; more non-seeded browser cases are still backlog.
- There is no append-only event history for forensic reconstruction beyond the existing tables/checkpoint/audit evidence.

Guardrail tests that must stay in CI:

- PR gate: `python -m pytest tests/test_langgraph_state_machine_oracles.py tests/test_snapshot_timeline_final_response_contract.py -q`.
- Focused SSE regression: `python -m pytest tests/test_event_stream_runtime.py -q`.
- Release/pre-merge gate: `npm run test:e2e:seeded-oracles`.
- Explicit release/dispatch proof: `npm run test:e2e:real-langgraph`.
- Frontend projection guard: `npm test`.

Reopen the durable ledger decision if any of these happen:

- A projection bug recurs after the relevant invariant was already in CI.
- Snapshot, SSE, timeline, final assistant response, and browser UI require a third independent implementation of terminal/approval/commit semantics.
- A new workflow needs forensic replay of intermediate operation state that cannot be reconstructed from existing rows, checkpoints, audit rows, and oracle artifacts.
- Seeded or real LangGraph gates start requiring brittle timestamp or ordering workarounds to keep projections aligned.
- More than two Phase 10-style projection bugs appear in one release cycle.

### Phase 11: Aggregate Final-Response Evidence Oracles

Goal:

Make final assistant responses prove the whole completed operation, not just the newest approval or the prettiest table.

New manual miss that opens this phase:

```text
change all medium priority job to high then change all high priority job to low
```

Observed risk:

- The prompt splits into two valid write intents: original medium -> high, then original high -> low.
- The visible final response can report only the high -> low write set, for example "Updated 10 job(s)" with only previous high/new low rows.
- If the first approval committed, this is a summary/projection defect. If the first approval did not commit, this is a graph execution defect. The phase must distinguish those two cases with evidence.
- This is not expected to be an LLM-quality issue in deterministic mode because `summary_backend.py` formats completed job recaps from structured `tool_outputs`; the likely failure surfaces are missing/partial commit outputs, plan persistence, snapshot projection, or frontend turn assembly.

Files likely touched:

- `factory-agent/factory_agent/analysis/summary_backend.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/graph/planner_graph.py`
- `factory-agent/factory_agent/graph/nodes/validate.py`
- `factory-agent/tests/test_summary_bundle.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `factory-agent/tests/test_langgraph_state_machine_oracles.py`
- `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs`
- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`
- `tests/e2e/scenarios/stateful_oracles/`
- `tests/e2e/scenarios/manual_prompt_regressions.json`

Implementation steps:

- Add the manual miss to the prompt regression bank before changing product behavior.
- Add a new oracle, `SO-041`, for medium -> high then original high -> low.
- Reproduce at the lowest useful layer and record whether approval 1 actually commits:
  - If DB/audit rows include medium -> high but final copy omits it, fix aggregate summary/projection.
  - If DB/audit rows do not include medium -> high, fix LangGraph planning/execution before summary work.
- Strengthen deterministic final-response generation so a completed multi-write-set operation includes:
  - all committed write sets,
  - row counts per write set,
  - previous priority and new priority per write set,
  - both approval ids,
  - unchanged source groups when the oracle requires them,
  - partial-failure or rejection wording when applicable.
- Add a negative-control test proving a final response that only mentions the last approval fails.
- Extend seeded cascade matrix coverage to include medium -> high then original high -> low if it is not already represented.
- Add one real LangGraph browser proof for `SO-041` after the backend oracle is green.
- Update frontend turn/activity tests so stale or partial final summaries cannot outrank complete aggregate terminal evidence.
- Add server and frontend activity tests proving a pending approval remains the current activity row even if a later stale `replan_requested`/`Improving the response` event is present.
- Add browser-visible assertions for approval 2 and final completion: no `Improving the response / Current` row while approval 2 is pending, no stale approval 1 text beside approval 2, and no final stale approval-decision/table copy after completion.

Acceptance criteria:

- The exact prompt above cannot pass with a final response that mentions only high -> low.
- The final assistant response, activity timeline, SSE/snapshot terminal event, DB state, audit rows, and approval rows all agree on both write sets.
- If original-state semantics are used, original medium jobs end high and original high jobs end low; newly-high rows from approval 1 are not included in approval 2.
- A response that says only `Updated 10 job(s)` for the second approval fails the oracle when approval 1 also committed.
- While approval 2 is pending, the visible browser summary, details, table, and approval card must all match approval 2. Stale approval 1 decision/waiting text must not be paired with approval 2's table.
- While approval 2 is pending, the activity timeline current row must be `Waiting for your approval`; a later `Improving the response` row must not be marked `Current`.
- Manual collapse of the active activity timeline must remain collapsed across snapshot/SSE refreshes until terminal state or a new user action changes the operation.
- After final completion, the visible browser response must show the aggregate final summary and must not render `Approved request to change record`, `Waiting for your approval`, `Please approve to continue`, or an approval-2-only `Affected records (11)` table as the final result.
- If the product intentionally chooses current-state semantics for this wording, the oracle must state that explicitly and prove the final response says the second step included newly changed rows. Silent ambiguity is not accepted.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_summary_bundle.py tests/test_snapshot_timeline_final_response_contract.py tests/test_langgraph_state_machine_oracles.py -q
Set-Location "..\eMas Front"
npm test
npm run test:e2e:real-langgraph -- --grep "SO-041"
```

Risks:

- This may reopen the Phase 10 ledger decision if the only way to build a truthful aggregate final response is to reconstruct operation history from too many independent projections.
- The first run should be expected to fail. Do not weaken the oracle to match the current output.

## Phase 12: Executable Enforcement Closure

Clarification: an SO JSON file is not considered complete unless an executable test reads or names that SO id and enforces the contract.

Phase 12 adds an `executable_enforcement` block to every current oracle file under `tests/e2e/scenarios/stateful_oracles/`. The block records:

- the backend pytest contract that loads the oracle and verifies snapshot, timeline, approval, audit, final-state, and final-response invariants;
- any lower-layer pytest needed for graph, route, parser, or API/UI projection behavior;
- the browser proof when the defect can render differently in the DOM than in backend snapshot text;
- the manual prompt regression mapping when the scenario comes from a manual prompt miss.

The common backend gate is:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_snapshot_timeline_final_response_contract.py::test_all_stateful_oracle_files_have_executable_snapshot_final_response_contract -q
```

Additional Phase 12 targeted gates:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_langgraph_state_machine_oracles.py::test_priority_cascade_oracles_use_original_state_for_second_write_set -q
python -m pytest tests/test_phase7_api_ui_alignment.py::test_so012_semantic_timeline_projection_keeps_both_approval_ids tests/test_phase7_api_ui_alignment.py::test_so013_activity_suppresses_completion_until_terminal_snapshot -q
python -m pytest tests/test_phase19_prompt_workflow_regression.py::test_so021_so025_prompt_oracles_route_loto_to_rag_with_machine_id -q
```

Browser tests must assert visible DOM text and forbidden stale text. Snapshot JSON or final assistant API text alone is not enough for browser closure.

### Phase 13: Test Quality Gate and Redundancy Control

Goal:

Keep the growing oracle suite sharp enough to find real bugs without becoming slow, repetitive, or hard to debug.

This phase does not delete existing coverage by default. It classifies coverage, keeps useful cross-layer overlap, and blocks future scenario additions that do not prove a distinct risk.

Files likely touched:

- `docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `tests/e2e/scenarios/stateful_oracles/*.json`
- `factory-agent/tests/test_stateful_oracle_schema.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js`
- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`

Implementation steps:

- Build a coverage map for every current SO id:
  - primary risk,
  - lowest useful layer,
  - backend enforcement command,
  - browser enforcement command if UI can diverge,
  - real LangGraph requirement if seeded coverage can hide planner behavior,
  - whether the scenario is smoke, contract, regression, release, or diagnostic.
- Mark each test as one of:
  - `canonical`: the main proof for this risk,
  - `supporting`: catches a different layer of the same risk,
  - `smoke`: useful for broad confidence but not proof,
  - `duplicate_candidate`: appears to check the same layer and same assertion as another test.
- Do not remove a test unless another test proves the same risk at the same or stronger layer and the tracker records why removal is safe.
- Add an authoring rule for future SO and manual prompt entries:
  - every new scenario must state the real bug it would catch,
  - the lowest useful layer must fail first,
  - browser tests are required only when visible DOM can differ from backend evidence,
  - real LangGraph is required only when seeded adapters can hide planning/routing/tool-selection behavior,
  - every browser proof must include at least one positive visible assertion and one forbidden stale-text assertion when stale UI is a known risk.
- Split future CI expectations into three lanes:
  - fast PR gate: schema, backend oracle contracts, frontend unit/component, mocked Chromium smoke,
  - deterministic release/pre-merge gate: seeded Playwright stateful oracles,
  - opt-in/nightly gate: real LangGraph, synthetic/read-only production checks, and slow visual/debug sweeps.
- Add a short scenario-author checklist to the manual prompt regression bank so future agents know how to add useful cases without rediscovering the test strategy.
- Record any deliberate redundancy as useful only when it catches a different failure mode, for example backend DB/audit evidence vs. visible browser stale timeline.

Acceptance criteria:

- The tracker names the canonical enforcement layer for every current high-risk group before more scenarios are added.
- Future agents can decide whether a new scenario belongs in parser, route, graph, snapshot, seeded browser, real LangGraph, or production synthetic coverage without asking.
- Redundant tests are classified before deletion; no useful cross-layer guard is removed.
- Each new scenario must answer: "What product bug would this test catch that existing tests would miss?"
- SO browser tests continue to assert visible DOM and forbidden stale text where UI projection is a risk.
- Slow real LangGraph tests remain targeted to planner/routing/execution risks, not used as a blanket duplicate of seeded flows.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_stateful_oracle_schema.py tests/test_phase18_manual_prompt_bank.py tests/test_snapshot_timeline_final_response_contract.py::test_all_stateful_oracle_files_have_executable_snapshot_final_response_contract -q
Set-Location "..\eMas Front"
node --check "e2e/specs/full-stack-data-integrity.spec.js"
node --check "e2e/specs/full-stack-prompt-workflow-regression.spec.js"
```

Risks:

- Over-deduplication can remove the exact layer that catches UI-only or projection-only bugs.
- Keeping every similar test forever will slow CI and make failures harder to triage.
- Real LangGraph coverage is expensive and should be selected by risk, not by a desire for more test count.

Rollback notes:

- If this phase accidentally weakens confidence, restore the removed or downgraded test and record why the overlap was useful.
- If a future manual bug escapes because a test was classified as duplicate, reopen Phase 13 and promote that failure into a canonical or supporting oracle.

### Phase 13 Next Batch Application

The next chatbot automation batch applies the quality gate to the highest-risk remaining gaps instead of adding prompt-volume tests:

| SO | Decision | Lowest useful layer | Browser? | Real LangGraph? | Coverage category |
|---|---|---|---|---|---|
| SO-018 | Strengthen active-refresh proof so the same pending approval id, single approval card, staged bundle, DB rows, and audit rows survive refresh and mutate only after approval. | Seeded browser | Yes | No | `canonical` |
| SO-030 | Strengthen stream-drop recovery proof so polling cannot fabricate success before terminal snapshot, and timeline/snapshot/final/UI agree after commit. | Seeded full-stack | Yes | No | `canonical` |
| SO-029 | Promote approved mid-run Go API 500 to seeded full-stack proof: no generic success, no data-integrity audit rows, unchanged DB rows, and visible retry guidance. | Seeded full-stack plus frontend unit | Yes | No | `canonical` |
| SO-020 | Strengthen the existing empty-final browser/component proof so empty terminal content renders an explicit diagnostic, not stale prior answer text or generic fake success. | Frontend unit | Yes | No | `supporting` |
| SO-021 / SO-025 | Do not add new real LangGraph/browser wording variants in this batch. Current parser/route and seeded browser coverage remain canonical unless a planner/RAG miss escapes seeded coverage. | Parser/route | Existing seeded browser only | No | `canonical` |

### Phase 14: Release Gate Validation

Goal:

Validate whether the automated chatbot pipeline is ready to replace routine manual release testing.

This phase is a release-sweep phase, not a scenario-volume phase. Do not add new scenarios first. Run the intended gate, classify failures as product bugs or test bugs, fix product bugs before continuing, and record the release decision in the tracker.

Required release-sweep commands:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_stateful_oracle_schema.py tests/test_phase18_manual_prompt_bank.py tests/test_stateful_oracle_harness.py tests/test_langgraph_state_machine_oracles.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py tests/test_phase19_prompt_workflow_regression.py tests/test_summary_bundle.py tests/test_event_stream_runtime.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:mocked
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
npm run test:e2e -- --project=chromium-release
npm run test:e2e:synthetic
```

Acceptance criteria:

- Backend oracle/schema/manual-bank coverage is green.
- Frontend unit/component coverage is green.
- Mocked Chromium PR smoke is green.
- Seeded Playwright oracle coverage is green.
- Focused real LangGraph critical coverage is green.
- Configured release, SSE, polling, and read-only synthetic checks are green.
- Product bugs found by the sweep are fixed before final readiness is claimed.
- Test bugs found by the sweep are fixed or recorded with owner, risk, and blocking status.
- Remaining manual-only work is limited to semantic/product judgment, compliance sign-off, exploratory discovery, or emergency incident diagnosis.

Phase 14 result on 2026-05-17:

- The gate is green after fixes.
- One product bug was fixed: operator cancellation terminal copy was hidden by stale active-plan copy in frontend turn assembly.
- Two release-smoke test bugs were fixed: stale mobile approval-copy assertion and hidden long-stream summary assertion.
- No release-blocking automated coverage gaps remain for routine chatbot release regression.

### Phase 15: CI/Release Enforcement and Ownership

Goal:

Turn the completed chatbot testing pipeline into a release operating model with explicit command lanes, blocking levels, owners, and failure triage rules. This phase does not add new product scenarios.

Files likely touched:

- `.github/workflows/playwright-e2e.yml`
- `.github/workflows/playwright-reliability-soak.yml`
- `eMas Front/package.json`
- `docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Implementation steps:

- Inspect existing package scripts, CI workflows, Playwright projects, and pytest config.
- Make the default backend oracle alias match the full Phase 14 fast backend gate.
- Add only command aliases that follow the existing `test:e2e:*` convention.
- Promote seeded, real LangGraph, and release validation to blocking release/pre-merge CI lanes.
- Keep synthetic checks read-only and separate from mutating release gates.
- Document owners, blocking level, triage rule, runtime evidence, and manual-only checks.

Final command lanes:

| Lane | CI trigger | Local command | Blocking level | Owner | Runtime evidence |
|---|---|---|---|---|---|
| PR fast deterministic | Pull request and protected branch push in `Chatbot Oracle Gates` | `npm run test:backend-oracles`; `npm test`; `npm run test:e2e:mocked` | Blocks PR merge | Factory Agent QA/backend owner, frontend chat owner, frontend E2E owner | Phase 14: backend 4.76s, frontend unit 15.77s, mocked Chromium 31.69s |
| Release/pre-merge deterministic | Push to `main`, `release/**`, or `pre-merge/**`; explicit dispatch | `npm run test:e2e:seeded-oracles`; `npm run test:e2e:real-langgraph`; `npm run test:e2e:release` | Blocks release/pre-merge signoff | Seeded L3 owner, Factory Agent/LangGraph owner, release L4 owner | Phase 14: seeded 179.66s, real LangGraph 18.29s, release 36.24s |
| Nightly/operational | Scheduled reliability workflow or manual operational readiness dispatch | `npm run test:e2e:reliability`; `npm run test:e2e:reliability:seeded`; `npm run test:e2e:operational`; `npm run operational:gate` | Blocks operational signoff; blocks release only when the owner promotes the failure to a release exception | Reliability owner, operational readiness owner, QA governance owner | Runtime varies by scheduled matrix; use workflow artifacts and `operational-gate-results.json` |
| Synthetic read-only | Explicit synthetic dispatch, post-deploy monitor, or live read-only canary schedule | `npm run test:e2e:synthetic` | Does not block PR; local harness failure blocks synthetic lane; live critical alert pages `chatbot-oncall` and can block rollout/rollback decision | Synthetic L5 owner / `chatbot-oncall` | Phase 14 local harness: 41.94s |

Ownership and blocking rules:

| Failure class | Blocking rule | Owner | Failure triage rule |
|---|---|---|---|
| Backend oracle/schema/manual-bank failure | Blocks PR and release. | Factory Agent QA/backend owner. | Reproduce with the focused pytest file or SO id, classify product vs test bug, fix before merge, and rerun `npm run test:backend-oracles` plus any touched focused command. Critical/high mutating gaps are not accepted without an explicit release exception. |
| Frontend unit/component failure | Blocks PR and release. | Frontend chat owner. | Reproduce with `npm test` or the focused `node --test` command, identify stale UI/projection/interaction risk, and rerun `npm test` plus mocked Chromium when visible behavior can diverge. |
| Seeded Playwright oracle failure | Blocks release/pre-merge. | Seeded full-stack L3 owner. | Inspect seeded stack artifacts, DB rows, audit rows, approvals, snapshot, timeline, and final UI. A mismatch between visible success and persisted state is a product bug unless proven to be a harness/test bug. |
| Real LangGraph failure | Blocks release/pre-merge. | Factory Agent/LangGraph owner. | Compare seeded and real-LangGraph evidence. If seeded passes but real fails, triage planner/tool-selection/routing/checkpoint behavior before changing browser assertions. |
| Synthetic read-only monitor failure | Does not block PR. Local harness failures block the synthetic lane; live critical failures page `chatbot-oncall` and can block rollout or trigger rollback. | Synthetic L5 owner / `chatbot-oncall`. | Confirm the prompt is read-only, inspect redacted synthetic artifacts and alert code, classify dependency outage vs product regression, and never add mutating synthetic coverage. |
| Accepted gap | Critical/high mutating gaps block release unless the tracker records an approved exception. Medium/low gaps need owner, risk, target, reason, and workaround. | QA governance owner. | Review weekly until closed or until two clean release cycles prove the gap no longer applies. |

Remaining manual-only checks:

- Nuanced answer quality, tone, and domain usefulness beyond structural assertions.
- Compliance or regulated wording sign-off.
- Exploratory discovery for brand-new workflows or unmodeled operational risk.
- Emergency incident diagnosis when automation, harnesses, or telemetry are unavailable.

Acceptance criteria:

- PR failures in backend oracles, frontend unit/component tests, or mocked Chromium block merge.
- Release/pre-merge failures in seeded Playwright, real LangGraph, or release validation block signoff.
- Synthetic live failures stay read-only, alert the owner, and never mutate production data.
- Accepted gaps have owner, severity, risk, workaround, target, and blocking status.
- Routine manual chatbot regression is not a release gate.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:backend-oracles
npm test
npm run test:e2e:mocked -- --list
npm run test:e2e:seeded-oracles -- --list
npm run test:e2e:real-langgraph -- --list
npm run test:e2e:release -- --list
npm run test:e2e:synthetic -- --list
npm run test:e2e:reliability -- --list
npm run test:e2e:reliability:seeded -- --list
node --check "playwright.config.js"
node --check "e2e/support/operationalGate.js"
```

### Phase 16: Remaining Normal-Use Breakage Scenarios

Goal:

Add a small, high-risk normal-use batch that covers remaining parser/route, multi-turn context, cancellation, and large-result breakage after Phase 15. This phase follows the Phase 13 quality gate and does not add redundant browser tests for wording-only variations.

Intended scope:

| SO | Distinct product bug it catches | Existing gap | Lowest useful layer | Browser required | Real LangGraph required | Coverage category |
|---|---|---|---|---|---|---|
| SO-022 | Missing-machine LOTO prompt invents `M-CNC-01`, claims sources, or completes as a successful LOTO answer. | Successful LOTO tests all include a machine id. | Parser/route | Yes, because final visible copy and source chrome can diverge from backend route evidence. | No. | `canonical` |
| SO-023 | Lowercase punctuation-free `m-cnc-01` LOTO wording loses normalization or asks for the ID again. | Prior lowercase bank entry used slash wording and was not a named SO-023 oracle. | Parser/route | Yes through the existing LOTO bank browser loop, because source chrome/final text are user-visible. | Optional only if parser/route cannot prove real planner normalization. | `canonical` |
| SO-026 | Follow-up `it` after a completed machine-status turn clarifies, reuses stale status, or routes to machine status instead of LOTO/RAG. | Single-turn LOTO tests cannot prove previous-turn context is applied before the LOTO short-circuit. | Parser/context route | Yes, because stale final response and snapshot/UI can diverge from route evidence. | Yes after seeded passes. | `canonical` |
| SO-028 | Cancelling an executing seeded graph leaves a hidden continuation that later fabricates success or mutates state. | Mocked cancel/navigation tests do not prove backend state after the long-running seeded fixture would have completed. | Seeded full-stack | Yes, because cancel button, busy state, final copy, snapshot, and mutation evidence must agree. | No. | `canonical` |
| SO-031 | Large structured results hide terminal state, leave stale loading/current state, or break table/activity controls. | Existing reliability coverage was outside the seeded oracle prompt-regression gate. | Seeded full-stack | Yes, because the risk is layout/visibility/control behavior. | No. | `canonical` |

Required positive evidence:

- SO-022: missing `machine_id` detected; clarification route selected; visible response asks for exact machine ID; no sources/steps; state unchanged.
- SO-023: `m-cnc-01` normalizes to `M-CNC-01`; LOTO/RAG selected; source metadata tied to `LOTO-M-CNC-01`; no clarification.
- SO-026: first turn identifies `M-CNC-01`; second turn resolves `it`; latest answer routes to LOTO/RAG; seeded browser and real LangGraph evidence do not reuse stale status.
- SO-028: cancel visible while executing; terminal snapshot stays `IDLE`/cancelled after the long fixture delay; no audit rows or mutations; final UI says cancelled safely.
- SO-031: 80-row deterministic fixture returns; table and activity controls work; `Run complete` and final response remain visible; snapshot is terminal.

Forbidden stale evidence:

- SO-022: `M-CNC-01`, source metadata, seeded RAG answer, knowledge sources, generic diagnostics, or successful LOTO answer.
- SO-023: machine-ID clarification, machine-status route/copy, or generic diagnostics.
- SO-026: stale machine-status final response as the latest answer, stale snapshot reuse, generic clarification, or status route on the follow-up.
- SO-028: `Run complete`, low-priority completion text, hidden continuation, successful audit rows, busy spinner, or cancel button after terminal cancel.
- SO-031: stale loading/current state, hidden final response, unusable activity/table controls, or generic error UI.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_stateful_oracle_schema.py tests/test_phase18_manual_prompt_bank.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase19_prompt_workflow_regression.py tests/test_phase7_api_ui_alignment.py -q

Set-Location "..\eMas Front"
npm test
npm run test:e2e:seeded-oracles
npx playwright test e2e/specs/full-stack-prompt-workflow-regression.spec.js --project=chromium-seeded --grep "SO-022|SO-023|SO-026|SO-031"
npx playwright test e2e/specs/full-stack-seeded.spec.js --project=chromium-seeded --grep "SO-028"
npm run test:e2e:real-langgraph -- --grep "SO-026"
```

### Phase 17: Security, Privacy, and Abuse Hardening

Goal:

Add the next high-risk chatbot security, privacy, and abuse checks using the Phase 13 quality gate. This phase strengthens existing `@security|@privacy` coverage rather than adding redundant prompt volume.

Intended scope:

| SO | Distinct product bug it catches | Existing gap | Lowest useful layer | Browser required | Real LangGraph required | Coverage category |
|---|---|---|---|---|---|---|
| SO-032 | Switching sessions, refreshing, or restoring history can carry over another session's final response, approval card, source table, audit evidence, or hidden details. | Earlier isolation coverage denied a tampered stored session id but did not switch between valid same-user sessions or exercise table/details/approval cleanup. | Mocked browser | Yes, because stale DOM state is the risk. | No. | `canonical` |
| SO-033 | Missing or invalid auth for REST, snapshot polling, or EventSource can show a retry/error banner while retaining a stale previous assistant response. | API auth probes can pass while the browser still renders a stale transcript after a denied snapshot switch. | API probe plus mocked browser | Yes, because stale visible transcript and retry UI can diverge from API status. | No. | `canonical` |
| SO-042 | Backend/model script-like markdown, image handlers, or unsafe links can execute or create unsafe anchor behavior. | Previous inert-render coverage did not include unsafe HTML links, markdown links, and target-blank behavior. | Mocked browser | Yes, DOM execution/link attributes are browser-only evidence. | No. | `canonical` |
| SO-043 | Very long pasted input can break controlled input state, lose the submitted prompt, leave a spinner stuck, or reuse stale final text. | Large-result tests covered big responses, not large user input lifecycle and request-body preservation. | Mocked browser | Yes, composer state and request lifecycle are visible-browser concerns. | No. | `canonical` |
| SO-044 | Dangerous prompts can bypass approval gates, mutate unsupported production records, or show fake completion. | Earlier allowlist checks did not exercise the exact dangerous operator examples or prove no mutation after an attempted approval. | Mocked browser | Yes, approval card, visible refusal, and request-log no-mutation evidence must agree. | No unless a real planner safety miss appears. | `canonical` |

Required positive evidence:

- SO-032: private evidence is visible before switching; safe session final response is visible after switching and refresh; pending approval from another session disappears.
- SO-033: unauthorized REST, snapshot polling, and EventSource probes are denied; safe retry/error UI appears; composer stays usable.
- SO-042: unsafe script/link/image markdown is visible as inert text; no XSS flags are set; no unsafe anchors exist; layout remains stable.
- SO-043: prompt length exceeds the large-input threshold; mock request log records the submitted length; composer clears and re-enables; no busy spinner remains.
- SO-044: approval gate appears before any action; destructive tool is absent from the allowlist; attempted approval returns safe blocked copy; snapshot has no tool-result mutation.

Forbidden stale evidence:

- SO-032: `PHASE17_LEAK_FINAL`, `PHASE17_LEAK_APPROVAL`, `PHASE17_LEAK_SOURCE_TABLE`, `PHASE17_LEAK_AUDIT_EVIDENCE`, `PHASE17_LEAK_HIDDEN_DETAILS`, or a stale `Approval required` card in the safe session.
- SO-033: prior assistant final response, unauthorized target final response, other-user secret transcript, or `Run complete` after auth failure.
- SO-042: executable `<script>`, `javascript:` links, target-blank links without `noopener`, XSS flags, layout overflow, or generic error UI.
- SO-043: stale previous final answer, stuck spinner, uncleared composer, prompt-length mismatch, layout overflow, or generic error UI.
- SO-044: `Run complete`, `Approved request to change record`, `deleted production`, mutation `tool_result`, `DELETE` requests, or blocked-action audit rows.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium --grep "@security|@privacy"
npm run test:e2e:release -- --grep "@security|@privacy"
```

## First Critical Scenario Set

Implement these before claiming manual chatbot testing is retired.

| ID | Scenario | Primary Bug It Should Catch | Required Layers |
|---|---|---|---|
| SO-001 | Medium priority jobs to high, then original high priority jobs to medium. | Second approval uses newly changed rows or finalizes early. | Pytest graph, seeded full-stack, real LangGraph browser |
| SO-002 | High to low, then original low to medium. | Existing Scenario 86 regression. | Pytest graph, seeded full-stack |
| SO-003 | Low to high, then original high to low. | Swap/cascade source overlap. | Pytest graph, seeded full-stack |
| SO-004 | High to medium, then original medium to low. | Reverse cascade ordering. | Pytest graph, seeded full-stack |
| SO-005 | Approval 1 accepted, approval 2 rejected. | Hidden continuation after rejection. | Pytest graph, dedicated seeded browser |
| SO-006 | Approval 1 accepted, approval 2 timeout. | Session completes despite pending timeout. | Pytest graph, seeded |
| SO-007 | Approval double-click and refresh replay. | Duplicate mutation. | Pytest API, seeded |
| SO-008 | Stale approval after new user revision. | Old approval mutates changed session. | Pytest API, browser |
| SO-009 | Partial bulk commit failure. | Final response claims full success. | Pytest graph, seeded |
| SO-010 | Commit succeeds but audit row missing. | UI success without audit evidence. | Seeded |
| SO-011 | Final response before approval 2 appears. | Premature terminal response. | Pytest snapshot, browser |
| SO-012 | Timeline omits approval 2. | UI loses intermediate approval. | Pytest snapshot, frontend unit |
| SO-013 | SSE sends completion before snapshot terminal. | Browser shows final too early. | SSE pytest, Playwright |
| SO-014 | SSE reconnect duplicates old activity rows. | Duplicate timeline rows. | Playwright SSE |
| SO-015 | SSE malformed payload then valid payload. | Stream crash or stuck UI. | Playwright SSE |
| SO-016 | EventSource disconnect on modal close. | Leaked streams and stale state. | Playwright |
| SO-017 | Static bearer polling fallback. | Auth mode disables streaming without fallback. | Playwright release |
| SO-018 | Browser refresh during active approval. | Lost or duplicated approval. | Playwright seeded |
| SO-019 | Existing completed session restored. | Stale previous answer becomes new answer. | Frontend unit, Playwright |
| SO-020 | Empty final response. | UI shows stale text or fake success. | Frontend unit, Playwright |
| SO-021 | LOTO with `M-CNC-01`. | Machine ID extracted but backend asks again. | Parser, route, seeded browser |
| SO-022 | LOTO missing machine id. | Should clarify honestly. | Parser, route, browser |
| SO-023 | Lowercase/punctuation machine IDs. | Entity extraction failure. | Parser, route, seeded browser |
| SO-024 | Job ID in markdown/quotes/newlines. | Entity extraction failure. | Parser |
| SO-025 | Route confusion: LOTO vs machine status. | Wrong RAG/tool route. | Route pytest, seeded |
| SO-026 | Multi-turn follow-up after completion. | New turn reuses old snapshot. | Parser/context route, seeded browser, real LangGraph browser |
| SO-027 | User sends revision while waiting approval. | Pending approval not invalidated. | Pytest API, browser |
| SO-028 | Cancel during executing graph. | Hidden continuation after cancel. | Seeded full-stack, browser |
| SO-029 | Go API 500 mid-run. | Generic success after backend error. | Seeded |
| SO-030 | Factory Agent restart or stream drop mid-run. | Infinite busy UI. | Seeded, Playwright |
| SO-031 | Large structured result plus final completion. | Layout hides final state. | Seeded full-stack, Playwright |
| SO-032 | Two browser sessions same user. | Cross-session leakage. | Playwright seeded |
| SO-033 | Authorization failure and owner leakage. | Stale previous answer remains after missing/invalid auth. | API, Playwright |
| SO-034 | Tool registry empty/unhealthy. | Misleading "No tools allowed" message. | API, Playwright |
| SO-035 | Real LangGraph no seeded adapter. | Seeded test hides planner bug. | Pytest graph, real LangGraph browser |
| SO-036 | RAG no source. | Fake citation or generic failure. | RAG pytest, browser |
| SO-037 | RAG source unavailable. | Broken source UI or false confidence. | RAG pytest, browser |
| SO-038 | Model returns malformed JSON. | Unsafe fallback or wrong mutation. | Pytest graph |
| SO-039 | Too much context causes planner fallback. | Final answer hides context overflow. | Pytest graph, later LLM eval |
| SO-040 | Long operation with heartbeats only. | Timeout or stuck UI. | SSE, Playwright |
| SO-041 | Medium priority jobs to high, then original high priority jobs to low. | Final response reports only the last approval/write set or silently changes semantics. | Pytest graph, summary contract, seeded full-stack, real LangGraph browser |
| SO-042 | Unsafe rendered content from backend/model. | Executable HTML/script or unsafe link behavior. | Browser |
| SO-043 | Large pasted input. | Controlled input breaks, request truncates, spinner sticks, or stale final text is reused. | Browser |
| SO-044 | Unsupported dangerous action. | Approval bypass, mutation, or fake completion for destructive prompts. | Browser |

## Definition of Done

The testing system is not good enough until these are true:

- Critical scenarios fail before a known bug fix and pass after the fix.
- Stateful fake tests mutate state like real tools.
- Seeded full-stack tests verify DB, audit, approval rows, timeline, SSE/snapshot, final response, and UI.
- Real LangGraph path is covered for the most important multi-approval workflows.
- Final response cannot be produced from stale or partial evidence.
- SSE/timeline tests can catch out-of-order, duplicate, missing, malformed, timeout, disconnect, and reconnect bugs.
- Every manual failure becomes a regression oracle or an accepted gap.
- No routine manual test remains as a release gate for chatbot flow.

## What This Plan Does Not Promise

No test strategy gives literal 100 percent certainty. This plan is designed to remove the current false confidence by testing state, transitions, and invariants. It should make normal-use bugs much harder to miss, and when a manual bug is found, the test system itself must be treated as defective until it gets a regression oracle.
