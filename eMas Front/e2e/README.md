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
