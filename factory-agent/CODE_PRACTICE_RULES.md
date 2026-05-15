# Factory Agent Code Practice Rules

Purpose: Rules for this cleanup and future FastAPI/backend work. These rules are meant to preserve behavior while improving maintainability, safety, and testability.

## 1. Change Safety

- Do not rewrite working systems unless a smaller safe path is impossible.
- Prefer small, reversible changes.
- Keep public API paths and response models stable unless a contract change is explicitly approved.
- Before changing behavior, add or identify a test that proves the current behavior.
- Every risky change must have a rollback plan.
- Do not mix cleanup, behavior change, and refactor in the same commit unless they cannot be separated.

## 2. API Contracts

- Every route must have an intentional auth policy.
- Every route must have an explicit request/response contract where practical.
- Do not expose operational data through unauthenticated endpoints.
- SSE endpoints must define:
  - auth method
  - reconnect behavior
  - heartbeat behavior
  - disconnect handling
  - expected client fallback
- Retired endpoints should return explicit status codes and clear messages until consumers are migrated.

## 3. FastAPI Route Design

- Route handlers should be thin.
- Route handlers may:
  - validate request-level inputs
  - call services
  - map known service errors to HTTP errors
  - return response models
- Route handlers should not contain large business flows, graph orchestration, or complex projection logic.
- Group routers by responsibility:
  - sessions
  - messages
  - plans
  - approvals
  - events
  - snapshots
  - admin
- Shared dependencies belong in `factory_agent/api/dependencies.py` or a clearly named dependency module.

## 4. Service and Module Boundaries

- Put business behavior behind service modules with small public interfaces.
- Keep persistence details out of route handlers where practical.
- Keep projection code separate from mutation code.
- Keep graph orchestration separate from HTTP concerns.
- Keep admin behavior separate from user-facing behavior.
- Prefer clear module names over generic utility modules.

## 5. Database and Transactions

- Related writes should be atomic.
- Prefer one transaction for one business operation.
- Use `flush()` when IDs are needed before commit.
- Publish external events only after the database transaction succeeds.
- Do not run production schema mutation implicitly during app startup.
- Use explicit migrations for schema changes.
- Avoid mutable ORM defaults such as `default={}` and `default=[]`; use callables such as `default=dict` and `default=list`.
- Add deletion tests whenever adding session-owned tables.

## 6. Security and Configuration

- Production mode must fail fast if required secrets or auth settings are missing.
- Default admin keys are allowed only for local development.
- JWT-disabled mode is allowed only for local development and isolated tests.
- Metrics exposure must be intentional and documented.
- Tool payloads, approval details, DLQ contents, session timelines, and checkpoint-derived state are sensitive unless proven otherwise.
- Do not rely on CORS as an auth boundary.

## 7. Planner, Graph, and Approval Flow

- Treat LangGraph planner semantics as high-risk.
- Do not change planner routing, checkpointing, approval resume, or commit behavior without regression tests.
- Approval writes must be auditable.
- Approval decision handling must be atomic with visible session state changes.
- Write execution must not happen before validation, dry-run checks, and approval rules pass.
- Preserve graph-native behavior when retiring legacy compatibility behavior.

## 8. Testing Rules

- Add tests before risky fixes when the expected behavior is not already covered.
- Minimum tests for API contract changes:
  - unauthorized request
  - authorized request
  - response shape
  - error shape
  - rollback behavior if writes occur
- Minimum tests for route refactors:
  - OpenAPI diff or endpoint contract snapshot
  - targeted route tests
  - relevant planner/approval regression tests
- Live LLM, Redis, and MySQL tests may remain opt-in, but local unit tests must cover fallback behavior.
- Avoid tests that depend on execution order or shared mutable state.

## 9. Observability

- Log structured events for important lifecycle transitions.
- Avoid logging secrets, JWTs, raw auth headers, or sensitive tool payloads.
- Metrics should measure useful operational behavior:
  - request failures
  - planner failures
  - validation failures
  - approval decisions
  - queue pressure
  - DB pool pressure
  - stream disconnects
- Error logs should include enough context to debug without exposing sensitive payloads.

## 10. Deployment and Packaging

- Keep dependency sources aligned.
- Docker images should not include local databases, logs, caches, scratch files, virtual environments, or accidental vector stores unless explicitly required.
- Docker builds should have a smoke test that imports the app.
- Local development artifacts should be ignored by default.
- Runtime-generated files should not be committed unless they are intentional seeded assets.

## 11. Documentation Rules

- Every architecture cleanup phase must update `FASTAPI_FIX_PROGRESS.md`.
- Any new route auth policy should be documented.
- Any intentional legacy behavior should be documented as active, deprecated, retired, or removed.
- Any production config requirement should be documented near the setting and in operations docs.
- Keep docs factual and tied to files, tests, or observed behavior.

## 12. Review Checklist

Before merging a backend cleanup:

- Did public API behavior stay the same, or is the change documented?
- Are auth requirements explicit?
- Are database writes atomic?
- Are new tests focused and meaningful?
- Did full tests pass?
- Did Docker/import smoke pass if packaging changed?
- Is rollback possible?
- Did the progress tracker get updated?

## 13. React Frontend Practice Rules

Use these rules for work in `../eMas Front`.

### Frontend Safety

- Do not directly refactor working UI without first identifying the current behavior and the risk.
- Prefer small changes that can be reverted independently.
- Do not mix visual cleanup, state behavior changes, API contract changes, and test harness changes in one commit unless they are inseparable.
- Before fixing a UI state bug, add or identify a test that can catch the regression.
- Preserve current working behavior unless the change is explicitly intended to fix a documented bug.
- Do not silently replace missing backend data with demo or mock data in operator-facing screens.
- If demo data is needed, gate it behind an explicit flag and show a visible demo/unavailable label.

### Frontend/API Contracts

- Keep REST API clients separated by backend responsibility.
- Main eMAS API calls belong in the main eMAS client layer.
- Factory Agent calls belong in the Factory Agent client layer.
- Do not duplicate endpoint strings in page components when a service client already owns that endpoint.
- Every response mapper should handle missing, null, partial, and wrapped data intentionally.
- Do not show success copy until the relevant backend operation has actually succeeded.
- Avoid contradictory messages such as "success" and "no match" in the same UI state.
- Snapshot, SSE, and polling behavior must share one documented state model.
- If REST calls use auth, streaming/SSE behavior must have an explicit compatible auth strategy.

### Factory Agent Chat Flow

- Treat the flow as a state machine:
  - user message
  - session create or resume
  - message persisted
  - plan created
  - execution started
  - snapshot/SSE/polling updates
  - approval required if needed
  - approval or rejection
  - resumed execution or stopped state
  - final answer
- Do not clear an approval card unless the UI also has a trustworthy next state.
- Approval approve and reject paths should both refresh or otherwise confirm fresh session state.
- Pending approval follow-up messages must make stale approval behavior explicit.
- Do not display stale tables when the final narrative describes a newer committed state.
- Do not display raw internal planner/tool text to normal users unless developer mode is enabled.
- Session switching must clear or scope activity rows, approval state, optimistic messages, and stream state correctly.

### Component Boundaries

- Page components should orchestrate data loading and layout, not contain large business logic.
- Shared UI components should not know backend-specific contracts unless intentionally named for that domain.
- Large components should be split only after tests or baseline behavior exist.
- Keep approval form validation separate from approval rendering where practical.
- Keep timeline assembly separate from timeline rendering.
- Keep transport hooks separate from presentation components.
- Prefer explicit helper names over generic "utils" for contract-sensitive logic.

### State Management

- Keep server state snapshot-derived where possible.
- Use optimistic UI only when rollback/error handling is clear.
- Avoid multiple independent sources of truth for the same status.
- Avoid stale local storage restoring deleted or inaccessible sessions.
- Polling and SSE fallback should be active only when useful.
- Loading, retry, blocked, failed, completed, and unavailable states must be distinct.

### Accessibility And Usability

- Do not nest interactive controls inside other interactive controls.
- Use real `button`, `input`, `select`, and `textarea` elements for controls.
- Provide accessible labels for icon-only actions.
- Keyboard users must be able to select, rename, delete, approve, reject, send, cancel, and close.
- Error states should be visible and specific enough to guide recovery.
- Do not hide backend unavailability behind generic success or demo content.

### Frontend Testing

- Keep existing utility tests for timeline, approval display, and turn summaries.
- Add component tests before changing Factory Agent chat behavior.
- Minimum Factory Agent chat test coverage:
  - send message
  - create or resume session
  - snapshot update rendering
  - SSE or polling update handling
  - approval card display
  - approve behavior
  - reject behavior
  - final answer rendering
  - backend unavailable state
  - no stale approval after decision
- Minimum page/data test coverage:
  - loading state
  - empty state
  - backend error state
  - real data display
  - no silent demo data unless explicitly flagged
- Add or maintain an `npm test` script when frontend tests exist.
- Lint should ignore generated artifacts and fail meaningfully on source issues.

### Frontend Rollback Rules

- Every behavior change must have a rollback note in `FRONTEND_FIX_PROGRESS.md`.
- Prefer feature flags for risky transport or stream changes.
- Keep config-only safety changes separate from UI behavior changes when practical.
- Do not remove legacy code until import checks and build verification pass.

### Frontend Phase Window And Worktree Rules

- Use one AI window/thread per frontend phase.
- At the start of each phase, read `FRONTEND_FIX_PROGRESS.md`, `FRONTEND_ARCHITECTURE_AUDIT.md`, and this rules file.
- Use the dedicated worktree `../emas-audit-frontend` for frontend audit/fix work.
- Create the worktree with:

```powershell
git worktree add ../emas-audit-frontend audit/frontend
```

- Use chained branches:
  - `audit/frontend-phase-0` from `audit/frontend`
  - `audit/frontend-phase-1` from `audit/frontend-phase-0`
  - `audit/frontend-phase-2` from `audit/frontend-phase-1`
  - `audit/frontend-phase-3` from `audit/frontend-phase-2`
  - `audit/frontend-phase-4` from `audit/frontend-phase-3`
  - `audit/frontend-phase-5` from `audit/frontend-phase-4`
- Work only on the active phase.
- Do not begin future-phase work in the current phase window.
- Update `FRONTEND_FIX_PROGRESS.md` before and after the phase.
- Commit after completing each phase.
- The next phase must branch from the committed previous phase.

## 14. Frontend Review Checklist

Before merging a frontend cleanup:

- Did current behavior stay the same, or is the behavior change documented?
- Did the change avoid fake success and silent demo data?
- Are missing, null, partial, and error responses handled?
- Are Factory Agent approval states fresh after approve and reject?
- Are SSE and polling states bounded and observable?
- Are tests focused on the risk changed?
- Did `npm test`, lint, and build run or is the blocker documented?
- Did browser behavior get checked for chat, approval, final answer, and error states?
- Is rollback possible?
- Did `FRONTEND_FIX_PROGRESS.md` get updated?
