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
| Existing service tests checked | Done | `go test ./internal/service -count=1` passed during audit and again on `audit/go-backend-phase-0` on 2026-05-15. |
| Existing e2e tests checked | Done | `go test ./internal/e2e -count=1` passed during audit and again on `audit/go-backend-phase-0` on 2026-05-15. |
| Full handler package checked | Blocked | `go test ./internal/handler -count=1 -timeout 180s -v` timed out. Bisection identified `TestAISchedulingHandler_Features` and `TestRealSolverProposalLifecycle` as proposal apply-by-ID timeout blockers on the shared SQLite test DB. |
| Swagger snapshot recorded | Done | Phase 0 snapshots saved under `docs/audit/phase0/swagger/`. |
| Docker Compose startup verified | Blocked | Non-invasive Compose checks only: worktree lacks `.env`, `emas/.env`, and `factory-agent/.env`; no Compose containers are running for this worktree. Startup was not attempted to avoid affecting other active chats/worktrees. |

## Phase 0: Safety Preparation

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Create backend fix branch | Done | Codex | Created `audit/go-backend-phase-0` from `audit/go-backend` at `afdb661`. |
| Run `go test ./internal/service -count=1` | Done | Codex | Passed on 2026-05-15. |
| Run `go test ./internal/e2e -count=1` | Done | Codex | Passed on 2026-05-15. |
| Bisect `internal/handler` timeout | Done | Codex | Full package timed out at `TestAISchedulingHandler_Features`; individual sweep also found `TestRealSolverProposalLifecycle` times out. All other individual handler tests passed with 60s timeouts. |
| Record key API response samples | Done | Codex | Samples saved under `docs/audit/phase0/api_responses/`; generated via `EMAS_CAPTURE_PHASE0_BASELINE=1 go test ./internal/audit -run TestCapturePhase0BaselineResponses -count=1 -v`. |
| Snapshot Swagger files | Done | Codex | Copied current `docs/swagger.json` and `docs/swagger.yaml` to `docs/audit/phase0/swagger/`. |
| Verify Docker Compose health | Blocked | Codex | Compose config requires missing worktree env files; startup not attempted to avoid affecting other active chats/worktrees. |

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

