# Scheduling Performance Smoke Tests

Phase 5 adds an HTTP-level smoke test for the scheduling endpoints with the highest operational risk:

```sh
go test ./internal/handler -run TestAISchedulingPerformanceSmokeBatchProposalsAndRescheduleAll -count=1
```

The test seeds a small deterministic planning set, calls `POST /api/v1/ai/scheduling/batch-proposals`, then calls `POST /api/v1/ai/scheduling/reschedule-all` with `dry_run=true`. It asserts both endpoints return at least one generated proposal within a generous local smoke budget.

This is not a full load test. Use it as a release gate to catch severe runtime regressions before broader profiling or production-like load testing.

