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
| 6 | CI integration | Done | Added root GitHub Actions workflow for deterministic frontend Playwright chatbot E2E with Chromium-only install, frontend unit tests, Playwright run, and failure artifacts. |
| 7 | Cleanup and replacement of old pipeline | Done | Marked In Progress during implementation; completed with replacement mapping, preserved seed pipeline guidance, smoke-script decision, CI scope, commands, and final documentation updates. |
| 8 | L3 seeded full-stack foundation | Done | Completed with `chromium-seeded`, isolated seeded Go API + Factory Agent + Vite startup, deterministic fake planner/RAG adapters, L3 scenarios 31-38, failure artifacts, and local verification. |
| 9 | L3 hard orchestration and break scenarios | Done | Completed with deterministic seeded L3 hard scenarios 39-52, product fixes for approval resume, partial failure, stale session recovery, duplicate submit, and SSE reconnect/drop behavior. |
| 10 | L4 production-like release validation | Done | Completed with opt-in `chromium-release`, production-built frontend behind nginx-style `/`, `/agent`, and `/api/v1` proxy paths, static-bearer polling fallback, CORS/preflight checks, latency budgets, release artifacts, outage/precheck drills, mobile/keyboard/slow-network/rollback/cache/long-stream coverage, and deterministic seeded providers by default. |
| 11 | L5 production synthetic monitoring | Done | Completed with opt-in `chromium-synthetic`, safe read-only canary prompts, live-mode env/token guardrails, machine-readable redacted results, alert classification, auth/provider fault drills, latency burn-rate reporting, and failure-only artifact policy. |
| 12 | Manual testing retirement and governance | Done | Completed with replacement matrix, scenario 80 governance audit, owner model, lifecycle rules, quarterly review, accepted gaps, preserved seed-pipeline guidance, and full L0-L5 verification. |
| 13 | Normal-use production hardening | Done | Completed with mocked scenarios 81-85 plus opt-in seeded reload/source coverage for scenario 83. |
| 14 | Data integrity and side-effect safety | Done | Completed with opt-in `@data-integrity` seeded scenarios 86-90, exact DB/audit/UI/SSE/final-summary checks, multi-approval write-set evidence, and approval idempotency/staleness guards. |
| 15 | Reliability, scale, and soak hardening | Done | Completed with opt-in `@reliability` mocked scenarios 91-95, seeded stream/large-result cross-checks, scheduled/dispatch soak workflow, isolated child smoke ports, timeout recovery, and cleanup artifacts. |
| 16 | Security, privacy, and abuse hardening | Done | Completed with tagged `@security`/`@privacy` mocked Chromium scenarios 96-100, opt-in release cross-checks for scenarios 96-98, owner isolation, auth-denial diagnostics, artifact redaction, oversized/unsafe rendering checks, and tool allowlist/approval-gate coverage. |
| 17 | Production-grade operational readiness | Done | Completed with opt-in `@operational` scenarios 101-105, severity rules, alert owner/runbook validation, rollback URL support, emergency disable diagnostics, clean environment recreation plan, operator gate command/workflow, and full PR/seeded/hard/release/synthetic/security/privacy/reliability matrix evidence. |
| 18 | Intent, entity, and RAG route robustness | Done | Completed with a manual prompt regression bank, parser matrix, deterministic LOTO/RAG routing, clarification-boundary checks, mocked browser smoke, and opt-in seeded fake-provider/browser route gates. |
| 19 | Prompt and workflow regression expansion | Done | Completed with Phase 19 regression-bank schema/triage, LOTO wording and ID matrices, route assertions, four-variant cascade matrix, two-approval/original-state invariants, targeted browser diagnostics, and passing mocked/seeded gates. |
| 20 | Real LangGraph approval-chain regression | Done | Completed with a non-seeded backend LangGraph regression for the exact medium-to-high then high-to-medium prompt, plus a graph commit-success continuation fix so approval 2 is raised after approval 1 commits. |

## Long-Term Scope Strategy

| Stage | Status | Scope | Notes |
|---|---|---|---|
| L0 Browser smoke | Done | App opens, chat opens, composer usable. | Covered by Phase 1 Chromium baseline specs. |
| L1 Deterministic mocked chat | In Progress | REST-backed mocked session/message/plan/execute/snapshot flows. | Scenario 5 happy path is covered; broader L1 scenarios remain for later phases. |
| L2 Deterministic mocked SSE | In Progress | Real `text/event-stream` from mock server for notification/activity scenarios. | Phase 4 covers notification/activity success paths; Phase 5 adds malformed SSE, stream drop fallback, non-terminal, cancel, and modal disconnect coverage. Reconnect/static bearer remain later expansion items. |
| L3 Seeded full-stack foundation | Done | Vite plus seeded Go API and Factory Agent fake planner/model/RAG provider. | Phase 8 completed as opt-in L3 gate; not default PR requirement. |
| L3 Hard orchestration | Done | Multi-step, multi-approval, concurrency, state recovery, SSE ordering, and service interruption against seeded services. | Phase 9 completed as opt-in `chromium-seeded --grep "@l3-hard"` gate. |
| L4 Production-like release validation | Done | Compose/staging-style release validation with nginx paths, auth mode, polling fallback, slow network, mobile, and release artifacts. | Phase 10 completed as opt-in `chromium-release`; not default PR CI. |
| L5 Production synthetic monitoring | Done | Safe read-only canary prompts, provider signals, alerting, health, and latency checks. | Phase 11 completed as opt-in `chromium-synthetic`; not default PR CI. |
| Production-grade hardening | Done | Normal-use, data integrity, reliability, security/privacy, operational readiness, intent/entity/RAG route robustness, prompt/workflow regression expansion, and real LangGraph approval-chain coverage. | Phases 13-20 are complete with no critical/high accepted gaps. The default PR suite remains deterministic mocked Chromium only; seeded, release, and synthetic projects remain opt-in. |

## Phase Gate Rule

- [ ] Phase 8 onward: if a reproducible defect is found, mark the phase `Blocked` or `In Progress`, fix the defect, add a regression assertion, rerun the current phase command plus `npm test` and mocked `chromium`, and record results before starting the next phase.
- [ ] Any deferred failure must be recorded as an accepted gap with owner, severity, reason, target phase/date, risk, and temporary manual workaround.
- [ ] Do not mark Phase 8 onward `Done` while the phase verification command is failing.
- [ ] Do not claim manual testing is eliminated until the replacement matrix maps every old manual check to automation or an accepted gap.
- [ ] Do not claim production-grade hardening until Phase 20 passes with no critical/high accepted gaps.

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

## L3-L5 and Production-Grade Scenario Expansion

These scenarios extend the original 30 into seeded full-stack, failure-seeking orchestration, production-like release validation, production synthetic monitoring, governance, and production-grade hardening. Scenarios 39-52 and 86-100 are intentionally hard and should block phase promotion when they reveal real defects.

| # | Scenario | Status | Layer |
|---|---|---|---|
| 31 | Seeded full-stack opens chat through Vite and creates a Factory Agent session. | Done | L3 foundation |
| 32 | Seeded full-stack machine status prompt completes against seeded Go API data. | Done | L3 foundation |
| 33 | Seeded full-stack low-priority jobs prompt renders structured results. | Done | L3 foundation |
| 34 | Seeded full-stack RAG/LOTO prompt renders answer and sources using controlled fake RAG/provider output. | Done | L3 foundation |
| 35 | Seeded full-stack approval-required flow renders pending approval from real Factory Agent snapshot. | Done | L3 foundation |
| 36 | Seeded full-stack approval approve resumes and reaches completed state with controlled provider. | Done | L3 foundation |
| 37 | Seeded full-stack cancel during execution returns to idle/cancelled state. | Done | L3 foundation |
| 38 | Seeded full-stack notification/activity SSE opens and reaches final snapshot. | Done | L3 foundation |
| 39 | Multi-step job runs at least four ordered steps: plan, read seeded data, apply business rule, summarize. | Done | L3 hard |
| 40 | Multi-approval chain requires two approvals before final execution completes. | Done | L3 hard |
| 41 | Multi-approval chain rejects the second approval and stops without running later steps. | Done | L3 hard |
| 42 | Approval timeout leaves the job safe, visible, and non-terminal without hidden continuation. | Done | L3 hard |
| 43 | Multi-step partial failure succeeds step 1, fails step 2, and never runs step 3. | Done | L3 hard |
| 44 | Tool payload/schema mismatch returns a visible safe error instead of crashing the chat panel. | Done | L3 hard |
| 45 | Duplicate submit or double-click sends only one user turn and one execute request. | Done | L3 hard |
| 46 | Stale local storage points to a deleted session and the UI recovers to a new safe state. | Done | L3 hard |
| 47 | Out-of-order or duplicate SSE events do not regress the visible phase or duplicate activity rows. | Done | L3 hard |
| 48 | EventSource reconnect uses `Last-Event-ID` and does not replay already-rendered steps. | Done | L3 hard |
| 49 | Large structured result renders without freezing, overlapping, or losing final completion state. | Done | L3 hard |
| 50 | Two browser contexts run different sessions at the same time without cross-session leakage. | Done | L3 hard |
| 51 | Factory Agent restarts or stream drops mid-run and the UI recovers by polling or safe failure. | Done | L3 hard |
| 52 | RAG answer has no sources or an unavailable source and the UI shows an honest fallback. | Done | L3 hard |
| 53 | Docker/nginx release path opens app at `/` and routes Factory Agent through `/agent`. | Done | L4 |
| 54 | Docker/nginx release path routes Go API through `/api/v1`. | Done | L4 |
| 55 | Production-like static bearer or auth-required mode disables EventSource and uses polling fallback. | Done | L4 |
| 56 | Production-like CORS preflight and browser requests succeed for Factory Agent and Go API. | Done | L4 |
| 57 | Release validation intentionally fails one controlled test and archives trace/video/report/log artifacts. | Done | L4 |
| 58 | Release validation checks chat-open, first progress, and final answer latency budgets. | Done | L4 |
| 59 | Controlled real-LLM connectivity smoke runs only when explicitly enabled. | Done | L4 |
| 60 | Go API unavailable during a chatbot job shows degraded/error state and no fake completion. | Done | L4 |
| 61 | Factory Agent unavailable at page load keeps chat usable enough to show diagnostics. | Done | L4 |
| 62 | Missing or bad frontend API env var fails fast with a visible diagnostic in release validation. | Done | L4 |
| 63 | Database migration or schema mismatch fails the release gate before browser tests claim success. | Done | L4 |
| 64 | Browser refresh during an active job restores or safely abandons the run without duplicate execution. | Done | L4 |
| 65 | Slow network profile still shows first progress before the agreed threshold or fails with evidence. | Done | L4 |
| 66 | Mobile viewport opens chat, submits prompt, handles approval card, and avoids text overlap. | Done | L4 |
| 67 | Keyboard-only flow can open chat, submit, approve/reject, and close modal. | Done | L4 |
| 68 | Release rollback candidate can run the same smoke command against previous build URL. | Done | L4 |
| 69 | Browser cache/version mismatch does not load stale frontend against incompatible backend schema. | Done | L4 |
| 70 | Long-running stream stays within memory/log limits and still reaches a terminal state or timeout. | Done | L4 |
| 71 | Production synthetic health check opens chat and confirms composer availability. | Done | L5 |
| 72 | Production synthetic read-only machine status canary completes with non-empty final response. | Done | L5 |
| 73 | Production synthetic RAG/source canary returns structurally valid answer and optional source metadata. | Done | L5 |
| 74 | Production synthetic SSE-or-polling canary observes progress then completion. | Done | L5 |
| 75 | Production synthetic alerting fires on timeout, backend unavailable, auth failure, or missing final answer. | Done | L5 |
| 76 | Synthetic auth token expiry or revocation fails clearly and alerts the owner. | Done | L5 |
| 77 | Synthetic provider outage canary detects model/RAG dependency failure without mutating data. | Done | L5 |
| 78 | Synthetic latency burn-rate check reports degraded performance before hard outage. | Done | L5 |
| 79 | Production trace/screenshot redaction prevents leaking sensitive operational data on failure. | Done | L5 |
| 80 | Manual replacement matrix audit confirms every old manual chatbot check has an automated gate or accepted gap. | Done | Governance |
| 81 | Ten-turn normal operator chat mixes machine status, jobs, LOTO/RAG, and follow-up questions without stale answers or lost UI state. | Done | Production hardening |
| 82 | Session list with many historical sessions loads, selects, and restores the correct transcript. | Done | Production hardening |
| 83 | Browser reload after a completed run restores final answer, sources/details, and non-busy composer state. | Done | Production hardening |
| 84 | User edits a draft, switches mode, and submits once with the final text and mode. | Done | Production hardening |
| 85 | Repeatedly open/close the chat across completed, failed, and cancelled sessions without leaked streams, timers, or stale banners. | Done | Production hardening |
| 86 | Cascading priority update changes all original high-priority jobs to low, then all original low-priority jobs to medium, with separate approvals and exact final DB state. | Done | Data integrity |
| 87 | Bulk update partial failure records exact per-row outcomes and does not claim all jobs succeeded. | Done | Data integrity |
| 88 | Approval double-click, refresh, or replay does not apply the same mutation twice. | Done | Data integrity |
| 89 | Expired or stale approval cannot mutate data after the session changes state. | Done | Data integrity |
| 90 | Audit log, DB state, SSE timeline, and final assistant summary agree for every mutating job. | Done | Data integrity |
| 91 | Ten concurrent read-only browser sessions complete without cross-session leakage. | Done | Reliability |
| 92 | Long stream with many activity events reaches terminal state without duplicate rows, high memory, or stuck busy UI. | Done | Reliability |
| 93 | Large structured result and many sources render with stable layout and usable controls. | Done | Reliability |
| 94 | Slow API/tool response shows progress, respects timeout, and preserves retry/cancel controls. | Done | Reliability |
| 95 | Repeated soak run completes the core mocked, seeded, and release smoke suites without leaked ports or orphan processes. | Done | Reliability |
| 96 | Tampered local storage or session id cannot expose another user's session. | Done | Security/privacy |
| 97 | Unauthorized REST, polling, and EventSource access are denied with safe visible diagnostics. | Done | Security/privacy |
| 98 | Logs, traces, screenshots, and reports redact tokens, secrets, and sensitive operational fields. | Done | Security/privacy |
| 99 | Very large pasted input and unsafe markdown render safely without script execution or layout collapse. | Done | Security/privacy |
| 100 | Tool allowlist and approval gates block requests that try to perform unsupported or unsafe actions. | Done | Security/privacy |
| 101 | Synthetic failure creates the expected alert, owner, severity, and runbook link. | Done | Operational readiness |
| 102 | Rollback validation command passes against the previous known-good build URL. | Done | Operational readiness |
| 103 | Chatbot feature flag or emergency disable path leaves the rest of the app usable with a clear diagnostic. | Done | Operational readiness |
| 104 | Recreated environment with seeded DB and synthetic account can run the release/synthetic gates from scratch. | Done | Operational readiness |
| 105 | Production-grade gate matrix runs PR, seeded, hard, release, synthetic, security/privacy, and reliability checks with no critical failures. | Done | Operational readiness |
| 106 | Natural LOTO query with explicit machine ID, `What LOTO procedure applies before working on M-CNC-01?`, routes to LOTO/RAG without asking for the machine again. | Done | Intent/entity robustness |
| 107 | LOTO prompt variants with punctuation, lowercase ID, missing question mark, and short phrasing all extract `M-CNC-01`. | Done | Intent/entity robustness |
| 108 | Machine/job/status prompt variants using synonyms like equipment, asset, work order, task, urgent, overdue, and priority map to the correct tools. | Done | Intent/entity robustness |
| 109 | Clarification boundary: missing machine ID asks a clarifying question, but present machine ID never asks for the same ID again. | Done | Intent/entity robustness |
| 110 | Multi-entity prompt with machine ID plus job ID chooses the correct primary route and does not drop either entity. | Done | Intent/entity robustness |
| 111 | RAG/LOTO route returns an honest not-found response when the machine exists but no LOTO source exists, without generic backend attention. | Done | Intent/entity robustness |
| 112 | RAG source relevance check verifies returned source metadata is tied to the requested machine/procedure. | Done | Intent/entity robustness |
| 113 | Intent/entity parser unit matrix covers IDs embedded in punctuation, newlines, markdown, quotes, and mixed case. | Done | Intent/entity robustness |
| 114 | Manual-regression query bank converts every newly found manual prompt miss into deterministic unit, seeded, or browser coverage. | Done | Intent/entity robustness |
| 115 | Prompt robustness gate runs the query bank through seeded fake-provider routing and fails on any unexpected clarification, wrong tool, or missing final state. | Done | Intent/entity robustness |
| 116 | LOTO wording matrix runs multiple natural variants of the same M-CNC-01 LOTO request and expects the same LOTO/RAG route. | Done | Prompt/workflow regression expansion |
| 117 | Machine and job ID extraction matrix covers punctuation, lowercase, quotes, parentheses, markdown, and newline-separated IDs. | Done | Prompt/workflow regression expansion |
| 118 | Route-selection matrix asserts selected intent/tool evidence for LOTO, machine status, job listing, priority mutation, approval, and cancel prompts. | Done | Prompt/workflow regression expansion |
| 119 | Priority cascade matrix covers high-to-low then low-to-medium, medium-to-high then high-to-medium, low-to-high then high-to-low, and high-to-medium then medium-to-low. | Done | Prompt/workflow regression expansion |
| 120 | Two-write-set approval invariant proves every two-step mutation shows approval 1, executes step 1, shows approval 2, executes step 2, then completes. | Done | Prompt/workflow regression expansion |
| 121 | Original-state mutation invariant proves second-step target groups are based on the original snapshot unless the user explicitly requests current-state behavior. | Done | Prompt/workflow regression expansion |
| 122 | Regression bank schema requires source prompt, observed failure, expected behavior, owner, severity, lowest test layer, and browser coverage flag. | Done | Prompt/workflow regression expansion |
| 123 | Manual failure triage rule maps every new manual miss to parser, route, seeded workflow, browser, or accepted-gap coverage before closure. | Done | Prompt/workflow regression expansion |
| 124 | Browser diagnostics regression check proves successful routed prompts do not show generic `Factory Agent needs attention`, while true unknowns do. | Done | Prompt/workflow regression expansion |
| 125 | Phase 19 regression gate runs the prompt/workflow bank through unit, seeded, and targeted browser checks with a coverage summary. | Done | Prompt/workflow regression expansion |
| 126 | Real LangGraph approval-chain regression proves the exact medium-to-high then high-to-medium prompt raises approval 2 after approval 1 commits without `SeededPlaywrightPlanner`. | Done | Real LangGraph approval-chain regression |

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

- [x] Identify CI provider/config location.
- [x] Add Playwright CI job.
- [x] Cache/install Node dependencies.
- [x] Install Chromium browser.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium`.
- [x] Upload Playwright report/test-results artifacts.
- [x] Configure traces, screenshots, and video on failure.
- [x] Keep full-stack/real-service browser job separate from deterministic mock job.

### Phase 7: Cleanup and Replacement of Old Pipeline

- [x] Map manual chatbot checks to Playwright specs.
- [x] Update docs with the replacement command.
- [x] Mark manual chatbot typing/waiting/checking as deprecated.
- [x] Decide whether `factory-agent-smoke.js` remains as API smoke.
- [x] Keep `tests/e2e/run_seed_pipeline.ps1` for API/seed/reliability coverage unless explicitly approved otherwise.
- [x] Record final replacement decisions in this tracker.

### Phase 8: L3 Seeded Full-Stack Foundation

- [x] Add a `chromium-seeded` Playwright project.
- [x] Add isolated startup/teardown for seeded Go API using `emas/cmd/e2e_server`.
- [x] Add isolated startup/teardown for Factory Agent with test DB and seeded Go API URL.
- [x] Add Vite startup with real local service URLs.
- [x] Add deterministic fake planner/model/RAG provider behavior if no suitable Factory Agent switch exists.
- [x] Capture Go API, Factory Agent, Vite, browser console, network, Playwright trace, screenshot, video, and environment fingerprint on failure.
- [x] Implement scenario 31.
- [x] Implement scenario 32.
- [x] Implement scenario 33.
- [x] Implement scenario 34.
- [x] Implement scenario 35.
- [x] Implement scenario 36.
- [x] Implement scenario 37.
- [x] Implement scenario 38.
- [x] Fix any Phase 8 defects before Phase 9 or record accepted gaps with owner, severity, risk, and target date.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium`.
- [x] Run `npm run test:e2e -- --project=chromium-seeded --grep "@l3-foundation"`.
- [x] Update this tracker with results, blockers, files changed, defects fixed, and accepted gaps.

### Phase 9: L3 Hard Orchestration and Break Scenarios

- [x] Add deterministic multi-step job fixtures for seeded full-stack services.
- [x] Add deterministic multi-approval chain fixtures.
- [x] Add fault controls for approval timeout, partial tool failure, malformed tool payload, stream drop, duplicate submit, and deleted/stale session.
- [x] Assert backend evidence for request counts, session IDs, tool step order, approval IDs, final state, and SSE lifecycle.
- [x] Implement scenario 39.
- [x] Implement scenario 40.
- [x] Implement scenario 41.
- [x] Implement scenario 42.
- [x] Implement scenario 43.
- [x] Implement scenario 44.
- [x] Implement scenario 45.
- [x] Implement scenario 46.
- [x] Implement scenario 47.
- [x] Implement scenario 48.
- [x] Implement scenario 49.
- [x] Implement scenario 50.
- [x] Implement scenario 51.
- [x] Implement scenario 52.
- [x] For every defect found, add the lowest useful regression test before moving to Phase 10.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium`.
- [x] Run `npm run test:e2e -- --project=chromium-seeded --grep "@l3-hard"`.
- [x] Update this tracker with defects, fixes, results, and accepted gaps.

### Phase 10: L4 Production-Like Release Validation

- [x] Add a `chromium-release` Playwright project.
- [x] Add release/staging environment config helper.
- [x] Validate deployment app path `/`.
- [x] Validate Factory Agent proxy path `/agent`.
- [x] Validate Go API proxy path `/api/v1`.
- [x] Validate auth-required/static bearer polling fallback.
- [x] Validate CORS preflight and browser connectivity.
- [x] Validate failure artifacts on controlled release test failure.
- [x] Add latency budgets for chat-open, first progress, final response, and long stream timeout.
- [x] Add opt-in real LLM connectivity smoke with structural assertions only.
- [x] Add dependency outage checks for Go API unavailable and Factory Agent unavailable.
- [x] Add bad env/migration/schema mismatch prechecks.
- [x] Add slow-network, mobile viewport, keyboard-only, rollback URL, cache/version, and long-stream checks.
- [x] Implement scenarios 53-70.
- [x] Fix any Phase 10 release gate failures before Phase 11 or record accepted gaps with rollback instructions.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium`.
- [x] Run `npm run test:e2e -- --project=chromium-release`.
- [x] Update release docs and tracker results.

### Phase 11: L5 Production Synthetic Monitoring

- [x] Define safe read-only synthetic user/token.
- [x] Add `chromium-synthetic` Playwright project or standalone monitor command.
- [x] Add synthetic environment config helper with secret redaction.
- [x] Add machine-readable synthetic reporter.
- [x] Implement scenario 71.
- [x] Implement scenario 72.
- [x] Implement scenario 73.
- [x] Implement scenario 74.
- [x] Implement scenario 75.
- [x] Implement scenario 76.
- [x] Implement scenario 77.
- [x] Implement scenario 78.
- [x] Implement scenario 79.
- [x] Emit machine-readable monitor results.
- [x] Configure alert thresholds for timeout, auth failure, backend unavailable, provider outage, missing final response, and latency.
- [x] Document alert routing, owner rotation, and triage.
- [x] Confirm screenshots/traces are captured only on failure with retention/redaction rules.
- [x] Backfill closest deterministic L0-L4 regression test for any synthetic defect found.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium`.
- [x] Run `npm run test:e2e -- --project=chromium-release`.
- [x] Run `npm run test:e2e -- --project=chromium-synthetic`.

### Phase 12: Manual Testing Retirement and Governance

- [x] Build a manual-test replacement matrix mapping old manual checks to L0-L5 automation.
- [x] Implement scenario 80 as a governance audit or checklist.
- [x] Mark each old manual check as retired, automated, human semantic review, compliance/sign-off, exploratory discovery, emergency-only, or accepted gap.
- [x] Define owners for PR E2E, seeded full-stack foundation, hard orchestration, release validation, production synthetic monitoring, and accepted-gap review.
- [x] Define scenario add/remove rules.
- [x] Define accepted-gap rules and review cadence.
- [x] Define quarterly scenario review checklist.
- [x] Document PR, L3 seeded, L3 hard, release, and post-deploy validation commands.
- [x] Record accepted gaps and non-automated human-review areas.
- [x] Confirm no routine manual chatbot regression remains required for PR, release, or post-deploy smoke.
- [x] Run `git status --short --branch`.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium`.
- [x] Run `npm run test:e2e -- --project=chromium-seeded`.
- [x] Run `npm run test:e2e -- --project=chromium-release`.
- [x] Run `npm run test:e2e -- --project=chromium-synthetic`.
- [x] Record Phase 12 commands, results, files changed, blockers, accepted gaps, and final decisions.

Phase 12 replacement matrix:

| Old manual chatbot check | Disposition | Replacement / accepted gap | Owner |
|---|---|---|---|
| Open app and find floating AI Assistant control. | automated | L0 mocked Chromium, scenarios 1-2. | Frontend E2E owner |
| Open chat modal and confirm empty state/composer. | automated | L0 mocked Chromium, scenarios 1-2. | Frontend E2E owner |
| Type machine-status prompt and verify final answer. | automated | L1 mocked scenario 5 and L3 seeded scenario 32. | Frontend E2E owner / Seeded L3 owner |
| Check low-priority jobs structured response. | automated | L3 seeded scenario 33. | Seeded L3 owner |
| Ask RAG/LOTO question and inspect source chrome. | automated | L3 seeded scenario 34 and L5 synthetic scenario 73 structural canary. | Seeded L3 owner / Synthetic L5 owner |
| Watch notification/activity streaming and completion. | automated | L2 scenarios 11, 13, 14 and L3 scenario 38. | Frontend E2E owner / Seeded L3 owner |
| Check malformed stream, stream drop, timeout, retry, empty answer, cancel, and modal close recovery. | automated | L1/L2 scenarios 18-26 and L3 hard scenarios 47-51. | Frontend E2E owner / Hard L3 owner |
| Approve/reject approval-gated chatbot flows. | automated | L3 seeded scenarios 35-36 and L3 hard scenarios 40-42. | Seeded L3 owner / Hard L3 owner |
| Confirm seeded Go API and Factory Agent contracts still match browser expectations. | automated | L3 seeded scenarios 31-38. | Seeded L3 owner |
| Try multi-step, multi-approval, stale-session, duplicate-submit, large-result, and cross-session hazards. | automated | L3 hard scenarios 39-52. | Hard L3 owner |
| Validate production-like paths, auth fallback, CORS, slow network, mobile, keyboard, artifact, rollback, and cache behavior. | automated | L4 release scenarios 53-70. | Release L4 owner |
| Check after deploy that chatbot opens, progresses, completes, and alerts on outage. | automated | L5 synthetic scenarios 71-79. | Synthetic L5 owner |
| Judge nuanced answer quality, usefulness, tone, or domain semantics beyond structural assertions. | human semantic review | Accepted gap AG-P12-001. | Product/SME review owner |
| Complete formal policy, compliance, or regulated operational sign-off. | compliance/sign-off | Accepted gap AG-P12-002. | Compliance owner |
| Explore brand-new prompts, workflows, or unmodeled operational risks. | exploratory discovery | Accepted gap AG-P12-003. | QA/exploratory owner |
| Diagnose incidents when automation, harnesses, or production telemetry are unavailable. | emergency-only | Accepted gap AG-P12-004. | On-call owner |
| Keep routine manual chatbot regression as a PR, release, or post-deploy requirement. | retired | Replaced by L0-L5 gates; not required after Phase 12 passes. | Frontend E2E owner |

Phase 12 governance owners:

| Area | Owner | Rule |
|---|---|---|
| PR mocked Playwright E2E | Frontend E2E owner | Owns deterministic `chromium` PR gate. |
| Seeded full-stack L3 | Seeded L3 owner | Owns real Vite, Go API, Factory Agent, seeded DB, and deterministic provider contract checks. |
| Hard orchestration L3 | Hard L3 owner | Owns scenarios 39-52 and blocks promotion on reproducible orchestration defects. |
| Release validation L4 | Release L4 owner | Owns release paths, auth fallback, CORS, mobile, keyboard, rollback, latency, and artifacts. |
| Production synthetic L5 | Synthetic L5 owner | Owns read-only canaries, alert classification, token checks, provider outage signals, and redaction. |
| Accepted-gap review | QA governance owner | Owns monthly accepted-gap review and quarterly scenario review. |

Scenario lifecycle rules:

- Add scenarios only for new risk, new user-visible state, new backend contract, new deployment hazard, or fixed-defect regression coverage.
- Remove or merge redundant scenarios when they prove the same risk with the same assertion and evidence.
- Require failure artifact expectations for every scenario layer.
- Require regression coverage at the lowest useful layer for every fixed defect.
- Keep production synthetic prompts read-only and non-mutating.
- Keep default PR CI on deterministic mocked `chromium` unless the team deliberately changes the governance rule.
- Keep `chromium-seeded`, `chromium-release`, and `chromium-synthetic` opt-in or scheduled, not silent default PR work.

Accepted-gap rules and review cadence:

- Every accepted gap must include owner, severity, risk, target date or phase, reason, and temporary workaround.
- Review Phase 12 human-only gaps monthly while open.
- Review all accepted gaps during quarterly scenario review.
- Reopen the relevant phase if a medium or higher gap starts affecting routine PR, release, or post-deploy regression confidence.
- Do not use any critical or high accepted gap to claim Phase 19 production-grade prompt/workflow robustness.

Quarterly scenario review checklist:

- Confirm owners are current.
- Confirm `chromium` remains deterministic and PR-safe.
- Confirm `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain opt-in unless deliberately promoted.
- Remove or merge redundant scenarios.
- Add scenarios for new incidents, product risks, or fixed defects missing regression coverage.
- Confirm failure artifacts are sufficient to debug without rerunning manually.
- Confirm synthetic prompts are still read-only.
- Review accepted gaps, target dates, workarounds, and whether any human-only check can now be automated.
- Confirm no routine manual chatbot regression has returned to PR, release, or post-deploy smoke.

Phase 12 validation commands:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
npm run test:e2e -- --project=chromium-seeded
npm run test:e2e -- --project=chromium-release
npm run test:e2e -- --project=chromium-synthetic
```

### Phase 13: Normal-Use Production Hardening

- [x] Add `@normal-use` scenario tag and file structure.
- [x] Implement scenario 81.
- [x] Implement scenario 82.
- [x] Implement scenario 83.
- [x] Implement scenario 84.
- [x] Implement scenario 85.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium --grep "@normal-use"`.
- [x] Run `npm run test:e2e -- --project=chromium-seeded --grep "@normal-use"`.
- [x] Record defects, fixes, accepted gaps, and files changed.

### Phase 14: Data Integrity and Side-Effect Safety

- [x] Add seeded fixtures for mutating job-priority workflows.
- [x] Define original-state semantics for cascading priority updates.
- [x] Implement scenario 86.
- [x] Implement scenario 87.
- [x] Implement scenario 88.
- [x] Implement scenario 89.
- [x] Implement scenario 90.
- [x] Assert DB state, audit log, SSE timeline, approval ids, and visible final summary agree.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium`.
- [x] Run `npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity"`.
- [x] Record defects, fixes, accepted gaps, and files changed.

### Phase 15: Reliability, Scale, and Soak Hardening

- [x] Add `@reliability` scenarios and opt-in/scheduled job plan.
- [x] Implement scenario 91.
- [x] Implement scenario 92.
- [x] Implement scenario 93.
- [x] Implement scenario 94.
- [x] Implement scenario 95.
- [x] Add checks for leaked ports, orphan child processes, orphan streams, and teardown timing.
- [x] Run `npm run test:e2e -- --project=chromium --grep "@reliability"`.
- [x] Run `npm run test:e2e -- --project=chromium-seeded --grep "@reliability"`.
- [x] Record flake rate, timing, defects, fixes, accepted gaps, and files changed.

### Phase 16: Security, Privacy, and Abuse Hardening

- [x] Add `@security` and `@privacy` scenarios.
- [x] Implement scenario 96.
- [x] Implement scenario 97.
- [x] Implement scenario 98.
- [x] Implement scenario 99.
- [x] Implement scenario 100.
- [x] Add artifact redaction scan for configured token/secret patterns.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium --grep "@security|@privacy"`.
- [x] Run `npm run test:e2e -- --project=chromium-release --grep "@security|@privacy"`.
- [x] Record defects, fixes, accepted gaps, and files changed.

### Phase 17: Production-Grade Operational Readiness

- [x] Add operational readiness scenario structure.
- [x] Implement scenario 101.
- [x] Implement scenario 102.
- [x] Implement scenario 103.
- [x] Implement scenario 104.
- [x] Implement scenario 105.
- [x] Define critical/high/medium/low gate severity rules.
- [x] Add one final production-grade gate command or workflow.
- [x] Run the full gate matrix.
- [x] Confirm no critical/high accepted gaps remain open.
- [x] Record final signoff result, owners, commands, failures, fixes, and accepted gaps.

### Phase 18: Intent, Entity, and RAG Route Robustness

- [x] Add manual prompt regression bank seeded with `What LOTO procedure applies before working on M-CNC-01?`.
- [x] Add parser/unit matrix for machine IDs, job IDs, punctuation, mixed case, markdown, quotes, and newlines.
- [x] Add seeded fake-provider routing checks for selected intent, extracted entities, tool/RAG route, clarification behavior, and final state.
- [x] Add browser-visible smoke for the most important prompt classes.
- [x] Implement scenario 106.
- [x] Implement scenario 107.
- [x] Implement scenario 108.
- [x] Implement scenario 109.
- [x] Implement scenario 110.
- [x] Implement scenario 111.
- [x] Implement scenario 112.
- [x] Implement scenario 113.
- [x] Implement scenario 114.
- [x] Implement scenario 115.
- [x] Confirm the LOTO prompt with `M-CNC-01` does not ask for the machine ID again.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium --grep "@intent-entity"`.
- [x] Run `npm run test:e2e -- --project=chromium-seeded --grep "@intent-entity|@rag-route"`.
- [x] Record defects, fixes, accepted gaps, prompt-bank additions, and files changed.

### Phase 19: Prompt and Workflow Regression Expansion

- [x] Extend the regression bank schema with prompt, observed failure, expected behavior, owner, severity, lowest test layer, and browser coverage flag.
- [x] Add LOTO wording variants for the M-CNC-01 failure class.
- [x] Add machine/job ID extraction variants for punctuation, lowercase, quotes, parentheses, markdown, and newlines.
- [x] Add route-selection assertions for LOTO/RAG, machine status, job listing, priority mutation, approval, and cancel prompts.
- [x] Add priority cascade matrix fixtures.
- [x] Add two-write-set approval invariant helper.
- [x] Add original-state mutation invariant helper.
- [x] Implement scenario 116.
- [x] Implement scenario 117.
- [x] Implement scenario 118.
- [x] Implement scenario 119.
- [x] Implement scenario 120.
- [x] Implement scenario 121.
- [x] Implement scenario 122.
- [x] Implement scenario 123.
- [x] Implement scenario 124.
- [x] Implement scenario 125.
- [x] Confirm the remaining cascade matrix variants beyond the Phase 14-covered high/low and medium/high two-step cascades.
- [x] Run `npm test`.
- [x] Run `npm run test:e2e -- --project=chromium --grep "@prompt-regression"`.
- [x] Run `npm run test:e2e -- --project=chromium-seeded --grep "@prompt-regression|@data-integrity"`.
- [x] Record defects, fixes, accepted gaps, prompt-bank additions, and files changed.

### Phase 20: Real LangGraph Approval-Chain Regression

- [x] Add scenario 126 backend regression outside `SeededPlaywrightPlanner`.
- [x] Make the regression fail when `resume_after_approval` completes after approval 1 instead of raising approval 2.
- [x] Fix real graph commit-success routing to clear committed staged writes, mark the current intent complete, and continue planning when another active intent remains.
- [x] Assert the exact prompt stages original medium -> high for approval 1 and original high -> medium for approval 2.
- [x] Run `python -m pytest tests/test_phase5_final_validator.py -q`.
- [x] Run `python -m pytest tests/test_planner_service_phase6.py -q`.
- [x] Run `python -m pytest tests/test_planner_phase3.py -q`.

## Current Blockers

- No current Phase 20 blockers.
- Phase 18 resolved the manual LOTO prompt miss: `What LOTO procedure applies before working on M-CNC-01?` now extracts `M-CNC-01`, routes to LOTO/RAG, and does not ask for the machine ID again.
- Manual cascade risk `change all medium priority job to high then change all high priority job to medium` is covered in both the seeded Phase 14/19 suites and the Phase 20 real LangGraph backend approval-chain regression.

## Accepted Gaps

- Phase 12 records the following non-routine human-only areas. They do not block retiring routine manual chatbot regression because each has an owner, review cadence, reason, risk, and workaround.

| ID | Manual check | Disposition | Owner | Severity | Risk | Target | Reason | Temporary workaround |
|---|---|---|---|---|---|---|---|---|
| AG-P12-001 | Nuanced answer quality, usefulness, tone, and domain semantics beyond structural assertions. | human semantic review | Product/SME review owner | Medium | Structurally valid answers can still be unhelpful, misleading, or poorly phrased. | Monthly accepted-gap review; revisit during Phase 19 signoff. | Exact semantic quality is nondeterministic and should not be made a brittle browser assertion. | Product/SME sample review for release candidates or material prompt/provider changes; convert recurring defects into deterministic scenarios or evals. |
| AG-P12-002 | Formal policy, compliance, or regulated operational sign-off. | compliance/sign-off | Compliance owner | Medium | Automation can miss policy/legal obligations that require accountable human sign-off. | Monthly accepted-gap review; revisit during Phase 19 signoff. | Compliance approval is outside engineering-only test authority. | Compliance owner signs off when required; engineering adds structural checks for repeatable policy defects. |
| AG-P12-003 | Brand-new prompts, workflows, or unmodeled operational risks. | exploratory discovery | QA/exploratory owner | Low | Unknown risks may not be covered until discovered. | Quarterly scenario review, or sooner after incidents/new features. | Exploratory testing is discovery work, not routine regression. | Exploratory findings become new scenarios only when they represent recurring or release-blocking risk. |
| AG-P12-004 | Incident diagnosis when automation, harnesses, or production telemetry are unavailable. | emergency-only | On-call owner | Low | During outages, a human may need to inspect behavior directly before automation is restored. | Quarterly scenario review, plus post-incident review. | Emergency diagnosis cannot be fully replaced by prewritten regression checks. | Use manual browser diagnosis only for incident response; backfill automation for any reproducible regression. |

- Phase 19 recorded no new accepted gaps. No critical or high accepted gaps remain open. The Phase 12 medium/low human-only governance gaps remain non-routine review areas and do not block Phase 19 prompt/workflow signoff.

Phase 10-17 implementation risks to resolve:

- Release and synthetic projects must stay opt-in and separate from default PR CI unless deliberately promoted.
- Real LLM connectivity should not run before Phase 10 and must be explicitly enabled with structural assertions only.
- Production synthetic checks must remain safe and read-only.
- Phase 13-19 reliability, security/privacy, operational, and prompt/workflow robustness gates remain deterministic opt-in/scheduled gates unless deliberately promoted.
- Mutating data-integrity scenarios must run only against seeded/resettable environments.
- Any reproducible defect found in Phase 10 onward blocks phase promotion until fixed or recorded as an accepted gap.

## Open Questions

| Question | Current Answer / Assumption |
|---|---|
| Should browser CI run against real Factory Agent? | No for default CI. Use a deterministic mock Factory Agent server first. Add full-stack as optional/nightly later. |
| Should tests cover legacy Go `/api/v1/ai/chats` UI flow? | Not initially. The visible chat UI uses Factory Agent. Legacy Go chat can remain covered by Go/API tests or a later optional browser track. |
| Should MSW be introduced? | Not recommended now. It is not present and native EventSource streaming is better tested with a real mock HTTP/SSE server. |
| Should Playwright route interception be used? | Yes for small REST-only cases, not as the primary SSE mocking mechanism. |
| Should real LLM calls run in CI? | No. Real LLM/RAG checks remain opt-in because they are nondeterministic and environment-dependent. |
| When should real LLM testing start? | Phase 10 / L4 only, as an opt-in controlled release validation smoke. L3 should use fake/controlled provider responses. |
| Can manual testing be fully eliminated? | Routine chatbot regression and post-deploy smoke can be automated by L0-L5. Human review may remain for exploratory testing, product judgment, compliance sign-off, or semantic quality audits. |
| What happens when Phase 8+ finds an error? | Fix it before starting the next phase, add regression coverage, rerun the current phase command plus fast PR tests, and record commands/results in this tracker. |
| Should hard scenarios be expected to pass immediately? | No. Phase 9 is intentionally failure-seeking. A discovered defect is useful only if it is fixed or explicitly accepted with owner and risk. |
| Do Phase 13-19 include model-quality evaluation? | No. Phase 13-19 stay focused on Playwright/browser, backend, deterministic provider, reliability, data integrity, privacy, operations, prompt-route robustness, and prompt/workflow regression expansion. |
| Can Phase 14 mutating tests run against production? | No. Mutating data-integrity scenarios must use seeded/resettable environments only. |
| Why did the LOTO prompt fail after Phase 14? | Phase 14 covers data mutation integrity, not broad prompt/entity/RAG route robustness. The failure belongs to Phase 18. |
| Does Phase 18 add Promptfoo? | No. Phase 18 uses deterministic parser/unit tests, seeded fake-provider routing, and targeted Playwright/browser checks only. |
| Does Phase 19 add Promptfoo? | No. Phase 19 expands deterministic prompt/workflow regression coverage. Real LLM quality evaluation remains a separate eval track. |
| Where should the medium-to-high then high-to-medium cascade be covered? | The exact manually raised cascade is covered by the Phase 14 Scenario 86 follow-up and by Phase 19 scenarios 119-121, which expand the broader cascade matrix with explicit two-approval and original-state invariants. |

## Decisions Made

| Decision | Rationale |
|---|---|
| Put Playwright under `eMas Front`. | The frontend package owns the browser app, npm scripts, Vite server, and package lock. |
| Use a test-only mock Factory Agent HTTP/SSE server. | It matches `VITE_FACTORY_AGENT_BASE_URL`, avoids real LLM calls, and can stream real EventSource frames. |
| Keep existing Go/Python seed pipeline during rollout. | It covers API contracts, seed data, reliability, and backend behavior that Playwright should not replace wholesale. |
| Treat current SSE as snapshot/activity streaming, not token streaming. | The inspected backend streams notification/activity/semantic events; final answer text is snapshot-derived and locally animated. |
| Start with Chromium only. | Reduces initial flake and install cost. Add more browsers after stability. |
| Cap the first browser portfolio at about 30 scenarios. | Keeps the suite meaningful and fast while covering distinct risks instead of prompt variants. |
| Grow from mocked browser tests to seeded full-stack foundation, hard orchestration, production-like release validation, then safe synthetic monitoring. | This gives fast PR feedback now while preserving a path to production confidence later. |
| Playwright replaces manual browser chatbot typing/waiting/checking for deterministic frontend validation. | It drives the real Vite UI and chat modal in Chromium while using mocked Factory Agent REST/SSE responses for stable assertions. |
| `tests/e2e/run_seed_pipeline.ps1` remains in place. | It still covers Go API seed checks, Factory Agent pytest/API checks, Promptfoo-enabled flows, and optional full-stack/live scenarios that Playwright does not replace. |
| `eMas Front/scripts/factory-agent-smoke.js` remains a quick API smoke. | It is useful for real Factory Agent HTTP session/message/plan/execute/cancel checks, but Playwright supersedes it for browser/modal validation. |
| Phase 6 CI runs only the deterministic mocked frontend chatbot E2E suite. | CI runs `npm test` and `npm run test:e2e -- --project=chromium`; real LLM/RAG and full-stack checks remain opt-in/non-deterministic. |
| Phase 8 introduces L3 foundation instead of putting real services into default PR CI. | It proves real service contracts while keeping fast deterministic mocked PR tests stable. |
| Phase 9 is a dedicated hard-orchestration phase. | Multi-step jobs, multi-approval chains, partial failures, duplicate submits, stale sessions, and SSE order hazards deserve their own failure-seeking gate before L4. |
| Any reproducible Phase 8+ defect blocks phase promotion until fixed or accepted. | The plan should improve the system, not only accumulate passing tests. |
| Phase 10 is the first stage where real LLM connectivity can be tested. | Provider connectivity is release risk, not PR regression risk; assertions must be structural and opt-in. |
| Phase 10 release validation is opt-in only. | `chromium-release` builds a production-like frontend behind local nginx-style proxy paths and is intended for release gates, not default PR CI. |
| Phase 11 uses only safe read-only production/staging canaries. | Production synthetic monitoring must not mutate operational data. |
| Phase 11 synthetic monitoring is opt-in only. | `chromium-synthetic` requires explicit project selection and live production/staging mode requires explicit URL/token/owner env vars. |
| Phase 12 is required before claiming manual testing is fully eliminated. | It creates the replacement matrix, ownership, scenario lifecycle, accepted-gap record, and final retirement gate. |
| Scenario 80 is a governance audit/checklist, not another browser prompt variant. | Manual-test retirement is a traceability problem: every old check must map to automation or an accepted human-only gap before routine manual regression can be retired. |
| Routine manual chatbot regression is retired only for PR, release, and post-deploy smoke checks. | Human semantic review, compliance sign-off, exploratory discovery, and emergency diagnosis remain bounded accepted gaps with owners and review cadence. |
| Default PR CI remains mocked Chromium only. | `npm test` plus `npm run test:e2e -- --project=chromium` stays deterministic and does not start Go API, real Factory Agent, Docker, release proxy, or real LLM/RAG services. |
| Seeded, release, and synthetic projects remain opt-in. | `chromium-seeded`, `chromium-release`, and `chromium-synthetic` are explicit L3-L5 gates, not default PR work. |
| Phase 13-19 extend beyond manual-test retirement into production-grade hardening. | They add normal-use, data-integrity, reliability, security/privacy, operational readiness, intent/entity/RAG route, and prompt/workflow regression gates so the chatbot is harder to break in daily use. |
| Scenario 86 uses original-state semantics for cascading priority updates. | This avoids accidentally converting jobs changed from high to low during step one into medium during step two unless the product explicitly chooses current-state semantics later. |
| Phase 18 is required after operational readiness for prompt robustness. | The system can pass workflow/data tests while still failing normal operator wording, entity extraction, clarification boundaries, or RAG route selection. |
| Every manual prompt miss becomes a regression-bank entry. | This prevents the same class of "works in tests but fails manually" issue from returning after it is fixed. |
| Phase 19 turns the prompt bank into an expansion gate. | It prevents one-off fixes by requiring wording matrices, route assertions, cascade matrices, approval invariants, and regression-bank schema enforcement. |
| Phase 14 mutating coverage is seeded-only and opt-in. | Data-integrity scenarios reset deterministic job-priority fixtures and assert persisted state, audit entries, SSE/timeline evidence, approval ids, and final summaries without touching production data or default PR CI. |
| Multi-group Phase 14 mutations require separate approval evidence per write set. | A cascading workflow must prove each group-specific write was approved independently before the final summary can claim success. |
| Phase 16 security/privacy scenarios are tag-selected. | `@security`/`@privacy` tests are excluded from un-grepped mocked `chromium` runs and stay explicit gate commands so default PR CI remains deterministic and unchanged. |
| Phase 16 release security checks use signed local JWTs. | The release harness signs a per-run local token and verifies owner/auth behavior without adding real LLM or external identity dependencies. |
| Session isolation is enforced at the backend boundary. | Browser-visible ownership hints and JWT principals are checked by Factory Agent session, snapshot, message, control, event, approval, planning, and execution paths before returning session data or performing actions. |
| Security/privacy artifacts are redacted before evidence is attached or reported. | Trace/log/report helpers redact tokens, secrets, session ids, approval ids, operation ids, and trace ids before storing Phase 16 evidence. |
| Phase 17 operational readiness is an opt-in operator gate. | `npm run test:e2e:operational`, `npm run operational:gate`, and `.github/workflows/playwright-operational-readiness.yml` provide operational signoff without changing default PR CI. |
| Critical/high operational failures block Phase 17 signoff. | The gate severity rules define critical/high/medium/low behavior, require owner/severity/runbook evidence, and allow accepted gaps only when owner, severity, risk, target, reason, and workaround are present. |
| Emergency disable must be browser-visible and scoped. | The chatbot can be disabled with a diagnostic while the rest of the app remains usable; this is not a substitute for Phase 18-19 prompt/workflow robustness. |
| Synthetic helpers use the release bearer in local synthetic mode. | Local synthetic canaries now authenticate direct `/agent/*` probes with the generated release bearer while live synthetic mode still requires an explicit read-only token. |

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

Hard scenario planning update commands:

```powershell
Get-Content C:\Users\dilun\.codex\skills\awt-e2e-testing\SKILL.md
rg -n "Phase 8|Phase 9|Phase 10|Phase 11|L3-L5|Scenario Expansion|Manual-Testing|Recommended Current Implementation Step|Phase Progression|Quality Gate|error" PLAN.md
rg -n "Phase 8|Phase 9|Phase 10|Phase 11|Scenario|blocker|error|Defect|Next action|Decisions made|L3-L5" TRACK.md
git status --short --branch
git diff --stat -- PLAN.md TRACK.md
```

Production-grade hardening planning update commands:

```powershell
Get-Content C:\Users\dilun\.codex\skills\awt-e2e-testing\SKILL.md
rg -n "Phase 1|Phase 8|Phase 9|Phase 10|Phase 11|Phase 12|Recommended Current Implementation Step|Next Action|Scenario|Production" PLAN.md
rg -n "Phase Status|Phase 8|Phase 9|Phase 10|Phase 11|Phase 12|L3-L5|Scenario|Current Blockers|Open Questions|Decisions Made|Next Action" TRACK.md
git status --short --branch
```

Intent/entity robustness planning update commands:

```powershell
Get-Content C:\Users\dilun\.codex\skills\awt-e2e-testing\SKILL.md
rg -n "Phase 17|Phase 18|106|115|prompt|entity|RAG|LOTO|Next Action" PLAN.md TRACK.md
git status --short --branch
```

Prompt/workflow regression expansion planning update commands:

```powershell
Get-Content C:\Users\dilun\.codex\skills\awt-e2e-testing\SKILL.md
rg -n "Phase 18|Phase 19|116|125|prompt-regression|cascade|approval invariant|Next Action" PLAN.md TRACK.md
git status --short --branch
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

Phase 6:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed only Phase 6 workflow/config/tracker changes before verification.
- First `npm ci`: failed with Windows `EPERM` unlinking `node_modules\@esbuild\win32-x64\esbuild.exe` because an existing local `npm run dev`/Vite process was holding esbuild open.
- Stopped only the stale local frontend Node/Vite/esbuild processes from `eMas Front`, then re-ran verification.
- `npm ci`: passed; npm reported 12 audit vulnerabilities and existing deprecation warnings.
- `npx playwright install chromium`: passed.
- `npm test`: passed, 48 tests.
- `npm run test:e2e -- --project=chromium`: passed, 13 Chromium Playwright tests.

Phase 7:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed Phase 7 documentation changes before verification.
- `npm test`: passed, 48 tests.
- `npm run test:e2e -- --project=chromium`: passed, 13 Chromium Playwright tests.

Phase 8+ planning update:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; clean before the Phase 8+ planning edit.
- `rg -n "Phase 7|Growth Beyond|Recommended First|Long-Term Testing Scope Strategy|Phase Status|Long-Term Scope Strategy|Next Action" PLAN.md TRACK.md`: located insertion points for Phase 8+ planning.
- `Get-Content -Tail 140 PLAN.md`: reviewed the end of the existing plan.
- `Get-Content -Tail 120 TRACK.md`: reviewed the existing tracker end state.
- `Get-Content -First 230 TRACK.md`: reviewed current phase/scenario status before adding Phase 8+ rows.
- `Get-Content -TotalCount 430 PLAN.md | Select-Object -Last 140`: reviewed the long-term scope section before adding L3-L5 details.

Hard scenario planning update:

- Documentation-only update. No application tests were run.

Phase 8:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed pre-existing `PLAN.md`/`TRACK.md` changes plus Phase 8 working tree changes.
- `node --check e2e/support/fullStackEnv.js; node --check e2e/support/startSeededStackForPlaywright.js; node --check e2e/support/seededArtifacts.js; node --check e2e/specs/full-stack-seeded.spec.js; node --check playwright.config.js`: passed.
- `factory-agent/.venv/Scripts/python.exe -m py_compile factory-agent/factory_agent/testing_seeded_adapters.py factory-agent/main.py`: passed.
- `npm run test:e2e -- --project=chromium-seeded --grep "@l3-foundation"`: initially passed scenarios 31-33 and 35, then exposed assertion gaps and a post-approval completion/snapshot issue. After fixes, passed 8 Chromium seeded tests.
- `npm test`: passed, 49 tests.
- `npm run test:e2e -- --project=chromium`: passed, 13 Chromium mocked Playwright tests.
- Final `npm run test:e2e -- --project=chromium-seeded --grep "@l3-foundation"`: passed, 8 Chromium seeded Playwright tests.

Phase 8 defect/fix notes:

- Defect: approved graph approval completion could leave the visible browser state on the approval-wait narrative while the real completed tool result was present in the snapshot details. Fix: added frontend regression coverage in `turnAssembler.test.mjs`, improved completed approval summary selection, and added bounded post-approval snapshot refresh in `useFactoryAgentChat.js`. Scenario 36 now verifies completed state and controlled-provider result through the real seeded browser path.
- Assertion hardening: RAG source text can appear both in the based-on line and the source list; the L3 assertion now scopes to the first matching source text. Cancel scenario now asserts the browser returns non-busy and the real Factory Agent snapshot is `IDLE` with a cancelled error.

Phase 9:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed Phase 9 working tree changes and pre-existing `PLAN.md` modification.
- `factory-agent/.venv/Scripts/python.exe -m py_compile factory-agent/factory_agent/testing_seeded_adapters.py factory-agent/factory_agent/services/plan_creation_service.py factory-agent/factory_agent/services/approval_resume_service.py factory-agent/factory_agent/services/execution_service.py factory-agent/factory_agent/api/routers/events.py`: passed.
- `node --check e2e/support/fullStackScenarios.js; node --check e2e/specs/full-stack-orchestration.spec.js; node --check e2e/specs/full-stack-resilience.spec.js; node --check e2e/specs/full-stack-sse-hard.spec.js; node --check playwright.config.js`: passed.
- `npm run test:e2e -- --project=chromium-seeded --grep "@l3-hard"`: initially exposed product defects and assertion gaps. After fixes, passed 14 Chromium seeded Playwright tests.
- Final `npm test`: passed, 49 tests.
- Final `npm run test:e2e -- --project=chromium`: passed, 13 mocked Chromium Playwright tests.
- Final `npm run test:e2e -- --project=chromium-seeded --grep "@l3-hard"`: passed, 14 Chromium seeded Playwright tests.

Phase 9 defect/fix notes:

- Defect: graph approval resume swallowed the second approval because the background task accessed an expired SQLAlchemy approval row after rollback. Fix: capture approval/session ids before rollback, log background resume failures, and persist the follow-up graph approval. Scenarios 40 and 41 cover the two-approval approve/reject branches.
- Defect: graph approval timeout used the default 24-hour expiry and retained `completed_at` from the compatibility empty plan. Fix: honor `expires_in_seconds` in graph approvals and clear terminal metadata while waiting. Scenario 42 covers visible, non-terminal timeout state.
- Defect: completed plans with failed tool outputs flattened every step to done and could mark the session completed. Fix: align raw tool outputs to steps, preserve failed/ambiguous status and `last_error`, leave downstream steps `NOT_STARTED`, and keep the session `FAILED`. Scenario 43 covers partial failure.
- Defect: malformed planner payloads left the session in a planning state after validation failure. Fix: transition validation failures to `BLOCKED` with visible safe errors. Scenario 44 covers schema mismatch.
- Defect: double-clicking Send could race React state and submit duplicate turns/execute requests. Fix: add an immediate send guard ref in the chat hook. Scenario 45 covers request/message idempotence.
- Defect: stale deleted-session restore could clear the newly created replacement session id due a late 404. Fix: only clear local storage for the session id that actually failed and store a new session id immediately on creation. Scenario 46 covers recovery.
- Defect: manual EventSource recreation prevented native `Last-Event-ID` reconnect behavior and seeded stream drops only triggered when the intent was present at connection start. Fix: let native EventSource reconnect, add seeded server-side connection fingerprints, emit a short retry hint, and trigger the seeded drop after intent changes too. Scenarios 47, 48, and 51 cover ordering, reconnect, and stream-drop recovery.
- No accepted gaps were recorded for Phase 9.

Phase 10:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed pre-existing `PLAN.md` modification plus Phase 10 working tree changes.
- `node --check e2e/support/releaseEnv.js; node --check e2e/support/releaseArtifacts.js; node --check e2e/support/releaseProxyServer.js; node --check e2e/support/startReleaseStackForPlaywright.js; node --check e2e/support/releaseScenarios.js; node --check e2e/specs/release-validation.spec.js; node --check e2e/specs/release-resilience.spec.js; node --check playwright.config.js`: passed.
- `factory-agent/.venv/Scripts/python.exe -m py_compile factory-agent/factory_agent/testing_seeded_adapters.py`: passed.
- `npm run test:e2e -- --project=chromium-release`: initially exposed release harness issues and assertion gaps. After fixes, passed 18 Chromium release Playwright tests.
- Final `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed Phase 10 working tree changes and pre-existing `PLAN.md` modification.
- Final `npm test`: passed, 49 tests.
- Final `npm run test:e2e -- --project=chromium`: first run had one timing failure in the existing SSE activity spec, then immediate rerun passed 13 Chromium mocked Playwright tests.
- Final `npm run test:e2e -- --project=chromium-seeded --grep "@l3-hard"`: passed, 14 Chromium seeded hard Playwright tests.
- Final `npm run test:e2e -- --project=chromium-release`: passed, 18 Chromium release Playwright tests.

Phase 10 defect/fix notes:

- Harness defect: release webServer initially reported ready when only the proxy was healthy, allowing tests to start before Factory Agent was ready. Fix: wait on `/agent/ready` and preserve release startup logs/fingerprint.
- Harness defect: Factory Agent in production app mode skipped SQLite table creation and failed startup in the isolated release DB. Fix: release harness enables startup table creation for the per-run SQLite DB while still using production-like static bearer frontend paths.
- Harness defect: Windows `go run` child processes could outlive the release stack and lock the SQLite DB. Fix: release stack teardown uses Windows process-tree termination for spawned children.
- Product diagnostic fix: release proxy backend-unavailable faults now classify as `Factory Agent backend unavailable` instead of a generic attention banner. Scenario 61 covers the visible diagnostic.
- Assertion hardening: refresh during active work now accepts either completed recovery or safe non-terminal abandon, while asserting no duplicate user turn. Mobile approval validates completed backend state, visible completion text, and no dialog overflow without depending on hidden duplicate DOM nodes.
- No accepted gaps were recorded for Phase 10.

Phase 11:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed pre-existing `PLAN.md`/`TRACK.md` modifications plus Phase 11 working tree changes.
- `node --check e2e/support/syntheticEnv.js; node --check e2e/support/syntheticReporter.js; node --check e2e/support/syntheticArtifacts.js; node --check e2e/support/syntheticScenarios.js; node --check e2e/specs/production-synthetic.spec.js; node --check playwright.config.js; node --check e2e/support/releaseProxyServer.js; node --check e2e/support/releaseScenarios.js`: passed.
- `npm run test:e2e -- --project=chromium-synthetic`: passed 9 Chromium synthetic Playwright tests.
- `npm test`: passed, 49 tests.
- First `npm run test:e2e -- --project=chromium`: failed because `production-synthetic.spec.js` was unintentionally included in the default mocked `chromium` project. Fix: excluded `production-synthetic.spec.js` from the default mocked project, keeping synthetic opt-in only.
- Second `npm run test:e2e -- --project=chromium`: failed on a strict locator in the existing happy-path progress assertion because two visible progress labels matched. Fix: scope the assertion to the first matching visible progress label.
- Third `npm run test:e2e -- --project=chromium`: hit the known intermittent SSE activity timing issue noted in Phase 10; immediate rerun passed.
- Final `npm run test:e2e -- --project=chromium`: passed, 13 mocked Chromium Playwright tests.
- Final `npm run test:e2e -- --project=chromium-release`: passed, 18 Chromium release Playwright tests.
- Final `npm run test:e2e -- --project=chromium-synthetic`: passed, 9 Chromium synthetic Playwright tests.

Phase 11 defect/fix notes:

- Configuration defect: the new synthetic spec initially leaked into default PR `chromium` runs. Fix: update the `chromium` project `testIgnore` to exclude `production-synthetic.spec.js`; `chromium-synthetic` remains opt-in.
- Assertion gap: the mocked happy-path progress assertion used a strict locator that could match both the status row and compact activity label. Fix: assert the first matching progress label.
- No production/staging data mutation, broad approval flow, real LLM exact-text assertion, or accepted gap was introduced for Phase 11.

Phase 12:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed pre-existing `PLAN.md` modification plus Phase 12 tracker/README/governance working tree changes.
- `npm test`: passed, 49 tests.
- `npm run test:e2e -- --project=chromium`: passed, 13 mocked Chromium Playwright tests.
- `npm run test:e2e -- --project=chromium-seeded`: passed, 22 Chromium seeded Playwright tests covering L3 foundation and hard orchestration.
- `npm run test:e2e -- --project=chromium-release`: passed, 18 Chromium release Playwright tests.
- `npm run test:e2e -- --project=chromium-synthetic`: passed, 9 Chromium synthetic Playwright tests.

Phase 12 final decisions:

- Scenario 80 is implemented as a governance audit/checklist in `docs/operations/chatbot_test_governance.md` and mirrored in this tracker.
- Routine manual chatbot regression is retired for PR, release, and post-deploy smoke only after the replacement matrix and L0-L5 verification pass.
- Human semantic review, compliance sign-off, exploratory discovery, and emergency diagnosis remain accepted, owner-bound human-only gaps AG-P12-001 through AG-P12-004.
- Default PR CI remains mocked `chromium` only. It does not start Go API, real Factory Agent, Docker/release proxy, or real LLM/RAG services.
- `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain opt-in L3-L5 gates.
- Existing Go/Python E2E coverage and `tests/e2e/run_seed_pipeline.ps1` remain preserved.
- No Phase 12 blockers were found.

Phase 13-19 planning update:

- Documentation-only update. No application tests were run.
- Added production-grade hardening phases and scenarios 81-105, then added Phase 18 with scenarios 106-115 for prompt/entity/RAG route robustness.

Phase 13:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed pre-existing `PLAN.md` modification before Phase 13 edits.
- `git switch codex/playwright-e2e-plan`: already on `codex/playwright-e2e-plan`.
- `node --check e2e/support/normalUseScenarios.js; node --check e2e/mock-server/fixtureStore.js; node --check e2e/mock-server/factoryAgentMockServer.js; node --check e2e/specs/normal-use-hardening.spec.js; node --check e2e/specs/full-stack-normal-use.spec.js`: passed.
- First `npm run test:e2e -- --project=chromium --grep "@normal-use"` exposed Phase 13 fixture/assertion issues. After fixes, passed 5 mocked Chromium normal-use tests.
- First `npm run test:e2e -- --project=chromium-seeded --grep "@normal-use"` passed 1 seeded Chromium normal-use test.
- Verification `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed Phase 13 working tree changes plus pre-existing `PLAN.md`.
- `npm test`: passed, 49 tests.
- First verification `npm run test:e2e -- --project=chromium`: new Phase 13 tests passed, but the existing `chat-sse-activity.spec.js` timing issue hit once. Immediate rerun passed 18 mocked Chromium Playwright tests.
- Final `npm run test:e2e -- --project=chromium --grep "@normal-use"`: passed 5 mocked Chromium normal-use tests.
- Final `npm run test:e2e -- --project=chromium-seeded --grep "@normal-use"`: passed 1 seeded Chromium normal-use test.

Phase 13 coverage and layer decisions:

- Scenario 81 is mocked in `normal-use-hardening.spec.js`: ten-turn normal operator chat covers machine status, jobs, LOTO/RAG source chrome, follow-ups, details, table rendering, stable session id, idle composer, and no stale terminal banners.
- Scenario 82 is mocked in `normal-use-hardening.spec.js`: the mock server seeds many completed historical sessions, then the browser selects the target session and verifies the correct transcript without decoy transcript leakage.
- Scenario 83 is both mocked and seeded: mocked coverage verifies reload/UI persistence; seeded `full-stack-normal-use.spec.js` verifies real Factory Agent snapshot restoration and controlled seeded RAG source metadata.
- Scenario 84 is mocked: request-log assertions verify the draft text is not submitted, the final edited text is submitted exactly once, and `mode: "plan"` is preserved.
- Scenario 85 is mocked: completed, failed, and cancelled sessions are reopened/closed repeatedly; assertions cover stale banners, non-busy composer state, and mock-server EventSource close evidence.
- Default PR CI remains `npm test` plus `npm run test:e2e -- --project=chromium`; this is still deterministic and mocked.
- `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain opt-in only.
- Existing Go/Python E2E coverage and `tests/e2e/run_seed_pipeline.ps1` remain preserved.
- Phase 13 does not claim production-grade hardening is complete; Phase 19 remains the final prompt/workflow robustness gate.

Phase 13 defect/fix notes:

- Fixture defect: the lifecycle prompt for scenario 85 was missing from the normal-use mock scenario resolver. Fix: include it in the `normalUseConversation` prompt list.
- Assertion defect: the LOTO answer renders citation chrome instead of raw `[^1]` text, and raw args/result details are dev-only. Fix: assert visible rendered answer text and the user-facing `Show details` disclosure.
- Existing intermittent: the full mocked Chromium suite hit the previously observed SSE activity timing issue once; immediate rerun passed. No reproducible Phase 13 defect remained.
- No accepted gaps, blockers, production/staging data mutation, real LLM exact-text assertion, or memory-specific assertion was introduced for Phase 13.

Phase 14:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed a pre-existing `PLAN.md` modification plus Phase 14 working tree changes.
- `git switch codex/playwright-e2e-plan`: already on `codex/playwright-e2e-plan`.
- `node --check e2e/support/dataIntegrityScenarios.js; node --check e2e/specs/full-stack-data-integrity.spec.js`: passed.
- `factory-agent\.venv\Scripts\python.exe -m py_compile factory-agent\factory_agent\testing_seeded_adapters.py factory-agent\factory_agent\services\approval_resume_service.py factory-agent\factory_agent\api\routers\approvals.py factory-agent\main.py`: passed.
- First `npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity"` exposed Phase 14 defects in cascade summary shaping, partial-failure assertion wording, and stale/expired approval handling. After fixes, the command passed 5 seeded Chromium data-integrity tests.
- Final `npm test`: passed, 49 tests.
- Final `npm run test:e2e -- --project=chromium`: passed, 18 mocked Chromium Playwright tests.
- Final `npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity"`: passed, 5 seeded Chromium data-integrity tests.
- Final `git status --short --branch`: branch `codex/playwright-e2e-plan`; pending Phase 14 changes only plus the pre-existing unstaged `PLAN.md` change.
- Scenario 86 follow-up `node --check src/components/features/chat/factory-agent/activityTimelineUtils.js; node --check src/components/features/chat/factory-agent/useFactoryAgentChat.js; node --check src/components/features/chat/factory-agent/activityTimeline.test.mjs; node --check e2e/specs/full-stack-data-integrity.spec.js`: passed.
- Scenario 86 follow-up `factory-agent\.venv\Scripts\python.exe -m py_compile factory-agent\factory_agent\testing_seeded_adapters.py factory-agent\factory_agent\services\session_snapshot_service.py`: passed.
- Scenario 86 follow-up first `npm run test:e2e -- --project=chromium-seeded --grep "scenario 86"` reproduced the natural-prompt regression path and exposed missing UI evidence; after the product/test fix, the command passed 1 seeded Chromium test.
- Scenario 86 follow-up first full `npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity"` exposed a premature active-session `Run complete` row while the session was still `EXECUTING`; after the product fix, the command passed 5 seeded Chromium data-integrity tests.
- Scenario 86 follow-up final `npm test`: passed, 50 tests.
- Scenario 86 follow-up first `npm run test:e2e -- --project=chromium`: hit the previously recorded mocked SSE activity timing flake; immediate rerun passed 18 mocked Chromium Playwright tests.
- Scenario 86 medium/high follow-up `node --check src/components/features/chat/factory-agent/useFactoryAgentChat.js`: passed.
- Scenario 86 medium/high follow-up `node --check src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`: not applicable because Node syntax check does not load `.jsx` directly; covered by `npm test`.
- Scenario 86 medium/high follow-up `node --check src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`: passed.
- Scenario 86 medium/high follow-up `node --check e2e/specs/full-stack-data-integrity.spec.js`: passed.
- Scenario 86 medium/high follow-up `factory-agent\.venv\Scripts\python.exe -m py_compile factory-agent\factory_agent\testing_seeded_adapters.py factory-agent\factory_agent\services\session_snapshot_service.py`: passed.
- Scenario 86 medium/high follow-up final `npm test`: passed, 51 tests.
- Scenario 86 medium/high follow-up final `npm run test:e2e -- --project=chromium-seeded --grep "scenario 86"`: passed, 2 seeded Chromium tests.
- Scenario 86 medium/high follow-up final `npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity"`: passed, 6 seeded Chromium data-integrity tests.
- Scenario 86 medium/high follow-up final `npm run test:e2e -- --project=chromium`: passed, 18 mocked Chromium Playwright tests.

Phase 14 coverage and layer decisions:

- Scenario 86 is seeded in `full-stack-data-integrity.spec.js`: canonical seeded priority fixtures reset before the test; original high-priority jobs become low, original low-priority jobs become medium, and original medium-priority jobs remain unchanged. It also covers the manually raised `change all medium priority job to high then change all high priority job to medium` variant: original medium-priority jobs become high, original high-priority jobs become medium, and original low-priority jobs remain unchanged. Both variants require two distinct approval ids and assert exact final Go API DB state, audit entries, approval timeline evidence, SSE/timeline rows, and visible persisted summary agreement. The broader Phase 19 cascade matrix remains not started.
- Scenario 87 is seeded: a bulk update with one missing job records row-level success/failure outcomes, persists only the valid job changes, records audit success/failure rows, leaves the session failed, and does not claim all jobs succeeded.
- Scenario 88 is seeded: double-click/replay after refresh uses the same approval id but applies the mutation once, with one success audit row and one final DB change.
- Scenario 89 is seeded: stale approval context and expired approval attempts return safe conflict responses and leave DB state and audit success rows unchanged.
- Scenario 90 is seeded: for every mutating job, the final Go API DB state, seeded audit log, SSE/timeline evidence, approval id, and visible final assistant summary agree.
- Default PR CI remains `npm test` plus mocked `npm run test:e2e -- --project=chromium`; Phase 14 did not add Go API, real Factory Agent, Docker, release proxy, or real LLM/RAG services to default PR CI.
- `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain opt-in only. The `@data-integrity` scenarios are seeded/resettable and are not allowed to run against production data.
- Existing Go/Python E2E coverage and `tests/e2e/run_seed_pipeline.ps1` remain preserved.
- Phase 14 does not claim production-grade hardening is complete; Phases 15-19 remain, and Phase 19 remains the final prompt/workflow robustness signoff.

Phase 14 defect/fix notes:

- Product safety defect: expired graph approvals could still be approved and resume a seeded mutation. Fix: the approval router now rejects expired approvals before resume, clears matching pending context, and returns a conflict response without mutation.
- Product safety defect: stale graph approvals could be replayed after the session no longer matched the pending approval context. Fix: the approval router now requires the session to still be `WAITING_APPROVAL` for the same approval id before resume.
- Fixture/result defect: the cascade scenario initially shaped the result like a plain query table, which allowed the visible summary to look like a generic medium-priority query. Fix: the seeded adapter returns mutation outcomes and a concise final summary, and the test asserts the persisted visible summary after reload.
- Assertion defect: the partial-failure summary honestly says not all jobs succeeded, so the negative assertion was changed to reject false full-success claims instead of the substring `all jobs succeeded`.
- No accepted gaps, blockers, production/staging data mutation, release/synthetic CI promotion, or production-grade signoff claim was introduced for Phase 14.
- Scenario 86 follow-up defect: the natural operator prompt `change all high priority job to low then change all low priority job to medium` routed to the older generic one-approval priority flow instead of the two-write-set cascade. Fix: the seeded planner now detects high-to-low plus low-to-medium priority cascade wording before the generic approval branch.
- Scenario 86 follow-up defect: after approval 1, the UI/backend snapshot could show a stale `Run complete` activity row while the session was still `EXECUTING`, making the workflow appear complete before approval 2. Fix: backend snapshot activity projection and frontend activity merging now suppress terminal completion rows while a session is still active, and a unit regression covers active approval resume before the next approval.
- Scenario 86 regression coverage now uses the exact reported natural prompt, requires visible approval 1, waits for `WAITING_APPROVAL` after approval 1, requires a distinct visible approval 2 before completion, and then verifies DB state, audit rows, timeline/SSE evidence, approval ids, and final summary agreement.
- Scenario 86 medium/high follow-up defect: the manually raised prompt `change all medium priority job to high then change all high priority job to medium` was not part of the original Phase 14 cascade fixture, so the previous fix was too narrow to prove this swap-shaped cascade would not stop after approval 1. Fix: the seeded planner now parses natural two-step priority cascades dynamically and keeps original-state write sets such as `original_medium_to_high` and `original_high_to_medium` separate.
- Scenario 86 medium/high follow-up defect: after approval 1, the backend could already have the second pending approval while the browser still hid the approval card because the matching timeline/status refresh lagged or a stale terminal snapshot was present. Fix: approval polling stops as soon as a different pending approval appears, the chat panel treats `pendingApproval` as authoritative for rendering and waiting state, and snapshot projection keeps a pending approval in `WAITING_APPROVAL` while suppressing completion events.
- Scenario 86 medium/high regression coverage now requires approval 1 for original medium -> high, approval 2 for original high -> medium, no final completion before approval 2, exact low-priority unchanged rows, exact DB map, audit rows, timeline/SSE approval ids, and final activity agreement.

Phase 15:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed inherited Phase 14 working tree changes plus Phase 15 additions.
- `git switch codex/playwright-e2e-plan`: already on `codex/playwright-e2e-plan`.
- Phase 15 was marked `In Progress` in `TRACK.md` before implementation and `Done` only after verification passed.
- Syntax checks passed: `node --check` for `playwright.config.js`, mock server/store, SSE scripts, reliability specs, reliability helpers, soak runner, Vite starter, and `src/services/factoryAgentApi.js`; `git diff --check` passed with line-ending warnings only.
- Focused mocked reliability check initially found an assertion defect in scenario 93 because answer copy also contained `Knowledge sources`; the assertion was tightened to the actual sources heading and rerun passed 4 mocked reliability tests for scenarios 91-94.
- Scenario 95 initially found a harness defect: nested Playwright child runs used the default `test-results` output and removed the parent test artifact folder. Fix: the soak runner now gives each child smoke command an isolated `--output` folder and `--reporter=list`; scenario 95 rerun passed.
- Final `npm test`: passed, 51 tests.
- Final `npm run test:e2e -- --project=chromium`: passed, 18 mocked Chromium tests. The default PR suite did not pick up reliability/soak tests.
- Final `npm run test:e2e -- --project=chromium --grep "@reliability"`: passed, 5 mocked Chromium reliability tests.
- Final `npm run test:e2e -- --project=chromium-seeded --grep "@reliability"`: passed, 2 seeded Chromium reliability cross-checks.

Phase 15 coverage and layer decisions:

- Scenario 91 is mocked Chromium: ten isolated browser contexts run unique read-only prompts, complete with unique session ids, and assert no other session answer appears in each transcript.
- Scenario 92 is mocked Chromium plus seeded cross-check: the mocked run streams 48 activity events, rejects duplicate labels, checks bounded browser resources, clears busy UI, and observes stream close evidence; the seeded run proves the real seeded stream reaches terminal state.
- Scenario 93 is mocked Chromium plus seeded cross-check: the mocked run renders 120 result rows, 24 sources, table count chrome, details, source chips, and non-overflow controls; the seeded run reuses the real seeded large-result path to prove layout stability against real services.
- Scenario 94 is mocked Chromium: a deliberately slow plan response exceeds the reliability-only request timeout, shows progress first, preserves retry/cancel controls, and cancels safely.
- Scenario 95 is mocked Chromium with child smoke commands: the soak runner executes core mocked, seeded, and release smoke tests on isolated ports, records child exit codes, timeouts, port closure, and result artifacts under `test-results/reliability-soak/soak-results.json`.
- `@reliability` mocked tests are excluded from un-grepped `chromium` runs by `playwright.config.js`; `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain opt-in. The scheduled/dispatch workflow `.github/workflows/playwright-reliability-soak.yml` does not run on pull requests.
- No real LLM/RAG dependency was introduced. Existing Go/Python E2E coverage and `tests/e2e/run_seed_pipeline.ps1` remain preserved.

Phase 15 defect/fix notes:

- Product reliability defect: Factory Agent browser requests had no bounded timeout, so a hung plan/tool call could leave the UI waiting on the browser fetch indefinitely. Fix: `factoryAgentApi` now applies configurable request timeouts and surfaces a timeout message while keeping retry/cancel recovery available.
- Harness defect: nested soak Playwright runs could remove parent test artifacts by sharing the default output directory. Fix: `soakRunner.js` assigns isolated child output directories and validates child exit, timeout, and port cleanup.
- Assertion defect: scenario 93's `Knowledge sources` locator was ambiguous because the final answer also mentioned knowledge sources. Fix: assert the actual sources heading.
- No accepted gaps, blockers, default PR CI promotion, seeded/release/synthetic default promotion, production/staging data mutation, real LLM dependency, or production-grade hardening signoff was introduced for Phase 15.

Phase 16:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed inherited Phase 14/planning changes plus Phase 16 working tree changes.
- `git switch codex/playwright-e2e-plan`: already on `codex/playwright-e2e-plan`.
- Phase 16 was marked `In Progress` in `TRACK.md` before implementation and `Done` only after verification passed.
- Syntax checks passed: `node --check` for `playwright.config.js`, mock server/store, security/privacy specs, redaction/security helpers, release helpers, and Factory Agent API client helpers; Python `py_compile` passed for modified Factory Agent auth/router/service files. A direct `node --check` attempt on JSX files was not applicable because Node does not parse `.jsx` files directly; the component coverage was exercised by `npm test`.
- Focused mocked security/privacy check initially exposed harness/product gaps in the mock server CORS/user header path, denied-session logging evidence, unsafe action approval handling, and a rendering wait for the final assistant text. After fixes, the rerun passed all 5 mocked Chromium Phase 16 tests.
- `npm test`: passed, 51 tests.
- `npm run test:e2e -- --project=chromium --grep "@security|@privacy"`: passed, 5 mocked Chromium security/privacy tests.
- `npm run test:e2e -- --project=chromium-release --grep "@security|@privacy"`: passed, 3 opt-in release Chromium security/privacy cross-checks.
- Extra default PR sanity check: first `npm run test:e2e -- --project=chromium` run excluded the new Phase 16 specs but hit the existing intermittent `chat-sse-activity` timeout after 17 of 18 mocked Chromium tests passed. Targeted rerun of that spec passed, and full rerun of `npm run test:e2e -- --project=chromium` passed all 18 mocked Chromium tests.

Phase 16 coverage and layer decisions:

- Scenario 96 is mocked Chromium plus release cross-check: tampered active session ids cannot render another user's transcript, the UI shows a safe missing/denied diagnostic, local storage is cleared for the bad id, and release mode proves the same visible recovery against a missing session.
- Scenario 97 is mocked Chromium plus release cross-check: unauthorized REST, polling/snapshot, and EventSource probes are denied; browser-visible diagnostics stay safe; release mode verifies unauthenticated session, snapshot, and event probes return `401` without leaking session content.
- Scenario 98 is mocked Chromium plus release cross-check: artifact helpers redact bearer tokens, query secrets, JSON secrets, API keys, session ids, approval ids, operation ids, and trace ids before attachments/reports/log evidence is stored.
- Scenario 99 is mocked Chromium: very large pasted input and unsafe markdown/HTML/script-shaped content render as inert text, do not execute script handlers, keep the composer usable, and avoid dialog/document horizontal layout collapse.
- Scenario 100 is mocked Chromium: unsupported unsafe tool requests surface an approval/blocked state, keep the unsafe tool out of the allowlist, reject/deny safely, and avoid claiming execution success.
- `@security`/`@privacy` mocked specs are excluded from un-grepped `chromium` runs by `playwright.config.js`; default PR CI remains `npm test` plus deterministic mocked `npm run test:e2e -- --project=chromium` only.
- `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain explicit opt-in projects. Phase 16 did not change `.github` PR triggers, did not add real LLM/RAG dependencies to default CI, did not remove the existing Go/Python E2E pipeline, and did not remove `tests/e2e/run_seed_pipeline.ps1`.

Phase 16 defect/fix notes:

- Product isolation defect: browser/API session access could rely on unauthenticated development defaults without a principal, making cross-user isolation impossible to prove at the backend boundary. Fix: frontend Factory Agent requests carry a deterministic user id in development/test mode, release checks use signed local JWTs, and Factory Agent enforces owner access across session, snapshot, message, event, control, approval, planning, and execution routes/services.
- Product diagnostic defect: network/auth failures could surface a stale hardcoded backend URL and miss some backend-unavailable wording. Fix: diagnostics now use the configured Factory Agent base URL and recognize the unhyphenated `cannot reach factory agent` message.
- Product rendering hardening: chat message text now wraps long unbroken content with `break-words`/`pre-wrap`, preventing oversized unsafe content from collapsing layout while still rendering markup/script-shaped text inertly through React.
- Harness privacy defect: release proxy logs and browser/network/report attachments could record raw bearer tokens or operational ids. Fix: release artifact/proxy helpers apply the Phase 16 redaction scanner before storing evidence.
- No accepted gaps, blockers, default PR CI promotion, seeded/release/synthetic default promotion, production/staging mutation, real LLM dependency, Go/Python pipeline removal, or production-grade hardening signoff was introduced for Phase 16.

Phase 17:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed inherited Phase 14/planning changes before Phase 17 work.
- `git switch codex/playwright-e2e-plan`: already on `codex/playwright-e2e-plan`.
- Phase 17 was marked `In Progress` in `TRACK.md` before implementation and `Done` only after all verification commands passed.
- Syntax checks passed: `node --check` for `playwright.config.js`, `e2e/support/operationalGate.js`, `e2e/specs/operational-readiness.spec.js`, `e2e/support/syntheticReporter.js`, `e2e/support/syntheticEnv.js`, and `e2e/support/startViteForPlaywright.js`; Python `py_compile` passed for `factory-agent/factory_agent/persistence/database.py`.
- `npm run operational:gate -- --dry-run`: passed and printed the operator matrix for PR unit, PR mocked Chromium, seeded foundation, seeded hard, release validation, synthetic monitoring, security/privacy mocked, reliability mocked, and reliability seeded checks.
- `npm run operational:gate`: passed 9 operator gate entries with no critical/high failures and no invalid accepted gaps; artifacts were written under `eMas Front/test-results/operational-gate`.
- `npm run test:e2e:operational`: initially exposed an emergency-disable locator issue because `aria-disabled` prevented the button diagnostic click; after switching to a data attribute and retaining clickability, passed 5 mocked Chromium operational tests.
- `npm test`: passed, 51 tests.
- `npm run test:e2e -- --project=chromium`: passed, 18 mocked Chromium tests. Default PR CI remains deterministic mocked Chromium only and did not pick up operational/security/reliability/synthetic/release/seeded-only specs.
- `npm run test:e2e -- --project=chromium-seeded`: initially found SQLite lock failures in existing L3 hard scenarios 42-45; after adding SQLite busy timeout/WAL setup for the Factory Agent test DB, targeted rerun for scenarios 42-45 passed and the full seeded run passed 31 Chromium seeded tests.
- `npm run test:e2e -- --project=chromium-release`: initially found release assertion/harness gaps in scenarios 53, 64, and 66; after fixing proxy-log matching, safe refresh-abandon validation, and mobile completion polling, targeted reruns passed and the full release run passed 21 Chromium release tests.
- `npm run test:e2e -- --project=chromium-synthetic`: initially found direct synthetic snapshot probes missing Authorization in local release-harness mode; after falling back to the generated release bearer for local synthetic mode, the full synthetic run passed 9 Chromium synthetic tests.
- `git diff --check`: passed with line-ending normalization warnings only.
- Final `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed inherited Phase 14/planning changes plus Phase 17 changes, with no switch to `main`.

Phase 17 coverage and layer decisions:

- Scenario 101 is covered by `operational-readiness.spec.js`: synthetic failure alerts must include the expected code, owner, severity, message, and runbook link.
- Scenario 102 is covered by rollback validation helpers and a local known-good URL precheck: rollback command construction and URL support must pass before release rollback is trusted.
- Scenario 103 is covered by a browser emergency-disable path: clicking the chat control shows a clear diagnostic, avoids opening/creating a Factory Agent session, and leaves the dashboard/navigation usable.
- Scenario 104 is covered by the clean environment recreation plan: seeded DB, release artifacts, synthetic account ownership, and release/synthetic commands are validated from scratch.
- Scenario 105 is covered by `operationalGate.js`: PR, seeded, hard, release, synthetic, security/privacy, and reliability gates are evaluated with no critical/high failures and no invalid accepted gaps.
- The Phase 17 workflow `.github/workflows/playwright-operational-readiness.yml` is manual `workflow_dispatch` only. It does not run on pull requests.
- No real LLM dependency, production/staging mutation, default PR CI promotion, seeded/release/synthetic default promotion, Go/Python E2E pipeline removal, or `tests/e2e/run_seed_pipeline.ps1` removal was introduced.
- No Phase 17 accepted gaps were recorded; all operational readiness items requested for Phase 17 are automated. Phase 17 does not claim production-grade hardening is complete; Phase 19 remains the final prompt/workflow robustness signoff.

Phase 17 defect/fix notes:

- Harness defect: local synthetic direct `/agent/*` probes used no bearer token, so snapshot polling returned `401 missing Authorization header` even though the browser app had the release token. Fix: local synthetic env now falls back to the generated release bearer, while live mode still requires `PLAYWRIGHT_SYNTHETIC_AUTH_TOKEN`.
- Product/harness defect: an emergency-disabled chat button using `aria-disabled` could not be clicked by Playwright, preventing the user-facing diagnostic from being verified. Fix: retain button clickability with `data-emergency-disabled`, keep visual disabled styling, and show the diagnostic without opening the chat.
- Reliability defect found during the required full seeded gate: concurrent seeded release/hard flows could hit transient SQLite locks. Fix: Factory Agent SQLite connections now set a busy timeout and WAL journal mode for file-backed SQLite databases.
- Assertion defects found during the required full release gate: release proxy log matching was too whitespace-sensitive, refresh recovery required restore instead of allowing safe abandon, and mobile completion matched hidden duplicate text before visible completion. Fixes hardened those assertions without broadening Phase 17 scope.
- No accepted gaps, blockers, default PR CI promotion, seeded/release/synthetic default promotion, production/staging mutation, real LLM dependency, Go/Python pipeline removal, `tests/e2e/run_seed_pipeline.ps1` removal, or Phase 19 signoff claim was introduced for Phase 17.

Phase 18 planning update:

- Documentation-only update. No application tests were run.
- Added deep coverage-gap analysis for prompts that fail manually despite passing deterministic workflow/data tests.
- Added the manual LOTO miss `What LOTO procedure applies before working on M-CNC-01?` as the first Phase 18 regression-bank seed.
- Added scenarios 106-115 for entity extraction, clarification boundaries, RAG route correctness, source relevance, parser/unit coverage, and query-bank governance.

Phase 18:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed inherited Phase 14/planning and Phase 17 changes plus Phase 18 changes. No switch to `main`.
- `git switch codex/playwright-e2e-plan`: already on `codex/playwright-e2e-plan`.
- Phase 18 was marked `In Progress` in `TRACK.md` before implementation and `Done` only after required verification passed.
- Added `tests/e2e/scenarios/manual_prompt_regressions.json`, seeded with `What LOTO procedure applies before working on M-CNC-01?`, plus `docs/qa/manual_prompt_regression_bank.md`.
- Parser/routing fixes: compound machine IDs like `M-CNC-01` now parse as full machine IDs across punctuation, lowercase, markdown, quotes, and newlines; bare `JOB-SEED-*` IDs and work-order/task synonyms map to job entities; LOTO procedure prompts with a machine ID route to RAG; LOTO procedure prompts without a machine ID ask for the machine ID; existing LOTO-plus-status tool workflows remain tool-routed.
- Seeded fake-provider fixes: RAG answers include machine/procedure source metadata, multi-entity LOTO prompts preserve both machine and job IDs, `M-CNC-02` returns an honest no-source LOTO fallback, and machine/job/status synonym prompts route to `get__machines_{id}`, `get__jobs_{id}`, or `get__jobs` as appropriate.
- Mocked browser coverage: `intent-entity-robustness.spec.js` verifies the prompt-bank seed reaches a visible LOTO/RAG answer, shows source chrome, reaches `Run complete`, and does not ask for the machine ID again.
- Seeded browser coverage: `full-stack-intent-entity.spec.js` covers scenarios 106-112 and 115 through the opt-in seeded fake-provider stack.
- Parser/query-bank coverage: `test_phase18_intent_entity_parser.py` covers scenario 113 and route/clarification boundaries; `test_phase18_manual_prompt_bank.py` covers scenario 114 and parser-gates the bank.
- Focused parser/bank command passed: `python -m pytest factory-agent\tests\test_phase18_intent_entity_parser.py factory-agent\tests\test_phase18_manual_prompt_bank.py -q` passed 19 tests.
- Existing regression command passed: `python -m pytest factory-agent\tests\test_intent.py factory-agent\tests\test_reliability_e2e.py::test_rag_sources_and_normal_tool_output_share_the_same_snapshot -q` passed 4 tests, confirming the existing LOTO-plus-machine-status hybrid behavior still keeps RAG sources and tool steps.
- Syntax checks passed: `node --check` for `e2e/support/intentEntityScenarios.js`, `e2e/mock-server/fixtureStore.js`, `e2e/specs/intent-entity-robustness.spec.js`, and `e2e/specs/full-stack-intent-entity.spec.js`.
- `npm run test:e2e -- --project=chromium --grep "@intent-entity"` passed 1 mocked Chromium test.
- `npm run test:e2e -- --project=chromium-seeded --grep "@intent-entity|@rag-route"` initially exposed a test assertion gap: seeded RAG citations are surfaced on terminal timeline details rather than `snapshot.plan.sources`. After adjusting the assertion to inspect both plan sources and timeline source metadata, the command passed 10 seeded Chromium tests.
- `npm test` passed 51 frontend unit/component tests.
- `npm run test:e2e -- --project=chromium`: first run hit a transient existing SSE activity visibility failure; the targeted `chat-sse-activity.spec.js` rerun passed, and the full mocked Chromium rerun passed 19 tests. No product or Phase 18 code change was needed for that transient.
- The exact prompt `What LOTO procedure applies before working on M-CNC-01?` was confirmed not to ask for the machine ID again in parser, mocked browser, and seeded browser coverage.
- No accepted Phase 18 gaps were recorded; all requested Phase 18 items were automated.
- Default PR CI remains deterministic mocked Chromium only. `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain opt-in only. Phase 18 did not add Promptfoo, did not add real LLM dependencies to default PR CI, did not remove the existing Go/Python E2E pipeline, and did not remove `tests/e2e/run_seed_pipeline.ps1`.
- Phase 18 does not claim production-grade hardening is complete; Phase 19 remains the final prompt/workflow robustness signoff.

Phase 19 planning update:

- Documentation-only update. No application tests were run.
- Added Phase 19 as the prompt/workflow regression expansion layer after Phase 18.
- Added scenarios 116-125 for wording matrices, route assertions, cascade matrices, two-approval invariants, original-state semantics, regression-bank schema, and manual-failure triage.
- Added the medium-to-high then original-high-to-medium cascade as an explicit Phase 19 risk; the exact manually raised prompt was later pulled into Phase 14 Scenario 86 follow-up coverage.

Phase 19:

- `git status --short --branch`: branch `codex/playwright-e2e-plan`; showed inherited Phase 14/planning, Phase 17, and Phase 18 changes. No switch to `main`.
- `git switch codex/playwright-e2e-plan`: already on `codex/playwright-e2e-plan`.
- Phase 19 was marked `In Progress` in `TRACK.md` before implementation and `Done` only after required verification passed.
- Extended `tests/e2e/scenarios/manual_prompt_regressions.json` to version 2 with required schema fields: `source_prompt`, `observed_failure`, `expected_behavior`, `owner`, `severity`, `lowest_test_layer`, and `browser_coverage`.
- Added a triage rule requiring every future manual prompt/workflow miss to map to parser, route, seeded workflow, browser, or accepted-gap coverage before closure.
- Added LOTO wording variants for M-CNC-01 and documented them in `docs/qa/manual_prompt_regression_bank.md`.
- Added `test_phase19_prompt_workflow_regression.py` covering scenario 116 LOTO route equivalence, scenario 117 machine/job ID extraction across punctuation/lowercase/quotes/parentheses/markdown/newlines, scenario 118 selected intent/tool evidence, scenario 119 cascade phrase extraction, and scenarios 122-123 bank schema/triage validation.
- Tightened parser classification so plural `jobs` routes as the job entity for list and priority-mutation prompts.
- Added mocked browser `@prompt-regression` coverage proving successful LOTO routed prompts do not show generic `Factory Agent needs attention`, while a true unsupported prompt does show the generic diagnostic.
- Added seeded `full-stack-prompt-workflow-regression.spec.js` coverage for the regression bank and all four cascade variants: high-to-low then original-low-to-medium, medium-to-high then original-high-to-medium, low-to-high then original-high-to-low, and high-to-medium then original-medium-to-low.
- The medium-to-high then original-high-to-medium risk is explicitly covered by Phase 19 and still remains covered by the Phase 14 Scenario 86 follow-up.
- Every two-write-set cascade asserts approval 1 visible, approval 1 approved, step 1 persisted, approval 2 visible, approval 2 approved, step 2 persisted, and only then final completion.
- Every cascade asserts original-state semantics by comparing approval rows, DB state, audit entries, timeline approval ids, and final summary against the original seeded priority snapshot.
- Focused parser/bank command passed: `python -m pytest factory-agent\tests\test_phase18_intent_entity_parser.py factory-agent\tests\test_phase18_manual_prompt_bank.py factory-agent\tests\test_phase19_prompt_workflow_regression.py -q` passed 37 tests.
- Syntax checks passed: `node --check` for `e2e/support/promptRegressionScenarios.js`, `e2e/specs/prompt-workflow-regression.spec.js`, `e2e/specs/full-stack-prompt-workflow-regression.spec.js`, and `e2e/mock-server/fixtureStore.js`.
- `npm run test:e2e -- --project=chromium --grep "@prompt-regression"` initially exposed a Playwright assertion defect because the unknown diagnostic appears in both the banner and activity row. Fix: target the first matching diagnostic. The rerun passed 2 mocked Chromium tests.
- `npm run test:e2e -- --project=chromium-seeded --grep "@prompt-regression|@data-integrity"` passed 11 seeded Chromium tests, including all Phase 14 data-integrity checks and all Phase 19 cascade variants.
- `npm test` passed 51 frontend unit/component tests.
- `git diff --check` completed with line-ending warnings only and no whitespace errors.
- Final `git status --short --branch`: branch `codex/playwright-e2e-plan`; inherited unstaged Phase 14/planning, Phase 17, and Phase 18 changes remain present alongside Phase 19 files.
- No accepted Phase 19 gaps were recorded. No critical/high accepted gaps remain open.
- Default PR CI remains deterministic mocked Chromium only. `chromium-seeded`, `chromium-release`, and `chromium-synthetic` remain opt-in only. Phase 19 did not add Promptfoo, did not add real LLM dependencies to default PR CI, did not remove the existing Go/Python E2E pipeline, and did not remove `tests/e2e/run_seed_pipeline.ps1`.
- Production-grade hardening through Phase 19 is complete with no critical/high accepted gaps; medium/low Phase 12 human-only governance gaps remain documented as non-routine review areas.

Phase 20:

- Investigation found a seeded-adapter blind spot: Phase 14/19 Playwright coverage proved `SeededPlaywrightPlanner`, but manual runs use the real LangGraph planner/resume path.
- Added scenario 126 in `test_phase5_final_validator.py` for the exact prompt `change all medium priority job to high then change all high priority job to medium`.
- The new regression failed before the fix because `resume_after_approval` completed after approval 1 instead of raising approval 2.
- Fixed real graph commit-success continuation: successful commits now route through the final validator, clear committed staged writes, mark the current intent complete, and continue planning if another active intent remains.
- Scenario 126 now proves approval 1 stages original medium -> high, approval 1 commits, approval 2 stages original high -> medium, and completion happens only after approval 2 commits.
- Verification passed: `python -m pytest tests/test_phase5_final_validator.py -q` passed 15 tests.
- Verification passed: `python -m pytest tests/test_planner_service_phase6.py -q` passed 5 tests.
- Verification passed: `python -m pytest tests/test_planner_phase3.py -q` passed 13 tests.
- No accepted Phase 20 gaps were recorded.

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

Phase 6 implementation:

- `.github/workflows/playwright-e2e.yml`
- `TRACK.md`
- `eMas Front/playwright.config.js`

Phase 7 implementation:

- `TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/README.md`
- `tests/e2e/README.md`

Phase 8+ planning update:

- `PLAN.md`
- `TRACK.md`

Hard scenario planning update:

- `PLAN.md`
- `TRACK.md`

Phase 8 implementation:

- `TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/playwright.config.js`
- `eMas Front/e2e/specs/full-stack-seeded.spec.js`
- `eMas Front/e2e/support/fullStackEnv.js`
- `eMas Front/e2e/support/seededArtifacts.js`
- `eMas Front/e2e/support/startSeededStackForPlaywright.js`
- `eMas Front/e2e/support/startViteForPlaywright.js`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.js`
- `eMas Front/src/components/features/chat/turns/turnAssembler.test.mjs`
- `factory-agent/main.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/testing_seeded_adapters.py`

Phase 9 implementation:

- `TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/playwright.config.js`
- `eMas Front/e2e/specs/full-stack-orchestration.spec.js`
- `eMas Front/e2e/specs/full-stack-resilience.spec.js`
- `eMas Front/e2e/specs/full-stack-sse-hard.spec.js`
- `eMas Front/e2e/support/fullStackScenarios.js`
- `eMas Front/src/components/features/chat/factory-agent/useActivityStream.js`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `eMas Front/src/components/features/chat/factory-agent/useSessionEvents.js`
- `factory-agent/factory_agent/api/routers/events.py`
- `factory-agent/factory_agent/services/approval_resume_service.py`
- `factory-agent/factory_agent/services/execution_service.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/testing_seeded_adapters.py`

Phase 10 implementation:

- `TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/playwright.config.js`
- `eMas Front/e2e/specs/release-validation.spec.js`
- `eMas Front/e2e/specs/release-resilience.spec.js`
- `eMas Front/e2e/support/releaseArtifacts.js`
- `eMas Front/e2e/support/releaseEnv.js`
- `eMas Front/e2e/support/releaseProxyServer.js`
- `eMas Front/e2e/support/releaseScenarios.js`
- `eMas Front/e2e/support/startReleaseStackForPlaywright.js`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `factory-agent/factory_agent/testing_seeded_adapters.py`

Phase 11 implementation:

- `TRACK.md`
- `eMas Front/package.json`
- `eMas Front/playwright.config.js`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/specs/chat-happy-path.spec.js`
- `eMas Front/e2e/specs/production-synthetic.spec.js`
- `eMas Front/e2e/support/releaseProxyServer.js`
- `eMas Front/e2e/support/releaseScenarios.js`
- `eMas Front/e2e/support/syntheticArtifacts.js`
- `eMas Front/e2e/support/syntheticEnv.js`
- `eMas Front/e2e/support/syntheticReporter.js`
- `eMas Front/e2e/support/syntheticScenarios.js`

Phase 12 implementation:

- `TRACK.md`
- `eMas Front/e2e/README.md`
- `tests/e2e/README.md`
- `docs/operations/chatbot_test_governance.md`

Phase 13-19 planning update:

- `PLAN.md`
- `TRACK.md`

Phase 13 implementation:

- `TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/fixtures/factoryAgentFixtures.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/normal-use-hardening.spec.js`
- `eMas Front/e2e/specs/full-stack-normal-use.spec.js`
- `eMas Front/e2e/support/normalUseScenarios.js`

Phase 14 implementation:

- `TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/support/dataIntegrityScenarios.js`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js`
- `eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `factory-agent/factory_agent/api/routers/approvals.py`
- `factory-agent/factory_agent/services/approval_resume_service.py`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/testing_seeded_adapters.py`
- `factory-agent/main.py`

Phase 14 Scenario 86 follow-up implementation:

- `TRACK.md`
- `eMas Front/e2e/specs/full-stack-data-integrity.spec.js`
- `eMas Front/e2e/support/dataIntegrityScenarios.js`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/activityTimeline.test.mjs`
- `eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js`
- `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- `factory-agent/factory_agent/services/session_snapshot_service.py`
- `factory-agent/factory_agent/testing_seeded_adapters.py`

Phase 15 implementation:

- `.github/workflows/playwright-reliability-soak.yml`
- `TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/fixtures/sseScripts.js`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/full-stack-reliability.spec.js`
- `eMas Front/e2e/specs/reliability-soak.spec.js`
- `eMas Front/e2e/support/reliabilityScenarios.js`
- `eMas Front/e2e/support/resourceMetrics.js`
- `eMas Front/e2e/support/soakRunner.js`
- `eMas Front/e2e/support/startViteForPlaywright.js`
- `eMas Front/playwright.config.js`
- `eMas Front/src/services/factoryAgentApi.js`

Phase 16 implementation:

- `TRACK.md`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/mock-server/factoryAgentMockServer.js`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/release-security-privacy.spec.js`
- `eMas Front/e2e/specs/security-privacy.spec.js`
- `eMas Front/e2e/support/artifactRedaction.js`
- `eMas Front/e2e/support/releaseArtifacts.js`
- `eMas Front/e2e/support/releaseEnv.js`
- `eMas Front/e2e/support/releaseProxyServer.js`
- `eMas Front/e2e/support/releaseScenarios.js`
- `eMas Front/e2e/support/securityScenarios.js`
- `eMas Front/e2e/support/startReleaseStackForPlaywright.js`
- `eMas Front/playwright.config.js`
- `eMas Front/src/components/features/chat/ChatMessage.jsx`
- `eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- `eMas Front/src/services/factoryAgentApi.js`
- `eMas Front/src/services/factoryAgentErrors.js`
- `factory-agent/factory_agent/api/dependencies.py`
- `factory-agent/factory_agent/api/routers/approvals.py`
- `factory-agent/factory_agent/api/routers/events.py`
- `factory-agent/factory_agent/api/routers/messages.py`
- `factory-agent/factory_agent/api/routers/session_controls.py`
- `factory-agent/factory_agent/api/routers/sessions.py`
- `factory-agent/factory_agent/api/routers/snapshots.py`
- `factory-agent/factory_agent/services/execution_service.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`

Phase 17 implementation:

- `.github/workflows/playwright-operational-readiness.yml`
- `TRACK.md`
- `docs/operations/chatbot_release_runbook.md`
- `docs/operations/chatbot_synthetic_monitoring.md`
- `eMas Front/e2e/README.md`
- `eMas Front/e2e/specs/operational-readiness.spec.js`
- `eMas Front/e2e/specs/release-resilience.spec.js`
- `eMas Front/e2e/specs/release-validation.spec.js`
- `eMas Front/e2e/support/operationalGate.js`
- `eMas Front/e2e/support/startViteForPlaywright.js`
- `eMas Front/e2e/support/syntheticEnv.js`
- `eMas Front/e2e/support/syntheticReporter.js`
- `eMas Front/package.json`
- `eMas Front/playwright.config.js`
- `eMas Front/src/App.jsx`
- `eMas Front/src/components/shared/FloatingChatButton.jsx`
- `factory-agent/factory_agent/persistence/database.py`

Phase 18 implementation:

- `TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/full-stack-intent-entity.spec.js`
- `eMas Front/e2e/specs/intent-entity-robustness.spec.js`
- `eMas Front/e2e/support/intentEntityScenarios.js`
- `factory-agent/factory_agent/planning/intent.py`
- `factory-agent/factory_agent/services/plan_creation_service.py`
- `factory-agent/factory_agent/testing_seeded_adapters.py`
- `factory-agent/tests/test_phase18_intent_entity_parser.py`
- `factory-agent/tests/test_phase18_manual_prompt_bank.py`

Phase 19 implementation:

- `TRACK.md`
- `docs/qa/manual_prompt_regression_bank.md`
- `tests/e2e/scenarios/manual_prompt_regressions.json`
- `eMas Front/e2e/mock-server/fixtureStore.js`
- `eMas Front/e2e/specs/prompt-workflow-regression.spec.js`
- `eMas Front/e2e/specs/full-stack-prompt-workflow-regression.spec.js`
- `eMas Front/e2e/support/promptRegressionScenarios.js`
- `factory-agent/factory_agent/planning/intent.py`
- `factory-agent/factory_agent/testing_seeded_adapters.py`
- `factory-agent/tests/test_phase19_prompt_workflow_regression.py`

Phase 20 implementation:

- `PLAN.md`
- `TRACK.md`
- `factory-agent/factory_agent/graph/nodes/tool_pipeline.py`
- `factory-agent/factory_agent/graph/nodes/validate.py`
- `factory-agent/tests/test_phase5_final_validator.py`

## Next Action

Phase 20 is complete. If manual UI behavior still diverges from the backend approval-chain contract, add a non-seeded browser/full-stack check that proves the UI surfaces approval 2 from the real LangGraph path.

Keep the default PR CI on the mocked `chromium` suite, keep `chromium-seeded` as the opt-in L3 full-stack foundation/hard-orchestration/normal-use/data-integrity/intent-entity/prompt-regression/reliability gate, keep `chromium-release` as an opt-in L4 release-candidate gate, and keep `chromium-synthetic` as the opt-in L5 post-deploy monitor.

Do not remove the existing Go/Python E2E pipeline. Do not add Go backend, Docker, real Factory Agent, release proxy, or real LLM dependencies to the default Playwright suite.
