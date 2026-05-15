# Deployment Rollback Notes

Use this checklist for Go backend releases that include runtime behavior, OpenAPI, or database changes.

## Before Deploy

- Confirm the release commit and previous known-good commit.
- Run relevant Go tests and record the command output in the release notes.
- If `docs/swagger.json` or `docs/swagger.yaml` changed, regenerate Swagger before tagging the release.
- If API tools are generated from OpenAPI, regenerate and smoke-test them before deploy.
- For schema changes, take a MySQL snapshot and apply versioned SQL in staging first.
- In production, set `EMAS_AUTO_MIGRATE=false` once all required migrations are managed through reviewed SQL.

## Roll Forward

- Apply database migrations first when they are backward-compatible.
- Deploy the Go backend.
- Check `/health`.
- Watch structured `http_request` logs by `correlation_id`, `route`, `status`, and `latency_ms`.
- Smoke-test scheduling endpoints:
  - `POST /api/v1/ai/scheduling/batch-proposals`
  - `POST /api/v1/ai/scheduling/reschedule-all` with `dry_run=true`
  - `POST /api/v1/ai/scheduling/verify-overlaps`

## Roll Back

- Roll back the Go backend binary/container to the previous known-good commit.
- Keep forward-compatible schema additions in place during application rollback unless a migration explicitly documents a safe down path.
- Restore the database snapshot only for destructive or incompatible migrations.
- If OpenAPI changed, republish the previous Swagger/tools bundle with the backend rollback.
- Verify logs show the previous version serving requests and no new 5xx spike.

