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

## Manual Failure Promotion

When QA or a developer finds a chatbot failure manually, use the Phase 8 intake template in [`../../docs/qa/manual_prompt_regression_bank.md`](../../docs/qa/manual_prompt_regression_bank.md). The bug must capture the exact prompt or user action, artifact/log/screenshot/trace link, observed behavior, expected behavior, selected existing oracle or proposed new oracle, lowest useful test layer, owner, and severity.

Do not close a chatbot failure as manual-only. Add a failing regression at the lowest useful layer before or with the fix, then record the passing command after the fix. The regression bank or stateful oracle file must map the bug to the test file and command.

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
npm run test:backend-oracles
npm test
npm run test:e2e:mocked
```

The backend oracle command runs the fast Factory Agent schema, manual-bank, state-machine, snapshot/final-response, API/UI-alignment, prompt-regression, summary, and SSE pytest contracts without live services. The seeded, real LangGraph, release, and synthetic projects remain outside the default PR gate:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium-seeded --grep "@l3-foundation"
npm run test:e2e -- --project=chromium-seeded --grep "@l3-hard"
npm run test:e2e:seeded-oracles
npm run test:e2e:real-langgraph
npm run test:e2e:release
npm run test:e2e:synthetic
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
- Keep default PR CI on `npm run test:backend-oracles`, `npm test`, and `npm run test:e2e:mocked`; the browser half remains deterministic and mocked.
- Keep `chromium-seeded`, `chromium-real-langgraph`, `chromium-release`, and `chromium-synthetic` opt-in unless the team deliberately promotes them.
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
- Keep default PR CI on `npm run test:backend-oracles`, `npm test`, and `npm run test:e2e:mocked`; `chromium-seeded --grep "@data-integrity"` remains opt-in.
- Keep `chromium-real-langgraph`, `chromium-release`, and `chromium-synthetic` opt-in. Phase 14 does not complete production-grade hardening; Phase 19 remains the final prompt/workflow robustness signoff.

## Phase 15 Reliability and Soak

Phase 15 adds `@reliability` coverage for concurrent sessions, long streams, large results, slow responses, and soak cleanup. These checks are explicit opt-in or scheduled reliability gates; they are not added to the default PR command.

Default PR validation remains:

```powershell
Set-Location "eMas Front"
npm run test:backend-oracles
npm test
npm run test:e2e:mocked
```

Reliability commands:

```powershell
Set-Location "eMas Front"
npm run test:e2e -- --project=chromium --grep "@reliability"
npm run test:e2e -- --project=chromium-seeded --grep "@reliability"
```

Scenario 95 can also be run as a standalone opt-in soak command:

```powershell
Set-Location "eMas Front"
$env:PLAYWRIGHT_RELIABILITY_SOAK_REPEAT = "2"
node e2e/support/soakRunner.js --repeat 2
```

Coverage:

| Scenario | Project | Spec | Evidence |
|---|---|---|---|
| 91 ten concurrent read-only sessions | `chromium` | `e2e/specs/reliability-soak.spec.js` | Ten isolated browser contexts complete unique read-only prompts, keep distinct session ids, and do not render another session's answer. |
| 92 long stream | `chromium`, seeded cross-check | `reliability-soak.spec.js`, `full-stack-reliability.spec.js` | Many activity events reach `Run complete`, duplicate labels are rejected, busy UI clears, browser resource metrics stay bounded, and stream close evidence is recorded. |
| 93 large result and many sources | `chromium`, seeded cross-check | `reliability-soak.spec.js`, `full-stack-reliability.spec.js` | Large table pagination text, source chips, details disclosure, composer controls, and dialog overflow are asserted. |
| 94 slow response timeout | `chromium` | `reliability-soak.spec.js` | A slow mocked plan exceeds the reliability request timeout, visible progress appears first, and retry plus cancel controls remain usable. |
| 95 repeated soak cleanup | `chromium` plus child smoke commands | `reliability-soak.spec.js`, `e2e/support/soakRunner.js` | Mocked, seeded, and release smoke commands run on isolated ports; child exit codes, leaked ports, and timeout state are recorded in `test-results/reliability-soak/soak-results.json`. |

Rules:

- `@reliability` mocked tests are excluded from un-grepped `chromium` runs so default PR CI remains fast deterministic backend oracles plus mocked Chromium without soak overhead.
- `chromium-seeded`, `chromium-real-langgraph`, `chromium-release`, and `chromium-synthetic` remain opt-in. Scenario 95 invokes release smoke only inside the opt-in soak runner or scheduled reliability workflow.
- The scheduled/dispatch workflow is `.github/workflows/playwright-reliability-soak.yml`; it does not run on pull requests.
- No real LLM dependency is introduced. Seeded and release smoke checks use deterministic fake planner/provider/RAG adapters unless a later phase explicitly opts into real-provider smoke.
- These checks harden reliability risks but do not claim production-grade hardening is complete.

## Phase 16 Security and Privacy

Phase 16 adds opt-in `@security` and `@privacy` checks for session isolation, authorization failures, artifact redaction, unsafe rendered content, large pasted input, and unsupported tool/approval abuse. These checks are excluded from un-grepped mocked Chromium runs so the default PR command stays unchanged.

```powershell
Set-Location "eMas Front"
npm test
npm run test:e2e -- --project=chromium --grep "@security|@privacy"
npm run test:e2e:release -- --grep "@security|@privacy"
```

Coverage:

| Scenario | Project | Spec | Evidence |
|---|---|---|---|
| 96 tampered local storage/session id | `chromium`, release cross-check | `security-privacy.spec.js`, `release-security-privacy.spec.js` | A stored session id for another user returns a safe not-found diagnostic, clears the active id, and never renders the other transcript. |
| 97 unauthorized REST, polling, and EventSource | `chromium`, `chromium-release` | `security-privacy.spec.js`, `release-security-privacy.spec.js` | Missing/wrong auth is denied for session REST, snapshot polling, and EventSource endpoints; visible diagnostics avoid transcript or token leakage. |
| 98 artifact redaction | `chromium`, `chromium-release` | `security-privacy.spec.js`, `release-security-privacy.spec.js`, `artifactRedaction.js` | Logs, report-like attachments, trace URLs, screenshot metadata, session ids, operation ids, bearer tokens, API keys, and token query params are redacted before retention. |
| 99 large unsafe rendered content | `chromium` | `security-privacy.spec.js` | Large pasted text and unsafe markdown/HTML render as inert text, do not execute script/image handlers, and do not collapse the mobile dialog layout. |
| 100 tool allowlist and approval gates | `chromium` | `security-privacy.spec.js` | Unsupported destructive tools are absent from the allowlisted tool response; the UI shows an approval gate and approval is blocked without any fake completion. |

Phase 17 strengthens the same lane with SO-backed security/privacy oracles:

| SO | Project | Spec | Evidence |
|---|---|---|---|
| SO-032 cross-session leakage | `chromium` | `security-privacy.spec.js` scenario 101 | Switching, refreshing, and restoring valid sessions clears another session's final response, approval card, source table, audit evidence, and hidden details. |
| SO-033 authorization failure | `chromium`, `chromium-release` | `security-privacy.spec.js`, `release-security-privacy.spec.js` | Missing/wrong auth for REST, snapshot polling, and EventSource is denied, and auth-failed session switching clears stale assistant responses. |
| SO-042 unsafe rendered content | `chromium` | `security-privacy.spec.js` scenario 99 | Script-like content and unsafe links render inertly as text with no executable script or unsafe anchor behavior. |
| SO-043 large pasted input | `chromium` | `security-privacy.spec.js` scenario 99 | Long pasted prompts stay controlled, submit at the expected length, clear after send, and do not leave stale final text or a stuck spinner. |
| SO-044 unsupported dangerous action | `chromium` | `security-privacy.spec.js` scenario 100 | `delete all production jobs without approval` and `bypass approvals and apply the changes directly` remain approval-gated and end with no mutation, no DELETE request, and no fake completion. |

Rules:

- Keep default PR CI on `npm run test:backend-oracles`, `npm test`, and `npm run test:e2e:mocked`; Phase 16/17 security/privacy coverage is an opt-in grep until deliberately promoted.
- Keep `chromium-seeded`, `chromium-real-langgraph`, `chromium-release`, and `chromium-synthetic` opt-in. The release cross-check is explicit and uses deterministic seeded providers.
- The release harness builds the frontend with `/agent`, `/api/v1`, a signed test JWT bearer, and polling fallback because browser `EventSource` cannot attach Authorization headers.
- Do not store raw bearer tokens, API keys, token query params, session ids, operation ids, approval ids, or trace ids in retained text artifacts.
- No real LLM/RAG dependency is introduced, and Phase 16 does not claim production-grade hardening is complete.

## Phase 17 Operational Readiness

Phase 17 adds opt-in `@operational` checks for alert contracts, rollback URL support, emergency disable behavior, environment recreation, and the final operational gate matrix. These checks are excluded from un-grepped mocked Chromium runs so default PR CI stays unchanged.

```powershell
Set-Location "eMas Front"
npm run test:e2e:operational
npm run operational:gate -- --dry-run
npm run operational:gate
```

Coverage:

| Scenario | Project | Spec/helper | Evidence |
|---|---|---|---|
| 101 synthetic failure alert | `chromium` with `@operational` | `operational-readiness.spec.js`, `syntheticReporter.js`, `operationalGate.js` | Synthetic failure alerts include owner, `critical` severity, message, and `docs/operations/chatbot_synthetic_monitoring.md` runbook link. |
| 102 rollback validation | `chromium` with `@operational`, release gate command | `operationalGate.js` | The rollback command targets `chromium-release` scenario 68 and validates a previous known-good `/__release/precheck` URL. |
| 103 emergency disable | `chromium` with `@operational` | `App.jsx`, `FloatingChatButton.jsx` | `VITE_FACTORY_AGENT_EMERGENCY_DISABLED` keeps the app usable, shows a clear diagnostic, and does not open a Factory Agent session. |
| 104 clean environment recreation | `chromium` with `@operational` | `operationalGate.js` | Seeded, release, and synthetic artifact/env overrides are generated for a fresh DB plus synthetic-account rerun. |
| 105 gate matrix | `chromium` with `@operational`, manual workflow | `operationalGate.js`, `.github/workflows/playwright-operational-readiness.yml` | Matrix covers PR backend/frontend checks, seeded stateful oracles, hard orchestration, real LangGraph proof, release, synthetic, security/privacy, and reliability checks, with critical/high failures blocking signoff. |

Rules:

- Keep `@operational` out of un-grepped `chromium`; use `npm run test:e2e:operational` or the manual workflow.
- Keep `chromium-seeded`, `chromium-real-langgraph`, `chromium-release`, and `chromium-synthetic` opt-in.
- Critical failures block release or require rollback. High failures block operational signoff. Medium gaps require owner, risk, target, reason, and workaround. Low gaps are tracked.
- Phase 17 proves operational readiness gates only. Phase 19 remains the final prompt/workflow robustness signoff.

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
- Keep default PR validation on `npm run test:backend-oracles`, `npm test`, and `npm run test:e2e:mocked`; `chromium-seeded --grep "@l3-hard"` is an opt-in L3 gate.

## Release Validation L4

Phase 10 adds an opt-in production-like release gate:

```powershell
Set-Location "eMas Front"
npm run test:e2e:release
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
VITE_FACTORY_AGENT_BEARER_TOKEN=<signed test JWT bearer>
VITE_FACTORY_AGENT_USER_ID=frontend-operator
```

The signed bearer is intentional: browser `EventSource` cannot attach Authorization headers, so the release gate asserts that EventSource is disabled and snapshot polling remains enabled while REST requests still authenticate. The Factory Agent still runs with deterministic Playwright seeded planner/RAG adapters by default; real LLM/RAG calls are not used.

Optional env vars:

- `PLAYWRIGHT_RELEASE_REAL_LLM_SMOKE=1` enables the structural real-provider connectivity smoke. Leave unset for normal release validation.
- `PLAYWRIGHT_RELEASE_STATIC_BEARER=<jwt>` overrides the generated signed test JWT. If set, it must match `PLAYWRIGHT_RELEASE_JWT_SECRET` because the local Factory Agent enforces JWT auth in the release harness.
- `PLAYWRIGHT_RELEASE_JWT_SECRET=<secret>` overrides the local release JWT signing secret.
- `PLAYWRIGHT_RELEASE_ROLLBACK_BASE_URL=<url>` runs the rollback smoke against a previous build URL. Defaults to the current local release proxy.
- `PLAYWRIGHT_RELEASE_CHAT_OPEN_BUDGET_MS`, `PLAYWRIGHT_RELEASE_FIRST_PROGRESS_BUDGET_MS`, `PLAYWRIGHT_RELEASE_FINAL_ANSWER_BUDGET_MS`, and `PLAYWRIGHT_RELEASE_LONG_STREAM_BUDGET_MS` tune latency budgets.
- `PLAYWRIGHT_RELEASE_PORT_BASE`, `PLAYWRIGHT_RELEASE_GO_API_PORT`, `PLAYWRIGHT_RELEASE_FACTORY_AGENT_PORT`, and `PLAYWRIGHT_RELEASE_PROXY_PORT` can be used when local ports collide.

Release failure artifacts are under `test-results/` and include Playwright traces, screenshots, video, browser console/network failure attachments, plus release stack files from `test-results/release-stack/`: `env-fingerprint.json`, `go-api.log`, `factory-agent.log`, `release-proxy.log`, `release-stack.log`, and `build.log`.

Troubleshooting notes:

- If startup fails, inspect `test-results/release-stack/env-fingerprint.json` first, then `factory-agent.log`, `go-api.log`, and `release-proxy.log`.
- If `/agent/ready` is not reachable, the release project will not start browser tests.
- If static bearer fallback fails, look for EventSource requests in the Playwright trace; the release suite expects none.
- If a bad env or schema mismatch is suspected, open `/__release/precheck` in the release proxy. The diagnostic page is intentionally visible and fails before browser smoke can claim success.
- Keep this command out of default PR CI unless the team intentionally promotes L4. PR CI remains `npm run test:backend-oracles`, `npm test`, and `npm run test:e2e:mocked`.

## Production Synthetic Monitoring L5

Phase 11 adds an opt-in synthetic monitor project:

```powershell
Set-Location "eMas Front"
npm run test:e2e:synthetic
```

By default, this runs against the local release-style harness so the command is safe to verify without real production/staging credentials. It still behaves like a production monitor: it opens the production-built app, uses `/agent` and `/api/v1` proxy paths, emits machine-readable results, and stores failure-only redacted artifacts.

Live production/staging mode is explicit only:

```powershell
$env:PLAYWRIGHT_SYNTHETIC_LIVE = "1"
$env:PLAYWRIGHT_SYNTHETIC_BASE_URL = "https://staging.example.com"
$env:PLAYWRIGHT_SYNTHETIC_AUTH_TOKEN = "<synthetic read-only token>"
$env:PLAYWRIGHT_SYNTHETIC_OWNER = "chatbot-oncall"
npm run test:e2e:synthetic
```

Synthetic env vars:

| Env var | Purpose |
|---|---|
| `PLAYWRIGHT_SYNTHETIC_LIVE=1` | Enables real production/staging mode. Without it, the local release harness is used. |
| `PLAYWRIGHT_SYNTHETIC_BASE_URL` | Required in live mode. App root URL that exposes `/agent`. |
| `PLAYWRIGHT_SYNTHETIC_AUTH_TOKEN` | Required in live mode. Synthetic read-only token used for readiness probes and credential lifecycle checks. |
| `PLAYWRIGHT_SYNTHETIC_OWNER` | Required in live mode. Alert owner written into result records. |
| `PLAYWRIGHT_SYNTHETIC_ALERT_WEBHOOK` | Optional downstream alert sink; the Playwright run writes local alert records either way. |
| `PLAYWRIGHT_SYNTHETIC_RUNBOOK_URL` | Optional runbook URL written into alert records. Defaults to `docs/operations/chatbot_synthetic_monitoring.md#alert-response-runbook`. |
| `PLAYWRIGHT_SYNTHETIC_*_PROMPT` | Optional safe read-only canary prompt overrides. Keep them read-only. |
| `PLAYWRIGHT_SYNTHETIC_CHAT_OPEN_BUDGET_MS`, `PLAYWRIGHT_SYNTHETIC_FIRST_PROGRESS_BUDGET_MS`, `PLAYWRIGHT_SYNTHETIC_FINAL_ANSWER_BUDGET_MS`, `PLAYWRIGHT_SYNTHETIC_BURN_RATE_WARNING_MS` | Latency budgets and burn-rate warning threshold. |
| `PLAYWRIGHT_SYNTHETIC_FAILURE_ARTIFACT_RETENTION`, `PLAYWRIGHT_SYNTHETIC_RESULT_RETENTION` | Retention notes written into result output. |

Machine-readable output:

- `test-results/synthetic-monitor/synthetic-results.json`
- `test-results/synthetic-monitor/synthetic-results.ndjson`
- `test-results/synthetic-monitor/synthetic-alerts.ndjson`

Alert classifications include `synthetic_timeout`, `backend_unavailable`, `auth_failure`, `provider_outage`, `missing_final_answer`, and `latency_burn_rate`. Each alert includes owner, severity, message, and runbook link. Results redact bearer tokens, token/query secret fields, API keys, passwords, and secrets before attachments or result files are used for alerting/trend analysis.

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
- Keep this command out of default PR CI. PR CI remains fast backend oracles plus mocked `chromium`; `chromium-seeded`, `chromium-real-langgraph`, `chromium-release`, and `chromium-synthetic` stay opt-in or release-gated.

## CI Scope

Phase 9 CI uses a split gate model. The default PR gate is fast and deterministic:

```powershell
Set-Location "eMas Front"
npm run test:backend-oracles
npm test
npm run test:e2e:mocked
```

The PR gate does not start the real Go API, real Factory Agent service, Docker, Promptfoo, real LangGraph browser stack, production synthetic live mode, or an LLM provider. That separation keeps PR feedback deterministic while still blocking broken backend oracle, schema, manual-bank, state-machine, snapshot/final-response, prompt-regression, summary, and SSE invariants.

Seeded full-stack oracles are release/pre-merge or explicit opt-in gates:

```powershell
Set-Location "eMas Front"
npm run test:e2e:seeded-oracles
```

Real LangGraph browser proof remains explicit opt-in or release-gated:

```powershell
Set-Location "eMas Front"
npm run test:e2e:real-langgraph
```

Production synthetic checks stay read-only. The default synthetic command uses the local release harness; live production/staging mode requires explicit read-only synthetic credentials and read-only prompts:

```powershell
Set-Location "eMas Front"
npm run test:e2e:synthetic
```

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
