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
| 2 | Chatbot happy-path E2E tests | Not Started | Depends on Phase 1 setup. |
| 3 | Deterministic mocking for chatbot responses | Not Started | Depends on baseline mock server and happy-path flow. |
| 4 | SSE streaming tests | Not Started | Depends on fixture-driven mock server with real `text/event-stream`. |
| 5 | Failure, timeout, retry, and disconnect scenarios | Not Started | Depends on SSE and fixture framework. |
| 6 | CI integration | Not Started | No root CI config found yet. |
| 7 | Cleanup and replacement of old pipeline | Not Started | Do only after Playwright suite is stable and accepted. |

## Long-Term Scope Strategy

| Stage | Status | Scope | Notes |
|---|---|---|---|
| L0 Browser smoke | Done | App opens, chat opens, composer usable. | Covered by Phase 1 Chromium baseline specs. |
| L1 Deterministic mocked chat | Not Started | REST-backed mocked session/message/plan/execute/snapshot flows. | Primary PR suite for user-visible behavior. |
| L2 Deterministic mocked SSE | Not Started | Real `text/event-stream` from mock server for notification/activity scenarios. | Adds stream lifecycle, chunk order, fallback, and disconnect coverage. |
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
| 5 | User sends "Show status for machine M-CNC-01" and sees final assistant answer. | Not Started | L1 |
| 6 | User asks for low priority jobs and sees a result/table-style answer. | Not Started | L1 |
| 7 | User asks a RAG/LOTO question and sees answer plus source/citation chrome. | Not Started | L1 |
| 8 | Follow-up message after completion creates a second distinct turn. | Not Started | L1 |
| 9 | Plan mode submission preserves mode and produces expected planning/progress copy. | Not Started | L1 |
| 10 | Final assistant text animates to completion before sources/details appear. | Not Started | L1 |
| 11 | Notification SSE `hello` opens, invalidates snapshot, and triggers refresh. | Not Started | L2 |
| 12 | Multiple notification events update in cursor order without duplicate refreshes. | Not Started | L2 |
| 13 | Activity stream emits multiple steps and the activity UI shows them in order. | Not Started | L2 |
| 14 | Final completion arrives through SSE plus snapshot and removes busy UI. | Not Started | L2 |
| 15 | SSE heartbeat frames do not create noisy visible messages. | Not Started | L2 |
| 16 | SSE reconnect uses `Last-Event-ID` and does not duplicate prior activity. | Not Started | L2 |
| 17 | Static bearer token mode disables EventSource and uses polling fallback. | Not Started | L2 |
| 18 | Malformed SSE payload is ignored and the next valid event still updates UI. | Not Started | L2 |
| 19 | SSE connection drops and UI shows snapshot polling fallback diagnostic. | Not Started | L2 |
| 20 | Plan creation returns 503 and UI shows backend unavailable/error state without fake success. | Not Started | L1 |
| 21 | Execute returns 409 once, UI/backend retries, and final response completes. | Not Started | L1 |
| 22 | Snapshot returns session not found and UI recovers to a safe state. | Not Started | L1 |
| 23 | Active session never reaches terminal state before timeout and UI remains honest. | Not Started | L2 |
| 24 | Completed snapshot has empty assistant content and does not show a stale previous answer. | Not Started | L1 |
| 25 | User cancels an active run and final UI returns to idle/cancelled state. | Not Started | L2 |
| 26 | User closes modal or navigates during an active stream and EventSource disconnects. | Not Started | L2 |
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

- [ ] Add happy-path fixture for session creation, user message, plan, execute, active snapshot, and completed snapshot.
- [ ] Test opening the chatbot page/modal.
- [ ] Test typing a user message.
- [ ] Test submitting the message.
- [ ] Assert visible user message.
- [ ] Assert loading/progress state.
- [ ] Assert visible final assistant response content.
- [ ] Assert completed/non-busy UI state.
- [ ] Assert composer is enabled after completion.

### Phase 3: Deterministic Mocking for Chatbot Responses

- [ ] Add named scenario fixture store.
- [ ] Add mock server per-test reset.
- [ ] Add REST request log capture.
- [ ] Add reusable Factory Agent snapshot builders.
- [ ] Add fixture for RAG answer with sources.
- [ ] Add fixture for approval-required response.
- [ ] Add fixture for backend unavailable response.
- [ ] Add fixture for empty completed answer.
- [ ] Document how to add scenarios.

### Phase 4: SSE Streaming Tests

- [ ] Add scripted notification SSE support.
- [ ] Add scripted activity SSE support.
- [ ] Test successful notification stream and final completion.
- [ ] Test multiple activity chunks arriving in order.
- [ ] Test final completion event/state.
- [ ] Test reconnect and `Last-Event-ID` behavior if practical.
- [ ] Assert EventSource connection lifecycle from mock server logs.

### Phase 5: Failure, Timeout, Retry, and Disconnect Scenarios

- [ ] Test backend error event/state.
- [ ] Test network interruption and polling fallback diagnostic.
- [ ] Test timeout or non-terminal session behavior.
- [ ] Test empty response.
- [ ] Test malformed event payload.
- [ ] Test user cancel during active stream.
- [ ] Test modal close or navigation away disconnects EventSource.
- [ ] Test static bearer mode disables EventSource and uses polling fallback.

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

- None for Phase 1.
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

## Next Action

Begin Phase 2 by extending the mock server with a fixture-driven happy path for session creation, user message submission, plan/execute behavior, active snapshot state, and completed assistant response rendering.

Do not remove the existing Go/Python E2E pipeline during Phase 2.
