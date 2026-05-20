# Playwright E2E Replacement Plan

Created: 2026-05-16

Branch: `codex/playwright-e2e-plan`

Scope: Playwright-based chatbot E2E replacement through production monitoring and production-grade hardening. Do not delete backend/API seed pipelines; retire routine manual browser chatbot validation only after Phase 12 gates pass, and claim production-grade hardening only after Phase 20 real LangGraph approval-chain coverage passes.

## Current-State Analysis

### Repository Shape

This repo is not a single app package. The relevant parts are:

| Area | Path | Role |
|---|---|---|
| React frontend | `eMas Front/` | Vite/React browser UI. The visible chatbot is the Factory Agent chat modal. |
| Go backend | `emas/` | Gin API, seeded E2E server, legacy `/api/v1/ai/chats` chatbot routes, scheduling and approval APIs. |
| Factory Agent | `factory-agent/` | FastAPI service used by the current frontend chat panel. Owns session, message, plan, execute, snapshot, approval, and SSE routes. |
| Existing E2E contracts | `tests/e2e/` | Seed manifest, PowerShell runner, Promptfoo config, and Python HTTP scenario runner. |
| RAG eval harness | `tests/rag_eval/` | Opt-in live LLM/RAG structural evaluation. |

### Existing E2E / Manual Testing Approach

Current coverage is mostly API and component level:

- `tests/e2e/run_seed_pipeline.ps1` orchestrates Go `internal/e2e` tests, Factory Agent pytest checks, seeded Go API startup, optional real Factory Agent API scenarios, and artifacts under `test-artifacts/`.
- `emas/internal/e2e/*` covers seeded Go API behavior and chatbot approval driver flows.
- `factory-agent/tests/*` covers FastAPI routes, snapshots, approvals, event stream runtime, planner behavior, reliability, RAG, and contracts.
- `eMas Front/package.json` has `npm test`, but it uses Node's built-in test runner plus jsdom/Vite SSR helpers for component and utility tests. It does not drive a real browser.
- `eMas Front/scripts/factory-agent-smoke.js` drives Factory Agent over HTTP, but not through the browser.
- `factory-agent/FRONTEND_PHASE0_BASELINE.md` documents manual/browser observations and screenshots from prior frontend baseline work.
- `eMas Front/playwright-report/` exists as an artifact, but there is no Playwright dependency, config, or test script in `eMas Front/package.json`.

There is no root `package.json`, no root `.github/` CI workflow, and no current automated browser E2E pipeline.

### Existing Test Tools and Scripts

| Tool | Current Use | Notes |
|---|---|---|
| Go `go test` | Go unit, handler, router, and seeded E2E tests | Includes `emas/cmd/e2e_server` for seeded local API startup. |
| Pytest | Factory Agent route, planner, snapshot, SSE, RAG, and reliability tests | Root `pytest.ini` disables pytest cache provider. |
| Node `--test` | Frontend component and utility tests in jsdom | Good for rendering regressions, not browser behavior. |
| Promptfoo | `tests/e2e/promptfoo.seed-pipeline.yaml` | LLM intent smoke harness, opt-in. |
| Manual browser checks | Recorded in `factory-agent/FRONTEND_PHASE0_BASELINE.md` and screenshots | This is the gap to replace. |

### Current Chatbot Flow

The primary user-facing chatbot flow is the React Factory Agent modal:

1. `eMas Front/src/App.jsx` renders `FloatingChatButton`.
2. Clicking it opens `AIAssistantModal`.
3. `AIAssistantModal` renders `FactoryAgentChatPanel`.
4. `FactoryAgentChatPanel` uses `useFactoryAgentChat`.
5. `useFactoryAgentChat` creates or restores a Factory Agent session, sends user messages, creates plans, executes sessions, refreshes snapshots, and receives EventSource updates.
6. `FactoryAgentChatComposer` provides the message mode select, textarea, send button, and cancel button.
7. Final visible assistant responses are assembled from Factory Agent snapshot timeline data by `turnAssembler` and rendered by `ChatMessage` / `StreamedAssistantText`.

Important nuance: the current backend SSE does not stream token-by-token assistant text. The actual SSE streams are notification/activity/semantic streams that invalidate snapshots and send activity steps. The final answer is snapshot-derived, then the frontend animates the visible text locally.

The legacy Go chatbot flow still exists:

- Frontend client wrapper: `eMas Front/src/services/api.js` under `aiApi.chats`.
- Backend routes: `emas/internal/handler/ai_chat_handler.go` under `/api/v1/ai/chats`.
- Phase 0 chatbot service: `emas/internal/service/chatbot_service.go`.

The visible React chat panel currently targets Factory Agent, so Playwright should start there and keep legacy Go chat coverage as a separate optional track.

### Frontend Entry Points

Primary files:

- `eMas Front/src/main.jsx`
- `eMas Front/src/App.jsx`
- `eMas Front/src/components/shared/FloatingChatButton.jsx`
- `eMas Front/src/components/features/chat/AIAssistantModal.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatComposer.jsx`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `eMas Front/src/components/features/chat/factory-agent/useSessionEvents.js`
- `eMas Front/src/components/features/chat/factory-agent/useActivityStream.js`
- `eMas Front/src/services/factoryAgentApi.js`

Current selector risk: the floating chat button has visible text only on hover and no `aria-label`. Phase 1 should add a stable accessible label or `data-testid` before relying on it.

### Backend / API / SSE Entry Points

Factory Agent REST:

- `POST /sessions`
- `GET /sessions`
- `GET /sessions/{session_id}`
- `PATCH /sessions/{session_id}`
- `DELETE /sessions/{session_id}`
- `POST /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/messages`
- `POST /sessions/{session_id}/plans`
- `POST /sessions/{session_id}/execute`
- `GET /sessions/{session_id}/snapshot`
- `GET /sessions/{session_id}/steps`
- `POST /sessions/{session_id}/confirm`
- `POST /sessions/{session_id}/cancel`
- `GET /approvals/pending`
- `POST /approvals/{approval_id}/approve`
- `POST /approvals/{approval_id}/reject`

Factory Agent SSE:

- `GET /sessions/{session_id}/events`
  - Notification-only stream.
  - Emits `notification` frames such as `hello`, `snapshot_invalidated`, `phase_changed`, and `heartbeat`.
- `GET /sessions/{session_id}/events/activity`
  - User-facing activity stream.
  - Emits `control` frames such as `STREAM_READY`, `SESSION_NOT_FOUND`, `HEARTBEAT`.
  - Emits `activity` frames with stable activity steps.
- `GET /sessions/{session_id}/events/semantic`
  - Semantic stream derived from snapshot timeline diffs.
  - Not currently consumed by the visible React chat hooks, but it is part of the backend streaming surface.

Relevant backend files:

- `factory-agent/factory_agent/api/routes.py`
- `factory-agent/factory_agent/api/routers/events.py`
- `factory-agent/factory_agent/api/routers/messages.py`
- `factory-agent/factory_agent/api/routers/plans.py`
- `factory-agent/factory_agent/api/routers/execution.py`
- `factory-agent/factory_agent/api/routers/snapshots.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/main.py`

Go backend / legacy chatbot:

- `emas/internal/router/router.go`
- `emas/internal/handler/ai_chat_handler.go`
- `emas/internal/service/chatbot_service.go`
- `emas/cmd/e2e_server/main.go`

### Auth, Session, and Environment Behavior

- Frontend Factory Agent base URL comes from `VITE_FACTORY_AGENT_BASE_URL`; default is `http://127.0.0.1:8000`.
- Frontend Go API base URL comes from `VITE_API_BASE_URL`; default is `http://localhost:8080/api/v1`.
- Docker uses `/agent` and `/api/v1` through nginx.
- Factory Agent auth is controlled by `JWT_REQUIRED`; development can run with auth disabled.
- `VITE_FACTORY_AGENT_BEARER_TOKEN` causes REST requests to send `Authorization`, but browser `EventSource` cannot set authorization headers. The frontend intentionally disables EventSource and keeps snapshot polling enabled when a static bearer token is configured.
- Go protected scheduling/approval routes can require `X-User-Id` and `X-User-Role`.
- CORS in `factory-agent/main.py` allows local Vite origins by default.

### Pain Points and Risks

- No current automated real-browser coverage for opening chat, typing, submitting, waiting, or asserting final UI state.
- Manual checks are still required to validate the actual chatbot flow.
- Existing smoke/API tests do not prove DOM behavior, loading state, stream diagnostics, accessibility, or cancel/navigation behavior.
- Real LLM/model calls are nondeterministic and should not be used in CI.
- EventSource streams are hard to validate with simple request interception because partial streaming, connection close, and disconnect behavior matter.
- Static bearer auth disables EventSource, so both SSE-enabled and polling-fallback modes need browser coverage.
- SSE unit tests exist in Factory Agent, but browser integration against `EventSource` and UI updates is missing.
- Existing generated `playwright-report/` is not ignored in `eMas Front/.gitignore`.
- No root CI workflow exists to run a Playwright browser suite.
- Docker/Compose startup needs local env values and external LLM config; this is too heavy for a deterministic default browser CI job.

## Target Architecture

### Playwright Test Structure

Keep Playwright owned by the frontend package because the browser app is under `eMas Front/`.

Proposed files:

```text
eMas Front/
  playwright.config.js
  e2e/
    fixtures/
      factoryAgentFixtures.js
      sseScripts.js
      selectors.js
    mock-server/
      factoryAgentMockServer.js
      fixtureStore.js
    specs/
      chat-happy-path.spec.js
      chat-loading-final-state.spec.js
      chat-sse-notification.spec.js
      chat-sse-activity.spec.js
      chat-stream-errors.spec.js
      chat-cancel-navigation.spec.js
    README.md
  test-results/              # ignored
  playwright-report/         # ignored
```

Package scripts:

```json
{
  "test:e2e": "playwright test",
  "test:e2e:headed": "playwright test --headed",
  "test:e2e:debug": "playwright test --debug",
  "test:e2e:report": "playwright show-report"
}
```

### Test Environment Strategy

Default CI/local deterministic job:

- Start Vite through Playwright `webServer`.
- Start a test-only mock Factory Agent HTTP/SSE server through Playwright global setup or a second `webServer`.
- Set `VITE_FACTORY_AGENT_BASE_URL=http://127.0.0.1:<mock-port>`.
- Keep `VITE_API_BASE_URL` pointed at a mock route/server only when approval option lookup requires it.
- Run Chromium in CI first; add Firefox/WebKit only after the suite is stable.

Optional full-stack job:

- Reuse `emas/cmd/e2e_server` for seeded Go API.
- Reuse Factory Agent with a fake planner/model/RAG provider or fixture mode.
- Keep this job opt-in or nightly until startup and model substitution are fully deterministic.

### Mocking Strategy

Best strategy for this repo: a test-only mock Factory Agent HTTP/SSE server.

Why:

- The frontend is already isolated behind `VITE_FACTORY_AGENT_BASE_URL`.
- The visible chat flow primarily depends on Factory Agent REST, snapshots, and EventSource streams.
- Browser `EventSource` needs a real HTTP stream to test open, message order, malformed frames, server close, and client disconnect behavior.
- Playwright route interception can mock REST endpoints, but it is a poor fit for timed partial SSE chunks and disconnect assertions.
- MSW is not present, would add a second mocking stack, and service-worker interception is not the most reliable way to test native EventSource behavior.
- A test-only API handler inside production code would increase app surface area for a test concern.
- A controlled fake model provider is still useful later for full-stack Factory Agent tests, but it is not the fastest path to deterministic browser E2E.

Use Playwright route interception only for narrow REST-only cases, such as one-off Go API lookup endpoints or forced HTTP 500 responses.

### SSE Validation Strategy

Use two layers:

1. Browser-facing SSE tests through the mock Factory Agent server.
   - The mock server sends scripted `text/event-stream` frames with delays.
   - It records connection open, last-event-id, close, and disconnect events for assertions.
   - Tests assert DOM behavior: progress bar, diagnostics, activity rows, final answer, cancel button, and final non-busy state.

2. SSE parser/contract tests in Playwright or Node helper code.
   - Parse fixture SSE scripts directly to prove event IDs, event names, data payloads, malformed payload handling, and expected snapshot mutations.
   - Keep Factory Agent backend event runtime tests in pytest as lower-level coverage.

Required SSE scenarios:

- Successful streamed response via notification invalidation plus final snapshot.
- Multiple activity chunks arriving in order.
- Final completion event represented by snapshot `phase`/`status` and terminal timeline event.
- Backend error represented by failed snapshot/timeline state and/or HTTP error on snapshot refresh.
- Network interruption by closing the SSE connection and asserting polling fallback diagnostic.
- Timeout by delaying final snapshot and asserting non-completed state or configured timeout UI.
- Empty response by returning completed session with no assistant summary.
- Malformed event payload by emitting invalid JSON and asserting the UI ignores it without crashing.
- User cancel or navigation away during stream by clicking cancel/close or changing route and asserting EventSource disconnect.

### CI Pipeline Strategy

Add a future root workflow such as `.github/workflows/playwright-e2e.yml` because no root CI workflow currently exists.

Recommended CI steps:

```powershell
cd "eMas Front"
npm ci
npx playwright install --with-deps chromium
npm run test:e2e -- --project=chromium
```

Artifacts:

- Upload `eMas Front/playwright-report/`.
- Upload `eMas Front/test-results/`.
- Keep traces, screenshots, and video only on failure or retry.

Flake controls:

- Use deterministic mock server scripts, not real LLM calls.
- Avoid arbitrary sleeps in tests; wait for locators, network events, mock server state, or DOM status.
- Keep per-test isolated session IDs and fixture state.
- Disable retries locally; allow one retry in CI only after traces are enabled.
- Use a single worker at first for SSE tests, then parallelize when fixture state isolation is proven.

### Data / Fixture Strategy

Fixture data should mirror real snapshot and event shapes from Factory Agent:

- Session fixture: `session_id`, `status`, `phase`, `cursor`, `name`, timestamps.
- Snapshot fixture: `session`, `timeline`, `pending_approval`, `activity_steps`, `resume_hint`, `plan`.
- Message fixture: user and assistant records.
- Event scripts:
  - notification frames with `id`, `event: notification`, and JSON `data`.
  - activity frames with `id`, `event: activity`, and JSON step payload.
  - control frames for readiness, heartbeats, and session-not-found.

Prefer a small number of readable fixture builders over massive static JSON dumps. Reuse seed identifiers such as `M-CNC-01`, `JOB-SEED-001`, and `frontend-operator` where it improves alignment with existing tests.

### Debugging / Reporting Strategy

- Enable Playwright HTML report.
- Use `trace: "on-first-retry"`, `screenshot: "only-on-failure"`, `video: "retain-on-failure"`.
- Capture console errors and failed network responses in a shared fixture.
- Add a mock server request log attachment for failed tests.
- Add `eMas Front/e2e/README.md` with local commands, env vars, and how to inspect reports.

## Long-Term Testing Scope Strategy

The Playwright effort should grow in layers. Each layer should earn its place by catching a different class of risk, not by repeating the same happy path with different prompt text.

### Scope Ladder

| Stage | Name | Main Purpose | Backend Strategy | CI Role | Promotion Gate |
|---|---|---|---|---|---|
| L0 | Browser smoke | Prove the app opens and the chat shell is usable. | Minimal mock Factory Agent. | Required on every PR. | Stable chat-open test and no real services. |
| L1 | Deterministic mocked chat | Cover user-visible chat behavior, final answers, approvals, and errors. | Fixture-driven mock Factory Agent REST. | Required on every PR. | First 12-15 scenarios pass in under 3 minutes. |
| L2 | Deterministic mocked SSE | Cover EventSource lifecycle, ordered chunks, fallback, malformed frames, cancel, and timeout behavior. | Mock Factory Agent REST plus real `text/event-stream`. | Required on every PR once stable; initially one worker. | Full 30-scenario portfolio passes with trace artifacts on failure. |
| L3 | Seeded full-stack browser | Prove frontend contracts against seeded Go API and Factory Agent without real LLM calls. | `emas/cmd/e2e_server` plus Factory Agent fake planner/model/RAG provider. | Scheduled or pre-merge gate for release branches. | Same critical scenarios pass against real services and seeded data. |
| L4 | Production-like release validation | Validate Docker/nginx paths, auth mode, polling fallback, and realistic deployment env. | Compose or staging environment with controlled fake model or approved external model. | Release candidate gate. | No critical flow regressions, reports archived. |
| L5 | Production synthetic monitoring | Keep a small safe canary running after release. | Read-only production/staging user and health-safe prompts only. | Post-deploy monitor, not PR CI. | Alerts on availability, latency, SSE/fallback, and final answer completion. |

### Phase Gate and Defect Rule

Phase 8 onward must be treated as quality gates, not just test-writing milestones.

- If a reproducible product, integration, data, environment, auth, SSE, orchestration, or deployment failure is found in the current phase, stop promotion to the next phase.
- Fix the defect before the next phase starts. The fix should include a regression assertion at the lowest useful layer: Go test, Factory Agent pytest, frontend unit/component test, mocked Playwright, seeded Playwright, release Playwright, or synthetic monitor.
- A failure can be deferred only as an explicit accepted gap in `TRACK.md` with owner, severity, reason, risk, target phase/date, and a temporary manual workaround. Deferred gaps cannot be hidden by marking the phase `Done`.
- After every fix, rerun the current phase verification command plus the fast deterministic PR suite: `npm test` and `npm run test:e2e -- --project=chromium`.
- Do not grow the next phase while current phase verification is failing. Passing more scenarios without fixing known defects gives false confidence.

### Test Pyramid for This Repo

Keep responsibilities separated:

- Go `go test`: backend handlers, routing, seed data, approval contracts, and database behavior.
- Factory Agent pytest: planner/service contracts, snapshot shape, SSE runtime, approval resume, RAG structure, and reliability.
- Frontend Node tests: component rendering and pure UI assembly logic.
- Playwright mocked browser tests: real user flows through the browser with deterministic REST/SSE fixtures.
- Playwright seeded full-stack tests: a smaller release-gate subset proving the browser still matches real service contracts.
- Production synthetic checks: safe read-only availability checks only, never broad destructive scenarios.

### Scenario Selection Rules

Use these rules to keep the first suite meaningful and non-redundant:

- Prefer one scenario per distinct risk: input, loading state, snapshot completion, SSE ordering, fallback, approval, cancellation, error, auth mode, and persistence.
- Do not add prompt variants unless they exercise a different UI state or backend contract.
- Every scenario must name the user-visible assertion and the backend/SSE behavior it proves.
- Default to mocked deterministic data for PR CI.
- Use seeded full-stack only when the scenario needs real routing, nginx, Go API data, or Factory Agent schema compatibility.
- Keep the initial browser suite around 30 scenarios. Add new scenarios by retiring or merging old ones if the suite becomes repetitive.

### First-Wave Scenario Portfolio

These 30 scenarios are the initial target. Implement them gradually across Phases 1-5; do not wait until all 30 are written before getting the first Playwright signal into CI.

| # | Scenario | Primary Risk Covered | Recommended Layer |
|---|---|---|---|
| 1 | App opens dashboard and floating chat control is reachable by an accessible selector. | Browser boot, routing, selector stability. | L0 |
| 2 | Chat modal opens and shows empty state plus enabled composer. | Core entry point and usable input. | L0 |
| 3 | New session can be started from the sidebar. | Session creation UX and REST `POST /sessions`. | L1 |
| 4 | Existing active session is restored from local storage. | Session persistence and initial snapshot load. | L1 |
| 5 | User sends "Show status for machine M-CNC-01" and sees final assistant answer. | Core happy path from input to completed response. | L1 |
| 6 | User asks for low priority jobs and sees a result/table-style answer. | Structured result rendering, not just plain text. | L1 |
| 7 | User asks a RAG/LOTO question and sees answer plus source/citation chrome. | Source rendering and stream-gated extras. | L1 |
| 8 | Follow-up message after completion creates a second distinct turn. | Multi-turn continuity and no stale answer overwrite. | L1 |
| 9 | Plan mode submission preserves mode and produces expected planning/progress copy. | Composer mode path and plan-specific behavior. | L1 |
| 10 | Final assistant text animates to completion before sources/details appear. | Local typewriter behavior and final completed state. | L1 |
| 11 | Notification SSE `hello` opens, invalidates snapshot, and triggers refresh. | EventSource notification contract. | L2 |
| 12 | Multiple notification events update in cursor order without duplicate refreshes. | Ordered stream processing and cursor handling. | L2 |
| 13 | Activity stream emits multiple steps and the activity UI shows them in order. | Activity chunk ordering and timeline display. | L2 |
| 14 | Final completion arrives through SSE plus snapshot and removes busy UI. | Terminal state transition. | L2 |
| 15 | SSE heartbeat frames do not create noisy visible messages. | Heartbeat handling. | L2 |
| 16 | SSE reconnect uses `Last-Event-ID` and does not duplicate prior activity. | Reconnect/resume behavior. | L2 |
| 17 | Static bearer token mode disables EventSource and uses polling fallback. | Auth-mode compatibility. | L2 |
| 18 | Malformed SSE payload is ignored and the next valid event still updates UI. | Stream robustness. | L2 |
| 19 | SSE connection drops and UI shows snapshot polling fallback diagnostic. | Network interruption behavior. | L2 |
| 20 | Plan creation returns 503 and UI shows backend unavailable/error state without fake success. | Backend failure display. | L1 |
| 21 | Execute returns 409 once, UI/backend retries, and final response completes. | Retry/concurrency behavior. | L1 |
| 22 | Snapshot returns session not found and UI recovers to a safe state. | Deleted/stale session handling. | L1 |
| 23 | Active session never reaches terminal state before timeout and UI remains honest. | Timeout/no false completion. | L2 |
| 24 | Completed snapshot has empty assistant content and does not show a stale previous answer. | Empty response handling. | L1 |
| 25 | User cancels an active run and final UI returns to idle/cancelled state. | Cancel path and `POST /cancel`. | L2 |
| 26 | User closes modal or navigates during an active stream and EventSource disconnects. | Client disconnect cleanup. | L2 |
| 27 | Approval-required response renders risk summary, preview/table, and Approve/Reject actions. | Approval UI and pending state. | L1 |
| 28 | Approval approve flow resumes and reaches completed final answer. | Approval decision/resume behavior. | L2/L3 |
| 29 | Approval reject flow returns to idle with rejection state and no fake completion. | Rejection handling. | L2/L3 |
| 30 | Confirmation-required flow shows choices, user selects one, and follow-up execution completes. | `WAITING_CONFIRMATION` branch and `/confirm`. | L2/L3 |

### Growth Beyond the First 30

After the first portfolio is stable, Phase 8 onward should become intentionally failure-seeking. The goal is not to add more prompt variants; it is to find the places where real services, state, timing, approvals, RAG, auth, and deployment behavior disagree with the mocked browser suite.

Focus expansion on:

- Seeded full-stack contract checks against real Vite, Factory Agent, Go API, seeded DB, and fake planner/model/RAG providers.
- Hard orchestration flows: multi-step jobs, multi-approval chains, approval reject/timeout, partial failure, retry, and cancel during execution.
- State hazards: stale local storage, duplicate submits, refresh during active job, two browsers using different sessions, backend restarts, and out-of-order or duplicated SSE events.
- Data hazards: large structured results, empty source lists, malformed tool payloads, missing optional fields, schema drift, and seeded RAG/source shape changes.
- Deployment hazards: nginx pathing, CORS, auth-required mode, static bearer polling fallback, missing env vars, slow network, mobile viewport, artifact collection, and release rollback signal.
- Production hazards: safe read-only canaries, latency thresholds, alert routing, auth token expiry, provider outage detection, and trace redaction.

### L3-L5 Manual-Testing Elimination Scope

Phases 1-7 remove routine manual browser regression for deterministic frontend behavior. Phases 8-12 remove the remaining manual release and production smoke checks by replacing them with controlled full-stack, production-like, synthetic, and governance gates.

| Level | Manual Check Replaced | Automated Replacement |
|---|---|---|
| L3 foundation | Manually starting local services, seeding data, opening the chat, and checking real-service integration. | Seeded full-stack Playwright job using real Vite, real Go API, real Factory Agent, seeded DB, and controlled fake planner/model/RAG responses. |
| L3 hard orchestration | Manually trying complex chatbot jobs, multi-step execution, approvals, cancellations, and awkward timing. | Seeded full-stack adversarial Playwright scenarios with deterministic service faults, multi-approval chains, state recovery, and SSE ordering checks. |
| L4 | Manually testing Docker/nginx/staging paths, auth configuration, slow networks, release artifacts, and release readiness. | Production-like release validation job against Compose or staging with deployment URLs, auth mode, fault injection, latency budgets, artifacts, and release gate assertions. |
| L5 | Manually checking after deploy that the chatbot still works. | Safe production/staging synthetic monitor with read-only canary prompts, latency thresholds, SSE/fallback checks, provider outage signals, and alerts. |
| Governance | Manually remembering which checks are still needed. | Replacement matrix, accepted-gap register, owners, scenario review cadence, and phase gate rules in `TRACK.md`. |

Keep one boundary clear: automated L5 can replace operational smoke testing, but human review may still be used for product judgment or deep semantic answer-quality audits. Exact answer quality belongs to evals and review workflows, not brittle browser assertions.

### L3-L5 and Production-Grade Scenario Expansion

Use this production-facing scenario set after the first 30 deterministic scenarios are stable. Scenarios 39-52 and 86-100 are deliberately hard and should be expected to reveal defects. When they do, fix the defect and keep the regression coverage before moving on.

| # | Scenario | Level | Purpose |
|---|---|---|---|
| 31 | Seeded full-stack opens chat through Vite and creates a Factory Agent session. | L3 foundation | Proves browser-to-real-Factory-Agent session contract. |
| 32 | Seeded full-stack machine status prompt completes against seeded Go API data. | L3 foundation | Proves Factory Agent tool-to-Go API contract and final UI rendering. |
| 33 | Seeded full-stack low-priority jobs prompt renders structured results. | L3 foundation | Proves real snapshot/timeline shape for table-like results. |
| 34 | Seeded full-stack RAG/LOTO prompt renders answer and sources using controlled fake RAG/provider output. | L3 foundation | Proves RAG response contract without real LLM nondeterminism. |
| 35 | Seeded full-stack approval-required flow renders pending approval from real Factory Agent snapshot. | L3 foundation | Proves approval contract and UI compatibility. |
| 36 | Seeded full-stack approval approve resumes and reaches completed state with controlled provider. | L3 foundation | Proves approval resume path across services. |
| 37 | Seeded full-stack cancel during execution returns to idle/cancelled state. | L3 foundation | Proves cancel endpoint and UI state across real services. |
| 38 | Seeded full-stack notification/activity SSE opens and reaches final snapshot. | L3 foundation | Proves real Factory Agent EventSource behavior with the browser. |
| 39 | Multi-step job runs at least four ordered steps: plan, read seeded data, apply business rule, summarize. | L3 hard | Catches broken orchestration ordering and missing step UI. |
| 40 | Multi-approval chain requires two approvals before final execution completes. | L3 hard | Catches skipped, duplicated, or stale approval state. |
| 41 | Multi-approval chain rejects the second approval and stops without running later steps. | L3 hard | Catches unsafe continuation after rejection. |
| 42 | Approval timeout leaves the job safe, visible, and non-terminal without hidden continuation. | L3 hard | Catches background execution after an expired decision. |
| 43 | Multi-step partial failure succeeds step 1, fails step 2, and never runs step 3. | L3 hard | Catches false success and accidental downstream execution. |
| 44 | Tool payload/schema mismatch returns a visible safe error instead of crashing the chat panel. | L3 hard | Catches fixture drift and backend/frontend schema assumptions. |
| 45 | Duplicate submit or double-click sends only one user turn and one execute request. | L3 hard | Catches duplicate jobs and race conditions in composer state. |
| 46 | Stale local storage points to a deleted session and the UI recovers to a new safe state. | L3 hard | Catches stale session restore bugs. |
| 47 | Out-of-order or duplicate SSE events do not regress the visible phase or duplicate activity rows. | L3 hard | Catches cursor/order handling bugs. |
| 48 | EventSource reconnect uses `Last-Event-ID` and does not replay already-rendered steps. | L3 hard | Catches reconnect duplication and missed updates. |
| 49 | Large structured result renders without freezing, overlapping, or losing final completion state. | L3 hard | Catches heavy DOM and layout regressions. |
| 50 | Two browser contexts run different sessions at the same time without cross-session leakage. | L3 hard | Catches session isolation and storage leakage. |
| 51 | Factory Agent restarts or stream drops mid-run and the UI recovers by polling or safe failure. | L3 hard | Catches service restart and connection-loss behavior. |
| 52 | RAG answer has no sources or an unavailable source and the UI shows an honest fallback. | L3 hard | Catches source rendering assumptions. |
| 53 | Docker/nginx release path opens app at `/` and routes Factory Agent through `/agent`. | L4 | Proves reverse proxy pathing. |
| 54 | Docker/nginx release path routes Go API through `/api/v1`. | L4 | Proves backend proxy pathing. |
| 55 | Production-like static bearer or auth-required mode disables EventSource and uses polling fallback. | L4 | Proves auth-mode compatibility. |
| 56 | Production-like CORS preflight and browser requests succeed for Factory Agent and Go API. | L4 | Proves deployment browser connectivity. |
| 57 | Release validation intentionally fails one controlled test and archives trace/video/report/log artifacts. | L4 | Proves debugging readiness before release. |
| 58 | Release validation checks chat-open, first progress, and final answer latency budgets. | L4 | Proves operator-facing performance. |
| 59 | Controlled real-LLM connectivity smoke runs only when explicitly enabled. | L4 | Proves provider connectivity without making PR CI flaky. |
| 60 | Go API unavailable during a chatbot job shows degraded/error state and no fake completion. | L4 | Catches dependency outage handling. |
| 61 | Factory Agent unavailable at page load keeps chat usable enough to show diagnostics. | L4 | Catches boot-time backend outage handling. |
| 62 | Missing or bad frontend API env var fails fast with a visible diagnostic in release validation. | L4 | Catches silent misconfiguration. |
| 63 | Database migration or schema mismatch fails the release gate before browser tests claim success. | L4 | Catches incompatible release artifacts. |
| 64 | Browser refresh during an active job restores or safely abandons the run without duplicate execution. | L4 | Catches release build persistence bugs. |
| 65 | Slow network profile still shows first progress before the agreed threshold or fails with evidence. | L4 | Catches timing regressions hidden by fast local runs. |
| 66 | Mobile viewport opens chat, submits prompt, handles approval card, and avoids text overlap. | L4 | Catches responsive chatbot regressions. |
| 67 | Keyboard-only flow can open chat, submit, approve/reject, and close modal. | L4 | Catches accessibility and focus regressions. |
| 68 | Release rollback candidate can run the same smoke command against previous build URL. | L4 | Proves rollback validation is ready. |
| 69 | Browser cache/version mismatch does not load stale frontend against incompatible backend schema. | L4 | Catches cache and asset version issues. |
| 70 | Long-running stream stays within memory/log limits and still reaches a terminal state or timeout. | L4 | Catches resource leaks. |
| 71 | Production synthetic health check opens chat and confirms composer availability. | L5 | Detects frontend availability regression. |
| 72 | Production synthetic read-only machine status canary completes with non-empty final response. | L5 | Detects end-to-end chatbot outage. |
| 73 | Production synthetic RAG/source canary returns structurally valid answer and optional source metadata. | L5 | Detects RAG path outage without exact-text assertions. |
| 74 | Production synthetic SSE-or-polling canary observes progress then completion. | L5 | Detects streaming/fallback outage. |
| 75 | Production synthetic alerting fires on timeout, backend unavailable, auth failure, or missing final answer. | L5 | Proves monitor is actionable. |
| 76 | Synthetic auth token expiry or revocation fails clearly and alerts the owner. | L5 | Catches credential lifecycle failures. |
| 77 | Synthetic provider outage canary detects model/RAG dependency failure without mutating data. | L5 | Catches external dependency outages. |
| 78 | Synthetic latency burn-rate check reports degraded performance before hard outage. | L5 | Catches slow failures. |
| 79 | Production trace/screenshot redaction prevents leaking sensitive operational data on failure. | L5 | Catches observability/privacy risk. |
| 80 | Manual replacement matrix audit confirms every old manual chatbot check has an automated gate or accepted gap. | Governance | Proves manual testing can be retired responsibly. |
| 81 | Ten-turn normal operator chat mixes machine status, jobs, LOTO/RAG, and follow-up questions without stale answers or lost UI state. | Production hardening | Catches normal-use drift after many turns without testing long-term memory features. |
| 82 | Session list with many historical sessions loads, selects, and restores the correct transcript. | Production hardening | Catches normal operator history and stale-session regressions. |
| 83 | Browser reload after a completed run restores final answer, sources/details, and non-busy composer state. | Production hardening | Catches refresh/persistence regressions in normal use. |
| 84 | User edits a draft, switches mode, and submits once with the final text and mode. | Production hardening | Catches composer state and accidental duplicate-submit regressions. |
| 85 | Repeatedly open/close the chat across completed, failed, and cancelled sessions without leaked streams, timers, or stale banners. | Production hardening | Catches everyday modal lifecycle leaks. |
| 86 | Cascading priority update changes all original high-priority jobs to low, then all original low-priority jobs to medium, with separate approvals and exact final DB state. | Data integrity | Catches planner stopping after one approval, mutating newly changed rows, or ending before the second operation. |
| 87 | Bulk update partial failure records exact per-row outcomes and does not claim all jobs succeeded. | Data integrity | Catches false success and unclear partial writes. |
| 88 | Approval double-click, refresh, or replay does not apply the same mutation twice. | Data integrity | Catches non-idempotent approval execution. |
| 89 | Expired or stale approval cannot mutate data after the session changes state. | Data integrity | Catches unsafe delayed approval execution. |
| 90 | Audit log, DB state, SSE timeline, and final assistant summary agree for every mutating job. | Data integrity | Catches inconsistency between UI claims and persisted side effects. |
| 91 | Ten concurrent read-only browser sessions complete without cross-session leakage. | Reliability | Catches isolation and concurrency issues under normal team use. |
| 92 | Long stream with many activity events reaches terminal state without duplicate rows, high memory, or stuck busy UI. | Reliability | Catches stream accumulation and frontend resource leaks. |
| 93 | Large structured result and many sources render with stable layout and usable controls. | Reliability | Catches heavy DOM and normal large-result regressions. |
| 94 | Slow API/tool response shows progress, respects timeout, and preserves retry/cancel controls. | Reliability | Catches poor degraded-network behavior. |
| 95 | Repeated soak run completes the core mocked, seeded, and release smoke suites without leaked ports or orphan processes. | Reliability | Catches flake and process cleanup issues. |
| 96 | Tampered local storage or session id cannot expose another user's session. | Security/privacy | Catches session isolation and authorization gaps. |
| 97 | Unauthorized REST, polling, and EventSource access are denied with safe visible diagnostics. | Security/privacy | Catches auth bypass and poor failure UX. |
| 98 | Logs, traces, screenshots, and reports redact tokens, secrets, and sensitive operational fields. | Security/privacy | Catches observability data leaks. |
| 99 | Very large pasted input and unsafe markdown render safely without script execution or layout collapse. | Security/privacy | Catches input abuse and rendering safety issues. |
| 100 | Tool allowlist and approval gates block requests that try to perform unsupported or unsafe actions. | Security/privacy | Catches unsafe tool execution paths. |
| 101 | Synthetic failure creates the expected alert, owner, severity, and runbook link. | Operational readiness | Catches unactionable monitoring. |
| 102 | Rollback validation command passes against the previous known-good build URL. | Operational readiness | Proves release recovery path. |
| 103 | Chatbot feature flag or emergency disable path leaves the rest of the app usable with a clear diagnostic. | Operational readiness | Proves safe kill-switch behavior. |
| 104 | Recreated environment with seeded DB and synthetic account can run the release/synthetic gates from scratch. | Operational readiness | Proves disaster-recovery readiness. |
| 105 | Production-grade gate matrix runs PR, seeded, hard, release, synthetic, security/privacy, and reliability checks with no critical failures. | Operational readiness | Proves operational gates are runnable before final prompt-robustness signoff. |
| 106 | Natural LOTO query with explicit machine ID, `What LOTO procedure applies before working on M-CNC-01?`, routes to LOTO/RAG without asking for the machine again. | Intent/entity robustness | Catches missed entity extraction when the ID is present in normal wording. |
| 107 | LOTO prompt variants with punctuation, lowercase ID, missing question mark, and short phrasing all extract `M-CNC-01`. | Intent/entity robustness | Catches brittle regex/case/punctuation matching. |
| 108 | Machine/job/status prompt variants using synonyms like equipment, asset, work order, task, urgent, overdue, and priority map to the correct tools. | Intent/entity robustness | Catches prompt wording gaps not covered by exact fixture phrases. |
| 109 | Clarification boundary: missing machine ID asks a clarifying question, but present machine ID never asks for the same ID again. | Intent/entity robustness | Catches over-eager clarification and under-specified execution. |
| 110 | Multi-entity prompt with machine ID plus job ID chooses the correct primary route and does not drop either entity. | Intent/entity robustness | Catches entity collision and wrong tool routing. |
| 111 | RAG/LOTO route returns an honest not-found response when the machine exists but no LOTO source exists, without generic backend attention. | Intent/entity robustness | Catches poor missing-knowledge handling. |
| 112 | RAG source relevance check verifies returned source metadata is tied to the requested machine/procedure. | Intent/entity robustness | Catches irrelevant source attachment. |
| 113 | Intent/entity parser unit matrix covers IDs embedded in punctuation, newlines, markdown, quotes, and mixed case. | Intent/entity robustness | Catches parser bugs below browser level. |
| 114 | Manual-regression query bank converts every newly found manual prompt miss into deterministic unit, seeded, or browser coverage. | Intent/entity robustness | Catches future "works in tests but fails manually" gaps. |
| 115 | Prompt robustness gate runs the query bank through seeded fake-provider routing and fails on any unexpected clarification, wrong tool, or missing final state. | Intent/entity robustness | Final prompt-robustness gate before claiming most normal-use prompts are covered. |
| 116 | LOTO wording matrix runs multiple natural variants of the same M-CNC-01 LOTO request and expects the same LOTO/RAG route. | Prompt/workflow regression expansion | Catches exact-phrase-only fixes. |
| 117 | Machine and job ID extraction matrix covers punctuation, lowercase, quotes, parentheses, markdown, and newline-separated IDs. | Prompt/workflow regression expansion | Catches brittle entity extraction across realistic copy/paste text. |
| 118 | Route-selection matrix asserts selected intent/tool evidence for LOTO, machine status, job listing, priority mutation, approval, and cancel prompts. | Prompt/workflow regression expansion | Catches prompts that render something but use the wrong route. |
| 119 | Priority cascade matrix covers high-to-low then low-to-medium, medium-to-high then high-to-medium, low-to-high then high-to-low, and high-to-medium then medium-to-low. | Prompt/workflow regression expansion | Catches untested cascade/swap patterns and middle-stop behavior. |
| 120 | Two-write-set approval invariant proves every two-step mutation shows approval 1, executes step 1, shows approval 2, executes step 2, then completes. | Prompt/workflow regression expansion | Catches workflows that stop after the first approval. |
| 121 | Original-state mutation invariant proves second-step target groups are based on the original snapshot unless the user explicitly requests current-state behavior. | Prompt/workflow regression expansion | Catches newly changed rows being mutated again by accident. |
| 122 | Regression bank schema requires source prompt, observed failure, expected behavior, owner, severity, lowest test layer, and browser coverage flag. | Prompt/workflow regression expansion | Catches undocumented manual failures that never become tests. |
| 123 | Manual failure triage rule maps every new manual miss to parser, route, seeded workflow, browser, or accepted-gap coverage before closure. | Prompt/workflow regression expansion | Catches "fixed once in code" without permanent regression coverage. |
| 124 | Browser diagnostics regression check proves successful routed prompts do not show generic `Factory Agent needs attention`, while true unknowns do. | Prompt/workflow regression expansion | Catches false attention/error states from routing misses. |
| 125 | Phase 19 regression gate runs the prompt/workflow bank through unit, seeded, and targeted browser checks with a coverage summary. | Prompt/workflow regression expansion | Final expansion gate for manual-failure-driven hardening. |
| 126 | Real LangGraph approval-chain regression proves `change all medium priority job to high then change all high priority job to medium` raises approval 2 after approval 1 commits, without `SeededPlaywrightPlanner`. | Real LangGraph approval-chain regression | Catches seeded-only false confidence where browser/full-stack tests pass but manual LangGraph stops after approval 1. |

### Coverage Gap Analysis After Phase 14

Phase 14 proves important mutating workflow integrity, but it does not prove that the system understands enough natural operator wording. The observed manual failure for `What LOTO procedure applies before working on M-CNC-01?` shows a distinct gap: the browser can render errors correctly, the graph can execute deterministic paths, and data-integrity checks can pass, while the planner/entity/RAG route still fails to recognize an explicit machine ID in normal phrasing.

Uncovered or under-covered areas:

- Entity extraction robustness: machine IDs, job IDs, and procedure names inside punctuation, mixed case, quotes, markdown, and short questions.
- Intent routing breadth: LOTO/RAG, status, jobs, approvals, and priority workflows must work across synonyms and normal operator wording, not only exact fixture prompts.
- Clarification boundaries: the agent should ask for missing required entities, but should not ask for an entity that is already present.
- RAG route correctness: the system must distinguish "no source found" from "missing machine ID" and from backend/model failure.
- Source relevance: returned source metadata must relate to the requested machine/procedure, not just any LOTO document.
- Prompt regression capture: every manual prompt failure should become a small deterministic test at the lowest useful layer, then one browser/seeded check when user-visible behavior matters.

Phase 18 addresses these gaps without adding Promptfoo or broad real-LLM evaluation. It uses deterministic parser/unit tests, seeded fake-provider routing, and a small browser query bank to prove normal-use prompt coverage is no longer limited to exact scenario wording.

Phase 19 expands the Phase 18 foundation into a repeatable regression program. Phase 18 should prove the system has the right parser/routing/test harness. Phase 19 should keep feeding that harness with real manual misses and workflow variants, especially cascade mutations and approval sequences that were not part of the original seeded examples. Phase 19 still does not add Promptfoo; real LLM quality evaluation remains a separate eval track.

## Phased Implementation Plan

### Phase 0: Discovery and Risk Mapping

Goal:

Document the current testing, frontend chat, backend/API/SSE, auth/session, and environment shape before adding Playwright.

Files likely to be touched:

- `PLAN.md`
- `TRACK.md`

Implementation steps:

- Inspect project layout, package files, tests, chat UI, Factory Agent routes, Go routes, env config, Docker/nginx config, and existing docs.
- Record current-state analysis and risks.
- Create `TRACK.md` with phase status, blockers, decisions, commands, and next action.

Acceptance criteria:

- `PLAN.md` contains repo-specific current state and target architecture.
- `TRACK.md` identifies Phase 1 as the next executable step.
- No implementation code, dependency, or test pipeline changes are made.

Verification command:

```powershell
git status --short --branch
```

Risks or unknowns:

- Some prior manual/browser baseline evidence may be stale.
- No CI provider was found in the repo.

Rollback notes:

- Revert `PLAN.md` and `TRACK.md`.

### Phase 1: Playwright Setup and Baseline Browser Tests

Goal:

Install Playwright and prove the React app can open in a real browser with a deterministic mock backend.

Files likely to be touched:

- `eMas Front/package.json`
- `eMas Front/package-lock.json`
- `eMas Front/playwright.config.js`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/specs/app-shell.spec.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/.gitignore`
- Possibly `eMas Front/src/components/shared/FloatingChatButton.jsx`

Implementation steps:

- Add `@playwright/test` as a dev dependency.
- Add `test:e2e`, `test:e2e:headed`, `test:e2e:debug`, and `test:e2e:report` scripts.
- Add Playwright config with Vite `webServer`.
- Add a minimal mock Factory Agent server returning empty sessions and health responses.
- Set `VITE_FACTORY_AGENT_BASE_URL` for Playwright runs.
- Add a baseline test that opens `/`, verifies the app shell, opens the AI Assistant, and verifies the composer is visible.
- Add an accessible label or stable test id to the floating chat button if needed.
- Ignore Playwright reports and test results.
- Cover scenarios 1-2 from the first-wave portfolio.

Acceptance criteria:

- `npm run test:e2e -- --project=chromium` launches Vite, opens the app, and passes a baseline browser test.
- Existing `npm test` remains unchanged and passing.
- No real Factory Agent, Go backend, Docker, or LLM dependency is required.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
```

Risks or unknowns:

- Current chat button lacks a stable accessible label.
- Vite env injection must happen before the frontend dev server starts.

Rollback notes:

- Remove Playwright dependency, scripts, config, e2e folder, and any selector-only UI change.

### Phase 2: Chatbot Happy-Path E2E Tests

Goal:

Automate the core user journey: open chatbot, type a message, submit it, observe loading/working UI, and assert final visible response.

Files likely to be touched:

- `eMas Front/e2e/specs/chat-happy-path.spec.js`
- `eMas Front/e2e/fixtures/factoryAgentFixtures.js`
- `eMas Front/e2e/fixtures/selectors.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`

Implementation steps:

- Add fixture state for one session lifecycle:
  - no active session
  - session created
  - user message added
  - plan created
  - execute started
  - snapshot moves from `PLANNING`/`EXECUTING` to `COMPLETED`
- In the browser, click the chat button, type a realistic prompt, and submit.
- Assert the user message appears optimistically or after snapshot refresh.
- Assert progress/loading UI appears while the session is active.
- Assert final assistant answer content appears.
- Assert the progress indicator is gone and the composer is enabled at completion.
- Cover scenarios 3-10 from the first-wave portfolio where practical.

Acceptance criteria:

- Browser test covers input through final streamed/snapshot-derived response.
- Assertions use user-visible roles/text where possible, with stable fallback selectors only where needed.
- Test does not call real LLM or real Factory Agent.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium --grep "happy path"
```

Risks or unknowns:

- Current UI has client-side typewriter behavior for final answer; tests must wait for completed visible text, not only snapshot state.
- Some current buttons rely on icon-only text and may need accessible labels.

Rollback notes:

- Remove the happy-path spec and fixtures.

### Phase 3: Deterministic Mocking for Chatbot Responses

Goal:

Make chatbot browser tests deterministic, readable, and extensible across multiple scenarios.

Files likely to be touched:

- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/fixtures/factoryAgentFixtures.js`
- `eMas Front/e2e/fixtures/sseScripts.js`
- `eMas Front/e2e/specs/chat-fixtures.spec.js`
- `eMas Front/e2e/README.md`

Implementation steps:

- Introduce named scenarios such as `readMachineHappyPath`, `ragAnswerWithSources`, `approvalRequired`, `backendUnavailable`, and `emptyCompletedAnswer`.
- Implement per-test fixture reset endpoint or in-process reset hook on the mock server.
- Support deterministic request logs and scenario assertions.
- Support REST errors for `/plans`, `/execute`, and `/snapshot`.
- Keep fixture shapes close to Factory Agent `SessionSnapshotResponse` and timeline events.
- Document how to add a new scenario.

Acceptance criteria:

- Tests can select a scenario without copy-pasting endpoint handlers.
- Mock server logs requests and EventSource lifecycle.
- Fixture builders are small enough for future agents to understand quickly.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium --grep "fixture"
```

Risks or unknowns:

- Fixture drift from real Factory Agent schemas can create false confidence.
- Mitigate by adding a later contract check that validates key fixture fields against existing Factory Agent schema/tests.

Rollback notes:

- Revert mock-server fixture framework and keep only the Phase 2 happy-path mocks.

### Phase 4: SSE Streaming Tests

Goal:

Validate the actual browser SSE behavior for Factory Agent notification and activity streams.

Files likely to be touched:

- `eMas Front/e2e/fixtures/sseScripts.js`
- `eMas Front/e2e/specs/chat-sse-notification.spec.js`
- `eMas Front/e2e/specs/chat-sse-activity.spec.js`
- `eMas Front/e2e/specs/chat-sse-final-state.spec.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`

Implementation steps:

- Add mock SSE script runner that writes valid `text/event-stream` frames with controlled delays.
- Test successful notification stream:
  - `hello`
  - `snapshot_invalidated`
  - `phase_changed`
  - final completed snapshot
- Test activity stream order:
  - `STREAM_READY`
  - multiple `activity` frames in order
  - final activity state
- Assert visible activity/progress UI updates in order.
- Assert final assistant response only appears after completed snapshot.
- Assert `Last-Event-ID` handling where the browser reconnects.
- Cover scenarios 11-19 and 25-26 from the first-wave portfolio.

Acceptance criteria:

- Multiple chunks/events arriving in order are verified.
- Final completion state is verified in the DOM.
- Mock server proves EventSource connections opened and closed as expected.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium --grep "SSE"
```

Risks or unknowns:

- Playwright cannot directly inspect native EventSource message callbacks from outside the page unless instrumented.
- Use DOM assertions plus mock server connection logs; add optional page instrumentation only if needed.

Rollback notes:

- Remove SSE specs and mock stream runner changes.

### Phase 5: Failure, Timeout, Retry, and Disconnect Scenarios

Goal:

Cover the failure modes currently handled manually or by lower-level tests.

Files likely to be touched:

- `eMas Front/e2e/specs/chat-stream-errors.spec.js`
- `eMas Front/e2e/specs/chat-timeouts.spec.js`
- `eMas Front/e2e/specs/chat-cancel-navigation.spec.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/fixtures/sseScripts.js`
- Possibly `eMas Front/src/components/features/chat/factory-agent/*` if missing states or selectors are discovered

Implementation steps:

- Test backend error:
  - `/plans` or `/execute` returns 500/503.
  - UI shows backend unavailable or error diagnostic without fake success.
- Test SSE network interruption:
  - mock server closes stream unexpectedly.
  - UI shows fallback/polling diagnostic.
- Test timeout:
  - snapshot never reaches terminal state within test timeout.
  - UI remains active or displays timeout handling as designed.
- Test empty response:
  - completed snapshot contains no assistant summary.
  - UI does not crash or show stale previous answer.
- Test malformed event payload:
  - invalid JSON frame is ignored.
  - subsequent valid frame still updates UI.
- Test user cancel:
  - active session exposes cancel button.
  - click cancel and assert `/cancel` is called, final state is idle/cancelled.
- Test navigation/close during stream:
  - close modal or navigate away.
  - mock server records EventSource disconnect.
- Cover scenarios 20-24 and 27-30 from the first-wave portfolio.

Acceptance criteria:

- Required failure matrix is covered in browser tests.
- No failure scenario depends on real model/API calls.
- Tests assert user-visible behavior plus mock server request/connection evidence.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium --grep "error|timeout|cancel|disconnect|malformed|empty"
```

Risks or unknowns:

- Some failure states may be handled silently by hooks today, requiring small UI/diagnostic improvements.
- Browser cancel/navigation disconnect timing can be timing-sensitive; use mock server logs with bounded waits.

Rollback notes:

- Remove failure specs and any selector-only UI changes. Keep bug fixes only if separately validated and desired.

### Phase 6: CI Integration

Goal:

Run Playwright browser E2E deterministically in CI with useful artifacts and low flake risk.

Files likely to be touched:

- `.github/workflows/playwright-e2e.yml` or the repo's actual CI config when identified
- `eMas Front/package.json`
- `eMas Front/playwright.config.js`
- `eMas Front/e2e/README.md`
- `.gitignore`

Implementation steps:

- Add CI job using Node 20 or the repo-standard Node version.
- Run `npm ci`.
- Install Playwright Chromium browser with cache-friendly setup.
- Run existing frontend tests first: `npm test`.
- Run Playwright: `npm run test:e2e -- --project=chromium`.
- Upload Playwright report and test results on failure.
- Set workers to `1` initially for SSE tests.
- Use CI retry policy of `1` with traces on retry.
- Keep full-stack/real-service jobs separate and opt-in/nightly.

Acceptance criteria:

- CI runs deterministic browser E2E with no real LLM/API dependency.
- Failure artifacts include report, trace, screenshot, video, and mock server log.
- Existing Go/Python/API pipeline remains intact.

Verification command:

```powershell
Set-Location "eMas Front"
npm ci
npx playwright install chromium
npm test
npm run test:e2e -- --project=chromium
```

Risks or unknowns:

- CI provider is not currently present in the repo.
- Browser cache behavior depends on CI provider.
- Windows vs Linux path handling must be kept portable because local development is on Windows.

Rollback notes:

- Remove the CI workflow/job. Keep local Playwright scripts if useful.

### Phase 7: Cleanup and Replacement of Old Pipeline

Goal:

Deprecate manual chatbot validation and clearly define what remains in the old API/seed pipeline.

Files likely to be touched:

- `tests/e2e/README.md`
- `tests/e2e/run_seed_pipeline.ps1`
- `eMas Front/e2e/README.md`
- `README.md` or `eMas Front/README.md`
- `TRACK.md`
- Existing manual baseline docs if they need deprecation notes

Implementation steps:

- Map old manual checks to new Playwright specs.
- Mark manual chatbot typing/waiting/checking steps as replaced by Playwright.
- Keep `tests/e2e/run_seed_pipeline.ps1` for API contract, seed, reliability, and optional live/full-stack checks.
- Decide whether `factory-agent-smoke.js` remains as a quick API smoke or is replaced by Playwright happy path.
- Update docs with local and CI commands.
- Add a final replacement checklist and owner notes.

Acceptance criteria:

- Future agents know which command replaces manual chatbot validation.
- Old pipeline is not deleted unless there is a proven replacement and explicit approval.
- `TRACK.md` records final decisions, commands, results, and remaining risks.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
```

Risks or unknowns:

- Existing API pipeline still covers important non-browser contracts and should not be removed wholesale.
- Live LLM/RAG testing remains opt-in and non-deterministic by design.

Rollback notes:

- Revert documentation deprecation notes and keep old instructions as primary.

### Phase 8: L3 Seeded Full-Stack Foundation

Goal:

Run Playwright against real local Vite, Factory Agent, Go API, and seeded data while still avoiding real LLM nondeterminism. This phase proves the full-stack test harness before adding deliberately hostile scenarios.

Files likely to be touched:

- `eMas Front/playwright.config.js`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/specs/full-stack-seeded.spec.js`
- `eMas Front/e2e/support/startSeededStackForPlaywright.js`
- `eMas Front/e2e/support/fullStackEnv.js`
- `eMas Front/e2e/support/serviceLogs.js`
- `factory-agent/` fake planner/provider/RAG test-mode files, if no suitable switch exists
- `tests/e2e/run_seed_pipeline.ps1`, only if sharing startup helpers is cleaner
- `TRACK.md`

Implementation steps:

- Add a separate Playwright project such as `chromium-seeded`.
- Start the seeded Go API using `emas/cmd/e2e_server` on an isolated port and SQLite DB.
- Start Factory Agent on an isolated port with `DATABASE_URL`, `GO_API_BASE_URL`, `OPENAPI_URL`, `JWT_REQUIRED=0`, and deterministic fake planner/model/RAG settings.
- Start Vite with `VITE_FACTORY_AGENT_BASE_URL` and `VITE_API_BASE_URL` pointing to those local services.
- Add deterministic fake planner/model/RAG behavior for the L3 foundation scenario set if it does not already exist.
- Capture Go API, Factory Agent, Vite, browser console, network, Playwright trace, screenshot, video, and environment fingerprint on failure.
- Run scenarios 31-38.
- If any scenario fails because of product or integration behavior, fix it before Phase 9. Record the defect, fix, regression test, command, and result in `TRACK.md`.
- Keep this job outside default PR CI until it is stable; use scheduled or release-branch CI first.

Acceptance criteria:

- Browser tests exercise real Vite, real Factory Agent, real Go API, and seeded data.
- No real LLM/API calls are required.
- Scenarios 31-38 pass locally.
- Phase 8 cannot be marked `Done` while any L3 foundation scenario is failing or deferred without an accepted-gap entry.
- Failures preserve Playwright traces and service logs.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
npm run test:e2e -- --project=chromium-seeded --grep "@l3-foundation"
```

Risks or unknowns:

- Service startup orchestration, ports, and teardown can be flaky if not isolated.
- A deterministic fake planner/model/RAG switch may need to be added to Factory Agent.
- L3 may expose schema drift that mocked tests cannot catch.
- Seed data must remain stable enough for browser assertions without becoming a second production database.

Rollback notes:

- Disable the `chromium-seeded` Playwright project and remove startup helpers. Keep L0-L2 mocked Playwright tests intact.

### Phase 9: L3 Hard Orchestration and Break Scenarios

Goal:

Deliberately try to break the real seeded chatbot flow with complex jobs, multi-approval chains, concurrency, state recovery, SSE ordering hazards, and service interruption while keeping model/provider behavior deterministic.

Files likely to be touched:

- `eMas Front/e2e/specs/full-stack-orchestration.spec.js`
- `eMas Front/e2e/specs/full-stack-resilience.spec.js`
- `eMas Front/e2e/specs/full-stack-sse-hard.spec.js`
- `eMas Front/e2e/support/fullStackScenarios.js`
- `eMas Front/e2e/support/fullStackEnv.js`
- `factory-agent/` deterministic planner/tool/fault injection test-mode files
- `factory-agent/tests/`, if lower-level regression tests are needed for defects found here
- `emas/internal/` or `emas/cmd/e2e_server`, if seeded API defects are found
- `TRACK.md`

Implementation steps:

- Add explicit seeded test data and fake planner fixtures for multi-step jobs and multi-approval chains.
- Add scenario tags such as `@l3-hard`, `@multi-step`, `@approval-chain`, `@sse-order`, and `@resilience`.
- Implement scenarios 39-52.
- Add fault controls for approval timeout, partial tool failure, malformed tool payload, stream drop, duplicate submit, and deleted/stale session.
- Assert both user-visible behavior and backend evidence: request counts, session IDs, tool step order, approval IDs, final state, and SSE connection lifecycle.
- When a hard scenario finds a defect, stop Phase 9 expansion until the defect is fixed or recorded as an accepted gap with owner and severity.
- Add lower-level regression coverage for each product defect where practical, then keep the Playwright scenario as the end-to-end guard.

Acceptance criteria:

- Scenarios 39-52 pass against real seeded services with deterministic providers.
- Multi-step and multi-approval scenarios prove no skipped, duplicated, or hidden execution occurs.
- Known defects found during Phase 9 are fixed before Phase 10 starts unless explicitly accepted in `TRACK.md`.
- Each fixed defect has a regression assertion and recorded verification commands.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
npm run test:e2e -- --project=chromium-seeded --grep "@l3-hard"
```

Risks or unknowns:

- Hard orchestration may require adding test-only fault injection to Factory Agent or the seeded Go API.
- Approval timeout behavior may not exist yet and may need product decisions before automation can assert it.
- Concurrency and service restart tests can be timing-sensitive; use deterministic controls and bounded waits.

Rollback notes:

- Temporarily exclude only the unstable `@l3-hard` tests from scheduled gates while keeping Phase 8 foundation and L0-L2 suites active. Do not hide product defects; record accepted gaps.

### Phase 10: L4 Production-Like Release Validation

Goal:

Replace manual release-candidate browser smoke checks with automated production-like validation across Compose or staging, including deployment paths, auth, slow networks, mobile layout, release artifacts, dependency outage behavior, and optional real-LLM connectivity.

Files likely to be touched:

- `.github/workflows/playwright-e2e.yml` or a new release validation workflow
- `eMas Front/playwright.config.js`
- `eMas Front/e2e/specs/release-validation.spec.js`
- `eMas Front/e2e/specs/release-resilience.spec.js`
- `eMas Front/e2e/support/releaseEnv.js`
- `eMas Front/e2e/support/releaseArtifacts.js`
- `docker-compose.yml`, only if test labels/health outputs are needed
- `nginx/default.conf`, only if proxy behavior needs correction
- `eMas Front/e2e/README.md`
- `TRACK.md`

Implementation steps:

- Add a `chromium-release` Playwright project that targets Compose or staging URLs instead of Vite.
- Validate `/`, `/agent`, `/api/v1`, `/health`, and `/agent/ready` through deployment paths.
- Test auth-required/static bearer behavior and confirm polling fallback when EventSource cannot attach headers.
- Add release-environment fault toggles or prechecks for Go API unavailable, Factory Agent unavailable, bad env vars, and migration/schema mismatch.
- Add latency budgets for chat-open, first progress indication, final answer, and long stream timeout.
- Add slow-network and mobile viewport projects or tagged release specs.
- Add keyboard-only flow for chat, submit, approve/reject, and close.
- Archive Playwright report, traces, screenshots, video, service logs, and environment fingerprints.
- Keep real LLM connectivity smoke opt-in with explicit env flags and structural assertions only.
- Run scenarios 53-70.
- If a release scenario fails, fix it before Phase 11. A release gate failure cannot be downgraded by adding a production synthetic check.

Acceptance criteria:

- Release validation can run against Compose or staging without manual browser steps.
- Deployment path, auth mode, proxy/CORS, slow network, mobile, dependency outage, and artifact behavior are covered.
- Controlled fake model is default; real LLM smoke is opt-in and structural.
- Scenarios 53-70 pass or have explicit accepted-gap entries with owner and rollback instruction.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
npm run test:e2e -- --project=chromium-release
```

Risks or unknowns:

- Compose/staging environment variables may differ from local defaults.
- Real LLM smoke can be flaky and must not block normal PR CI.
- Latency budgets should start generous and tighten after collecting baseline data.
- Some release failure injection may require deployment-specific support.

Rollback notes:

- Remove the release workflow/project or mark it non-blocking. L0-L3 suites remain valid. Do not proceed to production-monitoring replacement until L4 failures are fixed or accepted.

### Phase 11: L5 Production Synthetic Monitoring

Goal:

Replace post-deploy manual checks with safe, automated production/staging synthetic monitoring that catches availability, auth, latency, SSE/fallback, RAG/provider, and observability failures without mutating production data.

Files likely to be touched:

- `eMas Front/e2e/specs/production-synthetic.spec.js`
- `eMas Front/e2e/support/syntheticEnv.js`
- `eMas Front/e2e/support/syntheticReporter.js`
- `.github/workflows/production-synthetic.yml`, cron automation, or the team's monitoring runner config
- `docs/operations/chatbot_synthetic_monitoring.md`
- `TRACK.md`

Implementation steps:

- Define a dedicated read-only synthetic user or environment token.
- Add a `chromium-synthetic` Playwright project or standalone monitor command.
- Use only safe read-only prompts and health checks.
- Implement scenarios 71-79.
- Assert structural outcomes: chat opens, progress appears, final answer non-empty, optional source metadata, no backend-unavailable banner, latency within threshold.
- Emit machine-readable results for alerting and trend analysis.
- Configure alert channels, escalation notes, quiet hours if needed, and owner rotation.
- Add token expiry/revocation checks and provider outage detection.
- Store traces/screenshots only on failure with secrets redacted and retention rules.
- If a production synthetic exposes a defect, fix the defect and backfill the closest deterministic L0-L4 regression test.

Acceptance criteria:

- Synthetic monitor can run after deploy without a human opening the app.
- Monitor does not mutate production data.
- Failures alert on timeout, auth failure, backend unavailable, provider outage, SSE/fallback failure, missing final response, or latency budget breach.
- Runbook explains triage, escalation, and how to disable the monitor safely.
- Scenarios 71-79 are stable enough to alert without creating routine false alarms.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-synthetic
```

Risks or unknowns:

- Production synthetic checks need credentials, endpoint allowlisting, and alert routing.
- Real LLM/RAG outputs are nondeterministic; assertions must stay structural.
- Screenshots/traces may contain sensitive operational data and need retention/redaction rules.
- Synthetic tests cannot safely cover destructive approvals in production; those remain L3/L4 only.

Rollback notes:

- Pause the monitor or mark it non-alerting. Do not remove L0-L4 release validation. Keep any discovered defects in `TRACK.md` until fixed or accepted.

### Phase 12: Manual Testing Retirement and Governance

Goal:

Fully eliminate routine manual chatbot regression testing and define how future scenarios are added, retired, escalated, or accepted as human-only review.

Files likely to be touched:

- `PLAN.md`
- `TRACK.md`
- `eMas Front/e2e/README.md`
- `tests/e2e/README.md`
- `docs/operations/chatbot_test_governance.md`
- Existing manual baseline docs, if they need replacement notes

Implementation steps:

- Build a manual-test replacement matrix that maps every old manual chatbot check to L0-L5 automated coverage.
- Implement scenario 80 as a governance audit or checklist that blocks retirement when a manual check has no automated gate or accepted gap.
- Mark remaining manual checks as retired, human semantic review, compliance/sign-off, exploratory discovery, or emergency-only.
- Define ownership for PR E2E, seeded full-stack, hard orchestration, release validation, and synthetic monitors.
- Define scenario lifecycle rules:
  - add only for new risk,
  - remove redundant scenarios,
  - require failure artifact expectations,
  - require a regression test for every fixed defect,
  - keep production synthetic prompts read-only.
- Document required commands for PR, L3 seeded, L3 hard, release, and post-deploy validation.
- Add a quarterly scenario review checklist and accepted-gap review.

Acceptance criteria:

- No routine manual chatbot flow remains required for PR, release, or post-deploy smoke validation.
- Manual testing is limited to exploratory testing, product-quality review, compliance sign-off, emergency diagnosis, or new-risk discovery.
- `TRACK.md` records all automated replacement coverage, owners, commands, results, and accepted gaps.
- The project cannot claim manual testing is eliminated until Phases 8-11 are passing or accepted gaps are explicitly owned and the Phase 12 replacement matrix is complete.

Verification command:

```powershell
git status --short --branch
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
npm run test:e2e -- --project=chromium-seeded
npm run test:e2e -- --project=chromium-release
npm run test:e2e -- --project=chromium-synthetic
```

Risks or unknowns:

- Governance can rot if scenario owners are not explicit.
- Production synthetic monitoring cannot replace human review of nuanced answer quality.
- Some manual checks may remain for compliance or sign-off outside engineering control.

Rollback notes:

- Restore manual checklist as a release requirement while keeping automated suites active.

### Phase 13: Normal-Use Production Hardening

Goal:

Cover more realistic daily operator behavior after the core L0-L5 gates are in place, without adding model-quality evaluation to this phase.

Files likely to be touched:

- `eMas Front/e2e/specs/normal-use-hardening.spec.js`
- `eMas Front/e2e/support/normalUseScenarios.js`
- `eMas Front/e2e/support/selectors.js`
- `eMas Front/e2e/README.md`
- `TRACK.md`

Implementation steps:

- Add tagged Playwright scenarios for `@normal-use`.
- Implement scenarios 81-85.
- Reuse deterministic mocked or seeded responses depending on whether the scenario needs real services.
- Assert visible transcript state, session selection, composer state, sources/details, busy state, and stream lifecycle evidence.
- Keep memory-specific behavior out of scope until the memory feature exists.
- Fix every reproducible normal-use defect before Phase 14 or record an accepted gap with owner and target date.

Acceptance criteria:

- Scenarios 81-85 pass locally.
- Repeated open/close, reload, session restore, and multi-turn normal use do not leak stale answers, banners, timers, or streams.
- No real model call is required for the default run.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium --grep "@normal-use"
npm run test:e2e -- --project=chromium-seeded --grep "@normal-use"
```

Risks or unknowns:

- Long multi-turn UI tests can become slow; keep assertions focused on distinct state risks.
- Some session-history behavior may need stable selectors or test IDs.

Rollback notes:

- Disable the `@normal-use` tag from release gates while keeping earlier suites active. Record any deferred product defect in `TRACK.md`.

### Phase 14: Data Integrity and Side-Effect Safety

Goal:

Prove mutating chatbot workflows do exactly what the UI says they did, especially multi-step and approval-gated writes.

Files likely to be touched:

- `eMas Front/e2e/specs/data-integrity.spec.js`
- `eMas Front/e2e/support/dataIntegrityScenarios.js`
- `eMas Front/e2e/support/fullStackScenarios.js`
- `factory-agent/` test-mode planner/tool fixtures for write scenarios
- `emas/cmd/e2e_server` or seeded data helpers, if new write fixtures are needed
- `TRACK.md`

Implementation steps:

- Add deterministic seeded fixtures for mutating job-priority workflows.
- Implement scenarios 86-90.
- For scenario 86, define original-state semantics explicitly:
  - original high-priority jobs become low,
  - original low-priority jobs become medium,
  - original medium-priority jobs remain unchanged.
- Require separate approval evidence for each write set when a workflow mutates multiple groups.
- Assert DB state, audit log, SSE timeline, approval ids, and visible final summary agree.
- Treat any mismatch between UI claims and persisted state as a blocking defect.

Acceptance criteria:

- Scenarios 86-90 pass against seeded full-stack services.
- Mutating tests prove exact final DB state, not just visible final text.
- Approval replay, double-click, and stale approval cases do not duplicate or delay writes.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity"
```

Risks or unknowns:

- Seeded API helpers may need explicit audit/state inspection endpoints for tests.
- The product may need a decision about original-state versus current-state semantics for cascading updates.

Rollback notes:

- Keep mutating scenarios opt-in until the seed database can be reset reliably. Do not run destructive variants against production.

### Phase 15: Reliability, Scale, and Soak Hardening

Goal:

Find flake, resource leaks, slow-path failures, and concurrency issues that do not appear in single-run happy paths.

Files likely to be touched:

- `eMas Front/e2e/specs/reliability-soak.spec.js`
- `eMas Front/e2e/support/soakRunner.js`
- `eMas Front/e2e/support/resourceMetrics.js`
- `.github/workflows/playwright-e2e.yml` or scheduled reliability workflow
- `TRACK.md`

Implementation steps:

- Add scenarios 91-95.
- Run concurrent browser contexts only for read-only or reset-safe flows.
- Add service log and process cleanup checks for leaked ports, child processes, and orphan streams.
- Track timing for chat open, first progress, final completion, and teardown.
- Run soak/repeat tests on schedule or release branches, not default PR CI at first.

Acceptance criteria:

- Scenarios 91-95 pass in an isolated reliability job.
- Repeated runs leave no orphan local services, ports, or test data.
- Slow-path failures produce clear artifacts instead of silent timeouts.

Verification command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium --grep "@reliability"
npm run test:e2e -- --project=chromium-seeded --grep "@reliability"
```

Risks or unknowns:

- Soak tests can be expensive; keep them scheduled or opt-in until stable.
- Resource metrics may differ between Windows local runs and Linux CI.

Rollback notes:

- Mark the scheduled reliability job non-blocking while preserving artifacts and defects in `TRACK.md`.

### Phase 16: Security, Privacy, and Abuse Hardening

Goal:

Prove normal browser and API misuse cannot expose other sessions, bypass auth, leak secrets into artifacts, or execute unsafe rendered content.

Files likely to be touched:

- `eMas Front/e2e/specs/security-privacy.spec.js`
- `eMas Front/e2e/support/securityScenarios.js`
- `eMas Front/e2e/support/artifactRedaction.js`
- `factory-agent/tests/`, if lower-level auth/session tests are needed
- `emas/internal/`, if API auth/session defects are found
- `TRACK.md`

Implementation steps:

- Implement scenarios 96-100.
- Use deterministic fake providers for unsafe-action/tool-allowlist checks.
- Tamper with local storage, session ids, auth headers, EventSource URLs, and oversized pasted content in controlled test environments.
- Assert safe visible diagnostics and denied backend responses.
- Scan failure artifacts for configured secret/token patterns before storing or uploading them.

Acceptance criteria:

- Scenarios 96-100 pass locally or in an opt-in security/privacy job.
- Unauthorized access does not leak another session's transcript, snapshot, source metadata, token, or operational data.
- Traces, screenshots, logs, and reports are redacted enough for CI artifact retention.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium --grep "@security|@privacy"
npm run test:e2e -- --project=chromium-release --grep "@security|@privacy"
```

Risks or unknowns:

- Some auth cases may require test-only tokens or a dedicated auth test harness.
- Artifact scanning must avoid printing secrets while reporting failures.

Rollback notes:

- Keep the job opt-in until credentials and artifact redaction rules are stable. Do not upload unredacted failure artifacts.

### Phase 17: Production-Grade Operational Readiness

Goal:

Create the operational gate that proves the chatbot can be safely monitored, disabled, rolled back, and recovered before the final prompt-robustness signoff.

Files likely to be touched:

- `eMas Front/e2e/specs/operational-readiness.spec.js`
- `eMas Front/e2e/support/operationalGate.js`
- `.github/workflows/playwright-e2e.yml`
- `.github/workflows/production-synthetic.yml` or the actual monitor runner config
- `docs/operations/chatbot_release_runbook.md`
- `docs/operations/chatbot_synthetic_monitoring.md`
- `TRACK.md`

Implementation steps:

- Implement scenarios 101-105.
- Add a single production-grade gate command or workflow that orchestrates the required PR, seeded, hard, release, synthetic, security/privacy, and reliability checks.
- Validate alert ownership, severity, runbook links, rollback URL support, emergency disable path, and clean environment recreation.
- Define severity thresholds:
  - critical: blocks release or requires rollback,
  - high: blocks operational or production-grade signoff,
  - medium: accepted only with owner and target date,
  - low: tracked but not release blocking.
- Require all accepted gaps to be reviewed before signoff.

Acceptance criteria:

- Scenarios 101-105 pass.
- The production-grade gate can be run by a future agent/operator without rediscovering setup.
- No critical or high accepted gaps remain open.
- `TRACK.md` contains the final gate result, owners, commands, failures, fixes, and any remaining accepted gaps.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
npm run test:e2e -- --project=chromium-seeded
npm run test:e2e -- --project=chromium-release
npm run test:e2e -- --project=chromium-synthetic
```

Risks or unknowns:

- The operational gate may need environment-specific workflow secrets and monitor runner configuration.
- Some operational readiness steps depend on team-owned alerting and deployment systems outside this repo.

Rollback notes:

- Restore manual release and post-deploy smoke as a temporary requirement until the failed operational gate is fixed.

### Phase 18: Intent, Entity, and RAG Route Robustness

Goal:

Close the gap where deterministic workflow tests pass but normal operator wording still fails because entity extraction, intent routing, clarification logic, or RAG/source selection is too narrow.

Files likely to be touched:

- `factory-agent/tests/` parser, planner, routing, or RAG route tests
- `factory-agent/factory_agent/` entity extraction, routing, or seeded fake-provider code if defects are found
- `eMas Front/e2e/specs/intent-entity-robustness.spec.js`
- `eMas Front/e2e/support/intentEntityScenarios.js`
- `eMas Front/e2e/support/fullStackScenarios.js`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `docs/qa/manual_prompt_regression_bank.md`
- `TRACK.md`

Implementation steps:

- Add a manual prompt regression bank seeded with real misses, starting with `What LOTO procedure applies before working on M-CNC-01?`.
- Implement scenarios 106-115.
- Add parser/unit coverage for machine IDs, job IDs, punctuation, mixed case, markdown, quotes, and newlines.
- Add seeded fake-provider routing checks that assert selected intent, extracted entities, selected tool/RAG route, clarification behavior, and final terminal state.
- Add a small browser smoke that verifies the user-visible behavior for the most important prompt classes.
- For LOTO/RAG prompts, assert that present machine IDs are not re-requested, missing machine IDs do trigger clarification, and no-source cases are honest `not found` answers rather than generic backend attention.
- Convert every future manually discovered prompt miss into this bank before closing the defect.
- Do not add Promptfoo or broad model-quality evaluation in this phase.

Acceptance criteria:

- Scenarios 106-115 pass.
- The specific prompt `What LOTO procedure applies before working on M-CNC-01?` no longer asks for a machine ID and reaches the correct LOTO/RAG route.
- Prompt variants prove entity extraction is robust to case, punctuation, concise wording, and embedded formatting.
- Clarification behavior is correct for both missing and present required entities.
- Every fixed prompt miss has regression coverage at the lowest useful layer plus a browser/seeded check when the behavior is user-visible.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium --grep "@intent-entity"
npm run test:e2e -- --project=chromium-seeded --grep "@intent-entity|@rag-route"
```

Risks or unknowns:

- Some intent/entity fixes may belong in Factory Agent parser/planner code rather than frontend E2E.
- Real LLM wording can still vary; this phase proves deterministic route robustness, not broad semantic quality.
- Prompt bank growth must avoid redundant phrasing-only tests unless they expose a distinct parser/routing risk.

Rollback notes:

- Keep Phase 18 opt-in until parser/routing behavior is stable. If a prompt class fails, keep the failing prompt in the regression bank and record the accepted gap until fixed.

### Phase 19: Prompt and Workflow Regression Expansion

Goal:

Turn manually discovered prompt and workflow misses into a permanent deterministic regression program, so future fixes are not limited to one exact phrase or one exact cascade mutation.

Files likely to be touched:

- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `docs/qa/manual_prompt_regression_bank.md`
- `factory-agent/tests/` parser, route-selection, and workflow tests
- `factory-agent/factory_agent/testing_seeded_adapters.py`
- `eMas Front/e2e/specs/prompt-workflow-regression.spec.js`
- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/support/promptRegressionScenarios.js`
- `eMas Front/e2e/support/dataIntegrityScenarios.js`
- `TRACK.md`

Implementation steps:

- Implement scenarios 116-125.
- Create or extend a regression-bank file with schema fields for prompt, observed failure, expected behavior, owner, severity, test layer, and browser coverage.
- Add LOTO wording variants for the exact M-CNC-01 failure class.
- Add entity extraction variants for IDs inside punctuation, lowercase, markdown, quotes, parentheses, and newlines.
- Add route-selection assertions for LOTO/RAG, machine status, job listing, priority mutation, approval, and cancel intents.
- Add a priority cascade matrix beyond Scenario 86:
  - high -> low, original low -> medium,
  - medium -> high, original high -> medium,
  - low -> high, original high -> low,
  - high -> medium, original medium -> low.
- For every two-write-set mutation, assert the sequence:
  - approval 1 visible,
  - approve approval 1,
  - step 1 applied,
  - approval 2 visible,
  - approve approval 2,
  - step 2 applied,
  - only then final completion.
- Assert original-state semantics for all cascade/swap mutations unless a test explicitly names current-state semantics.
- Add a targeted browser diagnostic check so successful routed prompts do not show generic `Factory Agent needs attention`.
- Keep Promptfoo and broad real-LLM evaluation out of this phase.

Acceptance criteria:

- Scenarios 116-125 pass.
- The regression bank contains every manual miss discussed in this thread and at least one deterministic test mapping for each.
- The `medium -> high, original high -> medium` cascade shows two approvals before completion and exact final DB/audit/SSE/UI agreement.
- Route-selection tests prove prompts fail only for real missing information, not parser or route misses.
- Future manual failures have a documented triage path and cannot be closed without a regression-bank entry or accepted gap.

Verification command:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium --grep "@prompt-regression"
npm run test:e2e -- --project=chromium-seeded --grep "@prompt-regression|@data-integrity"
```

Risks or unknowns:

- The regression bank can become noisy if it stores redundant wording variants without distinct parser, route, or workflow risk.
- Cascade mutations need resettable seeded data and must never run against production.
- Some prompt misses may need product semantics decisions before they can be automated honestly.

Rollback notes:

- Keep Phase 19 opt-in until the bank and cascade matrix are stable. If a regression bank item fails, keep it listed with owner, severity, and accepted-gap status instead of deleting it.

### Phase 20: Real LangGraph Approval-Chain Regression

Goal:

Close the seeded-adapter blind spot by proving the real LangGraph planner/resume path, without `SeededPlaywrightPlanner`, continues from approval 1 to approval 2 for multi-step mutating prompts.

Files likely to be touched:

- `factory-agent/tests/test_phase5_final_validator.py`
- `factory-agent/factory_agent/graph/nodes/validate.py`
- `factory-agent/factory_agent/graph/nodes/tool_pipeline.py`
- `TRACK.md`

Implementation steps:

- Add scenario 126 as a backend LangGraph regression for `change all medium priority job to high then change all high priority job to medium`.
- Disable real LLM calls in the test and fail if the planner model is invoked.
- Use fake deterministic HTTP rows for original medium and original high priorities.
- Assert approval 1 stages original medium -> high.
- Approve approval 1 and assert `resume_after_approval` raises approval 2 instead of completing.
- Assert approval 2 stages original high -> medium.
- Approve approval 2 and assert completion only after the second commit.
- Fix the graph commit-success route so successful approved bundles clear staged writes, mark the current intent complete, and continue planning when another active intent remains.

Acceptance criteria:

- The regression fails before the graph fix and passes after it.
- No seeded adapter, browser fixture, or real LLM path is used by the backend regression.
- The exact manual prompt requires two distinct approvals in the real LangGraph path.
- Nearby graph planner and approval-resume tests still pass.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_phase5_final_validator.py -q
python -m pytest tests/test_planner_service_phase6.py -q
python -m pytest tests/test_planner_phase3.py -q
```

Risks or unknowns:

- This backend regression proves LangGraph mechanics, not final browser rendering.
- Production data semantics still need operator/product confirmation for original-state vs current-state behavior across every mutation family.
- A future non-seeded browser project may be needed if UI behavior diverges from the backend approval-chain contract.

Rollback notes:

- Revert the commit-success continuation route if it causes unrelated graph-native writes to loop, then keep scenario 126 failing/open as a blocker instead of relying on seeded Playwright coverage.

### Phase 21: Semantic Routing Contract and Anti-Overfitting

Goal:

Stop adding hardcoded prompt fixes for each new LOTO or document wording. Promote the existing intent vocabulary into an explicit semantic routing contract that can classify broad operator wording without confusing document/RAG guidance, live operational reads, mutations, approvals, cancellation, and unsafe actions.

Important distinction:

The project already has an intent vocabulary. This phase does not start over. It extends the existing `kind`, `action`, `entity`, and explicit constraint extraction with a stable semantic frame:

```json
{
  "domain_intent": "loto_procedure",
  "action": "read",
  "entity": "machine",
  "entities": {
    "machine_id": "M-CNC-01"
  },
  "missing_required_entities": [],
  "route": "rag.loto_procedure",
  "confidence": 0.92,
  "clarification_reason": null,
  "negative_route_assertions": ["tool.read.machine_status"]
}
```

Core routing rule:

Do not route purely because a word appears in a document. Route based on the user’s semantic frame:

- document/procedure/policy intent,
- live operational state intent,
- mutation intent,
- approval/cancel intent,
- extracted and normalized entities,
- required/missing entities,
- ambiguity/confidence,
- allowed route/tool/RAG source.

Required route families:

| Route family | Examples | Expected behavior |
|---|---|---|
| `rag.loto_procedure` | `LOTO for M-CNC-01`, `lockout tagout before servicing m-cnc-01` | Requires `machine_id`; returns source-backed procedure; never asks again when ID is present. |
| `rag.procedure` / `rag.safety_policy` | `What SOP applies before cleaning Line 2?`, `What does the PPE policy say?` | Routes to document/RAG only when the user asks for guidance, policy, procedure, standard, or source-backed instructions. |
| `tool.read.machine_status` | `status of M-CNC-01` | Uses live operational status tool, not RAG. |
| `tool.read.jobs` | `show delayed high-priority jobs` | Uses job query tooling with extracted filters. |
| `tool.write.jobs` plus approval | `change high priority jobs to low` | Requires approval and state/audit evidence. |
| `approval_action` | `approve the second request` | Resolves active approval context safely. |
| `cancel_run` | `cancel the current run` | Cancels only explicit cancel/stop commands. |
| `unsupported_dangerous_action` | `delete production jobs without approval` | Refuses or blocks safely; no mutation. |

Implementation steps:

- Inspect `factory-agent/factory_agent/planning/intent.py`, tool selection, validation, and seeded adapters.
- Add or formalize a semantic frame with `domain_intent`, `route`, `missing_required_entities`, `normalized_entities`, `confidence`, and `negative_route_assertions`.
- Refactor LOTO-specific helpers into one document/RAG route family instead of adding more phrase-specific branches.
- Add route-family matrix/property tests for document/RAG, machine status, job query, job mutation, approval, cancel, and dangerous action prompts.
- Keep most wording variants at parser/route level. Add browser tests only when UI/source chrome/approval cards/stale text can fail differently.
- Convert future manual prompt misses into route-family gaps before adding a new one-off test.

Acceptance criteria:

- Broad procedure/document wording routes correctly without hardcoded prompt branches.
- Machine status and document/procedure questions are separated even when both mention the same machine.
- Missing required entities clarify honestly; present entities are normalized and not re-requested.
- No seeded fixture ID is invented as a fallback.
- Dangerous or unsupported actions cannot bypass approval or mutation safeguards.
- The test strategy reduces prompt whack-a-mole by proving route families, not isolated phrases.

Verification command:

```powershell
Set-Location "factory-agent"
python -m pytest tests/test_intent_splitter.py tests/test_phase19_prompt_workflow_regression.py -q
Set-Location "..\eMas Front"
npm test
npm run test:e2e -- --project=chromium-seeded --grep "semantic-route|SO-021|SO-022|SO-023|SO-025|SO-026|SO-044"
```

Risks or unknowns:

- The current vocab may be too coarse for some route families and may need product naming decisions for `domain_intent`.
- Real LLM behavior can still vary; this phase proves deterministic routing contracts, not free-form answer quality.
- Overfitting can move into parser rules if every new phrase becomes a special case.

Rollback notes:

- Keep existing helpers until the semantic-frame contract has equivalent tests.
- If the refactor breaks a route family, keep the failing oracle open rather than adding another hardcoded branch.

## Recommended Current Implementation Step

Phases 8-20 are complete in `TRACK.md`. Phase 21 has now promoted the existing intent vocabulary into a semantic routing contract and proves route families, not isolated LOTO phrases.

1. Keep existing route helpers and SO/browser coverage intact while the semantic frame is introduced.
2. Add parser/route matrix coverage first for route families.
3. Add browser coverage only for route families where visible UI, source chrome, approval cards, or stale text can diverge from backend route evidence.
4. Keep the default PR suite on the existing mocked `chromium` project.

Phase 21 implementation record:

- Added `SemanticFrame` with route, domain intent, normalized entities, missing required entities, clarification reason, confidence, negative route assertions, and approval requirement metadata.
- Refactored LOTO helpers so they delegate to the semantic document/RAG route family.
- Added parser/route matrices for `rag.loto_procedure`, `rag.procedure`, `rag.safety_policy`, `tool.read.machine_status`, `tool.read.jobs`, `tool.write.jobs`, `approval_action`, `cancel_run`, and `unsupported_dangerous_action`.
- Kept browser coverage canonical and focused on existing SO cases where UI/source/approval/stale-state evidence can diverge.
- Verification passed: backend semantic route contract `63 passed`, backward compatibility LOTO/knowledge checks `20 passed`, frontend unit/component `64 passed`, focused seeded Chromium route/UI proof `4 passed`.

## Original First Implementation Step

Start with Phase 1:

1. Add `@playwright/test` and Playwright scripts under `eMas Front`.
2. Add a minimal mock Factory Agent server.
3. Add one browser test that opens the app and chat modal.
4. Add a stable accessible selector to the floating chat button if needed.

This creates the smallest real-browser signal without touching the backend, Docker, LLM, or old pipeline.
