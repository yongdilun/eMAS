# Go Backend Audit Report

Date: 2026-05-15

Scope: Go backend only under this `emas` module. This audit excludes the React frontend and Factory Agent backend except where Go API behavior, OpenAPI, response schema, or data correctness affects them.

## 1. Executive Summary

The Go backend has a recognizable Gin/GORM architecture with separate `handler`, `service`, `repository`, `domain`, and `middleware` packages. Scheduling and AI proposal logic already has meaningful tests and several transaction-aware flows, especially around proposal apply and agent transaction bundles.

The main backend risks are API contract drift, inconsistent JSON response shape, non-transactional multi-write CRUD flows, inventory write safety, and security behavior that trusts request headers for protected scheduling writes.

Highest-priority recommendation:

1. Fix OpenAPI/Swagger drift against actual registered routes.
2. Add contract tests for route parity and response schemas before runtime behavior changes.
3. Add transaction safety around ordinary multi-write operations.
4. Tighten inventory, auth, idempotency, and validation behavior incrementally.

## 2. Current Go Backend Architecture Map

### Main Folders and Packages

- `cmd/emas`: application entry point.
- `internal/router`: Gin route setup and dependency wiring.
- `internal/handler`: HTTP controllers.
- `internal/handler/dto`: request DTOs, query DTOs, and response wrapper.
- `internal/service`: business logic, scheduling logic, AI proposal logic, agent transaction logic.
- `internal/repository`: GORM database access.
- `internal/domain`: GORM models and domain constants.
- `internal/middleware`: request context, auth/role gate, idempotency.
- `internal/e2e`: backend end-to-end tests.
- `internal/testutil`: shared SQLite test setup.
- `docs`: generated Swagger/OpenAPI artifacts.
- `scripts`: Swagger enrichment and seed/helper scripts.

### Runtime API Flow

1. `cmd/emas/main.go` loads config.
2. Runtime connects to MySQL through `repository.InitDB`.
3. `repository.AutoMigrate` runs on startup.
4. `router.Setup` wires repositories, services, handlers, middleware, and `/api/v1` routes.
5. Handlers bind Gin request bodies or query params.
6. Services implement business logic.
7. Repositories execute GORM queries.
8. Handlers return `dto.Response`.

### Important Route Families

- Jobs: `/api/v1/jobs`
- Job steps and slots: `/api/v1/job-steps`, `/api/v1/slots`, `/api/v1/jobs/:id/slots`
- Machines: `/api/v1/machines`
- Processes and process-step materials
- Formulas
- Products and BOM/scheduling definitions
- Inventory materials, expected arrivals, product stock, reservations
- Scheduling readiness, validation, solver preview, training data
- AI scheduling proposals, apply, approval, replenishment, overlap verification
- Agent transaction bundle dry-run and commit
- Reports, dashboard, predictive, settings, reference data

### OpenAPI/Swagger Flow

Swagger artifacts exist in `docs/swagger.json`, `docs/swagger.yaml`, and `docs/docs.go`. Handler comments use swaggo annotations. `scripts/enrich_swagger_id_patterns.py` enriches generated docs with AI ID metadata.

Risk: actual Gin routes and handler annotations are currently out of sync.

### Confusing or Risky Boundaries

- `router.Setup` is a very large composition root and owns most wiring.
- `AIPredictiveService` mixes forecasting, proposal generation, proposal persistence, apply behavior, overlap verification, replenishment, metrics, and scheduling helpers.
- Some public APIs return domain models directly, while others return DTOs or maps.
- Some multi-write operations are transaction-aware; others are not.

## 3. Problems Found

### Problem 1: Swagger/OpenAPI Does Not Match Actual Routes

- Severity: High
- Risk Type: API Contract
- Affected Files/Packages:
  - `internal/router/router.go`
  - `internal/handler/settings_handler.go`
  - `internal/handler/scheduling_handler.go`
  - `internal/handler/reports_handler.go`
  - `internal/handler/formula_handler.go`
  - `docs/swagger.json`
  - `docs/swagger.yaml`
- Evidence:
  - Actual route: `/api/v1/formulas`
  - Documented route: `/api/v1/formula`
  - Actual route: `/api/v1/settings`
  - Documented route: `/api/v1/settings/get` and `/api/v1/settings/update`
  - Actual route: `/api/v1/scheduling/steps/:id/candidate-machines`
  - Documented route: `/api/v1/scheduling/candidate-machines`
  - Actual route: `/api/v1/production-logs`
  - Documented route: `/api/v1/production-log`
- Why This Is a Problem:
  Factory Agent tools generated from OpenAPI may call routes that do not exist.
- Possible Impact:
  Agent tool calls fail with 404, tool names/parameters become wrong, and frontend flows routed through the agent may receive bad final results.
- Recommended Fix:
  Add a route parity contract test comparing Gin registered routes to `docs/swagger.json`, then fix handler annotations and regenerate Swagger.
- Safe Implementation Notes:
  Preserve current runtime routes unless a route is proven wrong. Treat this first as a documentation/contract correction.
- Tests Needed:
  Route-vs-Swagger parity test, OpenAPI generation test, tools.md generation smoke test.
- Rollback Plan:
  Revert annotation and generated docs changes only. Runtime code should remain untouched in this phase.

### Problem 2: Response Schema Is Inconsistent Across Domain Models

- Severity: High
- Risk Type: API Contract / Maintainability
- Affected Files/Packages:
  - `internal/domain/formula.go`
  - `internal/domain/product.go`
  - `internal/domain/machine.go`
  - `internal/domain/inventory.go`
  - `internal/handler/dto/dto.go`
- Evidence:
  Many domain structs do not have explicit JSON tags, while `domain.Job` uses snake_case tags. Generated Swagger therefore describes some fields as lowerCamel/Pascal-style while job APIs return snake_case.
- Why This Is a Problem:
  Consumers cannot rely on a consistent field naming convention across machine, product, formula, inventory, job, and scheduling APIs.
- Possible Impact:
  Factory Agent and frontend parsing can break when endpoints return `MachineID`, `formulaID`, or `job_id` inconsistently.
- Recommended Fix:
  Introduce response DTOs or add explicit JSON tags carefully. Prefer DTOs for public API responses.
- Safe Implementation Notes:
  Treat response field casing changes as contract changes. If existing consumers rely on current casing, support a compatibility window.
- Tests Needed:
  Golden JSON response tests for key machine, product, formula, inventory, job, and scheduling responses.
- Rollback Plan:
  Keep old response fields during transition or revert DTO mapping.

### Problem 3: Multi-Write CRUD Flows Are Not Always Transactional

- Severity: High
- Risk Type: Database / Backend Bug
- Affected Files/Packages:
  - `internal/service/job_service.go`
  - `internal/service/job_slot_service.go`
  - `internal/service/production_log_service.go`
  - `internal/service/maintenance_service.go`
- Evidence:
  Job create writes job, steps, and slots separately. Job delete ignores slot/step delete errors before deleting the job. Production logging creates the production log first, then updates inventory, job step, job, slot, proposal outcome, and ML event with many ignored errors.
- Why This Is a Problem:
  Partial writes can leave inconsistent data if any later operation fails.
- Possible Impact:
  Orphan records, wrong job/slot status, incorrect inventory reservations, and inaccurate scheduling state.
- Recommended Fix:
  Add transaction wrappers around multi-write service operations, starting with job create/delete and production log.
- Safe Implementation Notes:
  Keep public API behavior the same. Only change atomicity and error propagation.
- Tests Needed:
  Forced failure rollback tests for job create/delete and production log.
- Rollback Plan:
  Revert transaction wrapper while preserving existing service method signatures.

### Problem 4: Inventory Consume Can Oversubtract Stock and Persist Partial State

- Severity: High
- Risk Type: Backend Bug / Database
- Affected Files/Packages:
  - `internal/service/inventory_service.go`
  - `internal/repository/inventory_repo.go`
- Evidence:
  `ConsumeMaterial` subtracts quantity from `CurrentStock`, updates material, then creates a transaction record separately. There is no stock floor, row lock, transaction, or reservation validation.
- Why This Is a Problem:
  Concurrent consumes or failed transaction creation can leave material stock incorrect or negative.
- Possible Impact:
  Bad material readiness, false scheduling feasibility, and incorrect inventory reports.
- Recommended Fix:
  Validate available stock, update stock and create transaction in one transaction, and use row-level locking where supported by MySQL.
- Safe Implementation Notes:
  If negative stock is intended, make it explicit through configuration and response metadata.
- Tests Needed:
  Insufficient stock, concurrent consume, transaction failure rollback.
- Rollback Plan:
  Add strict stock behavior behind a feature flag before making it default.

### Problem 5: Protected Scheduling Writes Trust Headers and Default Missing Role to Planner

- Severity: High
- Risk Type: Security
- Affected Files/Packages:
  - `internal/middleware/auth.go`
  - `pkg/featureflags/flags.go`
  - protected routes in `internal/router/router.go`
- Evidence:
  Missing `X-User-Id` becomes `system`, and missing `X-User-Role` becomes `planner`. `planner` is allowed for protected scheduling writes when auth is required.
- Why This Is a Problem:
  Unless an upstream gateway authenticates and injects trusted headers, clients can perform planner-level operations.
- Possible Impact:
  Unauthorized proposal apply, reschedule, replenishment, and scheduling settings updates.
- Recommended Fix:
  When auth is enabled, require a trusted identity and role. Default role should only exist in explicit test/local mode.
- Safe Implementation Notes:
  Verify deployment gateway assumptions before changing production behavior.
- Tests Needed:
  Missing identity, missing role, invalid role, allowed role.
- Rollback Plan:
  Use a temporary compatibility feature flag.

### Problem 6: Idempotency Is Partial and Race-Prone

- Severity: Medium
- Risk Type: Idempotency / Write Safety
- Affected Files/Packages:
  - `internal/middleware/idempotency.go`
  - `internal/service/agent_transaction_service.go`
  - `internal/handler/agent_transaction_handler.go`
- Evidence:
  Idempotency middleware only activates when the `Idempotency-Key` header exists. It ignores the final `db.Create` error. Agent commit requires a bundle key but does not persist/replay body-only bundle keys independently from middleware.
- Why This Is a Problem:
  Retried writes can duplicate data if the header is absent or if concurrent same-key requests race.
- Possible Impact:
  Duplicate jobs, stock movements, scheduling applies, or partial bundle confusion.
- Recommended Fix:
  Enforce idempotency keys on critical write endpoints and persist bundle-level idempotency in service logic.
- Safe Implementation Notes:
  Start with warnings and metrics before hard enforcement, except for agent transaction commit.
- Tests Needed:
  Same key/same payload, same key/different payload, concurrent same key, body key without header.
- Rollback Plan:
  Disable strict enforcement through a temporary feature flag.

### Problem 7: Validation and Error Statuses Are Inconsistent

- Severity: Medium
- Risk Type: API Contract / Backend Bug
- Affected Files/Packages:
  - `internal/handler`
  - `internal/service/job_service.go`
  - `internal/service/job_slot_service.go`
  - `internal/service/machine_service.go`
  - `internal/service/maintenance_service.go`
- Evidence:
  Invalid job deadline silently defaults to 24 hours. Slot start parsing ignores errors. Maintenance/downtime can have zero or negative duration. Many business validation errors become HTTP 500.
- Why This Is a Problem:
  Clients and agents cannot distinguish validation errors, conflicts, not-found errors, and server failures.
- Possible Impact:
  Bad data accepted, unnecessary retries, poor agent recovery.
- Recommended Fix:
  Introduce a small backend error taxonomy and central handler mapper.
- Safe Implementation Notes:
  Migrate endpoint families gradually.
- Tests Needed:
  Invalid date, invalid time range, not found, conflict, validation failure.
- Rollback Plan:
  Revert mapper integration route family by route family.

### Problem 8: Runtime AutoMigrate Has Limited Rollback Safety

- Severity: Medium
- Risk Type: Database / Deployment
- Affected Files/Packages:
  - `cmd/emas/main.go`
  - `internal/repository/migrate.go`
- Evidence:
  Application startup runs GORM `AutoMigrate`. The ML training event migration includes manual primary key/index changes.
- Why This Is a Problem:
  Schema changes happen at app startup without versioned migration history or down scripts.
- Possible Impact:
  Failed deploys, schema drift, difficult rollback.
- Recommended Fix:
  Move production schema changes to versioned migrations. Keep `AutoMigrate` for tests/local only.
- Safe Implementation Notes:
  Do not remove `AutoMigrate` until deployment scripts are ready.
- Tests Needed:
  Migration up/down on empty DB and existing DB snapshot.
- Rollback Plan:
  DB snapshot before migration and explicit down scripts.

### Problem 9: Handler Test Package Timed Out as a Full Package

- Severity: Medium
- Risk Type: Testing
- Affected Files/Packages:
  - `internal/handler`
  - `internal/testutil/setup.go`
- Evidence:
  `go test ./internal/service -count=1` passed quickly. `go test ./internal/e2e -count=1` passed quickly. `go test ./internal/handler -count=1` timed out after 180 seconds during audit.
- Why This Is a Problem:
  API regression tests are not reliable enough for safe backend refactoring.
- Possible Impact:
  CI blind spots or delayed feedback.
- Recommended Fix:
  Bisect slow tests, add package-level timeout discipline, and isolate expensive tests behind integration tags if needed.
- Safe Implementation Notes:
  Do not delete tests. Make runtime predictable.
- Tests Needed:
  CI command that completes under a fixed budget.
- Rollback Plan:
  Restore previous test setup if isolation changes create flakiness.

## 4. API Contract and OpenAPI Gap Analysis

Audited actual route registrations against `docs/swagger.json`.

- Actual route count observed: 138
- Documented Swagger operation count observed: 128

Representative gaps:

| Area | Actual Behavior | Documented Behavior | Risk | Recommended Fix |
|---|---|---|---|---|
| Formula | `/formulas` | `/formula` | Agent 404 | Fix annotations, regenerate Swagger |
| Settings | `/settings` | `/settings/get`, `/settings/update` | Agent 404 | Fix annotations |
| Candidate machines | `/scheduling/steps/{id}/candidate-machines` | `/scheduling/candidate-machines` | Missing path parameter | Fix annotation |
| Earliest completion | `/scheduling/jobs/{id}/earliest-completion` | `/scheduling/estimate-job-completion` | Wrong tool metadata | Fix annotation |
| Production logs | `/production-logs` | `/production-log` | Wrong endpoint | Fix annotation |
| Reports | `/reports/oee`, `/reports/bottlenecks` | `/reports/oee-trends`, `/reports/bottleneck-forecast` | Wrong endpoint | Fix annotation |
| Chatbot approvals | `/ai/chatbot/approvals/...` | `/chatbot/approval/...` | Wrong namespace | Fix annotation |
| Response fields | Mixed field styles | Domain-derived Swagger fields | Parser breakage | DTOs or explicit JSON tags |
| Error response | Mostly `dto.Response`, middleware sometimes raw `{"error": ...}` | Generic `dto.Response` | Inconsistent agent handling | Standardize envelope |

tools.md generation should not be trusted until route parity and schema tests are added.

## 5. Backend Testing Gap Analysis

### Useful Tests

- Handler CRUD tests exist for jobs, machines, inventory, products, process, reports, settings, scheduling, and AI scheduling.
- Service tests cover many scheduling and proposal helper behaviors.
- E2E tests cover transaction rollback and seed pipeline behavior.

### Weak or Shallow Tests

- Many handler tests assert status codes but not full response schemas.
- SQLite test database does not expose all MySQL concurrency and locking behavior.
- Shared in-memory DB can hide isolation problems.

### Misleading Tests

- Handler package test list succeeds quickly, but the full package timed out during audit.
- Tests do not consistently detect JSON casing drift.

### Missing Critical Tests

- Route-vs-OpenAPI parity.
- tools.md generation compatibility.
- Inventory negative stock and concurrent consume.
- Transaction rollback for job create/delete and production logs.
- Auth missing-header denial.
- Maintenance/downtime time-window validation.
- Golden response schemas for machine/job/scheduling/inventory APIs.

## 6. Recommended Go Backend Test Strategy

### Unit Tests

- Validators for dates, IDs, statuses, quantities, and time ranges.
- DTO/domain response mapping.
- Scheduling overlap, precedence, calendar, and maintenance helpers.
- Error mapping and response envelope formatting.
- Service-layer pure scheduling and inventory rules.

### Integration Tests

- API handler to DB for machine, job, inventory, scheduling, and production-log flows.
- Service-to-repository transaction behavior.
- Scheduling writes and inventory reservation writes.
- Machine/job CRUD with validation and not-found behavior.
- Error handling with a test database.

### Contract Tests

- OpenAPI paths/methods match actual Gin routes.
- Required fields, query params, path params, and request bodies are documented.
- API response golden files match actual JSON.
- tools.md generation receives correct metadata and ID patterns.
- Agent-required fields are present.

### Regression Tests

- Wrong endpoint in Swagger.
- Missing response field.
- Incorrect status code.
- Invalid validation acceptance.
- Scheduling overlap, maintenance, and calendar rejection.

## 7. Phased Go Backend Fix Plan

### Phase 0: Safety Preparation

- Goal: establish baseline.
- What to change: create branch, run tests, snapshot Swagger, record key API responses.
- What not to change: runtime behavior.
- Risk level: Low.
- Expected benefit: rollback clarity.
- Verification steps:
  - `go test ./internal/service -count=1`
  - `go test ./internal/e2e -count=1`
  - narrowed handler tests
  - Docker Compose health check

### Phase 1: Low-Risk Cleanup

- Goal: remove documentation and contract ambiguity.
- What to change: add route-vs-Swagger contract test, correct stale annotations.
- What not to change: actual routes or business behavior.
- Risk level: Low.
- Expected benefit: Factory Agent receives accurate tool metadata.
- Verification steps:
  - route parity test
  - regenerated Swagger diff review

### Phase 2: API and Contract Fixes

- Goal: make public contracts stable.
- What to change: response schemas, error envelope docs, missing fields, wrong status documentation.
- What not to change: route behavior unless a route is clearly wrong.
- Risk level: Medium.
- Expected benefit: fewer frontend and agent parsing bugs.
- Verification steps:
  - golden response tests
  - tools.md smoke generation
  - agent calls against key endpoints

### Phase 3: Backend Test Improvement

- Goal: protect behavior before deeper refactoring.
- What to change: unit tests, integration tests, contract tests, regression tests.
- What not to change: production behavior.
- Risk level: Low to Medium.
- Expected benefit: safer refactors and clearer CI signal.
- Verification steps:
  - full backend test suite completes under fixed timeout
  - contract test coverage for key flows

### Phase 4: Backend Architecture Refactoring

- Goal: reduce data integrity and maintainability risk.
- What to change: transaction wrappers, error mapper, DTO mappers, clearer service boundaries.
- What not to change: public behavior except clearly identified bugs.
- Risk level: Medium.
- Expected benefit: fewer partial writes and clearer API ownership.
- Verification steps:
  - rollback tests
  - contract tests
  - scheduling regression tests

### Phase 5: Long-Term Improvements

- Goal: operational maturity.
- What to change: versioned migrations, stronger auth integration, observability, performance profiling, deployment docs.
- What not to change: core scheduling algorithm without regression protection.
- Risk level: Medium.
- Expected benefit: safer releases and better production debugging.
- Verification steps:
  - migration dry run
  - load/performance smoke tests
  - logging/metrics checks

## 8. Priority Table

| Priority | Issue | Severity | Risk | Recommended Phase | Expected Benefit |
|---|---|---|---|---|---|
| P0 | Swagger route drift | High | API Contract | Phase 1-2 | Agent calls correct tools |
| P0 | Response schema inconsistency | High | API Contract | Phase 2 | Fewer parser bugs |
| P0 | Inventory oversubtract/non-atomic writes | High | Database | Phase 3-4 | Prevent bad stock state |
| P0 | Header-based role defaults | High | Security | Phase 2-3 | Prevent unauthorized writes |
| P1 | Multi-write CRUD without transactions | High | Database | Phase 4 | Prevent partial writes |
| P1 | Idempotency gaps | Medium | Write Safety | Phase 3-4 | Safer retries |
| P1 | Validation/status inconsistency | Medium | API Reliability | Phase 2-3 | Better client recovery |
| P2 | Runtime AutoMigrate in production path | Medium | Deployment | Phase 5 | Safer releases |
| P2 | Handler package timeout | Medium | Testing | Phase 3 | Reliable CI |

## 9. Safe Execution Checklist

Before changing Go backend code:

- Create or switch to a feature branch.
- Run current Go tests.
- Record current API behavior.
- Snapshot `docs/swagger.json` and `docs/swagger.yaml`.
- Apply the smallest possible change.
- Run Go tests again.
- Run backend integration tests.
- Check Docker Compose startup.
- Check Factory Agent can still call backend APIs.
- Regenerate tools.md if OpenAPI changes.
- Commit with clear message.
- Keep rollback possible.

## 10. Final Recommendation

Fix first: OpenAPI/Swagger drift and response schema contract tests. This will reduce Factory Agent and frontend API bugs fastest.

Fix next: inventory write safety, auth defaults, and transactions around ordinary multi-write operations.

Delay: broad service decomposition and migration-system replacement until contract tests and rollback tests exist.

Risky to touch now: scheduler proposal apply internals. They already have transaction-aware code and specialized tests, so add contract/regression protection before refactoring them.

