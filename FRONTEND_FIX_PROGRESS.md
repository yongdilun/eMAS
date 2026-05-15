# React Frontend Fix Progress

Purpose: Track frontend improvement work from `FRONTEND_ARCHITECTURE_AUDIT.md` without losing rollback safety.

Use one AI window/thread per phase. Each phase must start by reading this tracker, identifying the active phase, checking the previous phase status, using the correct worktree/branch base, completing only that phase, updating this file, and committing before stopping.

Status key:

- Not Started
- In Progress
- Blocked
- Done
- Deferred

## Worktree And Branch Strategy

Use a dedicated worktree for frontend audit/fix work:

```powershell
git worktree add ../emas-audit-frontend audit/frontend
```

Branch chain:

- Phase 0 branch: `audit/frontend-phase-0`
- Phase 1 branch: `audit/frontend-phase-1`, based on completed Phase 0 branch.
- Phase 2 branch: `audit/frontend-phase-2`, based on completed Phase 1 branch.
- Phase 3 branch: `audit/frontend-phase-3`, based on completed Phase 2 branch.
- Phase 4 branch: `audit/frontend-phase-4`, based on completed Phase 3 branch.
- Phase 5 branch: `audit/frontend-phase-5`, based on completed Phase 4 branch.

Rule: commit after each phase is complete. Do not start the next phase until the current phase is committed and this tracker is updated.

Suggested branch commands after the worktree exists:

```powershell
git switch -c audit/frontend-phase-0
git switch -c audit/frontend-phase-1 audit/frontend-phase-0
git switch -c audit/frontend-phase-2 audit/frontend-phase-1
git switch -c audit/frontend-phase-3 audit/frontend-phase-2
git switch -c audit/frontend-phase-4 audit/frontend-phase-3
git switch -c audit/frontend-phase-5 audit/frontend-phase-4
```

If a branch already exists, switch to it instead of recreating it. Before starting, check `git status --short` and do not overwrite unrelated user changes.

## Phase Window Prompt Template

Use this prompt when opening a new AI window for a phase:

```text
You are working on the React frontend audit/fix plan for eMAS.

Scope:
- React frontend only: ../eMas Front
- Tracking docs are in the repo root:
  - FRONTEND_ARCHITECTURE_AUDIT.md
  - FRONTEND_FIX_PROGRESS.md
  - factory-agent/CODE_PRACTICE_RULES.md
- Do not modify Go backend or Factory Agent backend unless explicitly needed to verify a frontend contract.

First actions:
1. Read FRONTEND_FIX_PROGRESS.md.
2. Read FRONTEND_ARCHITECTURE_AUDIT.md.
3. Read the React frontend section of factory-agent/CODE_PRACTICE_RULES.md.
4. Check git status.
5. Confirm which phase is active from the tracker.
6. Use the dedicated worktree ../emas-audit-frontend.
7. Use the branch for this phase. Phase N must be based on completed Phase N-1.

Execution rules:
- Work only on the active phase.
- Do not start future-phase work.
- Preserve current working behavior unless the phase explicitly fixes a documented bug.
- Add or update focused tests when behavior changes.
- Run the verification listed for the phase.
- Update FRONTEND_FIX_PROGRESS.md with status, commands, results, and rollback notes.
- Commit after the phase is complete.
- Stop after the phase is done and summarize the commit and verification.

Active phase: [replace with Phase 0/1/2/3/4/5]
```

## Baseline

| Item | Status | Owner | Notes |
|---|---|---|---|
| Create dedicated worktree | Not Started | TBD | Use `git worktree add ../emas-audit-frontend audit/frontend`. |
| Create Phase 0 branch | Not Started | TBD | Use `audit/frontend-phase-0` in the worktree. |
| Run current frontend utility tests | Done | Codex | 35 tests passed on 2026-05-15 using direct `node --test` command. |
| Run current lint | Done | Codex | `npm.cmd run lint` failed with 1085 errors and 26 warnings; generated `playwright-report` is currently included. |
| Run production build | Done | Codex | `npx.cmd vite build --outDir C:\tmp\emas-front-build-audit-20260515` passed; main JS chunk warning at 617.77 kB. |
| Record current Factory Agent UI behavior | Not Started | TBD | Need screenshots or notes for send, approval, reject, approve, final answer, error state. |
| Snapshot Factory Agent API examples | Not Started | TBD | Need sample session, snapshot, approval, SSE/event payloads from a safe local flow. |

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

- Status: In Progress
- Goal: Freeze current behavior and make rollback easy.
- Completed:
  - Documented frontend architecture audit.
  - Ran current utility tests.
  - Ran lint and recorded failure.
  - Ran production build into `C:\tmp`.
- Remaining:
  - Create branch before code changes.
  - Record browser behavior for Factory Agent chat flow.
  - Capture safe snapshot/SSE/approval payload examples.

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

## Current Next Step

Before changing frontend code:

1. Create a branch.
2. Add `npm test` and lint ignores as Phase 1 safety work.
3. Run tests, lint, and build.
4. Record current browser behavior for Factory Agent chat.
5. Start Phase 2 with FE-001 or FE-002.

## Update Rules For This Tracker

- Update status before starting a fix and after finishing it.
- Add the exact verification command and result.
- Keep rollback notes specific.
- If a fix changes backend/frontend contract assumptions, add a decision log entry.
- Do not mark an issue Done until tests or manual verification are recorded.
