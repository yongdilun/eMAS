# QA Upgrade Integration Plan

Created: 2026-05-15

This runbook is for the staged integration branch `integration/qa-upgrade-merge`.
Run commands from PowerShell unless a command says otherwise.

## Current Integration Base

| Item | Value |
|---|---|
| Main branch | `main` |
| Integration branch | `integration/qa-upgrade-merge` |
| Integration worktree | `C:\Users\dilun\OneDrive\Documents\emas-integration-qa` |
| Integration base commit | `361871d docs: move audit plans to repo root` |
| Remote state | `main` is 2 commits ahead of `origin/main`; `git pull --ff-only` returned `Already up to date.` |

## Branch Inventory

| Area | Branch | Worktree | Phase 0 Status |
|---|---|---|---|
| Go backend | `audit/go-backend-phase-5` | `C:\Users\dilun\OneDrive\Documents\emas-audit-go` | Clean |
| Factory Agent / FastAPI | `audit/factory-agent` | `C:\Users\dilun\OneDrive\Documents\emas-audit-agent` | Clean |
| React frontend | `audit/frontend-phase-5` | `C:\Users\dilun\OneDrive\Documents\emas-audit-frontend` | Clean |
| Main | `main` | `C:\Users\dilun\OneDrive\Documents\eMas APi` | Clean, ahead 2 |

Older branch pointers also exist, including `audit/go-backend`, `audit/frontend`, and intermediate phase branches.
For this integration, use the checked-out final phase branches listed above.

## Safety Rules

- Do not merge into `main`.
- Do not push unless explicitly approved.
- Do not force-push.
- Do not delete branches or worktrees.
- Do not run `git reset --hard` or `git clean -fd` unless explicitly approved.
- Stop before every merge if `git status --short --branch` shows uncommitted changes.
- Do not merge all branches at once.
- Do not make unrelated refactors while resolving conflicts.
- Do not claim a check passed unless the command was actually run.
- If a merge, test, build, or startup check fails, stop and record it in the tracker before continuing.

## Phase 0 - Completed

Commands already run from `C:\Users\dilun\OneDrive\Documents\eMas APi`:

```powershell
git status --short --branch
git branch --show-current
git branch --all
git worktree list --porcelain
git log --oneline --decorate --graph --all --max-count=40
```

All existing worktrees were checked with:

```powershell
git status --short --branch
```

Result: no uncommitted changes were found in the existing worktrees.

## Phase 1 - Completed

Commands already run from `C:\Users\dilun\OneDrive\Documents\eMas APi`:

```powershell
git switch main
git pull --ff-only
git worktree add -b integration/qa-upgrade-merge ../emas-integration-qa main
```

Result: `C:\Users\dilun\OneDrive\Documents\emas-integration-qa` was created on `integration/qa-upgrade-merge`.

## Phase 2 - Review Before Merge

Start here:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa"
git status --short --branch
```

Stop if the worktree is dirty.

Review the Go backend branch:

```powershell
git log main..audit/go-backend-phase-5 --oneline
git diff main..audit/go-backend-phase-5 --stat
git diff --name-status main..audit/go-backend-phase-5
```

Review the Factory Agent branch:

```powershell
git log main..audit/factory-agent --oneline
git diff main..audit/factory-agent --stat
git diff --name-status main..audit/factory-agent
```

Review the frontend branch:

```powershell
git log main..audit/frontend-phase-5 --oneline
git diff main..audit/frontend-phase-5 --stat
git diff --name-status main..audit/frontend-phase-5
```

For each branch, record these in the tracker:

- Main changes.
- Affected subsystem.
- Possible shared contract impact.
- Possible conflict risk.
- Runtime risk.

Contract watchpoints:

- Go API response fields and error payloads.
- `emas/docs/swagger.json`, `emas/docs/swagger.yaml`, and `rag_sources/01_emas_internal_docs/api_reference/openapi.json`.
- `factory-agent/factory_agent/tools.md` and `rag_sources/01_emas_internal_docs/api_reference/tools.md`.
- Factory Agent tool definitions, tool names, arguments, and response models.
- Approval payloads, session state, and write-flow behavior.
- SSE, snapshot, and polling event shapes.
- Frontend API mapping, final answer rendering, and approval UI.
- `docker-compose.yml`, `.env.example`, and environment variable names.
- Added, removed, or renamed tests.

Do not merge until all three branch reviews are recorded.

## Phase 3 - Merge Go Backend First

Pre-merge gate:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa"
git status --short --branch
```

Stop if dirty.

Merge:

```powershell
git merge --no-ff audit/go-backend-phase-5
git status --short --branch
```

If conflicts occur:

```powershell
git status --short
rg -n "<<<<<<<|=======|>>>>>>>" .
```

Resolve carefully, stage only resolved files, and finish the merge commit. Record every conflict in the tracker.

Minimum checks after a clean merge:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa\emas"
go test ./...
```

Optional backend contract checks, if the branch changed Swagger or OpenAPI generation:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa\emas"
go test ./internal/e2e
```

Continue only if the merge and required checks are acceptable.

## Phase 4 - Merge Factory Agent Second

Pre-merge gate:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa"
git status --short --branch
```

Stop if dirty.

Merge:

```powershell
git merge --no-ff audit/factory-agent
git status --short --branch
```

If conflicts occur:

```powershell
git status --short
rg -n "<<<<<<<|=======|>>>>>>>" .
```

Preserve session, approval, tool-calling, and SSE behavior. Do not overwrite OpenAPI or `tools.md` changes without comparing both sides.

Minimum checks after a clean merge:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa"
python -m pytest factory-agent/tests
```

Useful targeted checks if contract files changed:

```powershell
python -m pytest factory-agent/tests/test_seed_pipeline_manifest.py
python -m pytest factory-agent/tests/test_rag_live_llm.py
```

The live RAG test may skip unless the required environment variables are set. Mark it as `Skipped`, not `Passed`, if that happens.

Continue only if the merge and required checks are acceptable.

## Phase 5 - Merge Frontend Third

Pre-merge gate:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa"
git status --short --branch
```

Stop if dirty.

Merge:

```powershell
git merge --no-ff audit/frontend-phase-5
git status --short --branch
```

If conflicts occur:

```powershell
git status --short
rg -n "<<<<<<<|=======|>>>>>>>" .
```

Preserve chat UI behavior, approval UI behavior, SSE/snapshot/polling behavior, and Factory Agent response compatibility.

Available frontend commands on the current base:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa\eMas Front"
npm install
npm run lint
npm run build
npm run verify-overlaps
npm run factory-agent-smoke
```

There is no `npm test` script on the current base. If the frontend branch adds one, run it and record the exact command.

Continue only if the merge and required checks are acceptable.

## Phase 6 - Full Integration Verification

Run from the fully merged integration worktree.

Go backend:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa\emas"
go test ./...
go test ./internal/e2e
```

Factory Agent:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa"
python -m pytest factory-agent/tests
python -m pytest factory-agent/tests/test_seed_pipeline_manifest.py
```

Frontend:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa\eMas Front"
npm run lint
npm run build
npm run verify-overlaps
```

Seeded scenario runner:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa"
.\tests\e2e\run_seed_pipeline.ps1
```

Docker Compose build and startup:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\emas-integration-qa"
docker compose build
docker compose up -d
docker compose ps
```

If services were started only for this verification, stop them after recording results:

```powershell
docker compose down
```

Do not use `docker compose down -v` unless explicitly approved.

Critical manual or smoke flows to verify when services are running:

1. Find all machines.
2. Find all jobs.
3. Show status for machine `M-CNC-01`.
4. Approval-required write flow.
5. Approval rejection flow.
6. Backend error handling.
7. SSE, snapshot, or polling update.
8. Final frontend answer does not show contradictory messages.

## Phase 7 - Cross-Layer Contract Check

Verify and record:

- Go API behavior matches Factory Agent tool calls.
- Swagger/OpenAPI files match actual Go backend behavior.
- `tools.md` files are accurate if regenerated or edited.
- Factory Agent response fields match frontend expected fields.
- Approval payload remains compatible across backend, agent, and frontend.
- SSE/snapshot event shape remains compatible.
- Docker Compose can start all services with documented environment variables.

Suggested file-focused checks:

```powershell
git diff main..HEAD --stat
git diff main..HEAD -- "emas/docs/swagger.json" "emas/docs/swagger.yaml" "rag_sources/01_emas_internal_docs/api_reference/openapi.json"
git diff main..HEAD -- "factory-agent/factory_agent/tools.md" "rag_sources/01_emas_internal_docs/api_reference/tools.md"
git diff main..HEAD -- "docker-compose.yml" ".env.example"
```

## Phase 8 - Final Report

Use the required report sections from the task prompt:

- Integration Summary.
- Phase Result Table.
- Branch Review Table.
- Merge Result Table.
- Conflicts Resolved.
- Tests and Checks.
- Remaining Risks.
- Final Recommendation.

Recommendation choices:

- Safe to merge into main.
- Safe to merge into main with minor known risks.
- Not safe to merge into main yet.

Stop after the report. Do not merge `integration/qa-upgrade-merge` into `main` until approved.
