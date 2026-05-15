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
| 5 | Merge frontend branch | Not started | Branch: `audit/frontend-phase-5`. |
| 6 | Full integration verification | Not started | Run after all three merges are complete. |
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
| 3 | `audit/frontend-phase-5` | Not started |  |  |  |

## Conflicts Resolved

If no conflicts are found, write: `No merge conflicts were found.`

Phase 3 found no merge conflicts. Phase 4 found one merge conflict and it was resolved.

| File | Cause | Resolution | Why Safe |
|---|---|---|---|
| None | Go backend branch merged cleanly using Git `ort` strategy. | No conflict resolution was needed. | Phase 2 tracker updates were already committed before merge; Go backend API contract changes were accepted through the clean merge. |
| `factory-agent/CODE_PRACTICE_RULES.md` | The integration side contained frontend phase/window worktree rules that were absent on `audit/factory-agent`. | Kept the integration-side frontend phase/window rules and removed only the conflict markers. | Documentation-only conflict. It preserves prior integration rules and does not touch OpenAPI, `tools.md`, Go backend API contract changes, Factory Agent runtime/session/approval/SSE behavior, or tracker history. |

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
| Frontend install | `npm install` from `eMas Front` | Not started |  |
| Frontend lint | `npm run lint` from `eMas Front` | Not started |  |
| Frontend build | `npm run build` from `eMas Front` | Not started |  |
| Frontend overlap check | `npm run verify-overlaps` from `eMas Front` | Not started |  |
| Frontend factory-agent smoke | `npm run factory-agent-smoke` from `eMas Front` | Not started |  |
| Full seeded scenario runner | `.\tests\e2e\run_seed_pipeline.ps1` from repo root | Not started |  |
| Docker Compose build | `docker compose build` | Not started |  |
| Docker Compose startup | `docker compose up -d` and `docker compose ps` | Not started |  |

## Critical Flow Verification

| Flow | Status | Evidence / Notes |
|---|---|---|
| Find all machines | Not started |  |
| Find all jobs | Not started |  |
| Show status for machine `M-CNC-01` | Not started |  |
| Approval-required write flow | Not started |  |
| Approval rejection flow | Not started |  |
| Backend error handling | Not started |  |
| SSE / snapshot / polling update | Not started |  |
| Final frontend answer avoids contradictory messages | Not started |  |

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
- Frontend has not been merged. Remaining frontend conflict risk is inferred from changed files only; actual conflicts may still appear in Phase 5.
- `emas/docs/swagger.json` and `emas/docs/swagger.yaml` changed, but `rag_sources/01_emas_internal_docs/api_reference/openapi.json` did not; this needs a later cross-layer contract check.
- Factory Agent route/service behavior changed, but `factory-agent/factory_agent/tools.md` and `rag_sources/01_emas_internal_docs/api_reference/tools.md` did not; tool documentation and generated tool definitions need verification later.
- The Go backend adds `002_ml_training_events_lineage.sql`; database migration safety and seed data compatibility remain unverified.
- Factory Agent production startup now has stricter env/config behavior; `APP_MODE`, `JWT_REQUIRED`, `JWT_SECRET`, `ENABLE_STARTUP_CREATE_ALL`, and `ENABLE_STARTUP_SCHEMA_COMPAT` need deployment-style verification.
- Frontend EventSource streams are disabled when static bearer auth is configured because browser EventSource cannot send Authorization headers; snapshot polling fallback must be tested with bearer-token configuration.
- Phase 3 stabilization fixed the required Go aggregate test failures. Remaining risks are now Phase 4+ cross-layer risks, not known Go backend test failures.

## Final Recommendation

Choose one after Phase 7:

- Safe to merge into main.
- Safe to merge into main with minor known risks.
- Not safe to merge into main yet.

Current recommendation: `Not safe to merge into main yet` because phases 5 through 7 have not been run.
