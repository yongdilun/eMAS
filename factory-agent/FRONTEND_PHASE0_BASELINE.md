# Frontend Phase 0 Baseline

Date: 2026-05-15

Branch: `audit/frontend-phase-0`

Scope: React frontend only, under `eMas Front`.

## Verification Commands

Commands run from `eMas Front`:

```powershell
npm ci
node --test "src\components\features\chat\factory-agent\activityTimeline.test.mjs" "src\components\features\chat\factory-agent\approvalInterruptDisplay.test.mjs" "src\components\features\chat\turns\turnAssembler.test.mjs"
npm.cmd run lint
npx.cmd vite build --outDir C:\tmp\emas-front-build-phase0-20260515
```

Results:

- Existing Node utility tests passed: 35 tests.
- Lint failed with 1085 errors and 26 warnings. The failure is unchanged from the audit baseline: generated `playwright-report` files are linted, and source files also have existing `react/prop-types`, unused variable, hook dependency, and `vite.config.js` `__dirname` issues.
- Production build passed to `C:\tmp\emas-front-build-phase0-20260515`.
- Build warning remained: main JS chunk is 618.15 kB after minification.

## Browser Baseline

Temporary frontend server:

```powershell
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

The server was stopped after capture.

Local browser capture files were written under `captures/frontend-phase0/`:

- `00-dashboard.png`: dashboard with floating AI Assistant entry point.
- `01-chat-open.png`: Factory Agent modal with session list loaded from the live backend.
- `02-completed-session-final-answer.png`: completed session `de25fdec-ed66-44c4-b55d-a61006f1a52d` (`Chat 448`) rendering final answer and job table.
- `03-pending-approval-card.png`: pending approval session `307e8018-677a-42bf-a422-d63058d5568b` (`Chat 355`) rendering approval bundle table plus Approve and Reject controls.
- `05-send-plan-error-after-wait.png`: fresh send path where `POST /plans` fails and the UI displays raw `{"errors":["Connection error."]}` text.

Observed behavior:

- Opening the modal loads many existing Factory Agent sessions for `frontend-operator`.
- Completed sessions render the final answer bubble, activity summary, and result table.
- Pending approval sessions show the approval table, risk copy, editable request area, and Approve/Reject actions.
- Fresh send currently creates a session and persists the user message, then planning fails because the Factory Agent backend returns a planner connection error.
- The visible error state is raw backend JSON rather than a polished operator-facing message.

## API Baseline

Local backend health:

```json
{ "status": "ok" }
```

Captured API examples were written locally to `captures/frontend-phase0/factory-agent-api-examples.json`.

Representative responses:

- Completed snapshot: `GET /sessions/de25fdec-ed66-44c4-b55d-a61006f1a52d/snapshot`
  - `session.status`: `COMPLETED`
  - `current_intent`: `Find all low priority jobs`
  - `pending_approval`: `null`
- Pending approval snapshot: `GET /sessions/307e8018-677a-42bf-a422-d63058d5568b/snapshot`
  - `session.status`: `WAITING_APPROVAL`
  - pending approval action: `__langgraph_commit__`
  - side effect level: `HIGH`
  - approval table shows `JOB-SEED-001` moving from `low` to `high`.
- Fresh planning failure: `POST /sessions/a2fd8471-90c5-4901-97e9-de373667b8db/plans`
  - HTTP status: `503`
  - body: `{"detail":{"errors":["Connection error."]}}`
- SSE sampling:
  - `GET /sessions/{id}/events` and `GET /sessions/{id}/events/activity` opened against completed/pending sessions but produced no frames before the 2.5s capture timeout.

## Rollback

Phase 0 is documentation and baseline evidence only. To roll back the tracked change, revert this phase commit. Generated evidence under `captures/frontend-phase0/` can be deleted without affecting application behavior.
