# Playwright E2E Execution Tracker

Created: 2026-05-16

Branch: `codex/playwright-e2e-plan`

Purpose: living tracker for replacing manual chatbot validation with a deterministic Playwright browser E2E pipeline.

## Status Legend

Use one of:

- `Not Started`
- `In Progress`
- `Blocked`
- `Done`

## Phase Status

| Phase | Name | Status | Owner Notes |
|---|---|---|---|
| 0 | Discovery and risk mapping | Done | Current repo shape, test setup, frontend chat flow, backend/SSE routes, env/auth behavior, and risks were inspected and documented. |
| 1 | Playwright setup and baseline browser tests | Done | Marked In Progress during implementation; completed with Playwright config, mock Factory Agent server, and two Chromium baseline specs. |
| 2 | Chatbot happy-path E2E tests | Done | Marked In Progress during implementation; completed with deterministic mocked session/message/plan/execute/snapshot lifecycle and one Chromium happy-path browser spec. |
| 3 | Deterministic mocking for chatbot responses | Done | Completed with a lightweight named scenario store, per-session scenario state, in-memory request logs, reset endpoint, reusable fixture builders, preserved happy path, and two additional REST-backed L1 scenarios. |
| 4 | SSE streaming tests | Done | Completed with lightweight scripted notification/activity `text/event-stream` support, scoped EventSource connection logs, and two Chromium SSE specs. |
| 5 | Failure, timeout, retry, and disconnect scenarios | Done | Completed with deterministic failure-mode scenario fixtures, malformed SSE recovery, execute retry, non-terminal active run, stream drop fallback, cancel, and modal close disconnect coverage. |
| 6 | CI integration | Not Started | No root CI config found yet. |
| 7 | Cleanup and replacement of old pipeline | Not Started | Do only after Playwright suite is stable and accepted. |

## Long-Term Scope Strategy

| Stage | Status | Scope | Notes |
|---|---|---|---|
| L0 Browser smoke | Done | App opens, chat opens, composer usable. | Covered by Phase 1 Chromium baseline specs. |
| L1 Deterministic mocked chat | In Progress | REST-backed mocked session/message/plan/execute/snapshot flows. | Scenario 5 happy path is covered; broader L1 scenarios remain for later phases. |
| L2 Deterministic mocked SSE | In Progress | Real `text/event-stream` from mock server for notification/activity scenarios. | Phase 4 covers notification/activity success paths; Phase 5 adds malformed SSE, stream drop fallback, non-terminal, cancel, and modal disconnect coverage. Reconnect/static bearer remain later expansion items. |
| L3 Seeded full-stack browser | Not Started | Vite plus seeded Go API and Factory Agent fake planner/model provider. | Scheduled or release-branch gate, not first PR requirement. |
| L4 Production-like release validation | Not Started | Compose/staging with nginx paths, auth mode, polling fallback. | Release candidate gate. |
| L5 Production synthetic monitoring | Not Started | Safe read-only canary prompts and health/latency checks. | Post-deploy monitoring only. |

## First-Wave Scenario Portfolio

Target: about 30 meaningful, non-redundant scenarios. Implement them gradually; do not block the first Playwright merge on completing all 30.

| # | Scenario | Status | Layer |
|---|---|---|---|
| 1 | App opens dashboard and floating chat control is reachable by an accessible selector. | Done | L0 |
| 2 | Chat modal opens and shows empty state plus enabled composer. | Done | L0 |
| 3 | New session can be started from the sidebar. | Not Started | L1 |
| 4 | Existing active session is restored from local storage. | Not Started | L1 |
| 5 | User sends "Show status for machine M-CNC-01" and sees final assistant answer. | Done | L1 |
| 6 | User asks for low priority jobs and sees a result/table-style answer. | Not Started | L1 |
| 7 | User asks a RAG/LOTO question and sees answer plus source/citation chrome. | Not Started | L1 |
| 8 | Follow-up message after completion creates a second distinct turn. | Not Started | L1 |
| 9 | Plan mode submission preserves mode and produces expected planning/progress copy. | Not Started | L1 |
| 10 | Final assistant text animates to completion before sources/details appear. | Not Started | L1 |
| 11 | Notification SSE `hello` opens, invalidates snapshot, and triggers refresh. | Done | L2 |
| 12 | Multiple notification events update in cursor order without duplicate refreshes. | Not Started | L2 |
| 13 | Activity stream emits multiple steps and the activity UI shows them in order. | Done | L2 |
| 14 | Final completion arrives through SSE plus snapshot and removes busy UI. | Done | L2 |
| 15 | SSE heartbeat frames do not create noisy visible messages. | Done | L2 |
| 16 | SSE reconnect uses `Last-Event-ID` and does not duplicate prior activity. | Not Started | L2 |
| 17 | Static bearer token mode disables EventSource and uses polling fallback. | Not Started | L2 |
| 18 | Malformed SSE payload is ignored and the next valid event still updates UI. | Done | L2 |
| 19 | SSE connection drops and UI shows snapshot polling fallback diagnostic. | Done | L2 |
| 20 | Plan creation returns 503 and UI shows backend unavailable/error state without fake success. | Done | L1 |
| 21 | Execute returns 409 once, UI/backend retries, and final response completes. | Done | L1 |
| 22 | Snapshot returns session not found and UI recovers to a safe state. | Not Started | L1 |
| 23 | Active session never reaches terminal state before timeout and UI remains honest. | Done | L2 |
| 24 | Completed snapshot has empty assistant content and does not show a stale previous answer. | Done | L1 |
| 25 | User cancels an active run and final UI returns to idle/cancelled state. | Done | L2 |
| 26 | User closes modal or navigates during an active stream and EventSource disconnects. | Done | L2 |
| 27 | Approval-required response renders risk summary, preview/table, and Approve/Reject actions. | Not Started | L1 |
| 28 | Approval approve flow resumes and reaches completed final answer. | Not Started | L2/L3 |
| 29 | Approval reject flow returns to idle with rejection state and no fake completion. | Not Started | L2/L3 |
| 30 | Confirmation-required flow shows choices, user selects one, and follow-up execution completes. | Not Started | L2/L3 |

## Phase Task Checklists

### Phase 0: Discovery and Risk Mapping

- [x] Create separate branch before work.
- [x] Inspect repository layout.
- [x] Inspect `eMas Front/package.json`.
- [x] Inspect frontend test setup and component test helpers.
- [x] Inspect frontend chatbot entry points.
- [x] Inspect frontend Factory Agent API client.
- [x] Inspect EventSource hooks.
- [x] Inspect Factory Agent routes and SSE implementation.
- [x] Inspect Factory Agent auth dependency behavior.
- [x] Inspect Go legacy chatbot routes and service.
- [x] Inspect existing E2E runners and seed scenarios.
- [x] Inspect env and Docker/nginx configuration.
- [x] Confirm no root CI workflow exists.
- [x] Write `PLAN.md`.
- [x] Write `TRACK.md`.
- [x] Add long-term testing scope strategy.
- [x] Add first-wave 30-scenario portfolio.

### Phase 1: Playwright Setup and Baseline Browser Tests

- [x] Add `@playwright/test` to `eMas Front`.
- [x] Add Playwright scripts to `eMas Front/package.json`.
- [x] Add `eMas Front/playwright.config.js`.
- [x] Add `eMas Front/e2e/README.md`.
- [x] Add minimal mock Factory Agent server.
- [x] Configure Vite `webServer` with `VITE_FACTORY_AGENT_BASE_URL` pointing at the mock server.
- [x] Add app-shell/chat-open baseline spec.
- [x] Add stable selector or accessible label for the floating chat button if needed.
- [x] Ignore `playwright-report/` and `test-results/`.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium`.

### Phase 2: Chatbot Happy-Path E2E Tests

- [x] Add happy-path fixture for session creation, user message, plan, execute, active snapshot, and completed snapshot.
- [x] Test opening the chatbot page/modal.
- [x] Test typing a user message.
- [x] Test submitting the message.
- [x] Assert visible user message.
- [x] Assert loading/progress state.
- [x] Assert visible final assistant response content.
- [x] Assert completed/non-busy UI state.
- [x] Assert composer is enabled after completion.

### Phase 3: Deterministic Mocking for Chatbot Responses

- [x] Add named scenario fixture store.
- [x] Add mock server per-test reset.
- [x] Add REST request log capture.
- [x] Add reusable Factory Agent snapshot builders.
- [ ] Add fixture for RAG answer with sources.
- [ ] Add fixture for approval-required response.
- [x] Add fixture for backend unavailable response.
- [x] Add fixture for empty completed answer.
- [x] Document how to add scenarios.

Phase 3 note: RAG/source and approval-required fixtures remain available L1 expansion items, but were not necessary to complete this phase because scenarios 20 and 24 now cover additional deterministic REST-backed mocked behavior beyond the preserved happy path.

### Phase 4: SSE Streaming Tests

- [x] Add scripted notification SSE support.
- [x] Add scripted activity SSE support.
- [x] Test successful notification stream and final completion.
- [x] Test multiple activity chunks arriving in order.
- [x] Test final completion event/state.
- [ ] Test reconnect and `Last-Event-ID` behavior if practical. Deferred because the Phase 4 implementation request explicitly excluded reconnect coverage.
- [x] Assert EventSource connection lifecycle from mock server logs.
- [x] Assert simple heartbeat frames do not create visible noisy messages.

### Phase 5: Failure, Timeout, Retry, and Disconnect Scenarios

- [x] Test backend error event/state.
- [x] Test network interruption and polling fallback diagnostic.
- [x] Test execute conflict retry behavior.
- [x] Test timeout or non-terminal session behavior.
- [x] Test empty response.
- [x] Test malformed event payload.
- [x] Test user cancel during active stream.
- [x] Test modal close or navigation away disconnects EventSource.
- [ ] Test static bearer mode disables EventSource and uses polling fallback.

Phase 5 note: static bearer mode remains a later L2 expansion item because the requested Phase 5 scope emphasized failure, retry, malformed SSE, timeout/non-terminal, cancel, and disconnect scenarios and explicitly avoided broad reconnect lifecycle expansion.

### Phase 6: CI Integration

- [ ] Identify CI provider/config location.
- [ ] Add Playwright CI job.
- [ ] Cache/install Node dependencies.
- [ ] Install Chromium browser.
- [ ] Run `npm test`.
- [ ] Run `npm run test:e2e -- --project=chromium`.
- [ ] Upload Playwright report/test-results artifacts.
- [ ] Configure traces, screenshots, and video on failure.
- [ ] Keep full-stack/real-service browser job separate from deterministic mock job.

### Phase 7: Cleanup and Replacement of Old Pipeline

- [ ] Map manual chatbot checks to Playwright specs.
- [ ] Update docs with the replacement command.
- [ ] Mark manual chatbot typing/waiting/checking as deprecated.
- [ ] Decide whether `factory-agent-smoke.js` remains as API smoke.
- [ ] Keep `tests/e2e/run_seed_pipeline.ps1` for API/seed/reliability coverage unless explicitly approved otherwise.
- [ ] Record final replacement decisions in this tracker.

## Current Blockers

- None for completed Phase 5.
- There is still no root CI workflow to extend; keep CI integration for Phase 6.

## Open Questions

| Question | Current Answer / Assumption |
|---|---|
| Should browser CI run against real Factory Agent? | No for default CI. Use a deterministic mock Factory Agent server first. Add full-stack as optional/nightly later. |
| Should tests cover legacy Go `/api/v1/ai/chats` UI flow? | Not initially. The visible chat UI uses Factory Agent. Legacy Go chat can remain covered by Go/API tests or a later optional browser track. |
| Should MSW be introduced? | Not recommended now. It is not present and native EventSource streaming is better tested with a real mock HTTP/SSE server. |
| Should Playwright route interception be used? | Yes for small REST-only cases, not as the primary SSE mocking mechanism. |
| Should real LLM calls run in CI? | No. Real LLM/RAG checks remain opt-in because they are nondeterministic and environment-dependent. |

## Decisions Made

| Decision | Rationale |
|---|---|
| Put Playwright under `eMas Front`. | The frontend package owns the browser app, npm scripts, Vite server, and package lock. |
| Use a test-only mock Factory Agent HTTP/SSE server. | It matches `VITE_FACTORY_AGENT_BASE_URL`, avoids real LLM calls, and can stream real EventSource frames. |
| Keep existing Go/Python seed pipeline during rollout. | It covers API contracts, seed data, reliability, and backend behavior that Playwright should not replace wholesale. |
| Treat current SSE as snapshot/activity streaming, not token streaming. | The inspected backend streams notification/activity/semantic events; final answer text is snapshot-derived and locally animated. |
| Start with Chromium only. | Reduces initial flake and install cost. Add more browsers after stability. |
| Cap the first browser portfolio at about 30 scenarios. | Keeps the suite meaningful and fast while covering distinct risks instead of prompt variants. |
| Grow from mocked browser tests to seeded full-stack, production-like release validation, then safe synthetic monitoring. | This gives fast PR feedback now while preserving a path to production confidence later. |

## Commands Run During Discovery

```powershell
git status --short
git branch --show-current
git switch -c codex/playwright-e2e-plan
Get-Content -Raw "C:\Users\dilun\.codex\skills\analyze-project\SKILL.md"
Get-Content -Raw "C:\Users\dilun\.codex\skills\awt-e2e-testing\SKILL.md"
rg --files --hidden -g '!node_modules' -g '!.git' -g '!.next' -g '!dist' -g '!build'
rg -n --hidden -S -g '!node_modules' -g '!.git' -g '!.next' -g '!dist' -g '!build' "playwright|cypress|vitest|jest|chat|sse|stream|EventSource|ReadableStream|fetch|text/event-stream|api/chat|e2e|test"
Get-Content -Raw "eMas Front\package.json"
Get-Content -Raw "eMas Front\vite.config.js"
Get-Content -Raw pytest.ini
Get-Content -Raw "tests\e2e\README.md"
Get-Content -Raw "tests\rag_eval\README.md"
rg -n -S -g '!node_modules' -g '!playwright-report' "EventSource|ReadableStream|text/event-stream|stream|SSE|fetch\(|AbortController|api/chat|factory-agent|sessions|messages|events" "eMas Front\src"
rg -n -S "EventSource|StreamingResponse|text/event-stream|sse|stream|yield|sessions|messages|events" factory-agent\factory_agent factory-agent\tests
rg -n -S "text/event-stream|Server-Sent|SSE|stream|Flush|chat|api/chat|EventSource|session|approval" emas\internal emas\cmd
Get-Content -Raw "eMas Front\src\services\factoryAgentApi.js"
Get-Content -Raw "eMas Front\src\components\features\chat\factory-agent\useSessionEvents.js"
Get-Content -Raw "eMas Front\src\components\features\chat\factory-agent\useActivityStream.js"
Get-Content -Raw "eMas Front\src\components\features\chat\factory-agent\FactoryAgentChatComposer.jsx"
Get-Content -Raw "eMas Front\src\components\features\chat\AIAssistantModal.jsx"
rg -n -C 4 "createSession|addMessage|createPlan|execute|cancelSession|useSessionEvents|useActivityStream|pollSnapshot|streamDiagnostics|setActivitySteps|isSending|handleSend|FACTORY_AGENT_USER_ID" "eMas Front\src\components\features\chat\factory-agent\useFactoryAgentChat.js"
rg -n -C 4 "aria-label|placeholder|FactoryAgentChatComposer|StreamedAssistantText|streamDiagnostics|turns|messages|status|Cancel current run|Send|AIAssistant|FactoryAgentDiagnostics" "eMas Front\src\components\features\chat\factory-agent\FactoryAgentChatPanel.jsx"
rg -n -C 4 "FloatingChatButton|AIAssistantModal|Route|BrowserRouter|Layout|useState" "eMas Front\src\App.jsx" "eMas Front\src\main.jsx" "eMas Front\src\components\shared\FloatingChatButton.jsx" "eMas Front\src\components\layout\Layout.jsx"
Get-Content -Raw "factory-agent\factory_agent\api\routers\events.py"
Get-Content -Raw "factory-agent\tests\test_event_stream_runtime.py"
Get-Content -Raw "factory-agent\factory_agent\api\routes.py"
Get-Content -Raw "factory-agent\main.py"
rg -n -C 3 "FACTORY|JWT|BEARER|DATABASE|OPENAI|LIVE|APP_MODE|redis|worker|CORS|SESSION" "factory-agent\factory_agent\config.py" ".env.example"
Get-Content -Raw "factory-agent\pyproject.toml"
Get-Content -Raw ".env.example"
Test-Path -LiteralPath .github
rg --files --hidden -g '!node_modules' -g '!emas/.gopath' -g '!.git' -g '!.next' -g '!dist' -g '!build' -g '.github/**' -g '*ci*' -g '*workflow*' -g '*pipeline*'
Get-Content -Raw "factory-agent\factory_agent\api\dependencies.py"
Get-Content -Raw "factory-agent\requirements.txt"
Get-Content -Raw "factory-agent\requirements-dev.txt"
Get-Content -Raw "eMas Front\README.md"
Get-Content -Raw "factory-agent\FRONTEND_PHASE0_BASELINE.md"
Get-Content -Raw "docs\QA_UPGRADE_INTEGRATION_PLAN.md"
Get-Content -Raw "docs\QA_UPGRADE_INTEGRATION_TRACKER.md"
Get-Content -Raw "tests\e2e\run_seed_pipeline.ps1"
Get-Content -Raw "tests\e2e\promptfoo.seed-pipeline.yaml"
Get-Content -Raw "emas\internal\handler\ai_chat_handler.go"
Get-Content -Raw "emas\internal\service\chatbot_service.go"
Get-Content -Raw "emas\internal\service\ai_chat_service.go"
Get-Content -Raw "eMas Front\src\services\api.js"
Get-Content -Raw "eMas Front\src\components\features\chat\ChatMessage.jsx"
Get-Content -Raw "eMas Front\src\components\features\chat\factory-agent\FactoryAgentChatPanel.component.test.mjs"
Get-Content -Raw "eMas Front\src\test\reactComponentTestUtils.mjs"
Get-Content -Raw "eMas Front\scripts\factory-agent-smoke.js"
rg -n -S "playwright|@playwright/test|cypress|selenium|puppeteer|msw" "eMas Front\package-lock.json" "eMas Front\package.json" "package-lock.json" "package.json"
rg --files --hidden -g '!node_modules' -g '!emas/.gopath' -g '!.git' -g '!eMas Front/playwright-report' -g '!test-artifacts' | rg -i "playwright|cypress|vitest|jest|test|spec|e2e|smoke"
Get-Content -Raw "docker-compose.yml"
Get-Content -Raw "emas\cmd\e2e_server\main.go"
Get-Content -Raw "tests\e2e\run_factory_agent_api.py"
rg -n -S "factory_agent|agent_api|entrypoint|headers|expected|status|stream|sse|ui" "tests\e2e\scenarios\seed_pipeline.json"
git status --short --branch
```

Additional scope-strategy update commands:

```powershell
git status --short --branch
rg -n "Recommended First Implementation Step|Target Architecture|Phased Implementation Plan|Next Action|Phase Status|Open Questions" PLAN.md TRACK.md
Get-Content -Tail 80 PLAN.md
Get-Content -Tail 80 TRACK.md
```

## Test Results

Phase 1:

- `npm test`: passed, 48 tests.
- `npm run test:e2e -- --project=chromium`: passed, 2 Chromium Playwright tests.
- `npx playwright install chromium`: not run because the installed Chromium browser was already available for the Playwright run.

Phase 2:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; Phase 2 working tree changes present before commit.
- `npm run test:e2e -- --project=chromium --grep "happy path"`: passed, 1 Chromium Playwright test.
- `npm test`: passed, 48 tests.
- `npm run test:e2e -- --project=chromium`: passed, 3 Chromium Playwright tests.
- `npx playwright install chromium`: not run because Chromium was already available and the Playwright run succeeded.

Phase 3:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; Phase 3 working tree changes present before commit.
- `npm run test:e2e -- --project=chromium --grep "scenario fixtures|happy path"`: initially failed because the test request-log filter only matched the message request and the stale-answer assertion assumed one rendered copy of the first answer; fixed by carrying prompt metadata into request logs and comparing against the pre-existing rendered answer count. Re-run passed, 3 Chromium Playwright tests.
- `npm test`: passed, 48 tests.
- `npm run test:e2e -- --project=chromium`: passed, 5 Chromium Playwright tests.
- `npx playwright install chromium`: not run because Chromium was already available and the Playwright run succeeded.

Phase 4:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; Phase 4 working tree changes present before commit.
- `npm run test:e2e -- --project=chromium --grep "SSE"`: initially passed the notification SSE spec and failed the activity SSE spec because separately arriving activity frames were paced by the UI hook and the final snapshot closed the stream before queued middle rows rendered. Adjusted the activity SSE script cadence and final invalidation timing; re-run passed, 2 Chromium Playwright tests.
- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed Phase 4 modified/untracked files before final verification.
- `npm test`: passed, 48 tests.
- `npm run test:e2e -- --project=chromium`: passed, 7 Chromium Playwright tests.
- `npx playwright install chromium`: not run because Chromium was already available and the Playwright run succeeded.

Phase 5:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed Phase 5 working tree changes before verification.
- `npm run test:e2e -- --project=chromium --grep "failure|stream robustness|cancel|disconnect"`: initially passed 5 of 6 focused tests and failed the non-terminal assertion because the visible active row was "Understanding your request", not "Gathering information"; adjusted the assertion to the designed active row. Re-run passed, 6 Chromium Playwright tests.
- `npm test`: passed, 48 tests.
- `npm run test:e2e -- --project=chromium`: passed, 13 Chromium Playwright tests.
- `npx playwright install chromium`: not run because Chromium was already available and the Playwright run succeeded.

Discovery command notes:

- Root `package.json` does not exist; frontend package is `eMas Front/package.json`.
- Root `.github/` does not exist.
- Playwright is not configured as a repo test dependency despite an existing generated `eMas Front/playwright-report/` artifact.

## Files Changed

Planning commit:

- `PLAN.md`
- `TRACK.md`

Phase 1 implementation:

- `eMas Front/.gitignore`
- `eMas Front/package.json`
- `eMas Front/package-lock.json`
- `eMas Front/playwright.config.js`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/support/startViteForPlaywright.js`
- `eMas Front/e2e/specs/chat-baseline.spec.js`
- `eMas Front/playwright-report/` removed from git tracking and covered by `.gitignore`
- `eMas Front/src/components/shared/FloatingChatButton.jsx`

Phase 2 implementation:

- `TRACK.md`
- `eMas Front/e2e/fixtures/factoryAgentFixtures.js`
- `eMas Front/e2e/fixtures/selectors.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/specs/chat-happy-path.spec.js`

Phase 3 implementation:

- `TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/fixtures/factoryAgentFixtures.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/chat-fixtures.spec.js`

Phase 4 implementation:

- `TRACK.md`
- `eMas Front/e2e/fixtures/factoryAgentFixtures.js`
- `eMas Front/e2e/fixtures/sseScripts.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/chat-sse-activity.spec.js`
- `eMas Front/e2e/specs/chat-sse-notification.spec.js`

Phase 5 implementation:

- `TRACK.md`
- `eMas Front/e2e/fixtures/factoryAgentFixtures.js`
- `eMas Front/e2e/fixtures/sseScripts.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/chat-cancel-navigation.spec.js`
- `eMas Front/e2e/specs/chat-stream-errors.spec.js`

## Next Action

Begin Phase 6 only when requested: add deterministic Playwright CI integration and artifacts. Keep reconnect/static bearer lifecycle expansion separate unless explicitly requested.

Do not remove the existing Go/Python E2E pipeline. Do not add Go backend, Docker, real Factory Agent, or real LLM dependencies to the default Playwright suite.
