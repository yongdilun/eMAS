# Phase 0 Go Backend Baseline

Date: 2026-05-15

Branch: `audit/go-backend-phase-0`

Base commit before Phase 0 artifacts: `afdb661`

## Captured Artifacts

- Swagger snapshot:
  - `docs/audit/phase0/swagger/swagger.baseline.json`
  - `docs/audit/phase0/swagger/swagger.baseline.yaml`
- API response samples:
  - `docs/audit/phase0/api_responses/jobs_list_fields.json`
  - `docs/audit/phase0/api_responses/machines_list_fields.json`
  - `docs/audit/phase0/api_responses/inventory_materials_list.json`
  - `docs/audit/phase0/api_responses/scheduling_readiness.json`
  - `docs/audit/phase0/api_responses/ai_job_proposals_list.json`
  - `docs/audit/phase0/api_responses/ai_proposal_detail_seed_001.json`

## Regeneration

Swagger snapshots were copied from the current generated files before Phase 1 contract edits:

```powershell
Copy-Item docs\swagger.json docs\audit\phase0\swagger\swagger.baseline.json -Force
Copy-Item docs\swagger.yaml docs\audit\phase0\swagger\swagger.baseline.yaml -Force
```

API response samples were generated from the existing Gin router, SQLite test database, and canonical seed data:

```powershell
$env:EMAS_CAPTURE_PHASE0_BASELINE='1'
go test ./internal/audit -run TestCapturePhase0BaselineResponses -count=1 -v
```

Normal test runs do not write these files; the capture test skips unless `EMAS_CAPTURE_PHASE0_BASELINE=1` is set.

## Test Baseline

- `go test ./internal/service -count=1`: passed.
- `go test ./internal/e2e -count=1`: passed.
- `go test ./internal/audit -count=1`: passed.
- `go test ./internal/handler -count=1 -timeout 180s -v`: blocked by timeout.

Handler timeout bisection:

- `TestAISchedulingHandler_Features` times out when run alone with a 45s timeout.
- `TestRealSolverProposalLifecycle` times out when run alone with a 60s timeout.
- All other individual handler tests passed when run one at a time with 60s timeouts.
- Both timeout stacks block in proposal apply-by-ID while waiting for a database connection inside a transaction on the shared SQLite test DB.

## Docker Compose Health

Docker Compose startup was not performed in this Phase 0 branch to avoid affecting other active worktrees/chats. Non-invasive checks found:

- `docker compose ps` cannot load without environment values because the worktree does not contain `.env`.
- `docker compose --env-file "C:\Users\dilun\OneDrive\Documents\eMas APi\.env" config --quiet` still fails because `emas/.env` is missing in this worktree.
- `docker compose --env-file "C:\Users\dilun\OneDrive\Documents\eMas APi\.env" ps` shows no running Compose containers for this worktree.
