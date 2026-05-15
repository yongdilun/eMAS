# Playwright E2E

Phase 1 browser tests live under `e2e/specs` and run against Vite plus a deterministic test-only Factory Agent mock server.

```powershell
npm run test:e2e -- --project=chromium
```

The Playwright config starts both servers. The app receives `VITE_FACTORY_AGENT_BASE_URL` pointing at `e2e/mock-server/factoryAgentMockServer.js`, so these tests do not require the real Factory Agent, Go backend, Docker, or LLM calls.
