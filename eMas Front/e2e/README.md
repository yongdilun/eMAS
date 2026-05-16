# Playwright E2E

Browser tests live under `e2e/specs` and run against Vite plus a deterministic test-only Factory Agent mock server.

```powershell
npm run test:e2e -- --project=chromium
```

The Playwright config starts both servers. The app receives `VITE_FACTORY_AGENT_BASE_URL` pointing at `e2e/mock-server/factoryAgentMockServer.js`, so these tests do not require the real Factory Agent, Go backend, Docker, or LLM calls.

## Replacement for Manual Chatbot Validation

Use this Playwright suite instead of manual browser chatbot typing, waiting, and visual checking when the goal is deterministic frontend validation. It opens the real Vite app in Chromium, uses the same visible Factory Agent chat modal that operators use, and drives mocked Factory Agent REST/SSE responses through the browser.

The replacement command is:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium
```

Manual check replaced by Playwright:

| Old manual check | Playwright replacement |
|---|---|
| Open the app and confirm the floating AI Assistant control is reachable. | `e2e/specs/chat-baseline.spec.js` - app shell and accessible chat control. |
| Open the chat modal and confirm the composer can be used. | `e2e/specs/chat-baseline.spec.js` - empty state and enabled composer. |
| Type a machine-status prompt, send it, wait for the assistant, and check the final answer. | `e2e/specs/chat-happy-path.spec.js` - deterministic M-CNC-01 happy path. |
| Check that backend unavailable states do not show fake success. | `e2e/specs/chat-fixtures.spec.js` - plan 503 scenario. |
| Check that an empty completed response does not reuse stale assistant text. | `e2e/specs/chat-fixtures.spec.js` - empty assistant content scenario. |
| Watch notification streaming reach a completed answer. | `e2e/specs/chat-sse-notification.spec.js` - notification hello, invalidation, completion. |
| Watch activity rows arrive in order before final answer completion. | `e2e/specs/chat-sse-activity.spec.js` - ordered activity stream. |
| Check malformed stream, stream drop, retry, and non-terminal behavior. | `e2e/specs/chat-stream-errors.spec.js` - robustness and failure scenarios. |
| Click cancel or close the modal during work and confirm the UI returns safely. | `e2e/specs/chat-cancel-navigation.spec.js` - cancel and EventSource disconnect scenarios. |

This suite intentionally validates the deterministic mocked frontend path. Real Factory Agent, Go API, live RAG, and real LLM behavior remain outside this default browser suite.

## Phase 12 Governance and Retirement

Routine manual chatbot regression is retired only through the Phase 12 governance gate in [`../../docs/operations/chatbot_test_governance.md`](../../docs/operations/chatbot_test_governance.md). Scenario 80 is the audit checklist: every old manual chatbot check must be mapped to an L0-L5 automated gate or recorded as a human-only accepted gap with owner, severity, risk, target, reason, and workaround.

Manual checks are now classified as:

| Disposition | Meaning |
|---|---|
| `retired` | The old manual step is no longer a required PR, release, or post-deploy check. |
| `automated` | The check is covered by L0-L5 Playwright or lower-level regression gates. |
| `human semantic review` | Humans still review nuanced answer quality, usefulness, or tone beyond structural assertions. |
| `compliance/sign-off` | Humans still own formal policy or regulated sign-off outside Playwright. |
| `exploratory discovery` | Humans explore new risks; recurring findings must become automated scenarios or accepted gaps. |
| `emergency-only` | Humans may diagnose incidents when automation or telemetry is unavailable. |
| `accepted gap` | A non-automated check has explicit owner, severity, risk, target, reason, and workaround. |

Owners:

| Gate | Owner |
|---|---|
| PR mocked Playwright E2E | Frontend E2E owner |
| Seeded full-stack L3 | Seeded L3 owner |
| Hard orchestration L3 | Hard L3 owner |
| Release validation L4 | Release L4 owner |
| Production synthetic L5 | Synthetic L5 owner |
| Accepted-gap review | QA governance owner |

Scenario lifecycle rules:

- Add scenarios only for new risk, new user-visible state, new backend contract, new deployment hazard, or fixed-defect regression coverage.
- Remove or merge redundant scenarios that prove the same risk with the same assertion and evidence.
- Define failure artifact expectations for each scenario layer.
- Add regression coverage for every fixed defect at the lowest useful layer.
- Keep production synthetic prompts read-only.

Quarterly scenario review checks owners, redundant scenarios, new incidents or product risks, failure artifact usefulness, read-only synthetic prompts, accepted gaps, and whether routine manual chatbot regression has crept back into PR, release, or post-deploy smoke.

Default PR validation remains:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
```

The seeded, release, and synthetic projects remain opt-in:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@l3-foundation"
npm run test:e2e -- --project=chromium-seeded --grep "@l3-hard"
npm run test:e2e -- --project=chromium-release
npm run test:e2e -- --project=chromium-synthetic
```

## Phase 13 Normal-Use Hardening

Phase 13 adds `@normal-use` browser scenarios for realistic daily operator behavior. These checks harden normal chatbot usage after L0-L5 and governance are in place, but they do not complete production-grade hardening; that remains Phase 17.

Default mocked normal-use command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium --grep "@normal-use"
```

Opt-in seeded normal-use command:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@normal-use"
```

Coverage:

| Scenario | Project | Spec | Why this layer |
|---|---|---|---|
| 81 ten-turn operator chat | `chromium` | `e2e/specs/normal-use-hardening.spec.js` | UI-heavy transcript, source/detail, table, busy-state, and composer-state checks are deterministic with mocked responses. |
| 82 many historical sessions | `chromium` | `e2e/specs/normal-use-hardening.spec.js` | The mock server seeds many completed sessions and verifies sidebar selection restores the correct transcript without real service startup. |
| 83 reload after completion | `chromium` and `chromium-seeded` | `normal-use-hardening.spec.js`, `full-stack-normal-use.spec.js` | Mocked coverage checks UI persistence; seeded coverage verifies the real Factory Agent snapshot/RAG-source contract. |
| 84 edited draft plus mode switch | `chromium` | `e2e/specs/normal-use-hardening.spec.js` | Request-log assertions prove only the final edited text is sent and that `mode: "plan"` is preserved. |
| 85 repeated open/close across terminal sessions | `chromium` | `e2e/specs/normal-use-hardening.spec.js` | Mocked terminal sessions and SSE connection logs make stream close/leak evidence deterministic. |

Rules:

- Keep memory-specific assertions out of this phase until the memory feature exists.
- Keep default PR CI on `npm run test:e2e -- --project=chromium`; this remains deterministic and mocked.
- Keep `chromium-seeded`, `chromium-release`, and `chromium-synthetic` opt-in unless the team deliberately promotes them.
- Do not use these scenarios to claim production-grade hardening is complete.

## Phase 14 Data Integrity

Phase 14 adds `@data-integrity` scenarios for mutating chatbot workflows. These tests run only in the seeded full-stack project because they deliberately mutate job priorities and then prove the UI, Factory Agent approvals/timeline, seeded audit log, SSE evidence, and real Go API database state agree.

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@data-integrity"
```

Coverage:

| Scenario | Spec | Evidence |
|---|---|---|
| 86 cascading priority update | `e2e/specs/full-stack-data-integrity.spec.js` | Original high-priority jobs become low, original low-priority jobs become medium, original medium-priority jobs remain unchanged, and each write set has a separate approval id. |
| 87 bulk partial failure | `e2e/specs/full-stack-data-integrity.spec.js` | Per-row success/failure outcomes are recorded; the UI and persisted step state do not claim every job succeeded. |
| 88 approval replay safety | `e2e/specs/full-stack-data-integrity.spec.js` | Double-click/refresh/replay evidence shows the approved mutation is applied once. |
| 89 stale/expired approval safety | `e2e/specs/full-stack-data-integrity.spec.js` | Superseded or expired approvals return safe conflicts and do not mutate seeded job data. |
| 90 cross-surface agreement | `e2e/specs/full-stack-data-integrity.spec.js` | Audit entries, DB priorities, approval id, snapshot timeline/activity, SSE connection evidence, and final assistant summary name the same jobs and outcome. |

Rules:

- `@data-integrity` must run against resettable seeded services only. Do not run these mutating checks against production or synthetic live mode.
- Each test resets canonical seeded job priorities before it starts.
- Any mismatch between visible claims and persisted state is a blocking Phase 14 defect unless recorded as an accepted gap with owner, severity, risk, target, reason, and workaround.
- Keep default PR CI on `npm test` plus `npm run test:e2e -- --project=chromium`; `chromium-seeded --grep "@data-integrity"` remains opt-in.
- Keep `chromium-release` and `chromium-synthetic` opt-in. Phase 14 does not complete production-grade hardening; Phase 17 remains the final signoff.

## Seeded Full-Stack L3

Phase 8 adds an opt-in seeded project:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@l3-foundation"
```

`chromium-seeded` starts a real seeded Go API from `emas/cmd/e2e_server`, a real local Factory Agent FastAPI service, and Vite on isolated ports. The frontend receives `VITE_FACTORY_AGENT_BASE_URL` pointing at Factory Agent and `VITE_API_BASE_URL` pointing at the seeded Go API. The Factory Agent receives a per-run SQLite database, `GO_API_BASE_URL`, `OPENAPI_URL`, and deterministic Playwright seeded planner/RAG adapters.

This differs from `chromium`:

| Project | Services | Default PR CI | Model/RAG behavior |
|---|---|---|---|
| `chromium` | Vite + test-only mock Factory Agent HTTP/SSE server | Yes | Fully mocked browser fixtures. |
| `chromium-seeded` | Vite + real Factory Agent + real seeded Go API | No, opt-in L3 gate | Deterministic fake planner/provider/RAG adapters; no real LLM calls. |

Seeded failure artifacts include Playwright trace/screenshots/video plus `test-results/seeded-stack/env-fingerprint.json`, `go-api.log`, `factory-agent.log`, `vite.log`, and `seeded-stack.log`.

## Seeded L3 Hard Scenarios

Phase 9 reuses the `chromium-seeded` project and adds harder seeded-service workflows:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@l3-hard"
```

The `@l3-hard` specs cover scenarios 39-52: ordered multi-step jobs, two-step approval chains, approval rejection and timeout, partial tool failure, malformed schema, duplicate submit, stale/deleted session recovery, out-of-order/duplicate SSE, EventSource reconnect with `Last-Event-ID`, large structured results, two-context session isolation, stream-drop recovery, and no-source RAG fallback.

The hard scenarios stay deterministic. They use the real seeded Go API from `emas/cmd/e2e_server`, real local Factory Agent, and Vite on isolated per-run ports, but Factory Agent runs with Playwright seeded planner/RAG adapters, deterministic summary/tool-selection settings, disabled memory/vector/checkpoint backends, and no real LLM or live RAG provider calls.

Useful Phase 9 diagnostics:

- `test-results/seeded-stack/env-fingerprint.json` records ports, URLs, and DB paths.
- `test-results/seeded-stack/factory-agent.log`, `go-api.log`, `vite.log`, and `seeded-stack.log` capture service output.
- Failed tests retain Playwright trace, screenshot, video, browser console/network failures, and copies of the seeded service logs.
- The seeded Factory Agent exposes `GET /_playwright/sse-connections` only in seeded mode so reconnect tests can assert server-observed `Last-Event-ID` behavior.

Troubleshooting notes:

- If `chromium-seeded` cannot start, inspect `env-fingerprint.json` first, then the three service logs.
- Do not run these hard scenarios against real LLM/RAG credentials; Phase 9 expects deterministic fake planner/provider/RAG behavior.
- Keep default PR validation on `npm run test:e2e -- --project=chromium`; `chromium-seeded --grep "@l3-hard"` is an opt-in L3 gate.

## Release Validation L4

Phase 10 adds an opt-in production-like release gate:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-release
```

`chromium-release` builds the frontend with release-style paths, then starts a local nginx-style proxy in front of the seeded Go API and Factory Agent:

| Path | Release behavior |
|---|---|
| `/` | Serves the production Vite build from `dist/`. |
| `/agent` | Proxies to Factory Agent with the `/agent` prefix stripped. |
| `/api/v1` | Proxies to the seeded Go API. |
| `/__release/precheck` | Release helper diagnostics for env/schema/readiness checks. |
| `/__release/version` | Build/cache/schema compatibility check. |
| `/__release/faults` | Test-only fault toggles for Go API, Factory Agent, and schema mismatch drills. |

The release frontend is compiled with:

```text
VITE_FACTORY_AGENT_BASE_URL=/agent
VITE_API_BASE_URL=/api/v1
VITE_FACTORY_AGENT_BEARER_TOKEN=<test static bearer>
```

The static bearer is intentional: browser `EventSource` cannot attach Authorization headers, so the release gate asserts that EventSource is disabled and snapshot polling remains enabled. The Factory Agent still runs with deterministic Playwright seeded planner/RAG adapters by default; real LLM/RAG calls are not used.

Optional env vars:

- `PLAYWRIGHT_RELEASE_REAL_LLM_SMOKE=1` enables the structural real-provider connectivity smoke. Leave unset for normal release validation.
- `PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL=<url>` runs the rollback smoke against a previous build URL. Defaults to the current local release proxy.
- `PLAYWRIGHT_RELEASE_CHAT_OPEN_BUDGET_MS`, `PLAYWRIGHT_RELEASE_FIRST_PROGRESS_BUDGET_MS`, `PLAYWRIGHT_RELEASE_FINAL_ANSWER_BUDGET_MS`, and `PLAYWRIGHT_RELEASE_LONG_STREAM_BUDGET_MS` tune latency budgets.
- `PLAYWRIGHT_RELEASE_PORT_BASE`, `PLAYWRIGHT_RELEASE_GO_API_PORT`, `PLAYWRIGHT_RELEASE_FACTORY_AGENT_PORT`, and `PLAYWRIGHT_RELEASE_PROXY_PORT` can be used when local ports collide.

Release failure artifacts are under `test-results/` and include Playwright traces, screenshots, video, browser console/network failure attachments, plus release stack files from `test-results/release-stack/`: `env-fingerprint.json`, `go-api.log`, `factory-agent.log`, `release-proxy.log`, `release-stack.log`, and `build.log`.

Troubleshooting notes:

- If startup fails, inspect `test-results/release-stack/env-fingerprint.json` first, then `factory-agent.log`, `go-api.log`, and `release-proxy.log`.
- If `/agent/ready` is not reachable, the release project will not start browser tests.
- If static bearer fallback fails, look for EventSource requests in the Playwright trace; the release suite expects none.
- If a bad env or schema mismatch is suspected, open `/__release/precheck` in the release proxy. The diagnostic page is intentionally visible and fails before browser smoke can claim success.
- Keep this command out of default PR CI unless the team intentionally promotes L4. PR CI remains `npm test` plus `npm run test:e2e -- --project=chromium`.

## Production Synthetic Monitoring L5

Phase 11 adds an opt-in synthetic monitor project:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-synthetic
```

By default, this runs against the local release-style harness so the command is safe to verify without real production/staging credentials. It still behaves like a production monitor: it opens the production-built app, uses `/agent` and `/api/v1` proxy paths, emits machine-readable results, and stores failure-only redacted artifacts.

Live production/staging mode is explicit only:

```powershell
$env:PLAYWRIGHT_SYNTHETIC_LIVE = "1"
$env:PLAYWRIGHT_SYNTHETIC_BASE_URL = "https://staging.example.com"
$env:PLAYWRIGHT_SYNTHETIC_AUTH_TOKEN = "<synthetic read-only token>"
$env:PLAYWRIGHT_SYNTHETIC_OWNER = "chatbot-oncall"
npm run test:e2e -- --project=chromium-synthetic
```

Synthetic env vars:

| Env var | Purpose |
|---|---|
| `PLAYWRIGHT_SYNTHETIC_LIVE=1` | Enables real production/staging mode. Without it, the local release harness is used. |
| `PLAYWRIGHT_SYNTHETIC_BASE_URL` | Required in live mode. App root URL that exposes `/agent`. |
| `PLAYWRIGHT_SYNTHETIC_AUTH_TOKEN` | Required in live mode. Synthetic read-only token used for readiness probes and credential lifecycle checks. |
| `PLAYWRIGHT_SYNTHETIC_OWNER` | Required in live mode. Alert owner written into result records. |
| `PLAYWRIGHT_SYNTHETIC_ALERT_WEBHOOK` | Optional downstream alert sink; the Playwright run writes local alert records either way. |
| `PLAYWRIGHT_SYNTHETIC_*_PROMPT` | Optional safe read-only canary prompt overrides. Keep them read-only. |
| `PLAYWRIGHT_SYNTHETIC_CHAT_OPEN_BUDGET_MS`, `PLAYWRIGHT_SYNTHETIC_FIRST_PROGRESS_BUDGET_MS`, `PLAYWRIGHT_SYNTHETIC_FINAL_ANSWER_BUDGET_MS`, `PLAYWRIGHT_SYNTHETIC_BURN_RATE_WARNING_MS` | Latency budgets and burn-rate warning threshold. |
| `PLAYWRIGHT_SYNTHETIC_FAILURE_ARTIFACT_RETENTION`, `PLAYWRIGHT_SYNTHETIC_RESULT_RETENTION` | Retention notes written into result output. |

Machine-readable output:

- `test-results/synthetic-monitor/synthetic-results.json`
- `test-results/synthetic-monitor/synthetic-results.ndjson`
- `test-results/synthetic-monitor/synthetic-alerts.ndjson`

Alert classifications include `synthetic_timeout`, `backend_unavailable`, `auth_failure`, `provider_outage`, `missing_final_answer`, and `latency_burn_rate`. Results redact bearer tokens, token/query secret fields, API keys, passwords, and secrets before attachments or result files are used for alerting/trend analysis.

Safety and nondeterminism rules:

- Synthetic prompts are read-only health/status/RAG canaries. They do not approve, reject, or execute mutating workflows.
- The monitor never uses broad destructive approval flows in production/staging.
- Real LLM/RAG output is asserted structurally: chat opens, progress appears, final answer is non-empty, optional source metadata is structurally valid, and no fake completion is shown on dependency failure.
- Static bearer deployments may use polling fallback because browser `EventSource` cannot attach Authorization headers; scenario 74 accepts either SSE evidence or polling fallback evidence.

Artifacts:

- `chromium-synthetic` uses `trace: retain-on-failure`, automatic screenshots off, and video off.
- On failure, the synthetic fixture attaches redacted console/network logs, machine-readable result files, and a masked page screenshot where feasible.
- Retention defaults are 7 days for failure artifacts and 90 days for result history unless overridden by env vars.

Troubleshooting notes:

- If local synthetic startup fails, inspect `test-results/release-stack/env-fingerprint.json`, `factory-agent.log`, `go-api.log`, `release-proxy.log`, and `build.log`.
- If live mode fails before tests start, confirm all three required live env vars are present.
- If scenario 76 fails, rotate or replace the synthetic token and check whether the production/staging auth policy changed.
- If scenario 77 alerts, inspect provider/RAG readiness before changing browser assertions; the canary is designed to avoid mutating production data during dependency outages.
- Keep this command out of default PR CI. PR CI remains mocked `chromium`; `chromium-seeded`, `chromium-release`, and `chromium-synthetic` stay opt-in.

## CI Scope

Phase 6 CI runs only the deterministic mocked frontend chatbot E2E suite:

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium
```

The CI workflow does not start the real Go API, real Factory Agent service, Docker, Promptfoo, or an LLM provider. That separation keeps PR feedback deterministic and leaves full-stack/live validation opt-in.

## Factory Agent API Smoke

`npm run factory-agent-smoke` remains a quick API smoke for a real Factory Agent endpoint. It is useful when you want to confirm the HTTP session/message/plan/execute/cancel path outside the browser.

It is superseded by Playwright only for browser validation. Do not use the smoke script as proof that the modal, composer, loading states, EventSource handling, or final DOM rendering work.

## Mock Factory Agent Scenarios

The mock server keeps scenario state per created Factory Agent session. It chooses the active named scenario from the user prompt in `POST /sessions/{id}/messages`, which keeps parallel Chromium tests isolated without relying on one shared global scenario flag.

Named scenarios live in `e2e/mock-server/fixtureStore.js`. Keep them small:

- Add readable prompt constants and shared Factory Agent-shaped builders in `e2e/fixtures/factoryAgentFixtures.js`.
- Add only the scenario hooks needed by the REST lifecycle: `onMessage`, `onPlan`, `onExecute`, and `snapshot`.
- Keep snapshot, timeline, plan, step, and activity fields close to the real Factory Agent contracts.
- Prefer a unique prompt for each scenario so request-log assertions can filter deterministically.

The mock exposes scoped test diagnostics:

- `GET /__test/scenarios` lists available named scenarios.
- `GET /__test/requests?contains=<text>` returns in-memory request logs filtered by prompt/session content.
- `POST /__test/reset` clears all mock sessions and request logs for focused local debugging. Specs should avoid calling it during parallel runs unless they fully own the mock server.
