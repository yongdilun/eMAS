# Normal Operations Runbook

## Startup
1. Export env variables (`DATABASE_URL`, `REDIS_URL`, `MAX_CONCURRENT=100`, `MAX_QUEUE=500`, `JWT_REQUIRED`, `JWT_SECRET`).
2. Start API server.
3. Verify:
   - `GET /health` returns `{"status":"ok"}`
   - `GET /metrics` has `worker_pool_utilization`, `session_queue_depth`, `db_connection_pool_usage`

## Daily Checks
1. Queue health:
   - `session_queue_depth` should return to near-zero after peaks.
2. Worker health:
   - `worker_pool_utilization` should not stay pinned at `1.0` for long periods.
3. DLQ:
   - `GET /dlq?status=PENDING` should be reviewed each shift.
4. Slow queries:
   - Check `db_slow_query_total` trend.

## Incident Escalation Triggers
1. `sessions_rejected_429_total` increasing while utilization is low.
2. `dlq_pending_count` growing continuously for >30 minutes.
3. Repeated `redis_unavailable` events.
