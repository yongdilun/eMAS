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
| 2 | Review all branches before merging | Not started | Record all branch reviews before any merge. |
| 3 | Merge Go backend branch | Not started | Branch: `audit/go-backend-phase-5`. |
| 4 | Merge Factory Agent branch | Not started | Branch: `audit/factory-agent`. |
| 5 | Merge frontend branch | Not started | Branch: `audit/frontend-phase-5`. |
| 6 | Full integration verification | Not started | Run after all three merges are complete. |
| 7 | Cross-layer contract check | Not started | Run after integration verification. |
| 8 | Final report | Not started | Stop after report; do not merge to `main`. |

## Branch Review Table

| Branch | Area | Main Changes | Contract Impact | Conflict Risk | Runtime Risk | Review Status |
|---|---|---|---|---|---|---|
| `audit/go-backend-phase-5` | Go backend |  |  |  |  | Not started |
| `audit/factory-agent` | Factory Agent / FastAPI |  |  |  |  | Not started |
| `audit/frontend-phase-5` | React frontend |  |  |  |  | Not started |

## Merge Result Table

| Step | Branch | Result | Conflicts | Checks Run | Safe To Continue |
|---|---|---|---|---|---|
| 1 | `audit/go-backend-phase-5` | Not started |  |  |  |
| 2 | `audit/factory-agent` | Not started |  |  |  |
| 3 | `audit/frontend-phase-5` | Not started |  |  |  |

## Conflicts Resolved

If no conflicts are found, write: `No merge conflicts were found.`

| File | Cause | Resolution | Why Safe |
|---|---|---|---|
|  |  |  |  |

## Tests and Checks

| Check | Command | Result | Notes |
|---|---|---|---|
| Worktree clean before branch review | `git status --short --branch` | Not started |  |
| Go tests after Go merge | `go test ./...` from `emas` | Not started |  |
| Go e2e after Go merge | `go test ./internal/e2e` from `emas` | Not started |  |
| Factory Agent tests after agent merge | `python -m pytest factory-agent/tests` | Not started |  |
| Seed manifest check | `python -m pytest factory-agent/tests/test_seed_pipeline_manifest.py` | Not started |  |
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

- 

## Final Recommendation

Choose one after Phase 7:

- Safe to merge into main.
- Safe to merge into main with minor known risks.
- Not safe to merge into main yet.

Current recommendation: `Not safe to merge into main yet` because phases 2 through 7 have not been run.
