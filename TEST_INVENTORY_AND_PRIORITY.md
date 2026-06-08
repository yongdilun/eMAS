# Test Inventory And Priority

Approx total surfaces by count:

- Python pytest: about 1,101 test definitions
- Go backend: 188 test functions
- Frontend unit/component: about 166 tests
- Playwright E2E specs: about 167 tests
- Factory node benchmarks: 81 scenario cases
- Seed pipeline manifest: 124 scenarios

## Priority Ranking

| Rank | Test surface | Count | Priority | Attribute | Why |
| ---: | --- | ---: | --- | --- | --- |
| 1 | Real LangGraph critical E2E | 6 | P0 | Browser + real frontend + real Factory Agent + real LangGraph + Go API | Highest confidence for actual user workflow. This is now passing. |
| 2 | Planner-owned Python graph tests | subset of Python | P0 | Fast, deterministic graph/runtime contracts | Best for fixing LangGraph/state-machine bugs before browser E2E. |
| 3 | Node benchmark question bank | 81 | P0/P1 | Per-node scenario localization | Best diagnostic layer: tells which node failed instead of only final answer wrong. |
| 4 | Go backend tests | 188 | P0/P1 | API/data/scheduling correctness | Protects seeded Go API and scheduling domain logic. |
| 5 | Mocked Chromium frontend E2E | part of 167 | P1 | Frontend workflow with mocked backend | Good UI regression gate, deterministic, cheaper than full stack. |
| 6 | Frontend unit/component tests | 166 | P1 | Component-level rendering/state | Fast PR gate for UI behavior. |
| 7 | Seed pipeline normal | 124 manifest scenarios | P1 | Go + manifest + seeded contracts | Useful backend/API scenario coverage. |
| 8 | Seeded full-stack Playwright | part of 167 | P1/P2 | Frontend + seeded stack | Valuable, but more brittle/slower than real-LangGraph critical lane. |
| 9 | Seed pipeline -AgentApi | 63 factory-agent + related scenarios | P2 | Direct Factory Agent HTTP API against seeded Go API | Still useful, not deprecated, but optional and somewhat stale versus current LangGraph browser proof. |
| 10 | Release E2E | part of 167 | P2 | Proxy/auth/release harness | Useful for deployment config; lower priority for planner correctness. |
| 11 | RAG eval/live RAG | separate opt-in | P2/P3 | Live RAG quality/citation eval | Important for knowledge quality, not core factory graph regression. |
