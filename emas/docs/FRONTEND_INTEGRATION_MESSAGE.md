# Frontend Integration Message — Backend Interface Alignment Complete

**Date:** 2026-03-19  
**Status:** All backend gaps from `BACKEND_INTERFACE_ALIGNMENT.md` are implemented.

---

## Summary for Frontend Team

The backend has been updated to support the interface design (`INTERFACE_DESIGN.md`). Below is what you need to integrate.

---

## 1. Materials per Step (JobDetailsPanel, Process Routing, Scheduling Preview)

**→ Full API spec:** [`API_PROCESS_STEP_MATERIALS.md`](./API_PROCESS_STEP_MATERIALS.md)

**Endpoints:** `GET`, `POST`, `DELETE` `/api/v1/process-steps/:step_id/materials`

### GET — List materials
- **Use for:** "Show materials (N)" in JobDetailsPanel; "Materials" in Process Routing (BOM modal).
- **Query:** `?role=input` (default), `output`, or `all` — use `all` for Process Routing edit to show inputs + outputs.
- **Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": "PSM-P001-1-MAT001",
      "material_id": "MAT-001",
      "product_id": "",
      "role": "input",
      "quantity_per_unit": 2.5,
      "unit": "kg",
      "material_name": "Steel Sheet"
    }
  ]
}
```
- **Display:** e.g. `"MAT-001 (2.5 kg), P-007 (1 ea)"` — use `material_id` or `product_id`, `quantity_per_unit`, `unit`.

### POST — Add material to step
- **Use for:** Process Routing — "Add material" per step.
- **Body:**
```json
{
  "material_id": "MAT-001",
  "product_id": "",
  "role": "input",
  "quantity_per_unit": 2.5,
  "unit": "kg"
}
```
- Exactly one of `material_id` or `product_id` required. `role`: `"input"` or `"output"`.

### DELETE — Remove material from step
- **Path:** `/api/v1/process-steps/:step_id/materials/:id`
- **id:** The `id` from the GET response (e.g. `PSM-P001-1-MAT001`).

---

## 2. Slot Start / Pause / Resume / Complete

**Endpoint:** `PUT /api/v1/slots/:id` or `PATCH /api/v1/slots/:id`

**Request body (partial updates supported):**

| Action | Send |
|--------|------|
| Start | `{ "status": "running" }` — backend sets `actual_start` if not provided |
| Pause | `{ "status": "paused" }` |
| Resume | `{ "status": "running" }` |
| Complete | `{ "status": "completed" }` — backend sets `actual_end` if not provided |

Optional: `actual_start`, `actual_end` (ISO8601) to override defaults.

**Response:** Slot object with `actual_start`, `actual_end`, `status`.

---

## 3. Slot Data — Actual Times

**Slots now include (if present):**

- `actual_start` — when production started
- `actual_end` — when production finished

Use in slot cards and Gantt to show actual vs planned.

---

## 4. Record Downtime → Auto-Reschedule

**Endpoint:** `POST /api/v1/machines/downtime`

**Body:** `machine_id`, `cause`, `start_time`, `end_time` (ISO8601).

**Behavior:** Records downtime and, when `AI_EMIT_EVENT_ON_DOWNTIME=true` (default), emits a `machine_down` scheduling event. If `AI_AUTO_RESCHEDULE_ON_EVENT=true`, a reschedule runs automatically.

No need to call `POST /scheduling/events` separately for downtime.

---

## 5. Report Delay & Urgent Insert — Payload Format

**Endpoint:** `POST /api/v1/scheduling/events`

**Request:**
```json
{
  "type": "job_delay",
  "payload": "{\"job_id\":\"JOB-001\",\"delay_minutes\":60,\"reason\":\"Material late\"}"
}
```

**Important:** `payload` must be a JSON **string** (use `JSON.stringify` on the object).

**Payload formats by type:**

| type | Required | Optional | Example |
|------|----------|----------|---------|
| `machine_down` | `machine_id`, `start_time`, `end_time` | — | `{"machine_id":"M-001","start_time":"...","end_time":"..."}` |
| `job_delay` | `job_id`, `delay_minutes` | `reason` | `{"job_id":"JOB-001","delay_minutes":60,"reason":"..."}` |
| `urgent_insert` | `job_id` | `priority` ("high"\|"critical"), `reason` | `{"job_id":"JOB-001","priority":"critical","reason":"..."}` |

Invalid payloads return `400` with an error message.

---

## 6. Scheduling Settings (Settings Page)

**Full spec:** [`SCHEDULING_SETTINGS_FRONTEND.md`](./SCHEDULING_SETTINGS_FRONTEND.md) — single doc for all Scheduling UI (work times, workdays, public holidays, refresh).

**Endpoints:** `GET /api/v1/scheduling/settings`, `PUT /api/v1/scheduling/settings`, `POST /api/v1/scheduling/refresh-work-calendars`

**GET response:** Includes `work_start_time`, `work_end_time`, `work_days`, `public_holidays`. See SCHEDULING_SETTINGS_FRONTEND.md for full schema.

**Allowed values:** See SCHEDULING_SETTINGS_FRONTEND.md for validation and field reference.

---

## 7. Log Production — Downtime Minutes

**Endpoint:** `POST /api/v1/production-logs`

**Body:** add optional `downtime_minutes`:

```json
{
  "slot_id": "SLT-xxx",
  "start_time": "...",
  "end_time": "...",
  "quantity_produced": 100,
  "quantity_scrap": 2,
  "operator_notes": "...",
  "downtime_minutes": 15
}
```

---

## 8. Apply Proposal — Work Calendar Errors

**Context:** When the user clicks **Apply All → Write to job plan**, the frontend calls `applyProposal` (or `POST /api/v1/jobs/:id/proposals/:proposal_id/apply`) for each proposal. The backend validates that each slot’s start/end times fall within the machine’s and resource’s work calendars.

### Backend Fix (2026-03-19)

The proposal generator now respects **resource work calendars** when placing slots. If a step requires operators/resources (e.g. Assembly) with work calendars (e.g. 08:00–17:00 weekdays), the AI will only propose slots inside those windows. This should prevent most “slot is outside resource work calendar” errors for new proposals.

### If the Error Still Occurs

The backend returns an error such as:

- `slot is outside resource work calendar (ensure slot times fall within resource work hours, e.g. 08:00-17:00 weekdays)`
- `slot is outside machine work calendar (ensure slot times fall within machine shift hours)`

### Frontend Display

1. **Show the backend message** — Use `toast.error(apiErrorMessage(err, ...))` or equivalent to surface the backend message to the user.
2. **User guidance** — If desired, append a short hint: *"Check resource/machine calendar setup or regenerate proposals."*

### Root Causes & Fixes

| Cause | Fix |
|-------|-----|
| Proposal generated before backend fix | Regenerate proposals (they will now respect work calendars). |
| Resource calendar (e.g. operator) defines 08:00–17:00 weekdays | Ensure slot times fall within those windows, or extend resource calendar. |
| Machine calendar defines shift hours | Ensure slot times fall within machine shifts. |
| Seed data uses 08:00–17:00 weekdays | Default resource calendars; proposals should now align automatically. |

### Integration Summary

- **Backend:** Validates slot times vs. work calendars; returns clear error message.
- **Frontend:** Show error via toast; optionally suggest “Regenerate proposals” or “Check calendar setup”.

---

## General App Settings (theme, language, notifications, ai_enabled)

**→ Full API spec:** [`SETTINGS_FRONTEND.md`](./SETTINGS_FRONTEND.md)

**Endpoints:** `GET /api/v1/settings`, `PUT /api/v1/settings`

- **PUT payload:** Only `theme`, `language`, `notifications` (boolean), `ai_enabled` (boolean). Omit `timezone`, `simulation_mode`, `auto_save_interval`, `data_retention_days`, `erp_integration`.

---

## Route Reference

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/settings` | Get app settings (theme, language, notifications, ai_enabled) |
| PUT | `/api/v1/settings` | Update app settings |
| GET | `/api/v1/scheduling/settings` | Get scheduling settings |
| PUT | `/api/v1/scheduling/settings` | Update scheduling settings |
| POST | `/api/v1/scheduling/refresh-work-calendars` | Apply work template to resource/machine calendars |
| GET | `/api/v1/process-steps/:step_id/materials` | Materials per process step |
| PUT/PATCH | `/api/v1/slots/:id` | Update slot (incl. `status`, `actual_start`, `actual_end`) |
| POST | `/api/v1/machines/downtime` | Record downtime (may auto-emit `machine_down`) |
| POST | `/api/v1/scheduling/events` | Emit event (validate payload per type) |
| GET | `/api/v1/scheduling/settings` | Get scheduling settings |
| PUT | `/api/v1/scheduling/settings` | Update scheduling settings |
| POST | `/api/v1/production-logs` | Log production (incl. `downtime_minutes`) |

---

## Checklist for Frontend

- [ ] Call `GET /process-steps/:step_id/materials?role=all` for Process Routing "Materials" per step
- [ ] Call `GET /process-steps/:step_id/materials` for "Show materials (N)" expandable
- [ ] Use POST/DELETE to add/remove materials when editing Process Routing
- [ ] Slot cards: Start / Pause / Resume / Complete via `PUT /slots/:id` with `status`
- [ ] Display `actual_start`, `actual_end` on slots when present
- [ ] Record Downtime: use `POST /machines/downtime` only (no separate event call)
- [ ] Report Delay: `POST /scheduling/events` with `type: "job_delay"`, `payload` as JSON string
- [ ] Urgent Insert: `POST /scheduling/events` with `type: "urgent_insert"`, `payload` as JSON string
- [ ] Settings page: show/edit scheduling settings (lock-in window, split strategy, objective, auto-reschedule, work times, workdays, public holidays) via GET/PUT scheduling settings; add "Refresh work calendars" button calling POST /scheduling/refresh-work-calendars
- [ ] Log Production modal: include optional `downtime_minutes` field
- [ ] **AI Chat:** See [AI_CHAT_FRONTEND_NEEDS.md](./AI_CHAT_FRONTEND_NEEDS.md) — suggested_calls, auto-execute GET, Approve for POST/PUT/DELETE
- [ ] **Scheduling Apply-All:** Follow [SCHEDULING_APPLY_ALL_INTEGRATION_CONTRACT.md](./SCHEDULING_APPLY_ALL_INTEGRATION_CONTRACT.md) as the single source (approve/apply request body, stale handling, overlap verification scope, stop-on-first-hard-error)
