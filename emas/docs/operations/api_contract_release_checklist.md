# API Contract Release Checklist

Use this before publishing a Go backend change that affects routes, response schemas, OpenAPI, or generated tools.

## Required Checks

- Actual Gin routes match `docs/swagger.json`.
- Public response fields are intentionally named and covered by golden tests when changed.
- Error responses use the standard `dto.Response` envelope.
- New or changed write endpoints document auth, idempotency, and rollback behavior.
- Swagger has been regenerated when annotations, DTOs, routes, or schemas changed.
- API consumers have a compatibility note for any response casing or status-code change.
- Scheduling API changes include overlap/calendar regression coverage.

## Commands

```sh
go test ./internal/router -count=1
go test ./internal/handler -run Contract -count=1
go test ./internal/service -count=1
```

If OpenAPI changes, run the repository Swagger generation flow and then regenerate downstream tool metadata before release. If OpenAPI does not change, note "Swagger unchanged; tools.md regeneration not required" in the release notes.

## Release Note Template

- API behavior changed:
- Swagger regenerated:
- tools.md regenerated:
- Rollback impact:
- Contract tests run:

