# Scheduling Apply-All Integration Contract

Purpose: single source of truth for frontend integration of batch proposal generation, overlap verification, approve/apply-all, and recovery/error handling.

---

## 1) Canonical Flow (must follow in order)

1. Generate proposals:
   - `POST /api/v1/ai/scheduling/batch-proposals`
2. Verify proposal overlap before approval/apply:
   - `POST /api/v1/ai/scheduling/verify-overlaps` with `scope: "proposals"` and `proposal_ids`
3. Approve all proposals (if approval is enabled):
   - `POST /api/v1/ai/scheduling/proposals/:id/approve`
4. Apply all proposals:
   - `POST /api/v1/ai/scheduling/proposals/:id/apply`
5. Verify applied overlaps for the exact applied job set:
   - `POST /api/v1/ai/scheduling/verify-overlaps` with `scope: "applied"` and `job_ids`

Do not skip step 2 or step 5 in batch mode.
Only approve/apply proposals where `feasible=true`.

---

## 2) Required Request Body for Apply-All

Use this for both approve and apply requests in the same batch:

```json
{
  "skip_staleness_check": true,
  "idempotency_key": "apply-all-<batch-id>-<proposal-id>"
}
```

Notes:
- `skip_staleness_check: true` is mandatory in apply-all to avoid expected stale failures on proposal 2+.
- `idempotency_key` should be unique per proposal per batch; retries with same key are safe.

---

## 3) Verify-Overlaps Contract

### A) Proposal verification (pre-apply)

```json
{
  "scope": "proposals",
  "proposal_ids": ["AIPROP-1", "AIPROP-2"]
}
```

### B) Applied verification (post-apply)

```json
{
  "scope": "applied",
  "job_ids": ["JOB-1", "JOB-2"]
}
```

Important:
- If `scope="applied"` and `job_ids` is omitted, backend checks all active slots in the system.
- For batch validation, always send `job_ids` to avoid unrelated conflicts from other jobs.

---

## 4) Error Handling Rules

### A) Stale proposal (409)

Backend message includes `error_code=proposal_stale`.

Frontend behavior:
1. If apply-all: ensure both approve/apply requests include `skip_staleness_check: true`.
2. If still stale after fix: stop batch and run Reschedule All to regenerate.
3. Show one toast, not repeated per remaining proposal.

### B) Work calendar violation (400/422)

Example message:
`slot is outside resource work calendar (job_step_id=..., machine_id=..., start=..., end=...) ...`

Frontend behavior:
1. Stop batch on first such error.
2. Show one toast with backend message.
3. Run `POST /api/v1/scheduling/refresh-work-calendars`.
4. Regenerate proposals, then retry approve/apply.

Calendar evaluation guarantees:
- Backend evaluates machine calendar + global settings calendar + resource calendar using plant-local timezone.
- Proposal generation and apply-time validation both use the same strict calendar gate.
- If the heuristic/preview builder emits a slot that fails strict checks (common case: **scheduled end after `scheduling.work_end_time`**, e.g. 17:05 vs template 17:00), the backend runs **chain-aware repair** for that job (with the same tentative machine occupancy as earlier jobs in the batch) before failing `reschedule-all` / batch-proposals with 422.
- Repair path is chain-aware and forward-only: when a step conflicts, backend may reschedule from that step through the rest of the job chain.
- No-backtracking guarantee: a repaired slot will not be moved earlier than its prior attempted start in the same scheduling run.
- Reason codes may be included in message text:
  - `reason_code=calendar_outside_shift`
  - `reason_code=holiday_blocked`
  - `reason_code=resource_calendar_blocked`
  - `reason_code=horizon_cap_reached`
  - `reason_code=no_feasible_window`

### C) Overlap warning

If verify-overlaps returns conflicts:
1. Do not apply.
2. Show machine IDs and overlap pairs.
3. Regenerate proposals (or run Reschedule All) before retry.

### D) Horizon cap / no feasible window (422)

Backend may return no-feasible-window diagnostics when adaptive horizon expansion reaches cap.
Retry policy is deterministic and bounded:
- Primary strict-placement horizon: `3 days` (fast, near-term)
- Retry horizon: `6 days` (congestion / weekend gaps; also caps default adaptive candidate horizon)
- Extended fallback horizon: up to `14 days` **only** if primary + retry still fail with eligible `NO_WINDOW`-style reasons (reduces false infeasible without scanning 14d on every step)
- Retry/extended are forward-only; `max_retry_attempts=1` per tier for placement passes
- Strict placement uses per-step `TOP_K_MACHINES=2` deterministic machine attempts
- Candidate ranking is computed once per step cycle; no in-loop re-ranking
- Retry never relaxes constraints (global shift, machine calendar, resource calendar still required)
- Retry is skipped for structural failures (`calendar_outside_shift`, overlap conflicts, precedence violations)
- Machine attempts share identical immutable input state (start baseline, precedence-resolved cursor, horizon, tentative snapshot)
- Early-exit optimization may stop attempts when structural failure signatures repeat
- Split fallback (same machine only) may be used after continuous `NO_WINDOW` failure:
  - deterministic earliest-first interval packing
  - `slice_count <= maxSlicesPerStep`
  - `covered_minutes >= required_minutes`
  - slices are non-overlapping (`slice[i].end <= slice[i+1].start`)
  - precedence uses `last_slice.end` as step finish time
  - gap policy is explicit (`max_gap_between_slices`, default unlimited)

Example details embedded in message:
- `expanded_steps=<n>`
- `horizon_end=<timestamp>`
- `reason_code=overlap_unresolved` (if repair + fallback still cannot eliminate conflicts)

Backend observability (structured log fields):
- `job_id`
- `retry`
- `extended_fallback` (true when extended 14d pass ran)
- `primary_horizon_days`
- `retry_horizon_days`
- `extended_horizon_days`
- `result` (`feasible` | `still_infeasible`)
- `final_reason`
- `attempted_machine_ids`
- `attempted_count`
- `selected_machine_id`
- `early_exit`
- `early_exit_signature`
- `attempts: [{machine, result_enum, signature}]`
- `result_enum` values: `NO_WINDOW`, `OVERLAP`, `PRECEDENCE`, `CALENDAR`, `UNKNOWN`

Frontend behavior:
1. Stop batch and show one actionable toast.
2. Surface backend details directly in expandable error panel.
3. Offer retry actions:
   - regenerate proposals with updated calendars/capacity,
   - split job set into smaller batches.

### E) Infeasible proposal approval blocked (422)

Example message:
`proposal is not fully feasible and cannot be approved: reason_code=no_feasible_window ...`

Frontend behavior:
1. Skip the proposal and continue only with proposals where `feasible=true`.
2. Display `blocked_reasons[0]` inline in proposal card/details.
3. Do not retry approve/apply for the same infeasible proposal without regeneration.

---

## 5) Batch Execution Policy (frontend)

- Execute approve/apply sequentially per proposal to keep deterministic order.
- Stop-on-first-hard-error:
  - stale (without skip),
  - work calendar violation,
  - overlap validation failure.
- For mixed results, apply feasible subset only and report skipped infeasible proposals.
- Do not continue and spam repeated toasts after the first hard error.

---

## 6) Suggested UI Copy

- Success: `Applied X/Y proposals successfully.`
- Stale: `Some proposals are stale for this batch. Regenerate schedule or ensure skip_staleness_check is enabled.`
- Work calendar: `A slot is outside work calendar. Refresh calendars and regenerate proposals.`
- Overlap: `Schedule conflicts detected on machines: ... Regenerate before apply.`

---

## 7) Minimal Frontend Checklist

- [ ] Use `skip_staleness_check: true` for approve/apply in apply-all.
- [ ] Use deterministic idempotency keys per proposal.
- [ ] Pre-apply verify with `scope=proposals`.
- [ ] Post-apply verify with `scope=applied` + exact `job_ids`.
- [ ] Stop on first hard error; no repeated error spam.
- [ ] Show backend error message directly in toast.
- [ ] When `no feasible window` or `overlap_unresolved`, show diagnostics (`expanded_steps`, `horizon_end`, reason code) and block apply.
- [ ] Filter approve/apply candidates by `feasible=true` and show skipped count/reasons.

