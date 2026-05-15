# QA Upgrade Integration Tracker

Created: 2026-05-15

Integration branch: `integration/qa-upgrade-merge`

Integration worktree: `C:\Users\dilun\OneDrive\Documents\emas-integration-qa`

## Status Legend

Use one of: `Not started`, `In progress`, `Passed`, `Failed`, `Skipped`, `Could not run`.

## Phase Status

| Phase | Action | Status | Notes |
|---|---|---|---|
| 0 | Inspect current Git state | Passed | Existing worktrees clean. `main` is ahead of `origin/main` by 2 commits. |
| 1 | Create integration worktree | Passed | Created `integration/qa-upgrade-merge` at `C:\Users\dilun\OneDrive\Documents\emas-integration-qa`. |
| 2 | Review all branches before merging | Passed | Reviewed `git log`, `git diff --stat`, `git diff --name-status`, shared file overlap, and watchpoint paths for all three audit branches. No merges performed. |
| 3 | Merge Go backend branch | Passed | `audit/go-backend-phase-5` merged cleanly with no conflicts in merge commit `b3161cf`. Initial handler failures were fixed in Phase 3 stabilization; `go test ./...` and `go test ./internal/e2e` now pass. Phase 4 is ready to start. |
| 4 | Merge Factory Agent branch | Passed | `audit/factory-agent` merged in `9b42d3a` after one documentation conflict was resolved. Initial `python -m pytest factory-agent/tests` exited 1 because pytest could not create/use the default temp root `C:\Users\dilun\AppData\Local\Temp\pytest-of-dilun`; the same full suite passed when rerun with a repo-local `--basetemp ".pytest-basetemp"`. Targeted checks passed/skipped as noted below. Phase 5 is ready to start. |
| 5 | Merge frontend branch | Passed | `audit/frontend-phase-5` merged in `d7cc9f1` after one documentation conflict was resolved. Frontend build, overlap check, and `npm test` passed. `npm run lint` failed on the known source lint backlog, and `npm run factory-agent-smoke` failed on local Factory Agent planning `503 {"detail":{"errors":["Connection error."]}}`. Phase 6 is ready to start with known risks. |
| 6 | Full integration verification | Failed | Required automated suites now pass, including the full seeded runner after a narrow seed manifest auth-header fix. Docker Compose can build and start with documented/local verification env values, but the Compose Factory Agent natural-language smoke failed at `POST /sessions/{id}/plans` with `503 {"detail":{"errors":["Connection error."]}}`, indicating container planner LLM connectivity is not release-ready. Phase 7 is not ready to start. |
| 7 | Cross-layer contract check | Not started | Run after integration verification. |
| 8 | Final report | Not started | Stop after report; do not merge to `main`. |

## Branch Review Table

| Branch | Area | Main Changes | Contract Impact | Conflict Risk | Runtime Risk | Review Status |
|---|---|---|---|---|---|---|
| `audit/go-backend-phase-5` | Go backend | Backend contract hardening: app error kinds plus common error responses, transaction wrapping for job and production-log flows, AutoMigrate env gate, Swagger regeneration, phase 0 baselines, ML training event lineage migration, and expanded Go tests. | High. Swagger JSON/YAML changed; approval routes are documented under `/ai/chatbot`; agent transaction routes are documented; some handlers now return 404/409/422 instead of generic 500. `rag_sources` OpenAPI and `tools.md` were not changed. | Low to medium. Go source is isolated under `emas`, but moved/deleted audit docs and `factory-agent/CODE_PRACTICE_RULES.md` overlap with other branches. | Medium to high. `EMAS_AUTO_MIGRATE`/`AUTO_MIGRATE` behavior, `ml_training_events` primary key migration, and newly surfaced transaction errors need runtime verification. | Passed |
| `audit/factory-agent` | Factory Agent / FastAPI | FastAPI API split into routers and services, response mappers, graph-native approvals, snapshot service, semantic/activity/notification SSE streams, readiness endpoint, startup schema compatibility flags, and additional pytest coverage. | High. Approval behavior now centers on `subject_type=graph`; legacy plan/step approvals return 410; snapshots expose `cursor`, `phase`, `resume_hint`, and `activity_steps`; SSE emits snapshot invalidation and phase events. `tools.md` was not changed. | Low to medium. Factory Agent source changes are isolated; likely textual conflicts are shared docs and `factory-agent/CODE_PRACTICE_RULES.md`. | Medium to high. Production config validation, JWT requirements, startup create_all/schema compatibility flags, Redis readiness, and SSE auth behavior need startup and integration checks. | Passed |
| `audit/frontend-phase-5` | React frontend | Factory Agent chat UI refactor: legacy AI chat files removed, chat panel decomposed into sidebar/composer/dialog utilities, approval lookup/casting utilities added, SSE diagnostics and polling fallback improved, component tests added, and frontend `npm test` script added. | High. UI depends on Factory Agent snapshot/event fields, `resume_hint`, `activity_steps`, approval payload shape, and Go API lookup endpoints. EventSource is disabled when static bearer auth is configured, so polling fallback is contract-critical. | Low to medium. Frontend source is isolated under `eMas Front`; overlaps with other branches are mostly docs and `factory-agent/CODE_PRACTICE_RULES.md`. Compatibility risk is contract-level with Factory Agent rather than file-level. | Medium. Chat, approval, polling/SSE, dependency lockfile, and dynamic option lookup behavior need browser/build verification after merges. | Passed |

## Phase 2 Review Notes

### `audit/go-backend-phase-5`

- Affected subsystem: Go backend, Swagger/OpenAPI docs, backend tests, and database migration scripts.
- Possible shared contract impact: API error status codes may change from generic 500s to 404/409/422; Swagger paths include `/agent/transaction/*`, `/ai/chatbot/approvals*`, `/jobs/{id}/duplicate`, `/jobs/{id}/steps`, and `/scheduling/jobs/{id}/earliest-completion`.
- Possible conflict risk: source conflict risk appears low; doc move/delete conflicts are possible with Factory Agent and frontend branches.
- Runtime risk: `EMAS_AUTO_MIGRATE` defaults through `AUTO_MIGRATE` to true; new `002_ml_training_events_lineage.sql` changes the stable primary key; stricter transaction handling can expose failures previously ignored.
- Tests/checks likely needed later: `go test ./...`, route/Swagger parity tests, API contract golden tests, migration review against a snapshot DB, and approval/agent transaction smoke flows.

### `audit/factory-agent`

- Affected subsystem: Factory Agent FastAPI routes, service layer, graph-native approval resume flow, session snapshots, SSE streams, readiness/startup behavior, and pytest suite.
- Possible shared contract impact: frontend must tolerate snapshot `cursor`, `phase`, `resume_hint`, `activity_steps`, semantic/activity stream frames, and graph approval decisions. Legacy plan/step approval calls are intentionally retired with 410 responses.
- Possible conflict risk: code conflict risk appears low; shared conflicts are likely limited to audit/progress docs and `factory-agent/CODE_PRACTICE_RULES.md`.
- Runtime risk: production startup now depends on `APP_MODE`, `JWT_REQUIRED`, `JWT_SECRET`, `ENABLE_STARTUP_CREATE_ALL`, and `ENABLE_STARTUP_SCHEMA_COMPAT`; `/ready` may fail if Redis or tool registry health is enforced.
- Tests/checks likely needed later: `python -m pytest factory-agent/tests`, targeted event/snapshot/approval tests, startup with production-like env, `/ready`, and live UI polling/SSE smoke.

### `audit/frontend-phase-5`

- Affected subsystem: React Factory Agent chat UI, approval UI, snapshot polling, SSE fallback, frontend API mapping, package lockfile, and component tests.
- Possible shared contract impact: expects Factory Agent snapshot/event semantics and approval payloads; dynamic approval options call Go API list endpoints through `VITE_API_BASE_URL`; static bearer auth disables EventSource and relies on polling fallback.
- Possible conflict risk: source conflict risk appears low; shared conflicts are likely docs/progress files and `factory-agent/CODE_PRACTICE_RULES.md`.
- Runtime risk: chat and approval behavior changed substantially; browser behavior must verify polling fallback, stream diagnostics, final-answer rendering, and no contradictory messages.
- Tests/checks likely needed later: `npm install`, `npm run lint`, `npm run build`, `npm test`, `npm run verify-overlaps`, `npm run factory-agent-smoke`, plus browser smoke for approval approve/reject and completed answer rendering.

## Merge Result Table

| Step | Branch | Result | Conflicts | Checks Run | Safe To Continue |
|---|---|---|---|---|---|
| 1 | `audit/go-backend-phase-5` | Merged cleanly with `git merge --no-ff audit/go-backend-phase-5` (`b3161cf`), then stabilized on the integration branch. | None | `go test ./...` passed; `go test ./internal/e2e` passed; targeted handler regression subset passed. | Yes |
| 2 | `audit/factory-agent` | Merged with `git merge --no-ff audit/factory-agent`; merge completed as `9b42d3a Merge branch 'audit/factory-agent' into integration/qa-upgrade-merge`. | One conflict in `factory-agent/CODE_PRACTICE_RULES.md`, resolved before committing. | Initial full Factory Agent suite failed under the default pytest temp path: 489 passed, 4 skipped, 20 xfailed, 3 errors. Full suite rerun with repo-local `--basetemp` passed: 492 passed, 4 skipped, 20 xfailed. Seed manifest targeted check passed. Live RAG targeted check skipped because opt-in env vars are missing. | Yes |
| 3 | `audit/frontend-phase-5` | Merged with `git merge --no-ff audit/frontend-phase-5`; merge completed as `d7cc9f1 Merge branch 'audit/frontend-phase-5' into integration/qa-upgrade-merge`, then stabilized with targeted frontend/Factory Agent test fixes. | One conflict in `FRONTEND_FIX_PROGRESS.md`, resolved before committing. | Initial Phase 5 checks found lint failures and a local Factory Agent planner connection failure. Post-fix checks now pass: `npm run lint`, `npm run build`, `npm test`, `npm run verify-overlaps`, `npm run factory-agent-smoke`, full `python -m pytest factory-agent/tests --basetemp ".pytest-basetemp"`, and focused live memory/RAG checks. | Yes, Phase 6 can start with known risks |

## Conflicts Resolved

If no conflicts are found, write: `No merge conflicts were found.`

Phase 3 found no merge conflicts. Phase 4 found one merge conflict and it was resolved.
Phase 5 found one merge conflict and it was resolved.

| File | Cause | Resolution | Why Safe |
|---|---|---|---|
| None | Go backend branch merged cleanly using Git `ort` strategy. | No conflict resolution was needed. | Phase 2 tracker updates were already committed before merge; Go backend API contract changes were accepted through the clean merge. |
| `factory-agent/CODE_PRACTICE_RULES.md` | The integration side contained frontend phase/window worktree rules that were absent on `audit/factory-agent`. | Kept the integration-side frontend phase/window rules and removed only the conflict markers. | Documentation-only conflict. It preserves prior integration rules and does not touch OpenAPI, `tools.md`, Go backend API contract changes, Factory Agent runtime/session/approval/SSE behavior, or tracker history. |
| `FRONTEND_FIX_PROGRESS.md` | The integration side contained older baseline branch/worktree checklist rows while `audit/frontend-phase-5` contained the completed frontend phase tracker. | Kept the frontend branch's completed baseline entry and removed the conflict markers. | Documentation-only conflict. It preserves the completed frontend Phase 0-5 evidence and does not touch OpenAPI, Swagger, `tools.md`, Go backend API contract changes, Factory Agent runtime/session/approval/SSE behavior, or the QA integration tracker history. |

## Tests and Checks

| Check | Command | Result | Notes |
|---|---|---|---|
| Worktree clean before branch review | `git status --short --branch` | Passed | Output was only `## integration/qa-upgrade-merge`. |
| Phase 2 branch inventory | `git log`, `git diff --stat`, and `git diff --name-status` for all three audit branches | Passed | Reviewed `audit/go-backend-phase-5`, `audit/factory-agent`, and `audit/frontend-phase-5`; no merge commands were run. |
| Phase 3 pre-merge status | `git status --short --branch` from repo root | Passed | Output was only `## integration/qa-upgrade-merge` after committing the Phase 2 tracker update. |
| Go backend merge | `git merge --no-ff audit/go-backend-phase-5` from repo root | Passed | Clean merge, no conflicts. Merge commit: `b3161cf Merge branch 'audit/go-backend-phase-5' into integration/qa-upgrade-merge`. |
| Phase 3 post-merge status | `git status --short --branch` from repo root | Passed | Output was only `## integration/qa-upgrade-merge`. |
| Initial Go tests after Go merge | `go test ./...` from `emas` | Failed | Exit code 1. `emas/internal/handler` failed before stabilization: protected proposal write tests lacked planner auth headers, golden fixtures compared CRLF text literally, and authenticated apply exposed transaction-bound repair issues. |
| Initial Go handler failure isolation | `go test ./internal/handler -run "TestAISchedulingHandler_Features\|TestRealSolverProposalLifecycle\|TestAPIContractGolden" -count=1` from `emas` | Failed | Exit code 1 before stabilization. Reproduced auth-header failures, golden comparison failures, and then a legacy split repair failure after auth was corrected. |
| Phase 3 Go stabilization targeted rerun | `go test ./internal/handler -run "TestAISchedulingHandler_Features\|TestRealSolverProposalLifecycle\|TestAPIContractGolden" -count=1 -timeout=3m` from `emas` | Passed | Output included `PASS` and `ok emas/internal/handler 19.498s`. |
| Go tests after Phase 3 stabilization | `go test ./...` from `emas` | Passed | Output included `ok emas/internal/e2e 3.714s`, `ok emas/internal/handler 33.905s`, `ok emas/internal/router 0.709s`, and `ok emas/internal/service 1.939s`; all Go packages passed or had no test files. |
| Go e2e after Go merge | `go test ./internal/e2e` from `emas` | Passed | Output: `ok emas/internal/e2e (cached)`. |
| Phase 4 pre-merge branch/status gate | `git branch --show-current`; `git status --short --branch` from repo root | Passed | Branch was `integration/qa-upgrade-merge`; status output was only `## integration/qa-upgrade-merge`. |
| Factory Agent merge | `git merge --no-ff audit/factory-agent` from repo root, then `git commit --no-edit` after resolving the conflict | Passed | Initial merge stopped with one conflict in `factory-agent/CODE_PRACTICE_RULES.md`; conflict was resolved and merge commit `9b42d3a` was created. |
| Phase 4 post-merge status | `git status --short --branch` from repo root | Passed | Output was only `## integration/qa-upgrade-merge` after the merge commit. |
| Factory Agent tests after agent merge | `python -m pytest factory-agent/tests` | Failed | Exit code 1. Summary: 489 passed, 4 skipped, 20 xfailed, 1588 warnings, 3 errors in 82.09s. The three errors were `test_rag_ingestion.py` setup errors from `tmp_path`: `PermissionError: [WinError 5] Access is denied: 'C:\Users\dilun\AppData\Local\Temp\pytest-of-dilun'`. |
| Factory Agent tests after agent merge with repo-local temp base | `python -m pytest factory-agent/tests --basetemp ".pytest-basetemp"` | Passed | 492 passed, 4 skipped, 20 xfailed, 1588 warnings in 69.63s. This avoids the inaccessible default Windows temp root while keeping temp artifacts inside the integration worktree. |
| Seed manifest check | `python -m pytest factory-agent/tests/test_seed_pipeline_manifest.py` | Passed | 125 passed, 1 warning in 0.76s. |
| Live RAG check | `python -m pytest factory-agent/tests/test_rag_live_llm.py` | Skipped | 1 skipped, 1 warning in 0.55s. |
| Live RAG skip reason check | `python -m pytest -rs factory-agent/tests/test_rag_live_llm.py` | Skipped | 1 skipped, 1 warning in 0.71s. Skip reason: `FACTORY_AGENT_LIVE_RAG / FACTORY_AGENT_LIVE_LLM not set; live RAG eval is opt-in.` |
| RAG ingestion temp-base diagnostic | `python -m pytest factory-agent/tests/test_rag_ingestion.py --basetemp ".pytest-basetemp"` | Passed | 3 passed, 3 warnings in 16.41s. This indicates the full-suite errors are tied to the default Windows temp directory permission, not the three ingestion tests themselves. |
| Phase 5 pre-merge branch/status gate | `git branch --show-current`; `git status --short --branch` from repo root | Passed | Branch was `integration/qa-upgrade-merge`; status output was only `## integration/qa-upgrade-merge`. |
| Frontend merge | `git merge --no-ff audit/frontend-phase-5` from repo root, then `git commit --no-edit` after resolving the conflict | Passed | Initial merge stopped with one conflict in `FRONTEND_FIX_PROGRESS.md`; conflict was resolved and merge commit `d7cc9f1` was created. |
| Phase 5 post-merge status | `git status --short --branch` from repo root | Passed | Output was only `## integration/qa-upgrade-merge` after the merge commit. |
| Frontend install | `npm install` from `eMas Front` | Passed | Added/audited 371 packages in 7s. Reported 12 vulnerabilities (5 moderate, 7 high) and deprecation warnings for `inflight`, `@humanwhocodes/config-array`, `rimraf`, `glob`, `@humanwhocodes/object-schema`, and `eslint@8.57.1`. |
| Frontend lint | `npm run lint` from `eMas Front` | Failed | Exit code 1. Summary: 57 problems (35 errors, 22 warnings). Failures match the known source lint backlog: unused variables, hook dependency warnings, and fast-refresh warnings. |
| Frontend build | `npm run build` from `eMas Front` | Passed | Vite build passed in 1.44s. Initial `index` JS chunk was 179.72 kB; `AIAssistantModal` chunk was 114.98 kB; routed pages were emitted as separate chunks. |
| Frontend overlap check | `npm run verify-overlaps` from `eMas Front` | Passed | Found 26 jobs and 26 proposal IDs. Local partial-overlap check found no overlaps. API checks returned `valid: true`, `total_slots: 89`, `overlap_count: 0` for proposals and `valid: true`, `total_slots: 0`, `overlap_count: 0` for applied. |
| Frontend factory-agent smoke | `npm run factory-agent-smoke` from `eMas Front` | Failed | Session was created and message was added, then `POST /sessions/{id}/plans` failed with `[503] ... {"detail":{"errors":["Connection error."]}}`. Node also printed `Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src\win\async.c, line 76` after the smoke failure. |
| Frontend npm test | `npm test` from `eMas Front` | Passed | 48 tests passed, 0 failed, 0 skipped, duration 6297.8132 ms. |
| Local LLM endpoint check | `Invoke-RestMethod http://127.0.0.1:900/v1/models`; `Invoke-RestMethod http://127.0.0.1:901/v1/models` | Passed | Port 900 reported `Qwen2.5-7B-Instruct-Q4_K_M.gguf`; port 901 reported `bartowski/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M`. A local ignored `factory-agent/.env` was created so Factory Agent uses `OPENAI_BASE_URL` / `LLM_BASE_URL` and per-role base URL variables instead of the stale shell-only `OPENAI_API_BASE`. |
| Frontend factory-agent smoke after env/smoke fix | `npm run factory-agent-smoke` from `eMas Front` | Passed | Session created, message added, plan created, execute started, status reached `COMPLETED`, cancel flow ended `IDLE`, and smoke passed. Default smoke intent was narrowed to `list machines`; cancel flow now tests cancellation without a second ambiguous LLM planning prompt. |
| Focused live Factory Agent checks | `$env:FACTORY_AGENT_LIVE_RAG='1'; $env:FACTORY_AGENT_LIVE_LLM='1'; python -m pytest -q -rs factory-agent/tests/test_memory_live_llm.py factory-agent/tests/test_rag_live_llm.py --basetemp ".pytest-basetemp-live"` | Passed | 2 passed, 58 warnings in 46.58s. Memory test now verifies API-backed vector memory retrieval without relying on local-model planner quality; RAG live harness uses the current `RAGPipeline` instead of retired Phase 5 agent imports. |
| Factory Agent suite after fix pass | `python -m pytest factory-agent/tests --basetemp ".pytest-basetemp"` | Passed | 492 passed, 4 skipped, 20 xfailed, 1588 warnings in 77.08s. Live-only tests skipped in the normal suite as expected. |
| Frontend lint after fix pass | `npm run lint` from `eMas Front` | Passed | ESLint completed with 0 errors and 0 warnings under `--max-warnings 0`. Fixes were limited to unused props/imports, hook dependency stabilization, stale dead handlers, and the already-wired shortage recommendation include toggle. |
| Frontend build after fix pass | `npm run build` from `eMas Front` | Passed | Vite build passed in 1.60s. Initial `index` JS chunk was 179.72 kB; `AIAssistantModal` chunk was 115.00 kB; routed pages were emitted as separate chunks. |
| Frontend npm test after fix pass | `npm test` from `eMas Front` | Passed | 48 tests passed, 0 failed, 0 skipped, duration 5630.1475 ms. |
| Frontend overlap check after fix pass | `npm run verify-overlaps` from `eMas Front` | Passed | Found 26 jobs and 26 proposal IDs. Local partial-overlap check found no overlaps. API checks returned `valid: true`, `total_slots: 89`, `overlap_count: 0` for proposals and `valid: true`, `total_slots: 0`, `overlap_count: 0` for applied. |
| Phase 6 pre-check branch/status gate | `git branch --show-current`; `git status --short --branch` from repo root | Passed | Branch was `integration/qa-upgrade-merge`; status output was only `## integration/qa-upgrade-merge`. |
| Phase 6 Go aggregate tests | `go test ./...` from `emas` | Passed | All packages passed or had no test files; key packages included `emas/internal/e2e`, `emas/internal/handler`, `emas/internal/router`, and `emas/internal/service`. |
| Phase 6 Go e2e tests | `go test ./internal/e2e` from `emas` | Passed | Output: `ok emas/internal/e2e (cached)`. |
| Phase 6 Factory Agent suite | `python -m pytest factory-agent/tests --basetemp ".pytest-basetemp"` | Passed | 492 passed, 4 skipped, 20 xfailed, 1588 warnings in 65.95s. |
| Phase 6 seed manifest check | `python -m pytest factory-agent/tests/test_seed_pipeline_manifest.py --basetemp ".pytest-basetemp-seed"` | Passed | 125 passed, 1 warning in 0.73s before the seeded-runner fix; rerun after the auth-header fix also passed: 125 passed, 1 warning in 0.66s. |
| Phase 6 frontend lint | `npm run lint` from `eMas Front` | Passed | ESLint completed with 0 errors and 0 warnings under `--max-warnings 0`. |
| Phase 6 frontend build | `npm run build` from `eMas Front` | Passed | Vite build passed in 1.67s. Initial `index` JS chunk was 179.72 kB; `AIAssistantModal` chunk was 115.00 kB. |
| Phase 6 frontend overlap check | `npm run verify-overlaps` from `eMas Front` | Passed | Found 26 jobs and 26 proposal IDs. Local partial-overlap check found no overlaps. API checks returned `valid: true`, `total_slots: 89`, `overlap_count: 0` for proposals and `valid: true`, `total_slots: 0`, `overlap_count: 0` for applied. |
| Phase 6 frontend Factory Agent smoke | `npm run factory-agent-smoke` from `eMas Front` | Passed | Default host-local smoke used `base=http://127.0.0.1:8000`, created a session, added a message, created a plan, executed to `COMPLETED`, verified cancel flow returned `IDLE`, and passed. |
| Phase 6 frontend npm test script check | `npm pkg get scripts.test` from `eMas Front` | Passed | `scripts.test` exists and runs eight Node test files under `src/components/features/...`. |
| Phase 6 frontend npm tests | `npm test` from `eMas Front` | Passed | 48 tests passed, 0 failed, 0 skipped, duration 6708.408 ms. |
| Full seeded scenario runner initial run | `.\tests\e2e\run_seed_pipeline.ps1` from repo root | Failed | The Go fast e2e approval driver passed, Python manifest/reliability checks passed, then the full seeded scenario suite failed. Exact failing step: `Full seeded scenario suite`. Seven scenarios returned `401 {"success":false,"error":"missing authenticated user or role"}` instead of expected 200/403/422/409: `scheduling-batch-proposals`, `approval-role-blocks`, `approval-proposal-draft-required`, `approval-apply-requires-approval`, `approval-stale-proposal-fails`, `approval-idempotent-retry`, and `approval-already-decided`. Classification: API auth contract/test manifest mismatch; Phase 6 blocker until fixed. Log: `test-artifacts/logs/seed-pipeline-20260515T162713Z.log`. |
| Seeded scenario auth-header fix | Updated `tests/e2e/scenarios/seed_pipeline.json` | Passed | Added `X-User-Id` beside existing `X-User-Role` for protected scheduling/approval seeded scenarios. This matches Go middleware, which requires both user id and role when `AI_AUTH_REQUIRED=true`. |
| Full seeded scenario runner after fix | `.\tests\e2e\run_seed_pipeline.ps1` from repo root | Passed | Go fast e2e approval driver passed; Python checks passed with 128 passed, 1 warning; full seeded scenario suite passed in 95.333s. Result summary: 124 manifest scenarios, 126 artifact files, 52 HTTP scenarios ran, 2 approval proofs passed, 72 contracts skipped by design, 0 other/needs check. Log: `test-artifacts/logs/seed-pipeline-20260515T163011Z.log`. |
| Docker Compose build initial run | `docker compose build` | Failed | Compose interpolation failed before build: `MYSQL_PASSWORD` was missing; root `.env` does not exist in this worktree. Environment related. |
| Docker Compose build with verification env | `MYSQL_PASSWORD=phase6-emas-user; MYSQL_ROOT_PASSWORD=phase6-root; docker compose build` | Passed | Images built for `go-api`, `factory-agent`, and `frontend`. Frontend Docker build again reported the known npm deprecation/vulnerability notices. |
| Docker Compose startup missing env file | `MYSQL_PASSWORD=phase6-emas-user; MYSQL_ROOT_PASSWORD=phase6-root; docker compose up -d` | Failed | Compose failed because `emas/.env` was missing. A minimal ignored local `emas/.env` was created for verification only and was not staged. |
| Docker Compose startup production-mode gate | `MYSQL_PASSWORD=phase6-emas-user; MYSQL_ROOT_PASSWORD=phase6-root; docker compose up -d` after adding local `emas/.env` | Failed | MySQL, Redis, Go API, and frontend started; Factory Agent exited because default `APP_MODE=production` rejected unsafe production config: `JWT_REQUIRED must be enabled`, `JWT_SECRET must be set`, and `ADMIN_API_KEY` must be changed. Environment/config related. |
| Docker Compose startup with development env | `MYSQL_PASSWORD=phase6-emas-user; MYSQL_ROOT_PASSWORD=phase6-root; APP_MODE=development; docker compose up -d` | Passed | All services started. `docker compose ps` showed `mysql` healthy, `redis` healthy, `go-api` healthy, `factory-agent` healthy, `frontend` up, and `nginx` publishing `0.0.0.0:80->80/tcp`. |
| Docker Compose seed command | `docker compose exec -T go-api seed` | Passed | Seeded the Compose MySQL database with canonical machines, jobs, proposals, production logs, quality inspections, maintenance, downtime, and scheduling settings. |
| Docker Compose Factory Agent readiness | `GET http://127.0.0.1/agent/ready` | Passed after auto-repair | Initial readiness was `503 not_ready` with `tool_registry.ok=false`, `tool_count=0`. After the Compose Factory Agent smoke attempted planning, logs showed `tool_registry_auto_repaired` with `tool_count=138`; `/agent/ready` then returned `status=ready` with database/settings/redis/tool registry ok. |
| Docker Compose Factory Agent natural-language smoke | `FACTORY_AGENT_BASE_URL=http://127.0.0.1/agent npm run factory-agent-smoke` from `eMas Front` | Failed | Session and message creation succeeded, then `POST /sessions/3e62def1-9528-4dbc-a620-dde40b8d66c9/plans` returned `[503] ... {"detail":{"errors":["Connection error."]}}`. Factory Agent logs show planner transient retries for `list machines`, model `Qwen2.5-7B-Instruct-Q4_K_M.gguf`, then 503. Classification: Compose/container LLM connectivity or environment wiring; Phase 6 blocker for full-stack Factory Agent chat. |
| Docker Compose shutdown | `docker compose down` | Passed | Verification containers and network were stopped/removed. `docker compose down -v` was not used. |

## Critical Flow Verification

| Flow | Status | Evidence / Notes |
|---|---|---|
| Find all machines | Passed | With Compose running and seeded, `GET http://127.0.0.1/api/v1/machines` returned 10 machines and included `M-CNC-01`. |
| Find all jobs | Passed | With Compose running and seeded, `GET http://127.0.0.1/api/v1/jobs` returned 26 seeded jobs. |
| Show status for machine `M-CNC-01` | Passed | `GET http://127.0.0.1/api/v1/machines/M-CNC-01` returned `M-CNC-01`, `CNC Mill 01`, status `running`. |
| Approval-required write flow | Passed | Through nginx/Go API, authenticated proposal approval for `AIPROP-SEED-001` with `X-User-Id=phase6-smoke` and `X-User-Role=planner` resulted in proposal status `approved`. |
| Approval rejection flow | Passed | Generated a fresh proposal `AIPROP-4279b147` for `JOB-SEED-002`, then authenticated `POST /api/v1/ai/scheduling/proposals/AIPROP-4279b147/reject`; response succeeded and contained `rejected`. |
| Backend error handling | Passed | `GET http://127.0.0.1/api/v1/machines/M-NOT-REAL` returned HTTP 404 through nginx. |
| SSE / snapshot / polling update | Passed | Created Factory Agent session `6b338d31-86de-4086-96f8-9f03be8e2d4b`; `GET /agent/sessions/{id}/snapshot` returned `cursor=0`, `phase=IDLE`; `GET /agent/sessions/{id}/events` emitted an SSE `event: notification` hello frame. `curl` timed out after 3 seconds as expected for an open SSE stream. |
| Final frontend answer avoids contradictory messages | Skipped live Compose chat; automated frontend check passed | `npm test` passed 48 component/assembly tests, including backend-unavailable rendering and completed-answer/plan-summary cases. A live Compose final-answer check could not be completed because Factory Agent plan creation failed with `503 Connection error`; no final answer was produced to inspect. |

## Cross-Layer Contract Checklist

| Contract Item | Status | Notes |
|---|---|---|
| Go API matches Factory Agent tool calls | Not started |  |
| OpenAPI / Swagger matches Go backend behavior | Not started |  |
| `tools.md` files are accurate | Not started |  |
| Factory Agent response matches frontend expected fields | Not started |  |
| Approval payload remains compatible | Not started |  |
| SSE / snapshot event shape remains compatible | Not started |  |
| Docker Compose can start all services | Not started |  |

## Remaining Risks

Record untested or uncertain items here:

- Phase 4 full-suite testing depends on avoiding the inaccessible default pytest temp root `C:\Users\dilun\AppData\Local\Temp\pytest-of-dilun`. The suite passed with a repo-local `--basetemp`, but the underlying machine temp permission issue remains outside the integration worktree.
- The Phase 6 full seeded runner now passes after the seed manifest auth-header fix. The original failure was an API auth contract/test-manifest mismatch: protected scheduling/approval scenarios had `X-User-Role` but lacked `X-User-Id` while `AI_AUTH_REQUIRED=true`.
- Docker Compose requires local environment setup before it can run from this worktree: root `.env` values for `MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD`, an `emas/.env` env file, and `APP_MODE=development` or production-grade JWT/admin settings. Phase 6 used ephemeral shell values plus a minimal ignored local `emas/.env`; these were not staged.
- Compose Factory Agent natural-language planning remains a Phase 6 blocker. The stack starts and `/agent/ready` becomes ready after tool registry auto-repair, but `FACTORY_AGENT_BASE_URL=http://127.0.0.1/agent npm run factory-agent-smoke` fails during plan creation with `503 {"detail":{"errors":["Connection error."]}}`. Logs show planner transient retries against model `Qwen2.5-7B-Instruct-Q4_K_M.gguf`, indicating container LLM connectivity/env wiring rather than Go API or tool registry failure.
- Live Compose frontend final-answer verification is incomplete because the Compose Factory Agent could not produce a completed chat answer. Frontend component tests for backend-unavailable and completed-answer rendering passed, but this does not replace a live browser/chat check.
- `npm install` reported 12 vulnerabilities (5 moderate, 7 high) and deprecated package warnings. No audit remediation was attempted during Phase 5.
- `emas/docs/swagger.json` and `emas/docs/swagger.yaml` changed, but `rag_sources/01_emas_internal_docs/api_reference/openapi.json` did not; this needs a later cross-layer contract check.
- Factory Agent route/service behavior changed, but `factory-agent/factory_agent/tools.md` and `rag_sources/01_emas_internal_docs/api_reference/tools.md` did not; tool documentation and generated tool definitions need verification later.
- The Go backend adds `002_ml_training_events_lineage.sql`; database migration safety remains unverified beyond successful AutoMigrate/startup in the Phase 6 Compose smoke and seeded runner.
- Factory Agent production startup now has stricter env/config behavior. Phase 6 observed the production guard blocking startup when `APP_MODE` defaulted to production without production JWT/admin settings; deployment-style production config still needs verification.
- Frontend EventSource streams are disabled when static bearer auth is configured because browser EventSource cannot send Authorization headers; snapshot polling fallback must be tested with bearer-token configuration.
- Phase 3 stabilization fixed the required Go aggregate test failures. Remaining risks are now Phase 4+ cross-layer risks, not known Go backend test failures.

## Final Recommendation

Choose one after Phase 7:

- Safe to merge into main.
- Safe to merge into main with minor known risks.
- Not safe to merge into main yet.

Current recommendation: `Not safe to merge into main yet`. Phase 6 has been run and is not fully passing because Compose Factory Agent planning fails with an LLM connection error, and Phase 7 has not been run. Do not start Phase 7 until the Compose Factory Agent planner connectivity/environment issue is resolved or explicitly accepted as out-of-scope.
