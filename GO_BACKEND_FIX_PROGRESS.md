# Go Backend Fix Progress Tracker

Date created: 2026-05-15

Purpose: track safe, incremental Go backend fixes from `GO_BACKEND_AUDIT.md`.

Status values:

- Not Started
- In Progress
- Blocked
- Done
- Deferred

## Current Baseline

| Item | Status | Notes |
|---|---|---|
| Audit documented | Done | See `GO_BACKEND_AUDIT.md`. |
| Existing service tests checked | Done | `go test ./internal/service -count=1` passed during audit. |
| Existing e2e tests checked | Done | `go test ./internal/e2e -count=1` passed during audit. |
| Full handler package checked | Blocked | `go test ./internal/handler -count=1` timed out during audit. Needs bisection. |
| Swagger snapshot recorded | Not Started | Snapshot current `docs/swagger.json` and `docs/swagger.yaml` before edits. |
| Docker Compose startup verified | Not Started | Verify before runtime behavior changes. |

## Phase 0: Safety Preparation

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Create backend fix branch | Not Started | TBD | Use normal branch naming convention. |
| Run `go test ./internal/service -count=1` | Done | Codex | Passed during audit. |
| Run `go test ./internal/e2e -count=1` | Done | Codex | Passed during audit. |
| Bisect `internal/handler` timeout | Not Started | TBD | Use `go test ./internal/handler -run TestName -count=1`. |
| Record key API response samples | Not Started | TBD | Jobs, machines, inventory, scheduling, proposals. |
| Snapshot Swagger files | Not Started | TBD | Copy or commit current generated docs before contract fixes. |
| Verify Docker Compose health | Not Started | TBD | `mysql`, `go-api`, `factory-agent`, `frontend`, `nginx`. |

## Phase 1: Low-Risk Contract Cleanup

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Add Gin route vs Swagger parity test | Not Started | TBD | Should initially expose known drift. |
| Correct stale Swagger annotations for formulas | Not Started | TBD | `/formulas`, not `/formula`. |
| Correct stale Swagger annotations for settings | Not Started | TBD | `/settings`, not `/settings/get` or `/settings/update`. |
| Correct stale scheduling route annotations | Not Started | TBD | Candidate machines, earliest completion, training stats/backfill, refresh calendars. |
| Correct stale reports route annotations | Not Started | TBD | `/reports/oee`, `/reports/bottlenecks`. |
| Correct production log annotation | Not Started | TBD | `/production-logs`. |
| Correct chatbot approval annotations | Not Started | TBD | `/ai/chatbot/approvals/...`. |
| Regenerate Swagger | Not Started | TBD | Run the repo's Swagger generation flow. |
| Run tools.md generation smoke test | Not Started | TBD | Confirm Factory Agent receives correct paths. |

## Phase 2: API and Contract Fixes

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Decide public JSON field naming rule | Not Started | TBD | Prefer snake_case for API response DTOs. |
| Add golden response tests for jobs | Not Started | TBD | Include `deadline_status`. |
| Add golden response tests for machines | Not Started | TBD | Catch `MachineID` vs `machine_id` drift. |
| Add golden response tests for products/formulas | Not Started | TBD | Catch lowerCamel/Pascal/snake drift. |
| Add golden response tests for inventory | Not Started | TBD | Materials, product stock, reservations. |
| Standardize error envelope | Not Started | TBD | Ensure middleware also returns `dto.Response` shape. |
| Map validation errors to 400/422 consistently | Not Started | TBD | Avoid business validation returning 500. |

## Phase 3: Backend Test Improvement

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Add inventory insufficient-stock tests | Not Started | TBD | Consume should not silently oversubtract unless explicitly allowed. |
| Add inventory transaction rollback tests | Not Started | TBD | Stock update and transaction insert must be atomic. |
| Add job create rollback tests | Not Started | TBD | Job, steps, slots should commit or rollback together. |
| Add production log rollback tests | Not Started | TBD | Log, slot, step, job, inventory updates should be atomic. |
| Add auth protected-route tests | Not Started | TBD | Missing headers should not default to planner in secure mode. |
| Add idempotency concurrency tests | Not Started | TBD | Same key and payload should replay once. |
| Add scheduling overlap/calendar regression tests | Not Started | TBD | Include maintenance and downtime constraints. |

## Phase 4: Backend Architecture Refactoring

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Add transaction wrapper for job create | Not Started | TBD | Keep API response stable. |
| Add transaction wrapper for job delete | Not Started | TBD | Do not ignore child delete errors. |
| Add transaction wrapper for production logs | Not Started | TBD | Avoid partial execution updates. |
| Add transaction-safe inventory consume/receive | Not Started | TBD | Consider row locks under MySQL. |
| Introduce backend error mapper | Not Started | TBD | Small taxonomy: validation, not found, conflict, forbidden, internal. |
| Extract public response DTO mapping | Deferred | TBD | Do after golden response tests. |
| Split oversized AI scheduling service | Deferred | TBD | Only after contract and regression tests. |

## Phase 5: Long-Term Improvements

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Move production schema changes to versioned migrations | Not Started | TBD | Keep `AutoMigrate` for tests/local until migration flow exists. |
| Add structured request logging/correlation IDs | Not Started | TBD | Build on existing request context/logger. |
| Add performance smoke tests for scheduling APIs | Not Started | TBD | Focus batch proposal and reschedule-all. |
| Add deployment rollback notes | Not Started | TBD | Include DB migration rollback. |
| Add API contract release checklist | Not Started | TBD | Include Swagger and tools.md regeneration. |

## Decision Log

| Date | Decision | Reason | Follow-Up |
|---|---|---|---|
| 2026-05-15 | Fix OpenAPI drift before runtime refactors | Factory Agent depends on accurate generated tools. | Add route parity test first. |
| 2026-05-15 | Do not refactor scheduler internals first | Proposal apply has specialized logic and existing tests. | Add regression/contract protection before touching. |
| 2026-05-15 | Prefer incremental transactions over big rewrite | Reduces partial-write risk without changing API behavior. | Start with job and production-log paths. |

## Next Recommended Action

Add a route-vs-Swagger parity test, confirm it fails on the known mismatches, then correct annotations and regenerate Swagger.

