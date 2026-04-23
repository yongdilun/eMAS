# Scaling Guide

## Capacity Targets
1. Concurrency target: `MAX_CONCURRENT=100`
2. Queue target: `MAX_QUEUE=500`

## Vertical Scaling
1. Increase worker pool:
   - `MAX_CONCURRENT` (or `AGENT_WORKERS`)
2. Increase DB pool:
   - `DB_POOL_SIZE`
   - `DB_MAX_OVERFLOW`
3. Tune HTTP timeout/backoff:
   - `HTTP_TIMEOUT_S`
   - `RETRY_BASE_DELAY_S`
   - `RETRY_MAX_DELAY_S`

## Horizontal Scaling
1. Run multiple API instances behind a load balancer.
2. Share DB + Redis across instances.
3. Keep idempotency and approval state centralized in DB.

## Scale Validation
1. Run:
   - `python scripts/load_test_backpressure.py --sessions 100 --concurrency 100 --require-100-success`
2. Saturation test:
   - `python scripts/load_test_backpressure.py --sessions 1500 --concurrency 300 --expect-429`
3. Query growth check:
   - `python scripts/profile_query_growth.py --batch-a 25 --batch-b 100`
