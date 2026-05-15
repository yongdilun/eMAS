# Playwright E2E

Browser tests live under `e2e/specs` and run against Vite plus a deterministic test-only Factory Agent mock server.

```powershell
npm run test:e2e -- --project=chromium
```

The Playwright config starts both servers. The app receives `VITE_FACTORY_AGENT_BASE_URL` pointing at `e2e/mock-server/factoryAgentMockServer.js`, so these tests do not require the real Factory Agent, Go backend, Docker, or LLM calls.

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
