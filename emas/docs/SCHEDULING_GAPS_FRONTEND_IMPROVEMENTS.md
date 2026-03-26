# Scheduling Gaps – Frontend Improvements

Detailed document for frontend changes required to support and leverage the 15 scheduling-gap features. Use with [`SCHEDULING_GAPS_API_CHANGELOG.md`](SCHEDULING_GAPS_API_CHANGELOG.md) and [`FRONTEND_SCHEDULING_API.md`](../FRONTEND_SCHEDULING_API.md).

---

## 1. Event-Based Rescheduling (Gap 11)

### New endpoint: Emit Scheduling Event

**POST** `/api/v1/scheduling/events`

| Field     | Type   | Required | Description |
|-----------|--------|----------|-------------|
| `type`    | string | Yes      | `machine_down`, `job_delay`, `urgent_insert` |
| `payload` | string | No       | JSON string with event-specific data |

### Frontend improvements

| Area | Action | Priority |
|------|--------|----------|
| **Machine down form** | Add a form/dialog to report machine down. Fields: machine selector, down-until datetime. Call `POST /scheduling/events` with `type: "machine_down"` and payload `{"machine_id":"M-CNC-01","down_until":"2026-03-22T18:00:00Z"}`. | High |
| **Job delay form** | Add a form to report job delay (e.g. from MES). Payload example: `{"job_id":"JOB-001","delay_hours":4}`. | Medium |
| **Urgent insert** | Add a button/flow for "urgent insert" that emits `type: "urgent_insert"` and optionally triggers reschedule. | Medium |
| **Reschedule after event** | If `AI_AUTO_RESCHEDULE_ON_EVENT` is disabled, show a toast/banner after emitting an event: "Schedule may be outdated. Click to reschedule." with action to `POST /ai/scheduling/reschedule-all`. | High |
| **Event history** | Optional: list emitted events (if backend exposes `GET /scheduling/events` in future) for audit. | Low |

---

## 2. Validate Slot – Structured Reasons (Gap 14)

### Updated response shape

`POST /api/v1/scheduling/slots/validate` now returns:

- `validation_reasons`: `{ message, type, penalty }[]`
- `hard_reasons`: string[] – blocking issues
- `soft_reasons`: string[] – non-blocking issues
- `total_penalty`: number – for tie-breaking

### Frontend improvements

| Area | Action | Priority |
|------|--------|----------|
| **Validation result display** | Show `hard_reasons` as error list (red). Show `soft_reasons` as warning list (amber). | High |
| **Machine picker** | When user drags a slot to a new machine, validate. If invalid, show `hard_reasons` and block. If multiple candidates, rank by `total_penalty` (lower = better). | High |
| **Candidate ranking** | When suggesting alternative machines, use `total_penalty` to sort: "Machine A (penalty 0), Machine B (penalty 10)". | Medium |
| **Backward compat** | Keep using `reasons` (flat list) for simple tooltips; upgrade to `hard_reasons`/`soft_reasons` for richer UI. | Medium |

### Example UI text

- Hard: "Slot overlaps machine downtime"
- Soft: "Machine blocked by tentative slots from other jobs in batch (penalty: 10)"

---

## 3. Slot Model Extensions (Gap 12)

### New slot fields

| Field          | Type    | Description |
|----------------|---------|-------------|
| `actual_start` | string? | RFC3339. Actual start when production began. |
| `actual_end`   | string? | RFC3339. Actual end when slot completed. |

### New slot status

| Status    | Description |
|-----------|-------------|
| `paused`  | Temporarily paused; still blocks the machine. |

### Frontend improvements

| Area | Action | Priority |
|------|--------|----------|
| **Gantt / slot card** | Show `actual_start` / `actual_end` when present (e.g. "Started: 09:15", "Finished: 10:42"). Use different styling for planned vs actual times. | High |
| **Slot status badge** | Add `paused` to status options. Use distinct color (e.g. orange) and label "Paused". | High |
| **Production log form** | When operator starts a slot: call `PUT /slots/:id` with `status: "running"` and `actual_start`. When completes: `status: "completed"`, `actual_end`. | High |
| **Pause/Resume** | Add "Pause" button for running slots → `PUT /slots/:id` with `status: "paused"`. "Resume" → `status: "running"`. | Medium |
| **Slot detail panel** | Show planned vs actual in a side panel: "Planned: 08:00–10:00 | Actual: 08:15–10:30". | Medium |

### Backend note

If `UpdateSlotRequest` does not yet accept `actual_start`, `actual_end`, or `status`, these should be added to the backend DTO. Check `PUT /slots/:id` payload.

---

## 4. Batch Proposal – Material & Readiness

### Existing fields (use more prominently)

- `order_by: "readiness"` – schedules jobs ready now first.
- Readiness: `can_start_now`, `earliest_ready_at`.
- Delay risk: `MaterialShortageCount`, `SubProductShortageCount` (from `GET /ai/scheduling/jobs/:id/delay-risk`).

### Frontend improvements

| Area | Action | Priority |
|------|--------|----------|
| **Order-by selector** | Add dropdown for batch-proposals and reschedule-all: "Order by: EPO | EDD | FIFO | Readiness". Default EPO; "Readiness" schedules ready-now jobs first. | High |
| **Readiness badge** | On job list and proposal cards: show "Ready now" or "Ready in X hours" using `earliest_ready_at`. | High |
| **Material shortage** | From delay-risk or readiness: show "X materials short, Y sub-products short" with link to material/inventory views. | High |
| **Blocked summary** | In batch `summary`, use `blocked` and `skipped` to show counts. Display message: "2 jobs blocked (material shortage), 1 skipped." | Medium |

### API usage

- `GET /scheduling/products/:id/readiness?quantity=N` – returns `can_start_now`, `earliest_ready_at`, `materials`, `sub_products` with `shortage_qty`.
- `GET /ai/scheduling/jobs/:id/delay-risk` – returns `material_shortage_count`, `sub_product_shortage_count` in heuristic fallback.

---

## 5. Settings / Feature Flags

### Env vars (expose via settings API if available)

| Variable                      | Values | Description |
|-------------------------------|--------|-------------|
| `AI_SPLIT_STRATEGY`           | `equal`, `min_time`, `priority` | Split strategy for parallel steps. |
| `AI_OBJECTIVE`                | `minimize_tardiness`, `minimize_makespan`, `maximize_utilization` | Optimization goal. |
| `AI_AUTO_RESCHEDULE_ON_EVENT` | `true` / `false` | Auto-reschedule when events are emitted. |

### Frontend improvements

| Area | Action | Priority |
|------|--------|----------|
| **Settings page** | Add "Scheduling" section: Split strategy dropdown, Objective dropdown, "Auto-reschedule on events" toggle. Persist via `PUT /scheduling/settings` if supported. | Medium |
| **Defaults** | If settings API does not support these, document that they are env-based and require backend config. | Low |

---

## 6. Solver Preview & Constraints

### Existing endpoints

- `GET /scheduling/jobs/:id/solver-preview` – returns `can_start_now`, `earliest_ready_at`, `steps` with `candidate_machines`, `min_wait_minutes`, `transfer_minutes`.
- Constraints list includes: `material_and_sub_product_readiness`, `step_precedence`, `machine_capability`, etc.

### Frontend improvements (Gaps 3, 4, 5, 6, 13)

| Area | Action | Priority |
|------|--------|----------|
| **Step dependencies** | Display step order reflecting DAG (Gap 13). Show predecessors on step cards: "Depends on: Step 1, Step 2". | Medium |
| **Transfer / wait time** | Show `min_wait_minutes` and `transfer_minutes` between steps (e.g. "15 min cooling + 10 min transfer"). | Low |
| **Batch steps** | For batch steps, show "Batch size: 100" and "Min batch: 50" if available in step metadata. | Low |
| **Resource requirements** | If step requires operator/fixture (Gap 6), show badge "Requires: Operator A". | Low |
| **Setup time** | When switching products on a machine, setup rules apply. Show in tooltip: "30 min setup when switching from P-001 to P-002." | Low |

---

## 7. Gantt & Schedule View Enhancements

### Frontend improvements

| Area | Action | Priority |
|------|--------|----------|
| **Slot colors by status** | Color-code: `planned` (blue), `running` (green), `completed` (gray), `cancelled` (red), `paused` (orange). | High |
| **Actual vs planned** | For running/completed slots, overlay actual bar (solid) on planned bar (dashed) to show variance. | Medium |
| **Readiness timeline** | Optional: show `earliest_ready_at` as a marker on the timeline for jobs not yet ready. | Low |
| **Machine setup** | When two slots on same machine have different products, show setup segment between them (if API exposes it). | Low |

---

## 8. Summary Checklist

| Gap | Frontend improvement | Status |
|-----|----------------------|--------|
| 1–2 | WIP / material per step – readiness & shortage display | Use existing readiness/shortage APIs |
| 3 | Time offset – show transfer/wait between steps | Solver preview, step cards |
| 4 | Batch – show batch size on steps | Step metadata if exposed |
| 5 | Setup rules – setup time tooltip | When product switch on machine |
| 6 | Resources – show "Requires: Operator" on steps | Step metadata if exposed |
| 7 | Formula lead time – reflected in readiness | No direct UI change |
| 8 | Alternative routing – backend only for now | N/A |
| 9–10 | Split/Objective – settings page | Dropdowns if settings API supports |
| 11 | Event-based rescheduling | **Machine down form, reschedule prompt** |
| 12 | Slot model (actual, paused) | **Actual times, paused status, production log** |
| 13 | DAG – step order | Show dependencies on step cards |
| 14 | Constraint priority | **Hard/soft reasons in validation UI** |
| 15 | Versioning – backend only | N/A |

---

## 9. Recommended Implementation Order

1. **High priority**
   - Validate slot: hard/soft reasons display
   - Slot status `paused` and actual times in Gantt
   - Production log: start/complete with `actual_start` / `actual_end` / `status`
   - Order-by selector including "Readiness"
   - Machine down form + `POST /scheduling/events`
   - Reschedule prompt after events (when auto-reschedule off)

2. **Medium priority**
   - Readiness badge on jobs
   - Material shortage display from delay-risk
   - Pause/Resume for slots
   - Settings: split strategy, objective (if API supports)
   - Step dependencies in solver preview / job detail

3. **Low priority**
   - Transfer/wait time between steps
   - Batch size on steps
   - Resource requirements badge
   - Setup time tooltip

---

## 10. API Quick Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/scheduling/events` | POST | Emit machine_down, job_delay, urgent_insert |
| `/scheduling/slots/validate` | POST | Validate slot; use `hard_reasons`, `soft_reasons`, `total_penalty` |
| `/slots/:id` | GET | Slot includes `actual_start`, `actual_end` |
| `/slots/:id` | PUT | Extend to accept `actual_start`, `actual_end`, `status` |
| `/scheduling/products/:id/readiness` | GET | `can_start_now`, `earliest_ready_at`, materials, sub_products |
| `/ai/scheduling/jobs/:id/delay-risk` | GET | `material_shortage_count`, `sub_product_shortage_count` |
| `/ai/scheduling/batch-proposals` | POST | `order_by: "readiness"` supported |
| `/ai/scheduling/reschedule-all` | POST | Same `order_by` options |

---

## 11. Example: Validation Error Component

```tsx
interface ValidationResult {
  valid: boolean;
  hard_reasons?: string[];
  soft_reasons?: string[];
  total_penalty?: number;
}

function ValidationErrors({ data }: { data: ValidationResult }) {
  return (
    <div>
      {data.hard_reasons?.length ? (
        <Alert severity="error">
          {data.hard_reasons.map((r, i) => <div key={i}>{r}</div>)}
        </Alert>
      ) : null}
      {data.soft_reasons?.length ? (
        <Alert severity="warning">
          {data.soft_reasons.map((r, i) => (
            <div key={i}>{r} {data.total_penalty ? `(penalty: ${data.total_penalty})` : ''}</div>
          ))}
        </Alert>
      ) : null}
    </div>
  );
}
```

---

## 12. Example: Emit Event Component

```tsx
async function reportMachineDown(machineId: string, downUntil: string) {
  const payload = JSON.stringify({ machine_id: machineId, down_until: downUntil });
  await fetch(`${BASE}/scheduling/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-User-Role': 'planner' },
    body: JSON.stringify({ type: 'machine_down', payload }),
  });
  // If AI_AUTO_RESCHEDULE_ON_EVENT is false, show toast: "Reschedule recommended"
}
```
