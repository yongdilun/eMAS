# React Frontend Fix Progress

Purpose: Track frontend improvement work from `FRONTEND_ARCHITECTURE_AUDIT.md` without losing rollback safety.

Status key:

- Not Started
- In Progress
- Blocked
- Done
- Deferred

## Baseline

| Item | Status | Owner | Notes |
|---|---|---|---|
| Create frontend fix branch | Done | Codex | Created `audit/frontend-phase-0` from `audit/frontend` in `../emas-audit-frontend`. |
| Run current frontend utility tests | Done | Codex | 35 tests passed on 2026-05-15 using direct `node --test` command; rerun on Phase 0 branch also passed. |
| Run current lint | Done | Codex | `npm.cmd run lint` failed with 1085 errors and 26 warnings; generated `playwright-report` is currently included. |
| Run production build | Done | Codex | `npx.cmd vite build --outDir C:\tmp\emas-front-build-phase0-20260515` passed; main JS chunk warning at 618.15 kB. |
| Record current Factory Agent UI behavior | Done | Codex | Browser notes recorded in `factory-agent/FRONTEND_PHASE0_BASELINE.md`; local screenshots captured under `captures/frontend-phase0/`. Fresh planning currently fails with a 503 connection error, so approve/reject was observed on an existing pending session rather than executing an old approval. |
| Snapshot Factory Agent API examples | Done | Codex | Existing completed/pending snapshots and failed fresh `POST /plans` response recorded in `factory-agent/FRONTEND_PHASE0_BASELINE.md`; full local JSON capture at `captures/frontend-phase0/factory-agent-api-examples.json`. |

## Issue Tracker

| ID | Issue | Severity | Phase | Status | Verification | Rollback |
|---|---|---|---|---|---|---|
| FE-001 | Silent demo/mock data can look real | High | 2 | Not Started | Component tests for API failure and empty state | Re-enable demo fallback behind explicit flag |
| FE-002 | Approval approve path depends on SSE for fresh UI state | High | 2 | Not Started | Approve flow test with no SSE event | Remove direct refresh if needed |
| FE-003 | SSE streams do not share REST bearer-token behavior | High/Medium | 2 | Not Started | Auth-enabled stream/fallback tests | Feature flag SSE off |
| FE-004 | Snapshot event stream runs for inactive sessions | Medium | 2 | Not Started | Hook test for IDLE/COMPLETED stream gating | Restore always-on stream |
| FE-005 | Pending approval follow-up can create a new plan before decision | Medium | 2 | Not Started | Pending approval plus follow-up regression | Disable free-text input while approval pending |
| FE-006 | Approval card dynamic lookup and validation are too broad | Medium | 2-3 | Not Started | Field validation and lookup failure tests | Disable dynamic options only |
| FE-007 | Nested interactive controls in session list | Medium | 5 | Not Started | Keyboard navigation test | Revert session row component |
| FE-008 | Lint/test configuration is not a reliable safety gate | High | 1 | Not Started | `npm test`, lint, build pass or fail meaningfully | Revert config-only changes |
| FE-009 | Dead or stale frontend modules create maintenance risk | Low/Medium | 1 | Not Started | Import check and build | Restore files from git |
| FE-010 | Main bundle is eager and large | Medium | 5 | Not Started | Build chunk-size comparison and route smoke | Revert lazy imports |

## Phase Progress

### Phase 0: Safety Preparation

- Status: Done
- Goal: Freeze current behavior and make rollback easy.
- Completed:
  - Documented frontend architecture audit.
  - Ran current utility tests.
  - Ran lint and recorded failure.
  - Ran production build into `C:\tmp`.
  - Created `audit/frontend-phase-0` from `audit/frontend`.
  - Recorded browser behavior for completed, pending approval, and planner error states.
  - Captured Factory Agent snapshot, pending approval, failed planning, and SSE timeout examples.
- Remaining:
  - None for Phase 0.

### Phase 1: Low-Risk Cleanup

- Status: Not Started
- Goal: Make safety checks useful without changing behavior.
- Candidate changes:
  - Add `npm test` for existing Node tests.
  - Ignore generated artifacts such as `playwright-report`.
  - Identify dead frontend modules.
  - Remove or quarantine stale service wrappers only after import checks.
- Do not change:
  - UI behavior.
  - API payloads.
  - Factory Agent flow.

### Phase 2: UI Bug And Contract Fixes

- Status: Not Started
- Goal: Fix misleading UI and stale state risks.
- Candidate changes:
  - Replace silent demo data with explicit unavailable/demo states.
  - Refresh snapshot after approval approve succeeds.
  - Gate inactive session event streams.
  - Clarify pending approval follow-up behavior.
  - Tighten approval validation.
- Do not change:
  - Backend contracts without agreement.
  - Planner or approval semantics by assumption.

### Phase 3: Frontend Test Improvement

- Status: Not Started
- Goal: Add tests that make UI and state changes safe.
- Candidate changes:
  - Add component tests for Factory Agent chat panel.
  - Add approval card tests.
  - Add activity timeline rendering tests.
  - Add backend unavailable tests.
  - Add no-fake-data tests.
- Do not change:
  - Avoid broad visual snapshot tests unless they are stable and intentional.

### Phase 4: Frontend Architecture Refactoring

- Status: Not Started
- Goal: Reduce coupling after tests exist.
- Candidate changes:
  - Split `useFactoryAgentChat`.
  - Split `FactoryAgentChatPanel`.
  - Move approval lookup logic to explicit helpers.
  - Retire legacy chat modules after verification.
- Do not change:
  - User-visible Factory Agent behavior without regression tests.

### Phase 5: Long-Term Improvements

- Status: Not Started
- Goal: Improve UX, accessibility, observability, and performance.
- Candidate changes:
  - Route-level lazy loading.
  - Lazy-load Factory Agent modal.
  - Accessible session row controls.
  - Better SSE diagnostics.
  - Better backend unavailable and retry UX.
- Do not change:
  - Cosmetic-only styling unless it affects clarity, accessibility, or maintainability.

## Decision Log

| Date | Decision | Reason | Follow-up |
|---|---|---|---|
| 2026-05-15 | Scope audit to React frontend only | User requested frontend-only audit | Do not modify Go backend or Factory Agent backend for frontend fixes unless contract verification is needed |
| 2026-05-15 | Do not start with a rewrite | Current UI has working behavior and focused utility tests | Prefer phased, rollback-safe changes |
| 2026-05-15 | Prioritize misleading UI and stale state first | These are highest user-facing reliability risks | Start with FE-001, FE-002, FE-008 |
| 2026-05-15 | Document before code changes | User requested documentation first | Keep this tracker updated after each fix |
| 2026-05-15 | Fresh Factory Agent planning is unavailable in the local baseline | `POST /sessions/{id}/plans` returned `503 {"detail":{"errors":["Connection error."]}}` during Phase 0 capture | Treat polished planner error UI as a later frontend reliability concern; do not mask backend unavailability with fake success |

## Current Next Step

Phase 0 is complete. Start Phase 1 in a new phase window only.

Phase 1 should:

1. Branch `audit/frontend-phase-1` from committed `audit/frontend-phase-0`.
2. Add `npm test` and lint ignores as Phase 1 safety work.
3. Run tests, lint, and build.
4. Continue to keep UI behavior unchanged.

## Update Rules For This Tracker

- Update status before starting a fix and after finishing it.
- Add the exact verification command and result.
- Keep rollback notes specific.
- If a fix changes backend/frontend contract assumptions, add a decision log entry.
- Do not mark an issue Done until tests or manual verification are recorded.
