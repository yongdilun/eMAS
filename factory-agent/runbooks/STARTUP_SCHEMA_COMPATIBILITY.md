# Startup Schema Compatibility

Phase 5 / FA-004 is moving legacy startup schema mutation toward explicit
migration-backed behavior.

## Current Transition Behavior

- `ENABLE_STARTUP_SCHEMA_COMPAT=1` is the default and preserves the existing
  startup compatibility path.
- `ENABLE_STARTUP_SCHEMA_COMPAT=0` makes startup schema compatibility read-only.
  If compatibility DDL is still pending, startup fails with the affected
  table/column list instead of mutating the database.
- Startup logs emit `startup_schema_compatibility_check` with the pending
  compatibility action count. When mutation is enabled, each DDL action emits
  `startup_schema_compatibility_mutation`.

## Rollout Guidance

1. Run explicit schema migrations for the target database.
2. Start the app once with `ENABLE_STARTUP_SCHEMA_COMPAT=0` in staging.
3. Treat a startup failure as migration drift and apply the listed compatibility
   changes through the migration path before production rollout.
4. Keep the flag enabled only as a rollback bridge while migration coverage is
   being completed.
