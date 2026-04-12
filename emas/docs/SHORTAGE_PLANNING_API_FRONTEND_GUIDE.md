# Shortage Planning API + Frontend Integration Guide

This document explains the new shortage-aware scheduling APIs and the frontend changes required to use them safely.

**Base URL:** `http://localhost:8080/api/v1`  
**Auth/role header for write operations:** `X-User-Role: planner` (or manager/admin)

---

## New Endpoints

### 1) Shortage Analysis (read-only, dry-run style)

```http
GET /api/v1/ai/scheduling/jobs/{job_id}/shortage-analysis
```

Use this before apply/replenish to show users what is blocked and why.

**Response shape**
- `job_id`
- `shortages` (array of `MaterialShortageInfo`)
- `replenishment_suggestions` (currently mapped from `shortage_resolutions`)
- `resolution_options`
- `global_score`

---

### 2) Apply Replenishment (create expected arrivals)

```http
POST /api/v1/ai/scheduling/proposals/{proposal_id}/apply-replenishment
```

Creates `inventory_expected_arrivals` records, with deduplication checks.

**Request**
```json
{
  "suggestions": [
    {
      "material_id": "MAT-010",
      "quantity": 150,
      "arrive_at": "2026-04-15T08:00:00Z",
      "notes": "planner approved",
      "inventory_snapshot": {
        "material_id": "MAT-010",
        "version": "abc123...",
        "computed_at": "2026-04-10T14:10:00Z"
      }
    }
  ]
}
```

**Response**
```json
{
  "success": true,
  "data": {
    "created_arrivals": [/* ... */],
    "skipped_duplicates": 0
  }
}
```

**Important errors**
- `409 snapshot_conflict` — inventory changed since analysis; re-run shortage analysis.

---

### 3) Replenish + Replan (single action loop)

```http
POST /api/v1/ai/scheduling/jobs/{job_id}/replenish-and-replan
```

Creates arrivals and immediately regenerates proposal.

**Request**
```json
{
  "arrivals": [
    {
      "material_id": "MAT-010",
      "quantity": 150,
      "arrive_at": "2026-04-15T08:00:00Z",
      "inventory_snapshot": {
        "material_id": "MAT-010",
        "version": "abc123...",
        "computed_at": "2026-04-10T14:10:00Z"
      }
    }
  ],
  "attempt": 0,
  "previous_deficits": { "MAT-010": 200 },
  "previous_global_score": 350,
  "allow_partial": false
}
```

**Success response**
- Returns full `SchedulingProposal` (same shape as proposal endpoints), including shortage fields.

**Important errors**
- `422 lead_time_infeasible` — requested `arrive_at` is earlier than feasible.
- `409 snapshot_conflict` — optimistic concurrency conflict; re-run analysis.
- `409 convergence_failed` — deficit/global score did not improve; escalate to manual action.

---

## New Response Fields To Use In Frontend

These are now part of scheduling proposal payloads:

- `material_shortages[]`
  - `material_id`, `material_name`, `job_step_id`
  - `shortage_start_at`, `max_deficit`
  - `all_step_materials_feasible`
  - `feasible_qty`
  - `snapshot` (for optimistic concurrency)
  - `per_material_resolutions[]`

- `shortage_resolutions[]`
  - `material_id`
  - `option_type`: `replenish | schedule_production | delay_jobs | split_time_windows | prioritize_critical`
  - `priority`
  - `replenishment` (if relevant)
  - `earliest_feasible_start`

- `global_score`
  - Aggregate shortage score used for convergence.

- `partial_feasibility`
  - Partial runnable quantity and deferred quantity.

- `deferred_nodes[]`
  - Generated continuation nodes for deferred qty (for traceability / follow-up UI).

- `convergence_warnings[]`
  - Returned when replan convergence fails.

---

## Frontend Changes Required

### A) Add a shortage panel per proposal
- Render `material_shortages` grouped by `job_step_id`.
- Show badges:
  - `max_deficit`
  - `shortage_start_at`
  - `all_step_materials_feasible` (false => step blocked)
- Show `feasible_qty` and `partial_feasibility` when available.

### B) Render per-material resolution actions
- Group `shortage_resolutions` by `material_id`.
- Keep decisions independent per material.
- If `replenishment.is_lead_time_constrained = true`, default UI selection to delay option.
- For subproduct shortage, render `option_type=schedule_production` the same way as replenish cards (different CTA text).

### C) Add 1-click replenish flow
1. User chooses `replenish` option(s).
2. Send `POST /apply-replenishment` with selected items + `inventory_snapshot`.
3. On `409 snapshot_conflict`, show toast/modal: “Inventory changed, refresh analysis”.

### D) Add replenish-and-replan flow
1. Send `POST /replenish-and-replan`.
2. Handle:
   - `201` → refresh proposal view from returned payload.
   - `422` → adjust time to `earliest_possible_arrival` and retry.
   - `409 snapshot_conflict` → reload shortage analysis.
   - `409 convergence_failed` → stop loop and show manual intervention CTA.

### E) Track convergence state in UI
- Persist:
  - `attempt`
  - `previous_deficits`
  - `previous_global_score`
- Stop auto-loop at 3 attempts or first convergence conflict.

---

## Suggested UI Flow

1. Generate proposal as usual (`POST /ai/scheduling/jobs/{id}/proposals`).
2. If `material_shortages` not empty:
   - Show shortage drawer.
   - Allow material-by-material action selection.
3. On confirm:
   - either `apply-replenishment` only,
   - or `replenish-and-replan` for immediate feedback.
4. Re-render returned proposal.
5. Continue until:
   - no shortages, or
   - convergence/manual stop.

---

## Minimal Frontend Contract Notes

- Treat shortage fields as optional for backward compatibility.
- Always send snapshots when available (prevents stale writes).
- Do not assume one global resolution for a job; resolution is material-scoped.
- Do not auto-retry indefinitely; respect convergence and attempt caps.

---

## Troubleshooting: "Infeasible but no recommendation shown"

Use this checklist when summary shows `reason_code=material_shortage` but UI shows no recommendation cards.

1. Verify API payload first (Network tab), not UI state:
   - `proposals[].feasible == false`
   - `proposals[].blocked_reasons` contains `reason_code=material_shortage`
   - `proposals[].shortage_resolutions.length > 0` OR `proposals[].material_shortages.length > 0`

2. Frontend must render recommendations when **either** source is present:
   - Source A: `proposal.shortage_resolutions`
   - Source B: `proposal.material_shortages[].per_material_resolutions`

3. Recommended parsing fallback:
   - Primary list = `shortage_resolutions`
   - If empty, fallback = flatten all `material_shortages[].per_material_resolutions`

4. Do not gate recommendation panel only by `material_shortages.length`.
   - Some infeasible proposals are driven by dependent/subproduct blocks and still carry valid options in `shortage_resolutions`.

5. Expected outcome:
   - For any infeasible proposal with material shortage, UI shows at least one recommendation card (`replenish` or `schedule_production`).

