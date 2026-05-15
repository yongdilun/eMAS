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
| Record current Factory Agent UI behavior | Done | Codex | Browser notes recorded in `factory-agent/FRONTEND_PHASE0_BASELINE.md`. Fresh planning currently fails with a 503 connection error, so approve/reject was observed on an existing pending session rather than executing an old approval. |
| Snapshot Factory Agent API examples | Done | Codex | Existing completed/pending snapshots and failed fresh `POST /plans` response recorded in `factory-agent/FRONTEND_PHASE0_BASELINE.md`. |

## Issue Tracker

| ID | Issue | Severity | Phase | Status | Verification | Rollback |
|---|---|---|---|---|---|---|
| FE-001 | Silent demo/mock data can look real | High | 2 | Done | `npm test` passed 37 tests; `npx.cmd vite build` passed; Playwright smoke verified report/machine unavailable text and blocked high-risk jobs unavailable text | Restore removed demo fallback constants only behind a visible demo flag |
| FE-002 | Approval approve path depends on SSE for fresh UI state | High | 2 | Done | `npm test` passed 37 tests; build passed; approve path now calls direct snapshot refresh after approve succeeds | Remove the post-approve `safelyRefreshSnapshot` call |
| FE-003 | SSE streams do not share REST bearer-token behavior | High/Medium | 2 | Done | Build passed; EventSource is disabled when `VITE_FACTORY_AGENT_BEARER_TOKEN` is configured and snapshot polling remains active | Re-enable EventSource by removing the bearer-token guard |
| FE-004 | Snapshot event stream runs for inactive sessions | Medium | 2 | Done | Build passed; `useSessionEvents` is enabled only for active/running states or while sending | Restore `enabled: true` for `useSessionEvents` |
| FE-005 | Pending approval follow-up can create a new plan before decision | Medium | 2 | Done | Build passed; UI now states follow-up messages can revise the plan while the current approval remains pending | Remove the pending-approval helper copy and placeholder change |
| FE-006 | Approval card dynamic lookup and validation are too broad | Medium | 2-3 | Done | Added `approvalFieldUtils.test.mjs`; `npm test` passed 37 tests; strict integer/number casting rejects partial numeric strings | Restore previous lenient `parseInt`/`parseFloat` casting or remove the helper |
| FE-007 | Nested interactive controls in session list | Medium | 5 | Not Started | Keyboard navigation test | Revert session row component |
| FE-008 | Lint/test configuration is not a reliable safety gate | High | 1 | Done | `npm test` passed 35 tests; `npm.cmd run lint` now ignores generated artifacts and fails on source-only lint issues; `npx.cmd vite build` passed | Revert `.eslintrc.cjs`, `package.json`, and the tiny `useFactoryAgentChat.js` lint fix |
| FE-009 | Dead or stale frontend modules create maintenance risk | Low/Medium | 1 | Done | Import check for stale names returned no matches after removal; build passed | Restore removed files from git |
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

- Status: Done
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
- Completed:
  - Created `audit/frontend-phase-1` from committed `audit/frontend-phase-0`.
  - Added `npm test` for the existing Node test files.
  - Updated lint config to ignore generated artifacts: `playwright-report`, `test-results`, `coverage`, and `dist`.
  - Disabled `react/prop-types` for this non-PropTypes React codebase while keeping hook and no-undef checks active.
  - Added Node lint environment for `scripts/**/*.js` and `vite.config.js`.
  - Removed stale, unimported frontend modules after import checks:
    - `src/pages/AIAssistantChat.jsx`
    - `src/components/features/chat/AiChatPanel.jsx`
    - `src/components/features/chat/AiChatBlocks.jsx`
    - `src/components/features/chat/useAiChat.js`
    - `src/services/machineService.js`
    - `src/services/jobService.js`
    - `src/services/inventoryService.js`
  - Fixed the active Factory Agent chat lint issue where `startClientProgress` referenced `text` after naming the parameter `_text`.
- Verification:
  - `rg -n "AIAssistantChat|AiChatPanel|AiChatBlocks|useAiChat|machineService|jobService|inventoryService" src package.json vite.config.js` from `eMas Front`: no matches after removal.
  - `npm test` from `eMas Front`: passed, 35 tests.
  - `npm.cmd run lint` from `eMas Front`: failed meaningfully on source-only issues, reduced from the Phase 0 generated-artifact-heavy `1085 errors, 26 warnings` to `35 errors, 23 warnings`. Remaining items are existing unused variables and hook dependency warnings in source files.
  - `npx.cmd vite build` from `eMas Front`: passed; retained existing large chunk warning at `618.15 kB`.
- Rollback:
  - Revert the Phase 1 commit to restore the removed stale files and previous config.
  - For partial rollback, restore `eMas Front/.eslintrc.cjs`, `eMas Front/package.json`, and the deleted files listed above from `audit/frontend-phase-0`.

### Phase 2: UI Bug And Contract Fixes

- Status: Done
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
- Completed:
  - Created `audit/frontend-phase-2` from committed `audit/frontend-phase-1`.
  - Replaced Phase 2 audited silent demo fallbacks with explicit unavailable states:
    - `src/pages/MachineResources.jsx`
    - `src/components/features/machines/UtilizationChart.jsx`
    - `src/components/features/reports/ReportPreview.jsx`
    - `src/components/features/reports/ProductionOutputChart.jsx`
    - `src/components/features/predictive/HighRiskJobsTable.jsx`
  - Added direct snapshot refresh immediately after approval approve succeeds in `useFactoryAgentChat.js`.
  - Added bearer-token-aware SSE handling: browser `EventSource` is not opened when REST is configured with `VITE_FACTORY_AGENT_BEARER_TOKEN`; snapshot polling remains the fallback path.
  - Gated session invalidation streams to active states (`PLANNING`, `EXECUTING`, `WAITING_APPROVAL`, `WAITING_CONFIRMATION`, `BLOCKED`) or active sends.
  - Clarified pending-approval follow-up copy without changing backend planner or approval semantics.
  - Extracted approval field casting into `approvalFieldUtils.js` and tightened integer/number validation to reject partial numeric values such as `12abc`.
  - Reduced approval tool lookup load from `max_tools: 200` to `max_tools: 100` while preserving editable field fallback.
- Verification:
  - `npm test` from `eMas Front`: passed, 37 tests.
  - `npm.cmd run lint` from `eMas Front`: failed on known source lint backlog with `35 errors, 22 warnings`; remaining failures are unused variables and hook/fast-refresh warnings in existing source files.
  - `npx.cmd vite build` from `eMas Front`: passed; retained existing large chunk warning at `617.47 kB`.
  - Manual Playwright smoke against local Vite `http://127.0.0.1:5173`:
    - `/reports`: visible text `No demo report rows are being shown`.
    - `/machine-resources`: visible text `No demo machine values are being shown`.
    - `/predictive-analysis` with `/predictive/high-risk-jobs` request blocked: visible text `No demo risk rows are being shown`.
    - `/predictive-analysis` with local API available: rendered live `JOB-SEED-*` high-risk rows rather than demo rows.
- Rollback:
  - Revert the Phase 2 commit to restore prior fallback, stream, and approval-validation behavior.
  - For partial rollback, restore the report/machine/predictive fallback files listed above, remove the post-approve refresh in `useFactoryAgentChat.js`, remove `factoryAgentStreamAuth` and the stream guards, or restore lenient approval casting.
- Remaining:
  - Lint still fails on the existing source backlog from Phase 1.
  - No React component test harness exists yet; component-level coverage for unavailable states and chat flows remains Phase 3 work.

### Phase 3: Frontend Test Improvement

- Status: Done
- Goal: Add tests that make UI and state changes safe.
- Candidate changes:
  - Add component tests for Factory Agent chat panel.
  - Add approval card tests.
  - Add activity timeline rendering tests.
  - Add backend unavailable tests.
  - Add no-fake-data tests.
- Do not change:
  - Avoid broad visual snapshot tests unless they are stable and intentional.
- Completed:
  - Created `audit/frontend-phase-3` from committed `audit/frontend-phase-2`.
  - Added a small Vite SSR + jsdom React component test harness in `src/test/reactComponentTestUtils.mjs`.
  - Added Factory Agent component tests:
    - `src/components/features/chat/factory-agent/ApprovalCard.component.test.mjs`
    - `src/components/features/chat/factory-agent/ActivityTimeline.component.test.mjs`
    - `src/components/features/chat/factory-agent/FactoryAgentChatPanel.component.test.mjs`
  - Added unavailable/no-fake-data regression tests:
    - `src/components/features/reports/noFakeData.component.test.mjs`
  - Added `jsdom` as a dev dependency for component tests.
  - Added a test-only dependency injection prop to `FactoryAgentChatPanel` so tests can provide chat hook state while production keeps using `useFactoryAgentChat` by default.
- Verification:
  - `npm test` from `eMas Front`: passed, 46 tests.
  - `npm.cmd run lint` from `eMas Front`: failed on known source lint backlog with `35 errors, 22 warnings`; remaining failures are unused variables and hook/fast-refresh warnings already tracked from Phase 1/2.
  - `npx.cmd vite build --outDir C:\tmp\emas-front-build-phase3-20260515` from `eMas Front`: passed; retained existing large chunk warning at `617.49 kB`.
- Rollback:
  - Revert the Phase 3 commit to remove the component test harness, component tests, `jsdom` dependency, updated test script, and the optional `FactoryAgentChatPanel` hook injection prop.

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
| 2026-05-15 | Keep SSE bearer handling frontend-only in Phase 2 | Browser `EventSource` cannot attach the REST `Authorization` header, and backend contract changes are out of scope | Use snapshot polling when `VITE_FACTORY_AGENT_BEARER_TOKEN` is configured; define a backend stream auth contract in a later phase if needed |
| 2026-05-15 | Use Vite SSR plus jsdom for Phase 3 component tests | Existing tests are Node tests and the app has no React test framework; Vite can load JSX components without changing runtime bundling | Keep tests focused on stable rendered text and interactions, not broad visual snapshots |

## Current Next Step

Phase 3 is complete. Stop here and do not start Phase 4 in this window.

The next phase window should branch `audit/frontend-phase-4` from committed `audit/frontend-phase-3`.

## Update Rules For This Tracker

- Update status before starting a fix and after finishing it.
- Add the exact verification command and result.
- Keep rollback notes specific.
- If a fix changes backend/frontend contract assumptions, add a decision log entry.
- Do not mark an issue Done until tests or manual verification are recorded.
