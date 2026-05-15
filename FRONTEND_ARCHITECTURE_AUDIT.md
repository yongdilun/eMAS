# React Frontend Architecture Audit

Date: 2026-05-15

Scope: React frontend only, located at `../eMas Front`.

Purpose: Capture the read-only frontend audit findings before making any frontend code changes. This document is intentionally focused on structure, state flow, Factory Agent chat behavior, API contracts, tests, and safe phased fixes.

## Executive Summary

The frontend is workable, and the Factory Agent chat has stronger separation than the older AI chat path. The best-covered area is the Factory Agent timeline and turn summary logic, which already has focused Node tests.

The biggest frontend risks are:

- Silent demo/mock data can look like real production data.
- Approval approval flow relies on SSE invalidation for the next fresh snapshot.
- SSE streams do not share the REST client's bearer-token behavior.
- Factory Agent chat state and rendering are concentrated in very large files.
- Existing tests do not exercise React components, hooks, or browser behavior.
- Lint is not a useful safety gate yet because generated artifacts are included and source warnings are noisy.

Overall recommendation: avoid a rewrite. Fix misleading UI and state-contract risks first, add targeted tests, then refactor boundaries once behavior is pinned down.

## Current Architecture Map

Frontend root:

- `../eMas Front`

Main app shell:

- `src/App.jsx`
  - Eagerly imports all routed pages.
  - Mounts `FloatingChatButton`.
  - Opens `AIAssistantModal`, which currently renders the Factory Agent chat panel.

Main folders:

- `src/pages`
  - Page-level screens for dashboard, jobs, scheduling, reports, machine resources, inventory, products, settings.
- `src/components/features`
  - Domain components for chat, scheduling, machines, reports, inventory, forms, charts, etc.
- `src/components/features/chat/factory-agent`
  - Current Factory Agent chat implementation.
- `src/services`
  - Main eMAS API client, Factory Agent API client, normalizers, logger.
- `src/hooks`
  - Shared local hooks such as local storage, theme, reference data.
- `src/context`
  - Theme and toast providers.

Factory Agent files:

- `src/services/factoryAgentApi.js`
  - REST client for Factory Agent sessions, messages, snapshots, execution, approvals.
- `src/components/features/chat/factory-agent/useFactoryAgentChat.js`
  - Session state, snapshot refresh, polling, message send, approval decisions, session list, optimistic UI.
- `src/components/features/chat/factory-agent/useSessionEvents.js`
  - Snapshot invalidation SSE with polling fallback.
- `src/components/features/chat/factory-agent/useActivityStream.js`
  - Activity timeline SSE stream.
- `src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
  - Main UI shell, session sidebar, message rendering, input, activity timeline, approval card mounting.
- `src/components/features/chat/factory-agent/ApprovalCard.jsx`
  - Approval form, schema-driven fields, dynamic lookup options, approve/reject controls.
- `src/components/features/chat/factory-agent/activityTimelineUtils.js`
  - Snapshot/timeline to user-facing activity rows.
- `src/components/features/chat/turns/turnAssembler.js`
  - Timeline events to user/assistant turns and final summary text.

Important flow observed:

1. User enters a message in `FactoryAgentChatPanel`.
2. `useFactoryAgentChat.handleSend` creates a session if needed.
3. Frontend posts user message.
4. Frontend refreshes snapshot.
5. Frontend creates a plan.
6. Frontend executes, usually in background.
7. UI refreshes via snapshot polling and `useSessionEvents`.
8. Activity rows can stream through `useActivityStream`.
9. If backend returns `pending_approval`, `ApprovalCard` renders on the matching turn.
10. User approves or rejects.
11. Reject path refreshes snapshot immediately.
12. Approve path clears the approval card and depends on SSE/snapshot invalidation for the next fresh UI state.
13. Timeline/turn assembler computes final user-visible response.

## Verification Performed

Commands run from `../eMas Front`:

- `node --test "src\components\features\chat\factory-agent\activityTimeline.test.mjs" "src\components\features\chat\factory-agent\approvalInterruptDisplay.test.mjs" "src\components\features\chat\turns\turnAssembler.test.mjs"`
  - Result: 35 passed.
- `npm.cmd run lint`
  - Result: failed with 1085 errors and 26 warnings.
  - Major cause: generated `playwright-report` artifacts are linted because `.eslintrc.cjs` only ignores `dist`.
  - Source also has unused variables, prop-types noise, and hook dependency warnings.
- `npx.cmd vite build --outDir C:\tmp\emas-front-build-audit-20260515`
  - Result: passed.
  - Warning: main JS chunk is 617.77 kB after minification.

## Problems Found

### FE-001: Silent Demo Data Can Look Like Real Backend Data

- Severity: High
- Risk type: UI Bug, API Contract, UX
- Affected files:
  - `../eMas Front/src/pages/MachineResources.jsx`
  - `../eMas Front/src/components/features/reports/ReportPreview.jsx`
  - `../eMas Front/src/components/features/predictive/HighRiskJobsTable.jsx`
- Evidence:
  - Machine utilization falls back to `MOCK_UTILIZATION`.
  - Report preview uses mock rows when `data` is null.
  - High-risk jobs table initializes with demo jobs and silently keeps them on API failure.
- Why this is a problem:
  - Operators may treat fake production, machine, or risk data as current system truth.
- Possible impact:
  - Misleading operational decisions.
  - UI appears successful when backend data is unavailable.
- Recommended fix:
  - Replace silent demo fallback with explicit empty/error/demo states.
  - If demo data is still needed, gate it behind a visible `VITE_ENABLE_DEMO_DATA` flag.
- Safe implementation notes:
  - Add an `isDemoData` marker first.
  - Show a visible "Demo data" or "Data unavailable" state before removing mock constants.
- Tests needed:
  - Component tests for API failure and empty data.
  - Assert fake rows do not render as real data.
- Rollback plan:
  - Re-enable demo fallback behind a feature flag.

### FE-002: Approve Path Depends On SSE For Fresh UI State

- Severity: High
- Risk type: State Bug, UI Bug
- Affected files:
  - `../eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
- Evidence:
  - `decideApproval("approve")` clears `pendingApproval`, calls `factoryAgentApi.approve`, then waits for SSE invalidation.
  - Reject path calls `safelyRefreshSnapshot` immediately.
- Why this is a problem:
  - If SSE is delayed, blocked, or unauthenticated, the approval card disappears but the run may not visibly continue.
- Possible impact:
  - Stale or blank post-approval state.
  - User cannot tell whether approval actually resumed execution.
- Recommended fix:
  - After approve succeeds, call `safelyRefreshSnapshot(session.session_id)` just like the reject path.
- Safe implementation notes:
  - Keep optimistic card clearing.
  - Add bounded refresh and error recovery.
- Tests needed:
  - Approve flow test where no SSE event arrives.
- Rollback plan:
  - Remove only the direct refresh if it causes backend load issues.

### FE-003: SSE Streams Do Not Share REST Auth Handling

- Severity: High if Factory Agent auth is enabled, Medium otherwise
- Risk type: API Contract, Runtime
- Affected files:
  - `../eMas Front/src/services/factoryAgentApi.js`
  - `../eMas Front/src/components/features/chat/factory-agent/useSessionEvents.js`
  - `../eMas Front/src/components/features/chat/factory-agent/useActivityStream.js`
- Evidence:
  - REST requests can attach `VITE_FACTORY_AGENT_BEARER_TOKEN`.
  - Browser `EventSource` does not attach the REST Authorization header.
- Why this is a problem:
  - Authenticated REST can work while event streams fail.
- Possible impact:
  - Missing activity rows.
  - Delayed snapshot updates.
  - Approval flow depends more heavily on polling.
- Recommended fix:
  - Define a stream auth contract with the backend:
    - cookie auth, or
    - short-lived stream token query parameter, or
    - disable SSE when bearer-only auth is configured.
- Safe implementation notes:
  - Add diagnostics before changing protocol.
- Tests needed:
  - EventSource failure fallback test.
  - Auth-enabled stream test if backend supports it.
- Rollback plan:
  - Feature flag SSE off and rely on snapshot polling.

### FE-004: Snapshot Event Stream Runs For Inactive Sessions

- Severity: Medium
- Risk type: Performance, State Bug
- Affected files:
  - `../eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
  - `../eMas Front/src/components/features/chat/factory-agent/useSessionEvents.js`
- Evidence:
  - `useSessionEvents` is enabled whenever a session exists.
  - Interval snapshot polling is status-gated, but the SSE invalidation stream is not.
- Why this is a problem:
  - Completed or idle sessions can continue to hold stream/fallback polling resources.
- Possible impact:
  - Extra backend traffic.
  - Confusing refresh errors for idle sessions.
- Recommended fix:
  - Gate session events to active statuses or a short post-run window.
- Safe implementation notes:
  - Keep manual session switch refresh.
- Tests needed:
  - Hook test for IDLE and COMPLETED sessions not starting fallback polling.
- Rollback plan:
  - Restore always-on stream if missed updates appear.

### FE-005: Pending Approval Follow-Up Can Create A New Plan Before Decision

- Severity: Medium
- Risk type: State Bug, UX
- Affected files:
  - `../eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js`
  - `../eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- Evidence:
  - While `WAITING_APPROVAL`, the placeholder invites a plan change.
  - The handler appends the message, creates a plan, and executes.
- Why this is a problem:
  - This may be intended, but it needs explicit stale-approval semantics.
- Possible impact:
  - User may approve an old action after asking for changes.
  - Duplicate or contradictory UI states.
- Recommended fix:
  - Make "revise plan" explicit.
  - Cancel/invalidate old approval or clearly mark it obsolete.
- Safe implementation notes:
  - Verify backend behavior before changing UI.
- Tests needed:
  - Pending approval plus follow-up message regression.
- Rollback plan:
  - Disable free-text input during pending approval except approval/rejection controls.

### FE-006: Approval Card Dynamic Lookup And Validation Are Too Broad

- Severity: Medium
- Risk type: Performance, API Contract, Form Validation
- Affected files:
  - `../eMas Front/src/components/features/chat/factory-agent/ApprovalCard.jsx`
- Evidence:
  - Loads up to 200 tools.
  - Guesses lookup endpoints per field.
  - Tries several endpoints and silently falls back to empty options.
  - Numeric casting uses lenient parse behavior.
- Why this is a problem:
  - Approval options can be slow or ambiguous.
  - Values can be accepted that do not match the intended schema.
- Possible impact:
  - Wrong approval arguments submitted.
- Recommended fix:
  - Move lookup metadata into Factory Agent tool schema or a small explicit frontend mapper.
  - Use strict numeric validation.
- Safe implementation notes:
  - Keep free-text fallback until schemas are reliable.
- Tests needed:
  - Approval field validation tests.
  - Dynamic lookup failure tests.
- Rollback plan:
  - Disable dynamic options only; keep editable fields.

### FE-007: Nested Interactive Controls In Session List

- Severity: Medium
- Risk type: Accessibility, UI Bug
- Affected files:
  - `../eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx`
- Evidence:
  - Edit/delete spans with `role="button"` are nested inside a parent session `button`.
- Why this is a problem:
  - Nested interactive controls are invalid and can confuse keyboard/screen-reader behavior.
- Possible impact:
  - Accidental session switch while editing or deleting.
- Recommended fix:
  - Use a non-button row container with separate buttons for select, edit, and delete.
- Safe implementation notes:
  - Preserve click and keyboard behavior.
- Tests needed:
  - Keyboard navigation test.
- Rollback plan:
  - Revert only the session row component.

### FE-008: Lint And Test Configuration Are Not Reliable Gates

- Severity: High
- Risk type: Testing, Build Config
- Affected files:
  - `../eMas Front/package.json`
  - `../eMas Front/.eslintrc.cjs`
- Evidence:
  - No `test` script exists.
  - Existing tests must be run manually with `node --test`.
  - `playwright-report` is linted.
- Why this is a problem:
  - Developers cannot trust lint/test output as a quick safety gate.
- Possible impact:
  - Real regressions hide in noisy checks.
- Recommended fix:
  - Add `npm test`.
  - Ignore generated artifacts.
  - Clean source lint incrementally.
- Safe implementation notes:
  - Do not disable useful hook rules globally.
- Tests needed:
  - CI runs lint, tests, and build.
- Rollback plan:
  - Keep ignore-only config change separate from source lint cleanup.

### FE-009: Dead Or Stale Frontend Modules Create Maintenance Risk

- Severity: Low/Medium
- Risk type: Maintainability, API Contract
- Affected files:
  - `../eMas Front/src/pages/AIAssistantChat.jsx`
  - `../eMas Front/src/components/features/chat/AiChatPanel.jsx`
  - `../eMas Front/src/components/features/chat/useAiChat.js`
  - `../eMas Front/src/services/machineService.js`
  - `../eMas Front/src/services/jobService.js`
  - `../eMas Front/src/services/inventoryService.js`
- Evidence:
  - App does not route `AIAssistantChat`.
  - Modal imports Factory Agent chat only.
  - Old service files import a default `api` export that does not exist.
- Why this is a problem:
  - Future edits can accidentally revive broken code paths.
- Possible impact:
  - Runtime or build failures if stale modules are imported.
- Recommended fix:
  - Mark as deprecated or remove after import checks.
- Safe implementation notes:
  - Start with `rg` import checks.
- Tests needed:
  - Build after deletion.
- Rollback plan:
  - Restore deleted files from git.

### FE-010: Main Bundle Is Eager And Large

- Severity: Medium
- Risk type: Performance
- Affected files:
  - `../eMas Front/src/App.jsx`
- Evidence:
  - All pages and chat modal are eagerly imported.
  - Build produced one 617.77 kB minified JS chunk warning.
- Why this is a problem:
  - Initial load includes code for pages and chat users may not open.
- Possible impact:
  - Slower startup on lower-powered machines.
- Recommended fix:
  - Use route-level `React.lazy`.
  - Lazy-load Factory Agent modal only when opened.
- Safe implementation notes:
  - Add suspense fallbacks matching existing loading style.
- Tests needed:
  - Route smoke tests and modal open test.
- Rollback plan:
  - Revert lazy imports if deployment chunk loading breaks.

## Frontend Testing Gap Analysis

Useful tests:

- `activityTimeline.test.mjs`
- `approvalInterruptDisplay.test.mjs`
- `turnAssembler.test.mjs`

Weak or shallow tests:

- Utility-only tests.
- No React component tests.
- No hook tests.
- No browser behavior tests.

Missing critical tests:

- Chat message sending.
- Session creation and resume.
- Snapshot rendering.
- SSE invalidation rendering.
- Activity stream rendering.
- Approval card display.
- Approval and rejection behavior.
- Final answer rendering.
- Backend unavailable state.
- Loading and retry states.
- Machine/job response display.
- No contradictory success plus no-match message.
- No fake demo data on API failure.

## Recommended Test Strategy

Unit tests:

- Factory Agent response mappers.
- Activity timeline builders.
- Turn summary helpers.
- Approval state helpers and arg casting.
- Normalizers and formatters.
- Demo-data gating helpers.

Component tests:

- Factory Agent chat panel.
- Message list.
- Approval card.
- Activity timeline.
- Error/loading states.
- Machine/job result display.

Frontend integration tests:

- Mock API response to UI display.
- Snapshot or SSE event to UI update.
- Approval response to resumed UI state.
- Backend unavailable to clear UI error state.

Real E2E tests:

- Read machine status.
- List machines.
- List jobs.
- Approval write.
- Approval rejection.
- Backend error.
- SSE/polling update.

## Phased Frontend Fix Plan

### Phase 0: Safety Preparation

- Goal: Freeze current behavior and make rollback easy.
- What to change:
  - Create branch.
  - Run existing Node tests.
  - Run lint and record failures.
  - Run production build.
  - Capture screenshots and API examples for Factory Agent flow.
- What not to change:
  - No behavior changes.
- Risk level: Low.
- Expected benefit:
  - Known baseline.
- Verification steps:
  - Existing tests pass.
  - Build passes.
  - Browser flow recorded.

### Phase 1: Low-Risk Cleanup

- Goal: Make safety checks useful.
- What to change:
  - Add `npm test`.
  - Exclude generated artifacts from lint.
  - Identify dead frontend files.
  - Extract tiny duplicated helpers only when behavior stays identical.
- What not to change:
  - No UI behavior changes.
- Risk level: Low.
- Expected benefit:
  - Cleaner verification loop.
- Verification steps:
  - Lint noise reduced.
  - Tests still pass.
  - Build still passes.

### Phase 2: UI Bug And Contract Fixes

- Goal: Stop misleading UI and stale state.
- What to change:
  - Remove or visibly label demo fallback data.
  - Refresh snapshot directly after approval approve.
  - Gate inactive SSE streams.
  - Clarify pending approval follow-up behavior.
  - Tighten approval form validation.
- What not to change:
  - Do not change backend endpoints without contract review.
- Risk level: Medium.
- Expected benefit:
  - Fewer fake-success, stale-result, and contradictory states.
- Verification steps:
  - Mock API failure tests.
  - Approval approve/reject tests.
  - Manual Factory Agent flow.

### Phase 3: Frontend Test Improvement

- Goal: Lock in the real eMAS flow.
- What to change:
  - Add component tests for Factory Agent chat, approval card, timeline.
  - Add regression tests for demo data and backend failure states.
  - Add contract mock tests for snapshots and approvals.
- What not to change:
  - Avoid broad visual snapshot churn.
- Risk level: Low.
- Expected benefit:
  - Refactors become safer.
- Verification steps:
  - `npm test` passes locally and in CI.

### Phase 4: Frontend Architecture Refactoring

- Goal: Clearer ownership and smaller modules.
- What to change:
  - Split `useFactoryAgentChat` into session, transport, approval, and timeline hooks.
  - Split `FactoryAgentChatPanel` into sidebar, composer, turn list, header, delete modal.
  - Move approval dynamic lookup logic behind a small helper or schema mapper.
- What not to change:
  - Do not alter behavior without tests.
- Risk level: Medium.
- Expected benefit:
  - Easier maintenance and safer future changes.
- Verification steps:
  - Component/integration tests plus manual Factory Agent flow.

### Phase 5: Long-Term Improvements

- Goal: Improve UX, accessibility, observability, and performance.
- What to change:
  - Lazy-load routes and chat modal.
  - Improve keyboard/focus handling.
  - Add stream diagnostics.
  - Improve backend unavailable messaging.
- What not to change:
  - Avoid cosmetic-only rewrites.
- Risk level: Medium.
- Expected benefit:
  - Faster, clearer, more accessible UI.
- Verification steps:
  - Bundle size check.
  - Keyboard checks.
  - Manual browser smoke.

## Priority Table

| Priority | Issue | Severity | Risk | Recommended Phase | Expected Benefit |
|---|---|---|---|---|---|
| P0 | Silent demo data looks real | High | UI/API | 2 | Removes misleading operational data |
| P0 | Approve path waits on SSE | High | State | 2 | Prevents stale post-approval UI |
| P1 | SSE auth mismatch | High/Medium | API | 2 | Prevents stream-only failures |
| P1 | Lint/test gates unreliable | High | Testing | 1 | Makes regressions visible |
| P2 | WAITING_APPROVAL follow-up ambiguity | Medium | State | 2 | Avoids stale or duplicate operations |
| P2 | Oversized Factory Agent boundaries | Medium | Maintainability | 4 | Easier and safer changes |
| P2 | Approval card dynamic lookup/validation | Medium | UX/API | 2-3 | Safer approval args |
| P3 | Nested interactive controls | Medium | Accessibility | 5 | Better keyboard behavior |
| P3 | Dead/stale modules | Low/Medium | Maintainability | 1 | Less confusion |
| P3 | Eager large bundle | Medium | Performance | 5 | Faster startup |

## Safe Execution Checklist

Before changing frontend code:

- Create branch.
- Run existing frontend tests.
- Record current behavior.
- Capture snapshot and approval examples.
- Apply the smallest possible change.
- Run tests again.
- Check browser behavior manually.
- Check chat flow.
- Check approval flow.
- Check error state.
- Commit with a clear message.
- Keep rollback possible.

## Final Recommendation

Fix first:

1. Remove or visibly label silent demo/mock fallback data.
2. Add direct snapshot refresh after approval approve.
3. Make lint/test scripts reliable enough to support future changes.

Delay:

- Large Factory Agent hook/component refactors.
- Route-level lazy loading.
- Approval dynamic lookup redesign.

Risky to touch now:

- Pending-approval follow-up behavior, because it depends on backend approval invalidation semantics.

Most reliability gain:

- Add component and integration tests for the real Factory Agent flow:
  - send
  - session create/resume
  - snapshot/SSE update
  - approval display
  - approve/reject
  - final answer
  - backend unavailable
  - no fake success or stale result
