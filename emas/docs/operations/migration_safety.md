# Migration Safety Plan

Phase 5 keeps GORM `AutoMigrate` enabled by default for tests and local developer setup, while allowing production deployments to turn it off with:

```sh
EMAS_AUTO_MIGRATE=false
```

Production schema changes should be applied as reviewed SQL from `migrations/` before the application is rolled forward. The current manual runtime schema change for `ml_training_events` is captured in `migrations/002_ml_training_events_lineage.sql` so it can be reviewed, tested against a database snapshot, and rolled back independently from application startup.

## Rollout Steps

1. Take a MySQL snapshot or backup.
2. Run the pending SQL migration in a staging copy of production data.
3. Verify `ml_training_events` has `lineage_id`, nullable `slot_id`, `split_group_id`, and `batch_sequence`.
4. Run backend smoke tests against staging.
5. Set `EMAS_AUTO_MIGRATE=false` for production.
6. Apply the migration during the deployment window.
7. Deploy the Go backend.
8. Monitor startup logs for `automigrate_skipped` and request logs for elevated 4xx/5xx rates.

## Rollback Notes

Application rollback is safe when the database is forward-compatible. For `ml_training_events`, do not restore `slot_id` as the primary key until draft training rows without `slot_id` have been archived or removed. Prefer rolling back the application first, then performing any schema rollback as a separate database operation after data inspection.

