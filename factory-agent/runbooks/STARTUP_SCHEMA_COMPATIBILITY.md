# Startup Schema Compatibility

Phase 5 / FA-004 is moving legacy startup schema mutation toward explicit
migration-backed behavior.

## Current Transition Behavior

- `ENABLE_STARTUP_SCHEMA_COMPAT=0` is the default and makes startup schema
  compatibility read-only.
  If compatibility DDL is still pending, startup fails with the affected
  table/column list instead of mutating the database.
- `ENABLE_STARTUP_SCHEMA_COMPAT=1` temporarily restores the legacy startup
  compatibility mutation path as a rollback bridge.
- `ENABLE_STARTUP_CREATE_ALL=0` is the default in production mode. Development
  keeps `create_all` enabled by default for fresh local databases.
- Startup logs emit `startup_schema_compatibility_check` with the pending
  compatibility action count. When mutation is enabled, each DDL action emits
  `startup_schema_compatibility_mutation`.

## Rollout Guidance

1. Run explicit schema migrations for the target database.
2. Start the app once with `ENABLE_STARTUP_SCHEMA_COMPAT=0` in staging.
3. Treat a startup failure as migration drift and apply the listed compatibility
   changes through the migration path before production rollout.
4. Enable `ENABLE_STARTUP_SCHEMA_COMPAT=1` only as a short-lived rollback bridge.
