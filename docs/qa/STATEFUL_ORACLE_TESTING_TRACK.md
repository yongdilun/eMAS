# Stateful Oracle Testing Tracker

Created: 2026-05-16

Branch: `codex/playwright-e2e-plan`

Purpose: living execution tracker for the stateful oracle hardening plan. Future agents should update this file before and after each implementation phase.

## Status Legend

- `Not Started`
- `In Progress`
- `Blocked`
- `Done`

## Phase Status

| Phase | Name | Status | Notes |
|---|---|---|---|
| 0 | Test reality audit | Done | Audited current pytest, frontend unit/component, mocked Playwright, seeded Playwright, release, and synthetic tests. Phase moved Not Started -> In Progress -> Done during this pass. |
| 1 | Oracle schema and scenario bank | Done | Oracle schema validates. Bank includes SO-001 through SO-020 plus risk-ranked extras SO-021, SO-025, SO-027, SO-029, SO-030, and SO-035. Accepted-gap format is documented. |
| 2 | Stateful fake tool and commit harness | Done | Added reusable mutable oracle harness, focused SO-001/SO-006/SO-007/SO-008/SO-009 tests, and strengthened critical graph tests without starting Phase 3. |
| 3 | LangGraph state machine invariants | Done | Added focused LangGraph state-machine oracle pytest coverage for cursor movement, staged-write cleanup, approval boundaries, rejection, timeout, stale approval, distinct approval ids, and original-state cascade semantics. |
| 4 | Snapshot, timeline, and final response contract | Done | Added Phase 4 oracle contract tests tying graph actions, approvals, audit rows, fake committed state, SSE/timeline evidence, and final response copy together; fixed frontend stale-terminal-before-approval guard. |
| 5 | SSE contract and disconnect semantics | Done | Runtime and browser SSE oracles now prove order, reconnect, malformed recovery, disconnect, fallback, and terminal-state gating. |
| 6 | Seeded full-stack data and audit oracles | Done | Seeded Go API plus Factory Agent DB rows, approvals, audit rows, snapshot, timeline, final response, and UI now agree under Phase 6 oracles. |
| 7 | Non-seeded LangGraph browser proof | Done | SO-001 real LangGraph browser proof is committed at `9054b87`. |
| 8 | Manual failure promotion workflow | Done | Manual misses now have a required intake template, oracle mapping, lowest-layer regression mapping, and failing-regression closure rule. |
| 9 | CI gate restructure | Not Started | Put fast oracle tests in PR and heavier ones in release gates. |
| 10 | Ledger refactor decision | Not Started | Decide whether a durable operation ledger is needed. |

## Phase 0 Checklist: Test Reality Audit

- [x] Inventory current Factory Agent pytest tests.
- [x] Inventory current frontend unit/component tests.
- [x] Inventory mocked Playwright tests.
- [x] Inventory seeded Playwright tests.
- [x] Inventory release/synthetic tests.
- [x] Mark tests that assert only `COMPLETED` without state verification.
- [x] Mark tests that use non-mutating fake backend state.
- [x] Mark tests that use seeded adapter but claim real LangGraph behavior.
- [x] Mark tests that validate UI only without backend oracle.
- [x] Select top 20 scenarios to convert first.

## Phase 0 Audit: Test Reality Audit

Completed: 2026-05-16

Scope audited:

- Factory Agent pytest tests under `factory-agent/tests`.
- Frontend unit/component tests under `eMas Front/src/components/features/chat`.
- Mocked Playwright tests under `eMas Front/e2e/specs`.
- Seeded Playwright tests under `eMas Front/e2e/specs`.
- Release and synthetic Playwright tests under `eMas Front/e2e/specs`.

Summary:

- Found more than 20 weak-oracle risks. The highest risk is not missing tests; it is tests with useful coverage but insufficient state oracles.
- Stronger seeded data-integrity tests now exist, especially `full-stack-data-integrity.spec.js` and `full-stack-prompt-workflow-regression.spec.js`, but they still prove seeded adapter behavior rather than real LangGraph browser behavior.
- Many older seeded, release, synthetic, and frontend unit tests can pass with wrong DB state, missing audit rows, stale timeline rows, missing approval evidence, or premature final responses.
- Several Factory Agent pytest tests use fake HTTP or monkeypatched graph nodes and therefore prove local mechanics only. They should remain, but must not be treated as product state proof.

### Weak-Oracle Tests Found

| Priority | File path | Test/scenario name | Current assertion weakness | Real bug that could still pass | Recommended replacement or strengthening action |
|---|---|---|---|---|---|
| Critical | `factory-agent/tests/test_phase5_final_validator.py` | `test_two_step_priority_cascade_requires_second_langgraph_approval` | Uses an in-memory fake job map and monkeypatched dry-run/commit nodes; no DB, approval table, audit rows, snapshot, timeline, SSE, or browser oracle. | Real API commit could mutate the wrong rows, omit audit rows, or project stale timeline/final response while this fake graph test still passes. | Keep as graph mechanic coverage, but add SO-001/SO-002 stateful oracle pytest using mutable fake backend plus approval/audit/timeline invariants, and seeded plus real-LangGraph browser proof. |
| Critical | `factory-agent/tests/test_phase5_final_validator.py` | `test_approval_interrupt_resume_commits_from_checkpoint_without_replanning` | Verifies only fake event order, one prompt count, and fake commit invocation. | Resume could use stale approval id, lose pending approval state, or write without persisted approval evidence. | Add checkpoint-resume oracle that asserts approval row, distinct operation id, commit idempotency, snapshot pending state, and final response after commit only. |
| High | `factory-agent/tests/test_phase5_final_validator.py` | `test_bulk_low_priority_jobs_are_selected_by_filter_and_staged_as_one_approval_bundle` | Fake read returns fixed rows and stops at approval payload. | Product could approve the right preview but commit a different set, skip rows, or report success without mutation. | Convert to stateful fake commit harness with before/after priority map, unchanged rows, approval id, and audit rows. |
| High | `factory-agent/tests/test_phase5_final_validator.py` | `test_complete_create_intents_are_collected_into_one_bundle_approval` | Asserts staged writes count only; no commit, created rows, audit rows, idempotency, or final summary. | Create flow could duplicate jobs, miss one create, or claim created rows that are absent. | Add create oracle with final DB rows, generated IDs, idempotency replay, audit, and summary matching. |
| High | `factory-agent/tests/test_phase5_final_validator.py` | `test_bulk_low_priority_jobs_are_deleted_as_one_approval_bundle` | Asserts selected delete bundle only; no post-approval delete state, audit, or unchanged-row oracle. | Delete flow could delete extra rows, leave target rows, or show success despite failed deletes. | Add delete oracle with initial/final row sets, audit, approval id, and final summary. |
| Medium | `factory-agent/tests/test_phase5_final_validator.py` | `test_incomplete_create_intent_is_not_added_to_bundle` | Checks one staged write and approval count, but no clarification/snapshot contract for the incomplete second intent. | UI could silently drop the incomplete intent and still show success for the whole user request. | Strengthen with explicit clarification or partial-completion oracle and final response wording that names the skipped intent. |
| Critical | `factory-agent/tests/test_phase19_prompt_workflow_regression.py` | `test_phase19_scenario_119_cascade_prompt_matrix_extracts_two_write_sets` | Calls private `SeededPlaywrightPlanner._phase14_cascade_priority_changes` directly. | Real LangGraph planner could split or execute the cascade incorrectly while seeded private parser still passes. | Mark as seeded parser coverage only; add non-seeded LangGraph graph test and real-LangGraph browser smoke for top cascade prompts. |
| High | `factory-agent/tests/test_phase19_prompt_workflow_regression.py` | `test_phase19_scenario_116_loto_wording_matrix_uses_same_rag_route` | Parser/intent helper only; no RAG retrieval, source projection, final UI, or generic-diagnostic oracle. | Browser could still ask for machine ID, lose source metadata, or show generic error. | Pair with seeded browser source oracle and backend RAG contract asserting source metadata in snapshot/timeline/final UI. |
| Medium | `factory-agent/tests/test_phase19_prompt_workflow_regression.py` | `test_phase19_scenario_118_route_selection_matrix` | Tool selection assertions only; no execution or data oracle. | Correct tool could be selected but called with wrong args, wrong route continuation, or stale final answer. | Add route-to-execution contract for machine, job, approval, and cancel categories with snapshot evidence. |
| High | `factory-agent/tests/test_api_endpoints.py` | `test_conversation_message_returns_completed_empty_plan` | Accepts `COMPLETED` empty plan and session_completed timeline; no final-answer/stale-answer UI oracle. | Empty final response could reuse a previous answer or hide missing assistant content. | Add snapshot/final-response contract and frontend turn fixture for empty completion. |
| Medium | `factory-agent/tests/test_api_endpoints.py` | `test_planner_clarification_returns_message_not_error` and related clarification tests | Several clarification paths assert `COMPLETED` plus message content, not terminal-state/final-response consistency. | Clarification could be stored as completed terminal success or wrong turn association. | Assert session phase, no plan/steps, assistant message role, turn id, and no stale final answer. |
| High | `factory-agent/tests/test_api_endpoints.py` | legacy read-then-write approval flow around `WAITING_APPROVAL` -> `COMPLETED` | Verifies step statuses only after approval. | Write could commit without audit evidence, wrong backend state, or stale approval cleanup. | Replace legacy status proof with stateful API oracle including approval row, commit result, audit, and DB final state. |
| Medium | `factory-agent/tests/test_api_endpoints.py` | `test_machine_tool_result_summary_is_operator_readable` | Asserts `COMPLETED` and readable message text only. | Snapshot/timeline/presentation could omit the tool result while DB message assertion passes. | Add snapshot presentation and timeline event assertions for the same result. |
| Medium | `factory-agent/tests/test_api_endpoints.py` | `test_read_only_machine_not_found_returns_operator_friendly_completion` | Treats 404 read as `COMPLETED` with friendly message; no UI stale-answer oracle. | Not-found result could be terminal success in backend while browser displays previous answer or wrong source. | Add final response and frontend fixture proving not-found answer replaces stale content. |
| High | `factory-agent/tests/test_api_endpoints.py` | write machine precondition/not-found tests | Checks approval/no-approval branches but not final state or audit after approval. | Approval card could be correct while mutation target check uses stale machine state. | Add precondition oracle with target snapshot, approval payload, commit block on 404, and audit absence. |
| High | `eMas Front/e2e/specs/full-stack-seeded.spec.js` | scenario 35 approval-required flow | Confirms visible approval and pending row exists; no approval id/timeline/snapshot consistency. | UI could render stale approval card or wrong approval id while `/approvals/pending` has some pending row. | Assert pending approval id matches UI card, snapshot `pending_approval`, timeline approval event, and expected bundle rows. |
| High | `eMas Front/e2e/specs/full-stack-seeded.spec.js` | scenario 36 approval approve resumes and reaches completed state | Asserts `COMPLETED`, `Run complete`, and text; no DB/audit oracle. | Approval could complete without committing the seeded job change or with missing audit. | Strengthen with before/after job priority, audit row, approval status, timeline, and final assistant summary. |
| Medium | `eMas Front/e2e/specs/full-stack-seeded.spec.js` | scenario 38 notification and activity SSE open and reach final snapshot | Only proves EventSource URLs opened and final UI appeared. | SSE order, duplicate events, missing timeline rows, or snapshot/SSE disagreement could pass. | Add SSE event sequence oracle with event ids, activity rows, snapshot terminal state, and no premature final response. |
| High | `eMas Front/e2e/specs/full-stack-orchestration.spec.js` | scenario 40 two approvals required before final execution | Checks two approval ids and final text, but not DB/audit/timeline/final consistency. | Second approval could be cosmetic while one commit or wrong commit happens. | Convert to SO-005/SO-011 style oracle with DB state after each approval, approval rows, timeline, and no final before approval 2. |
| High | `eMas Front/e2e/specs/full-stack-orchestration.spec.js` | scenario 41 rejecting the second approval stops without later execution | Verifies no final UI and rejected approval row; no DB/audit unchanged oracle. | Rejection could still mutate data or append audit rows while UI stays non-terminal. | Assert DB unchanged from baseline, no successful audit rows, snapshot pending cleared, and rejection timeline event. |
| High | `eMas Front/e2e/specs/full-stack-orchestration.spec.js` | scenario 42 approval timeout remains visible and non-terminal | Checks expired timestamp and still `WAITING_APPROVAL`; no stale approval mutation attempt. | Expired approval could still mutate if approve endpoint is called later. | Attempt approval after expiry and assert 409/expired row, unchanged DB, no audit, and safe final response. |
| Medium | `eMas Front/e2e/specs/full-stack-orchestration.spec.js` | scenario 39 ordered multi-step job plans | Timeline text order and step statuses only. | Steps could read wrong DB data or summarize stale/seeded text. | Assert read source rows, result payloads, final summary matches row ids/counts, and unchanged rows. |
| Medium | `eMas Front/e2e/specs/full-stack-sse-hard.spec.js` | scenario 47 out-of-order and duplicate SSE events | Checks no duplicate visible `Run complete`, unique activity ids, and `COMPLETED`. | Out-of-order activity could still skip a required transition or final response could come from snapshot alone. | Assert exact expected SSE/timeline event sequence and monotonic event ids; compare against snapshot activity. |
| Medium | `eMas Front/e2e/specs/full-stack-sse-hard.spec.js` | scenario 48 EventSource reconnect sends Last-Event-ID | Checks server connection log contains a last event id; no exact replay/duplication oracle. | Reconnect could replay old non-terminal rows or skip terminal row while final UI remains visible. | Assert rendered activity ids before/after reconnect, no duplicated semantic rows, and snapshot/timeline equality. |
| High | `eMas Front/e2e/specs/full-stack-resilience.spec.js` | scenario 51 stream drop mid-run recovers by polling | Accepts final `COMPLETED` and text after stream drop; no event contract. | Polling could fabricate completion while activity stream lost commit or error evidence. | Add disconnect recovery oracle tying stream drop, polling snapshot, terminal timeline, and final answer source. |
| Medium | `eMas Front/e2e/specs/release-validation.spec.js` | scenario 53 release path opens app through `/agent` | Visible machine text plus `Run complete`; no backend state or snapshot oracle. | Release proxy could route to a fake/old answer or wrong session. | Assert active session snapshot, message turn id, and tool result source for the release proxy path. |
| Medium | `eMas Front/e2e/specs/release-validation.spec.js` | scenario 55 static bearer disables EventSource and uses polling fallback | Confirms no `/events`, diagnostic text, and final UI only. | Polling fallback could show final text without terminal snapshot/timeline agreement. | Assert polling snapshot progression and terminal state before final answer is allowed. |
| Low | `eMas Front/e2e/specs/release-validation.spec.js` | scenario 58 release latency budget | Measures visible progress/final text timing only. | Fast stale response could pass latency while backend operation is wrong. | Keep as performance smoke, but do not count as functional proof; pair with state oracle elsewhere. |
| High | `eMas Front/e2e/specs/production-synthetic.spec.js` | scenario 72 machine status synthetic canary | Non-empty final response and visible machine text only. | Production canary could pass on stale cached answer or wrong source data. | Add read-only snapshot/tool-result evidence and session age/turn id checks without mutating production. |
| High | `eMas Front/e2e/specs/production-synthetic.spec.js` | scenario 73 RAG/source synthetic canary | Allows `sourceCount >= 0`; exact source metadata optional. | RAG could invent/collapse citations or omit required source while test passes. | Require at least one cited source for known seeded/local mode; in live mode record accepted gap with degraded severity. |
| Medium | `eMas Front/e2e/specs/production-synthetic.spec.js` | scenario 74 SSE-or-polling canary | Any progress plus non-empty final response passes. | SSE/polling can disagree or final response can appear before terminal snapshot. | Assert progress event precedes terminal snapshot and final UI; record transport path explicitly. |
| High | `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs` | `completed LangGraph plan without terminal event renders the plan summary` | Explicitly allows completed plan summary without terminal event. | UI could display final answer when backend never emitted terminal completion. | Add companion negative fixture: latest operation must not render final assistant answer until terminal event or terminal snapshot evidence exists. |
| High | `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs` | `completed approval turn prefers completed tool result over stale approval wait terminal text` | Picks a completed tool result but has no approval/commit/audit oracle. | Tool result text could claim success for a failed or partial commit. | Feed the assembler from oracle snapshots where final summary, approval id, and committed rows agree. |
| Medium | `eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs` | `injects execution summary when plan steps exist but timeline has no tool rows` | UI synthesizes "Updating job records" from plan steps when timeline evidence is missing. | Timeline omission could be hidden by a synthesized activity row. | Add warning/diagnostic or contract test that missing tool rows fail for mutating oracle scenarios. |
| Medium | `eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs` | `terminal snapshot fallback uses full timeline across user turns` | Merges terminal fallback across turns. | Old turn evidence could make the latest turn look complete. | Add operation-id oracle fixtures and fail when latest operation lacks its own terminal chain. |
| High | `eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js` | scenario 116/124/125 LOTO regression bank | Stronger than parser tests, but still seeded RAG/planner; no real RAG or non-seeded LangGraph proof. | Real route/RAG integration could ask for machine ID or miss source metadata while seeded adapter passes. | Keep as seeded regression; add backend RAG contract and one real-LangGraph browser case for M-CNC-01 LOTO. |
| Critical | `eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js` | scenario 119/120/121/125 cascade matrix | Good seeded DB/audit oracle, but powered by `SeededPlaywrightPlanner`. | Real LangGraph could still finalize early, reuse mutated source set, or skip approval 2. | Promote top cascade scenarios to Phase 3 graph invariants and Phase 7 real-LangGraph browser proof. |

### Top 20 Scenarios To Convert First

| Rank | Scenario | Why first | Target strengthening |
|---|---|---|---|
| 1 | SO-001 medium->high then original high->medium | Exact recent high-risk cascade bug; seeded proof is not enough. | Pytest LangGraph invariant, seeded oracle, real-LangGraph browser. |
| 2 | SO-002 high->low then original low->medium | Existing scenario 86 regression and broad operator risk. | Stateful fake plus seeded DB/audit/timeline oracle. |
| 3 | SO-005 approval 1 accepted, approval 2 rejected | Hidden continuation after rejection can mutate silently. | DB unchanged after rejection, no successful audit, rejection timeline. |
| 4 | SO-011 final response before approval 2 appears | Direct false-confidence pattern from `COMPLETED` checks. | Assert no final UI/message until all approvals and commits complete. |
| 5 | SO-010 commit succeeds but audit row missing | UI success without audit evidence is a release blocker. | Seeded audit oracle tied to approval id and row ids. |
| 6 | SO-009 partial bulk commit failure | Final response can claim full success despite partial failure. | Exact per-row success/failure, final summary, and audit checks. |
| 7 | SO-007 approval double-click and refresh replay | Duplicate mutations can be invisible in final text. | Idempotency key, one audit row, one DB mutation. |
| 8 | SO-008 stale approval after new user revision | Old approval can mutate changed session. | Approval invalidation, 409 replay, unchanged DB. |
| 9 | SO-012 timeline omits approval 2 | UI can lose intermediate approval while final status passes. | Timeline includes both approval ids in order. |
| 10 | SO-013 SSE completion before snapshot terminal | Browser can show final too early. | SSE/snapshot/final UI ordering contract. |
| 11 | SO-014 SSE reconnect duplicates old activity rows | Duplicate rows can confuse operators and hide ordering bugs. | Last-Event-ID replay oracle with stable activity ids. |
| 12 | SO-018 browser refresh during active approval | Refresh can lose or duplicate approval state. | Restore pending approval id and prove no duplicate execute. |
| 13 | SO-019 existing completed session restored | Stale previous answer can become new answer. | Turn/operation id fixture plus browser reload oracle. |
| 14 | SO-020 empty final response | Empty completion can reuse stale answer. | Backend final-response contract plus frontend fixture. |
| 15 | SO-021 LOTO with `M-CNC-01` | Manual wording miss affected normal chatbot use. | Parser, route, seeded browser, backend RAG source oracle. |
| 16 | SO-025 route confusion: LOTO vs machine status | Correct route matters more than final text. | Route-to-execution contract with tool/RAG evidence. |
| 17 | SO-027 user sends revision while waiting approval | Pending approval must not survive superseding turn. | Approval invalidation and unchanged DB oracle. |
| 18 | SO-029 Go API 500 mid-run | Generic success after backend error is dangerous. | Seeded/release oracle with no final success and no audit. |
| 19 | SO-030 Factory Agent restart or stream drop mid-run | Infinite busy or fake final can pass weak checks. | Polling/SSE recovery tied to terminal snapshot. |
| 20 | SO-035 real LangGraph no seeded adapter | Seeded adapter hides planner bugs. | Opt-in real-LangGraph browser critical suite. |

### Phase 0 Commands Run

```powershell
git branch --show-current
git status --short
Get-Content -Raw -LiteralPath 'docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md'
Get-Content -Raw -LiteralPath 'docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md'
rg -n "COMPLETED|WAITING_APPROVAL|pending_approval|approval_id|timeline|final response|SSE|EventSource|SeededPlaywrightPlanner|testing_seeded_adapters" "factory-agent/tests" "eMas Front/e2e" "eMas Front/src/components/features/chat" -S
rg --files "factory-agent/tests" "eMas Front/e2e" "eMas Front/src/components/features/chat"
rg -n "toHaveText|toContainText|toBeVisible|COMPLETED|WAITING_APPROVAL|pending_approval|approval_id|approvalId|timeline|final|EventSource|SeededPlaywrightPlanner|testing_seeded_adapters|synthetic|release|seeded|data-integrity" "factory-agent/tests" "eMas Front/e2e/specs" "eMas Front/e2e/support" "eMas Front/src/components/features/chat" -S
rg -n "^(async\s+)?def test_|^\s*test\(|^\s*it\(" "factory-agent/tests/test_phase19_prompt_workflow_regression.py" "factory-agent/tests/test_phase18_intent_entity_parser.py" "factory-agent/tests/test_phase18_manual_prompt_bank.py" "factory-agent/tests/test_phase5_final_validator.py" "factory-agent/tests/test_planner_phase3.py" "factory-agent/tests/test_planner_service_phase6.py" "factory-agent/tests/test_event_stream_runtime.py" "factory-agent/tests/test_phase7_api_ui_alignment.py"
rg -n "^\s*test\(" "eMas Front/e2e/specs" -S
rg -n "^test\(" "eMas Front/src/components/features/chat" -S
Get-Content -Raw -LiteralPath 'factory-agent/tests/test_phase5_final_validator.py'
Get-Content -Raw -LiteralPath 'factory-agent/tests/test_phase19_prompt_workflow_regression.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/testing_seeded_adapters.py'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/specs/full-stack-data-integrity.spec.js'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/specs/full-stack-orchestration.spec.js'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/specs/full-stack-seeded.spec.js'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/specs/full-stack-sse-hard.spec.js'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/specs/full-stack-resilience.spec.js'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/specs/release-validation.spec.js'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/specs/release-resilience.spec.js'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/specs/production-synthetic.spec.js'
Get-Content -Raw -LiteralPath 'eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs'
Get-Content -Raw -LiteralPath 'eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs'
```

### Phase 0 Files Changed

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`

### Phase 0 Next Action

Start Phase 1 by creating machine-readable oracle files for the top 20 list above, beginning with SO-001, SO-002, SO-005, SO-011, and SO-010. Do not delete or rewrite the weak tests; reclassify them as smoke/regression coverage and add stateful oracle coverage beside them.

## Phase 1 Checklist: Oracle Schema and Scenario Bank

- [x] Create `tests/e2e/scenarios/stateful_oracles/`.
- [x] Define oracle JSON schema.
- [x] Add schema validation pytest.
- [x] Add initial five scenario oracles: SO-001, SO-002, SO-005, SO-010, SO-011.
- [x] Add SO-001 through SO-010.
- [x] Add SO-011 through SO-020.
- [x] Link each oracle to required test layer.
- [x] Link each oracle to existing manual failure or risk.
- [x] Document accepted-gap format.

## Phase 1 Implementation: Oracle Schema and Scenario Bank

Status: Done

Updated: 2026-05-16

Scope completed in this pass:

- Added the initial machine-readable oracle directory: `tests/e2e/scenarios/stateful_oracles/`.
- Added five oracle JSON files for the first requested high-risk scenarios:
  - `tests/e2e/scenarios/stateful_oracles/so-001_priority_medium_to_high_original_high_to_medium.json`
  - `tests/e2e/scenarios/stateful_oracles/so-002_priority_high_to_low_original_low_to_medium.json`
  - `tests/e2e/scenarios/stateful_oracles/so-005_second_approval_rejected.json`
  - `tests/e2e/scenarios/stateful_oracles/so-010_commit_succeeds_audit_missing.json`
  - `tests/e2e/scenarios/stateful_oracles/so-011_no_final_before_second_approval.json`
- Added schema/contract validation in `factory-agent/tests/test_stateful_oracle_schema.py`.
- Each initial oracle includes the required fields: stable `SO-###` id, prompt, initial state, expected intents or route, approvals, intermediate states, final state, audit rows, timeline, SSE/snapshot expectation, final response, UI expectation, unchanged rows, invariants, required layers, and Phase 0 weakness.

Continuation completed in this pass:

- Added five more top-priority oracle JSON files:
  - `tests/e2e/scenarios/stateful_oracles/so-007_approval_double_click_refresh_replay.json`
  - `tests/e2e/scenarios/stateful_oracles/so-008_stale_approval_after_user_revision.json`
  - `tests/e2e/scenarios/stateful_oracles/so-009_partial_bulk_commit_failure.json`
  - `tests/e2e/scenarios/stateful_oracles/so-012_timeline_omits_approval_2.json`
  - `tests/e2e/scenarios/stateful_oracles/so-013_sse_completion_before_snapshot_terminal.json`
- Current Phase 1 scenario bank now covers SO-001, SO-002, SO-005, SO-007, SO-008, SO-009, SO-010, SO-011, SO-012, and SO-013.
- At this earlier continuation point, Phase 1 remained `In Progress` because SO-003, SO-004, SO-006, SO-014 through SO-020, and accepted-gap format documentation were still open.

Final completion pass:

- Added the remaining first critical scenario set oracles:
  - `tests/e2e/scenarios/stateful_oracles/so-003_priority_low_to_high_original_high_to_low.json`
  - `tests/e2e/scenarios/stateful_oracles/so-004_priority_high_to_medium_original_medium_to_low.json`
  - `tests/e2e/scenarios/stateful_oracles/so-006_second_approval_timeout.json`
  - `tests/e2e/scenarios/stateful_oracles/so-014_sse_reconnect_duplicates_activity_rows.json`
  - `tests/e2e/scenarios/stateful_oracles/so-015_sse_malformed_payload_then_valid_payload.json`
  - `tests/e2e/scenarios/stateful_oracles/so-016_eventsource_disconnect_on_modal_close.json`
  - `tests/e2e/scenarios/stateful_oracles/so-017_static_bearer_polling_fallback.json`
  - `tests/e2e/scenarios/stateful_oracles/so-018_browser_refresh_during_active_approval.json`
  - `tests/e2e/scenarios/stateful_oracles/so-019_existing_completed_session_restored.json`
  - `tests/e2e/scenarios/stateful_oracles/so-020_empty_final_response.json`
- Added the risk-ranked extras explicitly called out by the Phase 1 continuation note:
  - `tests/e2e/scenarios/stateful_oracles/so-021_loto_machine_id_m_cnc_01.json`
  - `tests/e2e/scenarios/stateful_oracles/so-025_route_confusion_loto_vs_machine_status.json`
  - `tests/e2e/scenarios/stateful_oracles/so-027_revision_while_waiting_approval.json`
  - `tests/e2e/scenarios/stateful_oracles/so-029_go_api_500_mid_run.json`
  - `tests/e2e/scenarios/stateful_oracles/so-030_factory_agent_restart_or_stream_drop_mid_run.json`
  - `tests/e2e/scenarios/stateful_oracles/so-035_real_langgraph_no_seeded_adapter.json`
- Updated `factory-agent/tests/test_stateful_oracle_schema.py` so read-only or route-only oracles can explicitly set `expected_sse_or_snapshot.approval_required` to `false` with `expected_approvals: []` and the `no_approval_required` invariant, instead of inventing fake approval rows.
- Documented the accepted-gap format in `docs/qa/manual_prompt_regression_bank.md`.
- Phase 1 is now `Done` because the first critical scenario bank validates, every oracle names required layers and a Phase 0 weakness/risk, and the accepted-gap format is documented.

Commands run:

```powershell
git branch --show-current
git status --short
Get-Content -Raw docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md
Get-Content -Raw docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md
rg -n "SO-001|SO-002|SO-005|SO-010|SO-011|Phase 0 Audit|Top 20" docs/qa tests/e2e/scenarios factory-agent/tests "eMas Front/e2e" -S
rg --files factory-agent/tests tests/e2e/scenarios docs/qa
New-Item -ItemType Directory -Force tests\e2e\scenarios\stateful_oracles
Set-Location "factory-agent"
python -m pytest tests/test_stateful_oracle_schema.py -q
rg --files tests/e2e/scenarios/stateful_oracles
```

Test results:

```text
3 passed, 1 warning in 1.04s
3 passed, 1 warning in 0.61s
3 passed, 1 warning in 0.74s
3 passed, 1 warning in 0.58s
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope` appeared after pytest completion.

Files added:

- `factory-agent/tests/test_stateful_oracle_schema.py`
- `tests/e2e/scenarios/stateful_oracles/so-001_priority_medium_to_high_original_high_to_medium.json`
- `tests/e2e/scenarios/stateful_oracles/so-002_priority_high_to_low_original_low_to_medium.json`
- `tests/e2e/scenarios/stateful_oracles/so-003_priority_low_to_high_original_high_to_low.json`
- `tests/e2e/scenarios/stateful_oracles/so-004_priority_high_to_medium_original_medium_to_low.json`
- `tests/e2e/scenarios/stateful_oracles/so-005_second_approval_rejected.json`
- `tests/e2e/scenarios/stateful_oracles/so-006_second_approval_timeout.json`
- `tests/e2e/scenarios/stateful_oracles/so-007_approval_double_click_refresh_replay.json`
- `tests/e2e/scenarios/stateful_oracles/so-008_stale_approval_after_user_revision.json`
- `tests/e2e/scenarios/stateful_oracles/so-009_partial_bulk_commit_failure.json`
- `tests/e2e/scenarios/stateful_oracles/so-010_commit_succeeds_audit_missing.json`
- `tests/e2e/scenarios/stateful_oracles/so-011_no_final_before_second_approval.json`
- `tests/e2e/scenarios/stateful_oracles/so-012_timeline_omits_approval_2.json`
- `tests/e2e/scenarios/stateful_oracles/so-013_sse_completion_before_snapshot_terminal.json`
- `tests/e2e/scenarios/stateful_oracles/so-014_sse_reconnect_duplicates_activity_rows.json`
- `tests/e2e/scenarios/stateful_oracles/so-015_sse_malformed_payload_then_valid_payload.json`
- `tests/e2e/scenarios/stateful_oracles/so-016_eventsource_disconnect_on_modal_close.json`
- `tests/e2e/scenarios/stateful_oracles/so-017_static_bearer_polling_fallback.json`
- `tests/e2e/scenarios/stateful_oracles/so-018_browser_refresh_during_active_approval.json`
- `tests/e2e/scenarios/stateful_oracles/so-019_existing_completed_session_restored.json`
- `tests/e2e/scenarios/stateful_oracles/so-020_empty_final_response.json`
- `tests/e2e/scenarios/stateful_oracles/so-021_loto_machine_id_m_cnc_01.json`
- `tests/e2e/scenarios/stateful_oracles/so-025_route_confusion_loto_vs_machine_status.json`
- `tests/e2e/scenarios/stateful_oracles/so-027_revision_while_waiting_approval.json`
- `tests/e2e/scenarios/stateful_oracles/so-029_go_api_500_mid_run.json`
- `tests/e2e/scenarios/stateful_oracles/so-030_factory_agent_restart_or_stream_drop_mid_run.json`
- `tests/e2e/scenarios/stateful_oracles/so-035_real_langgraph_no_seeded_adapter.json`
- `docs/qa/manual_prompt_regression_bank.md`

Next action:

Start Phase 2 by building the stateful fake tool and commit harness from the oracle files. Keep the work oracle-driven and avoid product fixes until the harness exposes a reproducible defect.

## Phase 2 Checklist: Stateful Fake Tool and Commit Harness

- [x] Add stateful fake jobs.
- [x] Add stateful fake machine/RAG entities where needed.
- [x] Add fake transaction dry-run.
- [x] Add fake commit that mutates state.
- [x] Add audit row recording.
- [x] Add idempotency/replay behavior.
- [x] Add approval expiry/staleness behavior.
- [x] Replace fixed fake rows in critical graph tests.
- [x] Prove the previous cascade bug would fail.

## Phase 2 Implementation: Stateful Fake Tool and Commit Harness

Status: Done

Updated: 2026-05-16

Scope completed in this pass:

- Added `factory-agent/tests/support/stateful_oracle_harness.py` as a reusable mutable fake backend for oracle tests.
- Added `factory-agent/tests/support/operation_assertions.py` for shared final-state, audit, unchanged-row, and timeline assertions.
- The harness now supports seeded jobs, seeded machines, seeded RAG entities, original-vs-current state reads, dry-run bundles, approval lifecycle state, commits that mutate fake state, audit rows, idempotent approval replay, stale/superseded approval rejection, expired approval rejection, partial bulk failure with per-row results, and timeline/SSE-style event capture.
- Added `factory-agent/tests/test_stateful_oracle_harness.py` with focused coverage for:
  - SO-001 original-state cascade.
  - SO-006 second approval timeout.
  - SO-007 approval double-click and refresh replay.
  - SO-008 stale approval after user revision.
  - SO-009 partial bulk commit failure.
- Replaced the local fake job-priority map in `factory-agent/tests/test_phase5_final_validator.py::test_two_step_priority_cascade_requires_second_langgraph_approval` with the shared oracle harness.
- Strengthened `factory-agent/tests/test_planner_phase3.py` with a harness-backed snapshot-selection guard proving captured original rows remain usable after the fake backend mutates.
- No product behavior was changed. `factory-agent/factory_agent/testing_seeded_adapters.py` was inspected as Phase 2 context but did not need modification for the pytest harness.

Commands run:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_stateful_oracle_harness.py -q
python -m pytest tests/test_phase5_final_validator.py tests/test_planner_phase3.py -q
python -m pytest tests/test_stateful_oracle_schema.py -q
```

Test results:

```text
5 passed, 1 warning in 0.70s
29 passed, 17 warnings in 1.32s
3 passed, 1 warning in 0.53s
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `DeprecationWarning` from `factory_agent.observability.telemetry` using `datetime.utcnow()`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope` appeared after pytest completion.

Files changed:

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `factory-agent/tests/support/__init__.py`
- `factory-agent/tests/support/stateful_oracle_harness.py`
- `factory-agent/tests/support/operation_assertions.py`
- `factory-agent/tests/test_stateful_oracle_harness.py`
- `factory-agent/tests/test_phase5_final_validator.py`
- `factory-agent/tests/test_planner_phase3.py`

Next action:

Start Phase 3 only after reviewing whether the new Phase 2 harness should be wired into additional low-level graph invariant tests. Do not broaden into snapshot/SSE/UI contract work until Phase 3 is explicitly started.

## Phase 3 Checklist: LangGraph State Machine Invariants

- [x] Add `test_langgraph_state_machine_oracles.py`.
- [x] Assert no completion with active intent.
- [x] Assert no completion with pending approval.
- [x] Assert staged writes clear after successful commit.
- [x] Assert approval rejection stops continuation.
- [x] Assert approval timeout does not mutate.
- [x] Assert user revision invalidates stale approval.
- [x] Assert multi-approval flows create distinct approval ids.
- [x] Assert original-state semantics for cascade oracles.

## Phase 3 Implementation: LangGraph State Machine Invariants

Status: Done

Updated: 2026-05-16

Scope completed in this pass:

- Added `factory-agent/tests/test_langgraph_state_machine_oracles.py`.
- Covered successful-commit cursor semantics directly at `make_final_validator_node`: a successful commit with another active intent routes back to planning, advances the cursor, marks the committed intent complete, and clears staged writes through the reducer replacement marker instead of completing the operation.
- Covered SO-011 with a harnessed real LangGraph run: first approval raises an approval interrupt without terminal events; first commit produces the second approval, not completion; approval ids are distinct; terminal state appears only after approval 2 commits.
- Covered SO-001 with a harnessed real LangGraph run: the cascade snapshots medium and high source groups before the first write and stages the second approval from original high rows only, even after current high rows include the newly changed medium rows.
- Covered SO-005 with a harnessed real LangGraph run: rejecting the second approval does not call the second commit path, does not create audit rows for the rejected approval, and does not record operation completion.
- Covered SO-006 with a harnessed real LangGraph run through the second pending approval, then an oracle timeout transition proving late approval is rejected and no second mutation or completion occurs.
- Covered SO-008 with the Phase 2 oracle harness: a user revision supersedes the old pending approval, stale replay is rejected, only the new approval commits, and old approval audit/commit evidence remains absent.
- Added explicit oracle-validity controls that intentionally construct bad states and confirm the Phase 3 assertions go red for:
  - `COMPLETED` while active intents, staged writes, or pending approvals remain.
  - Missing second approval plus premature `final_response_created` / `operation_completed`.
  - Mutating job state before approval.
  - Using current-state rows for the second cascade source set instead of original-state rows.
  - Reusing the first approval id for the second approval.
  - Claiming final success after a rejected second approval without commit/timeline evidence.
- No product code was changed and no product defect was found during Phase 3.

Commands run:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_langgraph_state_machine_oracles.py -q
python -m pytest tests/test_stateful_oracle_schema.py -q
python -m pytest tests/test_stateful_oracle_harness.py -q
python -m pytest tests/test_phase5_final_validator.py tests/test_planner_phase3.py -q
python -m pytest tests/test_langgraph_state_machine_oracles.py -q
python -m pytest tests/test_langgraph_state_machine_oracles.py -q
```

Test results:

```text
tests/test_langgraph_state_machine_oracles.py: 6 passed, 1 warning in 1.02s
tests/test_stateful_oracle_schema.py: 3 passed, 1 warning in 0.58s
tests/test_stateful_oracle_harness.py: 5 passed, 1 warning in 0.53s
tests/test_phase5_final_validator.py tests/test_planner_phase3.py: 29 passed, 17 warnings in 1.03s
tests/test_langgraph_state_machine_oracles.py: 6 passed, 1 warning in 0.98s
tests/test_langgraph_state_machine_oracles.py: 14 passed, 1 warning in 1.19s
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `DeprecationWarning` from `factory_agent.observability.telemetry` using `datetime.utcnow()`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope` appeared after pytest completion.

Files changed:

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `factory-agent/tests/test_langgraph_state_machine_oracles.py`

Next action:

Start Phase 4: Snapshot, Timeline, and Final Response Contract. Keep Phase 4 focused on backend projection/final-response/timeline agreement and do not broaden into SSE or browser work until the Phase 4 contract is complete.

## Phase 4 Checklist: Snapshot, Timeline, and Final Response Contract

- [x] Add backend snapshot contract tests.
- [x] Add final response contract tests.
- [x] Add timeline event order tests.
- [x] Add approval id visibility tests.
- [x] Add final summary vs committed rows tests.
- [x] Add frontend turn assembler fixture tests from same oracle snapshots.
- [x] Add activity timeline fixture tests from same oracle snapshots.
- [x] Block stale previous answer display.

## Phase 4 Implementation: Snapshot, Timeline, and Final Response Contract

Status: Done

Updated: 2026-05-16

Scope completed in this pass:

- Added `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`.
- Added a Phase 4 evidence contract that compares graph actions, projected timeline events, SSE-style events, approvals, audit rows, committed fake state, pending approval state, and final assistant response text.
- Covered SO-001 with the known hard regression prompt:
  `change all medium priority job to high then change all high priority job to medium`
- SO-001 now requires approval 1, approval 2, final completion only after approval 2, original-state semantics for the second write set, and final summary agreement with committed state, audit rows, timeline, and SSE evidence.
- Covered SO-011 so a multi-step workflow cannot emit final completion after only approval 1.
- Covered SO-005 so rejected approval 2 cannot produce hidden commit evidence or success wording.
- Covered SO-009 so partial bulk failure is reported as partial failure and cannot claim full success.
- Added negative-control/oracle-validity checks proving the Phase 4 contract fails on:
  - empty or missing timeline evidence,
  - missing approval 2 evidence,
  - premature final response ordering,
  - duplicate SSE ids,
  - stale approval ids in final response,
  - duplicate/reused approval request evidence,
  - false success after rejection,
  - false full success after partial failure.
- Fixed a frontend product bug in `turnAssembler.js`: a stale `session_completed` event from approval 1 could outrank a newer pending approval 2 when computing the visible turn summary.
- Added frontend unit coverage proving a newer pending approval outranks stale terminal completion and activity timeline stays in `Waiting for approval` instead of showing `Run complete`.
- No backend product code was changed in Phase 4; the new backend contract tests passed against the current harness and graph mechanics.

Commands run:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_snapshot_timeline_final_response_contract.py -q
python -m pytest tests/test_langgraph_state_machine_oracles.py -q
Set-Location "..\eMas Front"
node --test --test-concurrency=1 "src/components/features/chat/turns/turnAssembler.test.mjs"
npm test
Set-Location "..\factory-agent"
python -m pytest tests/test_snapshot_timeline_final_response_contract.py -q
python -m pytest tests/test_snapshot_timeline_final_response_contract.py tests/test_langgraph_state_machine_oracles.py -q
```

Test results:

```text
tests/test_snapshot_timeline_final_response_contract.py: 7 passed, 1 warning in 0.66s
tests/test_langgraph_state_machine_oracles.py: 14 passed, 1 warning in 1.22s
combined Phase 3 + Phase 4 pytest: 21 passed, 1 warning in 1.11s
turnAssembler node test: 9 passed in 93.5243ms
eMas Front npm test: 53 passed in 6559.0198ms
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope` appeared after pytest completion.

Files changed:

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs`

Decisions made:

- Phase 4 treats timeline/SSE/final-response disagreement as an oracle failure, not as acceptable projection fallback.
- Final response copy for mutating oracle scenarios must cite actual approval ids; stale or invented ids fail the contract.
- Empty or synthesized timeline evidence is not enough for mutating oracle scenarios, even if plan steps or final status look complete.
- Partial failures may be terminal, but they must use partial/error wording and name failed rows; they cannot use full-success wording.

Blockers/open questions:

- No Phase 4 blockers remain.
- Phase 5 still needs dedicated runtime SSE reconnect/disconnect/malformed-event coverage beyond the harness-style SSE evidence used here.

Next action:

Start Phase 5: SSE Contract and Disconnect Semantics. Keep the next pass focused on stream order, reconnect, malformed payload recovery, duplicate suppression, and disconnect/polling behavior.

## Phase 5 Checklist: SSE Contract and Disconnect Semantics

- [x] Assert activity SSE event order.
- [x] Assert notification SSE snapshot invalidation.
- [x] Assert malformed SSE payload recovery.
- [x] Assert reconnect with `Last-Event-ID`.
- [x] Assert no duplicate activity rows after reconnect.
- [x] Assert stream drop leads to polling or safe diagnostic.
- [x] Assert modal close/navigation disconnects EventSource.
- [x] Assert SSE cannot force final UI before terminal snapshot.

## Phase 5 Implementation: SSE Contract and Disconnect Semantics

Status: Done

Updated: 2026-05-16

Pre-edit checkpoint:

- User asked to commit before editing Phase 5.
- Committed the existing worktree first: `527c9ea chore: checkpoint stateful oracle phases`.
- Phase 5 edits were made after that checkpoint.

Scope completed in this pass:

- Fixed a runtime SSE reconnect defect in `factory-agent/factory_agent/api/routers/events.py`: activity and semantic streams now only treat events as already seen when the supplied `Last-Event-ID` is found in the current snapshot/timeline. A stale or unknown `Last-Event-ID` now replays current evidence instead of suppressing every current row.
- Rebuilt `factory-agent/tests/test_event_stream_runtime.py` into a stronger runtime oracle:
  - notification stream poll sessions are separated from the auth dependency session,
  - activity reconnect resumes after `Last-Event-ID` without duplicate rows,
  - stale activity `Last-Event-ID` replays current ordered rows,
  - notification reconnect invalidates stale snapshot cursors,
  - semantic stream reconnect ties emitted events back to snapshot timeline order,
  - negative controls prove the assertions fail for duplicate, out-of-order, missing, and non-invalidating stream evidence.
- Added mock-server SSE frame logging via `eMas Front/e2e/mock-server/factoryAgentMockServer.js` and exposed `/__test/sse-events` so browser tests can assert actual emitted frames, ids, payload types, raw malformed frames, and ordering.
- Strengthened mocked Playwright `@sse` coverage:
  - `chat-sse-activity.spec.js` asserts monotonic unique activity frame ids, expected rendered order, snapshot terminal state, snapshot activity rows, timeline order, and no final answer before terminal snapshot.
  - `chat-sse-notification.spec.js` asserts notification frames include `snapshot_invalidated` and that a snapshot refresh happens after the invalidation frame.
  - `chat-stream-errors.spec.js` asserts malformed raw SSE is ignored, the next valid invalidation refreshes the snapshot, and stream drop produces safe polling diagnostics plus post-drop polling.
  - `chat-cancel-navigation.spec.js` asserts modal close disconnects both notification and activity EventSource streams.
- Strengthened seeded Playwright SSE/resilience coverage:
  - `full-stack-sse-hard.spec.js` now ties seeded activity rows to snapshot/timeline order, uniqueness, terminal state, and reconnect evidence.
  - `full-stack-resilience.spec.js` now proves stream-drop recovery ends in a terminal snapshot with one terminal activity row, ordered timeline evidence, and reconnect `Last-Event-ID`.
- Fixed one unrelated assertion drift encountered by the recommended seeded grep: scenario 52's no-source RAG test now accepts the actual safe wording `available cited LOTO source` instead of requiring the narrower contiguous phrase `available cited source`.

Commands run:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_event_stream_runtime.py -q

Set-Location "..\eMas Front"
npm run test:e2e -- --project=chromium --grep "@sse"
npm run test:e2e -- --project=chromium-seeded --grep "@sse|@l3-hard"
npm run test:e2e -- --project=chromium-seeded --grep "scenario 47|scenario 48|scenario 51"
npm run test:e2e -- --project=chromium-seeded --grep "scenario 52"
npm test
```

Test results:

```text
Initial backend runtime baseline: 2 failed, 1 warning.
  Reason: old poll-session assertions counted the auth snapshot load as a stream poll.

Final backend runtime:
  tests/test_event_stream_runtime.py: 6 passed, 1 warning in 1.19s

Mocked Chromium @sse:
  First run: 4 passed, 1 failed.
  Reason: notification test expected optional phase_changed after terminal invalidation, but the UI legitimately closed the stream after terminal snapshot refresh.
  Final run: 5 passed in 8.9s

Seeded Chromium @sse|@l3-hard:
  First run: 10 passed, 4 failed.
  Reasons: three new Phase 5 assertions were stricter than seeded timeline/activity projections, and scenario 52 had unrelated wording drift.
  Focused Phase 5 rerun: scenario 47, scenario 48, scenario 51 all passed.
  Final full run: 14 passed in 52.7s

Frontend unit suite:
  npm test: 53 passed in 6800.4769ms
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope`.

Files changed:

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `factory-agent/factory_agent/api/routers/events.py`
- `factory-agent/tests/test_event_stream_runtime.py`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/specs/chat-cancel-navigation.spec.js`
- `eMas Front/e2e/specs/chat-sse-activity.spec.js`
- `eMas Front/e2e/specs/chat-sse-notification.spec.js`
- `eMas Front/e2e/specs/chat-stream-errors.spec.js`
- `eMas Front/e2e/specs/full-stack-resilience.spec.js`
- `eMas Front/e2e/specs/full-stack-sse-hard.spec.js`

Decisions made:

- A stale or unknown `Last-Event-ID` must not mark every current activity/timeline row as seen; current evidence should replay rather than stall.
- Browser final-answer visibility remains snapshot-gated. SSE activity can show progress, but final answer and terminal activity require terminal snapshot/timeline evidence.
- Notification `snapshot_invalidated` is the core refresh contract. A later `phase_changed` frame is useful but optional once the invalidation refresh reaches terminal state and the client closes the stream.
- Seeded full-stack timeline oracles should assert the event sequence that the seeded stack actually projects (`plan_created` -> `tool_result` -> `session_completed`) instead of requiring `execution_started` where that projection is absent.
- Mocked SSE tests now inspect emitted frames through `/__test/sse-events`; visible busy UI alone is not treated as stream correctness evidence.

Blockers/open questions:

- No Phase 5 blockers remain.
- Phase 5 still does not prove non-seeded real LangGraph browser behavior; that remains Phase 7.
- The durable operation ledger question remains open for Phase 10.

Next action:

Start Phase 6: Seeded Full-Stack Data and Audit Oracles. Keep Phase 6 focused on seeded DB state, approval rows, audit rows, unchanged rows, snapshot/timeline/final UI agreement, and failure artifacts.

## Phase 6 Checklist: Seeded Full-Stack Data and Audit Oracles

- [x] Reset seeded DB per oracle.
- [x] Capture initial state artifact.
- [x] Capture approval rows after each approval.
- [x] Capture audit rows after each commit.
- [x] Capture final DB state.
- [x] Capture final snapshot/timeline.
- [x] Assert unchanged rows.
- [x] Assert final UI summary matches committed rows.
- [x] Export debug bundle on failure.

## Phase 6 Implementation: Seeded Full-Stack Data and Audit Oracles

Status: Done

Updated: 2026-05-16

Scope completed in this pass:

- Strengthened `full-stack-data-integrity.spec.js` so each mutating seeded oracle captures and asserts initial DB state before prompt execution, per-approval rows, audit rows after each commit, final DB state, unchanged rows, final snapshot/timeline, final assistant text, and visible UI copy.
- Strengthened `full-stack-prompt-workflow-regression.spec.js` cascade matrix so prompt-regression cascades now assert approval rows, audit rows, original-state source sets, unchanged rows, final snapshot state, ordered timeline evidence, and final summary copy.
- Added reusable Phase 6 seeded oracle helpers in `dataIntegrityScenarios.js` for initial/final evidence capture, failure artifact export, approval row assertions, audit commit assertions, unchanged-row protection, ordered timeline checks, and final-summary overclaim checks.
- Added oracle-validity/negative-control checks proving the Phase 6 assertions fail for wrong committed rows, missing audit evidence, out-of-order commit evidence, unchanged-row mutation, stale approval overclaim, and partial-failure full-success wording.
- Fixed a product projection bug in `session_snapshot_service.py`: approval-wait assistant messages are no longer projected as `session_completed`, plan timeline rows keep their real creation time instead of being backdated before approvals, and tool-result commit evidence now carries approval ids and is ordered after the matching approval decision.
- Fixed the seeded partial-failure workflow summary in `testing_seeded_adapters.py` so the final response/UI names succeeded and failed row ids, including `JOB-SEED-MISSING-014`, instead of only saying that one row failed.
- Fixed a seeded prompt-regression assertion drift where multiple legitimate `Run complete` labels caused a strict locator failure.

Commands run:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "medium-to-high"
npm run test:e2e -- --project=chromium-seeded --grep "cascading priority update uses original-state"
npm run test:e2e -- --project=chromium-seeded --grep "bulk partial failure"
npm run test:e2e -- --project=chromium-seeded --grep "medium-to-high then high-to-medium"
npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity|@prompt-regression"

Set-Location "..\factory-agent"
python -m py_compile "factory_agent\services\session_snapshot_service.py"
python -m py_compile "factory_agent\testing_seeded_adapters.py" "factory_agent\services\session_snapshot_service.py"
python -m pytest tests/test_snapshot_timeline_final_response_contract.py tests/test_phase19_prompt_workflow_regression.py -q

Set-Location "..\eMas Front"
node --check "e2e\support\dataIntegrityScenarios.js"
node --check "e2e\specs\full-stack-data-integrity.spec.js"
node --check "e2e\specs\full-stack-prompt-workflow-regression.spec.js"
npm test
```

Test results:

```text
Initial focused seeded prompt run: 1 passed, 1 failed.
  Reason: existing prompt-regression test used a strict `Run complete` locator while the UI can render more than one matching terminal label.

Initial full Phase 6 seeded run: 3 passed, 9 failed.
  Reason: new Phase 6 timeline oracle exposed product projection bugs: approval-wait messages appeared as `session_completed`, final-looking plan text was backdated before approval/commit evidence, and commit tool results lacked ordered approval-id evidence.

Focused cascade after projection fix: 1 passed in 27.1s.

Second full Phase 6 seeded run: 11 passed, 1 failed.
  Reason: partial-failure UI/final summary named counts but not the failed row id.

Focused partial failure after summary fix: 1 passed in 15.5s.

Final recommended Phase 6 seeded run:
  chromium-seeded `@data-integrity|@prompt-regression`: 12 passed in 2.7m.

Focused backend contract/parser guard:
  tests/test_snapshot_timeline_final_response_contract.py tests/test_phase19_prompt_workflow_regression.py: 25 passed, 5 warnings in 0.73s.

Frontend unit suite:
  npm test: 53 passed in 5644.8313ms.
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `DeprecationWarning` from `factory_agent.observability.telemetry` using `datetime.utcnow()`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope`.

Files changed:

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js`
- `eMas Front/e2e/support/dataIntegrityScenarios.js`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/testing_seeded_adapters.py`

Decisions made:

- Phase 6 seeded full-stack tests treat approval rows, audit rows, DB state, snapshot, timeline, final assistant response, and visible UI as one evidence bundle; any disagreement is a failing oracle.
- Failure artifacts are written as Playwright attachments with initial DB state, final DB state, approval/audit evidence, snapshot, timeline, and browser text so partial-failure/debug evidence survives test failure.
- For graph-native seeded snapshots, commit/tool-result timeline evidence is ordered from the matching approval decision when an approval id is available.
- Partial-failure summaries must name failed row ids; counts alone are not enough.

Blockers/open questions:

- No Phase 6 blockers remain.
- Phase 6 still proves seeded adapter behavior, not non-seeded real LangGraph browser behavior; that remains Phase 7.
- The durable operation ledger question remains open for Phase 10.

Next action:

Start Phase 7: Non-Seeded LangGraph Browser Proof. Prioritize SO-001 in the real LangGraph browser path, then expand to the agreed top critical scenarios.

## Phase 7 Checklist: Non-Seeded LangGraph Browser Proof

- [x] Add real LangGraph Playwright project or opt-in spec.
- [x] Start seeded Go API.
- [x] Start Factory Agent without `SeededPlaywrightPlanner`.
- [x] Prepopulate tool registry healthily.
- [x] Drive SO-001 through the browser.
- [x] Assert approval 1 card.
- [x] Assert approval 2 card.
- [x] Assert final UI and backend state.
- [x] Keep this pass scoped to SO-001; defer additional non-seeded critical cases to the next expansion pass.

## Phase 7 Implementation: Non-Seeded LangGraph Browser Proof

Status: Done

Updated: 2026-05-16

Scope completed in this pass:

- Added an opt-in `chromium-real-langgraph` Playwright project and stack launcher that starts the seeded Go API, starts Factory Agent without `SeededPlaywrightPlanner`, preloads OpenAPI tools, and points Vite at that real LangGraph backend.
- Added SO-001 real-browser coverage for `change all medium priority job to high then change all high priority job to medium`.
- Asserted approval 1 targets the original medium rows, approval 2 targets the original high rows, the approval ids are distinct/ordered, newly mutated rows are excluded from approval 2, and no `Run complete` text appears before approval 2 commits.
- Asserted final Go DB priorities, Factory Agent approval rows, snapshot status, timeline approval evidence, activity steps, plan audit rows, final assistant text, visible UI, and `/ready` registry health all agree.
- Kept the seeded Phase 6 pipeline intact and fixed a small scenario-89 UI race by waiting until the expired approval fixture is actually visible before driving the API replay.
- Fixed real product issues exposed by Phase 7: OpenAPI tool preload now works without seeded mode, graph bulk-write validation no longer truncates committed row-level audit plans, approval-resume fallback carries commit outputs, completed graph audit plans can persist all committed row steps, and completed graph executions replace raw quick summaries with deterministic post-commit recaps.

Commands run:

```powershell
Set-Location "factory-agent"
python -m py_compile main.py factory_agent\graph\nodes\validate.py factory_agent\graph\planner_graph.py
python -m py_compile main.py factory_agent\graph\nodes\validate.py factory_agent\graph\planner_graph.py factory_agent\services\plan_creation_service.py
python -m py_compile factory_agent\services\plan_creation_service.py
python -m pytest tests\test_phase5_final_validator.py -q

Set-Location "..\eMas Front"
node --check e2e/support/fullStackEnv.js; node --check e2e/support/startRealLangGraphStackForPlaywright.js; node --check e2e/support/realLangGraphArtifacts.js; node --check e2e/support/realLangGraphScenarios.js; node --check e2e/specs/real-langgraph-critical.spec.js
npm run test:e2e -- --project=chromium-real-langgraph --grep "@critical"
npm run test:e2e -- --project=chromium-seeded --grep "scenario 89"
npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity|@prompt-regression"
```

Test results:

```text
Initial real LangGraph browser runs: failed as intended by the oracle.
  Exposed product/evidence bugs: truncated committed audit steps, missing commit outputs in final evidence, completed bulk audit persistence capped at 10 steps, and raw-output final assistant text.

Final real LangGraph browser proof:
  chromium-real-langgraph @critical: 1 passed in 12.7s.

Focused backend guard:
  tests/test_phase5_final_validator.py: 17 passed, 4 warnings in 0.96s.

Seeded pipeline regression:
  First full seeded run after Phase 7: 11 passed, 1 failed.
    Reason: scenario 89 drove an expired-approval API replay before the browser had rendered the expired fixture text.
  Focused scenario 89 after UI wait: 1 passed in 11.4s.
  Final chromium-seeded @data-integrity|@prompt-regression: 12 passed in 1.6m.
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `DeprecationWarning` from `factory_agent.observability.telemetry` using `datetime.utcnow()`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope`.

Files changed:

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `eMas Front/playwright.config.js`
- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`
- `eMas Front/e2e/support/fullStackEnv.js`
- `eMas Front/e2e/support/realLangGraphArtifacts.js`
- `eMas Front/e2e/support/realLangGraphScenarios.js`
- `eMas Front/e2e/support/startRealLangGraphStackForPlaywright.js`
- `factory-agent/main.py`
- `factory-agent/factory_agent/graph/nodes/validate.py`
- `factory-agent/factory_agent/graph/planner_graph.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/tests/test_phase5_final_validator.py`

Decisions made:

- Phase 7 is scoped to SO-001 real LangGraph browser proof rather than adding the four additional critical cases in the older checklist.
- The real browser project is opt-in and separate from `chromium-seeded`; it does not delete or replace the seeded adapter pipeline.
- Factory Agent can preload OpenAPI tools for Playwright real-LangGraph runs without enabling seeded planner mode.
- Completed LangGraph bulk-write audit plans may exceed the generic interactive draft step cap only when persisting concrete completed execution evidence.
- Final completed graph responses should prefer the deterministic post-commit recap over the raw quick summary when commit outputs are available.

Blockers/open questions:

- No Phase 7 blockers remain.
- The next real-LangGraph expansion still needs the agreed additional critical scenarios beyond SO-001.
- The durable operation ledger question remains open for Phase 10.

Next action:

Start Phase 8 manual failure promotion before CI restructuring.

## Phase 8 Checklist: Manual Failure Promotion Workflow

- [x] Add manual failure intake template.
- [x] Require exact prompt and artifact link.
- [x] Require observed failure and expected behavior.
- [x] Require selected oracle or new oracle.
- [x] Require lowest useful test layer.
- [x] Require owner/severity.
- [x] Require failing regression before closing.
- [x] Review regression bank weekly until stable.

## Phase 8 Implementation: Manual Failure Promotion Workflow

Status: Done

Updated: 2026-05-16

Scope completed in this pass:

- Added the Phase 8 manual failure promotion workflow and copyable intake/closure template to `docs/qa/manual_prompt_regression_bank.md`.
- Linked the workflow from `eMas Front/e2e/README.md` so QA/devs find it while working in the browser E2E area.
- Extended `tests/e2e/scenarios/manual_prompt_regressions.json` with promotion workflow metadata, closure requirements, accepted-gap blocking status, artifact links, selected oracle mapping, and regression file/command fields.
- Added pytest coverage in `factory-agent/tests/test_phase18_manual_prompt_bank.py` so the bank requires reproducible intake fields, oracle/proposed-oracle mapping, and a failing-regression-before-closure rule.
- Kept Phase 6 seeded and Phase 7 real LangGraph pipelines intact; no seeded or real LangGraph test implementation was weakened or deleted.

Commands run:

```powershell
Set-Location "factory-agent"
python -m py_compile tests\test_phase18_manual_prompt_bank.py
python -m pytest tests/test_phase18_manual_prompt_bank.py tests/test_stateful_oracle_schema.py -q

Set-Location ".."
node -e "JSON.parse(require('fs').readFileSync('tests/e2e/scenarios/manual_prompt_regressions.json','utf8')); console.log('manual_prompt_regressions.json OK')"
```

Test results:

```text
Initial focused pytest run: 7 passed, 1 failed.
  Reason: the JSON closure rule described the red-run requirement but did not include the exact guarded phrase "failing regression".

Final focused pytest run:
  tests/test_phase18_manual_prompt_bank.py tests/test_stateful_oracle_schema.py: 8 passed, 1 warning in 0.63s.

Python syntax check:
  tests\test_phase18_manual_prompt_bank.py: passed.

JSON parse check:
  manual_prompt_regressions.json OK.
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope`.

Files changed:

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`
- `eMas Front/e2e/README.md`
- `factory-agent/tests/test_phase18_manual_prompt_bank.py`
- `tests/e2e/scenarios/manual_prompt_regressions.json`

Decisions made:

- Manual chatbot failures now close only as a promoted regression or an accepted gap with owner, severity, risk, workaround, target phase/date, reason, and blocking status.
- A promoted regression must name a test file, focused command, failing-before-fix evidence, and passing-after-fix evidence.
- The current LOTO manual-prompt bank entries map to existing oracle `SO-021`; future misses must either select an existing oracle or propose a new one.
- The workflow chooses the lowest useful layer first so parser/route defects do not wait for browser coverage, while state, SSE, snapshot, and real LangGraph defects still land in the stronger oracle layer that would have caught them.

Blockers/open questions:

- No Phase 8 blockers remain.
- The weekly bank review cadence is documented; the operational owner remains the QA regression bank owner named by the team.

Next action:

Start Phase 9: CI Gate Restructure. Keep PR gates fast and deterministic, preserve seeded/full-stack and real LangGraph checks as opt-in or release gates until intentionally promoted.

## Phase 9 Checklist: CI Gate Restructure

- [ ] Add fast backend oracle pytest command to PR gate.
- [ ] Keep mocked Chromium in PR gate.
- [ ] Keep seeded data oracles in release/pre-merge gate.
- [ ] Keep real LangGraph browser as opt-in or release gate.
- [ ] Keep production synthetic read-only.
- [ ] Upload oracle artifacts on failure.
- [ ] Document local run commands.

## Phase 10 Checklist: Ledger Refactor Decision

- [ ] Review recurring projection failures.
- [ ] Decide if durable operation ledger is required.
- [ ] If yes, write migration/design plan.
- [ ] If no, document why existing projections are now stable.
- [ ] Keep invariant tests either way.

## Current Blockers

- No Phase 8 blockers remain.
- The remaining backlog is CI restructuring, real LangGraph expansion, and the Phase 10 ledger decision.

## Open Questions

- Should all cascading bulk mutations default to original-state semantics? Current plan says yes unless the oracle explicitly says current-state semantics.
- Which additional scenarios should get non-seeded LangGraph browser coverage next? Proposed: SO-005, SO-011, SO-021, SO-034.
- Is a durable operation ledger required, or can invariant tests stabilize current projections?
- Which CI workflow should block release branches for seeded oracle failures?
- Who is the named QA regression bank owner for the documented weekly review cadence?

## Decisions Made

- Improve the current test stack instead of replacing it.
- Treat weak tests as test defects.
- Use stateful oracles for critical scenarios.
- Do not rely on real LLM calls in deterministic CI.
- Keep Promptfoo/LLM evaluation out of this core contract plan until state, SSE, timeline, and final-response contracts are stable.
- Stop phase progression when a reproducible defect is found.
- For mutating workflows, `COMPLETED` is not sufficient. DB, audit, approvals, timeline, snapshot, final response, and UI must agree.
- For Phase 4 mutating workflows, empty or synthesized timeline evidence is a failing oracle condition.
- A newer pending approval must outrank any stale terminal completion row in frontend turn summaries and activity timelines.
- For Phase 5 stream recovery, stale or unknown `Last-Event-ID` replays current evidence instead of suppressing all rows.
- SSE activity evidence can advance progress UI, but final assistant UI remains gated on terminal snapshot/timeline state.
- For Phase 6 seeded oracles, DB rows, approval rows, audit rows, snapshot, timeline, final response, and visible UI must agree before the scenario can pass.
- Partial-failure copy must name failed row ids, not only aggregate counts.
- Graph-native snapshot tool-result evidence should carry the approval id and be ordered after the matching approval decision.
- Phase 7's first pass proves SO-001 only; the real LangGraph Playwright project stays opt-in and separate from the seeded adapter project.
- Completed LangGraph bulk-write audit plans may exceed the generic draft step cap only when persisting concrete completed execution evidence.
- Final completed graph responses should replace raw quick summaries with deterministic post-commit recaps when commit outputs are available.
- Phase 8 manual failures close only as promoted regressions or accepted gaps; `tested manually only` is not an acceptable closure state.
- New manual misses must capture exact prompt/action, artifact link, observed/expected behavior, oracle mapping, lowest useful layer, owner/severity, failing regression evidence, and passing-after-fix evidence.

## Commands Run

Latest Phase 8 implementation and verification:

```powershell
git status --short
git diff --stat

Set-Location "factory-agent"
python -m py_compile tests\test_phase18_manual_prompt_bank.py
python -m pytest tests/test_phase18_manual_prompt_bank.py tests/test_stateful_oracle_schema.py -q

Set-Location ".."
node -e "JSON.parse(require('fs').readFileSync('tests/e2e/scenarios/manual_prompt_regressions.json','utf8')); console.log('manual_prompt_regressions.json OK')"
```

## Test Results

Phase 8 verification passed after one wording fix:

```text
Initial focused pytest run: 7 passed, 1 failed.
  Reason: JSON closure rule needed to include the exact guarded phrase "failing regression".

Final focused pytest run: 8 passed, 1 warning in 0.63s.
Python syntax check: passed.
JSON parse check: manual_prompt_regressions.json OK.
```

## Files Changed

- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`
- `eMas Front/e2e/README.md`
- `factory-agent/tests/test_phase18_manual_prompt_bank.py`
- `tests/e2e/scenarios/manual_prompt_regressions.json`

## Next Action

Start Phase 9: CI Gate Restructure.
