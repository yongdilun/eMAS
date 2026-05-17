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
| 9 | CI gate restructure | Done | PR gate now runs fast backend stateful oracles, frontend unit tests, and mocked Chromium. Seeded stateful oracles are release/pre-merge/manual; real LangGraph and synthetic remain opt-in/read-only. |
| 10 | Ledger refactor decision | Done | Durable operation ledger is not needed now; keep invariant-backed projections and reopen only on documented trigger conditions. |
| 11 | Aggregate final-response evidence oracles | Done | SO-041 added and verified across summary contract, LangGraph oracle, snapshot/activity contract, frontend pending-approval/timeline/final-bubble projection tests, seeded browser, and real LangGraph browser DOM assertions. Root causes were missing aggregate commit evidence, stale pending-approval UI ownership, and server activity projection letting a later replan row outrank the current approval; not LLM behavior. |
| 12 | Executable enforcement closure | Done | Every current SO oracle now has executable enforcement metadata, a backend contract mapping, and browser-visible proof where UI can diverge. SO-005 has a dedicated browser rejection proof. |
| 13 | Test quality gate and redundancy control | Done | Added coverage categories, current SO risk-group map, duplicate-candidate review, future scenario authoring gate, and lean PR/release/nightly lane split. No tests were deleted. |
| 14 | Release gate validation | Done | Full automated release sweep is green after fixes. One product bug and two release-smoke test bugs were found and fixed; no routine manual release checks remain as blockers. |
| 15 | CI/release enforcement and ownership | Done | Final PR, release, nightly, and synthetic lanes are documented with commands, owners, blocking levels, and triage rules. CI now enforces the full backend oracle PR alias plus seeded, real LangGraph, and release validation on release/pre-merge branches; synthetic remains read-only and opt-in. |
| 16 | Remaining normal-use breakage scenarios | Done | Added SO-022, SO-023, SO-026, SO-028, and SO-031 with Phase 13 quality-gate metadata, parser/route/backend regressions, seeded browser proof, and SO-026 real LangGraph proof. Fixed missing-machine clarification, multi-turn LOTO context resolution, stale snapshot steps, cancellation terminal evidence, over-broad cancel-command detection, and hidden background completion after cancel. |
| 17 | Security, privacy, and abuse hardening | Done | Added SO-032, SO-033, SO-042, SO-043, and SO-044 with Phase 13 quality-gate metadata. Strengthened mocked security/privacy browser coverage for session switching/refresh leakage, auth-failure stale-response clearing, inert unsafe rendering/link behavior, large pasted input control, and dangerous action no-mutation evidence. |
| 18 | Test reliability, runtime, and flake hardening | Done | Ran the PR lane, listed release/seeded/real LangGraph/security/reliability/synthetic lanes, fixed an event-order race in the mocked activity SSE fixture, and documented runtime, artifact, slow-test, duplicate, and flake triage policy. No functional scenarios were added and no tests were deleted. |

## Phase 18 Test Reliability, Runtime, and Flake Hardening

Completed: 2026-05-17

Scope:

- No new functional chatbot scenarios were added.
- No tests were deleted.
- The only code change was a mocked SSE fixture hardening fix: `activitySseOrdered` now completes after the activity stream delivers its ordered frames instead of completing on an independent timer.

Lane inventory and runtime evidence:

| Lane | Command | Result | Runtime evidence | Owner | Blocking level | Artifact policy |
|---|---|---|---|---|---|---|
| PR backend oracle | `Set-Location "eMas Front"; npm run test:backend-oracles` | Passed: `125 passed, 30 warnings` | pytest 4.18s; wall 7.79s | Factory Agent QA/backend owner | Blocks PR and release | JUnit under `factory-agent/test-results/backend-oracle/` uploaded on failure for 7 days. |
| PR frontend unit/component | `Set-Location "eMas Front"; npm test` | Passed: `64 passed` | node test 9.04s; wall 9.56s | Frontend chat owner | Blocks PR and release | Console output in CI logs; add focused artifacts only when a future component harness needs them. |
| PR mocked Chromium | `Set-Location "eMas Front"; npm run test:e2e:mocked` | Initial Phase 18 run failed 1 SSE test; final rerun after harness fix passed: `21 passed` | initial 36.51s; final fixed run 33.99s | Frontend E2E owner | Blocks PR and release | Playwright report and `test-results/` uploaded on failure for 7 days; config keeps trace/screenshot/video for failures. |
| Seeded release oracle collection | `Set-Location "eMas Front"; npm run test:e2e:seeded-oracles -- --list` | Listed `24 tests in 5 files` | 1.29s collection; last full sweep 24 passed in Phase 16/17 evidence | Seeded L3 owner | Blocks release/pre-merge | Playwright report, traces, screenshots, videos, and seeded stack logs uploaded on failure for 14 days. |
| Real LangGraph collection | `Set-Location "eMas Front"; npm run test:e2e:real-langgraph -- --list` | Listed `3 tests in 1 file` | 1.01s collection; last full sweep 3 passed across Phase 16/17 evidence | Factory Agent/LangGraph owner | Blocks release/pre-merge | Playwright report, traces, screenshots, videos, and real LangGraph stack logs uploaded on failure for 14 days. |
| Release validation collection | `Set-Location "eMas Front"; npm run test:e2e:release -- --list` | Listed `21 tests in 3 files` | 0.92s collection; last full Phase 14 sweep 36.24s | Release L4 owner | Blocks release/pre-merge | Release project captures trace, screenshot, and video for every run; CI uploads report and `test-results/` on failure for 14 days. |
| Security/privacy mocked collection | `Set-Location "eMas Front"; npm run test:e2e -- --project=chromium --grep "@security\|@privacy" --list` | Listed `6 tests in 1 file` | 1.44s collection; latest full Phase 17 run passed 6 tests | Security/privacy owner | Opt-in; blocks release only if promoted by owner or operational gate | Mocked Playwright failure artifacts follow the default failure-only trace/screenshot/video policy. |
| Security/privacy release collection | `Set-Location "eMas Front"; npm run test:e2e:release -- --grep "@security\|@privacy" --list` | Listed `3 tests in 1 file` | 1.11s collection; latest full Phase 17 run passed 3 tests | Security/privacy owner / release L4 owner | Release cross-check; blocks release when explicitly selected | Release trace/screenshot/video policy applies; sensitive fields must be redacted before retention. |
| Reliability mocked collection | `Set-Location "eMas Front"; npm run test:e2e:reliability -- --list` | Listed `5 tests in 1 file` | 1.23s collection | Reliability owner | Scheduled/dispatch; blocks operational signoff | Reliability workflow uploads report and `test-results/` on every run for 14 days. |
| Reliability seeded collection | `Set-Location "eMas Front"; npm run test:e2e:reliability:seeded -- --list` | Listed `2 tests in 1 file` | 1.12s collection | Reliability owner / seeded L3 owner | Scheduled/dispatch; blocks operational signoff | Reliability workflow uploads seeded stack logs and Playwright artifacts on every run for 14 days. |
| Synthetic collection | `Set-Location "eMas Front"; npm run test:e2e:synthetic -- --list` | Listed `9 tests in 1 file` | 1.08s collection; last full Phase 14 local harness 41.94s | Synthetic L5 owner / `chatbot-oncall` | Does not block PR; live critical alerts can block rollout/trigger rollback | Synthetic keeps trace on failure, disables automatic screenshots/video by project for privacy, and attaches redacted logs/result files plus masked screenshots where feasible. |

Flake found and fixed:

| ID | Classification | Symptom | Root cause | Fix | Verification |
|---|---|---|---|---|---|
| F18-001 | Test/harness bug | `chat-sse-activity.spec.js` sometimes saw zero mocked activity EventSource connections while the final UI was already complete. | The mock `activitySseOrdered` scenario completed on a fixed timer. Under parallel load, completion could win before React opened the activity stream, so the UI fell back to terminal snapshot activity and the stream-specific assertion failed. | Completion is now event-driven from the final mocked activity SSE frame via an `afterSent` hook; this preserves the scenario's real oracle without relying on a longer timeout. | Focused activity SSE passed: `1 passed`; full mocked Chromium rerun passed: `21 passed`. |

Slow or duplicate tests to keep out of the PR critical path:

| Test/lane | Classification | Policy |
|---|---|---|
| `reliability-soak.spec.js` scenario 95 | Slow soak/nightly | Keep in `npm run test:e2e:reliability` and scheduled reliability workflow only. Do not include in un-grepped PR Chromium. |
| `full-stack-reliability.spec.js` scenario 93 vs SO-031 seeded prompt workflow | Supporting duplicate of large-result layout risk | Keep scenario 93 as nightly/seeded reliability evidence only; SO-031 remains the seeded oracle closure for release. |
| Release scenarios that repeat seeded stateful outcomes without auth/proxy/polling evidence | Smoke, not oracle closure | Keep in `chromium-release` for deployment wiring. Do not count them as replacements for seeded DB/audit/approval oracles. |
| Seeded cascade matrix in `full-stack-prompt-workflow-regression.spec.js` plus focused data-integrity cascades | Intentional cross-layer overlap, possible duplicate candidate for future review | Keep until Phase 13 marks a specific duplicate and the tracker names the replacement command. Future cascades should add parser/graph evidence first before another browser variant. |
| Mocked `normal-use-hardening.spec.js` scenario 81 and `prompt-workflow-regression.spec.js` scenario 116/124 | Broad PR smoke with slower individual runtime | Keep while the mocked PR lane stays near the current 34s wall time. If mocked PR exceeds 60s median, move these to a separate smoke/nightly grep before removing any canonical oracle. |

Flake triage policy:

| Classification | Rule |
|---|---|
| One-off infra failure | Rerun once only when the evidence points to host, install, browser download, port collision, process startup, or transient dependency failure and the focused test passes without code changes. Record command, artifact link, owner, and date. If it repeats twice in 7 days, promote to test bug or environment bug. |
| Deterministic product bug | If the failure reproduces with a focused command or shows a stable DB/audit/snapshot/final UI mismatch, block the lane. Fix product behavior, add or update the lowest useful regression, then rerun the focused command plus the owning lane. |
| Test bug | If the product evidence is correct but the assertion is racing, using the wrong selector, relying on fixed sleeps, or the fixture is invalid, fix the harness with event-driven synchronization, stable test data, or a lower-layer oracle. Do not paper over with timeout bumps unless the timeout is tied to a documented latency budget. |
| Accepted temporary quarantine | Allowed only with owner, issue/link, reason, replacement coverage, affected command, expiry or target date, and blocking decision in the tracker. Critical/high mutating state or privacy leaks cannot be quarantined without release-owner approval. Quarantines are reviewed weekly and removed after the fix. |

Artifact confirmation:

- Default Playwright projects capture `trace: retain-on-failure` locally and `trace: on-first-retry` in CI, `screenshot: only-on-failure`, and `video: retain-on-failure`.
- `chromium-release` captures trace, screenshot, and video on every run because release failures often need proxy/build evidence.
- `chromium-synthetic` keeps failure traces but intentionally disables automatic screenshot/video for privacy; redacted synthetic result files and masked screenshots are attached by the synthetic fixture where feasible.
- CI uploads backend JUnit artifacts, Playwright reports, `test-results/`, seeded/real/release stack logs, reliability soak results, and redacted synthetic output according to lane retention.

Files changed:

- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/README.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`

Current blockers:

- None.

Next action:

Keep the PR gate on backend oracles, frontend unit/component, and mocked Chromium. Do not add new scenarios until the next batch names a distinct product bug and passes the Phase 13 quality gate.

## Phase 17 Security, Privacy, and Abuse Hardening

Completed: 2026-05-17

Scenarios changed:

| SO | Coverage category | Distinct bug / gap | Lowest useful layer | Browser required | Real LangGraph required |
|---|---|---|---|---|---|
| SO-032 | `canonical` | Valid same-user session switches or refreshes could leave another session's final response, approval card, source table, audit evidence, or hidden details in the DOM. Existing tampered-storage coverage did not exercise valid-session switching and details/table/approval cleanup. | Mocked browser | Yes, stale DOM state is the defect. | No |
| SO-033 | `canonical` | Missing/invalid auth on snapshot, SSE, or polling could show retry/error UI while retaining a stale previous assistant response. Existing API auth probes could miss stale browser transcript state. | API probe plus mocked browser | Yes, stale response suppression is visible UI behavior. | No |
| SO-042 | `canonical` | Backend/model script-like text, image handlers, unsafe HTML links, or unsafe markdown links could execute or create unsafe anchors. Existing inert-render coverage did not include unsafe link behavior. | Mocked browser | Yes, execution and anchor attributes are browser-only evidence. | No |
| SO-043 | `canonical` | Very long pasted prompts could break controlled input state, silently lose the request body, leave a spinner stuck, or reuse stale final text. Existing large-result tests covered large responses, not large user input. | Mocked browser | Yes, composer/request lifecycle behavior is browser-visible. | No |
| SO-044 | `canonical` | Dangerous prompts such as `delete all production jobs without approval` or `bypass approvals and apply the changes directly` could bypass approval, mutate unsupported records, or show fake completion. Existing allowlist coverage did not prove no mutation after an attempted approval. | Mocked browser | Yes, approval card, safe blocked copy, and request-log evidence must agree. | No unless a real planner safety miss appears |

Files changed:

- `eMas Front/e2e/specs/security-privacy.spec.js`
- `eMas Front/e2e/support/securityScenarios.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `eMas Front/e2e/README.md`
- `tests/e2e/scenarios/stateful_oracles/so-032_cross_session_leakage_security_privacy.json`
- `tests/e2e/scenarios/stateful_oracles/so-033_authorization_failure_stale_response.json`
- `tests/e2e/scenarios/stateful_oracles/so-042_unsafe_rendered_content_inert.json`
- `tests/e2e/scenarios/stateful_oracles/so-043_large_pasted_input_controlled.json`
- `tests/e2e/scenarios/stateful_oracles/so-044_unsupported_dangerous_action_blocked.json`
- `docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Commands and results:

| Command | Result |
|---|---|
| `Set-Location "eMas Front"; npm run test:e2e -- --project=chromium --grep "@security|@privacy"` | Passed: `6 passed` |
| `Set-Location "factory-agent"; python -m pytest tests/test_stateful_oracle_schema.py -q` | Passed: `3 passed, 1 warning` |
| `Set-Location "eMas Front"; npm test` | Passed: `64 passed` |
| `Set-Location "eMas Front"; npm run test:backend-oracles` | Passed: `125 passed, 30 warnings` |
| `Set-Location "eMas Front"; npm run test:e2e:release -- --grep "@security|@privacy"` | Passed: `3 passed` |

Bugs found and fixed:

| ID | Severity | Scenario | Root cause | Fix |
|---|---|---|---|---|
| P17-001 | High privacy risk | SO-033 | A denied snapshot during session restore/switch could leave the previous authorized session state in memory because stale state was only cleared for `not_found`, not `auth`. | `useFactoryAgentChat` now clears active snapshot state and local active-session storage on auth-denied snapshot refreshes, preventing stale final responses after missing/invalid auth. |

Test/harness issues fixed:

| ID | Issue | Fix |
|---|---|---|
| T17-001 | Parallel mocked security tests seeded sessions with duplicate display names, making session-switch selectors ambiguous. | Security seed names now include the per-test run id. |
| T17-002 | The very large paste fixture exceeded the default Chromium test budget while typing in parallel. | Kept the input above the large-paste threshold and set the focused scenario timeout to 60 seconds. |

Accepted gaps:

- None.

Remaining risks:

- SO-044 is deterministic mocked-browser coverage for the UI approval/allowlist boundary. Add real LangGraph safety coverage only if a planner or live tool-selection miss escapes this deterministic boundary.
- SO-033 release cross-check validates unauthenticated REST/polling/EventSource probes in the release proxy, while stale-response clearing is enforced in mocked browser where valid prior session state can be constructed deterministically.

Next action:

Keep future security additions behind the same Phase 13 quality gate. Do not add more dangerous-prompt wording unless it catches a new route, planner, approval, mutation, or visible stale-state failure.

## Phase 16 Remaining Normal-Use Breakage Scenarios

Completed: 2026-05-17

Scenarios changed:

| SO | Coverage category | Distinct bug / gap | Lowest useful layer | Browser required | Real LangGraph required |
|---|---|---|---|---|---|
| SO-022 | `canonical` | Missing-machine LOTO prompts could mention/invent `M-CNC-01` and look like a successful source-backed answer. Existing successful LOTO tests all supplied a machine id. | Parser/route | Yes, visible clarification/source chrome can diverge. | No |
| SO-023 | `canonical` | Plain lowercase `need lockout tagout for m-cnc-01 before service` could lose normalization or clarify again. Existing lowercase bank entry used different slash wording and was not a named SO-023 oracle. | Parser/route | Yes through the LOTO browser bank loop. | No |
| SO-026 | `canonical` | The LOTO short-circuit ran before previous-turn context resolution, so `it` could clarify or reuse stale status; snapshot also exposed previous-turn steps after the follow-up. Single-turn LOTO tests would miss this. | Parser/context route and snapshot contract | Yes, final visible turn and snapshot can diverge. | Yes |
| SO-028 | `canonical` | Cancellation could be hidden by three defects: a fixture prompt containing `cancel` was treated as a cancel command, cancelled sessions lacked terminal visible evidence, and the background executor could later overwrite cancel with `COMPLETED`. Mocked cancel tests did not prove backend state after the long-running fixture delay. | Seeded full-stack | Yes, cancel button, busy state, final copy, snapshot, audit, and later state must agree. | No |
| SO-031 | `canonical` | Large structured results can hide terminal state or leave stale loading/current UI. Existing reliability coverage was outside the seeded oracle prompt-regression lane. | Seeded full-stack | Yes, layout/visibility/control behavior is the risk. | No |

Files changed:

- `factory-agent/factory_agent/planning/intent.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/services/execution_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/api/routers/messages.py`
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`
- `factory-agent/tests/test_phase7_api_ui_alignment.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `eMas Front/e2e/specs/full-stack-intent-entity.spec.js`
- `eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js`
- `eMas Front/e2e/specs/full-stack-seeded.spec.js`
- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`
- `eMas Front/e2e/support/intentEntityScenarios.js`
- `eMas Front/e2e/support/promptRegressionScenarios.js`
- `tests/e2e/scenarios/stateful_oracles/so-022_loto_missing_machine_id.json`
- `tests/e2e/scenarios/stateful_oracles/so-023_loto_lowercase_punctuation_machine_id.json`
- `tests/e2e/scenarios/stateful_oracles/so-026_multiturn_loto_followup_after_completion.json`
- `tests/e2e/scenarios/stateful_oracles/so-028_cancel_during_executing_graph.json`
- `tests/e2e/scenarios/stateful_oracles/so-031_large_structured_result_layout_final_state.json`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Commands and results:

| Command | Result |
|---|---|
| `Set-Location "factory-agent"; python -m pytest tests/test_stateful_oracle_schema.py tests/test_phase18_manual_prompt_bank.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase19_prompt_workflow_regression.py tests/test_phase7_api_ui_alignment.py -q` | Passed: `89 passed, 26 warnings` |
| `Set-Location "eMas Front"; npm test` | Passed: `64 passed` |
| `Set-Location "eMas Front"; npx playwright test e2e/specs/full-stack-intent-entity.spec.js --project=chromium-seeded --grep "SO-022"` | Passed: `1 passed` |
| `Set-Location "eMas Front"; npx playwright test e2e/specs/full-stack-prompt-workflow-regression.spec.js --project=chromium-seeded --grep "SO-022|SO-023|SO-026|SO-031"` | Passed: `3 passed` (`SO-022` is enforced in `full-stack-intent-entity.spec.js`; this file contains SO-023/SO-026/SO-031) |
| `Set-Location "eMas Front"; npx playwright test e2e/specs/full-stack-seeded.spec.js --project=chromium-seeded --grep "SO-028"` | Passed: `1 passed` |
| `Set-Location "eMas Front"; npm run test:e2e:real-langgraph -- --grep "SO-026"` | Passed: `1 passed` |
| `Set-Location "eMas Front"; npm run test:e2e:seeded-oracles` | Passed: `24 passed` |

Bugs found and fixed:

| ID | Severity | Scenario | Root cause | Fix |
|---|---|---|---|---|
| P16-001 | High safety-answer risk | SO-022 | Missing-machine clarification and the seeded RAG fixture could name/default to `M-CNC-01`, violating the no-invented-machine rule. | Clarification now asks for the exact machine ID from the equipment label/work order, and seeded RAG no longer defaults machine-specific LOTO lookups to the CNC fixture when no machine ID is extracted. |
| P16-002 | High route/context risk | SO-026 | LOTO clarification/RAG short-circuit ran before previous-turn context could resolve `it`. | Resolve the machine from the immediately previous turn, store it as structured `replan_context.contextual_resolution`, and augment only the private RAG query instead of mutating `session.current_intent`. |
| P16-003 | High stale-snapshot risk | SO-026 | Current session snapshot exposed previous-plan steps after a follow-up no-step RAG answer. | Snapshot step projection is now scoped to the current plan. |
| P16-004 | Medium cancel-command risk | SO-028 | Any user message containing `cancel` triggered cancellation, including the seeded cancellable fixture prompt. | Cancel detection now matches explicit cancel/stop commands instead of arbitrary mentions. |
| P16-005 | High cancellation-state risk | SO-028 | Cancelled `IDLE` sessions lacked terminal cancellation timeline/activity evidence, leaving stale in-progress UI. | Snapshot projection now uses shared cancellation lifecycle helpers to synthesize a `session_failed` terminal event with `reason=cancelled_by_user` and a safe `Run cancelled` activity row. |
| P16-006 | High hidden-continuation risk | SO-028 | Background execution could finish after cancel and overwrite the session with `COMPLETED`. | Plan creation and background execution now refresh cancellation state and ignore late planner results after cancel. |

Accepted gaps:

- None.

Remaining risks:

- SO-031 uses the existing visible table plus activity expand/collapse and snapshot row-count evidence; the current product does not render the large read-only table behind a separate details disclosure.
- SO-026 real LangGraph proof focuses on previous-turn context and no stale clarification/status answer. Source availability remains covered by seeded RAG/source projection, not by live RAG content quality.

Next action:

Continue with the next Phase 13-ranked group only if it catches a distinct product bug that is not already represented by the current parser/route, seeded full-stack, real LangGraph, or release lanes. Avoid adding more LOTO wording browser variants unless seeded adapters or visible source projection hide a new failure mode.

## Phase 14 Release Gate Validation

Completed: 2026-05-17

Decision:

The current automated chatbot pipeline is ready to replace routine manual release testing after the fixes in this phase. Manual work remains only for human semantic review, compliance/sign-off, exploratory discovery, and emergency incident diagnosis.

### Commands, Results, and Runtime

| Gate | Exact command | Result | Runtime | Notes |
|---|---|---|---:|---|
| Backend oracle/schema/manual-bank | `Set-Location "factory-agent"; python -m pytest tests/test_stateful_oracle_schema.py tests/test_phase18_manual_prompt_bank.py tests/test_stateful_oracle_harness.py tests/test_langgraph_state_machine_oracles.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py tests/test_phase19_prompt_workflow_regression.py tests/test_summary_bundle.py tests/test_event_stream_runtime.py -q` | Passed: `112 passed, 24 warnings` | 4.76s | Warnings are existing LangGraph, SQLAlchemy, datetime, telemetry, and pytest-asyncio deprecations. |
| Frontend unit/component | `Set-Location "eMas Front"; npm test` | Initial pass: `63 passed`; final pass after cancellation fix: `64 passed` | 9.29s initial; 15.77s final | Added one focused cancellation summary regression because the sweep exposed a real coverage gap. |
| Mocked Chromium PR smoke | `Set-Location "eMas Front"; npm run test:e2e:mocked` | Initial run failed: `19 passed, 2 failed`; final run passed: `21 passed` | 31.30s initial; 31.69s final | Initial failures exposed the product cancellation-summary bug fixed in this phase. |
| Seeded Playwright oracle suite | `Set-Location "eMas Front"; npm run test:e2e:seeded-oracles` | Passed: `20 passed`; final rerun passed: `20 passed` | 167.35s initial; 179.66s final | Covers `@data-integrity`, `@prompt-regression`, and seeded `@sse` oracle checks. |
| Focused real LangGraph critical suite | `Set-Location "eMas Front"; npm run test:e2e:real-langgraph` | Passed: `2 passed`; final rerun passed: `2 passed` | 19.24s initial; 18.29s final | Covers SO-001/SO-035 and SO-041 real LangGraph browser proofs. |
| Release/SSE/polling smoke | `Set-Location "eMas Front"; npm run test:e2e -- --project=chromium-release` | Initial run failed: `19 passed, 2 failed`; final run passed: `21 passed` | 90.28s initial; 36.24s final | Initial failures were release-smoke test bugs, not product defects. SO-017 static bearer polling fallback passed. |
| Read-only synthetic SSE/polling monitor | `Set-Location "eMas Front"; npm run test:e2e:synthetic` | Passed: `9 passed`; final rerun passed: `9 passed` | 42.16s initial; 41.94s final | Includes scenario 74 SSE-or-polling canary. Local run used the release harness, not live production. |

Focused reruns and syntax checks:

```powershell
Set-Location "eMas Front"
node --check "e2e/specs/release-resilience.spec.js"
npm run test:e2e -- --project=chromium-release --grep "scenario 66|scenario 70"
node --check "src/components/features/chat/turns/turnAssembler.js"
node --test --test-concurrency=1 "src/components/features/chat/turns/turnAssembler.test.mjs"
npm run test:e2e:mocked -- --grep "cancel active run|scenario 85"
```

Focused results:

- Release scenario 66/70 focused rerun after release-smoke assertion fix: `2 passed` in 23.39s.
- Release scenario 66/70 focused rerun after whitespace-tolerant summary assertion: `2 passed` in 23.07s.
- Turn assembler focused regression suite: `13 passed` in 0.10s.
- Mocked cancellation focused rerun: `2 passed` in 14.38s.

### Bugs Found

Product bug:

| ID | Severity | Failure | Root cause | Fix | Verification |
|---|---|---|---|---|---|
| P14-001 | High for PR confidence; medium for release risk | Mocked cancel flows stayed on `The run is active and can be cancelled.` after cancel instead of showing `Run cancelled by operator request.` | Frontend failed-session summary selection preferred stale active plan copy over a terminal `session_failed` event with `details.reason=cancelled_by_user`. | `turnAssembler.js` now lets explicit operator cancellation terminal copy win over stale plan copy; added a unit regression in `turnAssembler.test.mjs`. | Focused unit `13 passed`; focused browser cancellation `2 passed`; full `npm test` and `npm run test:e2e:mocked` passed. |

Test bugs:

| ID | Failure | Fix | Verification |
|---|---|---|---|
| T14-001 | Release scenario 66 expected stale `Approved request to change record` after approval. Current UI correctly shows the final success summary/job evidence. | Updated the assertion to require `Run complete`, `Updated 1 job(s).`, `JOB-SEED-005`, no stale `Approved request to change record`, and no mobile dialog overflow. | Focused release reruns passed; full `chromium-release` passed. |
| T14-002 | Release scenario 70 waited for a helper summary that was present only in hidden details. Visible final evidence was the structured `Long Stream Terminal: true` field. | Updated the assertion to wait for the visible structured terminal field and terminal snapshot state. | Focused release reruns passed; full `chromium-release` passed. |

No backend product bugs were found in the oracle/schema/manual-bank, seeded, real LangGraph, release, or synthetic gates.

### Flaky or Slow Tests

- No flaky tests remained after the fixes and focused reruns.
- Slow but expected: seeded oracle suite is the longest deterministic release gate at about 3 minutes; the slowest individual seeded cases were cascade/prompt workflows around 12-17s each.
- Mocked Chromium scenario 81 took about 25s during the final full mocked run; keep it PR-visible but watch for future growth.
- Release scenario 70 long-stream smoke took about 7-9s after the assertion fix. The earlier 60s wait was a test bug waiting on hidden text.
- Synthetic monitor suite takes about 42s locally and should stay nightly/post-deploy rather than default PR.

### Remaining Manual-Only Checks

Routine manual chatbot release regression can be retired. Remaining manual-only checks are:

- Nuanced answer quality, tone, and domain usefulness beyond structural assertions.
- Compliance or regulated wording sign-off.
- Exploratory discovery for brand-new prompts, workflows, or unmodeled operational risks.
- Emergency incident diagnosis when automation, harnesses, or telemetry are unavailable.

These are not routine release blockers unless an owner explicitly promotes one to a release exception.

### Release-Blocking Gaps

- None open after the final green sweep.
- No accepted gap was added for Phase 14.
- No new SO scenario was added. One unit regression was added because the release sweep exposed a real product coverage gap in cancellation terminal summary selection.

### Recommended Command Split

PR / fast blocking:

```powershell
Set-Location "eMas Front"
npm run test:backend-oracles
npm test
npm run test:e2e:mocked
```

Release / pre-merge blocking:

```powershell
Set-Location "eMas Front"
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
npm run test:e2e:release
```

Nightly / post-deploy / opt-in:

```powershell
Set-Location "eMas Front"
npm run test:e2e:synthetic
npm run test:e2e:operational
npm run test:e2e:reliability
npm run test:e2e:reliability:seeded
```

## Phase 15 CI/Release Enforcement and Ownership

Completed: 2026-05-17

Decision:

The chatbot automation stack is now treated as an operating model, not only a test suite. PR, release/pre-merge, nightly/operational, and synthetic lanes have explicit commands, owners, blocking levels, and failure triage rules. No new product scenarios were added in this phase.

### Current CI and Script Findings

| Area inspected | Finding | Action |
|---|---|---|
| `eMas Front/package.json` | Existing aliases covered mocked, seeded, real LangGraph, synthetic, and operational lanes. `test:backend-oracles` still pointed at the older two-file subset, and release/reliability aliases were missing. | Expanded `test:backend-oracles` to the full Phase 14 fast backend gate. Added `test:e2e:release`, `test:e2e:reliability`, and `test:e2e:reliability:seeded` because they follow the existing `test:e2e:*` convention. |
| `.github/workflows/playwright-e2e.yml` | PR CI ran only the older two-file backend oracle subset. Seeded release/pre-merge was enforced, but real LangGraph and release validation were dispatch-only. | Updated PR backend pytest to the full oracle/schema/manual-bank command. Added release validation dispatch input and release validation job. Promoted real LangGraph and release validation to run on `main`, `release/**`, and `pre-merge/**` pushes. |
| `.github/workflows/playwright-reliability-soak.yml` | Reliability workflow used raw Playwright project/grep commands. | Switched to the new reliability aliases. |
| `eMas Front/playwright.config.js` | Projects already exist for `chromium`, `chromium-seeded`, `chromium-real-langgraph`, `chromium-release`, and `chromium-synthetic`; mocked default excludes slow/release/synthetic specs unless explicitly grepped. | No config change required. |
| `pytest.ini` and `factory-agent/pyproject.toml` | Pytest config is minimal; no marker or addopts change was needed for the final backend lane. | No config change required. |

### Final Command Lanes

| Lane | Exact command | CI enforcement | Blocking level | Owner | Runtime |
|---|---|---|---|---|---:|
| Backend oracle/schema/manual-bank | `Set-Location "eMas Front"; npm run test:backend-oracles` | Pull requests and protected branch pushes through `pr-fast-oracle-gate` | Blocks PR and release | Factory Agent QA/backend owner | Phase 14: 4.76s |
| Frontend unit/component | `Set-Location "eMas Front"; npm test` | Pull requests and protected branch pushes through `pr-fast-oracle-gate` | Blocks PR and release | Frontend chat owner | Phase 14 final: 15.77s |
| Mocked Chromium PR smoke | `Set-Location "eMas Front"; npm run test:e2e:mocked` | Pull requests and protected branch pushes through `pr-fast-oracle-gate` | Blocks PR and release | Frontend E2E owner | Phase 14 final: 31.69s |
| Seeded Playwright oracles | `Set-Location "eMas Front"; npm run test:e2e:seeded-oracles` | Push to `main`, `release/**`, `pre-merge/**`, or workflow dispatch | Blocks release/pre-merge | Seeded L3 owner | Phase 14 final: 179.66s |
| Real LangGraph critical proof | `Set-Location "eMas Front"; npm run test:e2e:real-langgraph` | Push to `main`, `release/**`, `pre-merge/**`, or workflow dispatch | Blocks release/pre-merge | Factory Agent/LangGraph owner | Phase 14 final: 18.29s |
| Release validation | `Set-Location "eMas Front"; npm run test:e2e:release` | Push to `main`, `release/**`, `pre-merge/**`, or workflow dispatch | Blocks release/pre-merge | Release L4 owner | Phase 14 final: 36.24s |
| Nightly mocked reliability | `Set-Location "eMas Front"; npm run test:e2e:reliability` | Scheduled/dispatch reliability workflow | Blocks operational signoff; release-blocking only if promoted by owner | Reliability owner | Runtime not captured in Phase 14 release sweep |
| Nightly seeded reliability | `Set-Location "eMas Front"; npm run test:e2e:reliability:seeded` | Scheduled/dispatch reliability workflow | Blocks operational signoff; release-blocking only if promoted by owner | Reliability owner / seeded L3 owner | Runtime not captured in Phase 14 release sweep |
| Operational readiness | `Set-Location "eMas Front"; npm run test:e2e:operational`; `npm run operational:gate` | Manual `Playwright Operational Readiness` dispatch | Critical/high failures block operational signoff | Operational readiness owner / QA governance owner | Runtime depends on selected matrix |
| Synthetic read-only monitor | `Set-Location "eMas Front"; npm run test:e2e:synthetic` | Explicit dispatch or post-deploy/live synthetic schedule | Does not block PR. Local harness failure blocks synthetic lane; live critical failure pages `chatbot-oncall` and may block rollout or trigger rollback. | Synthetic L5 owner / `chatbot-oncall` | Phase 14 final: 41.94s |

### Ownership and Blocking Rules

| Failure class | Blocking level | Owner | Failure triage rule |
|---|---|---|---|
| Backend oracle failures | PR and release blocker. | Factory Agent QA/backend owner. | Reproduce with the focused pytest or SO id, classify product vs test bug, fix before merge, and rerun `npm run test:backend-oracles` plus any touched focused command. |
| Frontend unit/component failures | PR and release blocker. | Frontend chat owner. | Reproduce with `npm test` or a focused `node --test` command, identify projection/turn/activity/component ownership, and rerun mocked Chromium if visible DOM can diverge. |
| Seeded Playwright failures | Release/pre-merge blocker. | Seeded full-stack L3 owner. | Inspect Playwright trace, seeded stack logs, DB rows, audit rows, approvals, snapshot, timeline, SSE, final response, and UI. Treat visible-success/persisted-state mismatch as product bug unless proven otherwise. |
| Real LangGraph failures | Release/pre-merge blocker. | Factory Agent/LangGraph owner. | Compare seeded and real-LangGraph evidence. If seeded passes but real fails, triage planner/routing/tool-selection/checkpoint behavior before changing browser assertions. |
| Synthetic read-only monitor failures | Synthetic-lane blocker; live critical alerts can block rollout or trigger rollback but do not block PR. | Synthetic L5 owner / `chatbot-oncall`. | Confirm the canary is read-only, inspect redacted artifacts and alert code, classify dependency outage vs product regression, and never add mutating synthetic prompts. |
| Accepted gaps | Critical/high mutating gaps block release unless an approved exception is recorded. Medium/low gaps require owner, severity, risk, target, reason, and workaround. | QA governance owner. | Review weekly until closed or until two clean release cycles prove the gap is obsolete. |

### Remaining Manual-Only Checks

Routine manual chatbot release regression remains retired. The only manual-only checks left are:

- Nuanced answer quality, tone, and domain usefulness beyond structural assertions.
- Compliance or regulated wording sign-off.
- Exploratory discovery for brand-new workflows or unmodeled operational risks.
- Emergency incident diagnosis when automation, harnesses, or telemetry are unavailable.

These do not block routine release unless an owner promotes one to an accepted gap or release exception.

### Phase 15 Verification Commands

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

Phase 15 verification results:

```text
npm run test:backend-oracles: 112 passed, 24 warnings in 3.69s.
npm test: 64 passed in 8129.721ms.
node --check playwright.config.js: passed.
node --check e2e/support/operationalGate.js: passed.
package.json JSON parse: passed.
workflow YAML parse: passed.
npm run test:e2e:mocked -- --list: 21 tests in 10 files.
npm run test:e2e:seeded-oracles -- --list: 20 tests in 3 files.
npm run test:e2e:real-langgraph -- --list: 2 tests in 1 file.
npm run test:e2e:release -- --list: 21 tests in 3 files.
npm run test:e2e:synthetic -- --list: 9 tests in 1 file.
npm run test:e2e:reliability -- --list: 5 tests in 1 file.
npm run test:e2e:reliability:seeded -- --list: 2 tests in 1 file.
npm run test:e2e:operational -- --list: 5 tests in 1 file.
npm run operational:gate -- --dry-run: printed the full operational matrix with critical/high severities.
git diff --check: passed with LF-to-CRLF warnings only.
```

Warnings observed:

- Existing LangGraph, SQLAlchemy, datetime, telemetry, and pytest-asyncio deprecation warnings in the backend oracle suite.

Files changed in this phase:

- `.github/workflows/playwright-e2e.yml`
- `.github/workflows/playwright-reliability-soak.yml`
- `docs/operations/chatbot_release_runbook.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`
- `eMas Front/e2e/README.md`
- `eMas Front/package.json`

Release-blocking gaps:

- None open.
- No accepted gaps were added.
- No tests or product scenarios were deleted or added.

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

- [x] Add fast backend oracle pytest command to PR gate.
- [x] Keep mocked Chromium in PR gate.
- [x] Keep seeded data oracles in release/pre-merge gate.
- [x] Keep real LangGraph browser as opt-in or release gate.
- [x] Keep production synthetic read-only.
- [x] Upload oracle artifacts on failure.
- [x] Document local run commands.

## Phase 9 Implementation: CI Gate Restructure

Status: Done

Updated: 2026-05-16

Scope completed in this pass:

- Reworked `.github/workflows/playwright-e2e.yml` into `Chatbot Oracle Gates`.
- The default PR/push fast gate now installs Factory Agent test dependencies and runs:
  - `python -m pytest tests/test_langgraph_state_machine_oracles.py tests/test_snapshot_timeline_final_response_contract.py -q`
  - `npm test`
  - `npm run test:e2e:mocked`
- The PR gate uploads backend oracle pytest results plus Playwright report/test-results on failure.
- Added a seeded full-stack oracle job for `main`, `release/**`, `pre-merge/**`, or explicit workflow dispatch. It runs `npm run test:e2e:seeded-oracles`.
- Added explicit workflow-dispatch jobs for real LangGraph critical browser proof and read-only synthetic checks. They do not run on pull requests.
- Updated the Phase 17 operational gate matrix to include backend stateful oracles, seeded data/prompt/SSE oracles, and the real LangGraph critical proof.
- Updated operational readiness CI to install Factory Agent dev test dependencies so the new backend oracle command can run from `npm run operational:gate`.
- Added discoverable npm scripts for local/CI gate commands.
- Fixed a Phase 9 test-gating bug: `real-langgraph-critical.spec.js` was being collected by the default mocked `chromium` project. `playwright.config.js` now excludes `real-langgraph-*` specs from mocked PR runs, keeping real LangGraph opt-in/release-gated only.
- Documented the split gates in `eMas Front/e2e/README.md` and `docs/operations/chatbot_release_runbook.md`.

Commands run:

```powershell
git status --short --branch
Get-Content -Raw -Path 'docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md'
Get-Content -Raw -Path 'docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md'
Get-Content -Raw -Path 'docs/qa/manual_prompt_regression_bank.md'
Get-Content -Raw -Path 'eMas Front/e2e/README.md'
Get-Content -Raw -Path 'eMas Front/package.json'
Get-Content -Raw -Path 'eMas Front/playwright.config.js'
Get-Content -Raw -Path '.github/workflows/playwright-e2e.yml'
Get-Content -Raw -Path '.github/workflows/playwright-operational-readiness.yml'
Get-Content -Raw -Path '.github/workflows/playwright-reliability-soak.yml'
Get-Content -Raw -Path 'docs/operations/chatbot_release_runbook.md'

Set-Location "eMas Front"
npm run test:backend-oracles
npm test
node --check "e2e/support/operationalGate.js"
node -e "JSON.parse(require('fs').readFileSync('package.json','utf8')); console.log('package.json OK')"
npm run test:e2e:mocked -- --list
npm run test:e2e:seeded-oracles -- --list
npm run test:e2e:real-langgraph -- --list
node --check playwright.config.js
npm run test:e2e:synthetic -- --list
npm run operational:gate -- --dry-run
npm run test:e2e:mocked

Set-Location ".."
python -c "import yaml, pathlib; [yaml.safe_load(p.read_text()) for p in pathlib.Path('.github/workflows').glob('*.yml')]; print('workflow yaml OK')"
git diff --check
git status --short
git diff --stat
```

Test results:

```text
Backend oracle PR command:
  npm run test:backend-oracles: 21 passed, 1 warning in 1.20s.

Frontend unit suite:
  npm test: 53 passed in 7240.0161ms.

Mocked Chromium PR browser suite:
  npm run test:e2e:mocked: 21 passed in 36.0s.

Package/script syntax:
  e2e/support/operationalGate.js node --check: passed.
  package.json JSON parse: passed.
  playwright.config.js node --check: passed.

Workflow YAML sanity:
  PyYAML parsed all `.github/workflows/*.yml`: passed.
  Ruby YAML check was attempted first but Ruby is not installed locally.

Playwright command wiring:
  npm run test:e2e:mocked -- --list: 21 tests, and real LangGraph is no longer collected by mocked Chromium.
  npm run test:e2e:seeded-oracles -- --list: 14 tests in 3 files.
  npm run test:e2e:real-langgraph -- --list: 1 test in 1 file.
  npm run test:e2e:synthetic -- --list: 9 read-only synthetic tests in 1 file.

Operational gate dry run:
  npm run operational:gate -- --dry-run: listed backend oracles, mocked Chromium, seeded oracles, real LangGraph, release, synthetic, security/privacy, and reliability lanes.

Diff hygiene:
  git diff --check: passed with line-ending warnings only.
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope`.
- Git line-ending warnings noted that LF will be replaced by CRLF next time Git touches the edited files.

Files changed:

- `.github/workflows/playwright-e2e.yml`
- `.github/workflows/playwright-operational-readiness.yml`
- `docs/operations/chatbot_release_runbook.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/support/operationalGate.js`
- `eMas Front/package.json`
- `eMas Front/playwright.config.js`

Decisions made:

- The default PR gate blocks fast deterministic backend oracle regressions, frontend unit regressions, and mocked Chromium browser regressions only.
- Seeded stateful data/prompt/SSE oracles run on `main`, `release/**`, `pre-merge/**`, or manual dispatch, not on pull requests.
- Real LangGraph browser proof stays explicit workflow dispatch and release/operational gated; it is excluded from mocked Chromium collection.
- Synthetic checks remain opt-in and read-only. The CI dispatch uses the local release harness by default; live production/staging mode still requires explicit read-only credentials and prompts.
- Browser/oracle failure artifacts are retained via workflow artifact uploads for backend pytest, mocked Chromium, seeded oracles, real LangGraph, and synthetic jobs.

Blockers/open questions:

- No Phase 9 blockers remain.
- The named QA regression bank owner is still a team/process question from Phase 8.
- The durable operation ledger question remains open for Phase 10.

Next action:

Start Phase 10: Ledger Refactor Decision. Review recurring projection failures from Phases 3-9 and decide whether the current invariant-backed projections are sufficient or whether a durable operation ledger is needed.

## Phase 10 Checklist: Ledger Refactor Decision

- [x] Review recurring projection failures.
- [x] Decide if durable operation ledger is required.
- [x] If yes, write migration/design plan. Not applicable: ledger is not required now.
- [x] If no, document why existing projections are now stable.
- [x] Keep invariant tests either way.

## Phase 10 Implementation: Ledger Refactor Decision

Status: Done

Updated: 2026-05-16

Decision:

Do not implement a durable operation ledger in this phase. The current invariant-backed snapshot, timeline, SSE, approval, audit, and final-response projections are stable enough for now. Keep a durable ledger as a future refactor option if the guardrail tests start showing repeated projection fragility.

Evidence reviewed from Phases 3-9:

- Phase 3 added LangGraph state-machine invariants for cursor movement, staged-write cleanup, distinct approvals, rejection, timeout, stale approval, no hidden continuation, and original-state cascade semantics. No product defect was found in that phase.
- Phase 4 added the snapshot/timeline/final-response contract and fixed a frontend projection bug where stale terminal completion from approval 1 could outrank newer pending approval 2.
- Phase 5 added runtime and browser SSE contracts and fixed an SSE reconnect bug where stale or unknown `Last-Event-ID` could suppress all current activity/timeline rows.
- Phase 6 found real backend projection bugs and fixed them in `session_snapshot_service.py`: approval-wait copy no longer projects as `session_completed`, plan timeline rows keep their real creation time instead of being backdated before approvals, and commit tool-result evidence carries approval ids ordered after matching approval decisions.
- Phase 7 found real LangGraph evidence bugs and fixed them: OpenAPI tool preload without seeded mode, non-truncated bulk audit plans, approval-resume commit outputs, completed bulk audit persistence beyond the old step cap, and deterministic post-commit recaps.
- Phase 9 moved the fast backend state-machine and snapshot/final-response oracle suite into the PR gate while preserving seeded and real LangGraph release/dispatch gates.

Projection/product audit:

- Snapshot/timeline/activity/final projection is centralized server-side in `factory-agent/factory_agent/services/session_snapshot_service.py`, derived from existing durable sessions, messages, plans, plan steps, approvals, execution snapshots, and workflow checkpoints.
- SSE in `factory-agent/factory_agent/api/routers/events.py` does not own terminal business state; notification, activity, and semantic streams poll the same snapshot projection and add only stream-level duplicate/reconnect semantics.
- Approval and final-response copy helpers in `factory-agent/factory_agent/graph/approval_summary.py` and `factory-agent/factory_agent/analysis/summary_backend.py` format structured facts; they do not decide terminal state.
- The frontend still has fallback turn/activity projection logic, but server `activity_steps` and timeline are preferred, and unit tests guard stale terminal rows, pending approvals, and terminal-gated assistant visibility.
- Duplicated logic remains mainly in UI fallback projection and user-facing activity labels. That duplication is acceptable while it remains a fallback and is covered by frontend tests; it is not an independent source of commit/approval truth.

Remaining risks:

- New workflow shapes can still expose mapping gaps because the snapshot is synthesized from several existing tables and LangGraph checkpoint data.
- Frontend fallback activity/turn logic can drift if new timeline event types are added without fixtures.
- Real LangGraph browser proof currently covers SO-001 only; SO-005, SO-011, SO-021, and SO-034 remain proposed next expansions.
- Forensic replay is limited to existing rows, checkpoints, audit evidence, and oracle artifacts rather than a single append-only event table.

Guardrail tests that must stay in CI:

- Fast PR backend oracles: `python -m pytest tests/test_langgraph_state_machine_oracles.py tests/test_snapshot_timeline_final_response_contract.py -q`.
- Focused SSE runtime regression: `python -m pytest tests/test_event_stream_runtime.py -q`.
- Frontend projection fixtures: `npm test`.
- Release/pre-merge seeded stateful oracles: `npm run test:e2e:seeded-oracles`.
- Explicit release/dispatch real LangGraph proof: `npm run test:e2e:real-langgraph`.

Reopen the ledger decision if:

- A projection bug recurs after the relevant invariant is already in CI.
- Snapshot, SSE, timeline, final assistant response, and browser UI require a third independent implementation of terminal/approval/commit semantics.
- A workflow needs forensic replay of intermediate operation state that existing rows, checkpoints, audit rows, and oracle artifacts cannot reconstruct.
- Seeded or real LangGraph gates start requiring brittle timestamp/order workarounds to keep projections aligned.
- More than two Phase 10-style projection bugs appear in one release cycle.

Commands run:

```powershell
git status --short --branch
Get-Content -Raw -LiteralPath 'docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md'
Get-Content -Raw -LiteralPath 'docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md'
Get-Content -Raw -LiteralPath 'docs/qa/manual_prompt_regression_bank.md'
Get-Content -Raw -LiteralPath 'docs/operations/chatbot_release_runbook.md'
Get-Content -Raw -LiteralPath 'eMas Front/e2e/README.md'
Get-Content -Raw -LiteralPath 'factory-agent/tests/test_snapshot_timeline_final_response_contract.py'
Get-Content -Raw -LiteralPath 'factory-agent/tests/test_event_stream_runtime.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/services/session_snapshot_service.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/api/routers/events.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/analysis/summary_backend.py'
Get-Content -Raw -LiteralPath 'factory-agent/factory_agent/graph/approval_summary.py'
rg -n "ledger|operation_|approval_id|session_completed|final_response|timeline|pending_approval|activity_steps|checkpoint|graph_native|audit|commit" factory-agent/factory_agent/services/session_snapshot_service.py factory-agent/factory_agent/api/routers/events.py factory-agent/factory_agent/analysis/summary_backend.py factory-agent/factory_agent/graph/approval_summary.py factory-agent/factory_agent/persistence/models.py factory-agent/factory_agent/graph factory-agent/tests/test_snapshot_timeline_final_response_contract.py factory-agent/tests/test_event_stream_runtime.py
rg -n "session_completed|approval_required|approval_decided|tool_result|Run complete|final|pending approval|terminal|activity" "eMas Front/src/components/features/chat" "eMas Front/e2e/specs" "eMas Front/e2e/support"

Set-Location "factory-agent"
python -m pytest tests/test_snapshot_timeline_final_response_contract.py tests/test_event_stream_runtime.py -q
python -m pytest tests/test_langgraph_state_machine_oracles.py -q
```

Test results:

```text
tests/test_snapshot_timeline_final_response_contract.py tests/test_event_stream_runtime.py:
  13 passed, 1 warning in 1.23s.

tests/test_langgraph_state_machine_oracles.py:
  14 passed, 1 warning in 1.06s.
```

Warnings observed:

- Existing `LangChainPendingDeprecationWarning` from `langgraph.checkpoint.serde.jsonplus`.
- Existing `PytestDeprecationWarning` for unset `asyncio_default_fixture_loop_scope`.

Files changed:

- `docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`

Decisions made:

- A durable operation ledger is not required now.
- Existing projection paths remain acceptable only while the Phase 3-9 oracle gates stay in CI and release/dispatch workflows.
- The durable ledger decision is reopened by repeated projection bugs, irreconcilable forensic replay needs, brittle timestamp/order workarounds, or any third independent terminal-state implementation.
- Phase 10 is documentation and decision scope only; no seeded, real LangGraph, SSE, snapshot, or PR oracle pipeline was weakened or deleted.

Blockers/open questions:

- No Phase 10 blockers remain.
- The QA regression bank owner question remains open from Phase 8.
- The next real LangGraph expansion still needs prioritization; proposed scenarios remain SO-005, SO-011, SO-021, and SO-034.

Next action:

Expand real LangGraph browser coverage beyond SO-001 when the team is ready, and assign the QA regression bank owner for the weekly review cadence.

## Current Blockers

- No Phase 11 blockers remain.
- The QA regression bank owner question remains open from Phase 8.

## Open Questions

- Should all cascading bulk mutations default to original-state semantics? Current plan says yes unless the oracle explicitly says current-state semantics.
- Phase 11 resolved: approval 1 committed correctly in the deterministic graph path; the defect was in final-response evidence/aggregation, not in real LLM behavior.
- Which additional scenarios should get non-seeded LangGraph browser coverage next? Proposed: SO-005, SO-011, SO-021, SO-034.
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
- Final completed graph responses must aggregate all committed write sets in a multi-approval operation; a recap that only describes the last approval is a test failure when earlier approvals committed.
- Phase 8 manual failures close only as promoted regressions or accepted gaps; `tested manually only` is not an acceptable closure state.
- New manual misses must capture exact prompt/action, artifact link, observed/expected behavior, oracle mapping, lowest useful layer, owner/severity, failing regression evidence, and passing-after-fix evidence.
- Phase 9 PR gates include fast backend stateful oracles, frontend unit tests, and mocked Chromium only.
- Seeded stateful oracles are release/pre-merge/manual gates; real LangGraph browser proof remains opt-in/release-gated and excluded from mocked Chromium collection.
- Production synthetic checks stay opt-in and read-only, with local release harness as the default CI dispatch mode.
- Phase 10 does not implement a durable operation ledger now; invariant-backed projections are acceptable until the documented reopen triggers occur.
- Phase 11 confirms multi-approval final responses must be built from committed write evidence carrying previous state, new state, source-state basis, and approval context; deriving copy from final row state alone is insufficient.
- Phase 11 also confirms current `pending_approval` from the snapshot owns the visible pending-approval summary/table/card. A stale approval 1 decision or waiting message must not render beside approval 2's table while approval 2 is pending.
- Phase 11 live UI regression confirms server `activity_steps` must trim any rows after the latest pending approval when the session is `WAITING_APPROVAL`; otherwise `Improving the response` can become the false current row.
- Phase 11 browser proof must assert visible DOM and forbidden stale text, not only final API text, because API evidence can be correct while the React bubble still renders stale timeline/table/details.
- Activity timeline manual collapse is a user state and must not be overwritten by routine snapshot/SSE refresh while the operation is still active.

## Phase 12 Executable Enforcement Closure

Status: Done.

Purpose: close the gap where SO JSON files existed without executable enforcement. The rule is now explicit: every current SO oracle must be named by a backend contract and, where UI can diverge, by browser-visible assertions that check both required text and forbidden stale text.

Files changed in this phase:

- `tests/e2e/scenarios/stateful_oracles/*.json`
- `factory-agent/tests/support/stateful_oracle_harness.py`
- `factory-agent/tests/support/operation_assertions.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `factory-agent/tests/test_langgraph_state_machine_oracles.py`
- `factory-agent/tests/test_phase7_api_ui_alignment.py`
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `docs/qa/manual_prompt_regression_bank.md`
- `eMas Front/e2e/support/promptRegressionScenarios.js`
- `eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js`
- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`
- `eMas Front/e2e/specs/full-stack-sse-hard.spec.js`
- `eMas Front/e2e/specs/chat-stream-errors.spec.js`
- `eMas Front/e2e/specs/chat-cancel-navigation.spec.js`
- `eMas Front/e2e/specs/release-validation.spec.js`
- `eMas Front/e2e/specs/normal-use-hardening.spec.js`

Decisions:

- Added `executable_enforcement` metadata to each current SO oracle so the contract file itself points at the enforcing pytest and browser files.
- Added one common snapshot/final-response contract matrix that loads every current SO id: SO-001, SO-002, SO-003, SO-004, SO-005, SO-006, SO-007, SO-008, SO-009, SO-010, SO-011, SO-012, SO-013, SO-014, SO-015, SO-016, SO-017, SO-018, SO-019, SO-020, SO-021, SO-025, SO-027, SO-029, SO-030, SO-035, and SO-041.
- Added LangGraph state-machine enforcement for SO-002, SO-003, SO-004, and SO-035 using the same original-state cascade mechanics as SO-041.
- Added API/UI projection enforcement for SO-012 approval-id timeline projection and SO-013 terminal-snapshot gating.
- Added route/parser enforcement for SO-021 and SO-025, and promoted the SO-025 route-confusion prompt into the manual prompt regression bank.
- Extended seeded and real browser tests to include explicit SO ids and visible DOM forbidden-text assertions where the browser can fail differently from backend evidence.
- Replaced SO-005's broad browser pointer with a dedicated seeded browser proof that drives the exact cascade flow, approves approval 1, rejects approval 2, checks visible rejection/stopped copy, proves original medium rows changed to high, proves original high rows did not change to low, and rejects approval-2 audit rows.
- Aligned the SO-005 oracle contract to the exact browser flow: medium -> high, then original high -> low, with approval 2 rejected before the second write can commit.

Commands run:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_stateful_oracle_schema.py tests/test_snapshot_timeline_final_response_contract.py tests/test_langgraph_state_machine_oracles.py tests/test_phase7_api_ui_alignment.py tests/test_phase19_prompt_workflow_regression.py -q
python -m pytest tests/test_stateful_oracle_schema.py tests/test_phase18_manual_prompt_bank.py tests/test_phase19_prompt_workflow_regression.py::test_phase19_scenarios_122_123_regression_bank_schema_and_triage_rule -q
python -m pytest tests/test_langgraph_state_machine_oracles.py::test_so005_second_approval_rejection_stops_without_hidden_commit tests/test_snapshot_timeline_final_response_contract.py::test_rejected_second_approval_does_not_produce_success_wording_or_hidden_commit tests/test_snapshot_timeline_final_response_contract.py::test_all_stateful_oracle_files_have_executable_snapshot_final_response_contract -q

Set-Location "..\eMas Front"
node --check "e2e/support/promptRegressionScenarios.js"
node --check "e2e/specs/full-stack-prompt-workflow-regression.spec.js"
node --check "e2e/specs/full-stack-data-integrity.spec.js"
node --check "e2e/specs/real-langgraph-critical.spec.js"
node --check "e2e/specs/chat-stream-errors.spec.js"
node --check "e2e/specs/chat-cancel-navigation.spec.js"
node --check "e2e/specs/full-stack-sse-hard.spec.js"
node --check "e2e/specs/release-validation.spec.js"
node --check "e2e/specs/normal-use-hardening.spec.js"
npx playwright test e2e/specs/full-stack-prompt-workflow-regression.spec.js e2e/specs/full-stack-data-integrity.spec.js --project=chromium-seeded --grep "SO-025|SO-030|SO-041"
npx playwright test e2e/specs/full-stack-data-integrity.spec.js --project=chromium-seeded --grep "SO-005"

Set-Location ".."
git diff --check
```

Results:

```text
Backend Phase 12 oracle cluster: 90 passed, 17 existing warnings.
Manual prompt bank/schema focused gate: 9 passed, 1 existing warning.
SO-005 backend graph/snapshot focused gate: 29 passed, 1 existing warning.
Frontend syntax checks: passed.
Seeded browser focused SO-025/SO-030/SO-041 slice: 3 passed.
Seeded browser focused SO-005 rejection slice: 1 passed.
git diff --check: passed; line-ending warnings only.
```

Intermediate findings:

- The first backend matrix run failed for SO-008 and SO-027 because superseded approvals were incorrectly treated like rejected approvals in the generic final-response gate. The contract now requires `approval_invalidated` evidence for superseded approvals and `approval_expired` evidence for expired approvals.
- The first seeded browser run passed SO-025 but exposed that SO-030's exact recovery sentence is hidden in details, so the visible DOM assertion was narrowed to visible terminal state plus forbidden stale text while the snapshot/timeline assertion still checks the recovery evidence.
- The first SO-041 seeded visible-DOM assertion read the DOM before the final bubble settled. The browser proof now waits for the aggregate final summary before asserting forbidden stale approval/waiting text.
- The first SO-005 seeded browser run exposed that the rejected/IDLE browser snapshot keeps the approval decision chain but does not project approval 1 as a `tool_result` row after approval 2 is rejected. The SO-005 browser proof therefore uses DB priority state and data-integrity audit rows as commit evidence, while timeline assertions prove approval 1 accepted, approval 2 requested, and approval 2 rejected in order.
- Running the manual prompt bank gate exposed that the existing Phase 11 cascade bank entry was missing parser-compatibility fields. Added `machine_ids: []`, `job_ids: []`, and `clarification_expected: false` to that entry and the new SO-005 rejection variant.

Remaining gaps: none for current SO oracle enforcement metadata. Full seeded/release/real-LangGraph suites remain broader release gates, but the focused Phase 12 enforcement checks above are green.

## Phase 13 Checklist: Test Quality Gate and Redundancy Control

- [x] Add Phase 13 to the plan and tracker before adding more scenario volume.
- [x] Define canonical, supporting, smoke, and duplicate-candidate coverage categories.
- [x] Document when redundancy is useful: backend state proof, browser visible-DOM proof, and real LangGraph planner/routing proof are different risks.
- [x] Document when redundancy is wasteful: same layer, same fixture, same assertions, and no new failure mode.
- [x] Add future scenario authoring rules to the manual prompt regression bank.
- [x] Build the current SO coverage map with one primary risk and canonical enforcement command per high-risk group.
- [x] Mark duplicate candidates in existing Playwright specs without deleting them yet.
- [x] Propose a lean PR/release/nightly command split from the coverage map.
- [x] Decide not to add schema checks yet; keep Phase 13 as a documentation gate until the next scenario batch proves which metadata should become mandatory.
- [x] Commit this documentation pass before the next scenario implementation batch.

## Phase 13 Implementation: Test Quality Gate and Redundancy Control

Status: Done.

Purpose: reduce future false confidence and test bloat. Phase 12 made the SO files enforceable; Phase 13 makes future additions disciplined so agents do not add five tests that all prove the same seeded happy path.

Coverage classification rule:

| Category | Meaning | Keep? |
|---|---|---|
| `canonical` | The main proof for a risk at the lowest useful layer. | Yes. Required. |
| `supporting` | Same scenario, different failure mode or layer, such as browser DOM vs. backend snapshot. | Yes, if it names the distinct risk. |
| `smoke` | Broad confidence or release wiring check; useful but not proof of state correctness. | Yes, but do not count as oracle closure. |
| `duplicate_candidate` | Same layer, same fixture, same assertions, no new failure mode. | Review before keeping; merge or delete only after a replacement command is documented. |

Useful redundancy examples:

- Backend graph/state oracle proves approval ids, DB rows, audit rows, and final state.
- Snapshot/final-response contract proves projection and wording cannot lie about state.
- Seeded browser proves visible UI, table/card/details rendering, and stale text behavior deterministically.
- Real LangGraph proves the real planner/router/tool path does not diverge from seeded adapters.

Wasteful redundancy examples:

- Two seeded browser tests drive the same prompt variant and assert only `Run complete`.
- A route parser test and a seeded browser test both assert only that a string contains `M-CNC-01`.
- A release smoke repeats the seeded stateful oracle but does not add auth/proxy/polling evidence.

Current decisions:

- Do not delete existing tests during this documentation pass.
- Do not weaken Phase 12 executable enforcement.
- Add more scenarios only after the author can state the distinct product bug and lowest useful layer.
- Real LangGraph coverage should be reserved for planner, route, graph, and live integration risks. It should not duplicate every seeded browser case.
- Keep the current overlapping SO tests for now, because the recent SO-041 bug proved backend-correct evidence can still render incorrectly in the browser.

Current SO coverage map:

| Risk group | SO ids | Canonical proof | Supporting proof to keep | Redundancy decision |
|---|---|---|---|---|
| Original-state multi-approval cascades | SO-001, SO-002, SO-003, SO-004, SO-041 | `test_snapshot_timeline_final_response_contract.py` plus `test_langgraph_state_machine_oracles.py` for original-state mechanics. | Seeded browser for deterministic UI/data proof; real LangGraph for SO-001/SO-035 and SO-041 live planner/DOM proof. | Keep cross-layer overlap. Review older broad seeded cascade cases only if they assert the same prompt, same rows, and no distinct visible-DOM/stale-text risk. |
| Approval rejection, timeout, stale approval, replay, refresh | SO-005, SO-006, SO-007, SO-008, SO-018, SO-027 | Backend snapshot/final-response contract plus focused graph/API tests where present. | Dedicated SO-005 seeded rejection browser proof; shared seeded stale/expired/replay browser specs. | Keep SO-005 dedicated browser proof. Shared browser scenarios are acceptable only while they assert distinct visible states: rejection, expiry/conflict, stale invalidation, replay idempotency, or refresh restore. |
| Commit truthfulness and audit integrity | SO-009, SO-010 | Backend contract must fail on false full success or missing audit evidence. | Seeded data-integrity browser checks for visible partial failure, audit rows, and final text. | Keep; this is not redundant because final copy, audit evidence, and DB state can disagree independently. |
| Premature final response and projection ordering | SO-011, SO-012, SO-013, SO-019, SO-020 | Backend snapshot/final-response and API/UI projection contracts. | Frontend component tests and targeted browser DOM assertions for stale final text, missing approval timeline, terminal gating, restore, and empty final response. | Keep frontend tests when they prove React turn assembly or activity timeline behavior that backend tests cannot see. |
| SSE, reconnect, polling, disconnect, and stream recovery | SO-014, SO-015, SO-016, SO-017, SO-029, SO-030 | Backend contract plus SSE/runtime tests where available. | Browser transport specs for duplicate/out-of-order events, malformed payload recovery, modal close disconnect, static bearer polling, Go API 500, and stream-drop polling. | Keep transport-level overlap if each test names a distinct transport failure. Merge only tests that assert only generic completion after a stream change. |
| LOTO/RAG routing and entity extraction | SO-021, SO-025 | Parser/route pytest plus backend prompt workflow regression. | One seeded browser proof for visible answer/source metadata; route-confusion browser proof for status-vs-LOTO. | Do not make every wording variant a browser test. Wording variants belong in parser/route matrices unless UI/source rendering can break differently. |
| Seeded adapter divergence | SO-035 | LangGraph state-machine oracle and real LangGraph browser critical suite. | Seeded browser remains useful for deterministic data/UI proof, but does not close real planner risk. | Keep targeted real LangGraph proofs only for planner/routing/multi-approval risks. Do not mirror the full seeded suite in real LangGraph. |

Duplicate-candidate review:

| Candidate area | Current judgment | Next action |
|---|---|---|
| Cascade matrix browser tests vs. data-integrity cascade tests | Potentially repetitive when both assert only the same final DB rows. Useful when one asserts prompt wording/visible stale text and the other asserts DB/audit/approval evidence. | Keep for now. When adding a new cascade, pick one canonical seeded browser test and add parser/graph variants before another browser variant. |
| LOTO wording matrix browser coverage | Browser tests become redundant if every wording variant renders the same source answer. | Keep one canonical browser for `M-CNC-01` and one route-confusion browser case. Add most future wording variants to parser/route only. |
| SO-030 stream-drop coverage in data-integrity and chat-stream-errors specs | Useful if one proves polling terminal snapshot and the other proves notification/stream error handling. | Keep if both distinct assertions remain. Merge if either becomes only a `Run complete` check. |
| SO-019 normal-use restore scenarios | Useful if one checks restoring completed state and the other checks no stale previous turn bleed. | Keep only if both risks are explicit in titles/assertions. |
| Release smoke tests overlapping seeded stateful tests | Useful only for auth/proxy/polling wiring, not state correctness. | Classify as `smoke`; do not count as oracle closure. |

Lean command split:

| Lane | Purpose | Commands |
|---|---|---|
| Fast PR | Catch schema, backend oracle, and frontend projection regressions quickly. | `python -m pytest tests/test_stateful_oracle_schema.py tests/test_snapshot_timeline_final_response_contract.py tests/test_langgraph_state_machine_oracles.py -q`; `npm test`; mocked Chromium smoke if configured. |
| Deterministic release/pre-merge | Prove seeded browser UI/data/SSE behavior without real LLM. | `npm run test:e2e:seeded-oracles`; focused `chromium-seeded --grep "SO-..."` for changed scenarios. |
| Opt-in/nightly | Catch real planner/routing/live integration drift. | `npm run test:e2e:real-langgraph -- --grep "@critical"` plus selected production synthetic read-only checks. |
| Manual-failure closure | Prove a manual miss became an executable regression. | Focused pytest/browser command named in the bank entry plus the fast PR lane. |

Commands run:

```powershell
git status --short --branch
rg -n "Phase|phase|Next action|redund|dedup|quality|SO-005|SO-041" docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md docs/qa/manual_prompt_regression_bank.md
Get-Content -Path "docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md" -TotalCount 220
Get-Content -Path "docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md" -TotalCount 260
Get-Content -Path "docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md" -Tail 180
Get-Content -Path "docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md" -Tail 260
Get-Content -Path "docs/qa/manual_prompt_regression_bank.md" -Tail 140
Get-ChildItem -Path "tests/e2e/scenarios/stateful_oracles" -Filter "so-*.json" | Sort-Object Name | ForEach-Object { $json = Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json; [PSCustomObject]@{ File=$_.Name; Id=$json.id; Title=$json.title; Risk=$json.risk; RequiredLayers=($json.required_layers -join ', '); Enforcement=($json.executable_enforcement.PSObject.Properties.Name -join ', ') } } | Format-Table -AutoSize
Get-ChildItem -Path "tests/e2e/scenarios/stateful_oracles" -Filter "so-*.json" | Sort-Object Name | ForEach-Object { $json = Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json; $enf = $json.executable_enforcement; [PSCustomObject]@{ Id=$json.id; Title=$json.title; Pytest=if($enf.pytest){($enf.pytest -join '; ')}else{''}; Playwright=if($enf.playwright){($enf.playwright -join '; ')}else{''}; VisibleDOM=$enf.visible_dom_assertions_required; Manual=if($enf.manual_prompt_regression){($enf.manual_prompt_regression -join '; ')}else{''} } } | ConvertTo-Csv -NoTypeInformation
git diff --check
Set-Location "factory-agent"
python -m pytest tests/test_stateful_oracle_schema.py tests/test_phase18_manual_prompt_bank.py tests/test_snapshot_timeline_final_response_contract.py::test_all_stateful_oracle_files_have_executable_snapshot_final_response_contract -q
Set-Location "..\eMas Front"
node --check "e2e/specs/full-stack-data-integrity.spec.js"
node --check "e2e/specs/full-stack-prompt-workflow-regression.spec.js"
```

Test results:

```text
Documentation-only update. Focused backend/schema/manual-bank/oracle gate passed: `35 passed, 1 warning`. Frontend syntax checks passed for `full-stack-data-integrity.spec.js` and `full-stack-prompt-workflow-regression.spec.js`. `git diff --check` passed with line-ending warnings only.
```

Files changed in this phase so far:

- `docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`

Current blockers:

- None.

Open questions:

- Should the next scenario batch make `coverage_category` and `primary_risk` mandatory in every SO oracle JSON, or is the tracker-level map enough?
- Which existing Playwright tests should be downgraded to `smoke` after one full release cycle without related failures?

Next action:

Start the next scenario implementation batch using the Phase 13 quality gate: add a new scenario only when it names a distinct product bug, lowest useful layer, required evidence, and forbidden stale evidence.

## Phase 13 Next Chatbot Oracle Risk Group

Scenarios changed:

- `SO-018`: added canonical seeded browser proof for refresh during active approval. It now checks same pending approval id, one approval card, restored staged bundle, no DB/audit mutation before approval, and exactly one commit/audit set after approval.
- `SO-030`: strengthened seeded stream-drop recovery from read-only/polling proof to mutating commit proof. It now checks seeded notification drop, no final UI before terminal snapshot, DB/audit rows after approval, and timeline/snapshot/final/UI agreement.
- `SO-029`: promoted approved Go API 500 from plan-start mock coverage to canonical seeded full-stack commit-failure coverage. It now requires failed session/snapshot, unchanged rows, no data-integrity audit rows, failed timeline evidence, and visible retry guidance.
- `SO-020`: strengthened empty-final coverage at frontend unit/component plus mocked browser. Empty terminal content now renders an explicit empty-response diagnostic and does not reuse prior answer text or generic `Execution completed.`.
- `SO-021` / `SO-025`: recorded the Phase 13 decision not to add real LangGraph or extra browser wording variants in this batch. Parser/route plus seeded browser remain canonical until seeded coverage hides a real planner/RAG miss.

Bugs found and fixed:

- `SO-029` exposed a real product bug: after an approved Go API 500, the persisted/snapshot plan message could be overwritten with stale success-shaped recap text. Fixed by skipping completed bundle narration for failed tool outputs and by guarding failed-session snapshot plan content against stale success messages.
- `SO-029` also exposed a UI assembly gap: failed sessions preferred a terse terminal error over the safe plan diagnostic. Fixed by making failed turn summaries prefer safe plan explanation/tool failure detail and by adding component/browser assertions for database-unavailable retry guidance.
- `SO-020` exposed that empty completed assistant content used the fake generic `Execution completed.` fallback. Fixed with an explicit empty-result diagnostic in turn assembly and fixture/browser coverage.
- The full seeded sweep exposed three test-stability gaps outside the new scenario group: streamed final text was asserted before completion in scenario 89 and prompt workflow matrix checks, and SO-014 asserted hidden detail text as visible. Stabilized those tests without changing product behavior.

Commands run:

```powershell
git status --short --branch

Set-Location "factory-agent"
python -m pytest tests/test_phase7_api_ui_alignment.py::test_phase7_failed_session_plan_event_uses_failure_guidance_not_stale_success -q
python -m pytest tests/test_stateful_oracle_schema.py tests/test_snapshot_timeline_final_response_contract.py::test_all_stateful_oracle_files_have_executable_snapshot_final_response_contract -q
python -m pytest tests/test_stateful_oracle_schema.py tests/test_phase18_manual_prompt_bank.py tests/test_snapshot_timeline_final_response_contract.py tests/test_phase7_api_ui_alignment.py tests/test_phase19_prompt_workflow_regression.py -q

Set-Location "..\eMas Front"
node --test --test-concurrency=1 "src/components/features/chat/turns/turnAssembler.test.mjs"
node --test --test-concurrency=1 "src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs"
node --check "src/components/features/chat/turns/turnAssembler.js"
node --check "e2e/specs/chat-fixtures.spec.js"
node --check "e2e/specs/full-stack-data-integrity.spec.js"
node --check "e2e/specs/full-stack-prompt-workflow-regression.spec.js"
node --check "e2e/specs/full-stack-sse-hard.spec.js"
npm test
npx playwright test e2e/specs/chat-fixtures.spec.js --grep "empty assistant"
npx playwright test e2e/specs/full-stack-data-integrity.spec.js --project=chromium-seeded --grep "SO-018|SO-029|SO-030"
npx playwright test e2e/specs/chat-stream-errors.spec.js --grep "SO-030"
npx playwright test e2e/specs/full-stack-data-integrity.spec.js --project=chromium-seeded --grep "SO-006/SO-008/SO-027"
npx playwright test e2e/specs/full-stack-prompt-workflow-regression.spec.js --project=chromium-seeded --grep "SO-002|SO-001|SO-041"
npx playwright test e2e/specs/full-stack-sse-hard.spec.js --project=chromium-seeded --grep "scenario 47"
npm run test:e2e:seeded-oracles
```

Results:

```text
Backend focused SO-029 snapshot regression: 1 passed.
Oracle schema plus all snapshot/final-response contracts: 30 passed.
Backend requested gate: 77 passed, warnings only.
Frontend turn assembler focused tests: 12 passed.
Frontend FactoryAgentChatPanel component tests: 9 passed.
Frontend npm test: 63 passed.
SO-020 mocked browser fixture: 1 passed.
SO-018/SO-029/SO-030 seeded data-integrity grep: 4 passed.
SO-030 stream-error supporting browser: 1 passed.
Stabilized focused reruns for scenario 89, prompt workflow SO-001/SO-002/SO-041, and SO-014 scenario 47: all passed.
Seeded oracle suite: 20 passed.
```

Remaining gaps:

- No real LangGraph run was added for `SO-021` / `SO-025`; keep that as an opt-in addition only if seeded parser/route/RAG coverage hides real planner or source behavior.
- `SO-030` now proves notification stream drop plus polling recovery with a mutating seeded commit, but it does not kill and restart the Factory Agent process. Add a process-restart proof only if release evidence shows polling can diverge from persisted terminal snapshot after actual restart.

Next action:

Continue with the next Phase 13-ranked group only if it proves a distinct product bug: likely large structured results/long heartbeat operations/cross-session leakage before adding any more LOTO wording volume.

## Commands Run

Latest Phase 11 implementation and verification:

```powershell
git status --short --branch

Set-Location "factory-agent"
python -m pytest tests/test_summary_bundle.py::test_phase11_completed_job_recap_aggregates_all_priority_write_sets -q
python -m pytest tests/test_langgraph_state_machine_oracles.py::test_so041_medium_to_high_then_original_high_to_low -q
python -m pytest tests/test_stateful_oracle_schema.py -q
python -m pytest tests/test_snapshot_timeline_final_response_contract.py::test_so041_final_response_must_summarize_all_committed_write_sets -q
python -m pytest tests/test_phase19_prompt_workflow_regression.py::test_phase19_scenarios_122_123_regression_bank_schema_and_triage_rule -q
python -m pytest tests/test_summary_bundle.py tests/test_langgraph_state_machine_oracles.py tests/test_snapshot_timeline_final_response_contract.py tests/test_stateful_oracle_schema.py tests/test_phase19_prompt_workflow_regression.py -q

Set-Location "..\eMas Front"
node --check "e2e/support/promptRegressionScenarios.js"; node --check "e2e/specs/real-langgraph-critical.spec.js"
node --test --test-concurrency=1 "src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs"
npm test
New-Item -ItemType Directory -Force -Path 'test-results\real-langgraph-stack' | Out-Null
npx playwright test --project=chromium-real-langgraph --grep "SO-041"
npx playwright test e2e/specs/full-stack-prompt-workflow-regression.spec.js --project=chromium-seeded --grep "medium-to-high then original-high-to-low"

# Phase 11 live UI regression follow-up after screenshot miss:
Set-Location "eMas Front"
node --test --test-concurrency=1 "src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs" "src/components/features/chat/factory-agent/activityTimeline.test.mjs" "src/components/features/chat/factory-agent/ActivityTimeline.component.test.mjs" "src/components/features/chat/turns/turnAssembler.test.mjs"
npm test
npm run test:e2e:real-langgraph -- --grep "SO-041"

Set-Location "..\factory-agent"
python -m pytest tests/test_phase7_api_ui_alignment.py -q
python -m pytest tests/test_phase7_api_ui_alignment.py tests/test_langgraph_state_machine_oracles.py tests/test_snapshot_timeline_final_response_contract.py tests/test_summary_bundle.py -q

Set-Location "..\eMas Front"
npm run test:backend-oracles
npm run test:e2e:real-langgraph -- --grep "SO-041"
```

## Test Results

Phase 11 verification passed:

```text
summary Phase 11 targeted test: passed.
SO-041 LangGraph state-machine oracle: passed.
stateful oracle schema: 3 passed.
SO-041 snapshot/final-response contract: passed.
manual prompt regression bank schema: passed.
combined backend Phase 11 cluster: 49 passed, 9 warnings in 1.44s.
frontend node syntax checks: passed.
FactoryAgentChatPanel focused component regression: 6 passed.
eMas Front npm test: 54 passed.
real LangGraph browser SO-041: 1 passed.
seeded browser cascade scenario: 1 passed.
Phase 11 live UI follow-up:
  - New visible-DOM regressions initially failed on manual collapse and approval_decided outranking terminal final response.
  - Real LangGraph SO-041 initially failed on the screenshot defect: `Improving the response / Current` was visible while approval 2 was pending.
  - Backend activity projection was fixed so `WAITING_APPROVAL` trims rows after the latest pending approval.
  - Focused frontend component/unit cluster: 44 passed.
  - eMas Front npm test: 59 passed.
  - factory-agent phase7 activity/snapshot contract: 11 passed, existing warnings only.
  - backend focused Phase 11 cluster: 39 passed, existing warnings only.
  - npm run test:backend-oracles: 23 passed, existing warning only.
  - real LangGraph browser SO-041 after fix: 1 passed.
  - seeded prompt workflow SO-041/SO-119 browser rerun: 1 passed.
```

Intermediate note: a real LangGraph SO-041 rerun briefly failed after adding explicit `source_state_basis` because the first summary group was over-labeled as `original medium`. The formatter was corrected to reserve `original` for later ambiguous write sets; the final real LangGraph rerun passed.
Intermediate note: a parallel real LangGraph/seeded browser run failed before test execution because `test-results\real-langgraph-stack\go-api.log` could not be opened while the web server booted. The log directory was recreated and the real LangGraph SO-041 proof passed on rerun.

## Files Changed

- `docs/qa/STATEFUL_ORACLE_TESTING_PLAN.md`
- `docs/qa/STATEFUL_ORACLE_TESTING_TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `tests/e2e/scenarios/stateful_oracles/so-041_priority_medium_to_high_original_high_to_low.json`
- `factory-agent/factory_agent/analysis/summary_backend.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/graph/nodes/tool_pipeline.py`
- `factory-agent/factory_agent/graph/nodes/validate.py`
- `factory-agent/tests/test_phase7_api_ui_alignment.py`
- `factory-agent/tests/test_summary_bundle.py`
- `factory-agent/tests/test_langgraph_state_machine_oracles.py`
- `factory-agent/tests/test_snapshot_timeline_final_response_contract.py`
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`
- `eMas Front/src/components/features/chat/factory-agent/ActivityTimeline.jsx`
- `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js`
- `eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/ActivityTimeline.component.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs`
- `eMas Front/src/test/reactComponentTestUtils.mjs`
- `eMas Front/e2e/support/promptRegressionScenarios.js`
- `eMas Front/e2e/specs/real-langgraph-critical.spec.js`

## Next Action

Commit the Phase 11 live UI regression fix before proceeding. Recommended next focus after commit: promote additional manual misses into the regression bank using the same pattern, especially routes where final response, activity timeline, visible UI, and DB/audit evidence can disagree.

## Phase 11 Checklist: Aggregate Final-Response Evidence Oracles

- [x] Add the manual miss to the prompt regression bank before changing product behavior.
- [x] Add `SO-041` for `change all medium priority job to high then change all high priority job to low`.
- [x] Reproduce at the lowest useful layer and record DB/audit/approval evidence after each approval.
- [x] Decide root cause: graph skipped approval 1, plan persistence lost approval 1 outputs, snapshot projection hid approval 1, deterministic summary only read last outputs, or frontend turn assembly selected partial copy.
- [x] Add a backend summary contract test that fails if the final response mentions only the last write set.
- [x] Add a state/snapshot oracle that requires both write sets, both approval ids, and unchanged-row evidence.
- [x] Add or extend seeded Playwright coverage for the new cascade wording.
- [x] Add real LangGraph browser proof for `SO-041` after backend contracts are green.
- [x] Update frontend turn/activity tests if UI selection can prefer partial final copy. Added a FactoryAgentChatPanel regression for the case where snapshot `pending_approval` has advanced to approval 2 but the timeline still contains approval 1 decision/waiting copy.
- [x] Add live UI regression coverage for approval 2 activity state: `Improving the response / Current` must not outrank `Waiting for your approval`.
- [x] Add UI regression coverage for active activity timeline manual collapse staying collapsed across refresh.
- [x] Add UI regression coverage for final completed SO-041 bubble not showing stale approval-decision text or approval-2-only table.
- [x] Rerun the focused backend, frontend, seeded, and real LangGraph verification commands.

## Phase 11 Investigation Notes

Manual miss observed:

```text
change all medium priority job to high then change all high priority job to low
```

Observed final response:

```text
Success

Updated 10 job(s).

No jobs were created or deleted.

Affected records show only previous high -> new low rows.
```

Initial local investigation:

- `split_user_intents()` splits the prompt into two job intents.
- `_infer_bulk_job_priority_mutation()` detects `medium -> high` for the first clause and `high -> low` for the second clause.
- `summary_backend.py` deterministic completed recap formats whatever job write `tool_outputs` it receives; it is not expected to call an LLM for this path.
- Root cause confirmed: deterministic graph mechanics can stage and approve both write sets with original-state semantics, but committed job write outputs did not carry enough previous-priority evidence for final summary generation to aggregate both write sets reliably.
- Product fix: staged writes now carry `previous_priority` evidence, committed outputs preserve that evidence, and deterministic completed job recaps group multi-write-set priority changes instead of reporting only a flat final table.
- Follow-up UI root cause confirmed: snapshot `pending_approval` can advance to approval 2 before the matching `approval_required` timeline row is present. The table/card used approval 2 from snapshot state, but the assistant bubble summary/details could still use approval 1's `approval_decided` or waiting text from the turn. Product fix: only the turn that owns the current `pendingApproval.approval_id` receives the pending approval presentation, pending approval copy overrides stale turn summary text, and stale details are hidden while the pending approval is active.
- Follow-up live screenshot root cause confirmed: server `activity_steps` finalized "all but the last row" when the session was `WAITING_APPROVAL`. If a stale `replan_requested` row arrived after approval 2, the latest pending approval row was turned into success and `Improving the response` became `Current`. Product fix: server and frontend activity projection trim rows after the latest pending approval while `WAITING_APPROVAL`, and real LangGraph browser coverage now asserts the visible DOM does not show `Improving the response / Current` during approval 2.
- Final visible bubble root cause confirmed: frontend turn assembly could let a later `approval_decided` event outrank `session_completed`, and completed turns could render stashed approval-table presentation/details. Product fix: terminal completion outranks approval-decision copy, completed write-bundle turns no longer use old approval bundle tables as final presentation, and completed user details filter stale approval-wait/approval-decision text.

Commands run for Phase 11 investigation:

```powershell
Set-Location "factory-agent"
@'
from factory_agent.planning.intent import split_user_intents
from factory_agent.graph.planner_graph_helpers import _infer_bulk_job_priority_mutation
p = "change all medium priority job to high then change all high priority job to low"
for it in split_user_intents(p):
    print(it.description, _infer_bulk_job_priority_mutation(it.description))
'@ | python -
```

Current Phase 11 status:

`Done`. SO-041 now has prompt-bank coverage, oracle JSON, backend summary contract coverage, LangGraph state-machine coverage, snapshot/final-response/activity contract coverage, frontend pending-approval/activity/final-bubble projection coverage, seeded browser coverage, and real LangGraph browser proof with visible-DOM stale-text assertions.
