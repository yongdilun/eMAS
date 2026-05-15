# Go Backend Engineering Rules

Date created: 2026-05-15

Purpose: rules for this backend improvement effort and future Go backend code practice.

## Scope Rules

1. Work only inside the Go backend unless a task explicitly includes another system.
2. Do not modify React frontend or Factory Agent code to mask Go API issues.
3. Mention frontend or Factory Agent only when Go API behavior, OpenAPI, response schema, or data correctness affects them.
4. Preserve current public API behavior unless a bug or contract issue is clearly identified.
5. Avoid broad rewrites. Prefer small, test-backed changes.

## API Contract Rules

1. Actual Gin routes and OpenAPI paths must match.
2. Every public endpoint must document:
   - path parameters
   - query parameters
   - request body
   - success response
   - error response
   - status codes
3. Regenerate Swagger whenever route annotations, DTOs, or response schemas change.
4. Regenerate tools.md when OpenAPI changes and Factory Agent tool metadata depends on it.
5. Public response field names must be intentional and stable. Prefer response DTOs over returning raw GORM models.
6. Do not change response field casing without contract tests and migration notes.
7. Error responses should use one standard envelope:
   - `success: false`
   - `error: string`
   - optional machine-readable details when needed.

## Handler Rules

1. Handlers should bind and validate request input.
2. Handlers should not contain business logic beyond request parsing, response formatting, and status mapping.
3. Handlers should map domain/service errors to correct HTTP status codes.
4. Do not return HTTP 500 for expected validation, conflict, not-found, or forbidden errors.
5. Do not ignore `ShouldBindJSON` errors unless the endpoint explicitly allows an empty body.
6. Empty optional bodies must be documented and tested.

## Service Rules

1. Services own business rules.
2. Services should not silently ignore important repository errors.
3. Multi-write operations must be atomic unless explicitly documented otherwise.
4. Scheduling, inventory, production logging, and proposal apply logic need rollback tests before refactoring.
5. Keep service boundaries clear:
   - job service owns job lifecycle
   - slot service owns slot lifecycle
   - inventory service owns stock movement
   - scheduling service owns feasibility and calendar logic
   - proposal service logic should not grow unrelated reporting behavior
6. Avoid adding more responsibilities to already oversized services without a reason.

## Repository and Database Rules

1. Repositories should hide GORM query details from handlers.
2. Repositories should not swallow errors.
3. Use database transactions for operations that update multiple tables.
4. Use row-level locking or equivalent safety for concurrent inventory and scheduling writes where needed.
5. Avoid runtime production schema changes without versioned migrations.
6. Keep `AutoMigrate` safe for tests/local until a production migration flow replaces it.
7. Data integrity rules should be enforced in both code and database constraints when practical.

## Inventory Rules

1. Stock changes must be atomic with transaction records.
2. Consuming stock must not create negative inventory unless explicitly allowed by a documented rule.
3. Reservation and consume flows must be consistent.
4. Product inventory and material inventory rules must be tested separately.
5. Scheduling feasibility must consider existing reservations, expected arrivals, and planned production consistently.

## Scheduling Rules

1. Slot validation must check:
   - machine overlap
   - downtime
   - maintenance
   - machine calendar
   - global work template
   - resource calendar
   - step precedence
   - quantity constraints
2. Proposal generation and proposal apply must not diverge on feasibility rules.
3. Apply-time validation must remain authoritative even when proposals were generated earlier.
4. Batch scheduling must have deterministic ordering and bounded runtime.
5. Any scheduling algorithm change needs regression tests for overlap, calendar, maintenance, and dependent jobs.

## Idempotency and Write Safety Rules

1. Critical write endpoints should require or strongly encourage idempotency keys.
2. Same idempotency key with same payload should replay the stored response.
3. Same idempotency key with different payload should return conflict.
4. Idempotency persistence errors must not be silently ignored for critical writes.
5. Agent bundle commits must be atomic and idempotent at the bundle level.

## Security Rules

1. Do not trust caller-supplied role headers unless an upstream trusted gateway is guaranteed.
2. Missing user or role should not default to a privileged role in secure mode.
3. Protected scheduling writes must have auth tests.
4. Secrets must come from environment/config, not hardcoded values.
5. CORS, auth, and role behavior must be documented for local and production modes.

## Testing Rules

1. Add tests before or with behavior changes.
2. Prefer focused tests that prove the risky behavior.
3. Required test categories for backend changes:
   - unit tests for pure rules
   - integration tests for handler/service/database flows
   - contract tests for OpenAPI and response shape
   - regression tests for known bugs
4. Contract-changing PRs must include Swagger regeneration and route parity checks.
5. Transaction changes must include rollback tests.
6. Inventory changes must include insufficient-stock and concurrent-write tests where relevant.
7. Scheduling changes must include overlap, calendar, and feasibility tests.
8. Full backend tests must complete under a predictable timeout.

## Rollback Rules

1. Keep each change small enough to revert independently.
2. Separate documentation-only, contract-only, test-only, and behavior-changing commits when possible.
3. Before behavior changes, record current API responses for affected endpoints.
4. Before schema changes, snapshot the database or provide a rollback migration.
5. Use feature flags for risky compatibility changes when current consumers may depend on old behavior.

## Review Checklist

Before merging a Go backend change, confirm:

- Actual routes match Swagger.
- API response shape is tested if public.
- Error statuses are intentional.
- Multi-table writes are transactional.
- Idempotency behavior is considered for writes.
- Auth behavior is covered for protected endpoints.
- Database changes have migration/rollback notes.
- Existing tests pass.
- Docker startup still works if runtime wiring changed.
- Factory Agent tool generation is updated if OpenAPI changed.

