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
| Add Gin route vs Swagger parity test | Done | Codex | Added `internal/router/route_swagger_parity_test.go`; `go test ./internal/router -run TestRegisteredRoutesMatchSwagger -count=1 -v` passes after annotation cleanup. |
| Correct stale Swagger annotations for formulas | Done | Codex | Corrected `/formulas`, `/formulas/{id}`, and `/formulas/{id}/ingredients`. |
| Correct stale Swagger annotations for settings | Done | Codex | Corrected `GET/PUT /settings`. |
| Correct stale scheduling route annotations | Done | Codex | Corrected candidate machines, slot validation, earliest completion, training stats/backfill, and refresh calendars. |
| Correct stale reports route annotations | Done | Codex | Corrected `/reports/oee` and `/reports/bottlenecks`; removed unregistered helper annotation. |
| Correct production log annotation | Done | Codex | Corrected `POST /production-logs`. |
| Correct chatbot approval annotations | Done | Codex | Corrected `/ai/chatbot/approvals/...` and `/ai/chats/{id}/approvals`. |
| Regenerate Swagger | Done | Codex | Regenerated `docs/docs.go`, `docs/swagger.json`, and `docs/swagger.yaml`, then ran `scripts/enrich_swagger_id_patterns.py`. |
| Run tools.md generation smoke test | Done | Codex | Non-mutating Factory Agent smoke parsed regenerated Swagger into 138 tools and rendered tools.md in memory; corrected Phase 1 endpoints were present. |

## Phase 2: API and Contract Fixes

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Decide public JSON field naming rule | Done | Codex | Documented in `GO_BACKEND_ENGINEERING_RULES.md`: new public response DTO fields use `snake_case`; legacy raw domain casing stays only with golden contract coverage until intentional migration. |
| Add golden response tests for jobs | Done | Codex | Added `TestAPIContractGoldenJobs`; locks job response shape including `deadline_status`. |
| Add golden response tests for machines | Done | Codex | Added `TestAPIContractGoldenMachines`; captures current legacy raw-domain casing such as `MachineID`. |
| Add golden response tests for products/formulas | Done | Codex | Added `TestAPIContractGoldenProductsAndFormulas`; captures current product/formula response casing. |
| Add golden response tests for inventory | Done | Codex | Added `TestAPIContractGoldenInventory`; covers materials, product stock, and reservations. |
| Standardize error envelope | Done | Codex | Idempotency and auth middleware errors now return `dto.Response{success:false,error:...}`; covered by middleware envelope test. |
| Map validation errors to 400/422 consistently | Done | Codex | Kept binding/syntax errors as 400; mapped semantic invalid time windows for machine downtime and maintenance to 422 with handler tests. Broader service error taxonomy remains Phase 4 scope. |

## Phase 3: Backend Test Improvement

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Add inventory insufficient-stock tests | Done | Codex | Added `TestInventoryConsumeRejectsInsufficientStock`; consume now rejects insufficient material stock and leaves stock/transactions unchanged. |
| Add inventory transaction rollback tests | Done | Codex | Added `TestInventoryConsumeRollsBackStockWhenTransactionInsertFails`; consume/receive stock movement and transaction insert run in one DB transaction. |
| Add job create rollback tests | Done | Codex | Added `TestJobCreateRollsBackWhenStepInsertFails`; job create now rolls back when child step creation fails. |
| Add production log rollback tests | Done | Codex | Added `TestProductionLogRollsBackWhenStepUpdateFails`; production logging now runs critical log/slot/step/job updates in one DB transaction and propagates critical update errors. |
| Add auth protected-route tests | Done | Codex | Added protected-route middleware coverage for missing identity, missing role, invalid role, allowed role, and local auth-disabled defaults. |
| Add idempotency concurrency tests | Done | Codex | Added `TestIdempotencyMiddlewareConcurrentSameKeyExecutesHandlerOnce`; same-key concurrent requests are serialized in-process and replay the first stored response. |
| Add scheduling overlap/calendar regression tests | Done | Codex | Added `TestValidateSlotRejectsOverlapDowntimeMaintenanceAndCalendarRegression`; covers overlap, downtime, maintenance, and machine work-calendar rejection. |

## Phase 4: Backend Architecture Refactoring

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Add transaction wrapper for job create | Done | Codex | Phase 3 wrapper reverified in Phase 4 with `TestJobCreateRollsBackWhenStepInsertFails`; API response remains stable. |
| Add transaction wrapper for job delete | Done | Codex | `JobService.Delete` now deletes slots, steps, and job inside one transaction and propagates child delete errors; covered by `TestJobDeleteRollsBackWhenSlotDeleteFails`. |
| Add transaction wrapper for production logs | Done | Codex | Production log flow continues to run in one transaction and now propagates missing slot, inventory side-effect, proposal outcome, and ML capture errors instead of committing partial execution state; covered by production-log rollback tests. |
| Add transaction-safe inventory consume/receive | Done | Codex | Consume/receive both update stock and transaction records atomically; material rows are fetched with MySQL `FOR UPDATE` locking where supported. Receive rollback coverage added. |
| Introduce backend error mapper | Done | Codex | Added small `apperror` taxonomy and handler mapper for validation, not found, conflict, forbidden, and internal errors; inventory insufficient stock now maps to 409. |
| Extract public response DTO mapping | Deferred | TBD | Do after golden response tests. |
| Split oversized AI scheduling service | Deferred | TBD | Only after contract and regression tests. |

## Phase 5: Long-Term Improvements

| Task | Status | Owner | Evidence / Notes |
|---|---|---|---|
| Move production schema changes to versioned migrations | Done | Codex | Added `EMAS_AUTO_MIGRATE=false` startup switch, documented migration safety in `docs/operations/migration_safety.md`, and captured the current `ml_training_events` production schema change as `migrations/002_ml_training_events_lineage.sql`. `AutoMigrate` remains enabled by default for tests/local. |
| Add structured request logging/correlation IDs | Done | Codex | `RequestContext` now propagates `X-Request-Id` and `X-Correlation-Id`, emits structured Zap request logs with route/status/latency/client fields, exposes correlation headers via CORS, and router uses structured logging plus recovery instead of Gin's plaintext logger. Covered by `go test ./internal/middleware -count=1`. |
| Add performance smoke tests for scheduling APIs | Done | Codex | Added `TestAISchedulingPerformanceSmokeBatchProposalsAndRescheduleAll` for `batch-proposals` and `reschedule-all` dry-run; documented command in `docs/operations/performance_smoke_tests.md`. |
| Add deployment rollback notes | Done | Codex | Added `docs/operations/deployment_rollback.md` with DB snapshot, forward-compatible rollback, OpenAPI/tools, health, and structured-log checks. |
| Add API contract release checklist | Done | Codex | Added `docs/operations/api_contract_release_checklist.md` covering route parity, response shape, error envelopes, Swagger, tools.md, and release note expectations. |

## Decision Log

| Date | Decision | Reason | Follow-Up |
|---|---|---|---|
| 2026-05-15 | Fix OpenAPI drift before runtime refactors | Factory Agent depends on accurate generated tools. | Add route parity test first. |
| 2026-05-15 | Do not refactor scheduler internals first | Proposal apply has specialized logic and existing tests. | Add regression/contract protection before touching. |
| 2026-05-15 | Prefer incremental transactions over big rewrite | Reduces partial-write risk without changing API behavior. | Start with job and production-log paths. |
| 2026-05-15 | Use snake_case for new public response DTO fields while preserving tested legacy raw-domain responses | Prevents silent casing drift without forcing a broad breaking response migration in Phase 2. | Migrate raw domain responses behind explicit DTO mapping in a later phase. |
| 2026-05-15 | Allow Phase 3 tests to drive the smallest runtime safety fixes | Rollback and security tests exposed clear bugs that would leave partial state or authorize missing headers. | Phase 4 can broaden the same patterns to remaining multi-write flows. |
| 2026-05-15 | Keep AutoMigrate enabled by default but make it explicitly disableable for production | Preserves test/local bootstrap behavior while allowing reviewed SQL migrations and safer rollback in deployed environments. | Adopt a migration runner before disabling AutoMigrate by default. |

## Next Recommended Action

Phase 5 is complete. Next recommended action: choose whether to adopt a formal Go migration runner before disabling `AutoMigrate` by default in production.

