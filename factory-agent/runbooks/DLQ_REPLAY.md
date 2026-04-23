# DLQ Replay Procedure

## Objective
Replay safe failures and keep unsafe failures blocked for review.

## Steps
1. List pending entries:
   - `GET /dlq?status=PENDING`
2. Inspect each entry:
   - `failure_type`
   - `reason`
   - `payload.tool`, `payload.args`
3. Decide action:
   - Replay when root cause is resolved.
   - Dismiss when replay is unsafe or obsolete.
4. Replay:
   - `POST /dlq/{dlq_id}/replay`
5. Dismiss:
   - `POST /dlq/{dlq_id}/dismiss` with reason.
6. Verify outcome:
   - Session status transitions to `EXECUTING` for replayed entries.
   - Step status resets to `NOT_STARTED`.

## Safety Rules
1. Never replay `ambiguous_execution` for non-idempotent tools without human confirmation.
2. Always annotate dismiss reason with ticket/reference id.
