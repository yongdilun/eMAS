# Cold Start Checklist

## Before Start
1. DB reachable.
2. Redis reachable (if configured).
3. Required env vars present.

## On Start
1. Confirm startup logs:
   - `agent_server_started`
   - `cold_start_recovery_sweep`
2. Validate metrics baseline:
   - `active_sessions`
   - `dlq_pending_count`
   - `ambiguous_step_count`

## Recovery Validation
1. Sessions previously in `EXECUTING/PLANNING/WAITING_APPROVAL` should:
   - Resume execution, or
   - Move to `BLOCKED` + DLQ when ambiguous.
2. Check pending approvals and DLQ entries from startup.

## Post-Start Actions
1. Run smoke load:
   - `python scripts/load_test_backpressure.py --sessions 20 --concurrency 10`
2. Confirm no persistent queue growth.
